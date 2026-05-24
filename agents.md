# AGENTS.md — Causal Intelligence Research Framework

A domain-neutral template for building causal loop research in plain Markdown.
Copy this file into any new project folder and start writing.

---

# Agent Operating Instructions

**If you are an AI agent reading this file, follow these rules every session:**

> **CRITICAL: All new research projects go in `usecases/<topic-name>/` — NEVER in `examples/`.  
> `examples/` is read-only reference material. Do not touch it.**

1. Read this file fully before doing any research work.

2. **Gather evidence first — before writing any loop or relationship file.**
   Search for high-quality, relevant, and recent sources on the research topic.
   For every major causal claim you intend to make, find at least one source that supports it.
   Document each source immediately in `evidence/` before moving on.
   Do not write a relationship file for a claim you cannot source.

3. Evaluate every source for:
   - **Relevance** — does it directly address the variable or mechanism in question?
   - **Recency** — prefer sources published within the last 3 years unless historical context requires older data
   - **Authority** — prefer primary sources (official reports, datasets, peer-reviewed papers) over secondary summaries
   - **Specificity** — a source with numbers beats a source with only qualitative claims

4. Record `release_date` for every evidence file. If the source has no publication date, flag it: `release_date: unknown — verify before citing`.

5. After creating or updating any file in `loops/`, `relationships/`, or `evidence/`, regenerate the diagram:

```bash
python cld_tool.py --project .
```

6. If `cld_tool.py` is not in the current folder, find it from the repo root:

```bash
python ../../cld_tool.py --project .
```

7. After generating, confirm the output files exist:
   - `causal_loop_system_map.html` — open this in the browser to review the diagram
   - `causal_graph.json` — machine-readable graph
   - `causal_loop_diagram.dot` — Graphviz source

8. Run validation before generating if you want a quality check first:

```bash
python cld_tool.py --project . --validate
```

9. Never end a research session without regenerating the diagram. The HTML is the deliverable.

---

# Getting Started

## Repository layout

```
Causal Intelligence Research Framework/
├── agents.md          ← this file — framework rules for humans and AI agents
├── cld_tool.py        ← the tool
├── assets/            ← screenshots and static assets
├── examples/          ← curated reference implementations
│   └── mideast-geopolitics/
└── usecases/          ← agentic research projects (one folder per topic)
    └── <your-topic>/  ← one folder per research topic
```

> **AGENT RULE — WHERE TO CREATE NEW RESEARCH:**
>
> **ALL new research projects MUST be created inside `usecases/`, never inside `examples/`.**
>
> - `usecases/your-topic-name/` — **use this for every new research session**
> - `examples/` — READ ONLY. Do not create or modify folders here. These are reference implementations only.
>
> If you are about to create a folder inside `examples/`, stop and create it inside `usecases/` instead.

## Minimum to generate a diagram

Create your project folder **inside `usecases/`** — for example `usecases/us-iran-war/`:

```
usecases/us-iran-war/          ← YOUR PROJECT LIVES HERE, not in examples/
├── agents.md                  ← copy from root agents.md and customize
├── loops/
│   └── L-01-my-first-loop.md
├── relationships/
└── evidence/                  ← required for confidence: High claims
```

Run from the repo root:

```bash
python cld_tool.py --project usecases/us-iran-war
```

Or from inside the project folder:

```bash
cd usecases/us-iran-war
python ../../cld_tool.py
```

Add `--no-log` to skip writing to `log.md`. Add `--validate` to check quality before generating.

Output: `causal_loop_system_map.html` (interactive diagram) + `causal_graph.json` + `causal_loop_diagram.html`

## Loop naming conventions

The visualizer accepts any alphanumeric loop ID prefix:

| Format | Example title | Detected ID |
|--------|--------------|-------------|
| `L-01` | `Loop L-01: Price War Spiral` | `L-01` |
| `B1` | `B1 Congestion Quality Loop` | `B1` |
| `R-02` | `R-02: Investment Flywheel` | `R-02` |
| `S3` | `S3 Supply Constraint` | `S3` |

---

# Objective

This framework turns domain research into a persistent causal intelligence wiki designed for:

- causal loop discovery
- system dynamics modeling
- policy analysis
- feedback loop analysis
- strategic systems thinking
- agentic recursive crawling

The repository is NOT a normal wiki. It is:
- variable-centric
- relationship-centric
- mechanism-centric
- loop-centric

The goal is to transform raw information into:
1. variables
2. causal relationships
3. mechanisms
4. feedback loops
5. policy insights

