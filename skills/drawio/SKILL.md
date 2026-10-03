---
name: drawio
description: Create, modify, and refactor draw.io diagram files (.drawio) directly as XML. Use whenever the user asks to draw, create, edit, update, or generate a diagram/flowchart/architecture/mindmap as a .drawio file, or to modify an existing one in the workspace. The agent writes raw XML and usually cannot see the rendered result, so the skill enforces layout planning and coordinate/XML checks on every change, with rendered-image verification as a supplement for vision-capable agents.
---

# Draw.io Diagram Authoring for Code Agents

You author **draw.io XML files** (`.drawio`). Any draw.io client (editor, viewer, or renderer) interprets the XML. You usually do **not** see the rendered diagram, so if coordinates or routing are wrong the diagram is broken and you may not notice.

**Correctness model, in priority order:**
1. **Layout planning + coordinate/XML checking is the primary mechanism and must run on every change** — creating, editing, or regenerating.
2. **If your model is vision-capable, add a rendered-image check as a supplement** — it catches what coordinate math misses, but it never replaces the layout planning step.

## 1. File Format Fundamentals

A `.drawio` file is XML. The canonical (non-compressed) structure is:

```xml
<mxfile host="app.diagrams.net" version="24.0.0" agent="kilo">
  <diagram id="page-1" name="Page-1">
    <mxGraphModel dx="800" dy="600" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="827" pageHeight="1169" math="0" shadow="0">
      <root>
        <mxCell id="0" />
        <mxCell id="1" parent="0" />
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>
```

Insert all user cells as **siblings after `<mxCell id="1" parent="0" />`**. A `.drawio` file can contain multiple `<diagram>` elements, one per page.

### Non-negotiable rules

1. **Keep both root cells**: `<mxCell id="0" />` and `<mxCell id="1" parent="0" />` must always exist and stay untouched.
2. **All user cells are siblings inside `<root>`** and use `parent="1"` for top-level shapes, or `parent="<container-id>"` for children of a container. Never nest one `<mxCell>` inside another `<mxCell>` — a child is a sibling whose `parent` points to the container's id.
3. **Unique `id`s** — start from `"2"` and never reuse. Use readable ids (e.g. `"start"`, `"edge-auth-to-db"`) as long as they are unique within the file.
4. **XML well-formedness**: every tag closed, attributes quoted, values escaped (`&lt; &gt; &amp; &quot; &#10;` for newline inside `value`). One unclosed tag breaks the whole file.
5. **Never include XML comments** `<!-- ... -->` anywhere in the file. draw.io strips them and they confuse the editor. If you must record intent, put it in the commit message or a side note, never in the XML.
6. **Indent with 2 spaces** and keep `mxGeometry` on one line per cell so diffs stay readable (waypoint arrays in §6 are the only exception).

### Compressed / embedded diagrams — CRITICAL

If an existing file's `<diagram>` content is **not XML** but a long base64 string (e.g. `zZ...`), the diagram payload is gzip/deflate-compressed. **Do not hand-edit compressed payloads.** In that case:
- If the user only needs small, well-specified changes, ask them to export the file in uncompressed XML form (draw.io: `Extras → Uncompressed XML`) so you can edit it, **or**
- Rewrite the whole file from scratch in uncompressed XML (acceptable when the diagram is small and you reproduce it faithfully).

Also beware **embedded formats**: `.drawio.svg` and `.drawio.png` are SVG/PNG files with the XML hidden inside metadata. Editing them as text breaks the file. If the user points you at one, ask them to export it as plain `.drawio` (uncompressed XML) first.

Always write **uncompressed XML** yourself (the format above).

## 2. Working on an Existing File

1. **Read the file first**, in full. Identify the current cells, their ids, coordinates, and edges before touching anything.
2. **Locate the exact cell to change by its `id`** — never guess or duplicate. If ids are numeric sequential, track which are taken.
3. **Preserve everything you are not asked to change**: other pages (`<diagram>` elements), other cells, styles, geometry, and page attributes (`pageWidth`, `pageHeight`, `page`). Only the cells you intend to change may differ.
4. For multi-page files, only touch the diagram page the user means; if ambiguous, ask.

