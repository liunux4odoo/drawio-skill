#!/usr/bin/env python3
"""skill-hub: install/maintain skills from user-specified URLs.

Pure Python standard library. Single file, no install, no dependencies.

Registry: ~/.config/skill-hub/registry.json  (overridable via SKILL_HUB_HOME)
Store:    ~/.local/share/skill-hub/skills/   (overridable via SKILL_HUB_DATA)

Subcommands:
    add [name] <url>            register + download; name inferred if omitted
    install <name> <target>     link (default) or copy store -> target
    update [name]               re-check; refresh every install point
    list                        print registry contents
    status <name>               show installed vs latest, install points
    uninstall <name> <target>   remove an install point (store kept)
    remove <name> [--purge]     drop a skill from the registry; --purge also
                                deletes the store (install points must already
                                be uninstalled)

Exit codes:
    0  success
    1  input/argument/registry error
    2  I/O error (network, extract, link)

URL forms:
    1. Direct skill tarball: .../my-skill.tar.gz -> registers 1 skill
    2. Bundle tarball:        .../skills-bundle.tar.gz containing skills/<a>/SKILL.md
                               skills/<b>/SKILL.md ... -> registers N skills
    Bundle mode is detected by the top-level "skills/<child>/SKILL.md" pattern.

Update flow (v0.2):
    1. HTTP HEAD on the URL; compare ETag (and Last-Modified) with stored hints
    2. If 304 Not Modified (or ETag matches) -> skip download, no change
    3. Otherwise GET the tarball, compare SHA-256 to stored version
    4. If SHA-256 unchanged -> skip extract, just update timestamp
    5. If SHA-256 changed -> replace store + re-link/re-copy installs

Schema migration (v0.3):
    The registry carries a schema_version field. On load, any older version
    is upgraded in-memory via MIGRATIONS and rewritten to disk the next time
    a save verb runs. Newer versions than the running tool errors out (the
    user must upgrade skill-hub).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
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

SCHEMA_VERSION = 2
EXIT_OK = 0
EXIT_INPUT_ERROR = 1
EXIT_IO_ERROR = 2

CHUNK = 65536
DEFAULT_TIMEOUT = 60  # seconds
BUNDLE_DIR_NAME = "skills"
USER_AGENT = "skill-hub/1.3"

FRONTMATTER_NAME_RE = re.compile(r"^name:\s*([A-Za-z0-9._\-]+)\s*$", re.MULTILINE)
URL_BASENAME_RE = re.compile(r"^.*?([^/]+?)(?:\.tar\.gz|\.tgz|\.zip)(?:\?.*)?$", re.IGNORECASE)
SUFFIX_SKILL_RE = re.compile(r"[-_]?skills?$", re.IGNORECASE)


def _home() -> Path:
    return Path(os.environ.get("SKILL_HUB_HOME") or (Path.home() / ".config" / "skill-hub"))


def _store() -> Path:
    return Path(os.environ.get("SKILL_HUB_DATA") or (Path.home() / ".local" / "share" / "skill-hub" / "skills"))


def registry_path() -> Path:
    return _home() / "registry.json"


def store_dir() -> Path:
    return _store()


def _migrate_v1_to_v2(data: dict[str, Any]) -> list[str]:
    """v1 -> v2: add `bundles` map; backfill `source_bundle` on every skill.

    v1 registry had no bundles and no source_bundle field. Every v1 skill came
    from a single-skill URL, so source_bundle is always null. The bundles map
    starts empty. `etag` / `last_modified` are cache hints; absent means "unknown",
    which makes update fall through to the SHA-256 path exactly once.
    """
    notes: list[str] = []
    data.setdefault("bundles", {})
    for info in data.get("skills", {}).values():
        info.setdefault("source_bundle", None)
        info.setdefault("etag", None)
        info.setdefault("last_modified", None)
    notes.append(f"v1->v2: 新增 bundles 映射；{len(data.get('skills', {}))} 个 skill 标记 source_bundle=null")
    return notes


# Ordered migration steps: (from_version, to_version, fn). Each fn mutates the
# registry dict in place and returns human-readable notes for stderr.
MIGRATIONS: list[tuple[int, int, Any]] = [
    (1, 2, _migrate_v1_to_v2),
]


def _apply_migrations(data: dict[str, Any]) -> list[str]:
    """Migrate `data` up to SCHEMA_VERSION in place; return note strings.

    Raises InputError when the registry is newer than this build (a downgrade)
    or when no migration path exists.
    """
    current = data.get("schema_version")
    if not isinstance(current, int):
        raise InputError(f"registry schema_version={current!r} 不是整数（registry 可能损坏）")
    if current > SCHEMA_VERSION:
        raise InputError(
            f"registry schema_version={current} 高于本工具支持的 {SCHEMA_VERSION}；"
            f"请升级 skill-hub 后再试（不会自动降级）"
        )
    notes: list[str] = []
    while current < SCHEMA_VERSION:
        step = next(
            ((f, t, fn) for f, t, fn in MIGRATIONS if f == current), None
        )
        if step is None:
            raise InputError(
                f"缺少 schema_version {current} -> {SCHEMA_VERSION} 的迁移路径；"
                f"请手工编辑 {registry_path()}"
            )
        frm, to, fn = step
        notes.extend(fn(data))
        current = to
        data["schema_version"] = to
    return notes


def load_registry(*, quiet: bool = False) -> dict[str, Any]:
    """Load the registry, auto-migrating older schema versions forward.

    Migration is in-memory here; the file is rewritten only when a verb saves.
    Pass quiet=True to suppress the migration notice (used by read-only verbs).
    """
    p = registry_path()
    if not p.exists():
        return {"schema_version": SCHEMA_VERSION, "skills": {}, "installs": {}, "bundles": {}}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InputError(f"registry 无法解析 {p}：{exc}") from exc
    if not isinstance(data, dict):
        raise InputError(f"registry 顶层不是 JSON 对象（{p}）")

    notes = _apply_migrations(data)
    data.setdefault("skills", {})
    data.setdefault("installs", {})
    data.setdefault("bundles", {})
    if notes and not quiet:
        print(
            "skill-hub: registry 已自动迁移 "
            f"-> schema_version {data['schema_version']}",
            file=sys.stderr,
        )
        for n in notes:
            print(f"  - {n}", file=sys.stderr)
    return data


def save_registry(reg: dict[str, Any]) -> None:
    p = registry_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(reg, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


# ---------- network: download + HTTP HEAD (v0.2 fast path) ----------


def head_metadata(url: str) -> dict[str, str]:
    """Return lowercase header dict via HEAD; empty dict on failure."""
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT) as resp:
            return {k.lower(): v for k, v in resp.headers.items()}
    except (urllib.error.URLError, TimeoutError, OSError, AttributeError):
        return {}


def _capture_cache_headers(url: str) -> dict[str, str]:
    """Return lowercased ETag/Last-Modified via HEAD; empty dict on failure."""
    headers = head_metadata(url)
    return {k: v for k, v in headers.items() if k in ("etag", "last-modified")}


def _stamp_cache_headers(info: dict[str, Any], headers: dict[str, str]) -> None:
    """Persist ETag/Last-Modified in the skill entry for the HEAD fast path."""
    for k in ("etag", "last-modified"):
        if k in headers:
            info[k.replace("-", "_")] = headers[k]


def download_with_headers(url: str, dest: Path) -> dict[str, str]:
    """Download and return lowercased ETag/Last-Modified (if server sent them)."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT) as resp:
            with open(dest, "wb") as fh:
                shutil.copyfileobj(resp, fh)
            return {k.lower(): v for k, v in resp.headers.items()
                    if k.lower() in ("etag", "last-modified")}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise IOErr(f"下载失败 {url}：{exc}") from exc