---

# Core Principles

## Principle 0 — Evidence Before Analysis

**Data gathering is the foundation. Do not theorize before you have sources.**

The order is:
1. Find the evidence
2. Extract the variables from what the evidence shows
3. Identify the relationships the evidence supports
4. Build loops from those relationships

Working in reverse — building loops first and hunting for evidence to confirm them — produces confirmation bias, not causal intelligence.

**Quality filters for evidence:**

| Filter | Rule |
|--------|------|
| Relevance | The source must directly address the variable or mechanism — not just mention it in passing |
| Recency | Prefer sources published within 3 years; flag older sources explicitly with their date |
| Authority | Primary sources first (official statistics, regulatory filings, peer-reviewed research, company reports); secondary sources only when primary is unavailable |
| Specificity | Quantitative evidence (numbers, trends, rates) outranks qualitative assertions |
| Independence | Do not cite sources that cite each other — trace back to the original data |

**Every evidence file must record when the source was released.** A source with an unknown or missing release date cannot be used to anchor a `confidence: High` claim.

---

## Principle 1 — Variables over Topics

Always prioritize extracting **variables** rather than broad topics.

**Too broad:**
- economy
- tourism
- healthcare

**Good variables:**
- inflation rate
- tourist arrivals per month
- hospital bed occupancy rate
- perceived travel affordability index
- workforce productivity

Variables are dynamic, measurable quantities that change over time.

---

## Principle 2 — Mechanisms over Correlations

Never store only `A -> B`. Always explain **why A changes B**.

**Weak:** "social media causes tourism"

**Strong:** "social media exposure increases destination awareness,
which raises travel intention, which increases tourist arrivals"

Mechanisms are mandatory.

---

## Principle 3 — Feedback Loops are Primary

The framework exists to discover:
- reinforcing loops (R) — self-amplifying dynamics
- balancing loops (B) — self-correcting dynamics
- delays — time lags between cause and effect
- nonlinearities — threshold effects, saturation
- tipping points — irreversible state changes

Relationships are not isolated. They are parts of loops.

---

## Principle 4 — Contradictions are Valuable

Conflicting evidence must NOT be deleted. Store:
- competing hypotheses
- conflicting mechanisms
- uncertainty ranges
- confidence levels

---

## Principle 5 — Dynamic Dominance

Different loops dominate at different time periods. Always track:
- dominant loops (currently active)
- weakening loops (losing influence)
- emerging loops (gaining strength)
- delayed effects (latent dynamics)

---

# Repository Structure

## `systems/`

Overall system boundary definitions — scope, players, key variables.

Example topics: supply chain resilience, urban traffic flow, energy transition, public health.

---

## `variables/`

One file per causal variable. These files populate the **Component Glossary** in the interactive panel — click any node on the diagram to jump to its definition.

`cld_tool.py` reads key-value fields **and** `## Heading` sections (headings take priority). Use the format below to get the richest panel display:

### Variable Template

```markdown
# Variable Name Here

- unit: e.g. IDR/month, %, persons, index 0–100
- related_loops: L-01, L-03

## Definition

One or two sentences — what this variable measures, in plain terms.
Two people reading this should interpret it the same way.

## Unit

e.g. IDR/month per active subscriber

## Delays

Typical lag between cause and effect: 3–6 months due to [reason].

## Related Loops

L-01, L-03, L-05
```

**Minimum required:** `unit` and a `## Definition` section.  
The panel will still show any node that lacks a file — it just displays "No variable definition file found."

---

## `relationships/`

One file per explicit causal claim — see **Relationship Template** below.

---

## `mechanisms/`

Deeper explanations of causal behavior that span multiple relationships. These files populate the **Causal Mechanisms** section in the interactive panel.

Examples: network effects, economies of scale, social contagion, behavioral reinforcement, resource depletion.

`cld_tool.py` reads the `## Heading` sections below. The `## Why` heading (or `## Explanation` / `## Description` / `## Overview`) is used as the explanation text in the panel.

### Mechanism Template

```markdown
# Mechanism: Short Mechanism Name

- confidence: High | Medium | Low

## Mechanism Name

Short Mechanism Name

## Relationship Governed

Source Variable → Target Variable (the specific link this mechanism explains)

## Why

One paragraph explaining the causal pathway in plain language.
What is the underlying process? Why does the source variable change the target?
Include empirical grounding if available.

## Boundary Conditions

When does this mechanism hold? When does it break down or reverse?

## Related Loops

L-01, L-02
```

