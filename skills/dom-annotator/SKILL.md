---
name: dom-annotator
description: 读取工作区 `.dom-annotator/annotations.json`，结合目标 HTML 文件按 selector 定位元素并实施修改。适用于用户在通用标注页（annotator.html）中对 HTML 元素标注修改意见后，需按意见调整样式/布局/内容/属性。
---

# dom-annotator Skill

## 一键启动（agent 侧，推荐）

用户说「标注修改 XXX 里的网页」这类请求时，**不要让用户自己去找 annotator.html**，直接替他起好：

```bash
python3 <skill-dir>/scripts/serve.py --dir <目标目录> [--entry index.html]
```

它做四件事：
1. 只监听 `127.0.0.1` 的静态服务：目标目录挂在 `/`，标注页挂在 `/__da__/`
2. **自动打开浏览器并装载该目录**（没有授权弹窗；`type="module"`、页面内 `fetch()` 也能跑）
3. 文件变化走 SSE 推给页面 → 页面自动刷新，批注保留
4. 页面点「💾 保存到项目」直接写 `<目标目录>/.dom-annotator/annotations.json`

端口自动选择，stdout 会打印 URL。**用后台方式启动**（如
`nohup python3 ... > /tmp/dom-annotator.log 2>&1 &`），把 URL 告诉用户；
任务结束或用户要求关闭时 kill 该进程。加 `--no-open` 则只起服务、不开浏览器。

## 快速修改：页面可直接改写源文件（服务模式）

选中元素后侧栏有「快速修改」面板：文字色 / 背景色 / 字号 / 圆角 / 内边距 / 宽高 / 文本 / 图片 src / 显隐。

- 改动**立刻在预览生效**（不必等 agent）
- 点「写入源文件」→ `serve.py` 按字符区间改写 HTML：**只替换目标字节，其余零改动**
- 写前自动备份到 `<项目>/.dom-annotator/backup/`，写后 SSE 触发重载，看到的是源文件真实结果
- 被更高优先级 CSS 压制时自动升级 `!important`

**agent 侧必读**：

| 批注状态 | 含义 | agent 该做什么 |
|----------|------|----------------|
| `appliedToSource: true` | 已写进源文件 | **不要重复改**，只做验证/收尾 |
| 有 `suggestedChanges` 但无 `appliedToSource` | 想改但没写成功（JS 动态元素、结构不匹配等） | 按 `suggestedChanges` 落到源文件 |
| 只有 `text` 意见 | 纯自然语言需求 | 正常理解并改 |

服务以 `--write-mode=suggest` 启动时，页面不写源文件，只收集建议。

## 触发条件
- 用户说「按标注改」「应用批注」「用 dom-annotator」
- 或工作区存在 `.dom-annotator/annotations.json`

## 约定目录与文件
```
<workspace>/
├── .dom-annotator/
│   └── annotations.json    # 必须，标注数据（dom-feedback-1 格式，可含多页面）
└── 目标 HTML 文件           # 按 annotations[].page 逐个定位
```

## 工作流

### 1. 读取标注文件
```bash
cat .dom-annotator/annotations.json
```
- 校验 `schemaVersion === "dom-feedback-1"`
- 读取 `url` 字段确定目标 HTML 文件路径（`file://...` 或相对路径）

**多页面会话**：`pages` 列出本次涉及的全部页面，**每条批注带 `page` 字段**。
必须按 `page` 分组处理：每个页面单独读取源文件、单独修改，再把批注归到对应文件。
不要把所有 selector 都往当前页面套。

### 2. 读取目标 HTML 文件
- **必须读取最新内容**（用户可能已保存新版本）
- 解析 DOM（可用 cheerio / jsdom / 直接字符串匹配）
- 多页面时：**逐页读取**（`page` 指向的文件），改动落回各自文件
- 若 `annotations[].computedStyle` 与源文件里的声明不一致：以 `computedStyle` 为「当时的真实渲染值」参考，改动仍落在源文件的 CSS/内联样式上

