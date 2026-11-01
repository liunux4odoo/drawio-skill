---
name: reme-memory
description: Query QwenPaw agents' accumulated experience and memory, and write project/agent memory notes into ReMe vaults. Use when the task needs historical decisions, lessons learned, domain notes, or personal preferences recorded by any QwenPaw agent (e.g. a travel assistant, developer, QA helper), or when you want to persist a durable note into an agent's workspace memory or a project-level memory vault (<project>/.qwenpaw). First locate the right agent with scripts/reme_agents.py, then search its memory with scripts/reme_search.py --agent <id> "<query>" (or --project <dir> for a project vault). Writes go through scripts/reme_write.py, which uses a writable ReMe instance so frontmatter/atomic-write/indexing match QwenPaw's own memory writer.
---

# QwenPaw Agent Memory Query & Write

You bridge into **QwenPaw** (the local open-source agent framework) to consult or update the experience stored by its agents and projects. Each QwenPaw agent keeps an isolated memory: `MEMORY.md`, daily notes under `memory/YYYY-MM-DD*.md`, topic notes under `memory/YYYY-MM-DD/<topic>.md`, plus a ReMe index (`mem_metadata/`) built by QwenPaw itself.

A **project** may also have its own L3 memory vault at `<project>/.qwenpaw/` (memory/, digest/, mem_metadata/...) that multiple agents can share. The same scripts handle both targets.

Memory is **per-agent or per-project**. Always resolve which target you mean before searching or writing.

## When to use

- **Search**: a task needs historical decisions, lessons learned, domain knowledge, or user preferences that may have been recorded by a QwenPaw agent, or by a project vault.
- **Write**: the user explicitly asks to record a durable note ("记下来/更新项目记忆/保存这个结论"), or a project task produces a canonical fact worth persisting to the project vault.

## Workflow — Search

1. **Locate the agent** (if not already known):
   ```bash
   python3 scripts/reme_agents.py                 # list all agents + memory size
   python3 scripts/reme_agents.py <keyword>       # find by id/name/description
   ```
   Choose the agent whose domain matches the query. If several match, prefer the one with larger memory, or ask the user.

2. **Search that agent's memory**:
   ```bash
   python3 scripts/reme_search.py --agent <agent_id> "<query>"
   ```
   Or search a **project L3 vault**:
   ```bash
   python3 scripts/reme_search.py --project <project_dir> "<query>"
   ```
   Examples:
   ```bash
   python3 scripts/reme_search.py --agent travel-assistant "签证材料清单"
   python3 scripts/reme_search.py --agent small_reactor "标准规范检索"
   python3 scripts/reme_search.py --project /path/to/proj "部署流程"
   ```

3. **Interpret the result**. Output is ReMe's own retrieval (BM25 keyword + vector RRF fusion — identical logic to QwenPaw's `memory_search`), with entries like:
   ```
   ========== memory/2026-10-09/qwenpaw-workbuddy-interop.md:14-90 [score=5.2706] ==========
   ```
   The path and line range let you open the source file for full context if needed.

## Workflow — Write

Use **scripts/reme_write.py** to persist a note with ReMe-quality writing (frontmatter + atomic write + ingest + reindex). Two targets:

```bash
# Write into an agent's workspace memory (L2)
python3 scripts/reme_write.py --agent <agent_id> \
    --name <frontmatter name> --description <summary> \
    --content "<markdown body>" [--path memory/notes/<topic>.md]

# Write into a project L3 vault (<project>/.qwenpaw/)  ← shared by agents
python3 scripts/reme_write.py --project <project_dir> \
    --name <frontmatter name> --description <summary> \
    --content "<markdown body>" [--path memory/notes/<topic>.md]
```

- `--path` defaults to `memory/notes/note.md`; the write workflow does **not** create daily notes or the `memory/YYYY-MM-DD.md` index page (that's `daily_write`'s job; we use plain `write`). Use theme files under `memory/notes/<topic>.md` (or any vault-relative path) instead.
- The script writes, ingests the new file, and reindexes automatically (BM25 + vector if embedding is configured). Use `--no-index` to skip ingest/reindex for pure recording.
- For `--project`, embedding is off by default (pure BM25); pass `--embedding-config <json>` to enable vector search on that vault.
- **Conventions**: project vaults live at `<project>/.qwenpaw/`; keep canonical project facts there (shared), and personal observations in your own agent workspace.
- If the user wants non-QwenPaw tools/agents to discover a project vault, append the snippet in `references/project-agents-md-template.md` to the **project root** `AGENTS.md` (only when the user asks — do not write it by default).

## Scripts

| Script | Purpose |
|---|---|
| `scripts/reme_agents.py` | List/find QwenPaw agents (id, name, description, memory size). `--json` for machine-readable output, `--root` to override workspaces root. |
| `scripts/reme_search.py` | Search a ReMe memory index. `--agent <id>` or `--project <dir>` (required); `--root` overrides workspaces root; `--limit N` caps results. Read-only. |
| `scripts/reme_write.py` | Write a note into an agent workspace (`--agent`) or project vault (`--project`). Writable ReMe instance: frontmatter, atomic write, ingest, reindex. `--no-index` skips indexing. |

## Constraints & notes

- **Read is zero-write**: `reme_search.py` opens the ReMe index read-only and never starts the `index_update_loop` background job — safe to run while QwenPaw is active. It only uses the `reme` Python package (no `qwenpaw` import), so cold start is ~1–2s.
- **Write is explicit**: `reme_write.py` constructs a writable ReMe instance but still has no background write jobs — it writes, ingests, reindexes, then exits. Use it deliberately, not in a loop.
- **Python environment**: the scripts need the QwenPaw runtime's Python (where `reme-ai` is installed), e.g. `/data/apps/miniforge3/envs/py312/bin/python`. Use that interpreter or a venv containing `reme-ai`.
- **Index freshness**: search results come from the persisted ReMe index. Writes you just made are indexed immediately; QwenPaw's own background index may lag on other files — acceptable for experience/advice queries.
- **Agent id vs workspace dir**: `--agent` accepts the agent id (e.g. `travel-assistant`) or the workspace directory name. The script resolves it under the workspaces root.
- **Privacy**: output may include personal notes. Do not paste memory contents into channels that should not see them.
