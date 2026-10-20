---
name: skill-hub
description: Install and maintain skills from user-specified URLs (tarballs). Use when the user wants to add a new skill from a URL, update installed skills to the latest version, install/link/copy a registered skill into a target directory (e.g. an agent's skills folder), or list/status the skill registry. Does NOT search, discover, or recommend skills — only maintains a user-curated set.
---

# Skill Hub

A minimal **install/maintain** registry for skills. The user supplies the URL of each skill's source archive (`.tar.gz`/`.tgz`/`.zip`); the skill downloads it once to a central store, then links or copies it to one or more target paths (typically an agent's `skills/` folder). Subsequent `update` calls re-download from the same URL, compare by tarball SHA-256, and refresh every install point in the chosen mode.

The skill does **not** search or recommend skills. If the user wants a new skill but does not provide a URL, ask for one or refuse — never invent sources.

## When to use

- The user provides a skill URL (tarball) and wants it added and/or installed.
- The user wants to refresh an installed skill to the latest version.
- The user wants to list installed skills or check which ones are out of date.
- The user wants to remove an installed copy (without deleting the source from the store).

Do **not** use it for: searching, browsing, rating, or recommending skills; modifying a skill's source code (edit the store directly, or override at the target with a real file/dir if `link` mode is in use); packaging or publishing skills.

## Layout

| Path | Purpose |
|---|---|
| `~/.config/skill-hub/registry.json` | Single source of truth: URLs, SHA-256 versions, install targets and modes. |
| `~/.local/share/skill-hub/skills/<name>/` | Central source pool: extracted tarball contents. |
| `<target>` (e.g. an agent's `skills/<name>/`) | Install point. Either a symlink to the store (default) or a recursive copy. |

## Commands

The bundled helper (`scripts/skill_hub.py`) speaks one verb per subcommand. Run it from anywhere; paths are absolute, no CWD assumptions.

```bash
# 1. Register + download
python3 scripts/skill_hub.py add <name> <tarball-url>

# 2. Install to a target (default: symlink; --copy to duplicate)
python3 scripts/skill_hub.py install <name> <target-path>
python3 scripts/skill_hub.py install <name> <target-path> --copy

# 3. Update everything (or one skill)
python3 scripts/skill_hub.py update              # all registered skills
python3 scripts/skill_hub.py update <name>       # one skill

# 4. Inspect
python3 scripts/skill_hub.py list
python3 scripts/skill_hub.py status <name>       # shows installed vs latest, install points

# 5. Remove an install (does not delete the store entry)
python3 scripts/skill_hub.py uninstall <name> <target-path>
```

Exit codes: `0` success, `1` input/argument error, `2` I/O error (network, extract, link).

## Workflow

1. **Locate the helper.** Resolve `scripts/skill_hub.py` relative to this skill folder (or to wherever the user installed the skill-hub skill).
2. **Ask for a URL** if the user has not provided one. The skill does not search.
3. **Run `add`** to download and register. Confirm the new entry with `status <name>` (shows URL, installed version, latest version).
4. **Run `install`** for each target the user wants. Default is `link` — point multiple targets (different agents, projects) at the same store entry without duplicating files. Use `--copy` when the target cannot host a symlink (e.g. some synced/remote filesystems, sandboxed locations).
5. **Update**: when the user says "update skills" or "refresh skill X", run `update`. The helper re-downloads the tarball, recomputes the SHA-256, and:
   - If unchanged: reports `up-to-date` and stops.
   - If changed: replaces the store contents, then for each install point: re-creates the `link` (remove old symlink, point to the new store path) or re-copies into `copy` targets.
6. **Uninstall** when a target is no longer needed; the store entry stays so the skill can be re-installed without re-downloading.
7. **Report** any non-zero exit code back to the user with the helper's stderr.

## Safety / boundaries

- The helper **never deletes the store entry** unless the user explicitly removes it (no `remove` verb yet — by design; if needed, add it).
- The helper **never overwrites a non-empty target** that is not a symlink or directory of the same skill. It will fail rather than wipe an unrelated directory. (If the target is a regular file, it is treated as the same slot and replaced.)
- `link` mode: removing the symlink does **not** affect the store; re-installing recreates it.
- `copy` mode: the target is a true duplicate; updates replace its contents.
- Network access is required only for `add` and `update`; `list`, `status` (without comparison), `install`, `uninstall` are fully offline once the store is populated.

## Reference Files

| File | Purpose |
|---|---|
| `references/quick-reference.md` | Copy-paste cheat sheet for the six subcommands, with typical one-liners. |
| `scripts/skill_hub.py` | Pure-stdlib Python helper (~15 KB). Single file, no install, no dependencies. |