## 3. Layout Planning & Checking — Required for Every Change

Layout planning is **not** a creation-only step. It applies to **every modification**, no matter how small: a single added node can introduce an overlap or an edge crossing even when everything else is unchanged. Never skip §3 on the assumption that an edit is trivial.

### 3.1 Creating a diagram: plan coordinates first

You may not be able to see the result, so layout is a math exercise. Follow this sequence:

1. Decide a grid: standard **column width ~160-200px**, row height ~60-80px, **gap ≥ 40px** between all elements (60px preferred).
2. Assign each shape an `(x, y, width, height)` slot on that grid before writing XML. Sketch it in your reasoning, not in the file.
3. Place containers/regions first, then their children **relative to the container's origin** (children use coordinates relative to the container, not absolute).
4. Keep the whole diagram within a single page: for A4 portrait (pageWidth 827) use `x: 40..780`, `y: 40..1080`; for landscape keep `y: 40..760`. If the diagram is large, prefer a wider/shorter layout rather than going off-page.
5. **Route edges last**, mentally tracing each one as described in §6.

See the numeric grid in §7 for concrete column/row start points.

### 3.2 Editing a diagram: re-check the affected layout

Once you have located the target cell (§2), make the **smallest targeted change** (id-based update/add/delete), then recompute the affected region:

1. New or moved cells do not overlap existing ones (gaps ≥40px).
2. New edges do not cross unrelated shapes.
3. Children stay inside their containers (and below swimlane headers, §4.2).
4. Everything remains on-page.
5. If the change ripples (e.g. a new node forces neighbors to move), re-plan the affected region with §3.1's grid and re-verify — do not just nudge numbers until it "looks close".

## 4. Element Reference

Use the structure from §1 and insert cells as siblings **after** `<mxCell id="1" parent="0" />`.

### 4.1 Shape (vertex)

```xml
<mxCell id="2" value="Label" style="rounded=1;whiteSpace=wrap;html=1;" vertex="1" parent="1">
  <mxGeometry x="40" y="40" width="160" height="60" as="geometry" />
</mxCell>
```

- `vertex="1"` marks a shape; `edge="1"` marks a connector.
- `parent="1"` for top-level; `parent="containerId"` for a child of a container.
- `value` is the displayed label. Use `&#10;` for a line break. With `html=1` the label is HTML, so `<br>`, `<b>`, `<i>`, and `<font color="#...">` are also valid inside `value`.
- Text-only label: `style="text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;whiteSpace=wrap;fontSize=14;"`.

### 4.2 Container (swimlane / group)

A container is just a shape whose id other cells use as `parent`:

```xml
<mxCell id="backend" value="Backend" style="swimlane;startSize=26;html=1;" vertex="1" parent="1">
  <mxGeometry x="280" y="40" width="200" height="220" as="geometry" />
</mxCell>
<mxCell id="svc1" value="API Service" style="rounded=1;whiteSpace=wrap;html=1;" vertex="1" parent="backend">
  <mxGeometry x="20" y="60" width="160" height="40" as="geometry" />
</mxCell>
```

- Child coordinates are **relative to the container's top-left corner** (the whole cell, including a swimlane's title bar).
- For swimlanes, children must sit **below the title bar**: `y ≥ startSize + margin` (with `startSize=26`, use `y ≥ 40`). A child placed at `y < startSize` is hidden behind the header.
- Keep children ≥20px inside the container bounds.
- For **pure-group containers** (a plain rectangle that holds children), add `container=1;` to the style so draw.io treats it as a container — verify the render afterwards, since behavior varies slightly across draw.io versions.
- If a container is purely visual, use `fillColor=none;` so it does not cover its children.

### 4.3 Edge (connector)

```xml
<mxCell id="e1" value="auth ok" style="edgeStyle=orthogonalEdgeStyle;html=1;endArrow=classic;" edge="1" parent="1" source="login" target="dashboard">
  <mxGeometry relative="1" as="geometry" />
</mxCell>
```

