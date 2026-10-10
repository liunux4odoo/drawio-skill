# Quarkdown Skill 扩展：纯 Markdown → PDF 开发方案

> 交付对象：code agent（执行者）。
> 背景：用户希望 quarkdown skill 能把**任意纯 md 文件**导出为 PDF，流程三步：
> ① 根据用户要求生成临时 qd 模板 → ② 自动拼接进 md 文件 → ③ 输出 PDF。
> 本文件是**任务契约**：WHAT 必须达成，HOW 由你决定。
> 与本仓库 `DEVELOPMENT_PLAN_DOCX_QD_TEMPLATE.md`（docx→qd 模板）互补：
> 那个是"样式学习"（docx → qd 模板），这个是"样式应用"（qd 模板 + md → PDF）。

---

## 0. 全局约束

1. **Python 标准库零依赖**。md2pdf 脚本用纯标准库（拼接 = 文本操作，编译 = subprocess
   调 quarkdown），不引入第三方库。
2. **向后兼容**：不改动 quarkdown skill 现有 SKILL.md 的内容与章节；新增内容一律
   **追加**（沿用约定：diff 验证 `<` 侧为空）。
3. **文档同步是任务的一部分**：SKILL.md 必须新增"Markdown → PDF"用法一节。
4. **生成器输出保持确定性**（无时间戳/随机数）。
5. **不修改用户的源 md 文件**：拼接在临时文件进行，输出 PDF 到指定路径或源文件同目录。
6. **环境前提（已完成，勿重复排查）**：
   - quarkdown wrapper `~/bin/quarkdown` 已加 `-Djava.awt.headless=true`
     （headless JRE 缺 libawt_xawt.so 的坑已绕过，实测 .font + PDF 全链路通过）
   - `QD_CHROME_PATH=/data/apps/chromium/chromium-147/chrome` 由 wrapper 自动 export
   - 因此脚本只需调用 `quarkdown` 命令，无需关心 JVM/Chromium 细节

### 沟通规约（沿用仓库约定）

- **QUESTIONS.md（仓库根）**：遇到契约歧义、两种合理实现无法抉择、或发现本计划
  自相矛盾时，停下来把问题写进该文件，**不要自己发明 workaround 再往下跑**。
- **FINDINGS.md（仓库根）**：记录计划之外的意外发现，每条附复现方式。
- 没有相关内容时可不建文件；任务结束时保留这两个文件作为交付说明的一部分。

---

## 1. 功能目标（WHAT）

新增脚本 `skills/quarkdown/references/md2pdf.py`，实现：

**输入**：
- 指定的纯 Markdown 文件（`.md`，任意路径）
- 用户要求的样式参数（命令行参数，见 §5）

**输出**：
- PDF 文件（默认与源 md 同目录同名 `.pdf`，可 `-o` 指定）
- 临时 `.qd` 文件在 `/tmp` 生成，编译后清理

**流程**（对应需求三步）：
1. 按参数生成临时 qd 模板头（`.docname` / `.doctype` / `.doclang` / `.theme` /
   `.pageformat` / `.font` / `.paragraphstyle` / `.extend`）
2. 模板头 + md 内容拼接成临时 `.qd`（**不修改源 md**）
3. `quarkdown compile <tmp.qd> -o <out> --pdf --strict` → 输出 PDF → 清理临时文件

---

## 2. 模板头生成规则（WHAT）

### 2.1 参数 → 指令映射

| 参数 | 默认值 | 生成的指令 |
|---|---|---|
| `--title` | md 第一个 `#` 标题 或 文件名 | `.docname {<title>}` |
| `--lang` | `zh-CN` | `.doclang {<lang>}` |
| `--theme` | `paperwhite` | `.theme {<theme>} layout:{latex}` |
| `--page` | `A4` | `.pageformat size:{<page>} margin:{2cm}` |
| `--font` | `Noto Serif CJK SC` | `.font {<font>} size:{<size>}pt` |
| `--size` | `12` | 同上（全局基准字号，pt） |
| `--lineheight` | `1.6` | `.paragraphstyle lineheight:{<v>}` |
| `--spacing` | `0.5` | `.paragraphstyle spacing:{<v>}` |
| `--indent` | `0` | `.paragraphstyle indent:{<v>}` |
| `--heading-color` | 不设置 | `.extend {heading} ... foreground:{<color>}` |
| `--numbered-off` | 默认关闭编号 | 每个 `.extend {heading}` 块加 `numbered:{no}` |

### 2.2 编号默认策略（与 docx→qd 方案一致）

