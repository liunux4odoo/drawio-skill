#!/usr/bin/env python3
"""Render a .drawio file to SVG (stdlib only).

Fallback when the draw.io CLI / container / browser viewer is unavailable.
Renders the basic shapes the drawio skill uses (rect, rounded, rhombus,
ellipse, swimlane, cylinder, hexagon, parallelogram, text) and orthogonal
edges with arrows and waypoints.

This is an APPROXIMATION of draw.io rendering — HTML labels, fonts, and
complex shapes (cylinders, clouds, icons) will not be pixel-identical. It is
intended for the skill's §8.2 visual layout check: overlaps, edge crossings,
clipped labels, off-page content.

Optional PNG output requires cairosvg (pip install cairosvg).

Usage:
    python3 render_drawio.py file.drawio                # -> file.svg
    python3 render_drawio.py file.drawio -o out.svg
    python3 render_drawio.py file.drawio --png          # -> file.svg + file.png
"""

from __future__ import annotations

import argparse
import html
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET

DEFAULT_FILL = "#ffffff"
DEFAULT_STROKE = "#000000"
DEFAULT_TEXT = "#000000"
HEADER_DEFAULT = 26  # swimlane startSize fallback


def localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


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


def has_shape(style: dict[str, str], name: str) -> bool:
    """True when `name` is the shape, written either as `shape=name` or as a
    bare style token — both spellings are legal in draw.io style strings."""
    return style.get("shape") == name or name in style


def unescape(value: str | None) -> str:
    if value is None:
        return ""
    return re.sub(r"<[^>]+>", "", html.unescape(value)).replace("&#10;", "\n")


def char_width(ch: str) -> float:
    """Approximate glyph width in em units.

    East Asian wide/full/ambiguous characters (CJK, full-width punctuation) are
    ~1.0em wide; everything else is estimated at 0.6em (Latin average). Shared
    rule with verify_diagram.py — keep both in sync.
    """
    return 1.0 if unicodedata.east_asian_width(ch) in ("W", "F", "A") else 0.6


def wrap_label(line: str, size: float, width: float) -> list[str]:
    """Break `line` into display lines by word boundaries.

    Words are maximal runs of non-space characters, packed greedily so each
    line's width (per-char widths, East Asian aware) stays within `width`. A
    single word wider than the box is kept whole so it overflows — draw.io
    wraps at spaces and clips an over-long unbroken run. Mirrors
    verify_diagram.py's wrap logic.
    """
    if line == "":
        return [""]
    cap_em = (width / size) if size > 0 else 0.0
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


def split_lines(text: str, style: dict, width: float) -> list[str]:
    lines = text.split("\n")
    if style.get("whiteSpace") != "wrap":
        return lines
    size = float(style.get("fontSize", "12") or "12")
    out: list[str] = []
    for ln in lines:
        out.extend(wrap_label(ln, size, width))
    return out