def download(url: str, dest: Path) -> None:
    """Download only (ignores response headers)."""
    download_with_headers(url, dest)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def archive_suffix(url: str) -> str:
    """Return the archive suffix for a URL: 'tar.gz', 'tgz', or 'zip'."""
    base = url.split("?", 1)[0].lower()
    if base.endswith(".tar.gz"):
        return "tar.gz"
    if base.endswith(".zip"):
        return "zip"
    if base.endswith(".tgz"):
        return "tgz"
    # default to .tgz (most common); extract() will fail with a clear error if not
    return "tgz"


# ---------- extraction + name inference ----------


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


def detect_bundle_layout(extracted_root: Path) -> list[Path] | None:
    """If extracted_root/<BUNDLE_DIR_NAME>/<child>/SKILL.md pattern, return child dirs.
    Otherwise return None (single-skill layout)."""
    bundle = extracted_root / BUNDLE_DIR_NAME
    if not bundle.is_dir():
        return None
    children: list[Path] = []
    for child in sorted(bundle.iterdir()):
        if not child.is_dir():
            continue
        if (child / "SKILL.md").is_file():
            children.append(child)
    return children or None


def read_skill_name(skill_dir: Path) -> str | None:
    """Read SKILL.md frontmatter; return `name:` value if present and valid."""
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        return None
    try:
        text = skill_md.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = FRONTMATTER_NAME_RE.search(text[:2000])  # frontmatter is at the top
    return m.group(1) if m else None


