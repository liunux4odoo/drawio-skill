"""Tests for skill-hub: install/maintain skill registry.

Strategy: monkeypatch `download` so tests run offline against a locally built
tarball. Exercises every subcommand (add / update / install / uninstall /
list / status), the link vs copy modes, and the error paths.
"""
import io
import json
import os
import shutil
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "skill-hub" / "scripts" / "skill_hub.py"


# ---------- fixtures: a fake skill archive built once per session ----------


def _make_tarball(dest: Path, name: str, marker_text: str = "v1") -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    archive = dest / name
    with tarfile.open(archive, "w:gz") as t:
        data = marker_text.encode("utf-8")
        info = tarfile.TarInfo(name="SKILL.md")
        info.size = len(data)
        t.addfile(info, io.BytesIO(data))
    return archive


def _make_zip(dest: Path, name: str, marker_text: str = "v1") -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    archive = dest / name
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("SKILL.md", marker_text)
    return archive


# ---------- per-test isolation: isolated HOME ----------


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    """Redirect registry and store into a tmp dir; reset module-level paths."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.delenv("SKILL_HUB_HOME", raising=False)
    monkeypatch.delenv("SKILL_HUB_DATA", raising=False)

    # Reset module caches that captured paths
    import importlib
    sys.modules.pop("skill_hub", None)
    spec = importlib.util.spec_from_file_location("skill_hub", SCRIPT)  # type: ignore[attr-defined]
    mod = importlib.util.module_from_spec(spec)  # type: ignore[attr-defined]
    sys.modules["skill_hub"] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return tmp_path, mod


@pytest.fixture
def patch_download(isolated_home, request):
    """Replace skill_hub.download with a local file copy.

    Default mode: first download per URL returns v1, subsequent returns v2
    (simulates a CI tarball that was updated between calls).

    Also mocks head_metadata: by default returns no ETag/Last-Modified (forces
    GET+sha path). Tests that want the HEAD fast path can parametrize
    `"with_etag"`. Parametrizing `"stable"` keeps downloads at v1.
    """
    tmp_path, mod = isolated_home
    archive_v1 = _make_tarball(tmp_path / "archives", "sample-skill-v1.tar.gz", "v1")
    archive_v2 = _make_tarball(tmp_path / "archives", "sample-skill-v2.tar.gz", "v2")
    archive_zip = _make_zip(tmp_path / "archives", "sample-skill-v1.zip", "v1-zip")

    param = getattr(request, "param", None)
    stable = param == "stable"
    with_etag = param == "with_etag"

    calls: list[str] = []
    seen: set[str] = set()

    def fake_download(url: str, dest: Path) -> dict[str, str]:
        calls.append(url)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if url.endswith(".zip"):
            shutil.copy2(archive_zip, dest)
            return {}
        if stable:
            shutil.copy2(archive_v1, dest)
            return {}
        first_time = url not in seen
        seen.add(url)
        if first_time:
            shutil.copy2(archive_v1, dest)
        else:
            shutil.copy2(archive_v2, dest)
        return {}  # no ETag/Last-Modified from fake server

    def fake_head(url: str) -> dict[str, str]:
        # with_etag mode: return a stable ETag for any tar.gz URL. The HEAD
        # fast path checks against the registry's stored etag; the tests that
        # want a cache hit write the matching etag into the registry first.
        if with_etag and url.endswith(".tar.gz"):
            return {"etag": 'W/"stable-v1-etag"', "last-modified": "Mon, 01 Jan 2026 00:00:00 GMT"}
        return {}

    mod.download_with_headers = fake_download  # type: ignore[assignment]
    mod.head_metadata = fake_head  # type: ignore[assignment]
    return tmp_path, mod, calls, {
        "v1": "https://example.test/sample-skill-v1.tar.gz",
        "v2": "https://example.test/sample-skill-v2.tar.gz",
        "zip": "https://example.test/sample-skill-v1.zip",
    }


def run(mod, *args):
    return mod.main(list(args))


# ---------- tests ----------


def test_help_exits_cleanly(isolated_home):
    tmp_path, mod = isolated_home
    # main() with -h calls sys.exit(0); capture via SystemExit
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        with pytest.raises(SystemExit) as exc:
            mod.main(["-h"])
    assert exc.value.code == 0


def test_add_registers_and_extracts(patch_download):
    tmp_path, mod, calls, urls = patch_download
    rc = run(mod, "add", "demo", urls["v1"])
    assert rc == 0
    assert calls == [urls["v1"]]
    store = mod.store_dir() / "demo"
    assert (store / "SKILL.md").read_text(encoding="utf-8") == "v1"
    reg = json.loads(mod.registry_path().read_text())
    assert "demo" in reg["skills"]
    assert reg["skills"]["demo"]["url"] == urls["v1"]
    assert len(reg["skills"]["demo"]["version"]) == 64  # sha256 hex


def test_add_duplicate_rejected(patch_download):
    tmp_path, mod, calls, urls = patch_download
    run(mod, "add", "demo", urls["v1"])
    rc = run(mod, "add", "demo", urls["v1"])
    assert rc == 1


def test_add_rejects_non_http_url(patch_download):
    tmp_path, mod, calls, urls = patch_download
    rc = run(mod, "add", "demo", "ftp://example.test/x.tar.gz")
    assert rc == 1


def test_add_rejects_bad_name(patch_download):
    tmp_path, mod, calls, urls = patch_download
    for bad in ("", "../escape", "with space", "a/b"):
        rc = run(mod, "add", bad, urls["v1"])
        assert rc == 1, f"should reject name={bad!r}"


def test_install_link_default(patch_download):
    tmp_path, mod, calls, urls = patch_download
    run(mod, "add", "demo", urls["v1"])
    target = tmp_path / "installs" / "demo"
    rc = run(mod, "install", "demo", str(target))
    assert rc == 0
    assert target.is_symlink()
    assert target.resolve() == (mod.store_dir() / "demo").resolve()
    assert (target / "SKILL.md").read_text(encoding="utf-8") == "v1"


def test_install_copy_mode(patch_download):
    tmp_path, mod, calls, urls = patch_download
    run(mod, "add", "demo", urls["v1"])
    target = tmp_path / "installs-copy" / "demo"
    rc = run(mod, "install", "demo", str(target), "--copy")
    assert rc == 0
    assert not target.is_symlink()
    assert target.is_dir()
    assert (target / "SKILL.md").read_text(encoding="utf-8") == "v1"


def test_install_unknown_skill_rejected(patch_download):
    tmp_path, mod, calls, urls = patch_download
    rc = run(mod, "install", "ghost", "/tmp/never")
    assert rc == 1


def test_install_rejects_unrelated_existing_file(patch_download):
    tmp_path, mod, calls, urls = patch_download
    run(mod, "add", "demo", urls["v1"])
    blocker = tmp_path / "installs" / "demo"
    blocker.parent.mkdir(parents=True, exist_ok=True)
    blocker.write_text("not a directory")
    rc = run(mod, "install", "demo", str(blocker))
    assert rc == 1
    assert blocker.read_text() == "not a directory"  # untouched


def test_update_refreshes_link(patch_download):
    tmp_path, mod, calls, urls = patch_download
    run(mod, "add", "demo", urls["v1"])
    target = tmp_path / "installs" / "demo"
    run(mod, "install", "demo", str(target))
    rc = run(mod, "update", "demo")
    assert rc == 0
    # Store now has v2; link still points at it
    assert (mod.store_dir() / "demo" / "SKILL.md").read_text(encoding="utf-8") == "v2"
    assert target.is_symlink()
    assert (target / "SKILL.md").read_text(encoding="utf-8") == "v2"


def test_update_refreshes_copy(patch_download):
    tmp_path, mod, calls, urls = patch_download
    run(mod, "add", "demo", urls["v1"])
    target = tmp_path / "installs" / "demo"
    run(mod, "install", "demo", str(target), "--copy")
    rc = run(mod, "update", "demo")
    assert rc == 0
    assert (target / "SKILL.md").read_text(encoding="utf-8") == "v2"


def test_update_no_change_reports_up_to_date(patch_download, capsys):
    tmp_path, mod, calls, urls = patch_download
    run(mod, "add", "demo", urls["v1"])
    calls.clear()
    rc = run(mod, "update", "demo")
    assert rc == 0
    out = capsys.readouterr().out
    assert "up-to-date" in out
    assert calls == [urls["v1"]]  # one fetch, no extract


test_update_no_change_reports_up_to_date = pytest.mark.parametrize(
    "patch_download", ["stable"], indirect=True
)(test_update_no_change_reports_up_to_date)


def test_status_shows_up_to_date(patch_download, capsys):
    tmp_path, mod, calls, urls = patch_download
    run(mod, "add", "demo", urls["v1"])
    rc = run(mod, "status", "demo")
    assert rc == 0
    out = capsys.readouterr().out
    assert "up-to-date" in out


test_status_shows_up_to_date = pytest.mark.parametrize(
    "patch_download", ["stable"], indirect=True
)(test_status_shows_up_to_date)


def test_status_needs_update(patch_download, capsys):
    """First download returns v1, second returns v2: add then status sees the change."""
    tmp_path, mod, calls, urls = patch_download
    run(mod, "add", "demo", urls["v1"])  # serves v1
    rc = run(mod, "status", "demo")  # second fetch serves v2
    assert rc == 0
    out = capsys.readouterr().out
    assert "NEEDS UPDATE" in out


def test_update_all_skills(patch_download):
    tmp_path, mod, calls, urls = patch_download
    run(mod, "add", "a", urls["v1"])
    run(mod, "add", "b", urls["v2"])
    calls.clear()
    rc = run(mod, "update")
    assert rc == 0
    assert sorted(calls) == sorted([urls["v1"], urls["v2"]])


def test_uninstall_removes_link(patch_download):
    tmp_path, mod, calls, urls = patch_download
    run(mod, "add", "demo", urls["v1"])
    target = tmp_path / "installs" / "demo"
    run(mod, "install", "demo", str(target))
    rc = run(mod, "uninstall", "demo", str(target))
    assert rc == 0
    assert not target.exists()
    # Store stays
    assert (mod.store_dir() / "demo" / "SKILL.md").exists()


def test_uninstall_removes_copy(patch_download):
    tmp_path, mod, calls, urls = patch_download
    run(mod, "add", "demo", urls["v1"])
    target = tmp_path / "installs" / "demo"
    run(mod, "install", "demo", str(target), "--copy")
    rc = run(mod, "uninstall", "demo", str(target))
    assert rc == 0
    assert not target.exists()


def test_list_shows_empty_when_no_skills(patch_download, capsys):
    tmp_path, mod, calls, urls = patch_download
    rc = run(mod, "list")
    assert rc == 0
    out = capsys.readouterr().out
    assert "(no skills registered)" in out


def test_list_shows_skills_and_installs(patch_download, capsys):
    tmp_path, mod, calls, urls = patch_download
    run(mod, "add", "demo", urls["v1"])
    run(mod, "install", "demo", str(tmp_path / "x"), "--copy")
    rc = run(mod, "list")
    assert rc == 0
    out = capsys.readouterr().out
    assert "demo" in out
    assert urls["v1"] in out
    assert "copy" in out


def test_status_unknown_skill_rejected(patch_download):
    tmp_path, mod, calls, urls = patch_download
    rc = run(mod, "status", "ghost")
    assert rc == 1


def test_zip_archive_supported(patch_download):
    tmp_path, mod, calls, urls = patch_download
    rc = run(mod, "add", "ziptool", urls["zip"])
    assert rc == 0
    assert (mod.store_dir() / "ziptool" / "SKILL.md").read_text(encoding="utf-8") == "v1-zip"


# ---------- 4.1: bundle mode (skills/<child>/SKILL.md) ----------


def _make_bundle(tmp_path: Path, name: str, child_names: list[str], marker: str = "v1") -> Path:
    """Build a tarball whose top-level layout is skills/<child>/SKILL.md."""
    src_root = tmp_path / "bundle-src" / name.replace(".tar.gz", "")
    src_root.mkdir(parents=True, exist_ok=True)
    archive = tmp_path / "archives" / name
    archive.parent.mkdir(parents=True, exist_ok=True)
    for child in child_names:
        child_dir = src_root / "skills" / child
        child_dir.mkdir(parents=True, exist_ok=True)
        (child_dir / "SKILL.md").write_text(
            f"---\nname: {child}\ndescription: {child} skill\n---\n\n# {child} body ({marker})\n",
            encoding="utf-8",
        )
    with tarfile.open(archive, "w:gz") as t:
        t.add(src_root, arcname=".")
    return archive


def test_add_bundle_registers_all_children(patch_download, tmp_path):
    """4.1: URL whose extracted layout is skills/<child>/SKILL.md -> register all."""
    _, mod, calls, _ = patch_download
    archive = _make_bundle(tmp_path, "bundle-v1.tar.gz", ["alpha", "beta"])
    bundle_url = "https://example.test/bundle-v1.tar.gz"

    # monkey-patch download to serve our bundle
    def serve(url: str, dest: Path) -> dict[str, str]:
        calls.append(url)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(archive, dest)
        return {}
    mod.download_with_headers = serve  # type: ignore[assignment]

    rc = run(mod, "add", bundle_url)
    assert rc == 0
    reg = json.loads(mod.registry_path().read_text())
    assert set(reg["skills"].keys()) == {"alpha", "beta"}
    assert reg["skills"]["alpha"]["source_bundle"] == bundle_url
    assert reg["skills"]["beta"]["source_bundle"] == bundle_url
    assert "alpha body" in (mod.store_dir() / "alpha" / "SKILL.md").read_text(encoding="utf-8")
    assert "beta body" in (mod.store_dir() / "beta" / "SKILL.md").read_text(encoding="utf-8")
    # bundles map is populated
    assert bundle_url in reg["bundles"]
    assert sorted(reg["bundles"][bundle_url]["skills"]) == ["alpha", "beta"]


def test_add_bundle_rejects_explicit_name(patch_download, tmp_path, capsys):
    """Bundle + name is a user error: tell them to omit the name."""
    _, mod, calls, _ = patch_download
    archive = _make_bundle(tmp_path, "bundle-v1.tar.gz", ["alpha"])
    mod.download_with_headers = lambda url, dest: (calls.append(url), shutil.copy2(archive, dest), {})[-1]  # type: ignore[assignment]
    rc = run(mod, "add", "name-ignored", "https://example.test/bundle-v1.tar.gz")
    assert rc == 1
    err = capsys.readouterr().err
    assert "bundle" in err
    # No registry was written (the command errored before save_registry)
    assert not mod.registry_path().exists()


def test_add_bundle_collides_with_existing_rejected(patch_download, tmp_path):
    """4.1+4.3: bundle mode hits an already-registered name -> error, no overwrite."""
    _, mod, calls, urls = patch_download
    # First add a single-skill with name "alpha"
    run(mod, "add", "alpha", urls["v1"])
    # Now try a bundle that also contains "alpha"
    archive = _make_bundle(tmp_path, "bundle-v1.tar.gz", ["alpha", "gamma"])
    mod.download_with_headers = lambda url, dest: (calls.append(url), shutil.copy2(archive, dest), {})[-1]  # type: ignore[assignment]
    rc = run(mod, "add", "https://example.test/bundle-v1.tar.gz")
    assert rc == 1
    # Original "alpha" is intact, "gamma" is not registered
    reg = json.loads(mod.registry_path().read_text())
    assert reg["skills"]["alpha"]["url"] == urls["v1"]  # not overwritten
    assert "gamma" not in reg["skills"]


# ---------- 4.2: name inference ----------


def _make_single_skill_tarball(tmp_path: Path, archive_name: str, fm_name: str, body: str = "hi") -> Path:
    """Build a tarball containing one top-level dir with SKILL.md (frontmatter name: X)."""
    src = tmp_path / "src" / archive_name.replace(".tar.gz", "")
    src.mkdir(parents=True, exist_ok=True)
    (src / "SKILL.md").write_text(
        f"---\nname: {fm_name}\ndescription: x\n---\n\n# {fm_name} body\n{body}\n",
        encoding="utf-8",
    )
    archive = tmp_path / "archives" / archive_name
    archive.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "w:gz") as t:
        t.add(src, arcname=src.name)
    return archive


def test_add_infers_name_from_skill_md_frontmatter(patch_download, tmp_path):
    """4.2: no name passed -> read SKILL.md frontmatter."""
    _, mod, calls, _ = patch_download
    archive = _make_single_skill_tarball(tmp_path, "quirky-archive-name.tar.gz", "right-name")
    url = "https://example.test/quirky-archive-name.tar.gz"
    mod.download_with_headers = lambda u, dest: (calls.append(u), shutil.copy2(archive, dest), {})[-1]  # type: ignore[assignment]
    rc = run(mod, "add", url)
    assert rc == 0
    reg = json.loads(mod.registry_path().read_text())
    assert "right-name" in reg["skills"]
    # And no "quirky-archive-name" was registered
    assert "quirky-archive-name" not in reg["skills"]


def test_add_infers_name_from_url_when_no_frontmatter(patch_download, tmp_path):
    """4.2 fallback: no frontmatter -> strip URL basename + strip -skill suffix."""
    _, mod, calls, _ = patch_download
    # Build a tarball with SKILL.md but no frontmatter name
    src = tmp_path / "src" / "v1"
    src.mkdir(parents=True, exist_ok=True)
    (src / "SKILL.md").write_text("# Just a body, no frontmatter\n", encoding="utf-8")
    archive = tmp_path / "archives" / "demo-skill.tar.gz"
    archive.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "w:gz") as t:
        t.add(src, arcname="v1")
    url = "https://example.test/demo-skill.tar.gz"
    mod.download_with_headers = lambda u, dest: (calls.append(u), shutil.copy2(archive, dest), {})[-1]  # type: ignore[assignment]
    rc = run(mod, "add", url)
    assert rc == 0
    reg = json.loads(mod.registry_path().read_text())
    assert "demo" in reg["skills"]  # -skill suffix stripped


def test_add_explicit_name_overrides_inference(patch_download, tmp_path):
    """4.2: if name is given, use it (don't read frontmatter)."""
    _, mod, calls, urls = patch_download
    rc = run(mod, "add", "my-chosen", urls["v1"])
    assert rc == 0
    reg = json.loads(mod.registry_path().read_text())
    assert "my-chosen" in reg["skills"]
    assert "demo" not in reg["skills"]  # frontmatter would have said "demo"


# ---------- 4.3: duplicate name rejected (already in v0.1; tightened error) ----------


def test_add_duplicate_includes_source_url_in_error(patch_download, capsys):
    _, mod, calls, urls = patch_download
    run(mod, "add", "demo", urls["v1"])
    rc = run(mod, "add", "demo", "https://example.test/other.tar.gz")
    assert rc == 1
    err = capsys.readouterr().err
    assert "demo" in err
    assert urls["v1"] in err  # error points at the original source


# ---------- 4.4: HTTP HEAD fast path ----------


def test_update_head_etag_match_skips_download(patch_download, capsys):
    """4.4: HEAD returns an ETag the registry already knows -> skip GET entirely.

    Uses the "with_etag" fixture variant so fake_head returns a stable ETag.
    We pre-seed the registry with the matching ETag to simulate that a
    previous update stored the cache key.
    """
    tmp_path, mod, calls, urls = patch_download
    run(mod, "add", "demo", urls["v1"])
    reg = json.loads(mod.registry_path().read_text())
    reg["skills"]["demo"]["etag"] = 'W/"stable-v1-etag"'
    mod.registry_path().write_text(json.dumps(reg))

    calls.clear()
    rc = run(mod, "update", "demo")
    assert rc == 0
    out = capsys.readouterr().out
    assert "up-to-date" in out
    assert calls == []  # no GET happened -- HEAD said "unchanged"


def test_update_head_no_etag_falls_through_to_sha(patch_download):
    """4.4: HEAD returns no ETag -> still GET + compare SHA-256 (fallback)."""
    tmp_path, mod, calls, urls = patch_download
    run(mod, "add", "demo", urls["v1"])
    calls.clear()
    rc = run(mod, "update", "demo")
    assert rc == 0
    # HEAD had no metadata, so we fell through to GET. fake_download flips
    # to v2 on second call -> SHA differs -> refreshed
    assert calls == [urls["v1"]]


def test_status_head_etag_match_skips_download(patch_download, capsys):
    """4.4: status also benefits from HEAD fast path."""
    tmp_path, mod, calls, urls = patch_download
    run(mod, "add", "demo", urls["v1"])
    reg = json.loads(mod.registry_path().read_text())
    reg["skills"]["demo"]["etag"] = 'W/"stable-v1-etag"'
    mod.registry_path().write_text(json.dumps(reg))

    calls.clear()
    rc = run(mod, "status", "demo")
    assert rc == 0
    out = capsys.readouterr().out
    assert "up-to-date" in out
    assert calls == []  # no GET


def test_update_bundle_refreshes_member_only(patch_download, tmp_path):
    """4.1 regression: bundle update must replace each member with ITS OWN subdir,
    not the whole extracted tarball (which would nest skills/ inside each store dir)."""
    _, mod, calls, _ = patch_download
    archive_v1 = _make_bundle(tmp_path, "b1.tar.gz", ["alpha", "beta"], marker="v1")
    archive_v2 = _make_bundle(tmp_path, "b2.tar.gz", ["alpha", "beta"], marker="v2")
    url = "https://example.test/b1.tar.gz"
    served = {"cur": archive_v1}

    def serve(u: str, dest: Path) -> dict[str, str]:
        calls.append(u)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(served["cur"], dest)
        return {}

    mod.download_with_headers = serve  # type: ignore[assignment]

    assert run(mod, "add", url) == 0
    assert (mod.store_dir() / "alpha" / "SKILL.md").is_file()
    # No nesting bug at add time
    assert not (mod.store_dir() / "alpha" / "skills").exists()

    # Swap in v2 (different sha256) and update
    served["cur"] = archive_v2
    assert run(mod, "update") == 0

    # Each member store dir holds ONLY its own SKILL.md
    assert (mod.store_dir() / "alpha" / "SKILL.md").read_text(encoding="utf-8").count("name: alpha") == 1
    assert (mod.store_dir() / "beta" / "SKILL.md").read_text(encoding="utf-8").count("name: beta") == 1
    assert not (mod.store_dir() / "alpha" / "skills").exists()
    assert not (mod.store_dir() / "beta" / "skills").exists()
    # v2 marker present
    assert "alpha body (v2)" in (mod.store_dir() / "alpha" / "SKILL.md").read_text(encoding="utf-8")


def test_update_bundle_install_points_refreshed(patch_download, tmp_path):
    """Bundle update must also re-link/re-copy the member's install points."""
    _, mod, calls, _ = patch_download
    archive_v1 = _make_bundle(tmp_path, "b1.tar.gz", ["alpha"], marker="v1")
    archive_v2 = _make_bundle(tmp_path, "b2.tar.gz", ["alpha"], marker="v2")
    url = "https://example.test/b1.tar.gz"
    served = {"cur": archive_v1}

    def serve(u: str, dest: Path) -> dict[str, str]:
        calls.append(u)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(served["cur"], dest)
        return {}

    mod.download_with_headers = serve  # type: ignore[assignment]

    run(mod, "add", url)
    link_target = tmp_path / "t-link" / "alpha"
    copy_target = tmp_path / "t-copy" / "alpha"
    run(mod, "install", "alpha", str(link_target))
    run(mod, "install", "alpha", str(copy_target), "--copy")

    served["cur"] = archive_v2
    run(mod, "update", "alpha")

    assert link_target.is_symlink()
    assert "alpha body (v2)" in (link_target / "SKILL.md").read_text(encoding="utf-8")
    assert not copy_target.is_symlink()
    assert "alpha body (v2)" in (copy_target / "SKILL.md").read_text(encoding="utf-8")


# Parametrize the two "etag match" tests to use the with_etag fixture variant.
for _name in ("test_update_head_etag_match_skips_download",
              "test_status_head_etag_match_skips_download"):
    _fn = locals()[_name]
    globals()[_name] = pytest.mark.parametrize(
        "patch_download", ["with_etag"], indirect=True
    )(_fn)


# ---------- end of v0.2 tests ----------


def test_registry_path_override_via_env(tmp_path, monkeypatch):
    custom_home = tmp_path / "alt-home"
    custom_home.mkdir()
    custom_store = tmp_path / "alt-store"
    custom_store.mkdir()
    monkeypatch.setenv("SKILL_HUB_HOME", str(custom_home))
    monkeypatch.setenv("SKILL_HUB_DATA", str(custom_store))
    monkeypatch.setenv("HOME", str(tmp_path))  # default should be ignored

    import importlib.util
    sys.modules.pop("skill_hub", None)
    spec = importlib.util.spec_from_file_location("skill_hub", SCRIPT)  # type: ignore[attr-defined]
    mod = importlib.util.module_from_spec(spec)  # type: ignore[attr-defined]
    sys.modules["skill_hub"] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]

    assert mod.registry_path() == custom_home / "registry.json"
    assert mod.store_dir() == custom_store
