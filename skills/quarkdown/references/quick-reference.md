# Quarkdown Quick Reference

Copy-paste syntax for the most common Quarkdown tasks. Each section ends with a **Learn more** pointer to the offline wiki page under `$QUARKDOWN_INSTALL/docs/wiki/` (resolve with `QUARKDOWN_INSTALL="$(quarkdown doctor get install-dir)"`).

## Minimal document skeleton

```markdown
.docname {My Document}
.doctype {paged}
.doclang {English}
.theme {paperwhite} layout:{latex}

# Title

Content goes here.
```

- `.doctype` values: `plain`, `paged`, `slides`, `docs`.
- Common theme pairs: `paperwhite + latex`, `darko + minimal`, `galactic + hyperlegible`, `beaver + beamer`.
- **Learn more:** [document-metadata.qd](document-metadata.qd), [document-types.qd](document-types.qd), [themes.qd](themes.qd).

## Page setup: margins, counter, page breaks

```markdown
.pageformat {letter} margin:{2cm}

.pagemargin {bottomcenter}
    .currentpage / .totalpages

.pagebreak          # force a new page (or slide)
```

- `.pagemargin` positions: `topcenter`, `topleft`, `topright`, `topoutside`, `bottomcenter`, `bottomleft`, `bottomright`, ... `.footer` is shorthand for `bottomcenter`.
- `.autopagebreak maxdepth:{3}` controls which heading levels start a new page automatically.
- **Learn more:** [page-format.qd](page-format.qd), [page-margin-content.qd](page-margin-content.qd), [page-break.qd](page-break.qd).

## Function call syntax

```markdown
.pow {5} to:{2}              # positional + named args
.sum {10} {5}::multiply {2}  # chaining: a::b  ==  .b {a}
.align {center}              # block call with indented body
    This paragraph is centered.

.function {example}          # custom reusable function
    content:
    .box {Example} type:{tip}
        .content
```

- `name:{arg}` for named arguments; `::` chains (left result becomes first arg of right call).
- Block bodies are indented (≥2 spaces) and map to the function's last parameter.
- **Learn more:** [syntax-of-a-function-call.qd](syntax-of-a-function-call.qd), [declaring-functions.qd](declaring-functions.qd).

## Variables & control flow

```markdown
.var {name} {Quarkdown}
Hello, **.name**!              # access
.name {Jane}                   # reassign

.if {.iseven {4}}
    Four is even!

.foreach {1..3}
    n:
    Number: **.n**
```

- `.let` creates scoped variables inside a lambda block.
- **Learn more:** [variables.qd](variables.qd), [conditional-statements.qd](conditional-statements.qd), [loops.qd](loops.qd), [let.qd](let.qd).

## Math

```markdown
# IMPORTANT — the $ delimiters MUST be surrounded by whitespace or the formula won't render:
#   $ E = mc^2 $     (correct, renders)     vs     $E = mc^2$     (wrong, stays plain text)
Inline:  $ E = mc^2 $
Block:   $ f(x, y) = \frac{x}{y} $      # isolated on its own line → block

Multiline:
$$$
f(x) =
\begin{cases}
    0 & \text{if } x = 0 \\
    1 & \text{otherwise}
\end{cases}
$$$
```

> **IMPORTANT — spaces around `$` are mandatory.** Both `$` delimiters must be preceded **and** followed by whitespace (or start/end of line), otherwise Quarkdown does not recognize the formula and renders it as plain text:
>
> - Correct: `$ E = mc^2 $` → renders as math
> - Wrong: `$E = mc^2$` → **not** rendered, stays plain text
>
> A one-line block formula must also be isolated on its own line with blank lines around it, or Markdown lazy lines turn it into inline math.

- Cross-reference an equation: `$ E = mc^2 $ {#energy}` then `.ref {energy}`.
- **Learn more:** [tex-formulae.qd](tex-formulae.qd).

## Images & figures

```markdown
!(50%)[Alt text](assets/logo.png)
!(6cm 2cm)[Alt](assets/photo.jpg "Caption") {#logo}   # size, caption, id
```

- Size accepts `px`, `pt`, `cm`, `mm`, `in`, `%`; `_` keeps a dimension automatic (`!(_ 2cm)[...]`).
- An isolated image becomes a centered figure; with a title it gets a caption.
- **Learn more:** [image-size.qd](image-size.qd), [figure.qd](figure.qd).

## Tables

```markdown
| A | B |
|---|---|
| 1 | 2 |
"Caption text" {#tbl-id}
```

- Caption line sits directly after the table (optional). `{#tbl-id}` enables cross-references.
- Load from CSV: `.csv {assets/data.csv} caption:{...}`; from JSON: `.json {file.json}::get {key}`.
- **Learn more:** [table-caption.qd](table-caption.qd), [table-from-csv.qd](table-from-csv.qd), [data-from-json.qd](data-from-json.qd).

