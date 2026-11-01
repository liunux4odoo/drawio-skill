---
name: project-agents-md-template
description: Optional snippet to declare the QwenPaw L3 project memory vault (.qwenpaw/) in a project root AGENTS.md, so agents/tools that follow the project-level AGENTS.md convention (Claude Code, Cursor, CodeAgent, WorkBuddy, etc.) can discover it even without the reme-memory skill. Use only when the user asks to expose project memory to non-QwenPaw tools.
---

# 可选：在项目根 AGENTS.md 声明 QwenPaw L3 记忆库

## 用途

默认情况下，`.qwenpaw/` 是 QwenPaw 的 L3 项目记忆库（私有实现细节），QwenPaw agent 通过 reme-memory skill 或共享规则即可发现，**不需要**写进项目文档。

但当用户希望**非 QwenPaw 工具/agent**（Claude Code、Cursor、CodeAgent、WorkBuddy 等遵循"项目级 AGENTS.md"惯例的工具，进项目会先读这份文件）也能发现并阅读项目记忆时，可在项目根 `AGENTS.md` 追加以下说明片段。

> 注意：QwenPaw 自己的 agent 不读项目根 AGENTS.md（`prompt_contributors.py` 只从 agent workspace 读），这段说明对 QwenPaw agent 只是"可发现"而非"自动加载"；QwenPaw 生态内的发现性由共享规则/各 agent 记忆负责。

## 使用方式

用户明确要求时（例如「让其他 agent 也能看到项目记忆」「在项目 AGENTS.md 里说明 .qwenpaw」），将以下片段追加到**项目根目录**的 `AGENTS.md`（不是 agent workspace 的 AGENTS.md）：

```markdown
## QwenPaw project memory
This project keeps a QwenPaw L3 memory vault at `.qwenpaw/`:
- `.qwenpaw/memory/notes/` — topic notes (canonical project facts)
- `.qwenpaw/digest/` — long-term digested knowledge (if present)
- `.qwenpaw/mem_metadata/` — search index (regenerate; do not edit)

Read them as plain markdown. Agents with the reme-memory skill can search/write
via `reme_search.py --project <dir>` / `reme_write.py --project <dir>`.
```

## 注意事项

- **默认不自动写**：项目根 AGENTS.md 是用户的项目资产，可能由团队维护、有自己的约定；`.qwenpaw/` 是 QwenPaw 实现细节，默认写入等于强加依赖。只在用户要求时写入。
- **位置是项目根目录**，不是 agent workspace。
- **可逆**：不需要时删除该片段即可，不影响 `.qwenpaw/` 本身。
