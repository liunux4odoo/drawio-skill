# Quarkdown Skill 扩展：docx 格式 → qd 模板定义 开发方案

> 交付对象：code agent（执行者）。
> 背景：用户希望 quarkdown skill 能从指定 docx 文件（或 docx 生成 py 脚本）读取格式，
> 转化为可复用的 qd 模板定义（`.font` + `.paragraphstyle` + `.numbering` + `.extend` 集合）。
> 本文件是**任务契约**：WHAT 必须达成，HOW 由你决定。与 drawio 的
> `DEVELOPMENT_PLAN.md` 同级，互不影响。

---

## 0. 全局约束

1. **Python 标准库零依赖 + python-docx 可选依赖**。主脚本 `extract_docx_style.py`
   纯标准库可解析 docx（zipfile + xml），python-docx（本机 1.2.0）用于"执行 py
   脚本生成临时 docx"场景时可选加载。仅兼容 Python 3.10+（本机 3.12）。
2. **向后兼容**：不改动 quarkdown skill 现有 SKILL.md 的内容与章节；新增内容一律
   **追加**（延续上一轮"原内容一字未删改"的约定，diff 验证 `<` 侧为空）。
3. **文档同步是任务的一部分**：SKILL.md 必须新增"docx → qd 模板"用法一节，README.md
   如涉及 quarkdown 需同步（README 目前仍是纯 drawio 内容，可在本任务中顺带把
   quarkdown skill 加进 Contents 清单，但**不得**删除 drawio 相关表述）。
4. **生成器输出保持确定性**（无时间戳/随机数；头部注释可含来源 docx 文件名，但不得
   含生成时刻）。
5. 提交前删除测试产生的 `__pycache__`；生成物（临时 docx / 输出模板）不要留在仓库里。
6. 仓库当前 git 状态：`skills/quarkdown/`、`example.qd`、`output/` 未跟踪。本任务
   完成后按现状提交或按现有 git 工作流处理，commit message 中文、简短。

### 沟通规约（沿用 drawio 计划的约定）

- **QUESTIONS.md（仓库根）**：遇到契约歧义、两种合理实现无法抉择、或发现本计划
  自相矛盾时，停下来把问题写进该文件，**不要自己发明 workaround 再往下跑**。
- **FINDINGS.md（仓库根）**：记录计划之外的意外发现，每条附复现方式。
- 没有相关内容时可不建文件；任务结束时保留这两个文件作为交付说明的一部分。

---

## 1. 功能目标（WHAT）

新增脚本 `skills/quarkdown/scripts/extract_docx_style.py`，实现：

**输入**（二选一，入口统一为 docx）：
- 指定 `.docx` 文件 → 直接解析
- 指定 `.py` 生成脚本 → 在临时目录执行该脚本生成 `.docx`，再走 docx 解析。
  执行前检查脚本内容无破坏性副作用（无 `rm` / 网络 / 写仓库外路径）；有疑问时
  报错提示用户，不擅自执行。

**输出**：一个可复用的 `.qd` 模板定义文件，集中包含：
- `.font`（main / heading / code + size；含中文字体 fallback）
- `.paragraphstyle`（lineheight / spacing / indent）
- `.numbering`（**仅当 docx 编号全部落在 qd 支持范围内**，见 §2）
- `.extend {heading}` 按 `where:{depth}` 分级别定义字体/字号/颜色/字重等
- `.extend {paragraph}` 定义正文样式
- 头部注释：来源 docx 路径、提取到的格式摘要、编号处理说明（见 §2）

**校验**：生成后执行 `quarkdown c <template>.qd --strict --out /tmp/quarkdown-verify`
必须通过。模板文件设计为可被业务文档 `.include` 复用（`sandbox:{share}` 默认）。

---

## 2. 编号映射规则（核心约定，本轮讨论的结论）

**总原则：qd 不支持的编号一律走方案 B —— 编号写死进标题文本 + `numbered:{no}`，
不映射成 `.numbering` 格式串。** 只把 qd 原生支持的编号映射到 `.numbering`。

### 2.1 qd 原生支持的编号（`numbering.qd` 实测）

`.numbering` 格式串中每个字符代表一层计数器，支持且仅支持：
- `1` 十进制（1, 2, 3, ...）
- `a` 小写拉丁字母（a, b, c, ...）
- `A` 大写拉丁字母（A, B, C, ...）
- `i` 小写罗马数字（i, ii, iii, ...）
- `I` 大写罗马数字（I, II, III, ...）
- 其他字符为固定符号（`.`、`（`、`）` 等原样输出）

例：`1.A.a` → H2: `1`、H3: `1.A`、H4: `1.A.a`。

**不支持**：中文数字（一、二、三）、中文序号（（一）（二））、天干地支、
自定义序列等。**无法逐级独立设置编号规则**（`1.A.a` 是一整条层级串）。

