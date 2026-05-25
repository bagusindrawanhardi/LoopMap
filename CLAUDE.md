# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Read `agents.md` fully before doing any research work in this repository. It contains all evidence-first workflow rules, file templates, and parser field specifications.

---

## What this framework does

LoopMap turns plain Markdown research files into interactive causal loop diagrams. Write variables, relationships, loops, and evidence in Markdown. One command generates a fully interactive HTML diagram where every loop is traceable and every claim is anchored to a dated source.

---

## Running the tool

Use whichever runner is available — try in this order:

```bash
# Windows binary (no Python needed)
loopmap.exe --project usecases/<topic-name> --serve

# macOS / Linux binary
./loopmap --project usecases/<topic-name> --serve

# Python fallback
python cld_tool.py --project usecases/<topic-name> --serve
```

| Flag | Effect |
|------|--------|
| *(none)* | Parse, generate, append to `log.md` |
| `--no-log` | Generate without writing to `log.md` |
| `--serve` | Generate + start live-edit server at `http://localhost:7654` |
| `--validate` | Quality check before generating — fix all `[ERR]` items |

If no `--project` is given, defaults to the **current working directory** (not the repo root).

---

## Building the binary (developers)

```bash
pip install pyinstaller
pyinstaller --onefile --name loopmap cld_tool.py
# Output: dist/loopmap.exe (Windows) or dist/loopmap (Mac/Linux)
```

**Releasing a new version** — push a `v*` tag to trigger `.github/workflows/release.yml`:

```bash
git tag v1.0.4
git push origin v1.0.4
```

The workflow builds three platform binaries (windows/macos/linux), renames them (`loopmap-windows.exe`, `loopmap-macos`, `loopmap-linux`), and creates a GitHub Release. To replace an existing tag:

```bash
git push origin --delete v1.0.3 && git tag -d v1.0.3
git tag v1.0.3 && git push origin v1.0.3
```

---

## `cld_tool.py` architecture

Single-file, stdlib-only (~3500 lines). No pip dependencies.

**Major sections:**

| Lines (approx) | Section |
|----------------|---------|
| 1–250 | Data parsing — `parse_loops()`, `parse_relationships()`, `parse_variables()`, `parse_evidence()`, `parse_mechanisms()`. Reads `- key: value` lines from Markdown; last match per key wins. |
| 250–650 | SVG primitives — `svg_node()`, `svg_edge()`, `svg_defs()`, bezier path calculation, arrowheads |
| 650–980 | Per-loop SVG panels and relationship table SVG (rendered into the right panel) |
| 980–1900 | HTML template — CSS styles embedded in an f-string (double `{{` for literal braces) |
| 1900–2050 | HTML structure — toolbar, panels, canvas |
| 2050–2800 | JavaScript — zoom/pan, loop highlighting, timeline dominance, node dragging, edit tools (Add/Relate/Delete), tooltip system |
| 2800–3100 | Report generation JS (PDF/print export) |
| 3100–3480 | Second HTML output (`causal_loop_diagram.html`) — simpler static CLD view |
| 3480–end | CLI entry point (`main()`), `--serve` HTTP server (`LiveServer` class), `--validate` logic |

**Key JS internals (inside the HTML f-string):**

- `.map-node` elements carry `data-tip` (JSON with `loops` array) for tooltip and timeline logic
- `.map-edge` elements carry `data-loops` (space-separated loop IDs, e.g. `"L-01 L-04"`) for timeline dimming
- `LOOP_DATA` — JS object keyed by loop ID, contains `year_start`/`year_end` parsed from `dominant_period`
- `applyLoopDominance(year)` — uses **inline styles** (not CSS classes) to dim buttons, nodes, and edges; CSS classes were tried first but lost to specificity conflicts
- `resetZoom()` — called via double `requestAnimationFrame` on `load` event so CSS layout settles before measuring canvas dimensions
- Panel widths use `clamp(180px, 26vw, 500px)` — responsive for high-DPI/Surface screens

**Frozen binary detection** (critical for `--serve` regen):

```python
if getattr(sys, "frozen", False):
    cmd = [sys.executable, "--project", str(root), "--no-log"]
else:
    cmd = [sys.executable, str(Path(__file__).resolve()), "--project", str(root), "--no-log"]
```

When PyInstaller freezes the binary, `sys.executable` IS the binary — passing `__file__` as an argument would be treated as an unrecognized positional argument.

---

## Parser rules (what breaks it)

| Problem | Effect | Fix |
|---------|--------|-----|
| `- variables:` value spans multiple lines | Only last line read; loop has 0 variables | Put entire `->` chain on ONE line |
| `→` instead of ` -> ` in variables chain | Chain not split | Use ASCII ` -> ` |
| VAR-ID codes in `source`/`target` | IDs shown in diagram instead of names | Use human-readable names |
| Empty `source` or `target` | Relationship silently skipped | Always populate both fields |
| `## Source Variable` heading instead of `- source: value` | Field not found | Use `- key: value` format |

The parser reads everything before the first `##` heading as key-value fields. `##` sections are read separately as rich content for the panel display.

---

## Research workflow (non-negotiable)

- **Evidence before analysis** — find and document a source in `evidence/` before writing any relationship or loop file
- **`examples/` is read-only** — reference material only; all new research goes in `usecases/`
- **Every session ends with a regenerated diagram** — the HTML is the deliverable
- **`release_date` is required** on every evidence file — undated sources cap confidence at Medium
- **Mechanisms are mandatory** — every relationship must explain *why* A changes B

---

## Repository layout

```
LoopMap/
├── CLAUDE.md          ← you are here
├── agents.md          ← full rules and file templates — read this first
├── cld_tool.py        ← the diagram generator (single file, stdlib only)
├── install.bat        ← downloads loopmap.exe on Windows (no Python needed)
├── install.sh         ← downloads loopmap binary on macOS/Linux
├── .github/workflows/release.yml  ← PyInstaller build + GitHub Release on v* tag
├── examples/          ← READ ONLY reference implementations
│   └── mideast-geopolitics/
└── usecases/          ← ALL new research goes here
    └── <your-topic>/
        ├── agents.md
        ├── variables/
        ├── relationships/
        ├── loops/
        ├── mechanisms/
        ├── evidence/
        └── policies/
```

---

## License

Apache 2.0
