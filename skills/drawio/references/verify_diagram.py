#!/usr/bin/env python3
"""Mechanical verifier for .drawio files.

A code agent that cannot see the rendered diagram uses this to confirm the
invariants from the drawio skill: well-formed XML, valid structure, and clean
geometry (no overlaps, no edges crossing unrelated shapes, children inside
containers, everything on-page).

Multi-page files are checked page by page: each <diagram> owns its own root
cells (id="0"/"1"), its own page geometry, and its own coordinate space.
References (edge source/target, cell parent) never cross pages. Compressed /
encoded payloads (base64 diagram bodies) get a dedicated error instead of a
confusing "missing root cell" message.

Exit codes: 0 = no errors (warnings allowed), 1 = errors found, 2 = usage/file error.

Usage:
    python3 verify_diagram.py path/to/file.drawio [--min-gap 40]
"""

from __future__ import annotations

import argparse
import math
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
from html import unescape as hunescape

DEFAULT_MIN_GAP = 40
DEFAULT_PAGE = (827, 1169)  # draw.io A4 portrait
INSET_WARN = 20  # children should be >= 20px inside a container
HEADER_WARN = 40  # swimlane children should sit below the title bar

# Text-fit heuristics. char_width() and wrap_label() mirror render_drawio.py
# (see the matching functions there) so the two tools agree on what "fits".
LINE_H_FACTOR = 1.2   # line height, em units
H_PAD = 12            # total horizontal padding in the label area, px
V_PAD = 8             # total vertical padding in the label area, px


def localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def clean_text(value: str | None) -> str:
    """Unescape entities and strip HTML tags from a draw.io label."""
    if value is None:
        return ""
    return re.sub(r"<[^>]+>", "", hunescape(value))


def parse_style(style: str) -> dict[str, str]:
    d: dict[str, str] = {}
    for tok in (style or "").split(";"):
        if not tok:
            continue
        if "=" in tok:
            k, v = tok.split("=", 1)
            d[k] = v
        else:
            d[tok] = "1"
    return d


def char_width(ch: str) -> float:
    """Approximate glyph width in em units.

    East Asian wide/full/ambiguous characters (CJK, full-width punctuation) are
    ~1.0em wide; everything else is estimated at 0.6em (Latin average). Shared
    rule with render_drawio.py — keep both in sync.
    """
    return 1.0 if unicodedata.east_asian_width(ch) in ("W", "F", "A") else 0.6


def wrap_label(line: str, size: float, avail_w: float) -> list[str]:
    """Break `line` into display lines by word boundaries.

    Words are maximal runs of non-space characters, packed greedily so each
    line's width (per-char widths, East Asian aware) stays within avail_w. A
    single word wider than the box is kept whole so it overflows — draw.io
    wraps at spaces and clips an over-long unbroken run. Mirrors
    render_drawio.py's wrap logic.
    """
    if line == "":
        return [""]
    cap_em = (avail_w / size) if size > 0 else 0.0
    out: list[str] = []
    cur = ""
    cur_em = 0.0
    for word in line.split(" "):
        w_em = sum(char_width(ch) for ch in word)
        if cur and cur_em + char_width(" ") + w_em > cap_em:
            out.append(cur)
            cur = word
            cur_em = w_em
        elif cur:
            cur = f"{cur} {word}"
            cur_em = cur_em + char_width(" ") + w_em
        else:
            cur = word
            cur_em = w_em
    if cur:
        out.append(cur)
    return out


