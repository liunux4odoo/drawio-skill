# draw.io Reference: Common Patterns & Styles

Copy-paste templates for the drawio skill. All patterns use only basic shapes,
which render identically in any draw.io client. Wrap the cells below in the
§1 structure of SKILL.md (root cells `id="0"` / `id="1"` included).

## Flowchart

Key styles:
- decision diamond: `rhombus;whiteSpace=wrap;html=1;`
- process box: `rounded=1;whiteSpace=wrap;html=1;`
- terminator (start/end): `rounded=1;arcSize=50;whiteSpace=wrap;html=1;`

```xml
<mxCell id="d1" value="valid?" style="rhombus;whiteSpace=wrap;html=1;" vertex="1" parent="1">
  <mxGeometry x="320" y="40" width="120" height="80" as="geometry"/>
</mxCell>
<mxCell id="e1" value="yes" style="edgeStyle=orthogonalEdgeStyle;exitX=0.5;exitY=1;entryX=0.5;entryY=0;html=1;endArrow=classic;" edge="1" parent="1" source="d1" target="s1">
  <mxGeometry relative="1" as="geometry"/>
</mxCell>
```

## Org Chart (tree)

Same-level nodes share a row `y`; children fan out below their parent, each
child centered under its parent's column. Use a child-x offset table rather
than eyeballing.

```xml
<mxCell id="ceo" value="CEO" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;" vertex="1" parent="1">
  <mxGeometry x="320" y="40" width="160" height="50" as="geometry"/>
</mxCell>
<mxCell id="eng" value="Engineering" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;" vertex="1" parent="1">
  <mxGeometry x="120" y="180" width="160" height="50" as="geometry"/>
</mxCell>
<mxCell id="ops" value="Operations" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;" vertex="1" parent="1">
  <mxGeometry x="520" y="180" width="160" height="50" as="geometry"/>
</mxCell>
<mxCell id="e-ceo-eng" style="edgeStyle=orthogonalEdgeStyle;exitX=0.33;exitY=1;entryX=0.5;entryY=0;html=1;endArrow=classic;" edge="1" parent="1" source="ceo" target="eng">
  <mxGeometry relative="1" as="geometry"/>
</mxCell>
<mxCell id="e-ceo-ops" style="edgeStyle=orthogonalEdgeStyle;exitX=0.66;exitY=1;entryX=0.5;entryY=0;html=1;endArrow=classic;" edge="1" parent="1" source="ceo" target="ops">
  <mxGeometry relative="1" as="geometry"/>
</mxCell>
```

## Swimlane (two lanes)

Children of a lane use coordinates **relative to the lane**, and must sit below
the lane's title bar: `y >= startSize + margin` (with `startSize=26`, use
`y >= 40`).

```xml
<mxCell id="laneA" value="Frontend" style="swimlane;startSize=26;html=1;" vertex="1" parent="1">
  <mxGeometry x="40" y="40" width="240" height="200" as="geometry"/>
</mxCell>
<mxCell id="laneB" value="Backend" style="swimlane;startSize=26;html=1;" vertex="1" parent="1">
  <mxGeometry x="360" y="40" width="240" height="200" as="geometry"/>
</mxCell>
<mxCell id="f1" value="UI" style="rounded=1;whiteSpace=wrap;html=1;" vertex="1" parent="laneA">
  <mxGeometry x="40" y="60" width="160" height="40" as="geometry"/>
</mxCell>
<mxCell id="b1" value="API" style="rounded=1;whiteSpace=wrap;html=1;" vertex="1" parent="laneB">
  <mxGeometry x="40" y="60" width="160" height="40" as="geometry"/>
</mxCell>
<mxCell id="e-ab" style="edgeStyle=orthogonalEdgeStyle;exitX=1;exitY=0.5;entryX=0;entryY=0.5;html=1;endArrow=classic;" edge="1" parent="1" source="f1" target="b1">
  <mxGeometry relative="1" as="geometry"/>
</mxCell>
```

## Entity / ER

Entity box with fields; primary key styled bold. Relationship edge carries the
cardinality label.

```xml
<mxCell id="user" value="User&#10;&#10;id (PK)&#10;name&#10;email" style="rounded=0;whiteSpace=wrap;html=1;align=left;verticalAlign=top;spacing=10;" vertex="1" parent="1">
  <mxGeometry x="40" y="40" width="180" height="90" as="geometry"/>
</mxCell>
<mxCell id="order" value="Order&#10;&#10;id (PK)&#10;user_id (FK)" style="rounded=0;whiteSpace=wrap;html=1;align=left;verticalAlign=top;spacing=10;" vertex="1" parent="1">
  <mxGeometry x="420" y="40" width="180" height="90" as="geometry"/>
</mxCell>
<mxCell id="e-uo" value="1:N" style="edgeStyle=orthogonalEdgeStyle;exitX=1;exitY=0.5;entryX=0;entryY=0.5;html=1;endArrow=classic;startArrow=classic;" edge="1" parent="1" source="user" target="order">
  <mxGeometry relative="1" as="geometry"/>
</mxCell>
```

## Style catalog

### Standard fill palette

| Color | fillColor / strokeColor |
|---|---|
| Blue | `#dae8fc` / `#6c8ebf` |
| Green | `#d5e8d4` / `#82b366` |
| Yellow | `#fff2cc` / `#d6b656` |
| Orange | `#ffe6cc` / `#d79b00` |
| Red | `#f8cecc` / `#b85450` |
| Purple | `#e1d5e7` / `#9673a6` |

### Shape styles

- Rounded box: `rounded=1;whiteSpace=wrap;html=1;`
- Sharp box: `rounded=0;whiteSpace=wrap;html=1;`
- Ellipse: `ellipse;whiteSpace=wrap;html=1;`
- Diamond: `rhombus;whiteSpace=wrap;html=1;`
- Hexagon: `shape=hexagon;whiteSpace=wrap;html=1;`
- Cylinder (DB): `shape=cylinder3;whiteSpace=wrap;html=1;boundedLbl=1;`
- Parallelogram: `shape=parallelogram;whiteSpace=wrap;html=1;`
- Swimlane: `swimlane;startSize=26;html=1;`
- Text-only: `text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;whiteSpace=wrap;`
- Transparent container: `rounded=1;whiteSpace=wrap;html=1;fillColor=none;`

### Edge styles

- Arrow: `endArrow=classic;` (solid `block`, open `open`, none `none`)
- Orthogonal routing: `edgeStyle=orthogonalEdgeStyle;`
- Curved: `curved=1;`
- Dashed: `dashed=1;`
- Label background (keep label readable over lines): `labelBackgroundColor=#ffffff;`
- Animated flow: `flowAnimation=1;`

### Text styles

- Font size: `fontSize=12;`
- Bold / italic / underline: `fontStyle=1;` / `fontStyle=2;` / `fontStyle=4;` (combine by adding)
- Alignment: `align=center;` (or `left`/`right`), `verticalAlign=middle;`
- Color: `fontColor=#333333;`
- Line breaks in `value`: `&#10;` (plain) or `<br>` when `html=1`
