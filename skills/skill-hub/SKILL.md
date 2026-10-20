---
name: skill-hub
description: Install and maintain skills from user-specified URLs (tarballs). Use when the user wants to add a skill or skill bundle from a URL, update installed skills (HTTP HEAD fast path), install/link/copy a registered skill into a directory or a known agent's default skills folder (qwenpaw, claude, codex, gemini, opencode, cursor, copilot, plus more), remove a skill, or inspect the skill registry. Does NOT search, discover, or recommend skills — only maintains a user-curated set.
---

# Skill Hub

A minimal install/maintain registry for skills. The user supplies the URL of each
skill's archive (`.tar.gz` / `.tgz` / `.zip`); the helper downloads it once into a
central store, then links or copies it to any number of targets — typically an
agent's `skills/` folder. `update` re-checks the URL and refreshes every install
point.

**Out of scope**: searching, browsing, rating, or recommending skills. If the user
wants a skill but gives no URL, ask for one — never invent a source.

## Model

| Path | Role |
|---|---|
| `~/.config/skill-hub/registry.json` | State: URLs, versions (sha256), install points, bundles, alias overrides |
| `~/.local/share/skill-hub/skills/<name>/` | Store: one extracted archive per skill |
| `<target>/<name>` | Install point: symlink to the store (**default**) or a copy |

One store entry feeds many install points. `link` keeps them in sync automatically;
`copy` is for targets that reject symlinks. `uninstall` drops one point, `remove`
drops the registry entry (the store survives unless `--purge`).

## Commands

```bash
HUB=scripts/skill_hub.py

python3 $HUB add [<name>] <url>            # register + download (URL may be a bundle)
python3 $HUB install <name> <target>       # link (default) | --copy
python3 $HUB install <name> --agent <alias> [--create]   # agent's skills dir
python3 $HUB update [<name>]               # HEAD → sha256 → refresh installs
python3 $HUB list                          # registry + install points
python3 $HUB status <name>                 # installed vs latest
python3 $HUB uninstall <name> <target>     # drop one install point
python3 $HUB remove <name> [--purge]       # drop registry entry (+ store)
python3 $HUB agents list|add|remove|reset  # alias table
```

`add` without `<name>` infers it from `SKILL.md` frontmatter, else the URL basename.
An archive whose top level is `skills/<child>/SKILL.md` is a bundle and registers one
entry per child — never pass a name for it.

Installing by agent: `--agent claude` (or `@claude`) walks that alias's candidate
paths and uses the first that exists; a set env root such as `CLAUDE_CONFIG_DIR` is
authoritative and never quietly falls back to `~/.claude/skills`. Alias table, env
vars, and path sources live in `references/agents.md`.

## Hard rules

- `remove` refuses (exit 1) while any install point references the skill, and lists
  the targets — `uninstall` those first. A dropped registry slot can no longer tell
  you which targets went stale.
- Nothing is deleted implicitly: `uninstall` never touches the store; `remove` needs
  `--purge` to delete it.
- Name collisions are errors, never auto-renames; bundles do not namespace.
- An install never overwrites a target that is neither a symlink nor a directory.
- An alias install never creates a directory unless `--create` is passed.
- A registry newer than this build is refused, not downgraded. Older ones migrate on
  load (`references/registry.md`).
- Report non-zero exits with the helper's stderr instead of retrying blindly.

## Workflow

1. Locate the helper (`scripts/skill_hub.py` in this skill folder).
2. Ask for a URL if missing — the skill does not search.
3. `add` (omit `<name>` when possible; a bundle registers several skills at once).
4. `install` per target: prefer `--agent <alias>` when the user names an agent rather
   than a path; use `--copy` only for targets that reject symlinks.
5. `update` on request; say "up-to-date" vs "updated" per skill.
6. `uninstall` then `remove` when deleting; confirm before `--purge`.

## Reference files

| File | Load when |
|---|---|
| `references/commands.md` | Full verb/flag list, URL forms, name inference, update-flow detail, one-liners |
| `references/agents.md` | Choosing or adding an agent alias, env-configurable roots, path sources |
| `references/registry.md` | Inspecting or hand-editing `registry.json`, schema migrations, link vs copy |