- **默认 `numbered:{no}`**（方案 B）：纯 md 的标题里若已有编号文本（如 `（一）`、
  `1.`），自动编号会重复；qd 原生不支持中文数字编号（只支持 `1/a/A/i/I`），
  一律走"编号写死进标题文本 + 关闭自动编号"。
- 若用户明确要求自动编号（`--numbered on`）→ 生成 `.numbering - headings: 1.1.1`（或
  用户指定格式串），但 md 标题文本里**不能**再含编号前缀。

### 2.3 字号映射（复用 docx→qd 方案的 §3.6）

- `fontsize` 只接受相对枚举 `tiny/small/normal/medium/large/larger/huge`
- 全局绝对字号：`.font size:{N}pt`
- 元素级字号（如 `.extend {heading}`）：用相对枚举，**禁止 `fontsize:{16pt}`**

### 2.4 标题样式（可选扩展）

`--heading-style` 可按级别生成 `.extend {heading} where:{depth: .depth::equals {N}}`
块。默认只加 `numbered:{no}` + 可选颜色，字体/字号继承全局 `.font`。

---

## 3. 拼接与编译（WHAT）

### 3.1 拼接规则

```text
<模板头>
<源 md 内容（原样，零改动）>
```

- 模板头各指令按 §2 生成，行序固定：docname → doctype → doclang → theme →
  pageformat → font → paragraphstyle → extend*
- md 内容**逐字复制**，不做任何改写（这是"纯 md 直通"的承诺）
- 临时文件：`/tmp/md2pdf-<短哈希>.qd`（确定性哈希，如源文件路径的 sha1 前 8 位）

### 3.2 md 兼容性风险（必须处理）

quarkdown 是 Markdown 超集，纯 md 基本兼容，但以下情况需注意：

| md 特征 | 风险 | 处理 |
|---|---|---|
| `.` 开头的行 | 被当成 qd 函数调用 | 编译错误时报错并提示用户（md 中罕见，不自动改） |
| `$...$` / `$$` | 可能被当数学公式 | **实测 `$100` 正常显示**（非公式上下文）；若渲染异常提示用户转义 |
| `#` 标题层级 | 正常 | 编号默认关闭（§2.2） |
| HTML 标签 | 部分支持 | 不承诺；渲染异常提示用户 |
| 表格/列表/引用 | 正常 | 实测通过 |

**原则**：脚本不自动修改用户 md 内容；遇到编译失败，报错并建议定位到具体行，
绝不静默改内容重试。

### 3.3 编译命令

```bash
quarkdown compile <tmp.qd> -o <out_dir> --pdf --strict
```

- `--strict`：严格模式，编译错误即失败
- `<out_dir>` 由 `-o <output.pdf>` 推断（临时目录，编译后把 PDF 移到目标路径）
- 编译成功后：移动 PDF → 清理临时 .qd → 报告 PDF 路径

### 3.4 退出码

- 0：成功（PDF 已生成）
- 1：输入错误（md 不存在、参数非法）
- 2：编译失败（quarkdown 报错；stdout 给出错误定位建议）
- 3：PDF 移动失败（输出路径不可写）

---

## 4. 输出报告（WHAT）

stdout 报告（人可读 + 机器可解析，沿用 drawio 脚本风格）：

```
md2pdf: 成功
  源文件:   /path/to/input.md
  模板头:   /tmp/md2pdf-<hash>.qd（已清理）
  PDF:      /path/to/output.pdf（130KB, 10页）
  参数:     --theme paperwhite --page A4 --font Noto Serif CJK SC size 12pt
```

失败时输出错误类型 + 定位建议（如"第 15 行 `.foo` 被解析为 qd 函数调用"）。

---

## 5. 脚本接口（WHAT）

```
python3 skills/quarkdown/references/md2pdf.py <input.md> \
    [-o output.pdf] \
    [--title <标题>] \
    [--lang <语言>] \
    [--theme <paperwhite|darko|...>] \
    [--page <A4|A5|letter|...>] \
    [--font <字体名>] \
    [--size <pt>] \
    [--lineheight <系数>] \
    [--spacing <系数>] \
    [--indent <系数>] \
    [--heading-color <颜色>] \
    [--numbered on|off] \
    [--heading-style <N:枚举,...>] \
    [--dry-run]
```

- `--dry-run`：只打印生成的模板头 + 拼接预览（前 N 行），不编译
- 参数缺省用 §2.1 默认值；`--heading-style 1:large,2:medium` 支持按级别设字号枚举

---

