#!/usr/bin/env python3
"""Mechanical verifier for .drawio files.

A code agent that cannot see the rendered diagram uses this to confirm the
invariants from the drawio skill: well-formed XML, valid structure, and clean
geometry (no overlaps, no edges crossing unrelated shapes, children inside
containers, everything on-page).

Exit codes: 0 = no errors (warnings allowed), 1 = errors found, 2 = usage/file error.

Usage:
    python3 verify_diagram.py path/to/file.drawio [--min-gap 40]
"""

from __future__ import annotations

import argparse
import math
import re
import sys
import xml.etree.ElementTree as ET
from html import unescape as hunescape

DEFAULT_MIN_GAP = 40
DEFAULT_PAGE = (827, 1169)  # draw.io A4 portrait
INSET_WARN = 20  # children should be >= 20px inside a container
HEADER_WARN = 40  # swimlane children should sit below the title bar

# Text-fit heuristics. CHAR_W_FACTOR and LINE_H_FACTOR mirror
# render_drawio.py so the two tools agree on what "fits".
CHAR_W_FACTOR = 0.6   # average glyph width, em units
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


def text_fit_warning(cid: str, value: str, style: dict[str, str],
                     w: float, h: float) -> str | None:
    """Return a warning if the label may overflow its shape, else None."""
    if not value:
        return None
    size = float(style.get("fontSize", "12") or "12")
    wrap = style.get("whiteSpace") == "wrap"
    char_w = size * CHAR_W_FACTOR
    avail_w = max(w - H_PAD, 10.0)
    raw_lines = value.split("\n")

    if wrap:
        per_line = max(int(avail_w // char_w), 4)
        lines: list[str] = []
        for ln in raw_lines:
            while len(ln) > per_line:
                lines.append(ln[:per_line])
                ln = ln[per_line:]
            lines.append(ln)
    else:
        lines = raw_lines

    widest = max((len(ln) for ln in lines), default=0)
    if widest * char_w > avail_w + 1.0:
        return (
            f"label of {cid!r} may overflow its box horizontally "
            f"(~{widest * char_w:.0f}px text vs {avail_w:.0f}px available); "
            f"widen the shape or enable whiteSpace=wrap"
        )
    need_h = len(lines) * size * LINE_H_FACTOR
    avail_h = max(h - V_PAD, 4.0)
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


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)


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


def main() -> int:
    args = parse_args()
    rep = Report()

    try:
        tree = ET.parse(args.file)
    except ET.ParseError as exc:
        print(f"ERROR: not well-formed XML: {exc}")
        return 1
    except OSError as exc:
        print(f"ERROR: cannot read file: {exc}")
        return 2

    root = tree.getroot()

    # ---- page geometry -------------------------------------------------
    page_w, page_h = DEFAULT_PAGE
    page_flag = True
    for el in root.iter():
        if localname(el.tag) == "mxGraphModel":
            pw, ph = el.get("pageWidth"), el.get("pageHeight")
            if pw and ph:
                page_w, page_h = float(pw), float(ph)
            page_flag = el.get("page", "1") != "0"
            break

    # ---- collect cells -------------------------------------------------
    cells: dict[str, dict] = {}
    for el in root.iter():
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

    if not cells:
        rep.error("no <mxCell> elements found; this is not a valid diagram")

    # ---- structure checks ---------------------------------------------
    if "0" not in cells:
        rep.error('missing root cell id="0"')
    if "1" not in cells:
        rep.error('missing root cell id="1"')

    for cid, c in cells.items():
        if c["parent"] is not None and c["parent"] not in cells:
            rep.error(f'cell {cid!r}: parent={c["parent"]!r} does not exist')
        if c["edge"]:
            for attr in ("source", "target"):
                ref = c[attr]
                if ref is not None and ref not in cells:
                    rep.error(f'edge {cid!r}: {attr}={ref!r} does not exist')
            if c["source"] is not None and c["source"] == c["target"]:
                rep.warn(f'edge {cid!r}: source == target (loopback)')

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

    if page_flag:
        for cid, (x, y, x1, y1) in abs_rect.items():
            if x1 > page_w + 0.5 or y1 > page_h + 0.5:
                rep.error(
                    f"cell {cid!r}: extends past page bounds "
                    f"({x1:.0f} > {page_w:.0f} or {y1:.0f} > {page_h:.0f}); the render will clip it"
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

    # ---- edge crossing check -------------------------------------------
    def center(cid: str):
        r = abs_rect.get(cid)
        if r is None:
            return None
        return ((r[0] + r[2]) / 2.0, (r[1] + r[3]) / 2.0)

    for cid, c in cells.items():
        if not c["edge"]:
            continue
        s, t = c["source"], c["target"]
        if s not in abs_rect or t not in abs_rect:
            continue
        p0, p1 = center(s), center(t)
        if p0 is None or p1 is None:
            continue
        poly = [p0] + c["points"] + [p1]
        blocked = set(parent_chain(s)) | set(parent_chain(t)) | {s, t}
        for other, rect in abs_rect.items():
            if not cells[other]["vertex"] or other in blocked:
                continue
            for k in range(len(poly) - 1):
                if seg_rect_intersect(poly[k], poly[k + 1], rect):
                    rep.error(f"edge {cid!r} ({s!r}->{t!r}) crosses unrelated shape {other!r}")
                    break

    # ---- report --------------------------------------------------------
    print(f"Checked: {args.file}")
    n_shapes = sum(1 for c in cells.values() if c["vertex"])
    n_edges = sum(1 for c in cells.values() if c["edge"])
    print(f"  cells: {len(cells)}, shapes: {n_shapes}, edges: {n_edges}")
    print(f"  page: {page_w:.0f}x{page_h:.0f} (page={page_flag})")
    if rep.warnings:
        print(f"WARNINGS ({len(rep.warnings)}):")
        for w in rep.warnings:
            print(f"  - {w}")
    if rep.errors or (args.strict and rep.warnings):
        print(f"ERRORS ({len(rep.errors)}):")
        for e in rep.errors:
            print(f"  - {e}")
        if args.strict and rep.warnings:
            print(f"ERRORS (warnings promoted by --strict) ({len(rep.warnings)}):")
            for w in rep.warnings:
                print(f"  - {w}")
        return 1
    print("OK: no errors.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