def text_fit_warning(cid: str, value: str, style: dict[str, str],
                     w: float, h: float) -> str | None:
    """Return a warning if the label may overflow its shape, else None."""
    if not value:
        return None
    size = float(style.get("fontSize", "12") or "12")
    wrap = style.get("whiteSpace") == "wrap"
    avail_w = max(w - H_PAD, 10.0)
    avail_h = max(h - V_PAD, 4.0)
    raw_lines = value.split("\n")
    if wrap:
        lines: list[str] = []
        for ln in raw_lines:
            lines.extend(wrap_label(ln, size, avail_w))
    else:
        lines = raw_lines

    widest = 0.0
    for ln in lines:
        widest = max(widest, sum(char_width(ch) for ch in ln) * size)
    if widest > avail_w + 1.0:
        return (
            f"label of {cid!r} may overflow its box horizontally "
            f"(~{widest:.0f}px text vs {avail_w:.0f}px available); "
            f"widen the shape or enable whiteSpace=wrap"
        )
    need_h = len(lines) * size * LINE_H_FACTOR
    if need_h > avail_h + 1.0:
        return (
            f"label of {cid!r} may overflow its box vertically "
            f"({len(lines)} lines need ~{need_h:.0f}px vs {avail_h:.0f}px "
            f"available); grow the shape or shrink the label"
        )
    return None


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("file", help="path to the .drawio file")
    ap.add_argument(
        "--min-gap",
        type=float,
        default=DEFAULT_MIN_GAP,
        help=f"minimum gap between shapes in px (default {DEFAULT_MIN_GAP})",
    )
    ap.add_argument(
        "--strict",
        action="store_true",
        help="treat warnings (e.g. label overflow) as errors",
    )
    return ap.parse_args()


def rect_gap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    """Signed separation between axis-aligned rects (x0,y0,x1,y1).
    >0 gap, 0 touch, <0 overlap depth."""
    dx = max(a[0] - b[2], b[0] - a[2], 0.0)
    dy = max(a[1] - b[3], b[1] - a[3], 0.0)
    if dx == 0 and dy == 0:
        ox = min(a[2], b[2]) - max(a[0], b[0])
        oy = min(a[3], b[3]) - max(a[1], b[1])
        if ox > 0 and oy > 0:
            return -max(ox, oy)
        return 0.0
    return math.hypot(dx, dy) if dx and dy else max(dx, dy)


def seg_rect_intersect(p0: tuple[float, float], p1: tuple[float, float],
                       rect: tuple[float, float, float, float]) -> bool:
    """True if segment p0-p1 enters the rect (Liang-Barsky)."""
    x0, y0 = p0
    x1, y1 = p1
    xa, ya, xb, yb = rect
    dx, dy = x1 - x0, y1 - y0
    p = (-dx, dx, -dy, dy)
    q = (x0 - xa, xb - x0, y0 - ya, yb - y0)
    u1, u2 = 0.0, 1.0
    for pi, qi in zip(p, q):
        if pi == 0:
            if qi < 0:
                return False
            continue
        r = qi / pi
        if pi < 0:
            if r > u2:
                return False
            u1 = max(u1, r)
        else:
            if r < u1:
                return False
            u2 = min(u2, r)
    return True


class Page:
    def __init__(self, name: str, diagram_el: ET.Element, model_el: ET.Element | None) -> None:
        self.name = name
        self.diagram_el = diagram_el
        self.model_el = model_el
        self.page_w, self.page_h = DEFAULT_PAGE
        self.page_flag = True
        if model_el is not None:
            pw, ph = model_el.get("pageWidth"), model_el.get("pageHeight")
            if pw and ph:
                self.page_w, self.page_h = float(pw), float(ph)
            self.page_flag = model_el.get("page", "1") != "0"


class PageReport:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.n_cells = 0
        self.n_shapes = 0
        self.n_edges = 0

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)


def first_model(el: ET.Element) -> ET.Element | None:
    for node in el.iter():
        if localname(node.tag) == "mxGraphModel":
            return node
    return None


def collect_pages(root: ET.Element) -> list[Page]:
    diagrams = [el for el in root if localname(el.tag) == "diagram"]
    if not diagrams:
        # No <diagram> wrapper: treat the whole document as one page.
        return [Page("", root, first_model(root))]
    return [
        Page(diag.get("name") or diag.get("id") or "", diag, first_model(diag))
        for diag in diagrams
    ]


def compressed_payload(diagram_el: ET.Element) -> bool:
    """True if a <diagram> holds non-XML content (typically a base64 payload)."""
    for node in diagram_el.iter():
        if localname(node.tag) in ("mxGraphModel", "mxCell"):
            return False
    return bool("".join(diagram_el.itertext()).strip())