**Minimum required:** a `## Why` section (or `## Explanation`) and a `## Relationship Governed` section.  
The title becomes the mechanism label shown in the panel.

---

## `loops/`

One file per feedback loop — see **Loop Standards** below.

---

## `policies/`

Strategic interventions and leverage points. Each policy file should include:
- intended effect on loops
- unintended consequences
- affected variables
- implementation delays
- loop interactions

---

## `hypotheses/`

Uncertain or emerging causal claims under investigation. Include:
- supporting evidence
- conflicting evidence
- confidence level
- variables involved

---

## `evidence/`

**Primary source of truth for all causal claims.** Every relationship and loop must trace back to at least one file here.

Evidence files are never modified after creation — they are immutable records of what was observed.

Each file captures one source or finding:

```
- evidence_type: Article | Report | Dataset | Interview | Statistic | Regulatory Filing | Earnings Call | Press Release | Academic Paper | Observation
- source: Publication name, author, URL, or institution
- release_date: YYYY-MM-DD when the source was published or released — REQUIRED
- retrieved_date: YYYY-MM-DD when this evidence was gathered by the agent
- finding: One-sentence summary of the key finding relevant to this project
- supports_relationships: Relationship filename(s) this evidence backs
- supports_loops: Loop ID(s) this evidence is relevant to
- confidence_boost: High | Medium | Low — how strongly this source supports the claim
- quote: Optional direct quote from the source
```

**`release_date` is mandatory.** If the source has no visible publication date, write:
`release_date: unknown — verify before citing`
and cap the confidence of any relationship it backs at `Medium`.

**Evidence drives confidence:**
- `confidence: High` — 2+ strong evidence files with known release dates, consistent findings
- `confidence: Medium` — 1 evidence file, or release date unknown on one source
- `confidence: Low` — no evidence file, or `release_date: unknown` on all backing sources

Never leave the `evidence` field blank in a relationship file. If no source exists yet, write `evidence: none — needs sourcing` to flag it explicitly for follow-up.

**Timeliness matters.** A source older than 5 years must be explicitly noted in the `finding` field. A source older than 10 years should only be used for historical context, never as the primary basis for a current causal claim.

---

## `simulations/`

Stock-flow models, Vensim exports, PySD scripts, simulation assumptions.

---

# Causal Extraction Workflow

## Step 0 — Gather Evidence First

Before writing any loop, relationship, or variable file, conduct a structured evidence search.

**For each research topic:**

1. Identify the key questions: What drives this system? What are the main feedback dynamics? What do the numbers show over time?
2. Search for primary sources: official statistics, industry reports, regulatory filings, academic papers, earnings calls, government data.
3. For each source found, immediately create a file in `evidence/` using the Evidence Template.
4. Record `release_date` and `retrieved_date` for every file — do not skip this even if the date requires inference.
5. Only after documenting a source may you use its findings to populate `loops/` or `relationships/`.

**Relevance test before documenting any source:**
- Does this source contain data or findings that directly affect a specific variable in this system?
- Is this source recent enough to reflect the current state of the system?
- Is this the original source, or is it citing another source I should find instead?

If a source fails the relevance test, do not create an evidence file for it.

**Minimum evidence coverage before generating a diagram:**
- At least 1 evidence file per explicit relationship
- At least 1 evidence file per loop (covering the dominant mechanism)
- Zero relationships with blank `evidence` fields

---

## Step 1 — Extract Variables

Identify: measurable quantities, changing states, pressures, constraints, capacities, perceptions.

Convert broad concepts into dynamic variables.

**Example:** "market competitiveness" becomes:
- competitor price level
- market share (%)
- customer switching rate
- price-to-quality ratio

---

## Step 2 — Extract Relationships

Identify: what affects what, polarity (+/−), causal direction, delays, strength.
Store each relationship independently in `relationships/`.

---

## Step 3 — Extract Mechanisms

For every relationship ask: **WHY does this happen?**

Mechanisms are mandatory. One clear sentence minimum.

---

## Step 3b — Anchor Every Claim to Evidence

For every relationship, identify the source that justifies it:

1. Find or create the supporting file in `evidence/`
2. Set `evidence:` in the relationship file to point at it
3. If no source exists, set `confidence: Low` and flag it: `evidence: none — needs sourcing`

A causal claim without evidence is a hypothesis. Treat it as one.

---

## Step 4 — Detect Loops

Search for closed chains: `A -> B -> C -> A`