### 2.2 docx 编号检测决策树

脚本扫描各 Heading 级别段落文本开头，用正则识别编号模式，按以下规则映射：

| docx 编号形态（示例） | 正则识别 | 是否 qd 支持 | 处理 |
|---|---|---|---|
| `1.` / `1、` / `1．` | `^\d+[.、．]` | ✅ 十进制 | 映射 `1` |
| `1.1` / `1.1.1` | 多级十进制 | ✅ | 映射 `1.1.1`（按实际层级） |
| `（一）` / `一、` / `第一章` | 中文数字 | ❌ | **方案 B** |
| `（1）` / `(1)` | `^[（(]\d+[)）]` | ⚠️ 层级内固定符号 | 若整个层级串都是 `1` 层级组合可映射；否则方案 B |
| `（a）` / `(a)` | 小写字母 | ✅ 映射 `a`（嵌套括号为固定符号） | 映射 `a` |
| `（A）` / `(A)` | 大写字母 | ✅ 映射 `A` | 映射 `A` |
| `i.` / `I.` / `（i）` | 罗马数字 | ✅ 映射 `i`/`I` | 映射 `i`/`I` |
| 其他 / 无法识别 | — | ❌ | **方案 B** |

**决策规则**：
1. 对每个 Heading 级别独立识别。
2. 若**所有**参与编号的 Heading 级别都落在 ✅ 区间 → 生成 `.numbering` 层级串。
3. 若**任一级别**落在 ❌ 区间（中文数字、无法识别、混合风格）→ **整体走方案 B**：
   - `.numbering` **不生成**（或显式 `headings: none` 关闭自动编号）
   - 每个标题的 `.extend {heading} where:{depth}` 块中加 `numbered:{no}`
   - 模板头部注释说明："编号由正文标题文本自带，qd 自动编号已关闭"
   - **标题文本保留 docx 中的编号原文**（如 `（一）标题`），业务文档写作时需在
     标题里手写编号
4. **Word 自动编号（numPr）特殊处理**：若 docx 的编号不是文本而是 Word 自动编号
   （段落 XML 含 `<w:numPr>`，python-docx 读不到文本编号），脚本检测到后**提示用户**：
   自动编号无法提取，要么先转成文本编号再跑，要么接受方案 B 手动补写编号。
   不得静默假设。

### 2.3 为什么这样约定（决策留痕）

- **否决"lambda 转中文数字"（方案 A）**：`.numbered` 面向非标题元素，用在标题上
  需绕过 `headings` 格式串，复杂度高、收益低，不值得为"自动编号"这一非核心能力
  引入。
- **否决"接受 （A）（B） 替代 （一）（二）"（方案 C）**：中文公文习惯强约束，
  拉丁字母替代不符合用户文档规范。
- **选定方案 B**：中文编号写死在标题文本最符合中文公文习惯；`\ref` 交叉引用
  用的是标题 ID，不受编号格式影响；模板提取脚本只需 `numbered:{no}` + 保留原文，
  实现最简、行为最可预测。

---

## 3. 格式提取范围（WHAT）

提取三类格式，**遍历实际文档元素**（真实段落/run 的 effective 值），不读样式
定义表（避免 python-docx `style.font` 返回 None、需沿 `base_style` 继承链解析
的坑）：

### 3.1 标题（Heading 1–6 / Title）
- 按样式名（Heading 1–3 / Title / 自定义标题样式）或 outline level 聚合
- 提取：字体族（西文 + 中文 eastAsia）、字号、字重（bold）、颜色、斜体、下划线
- 映射：`depth` = 标题级别；`where:{depth: .depth::equals {N}}`

### 3.2 正文段落
- 聚合普通段落：对齐（alignment）、段前距（space_before）、段后距（space_after）、
  行距（line_spacing）、首行缩进（first_line_indent）
- 映射：
  - `lineheight` = 行距系数（docx 行距 pt ÷ 字号 pt）
  - `spacing` = 段距系数（docx 段后距 pt ÷ 字号 pt）
  - `indent` = 首行缩进系数（docx 缩进 pt ÷ 字号 pt）
  - 注：`.paragraphstyle` 的 `spacing`/`indent` 是"×字号"的系数，**必须换算**
- 对齐映射：left→`start`、center→`center`、right→`end`、justify→`justify`

### 3.3 文字 run
- 聚合 run 级：bold / italic / underline / 颜色 / 字号 / 字体
- 映射到 `.extend {paragraph}` 或文字样式相关的 primitive 参数：
  `fontweight:{bold}` / `fontstyle:{italic}` / `textdecoration:{underline}` /
  `foreground:{color}`

