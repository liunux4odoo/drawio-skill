# Skill Hub — Quick Reference

Minimal install/maintain for skills from user-specified tarball URLs.

## Six verbs

| Verb | Purpose | Online? |
|---|---|---|
| `add <name> <url>` | Download + extract + register | yes |
| `install <name> <target>` | Symlink target to store (use `--copy` to duplicate) | no |
| `update [name]` | Re-download, refresh store, re-link/copy all installs | yes |
| `list` | Show every registered skill + its install points | no |
| `status <name>` | Show installed version, latest version, all install points | yes (fetches once) |
| `uninstall <name> <target>` | Remove an install point (store stays) | no |

Exit codes: `0` ok, `1` argument/registry error, `2` I/O (network/extract/link).

## Typical one-liners

```bash
# Fresh install
HUB=~/.local/share/work-skills/skills/skill-hub/scripts/skill_hub.py

python3 $HUB add quarkdown https://example.com/skills/quarkdown-1.2.0.tar.gz
python3 $HUB install quarkdown /data/myrepo/work-skills/skills/quarkdown
python3 $HUB install quarkdown ~/.config/qwenpaw/agents/dev/skills/quarkdown --copy

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
| `~/.config/skill-hub/registry.json` | URLs, versions (sha256), install targets |
| `~/.local/share/skill-hub/skills/<name>/` | Extracted source per skill |

Override `XDG_CONFIG_HOME` / `XDG_DATA_HOME` to relocate.

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
  "schema_version": 1,
  "skills": {
    "<name>": {
      "url": "https://...",
      "version": "<sha256 of downloaded tarball>",
      "installed_at": "2026-10-20T10:00:00+00:00"
    }
  },
  "installs": {
    "<name>": [
      {"target": "/abs/path/...", "mode": "link"},
      {"target": "/abs/path/...", "mode": "copy"}
    ]
  }
}
```

The file is human-editable; preserve JSON formatting and the `schema_version` field. Re-running any verb will rewrite it.
