---
name: quarkdown
description: Author Quarkdown (.qd) documents, a Markdown-superset typesetting language that compiles to HTML, PDF, or plaintext. Use when the user wants to write or edit .qd files, produce typeset output (articles, reports, slides, books, wikis, notes, static sites) beyond what plain Markdown offers, or share structured plans in a presentation-ready format. Quarkdown adds function calls (`.func {arg}`), variables, layouts, math, diagrams, and document types (plain/paged/slides/docs).
---

# Quarkdown

Quarkdown is a Markdown flavor and typesetting system. It compiles `.qd` source files to HTML, PDF, or plaintext, extending CommonMark/GFM with function calls, variables, layouts, math, custom themes, and document types. Think of it as a more readable LaTeX.

## When to use

Use this skill when the user wants to write or edit a `.qd` file, or asks for typeset output (PDF, slides, paged article, themed wiki) instead of plain Markdown. Also when they want a polished, shareable version of a plan or report.

Do **not** use it when plain Markdown is the final target (chat, READMEs, GitHub issues).

## How to use this skill

- **`references/quick-reference.md`** (same directory): copy-paste syntax for the most common tasks — document setup, math, figures, tables, cross-references, layout, slides, includes. Start here; most documents need nothing else.
- **Capability catalog below**: everything Quarkdown can do, grouped by topic, each with the wiki page that explains it. Consult the wiki when a feature is not in the quick reference or you need details the snippets don't cover.
- Both reference the **offline wiki** shipped with Quarkdown. Resolve it once:

  ```bash
  QUARKDOWN_INSTALL="$(quarkdown doctor get install-dir)"
  # $QUARKDOWN_INSTALL/docs/wiki/*.qd   — wiki pages
  # $QUARKDOWN_INSTALL/docs/quarkdown-stdlib/   — stdlib API reference (HTML)
  ```

## Capability catalog

Every capability below maps to a page in `$QUARKDOWN_INSTALL/docs/wiki/`. Read the page before writing that feature. "→ quick-ref" marks capabilities covered by copy-paste snippets in `references/quick-reference.md`.

### Document setup