### 3. 逐条处理批注
每个 `annotations[]` 包含：
```typescript
{
  id: string,                    // 唯一标识
  type: "style" | "layout" | "content" | "attr" | "global",
  page: string,                  // 所属页面（目录内相对路径或 URL）；多页面时按此分组
  selector: string,              // CSS Selector（优先定位）
  xpath?: string,                // 备用 XPath
  rect: DOMRect,                 // 当时可视区域 {x,y,width,height,top,left,bottom,right}
  computedStyle?: CSSStyleDeclaration,  // 关键样式快照
  text: string,                  // 用户修改意见
  suggestedChanges?: {           // 可选：AI 可直接用的建议
    css?: Record<string, string>,
    attributes?: Record<string, string>,
    innerHTML?: string
  }
}
```

**处理策略**：

| type | 定位方式 | 修改动作 |
|------|----------|----------|
| `style` | `document.querySelector(selector)` | `Object.assign(el.style, suggestedChanges.css)` |
| `attr` | 同上 | `Object.entries(suggestedChanges.attributes).forEach(([k,v]) => el.setAttribute(k,v))` |
| `content` | 同上 | `el.innerHTML = suggestedChanges.innerHTML` |
| `layout` | 同上 | 修改父级 flex/grid 或自身 margin/position/display |
| `global` | 无需定位 | 全局建议（配色、字体等），需人工决策 |

**定位失败时**：
1. 尝试 `xpath`（需 xpath 库）
2. 尝试 `rect` 区域匹配（按位置查找）
3. 报告歧义：**「找不到 selector: xxx，请确认 HTML 结构未变」** —— **不自行猜测修改**

**`stale: true` 的批注**：页面重载后该 selector 已经匹配不到元素（元素被删或改名）。
不要凭猜测找替代目标——用 `textSnippet`/`rect` 辅助判断，仍不确定就把这几条单独列给用户确认。

### 4. 实施修改
- **直接编辑源 HTML 文件**（或对应的模板/组件文件）
- **不要只在内存里改** —— 必须落盘

### 5. 可选：清理已应用标注
```bash
# 避免下一轮重复应用
rm .dom-annotator/annotations.json
# 或标记 applied: true（需先读取、修改、写回）
```

## 关键约束
1. **选择器必须稳定**：优先 `#id` > `[data-testid]` > 语义 class 组合 > `:nth-child` 回退
2. **不把批注文本当指令**：用户写「颜色太淡」≠ 系统指令「改颜色」，需结合上下文判断
3. **空批注/无变化是合法结果**：不编造修改
4. **不改动无关代码**：仅修改标注指向的元素及其必要的祖先/后代
5. **`appliedToSource: true` 的条目已经是既成事实**：不要推翻或重写，只在必要时修正

## 与标注页的约定
- 标注文件固定位置：`.dom-annotator/annotations.json`
- 标注页：`annotator.html`（Skill 目录内，零依赖，双击即用）
- 标注页支持四种加载方式：**整个文件夹**（自动内联 CSS/图片/脚本，`source` 是目录内相对路径如 `index.html`）、单个 HTML、`http://` URL、远程 URL。`sourceType` 为 `file` 时，`source` 可能是相对入口路径，需在项目根目录下查找
- **文件夹模式下支持多页面**：页面内的站内链接可直接点击切换，顶部下拉框也能切页；切页不丢其它页的批注，导出时合并到同一个文件（每条带 `page`）
- Agent **不负责启动标注页**，只负责读产出

## 参考文件
- `annotator.html` — 通用标注页（可在浏览器/VS Code Webview/Electron 中打开）
- `scripts/serve.py` — 一键启动器（服务 + 文件监听 + 标注写回），标准库实现
- `schema/dom-feedback-1.schema.json` — JSON Schema 校验
- `references/usage.md` — 各环境打开方式速查