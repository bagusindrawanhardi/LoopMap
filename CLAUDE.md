# LoopMap — Causal Intelligence Research Framework

Read `agents.md` fully before doing anything in this repository. It contains all rules, file templates, and workflow steps you must follow.

---

## What this framework does

LoopMap turns plain Markdown research files into interactive causal loop diagrams. You write variables, relationships, loops, and evidence in Markdown. One command generates a fully interactive HTML diagram where every loop is traceable and every claim is anchored to a dated source.

---

## Starting a new research session

The user will give you a topic. Do this:

1. Create `usecases/<topic-name>/` — **never create anything inside `examples/`**
2. Create the required subfolders: `variables/`, `relationships/`, `loops/`, `evidence/`
3. Copy the root `agents.md` into the new folder as your working reference
4. Follow the evidence-first workflow in `agents.md` exactly
5. After every batch of changes, regenerate the diagram. Use this decision tree:

**Step 5a — ensure a runner exists (do once per machine):**
- If `loopmap.exe` (Windows) or `./loopmap` (Mac/Linux) exists in the repo root → skip to 5b
- If Python is available (`python --version` works) → skip to 5b
- Otherwise, install the binary automatically:
  ```bash
  # Windows — double-click install.bat or run in terminal:
  install.bat

  # macOS / Linux
  bash install.sh
  ```

**Step 5b — regenerate:**
```bash
# Windows binary
loopmap.exe --project usecases/<topic-name> --serve

# macOS / Linux binary
./loopmap --project usecases/<topic-name> --serve

# Python fallback
python cld_tool.py --project usecases/<topic-name> --serve
```

Try them in that order — use the first one that works.

6. Open `http://localhost:7654` to review the diagram before reporting back

---

## Non-negotiable rules

- **Evidence before analysis** — find and document a source in `evidence/` before writing any relationship or loop file
- **`examples/` is read-only** — it is reference material, never a workspace
- **Every session ends with a regenerated diagram** — the HTML is the deliverable
- **`release_date` is required** on every evidence file — undated sources cap confidence at Medium
- **Mechanisms are mandatory** — every relationship must explain *why* A changes B, not just that it does

---

## Repository layout

```
LoopMap/
├── CLAUDE.md          ← you are here
├── agents.md          ← full rules and file templates — read this first
├── cld_tool.py        ← the diagram generator (run with --serve for live editing)
├── install.bat        ← downloads loopmap.exe on Windows (double-click, no Python needed)
├── install.ps1        ← PowerShell alternative (requires execution policy change)
├── install.sh         ← downloads loopmap binary on macOS/Linux (no Python needed)
├── examples/          ← READ ONLY reference implementations
│   └── mideast-geopolitics/
└── usecases/          ← ALL new research goes here
    └── <your-topic>/
        ├── agents.md
        ├── variables/
        ├── relationships/
        ├── loops/
        └── evidence/
```

---

## Diagram generation commands

Use whichever runner is available — try in this order:

| Runner | Command |
|--------|---------|
| Windows binary | `loopmap.exe --project usecases/<topic-name> --serve` |
| macOS/Linux binary | `./loopmap --project usecases/<topic-name> --serve` |
| Python | `python cld_tool.py --project usecases/<topic-name> --serve` |

Binaries can be downloaded from the [Releases page](https://github.com/bagusindrawanhardi/LoopMap/releases) and placed in the repo root.

```bash
# Generate and start live edit server (recommended)
loopmap.exe --project usecases/<topic-name> --serve

# Generate only, no server
loopmap.exe --project usecases/<topic-name> --no-log

# Validate quality before generating
loopmap.exe --project usecases/<topic-name> --validate
```

---

## License

Apache 2.0
