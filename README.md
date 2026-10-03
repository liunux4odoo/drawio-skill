# Drawio Skill

A [Agent Skills](https://agentskills.io) skill that teaches an AI agent how to
create, modify, and refactor **draw.io diagram files** (`.drawio`) directly as
XML. Any draw.io client (editor, viewer, renderer) interprets the XML; the
agent writes raw XML and usually cannot see the rendered result, so the skill
enforces layout planning and coordinate/XML checks on every change, with
rendered-image verification as a supplement for vision-capable agents.

## Contents

```
skills/
└── drawio/
    ├── SKILL.md              # skill instructions (the entry point)
    └── references/
        ├── verify_diagram.py     # mechanical verifier: structure + geometry + label overflow
        ├── render_drawio.py      # stdlib-only SVG exporter (optional PNG via cairosvg)
        ├── generate_diagram.py   # transient generator template (box/edge/container helpers)
        └── patterns.md           # copy-paste patterns + full style catalog
```

## Installation

The skill lives at `skills/drawio/` following the Agent Skills layout
(`<skill-name>/SKILL.md`), so any skill-capable agent can load it:

- **Claude Code / Claude**: register this repository as a plugin marketplace, or
  install the `drawio` skill folder into your agent's skills directory.
- **Kilo**: add `skills/drawio` to the `skills.paths` list in `kilo.json`, or
  copy `skills/drawio/` into `.kilo/skills/` of any project.
- **Manual**: copy the whole `skills/drawio/` folder wherever your agent expects
  skills (the `references/` subfolder must travel with `SKILL.md`).

## Usage

Once installed, just ask in natural language, e.g.:

> Create a login flow diagram as `login.drawio`.

The agent will:

1. Plan the layout in coordinates (§3 of `SKILL.md`).
2. Write the XML directly, or use a transient generator for data-driven diagrams
   (`references/generate_diagram.py`).
3. Verify mechanically on every change — `references/verify_diagram.py`
   (structure, geometry, label overflow).
4. If vision-capable, render `references/render_drawio.py file.drawio -o out.svg`
   and visually inspect the result.

### Reference scripts

```bash
# Verify a file (exit 0 clean, 1 errors; --strict promotes warnings)
python3 references/verify_diagram.py file.drawio [--min-gap 40] [--strict]

# Render to SVG (no dependencies); --png needs cairosvg
python3 references/render_drawio.py file.drawio [-o out.svg] [--png]

# Transient generator template (edit DATA, then paste stdout into the .drawio)
python3 references/generate_diagram.py > out.drawio
```

## License

Apache 2.0 — derived from the prompt engineering in
[next-ai-draw-io](https://github.com/DayuanJiang/next-ai-draw-io).
