# Skill Hub — Quick Reference

Minimal install/maintain for skills from user-specified tarball URLs.

## Verbs

| Verb | Purpose | Online? |
|---|---|---|
| `add [<name>] <url>` | Download + extract + register (1 skill, or N if URL is a bundle) | yes |
| `install <name> <target>` | Symlink target to store (use `--copy` to duplicate) | no |
| `install <name> --agent <alias>` | Install into the alias's first existing skills dir (alias mode applies) | no |
| `update [name]` | HEAD check; on mismatch, GET + SHA-256 compare; refresh all installs | yes (HEAD first, GET only if needed) |
| `list` | Show every registered skill + its install points | no |
| `status <name>` | Show installed version, latest version, all install points | yes (HEAD first, GET only if needed) |
| `uninstall <name> <target>` | Remove an install point (store stays) | no |
| `remove <name> [--purge]` | Drop the registry entry (`--purge` also deletes the store) | no |
| `agents list` / `add` / `remove` / `reset` | Manage the agent alias table | no |

Exit codes: `0` ok, `1` argument/registry error, `2` I/O (network/extract/link).

## URL forms

`add` auto-detects between two URL shapes:

- **Single skill**: `.../my-skill.tar.gz` → 1 entry in the registry
- **Bundle**: `.../skills-bundle.tar.gz` whose top-level layout is `skills/<child>/SKILL.md` → N entries (one per child), all sharing the same parent URL

To register a bundle, pass the URL **without** an explicit `<name>`:

```bash
python3 $HUB add https://example.com/bundle.tar.gz   # bundle: N skills
python3 $HUB add my-skill https://example.com/skill.tar.gz   # single
```

## Name inference (when `<name>` is omitted)

1. Read `SKILL.md` frontmatter's `name:` field (most accurate)
2. Fallback: URL basename with archive extension + `-skill`/`_skill` suffix stripped
3. Error: neither yields a name → exit code 1

## Update flow

```
HEAD <url>
  ├─ ETag / Last-Modified matches stored value → up-to-date (no download)
  └─ mismatch or no metadata → GET + SHA-256 compare
                                  ├─ SHA-256 matches → up-to-date (just stamp installed_at)
                                  └─ differs → replace store + re-link/re-copy
```

## Typical one-liners

```bash
HUB=~/.local/share/work-skills/skills/skill-hub/scripts/skill_hub.py

# Fresh single-skill install
python3 $HUB add quarkdown https://example.com/skills/quarkdown-1.2.0.tar.gz
python3 $HUB install quarkdown /data/myrepo/work-skills/skills/quarkdown
python3 $HUB install quarkdown ~/.config/qwenpaw/agents/dev/skills/quarkdown --copy

# Bundle install (e.g. 5-skill pack)
python3 $HUB add https://example.com/wps-bundle.tar.gz
python3 $HUB list                       # see the 5 skills that were registered
python3 $HUB install wps-office ~/.config/qwenpaw/agents/dev/skills/wps-office

# Mirror the same skill into a second agent
python3 $HUB install quarkdown ~/.config/qwenpaw/agents/research/skills/quarkdown

# Update all registered skills
python3 $HUB update

# Update one
python3 $HUB update quarkdown

# Inspect
python3 $HUB list
python3 $HUB status quarkdown   # shows NEEDS UPDATE / up-to-date

# Remove a copy (store unaffected)
python3 $HUB uninstall quarkdown ~/.config/qwenpaw/agents/research/skills/quarkdown

# Drop a skill from the registry (all install points must be gone first)
python3 $HUB uninstall quarkdown /data/myrepo/work-skills/skills/quarkdown
python3 $HUB uninstall quarkdown ~/.config/qwenpaw/agents/dev/skills/quarkdown
python3 $HUB remove quarkdown            # registry entry gone, store kept
python3 $HUB remove quarkdown --purge    # store deleted too
```

## Agent aliases — built-in table

`install … --agent <alias>` (or `@alias`) picks the **first existing** candidate in order.

| Alias | Candidates (priority order) | Mode |
|---|---|---|
| `qwenpaw` | `${QWENPAW_WORKING_DIR}/skill_pool` → `~/.qwenpaw/skill_pool` → `…/workspaces/${QWENPAW_AGENT_ID}/skills` | copy |
| `claude` | `{cwd}/.claude/skills` → `~/.claude/skills` | link |
| `codex` | `{cwd}/.agents/skills` → `{cwd}/.codex/skills` → `~/.agents/skills` → `~/.codex/skills` → `/etc/codex/skills` | link |
| `gemini` | `{cwd}/.gemini/skills` → `{cwd}/.agents/skills` → `~/.gemini/skills` → `~/.agents/skills` | link |
| `opencode` | `{cwd}/.opencode/skills` → `{cwd}/.claude/skills` → `{cwd}/.agents/skills` → `~/.config/opencode/skills` → `~/.claude/skills` → `~/.agents/skills` | link |
| `cursor` | `{cwd}/.cursor/skills` → `{cwd}/.agents/skills` → `{cwd}/.claude/skills` → `{cwd}/.codex/skills` → `~/.cursor/skills` → `~/.agents/skills` → `~/.claude/skills` → `~/.codex/skills` | link |
| `copilot` | `{cwd}/.github/skills` → `{cwd}/.claude/skills` → `{cwd}/.agents/skills` → `~/.copilot/skills` → `~/.agents/skills` | link |
| `qwen-code` | `{cwd}/.qwen/skills` → `~/.qwen/skills` | link |
| `codebuddy` | `{cwd}/.codebuddy/skills` → `~/.codebuddy/skills` | link |
| `iflow` | `{cwd}/.iflow/skills` → `~/.iflow/skills` | link |
| `qoder` | `{cwd}/.qoder/skills` → `~/.qoder/skills` | link |
| `trae` | `{cwd}/.trae/skills` → `~/.trae/skills` | link |

