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

    "stable" mode (via `@pytest.mark.parametrize("patch_download", ["stable"], indirect=True)`):
    always returns v1 (no version change between calls).
    """
    tmp_path, mod = isolated_home
    archive_v1 = _make_tarball(tmp_path / "archives", "sample-skill-v1.tar.gz", "v1")
    archive_v2 = _make_tarball(tmp_path / "archives", "sample-skill-v2.tar.gz", "v2")
    archive_zip = _make_zip(tmp_path / "archives", "sample-skill-v1.zip", "v1-zip")

    stable = getattr(request, "param", None) == "stable"

    calls: list[str] = []
    seen: set[str] = set()

    def fake_download(url: str, dest: Path) -> None:
        calls.append(url)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if url.endswith(".zip"):
            shutil.copy2(archive_zip, dest)
            return
        if stable:
            shutil.copy2(archive_v1, dest)
            return
        first_time = url not in seen
        seen.add(url)
        if first_time:
            shutil.copy2(archive_v1, dest)
        else:
            shutil.copy2(archive_v2, dest)

    mod.download = fake_download  # type: ignore[assignment]
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
