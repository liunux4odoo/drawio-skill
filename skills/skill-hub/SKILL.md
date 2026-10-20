---
name: skill-hub
description: Install and maintain skills from user-specified URLs (tarballs). Use when the user wants to add a new skill or skill bundle from a URL, update installed skills to the latest version (with HTTP HEAD fast path), install/link/copy a registered skill into a target directory, remove a skill from the registry, or list/status the skill registry. Does NOT search, discover, or recommend skills — only maintains a user-curated set.
---

# Skill Hub

A minimal **install/maintain** registry for skills. The user supplies the URL of each skill's source archive (`.tar.gz`/`.tgz`/`.zip`); the helper downloads it once to a central store, then links or copies it to one or more target paths (typically an agent's `skills/` folder). Subsequent `update` calls re-check the URL — first via a cheap HTTP `HEAD` (ETag/Last-Modified), then by SHA-256 if HEAD cannot decide — and refresh every install point when the remote has changed.

The skill does **not** search or recommend skills. If the user wants a new skill but does not provide a URL, ask for one or refuse — never invent sources.

## When to use

- The user provides a skill URL (tarball or bundle) and wants it added and/or installed.
- The user wants to refresh an installed skill to the latest version.
- The user wants to list installed skills or check which ones are out of date.
- The user wants to remove an installed copy (without deleting the source from the store).
- The user wants to drop a skill from the registry entirely (optionally deleting its store copy).

Do **not** use it for: searching, browsing, rating, or recommending skills; modifying a skill's source code (edit the store directly, or override at the target with a real file/dir if `link` mode is in use); packaging or publishing skills.

## Layout