## Cross-references & footnotes

```markdown
## Getting started {#start}
See .ref {start}.

Figure: ![Logo](logo.svg "Icon") {#logo} → see .ref {logo}

Footnote: some text[^1]
[^1]: Footnote definition.

Compact footnote: some text[^: Inline definition.]
```

- IDs attach via `{#id}` to headings, figures, tables (after the caption line), equations, and code blocks.
- **Learn more:** [cross-references.qd](cross-references.qd), [footnotes.qd](footnotes.qd).

## Numbering & table of contents

```markdown
.numbering
    - headings: 1.1.1
    - figures: 1.1
    - tables: 1.1
    - equations: (1)
    - code: 1

.tableofcontents
```

- Formats: `1` decimal, `a`/`A` letters, `i`/`I` Roman; any other char is literal, `\` escapes.
- `.nonumbering` disables numbering; `.numbered {key}` numbers custom elements.
- **Learn more:** [numbering.qd](numbering.qd), [table-of-contents.qd](table-of-contents.qd).

## Layout: stacks, containers, boxes

```markdown
.row gap:{1cm}
    A

    B

.column cross:{start}
    Left

.grid columns:{2} alignment:{spacearound}
    A

    B

.container borderstyle:{dashed} padding:{1cm}
    Content

.box {Title} type:{tip}
    Box content.
```

- Stack args: `alignment` (`start|center|end|spacebetween|spacearound|spaceevenly`), `cross`, `gap`.
- Box types: `callout` (default), `tip`, `note`, `warning`, `error`.
- Each item must be a separate Markdown block (blank line between items), else they merge into one paragraph.
- **Learn more:** [stacks.qd](stacks.qd), [container.qd](container.qd), [box.qd](box.qd).

## Alerts / typed quotes

```markdown
> Note: This is a note.
> Warning: Be careful.
> [!TIP]
> GitHub-style alert.
```

- **Learn more:** [quote-types.qd](quote-types.qd), [box.qd](box.qd).

## Code blocks

````markdown
```python "Function" {#main}
def main():
    print("Hello")
```
````

- Caption in quotes after the language; `{#id}` enables cross-references/numbering.
- Embed from file: `.code {python}` with `.read {file.py}` as the body.
- **Learn more:** [code.qd](code.qd), [code-caption.qd](code-caption.qd).

## Diagrams: Mermaid & XY charts

```markdown
.mermaid caption:{Architecture.}
    graph TD
        A[Start] --> B[End]

.xychart x:{Months} y:{Revenue} yrange:{100..}
    - 250
    - 500
    - 350
```

- **Learn more:** [mermaid-diagrams.qd](mermaid-diagrams.qd), [xy-chart.qd](xy-chart.qd).

## Includes & subdocuments

```markdown
.include {chapter1.qd}
.includeall
    - chapter1.qd
    - chapter2.qd
```

- Subdocuments (wikis/knowledge bases): link `.qd` files directly `[Intro](intro.qd)`; each becomes its own page sharing setup. Visualize links with `.subdocumentgraph`.
- **Learn more:** [including-other-quarkdown-files.qd](including-other-quarkdown-files.qd), [subdocuments.qd](subdocuments.qd).

## Slides

```markdown
.doctype {slides}
.theme {beaver} layout:{beamer}
.slides transition:{fade} center:{yes}

# Slide title
Content.

.pagebreak            # next slide

.fragment behavior:{show}
    This appears on click.
```

- `.slides` args: `center`, `controls`, `speakernotes`, `transition` (`none|fade|slide|zoom`), `speed`.
- `.fragment behavior`: `show` (default), `hide`, `semihide`, `showhide`.
- **Learn more:** [slides-configuration.qd](slides-configuration.qd), [slides-fragment.qd](slides-fragment.qd).

## Compiling

```bash
# HTML (default) — always use --strict to surface errors
quarkdown c main.qd --strict --out /tmp/quarkdown-verify

# PDF
quarkdown c main.qd --pdf --strict --out /tmp/quarkdown-verify

# Plain text / Markdown renderers
quarkdown c main.qd -r text
quarkdown c main.qd -r gfm

# Live preview (long-running server — suggest to the user, don't run yourself)
quarkdown c main.qd -p -w
```

- Grant missing permissions: `quarkdown c main.qd --allow network --allow global-read`.
- **Learn more:** [cli-compiler.qd](cli-compiler.qd), [cli-options.qd](cli-options.qd), [pdf-export.qd](pdf-export.qd).

## Where to find more

- Wiki index: `$QUARKDOWN_INSTALL/docs/wiki/_nav.qd`
- New to Quarkdown: `$QUARKDOWN_INSTALL/docs/wiki/quickstart.qd`
- Stdlib API reference (function signatures, parameters, return types): `$QUARKDOWN_INSTALL/docs/quarkdown-stdlib/`