def infer_name_from_url(url: str) -> str:
    """Fallback name inference: strip suffix, query, archive extension."""
    m = URL_BASENAME_RE.match(url)
    base = m.group(1) if m else "skill"
    base = SUFFIX_SKILL_RE.sub("", base)
    return base or "skill"


def validate_name(name: str) -> None:
    if not name or "/" in name or "\\" in name or name in (".", "..") or any(
        ch.isspace() for ch in name
    ):
        raise InputError(f"非法的 skill 名：{name!r}（不允许路径分隔符或空白）")


# ---------- refresh helper used by add and update ----------


def _refresh_install(reg: dict[str, Any], name: str, store: Path) -> None:
    """Re-link or re-copy every install point of a skill after its store updated."""
    for ins in reg.get("installs", {}).get(name, []):
        tgt = Path(ins["target"])
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


# ---------- subcommand implementations ----------


def cmd_add(name: str | None, url: str) -> int:
    if not (url.startswith("http://") or url.startswith("https://")):
        raise InputError(f"url 必须以 http:// 或 https:// 开头，得到 {url!r}")
    reg = load_registry()

    with tempfile.TemporaryDirectory(prefix="skill-hub-") as td:
        archive = Path(td) / f"skill.{archive_suffix(url)}"
        cache_headers = download_with_headers(url, archive)
        version = sha256_file(archive)
        extract_root = Path(td) / "extracted"
        extract(archive, extract_root)
        children = detect_bundle_layout(extract_root)

        if children is not None:
            # Bundle mode: register every child
            if name is not None:
                # user gave an explicit name; treat as single-skill (ignore bundle)
                # OR error? design choice: warn + single-skill mode for the bundle root
                # -> simpler: error and tell user to call without name
                raise InputError(
                    f"检测到 bundle（顶层 skills/），请省略 name 参数让脚本逐个注册"
                )
            bundle_id = url  # use url as the bundle id (one source -> one bundle)
            reg.setdefault("bundles", {})
            bundle_skills: list[str] = []
            for child in children:
                sname = read_skill_name(child) or child.name
                validate_name(sname)
                if sname in reg["skills"]:
                    raise InputError(
                        f"skill '{sname}' 已注册（来自 {reg['skills'][sname].get('url', '?')}）；"
                        f"bundle 中重名 skill 不会自动 namespace，请先 `remove` 已有 skill 或从 bundle 中排除"
                    )
                # copy child into store/<sname>
                target = store_dir() / sname
                if target.exists():
                    shutil.rmtree(target)
                shutil.copytree(child, target)
                reg["skills"][sname] = {
                    "url": url,  # same parent url
                    "version": version,  # same parent hash
                    "installed_at": datetime.now(timezone.utc).isoformat(),
                    "source_bundle": bundle_id,
                }
                _stamp_cache_headers(reg["skills"][sname], cache_headers)
                bundle_skills.append(sname)
            reg["bundles"][bundle_id] = {
                "url": url,
                "version": version,
                "skills": bundle_skills,
                "installed_at": datetime.now(timezone.utc).isoformat(),
            }
            save_registry(reg)
            for s in bundle_skills:
                print(f"added '{s}' (from bundle) version={version[:12]} store={store_dir() / s}")
            print(f"bundle '{bundle_id}' registered {len(bundle_skills)} skills")
            return EXIT_OK

        # Single-skill mode
        # Detect if the extracted root is a single wrapper directory
        only_child = next(iter(extract_root.iterdir()), None) if extract_root.is_dir() else None
        single_wrapper = (
            only_child is not None
            and only_child.is_dir()
            and len(list(extract_root.iterdir())) == 1
        )
        skill_root = only_child if single_wrapper else extract_root
        if name is None:
            # infer: first try SKILL.md frontmatter, then URL
            sname = read_skill_name(skill_root) or infer_name_from_url(url)
        else:
            sname = name
        validate_name(sname)
        if sname in reg["skills"]:
            raise InputError(
                f"skill '{sname}' 已注册（来自 {reg['skills'][sname].get('url', '?')}）；"
                f"如需替换请先 `remove`，或用 `update` 刷新内容"
            )
        target = store_dir() / sname
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(skill_root, target)
        reg["skills"][sname] = {
            "url": url,
            "version": version,
            "installed_at": datetime.now(timezone.utc).isoformat(),
            "source_bundle": None,
        }
        _stamp_cache_headers(reg["skills"][sname], cache_headers)
        save_registry(reg)
        print(f"added '{sname}' version={version[:12]} store={target}")
        return EXIT_OK