- `source` / `target` must reference existing **vertex** ids.
- The default `mxGeometry relative="1"` with no points is the simplest correct form. Add `<Array as="points"><mxPoint .../></Array>` only for waypoints (§6 rule 5).
- Two edges between the same pair of cells must not share a path (§6 rule 2).

### 4.4 Style cheat-sheet

- Shape base: `rounded=1;whiteSpace=wrap;html=1;` (rounded corners) or `rounded=0;` for sharp.
- Fill/stroke: use draw.io's standard palette (Blue `#dae8fc/#6c8ebf`, Green `#d5e8d4/#82b366`, Yellow `#fff2cc/#d6b656`, Orange `#ffe6cc/#d79b00`, Red `#f8cecc/#b85450`, Purple `#e1d5e7/#9673a6`).
- Edge: `endArrow=classic;` (or `block`), `edgeStyle=orthogonalEdgeStyle;` for orthogonal routing, `curved=1;` for curved.
- Text: `fontSize=12;fontStyle=1;` (1 = bold, 2 = italic), `align=center;` / `align=left;`.
- For the full shape/edge/text style catalog and copy-paste patterns (flowchart, org chart, swimlane, ER), see `references/patterns.md`.
- Do **not** invent icon-library styles (AWS/Azure/GCP shapes, `shape=mxgraph.aws4.xxx` etc.) from memory — the exact style strings are long and version-specific. If the workspace contains draw.io shape-library docs (e.g. a `docs/shape-libraries/` directory), consult those first. Otherwise, ask the user to enable the relevant library in their draw.io client and provide a reference file; stick to basic shapes, which always render.

## 5. Page Settings

- `page="1"` shows the page border/background; `page="0"` gives an infinite canvas.
- `pageWidth`/`pageHeight` set the page size in pixels. Defaults: A4 portrait 827×1169; landscape 1169×827.
- Keep `grid="1" gridSize="10"` and `guides="1"` — the client's snapping depends on them.
- Do not change page settings unless the user asks; a diagram that exceeds the page silently clips in the render.

## 6. Layout & Edge-Routing Rules

These rules exist because overlapping shapes and crossing lines are the #1 defect in agent-generated diagrams, and you may not see them. Apply them during §3 planning, not as an afterthought.

1. **Spacing**: minimum 40px gap between any two shapes, 60px preferred. Never touch or overlap bounding boxes.
2. **Shared paths**: two edges connecting the same pair of nodes MUST use different exit/entry anchors — e.g. first edge `exitX=1;exitY=0.3;entryX=0;entryY=0.3;`, second `exitX=1;exitY=0.7;entryX=0;entryY=0.7;`. Never both 0.5.
3. **Natural anchors**: for left-to-right flow use `exitX=1` → `entryX=0`; for top-to-bottom flow use `exitY=1` → `entryY=0`. Never attach at corners (both X and Y at 0 or 1 simultaneously).
4. **Obstacle avoidance**: before writing an edge, list every shape between source and target. If any shape is in the direct path, route around the outside of the diagram with waypoints at 20-30px clearance from shape boundaries. Never draw a line visually crossing another shape's bounding box.
5. **Waypoints** (L/U-shaped detours):

```xml
<mxCell id="e2" style="edgeStyle=orthogonalEdgeStyle;exitX=0.5;exitY=0;entryX=1;entryY=0.5;html=1;endArrow=classic;" edge="1" parent="1" source="hotfix" target="main">
  <mxGeometry relative="1" as="geometry">
    <Array as="points">
      <mxPoint x="760" y="60" />
      <mxPoint x="760" y="200" />
    </Array>
  </mxGeometry>
</mxCell>
```

6. **Layout zones**: organize shapes into columns/rows by flow direction (left→right or top→bottom). Space columns ~200px apart so edge channels exist between them. Route edges through the empty channels, not through shape rows.
7. **Self-check before writing**: for every edge ask (a) does it cross a shape that is not its source/target? (b) does it share a path with another edge? (c) does it attach at a corner? Fix all three before finalizing.

