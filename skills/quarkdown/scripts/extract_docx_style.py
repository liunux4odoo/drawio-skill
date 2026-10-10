#!/usr/bin/env python3
"""Extract styles from a .docx (or a .py script that generates one) into a
reusable Quarkdown (.qd) template definition.

Pure Python standard library (zipfile + xml.etree).  In the "input is a .py
generator script" mode the script is executed in a throwaway temp directory
after an AST safety scan, and the resulting .docx is parsed the same way.

Output is deterministic: no timestamps or random values in the generated
template or report; the temp paths are cleaned up.

Exit codes:
    0  success (template generated and, unless --no-verify/--dry-run, verified)
    1  input/argument error (missing file, parse failure, risky .py script)
    2  output/file error (unwritable output, quarkdown verification failed)

Usage:
    python3 extract_docx_style.py <input.docx|input.py> [-o output.qd]
        [--heading-levels 1-3] [--dry-run] [--no-verify]
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
import xml.etree.ElementTree as ET

EXIT_OK = 0
EXIT_INPUT_ERROR = 1
EXIT_OUTPUT_ERROR = 2

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
DC_NS = "http://purl.org/dc/elements/1.1/"
W = f"{{{W_NS}}}"
DC = f"{{{DC_NS}}}"

QUARKDOWN_CMD = "quarkdown"
VERIFY_TIMEOUT = 300
PY_TIMEOUT = 60
DEFAULT_BODY_SIZE = 12.0

FONTSIZE_ENUMS = (
    ("tiny", 0.5),
    ("small", 0.75),
    ("normal", 1.0),
    ("medium", 1.25),
    ("large", 1.5),
    ("larger", 2.0),
    ("huge", 3.0),
)

HEADING_STYLE_RE = re.compile(r"^(?:Heading|标题)\s*([1-6])$", re.IGNORECASE)
CJK_NUMERAL = "一二三四五六七八九十百千两零"
CJK_NUMERAL_RE = re.compile(rf"^[（(]?第?[{CJK_NUMERAL}]+[章节篇]?[）)、．.]?")
LATIN_RUN_RE = re.compile(r"\d+|[a-zA-Z]+")
HEX_COLOR_RE = re.compile(r"^[0-9a-fA-F]{6}$")

# ---- safety scan for the .py generator input --------------------------------

FORBIDDEN_IMPORTS = {
    "subprocess", "socket", "requests", "urllib", "urllib.request", "urllib2",
    "http", "http.client", "ftplib", "smtplib", "telnetlib", "aiohttp",
    "httpx", "shutil",
}
DANGEROUS_ATTRS = {
    "system", "popen", "remove", "unlink", "rmdir", "chdir", "makedirs",
    "mkdir", "rmtree", "move", "replace", "kill", "terminate", "run",
    "Popen", "call", "check_call", "check_output", "connect", "urlopen",
    "Request", "send", "recv",
}
DANGEROUS_BUILTINS = {"eval", "exec", "compile", "__import__", "input", "breakpoint"}
SHELL_PATTERNS = (
    re.compile(r"\brm\b"),
    re.compile(r"\brm\s+-[a-z]"),
    re.compile(r"\bdeltree\b"),
    re.compile(r"\bmove\s+/"),
    re.compile(r">\s*/"),
)


def check_script_safety(source: str) -> list[str]:
    """Return a list of safety findings; empty means the script is acceptable."""
    findings: list[str] = []
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [f"脚本语法错误: {exc}"]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if alias.name in FORBIDDEN_IMPORTS or root in FORBIDDEN_IMPORTS:
                    findings.append(f"禁止导入模块: {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.module and (
                node.module in FORBIDDEN_IMPORTS or node.module.split(".")[0] in FORBIDDEN_IMPORTS
            ):
                findings.append(f"禁止导入模块: {node.module}")
        elif isinstance(node, ast.Call):
            name = _call_name(node)
            if name in DANGEROUS_BUILTINS:
                findings.append(f"禁止调用: {name}")
            elif isinstance(node.func, ast.Attribute) and node.func.attr in DANGEROUS_ATTRS:
                findings.append(f"禁止调用: {_render(node.func)}")
            elif name == "open":
                path = _open_write_path(node)
                if path:
                    findings.append(f"禁止写文件: open({path!r}, 'w'|'a')")
            elif name in ("write_text", "write_bytes", "mkdir", "makedirs", "unlink",
                          "save", "write"):
                path = _first_string_arg(node)
                if path and (os.path.isabs(path) or ".." in path):
                    findings.append(f"禁止写绝对/越界路径: {name}({path!r})")
    for pat in SHELL_PATTERNS:
        m = pat.search(source)
        if m:
            findings.append(f"疑似 shell/危险命令模式: {m.group(0)!r}")
    return findings


def _call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _render(node: ast.AST) -> str:
    return ast.unparse(node) if hasattr(ast, "unparse") else "?"


def _first_string_arg(node: ast.Call) -> str | None:
    for arg in node.args:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            return arg.value
    return None


def _open_write_path(node: ast.Call) -> str | None:
    if len(node.args) < 2:
        return None
    mode = node.args[1]
    if not (isinstance(mode, ast.Constant) and isinstance(mode.value, str)):
        return None
    if not any(ch in mode.value for ch in "waxb"):
        return None
    path = node.args[0]
    if isinstance(path, ast.Constant) and isinstance(path.value, str):
        return path.value
    return None


# ---- docx parsing -----------------------------------------------------------

class Run:
    __slots__ = ("text", "font_ascii", "font_east", "size_pt", "bold", "italic",
                 "underline", "color")

    def __init__(self, text="", font_ascii=None, font_east=None, size_pt=None,
                 bold=None, italic=None, underline=None, color=None):
        self.text = text
        self.font_ascii = font_ascii
        self.font_east = font_east
        self.size_pt = size_pt
        self.bold = bold
        self.italic = italic
        self.underline = underline
        self.color = color


class Paragraph:
    __slots__ = ("text", "style", "outline_level", "alignment", "space_before",
                 "space_after", "line_ratio", "line_exact_pt", "first_line",
                 "has_numpr", "runs")

    def __init__(self):
        self.text = ""
        self.style = None
        self.outline_level = None
        self.alignment = None
        self.space_before = 0.0
        self.space_after = 0.0
        self.line_ratio = None
        self.line_exact_pt = None
        self.first_line = 0.0
        self.has_numpr = False
        self.runs: list[Run] = []


def _val(elem: ET.Element | None, name: str) -> str | None:
    if elem is None:
        return None
    v = elem.get(f"{W}{name}")
    if v is None:
        v = elem.get(name)
    return v


def _twips_to_pt(twips: str | None) -> float | None:
    if twips is None:
        return None
    try:
        return float(twips) / 20.0
    except ValueError:
        return None


def _half_pts_to_pt(val: str | None) -> float | None:
    if val is None:
        return None
    try:
        return float(val) / 2.0
    except ValueError:
        return None


def _bool_attr(elem: ET.Element | None) -> bool | None:
    if elem is None:
        return None
    v = _val(elem, "val")
    if v is None or v in ("true", "1", "on"):
        return True
    if v in ("false", "0", "off"):
        return False
    return True


def _parse_rpr(rpr: ET.Element | None, run: Run) -> None:
    if rpr is None:
        return
    rfonts = rpr.find(f"{W}rFonts")
    if rfonts is not None:
        run.font_ascii = _val(rfonts, "ascii") or _val(rfonts, "hAnsi")
        run.font_east = _val(rfonts, "eastAsia")
    run.size_pt = _half_pts_to_pt(_val(rpr.find(f"{W}sz"), "val")) if rpr.find(f"{W}sz") is not None else None
    run.bold = _bool_attr(rpr.find(f"{W}b"))
    run.italic = _bool_attr(rpr.find(f"{W}i"))
    u = rpr.find(f"{W}u")
    if u is not None and _val(u, "val") not in (None, "none", "0", "false"):
        run.underline = True
    color = rpr.find(f"{W}color")
    if color is not None:
        val = _val(color, "val")
        if val and val.lower() != "auto" and HEX_COLOR_RE.match(val):
            run.color = val.upper()
        elif _val(color, "themeColor"):
            run.color = None


def _iter_runs(p: Paragraph, para_rpr: ET.Element | None, container: ET.Element) -> None:
    for r in container.findall(f"{W}r"):
        rpr = r.find(f"{W}rPr")
        run = Run()
        if rpr is not None:
            _parse_rpr(rpr, run)
        elif para_rpr is not None:
            _parse_rpr(para_rpr, run)
        texts = r.findall(f"{W}t")
        run.text = "".join((t.text or "") for t in texts)
        if run.text or run.font_ascii or run.size_pt:
            p.runs.append(run)
            p.text += run.text
    for h in container.findall(f"{W}hyperlink"):
        _iter_runs(p, para_rpr, h)


def _heading_depth(style: str | None, outline_level: str | None) -> int | None:
    if style:
        if style.lower() == "title":
            return 0
        m = HEADING_STYLE_RE.match(style)
        if m:
            return int(m.group(1))
    if outline_level is not None:
        try:
            lvl = int(outline_level)
        except ValueError:
            return None
        if 0 <= lvl <= 5:
            return lvl + 1
    return None


def parse_docx(path: str) -> tuple[list[Paragraph], str | None]:
    """Parse a .docx file. Returns (paragraphs, title)."""
    title = None
    with zipfile.ZipFile(path) as zf:
        try:
            tree = ET.fromstring(zf.read("word/document.xml"))
        except KeyError:
            raise ValueError(f"不是有效的 docx（缺少 word/document.xml）: {path}")
        try:
            core = ET.fromstring(zf.read("docProps/core.xml"))
            dc = core.find(f"{DC}title")
            if dc is not None and dc.text and dc.text.strip():
                title = dc.text.strip()
        except (KeyError, ET.ParseError):
            title = None

    paragraphs: list[Paragraph] = []
    body = tree.find(f"{W}body")
    if body is None:
        return paragraphs, title
    for el in body:
        if el.tag != f"{W}p":
            continue
        p = Paragraph()
        ppr = el.find(f"{W}pPr")
        if ppr is not None:
            pstyle = ppr.find(f"{W}pStyle")
            p.style = _val(pstyle, "val")
            olvl = ppr.find(f"{W}outlineLvl")
            p.outline_level = _val(olvl, "val")
            jc = ppr.find(f"{W}jc")
            p.alignment = _val(jc, "val")
            spacing = ppr.find(f"{W}spacing")
            if spacing is not None:
                before = _twips_to_pt(_val(spacing, "before"))
                after = _twips_to_pt(_val(spacing, "after"))
                p.space_before = before or 0.0
                p.space_after = after or 0.0
                line = _val(spacing, "line")
                rule = _val(spacing, "lineRule")
                if line is not None and rule == "auto":
                    try:
                        p.line_ratio = float(line) / 240.0
                    except ValueError:
                        pass
                elif line is not None:
                    p.line_exact_pt = _twips_to_pt(line)
            ind = ppr.find(f"{W}ind")
            if ind is not None:
                first_line = _twips_to_pt(_val(ind, "firstLine"))
                first_chars = _val(ind, "firstLineChars")
                if first_chars is not None:
                    try:
                        p.first_line = float(first_chars) / 100.0
                    except ValueError:
                        p.first_line = first_line or 0.0
                else:
                    p.first_line = first_line or 0.0
            p.has_numpr = ppr.find(f"{W}numPr") is not None
            para_rpr = ppr.find(f"{W}rPr")
        else:
            para_rpr = None
        _iter_runs(p, para_rpr, el)
        if p.text.strip():
            paragraphs.append(p)
    return paragraphs, title


# ---- aggregation ------------------------------------------------------------

def _mode_count(items: list, weight_fn=None) -> tuple:
    if not items:
        return None, 0
    counts: dict = {}
    for item in items:
        key = item
        if weight_fn is not None:
            key = weight_fn(item)
        counts[key] = counts.get(key, 0) + 1
    best_key = max(counts, key=lambda k: (counts[k], -list(counts).index(k)))
    return best_key, counts[best_key]


def _weighted_mode(runs: list[Run], attr: str) -> tuple:
    counts: dict = {}
    total = 0.0
    for r in runs:
        value = getattr(r, attr)
        weight = max(1, len(r.text))
        total += weight
        if value is None:
            continue
        counts[value] = counts.get(value, 0.0) + weight
    if not counts:
        return None, 0
    best = max(counts, key=lambda k: (counts[k], -list(counts).index(k)))
    return best, counts[best]


def _color_majority(runs: list[Run]) -> str | None:
    """Return a color only when more than half of the body text uses it."""
    counts: dict = {}
    total = 0.0
    for r in runs:
        weight = max(1, len(r.text))
        total += weight
        color = r.color
        if color is None or color.lower() == "auto":
            continue
        counts[color] = counts.get(color, 0.0) + weight
    if not counts:
        return None
    best = max(counts, key=lambda k: (counts[k], -list(counts).index(k)))
    return best if counts[best] > total / 2 else None


def _bool_majority(runs: list[Run], attr: str) -> bool | None:
    """Return True/False when the property is (by char weight) predominantly set.

    Absence of the XML property counts as the Word default (False).  When no
    run sets the property to True at all, returns None (no information).
    """
    true_w = 0.0
    false_w = 0.0
    has_true = False
    for r in runs:
        v = getattr(r, attr)
        w = max(1, len(r.text))
        if v:
            has_true = True
            true_w += w
        else:
            false_w += w
    if not has_true:
        return None
    return true_w > false_w


def _format_ratio(pt: float | None, base: float) -> float | None:
    if pt is None or base <= 0:
        return None
    return pt / base


def nearest_enum(pt: float | None, base: float) -> str | None:
    ratio = _format_ratio(pt, base)
    if ratio is None:
        return None
    best_name, best_diff = "normal", abs(ratio - 1.0)
    for name, val in FONTSIZE_ENUMS:
        diff = abs(ratio - val)
        if diff < best_diff:
            best_name, best_diff = name, diff
    return best_name


def _round(v: float | None, ndigits: int = 2) -> float | None:
    if v is None:
        return None
    r = round(v, ndigits)
    return int(r) if float(r).is_integer() else r


# ---- numbering detection ----------------------------------------------------

def classify_counter(s: str) -> str | None:
    if re.fullmatch(r"\d+", s):
        return "1"
    if len(s) == 1:
        if s in "ivxlcdm":
            return "i"
        if s in "IVXLCDM":
            return "I"
        if s.islower():
            return "a"
        if s.isupper():
            return "A"
        return None
    if re.fullmatch(r"[ivxlcdm]{2,}", s):
        return "i"
    if re.fullmatch(r"[IVXLCDM]{2,}", s):
        return "I"
    return None


def detect_numbering(text: str) -> tuple[list | None, str]:
    """Detect the leading numbering prefix of a heading text.

    Returns (tokens, kind).  tokens is a list of ('counter', char) / ('fix',
    char) pairs, or None when the prefix is not usable.  kind is one of:
    'ok', 'chinese', 'unsupported', 'none'.
    """
    t = text.strip()
    if not t:
        return None, "none"
    if CJK_NUMERAL_RE.match(t):
        return None, "chinese"
    tokens: list = []
    has_counter = False
    i = 0
    n = len(t)
    while i < n:
        ch = t[i]
        if ch in "（(" or ch in "）)":
            tokens.append(("fix", ch))
            i += 1
            continue
        if ch in ".、．":
            tokens.append(("fix", ch))
            i += 1
            continue
        m = LATIN_RUN_RE.match(t, i)
        if m:
            s = m.group(0)
            c = classify_counter(s)
            if c is None:
                return None, "unsupported"
            tokens.append(("counter", c))
            has_counter = True
            i += len(s)
            continue
        break
    if not has_counter:
        return None, "none"
    if tokens and tokens[0][0] == "fix" and tokens[0][1] in ".、．":
        return None, "unsupported"
    return tokens, "ok"


def _extension(prev: list, cur: list) -> bool:
    if len(cur) <= len(prev):
        return False
    if cur[: len(prev)] != prev:
        return False
    return any(typ == "counter" for typ, _ in cur[len(prev):])


def build_numbering_chain(per_level: dict) -> tuple[str | None, str]:
    """per_level: {depth: (tokens, kind)} for heading depths present.

    Returns (chain, plan) where plan is 'A' or 'B'.

    Plan A requires every heading depth present in the document to carry a
    supported numbering prefix, contiguous from depth 1, with each deeper level
    extending the previous one.  A depth whose headings are unnumbered
    (kind 'none'), unsupported (Chinese numerals, mixed, numPr) forces plan B:
    Quarkdown would otherwise auto-number that depth.
    """
    depths = sorted(per_level)
    if not depths:
        return None, "B"
    if depths != list(range(1, depths[-1] + 1)):
        return None, "B"
    for d in depths:
        tokens, kind = per_level[d]
        if tokens is None or kind != "ok":
            return None, "B"
    tokens_by_depth = {d: per_level[d][0] for d in depths}
    prev = tokens_by_depth[1]
    for d in depths[1:]:
        cur = tokens_by_depth[d]
        if not _extension(prev, cur):
            return None, "B"
        prev = cur
    chain = "".join(v for _, v in prev)
    return chain, "A"


# ---- template generation ----------------------------------------------------

def _esc(text: str | None) -> str:
    if text is None:
        return ""
    return re.sub(r"[{}\r\n]", "", text)


def _color_hex(color: str | None) -> str | None:
    if not color:
        return None
    return f"#{color.lower()}"


def _align_qd(alignment: str | None) -> str | None:
    if alignment is None:
        return None
    return {"left": "start", "center": "center", "right": "end",
            "both": "justify", "justify": "justify", "distribute": "justify"}.get(alignment)


class Extraction:
    def __init__(self):
        self.title = None
        self.core_title = None
        self.docname = None
        self.base_size = DEFAULT_BODY_SIZE
        self.main_font = None
        self.main_font_east = None
        self.heading_font = None
        self.heading_font_east = None
        self.heading_styles: dict[int, dict] = {}
        self.all_heading_depths: list[int] = []
        self.line_ratio = None
        self.spacing = None
        self.indent = None
        self.alignment = None
        self.body_bold = None
        self.body_italic = None
        self.body_underline = None
        self.body_color = None
        self.numbering: dict[int, tuple] = {}
        self.plan = "B"
        self.chain = None
        self.numpr_levels: list[int] = []
        self.notes: list[str] = []


def _aggregate(paragraphs: list[Paragraph], heading_levels: set[int], core_title: str | None = None) -> Extraction:
    ex = Extraction()
    ex.core_title = core_title
    body: list[Paragraph] = []
    headings: dict[int, list[Paragraph]] = {}
    for p in paragraphs:
        depth = _heading_depth(p.style, p.outline_level)
        if depth is None or depth == 0:
            if depth == 0:
                if ex.title is None and p.text.strip():
                    ex.title = p.text.strip()
                headings.setdefault(0, []).append(p)
            else:
                body.append(p)
        else:
            headings.setdefault(depth, []).append(p)

    body_runs = [r for p in body for r in p.runs]
    body_size, _ = _weighted_mode(body_runs, "size_pt")
    if body_size:
        ex.base_size = body_size

    ex.main_font, _ = _weighted_mode(body_runs, "font_ascii")
    ex.main_font_east, _ = _weighted_mode(body_runs, "font_east")

    align_vals = [p.alignment for p in body if p.alignment]
    if align_vals:
        ex.alignment = _align_qd(_mode_count(align_vals)[0])

    line_vals = [p.line_ratio for p in body if p.line_ratio]
    line_exact_vals = [
        _round(p.line_exact_pt / ex.base_size)
        for p in body if p.line_exact_pt
    ]
    if line_vals:
        ex.line_ratio = _round(_mode_count(line_vals)[0])
    elif line_exact_vals:
        ex.line_ratio = _round(max(line_exact_vals, key=line_exact_vals.count))

    space_vals = [p.space_after / ex.base_size for p in body if p.space_after]
    if space_vals:
        ex.spacing = _round(max(space_vals, key=space_vals.count))

    indent_vals = []
    for p in body:
        if p.first_line:
            v = p.first_line / ex.base_size
            indent_vals.append(v)
    if indent_vals:
        ex.indent = _round(max(indent_vals, key=indent_vals.count))

    ex.body_bold = _bool_majority(body_runs, "bold")
    ex.body_italic = _bool_majority(body_runs, "italic")
    ex.body_underline = _bool_majority(body_runs, "underline")
    ex.body_color = _color_majority(body_runs)

    heading_runs = [r for d, plist in headings.items() if d != 0 for r in plist for r in r.runs]
    ex.heading_font, _ = _weighted_mode(heading_runs, "font_ascii")
    ex.heading_font_east, _ = _weighted_mode(heading_runs, "font_east")
    ex.all_heading_depths = sorted(d for d in headings if d != 0)

    for d, plist in sorted(headings.items()):
        if d == 0:
            continue
        if heading_levels and d not in heading_levels and d not in {0}:
            continue
        runs = [r for p in plist for r in p.runs]
        size, _ = _weighted_mode(runs, "size_pt")
        font, _ = _weighted_mode(runs, "font_ascii")
        color = _color_majority(runs)
        ex.heading_styles[d] = {
            "size": size,
            "fontsize": nearest_enum(size, ex.base_size),
            "bold": _bool_majority(runs, "bold"),
            "italic": _bool_majority(runs, "italic"),
            "underline": _bool_majority(runs, "underline"),
            "color": color,
            "font": font,
        }

    for d, plist in sorted(headings.items()):
        if d == 0:
            continue
        texts = [p.text.strip() for p in plist]
        kinds = [detect_numbering(t) for t in texts]
        tokens = [k[0] for k in kinds]
        kinds_set = {k[1] for k in kinds}
        if any(p.has_numpr for p in plist):
            ex.numpr_levels.append(d)
            ex.numbering[d] = (None, "numpr")
        elif len(kinds_set) == 1 and kinds_set == {"ok"}:
            ex.numbering[d] = (tokens[0], "ok")
        elif len(kinds_set) == 1 and kinds_set == {"none"}:
            ex.numbering[d] = (None, "none")
        elif "chinese" in kinds_set:
            ex.numbering[d] = (None, "chinese")
        else:
            ex.numbering[d] = (None, "mixed")

    chain, plan = build_numbering_chain(ex.numbering)
    ex.chain = chain
    ex.plan = plan
    if ex.numpr_levels:
        ex.notes.append(
            "检测到 Word 自动编号（numPr）的标题级别: "
            + ", ".join(str(d) for d in ex.numpr_levels)
            + " —— 自动编号无法提取为文本，模板按方案 B 处理（编号需手写在标题文本中）"
        )
    return ex


def _heading_line(depth: int, ex: Extraction, numbered_off: bool) -> list[str]:
    style = ex.heading_styles.get(depth, {})
    params: list[str] = []
    if numbered_off:
        params.append("numbered:{no}")
    if style.get("fontsize") and style.get("fontsize") != "normal":
        params.append(f"fontsize:{{{style['fontsize']}}}")
    if style.get("bold"):
        params.append("fontweight:{bold}")
    if style.get("italic"):
        params.append("fontstyle:{italic}")
    if style.get("underline"):
        params.append("textdecoration:{underline}")
    color = _color_hex(style.get("color"))
    if color:
        params.append(f"foreground:{{{color}}}")
    if not params:
        return []
    return [
        f".extend {{heading}} where:{{depth: .depth::equals {{{depth}}}}}",
        f"    .super {' '.join(params)}",
    ]


def build_template_lines(ex: Extraction, source_label: str) -> list[str]:
    numbered_off = ex.plan == "B"
    summary_lines = []
    summary_lines.append(f"    正文: {ex.base_size:g}pt / {ex.main_font or '-'} + {ex.main_font_east or '-'} / "
                         f"行距 {ex.line_ratio or '-'} / 段距 {ex.spacing or '-'} / "
                         f"缩进 {ex.indent or '-'} / 对齐 {ex.alignment or '-'}")
    for d, style in sorted(ex.heading_styles.items()):
        summary_lines.append(
            f"    H{d}: {style.get('size') or '-'}pt / {style.get('font') or '-'} / "
            f"{'加粗' if style.get('bold') else '常规'} / "
            f"{style.get('color') and '#' + style['color'].lower() or '-'}"
        )
    numbering_lines = []
    for d in sorted(ex.numbering):
        tokens, kind = ex.numbering[d]
        label = {
            "ok": "qd 支持",
            "chinese": "中文数字（不支持）",
            "mixed": "混合/不一致",
            "none": "无编号",
            "numpr": "Word 自动编号(numPr)",
        }.get(kind, kind)
        numbering_lines.append(f"    H{d}: {label}")
    plan_note = ""
    if ex.plan == "A":
        plan_note = f"方案 A —— qd 自动编号 headings: {ex.chain}"
    else:
        plan_note = "方案 B —— 编号写死进标题文本，qd 自动编号已关闭"
    header = [
        "<!--",
        f"  来源: {_esc(source_label)}",
        "  提取格式摘要:",
    ] + summary_lines + [
        "  编号检测:",
    ] + numbering_lines + [
        f"  编号处理: {plan_note}",
    ] + (["  " + n for n in ex.notes] if ex.notes else []) + [
        "-->",
        "",
    ]
    lines = header
    lines.append(f".docname {{{_esc(ex.docname)}}}")
    lines.append(".doctype {paged}")
    lines.append(".doclang {zh-CN}")
    lines.append("")
    if ex.main_font or ex.heading_font:
        font_line = f".font {{{ex.main_font or ex.heading_font or 'Noto Serif CJK SC'}}}"
        if ex.heading_font and ex.heading_font != (ex.main_font or ex.heading_font):
            font_line += f" heading:{{{ex.heading_font}}}"
        font_line += f" size:{{{ex.base_size:g}}}pt"
        lines.append(font_line)
    cjk_font = ex.main_font_east or ex.heading_font_east
    if cjk_font:
        cjk_line = f".font {{{cjk_font}}}"
        if ex.heading_font_east and ex.heading_font_east != cjk_font:
            cjk_line += f" heading:{{{ex.heading_font_east}}}"
        lines.append(cjk_line)
    lines.append("")
    ps_params = []
    if ex.line_ratio is not None:
        ps_params.append(f"lineheight:{{{ex.line_ratio}}}")
    if ex.spacing is not None:
        ps_params.append(f"spacing:{{{ex.spacing}}}")
    if ex.indent is not None:
        ps_params.append(f"indent:{{{ex.indent}}}")
    if ps_params:
        lines.append(f".paragraphstyle {' '.join(ps_params)}")
        lines.append("")

    if ex.plan == "A":
        lines.append(".numbering")
        lines.append(f"    - headings: {ex.chain}")
        lines.append("")
    for d in sorted(ex.heading_styles):
        block = _heading_line(d, ex, numbered_off)
        lines.extend(block)
        if block:
            lines.append("")
    if numbered_off:
        extra_depths = [d for d in ex.all_heading_depths if d not in ex.heading_styles]
        for d in extra_depths:
            lines.append(f".extend {{heading}} where:{{depth: .depth::equals {{{d}}}}}")
            lines.append("    .super numbered:{no}")
            lines.append("")
    para_params = []
    if ex.alignment and ex.alignment != "start":
        para_params.append(f"textalignment:{{{ex.alignment}}}")
    if ex.body_bold:
        para_params.append("fontweight:{bold}")
    if ex.body_italic:
        para_params.append("fontstyle:{italic}")
    if ex.body_underline:
        para_params.append("textdecoration:{underline}")
    body_color = _color_hex(ex.body_color)
    if body_color:
        para_params.append(f"foreground:{{{body_color}}}")
    if para_params:
        lines.append(".extend {paragraph}")
        lines.append(f"    .super {' '.join(para_params)}")
        lines.append("")
    while lines and lines[-1] == "":
        lines.pop()
    lines.append("")
    return lines


def build_report(ex: Extraction) -> str:
    lines = [
        "提取摘要:",
        f"  文档标题: {ex.docname or '-'}",
        f"  正文字号基准: {ex.base_size:g}pt",
        f"  正文字体: {ex.main_font or '-'} / {ex.main_font_east or '-'}",
        f"  标题字体: {ex.heading_font or '-'} / {ex.heading_font_east or '-'}",
        f"  行距系数: {ex.line_ratio or '-'}",
        f"  段距系数: {ex.spacing or '-'}",
        f"  缩进系数: {ex.indent or '-'}",
        f"  正文对齐: {ex.alignment or '-'}",
    ]
    for d, style in sorted(ex.heading_styles.items()):
        lines.append(
            f"  H{d}: 字号 {style.get('size') or '-'}pt -> fontsize:{style.get('fontsize') or '-'} / "
            f"{'加粗' if style.get('bold') else '常规'} / "
            f"{style.get('color') and '#' + style['color'].lower() or '-'}"
        )
    lines.append("  编号检测:")
    for d in sorted(ex.numbering):
        _, kind = ex.numbering[d]
        label = {
            "ok": "qd 支持",
            "chinese": "中文数字（不支持）",
            "mixed": "混合/不一致",
            "none": "无编号",
            "numpr": "Word 自动编号(numPr)",
        }.get(kind, kind)
        lines.append(f"    H{d}: {label}")
    lines.append(f"  方案判定: {'方案 A —— 映射 .numbering headings: ' + (ex.chain or '') if ex.plan == 'A' else '方案 B —— 编号写死进标题文本，qd 自动编号关闭'}")
    lines.extend("  " + n for n in ex.notes)
    return "\n".join(lines)


# ---- py script input --------------------------------------------------------

def run_py_generator(script_path: str) -> tuple[str, str]:
    """Execute a generator script in a temp dir. Returns (docx_path, tmpdir).

    The caller must remove tmpdir after parsing the docx.
    """
    source = open(script_path, "r", encoding="utf-8").read()
    findings = check_script_safety(source)
    if findings:
        raise ValueError(
            "py 生成脚本存在风险，拒绝执行:\n  " + "\n  ".join(findings)
        )
    tmpdir = tempfile.mkdtemp(prefix="docxstyle-gen-")
    dst = os.path.join(tmpdir, os.path.basename(script_path))
    shutil.copy2(script_path, dst)
    try:
        proc = subprocess.run(
            [sys.executable, os.path.basename(script_path)],
            cwd=tmpdir, capture_output=True, text=True, timeout=PY_TIMEOUT,
        )
    except FileNotFoundError:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise ValueError("执行 py 生成脚本失败: 未找到 python3")
    except subprocess.TimeoutExpired:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise ValueError(f"执行 py 生成脚本超时（>{PY_TIMEOUT}s）")
    if proc.returncode != 0:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise ValueError(
            f"py 生成脚本执行失败（退出码 {proc.returncode}）:\n"
            + (proc.stdout or "").strip()
            + "\n"
            + (proc.stderr or "").strip()
        )
    docx_files = sorted(
        f for f in os.listdir(tmpdir) if f.lower().endswith(".docx")
    )
    if not docx_files:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise ValueError("py 生成脚本未产生任何 .docx 文件")
    if len(docx_files) > 1:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise ValueError(
            "py 生成脚本产生多个 .docx 文件，无法确定目标: " + ", ".join(docx_files)
        )
    return os.path.join(tmpdir, docx_files[0]), tmpdir


# ---- verification -----------------------------------------------------------

def verify_template(tpl_path: str) -> tuple[bool, str]:
    out_dir = tempfile.mkdtemp(prefix="quarkdown-verify-")
    try:
        proc = subprocess.run(
            [QUARKDOWN_CMD, "c", tpl_path, "--strict", "--out", out_dir],
            capture_output=True, text=True, timeout=VERIFY_TIMEOUT,
        )
    except FileNotFoundError:
        return False, "未找到 `quarkdown` 命令（请确认其已在 PATH 中）"
    except subprocess.TimeoutExpired:
        return False, f"quarkdown 校验超过 {VERIFY_TIMEOUT}s 未完成"
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)
    if proc.returncode != 0:
        detail = (proc.stdout or "") + (proc.stderr or "")
        detail_lines = [ln for ln in detail.splitlines() if ln.strip()][:12]
        return False, "\n".join(detail_lines) or f"quarkdown 退出码 {proc.returncode}"
    return True, ""


def _parse_heading_levels(text: str) -> set[int]:
    levels: set[int] = set()
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            lo, hi = int(a), int(b)
            levels.update(range(lo, hi + 1))
        else:
            levels.add(int(part))
    return levels


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(EXIT_INPUT_ERROR, f"{self.prog}: error: {message}\n")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = _Parser(
        prog="extract_docx_style",
        description="从 docx（或生成 docx 的 py 脚本）提取样式，生成可复用的 Quarkdown 模板。",
    )
    parser.add_argument("input", metavar="<input.docx|input.py>", help="输入 docx 或 py 生成脚本")
    parser.add_argument("-o", "--output", metavar="output.qd", help="输出 .qd 模板路径（默认: 与输入同名 .qd）")
    parser.add_argument("--heading-levels", default="1-3",
                        help="参与提取的标题级别范围，如 1-3（默认 1-3）")
    parser.add_argument("--dry-run", action="store_true",
                        help="只打印提取摘要与方案判定，不生成文件")
    parser.add_argument("--no-verify", action="store_true",
                        help="跳过 quarkdown 编译校验（默认自动校验）")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(list(sys.argv[1:] if argv is None else argv))
    try:
        heading_levels = _parse_heading_levels(args.heading_levels)
    except ValueError:
        print(f"error: --heading-levels '{args.heading_levels}' 非法（需如 1-3）", file=sys.stderr)
        return EXIT_INPUT_ERROR

    if not os.path.isfile(args.input):
        print(f"error: 输入文件不存在: {args.input}", file=sys.stderr)
        return EXIT_INPUT_ERROR

    ext = os.path.splitext(args.input)[1].lower()
    tmpdir = None
    try:
        if ext == ".py":
            docx_path, tmpdir = run_py_generator(args.input)
            source_label = args.input
        elif ext == ".docx":
            docx_path = args.input
            source_label = args.input
        else:
            print(f"error: 不支持的输入类型 '{ext}'（需 .docx 或 .py）", file=sys.stderr)
            return EXIT_INPUT_ERROR
        paragraphs, title = parse_docx(docx_path)
        ex = _aggregate(paragraphs, heading_levels, title)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_INPUT_ERROR
    except (zipfile.BadZipFile, ET.ParseError, OSError) as exc:
        print(f"error: 解析 docx 失败: {exc}", file=sys.stderr)
        return EXIT_INPUT_ERROR
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)

    ex.docname = ex.core_title or ex.title or os.path.splitext(os.path.basename(args.input))[0] or "Untitled"

    print(build_report(ex))
    print("")

    if args.dry_run:
        print("dry-run: 未生成文件")
        return EXIT_OK

    output = args.output or os.path.splitext(args.input)[0] + ".qd"
    if os.path.abspath(output) == os.path.abspath(args.input):
        print(f"error: 输出路径与输入相同: {output}", file=sys.stderr)
        return EXIT_INPUT_ERROR
    try:
        with open(output, "w", encoding="utf-8") as fh:
            fh.write("\n".join(build_template_lines(ex, source_label)))
    except OSError as exc:
        print(f"error: 无法写入输出文件 {output}: {exc}", file=sys.stderr)
        return EXIT_OUTPUT_ERROR

    print(f"模板已生成: {os.path.abspath(output)}")
    if args.no_verify:
        print("校验: 已跳过（--no-verify）")
        return EXIT_OK
    ok, err = verify_template(output)
    if not ok:
        print("校验: 失败（quarkdown c --strict）", file=sys.stderr)
        if err:
            print(err, file=sys.stderr)
        print("提示: 常见原因是 docx 引用的字体未安装；可用 --no-verify 跳过，或安装对应字体。", file=sys.stderr)
        return EXIT_OUTPUT_ERROR
    print("校验: quarkdown c --strict 通过")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