| Path | Purpose |
|---|---|
| `~/.config/skill-hub/registry.json` | Single source of truth: URLs, SHA-256 versions, ETag/Last-Modified hints, install targets and modes, bundle metadata. |
| `~/.local/share/skill-hub/skills/<name>/` | Central source pool: extracted tarball contents. |
| `<target>` (e.g. an agent's `skills/<name>/`) | Install point. Either a symlink to the store (default) or a recursive copy. |

## URL forms

`add` accepts two URL shapes and auto-detects which one to use:

| Shape | Detection | Result |
|---|---|---|
| **Single skill tarball** | No `skills/<child>/SKILL.md` pattern under the extracted root | 1 entry in the registry |
| **Skill bundle** | Top-level `skills/<child>/SKILL.md` (one or more children) | N entries in the registry, all linked to the same parent URL; a `bundles[<parent-url>]` record lists them |

Bundle mode is the natural fit for repositories that ship several skills in one `skills/` directory (e.g. `opencode-wps`). To use it, pass the URL **without** an explicit `<name>`:

```bash
# Single skill
python3 scripts/skill_hub.py add https://example.com/skill.tar.gz

# Bundle (5 skills in one tarball)
python3 scripts/skill_hub.py add https://example.com/skills-bundle.tar.gz
```

## Name inference

When `add` is called without a `<name>` argument, the helper picks a registry key in this order:

1. **SKILL.md frontmatter** — reads the `name:` field (most accurate, ships with the skill)
2. **URL basename** — strips the archive extension (`.tar.gz`/`.tgz`/`.zip`) and the trailing `-skill`/`_skill` suffix
3. **Error** — neither source yields a name; the command fails with exit code 1

The explicit name (when given) always wins. Passing a name for a bundle URL is an error (since the bundle will register multiple skills, none of which would match the supplied name).

## Update flow (v0.2)

1. `HTTP HEAD` on each skill's URL. The helper caches the first-seen `ETag` and `Last-Modified` in the registry after each add/update.
2. If the server returns the same `ETag` (or same `Last-Modified`) as the registry, the helper reports `up-to-date` and **does not download** the tarball.
3. Otherwise the helper `GET`s the tarball, recomputes its `SHA-256`, and compares it with the stored version.
4. If `SHA-256` matches, the helper still updates the `installed_at` timestamp (server rotated metadata but content is unchanged) — no re-extract.
5. If `SHA-256` differs, the helper replaces the store contents and re-links/re-copies every install point.

The HEAD step is best-effort: servers that don't send `ETag` or `Last-Modified` simply fall through to the SHA-256 path with no extra round-trips.

## Commands

The bundled helper (`scripts/skill_hub.py`) speaks one verb per subcommand. Run it from anywhere; paths are absolute, no CWD assumptions.

```bash
# 1. Register + download
python3 scripts/skill_hub.py add [<name>] <tarball-url>

# 2. Install to a target (default: symlink; --copy to duplicate)
python3 scripts/skill_hub.py install <name> <target-path>
python3 scripts/skill_hub.py install <name> <target-path> --copy

# 3. Update everything (or one skill)
python3 scripts/skill_hub.py update              # all registered skills
python3 scripts/skill_hub.py update <name>       # one skill

# 4. Inspect
python3 scripts/skill_hub.py list
python3 scripts/skill_hub.py status <name>       # installed vs latest, install points

# 5. Remove an install (does not delete the store entry)
python3 scripts/skill_hub.py uninstall <name> <target-path>

# 6. Drop a skill from the registry (requires all install points uninstalled first)
python3 scripts/skill_hub.py remove <name>
python3 scripts/skill_hub.py remove <name> --purge   # also delete the store copy
```

Exit codes: `0` success, `1` input/argument/registry error, `2` I/O error (network, extract, link).

## Removing skills (`remove` vs `uninstall`)

Two verbs, two different scopes — do not mix them up:

| Verb | Touches | Store | Registry entry |
|---|---|---|---|
| `uninstall <name> <target>` | one install point only | kept | kept (install list shrinks) |
| `remove <name>` | registry slot | kept | **deleted** |
| `remove <name> --purge` | registry slot + store | **deleted** | **deleted** |

Safety gate: `remove` **refuses** (exit code 1) while any install point still references the skill, and the error lists every target path. The correct order is:

```bash
python3 scripts/skill_hub.py uninstall <name> <target-1>
python3 scripts/skill_hub.py uninstall <name> <target-2>
python3 scripts/skill_hub.py remove <name> --purge
```

`remove` never touches install points itself — a `remove` that silently left stale install entries would be unrecoverable once the registry slot is gone.

Bundle-awareness: removing one child prunes that name from its parent bundle's `skills[]`. When the last child is removed, the bundle record is dropped too. Siblings are never affected.

## Registry schema migration

The registry carries `schema_version`. `load_registry()` upgrades older registries **in memory** through an ordered `MIGRATIONS` table and rewrites the file only when the next write verb runs (`add`/`install`/`uninstall`/`update`/`remove`). Read-only verbs load quietly — no migration notice on `list`/`status`.

| From → To | What changes |
|---|---|
| `1 → 2` | add `bundles` map; backfill `source_bundle=null`, `etag=null`, `last_modified=null` on every skill (first `update` after migration falls through to the SHA-256 path once) |

Failure modes are explicit, never silent:

- registry `schema_version` **newer** than this build → exit 1, "upgrade skill-hub first" (no downgrade).
- no migration path for the current version → exit 1, telling the user to hand-edit the registry.
- top-level JSON is not an object, or `schema_version` is not an int → exit 1 (corrupt registry).

## Workflow

1. **Locate the helper.** Resolve `scripts/skill_hub.py` relative to this skill folder (or to wherever the user installed the skill-hub skill).
2. **Ask for a URL** if the user has not provided one. The skill does not search.
3. **Run `add`**. Omit `<name>` whenever possible — the helper will read the skill's own `SKILL.md` or fall back to the URL basename. If `add` prints "added 'alpha' (from bundle) …", the URL was a bundle and multiple skills were registered at once.
4. **Confirm** with `list` or `status <name>` (shows URL, installed version, latest version, install points).
5. **Run `install`** for each target the user wants. Default is `link` — point multiple targets (different agents, projects) at the same store entry without duplicating files. Use `--copy` when the target cannot host a symlink (e.g. some synced/remote filesystems, sandboxed locations).
6. **Update**: when the user says "update skills" or "refresh skill X", run `update`. The helper tries HEAD first; if HEAD confirms the remote is unchanged, no download happens. If HEAD is missing or differs, it downloads the tarball and compares SHA-256, then refreshes every install point.
7. **Uninstall** when a target is no longer needed; the store entry stays so the skill can be re-installed without re-downloading.
8. **Remove** when the skill should disappear from the registry. If it still has install points, the helper refuses and lists them — uninstall those first, then re-run `remove` (add `--purge` to also delete the store copy).
9. **Report** any non-zero exit code back to the user with the helper's stderr.

## Safety / boundaries

- The helper **never deletes a store entry implicitly**: `remove` leaves the store untouched unless `--purge` is passed, and `uninstall` never touches the store at all.
- The helper **never deletes the registry entry** while install points still exist; the gate is hard (exit 1), not a warning.
- The helper **never overwrites a non-empty target** that is not a symlink or directory of the same skill. It will fail rather than wipe an unrelated directory.
- **Name collisions** are explicit errors: `add foo <url>` fails with exit code 1 if `foo` is already registered, with the original source URL in the error message. Bundles never auto-namespace — if a bundle contains a child whose `SKILL.md` name already exists in the registry, the whole `add` fails and no skill is registered.
- `link` mode: removing the symlink does **not** affect the store; re-installing recreates it.
- `copy` mode: the target is a true duplicate; updates replace its contents.
- Network access is required only for `add` and `update` (and `status` when HEAD fails); `list`, `status` (with HEAD hit), `install`, `uninstall` are fully offline once the store is populated.

## Reference Files

| File | Purpose |
|---|---|
| `references/quick-reference.md` | Copy-paste cheat sheet for the seven subcommands, with typical one-liners and the registry schema. |
| `scripts/skill_hub.py` | Pure-stdlib Python helper (~28 KB). Single file, no install, no dependencies. |
