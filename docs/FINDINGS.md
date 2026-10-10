# FINDINGS — MD2PDF 开发过程中的意外发现与决策记录

实现 `DEVELOPMENT_PLAN_MD2PDF.md` 时，计划之外/计划未明确的有用信息，均附复现方式。
本计划没有遇到需要暂停并上报 `QUESTIONS.md` 的契约歧义。

## F1. quarkdown 输出 PDF 的文件名由 `.docname` 决定，而非源文件名

编译 `quarkdown compile <tmp.qd> -o <out_dir> --pdf` 后，输出目录里的 PDF 文件名是
`.docname` 的值（特殊字符替换为 `-`），例如 `.docname {Probe Doc}` → `Probe-Doc.pdf`；
中文标题则原样保留（`测试标题` → `测试标题.pdf`）。

**影响**：md2pdf 脚本不能假设输出文件名，须在编译后在输出目录内 glob `*.pdf` 再移动到
目标路径（脚本 `find_pdf()`）。

**复现**：`quarkdown compile` 任意含 `.docname {Probe Doc}` 的 .qd，`ls <out_dir>` 可见
`Probe-Doc.pdf`。

## F2. `quarkdown compile --strict` 出错时退出码不是 1，而是 67

严格模式下编译失败，quarkdown 返回 67（同时 stdout/stderr 打出
`An error occurred while in strict mode (error code 67)` + Java 堆栈）。

**影响**：md2pdf 把"任何非 0 退出码"统一映射为自己的退出码 2（编译失败），不依赖
具体的 67。

**复现**：对含 `.foo {x}`（未定义函数）的 .qd 执行 `quarkdown compile x.qd --strict`，
`echo $?` 输出 67。

## F3. `paged` 文档类型默认开启标题自动编号，必须显式关闭

`.doctype {paged}` 在未配置 `.numbering` 时，标题默认按 `1.1.1` 编号（见 numbering.qd
"Default formats"）。因此"编号默认关闭（方案 B）"**不能**靠省略 `.numbering` 实现，必须
生成 `.extend {heading}` + `.super numbered:{no}` 才会真正关闭。

**影响**：md2pdf 在 `--numbered off`（默认）时总会输出至少一个 `.extend {heading}`
块加 `numbered:{no}`（§2.1/§2.2 的实现细节，与计划一致）。

**复现**：编译一个仅含 `.doctype {paged}` + `## 小节`（无任何 numbering 配置）的 .qd，
生成的 PDF 中该标题带自动编号。

## F4. `.font ... size:{12}pt` 与 `size:{12pt}` 均可编译

计划 §2.1 写作 `.font {<font>} size:{<size>}pt`，实测与 `size:{12pt}` 两种写法都通过
编译。脚本采用计划原文写法 `size:{<size>}pt`。

**复现**：分别用两种写法编译含 `.font {Noto Serif CJK SC} size:{12}pt` / 
`size:{12pt}` 的最小 .qd，均成功。

## F5. 测试文件位置沿用仓库现有体系，未建 `skills/quarkdown/tests/`

计划 §7 建议 `skills/quarkdown/tests/` 下用 pytest，但注明"如仓库已有测试体系则沿用"。
仓库已有根级 `tests/`（conftest.py + fixtures/）。同时 §9 验收命令直接引用
`tests/fixtures/sample.md`。因此：

- fixture：`tests/fixtures/sample.md`
- 测试：`tests/test_md2pdf.py`（自包含 subprocess helper，不改动 conftest.py）
- 新增 `pytest.ini` 注册 `integration` 标记（PDF 编译测试较慢，Chromium 起服务 ~5s）

**复现**：`python -m pytest -q` 在仓库根运行，44 例全绿（含 2 例 integration）。

## F6. 缺失 `quarkdown` 命令 / 编译超时的退出码选择

计划 §3.4 只定义 0–3 四个退出码，未定义"工具缺失/超时"。脚本把这两种情况都归入
编译失败（退出码 2），并在错误信息中说明原因，避免引入新退出码。

**复现**：`PATH` 中移除 quarkdown 后运行脚本，输出"未找到 quarkdown 命令"，退出码 2。

## F7. docx 引用未安装字体时 `quarkdown c --strict` 校验失败