Classify each loop:
- **Reinforcing (R)** — odd number of negative links, or all positive: self-amplifying
- **Balancing (B)** — even number of negative links: self-correcting

Detect delays, bottlenecks, constraints.

---

## Step 5 — Detect Policies

Identify: interventions, regulations, incentives, strategic decisions.
Map each policy to the loops it affects and the leverage point it targets.

---

## Step 6 — Generate the Diagram

After every research session — or after any change to `loops/`, `relationships/`, or `evidence/` — run:

```bash
python cld_tool.py --project .
```

Then open `causal_loop_system_map.html` to review the result:

- **Hover over edges** — verify the mechanism and evidence source are correct
- **Hover over nodes** — confirm they appear in the right loops
- **Click any node** — opens its full definition from `variables/` in the left panel
- **Click a loop button** — highlights the path and shows loop detail + relevant evidence
- **Component Glossary** (left panel) — confirms all variable files are parsed correctly; missing definitions show "No variable definition file found"
- **Causal Mechanisms** (left panel) — confirms all mechanism files are loaded

If errors appear, run `--validate` first to diagnose:

```bash
python cld_tool.py --project . --validate
```

Fix all `[ERR]` items before treating the diagram as final.

**The diagram is not optional.** It is the primary output of every research session.

---

# Relationship Standards

## Relationship Template

The visualizer (`cld_tool.py`) scans every line matching `- key: value`.
These fields **must** appear verbatim in each `relationships/*.md` file.
Write each field exactly once; the last occurrence of each key wins.

```
- source: Human-readable variable name
- target: Human-readable variable name
- polarity: Positive | Negative | Unknown
- mechanism: One-line causal explanation — WHY source changes target (no line breaks)
- delay: e.g. "3–6 months" or "immediate"
- confidence: Low | Medium | High
- evidence: Filename(s) from evidence/ folder that back this claim — REQUIRED; write "none — needs sourcing" if missing
- counterarguments: One-line alternative or conflicting mechanism
- related_loops: L-01, L-02
```

Prose elaboration goes in `##` sections below the machine-readable block.

### Minimum Viable Relationship File

```markdown
# Relationship: Variable A → Variable B

- source: Variable A
- target: Variable B
- polarity: Positive
- mechanism: When A increases, it raises B because [causal pathway]
- delay: 2–4 months
- confidence: Medium
- evidence: evidence/source-filename.md — [brief label, e.g. "GSMA 2023 pricing report"]
- counterarguments: Effect may be dampened by [limiting factor]
- related_loops: L-01

## Extended Description

Prose elaboration here...
```

---

# Loop Standards

## Loop Template

The visualizer scans every line matching `- key: value`.
These fields **must** appear in each `loops/*.md` file.

```
- loop_type: Reinforcing | Balancing
- variables: Var A -> Var B -> Var C -> Var A
- narrative: One-line summary of the dynamic (no line breaks)
- dominant_period: e.g. 2019–present, or "early-stage growth phase"
- delay_points: e.g. "3–6 months for X; 12–24 months for Y"
- leverage_points: Intervention A, Intervention B
- collapse_conditions: Single-line description of what breaks or reverses the loop
```

**CRITICAL rules for `variables`:**
- Must be on **ONE line only** — the parser reads line-by-line
- Use ` -> ` (space-hyphen-greater-space) as separator, not `→`
- The loop closes automatically: the last variable connects back to the first
- Use human-readable variable names, **not** ID codes

### Minimum Viable Loop File

```markdown
# Loop L-01: Loop Name

- loop_type: Reinforcing
- variables: Variable A -> Variable B -> Variable C -> Variable A
- narrative: Rising A increases B, which drives C, which further amplifies A
- dominant_period: 2020–present
- delay_points: 3–6 months for A to affect B; 12–18 months for C to feed back
- leverage_points: Policy lever X, structural change Y
- collapse_conditions: Loop breaks when A hits its physical/regulatory ceiling

## Loop Structure

```
Variable A
    ↓ (+)
Variable B
    ↓ (+)
Variable C
    ↓ (+)
→ Variable A  [REINFORCING]
```

## Narrative

Extended prose explanation here...

## Leverage Points

1. **Lever X** — explain why this is effective
2. **Lever Y** — explain mechanism
```

---

# Visualizer Compatibility

The script `cld_tool.py` reads four directories:

