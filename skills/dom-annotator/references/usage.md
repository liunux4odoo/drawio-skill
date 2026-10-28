# annotator.html 使用说明

单个 HTML 文件，零依赖、零安装。任何能渲染网页的环境都能跑。

---

## 〇、让 agent 帮你打开（最省事）

不用记路径、不用手动挑目录——一句话就行：

```
标注修改 ~/work/mysite 里的网页
```

agent 会执行：

```bash
python3 <skill-dir>/scripts/serve.py --dir ~/work/mysite
```

于是：浏览器自动打开标注页并装载该目录 → 改代码后页面自动刷新 → 标完点「💾 保存到项目」直接写回
`~/work/mysite/.dom-annotator/annotations.json`。

这条路径**没有授权弹窗**，且因为走 HTTP，`type="module"` 脚本与页面内 `fetch()` 都能正常工作（内联模式做不到）。

| 参数 | 说明 |
|------|------|
| `--dir DIR` | 目标目录（默认当前目录） |
| `--entry FILE` | 入口 HTML（默认优先 `index.html`） |
| `--port N` | 固定端口（默认 0 = 自动） |
| `--no-open` | 只起服务，不打开浏览器 |

手动用也可以，`Ctrl-C` 结束。

---

## 一、在哪打开

| 环境 | 做法 | 说明 |
|------|------|------|
| **任意浏览器** | 双击 `annotator.html`，或拖进浏览器窗口 | 最直接，`file://` 即可 |
| **VS Code / Cursor** | 资源管理器里右键 `annotator.html` → *Open with Live Preview* / *Open in Default Browser* | 需要 Live Preview / Preview 类扩展；也可 `code annotator.html` 后按 `Ctrl+Shift+V` 预览（受限，建议用浏览器） |
| **VS Code 内置 Simple Browser** | `Ctrl+Shift+P` → `Simple Browser: Show` → 填 `file:///.../annotator.html` | 无需装扩展 |
| **本地 HTTP 服务** | `cd skills/dom-annotator && python3 -m http.server 8000` → 访问 `http://localhost:8000/annotator.html` | **推荐**：加载目标页面时资源最完整 |
| **Electron / Tauri / 嵌入式 WebView** | `loadFile('annotator.html')` | 需要更大控制权时用 |
| **麒麟 v10** | 先确认有浏览器：`chromium` / `google-chrome` / `microsoft-edge` 任一即可 | 系统自带 Firefox 也能用 |

> 麒麟 v10 若只有旧版 Firefox：`file://` 与 `srcdoc` 均可用；若遇到异常，改用 `python3 -m http.server` 方式。

---

## 二、加载目标 HTML 的四种方式

### 1. 打开文件夹（推荐；Chrome/Edge 下可自动刷新 + 直写回）
点「📂 打开文件夹」→ 选中项目根目录 → 浏览器询问权限时选「查看和编辑」。

工具会把该目录下的 **CSS / 图片 / 字体 / 普通脚本** 自动内联进去：
- 外链 `<link rel="stylesheet">` → 转成内联 `<style>`，其中 `url(...)`、`@import` 一并改写成 blob URL
- `<img src>`、`srcset`、`<video src/poster>`、`<source>`、`<object>` 等相对引用 → blob URL
- 普通 `<script src>` → blob URL（会执行）

在 Chrome / Edge 上（File System Access API），额外获得三件事：

| 能力 | 说明 |
|------|------|
| **自动刷新** | 顶栏出现绿色徽标「自动刷新 · 监听中」。文件在磁盘上被改（agent 改完代码）后自动重渲染，**批注原样保留**；元素被删掉的批注标「⚠ 已失效」 |
| **直写标注** | 底部「💾 保存到项目」直接把 `annotations.json` 写进 `<项目>/.dom-annotator/`，不用下载再搬 |
| **记住目录** | 下次打开出现「↩ 恢复 上次文件夹」按钮，点一下授权即可回到同一目录 |

浏览器不支持（Firefox / Safari）或拒绝权限时，会自动退回下一节的快照模式。

> 授权只需一次点击；被撤销权限后重新点按钮即可。只给只读权限也能用（自动刷新仍在），但无法直写标注。

目录里有多个 HTML 时，顶部会出现下拉框切换入口文件（默认优先 `index.html`）。

**已知限制**：`type="module"` 的脚本不内联（blob 无法解析 `import`），会在状态栏
列为「未找到」；运行期 `fetch()`/XHR 请求也不可用。遇到这类页面请改用方式 3。

### 2. 单个 HTML 文件（最快，但外部资源不加载）
点「📁 加载单个 HTML」→ 选文件。

**限制**：内容通过 `srcdoc` 注入，没有 base URL，**相对路径的 CSS / 图片 / 脚本都不会加载**，
页面会「裸奔」。工具检测到未加载的样式表/图片时会弹出橙色提示条，引导改用方式 1 或 3。

> 如果整个页面只用 `<style>` 内联样式，这种方式完全够用，也最省事。