## 7. Numeric Layout Guide

| Element | Typical size | Spacing |
|---|---|---|
| Decision diamond | 120×60 | ≥60px gap |
| Process/step box | 160×50 | ≥60px gap |
| Container/swimlane | width ≥ 240 | children inset ≥20px |
| Edge channel between columns | — | ≥40px clear corridor |

Recommended column start points: col1 `x=40`, col2 `x=280`, col3 `x=520`, col4 `x=760`. Rows: `y=40`, `y=140`, `y=240`, ... on a 100px pitch. This grid keeps everything inside an A4-landscape page and leaves clean routing corridors. It matches §3.1: a 240px column pitch = ~160-200px shapes + the required 60px gap.

## 8. Verification — run on every change

### 8.1 Coordinate & XML checklist (primary, always)

Run this after every create **and** every edit, before reporting done:

1. **Mechanical validation first** — actually parse the file with a tool, never just re-read it. Prefer the bundled verifier, which checks structure AND geometry:
   ```bash
   python3 references/verify_diagram.py file.drawio
   ```
   At minimum, confirm the XML is well-formed:
   ```bash
   xmllint --noout file.drawio
   # or:
   python3 -c "import xml.dom.minidom, sys; xml.dom.minidom.parse(sys.argv[1])" file.drawio
   ```
   A parser catches unclosed tags, unquoted attributes, and escaping errors that re-reading can miss.
2. Root cells `id="0"` and `id="1"` present and untouched.
3. All cell ids unique.
4. Every edge `source`/`target` references an existing vertex id; every child `parent` references an existing container id.
5. No two shapes overlap (an error); shapes closer than the minimum gap are reported as a spacing warning (`verify_diagram.py --min-gap N` adjusts the threshold, default 40px).
6. No edge crosses a shape other than its source/target (curved edges are reported as a warning instead — crossing cannot be judged mechanically).
7. All coordinates and sizes are non-negative; children stay inside their containers (and below swimlane headers); everything fits on the page.
8. No label overflows its shape — `verify_diagram.py` reports this as a warning (horizontal when a line is wider than the shape, including over-long unbroken runs such as CJK text that draw.io clips even with `whiteSpace=wrap`, vertical when too many wrapped lines); `--strict` promotes it to an error.
9. Unrelated cells, pages, styles, and page attributes were preserved during edits.
10. The user's requested labels/values are exact (respect language, casing, and special chars).
11. Re-read the final file once more before reporting done.

### 8.2 Visual check (supplement — vision-capable models only)

The §8.1 checklist always runs. If your model can see images, **add** a rendered-image pass on top:

1. **Render to an image.** Use whatever renderer is available:
   - Prefer the draw.io CLI (`drawio --export --format png --output out.png file.drawio`) or a draw.io container image when installed.
   - **No draw.io CLI?** Use the bundled stdlib-only SVG exporter — it renders the basic shapes this skill produces (rect, rounded, rhombus, ellipse, swimlane, cylinder, hexagon, parallelogram, orthogonal edges with arrows) and is sufficient for this layout check:
     ```bash
     python3 references/render_drawio.py file.drawio -o out.svg
     python3 references/render_drawio.py file.drawio --png   # needs pip install cairosvg
     python3 references/render_drawio.py file.drawio --page 2   # multi-page: pick a page
     ```
   - Multi-page files are merged into one SVG by default; the exporter prints a
     NOTE when that happens. Use `--page` (1-based index or page name) to render
     a single page.
   - Or export via the draw.io client's PNG/SVG export if available.
   - If no renderer exists at all, skip this step and say so — §8.1 still applies.
   - Caveat: the Python exporter approximates draw.io (no HTML labels / icon shapes); exact-render mismatches are acceptable here — you are checking layout defects, not pixel fidelity.
