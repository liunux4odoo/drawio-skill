# Agent aliases

Reference table behind `install <name> --agent <alias>` / `@<alias>`.
Paths verified against vendor docs on 2026-10-20; source per row at the bottom.

## Resolution rules

1. **Env-pinned first.** If a candidate's `${VAR}` is actually set, the user has
   declared that agent's config root. That candidate is authoritative: if its
   `skills/` dir is missing, install fails and asks for `--create`. It never
   falls back to the default path, because the agent (started with that env var)
   would not read the default path either.
2. **Otherwise first existing wins.** Candidates are tried in declared order, so
   project scope (`{cwd}/...`) beats user scope when the project dir exists.
3. If nothing exists: exit 1 with the candidate list; `--create` creates the
   winning candidate.

`agents list` prints every candidate with `[OK]` / `[missing]` /
`[skip: 环境变量未设置]`, and tags env-pinned rows `[env-pinned]`.

## Table

| Alias | Agent | Candidate paths (priority order) | Mode |
|---|---|---|---|
| `qwenpaw` | QwenPaw | `${QWENPAW_WORKING_DIR}/skill_pool`, `~/.qwenpaw/skill_pool`, then workspace-local `…/workspaces/${QWENPAW_AGENT_ID}/skills` | **copy** |
| `claude` | Claude Code | `{cwd}/.claude/skills`, `${CLAUDE_CONFIG_DIR}/skills`, `~/.claude/skills` | link |
| `codex` | Codex CLI | `{cwd}/.agents/skills`, `{cwd}/.codex/skills`, `${CODEX_HOME}/skills`, `~/.agents/skills`, `~/.codex/skills`, `/etc/codex/skills` | link |
| `gemini` | Gemini CLI | `{cwd}/.gemini/skills`, `{cwd}/.agents/skills`, `${GEMINI_CLI_HOME}/.gemini/skills`, `~/.gemini/skills`, `~/.agents/skills` | link |
| `opencode` | OpenCode | `{cwd}/.opencode/skills`, `{cwd}/.claude/skills`, `{cwd}/.agents/skills`, `~/.config/opencode/skills`, `~/.claude/skills`, `~/.agents/skills` | link |
| `cursor` | Cursor | `{cwd}/.cursor/skills`, `{cwd}/.agents/skills`, `{cwd}/.claude/skills`, `{cwd}/.codex/skills`, `~/.cursor/skills`, `~/.agents/skills`, `~/.claude/skills`, `~/.codex/skills` | link |
| `copilot` | GitHub Copilot | `{cwd}/.github/skills`, `{cwd}/.claude/skills`, `{cwd}/.agents/skills`, `${COPILOT_HOME}/skills`, `~/.copilot/skills`, `~/.agents/skills` | link |
| `qwen-code` | Qwen Code (阿里) | `{cwd}/.qwen/skills`, `${QWEN_HOME}/skills`, `~/.qwen/skills` | link |
| `codebuddy` | CodeBuddy (腾讯) | `{cwd}/.codebuddy/skills`, `${CODEBUDDY_CONFIG_DIR}/skills`, `~/.codebuddy/skills` | link |
| `iflow` | iFlow CLI (心流) | `{cwd}/.iflow/skills`, `~/.iflow/skills` | link |
| `qoder` | Qoder (阿里) | `{cwd}/.qoder/skills`, `~/.qoder/skills` | link |
| `trae` | Trae (字节) | `{cwd}/.trae/skills`, `~/.trae/skills` | link |

Template syntax: `{cwd}` = current dir, `${VAR}` = env, `${VAR:-default}` = env
with fallback, `~` = home. A var with no value and no default makes that
candidate **skip** (not fail).

Modes: `link` everywhere except `qwenpaw`, whose pool is manifest-managed
(`skill.json`) and can desync if symlinked. `--link` / `--copy` on `install`
always override the alias mode.

## Env-configurable roots

| Env var | Agent | Skills dir becomes |
|---|---|---|
| `CLAUDE_CONFIG_DIR` | Claude Code | `$VAR/skills` |
| `CODEX_HOME` | Codex CLI | `$VAR/skills` (default root `~/.codex`) |
| `GEMINI_CLI_HOME` | Gemini CLI | `$VAR/.gemini/skills` (var is the **root**; CLI creates `.gemini/` inside) |
| `QWEN_HOME` | Qwen Code | `$VAR/skills` (default `~/.qwen`; docs list skills among stored state) |
| `CODEBUDDY_CONFIG_DIR` | CodeBuddy | `$VAR/skills` (default `~/.codebuddy`) |
| `COPILOT_HOME` | GitHub Copilot CLI | `$VAR/skills` (default `~/.copilot`) |
| `QWENPAW_WORKING_DIR` | QwenPaw | `$VAR/skill_pool` (default `~/.qwenpaw`) |

Deliberately **not** install roots:

- `OPENCODE_CONFIG_DIR` — OpenCode documents it as searched for agents, commands,
  modes and plugins "just like `.opencode`", but never states that `skills/`
  inside it is discovered. Installing there could land outside discovery.
- `COPILOT_SKILLS_DIRS` — comma-separated list of **extra search paths**, not
  the personal skills dir.
- Cursor / Qoder / Trae — GUI products, no documented env override.

## Managing aliases

Built-ins live in the script (`DEFAULT_AGENTS`); edits live in
`registry.json["agents"]`, so upgrading skill-hub still ships new built-ins.

```bash
python3 $HUB agents list                                  # candidates + status
python3 $HUB agents add myagent ~/skills/mine             # new alias (mode=link)
python3 $HUB agents add claude ~/alt/claude-skills --mode copy   # override built-in
python3 $HUB agents remove trae                           # builtin → tombstone
python3 $HUB agents reset trae                            # drop one override
python3 $HUB agents reset                                 # drop all overrides
```

`agents add` **replaces** the alias's path list (not append) — re-run it to
reorder priority. Adding a tombstoned alias revives it.

Agents with no Agent Skills directory (rules-file-only tools) are intentionally
absent — there is nothing to point at.

## Sources

- QwenPaw: local `docs/config.en.md` → Directory Structure (`skill_pool/`, `workspaces/{agent}/skills/`)
- Claude Code: `code.claude.com/docs/en/skills`, `code.claude.com/docs/en/env-vars`
- Codex CLI: `developers.openai.com/codex/skills`; `CODEX_HOME` documented as the state root
- Gemini CLI: `geminicli.com/docs/cli/skills`; `geminicli.com/docs/reference/configuration`
- OpenCode: `opencode.ai/docs/skills`, `opencode.ai/docs/config`
- Cursor: `cursor.com/docs/skills`
- GitHub Copilot: `docs.github.com/en/copilot/concepts/agents/about-agent-skills`; CLI config-dir reference
- Qwen Code: QwenLM/qwen-code `docs/users/features/skills.md`; settings page (`QWEN_HOME`)
- CodeBuddy: `cloud.tencent.com/document/product/1831/137020`; CLI installation guide (`CODEBUDDY_CONFIG_DIR`)
- iFlow: `platform.iflow.cn/en/docs/skill`
- Qoder: `docs.qoder.com/extensions/skills`
- Trae: `docs.trae.ai/ide/skills`
