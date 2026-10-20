# Work Skills

A collection of [Agent Skills](https://agentskills.io) for AI agents. Each skill
lives in its own folder under `skills/` following the Agent Skills layout
(`<skill-name>/SKILL.md`), so any skill-capable agent can load it.

## Contents

```
skills/
├── drawio/
│   ├── SKILL.md              # create/edit draw.io XML diagrams
│   └── references/
│       ├── verify_diagram.py     # mechanical verifier: structure + geometry + label overflow
│       ├── render_drawio.py      # stdlib-only SVG exporter (optional PNG via cairosvg)
│       ├── generate_diagram.py   # transient generator template (box/edge/container helpers)
│       └── patterns.md           # copy-paste patterns + full style catalog
├── quarkdown/
│   ├── SKILL.md              # author .qd documents (typeset HTML/PDF/slides/wikis)
│   ├── references/
│   │   └── quick-reference.md    # copy-paste syntax for common tasks + wiki pointers
│   └── scripts/
│       ├── md2pdf.py             # plain Markdown → PDF via a generated .qd template
│       └── extract_docx_style.py # docx / docx-generator → reusable .qd template
├── skill-hub/
│   ├── SKILL.md              # install/maintain skills from user-specified URLs
│   ├── references/
│   │   ├── commands.md           # every verb/flag, URL forms, update flow
│   │   ├── agents.md             # agent alias table, env roots, path sources
│   │   └── registry.md           # registry schema, migrations, link vs copy
│   └── scripts/
│       └── skill_hub.py          # stdlib-only registry: add/install/update/list/status/uninstall
└── qwenpaw/
    ├── SKILL.md              # query QwenPaw agents' accumulated memory
    └── scripts/
        ├── qwenpaw_agents.py     # list/find QwenPaw agents
        └── qwenpaw_search.py     # search one agent's ReMe memory index
```

## Installation

Each skill lives at `skills/<name>/` following the Agent Skills layout
(`<skill-name>/SKILL.md`), so any skill-capable agent can load it:

- **Claude Code / Claude**: install the skill folder into your agent's skills
  directory.
- **Kilo**: add `skills/<name>` to the `skills.paths` list in `kilo.json`, or
  copy the folder into `.kilo/skills/` of any project.
- **Manual**: copy the whole skill folder wherever your agent expects skills
  (the `references/` and `scripts/` subfolders must travel with `SKILL.md`).

Once installed, just ask in natural language — e.g. *"Create a login flow
diagram as `login.drawio`"*, *"Write a PDF-ready report in Quarkdown"*, or
*"Ask the travel assistant what it knows about visa documents."*

## Skills

### Drawio (`skills/drawio/`)

Teaches an agent how to create, modify, and refactor **draw.io diagram files**
(`.drawio`) directly as XML. Any draw.io client (editor, viewer, renderer)
interprets the XML; the agent writes raw XML and usually cannot see the rendered
result, so the skill enforces layout planning and coordinate/XML checks on every
change, with rendered-image verification as a supplement for vision-capable
agents.

Usage workflow: plan the layout in coordinates (§3 of `SKILL.md`), write the
XML directly or via a transient generator for data-driven diagrams, verify
mechanically on every change with `references/verify_diagram.py`, and (if
vision-capable) render `references/render_drawio.py file.drawio -o out.svg` and
visually inspect.

```bash
# Verify a file (exit 0 clean, 1 errors; --strict promotes warnings)
python3 references/verify_diagram.py file.drawio [--min-gap 40] [--strict]

# Render to SVG (no dependencies); --png needs cairosvg
python3 references/render_drawio.py file.drawio [-o out.svg] [--png]

# Transient generator template (edit DATA, then paste stdout into the .drawio)
python3 references/generate_diagram.py > out.drawio
```

### Quarkdown (`skills/quarkdown/`)

Teaches an agent to author **Quarkdown** (`.qd`) documents — a Markdown-superset
typesetting language that compiles to HTML, PDF, or plaintext for articles,
reports, slides, books, wikis, and static sites. `SKILL.md` lists every
capability (metadata, math, figures, tables, cross-references, layout, slides,
multi-file projects, data & scripting) and maps each to the relevant page of the
offline wiki shipped with Quarkdown. `references/quick-reference.md` provides
copy-paste syntax for the most common tasks, so most documents compile without
opening the wiki.

Compile to verify (always `--strict`, output to a scratch dir):

```bash
quarkdown c main.qd --strict --out /tmp/quarkdown-verify   # HTML
quarkdown c main.qd --pdf --strict --out /tmp/quarkdown-verify  # PDF
```

To turn a **plain Markdown** file into a PDF without authoring `.qd`, use the
bundled helper (it builds a temporary Quarkdown template, compiles, and cleans
up — the source `.md` is never modified):

```bash
python3 scripts/md2pdf.py input.md [-o out.pdf] [--theme ...] [--numbered on|off]
```

To turn a **`.docx`** (or a `.py` that generates one) into a reusable Quarkdown
template — fonts, sizes, colors, paragraph spacing, alignment, and heading
numbering — use the style extractor:

```bash
python3 scripts/extract_docx_style.py input.docx [-o template.qd] [--dry-run]
```

### Skill Hub (`skills/skill-hub/`)

Teaches an agent to **install and maintain a user-curated set of skills** from
URLs the user supplies. The user provides a tarball URL; the helper downloads
it once to `~/.local/share/skill-hub/skills/<name>/` and registers it in
`~/.config/skill-hub/registry.json`. The agent then links (or copies) that
store entry into one or more target directories — typically the `skills/`
folders of various agents or projects.

- **Bundle mode**: if the URL's tarball extracts to a `skills/<child>/SKILL.md`
  layout, the helper registers every child in one call (typical for repos that
  ship several skills together).
- **Name inference**: `add <url>` (no name) reads `SKILL.md` frontmatter or
  falls back to the URL basename; the explicit name always wins.
- **Update v0.2**: tries `HTTP HEAD` first (ETag/Last-Modified) and skips the
  full download when the server says "not modified"; falls back to SHA-256
  comparison when HEAD can't decide.
- **Name collisions** are explicit errors — no auto-namespacing.

The skill does **not** search, browse, or recommend skills — only
install/maintain what the user has pointed at.

```bash
HUB=~/.local/share/work-skills/skills/skill-hub/scripts/skill_hub.py

python3 $HUB add   [<name>] <tarball-url>    # download + register (1 or N skills)
python3 $HUB install <name> <target>         # symlink (default)
python3 $HUB install <name> <target> --copy  # duplicate
python3 $HUB update [name]                   # HEAD check; refresh all installs
python3 $HUB list
python3 $HUB status <name>                   # installed vs latest
python3 $HUB uninstall <name> <target>       # remove install (store kept)
```

### QwenPaw (`skills/qwenpaw/`)

Teaches an agent to query **QwenPaw** agents' accumulated experience and memory.
Each QwenPaw agent keeps an isolated memory (notes plus a ReMe index); the skill
first resolves the right agent with `scripts/qwenpaw_agents.py`, then searches
its memory with `scripts/qwenpaw_search.py --agent <id> "<query>"`. The scripts
are read-only and never write to QwenPaw's index.

```bash
python3 scripts/qwenpaw_agents.py                    # list all agents + memory size
python3 scripts/qwenpaw_search.py --agent travel-assistant "签证材料清单"
```

The scripts need the QwenPaw runtime's Python (where `reme-ai` is installed).

## License

Apache 2.0 — the drawio skill is derived from the prompt engineering in
[next-ai-draw-io](https://github.com/DayuanJiang/next-ai-draw-io).