def _is_unchanged_remote(reg: dict[str, Any], info: dict[str, Any]) -> bool:
    """Return True if HEAD metadata indicates the remote has not changed since last fetch.

    Falls through to False (caller must do full GET+sha compare) when metadata is
    missing or the request fails.
    """
    headers = head_metadata(info["url"])
    etag = headers.get("etag")
    last_mod = headers.get("last-modified")
    stored_etag = info.get("etag")
    stored_last_mod = info.get("last_modified")
    if etag and stored_etag and etag == stored_etag:
        return True
    if last_mod and stored_last_mod and last_mod == stored_last_mod:
        return True
    return False


def _install_bundle_member(
    extract_root: Path, store: Path, skill_name: str
) -> None:
    """Copy a bundle child (extract_root/skills/<child>) into store, matching `add`."""
    bundle_dir = extract_root / BUNDLE_DIR_NAME
    child = bundle_dir / skill_name
    if not (child / "SKILL.md").is_file():
        raise IOErr(f"bundle 中找不到 skill '{skill_name}' 的 SKILL.md（源布局可能变了）")
    if store.exists():
        shutil.rmtree(store)
    shutil.copytree(child, store)


def cmd_update(name: str | None = None) -> int:
    reg = load_registry()
    targets = [name] if name else sorted(reg["skills"])
    if name and name not in reg["skills"]:
        raise InputError(f"未注册的 skill：{name}")
    refreshed: list[str] = []
    up_to_date: list[str] = []
    for n in targets:
        info = reg["skills"][n]
        # 1. HTTP HEAD fast path: ETag/Last-Modified match -> no download at all
        if _is_unchanged_remote(reg, info):
            up_to_date.append(n)
            continue
        # 2. GET + SHA-256 compare
        with tempfile.TemporaryDirectory(prefix="skill-hub-") as td:
            archive = Path(td) / f"skill.{archive_suffix(info['url'])}"
            cache_headers = download_with_headers(info["url"], archive)
            new_version = sha256_file(archive)
            if new_version == info["version"]:
                # Content unchanged but HEAD differed -> server rotated metadata only
                info["installed_at"] = datetime.now(timezone.utc).isoformat()
                _stamp_cache_headers(info, cache_headers)
                up_to_date.append(n)
                continue
            # 3. Content changed -> replace store + refresh install points
            store = store_dir() / n
            if info.get("source_bundle"):
                # Bundle member: extract once, then copy just this skill's subdir
                extract_root = Path(td) / "extracted"
                extract(archive, extract_root)
                _install_bundle_member(extract_root, store, n)
            else:
                extract(archive, store)
        info["version"] = new_version
        info["installed_at"] = datetime.now(timezone.utc).isoformat()
        _stamp_cache_headers(info, cache_headers)
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
        raise IOErr(f"store 缺失：{src}（重新 add 或修复后重试）")
    tgt = Path(target).expanduser().resolve() if mode == "link" else Path(target).expanduser()
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


def cmd_remove(name: str, purge: bool) -> int:
    """Drop a skill from the registry (and, with --purge, delete its store).

    Bundle-aware: removing one child does not touch its siblings. If the
    parent bundle is no longer reachable (no other child references it), the
    bundle entry is also pruned.

    Install points are NEVER touched by `remove` -- a `remove` followed by an
    `add` with a new name would leave stale install entries for the old
    name, so we explicitly fail when any install is registered, listing the
    targets. Use `uninstall` for each target first, then `remove`.
    """
    reg = load_registry()
    if name not in reg["skills"]:
        raise InputError(f"未注册的 skill：{name}")
    if reg.get("installs", {}).get(name):
        targets = ", ".join(i["target"] for i in reg["installs"][name])
        raise InputError(
            f"skill '{name}' 还有 install 点未清理：{targets}。"
            f"先逐个 `uninstall '{name}' <target>` 再 `remove`"
        )

    info = reg["skills"].pop(name)
    reg.get("installs", {}).pop(name, None)
    # If the parent bundle is now orphan (no surviving child), drop it too.
    bundle_id = info.get("source_bundle")
    if bundle_id and bundle_id in reg.get("bundles", {}):
        # Prune this child from the bundle's skills list
        bundle_skills = reg["bundles"][bundle_id].get("skills", [])
        reg["bundles"][bundle_id]["skills"] = [s for s in bundle_skills if s != name]
        if not reg["bundles"][bundle_id]["skills"]:
            reg["bundles"].pop(bundle_id)

    store = store_dir() / name
    if purge and store.exists():
        if store.is_symlink():
            store.unlink()
        else:
            shutil.rmtree(store)
        print(f"removed store: {store}")

    save_registry(reg)
    print(f"removed '{name}' from registry (was: {info['url']})")
    return EXIT_OK


