# Registry & storage

## Locations

| Path | Role |
|---|---|
| `~/.config/skill-hub/registry.json` | URLs, versions (sha256), ETag/Last-Modified hints, install points, bundle map, alias overrides |
| `~/.local/share/skill-hub/skills/<name>/` | Extracted source, one dir per skill |
| `<target>/<name>` | Install point: symlink to the store, or a copy |

Override with `SKILL_HUB_HOME` / `SKILL_HUB_DATA`.

## link vs copy

- **link (default)**: no extra space, updates propagate automatically. Use for
  local filesystems and normal agent skill folders.
- **copy**: independent duplicate; costs space and needs a re-copy on update.
  Use when the target rejects symlinks (synced/remote filesystems, sandboxes,
  read-only mounts).

## Verify an install

```bash
readlink <target>                                                       # link mode
diff -r ~/.local/share/skill-hub/skills/<name>/ <target>/               # copy mode
```

## Schema (v3)

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
    "<alias>": {"paths": ["{cwd}/.foo/skills", "~/.foo/skills"], "mode": "link", "label": "My Agent"},
    "<disabled-builtin>": {"deleted": true}
  }
}
```

Notes:

- `etag` / `last_modified` are optional HEAD cache hints (absent when the server
  sends none, which just forces the SHA-256 path).
- `source_bundle` is non-null only for skills registered through a bundle URL.
- `agent` appears only on install points created via `--agent`.
- `agents` holds **overrides only**; built-ins live in `DEFAULT_AGENTS` in the
  script. `{"deleted": true}` hides a built-in; `agents reset <alias>` removes it.
- The file is hand-editable but always rewritten by the next write verb.

## Migration

`schema_version` is checked on every load. Older files are upgraded **in memory**
and persisted by the next write verb; read-only verbs (`list`, `status`) stay
quiet.

| From → To | Change |
|---|---|
| `1 → 2` | add `bundles`; backfill `source_bundle=null`, `etag=null`, `last_modified=null` |
| `2 → 3` | add the empty `agents` override map |

| Edge case | Behavior |
|---|---|
| registry newer than the tool | exit 1 — upgrade skill-hub (no downgrade) |
| no migration path | exit 1 — hand-edit `registry.json` |
| top-level JSON not an object, or non-int `schema_version` | exit 1 (corrupt registry) |