`extract_docx_style.py`（docx → qd 模板）计划 §1 要求生成后校验必须通过。实测
Quarkdown 的 `.font {字体名}` 通过 AWT `GraphicsEnvironment` 按**精确字体族名**解析
系统字体：本机安装了 Times New Roman / Noto Serif CJK SC / 华文宋体 / 国标宋体 等，
但常见的 docx 字体名（宋体 / SimSun / 黑体 / SimHei / 仿宋 / Arial）未安装，
`.font {宋体}` 编译报 `Media path cannot be resolved`（strict 模式退出码 66）。

**影响**：从引用未安装字体的 docx 提取模板时，脚本自带校验会失败（退出码 2，模板
仍已生成）。脚本新增 `--no-verify` 可跳过校验；提示用户装字体或用 `--dry-run` 只看
提取摘要。测试 fixture 刻意使用已安装字体（Times New Roman + 华文宋体）保证验收通过。

**复现**：`printf '.docname {P}\n.doctype {paged}\n.font {宋体}\n# t\n' > /tmp/x.qd && quarkdown c /tmp/x.qd --strict --out /tmp/x` → `Media path cannot be resolved: 宋体`。

## F8. 字体 fallback 链：第二个 `.font` 带 `heading:` 才覆盖标题 CJK

`.font {Times New Roman} heading:{Times New Roman}` + `.font {华文宋体}` 时，生成的
CSS 中标题字体族只有 Times New Roman（CJK 无法回退到华文宋体）；第二个 `.font` 加上
`heading:{国标黑体}` 后，标题字体族变为 `国标黑体, Times New Roman`。因此脚本对
标题 CJK 与正文 CJK 不同的 docx，第二个 `.font` 需要带 `heading:` 参数。

**复现**：编译上述两种 `.font` 组合，检查输出 `index.html` 的
`--qd-heading-custom-font` 值。

## F9. `.numbering` 层级串按深度位置映射，标题文本的编号前缀保留尾随分隔符

`.numbering - headings: 1.1.1` 实测：H1 → `1`、H2 → `1.1`、H3 → `1.1.1`（深度与
格式串字符一一对应，见 A3 探针 H4 无编号）。单级 `1.` 链时 H1 渲染为 `1.`（尾随
分隔符保留）；`1、1` 链时 H1 为 `1`（分隔符只在层间出现）。脚本据此构造链：取最深
参与层的前缀结构，逐层校验"下一级前缀 = 上一级前缀 + 分隔符 + 计数器"，否则方案 B。

**复现**：分别编译 `- headings: 1.` 与 `- headings: 1、1` 的 .qd，查 HTML `data-location`。

## F10. docx 标题无显式 run 属性（加粗来自样式表）时按"常规"处理

计划 §3 约定"遍历实际元素，不读样式定义表"。python-docx `add_heading` 的加粗来自
Heading 样式而非 run 的 `<w:b/>`，因此不显式设 `run.font.bold` 的标题会被判定为
"常规"。fixture 与说明均明确要求标题/正文显式设置 run 属性。

**复现**：`doc.add_heading('x', 1)` 不加粗 → 提取摘要显示 H1 常规。

## F11. 段落块 `.extend {paragraph}` 只聚合多数派样式，避免单 run 样式污染

提取正文 run 级 bold/italic/underline/color 时，若仅个别 run 带样式（如一个红色
下划线强调），按字符权重多数派判定不通过则该属性不进 `.extend {paragraph}`，防止
整篇正文被误设为加粗/下划线/变色。

**复现**：fixture mixed_numbering.docx 含一个红色下划线 run，生成的模板
`.extend {paragraph}` 仅含 `textalignment:{justify}`。

## F12. 测试沿用根级 `tests/` 而非 `skills/quarkdown/tests/`

计划 §7 建议 `skills/quarkdown/tests/`，但注明"如仓库已有测试体系则沿用"（F5 同款
约定）。本次沿用根级 `tests/`：
- fixture：`tests/fixtures/mixed_numbering.docx`、`dec_numbering.docx`、
  `gen_docx.py`（另附 `make_docx_fixtures.py` 生成器，便于重建）
- 测试：`tests/test_extract_docx_style.py`（unit 编号决策树 + subprocess 端到端；
  编译校验用例标 `integration`）
- 新增 `pytest.ini` 的 `integration` 标记沿用既有注册，未改动。

**复现**：`python -m pytest -q` 全绿（85 例，含新增 41 例）。
