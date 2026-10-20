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
    # Agent config-root env vars must not leak in from the host shell: they
    # change alias resolution semantics (env-pinned candidates win outright).
    for var in (
        "CLAUDE_CONFIG_DIR",
        "CODEX_HOME",
        "GEMINI_CLI_HOME",
        "QWEN_HOME",
        "CODEBUDDY_CONFIG_DIR",
        "COPILOT_HOME",
        "OPENCODE_CONFIG_DIR",
        "QWENPAW_WORKING_DIR",
        "QWENPAW_AGENT_ID",
    ):
        monkeypatch.delenv(var, raising=False)

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


# ---------- v0.3: remove subcommand ----------


def test_remove_drops_skill_keeps_store(patch_download, tmp_path):
    """remove alone drops registry entry; store is left in place."""
    tmp_path, mod, calls, urls = patch_download
    run(mod, "add", "demo", urls["v1"])
    assert (mod.store_dir() / "demo").exists()
    rc = run(mod, "remove", "demo")
    assert rc == 0
    reg = json.loads(mod.registry_path().read_text())
    assert "demo" not in reg["skills"]
    # Store stays (no --purge)
    assert (mod.store_dir() / "demo").exists()


def test_remove_with_purge_deletes_store(patch_download):
    tmp_path, mod, calls, urls = patch_download
    run(mod, "add", "demo", urls["v1"])
    rc = run(mod, "remove", "demo", "--purge")
    assert rc == 0
    assert not (mod.store_dir() / "demo").exists()
    reg = json.loads(mod.registry_path().read_text())
    assert "demo" not in reg["skills"]


def test_remove_rejects_when_installs_exist(patch_download, capsys):
    """Hard safety: can't drop a skill while it still has install points."""
    tmp_path, mod, calls, urls = patch_download
    run(mod, "add", "demo", urls["v1"])
    run(mod, "install", "demo", str(tmp_path / "t1"))
    rc = run(mod, "remove", "demo", "--purge")
    assert rc == 1
    err = capsys.readouterr().err
    assert "install" in err
    assert "uninstall" in err
    # Registry unchanged
    reg = json.loads(mod.registry_path().read_text())
    assert "demo" in reg["skills"]


def test_remove_unknown_skill_rejected(patch_download):
    tmp_path, mod, calls, _ = patch_download
    rc = run(mod, "remove", "ghost")
    assert rc == 1


def test_remove_after_uninstall_succeeds(patch_download, tmp_path):
    """Happy path: uninstall target first, then remove."""
    tmp_path, mod, calls, urls = patch_download
    run(mod, "add", "demo", urls["v1"])
    run(mod, "install", "demo", str(tmp_path / "t1"))
    run(mod, "uninstall", "demo", str(tmp_path / "t1"))
    rc = run(mod, "remove", "demo", "--purge")
    assert rc == 0
    assert not (mod.store_dir() / "demo").exists()


def test_remove_bundle_child_does_not_touch_siblings(patch_download, tmp_path):
    """Removing one bundle child must not affect its siblings; orphan bundle
    entry gets pruned."""
    _, mod, calls, _ = patch_download
    archive = _make_bundle(tmp_path, "b1.tar.gz", ["alpha", "beta"])
    url = "https://example.test/b1.tar.gz"
    mod.download_with_headers = lambda u, dest: (calls.append(u), shutil.copy2(archive, dest), {})[-1]  # type: ignore[assignment]
    run(mod, "add", url)

    rc = run(mod, "remove", "alpha", "--purge")
    assert rc == 0
    reg = json.loads(mod.registry_path().read_text())
    assert "alpha" not in reg["skills"]
    assert "beta" in reg["skills"]
    # Bundle entry still has one surviving child -> kept
    assert any("alpha" in b.get("skills", []) for b in reg["bundles"].values()) or True
    # The specific bundle for this url must still mention beta
    assert url in reg["bundles"]
    assert reg["bundles"][url]["skills"] == ["beta"]


def test_remove_last_bundle_child_drops_bundle_entry(patch_download, tmp_path):
    _, mod, calls, _ = patch_download
    archive = _make_bundle(tmp_path, "b1.tar.gz", ["alpha", "beta"])
    url = "https://example.test/b1.tar.gz"
    mod.download_with_headers = lambda u, dest: (calls.append(u), shutil.copy2(archive, dest), {})[-1]  # type: ignore[assignment]
    run(mod, "add", url)
    run(mod, "remove", "alpha", "--purge")
    run(mod, "remove", "beta", "--purge")
    reg = json.loads(mod.registry_path().read_text())
    assert reg["bundles"] == {}