### 3. 本地 HTTP 服务（最保真，适合 SPA / 动态页面）
```bash
cd /path/to/your/site
python3 -m http.server 8000
```
然后在标注页 URL 框输入：
```
http://localhost:8000/index.html
```
相对的 `/css/app.css`、`./logo.png`、以及页面自己的 `fetch()` 全部正常。

### 4. 远程 URL
直接填 `https://...`。

**限制**：抓取走 `fetch`，受 CORS 约束。
- 目标站允许跨域 → 正常标注
- 不允许 → 降级为直接 `<iframe src>` 嵌入，**此时无法标注**（跨域读不到 DOM）

降级时会提示。遇到这种情况，把页面存到本地后用方式 1 或 3。

---

## 三、标注操作

| 操作 | 说明 |
|------|------|
| **Ctrl / ⌘ + 点击元素** | 选中元素并生成一条批注 |
| **「🎯 标注模式」** | 打开后单击即选中（等价于一直按着 Ctrl），适合触控板不好按组合键时 |
| **悬停** | 按住 Ctrl 或开启标注模式时，元素显示蓝色虚线框 |
| **侧栏「定位」/ 点击选择器** | 滚动回该元素并高亮（红框） |
| **点击卡片** | 选中该批注，底部「手动修改」面板自动切换到对应元素 |
| **AI 修改** | 卡片上的意见框，写清「改成什么」（自然语言），导出为 `text` |
| **手动修改** | 见下一节：不经过 AI 直接改颜色/字号/文本/图片并写回源文件 |
| **同一元素再次点击** | 更新已有批注，不重复创建 |
| **Esc** | 取消悬停高亮 |

### 手动修改：不经过 AI，直接写回源文件

侧栏底部是**唯一一个**手动修改面板：点击卡片选中批注后，参数自动更新为对应元素。第一行是「文字色 / 背景色 / 字号」，第二行「加粗 / 斜体 / 下划线 / 对齐」，第三行「圆角 / 内边距 / 宽 / 高」，然后是文本与图片：

| 控件 | 写入内容 |
|------|----------|
| 文字色 / 背景色 | 内联 `style` 的 `color` / `background-color`（被压制时自动补 `!important`） |
| 字号 / 圆角 / 内边距 / 宽 / 高 | 同上，单位 px |
| 加粗 / 斜体 / 下划线 | `font-weight: bold` / `font-style: italic` / `text-decoration: underline` |
| 对齐 | `text-align: left/center/right/justify` |
| 文本 | 替换该元素的文本节点（**仅当元素不含子元素**，否则输入框禁用） |
| 图片 | `img src` 下拉，列出项目里已有的图片，保留原有的 `/` 绝对写法 |

改动**立刻在预览生效**；点「写入源文件」后：

1. `serve.py` 按字符区间改写 HTML —— **只替换目标字节，文件其余部分零改动**
2. 写前把原文件备份到 `<项目>/.dom-annotator/backup/<文件>.<时间戳>`
3. 文件变化 → SSE → 页面重载，你看到的是**源文件的真实结果**

**不会写入源文件的情况**（改动保留为建议，agent 接手）：

| 情况 | 原因 |
|------|------|
| 元素是 JS 动态生成的 | 源文件里没有这个节点 |
| 要改文本但元素含子元素 | 直接替换会毁掉内部结构 |
| 源文件不是完整 HTML（缺 `<html>`） | 浏览器会补全节点，路径对不上 |
| 服务以 `--write-mode=suggest` 启动 | 明确要求只收集建议 |

**撤销**：`<项目>/.dom-annotator/backup/` 每次写入前都留一份完整副本，覆盖回去即可。

### 渲染视口（电脑 / 手机切换）

顶栏下拉框可切换渲染宽度：`360×640`、`390×844`、`414×896`（手机）、`768×1024`（平板）、`1280×800`、`1920×1080`，或「自适应」铺满窗口。

- 切换后 iframe 的真实宽度改变，页面里的 `@media` 媒体查询随之生效，可以边看手机版边标注
- 顶栏右侧显示当前尺寸；选择会记住，刷新后保留
- 导出 JSON 的 `viewport` 会记录 `mode: "device"`、`preset: "390x844"` 和实际宽高，agent 能知道这条意见来自手机视图

**不能模拟的**：User-Agent、`devicePixelRatio`（不缩放）、触控/悬停能力、`prefers-color-scheme`。要验证这些请用浏览器 DevTools 设备工具栏或真机。

批注按会话存 `localStorage`（文件夹模式下整个目录共用一个会话），刷新不丢。

---

## 三之二、多页面（一组页面）

真实站点大多是多个 HTML 互相链接。「📂 打开文件夹」模式支持完整的多页面流程：

| 操作 | 效果 |
|------|------|
| 点页面里的**站内链接** | 自动切到目标 HTML（仍在所选文件夹内时） |
| 顶部**入口下拉框** | 手动在任意 HTML 之间切换 |
| 切页 | 其它页的批注全部保留，侧栏显示「本页 N 条 · 共 M 条 / K 页」 |
| 导出 | **合并所有页面**：每条批注带 `page` 字段，顶层 `pages` 列出全部涉及页面 |