class Renderer:
    def __init__(self) -> None:
        self.cells: dict[str, dict] = {}
        self.defs: list[str] = []
        self.body: list[str] = []
        self.marker_ids: set[str] = set()

    def load(self, path: str) -> None:
        tree = ET.parse(path)
        for el in tree.getroot().iter():
            if localname(el.tag) != "mxCell":
                continue
            cid = el.get("id")
            if cid in (None, "0", "1"):
                continue
            geom = None
            points: list[tuple[float, float]] = []
            rel = False
            for child in el:
                if localname(child.tag) != "mxGeometry":
                    continue
                rel = child.get("relative", "0") == "1"
                x, y, w, h = (child.get(k) for k in ("x", "y", "width", "height"))
                try:
                    geom = (float(x or 0), float(y or 0),
                            float(w or 0), float(h or 0))
                except ValueError:
                    geom = (0.0, 0.0, 0.0, 0.0)
                for arr in child:
                    if localname(arr.tag) != "Array" or arr.get("as") != "points":
                        continue
                    for pt in arr:
                        if localname(pt.tag) == "mxPoint":
                            try:
                                points.append((float(pt.get("x", 0)),
                                               float(pt.get("y", 0))))
                            except ValueError:
                                pass
            self.cells[cid] = {
                "id": cid,
                "parent": el.get("parent"),
                "vertex": el.get("vertex") == "1",
                "edge": el.get("edge") == "1",
                "source": el.get("source"),
                "target": el.get("target"),
                "value": unescape(el.get("value")),
                "style": parse_style(el.get("style", "")),
                "geom": geom,
                "rel": rel,
                "points": points,
            }

    # ---- geometry -----------------------------------------------------
    def parent_chain(self, cid: str) -> list[str]:
        chain: list[str] = []
        seen: set[str] = set()
        while cid in self.cells and cid not in seen:
            seen.add(cid)
            chain.append(cid)
            cid = self.cells[cid]["parent"] or ""
        return chain

    def abs_geom(self, cid: str):
        c = self.cells[cid]
        if not c["vertex"] or c["geom"] is None or c["rel"]:
            return None
        x, y, w, h = c["geom"]
        for p in self.parent_chain(cid)[1:]:
            g = self.cells[p]["geom"]
            if g is not None:
                x += g[0]
                y += g[1]
        return (x, y, w, h)

    # ---- svg helpers ---------------------------------------------------
    def esc(self, s: str) -> str:
        return html.escape(s, quote=True)

    def marker(self, color: str, reverse: bool = False) -> str:
        key = f"{color}-{'r' if reverse else 'f'}"
        if key in self.marker_ids:
            return key
        self.marker_ids.add(key)
        fill = self.esc(color)
        if reverse:
            path = "M 10 0 L 0 5 L 10 10 z"
            ref = 0
        else:
            path = "M 0 0 L 10 5 L 0 10 z"
            ref = 9
        self.defs.append(
            f'<marker id="m-{key}" viewBox="0 0 10 10" refX="{ref}" refY="5" '
            f'markerWidth="8" markerHeight="8" orient="auto-start-reverse">'
            f'<path d="{path}" fill="{fill}" stroke="{fill}" stroke-width="0.5"/>'
            f"</marker>"
        )
        return key

    # ---- shape rendering ------------------------------------------------
    def text_el(self, x: float, y: float, w: float, h: float, value: str,
                style: dict) -> list[str]:
        lines = split_lines(value, style, w)
        if not lines:
            return []
        size = float(style.get("fontSize", "12") or "12")
        weight = "bold" if style.get("fontStyle") in ("1", "3", "5", "7") else "normal"
        italic = "italic" if style.get("fontStyle") in ("2", "3", "6", "7") else "normal"
        color = self.esc(style.get("fontColor", DEFAULT_TEXT))
        align = style.get("align", "center")
        valign = style.get("verticalAlign", "middle")
        anchor = {"left": "start", "right": "end"}.get(align, "middle")
        if valign == "top":
            base_y = y + 4 + size
        elif valign == "bottom":
            base_y = y + h - 4
        else:
            base_y = y + h / 2 + size * 0.35 - (len(lines) - 1) * size * 0.6
        x_pos = {"left": x + 4, "right": x + w - 4}.get(align, x + w / 2)
        parts = [
            f'<text x="{x_pos:.1f}" y="{base_y:.1f}" text-anchor="{anchor}" '
            f'font-family="sans-serif" font-size="{size}" '
            f'font-weight="{weight}" font-style="{italic}" fill="{color}">'
        ]
        for i, ln in enumerate(lines):
            dy = i * float(size) * 1.2
            parts.append(f'<tspan x="{x_pos:.1f}" dy="{dy if i else 0}">'
                         f"{self.esc(ln)}</tspan>")
        parts.append("</text>")
        return parts

    def draw_vertex(self, cid: str, g: tuple[float, float, float, float]) -> None:
        c = self.cells[cid]
        st = c["style"]
        x, y, w, h = g
        fill = self.esc(st.get("fillColor", DEFAULT_FILL))
        stroke = self.esc(st.get("strokeColor", DEFAULT_STROKE))
        sw = st.get("strokeWidth", "1")
        dash = ' stroke-dasharray="4 3"' if st.get("dashed") == "1" else ""
        common = (f'stroke="{stroke}" stroke-width="{sw}" fill="{fill}"{dash}')
        body: list[str] = []

        if "swimlane" in st:
            start = float(st.get("startSize", HEADER_DEFAULT))
            body.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="2" {common}/>')
            body.append(f'<path d="M {x} {y + start} L {x + w} {y + start}" '
                        f'stroke="{stroke}" stroke-width="{sw}"/>')
            body.append(f'<rect x="{x}" y="{y}" width="{w}" height="{start}" '
                        f'fill="{fill}" fill-opacity="0.25"/>')
            if c["value"]:
                body.extend(self.text_el(x, y, w, start, c["value"], st))
            return
        if "text" in st:
            body.extend(self.text_el(x, y, w, h, c["value"], st))
            return
        if has_shape(st, "rhombus"):
            cx, cy = x + w / 2, y + h / 2
            pts = f"{cx},{y} {x + w},{cy} {cx},{y + h} {x},{cy}"
            body.append(f'<polygon points="{pts}" {common}/>')
        elif has_shape(st, "ellipse"):
            body.append(f'<ellipse cx="{x + w / 2}" cy="{y + h / 2}" rx="{w / 2}" '
                        f'ry="{h / 2}" {common}/>')
        elif has_shape(st, "parallelogram"):
            skew = min(w * 0.15, 24)
            pts = f"{x + skew},{y} {x + w},{y} {x + w - skew},{y + h} {x},{y + h}"
            body.append(f'<polygon points="{pts}" {common}/>')
        elif has_shape(st, "hexagon"):
            cx = x + w / 2
            pts = f"{cx},{y} {x + w},{y + h * 0.5} {cx},{y + h} {x},{y + h * 0.5}"
            body.append(f'<polygon points="{pts}" {common}/>')
        elif has_shape(st, "cylinder3"):
            r = min(w, h) * 0.15
            body.append(f'<path d="M {x},{y + r} L {x},{y + h - r} A {r} {r} 0 0 0 '
                        f"{x + w},{y + h - r} L {x + w},{y + r} A {r} {r} 0 0 0 "
                        f'{x},{y + r} Z" {common}/>')
            body.append(f'<ellipse cx="{x + w / 2}" cy="{y + r}" rx="{w / 2}" '
                        f'ry="{r}" {common}/>')
        else:
            rx = ""
            if st.get("rounded") == "1":
                arc = float(st.get("arcSize", "10"))
                r = min(w, h) * (arc / 100)
                rx = f' rx="{r:.1f}"'
            body.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}"{rx} {common}/>')

        if c["value"]:
            body.extend(self.text_el(x, y, w, h, c["value"], st))
        self.body.extend(body)

    # ---- edge rendering ---------------------------------------------------
    def anchor(self, cid: str, style: dict, is_source: bool):
        g = self.abs_geom(cid)
        if g is None:
            return None
        x, y, w, h = g
        if is_source:
            ax, ay = style.get("exitX"), style.get("exitY")
        else:
            ax, ay = style.get("entryX"), style.get("entryY")
        if ax is not None and ay is not None:
            return (x + w * float(ax), y + h * float(ay))
        # default: toward the other endpoint
        other = self.cells[cid]["target"] if is_source else self.cells[cid]["source"]
        og = self.abs_geom(other) if other in self.cells else None
        if og is None:
            return (x + w / 2, y + h / 2)
        if og[0] >= x + w:
            return (x + w, y + h / 2)
        if og[0] + og[2] <= x:
            return (x, y + h / 2)
        if og[1] >= y + h:
            return (x + w / 2, y + h)
        return (x + w / 2, y)

    def edge_points(self, cid: str) -> list[tuple[float, float]] | None:
        """Polyline for an edge: anchors + waypoints (+ orthogonal bend).

        Reuses the same anchor rule and single-bend L routing as
        verify_diagram.py's edge geometry, so the rendered path and the
        checked path agree. Returns None when an endpoint has no geometry.
        """
        c = self.cells[cid]
        st = c["style"]
        s, t = c["source"], c["target"]
        p0 = self.anchor(s, st, True)
        p1 = self.anchor(t, st, False)
        if p0 is None or p1 is None:
            return None
        pts = [p0] + c["points"] + [p1]
        if not c["points"] and st.get("edgeStyle") == "orthogonalEdgeStyle":
            # single-bend L route
            if abs(p1[0] - p0[0]) >= abs(p1[1] - p0[1]):
                pts = [p0, (p1[0], p0[1]), p1]
            else:
                pts = [p0, (p0[0], p1[1]), p1]
        return pts

    def draw_edge(self, cid: str) -> None:
        c = self.cells[cid]
        st = c["style"]
        pts = self.edge_points(cid)
        if pts is None:
            return
        d = " ".join(f"L {px:.1f} {py:.1f}" for px, py in pts[1:])
        color = st.get("strokeColor", DEFAULT_STROKE)
        sw = st.get("strokeWidth", "1")
        dash = ' stroke-dasharray="4 3"' if st.get("dashed") == "1" else ""
        attrs = f'fill="none" stroke="{self.esc(color)}" stroke-width="{sw}"{dash}'
        if st.get("endArrow", "classic") not in ("none", ""):
            attrs += f' marker-end="url(#m-{self.marker(color)})"'
        if st.get("startArrow") not in (None, "", "none"):
            attrs += f' marker-start="url(#m-{self.marker(color, reverse=True)})"'
        self.body.append(f'<path d="M {pts[0][0]:.1f} {pts[0][1]:.1f} {d}" {attrs}/>')
        if c["value"]:
            mx = sum(p[0] for p in pts) / len(pts)
            my = sum(p[1] for p in pts) / len(pts)
            self.body.extend(
                self.text_el(mx - 60, my - 10, 120, 20, c["value"], st)
            )

    # ---- output ----------------------------------------------------------
    def render(self) -> str:
        # Bounds first: vertex rectangles plus every edge's actual anchors and
        # waypoints (a detour may run far outside the vertex bounding box).
        xs: list[float] = []
        ys: list[float] = []
        xe: list[float] = []
        ye: list[float] = []
        for cid in list(self.cells):
            c = self.cells[cid]
            if c["vertex"]:
                g = self.abs_geom(cid)
                if g is not None:
                    xs.append(g[0])
                    ys.append(g[1])
                    xe.append(g[0] + g[2])
                    ye.append(g[1] + g[3])
            elif c["edge"]:
                pts = self.edge_points(cid)
                if pts:
                    for px, py in pts:
                        xs.append(px)
                        ys.append(py)
                        xe.append(px)
                        ye.append(py)
        # Draw afterwards so vertices and edges keep their original order.
        for cid in list(self.cells):
            c = self.cells[cid]
            if c["vertex"]:
                g = self.abs_geom(cid)
                if g is not None:
                    self.draw_vertex(cid, g)
            elif c["edge"]:
                self.draw_edge(cid)
        if not xs:
            return "<svg xmlns='http://www.w3.org/2000/svg' width='100' height='100'/>"
        pad = 20
        x0, y0 = min(xs) - pad, min(ys) - pad
        x1, y1 = max(xe) + pad, max(ye) + pad
        defs = ("<defs>" + "\n".join(self.defs) + "</defs>") if self.defs else ""
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{x1 - x0}" height="{y1 - y0}" '
            f'viewBox="{x0} {y0} {x1 - x0} {y1 - y0}" font-family="sans-serif">\n'
            f"{defs}\n" + "\n".join(self.body) + "\n</svg>"
        )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("file", help="path to the .drawio file")
    ap.add_argument("-o", "--output", help="output .svg path (default: input name)")
    ap.add_argument("--png", action="store_true", help="also write .png (needs cairosvg)")
    args = ap.parse_args()

    out_svg = args.output or (args.file.rsplit(".", 1)[0] + ".svg")
    try:
        r = Renderer()
        r.load(args.file)
        svg = r.render()
        with open(out_svg, "w", encoding="utf-8") as f:
            f.write(svg)
        print(f"Wrote {out_svg} ({len(r.cells)} cells)")
    except ET.ParseError as exc:
        print(f"ERROR: not well-formed XML: {exc}")
        return 1
    except OSError as exc:
        print(f"ERROR: {exc}")
        return 2

    if args.png:
        try:
            import cairosvg  # type: ignore
            png = out_svg.rsplit(".", 1)[0] + ".png"
            cairosvg.svg2png(url=out_svg, write_to=png)
            print(f"Wrote {png}")
        except ImportError:
            print("WARNING: --png needs cairosvg (pip install cairosvg); skipping PNG")
    return 0


if __name__ == "__main__":
    sys.exit(main())
