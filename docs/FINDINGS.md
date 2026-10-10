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