def check_page(page: Page, args: argparse.Namespace, page_idx: int,
               all_page_ids: list[set[str]]) -> PageReport:
    rep = PageReport()

    # ---- compressed / encoded payload ----------------------------------
    if page.model_el is None:
        if compressed_payload(page.diagram_el):
            rep.error(
                f"page {page.name or page_idx + 1!r}: detected a compressed/encoded "
                f"diagram payload (压缩/编码图表载荷); do not hand-edit it — export "
                f"from draw.io via 'Extras -> Uncompressed XML' before editing"
            )
            return rep
        # No model and no payload: an empty/blank page. Fall through to the
        # normal checks so an empty document still reports missing cells.

    # ---- collect cells (page-scoped) -----------------------------------
    cells: dict[str, dict] = {}
    for el in page.diagram_el.iter():
        if localname(el.tag) != "mxCell":
            continue
        cid = el.get("id")
        if cid is None:
            rep.error("found an <mxCell> without an id attribute")
            continue
        if cid in cells:
            rep.error(f"duplicate cell id: {cid!r}")
            continue

        geom: tuple[float, float, float, float] | None = None
        rel = False
        points: list[tuple[float, float]] = []
        for child in el:
            if localname(child.tag) != "mxGeometry":
                continue
            rel = child.get("relative", "0") == "1"
            x, y, w, h = child.get("x"), child.get("y"), child.get("width"), child.get("height")
            try:
                geom = (float(x) if x is not None else 0.0,
                        float(y) if y is not None else 0.0,
                        float(w) if w is not None else 0.0,
                        float(h) if h is not None else 0.0)
            except ValueError:
                rep.error(f"cell {cid!r}: mxGeometry has non-numeric x/y/width/height")
                geom = (0.0, 0.0, 0.0, 0.0)
            for arr in child:
                if localname(arr.tag) != "Array" or arr.get("as") != "points":
                    continue
                for pt in arr:
                    if localname(pt.tag) != "mxPoint":
                        continue
                    try:
                        points.append((float(pt.get("x", 0)), float(pt.get("y", 0))))
                    except ValueError:
                        pass

        cells[cid] = {
            "id": cid,
            "parent": el.get("parent"),
            "vertex": el.get("vertex") == "1",
            "edge": el.get("edge") == "1",
            "source": el.get("source"),
            "target": el.get("target"),
            "style": parse_style(el.get("style", "") or ""),
            "value": el.get("value"),
            "geom": geom,
            "rel": rel,
            "has_geom": geom is not None,
            "points": points,
        }

    rep.n_cells = len(cells)
    rep.n_shapes = sum(1 for c in cells.values() if c["vertex"])
    rep.n_edges = sum(1 for c in cells.values() if c["edge"])

    if not cells:
        rep.error("no <mxCell> elements found; this is not a valid diagram")

    # ---- structure checks (page-scoped, no cross-page references) ------
    other_ids: set[str] = set()
    for i, ids in enumerate(all_page_ids):
        if i != page_idx:
            other_ids |= ids

    if "0" not in cells:
        rep.error('missing root cell id="0"')
    if "1" not in cells:
        rep.error('missing root cell id="1"')

    for cid, c in cells.items():
        if c["parent"] is not None and c["parent"] not in cells:
            if c["parent"] in other_ids:
                rep.error(
                    f'cell {cid!r}: parent={c["parent"]!r} is on another page '
                    f"(cross-page parent reference)"
                )
            else:
                rep.error(f'cell {cid!r}: parent={c["parent"]!r} does not exist')
        if c["edge"]:
            for attr in ("source", "target"):
                ref = c[attr]
                if ref is None:
                    rep.error(f'edge {cid!r}: missing required {attr} attribute')
                elif ref not in cells:
                    if ref in other_ids:
                        rep.error(
                            f'edge {cid!r}: {attr}={ref!r} is on another page '
                            f"(cross-page reference)"
                        )
                    else:
                        rep.error(f'edge {cid!r}: {attr}={ref!r} does not exist')
            if c["source"] is not None and c["source"] == c["target"]:
                rep.warn(f'edge {cid!r}: source == target (loopback)')

    # ---- edge style checks (§6 rules 2 & 3) -----------------------------
    # rule 3: never attach at corners (exitX/exitY or entryX/entryY both 0/1)
    for cid, c in cells.items():
        if not c["edge"]:
            continue
        st = c["style"]
        for side, (xk, yk) in (("exit", ("exitX", "exitY")),
                               ("entry", ("entryX", "entryY"))):
            xv, yv = st.get(xk), st.get(yk)
            if xv in ("0", "1") and yv in ("0", "1"):
                rep.warn(
                    f'edge {cid!r}: {side} anchor sits on a corner '
                    f"({xk}={xv}, {yk}={yv}); attach on a side, not a corner "
                    f"(§6 rule 3)"
                )
                break
    # rule 2: two edges between the same pair must differ in exit/entry anchors
    same_pair: dict[tuple[str | None, str | None],
                    list[tuple[str, tuple[str | None, ...]]]] = {}
    for cid, c in cells.items():
        if not c["edge"]:
            continue
        st = c["style"]
        key = (st.get("exitX"), st.get("exitY"),
               st.get("entryX"), st.get("entryY"))
        same_pair.setdefault((c["source"], c["target"]), []).append((cid, key))
    for (s, t), edges in same_pair.items():
        if s is None or t is None:
            continue
        seen: dict[tuple[str | None, ...], str] = {}
        for cid, key in edges:
            if key in seen:
                rep.warn(
                    f'edges {seen[key]!r} and {cid!r} share source/target '
                    f"({s!r}->{t!r}) with identical anchors {key}; use "
                    f"different exit/entry anchors (§6 rule 2)"
                )
            else:
                seen[key] = cid

    # ---- absolute geometry ---------------------------------------------
    def parent_chain(cid: str) -> list[str]:
        chain: list[str] = []
        seen: set[str] = set()
        while cid in cells and cid not in seen:
            seen.add(cid)
            chain.append(cid)
            cid = cells[cid]["parent"] or ""
        return chain

    def abs_geom(cid: str):
        """Absolute (x0,y0,x1,y1) for a vertex cell, else None."""
        c = cells[cid]
        if not c["vertex"] or not c["has_geom"] or c["rel"]:
            return None
        x, y, w, h = c["geom"]
        for p in parent_chain(cid)[1:]:
            if cells[p]["has_geom"] and cells[p]["geom"] is not None:
                px, py, _, _ = cells[p]["geom"]
                x += px
                y += py
        return (x, y, x + w, y + h)

    abs_rect: dict[str, tuple[float, float, float, float]] = {}
    for cid in cells:
        r = abs_geom(cid)
        if r is not None:
            abs_rect[cid] = r
            if r[0] < 0 or r[1] < 0:
                rep.error(f"cell {cid!r}: negative coordinates ({r[0]:.0f},{r[1]:.0f})")

    if page.page_flag:
        for cid, (x, y, x1, y1) in abs_rect.items():
            if x1 > page.page_w + 0.5 or y1 > page.page_h + 0.5:
                rep.error(
                    f"cell {cid!r}: extends past page bounds "
                    f"({x1:.0f} > {page.page_w:.0f} or {y1:.0f} > {page.page_h:.0f}); "
                    f"the render will clip it"
                )

    # children inside containers + below swimlane header
    for cid, c in cells.items():
        if not c["vertex"] or c["geom"] is None:
            continue
        p = c["parent"]
        if p not in cells or p in ("0", "1"):
            continue
        parent_abs = abs_rect.get(p)
        child_abs = abs_rect.get(cid)
        if parent_abs is None or child_abs is None:
            continue
        px0, py0, px1, py1 = parent_abs
        cx0, cy0, cx1, cy1 = child_abs
        if cx0 < px0 - 0.5 or cy0 < py0 - 0.5 or cx1 > px1 + 0.5 or cy1 > py1 + 0.5:
            rep.error(f"child {cid!r} escapes its container {p!r}")
        inset = min(cx0 - px0, cy0 - py0, px1 - cx1, py1 - cy1)
        if inset < INSET_WARN:
            rep.warn(f"child {cid!r} is only {inset:.0f}px inside container {p!r} (< {INSET_WARN})")
        start_size = None
        try:
            start_size = float(cells[p]["style"]["startSize"])
        except (KeyError, ValueError):
            pass
        if start_size is not None and "swimlane" in cells[p]["style"] and cy0 - py0 < start_size:
            rep.warn(
                f"child {cid!r} sits above the swimlane header of {p!r} "
                f"(needs y >= {start_size:.0f}); it will be hidden behind the title bar"
            )

    # ---- label overflow check ------------------------------------------
    # Text-only cells and swimlane headers are exempt (no fixed label area).
    for cid in abs_rect:
        c = cells[cid]
        if not c["vertex"]:
            continue
        st = c["style"]
        if "text" in st or "swimlane" in st:
            continue
        value = clean_text(c["value"])
        if not value:
            continue
        msg = text_fit_warning(cid, value, st, c["geom"][2], c["geom"][3])
        if msg:
            rep.warn(msg)

    # ---- overlap check (skip ancestor/descendant pairs) ----------------
    ids = [cid for cid in abs_rect if cells[cid]["vertex"]]
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            a, b = ids[i], ids[j]
            if a in set(parent_chain(b)) or b in set(parent_chain(a)):
                continue  # ancestor/descendant, allowed to nest
            gap = rect_gap(abs_rect[a], abs_rect[b])
            if gap < 0:
                rep.error(f"overlap: {a!r} and {b!r} overlap by {-gap:.0f}px")
            elif gap < args.min_gap:
                rep.warn(
                    f"tight spacing: {a!r} and {b!r} are only {gap:.0f}px apart "
                    f"(< {args.min_gap:.0f})"
                )

    # ---- edge geometry --------------------------------------------------
    def edge_anchor(cid: str, style: dict[str, str], is_source: bool):
        """Absolute edge endpoint from explicit style anchors, else the default
        rule shared with render_drawio.py's anchor(): the side midpoint facing
        the other endpoint."""
        r = abs_rect.get(cid)
        if r is None:
            return None
        x, y = r[0], r[1]
        w, h = r[2] - r[0], r[3] - r[1]
        if is_source:
            ax, ay = style.get("exitX"), style.get("exitY")
        else:
            ax, ay = style.get("entryX"), style.get("entryY")
        if ax is not None and ay is not None:
            try:
                return (x + w * float(ax), y + h * float(ay))
            except ValueError:
                pass
        other = cells[cid]["target"] if is_source else cells[cid]["source"]
        og = abs_rect.get(other)
        if og is None:
            return (x + w / 2, y + h / 2)
        if og[0] >= x + w:
            return (x + w, y + h / 2)
        if og[2] <= x:
            return (x, y + h / 2)
        if og[1] >= y + h:
            return (x + w / 2, y + h)
        return (x + w / 2, y)

    for cid, c in cells.items():
        if not c["edge"]:
            continue
        s, t = c["source"], c["target"]
        if s not in abs_rect or t not in abs_rect:
            continue
        st = c["style"]
        p0 = edge_anchor(s, st, True)
        p1 = edge_anchor(t, st, False)
        if p0 is None or p1 is None:
            continue
        pts = [p0] + c["points"] + [p1]
        if not c["points"] and st.get("edgeStyle") == "orthogonalEdgeStyle":
            # single-bend L route, matching render_drawio.py
            if abs(p1[0] - p0[0]) >= abs(p1[1] - p0[1]):
                pts = [p0, (p1[0], p0[1]), p1]
            else:
                pts = [p0, (p0[0], p1[1]), p1]

        # ---- waypoints / anchors on page (T5) --------------------------
        if page.page_flag:
            for px, py in pts:
                if px < -0.5 or py < -0.5 or px > page.page_w + 0.5 or py > page.page_h + 0.5:
                    rep.error(
                        f"edge {cid!r}: point ({px:.0f},{py:.0f}) is outside page bounds "
                        f"({page.page_w:.0f}x{page.page_h:.0f}); the render will clip it"
                    )

        # ---- crossing check (T3) ----------------------------------------
        if st.get("curved") == "1":
            rep.warn(
                f"edge {cid!r} ({s!r}->{t!r}) is curved; crossing with unrelated "
                f"shapes cannot be determined mechanically, please confirm visually"
            )
            continue
        blocked = set(parent_chain(s)) | set(parent_chain(t)) | {s, t}
        for other, rect in abs_rect.items():
            if not cells[other]["vertex"] or other in blocked:
                continue
            for k in range(len(pts) - 1):
                if seg_rect_intersect(pts[k], pts[k + 1], rect):
                    rep.error(f"edge {cid!r} ({s!r}->{t!r}) crosses unrelated shape {other!r}")
                    break

    return rep


