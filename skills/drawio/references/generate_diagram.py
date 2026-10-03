#!/usr/bin/env python3
"""Transient generator template for .drawio files.

Copy, adapt, run, then paste the printed XML into the .drawio file and delete
this script. The .drawio file is the single source of truth (drawio skill §9).

Rules for a transient generator:
- deterministic: stable cell ordering and ids across runs, no randomness/timestamps
- emit the full uncompressed structure from skill §1 (no comments, bare cells)
- verify the result afterwards with references/verify_diagram.py

Usage:
    python3 generate_diagram.py > out.drawio
"""

from __future__ import annotations

# ---- layout constants ---------------------------------------------------
GAP = 60        # px between shapes (skill: >= 40, 60 preferred)
COL_W = 180     # column width
ROW_H = 60      # row height
PAGE_W = 1169   # A4 landscape
PAGE_H = 827


def esc(s) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("\n", "&#10;")
    )


def box(cid, label, x, y, w=COL_W, h=ROW_H, fill="#dae8fc", stroke="#6c8ebf",
        extra=""):
    style = (f"rounded=1;whiteSpace=wrap;html=1;fillColor={fill};"
             f"strokeColor={stroke};{extra}")
    return (
        f'<mxCell id="{cid}" value="{esc(label)}" style="{style}" vertex="1" parent="1">\n'
        f'  <mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/>\n'
        f'</mxCell>'
    )


def container(cid, label, x, y, w, h, extra="swimlane;startSize=26;"):
    style = f"{extra}html=1;"
    return (
        f'<mxCell id="{cid}" value="{esc(label)}" style="{style}" vertex="1" parent="1">\n'
        f'  <mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/>\n'
        f'</mxCell>'
    )


def child(cid, label, parent, x, y, w=COL_W - 40, h=40, fill="#d5e8d4",
          stroke="#82b366"):
    style = f"rounded=1;whiteSpace=wrap;html=1;fillColor={fill};strokeColor={stroke};"
    return (
        f'<mxCell id="{cid}" value="{esc(label)}" style="{style}" vertex="1" parent="{parent}">\n'
        f'  <mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/>\n'
        f'</mxCell>'
    )


def edge(cid, source, target, label="", anchor=0.5, start_anchor=1.0):
    """Left-to-right edge; override anchors for top-to-bottom flow."""
    style = (
        f"edgeStyle=orthogonalEdgeStyle;html=1;endArrow=classic;"
        f"exitX={start_anchor};exitY={anchor};entryX=0;entryY={anchor};"
    )
    val = f' value="{esc(label)}"' if label else ""
    return (
        f'<mxCell id="{cid}"{val} style="{style}" edge="1" parent="1" '
        f'source="{source}" target="{target}">\n'
        f'  <mxGeometry relative="1" as="geometry"/>\n'
        f'</mxCell>'
    )


def emit(cells: list[str], page_w: int = PAGE_W, page_h: int = PAGE_H) -> str:
    body = "\n".join(cells)
    return (
        '<mxfile host="app.diagrams.net" version="24.0.0" agent="kilo">\n'
        '  <diagram id="page-1" name="Page-1">\n'
        '    <mxGraphModel dx="800" dy="600" grid="1" gridSize="10" guides="1" '
        f'tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" '
        f'pageWidth="{page_w}" pageHeight="{page_h}" math="0" shadow="0">\n'
        '      <root>\n'
        '        <mxCell id="0"/>\n'
        '        <mxCell id="1" parent="0"/>\n'
        f"{body}\n"
        '      </root>\n'
        '    </mxGraphModel>\n'
        '  </diagram>\n'
        '</mxfile>\n'
    )


# ---- example: data-driven pipeline (edit DATA, layout is computed) ------
PIPELINE = ["Collect", "Clean", "Transform", "Load", "Report"]


def main() -> None:
    cells: list[str] = []
    x = 40
    prev = None
    for i, step in enumerate(PIPELINE, start=2):
        cid = f"s{i}"
        cells.append(box(cid, step, x, 40))
        if prev:
            cells.append(edge(f"e{i}", prev, cid))
        prev = cid
        x += COL_W + GAP
    # Size the page to the content so the verifier's on-page check passes.
    total_w = x - GAP + 40  # last box right edge + right margin
    page_w = max(PAGE_W, total_w)
    print(emit(cells, page_w=page_w))


if __name__ == "__main__":
    main()
