---
name: qwenpaw
description: Query QwenPaw agents' accumulated experience and memory. Use when the user or current task needs historical decisions, lessons learned, domain notes, or personal preferences recorded by any QwenPaw agent (e.g. a travel assistant, developer, QA helper). First locate the right agent with scripts/qwenpaw_agents.py, then search its memory with scripts/qwenpaw_search.py --agent <id> "<query>". Results come straight from the agent's ReMe index (same retrieval as QwenPaw's memory_search), with file paths and line ranges for traceability.
---

# QwenPaw Agent Memory Query

You bridge into **QwenPaw** (the local open-source agent framework) to consult the experience stored by its agents. Each QwenPaw agent keeps an isolated memory: `MEMORY.md`, daily notes under `memory/YYYY-MM-DD*.md`, topic notes under `memory/YYYY-MM-DD/<topic>.md`, plus a ReMe index (`mem_metadata/`) built by QwenPaw itself.

Memory is **per-agent**. Always resolve which agent you mean before searching.

## When to use

- A task needs historical decisions, lessons learned, domain knowledge, or user preferences that may have been recorded by a QwenPaw agent.
- The user asks "what did X agent record about ..." or wants QwenPaw's accumulated experience on a topic.
- You need a second opinion grounded in long-term memory rather than current context.

## Workflow

1. **Locate the agent** (if not already known):
   ```bash
   python3 scripts/qwenpaw_agents.py                 # list all agents + memory size
   python3 scripts/qwenpaw_agents.py <keyword>       # find by id/name/description
   ```
   Choose the agent whose domain matches the query. If several match, prefer the one with larger memory, or ask the user.

2. **Search that agent's memory**:
   ```bash
   python3 scripts/qwenpaw_search.py --agent <agent_id> "<query>"
   ```
   Examples:
   ```bash
   python3 scripts/qwenpaw_search.py --agent travel-assistant "签证材料清单"
   python3 scripts/qwenpaw_search.py --agent small_reactor "标准规范检索"
   python3 scripts/qwenpaw_search.py --agent QwenPaw_QA_Agent_0.2 "workbuddy 互通"
   ```

3. **Interpret the result**. Output is ReMe's own retrieval (BM25 keyword + vector RRF fusion — identical logic to QwenPaw's `memory_search`), with entries like:
   ```
   ========== memory/2026-10-09/qwenpaw-workbuddy-interop.md:14-90 [score=5.2706] ==========
   ```
   The path and line range let you open the source file for full context if needed.

## Scripts

| Script | Purpose |
|---|---|
| `scripts/qwenpaw_agents.py` | List/find QwenPaw agents (id, name, description, memory size). `--json` for machine-readable output, `--root` to override workspaces root. |
| `scripts/qwenpaw_search.py` | Search one agent's ReMe memory index. `--agent <id>` is required; `--root` overrides workspaces root; `--limit N` caps results. |

## Constraints & notes

- **Zero write, zero conflict**: scripts open the ReMe index read-only and never start the `index_update_loop` background job, so they never write to QwenPaw's `mem_metadata/` — safe to run while QwenPaw is active. They only use the `reme` Python package (no `qwenpaw` import), so cold start is ~1–2s.
- **Python environment**: the scripts need the QwenPaw runtime's Python (where `reme-ai` is installed), e.g. `/data/apps/miniforge3/envs/py312/bin/python`. Use that interpreter or a venv containing `reme-ai`.
- **Index freshness**: results come from the persisted ReMe index, which QwenPaw refreshes in the background. Very recent writes may not appear until reindexed — acceptable for experience/advice queries.
- **Agent id vs workspace dir**: `--agent` accepts the agent id (e.g. `travel-assistant`) or the workspace directory name. The script resolves it under the workspaces root.
- **Privacy**: output may include personal notes. Do not paste memory contents into channels that should not see them.