## 6. SKILL.md 更新（WHAT）

在 `skills/quarkdown/SKILL.md` **末尾追加**一节（不删改现有内容）：

- `## Converting Markdown to PDF`：
  - 何时用：用户给纯 md 要 PDF（快速打印/交付）
  - 用法：`python3 references/md2pdf.py input.md [-o out.pdf] [--theme ...]`
  - 编号默认关闭（方案 B，理由一句话）
  - md 兼容性提示（§3.2 表格精简版）
  - 校验：输出 PDF 后抽查页数/内容

---

## 7. 测试（建议，P2 级）

在 `skills/quarkdown/tests/` 下用 pytest（如仓库已有测试体系则沿用）：
- `test_md2pdf.py`：
  - fixture 纯 md（含中文标题/表格/列表/`$100`）→ 生成 PDF → 断言文件存在且非空
  - 断言源 md 未被修改（前后 hash 一致）
  - `--dry-run` 输出含模板头关键指令
  - `--numbered off` 生成 `numbered:{no}`；`--numbered on` 生成 `.numbering`
  - 非法参数 → 退出码 1
- 测试不得依赖网络；PDF 编译较慢（Chromium 起服务 ~5s），标记为 integration

---

## 8. 建议实施顺序

1. 模板头生成（参数 → 指令，纯函数，先写测试）
2. 拼接 + 临时文件管理
3. `quarkdown compile` 子进程调用 + 退出码/错误处理
4. PDF 移动 + 报告
5. SKILL.md 追加一节
6. 端到端验证（§9 命令）

---

## 9. 验收命令（全部须实际执行通过）

```bash
# 1. 脚本语法
python3 -m py_compile skills/quarkdown/references/md2pdf.py

# 2. 默认参数生成 PDF（fixture 纯 md）
python3 skills/quarkdown/references/md2pdf.py tests/fixtures/sample.md -o /tmp/_out.pdf
# 期望：退出码 0，/tmp/_out.pdf 存在且非空

# 3. dry-run（不编译）
python3 skills/quarkdown/references/md2pdf.py tests/fixtures/sample.md --dry-run
# 期望：输出模板头含 .docname/.theme/.font/.extend，且含 numbered:{no}

# 4. 自定义参数
python3 skills/quarkdown/references/md2pdf.py tests/fixtures/sample.md \
    --title 自定义 --theme darko --page A5 --font Noto Sans CJK SC \
    --size 10 --heading-color navy --heading-style 1:large,2:medium \
    -o /tmp/_out2.pdf
# 期望：退出码 0，PDF 存在

# 5. 自动编号模式
python3 skills/quarkdown/references/md2pdf.py tests/fixtures/sample.md --numbered on -o /tmp/_out3.pdf
# 期望：模板头含 .numbering - headings: ...（标题文本无编号前缀的 fixture）

# 6. 源文件未被修改
sha256sum tests/fixtures/sample.md   # 前后一致（测试内断言）

# 7. 错误处理（不存在的文件）
python3 skills/quarkdown/references/md2pdf.py /tmp/nonexistent.md
# 期望：退出码 1，错误信息明确

# 8. 文档残留检查
grep -n "Converting Markdown to PDF" skills/quarkdown/SKILL.md   # 存在
```

验收标准：上述命令逐条满足；`QUESTIONS.md` 中的问题有结论或已上报；
`FINDINGS.md` 如实记录；最终汇报列出改动文件与对应验收结果。

---

## 10. 决策留痕

| 决策 | 选项 | 选择 | 理由 |
|---|---|---|---|
| 拼接方式 | 修改源 md / 临时文件拼接 | **临时文件拼接** | 承诺"纯 md 直通"零改动；用户源文件不可变 |
| 编号策略 | 自动编号 / 默认关闭 | **默认关闭（方案 B）** | 与 docx→qd 方案一致；md 标题常有手写编号；qd 无中文数字 |
| 字号 | 绝对 pt / 相对枚举 | **相对枚举 + 全局 size** | qd `fontsize` 只接受枚举（实测）；绝对 pt 仅 `.font size` |
| 模板生成 | 写死模板 / 参数化 | **参数化** | 用户"按需求生成"是核心诉求；默认值覆盖 80% 场景 |
| 错误处理 | 自动改 md 重试 / 报错提示 | **报错提示** | 不静默改用户内容；编译失败定位到行 |
| 环境 | 脚本管 JVM/Chromium / 依赖 wrapper | **依赖 wrapper** | wrapper 已修 headless 坑并 export QD_CHROME_PATH，脚本只调命令 |