### 3.4 全局字体
- main 字体：Normal 样式或多数段落字体
- heading 字体：多数标题字体
- code 字体：如检测到代码块样式（可选）
- size：正文基准字号（`.font size:{N}pt`）
- **中文字体必须从 XML `w:rFonts w:eastAsia` 读取**（`font.name` 只读西文字体），
  生成第二个 `.font` 调用做 CJK fallback

### 3.5 明确不覆盖（写进 SKILL.md，避免 agent 误以为全复刻）
- 表格列宽/行高、页眉页脚、分页控制、域、SmartArt、文本框坐标
- 这些是 docx 版面机制，quarkdown 排版模型无 1:1 对应；只提取"样式规范族"

### 3.6 字号映射规则（实测确认的 qd 语法约束）

**qd 的 `fontsize`（`.heading`/`.text` 的 size 参数）只接受相对枚举，不接受绝对 pt**：

| 枚举 | 相对大小 |
|---|---|
| `tiny` | 50% |
| `small` | 75% |
| `normal` | 100%（基准） |
| `medium` | 125% |
| `large` | 150% |
| `larger` | 200% |
| `huge` | 300% |

**绝对字号只能通过 `.font size:{N}pt` 设全局基准**，元素级用枚举相对缩放。

docx 提取的 pt 字号 → qd 映射规则（二选一，默认策略 1）：

1. **策略 1（默认，推荐）**：固定 `.font size` 为正文基准（如 12pt），标题字号 = 提取的 pt ÷ 基准 pt，映射到最近枚举。例：H1=22pt、基准 12pt → 22/12≈1.83 → 取 `large`(150%) 或 `larger`(200%)，选更接近者。
2. **策略 2**：若标题字号比例不在枚举覆盖内（如想精确 16pt），调整 `.font size` 让比值落进枚举。例：想 H1 精确 16pt → 基准 10pt + `larger`(200%) = 20pt？不精确，故策略 2 仅作兜底，优先策略 1。

**禁止**：`fontsize:{16pt}` 这类绝对 pt 写法——编译报错（实测：`No such element '16pt' among values [tiny, small, normal, medium, large, larger, huge]`）。

---

## 4. 输出模板结构（模板）

生成的 `.qd` 模板文件结构如下（示意，具体值由提取结果决定）：

```markdown
<!--
  来源: <docx 路径>
  提取格式摘要: ...
  编号处理: 方案 B —— 编号写死进标题文本，qd 自动编号已关闭（或 方案 A 映射层级串）
-->

.docname {<从 docx 标题提取或默认>}
.doctype {paged}
.doclang {zh-CN}

.font {<main 字体>} heading:{<标题字体>} size:{<N>pt}
.font {<中文字体>}                                    <!-- CJK fallback -->

.paragraphstyle lineheight:{<系数>} spacing:{<系数>} indent:{<系数>}

<!-- 方案 A（qd 支持编号时） -->
.numbering
    - headings: <层级串>

<!-- 方案 B（任一级不支持时） -->
.extend {heading} where:{depth: .depth::equals {1}}
    .super numbered:{no} fontsize:{...} fontweight:{...} foreground:{...}
.extend {heading} where:{depth: .depth::equals {2}}
    .super numbered:{no} fontsize:{...} ...
.extend {heading} where:{depth: .depth::equals {3}}
    .super numbered:{no} fontsize:{...} ...

.extend {paragraph}
    .super textalignment:{...}

<!-- 字号映射：fontsize 只接受相对枚举（tiny~huge），见 §3.6；
     绝对 pt 只能设全局 .font size，元素级用枚举相对缩放。
     禁止 fontsize:{16pt} 这类绝对 pt 写法（编译报错）。 -->
```

业务文档用法：

```markdown
.include {qa-template.qd}

# （一）标题   <!-- 编号写死在文本里 -->
```

---

## 5. 脚本接口（WHAT）

```
python3 skills/quarkdown/scripts/extract_docx_style.py \
    <input.docx | input.py> \
    [-o output.qd] \
    [--heading-levels 1-3] \
    [--dry-run]
```

- `--dry-run`：只打印提取摘要（各 Heading 级别的字体/字号/颜色、编号检测结果、
  方案 A/B 判定），不生成文件
- `--heading-levels`：参与提取的标题级别范围，默认 1–3
- 退出码：0 成功 / 1 错误（输入不存在、解析失败、py 脚本有风险）/ 2 文件错误
- stdout 基本格式：提取摘要 + 生成路径 + 校验结果（沿用 drawio 脚本的退出码语义）

---

## 6. SKILL.md 更新（WHAT）

在 `skills/quarkdown/SKILL.md` **末尾追加**一节（不删改现有内容）：

- `## Converting docx styles to a qd template`：
  - 何时用：用户给 docx / docx 生成脚本，要 qd 模板
  - 用法：`python3 scripts/extract_docx_style.py <input> -o template.qd`
  - 编号处理约定（§2 总原则，一句话）：qd 不支持的编号写死进标题文本
  - 覆盖范围边界（§3.5）：表格/页眉页脚等不覆盖
  - 校验：`quarkdown c template.qd --strict`（引现有 Workflow 节的编译命令）