Templates: `{cwd}` = current dir, `${VAR}` = env, `${VAR:-default}` = env with fallback, `~` = home. An unresolved var without default ⇒ that candidate is **skipped**.

Modes: link everywhere except `qwenpaw` (copy — manifest-managed pool). `--link` / `--copy` on `install` override the alias mode.

```bash
# Resolve and install
python3 $HUB install docx --agent claude
python3 $HUB install docx @cursor --copy        # force copy into ~/.cursor/skills
python3 $HUB install docx --agent claude --create   # create candidate #1 if none exists

# Inspect resolved paths ([OK]/[missing]/[skip: …])
python3 $HUB agents list

# Custom / override / delete / restore
python3 $HUB agents add desktop ~/skills/desktop --mode link --label "My Desktop"
python3 $HUB agents add claude ~/alt/claude-skills        # replaces built-in paths
python3 $HUB agents remove trae                           # builtin: tombstone
python3 $HUB agents reset trae                            # restore built-in
python3 $HUB agents reset                                 # clear ALL overrides
```

Precedence rule of thumb: project-scoped candidates (`{cwd}/...`) win only when they exist; otherwise the user-global candidate is used. If neither exists, nothing is created without `--create`.

## `remove` vs `uninstall` — scope table

| Verb | Install points | Store | Registry entry |
|---|---|---|---|
| `uninstall` | one target removed | kept | kept |
| `remove` | untouched (must already be empty) | kept | deleted |
| `remove --purge` | untouched (must already be empty) | deleted | deleted |

`remove` **fails with exit 1** while any install point exists, printing every target path:

```
skill-hub: skill 'quarkdown' 还有 install 点未清理：/a/skills/quarkdown, /b/skills/quarkdown。
先逐个 `uninstall 'quarkdown' <target>` 再 `remove`
```

Bundle children: removing one child prunes it from `bundles[<parent-url>].skills`; the bundle entry disappears when its last child is removed. Siblings unaffected.

## Registry schema migration

`schema_version` is checked on every load. Older registries are upgraded **in memory**; the file is only rewritten by the next write verb. Read-only verbs (`list`, `status`) load quietly and print no notice.

| Edge case | Behavior |
|---|---|
| registry older than tool | auto-migrate `1 → 2 → 3` (adds `bundles`, backfills `source_bundle`/`etag`/`last_modified`, then adds the empty `agents` override map); notice on stderr at the next write |
| registry newer than tool | exit 1 — upgrade skill-hub, no downgrade |
| no migration path | exit 1 — hand-edit `registry.json` |
| top-level JSON not an object, or non-int `schema_version` | exit 1 (corrupt registry) |

## Storage locations

| Path | Role |
|---|---|
| `~/.config/skill-hub/registry.json` | URLs, versions (sha256), ETag/Last-Modified hints, install targets, bundle map |
| `~/.local/share/skill-hub/skills/<name>/` | Extracted source per skill |

Override `SKILL_HUB_HOME` / `SKILL_HUB_DATA` to relocate.

## link vs copy — when to use which

- **link (default)**: zero extra space, source updates propagate automatically. Use when the target directory can host symlinks (local filesystems, most agent skill folders).
- **copy**: true duplicate, immune to source changes, costs disk space and needs explicit re-copy on update. Use when the target rejects symlinks (some remote/synced filesystems, sandboxed locations, read-only mounts).

## Verifying the install worked

After `install`, the target should contain the same `SKILL.md` as the store:

```bash
diff ~/.local/share/skill-hub/skills/<name>/SKILL.md <target>/SKILL.md   # link mode: equal
diff -r ~/.local/share/skill-hub/skills/<name>/ <target>/                # copy mode: equal
readlink <target>                                                        # link mode: → store path
```

## Registry schema (for inspection / hand-edit)

```json
{
  "schema_version": 3,
  "skills": {
    "<name>": {
      "url": "https://...",
      "version": "<sha256 of downloaded tarball>",
      "installed_at": "2026-10-20T10:00:00+00:00",
      "source_bundle": "<parent-url>" | null,
      "etag": "<from HEAD response>" | null,
      "last_modified": "<from HEAD response>" | null
    }
  },
  "installs": {
    "<name>": [
      {"target": "/abs/path/...", "mode": "link", "agent": "claude"},
      {"target": "/abs/path/...", "mode": "copy"}
    ]
  },
  "bundles": {
    "<parent-url>": {
      "url": "https://...",
      "version": "<sha256>",
      "skills": ["alpha", "beta", "..."],
      "installed_at": "2026-10-20T10:00:00+00:00"
    }
  },
  "agents": {
    "<alias>": {
      "paths": ["{cwd}/.foo/skills", "~/.foo/skills"],
      "mode": "link",
      "label": "My Agent"
    },
    "<disabled-builtin>": {"deleted": true}
  }
}
```

The file is human-editable; preserve JSON formatting and the `schema_version` field. Re-running any verb will rewrite it. `etag` and `last_modified` are optional (omitted when the server doesn't send them); `source_bundle` is non-null only for skills registered via a bundle URL; `agent` is present only on installs made through an alias.

`agents` holds **overrides only** — built-in aliases live in the script (`DEFAULT_AGENTS`), so a new skill-hub release can add aliases without touching your registry. `{"deleted": true}` is a tombstone that hides a built-in; `agents reset <alias>` removes the key.
