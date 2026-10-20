#!/usr/bin/env python3
"""skill-hub: install/maintain skills from user-specified URLs.

Pure Python standard library. Single file, no install, no dependencies.

Registry: ~/.config/skill-hub/registry.json  (overridable via SKILL_HUB_HOME)
Store:    ~/.local/share/skill-hub/skills/   (overridable via SKILL_HUB_DATA)

Subcommands:
    add <name> <url>             register + download + extract to store
    install <name> <target>      link (default) or copy store -> target
    update [name]                re-download; refresh every install point
    list                         print registry contents
    status <name>                installed vs latest, install points
    uninstall <name> <target>    remove an install point (store kept)

Exit codes:
    0  success
    1  input/argument/registry error
    2  I/O error (network, extract, link)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
EXIT_OK = 0
EXIT_INPUT_ERROR = 1
EXIT_IO_ERROR = 2

CHUNK = 65536
DEFAULT_TIMEOUT = 60  # seconds


def _home() -> Path:
    return Path(os.environ.get("SKILL_HUB_HOME") or (Path.home() / ".config" / "skill-hub"))


def _store() -> Path:
    return Path(os.environ.get("SKILL_HUB_DATA") or (Path.home() / ".local" / "share" / "skill-hub" / "skills"))


def registry_path() -> Path:
    return _home() / "registry.json"


def store_dir() -> Path:
    return _store()


def load_registry() -> dict[str, Any]:
    p = registry_path()
    if not p.exists():
        return {"schema_version": SCHEMA_VERSION, "skills": {}, "installs": {}}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InputError(f"registry 无法解析 {p}：{exc}") from exc
    if data.get("schema_version") != SCHEMA_VERSION:
        raise InputError(
            f"registry schema_version={data.get('schema_version')}，期望 {SCHEMA_VERSION}（不支持自动迁移）"
        )
    data.setdefault("skills", {})
    data.setdefault("installs", {})
    return data


def save_registry(reg: dict[str, Any]) -> None:
    p = registry_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(reg, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "skill-hub/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT) as resp:
            with open(dest, "wb") as fh:
                shutil.copyfileobj(resp, fh)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise IOErr(f"下载失败 {url}：{exc}") from exc


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def extract(archive: Path, dest: Path) -> None:
    """Extract .tar.gz/.tgz or .zip into dest (created/cleared beforehand)."""
    name = archive.name.lower()
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    if name.endswith(".zip"):
        try:
            with zipfile.ZipFile(archive) as z:
                z.extractall(dest)
        except (zipfile.BadZipFile, OSError) as exc:
            raise IOErr(f"zip 解压失败 {archive}：{exc}") from exc
    else:
        try:
            with tarfile.open(archive) as t:
                t.extractall(dest, filter="data")
        except (tarfile.TarError, OSError) as exc:
            raise IOErr(f"tar 解压失败 {archive}：{exc}") from exc


def validate_name(name: str) -> None:
    if not name or "/" in name or "\\" in name or name in (".", "..") or any(
        ch.isspace() for ch in name
    ):
        raise InputError(f"非法的 skill 名：{name!r}（不允许路径分隔符或空白）")


# ---------- subcommand implementations ----------


def cmd_add(name: str, url: str) -> int:
    validate_name(name)
    reg = load_registry()
    if name in reg["skills"]:
        raise InputError(f"skill '{name}' 已注册；如需更新请用 update")
    if not (url.startswith("http://") or url.startswith("https://")):
        raise InputError(f"url 必须以 http:// 或 https:// 开头，得到 {url!r}")
    with tempfile.TemporaryDirectory(prefix="skill-hub-") as td:
        archive = Path(td) / ("skill." + url.rsplit(".", 1)[-1].split("?", 1)[0])
        download(url, archive)
        version = sha256_file(archive)
        target = store_dir() / name
        extract(archive, target)
    reg["skills"][name] = {
        "url": url,
        "version": version,
        "installed_at": datetime.now(timezone.utc).isoformat(),
    }
    save_registry(reg)
    print(f"added '{name}' version={version[:12]} store={target}")
    return EXIT_OK


def _refresh_install(reg: dict[str, Any], name: str, store: Path) -> None:
    """Re-link or re-copy every install point of a skill after its store updated."""
    for ins in reg.get("installs", {}).get(name, []):
        tgt = Path(ins["target"])
        # Remove existing slot
        if tgt.is_symlink():
            tgt.unlink()
        elif tgt.is_dir():
            shutil.rmtree(tgt)
        elif tgt.exists():
            tgt.unlink()
        tgt.parent.mkdir(parents=True, exist_ok=True)
        if ins["mode"] == "link":
            tgt.symlink_to(store.resolve())
        else:  # copy
            shutil.copytree(store, tgt)


def cmd_update(name: str | None = None) -> int:
    reg = load_registry()
    targets = [name] if name else sorted(reg["skills"])
    if name and name not in reg["skills"]:
        raise InputError(f"未注册的 skill：{name}")
    refreshed: list[str] = []
    up_to_date: list[str] = []
    for n in targets:
        info = reg["skills"][n]
        with tempfile.TemporaryDirectory(prefix="skill-hub-") as td:
            archive = Path(td) / "skill.tgz"
            download(info["url"], archive)
            new_version = sha256_file(archive)
            if new_version == info["version"]:
                up_to_date.append(n)
                continue
            store = store_dir() / n
            extract(archive, store)
        info["version"] = new_version
        info["installed_at"] = datetime.now(timezone.utc).isoformat()
        _refresh_install(reg, n, store)
        refreshed.append(n)
    save_registry(reg)
    for n in refreshed:
        print(f"updated '{n}'")
    for n in up_to_date:
        print(f"up-to-date '{n}'")
    return EXIT_OK


def cmd_install(name: str, target: str, mode: str) -> int:
    if mode not in ("link", "copy"):
        raise InputError(f"mode 必须是 link 或 copy，得到 {mode!r}")
    reg = load_registry()
    if name not in reg["skills"]:
        raise InputError(f"未注册的 skill：{name}（先 add）")
    src = store_dir() / name
    if not src.exists():
        raise IOError(f"store 缺失：{src}（重新 add 或修复后重试）")
    tgt = Path(target).expanduser().resolve() if mode == "link" else Path(target).expanduser()
    # Clear any prior slot
    if tgt.is_symlink():
        tgt.unlink()
    elif tgt.is_dir():
        shutil.rmtree(tgt)
    elif tgt.exists():
        raise InputError(f"目标已存在且不是目录/链接：{tgt}（拒绝覆盖未识别的文件）")
    tgt.parent.mkdir(parents=True, exist_ok=True)
    if mode == "link":
        tgt.symlink_to(src.resolve())
    else:
        shutil.copytree(src, tgt)
    reg.setdefault("installs", {}).setdefault(name, [])
    installs = reg["installs"][name]
    installs[:] = [i for i in installs if i["target"] != str(tgt)]
    installs.append({"target": str(tgt), "mode": mode})
    save_registry(reg)
    print(f"installed '{name}' → {tgt} ({mode})")
    return EXIT_OK


def cmd_uninstall(name: str, target: str) -> int:
    reg = load_registry()
    tgt = Path(target).expanduser()
    if not (tgt.is_symlink() or tgt.exists()):
        raise InputError(f"目标不存在：{tgt}")
    if tgt.is_symlink():
        tgt.unlink()
    elif tgt.is_dir():
        shutil.rmtree(tgt)
    else:
        tgt.unlink()
    if name in reg.get("installs", {}):
        reg["installs"][name] = [i for i in reg["installs"][name] if i["target"] != str(tgt)]
        save_registry(reg)
    print(f"uninstalled '{name}' from {tgt}")
    return EXIT_OK


def cmd_list() -> int:
    reg = load_registry()
    if not reg["skills"]:
        print("(no skills registered)")
        return EXIT_OK
    for name, info in sorted(reg["skills"].items()):
        print(f"{name}\t{info['url']}\t{info['version'][:12]}\t{info['installed_at']}")
        for ins in reg.get("installs", {}).get(name, []):
            print(f"  → {ins['target']} ({ins['mode']})")
    return EXIT_OK


def cmd_status(name: str) -> int:
    reg = load_registry()
    if name not in reg["skills"]:
        raise InputError(f"未注册的 skill：{name}")
    info = reg["skills"][name]
    print(f"name:             {name}")
    print(f"url:              {info['url']}")
    print(f"installed_version:{info['version']}")
    print(f"installed_at:     {info['installed_at']}")
    try:
        with tempfile.TemporaryDirectory(prefix="skill-hub-") as td:
            archive = Path(td) / "skill.tgz"
            download(info["url"], archive)
            latest = sha256_file(archive)
        print(f"latest_version:   {latest}")
        print(f"status:           {'up-to-date' if latest == info['version'] else 'NEEDS UPDATE'}")
    except IOError as exc:
        print(f"latest_version:   (unavailable: {exc})")
    for ins in reg.get("installs", {}).get(name, []):
        print(f"install:          {ins['target']} ({ins['mode']})")
    return EXIT_OK


# ---------- CLI plumbing ----------


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        self.print_usage(sys.stderr)
        self.exit(EXIT_INPUT_ERROR, f"{self.prog}: error: {message}\n")


class InputError(Exception):
    """Raised for user-facing argument/registry errors; maps to exit code 1."""


class IOErr(Exception):
    """Raised for I/O failures; maps to exit code 2."""


# Re-bind module-level helpers to raise typed exceptions instead of bare ones
# (download and extract above already raise IOErr directly)

def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    p = _Parser(
        prog="skill-hub",
        description="Install/maintain skills from user-specified tarball URLs.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="register + download a new skill")
    a.add_argument("name")
    a.add_argument("url")

    u = sub.add_parser("update", help="re-download; refresh every install point")
    u.add_argument("name", nargs="?", default=None)

    i = sub.add_parser("install", help="install skill to target (link or copy)")
    i.add_argument("name")
    i.add_argument("target")
    i.add_argument("--copy", action="store_true", help="copy instead of symlink")

    r = sub.add_parser("uninstall", help="remove an install point (store kept)")
    r.add_argument("name")
    r.add_argument("target")

    sub.add_parser("list", help="list every registered skill + install points")
    s = sub.add_parser("status", help="show installed vs latest, install points")
    s.add_argument("name")

    args = p.parse_args(argv)
    ns = vars(args).copy()
    cmd = ns.pop("cmd")
    try:
        if cmd == "add":
            return cmd_add(ns["name"], ns["url"])
        if cmd == "update":
            return cmd_update(ns.get("name"))
        if cmd == "install":
            mode = "copy" if ns.pop("copy", False) else "link"
            return cmd_install(ns["name"], ns["target"], mode)
        if cmd == "uninstall":
            return cmd_uninstall(ns["name"], ns["target"])
        if cmd == "list":
            return cmd_list()
        if cmd == "status":
            return cmd_status(ns["name"])
    except InputError as exc:
        print(f"skill-hub: {exc}", file=sys.stderr)
        return EXIT_INPUT_ERROR
    except IOErr as exc:
        print(f"skill-hub: {exc}", file=sys.stderr)
        return EXIT_IO_ERROR
    return EXIT_INPUT_ERROR  # unreachable


if __name__ == "__main__":
    sys.exit(main())
