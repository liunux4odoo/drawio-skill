#!/usr/bin/env python3
"""md2pdf: convert a plain Markdown file to PDF via a generated Quarkdown template.

Pure Python standard library. The helper builds a temporary Quarkdown template
header around the Markdown source, compiles it to PDF with the `quarkdown` CLI
(whose wrapper already handles the headless JVM / Chromium setup), moves the PDF
to the target path, and cleans up. The source Markdown file is never modified.

Output is deterministic: no timestamps or random values in the generated
template or the report; the temporary file path is a hash of the source path and
the resolved parameters.

Exit codes:
    0  success (PDF generated)
    1  input/argument error (missing file, invalid parameter)
    2  compilation failure (quarkdown reported an error)
    3  output move failure (target path not writable)

Usage:
    python3 md2pdf.py input.md [-o output.pdf] [--title ...] [--theme ...]
        [--page ...] [--font ...] [--size 12] [--lineheight ...]
        [--spacing ...] [--indent ...] [--heading-color ...]
        [--numbered on|off] [--heading-style 1:large,2:medium] [--dry-run]
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys

EXIT_OK = 0
EXIT_INPUT_ERROR = 1
EXIT_COMPILE_ERROR = 2
EXIT_MOVE_ERROR = 3

PAGE_SIZES = {
    *[f"A{i}" for i in range(11)],
    *[f"B{i}" for i in range(6)],
    "letter",
    "legal",
    "ledger",
}
FONTSIZE_ENUMS = ("tiny", "small", "normal", "medium", "large", "larger", "huge")
QUARKDOWN_CMD = "quarkdown"
PREVIEW_LINES = 5
COMPILE_TIMEOUT = 300

H1_RE = re.compile(r"^#\s+(.+?)\s*$")
VALID_HEADING_COLOR_RE = re.compile(r"^[A-Za-z0-9#_\-]+$")
CHARSET_OK_RE = re.compile(r"^[^{}\r\n]+$")


class Md2PdfError(Exception):
    """Raised for user-facing errors; carries the exit code to use."""

    def __init__(self, message: str, code: int):
        super().__init__(message)
        self.code = code


def positive_float(text: str, name: str) -> float:
    try:
        value = float(text)
    except ValueError:
        raise Md2PdfError(f"--{name} 参数 '{text}' 不是合法数字", EXIT_INPUT_ERROR)
    if value <= 0:
        raise Md2PdfError(f"--{name} 参数必须为正数，得到 {value}", EXIT_INPUT_ERROR)
    return value


def nonnegative_float(text: str, name: str) -> float:
    try:
        value = float(text)
    except ValueError:
        raise Md2PdfError(f"--{name} 参数 '{text}' 不是合法数字", EXIT_INPUT_ERROR)
    if value < 0:
        raise Md2PdfError(f"--{name} 参数不能为负数，得到 {value}", EXIT_INPUT_ERROR)
    return value


def charset_ok(text: str, name: str) -> None:
    if not CHARSET_OK_RE.match(text or ""):
        raise Md2PdfError(
            f"--{name} 参数 '{text}' 含非法字符（不能包含 {{ }} 或换行）", EXIT_INPUT_ERROR
        )


def parse_heading_style(text: str) -> dict[int, str]:
    """Parse '--heading-style 1:large,2:medium' into {depth: fontsize-enum}."""
    result: dict[int, str] = {}
    if not text:
        return result
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if ":" not in part:
            raise Md2PdfError(
                f"--heading-style 段 '{part}' 缺少 ':'（格式 N:枚举，如 1:large）",
                EXIT_INPUT_ERROR,
            )
        depth_s, enum = (s.strip() for s in part.split(":", 1))
        if not depth_s.isdigit() or int(depth_s) < 1:
            raise Md2PdfError(
                f"--heading-style 级别 '{depth_s}' 非法（需为正整数）", EXIT_INPUT_ERROR
            )
        if enum not in FONTSIZE_ENUMS:
            raise Md2PdfError(
                f"--heading-style 字号 '{enum}' 非法（需为 {', '.join(FONTSIZE_ENUMS)}）",
                EXIT_INPUT_ERROR,
            )
        result[int(depth_s)] = enum
    return result


def first_h1(text: str) -> str | None:
    """Return the text of the first level-1 heading, or None."""
    for line in text.splitlines():
        m = H1_RE.match(line)
        if m:
            return re.sub(r"[{}]", "", m.group(1).strip())
    return None


def sanitize_title(title: str) -> str:
    title = re.sub(r"[{}]", "", title).strip()
    title = re.sub(r"^[*_`]+|[*_`]+$", "", title).strip()
    return title or "Untitled"


def default_title(md_text: str, source_path: str) -> str:
    heading = first_h1(md_text)
    if heading:
        return heading
    stem = os.path.splitext(os.path.basename(source_path))[0]
    return stem or "Untitled"


def build_extend_blocks(args: argparse.Namespace) -> list[str]:
    """Generate `.extend {heading}` blocks per §2 of the development plan.

    Numbering defaults to off: a `numbered:{no}` is emitted unless `--numbered
    on` was requested. `--heading-color` and `--heading-style` add per-block
    foreground / fontsize overrides; otherwise one block applies to all depths.
    """
    blocks: list[str] = []
    styles = parse_heading_style(args.heading_style)
    color = args.heading_color
    numbered_off = args.numbered == "off"

    if styles:
        if numbered_off:
            params = ["numbered:{no}"]
            if color:
                params.append(f"foreground:{{{color}}}")
            blocks.append(f".extend {{heading}}\n    .super {' '.join(params)}")
        for depth in sorted(styles):
            params = []
            if color:
                params.append(f"foreground:{{{color}}}")
            params.append(f"fontsize:{{{styles[depth]}}}")
            blocks.append(
                f".extend {{heading}} where:{{depth: .depth::equals {{{depth}}}}}\n"
                f"    .super {' '.join(params)}"
            )
    elif numbered_off or color:
        params = ["numbered:{no}"] if numbered_off else []
        if color:
            params.append(f"foreground:{{{color}}}")
        blocks.append(f".extend {{heading}}\n    .super {' '.join(params)}")
    return blocks


def build_template_lines(
    args: argparse.Namespace, md_text: str, source_path: str
) -> list[str]:
    """Build the template header lines in the fixed §3.1 order.

    If --template is provided, emit `.include {path}` followed by override
    directives. Override items come from --override if given, otherwise
    auto-inferred from explicitly passed non-default parameters.
    Otherwise emit the full inline template per §3.1 of the development plan.
    """
    # Template mode: include external template + optional overrides
    if args.template:
        template_path = os.path.abspath(args.template)
        if not os.path.isfile(template_path):
            raise Md2PdfError(
                f"--template 文件不存在：{template_path}", EXIT_INPUT_ERROR
            )
        lines = [f".include {{{template_path}}}"]

        # Determine override items: explicit --override or auto-inferred
        if args.override:
            override_items = {item.strip() for item in args.override.split(",") if item.strip()}
        else:
            override_items = _infer_override_items(args)

        if override_items:
            lines.extend(build_override_lines(args, md_text, source_path, override_items))
        return lines

    # Inline mode (original behavior)
    title = sanitize_title(args.title or default_title(md_text, source_path))
    lines = [
        f".docname {{{title}}}",
        ".doctype {paged}",
        f".doclang {{{args.lang}}}",
        f".theme {{{args.theme}}} layout:{{latex}}",
        f".pageformat size:{{{args.page}}} margin:{{2cm}}",
        f".font {{{args.font}}} size:{{{args.size}}}pt",
        (
            f".paragraphstyle lineheight:{{{args.lineheight}}} "
            f"spacing:{{{args.spacing}}} indent:{{{args.indent}}}"
        ),
    ]
    if args.numbered == "on":
        lines.append(".numbering")
        lines.append("    - headings: 1.1.1")
    lines.extend(build_extend_blocks(args))
    return lines


def _infer_override_items(args: argparse.Namespace) -> set[str]:
    """Infer override items from args that differ from defaults.

    Only called when --template is given but --override is NOT given.
    User explicitly passing a non-default value signals intent to override.
    """
    inferred: set[str] = set()
    for key, default in OVERRIDE_DEFAULTS.items():
        arg_key = key.replace("_", "-")
        # Map back to argparse attribute name
        attr = key
        value = getattr(args, attr, None)
        if value != default:
            inferred.add(arg_key)
    return inferred


def build_override_lines(
    args: argparse.Namespace,
    md_text: str,
    source_path: str,
    override_items: set[str],
) -> list[str]:
    """Generate override directives for template mode.

    Quarkdown applies directives in order; directives after .include override
    those from the included template. Only emit overrides for items explicitly
    listed in --override (or auto-inferred when --override omitted).
    """
    lines: list[str] = []
    title = sanitize_title(args.title or default_title(md_text, source_path))

    if "title" in override_items:
        lines.append(f".docname {{{title}}}")
    if "lang" in override_items:
        lines.append(f".doclang {{{args.lang}}}")
    if "theme" in override_items:
        lines.append(f".theme {{{args.theme}}} layout:{{latex}}")
    if "page" in override_items:
        lines.append(f".pageformat size:{{{args.page}}} margin:{{2cm}}")
    if "font" in override_items or "size" in override_items:
        # font and size go together in .font directive
        lines.append(f".font {{{args.font}}} size:{{{args.size}}}pt")
    if any(k in override_items for k in ("lineheight", "spacing", "indent")):
        lh = args.lineheight if "lineheight" in override_items else "1.6"
        sp = args.spacing if "spacing" in override_items else "0.5"
        ind = args.indent if "indent" in override_items else "0"
        lines.append(
            f".paragraphstyle lineheight:{{{lh}}} spacing:{{{sp}}} indent:{{{ind}}}"
        )
    if "numbered" in override_items:
        if args.numbered == "on":
            lines.append(".numbering")
            lines.append("    - headings: 1.1.1")
        else:
            # Explicitly disable numbering from template
            lines.append(".extend {heading}")
            lines.append("    .super numbered:{no}")
    if any(k in override_items for k in ("heading-style", "heading-color")):
        # Rebuild heading extend blocks with override values
        styles = parse_heading_style(args.heading_style) if "heading-style" in override_items else {}
        color = args.heading_color if "heading-color" in override_items else ""
        numbered_off = args.numbered == "off" if "numbered" in override_items else False

        if styles:
            if numbered_off:
                params = ["numbered:{no}"]
                if color:
                    params.append(f"foreground:{{{color}}}")
                lines.append(f".extend {{heading}}\n    .super {' '.join(params)}")
            for depth in sorted(styles):
                params = []
                if color:
                    params.append(f"foreground:{{{color}}}")
                params.append(f"fontsize:{{{styles[depth]}}}")
                lines.append(
                    f".extend {{heading}} where:{{depth: .depth::equals {{{depth}}}}}\n"
                    f"    .super {' '.join(params)}"
                )
        elif numbered_off or color:
            params = ["numbered:{no}"] if numbered_off else []
            if color:
                params.append(f"foreground:{{{color}}}")
            lines.append(f".extend {{heading}}\n    .super {' '.join(params)}")
    return lines


def params_summary(args: argparse.Namespace) -> str:
    parts = []
    if args.template:
        parts.append(f"--template {os.path.basename(args.template)}")
        if args.override:
            parts.append(f"--override {args.override}")
    else:
        parts.extend([
            f"--theme {args.theme}",
            f"--page {args.page}",
            f"--font {args.font}",
            f"size {args.size}pt",
            f"--lineheight {args.lineheight}",
            f"--spacing {args.spacing}",
            f"--indent {args.indent}",
            f"--numbered {args.numbered}",
        ])
        if args.heading_color:
            parts.append(f"--heading-color {args.heading_color}")
        if args.heading_style:
            parts.append(f"--heading-style {args.heading_style}")
        if args.title:
            parts.append(f"--title {args.title}")
    return " ".join(parts)


def temp_paths(source_path: str, args: argparse.Namespace) -> tuple[str, str]:
    """Deterministic temp paths (hash of source path + resolved parameters)."""
    canonical = "|".join(
        [
            os.path.abspath(source_path),
            str(args.title or ""),
            str(args.lang),
            str(args.theme),
            str(args.page),
            str(args.font),
            str(args.size),
            str(args.lineheight),
            str(args.spacing),
            str(args.indent),
            str(args.heading_color or ""),
            str(args.numbered),
            str(args.heading_style or ""),
            str(args.template or ""),
            str(args.override or ""),
        ]
    )
    h = hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:8]
    return f"/tmp/md2pdf-{h}.qd", f"/tmp/md2pdf-{h}-out"


def dot_line_hints(md_text: str, max_hints: int = 5) -> list[str]:
    """Locate lines that Quarkdown would parse as function calls."""
    hints: list[str] = []
    for i, line in enumerate(md_text.splitlines(), 1):
        if line.startswith("."):
            hints.append(f"  第 {i} 行 `{line.strip()}`：以 `.` 开头会被当作 Quarkdown 函数调用")
            if len(hints) >= max_hints:
                break
    return hints


def pdf_pages(path: str) -> int:
    """Best-effort page count from uncompressed PDF objects (0 if undetectable)."""
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError:
        return 0
    return len(re.findall(rb"/Type\s*/Page[^s]", data))


def human_size(num_bytes: int) -> str:
    if num_bytes >= 1024 * 1024:
        return f"{num_bytes / 1024 / 1024:.1f}MB"
    return f"{max(1, round(num_bytes / 1024))}KB"


def pdf_summary(path: str) -> str:
    size = human_size(os.path.getsize(path))
    pages = pdf_pages(path)
    return f"{size}, {pages}页" if pages else size


def compile_pdf(tmp_qd: str, out_dir: str, md_text: str) -> None:
    cmd = [QUARKDOWN_CMD, "compile", tmp_qd, "-o", out_dir, "--pdf", "--strict"]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=COMPILE_TIMEOUT
        )
    except FileNotFoundError:
        raise Md2PdfError(
            "编译失败：未找到 `quarkdown` 命令（请确认其已在 PATH 中）", EXIT_COMPILE_ERROR
        )
    except subprocess.TimeoutExpired:
        raise Md2PdfError(
            f"编译失败：quarkdown 超过 {COMPILE_TIMEOUT}s 未完成", EXIT_COMPILE_ERROR
        )
    if proc.returncode != 0:
        detail = (proc.stdout or "") + (proc.stderr or "")
        detail_lines = [ln for ln in detail.splitlines() if ln.strip()][:10]
        message = [f"md2pdf: 编译失败（quarkdown 退出码 {proc.returncode}）"]
        hints = dot_line_hints(md_text)
        if hints:
            message.append("  可能原因：以下行以 `.` 开头，会被 Quarkdown 当作函数调用：")
            message.extend(hints)
        if detail_lines:
            message.append("  quarkdown 原始输出（前 10 行）：")
            message.extend(f"    {ln}" for ln in detail_lines)
        raise Md2PdfError("\n".join(message), EXIT_COMPILE_ERROR)
    if not any(
        f.lower().endswith(".pdf")
        for f in os.listdir(out_dir)
    ):
        raise Md2PdfError(
            "编译失败：quarkdown 未在输出目录生成任何 PDF 文件", EXIT_COMPILE_ERROR
        )


def find_pdf(out_dir: str) -> str:
    for f in os.listdir(out_dir):
        if f.lower().endswith(".pdf"):
            return os.path.join(out_dir, f)
    return ""


def move_pdf(src_pdf: str, target: str) -> None:
    try:
        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
        shutil.move(src_pdf, target)
    except OSError as exc:
        raise Md2PdfError(
            f"PDF 移动失败：无法写入目标路径 {target}（{exc}）", EXIT_MOVE_ERROR
        )


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(EXIT_INPUT_ERROR, f"{self.prog}: error: {message}\n")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = _Parser(
        prog="md2pdf",
        description="把纯 Markdown 文件转换为 PDF（生成临时 Quarkdown 模板，不修改源文件）。",
    )
    parser.add_argument("input", metavar="input.md", help="源 Markdown 文件")
    parser.add_argument("-o", "--output", metavar="output.pdf",
                        help="输出 PDF 路径（默认：与源文件同目录同名 .pdf）")
    parser.add_argument("--title", help="文档标题（默认：md 第一个 `#` 标题或文件名）")
    parser.add_argument("--lang", default="zh-CN", help="文档语言（默认 zh-CN）")
    parser.add_argument("--theme", default="paperwhite", help="Quarkdown 主题（默认 paperwhite）")
    parser.add_argument("--page", default="A4",
                        help="页面尺寸 A0-A10 / B0-B5 / letter / legal / ledger（默认 A4）")
    parser.add_argument("--font", default="Noto Serif CJK SC", help="主字体（默认 Noto Serif CJK SC）")
    parser.add_argument("--size", default="12", help="全局基准字号，pt（默认 12）")
    parser.add_argument("--lineheight", default="1.6", help="行距系数（默认 1.6）")
    parser.add_argument("--spacing", default="0.5", help="段距系数（默认 0.5）")
    parser.add_argument("--indent", default="0", help="首行缩进系数（默认 0）")
    parser.add_argument("--heading-color", default="", help="标题颜色，如 navy 或 #112233")
    parser.add_argument("--numbered", choices=["on", "off"], default="off",
                        help="是否启用自动编号（默认 off；on 时标题文本不得含编号前缀）")
    parser.add_argument("--heading-style", default="",
                        help="按级别设置标题字号枚举，如 1:large,2:medium")
    parser.add_argument("--dry-run", action="store_true",
                        help="只打印生成的模板头与拼接预览，不编译")
    parser.add_argument("--template", metavar="template.qd",
                        help="使用外部 Quarkdown 模板（.include 该文件），忽略内置模板参数")
    parser.add_argument("--override", metavar="ITEMS",
                        help="template 模式下覆盖的设置项，逗号分隔；可选：title,lang,theme,page,font,size,lineheight,spacing,indent,numbered,heading-style,heading-color")
    return parser.parse_args(argv)


OVERRIDE_CHOICES = {
    "title", "lang", "theme", "page", "font", "size",
    "lineheight", "spacing", "indent", "numbered",
    "heading-style", "heading-color",
}

# Default values for each overridable parameter (must match parse_args defaults)
OVERRIDE_DEFAULTS = {
    "title": None,              # auto-detected from markdown
    "lang": "zh-CN",
    "theme": "paperwhite",
    "page": "A4",
    "font": "Noto Serif CJK SC",
    "size": "12",
    "lineheight": "1.6",
    "spacing": "0.5",
    "indent": "0",
    "heading_color": "",
    "numbered": "off",
    "heading_style": "",
}

# Meta args that should never be auto-inferred as overrides
META_ARGS = {"dry_run", "output", "template", "override", "input"}


def validate(args: argparse.Namespace) -> None:
    if not os.path.isfile(args.input):
        raise Md2PdfError(f"输入文件不存在：{args.input}", EXIT_INPUT_ERROR)
    if args.page not in PAGE_SIZES:
        raise Md2PdfError(
            f"--page 参数 '{args.page}' 非法（需为 A0-A10 / B0-B5 / letter / legal / ledger）",
            EXIT_INPUT_ERROR,
        )
    positive_float(args.size, "size")
    nonnegative_float(args.lineheight, "lineheight")
    nonnegative_float(args.spacing, "spacing")
    nonnegative_float(args.indent, "indent")
    if args.heading_color and not VALID_HEADING_COLOR_RE.match(args.heading_color):
        raise Md2PdfError(
            f"--heading-color 参数 '{args.heading_color}' 非法（需为颜色名或 #rrggbb）",
            EXIT_INPUT_ERROR,
        )
    for name, value in (
        ("lang", args.lang),
        ("theme", args.theme),
        ("font", args.font),
    ):
        charset_ok(value, name)
    parse_heading_style(args.heading_style)
    out = args.output or os.path.splitext(args.input)[0] + ".pdf"
    if os.path.abspath(out) == os.path.abspath(args.input):
        raise Md2PdfError(
            f"输出路径与源文件相同：{out}（源文件不可被覆盖）", EXIT_INPUT_ERROR
        )

    # Validate --override items
    if args.override:
        for item in args.override.split(","):
            item = item.strip()
            if item and item not in OVERRIDE_CHOICES:
                raise Md2PdfError(
                    f"--override 项 '{item}' 非法（可选：{', '.join(sorted(OVERRIDE_CHOICES))}）",
                    EXIT_INPUT_ERROR,
                )

    # Template file existence is checked in build_template_lines


def read_md(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except (OSError, UnicodeDecodeError) as exc:
        raise Md2PdfError(f"无法读取源文件 {path}（{exc}）", EXIT_INPUT_ERROR)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    args = parse_args(argv)
    try:
        validate(args)
        md_text = read_md(args.input)
        header = build_template_lines(args, md_text, args.input)
    except Md2PdfError as exc:
        print(exc, file=sys.stderr)
        return exc.code

    if args.dry_run:
        preview = [ln for ln in md_text.splitlines() if ln.strip()][:PREVIEW_LINES]
        print("md2pdf: dry-run（不编译）")
        print("模板头:")
        print("\n".join(header))
        print(f"拼接预览（前 {PREVIEW_LINES} 行）:")
        print("\n".join(preview))
        return EXIT_OK

    tmp_qd, out_dir = temp_paths(args.input, args)
    try:
        os.makedirs(out_dir, exist_ok=True)
        with open(tmp_qd, "w", encoding="utf-8") as fh:
            fh.write("\n".join(header) + "\n\n" + md_text.rstrip("\n") + "\n")
        compile_pdf(tmp_qd, out_dir, md_text)
        target = args.output or os.path.splitext(args.input)[0] + ".pdf"
        move_pdf(find_pdf(out_dir), target)
    except Md2PdfError as exc:
        print(exc, file=sys.stderr)
        return exc.code
    finally:
        for path in (tmp_qd, out_dir):
            try:
                if os.path.isdir(path):
                    shutil.rmtree(path, ignore_errors=True)
                elif os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass

    print("md2pdf: 成功")
    print(f"  源文件:   {os.path.abspath(args.input)}")
    print(f"  模板头:   {tmp_qd}（已清理）")
    print(f"  PDF:      {os.path.abspath(target)}（{pdf_summary(target)}）")
    print(f"  参数:     {params_summary(args)}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