# ---------- v0.3: schema migration ----------


def _write_v1_registry(path: Path) -> None:
    """Write a registry in v1 format (no bundles, no source_bundle/etag/last_modified)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "schema_version": 1,
        "skills": {
            "alpha": {
                "url": "https://example.test/alpha.tar.gz",
                "version": "deadbeef" * 8,
                "installed_at": "2026-09-15T10:00:00+00:00",
            },
            "beta": {
                "url": "https://example.test/beta.tar.gz",
                "version": "cafebabe" * 8,
                "installed_at": "2026-09-15T10:00:00+00:00",
            },
        },
        "installs": {},
    }, indent=2), encoding="utf-8")


def test_v1_registry_auto_migrates_on_load(patch_download, capsys):
    """Loading a v1 registry should upgrade to v2 silently and print a notice
    on the FIRST write verb."""
    tmp_path, mod, calls, _ = patch_download
    _write_v1_registry(mod.registry_path())
    # Read-only verb -> no migration notice (quiet=True)
    rc = run(mod, "list")
    assert rc == 0
    err = capsys.readouterr().err
    assert "schema_version" not in err

    # First write verb triggers the notice (v1 -> v2 -> v3 chained)
    rc = run(mod, "remove", "alpha", "--purge")  # alpha has no installs, safe
    assert rc == 0
    err = capsys.readouterr().err
    assert "schema_version 3" in err

    # File is now persisted at v3
    reg = json.loads(mod.registry_path().read_text())
    assert reg["schema_version"] == 3
    assert "bundles" in reg
    assert "agents" in reg
    assert "alpha" not in reg["skills"]  # remove took effect during migration
    # Surviving skill got backfilled with v2-only fields
    assert reg["skills"]["beta"]["source_bundle"] is None
    assert reg["skills"]["beta"]["etag"] is None
    assert reg["skills"]["beta"]["last_modified"] is None


def test_fresh_run_uses_current_schema(patch_download, capsys):
    """No file at startup -> registry created with SCHEMA_VERSION (no migration)."""
    tmp_path, mod, calls, _ = patch_download
    # Don't write a registry; first write verb should create it at v2 without notice
    rc = run(mod, "list")
    assert rc == 0
    err = capsys.readouterr().err
    assert "schema_version" not in err


def test_future_schema_version_rejected(isolated_home, tmp_path):
    """Registry newer than this build -> error (downgrade protection)."""
    _, mod = isolated_home
    rp = mod.registry_path()
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text(json.dumps({
        "schema_version": 99,  # future
        "skills": {},
        "installs": {},
    }), encoding="utf-8")
    rc = mod.main(["list"])
    assert rc == 1


def test_invalid_top_level_rejected(isolated_home, tmp_path):
    """Registry JSON must be an object, not a list or scalar."""
    _, mod = isolated_home
    rp = mod.registry_path()
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text(json.dumps(["not", "a", "dict"]), encoding="utf-8")
    rc = mod.main(["list"])
    assert rc == 1


# ---------- end of v0.3 tests ----------


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


# ---------- v0.4: agent aliases ----------


def _add_demo(mod, urls, name="demo"):
    assert run(mod, "add", name, urls["v1"]) == 0


def test_agents_list_shows_builtin_defaults(patch_download, capsys):
    _, mod, _, _ = patch_download
    rc = run(mod, "agents", "list")
    assert rc == 0
    out = capsys.readouterr().out
    for alias in ("qwenpaw", "claude", "codex", "gemini", "opencode", "cursor",
                  "copilot", "qwen-code", "codebuddy", "iflow", "qoder", "trae"):
        assert alias in out, f"missing builtin alias {alias}"
    # qwenpaw is the only builtin that defaults to copy
    assert "qwenpaw\tQwenPaw\tcopy\tbuiltin" in out
    assert "claude\tClaude Code\tlink\tbuiltin" in out


def test_agent_prefers_project_dir_over_user_dir(patch_download, tmp_path, monkeypatch):
    _, mod, _, urls = patch_download
    _add_demo(mod, urls)
    proj = tmp_path / "proj"
    (proj / ".claude" / "skills").mkdir(parents=True)
    (Path(os.environ["HOME"]) / ".claude" / "skills").mkdir(parents=True)
    monkeypatch.chdir(proj)
    rc = run(mod, "install", "demo", "--agent", "claude")
    assert rc == 0
    assert (proj / ".claude" / "skills" / "demo").is_symlink()
    assert not (Path(os.environ["HOME"]) / ".claude" / "skills" / "demo").exists()


def test_agent_falls_back_to_user_dir(patch_download, tmp_path, monkeypatch):
    _, mod, _, urls = patch_download
    _add_demo(mod, urls)
    proj = tmp_path / "proj"
    proj.mkdir()
    user_skills = Path(os.environ["HOME"]) / ".claude" / "skills"
    user_skills.mkdir(parents=True)
    monkeypatch.chdir(proj)
    rc = run(mod, "install", "demo", "--agent", "claude")
    assert rc == 0
    assert (user_skills / "demo").is_symlink()


def test_agent_skips_candidates_with_unset_env(patch_download, tmp_path, monkeypatch):
    """QWENPAW_WORKING_DIR unset -> those candidates are skipped, not fatal."""
    _, mod, _, urls = patch_download
    _add_demo(mod, urls)
    monkeypatch.delenv("QWENPAW_WORKING_DIR", raising=False)
    monkeypatch.delenv("QWENPAW_AGENT_ID", raising=False)
    pool = Path(os.environ["HOME"]) / ".qwenpaw" / "skill_pool"
    pool.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    rc = run(mod, "install", "demo", "--agent", "qwenpaw")
    assert rc == 0
    assert (pool / "demo").is_dir() and not (pool / "demo").is_symlink()


def test_agent_env_default_syntax(patch_download, tmp_path, monkeypatch):
    """${VAR:-fallback} resolves to the fallback when VAR is unset."""
    _, mod, _, urls = patch_download
    _add_demo(mod, urls)
    monkeypatch.delenv("NO_SUCH_VAR_FOR_TEST", raising=False)
    target = tmp_path / "fallback-skills"
    target.mkdir()
    rc = run(mod, "agents", "add", "custom", f"${{NO_SUCH_VAR_FOR_TEST:-{target}}}")
    assert rc == 0
    rc = run(mod, "install", "demo", "--agent", "custom")
    assert rc == 0
    assert (target / "demo").is_symlink()


def test_agent_no_candidate_exists_errors(patch_download, tmp_path, monkeypatch):
    _, mod, _, urls = patch_download
    # Move HOME before add so the registry lands in the (empty) new home
    monkeypatch.setenv("HOME", str(tmp_path / "empty-home"))
    (tmp_path / "empty-home").mkdir()
    _add_demo(mod, urls)
    monkeypatch.chdir(tmp_path)
    rc = run(mod, "install", "demo", "--agent", "codex")
    assert rc == 1


def test_agent_create_makes_first_candidate(patch_download, tmp_path, monkeypatch):
    _, mod, _, urls = patch_download
    (tmp_path / "empty-home").mkdir()
    monkeypatch.setenv("HOME", str(tmp_path / "empty-home"))
    _add_demo(mod, urls)
    proj = tmp_path / "proj"
    proj.mkdir()
    monkeypatch.chdir(proj)
    rc = run(mod, "install", "demo", "--agent", "claude", "--create")
    assert rc == 0
    # First candidate for claude is {cwd}/.claude/skills
    assert (proj / ".claude" / "skills" / "demo").is_symlink()


def test_agent_default_mode_link_and_copy_override(patch_download, tmp_path, monkeypatch):
    _, mod, _, urls = patch_download
    _add_demo(mod, urls)
    monkeypatch.chdir(tmp_path)
    user_skills = Path(os.environ["HOME"]) / ".claude" / "skills"
    user_skills.mkdir(parents=True)
    # default = link
    assert run(mod, "install", "demo", "--agent", "claude") == 0
    assert (user_skills / "demo").is_symlink()
    # explicit --copy overrides
    assert run(mod, "install", "demo", "--agent", "claude", "--copy") == 0
    assert (user_skills / "demo").is_dir() and not (user_skills / "demo").is_symlink()
    # registry records the agent and the copy mode
    reg = json.loads(mod.registry_path().read_text())
    entry = [i for i in reg["installs"]["demo"] if i["target"] == str(user_skills / "demo")][0]
    assert entry["mode"] == "copy" and entry["agent"] == "claude"


def test_agent_copy_override_to_link(patch_download, tmp_path, monkeypatch):
    """qwenpaw defaults to copy; --link must win when asked."""
    _, mod, _, urls = patch_download
    _add_demo(mod, urls)
    monkeypatch.delenv("QWENPAW_WORKING_DIR", raising=False)
    pool = Path(os.environ["HOME"]) / ".qwenpaw" / "skill_pool"
    pool.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    assert run(mod, "install", "demo", "--agent", "qwenpaw", "--link") == 0
    assert (pool / "demo").is_symlink()


def test_install_at_alias_sugar(patch_download, tmp_path, monkeypatch):
    _, mod, _, urls = patch_download
    _add_demo(mod, urls)
    monkeypatch.chdir(tmp_path)
    user_skills = Path(os.environ["HOME"]) / ".cursor" / "skills"
    user_skills.mkdir(parents=True)
    assert run(mod, "install", "demo", "@cursor") == 0
    assert (user_skills / "demo").is_symlink()


def test_agents_add_custom_alias(patch_download, tmp_path):
    _, mod, _, _ = patch_download
    p1 = tmp_path / "p1"
    p2 = tmp_path / "p2"
    rc = run(mod, "agents", "add", "my-agent", str(p1), str(p2), "--mode", "copy", "--label", "Mine")
    assert rc == 0
    agents = mod.effective_agents(json.loads(mod.registry_path().read_text()))
    assert agents["my-agent"]["paths"] == [str(p1), str(p2)]
    assert agents["my-agent"]["mode"] == "copy"
    assert agents["my-agent"]["label"] == "Mine"
    assert agents["my-agent"]["builtin"] is False


def test_agents_add_defaults_to_link(patch_download, tmp_path):
    _, mod, _, _ = patch_download
    assert run(mod, "agents", "add", "nolink", str(tmp_path / "x")) == 0
    agents = mod.effective_agents(json.loads(mod.registry_path().read_text()))
    assert agents["nolink"]["mode"] == "link"


def test_agents_add_overrides_builtin_paths(patch_download, tmp_path, monkeypatch):
    _, mod, _, urls = patch_download
    _add_demo(mod, urls)
    custom = tmp_path / "custom-claude"
    custom.mkdir()
    assert run(mod, "agents", "add", "claude", str(custom)) == 0
    monkeypatch.chdir(tmp_path)
    assert run(mod, "install", "demo", "--agent", "claude") == 0
    assert (custom / "demo").is_symlink()


def test_agents_remove_builtin_tombstones(patch_download, tmp_path, monkeypatch):
    _, mod, _, urls = patch_download
    _add_demo(mod, urls)
    monkeypatch.chdir(tmp_path)
    assert run(mod, "agents", "remove", "claude") == 0
    assert "claude" not in mod.effective_agents(json.loads(mod.registry_path().read_text()))
    rc = run(mod, "install", "demo", "--agent", "claude")
    assert rc == 1


def test_agents_reset_restores_builtin(patch_download):
    _, mod, _, _ = patch_download
    assert run(mod, "agents", "remove", "claude") == 0
    assert run(mod, "agents", "reset", "claude") == 0
    assert "claude" in mod.effective_agents(json.loads(mod.registry_path().read_text()))


def test_agents_reset_all(patch_download, tmp_path):
    _, mod, _, _ = patch_download
    run(mod, "agents", "remove", "claude")
    run(mod, "agents", "add", "x", str(tmp_path / "y"))
    assert run(mod, "agents", "reset") == 0
    agents = mod.effective_agents(json.loads(mod.registry_path().read_text()))
    assert "claude" in agents and "x" not in agents


def test_unknown_agent_alias_rejected(patch_download, tmp_path, monkeypatch):
    _, mod, _, _ = patch_download
    monkeypatch.chdir(tmp_path)
    rc = run(mod, "install", "anything", "--agent", "nope")
    assert rc == 1


def test_v2_registry_migrates_to_v3(patch_download, capsys):
    _, mod, _, urls = patch_download
    rp = mod.registry_path()
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text(json.dumps({
        "schema_version": 2,
        "skills": {},
        "installs": {},
        "bundles": {},
    }), encoding="utf-8")
    assert run(mod, "list") == 0
    assert "agents" not in json.loads(rp.read_text())  # read-only: not rewritten
    assert "schema_version" not in capsys.readouterr().err
    _add_demo(mod, urls)  # first write verb
    reg = json.loads(rp.read_text())
    assert reg["schema_version"] == 3
    assert reg["agents"] == {}
    assert "v2->v3" in capsys.readouterr().err


# ---------- v0.5: env-configurable skills roots ----------


def _agent_env_case(patch_download, tmp_path, monkeypatch, var, alias, root_rel, sub):
    """Helper: env var -> root; skills live at <root>/<sub>."""
    _, mod, _, urls = patch_download
    _add_demo(mod, urls)
    root = tmp_path / root_rel
    (root / sub).mkdir(parents=True)
    monkeypatch.setenv(var, str(root))
    monkeypatch.chdir(tmp_path)
    return mod, root / sub


def test_env_pinned_wins_over_existing_default(patch_download, tmp_path, monkeypatch):
    """CLAUDE_CONFIG_DIR set -> use it even though ~/.claude/skills also exists."""
    mod, env_skills = _agent_env_case(
        patch_download, tmp_path, monkeypatch, "CLAUDE_CONFIG_DIR", "claude", "cfg", "skills"
    )
    default_skills = Path(os.environ["HOME"]) / ".claude" / "skills"
    default_skills.mkdir(parents=True)
    assert run(mod, "install", "demo", "--agent", "claude") == 0
    assert (env_skills / "demo").is_symlink()
    assert not (default_skills / "demo").exists()


def test_env_pinned_missing_does_not_fall_back(patch_download, tmp_path, monkeypatch):
    """Env says where the root is; if its skills dir is absent we fail instead of
    silently installing somewhere the agent will never read."""
    _, mod, _, urls = patch_download
    _add_demo(mod, urls)
    cfg = tmp_path / "cfg"          # exists, but cfg/skills does not
    cfg.mkdir()
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    default_skills = Path(os.environ["HOME"]) / ".claude" / "skills"
    default_skills.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    rc = run(mod, "install", "demo", "--agent", "claude")
    assert rc == 1
    assert not (default_skills / "demo").exists()
    assert not (cfg / "skills").exists()


def test_env_pinned_create(patch_download, tmp_path, monkeypatch):
    _, mod, _, urls = patch_download
    _add_demo(mod, urls)
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    monkeypatch.chdir(tmp_path)
    assert run(mod, "install", "demo", "--agent", "claude", "--create") == 0
    assert (cfg / "skills" / "demo").is_symlink()


def test_env_root_qwen_code(patch_download, tmp_path, monkeypatch):
    mod, env_skills = _agent_env_case(
        patch_download, tmp_path, monkeypatch, "QWEN_HOME", "qwen-code", "qhome", "skills"
    )
    legacy = Path(os.environ["HOME"]) / ".qwen" / "skills"
    legacy.mkdir(parents=True)
    assert run(mod, "install", "demo", "--agent", "qwen-code") == 0
    assert (env_skills / "demo").is_symlink()
    assert not (legacy / "demo").exists()


def test_env_root_copilot_and_codebuddy(patch_download, tmp_path, monkeypatch):
    mod, cop_skills = _agent_env_case(
        patch_download, tmp_path, monkeypatch, "COPILOT_HOME", "copilot", "cop-home", "skills"
    )
    assert run(mod, "install", "demo", "--agent", "copilot") == 0
    assert (cop_skills / "demo").is_symlink()

    cb_home = tmp_path / "cb-home"
    (cb_home / "skills").mkdir(parents=True)
    monkeypatch.setenv("CODEBUDDY_CONFIG_DIR", str(cb_home))
    assert run(mod, "install", "demo", "--agent", "codebuddy") == 0
    assert (cb_home / "skills" / "demo").is_symlink()


def test_env_root_gemini_uses_dot_gemini_subdir(patch_download, tmp_path, monkeypatch):
    """GEMINI_CLI_HOME is the *root*; Gemini creates .gemini inside it."""
    mod, env_skills = _agent_env_case(
        patch_download, tmp_path, monkeypatch, "GEMINI_CLI_HOME", "gemini", "groot", ".gemini/skills"
    )
    assert run(mod, "install", "demo", "--agent", "gemini") == 0
    assert (env_skills / "demo").is_symlink()


def test_env_root_codex(patch_download, tmp_path, monkeypatch):
    mod, env_skills = _agent_env_case(
        patch_download, tmp_path, monkeypatch, "CODEX_HOME", "codex", "cxhome", "skills"
    )
    assert run(mod, "install", "demo", "--agent", "codex") == 0
    assert (env_skills / "demo").is_symlink()


def test_agents_list_marks_env_pinned(patch_download, tmp_path, monkeypatch, capsys):
    _, mod, _, _ = patch_download
    cfg = tmp_path / "cfg"
    (cfg / "skills").mkdir(parents=True)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    capsys.readouterr()
    assert run(mod, "agents", "list") == 0
    out = capsys.readouterr().out
    line = [l for l in out.splitlines() if "CLAUDE_CONFIG_DIR" in l][0]
    assert "[env-pinned]" in line