2. **Inspect the rendered image against these defect categories:**
   - **Overlap** (critical): shapes covering each other inappropriately, content unreadable.
   - **Edge routing** (critical): lines/arrows crossing through shapes that are not their source or target; two edges overlapping each other.
   - **Text readability** (warning): labels cut off, clipped, overlapping, or too small to read.
   - **Layout quality** (warning): poor spacing, misalignment, cramped elements, off-page clipping.
   - **Rendering errors** (critical): missing, empty, or corrupted elements; wrong styles.
3. **Fix and re-verify.** If you find issues, correct the XML, re-render, and re-inspect. Iterate until clean; cap the loop (e.g. 3 attempts) and if problems persist, tell the user what remains rather than silently shipping a broken diagram.
4. For icon-library shapes you could not verify from documentation, the rendered image is your chance to catch wrong style strings — check them specifically.

## 9. When to Generate via a Script

**Default: write/edit the XML directly.** Direct XML editing keeps the `.drawio` file as the single source of truth and stays safe when the user hand-edits the diagram in a draw.io client. Reach for a generation script only when it clearly pays off.

Prefer a **one-off (transient) generator** when:
- The diagram is data-driven, highly repetitive, or large (org charts, cloud topologies, sequence/timeline diagrams, anything with dozens of near-identical nodes).
- Layout benefits from programmatic computation: grid loops, automatic spacing, collision-avoidance logic.
- Writing the cells by hand would mean pasting dozens of near-identical blocks with hand-computed coordinates.

Transient generator workflow:
1. Write a script (e.g. Python) that computes the cells and coordinates, run it, and paste the emitted XML into the `.drawio` file. A ready-made template with `box()`/`container()`/`child()`/`edge()` helpers and a data-driven layout loop lives in `references/generate_diagram.py` — adapt it rather than starting from scratch.
2. **The script is disposable; the `.drawio` file remains the single source of truth.**
3. Requirements: **deterministic output** (stable cell ordering and ids across runs — no randomness, no timestamps), and cells emitted in the §1 structure.
4. After pasting, run the full §8 verification (mechanical parse + coordinate/XML checklist always; visual pass if available).

**Verification script (recommended — even more valuable than a generator):** for non-vision work, writing the geometric checks by hand is error-prone. Use `references/verify_diagram.py`, which parses the `.drawio` and mechanically asserts every §8.1 geometric item: no bounding-box overlaps, gaps ≥40px, every edge `source`/`target` exists, no edge rect crosses a shape that is not its source/target, children inside containers, all on-page. It is the most reliable way to honor "layout check on every change" without vision, and is reusable across every subsequent edit.

**Do NOT keep a persistent generator / regenerate over a file** when:
- The user edits the diagram in a draw.io client — the file diverges from the script, and re-running clobbers their manual changes. This is the dominant case for `.drawio` files.
- Exception: the user explicitly wants a maintained generator (diagram regenerated from data on a schedule and never hand-edited). Then keep it as a real artifact, note it clearly, and warn the user before any rerun that could override their edits.

## 10. Workflow

1. Read or create the target `.drawio` file.
2. Plan / re-derive the layout (§3) — required for both creation and edits.
3. Write the XML directly, or use a transient generator for complex data-driven cases (§9).
4. Verify (§8): mechanically parse the file, then run the coordinate/XML checklist — always; add the rendered-image pass when vision-capable and a renderer exists.
5. Tell the user the file is updated and which page/cells changed. If you could not verify something visually (e.g. icon-library styling, or no renderer available), say so explicitly instead of claiming success.

## Reference Files (in this skill directory)

| File | Purpose |
|---|---|
| `references/verify_diagram.py` | Mechanical verifier: parse + structure + geometry checks + label-overflow heuristic + edge anchor rules (§6 rules 2–3). Run after every create/edit (§8.1). |
| `references/render_drawio.py` | Stdlib-only SVG exporter (optional PNG via cairosvg) for the §8.2 visual check when no draw.io CLI is installed. |
| `references/generate_diagram.py` | Transient generator template with `box()`/`container()`/`child()`/`edge()` helpers and a data-driven layout loop (§9). |
| `references/patterns.md` | Copy-paste patterns (flowchart, org chart, swimlane, ER) and the full shape/edge/text style catalog (§4.4). |