def report(args: argparse.Namespace, pages: list[Page], reports: list[PageReport],
           file_errors: list[str]) -> int:
    print(f"Checked: {args.file}")
    multi = len(pages) > 1
    if multi:
        print(f"  pages: {len(pages)}")

    if not multi:
        page, r = pages[0], reports[0]
        print(f"  cells: {r.n_cells}, shapes: {r.n_shapes}, edges: {r.n_edges}")
        print(f"  page: {page.page_w:.0f}x{page.page_h:.0f} (page={page.page_flag})")
        if r.warnings:
            print(f"WARNINGS ({len(r.warnings)}):")
            for w in r.warnings:
                print(f"  - {w}")
        if r.errors or (args.strict and r.warnings):
            print(f"ERRORS ({len(r.errors)}):")
            for e in r.errors:
                print(f"  - {e}")
            if args.strict and r.warnings:
                print(f"ERRORS (warnings promoted by --strict) ({len(r.warnings)}):")
                for w in r.warnings:
                    print(f"  - {w}")
            return 1
        print("OK: no errors.")
        return 0

    for i, (page, r) in enumerate(zip(pages, reports)):
        name = page.name or f"page-{i + 1}"
        print(f'Page "{name}" ({page.page_w:.0f}x{page.page_h:.0f}, page={page.page_flag}):')
        print(f"  cells: {r.n_cells}, shapes: {r.n_shapes}, edges: {r.n_edges}")
        if r.warnings:
            print(f"  WARNINGS ({len(r.warnings)}):")
            for w in r.warnings:
                print(f"    - {w}")
        if r.errors:
            print(f"  ERRORS ({len(r.errors)}):")
            for e in r.errors:
                print(f"    - {e}")

    if file_errors:
        print(f"ERRORS (file) ({len(file_errors)}):")
        for e in file_errors:
            print(f"  - {e}")

    any_errors = bool(file_errors or any(r.errors for r in reports))
    promoted = bool(args.strict and any(r.warnings for r in reports))
    if any_errors or promoted:
        n_err = len(file_errors) + sum(len(r.errors) for r in reports)
        msg = f"ERRORS: {n_err} error(s)"
        if promoted:
            n_prom = sum(len(r.warnings) for r in reports)
            msg += f" (+ {n_prom} warning(s) promoted by --strict)"
        print(msg)
        return 1
    print("OK: no errors.")
    return 0


def main() -> int:
    args = parse_args()

    try:
        tree = ET.parse(args.file)
    except ET.ParseError as exc:
        print(f"ERROR: not well-formed XML: {exc}")
        return 1
    except OSError as exc:
        print(f"ERROR: cannot read file: {exc}")
        return 2

    root = tree.getroot()
    pages = collect_pages(root)

    # file-level: <diagram> ids must be unique
    file_errors: list[str] = []
    seen_ids: dict[str, int] = {}
    for i, p in enumerate(pages):
        did = p.diagram_el.get("id")
        if did is None:
            continue
        if did in seen_ids:
            file_errors.append(
                f"duplicate <diagram> id: {did!r} (page {seen_ids[did] + 1} and page {i + 1})"
            )
        else:
            seen_ids[did] = i

    all_page_ids: list[set[str]] = []
    for p in pages:
        ids = {el.get("id") for el in p.diagram_el.iter()
               if localname(el.tag) == "mxCell" and el.get("id") is not None}
        all_page_ids.append(ids)

    reports = [check_page(p, args, i, all_page_ids) for i, p in enumerate(pages)]
    return report(args, pages, reports, file_errors)


if __name__ == "__main__":
    sys.exit(main())