| You want to... | Wiki page |
|---|---|
| Set metadata (name, description, authors, keywords) | [document-metadata.qd](document-metadata.qd) → quick-ref |
| Choose output type: `plain`, `paged`, `slides`, `docs` | [document-types.qd](document-types.qd) → quick-ref |
| Set color + layout theme | [themes.qd](themes.qd) → quick-ref |
| Style elements globally (`.extend`, `.super`, `.css`) | [element-styling.qd](element-styling.qd) |
| Configure fonts | [font-configuration.qd](font-configuration.qd) |
| Page size/margins (`.pageformat`) | [page-format.qd](page-format.qd) → quick-ref |
| Multi-column layout | [multi-column-layout.qd](multi-column-layout.qd) |
| Content in page margins (`.pagemargin`) | [page-margin-content.qd](page-margin-content.qd) → quick-ref |
| Page counter (`.currentpage` / `.totalpages`) | [page-counter.qd](page-counter.qd) |
| Running headers with current heading (`.lastheading`) | [persistent-headings.qd](persistent-headings.qd) |
| Number headings/figures/tables/equations (`.numbering`) | [numbering.qd](numbering.qd) → quick-ref |
| Numbering for custom elements (`.numbered`) | [numbering.qd](numbering.qd#custom-numbered-elements) |
| Table of contents (`.tableofcontents`) | [table-of-contents.qd](table-of-contents.qd) → quick-ref |
| Bibliography / citations | [bibliography.qd](bibliography.qd) |
| Footnotes | [footnotes.qd](footnotes.qd) → quick-ref |
| Book cover | [book-cover.qd](book-cover.qd) |
| Paragraph style, caption position | [paragraph-style.qd](paragraph-style.qd), [caption-position.qd](caption-position.qd) |

### Markdown enhancements

| You want to... | Wiki page |
|---|---|
| Images with size/caption (figures) | [image-size.qd](image-size.qd), [figure.qd](figure.qd) → quick-ref |
| TeX equations (`$ ... $`, `$$$`) | [tex-formulae.qd](tex-formulae.qd) → quick-ref |
| Table caption | [table-caption.qd](table-caption.qd) |
| Code caption | [code-caption.qd](code-caption.qd) |
| Decorative headings (`#!`) | [decorative-headings.qd](decorative-headings.qd) |
| Alerts / typed quotes (`> Note:`, `> [!TIP]`) | [quote-types.qd](quote-types.qd) → quick-ref |
| Quotation source | [quotation-source.qd](quotation-source.qd) |
| Cross-references (`.ref {id}`) | [cross-references.qd](cross-references.qd) → quick-ref |
| Page breaks (`.pagebreak`, `.autopagebreak`) | [page-break.qd](page-break.qd) → quick-ref |
| Text symbols | [text-symbols.qd](text-symbols.qd) |
| Icons (`.icon`) | [icons.qd](icons.qd) |
| Emojis | [emojis.qd](emojis.qd) |

### Layout

| You want to... | Wiki page |
|---|---|
| Row/column/grid stacks (`.row`, `.column`, `.grid`) | [stacks.qd](stacks.qd) → quick-ref |
| Container blocks (`.container`) | [container.qd](container.qd) → quick-ref |
| Boxes with title + type (`.box`) | [box.qd](box.qd) → quick-ref |
| Alignment (`.align`) | [align.qd](align.qd) |
| Float content | [float.qd](float.qd) |
| Custom figures | [custom-figure.qd](custom-figure.qd) |
| Clip/crop | [clip.qd](clip.qd) |
| File tree (`.filetree`) | [file-tree.qd](file-tree.qd) |
| Collapsible sections | [collapsible.qd](collapsible.qd) |
| Landscape pages | [landscape-content.qd](landscape-content.qd) |
| Whitespace control | [whitespace.qd](whitespace.qd) |

### Multi-file projects

| You want to... | Wiki page |
|---|---|
| Include other `.qd` files (`.include`, `.includeall`) | [including-other-quarkdown-files.qd](including-other-quarkdown-files.qd) → quick-ref |
| Subdocuments / wikis (link `.qd` files, knowledge graph) | [subdocuments.qd](subdocuments.qd) |
| Include vs. reference, which to pick | [inclusion-vs-subdocuments.qd](inclusion-vs-subdocuments.qd) |
| Import external libraries | [importing-external-libraries.qd](importing-external-libraries.qd) |

### Variables & scripting

| You want to... | Wiki page |
|---|---|
| Variables (`.var`) | [variables.qd](variables.qd) → quick-ref |
| Conditionals (`.if`, `.ifnot`) | [conditional-statements.qd](conditional-statements.qd) → quick-ref |
| Loops (`.foreach`, `.repeat`) | [loops.qd](loops.qd) → quick-ref |
| Scoped variables (`.let`) | [let.qd](let.qd) |
| Destructuring | [destructuring.qd](destructuring.qd) |
| Optionality / null (`none`) | [none.qd](none.qd) |
| Math operations (`.math`, `.sum`, `.pow`, ...) | [math.qd](math.qd) |

### Data & tables

| You want to... | Wiki page |
|---|---|
| Generate tables programmatically (`.tablebyrows`, ...) | [table-generation.qd](table-generation.qd) |
| Manipulate tables (`.tabletranspose`, `.tablesort`, ...) | [table-manipulation.qd](table-manipulation.qd) |
| Table from CSV (`.csv`) | [table-from-csv.qd](table-from-csv.qd) → quick-ref |
| Data from JSON (`.json`) | [data-from-json.qd](data-from-json.qd) → quick-ref |
| Read file text (`.read`) | [file-text-content.qd](file-text-content.qd) |
| File name | [file-name.qd](file-name.qd) |
| List files in a directory | [listing-files.qd](listing-files.qd) |

### Charts & diagrams

| You want to... | Wiki page |
|---|---|
| XY charts (`.xy`) | [xy-chart.qd](xy-chart.qd) |
| Mermaid diagrams (`.mermaid`) | [mermaid-diagrams.qd](mermaid-diagrams.qd) → quick-ref |

### Text & code

| You want to... | Wiki page |
|---|---|
| Regex-based styling (`.match`) | [regex-match.qd](regex-match.qd) |
| Advanced text formatting | [text.qd](text.qd) |
| Advanced code blocks (`.code`) | [code.qd](code.qd) → quick-ref |
| Explicit line breaks | [line-breaks.qd](line-breaks.qd) |
| TeX macros | [tex-macros.qd](tex-macros.qd) |

### Slides

| You want to... | Wiki page |
|---|---|
| Configure slides (`.slides`, transition, controls) | [slides-configuration.qd](slides-configuration.qd) → quick-ref |
| Interactive fragments (`.fragment`) | [slides-fragment.qd](slides-fragment.qd) → quick-ref |
| Speaker notes | [slides-speaker-notes.qd](slides-speaker-notes.qd) |

### HTML & output

| You want to... | Wiki page |
|---|---|
| Embed raw HTML | [html.qd](html.qd) |
| Custom CSS (`.css`, `.cssproperties`) | [css.qd](css.qd) |
| HTML output options | [html-options.qd](html-options.qd) |
| SEO/AEO optimization | [seo-aeo-optimization.qd](seo-aeo-optimization.qd) |
| Static assets (`public/` dir) | [html-static-assets.qd](html-static-assets.qd) |

### Functions & types

| You want to... | Wiki page |
|---|---|
| Function call syntax (args, chaining, block bodies) | [syntax-of-a-function-call.qd](syntax-of-a-function-call.qd) → quick-ref |
| Declare custom functions (`.function`) | [declaring-functions.qd](declaring-functions.qd) → quick-ref |
| Extend/override functions (`.extend`) | [extending-functions.qd](extending-functions.qd) |
| Dynamic typing | [typing.qd](typing.qd) |
| Localization | [localization.qd](localization.qd) |
| Value types (string, number, boolean, range, color, ...) | `String`, `Number`, [boolean.qd](boolean.qd), [range.qd](range.qd), [color.qd](color.qd), ... in the wiki |

### Built-in libraries & CLI

| You want to... | Wiki page |
|---|---|
| Docs/wikis library (`.docs...`) | [docs-library.qd](docs-library.qd) |
| Academic paper library (`.theorem`, `.definition`, ...) | [paper-library.qd](paper-library.qd) |
| Compiler CLI (`quarkdown c`, options, permissions) | [cli-compiler.qd](cli-compiler.qd) |
| Full CLI options reference | [cli-options.qd](cli-options.qd) |
| PDF export | [pdf-export.qd](pdf-export.qd) → quick-ref |
| Project creator (`quarkdown create`) | [cli-project-creator.qd](cli-project-creator.qd) |
| Webserver / live preview | [cli-webserver.qd](cli-webserver.qd) |
| Doctor (`quarkdown doctor`) | [cli-doctor.qd](cli-doctor.qd) |

## Installing this skill

Quarkdown ships this skill and a full offline copy of its wiki and stdlib API reference. Locate the bundled copy with:

```bash
quarkdown doctor get agent-skill
```

- **Claude Code**: symlink the bundled skill into your skills directory:

  ```bash
  ln -s "$(quarkdown doctor get agent-skill)" ~/.claude/skills/quarkdown
  ```

- **Other agents**: point the agent at the returned path (or `echo "$(quarkdown doctor get agent-skill)/SKILL.md"`) and upload/copy the folder so `references/` (if any) travels with it.

If the skill doesn't spin up automatically, you can invoke `/quarkdown` to trigger it.

## New projects

If the user wants to start a new Quarkdown project, tell them to run `quarkdown create [dir]` themselves. It's an interactive wizard that prompts for values. Don't scaffold project files by hand.

## Workflow

1. **Locate** the install dir (snippet above).
2. **Check the quick reference** (`references/quick-reference.md`) for the features you need — copy the snippets and adapt.
3. **Read the wiki page** for any capability you need beyond the quick reference (see the catalog above). Read `docs/wiki/quickstart.qd` first if you don't know the syntax yet.
4. **Write** the `.qd` file.
5. **Compile to verify**: `quarkdown c <main>.qd --strict --out /tmp/quarkdown-verify`. `<main>` is usually `main.qd` but confirm against the project. `--strict` surfaces errors; `--out /tmp/quarkdown-verify` keeps build artifacts out of the user's project (otherwise output lands in `./quarkdown-output` relative to your CWD).
   - PDF export (`--pdf`) is slower because it spins up a headless browser. Only use it when the user asks for a PDF.
   - **Never** run live preview (`-p`, `-w`) yourself; it starts a long-running web server. Suggest the command to the user instead.
6. **Report** any compile errors back to the user.

## Troubleshooting

- **`quarkdown` command not found** — Quarkdown is not on `PATH` (or not installed). Check `quarkdown doctor` exists under the install dir, or ask the user how they invoke it.
- **PDF fails with `Chrome executable cannot be found at 'chrome-headless-shell'`** — PDF export needs a Chromium-family browser on the machine. Install one, or point Quarkdown at it explicitly: `quarkdown c main.qd --pdf --chrome-path /path/to/chrome`.
- **PDF fails with a Chrome sandbox error** — some environments block the Chromium sandbox. Retry with `--pdf-no-sandbox` (unsafe, only as a fallback).
- **Compile passes but output looks wrong** — re-run with `--strict` (if not already) and check the output directory; read the relevant wiki page under `docs/wiki/` for the feature you used. If nothing helps, consult `docs/wiki/cli-compiler.qd` for compiler behavior and known flags.
- **Output lands in the user's project unexpectedly** — you forgot `--out`. Always compile with `--out /tmp/quarkdown-verify` (or another scratch dir) unless the user asked for output in place.
- **Compilation error mentions a missing permission** — the document needs a [permission](cli-compiler.qd#permissions) it does not have (e.g. `network` for remote images, `global-read` for files outside the project). Recompile with `--allow <permission>`, or ask the user whether granting it is acceptable.

## Reference Files (in this skill directory)

| File | Purpose |
|---|---|
| `references/quick-reference.md` | Copy-paste syntax for the most common Quarkdown tasks, each with a link to the full wiki page for details. |
| `scripts/md2pdf.py` | Convert a plain Markdown file to PDF via a generated Quarkdown template (see "Converting Markdown to PDF" below). |
| `references/extract_docx_style.py` | Extract styles from a `.docx` (or a `.py` that generates one) into a reusable `.qd` template (see "Converting docx styles to a qd template" below). |

## Converting Markdown to PDF

Use `scripts/md2pdf.py` when the user hands you a **plain Markdown** file and wants a quick PDF (printing, sharing, delivery) — without authoring a `.qd` file. The helper wraps the Markdown in a temporary Quarkdown template, compiles it to PDF, moves the PDF to the target path, and cleans up. **Your source `.md` is never modified.**

```bash
python3 scripts/md2pdf.py input.md [-o out.pdf] [--theme ...] [--page ...]
    [--font ...] [--size 12] [--lineheight ...] [--spacing ...] [--indent ...]
    [--heading-color ...] [--numbered on|off] [--heading-style 1:large,2:medium]
    [--dry-run]
```

- Defaults: theme `paperwhite`, page `A4`, font `Noto Serif CJK SC` size `12pt`, lineheight `1.6`, spacing `0.5`, indent `0`.
- **Numbering is off by default**: Markdown headings usually carry their own numbers (e.g. `（一）`, `1.`), and Quarkdown's native numbering has no Chinese numerals — enabling it would double-number. Use `--numbered on` only when the heading text has no number prefix.
- **Plain-Markdown compatibility**: a line starting with `.` is parsed as a Quarkdown function call, and `$...$` may be parsed as math (`$100` renders fine in practice). The script never rewrites your content; if compilation fails it reports the error and points at likely offending lines.
- **Verify**: after the PDF is generated, spot-check the page count and a couple of headings / content in the output.

Exit codes: `0` success, `1` input/argument error, `2` compilation failure, `3` output move failure.

## Converting docx styles to a qd template

Use `references/extract_docx_style.py` when the user hands you a **`.docx` file** (or a `.py` script that generates one) and wants a reusable Quarkdown template that reproduces its styling — fonts, sizes, colors, spacing, line height, indent, alignment, and heading numbering. The script extracts the effective formatting from the actual document elements (paragraphs/runs, including the CJK font from `w:rFonts w:eastAsia`) and writes a `.qd` template meant to be `.include`d by business documents.

```bash
python3 references/extract_docx_style.py <input.docx|input.py> [-o template.qd]
    [--heading-levels 1-3] [--dry-run] [--no-verify]
```

- **Input** is a `.docx` to parse directly, or a `.py` generator script that is executed in a throwaway temp dir after an AST safety scan (rejects `rm`/shell commands, network imports, subprocess, and writes to absolute/`..` paths). The generated `.docx` is then parsed. If a `.py` script looks risky the script refuses to run it.
- **Numbering convention**: Quarkdown's `.numbering` only supports decimal (`1`), letters (`a`/`A`) and Roman (`i`/`I`) counters in a single hierarchy string. Unsupported patterns — Chinese numerals (`（一）`, `一、`, `第一章`), mixed/independent per-level counters, or Word auto-numbering (`numPr`, which cannot be read as text) — fall back to **Plan B**: numbers are written into the heading text itself and qd auto-numbering is disabled via `numbered:{no}`. When every heading level uses a supported, hierarchical pattern (e.g. `1.` / `1.1` / `1.1.1`), the script emits `.numbering - headings: 1.1.1` instead.
- **Coverage boundary**: only the "style spec family" is extracted. Tables, headers/footers, page-break control, fields, SmartArt, and text-box coordinates have no 1:1 mapping in Quarkdown and are not reproduced.
- **Font size mapping**: qd's `fontsize` takes only relative enums (`tiny`–`huge`), so absolute sizes are set on the global `.font size:{N}pt` (body base) and heading sizes become the nearest enum (e.g. H1 22pt on a 12pt base → `larger`).
- **Verify**: by default the script runs `quarkdown c template.qd --strict --out /tmp/quarkdown-verify` after generation (compile the same way as in the Workflow section). Use `--no-verify` to skip, and `--dry-run` to print only the extraction summary and plan A/B decision. A failed verification usually means a font referenced by the docx is not installed locally; install the font or pass `--no-verify`.
- Exit codes: `0` success, `1` input/argument error (missing file, parse failure, risky `.py`), `2` output/verification error.
