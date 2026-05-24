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
5. After every batch of changes, regenerate the diagram:

```bash
python cld_tool.py --project usecases/<topic-name> --serve
```

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
Causal Intelligence Research Framework/
├── CLAUDE.md          ← you are here
├── agents.md          ← full rules and file templates — read this first
├── cld_tool.py        ← the diagram generator (run with --serve for live editing)
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

```bash
# Generate and start live edit server (recommended)
python cld_tool.py --project usecases/<topic-name> --serve

# Generate only, no server
python cld_tool.py --project usecases/<topic-name> --no-log

# Validate quality before generating
python cld_tool.py --project usecases/<topic-name> --validate
```

---

## License

Apache 2.0