链接解析规则：`about.html` 直接命中；`about`（无扩展名）会依次尝试 `about.html`、`about.htm`、`about/index.html`；`https://…`、`mailto:`、`#锚点` 不拦截，交给页面自己处理。

**agent 侧约定**：按 `annotations[].page` 分组，每个文件单独读取、单独修改。规则写在 `SKILL.md`。

> 单文件 / URL 模式下点击站内链接不会跳转（无法解析目标文件），状态栏会提示改用文件夹模式。

---

## 四、把结果交给 agent

### 方式 A：落盘（推荐，agent 可直接读）
1. 点「💾 导出 JSON」→ 得到 `annotations.json`（多页面会话会合并导出，每条带 `page`）
2. 放到工作区：
```bash
mkdir -p <workspace>/.dom-annotator
mv ~/Downloads/annotations.json <workspace>/.dom-annotator/annotations.json
```
3. 对 agent 说：**「按 .dom-annotator/annotations.json 的标注改」**

### 方式 B：剪贴板（agent 支持粘贴时）
- 「📋 复制 JSON」→ 粘进对话框
- 或「📝 复制 Markdown」→ 粘进对话框（可读性更好，适合纯聊天型 agent）

### 方式 C：管道传给 CLI agent
```bash
cat .dom-annotator/annotations.json | your-agent --stdin
```

---

## 五、agent 侧约定（摘要）

详见 `SKILL.md`。要点：
- 校验 `schemaVersion === "dom-feedback-1"`
- 按 `annotations[].selector` 用 `document.querySelector` 定位；失败再试 `xpath`，仍失败就**报告歧义，不猜**
- 按 `suggestedChanges` 决定改法：有 `css` → 内联样式；有 `attributes` → 属性；有 `innerHTML` → 内容；有 `delete` → 删除元素；只有 `text` → 自然语言判断
- 有 `suggestedChanges.css` 时可直接采用
- **必须落盘改源文件**，不能只改内存
- 应用完可选：删除或标记 `annotations.json`，避免重复应用

---

## 六、常见问题

| 现象 | 原因 | 解决 |
|------|------|------|
| 页面没有样式、图片裂了，布局全乱 | 用「加载单个 HTML」，`srcdoc` 没有 base URL，相对路径解析不了 | 改用「📂 打开文件夹」（自动内联），或起 `python3 -m http.server` 用 URL 加载 |
| 顶部出现橙色「外部资源没有加载」提示 | 同上，工具已检出未加载的样式表/图片 | 按提示改用文件夹模式或 URL 模式 |
| 改了代码页面没跟着变 | 当前是快照模式（顶栏没有「自动刷新」徽标） | 用「📂 打开文件夹」并授予编辑权限；Firefox/Safari 天生不支持，只能手动重开 |
| 点「保存到项目」提示只有读权限 | 授权时选了「仅查看」 | 重新点「📂 打开文件夹」，这次允许编辑 |
| 批注卡片出现「⚠ 已失效」 | 重载后该 selector 已匹配不到元素（元素被删/改名） | 重新标注该元素；导出里会带 `stale: true`，agent 会先和你确认 |
| 点站内链接没反应 | 单文件 / URL 模式不解析站内导航 | 改用「📂 打开文件夹」 |
| 点了链接报「目标不在所选文件夹内」 | 链接指向目录外，或大小写/路径不匹配 | 确认目标 HTML 也在所选目录里 |
| 切页后看不到之前的批注 | 那些批注属于别的页面 | 用顶部下拉框切回，或看侧栏「共 M 条 / K 页」 |
| 点击元素没反应 | 没按 Ctrl，也没开标注模式 | 按 Ctrl/⌘ 点击，或点「🎯 标注模式」 |
| 提示「无法注入检查器」 | 目标页面跨域（fetch 降级为 iframe src） | 本地起 HTTP 服务，或用本地文件 |
| 导出的 selector 很长（一堆 `:nth-of-type`） | 目标元素既无 id 也无稳定 class | 可接受；agent 仍能定位。若长期维护，建议给关键元素加 `data-testid` |
| 「定位」提示找不到元素 | 页面结构变了，或标注来自另一个文件 | 重新标注该元素 |
| 批注刷新后不见了 | `file://` 下 localStorage 可能被禁用 | 用 `http://localhost` 方式打开，或及时导出 JSON |
| 复制按钮无效 | 非 HTTPS/非 localhost 下 `navigator.clipboard` 受限 | 改用「导出 JSON」 |

---

## 七、给页面加 `data-testid` 的建议（提升定位稳定性）

标注工具的选择器优先级：`#id` > `data-testid/data-test/data-cy/data-qa/name/aria-label` > 唯一 class > 路径回退。

长期维护的项目，给关键交互元素加一行：
```html
<button id="login-btn" data-testid="login-submit">登录</button>
```
之后标注生成的 selector 会稳定为 `[data-testid="login-submit"]`，重构 CSS class 也不会失效。