| Directory | Used for | Panel section |
|-----------|----------|---------------|
| `loops/*.md` | Loop buttons, path highlighting, loop detail view | Feedback Loops |
| `relationships/*.md` | Explicit edges (solid lines), edge tooltips | — |
| `variables/*.md` | Node definitions and delay/evidence context | Component Glossary |
| `mechanisms/*.md` | Causal pathway explanations | Causal Mechanisms |
| `evidence/*.md` | Source citations, dates, findings | Evidence Sources |

## Interactive Panel

The left panel in `causal_loop_system_map.html` shows five sections automatically built from your research files:

| Section | Source | Interaction |
|---------|--------|-------------|
| System Overview | Counts derived from all directories | — |
| Feedback Loops | `loops/*.md` | Click to highlight loop path on diagram |
| Component Glossary | `variables/*.md` | Click a row or click any node on the diagram to see full definition |
| Causal Mechanisms | `mechanisms/*.md` | Read-only explanation cards |
| Evidence Sources | `evidence/*.md` | Cards showing source, date, finding |

**The richer your `variables/` and `mechanisms/` files, the more useful the panel.** A variable file with a good `## Definition` and `## Delays` section lets any reader understand the node without leaving the diagram.

## How the Parser Works

```
line matches:  - key: value
```

- Key = everything before the first `:`
- Value = everything after the first `:`
- Markdown formatting in values is stripped automatically
- The **last** match for each key wins — write each field once
- Lines starting with `##`, `**`, code fences, or tables are **not** read as key-value fields — they are read as section content by the `## Heading` parser instead

## What Breaks the Parser

| Problem | Effect | Fix |
|---------|--------|-----|
| `## Source Variable` heading instead of `- source: value` | Field not found; relationship skipped | Use `- source:` format |
| Multi-line `- variables:` value | Only the last line is read | Put entire arrow chain on ONE line |
| `→` instead of ` -> ` in variables chain | Chain not split; loop has 0 variables; skipped | Use ` -> ` (ASCII) |
| VAR-ID codes in source/target (e.g. `VAR-001`) | IDs shown in diagram instead of readable names | Use human-readable names |
| Empty source or target | Entire relationship silently skipped | Always populate both fields |

---

# Causal Quality Rules

## Avoid Generic Concepts

Avoid: economy, society, technology, competition, performance.

Prefer: GDP growth rate, labor productivity index, AI adoption rate (% of firms), market price per unit.

## Avoid Weak Correlations

Do not assume causality without mechanism.

## Evidence is Mandatory, Not Optional

Every relationship file must have a non-empty `evidence` field pointing to a file in `evidence/` or an explicit flag (`none — needs sourcing`). An unflagged blank evidence field is a data quality error.

The `evidence/` folder is the foundation of the system. Diagrams without evidence are speculation diagrams.

## Source Release Date is Mandatory

Every evidence file must have a `release_date`. A diagram where any evidence file is missing `release_date` is an incomplete diagram. The release date is what lets future researchers and agents know whether the evidence is still current.

## Data Freshness Rule

| Source age | Usage rule |
|------------|-----------|
| 0–3 years | Primary basis for current causal claims |
| 3–5 years | Usable but note the date explicitly in `finding` |
| 5–10 years | Historical context only — flag with `[HISTORICAL]` in `finding` |
| 10+ years | Do not use unless the claim is explicitly about historical behavior |

## Prioritize Dynamic Variables

Prefer variables that: change over time, create feedback, produce delays, influence multiple systems.

---

# Confidence Scoring

Rate every relationship:

| Level | Meaning |
|-------|---------|
| High | 2+ strong evidence files in `evidence/`, consistent across sources, mechanism well-understood |
| Medium | 1 evidence file, plausible mechanism, some uncertainty or indirect sourcing |
| Low | No evidence file yet (`none — needs sourcing`), hypothesized, weak or conflicting accounts |

---

# Logging Rules

Every major operation should append to `log.md`:

```markdown
## [YYYY-MM-DD] operation | description

- pages updated: ...
- variables extracted: ...
- loops discovered: ...
- contradictions found: ...
```

---

# Index Rules

`index.md` must maintain a master index of all: systems, variables, relationships, loops, policies, hypotheses — with summaries, file links, and tags.

---

# Long-Term Goal

The repository should evolve into a continuously improving causal intelligence system capable of:
- generating causal loop diagrams automatically from research notes
- identifying high-leverage intervention points
- forecasting systemic behavior under different policies
- supporting evidence-based strategic decision-making

The repository is not static documentation. It is a living, evolving systems-thinking engine.