---

## 7. 测试（建议，P2 级）

在 `skills/quarkdown/tests/` 下用 pytest 固化（如仓库已有测试体系则沿用）：
- `test_numbering_detection.py`：编号决策树各分支（十进制/中文数字/字母/罗马/混合/
  numPr 自动编号）
- `test_extract.py`：给定 fixture docx → 断言生成的 `.font`/`.paragraphstyle`/
  `.extend` 块与期望一致
- `test_py_script_input.py`：给定生成脚本 → 执行 → 提取 → 断言（脚本须无副作用）
- fixture 用最小 docx（python-docx 生成，提交到仓库，或测试内联生成）
- 测试不得依赖网络

---

## 8. 建议实施顺序

1. 编号检测决策树（纯函数，先写测试）
2. docx 解析（标题/段落/run/字体 + eastAsia）
3. qd 模板生成（含方案 A/B 分支）
4. py 脚本输入入口（执行 + 风险检查）
5. SKILL.md 追加一节 + README Contents 顺带补 quarkdown
6. 端到端校验（样例 docx → 模板 → `quarkdown c --strict`）
7. 提交

---

## 9. 验收命令（全部须实际执行通过）

```bash
# 1. 脚本语法
python3 -m py_compile skills/quarkdown/scripts/extract_docx_style.py

# 2. docx 输入 → 生成模板（fixture：含 1. / （一）/ 1.1 混合编号的样例 docx）
python3 skills/quarkdown/scripts/extract_docx_style.py tests/fixtures/mixed_numbering.docx -o /tmp/_tpl.qd --dry-run
# 期望：编号检测报告中文数字（（一））→ 方案 B

python3 skills/quarkdown/scripts/extract_docx_style.py tests/fixtures/mixed_numbering.docx -o /tmp/_tpl.qd
# 期望：生成的模板中 .extend 块含 numbered:{no}，.numbering 不出现 headings 或为 none

# 3. 纯 qd 支持编号（fixture：1.1.1 十进制）
python3 skills/quarkdown/scripts/extract_docx_style.py tests/fixtures/dec_numbering.docx -o /tmp/_tpl2.qd
# 期望：.numbering - headings: 1.1.1（或按实际层级）

# 4. py 脚本输入（fixture：无副作用的 python-docx 生成脚本）
python3 skills/quarkdown/scripts/extract_docx_style.py tests/fixtures/gen_docx.py -o /tmp/_tpl3.qd

# 5. 模板编译校验
quarkdown c /tmp/_tpl.qd --strict --out /tmp/quarkdown-verify
quarkdown c /tmp/_tpl2.qd --strict --out /tmp/quarkdown-verify

# 6. 中文字体（fixture：中文 docx，验证 w:rFonts eastAsia 被提取为第二个 .font）
grep -c "^\.font" /tmp/_tpl.qd   # 期望 >= 2

# 7. 回归测试（若做 §7）
python3 -m pytest -q skills/quarkdown/tests/

# 8. 文档残留检查
grep -n "Converting docx styles" skills/quarkdown/SKILL.md   # 存在
```

验收标准：上述命令逐条满足；`QUESTIONS.md` 中的问题有结论或已上报；
`FINDINGS.md` 如实记录；最终汇报列出每个任务的改动文件与对应验收结果。

---

## 10. 决策留痕

| 决策 | 选项 | 选择 | 理由 |
|---|---|---|---|
| 编号不支持时怎么处理 | A lambda 转中文 / B 写死进标题 / C 接受拉丁替代 | **B** | 中文公文习惯强约束；实现最简；交叉引用不受影响 |
| 输入形态 | 直接解析 py / 执行生成 docx 再解析 | **执行生成 docx** | py AST 解析脆弱；docx 是统一解析目标 |
| 格式提取源 | 样式定义表 / 实际元素 effective 值 | **实际元素** | 避免 `style.font` None 与继承链解析坑 |
| 编号映射边界 | 逐级独立 / 单一层级串 | **单一层级串 + 方案 B 兜底** | qd 能力边界（`.numbering` 只有一种格式串） |
| 中文字体 | 只读 font.name / XML eastAsia | **XML eastAsia** | `font.name` 只读西文字体，中文会丢 |
| 输出形态 | 样式散落文档 / 集中 template.qd | **集中 template.qd + include** | 一处定义、跨文档复用 |
| 字号映射 | 绝对 pt 直写 / 相对枚举 + 全局 size | **相对枚举 + 全局 size（策略 1）** | qd `fontsize` 只接受 tiny~huge 枚举（实测编译报错）；绝对 pt 仅 `.font size` 支持 |
