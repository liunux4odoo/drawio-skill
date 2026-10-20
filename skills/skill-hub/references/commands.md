# Command reference

Every verb of `scripts/skill_hub.py`. Stored-state details are in
`registry.md`; agent aliases are in `agents.md`.

## Verbs

| Verb | Purpose | Online? |
|---|---|---|
| `add [<name>] <url>` | Download + extract + register (1 skill, or N for a bundle) | yes |
| `install <name> <target>` | Symlink target to store (use `--copy` to duplicate) | no |
| `install <name> --agent <alias>` | Install into the alias's resolved skills dir (alias mode applies) | no |
| `update [name]` | HEAD check; on mismatch GET + SHA-256 compare; refresh all installs | HEAD first, GET only if needed |
| `list` | Every registered skill + its install points | no |
| `status <name>` | Installed version, latest version, install points | HEAD first, GET only if needed |
| `uninstall <name> <target>` | Remove one install point (store kept) | no |
| `remove <name> [--purge]` | Drop the registry entry (`--purge` also deletes the store) | no |
| `agents list` / `add` / `remove` / `reset` | Manage the agent alias table | no |

Exit codes: `0` ok, `1` argument/registry error, `2` I/O (network/extract/link).

## `install` flags

| Flag | Effect |
|---|---|
| `--copy` | Copy instead of symlink |
| `--link` | Force symlink (overrides an alias's copy default) |
| `--agent <alias>` | Resolve the target dir from the alias table |
| `@<alias>` | Sugar for `--agent <alias>` (used in the target position) |
| `--create` | Create the winning candidate dir if it does not exist |

## URL forms

`add` auto-detects two shapes:

- **Single skill**: `.../my-skill.tar.gz` → 1 registry entry
- **Bundle**: archive whose top level is `skills/<child>/SKILL.md` → N entries,
  all sharing the parent URL and a `bundles[<url>]` record

Pass the URL **without** `<name>` for a bundle (a name there is an error):

```bash
python3 $HUB add https://example.com/bundle.tar.gz          # bundle: N skills
python3 $HUB add my-skill https://example.com/skill.tar.gz  # single
```

## Name inference (when `<name>` is omitted)

1. `SKILL.md` frontmatter `name:` field
2. URL basename minus archive extension and a trailing `-skill` / `_skill`
3. Neither → exit 1

## Update flow

```
HEAD <url>
  ├─ ETag / Last-Modified matches stored value → up-to-date (no download)
  └─ mismatch or no metadata → GET + SHA-256 compare
                                  ├─ matches → up-to-date (only installed_at is stamped)
                                  └─ differs → replace store + re-link/re-copy every install
```

## `uninstall` vs `remove`

| Verb | Install points | Store | Registry entry |
|---|---|---|---|
| `uninstall` | one target removed | kept | kept |
| `remove` | untouched (must already be empty) | kept | deleted |
| `remove --purge` | untouched (must already be empty) | deleted | deleted |

`remove` exits 1 while any install point exists and prints every target:

```
skill-hub: skill 'quarkdown' 还有 install 点未清理：/a/skills/quarkdown, /b/skills/quarkdown。
先逐个 `uninstall 'quarkdown' <target>` 再 `remove`
```

Bundle children: `remove` prunes the name from `bundles[<url>].skills`; the bundle
record disappears with its last child. Siblings are never touched.

## One-liners

```bash
HUB=scripts/skill_hub.py

# Single skill, installed into an agent
python3 $HUB add https://example.com/quarkdown-1.2.0.tar.gz
python3 $HUB install quarkdown --agent claude

# Bundle → pick the members the user wants
python3 $HUB add https://example.com/wps-bundle.tar.gz
python3 $HUB list
python3 $HUB install wps-office --agent qwenpaw

# Copy into a target that cannot hold symlinks
python3 $HUB install quarkdown /mnt/shared/skills/quarkdown --copy

# Update / inspect
python3 $HUB update
python3 $HUB update quarkdown
python3 $HUB status quarkdown        # up-to-date / NEEDS UPDATE

# Remove an install point, then the registry entry
python3 $HUB uninstall quarkdown /mnt/shared/skills/quarkdown
python3 $HUB remove quarkdown --purge
```