def cmd_list() -> int:
    reg = load_registry(quiet=True)
    if not reg["skills"]:
        print("(no skills registered)")
        return EXIT_OK
    for name, info in sorted(reg["skills"].items()):
        bundle = f"  [bundle: {info['source_bundle']}]" if info.get("source_bundle") else ""
        print(f"{name}\t{info['url']}\t{info['version'][:12]}\t{info['installed_at']}{bundle}")
        for ins in reg.get("installs", {}).get(name, []):
            print(f"  → {ins['target']} ({ins['mode']})")
    return EXIT_OK


def cmd_status(name: str) -> int:
    reg = load_registry(quiet=True)
    if name not in reg["skills"]:
        raise InputError(f"未注册的 skill：{name}")
    info = reg["skills"][name]
    print(f"name:             {name}")
    print(f"url:              {info['url']}")
    if info.get("source_bundle"):
        print(f"source_bundle:    {info['source_bundle']}")
    print(f"installed_version:{info['version']}")
    print(f"installed_at:     {info['installed_at']}")
    # Try HEAD fast path first
    headers = head_metadata(info["url"])
    etag = headers.get("etag", "")
    last_mod = headers.get("last-modified", "")
    if etag and info.get("etag") and etag == info["etag"]:
        print(f"latest_etag:      {etag} (unchanged)")
        print(f"status:           up-to-date")
    elif last_mod and info.get("last_modified") and last_mod == info["last_modified"]:
        print(f"latest_modified:  {last_mod} (unchanged)")
        print(f"status:           up-to-date")
    else:
        # Fallback: GET + sha compare
        try:
            with tempfile.TemporaryDirectory(prefix="skill-hub-") as td:
                archive = Path(td) / "skill.tgz"
                download(info["url"], archive)
                latest = sha256_file(archive)
            print(f"latest_version:   {latest}")
            print(f"status:           {'up-to-date' if latest == info['version'] else 'NEEDS UPDATE'}")
        except IOErr as exc:
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


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    p = _Parser(
        prog="skill-hub",
        description="Install/maintain skills from user-specified tarball URLs.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="register + download a new skill or skill bundle")
    a.add_argument("name", nargs="?", default=None,
                   help="skill 名（可选：从 SKILL.md frontmatter 或 URL 推断）")
    a.add_argument("url")

    u = sub.add_parser("update", help="re-check; refresh every install point")
    u.add_argument("name", nargs="?", default=None)

    i = sub.add_parser("install", help="install skill to target (link or copy)")
    i.add_argument("name")
    i.add_argument("target")
    i.add_argument("--copy", action="store_true", help="copy instead of symlink")

    r = sub.add_parser("uninstall", help="remove an install point (store kept)")
    r.add_argument("name")
    r.add_argument("target")

    rm = sub.add_parser("remove", help="drop a skill from the registry (use --purge to also delete its store)")
    rm.add_argument("name")
    rm.add_argument("--purge", action="store_true",
                    help="also delete the extracted source under the store dir")
    rm.add_argument("--yes", action="store_true",
                    help="(no-op, kept for future safety prompts)")

    sub.add_parser("list", help="list every registered skill + install points")
    s = sub.add_parser("status", help="show installed vs latest, install points")
    s.add_argument("name")

    args = p.parse_args(argv)
    ns = vars(args).copy()
    cmd = ns.pop("cmd")
    try:
        if cmd == "add":
            return cmd_add(ns.get("name"), ns["url"])
        if cmd == "update":
            return cmd_update(ns.get("name"))
        if cmd == "install":
            mode = "copy" if ns.pop("copy", False) else "link"
            return cmd_install(ns["name"], ns["target"], mode)
        if cmd == "uninstall":
            return cmd_uninstall(ns["name"], ns["target"])
        if cmd == "remove":
            return cmd_remove(ns["name"], ns["purge"])
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
