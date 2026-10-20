# Skill Hub — Quick Reference

Minimal install/maintain for skills from user-specified tarball URLs.

## Six verbs

| Verb | Purpose | Online? |
|---|---|---|
| `add [<name>] <url>` | Download + extract + register (1 skill, or N if URL is a bundle) | yes |
| `install <name> <target>` | Symlink target to store (use `--copy` to duplicate) | no |
| `update [name]` | HEAD check; on mismatch, GET + SHA-256 compare; refresh all installs | yes (HEAD first, GET only if needed) |
| `list` | Show every registered skill + its install points | no |
| `status <name>` | Show installed version, latest version, all install points | yes (HEAD first, GET only if needed) |
| `uninstall <name> <target>` | Remove an install point (store stays) | no |

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

## Update flow (v0.2)

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
```

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
  "schema_version": 2,
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
      {"target": "/abs/path/...", "mode": "link"},
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
  }
}
```

The file is human-editable; preserve JSON formatting and the `schema_version` field. Re-running any verb will rewrite it. `etag` and `last_modified` are optional (omitted when the server doesn't send them); `source_bundle` is non-null only for skills registered via a bundle URL.
