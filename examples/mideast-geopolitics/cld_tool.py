"""Create a causal loop diagram from the repository's markdown pages.

The script reads:
- relationships/*.md for explicit causal relationships
- loops/*.md for named loop paths and loop classifications

It writes:
- causal_graph.json
- causal_loop_diagram.dot
- causal_loop_diagram.html
- causal_loop_system_map.html

The HTML output is self-contained and uses only standard browser SVG, so the
script has no third-party Python dependencies.
"""

from __future__ import annotations

import argparse
import html
import http.server
import json
import math
import re
import socketserver
import subprocess
import sys
import threading
import urllib.parse
import webbrowser
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Iterable


# Canvas dimensions for the system map SVG.
# Both system_map_positions and write_system_map_html derive from these.
CANVAS_W = 2600
CANVAS_H = 1800


@dataclass
class Edge:
    source: str
    target: str
    polarity: str = "unknown"
    mechanism: str = ""
    delay: str = ""
    confidence: str = ""
    evidence: str = ""
    counterarguments: str = ""
    related_loops: list[str] = field(default_factory=list)
    inferred_from_loop: bool = False

    @property
    def key(self) -> tuple[str, str]:
        return (normalize_name(self.source), normalize_name(self.target))


@dataclass
class Loop:
    name: str
    loop_type: str
    variables: list[str]
    narrative: str = ""
    dominant_period: str = ""
    delay_points: str = ""
    leverage_points: str = ""
    collapse_conditions: str = ""


def normalize_name(value: str) -> str:
    cleaned = strip_markdown(value).strip().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", cleaned)).strip()


def display_name(value: str) -> str:
    return re.sub(r"\s+", " ", strip_markdown(value).strip())


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", normalize_name(value)).strip("-")


def strip_markdown(value: str) -> str:
    """Convert simple markdown links to visible text and remove emphasis marks."""
    value = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", value)
    value = value.replace("`", "")
    return value.strip()


def read_fields(path: Path) -> dict[str, str]:
    """Read top-level '- key: value' fields from a markdown page."""
    fields: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^\s*-\s*([^:]+):\s*(.*)\s*$", line)
        if match:
            key = normalize_name(match.group(1)).replace(" ", "_")
            fields[key] = match.group(2).strip()
    return fields


def read_title(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem.replace("-", " ").title()


def split_loop_variables(value: str) -> list[str]:
    return [display_name(part) for part in re.split(r"\s*->\s*", value) if part.strip()]


def split_related_loops(value: str) -> list[str]:
    if not value:
        return []
    cleaned = strip_markdown(value)
    return [part.strip() for part in re.split(r",|;", cleaned) if part.strip()]


def add_related_loop(edge: Edge, loop_name: str) -> None:
    if normalize_name(loop_name) not in {normalize_name(name) for name in edge.related_loops}:
        edge.related_loops.append(loop_name)


def load_relationships(relationships_dir: Path) -> list[Edge]:
    edges: list[Edge] = []
    if not relationships_dir.exists():
        return edges

    for path in sorted(relationships_dir.glob("*.md")):
        fields = read_fields(path)
        source = display_name(fields.get("source", ""))
        target = display_name(fields.get("target", ""))
        if not source or not target:
            missing = "source" if not source else "target"
            print(f"  WARN  {path.name}: missing '{missing}' field - relationship skipped", file=sys.stderr)
            continue

        edges.append(
            Edge(
                source=source,
                target=target,
                polarity=display_name(fields.get("polarity", "unknown")),
                mechanism=strip_markdown(fields.get("mechanism", "")),
                delay=strip_markdown(fields.get("delay", "")),
                confidence=strip_markdown(fields.get("confidence", "")),
                evidence=strip_markdown(fields.get("evidence", "")),
                counterarguments=strip_markdown(fields.get("counterarguments", "")),
                related_loops=split_related_loops(fields.get("related_loops", "")),
            )
        )

    return edges


def load_loops(loops_dir: Path) -> list[Loop]:
    loops: list[Loop] = []
    if not loops_dir.exists():
        return loops

    for path in sorted(loops_dir.glob("*.md")):
        fields = read_fields(path)
        variables_raw = fields.get("variables", "")
        if "→" in variables_raw:
            print(f"  WARN  {path.name}: 'variables' uses a Unicode arrow - replace with ASCII ' -> '", file=sys.stderr)
        variables = split_loop_variables(variables_raw)
        if len(variables) < 2:
            print(f"  WARN  {path.name}: fewer than 2 variables parsed - loop skipped. Check 'variables' field.", file=sys.stderr)
            continue

        loops.append(
            Loop(
                name=read_title(path),
                loop_type=display_name(fields.get("loop_type", fields.get("reinforcing_or_balancing", "unknown"))),
                variables=variables,
                narrative=strip_markdown(fields.get("narrative", "")),
                dominant_period=strip_markdown(fields.get("dominant_period", "")),
                delay_points=strip_markdown(fields.get("delay_points", "")),
                leverage_points=strip_markdown(fields.get("leverage_points", "")),
                collapse_conditions=strip_markdown(fields.get("collapse_conditions", "")),
            )
        )

    return loops


def _section_content(lines: list[str], heading: str) -> str:
    """Return the first non-empty content line after a ## heading."""
    target = heading.lower().strip()
    in_section = False
    for line in lines:
        if line.startswith("## ") and line[3:].strip().lower() == target:
            in_section = True
            continue
        if in_section:
            if line.startswith("## "):
                break
            text = strip_markdown(line.strip())
            if text:
                return text
    return ""


def _section_bullets(lines: list[str], heading: str, limit: int = 3) -> str:
    """Return bullet items from a ## section joined as a string."""
    target = heading.lower().strip()
    in_section = False
    items: list[str] = []
    for line in lines:
        if line.startswith("## ") and line[3:].strip().lower() == target:
            in_section = True
            continue
        if in_section:
            if line.startswith("## "):
                break
            text = strip_markdown(line.strip().lstrip("-•*").strip())
            if text:
                items.append(text)
                if len(items) >= limit:
                    break
    return "; ".join(items)


def load_evidence(evidence_dir: Path) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    if not evidence_dir.exists():
        return records
    for path in sorted(evidence_dir.glob("*.md")):
        raw_lines = path.read_text(encoding="utf-8").splitlines()
        fields = read_fields(path)
        title = read_title(path)

        # Primary: structured key-value fields
        evidence_type = strip_markdown(fields.get("evidence_type", ""))
        source        = strip_markdown(fields.get("source", ""))
        release_date  = strip_markdown(fields.get("release_date", fields.get("date", "")))
        finding       = strip_markdown(fields.get("finding", ""))
        supports_loops = strip_markdown(fields.get("supports_loops", ""))

        # Fallback: parse markdown sections for files that use ## headings
        if not evidence_type:
            evidence_type = _section_content(raw_lines, "type")
        if not release_date:
            release_date = _section_content(raw_lines, "date range") or \
                           _section_content(raw_lines, "date") or \
                           _section_content(raw_lines, "period")
        if not source:
            source = _section_bullets(raw_lines, "sources", limit=2) or \
                     _section_content(raw_lines, "source")
        if not finding:
            # Use first substantive paragraph after front-matter as the finding
            for line in raw_lines:
                stripped = line.strip()
                if stripped and not stripped.startswith("#") and \
                   not stripped.startswith("|") and not stripped.startswith("-") and \
                   not stripped.startswith("`") and len(stripped) > 30:
                    finding = strip_markdown(stripped)[:180]
                    break

        records.append({
            "id": path.stem,
            "title": title,
            "evidence_type": evidence_type,
            "source": source,
            "release_date": release_date,
            "retrieved_date": strip_markdown(fields.get("retrieved_date", "")),
            "finding": finding,
            "supports_loops": supports_loops,
            "supports_relationships": strip_markdown(fields.get("supports_relationships", "")),
            "confidence_boost": strip_markdown(fields.get("confidence_boost", "")),
        })
    return records


def load_variables(variables_dir: Path) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    if not variables_dir.exists():
        return records
    for path in sorted(variables_dir.glob("*.md")):
        raw_lines = path.read_text(encoding="utf-8").splitlines()
        fields = read_fields(path)
        title = read_title(path)
        # Strip "Variable:" prefix from title
        label = re.sub(r"^variable\s*:\s*", "", title, flags=re.IGNORECASE).strip()
        records.append({
            "id": path.stem,
            "label": label,
            "variable_type": strip_markdown(fields.get("variable_type", "")) or
                             _section_content(raw_lines, "variable type") or
                             _section_content(raw_lines, "stock or flow"),
            "unit": strip_markdown(fields.get("unit", "")) or
                    _section_content(raw_lines, "unit"),
            "definition": strip_markdown(fields.get("description", fields.get("definition", ""))) or
                          _section_content(raw_lines, "definition"),
            "delays": strip_markdown(fields.get("delays", "")) or
                      _section_content(raw_lines, "delays"),
            "related_loops": strip_markdown(fields.get("related_loops", "")) or
                             _section_content(raw_lines, "related loops"),
            "inflows": _section_bullets(raw_lines, "inflows", limit=4),
            "outflows": _section_bullets(raw_lines, "outflows", limit=4),
        })
    return records


def load_mechanisms(mechanisms_dir: Path) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    if not mechanisms_dir.exists():
        return records
    for path in sorted(mechanisms_dir.glob("*.md")):
        raw_lines = path.read_text(encoding="utf-8").splitlines()
        fields = read_fields(path)
        title = read_title(path)
        label = re.sub(r"^mechanism\s*:\s*", "", title, flags=re.IGNORECASE).strip()
        mech_name = _section_content(raw_lines, "mechanism name") or label
        # Get first paragraph of explanation (first non-empty line after ## Why or first body paragraph)
        explanation = ""
        for heading in ["why", "explanation", "description", "overview"]:
            explanation = _section_content(raw_lines, heading)
            if explanation:
                break
        if not explanation:
            for line in raw_lines:
                s = line.strip()
                if s and not s.startswith("#") and not s.startswith("|") and \
                   not s.startswith("-") and not s.startswith("`") and len(s) > 40:
                    explanation = strip_markdown(s)[:200]
                    break
        records.append({
            "id": path.stem,
            "label": label,
            "mechanism_name": mech_name,
            "relationship": _section_content(raw_lines, "relationship governed"),
            "explanation": explanation,
            "confidence": strip_markdown(fields.get("confidence", "")) or
                          _section_content(raw_lines, "confidence"),
        })
    return records


def loop_edge_pairs(loop: Loop) -> Iterable[tuple[str, str]]:
    variables = loop.variables
    for index, source in enumerate(variables):
        target = variables[(index + 1) % len(variables)]
        if normalize_name(source) != normalize_name(target):
            yield source, target


def merge_edges(relationship_edges: list[Edge], loops: list[Loop]) -> list[Edge]:
    merged: dict[tuple[str, str], Edge] = {edge.key: edge for edge in relationship_edges}

    for loop in loops:
        for source, target in loop_edge_pairs(loop):
            key = (normalize_name(source), normalize_name(target))
            if key not in merged:
                merged[key] = Edge(
                    source=source,
                    target=target,
                    polarity="unknown",
                    mechanism=f"Inferred from loop path: {loop.name}",
                    related_loops=[loop.name],
                    inferred_from_loop=True,
                )
            else:
                add_related_loop(merged[key], loop.name)

    return list(merged.values())


def loop_path_text(variables: list[str]) -> str:
    if not variables:
        return ""
    if normalize_name(variables[0]) == normalize_name(variables[-1]):
        return " -> ".join(variables)
    return " -> ".join([*variables, variables[0]])


def build_payload(edges: list[Edge], loops: list[Loop]) -> dict[str, object]:
    node_names = sorted({edge.source for edge in edges} | {edge.target for edge in edges}, key=normalize_name)
    return {
        "nodes": [{"id": name, "label": name} for name in node_names],
        "edges": [
            {
                "id": f"{slugify(edge.source)}-to-{slugify(edge.target)}",
                "source": edge.source,
                "target": edge.target,
                "polarity": edge.polarity,
                "mechanism": edge.mechanism,
                "delay": edge.delay,
                "confidence": edge.confidence,
                "evidence": edge.evidence,
                "counterarguments": edge.counterarguments,
                "related_loops": edge.related_loops,
                "inferred_from_loop": edge.inferred_from_loop,
            }
            for edge in edges
        ],
        "loops": [
            {
                "name": loop.name,
                "loop_type": loop.loop_type,
                "variables": loop.variables,
                "path": loop_path_text(loop.variables),
                "narrative": loop.narrative,
                "dominant_period": loop.dominant_period,
                "delay_points": loop.delay_points,
                "leverage_points": loop.leverage_points,
                "collapse_conditions": loop.collapse_conditions,
            }
            for loop in loops
        ],
    }


def polarity_symbol(polarity: str) -> str:
    value = normalize_name(polarity)
    if value in {"positive", "+", "plus"}:
        return "+"
    if value in {"negative", "-", "minus"}:
        return "-"
    return "?"


def polarity_color(polarity: str) -> str:
    value = normalize_name(polarity)
    if value in {"positive", "+", "plus"}:
        return "#18864b"
    if value in {"negative", "-", "minus"}:
        return "#c33a32"
    return "#6f7782"


def write_json(payload: dict[str, object], path: Path) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def write_dot(edges: list[Edge], loops: list[Loop], path: Path) -> None:
    explicit_nodes = {
        normalize_name(node)
        for edge in edges
        if not edge.inferred_from_loop
        for node in (edge.source, edge.target)
    }
    lines = [
        "digraph causal_loop_diagram {",
        '  graph [layout=neato, overlap=false, splines=curved, bgcolor="white", pad="0.4", outputorder=edgesfirst];',
        '  node [fontname="Times New Roman", fontsize=12, margin="0.06,0.04"];',
        '  edge [fontname="Times New Roman", fontsize=11, arrowsize="0.7", color="blue", fontcolor="blue"];',
        "",
    ]

    nodes = sorted({edge.source for edge in edges} | {edge.target for edge in edges}, key=normalize_name)
    for node in nodes:
        if normalize_name(node) in explicit_nodes:
            lines.append(f'  "{node}" [shape=box, style=filled, fillcolor=red, color=black, fontcolor=white];')
        else:
            lines.append(f'  "{node}" [shape=plaintext, fontcolor=black];')

    lines.append("")
    for edge in edges:
        style = "dashed" if edge.inferred_from_loop else "solid"
        label = polarity_symbol(edge.polarity)
        tooltip = edge.mechanism.replace('"', "'")
        lines.append(
            f'  "{edge.source}" -> "{edge.target}" '
            f'[label="{label}", color="blue", fontcolor="blue", style="{style}", tooltip="{tooltip}"];'
        )

    lines.append("}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def svg_text(value: str, max_chars: int = 24) -> list[str]:
    words = value.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) > max_chars and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines[:3]


def edge_lookup(edges: list[Edge]) -> dict[tuple[str, str], Edge]:
    return {(normalize_name(edge.source), normalize_name(edge.target)): edge for edge in edges}


def loop_variables_for_display(variables: list[str]) -> list[str]:
    if len(variables) > 1 and normalize_name(variables[0]) == normalize_name(variables[-1]):
        return variables[:-1]
    return variables


def svg_node(x: float, y: float, label: str, css_class: str = "node") -> str:
    text_lines = svg_text(label, 22)
    start_y = y - ((len(text_lines) - 1) * 8)
    text = "".join(
        f'<text x="{x:.1f}" y="{start_y + index * 16:.1f}" class="node-label">{html.escape(line)}</text>'
        for index, line in enumerate(text_lines)
    )
    return (
        f'<g class="{css_class}">'
        f"<title>{html.escape(label)}</title>"
        f'<rect x="{x - 86:.1f}" y="{y - 30:.1f}" width="172" height="60" rx="7" />'
        f"{text}</g>"
    )


def svg_edge(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    polarity: str,
    tooltip: str,
    inferred: bool = False,
    arc: bool = False,
) -> str:
    color = polarity_color(polarity)
    symbol = polarity_symbol(polarity)
    marker = symbol.replace("+", "plus").replace("-", "minus").replace("?", "unknown")
    dash = ' stroke-dasharray="6 6"' if inferred else ""
    label_x = (x1 + x2) / 2
    label_y = (y1 + y2) / 2
    if arc:
        control_y = min(y1, y2) - 76
        path = f'M{x1:.1f},{y1:.1f} C{x1:.1f},{control_y:.1f} {x2:.1f},{control_y:.1f} {x2:.1f},{y2:.1f}'
        label_y = control_y - 8
        shape = (
            f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2.2"{dash} '
            f'marker-end="url(#arrow-{marker})" />'
        )
    else:
        shape = (
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="{color}" stroke-width="2.2"{dash} marker-end="url(#arrow-{marker})" />'
        )
    return (
        f'<g class="edge {"inferred" if inferred else "explicit"}">'
        f"<title>{html.escape(tooltip)}</title>"
        f"{shape}"
        f'<circle cx="{label_x:.1f}" cy="{label_y:.1f}" r="12" fill="white" stroke="{color}" stroke-width="1.4" />'
        f'<text x="{label_x:.1f}" y="{label_y + 4.5:.1f}" class="edge-label" fill="{color}">{symbol}</text>'
        "</g>"
    )


def svg_defs() -> str:
    return """
        <defs>
          <marker id="arrow-plus" markerWidth="12" markerHeight="12" refX="10" refY="6" orient="auto">
            <path d="M2,2 L10,6 L2,10 Z" fill="#16834a"></path>
          </marker>
          <marker id="arrow-minus" markerWidth="12" markerHeight="12" refX="10" refY="6" orient="auto">
            <path d="M2,2 L10,6 L2,10 Z" fill="#c13b34"></path>
          </marker>
          <marker id="arrow-unknown" markerWidth="12" markerHeight="12" refX="10" refY="6" orient="auto">
            <path d="M2,2 L10,6 L2,10 Z" fill="#66717f"></path>
          </marker>
        </defs>
"""


def render_loop_svg(loop: dict[str, object], lookup: dict[tuple[str, str], Edge]) -> str:
    variables = loop_variables_for_display([str(variable) for variable in loop["variables"]])  # type: ignore[index]
    width = max(760, 210 * len(variables))
    height = 250
    y = 128
    gap = (width - 180) / max(len(variables) - 1, 1)
    positions = [(90 + index * gap, y) for index in range(len(variables))]
    nodes = [svg_node(x, y, variable) for (x, y), variable in zip(positions, variables)]
    edges = []

    for index, source in enumerate(variables):
        target = variables[(index + 1) % len(variables)]
        edge = lookup.get((normalize_name(source), normalize_name(target)))
        polarity = edge.polarity if edge else "unknown"
        tooltip = edge.mechanism if edge else f"Inferred from loop path: {loop['name']}"
        inferred = edge.inferred_from_loop if edge else True

        x1, y1 = positions[index]
        x2, y2 = positions[(index + 1) % len(variables)]
        if index == len(variables) - 1:
            edges.append(svg_edge(x1 - 82, y1 - 31, x2 + 82, y2 - 31, polarity, tooltip, inferred, arc=True))
        else:
            edges.append(svg_edge(x1 + 88, y1, x2 - 88, y2, polarity, tooltip, inferred))

    loop_type = str(loop["loop_type"])
    return (
        f'<svg viewBox="0 0 {width} {height}" class="loop-svg" role="img" '
        f'aria-label="{html.escape(str(loop["name"]))}">'
        f"{svg_defs()}{''.join(edges)}{''.join(nodes)}"
        f'<text x="{width - 18}" y="28" class="loop-type">{html.escape(loop_type)}</text>'
        "</svg>"
    )


def render_relationship_svg(edges: list[Edge]) -> str:
    explicit = [edge for edge in edges if not edge.inferred_from_loop]
    row_height = 92
    width = 980
    height = max(140, 42 + row_height * len(explicit))
    parts = [f'<svg viewBox="0 0 {width} {height}" class="relationship-svg" role="img" aria-label="Explicit relationships">']
    parts.append(svg_defs())
    for index, edge in enumerate(explicit):
        y = 70 + index * row_height
        parts.append(svg_node(185, y, edge.source, "node source-node"))
        parts.append(svg_node(795, y, edge.target, "node target-node"))
        tooltip = "\n".join(
            part
            for part in [
                f"{edge.source} -> {edge.target}",
                f"polarity: {edge.polarity}",
                f"delay: {edge.delay}",
                f"confidence: {edge.confidence}",
                f"mechanism: {edge.mechanism}",
            ]
            if not part.endswith(": ")
        )
        parts.append(svg_edge(273, y, 707, y, edge.polarity, tooltip))
    parts.append("</svg>")
    return "".join(parts)


def system_map_positions(nodes: list[str]) -> dict[str, tuple[float, float]]:
    """Arrange nodes in concentric rings — works for any topic, any scale.

    Each ring's node count is capped so arc-spacing >= 220 px, preventing
    label collisions.  Adjacent rings are angularly offset by half a step so
    nodes never align radially, which keeps edges from overlapping each other.
    Canvas assumed to be 2600 x 1800; centre is (1300, 950).
    """
    n = len(nodes)
    if n == 0:
        return {}
    cx, cy = CANVAS_W // 2, CANVAS_H // 2

    def ring_capacity(radius: float) -> int:
        """Max nodes per ring keeping arc-spacing >= 220 px."""
        return max(1, int(2 * math.pi * radius / 220))

    if n <= 8:
        rings_spec: list[tuple[int, float, float]] = [(n, 400, 0.0)]
    elif n <= 16:
        a = n // 2
        rings_spec = [
            (a, 320, 0.0),
            (n - a, 600, math.pi / (n - a)),
        ]
    elif n <= 28:
        r1, r2, r3 = 280, 520, 780
        c1 = min(ring_capacity(r1), max(4, n // 3))
        c2 = min(ring_capacity(r2), max(6, (n - c1) // 2 + 1))
        c3 = n - c1 - c2
        rings_spec = [
            (c1, r1, 0.0),
            (c2, r2, math.pi / c2),
            (c3, r3, 0.0),
        ]
    else:
        # Four rings: sizes derived from arc-spacing budget, then remainder spills
        # inward so the outer ring is never overcrowded.
        r1, r2, r3, r4 = 280, 500, 730, 940
        c1 = min(ring_capacity(r1), max(5, n // 6))
        c2 = min(ring_capacity(r2), max(7, n // 4))
        c3 = min(ring_capacity(r3), max(10, n // 3))
        c4 = n - c1 - c2 - c3
        if c4 < 0:          # overflow: push excess onto ring 3
            c3 += c4
            c4 = 0
        rings_spec = [
            (c1, r1, 0.0),
            (c2, r2, math.pi / c2),
            (c3, r3, 0.0),
            (c4, r4, math.pi / c4 if c4 > 0 else 0.0),
        ]

    positions: dict[str, tuple[float, float]] = {}
    idx = 0
    for count, radius, offset in rings_spec:
        if count <= 0:
            continue
        for i in range(count):
            if idx >= n:
                break
            angle = 2 * math.pi * i / count - math.pi / 2 + offset
            positions[nodes[idx]] = (
                cx + radius * math.cos(angle),
                cy + radius * math.sin(angle),
            )
            idx += 1
    return positions


_VT_ALIAS: dict[str, str] = {
    "stock": "stock", "level": "stock", "accumulation": "stock",
    "flow": "flow", "rate": "flow", "flow/rate": "flow", "rate/flow": "flow",
    "constant": "constant", "parameter": "constant", "param": "constant",
    "exogenous": "exogenous", "external": "exogenous", "input": "exogenous",
    "auxiliary": "auxiliary", "aux": "auxiliary", "intermediate": "auxiliary",
}

def _norm_vtype(vt: str | None) -> str:
    return _VT_ALIAS.get((vt or "").lower().strip(), "auxiliary")


def render_map_node(
    x: float,
    y: float,
    label: str,
    variable_type: str | bool = "auxiliary",
    data_node: str = "",
    loops: list[str] | None = None,
) -> str:
    # Accept legacy bool (emphasized) for backward-compat call sites
    if isinstance(variable_type, bool):
        variable_type = "stock" if variable_type else "auxiliary"
    vt = _norm_vtype(variable_type)
    line_height = 16
    node_attr = f' data-node="{data_node}"' if data_node else ""
    tip_data = {"kind": "node", "label": label, "node_type": vt, "loops": loops or []}
    tip_attr = f' data-tip="{html.escape(json.dumps(tip_data, ensure_ascii=False))}"'

    if vt in ("stock", "flow", "exogenous"):
        lines = svg_text(label, 16)
        box_h = 28 + (len(lines) - 1) * line_height
        box_w = max(90, min(170, max(len(line) for line in lines) * 8 + 22))
        start_y = y - ((len(lines) - 1) * line_height / 2)
        css_g   = {"stock": "stock-node",    "flow": "flow-node",    "exogenous": "exo-node"}[vt]
        css_txt = {"stock": "map-stock-label","flow": "map-flow-label","exogenous": "map-exo-label"}[vt]
        rx      = {"stock": "4",             "flow": "14",           "exogenous": "4"}[vt]
        text = "".join(
            f'<text x="{x:.1f}" y="{start_y + i * line_height:.1f}" class="{css_txt}">{html.escape(line)}</text>'
            for i, line in enumerate(lines)
        )
        return (
            f'<g class="map-node {css_g}"{node_attr}{tip_attr}>'
            f'<rect x="{x - box_w / 2:.1f}" y="{y - box_h / 2:.1f}" width="{box_w:.1f}" height="{box_h:.1f}" rx="{rx}" />'
            f"{text}</g>"
        )
    # auxiliary or constant: text only
    lines = svg_text(label, 18)
    start_y = y - ((len(lines) - 1) * line_height / 2)
    css_g   = "constant-node" if vt == "constant" else "variable-node"
    css_txt = "map-constant-label" if vt == "constant" else "map-variable-label"
    text = "".join(
        f'<text x="{x:.1f}" y="{start_y + i * line_height:.1f}" class="{css_txt}">{html.escape(line)}</text>'
        for i, line in enumerate(lines)
    )
    return f'<g class="map-node {css_g}"{node_attr}{tip_attr}>{text}</g>'


def render_map_edge(
    edge: Edge,
    positions: dict[str, tuple[float, float]],
    index: int,
    explicit_nodes: set[str] | None = None,
    data_loops: str = "",
    elem_id: str = "",
) -> str:
    x1, y1 = positions[edge.source]
    x2, y2 = positions[edge.target]
    dx = x2 - x1
    dy = y2 - y1
    distance = max((dx * dx + dy * dy) ** 0.5, 1)
    nx, ny = dx / distance, dy / distance  # unit direction vector

    # Offset the path endpoints to clear node boundaries.
    # Red-box (stock) nodes are ~85 px half-width; plain text labels need ~28 px.
    def clear(name: str) -> float:
        return 90.0 if (explicit_nodes and normalize_name(name) in explicit_nodes) else 28.0

    start_x = x1 + nx * clear(edge.source)
    start_y = y1 + ny * clear(edge.source)
    end_x   = x2 - nx * clear(edge.target)
    end_y   = y2 - ny * clear(edge.target)

    # Vary curve magnitude (0.10–0.22) and direction by index so co-incident
    # paths fan out rather than stacking on top of each other.
    curve = (0.10 + 0.04 * (index % 4)) * (1 if index % 2 == 0 else -1)
    control_x = (start_x + end_x) / 2 - dy * curve
    control_y = (start_y + end_y) / 2 + dx * curve
    label_x = (start_x + control_x + end_x) / 3
    label_y = (start_y + control_y + end_y) / 3

    dash = ' stroke-dasharray="6 5"' if edge.inferred_from_loop else ""
    stroke_w = "1.5" if edge.inferred_from_loop else "1.8"
    marker = "url(#map-arrow-inferred)" if edge.inferred_from_loop else "url(#map-arrow)"
    tip_data = {
        "kind": "edge",
        "src": edge.source,
        "tgt": edge.target,
        "polarity": edge.polarity,
        "mechanism": edge.mechanism,
        "delay": edge.delay,
        "confidence": edge.confidence,
        "evidence": edge.evidence,
        "inferred": edge.inferred_from_loop,
    }
    tip_attr = f' data-tip="{html.escape(json.dumps(tip_data, ensure_ascii=False))}"'
    loops_attr = f' data-loops="{data_loops}"' if data_loops else ""
    initial_opacity = ' style="opacity:0.45"' if edge.inferred_from_loop else ""
    id_attr = f' id="{elem_id}"' if elem_id else ""
    return (
        f'<g{id_attr} class="map-edge {"inferred" if edge.inferred_from_loop else "explicit"}"{loops_attr}{initial_opacity}{tip_attr}>'
        f'<path d="M{start_x:.1f},{start_y:.1f} Q{control_x:.1f},{control_y:.1f} {end_x:.1f},{end_y:.1f}" '
        f'fill="none" stroke="#0000cc" stroke-width="{stroke_w}"{dash} marker-end="{marker}" />'
        f'<text x="{label_x:.1f}" y="{label_y:.1f}" class="map-polarity">{polarity_symbol(edge.polarity)}</text>'
        "</g>"
    )


def write_system_map_html(
    payload: dict[str, object],
    path: Path,
    evidence: list[dict[str, str]] | None = None,
    variables: list[dict[str, str]] | None = None,
    mechanisms: list[dict[str, str]] | None = None,
) -> None:
    nodes = [str(node["id"]) for node in payload["nodes"]]  # type: ignore[index]

    # Append orphan variables (defined in variables/ but not yet in the network)
    if variables:
        network_norms = {normalize_name(n) for n in nodes}
        for v in variables:
            lbl = v.get("label", "").strip()
            if lbl and normalize_name(lbl) not in network_norms:
                nodes.append(lbl)

    edges = [
        Edge(
            source=str(edge["source"]),
            target=str(edge["target"]),
            polarity=str(edge["polarity"]),
            mechanism=str(edge["mechanism"]),
            delay=str(edge["delay"]),
            confidence=str(edge["confidence"]),
            evidence=str(edge["evidence"]),
            inferred_from_loop=bool(edge["inferred_from_loop"]),
        )
        for edge in payload["edges"]  # type: ignore[index]
    ]

    # ── Build loop metadata and edge→loop membership map ─────────────────────
    loop_records: list[dict[str, object]] = []
    edge_loop_map: dict[tuple[str, str], list[str]] = {}

    for loop_data in payload["loops"]:  # type: ignore[index]
        loop_name = str(loop_data["name"])  # type: ignore[index]
        # Match any common loop-ID pattern: L-01, L01, B-01, B1, R1, R-02 …
        m = re.search(r"[A-Za-z]-?\d+", loop_name)
        loop_id = m.group(0).upper() if m else f"L-{len(loop_records) + 1:02d}"

        loop_vars = [str(v) for v in loop_data["variables"]]  # type: ignore[index]
        loop_type = str(loop_data["loop_type"])  # type: ignore[index]
        narrative = str(loop_data.get("narrative", ""))  # type: ignore[union-attr]

        # Short display name: strip any leading ID prefix, e.g.
        # "Loop L-01: Price War Spiral" → "Price War Spiral"
        # "B1 Price Competition Loop"   → "Price Competition Loop"
        # "R-02: Investment Loop"       → "Investment Loop"
        short_name = re.sub(r"^(Loop\s+)?[A-Za-z]-?\d+[:\s]+", "", loop_name, flags=re.IGNORECASE).strip()
        if not short_name:
            short_name = loop_name

        # Register each consecutive edge pair for this loop
        node_slugs: list[str] = []
        for i, src in enumerate(loop_vars):
            tgt = loop_vars[(i + 1) % len(loop_vars)]
            s = slugify(src)
            if not node_slugs or node_slugs[-1] != s:
                node_slugs.append(s)
            if normalize_name(src) == normalize_name(tgt):
                continue
            key = (normalize_name(src), normalize_name(tgt))
            edge_loop_map.setdefault(key, [])
            if loop_id not in edge_loop_map[key]:
                edge_loop_map[key].append(loop_id)

        is_reinforcing = "reinforcing" in loop_type.lower()
        loop_records.append(
            {
                "id": loop_id,
                "name": loop_name,
                "short_name": short_name,
                "type": loop_type,
                "narrative": narrative,
                "node_slugs": node_slugs,
                "is_reinforcing": is_reinforcing,
            }
        )

    # ── Node → loop membership (for tooltip) ─────────────────────────────────
    node_loop_map: dict[str, list[str]] = {}
    for rec in loop_records:
        for slug in rec["node_slugs"]:  # type: ignore[union-attr]
            node_loop_map.setdefault(str(slug), [])
            if rec["id"] not in node_loop_map[str(slug)]:
                node_loop_map[str(slug)].append(str(rec["id"]))

    # ── Explicit nodes (variables with their own relationship page) ───────────
    explicit_nodes = {
        normalize_name(node)
        for edge in edges
        if not edge.inferred_from_loop
        for node in (edge.source, edge.target)
    }

    def get_data_loops(edge: Edge) -> str:
        key = (normalize_name(edge.source), normalize_name(edge.target))
        return " ".join(edge_loop_map.get(key, []))

    # ── Positions and SVG ─────────────────────────────────────────────────────
    positions = system_map_positions(nodes)
    inferred_edges = [e for e in edges if e.inferred_from_loop]
    explicit_edges = [e for e in edges if not e.inferred_from_loop]

    # Inferred edges render first (behind explicit); each starts hidden (opacity:0)
    edge_raw: list[dict] = []
    inferred_svg_parts = []
    for i, e in enumerate(inferred_edges):
        eid = f"emap-i{i}"
        edge_raw.append({"id": eid, "src": slugify(e.source), "tgt": slugify(e.target),
                         "polarity": e.polarity, "curveIdx": i, "inferred": True})
        inferred_svg_parts.append(render_map_edge(e, positions, i, explicit_nodes, get_data_loops(e), eid))
    inferred_svg = "".join(inferred_svg_parts)

    explicit_svg_parts = []
    for i, e in enumerate(explicit_edges):
        eid = f"emap-x{i}"
        edge_raw.append({"id": eid, "src": slugify(e.source), "tgt": slugify(e.target),
                         "polarity": e.polarity, "curveIdx": i, "inferred": False})
        explicit_svg_parts.append(render_map_edge(e, positions, i, explicit_nodes, get_data_loops(e), eid))
    explicit_svg = "".join(explicit_svg_parts)

    # Build variable-type lookup from loaded variable files
    var_type_map: dict[str, str] = {}
    for v in variables:
        slug_v = slugify(v.get("label", v.get("id", "")))
        var_type_map[slug_v] = _norm_vtype(v.get("variable_type", ""))

    def node_vtype(node: str) -> str:
        s = slugify(node)
        if s in var_type_map:
            return var_type_map[s]
        # Fallback: nodes with explicit relationships default to stock (legacy)
        return "stock" if normalize_name(node) in explicit_nodes else "auxiliary"

    # box_types affect arrowhead clearance (need extra padding around visible rect)
    _box_types = {"stock", "flow", "exogenous"}
    node_pos_data = {
        slugify(n): {
            "x": round(px, 1), "y": round(py, 1),
            "isStock": node_vtype(n) in _box_types,
        }
        for n, (px, py) in positions.items()
    }
    node_positions_js = json.dumps(node_pos_data, ensure_ascii=False)
    edge_raw_js_data   = json.dumps(edge_raw, ensure_ascii=False)

    node_svg = "".join(
        render_map_node(
            x, y, node,
            node_vtype(node),
            slugify(node),
            node_loop_map.get(slugify(node), []),
        )
        for node, (x, y) in positions.items()
    )

    # ── Loop buttons ──────────────────────────────────────────────────────────
    R_COLOR = "#1d4ed8"   # reinforcing loops: blue
    B_COLOR = "#7c3aed"   # balancing loops: violet
    loop_buttons_html = ""
    for rec in loop_records:
        color = R_COLOR if rec["is_reinforcing"] else B_COLOR
        type_icon = "↺" if rec["is_reinforcing"] else "⇌"
        loop_buttons_html += (
            f'<button class="loop-btn" data-loop="{rec["id"]}" '
            f'style="--lc:{color}" '
            f'onclick="highlightLoop(\'{rec["id"]}\',this)" '
            f'title="{html.escape(str(rec["type"]))} — {html.escape(str(rec["narrative"]))}">'
            f'<span class="loop-type-icon">{type_icon}</span>'
            f'<b>{rec["id"]}</b> '
            f'<span class="loop-short-name">{html.escape(str(rec["short_name"]))}</span>'
            f'</button>'
        )

    # ── Embed loop data as JSON for JS ────────────────────────────────────────
    # Enrich loop records with full variable names and metadata for the panel
    loop_data_by_id = {rec["id"]: rec for rec in loop_records}
    for loop_data in payload["loops"]:  # type: ignore[index]
        lname = str(loop_data["name"])
        m = re.search(r"[A-Za-z]-?\d+", lname)
        lid = m.group(0).upper() if m else None
        if lid and lid in loop_data_by_id:
            loop_data_by_id[lid]["variables_list"] = [str(v) for v in loop_data["variables"]]  # type: ignore[index]
            loop_data_by_id[lid]["dominant_period"] = str(loop_data.get("dominant_period", ""))  # type: ignore[union-attr]
            loop_data_by_id[lid]["delay_points"] = str(loop_data.get("delay_points", ""))  # type: ignore[union-attr]
            loop_data_by_id[lid]["leverage_points"] = str(loop_data.get("leverage_points", ""))  # type: ignore[union-attr]
            loop_data_by_id[lid]["collapse_conditions"] = str(loop_data.get("collapse_conditions", ""))  # type: ignore[union-attr]
    loop_js_data = json.dumps(loop_data_by_id, ensure_ascii=False)
    evidence_js_data = json.dumps(evidence or [], ensure_ascii=False)
    variable_js_data = json.dumps(variables or [], ensure_ascii=False)
    mechanism_js_data = json.dumps(mechanisms or [], ensure_ascii=False)

    project_name = path.parent.name.replace("-", " ").title()
    explicit_count = len(explicit_edges)
    inferred_count = len(inferred_edges)
    width = CANVAS_W
    height = CANVAS_H

    html_doc = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>LoopMap — {project_name}</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: #f5f7fb;
      font-family: Arial, Helvetica, sans-serif;
      color: #1a202c;
      display: flex;
      flex-direction: column;
      height: 100vh;
      overflow: hidden;
    }}

    /* ── Top toolbar ──────────────────────────────────────────────────── */
    .toolbar {{
      position: sticky;
      top: 0;
      z-index: 20;
      padding: 8px 16px;
      background: rgba(255,255,255,0.97);
      border-bottom: 1px solid #d0d5dd;
      box-shadow: 0 1px 4px rgba(0,0,0,.07);
    }}
    .toolbar-row1 {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px 18px;
      align-items: center;
      font-size: 13px;
      color: #3a424e;
    }}
    .toolbar-row1 strong {{ font-size: 14px; color: #111827; }}

    /* ── LoopMap brand ───────────────────────────────────────────────── */
    .brand {{
      display: flex; align-items: center; gap: 9px; flex-shrink: 0; user-select: none;
    }}
    .brand-mark {{
      width: 30px; height: 30px; flex-shrink: 0;
      background: linear-gradient(135deg, #1d4ed8 0%, #7c3aed 100%);
      border-radius: 8px;
      display: flex; align-items: center; justify-content: center;
      color: #fff; font-size: 17px; line-height: 1; font-weight: 900;
      box-shadow: 0 1px 4px rgba(124,58,237,.35);
    }}
    .brand-text {{ display: flex; flex-direction: row; align-items: baseline; gap: 8px; line-height: 1; }}
    .brand-wordmark {{
      font-size: 16px; font-weight: 800; letter-spacing: -0.04em;
      background: linear-gradient(90deg, #1d4ed8, #7c3aed);
      -webkit-background-clip: text; -webkit-text-fill-color: transparent;
      background-clip: text;
    }}
    .brand-sub {{
      font-size: 9px; font-weight: 600; letter-spacing: .1em;
      text-transform: uppercase; color: #94a3b8;
    }}
    .brand-divider {{
      width: 1px; height: 28px; background: #d0d5dd; flex-shrink: 0; margin: 0 4px;
    }}

    .legend {{ display: flex; gap: 14px; align-items: center; color: #5a6473; font-size: 12px; }}
    .legend span {{ display: flex; align-items: center; gap: 5px; }}
    .swatch {{ width: 26px; height: 3px; border-radius: 2px; }}
    .swatch.solid  {{ background: #0000cc; }}
    .swatch.dashed {{ background: repeating-linear-gradient(90deg,#0000cc 0 5px,transparent 5px 10px); }}

    /* ── Loop selector bar ────────────────────────────────────────────── */
    .loop-bar {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px 8px;
      align-items: center;
      padding: 7px 0 4px;
      border-top: 1px solid #e9ecf1;
      margin-top: 7px;
    }}
    .loop-bar-label {{
      font-size: 11px;
      font-weight: 700;
      color: #6b7280;
      text-transform: uppercase;
      letter-spacing: .05em;
      white-space: nowrap;
    }}

    /* ── Loop buttons ──────────────────────────────────────────────────── */
    button {{
      padding: 4px 10px;
      font-size: 12px;
      font-family: Arial, Helvetica, sans-serif;
      border: 1.5px solid #c6cdd8;
      border-radius: 5px;
      background: #f2f4f7;
      cursor: pointer;
      transition: background .12s, border-color .12s;
      white-space: nowrap;
    }}
    button:hover {{ background: #e4e8ef; border-color: #9aa3b0; }}
    .loop-btn {{ border-color: var(--lc, #6b7280); color: #1f2937; }}
    .loop-btn:hover {{ background: color-mix(in srgb, var(--lc) 10%, white); }}
    .loop-btn.active {{
      background: var(--lc, #1d4ed8);
      color: #ffffff;
      border-color: var(--lc, #1d4ed8);
    }}
    .loop-btn.active .loop-short-name {{ color: rgba(255,255,255,0.85); }}
    .loop-type-icon {{ margin-right: 3px; }}
    .loop-short-name {{ color: #4b5563; font-size: 11px; }}

    /* ── Loop info panel ──────────────────────────────────────────────── */
    .loop-info-bar {{
      padding: 4px 0 0;
      font-size: 12px;
      color: #374151;
      min-height: 18px;
    }}

    /* ── Utility button ───────────────────────────────────────────────── */
    #btn-inferred {{ font-size: 12px; }}
    #btn-clear    {{ font-size: 12px; display: none; }}
    #btn-report   {{ font-size: 12px; background: linear-gradient(135deg,#1d4ed8,#7c3aed); color:#fff; border-color: transparent; font-weight: 600; }}
    #btn-report:hover {{ opacity: 0.88; }}
    .edit-tools-overlay {{
      position: absolute; top: 14px; right: 14px; z-index: 50;
      display: flex; flex-direction: column; align-items: center; gap: 8px;
      background: rgba(15,23,42,0.82); backdrop-filter: blur(6px);
      border: 1px solid #334155; border-radius: 10px;
      padding: 10px 8px; box-shadow: 0 4px 18px rgba(0,0,0,0.35);
    }}
    .edit-tools-label {{
      font-size: 9px; color: #64748b; text-transform: uppercase;
      letter-spacing: 0.7px; user-select: none; line-height: 1;
    }}
    .edit-tools-overlay button {{
      width: 32px; height: 32px; padding: 0; font-size: 16px; line-height: 1;
      display: flex; align-items: center; justify-content: center;
      border-radius: 7px; border: 1px solid #334155; background: #1e293b;
      cursor: pointer; color: #94a3b8; transition: background 0.15s, color 0.15s, border-color 0.15s;
    }}
    #btn-add-var        {{ color: #4ade80; border-color: #166534; }}
    #btn-add-var:hover  {{ background: #14532d; color: #86efac; border-color: #16a34a; }}
    #btn-add-var.no-server {{ opacity: 0.35; cursor: not-allowed; }}
    #btn-relate         {{ color: #60a5fa; border-color: #1e3a5f; }}
    #btn-relate.active  {{ background: #1d4ed8; color: #fff; border-color: #3b82f6; }}
    #btn-relate:hover   {{ background: #1e3a5f; color: #93c5fd; border-color: #3b82f6; }}
    #btn-relate.no-server {{ opacity: 0.35; cursor: not-allowed; }}
    #btn-delete         {{ color: #f87171; border-color: #450a0a; }}
    #btn-delete.active  {{ background: #dc2626; color: #fff; border-color: #ef4444; }}
    #btn-delete:hover   {{ background: #450a0a; color: #fca5a5; border-color: #dc2626; }}
    #btn-delete.no-server {{ opacity: 0.35; cursor: not-allowed; }}

    /* ── Mode banner ──────────────────────────────────────────────────── */
    .edit-mode-banner {{
      display: none; position: fixed; bottom: 18px; left: 50%; transform: translateX(-50%);
      background: rgba(30,64,175,0.94); color: #fff; padding: 9px 22px; border-radius: 24px;
      font-size: 12px; font-weight: 600; z-index: 8000; pointer-events: none; white-space: nowrap;
      box-shadow: 0 2px 14px rgba(30,64,175,0.45);
    }}
    .edit-mode-banner.visible {{ display: block; }}
    body.delete-mode .canvas  {{ cursor: crosshair !important; }}
    body.delete-mode .map-node {{ cursor: not-allowed !important; }}
    body.relate-mode .canvas  {{ cursor: crosshair !important; }}
    body.relate-mode .map-node {{ cursor: cell !important; }}
    .map-node.node-selected rect {{ stroke: #16a34a !important; stroke-width: 3px !important;
      filter: drop-shadow(0 0 8px rgba(22,163,74,0.6)) !important; }}
    .map-node.node-selected text {{ font-weight: 900; }}

    /* ── Edit dialogs ─────────────────────────────────────────────────── */
    .edit-dlg-overlay {{
      display: none; position: fixed; inset: 0; z-index: 9500;
      background: rgba(0,0,0,0.48); backdrop-filter: blur(2px);
      align-items: center; justify-content: center;
    }}
    .edit-dlg-overlay.open {{ display: flex; }}
    .edit-dlg {{
      background: #fff; border-radius: 12px; width: 100%; max-width: 430px;
      box-shadow: 0 10px 44px rgba(0,0,0,0.24); overflow: hidden;
    }}
    .edit-dlg-head {{
      padding: 14px 20px; font-size: 14px; font-weight: 800; color: #fff;
      background: linear-gradient(90deg,#16a34a 0%,#15803d 100%);
    }}
    .edit-dlg-body {{ padding: 18px 20px; }}
    .edit-dlg-body label {{
      display: block; font-size: 10px; font-weight: 700; color: #64748b;
      text-transform: uppercase; letter-spacing: .07em; margin-top: 12px; margin-bottom: 3px;
    }}
    .edit-dlg-body label:first-child {{ margin-top: 0; }}
    .edit-dlg-body input, .edit-dlg-body select, .edit-dlg-body textarea {{
      width: 100%; box-sizing: border-box; padding: 7px 10px; font-size: 13px;
      border: 1px solid #cbd5e1; border-radius: 6px; font-family: inherit; color: #1e293b;
      background: #f8fafc;
    }}
    .edit-dlg-body input:focus, .edit-dlg-body select:focus, .edit-dlg-body textarea:focus {{
      outline: 2px solid #16a34a; outline-offset: 1px; background: #fff;
    }}
    .edit-dlg-body textarea {{ height: 76px; resize: vertical; }}
    .edit-dlg-body input[readonly] {{ color: #64748b; cursor: default; }}
    .edit-dlg-foot {{
      padding: 12px 20px; display: flex; gap: 8px; justify-content: flex-end;
      border-top: 1px solid #f1f5f9;
    }}
    .edit-dlg-foot button {{
      padding: 7px 18px; border-radius: 6px; font-size: 13px; font-weight: 600;
      cursor: pointer; border: 1px solid #cbd5e1; background: #f8fafc; color: #374151;
    }}
    .edit-dlg-foot button.primary {{
      background: linear-gradient(90deg,#16a34a,#15803d); color: #fff; border-color: transparent;
    }}
    .edit-dlg-foot button.primary:hover {{ opacity: 0.87; }}
    body.dark .edit-dlg {{ background: #1e2d40; }}
    body.dark .edit-dlg-body input,
    body.dark .edit-dlg-body select,
    body.dark .edit-dlg-body textarea {{ background: #0f172a; border-color: #334155; color: #e2e8f0; }}
    body.dark .edit-dlg-foot {{ border-top-color: #1e3358; }}
    body.dark .edit-dlg-foot button {{ background: #1e3358; border-color: #334155; color: #cbd5e1; }}

    /* ── Report modal ─────────────────────────────────────────────────── */
    #report-modal {{
      display: none; position: fixed; inset: 0; z-index: 9999;
      background: rgba(0,0,0,0.55); backdrop-filter: blur(3px);
      align-items: flex-start; justify-content: center; overflow-y: auto; padding: 32px 16px;
    }}
    #report-modal.open {{ display: flex; }}
    #report-box {{
      background: #fff; border-radius: 12px; width: 100%; max-width: 820px;
      box-shadow: 0 8px 40px rgba(0,0,0,0.28); overflow: hidden; flex-shrink: 0;
    }}
    #report-header {{
      display: flex; align-items: center; justify-content: space-between;
      padding: 16px 22px; border-bottom: 1px solid #e2e8f0;
      background: linear-gradient(90deg,#1d4ed8 0%,#7c3aed 100%);
    }}
    #report-header h2 {{ color:#fff; font-size:15px; font-weight:800; letter-spacing:-.02em; margin:0; }}
    #report-header span {{ color:rgba(255,255,255,.75); font-size:11px; }}
    .report-actions {{
      display: flex; gap: 8px;
    }}
    .report-actions button {{
      font-size: 11px; padding: 5px 12px; border-radius: 5px;
      background: rgba(255,255,255,0.18); color: #fff; border: 1px solid rgba(255,255,255,0.35);
      cursor: pointer; font-weight: 600;
    }}
    .report-actions button:hover {{ background: rgba(255,255,255,0.30); }}
    #report-close {{
      background: none !important; border: none !important; font-size: 18px !important;
      line-height: 1; color: #fff !important; cursor: pointer; padding: 2px 6px !important;
    }}
    #report-content {{
      padding: 24px 28px; font-family: Arial, Helvetica, sans-serif;
      font-size: 12.5px; color: #1e293b; line-height: 1.6; overflow-x: hidden;
    }}
    .rpt-section {{ margin-bottom: 26px; }}
    .rpt-h1 {{
      font-size: 18px; font-weight: 900; letter-spacing: -.03em;
      color: #0f172a; margin-bottom: 2px;
    }}
    .rpt-meta {{ font-size: 10px; color: #94a3b8; margin-bottom: 18px; }}
    .rpt-h2 {{
      font-size: 12px; font-weight: 800; text-transform: uppercase;
      letter-spacing: .08em; color: #1d4ed8; border-bottom: 2px solid #dbeafe;
      padding-bottom: 4px; margin-bottom: 10px;
    }}
    .rpt-stats {{
      display: grid; grid-template-columns: repeat(4,1fr); gap: 10px; margin-bottom: 4px;
    }}
    .rpt-stat-box {{
      background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px;
      padding: 10px 12px; text-align: center;
    }}
    .rpt-stat-num {{ font-size: 22px; font-weight: 900; color: #1d4ed8; line-height:1; }}
    .rpt-stat-lbl {{ font-size: 10px; color: #64748b; margin-top: 2px; }}
    .rpt-loop {{
      border: 1px solid #e2e8f0; border-radius: 8px; padding: 12px 14px;
      margin-bottom: 10px; border-left: 4px solid #1d4ed8;
    }}
    .rpt-loop.balancing {{ border-left-color: #7c3aed; }}
    .rpt-loop-head {{ display:flex; align-items:center; gap:8px; margin-bottom:6px; }}
    .rpt-loop-id {{ font-size:13px; font-weight:900; color:#1d4ed8; }}
    .rpt-loop.balancing .rpt-loop-id {{ color:#7c3aed; }}
    .rpt-loop-name {{ font-size:12px; font-weight:700; color:#0f172a; }}
    .rpt-loop-badge {{
      font-size:9px; font-weight:700; padding:2px 7px; border-radius:20px;
      text-transform:uppercase; letter-spacing:.06em;
    }}
    .rpt-loop-badge.r {{ background:#dbeafe; color:#1d4ed8; }}
    .rpt-loop-badge.b {{ background:#ede9fe; color:#6d28d9; }}
    .rpt-field {{ margin-bottom: 5px; }}
    .rpt-field-label {{ font-size:10px; font-weight:700; text-transform:uppercase;
      letter-spacing:.06em; color:#64748b; }}
    .rpt-field-value {{ color:#334155; }}
    .rpt-chain {{ display:flex; flex-wrap:wrap; gap:4px; align-items:center; margin-top:3px; }}
    .rpt-chip {{ font-size:10px; background:#f1f5f9; border:1px solid #cbd5e1;
      border-radius:4px; padding:2px 7px; color:#334155; }}
    .rpt-arrow {{ font-size:10px; color:#94a3b8; }}
    .rpt-ev {{
      padding: 8px 12px; border-left: 3px solid #10b981;
      background: #f0fdf4; border-radius: 0 6px 6px 0; margin-bottom: 8px;
    }}
    .rpt-ev-source {{ font-weight:700; font-size:11px; color:#065f46; }}
    .rpt-ev-date {{ font-size:10px; color:#64748b; }}
    .rpt-ev-finding {{ font-size:11px; color:#1e293b; margin-top:3px; line-height:1.45; }}
    .rpt-mech {{ padding:6px 0; border-bottom:1px solid #f1f5f9; }}
    .rpt-mech:last-child {{ border-bottom:none; }}
    .rpt-mech-label {{ font-weight:700; font-size:11px; color:#1e293b; }}
    .rpt-mech-rel {{ font-size:10px; color:#7c3aed; margin:1px 0; }}
    .rpt-mech-exp {{ font-size:11px; color:#475569; line-height:1.4; }}
    .rpt-var-grid {{
      display:grid; grid-template-columns: 1fr 1fr; gap:6px;
    }}
    .rpt-var {{
      background:#f8fafc; border:1px solid #e2e8f0; border-radius:6px; padding:8px 10px;
    }}
    .rpt-var-label {{ font-weight:700; font-size:11px; color:#1e293b; }}
    .rpt-var-type {{ font-size:9px; color:#94a3b8; text-transform:uppercase; letter-spacing:.05em; }}
    .rpt-var-def {{ font-size:10px; color:#475569; margin-top:2px; line-height:1.35; }}
    .rpt-leverage {{ background:#eff6ff; border-radius:6px; padding:8px 12px; margin-bottom:6px; }}
    .rpt-leverage-loop {{ font-size:10px; font-weight:700; color:#1d4ed8; margin-bottom:3px; }}
    .rpt-collapse {{ background:#fff7ed; border-radius:6px; padding:8px 12px; margin-bottom:6px; }}
    .rpt-collapse-loop {{ font-size:10px; font-weight:700; color:#c2410c; margin-bottom:3px; }}
    .rpt-summary-text {{ color:#334155; line-height:1.65; }}
    body.dark #report-box {{ background:#0c1627; }}
    body.dark #report-content {{ color:#dde6f0; }}
    body.dark .rpt-h2 {{ color:#60a5fa; border-bottom-color:#1e3358; }}
    body.dark .rpt-stat-box {{ background:#0f1e35; border-color:#1e3358; }}
    body.dark .rpt-stat-lbl {{ color:#4a7fa8; }}
    body.dark .rpt-loop {{ border-color:#1e3358; background:#0a1628; }}
    body.dark .rpt-chip {{ background:#1a2640; border-color:#2a3f60; color:#94a3b8; }}
    body.dark .rpt-ev {{ background:#0a1e12; border-left-color:#10b981; }}
    body.dark .rpt-ev-finding {{ color:#94a3b8; }}
    body.dark .rpt-var {{ background:#0f1e35; border-color:#1e3358; }}
    body.dark .rpt-leverage {{ background:#0f1e35; }}
    body.dark .rpt-collapse {{ background:#1e140a; }}
    body.dark .rpt-mech {{ border-bottom-color:#1e3358; }}
    body.dark .rpt-field-value {{ color:#94a3b8; }}
    body.dark .rpt-summary-text {{ color:#94a3b8; }}
    @media print {{
      #report-modal {{ position: static; background:none; padding:0; }}
      #report-box {{ box-shadow:none; border-radius:0; max-width:100%; }}
      #report-header {{ print-color-adjust: exact; -webkit-print-color-adjust: exact; }}
      #report-header .report-actions {{ display:none; }}
    }}

    /* ── SVG canvas ───────────────────────────────────────────────────── */
    .canvas {{
      flex: 1 1 0;
      overflow: hidden;
      background: #ffffff;
      cursor: grab;
      user-select: none;
      -webkit-user-select: none;
    }}
    .canvas.dragging {{ cursor: grabbing; }}
    svg {{
      display: block;
      width: 100%;
      height: 100%;
      background: white;
    }}
    /* ── Zoom controls ────────────────────────────────────────────────── */
    .zoom-controls {{ display: flex; gap: 4px; align-items: center; margin-left: 4px; }}
    .zoom-controls button {{
      padding: 2px 9px;
      font-size: 16px;
      font-weight: 700;
      line-height: 1.2;
      min-width: 28px;
    }}
    #zoom-level {{
      font-size: 11px;
      color: #6b7280;
      min-width: 38px;
      text-align: center;
    }}
    /* Stock — red box */
    .stock-node rect {{ fill: #c53030; stroke: #742a2a; stroke-width: 1.5; }}
    .map-stock-label {{
      fill: #ffffff; text-anchor: middle; dominant-baseline: middle;
      font-family: "Times New Roman", Times, serif; font-size: 15px; font-weight: 400;
    }}
    /* Flow / Rate — amber rounded box */
    .flow-node rect {{ fill: #b45309; stroke: #78350f; stroke-width: 1.5; }}
    .map-flow-label {{
      fill: #ffffff; text-anchor: middle; dominant-baseline: middle;
      font-family: "Times New Roman", Times, serif; font-size: 15px; font-weight: 400;
    }}
    /* Exogenous — dashed blue-gray box */
    .exo-node rect {{ fill: #1e3a5f; stroke: #3b82f6; stroke-width: 1.5; stroke-dasharray: 5,3; }}
    .map-exo-label {{
      fill: #bfdbfe; text-anchor: middle; dominant-baseline: middle;
      font-family: "Times New Roman", Times, serif; font-size: 15px; font-weight: 400;
    }}
    /* Constant — small italic gray text */
    .map-constant-label {{
      fill: #6b7280; text-anchor: middle; dominant-baseline: middle;
      font-family: "Times New Roman", Times, serif; font-size: 13px; font-style: italic;
    }}
    /* Auxiliary — plain text */
    .map-variable-label {{
      fill: #1a202c;
      text-anchor: middle;
      dominant-baseline: middle;
      font-family: "Times New Roman", Times, serif;
      font-size: 16px;
    }}
    .map-polarity {{
      fill: #0000cc;
      font-family: Arial, Helvetica, sans-serif;
      font-size: 15px;
      font-weight: 700;
      text-anchor: middle;
    }}
    /* Loop-highlighted nodes and edges glow slightly */
    .map-node.loop-lit rect  {{ filter: drop-shadow(0 0 6px rgba(255,200,0,.9)); }}
    .map-node.loop-lit text  {{ font-weight: 900; }}
    .map-edge.loop-lit path  {{ filter: drop-shadow(0 0 3px rgba(0,0,200,.6)); }}
    .map-edge:hover {{ cursor: pointer; }}
    .map-node:hover {{ cursor: pointer; }}

    /* ── Hover animations ─────────────────────────────────────────────── */
    .map-node rect {{
      transform-box: fill-box;
      transform-origin: center;
      transition: transform 0.15s ease, filter 0.15s ease;
    }}
    .map-node:hover rect {{
      transform: scale(1.1);
      filter: brightness(1.15) drop-shadow(0 2px 10px rgba(0,0,200,0.28));
    }}
    .map-edge path {{
      transition: stroke-width 0.12s ease, filter 0.12s ease;
    }}
    .map-edge:hover path {{
      stroke-width: 3.2px !important;
      filter: drop-shadow(0 0 6px rgba(0,0,200,0.5));
    }}

    /* ── Ambient always-on animations ────────────────────────────────── */

    /* Inferred dashed edges: slow flowing dashes (ambient) */
    @keyframes flow-ambient {{
      from {{ stroke-dashoffset: 22; }}
      to   {{ stroke-dashoffset: 0; }}
    }}
    .map-edge.inferred path {{
      animation: flow-ambient 1.1s linear infinite;
    }}
    .map-edge.inferred:nth-child(even) path {{
      animation-delay: -0.55s;
    }}
    .map-edge.inferred:nth-child(3n) path {{
      animation-delay: -0.3s; animation-duration: 1.4s;
    }}

    /* Explicit solid edges: subtle heartbeat glow */
    @keyframes edge-pulse {{
      0%, 100% {{ filter: none; }}
      50%       {{ filter: drop-shadow(0 0 5px rgba(30,80,220,0.28)); }}
    }}
    .map-edge.explicit:not(:hover) path {{
      animation: edge-pulse 1.8s ease-in-out infinite;
    }}
    .map-edge.explicit:nth-child(even):not(:hover) path {{
      animation-delay: -0.9s;
    }}
    .map-edge.explicit:nth-child(3n):not(:hover) path {{
      animation-delay: -0.45s; animation-duration: 2.2s;
    }}

    /* Node breathing: staggered brightness pulse */
    @keyframes node-breathe {{
      0%, 100% {{ filter: brightness(1); }}
      50%       {{ filter: brightness(0.87) drop-shadow(0 0 10px rgba(80,120,255,0.22)); }}
    }}
    .map-node:not(:hover):not(.bouncing) rect {{
      animation: node-breathe 2s ease-in-out infinite;
    }}
    .map-node:nth-child(2n):not(:hover):not(.bouncing) rect {{
      animation-delay: -0.8s;
    }}
    .map-node:nth-child(3n):not(:hover):not(.bouncing) rect {{
      animation-delay: -0.4s; animation-duration: 2.4s;
    }}
    .map-node:nth-child(5n):not(:hover):not(.bouncing) rect {{
      animation-delay: -1.4s; animation-duration: 1.7s;
    }}

    /* ── Loop flow animation (active loop edges — fast + glowing) ──── */
    @keyframes flow-dash {{
      from {{ stroke-dashoffset: 20; }}
      to   {{ stroke-dashoffset: 0; }}
    }}
    .map-edge.flowing path {{
      stroke-dasharray: 7 3 !important;
      animation: flow-dash 0.42s linear infinite !important;
      filter: drop-shadow(0 0 7px rgba(29,78,216,0.70)) !important;
    }}

    /* ── Node click bounce ────────────────────────────────────────────── */
    @keyframes node-bounce {{
      0%   {{ transform: scale(1); }}
      35%  {{ transform: scale(1.22); }}
      65%  {{ transform: scale(0.96); }}
      100% {{ transform: scale(1); }}
    }}
    .map-node.bouncing rect {{
      animation: node-bounce 0.38s ease;
      transform-box: fill-box;
      transform-origin: center;
    }}

    /* ── Main area: panel + canvas side by side ────────────────────── */
    .main-area {{
      display: flex;
      flex: 1 1 0;
      overflow: hidden;
    }}

    /* ── Left info panel ───────────────────────────────────────────── */
    #info-panel {{
      width: 500px;
      min-width: 500px;
      background: #f8fafc;
      border-right: 1px solid #d0d5dd;
      display: flex;
      flex-direction: column;
      overflow: visible;
      transition: width .2s ease, min-width .2s ease;
      font-size: 12px;
      font-family: Arial, Helvetica, sans-serif;
      position: relative;
      flex-shrink: 0;
    }}
    #info-panel.collapsed {{
      width: 0;
      min-width: 0;
    }}
    .panel-inner {{
      display: flex;
      flex-direction: column;
      flex: 1 1 0;
      min-height: 0;
      overflow: hidden;
    }}
    #panel-toggle {{
      position: absolute;
      right: -18px;
      top: 50%;
      transform: translateY(-50%);
      z-index: 30;
      width: 18px;
      height: 48px;
      background: #e2e8f0;
      border: 1px solid #cbd5e1;
      border-left: none;
      border-radius: 0 6px 6px 0;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 10px;
      color: #64748b;
      padding: 0;
    }}
    .canvas-wrap {{ position: relative; flex: 1 1 0; overflow: hidden; display: flex; }}

    /* ── Right evidence panel ──────────────────────────────────────── */
    #evidence-panel {{
      width: 500px;
      min-width: 500px;
      background: #f8fafc;
      border-left: 1px solid #d0d5dd;
      display: flex;
      flex-direction: column;
      overflow: hidden;
      transition: width .2s ease, min-width .2s ease;
      font-size: 12px;
      font-family: Arial, Helvetica, sans-serif;
      position: relative;
    }}
    #evidence-panel.collapsed {{ width: 0; min-width: 0; }}
    #panel-toggle-right {{
      position: absolute;
      left: -18px;
      top: 50%;
      transform: translateY(-50%);
      z-index: 30;
      width: 18px;
      height: 48px;
      background: #e2e8f0;
      border: 1px solid #cbd5e1;
      border-right: none;
      border-radius: 6px 0 0 6px;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 10px;
      color: #64748b;
      padding: 0;
    }}
    body.dark #evidence-panel {{ background: #0c1627; border-color: #1a2f4e; }}
    body.dark #panel-toggle-right {{ background: #1a2640; border-color: #2a3f60; color: #475569; }}

    .panel-header {{
      padding: 10px 12px 8px;
      background: #1e293b;
      color: #f1f5f9;
      font-weight: 700;
      font-size: 13px;
      letter-spacing: .02em;
      flex-shrink: 0;
    }}
    .panel-body {{
      flex: 1;
      overflow-y: auto;
      padding: 0;
    }}
    .panel-section {{
      border-bottom: 1px solid #e2e8f0;
      padding: 10px 12px;
    }}
    .panel-section-title {{
      font-size: 10px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: .07em;
      color: #94a3b8;
      margin-bottom: 7px;
    }}
    .panel-stat {{
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      margin-bottom: 3px;
      color: #334155;
    }}
    .panel-stat-val {{
      font-weight: 700;
      color: #1e293b;
      font-size: 14px;
    }}

    /* Loop list items */
    .panel-loop-item {{
      padding: 6px 8px;
      border-radius: 5px;
      margin-bottom: 4px;
      cursor: pointer;
      border: 1px solid transparent;
      transition: background .12s;
    }}
    .panel-loop-item:hover {{ background: #e8edf5; }}
    .panel-loop-item.active {{ background: #eff6ff; border-color: #bfdbfe; }}
    .panel-loop-id {{ font-weight: 700; font-size: 11px; }}
    .panel-loop-name {{ color: #374151; font-size: 11px; margin-left: 4px; }}
    .panel-loop-sub {{ color: #94a3b8; font-size: 10px; margin-top: 2px; }}

    /* Loop detail view */
    .panel-detail-header {{
      padding: 10px 12px 6px;
      border-bottom: 1px solid #e2e8f0;
      flex-shrink: 0;
    }}
    .panel-detail-id {{ font-size: 18px; font-weight: 900; color: #1e293b; }}
    .panel-detail-name {{ font-size: 12px; color: #475569; margin-top: 2px; }}
    .panel-detail-type {{
      display: inline-block;
      margin-top: 5px;
      padding: 2px 8px;
      border-radius: 10px;
      font-size: 10px;
      font-weight: 700;
    }}
    .type-reinforcing {{ background: #dbeafe; color: #1d4ed8; }}
    .type-balancing   {{ background: #ede9fe; color: #6d28d9; }}
    .panel-field {{ margin-bottom: 10px; }}
    .panel-field-label {{
      font-size: 10px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: .07em;
      color: #94a3b8;
      margin-bottom: 3px;
    }}
    .panel-field-value {{ color: #1e293b; line-height: 1.5; }}
    .panel-var-chain {{
      display: flex;
      flex-wrap: wrap;
      gap: 3px;
      align-items: center;
    }}
    .panel-var-chip {{
      background: #f1f5f9;
      border: 1px solid #cbd5e1;
      border-radius: 4px;
      padding: 2px 6px;
      font-size: 10px;
      color: #334155;
    }}
    .panel-var-arrow {{ color: #94a3b8; font-size: 10px; }}
    .panel-back {{
      background: none;
      border: none;
      color: #3b82f6;
      font-size: 11px;
      cursor: pointer;
      padding: 8px 12px 4px;
      text-align: left;
      display: block;
    }}
    .panel-back:hover {{ text-decoration: underline; }}

    /* Glossary items */
    .panel-glossary-item {{
      padding: 5px 8px;
      border-radius: 4px;
      margin-bottom: 3px;
      cursor: pointer;
      border: 1px solid transparent;
      transition: background .1s;
    }}
    .panel-glossary-item:hover {{ background: #eff6ff; border-color: #bfdbfe; }}
    .panel-glossary-def {{
      font-size: 10px;
      color: #64748b;
      margin-top: 2px;
      line-height: 1.4;
    }}
    .glossary-toggle-btn {{
      display: block;
      width: 100%;
      margin-top: 4px;
      padding: 5px 8px;
      background: #f1f5f9;
      border: 1px dashed #cbd5e1;
      border-radius: 4px;
      color: #3b82f6;
      font-size: 11px;
      font-weight: 600;
      cursor: pointer;
      text-align: center;
    }}
    .glossary-toggle-btn:hover {{ background: #e0e7ff; border-color: #93c5fd; }}

    /* Mechanism items */
    .panel-mech-item {{
      padding: 5px 8px;
      border-left: 3px solid #e2e8f0;
      margin-bottom: 6px;
      border-radius: 0 4px 4px 0;
    }}
    .panel-mech-item:hover {{ border-left-color: #94a3b8; background: #f8fafc; }}

    /* Evidence cards */
    .panel-evidence-card {{
      padding: 7px 9px;
      background: #fff;
      border: 1px solid #e2e8f0;
      border-left: 3px solid #16a34a;
      border-radius: 5px;
      margin-bottom: 6px;
    }}
    .panel-evidence-card.no-date {{ border-left-color: #f59e0b; }}
    .panel-evidence-source {{ font-weight: 700; font-size: 11px; color: #1e293b; }}
    .panel-evidence-date {{ font-size: 10px; color: #94a3b8; margin-bottom: 3px; }}
    .panel-evidence-finding {{ font-size: 11px; color: #374151; line-height: 1.45; }}

    /* ── Hover tooltip popup ───────────────────────────────────────────── */
    #cld-tooltip {{
      position: fixed;
      pointer-events: none;
      z-index: 1000;
      background: #fff;
      border: 1px solid #d1d5db;
      border-radius: 8px;
      box-shadow: 0 4px 18px rgba(0,0,0,.13);
      padding: 10px 14px;
      max-width: 360px;
      font-size: 12px;
      line-height: 1.55;
      font-family: system-ui, -apple-system, sans-serif;
      display: none;
    }}
    #cld-tooltip.tip-visible {{ display: block; }}
    .tip-header {{ font-weight: 700; font-size: 13px; margin-bottom: 5px; color: #111; }}
    .tip-divider {{ border: none; border-top: 1px solid #e5e7eb; margin: 6px 0; }}
    .tip-row {{ display: flex; gap: 8px; margin-bottom: 3px; align-items: baseline; }}
    .tip-label {{ color: #6b7280; font-size: 11px; flex: 0 0 72px; }}
    .tip-value {{ color: #1f2937; }}
    .tip-pol-pos {{ color: #16a34a; font-weight: 700; }}
    .tip-pol-neg {{ color: #dc2626; font-weight: 700; }}
    .tip-pol-unk {{ color: #6b7280; font-weight: 700; }}
    .tip-evidence {{
      margin-top: 7px; padding: 5px 8px;
      background: #f0fdf4; border-left: 3px solid #16a34a;
      border-radius: 4px; font-size: 11px; color: #15803d; word-break: break-word;
    }}
    .tip-evidence-missing {{
      margin-top: 7px; padding: 5px 8px;
      background: #fefce8; border-left: 3px solid #ca8a04;
      border-radius: 4px; font-size: 11px; color: #92400e;
    }}
    .tip-inferred {{ margin-top: 5px; color: #9ca3af; font-size: 10px; }}
    .tip-loops {{ margin-top: 5px; display: flex; flex-wrap: wrap; gap: 4px; }}
    .tip-loop-badge {{
      background: #eff6ff; color: #1d4ed8;
      border: 1px solid #bfdbfe; border-radius: 3px;
      padding: 1px 5px; font-size: 10px; font-weight: 700;
    }}

    /* ── Dark mode ─────────────────────────────────────────────────────── */
    body.dark {{ background: #0f172a; color: #e2e8f0; }}
    body.dark .toolbar {{ background: rgba(12,20,38,0.97); border-color: #1e3358; box-shadow: 0 1px 6px rgba(0,0,0,.5); }}
    body.dark .toolbar-row1 {{ color: #94a3b8; }}
    body.dark .toolbar-row1 strong {{ color: #e2e8f0; }}
    body.dark .brand-sub {{ color: #3d5a7a; }}
    body.dark .brand-divider {{ background: #1e3358; }}
    body.dark .legend {{ color: #475569; }}
    body.dark .swatch.solid  {{ background: #6699ff; }}
    body.dark .swatch.dashed {{ background: repeating-linear-gradient(90deg,#6699ff 0 5px,transparent 5px 10px); }}
    body.dark .map-edge.flowing path {{
      filter: drop-shadow(0 0 10px rgba(102,153,255,0.9)) !important;
    }}
    @keyframes edge-pulse-dark {{
      0%, 100% {{ filter: none; }}
      50%       {{ filter: drop-shadow(0 0 6px rgba(102,153,255,0.3)); }}
    }}
    body.dark .map-edge.explicit:not(:hover) path {{
      animation-name: edge-pulse-dark;
    }}
    @keyframes node-breathe-dark {{
      0%, 100% {{ filter: brightness(1); }}
      50%       {{ filter: brightness(0.8) drop-shadow(0 0 12px rgba(80,130,255,0.35)); }}
    }}
    body.dark .map-node:not(:hover):not(.bouncing) rect {{
      animation-name: node-breathe-dark;
    }}
    body.dark .loop-bar {{ border-color: #1e3358; }}
    body.dark .loop-bar-label {{ color: #3d5a7a; }}
    body.dark .loop-info-bar {{ color: #64748b; }}
    body.dark button {{ background: #1a2640; border-color: #2a3f60; color: #cbd5e1; }}
    body.dark button:hover {{ background: #1e2e50; border-color: #3b5280; }}
    body.dark .loop-short-name {{ color: #475569; }}
    body.dark .loop-btn.active .loop-short-name {{ color: rgba(255,255,255,.8); }}
    body.dark .canvas {{ background: #0d1424; }}
    body.dark svg {{ background: #0d1424; }}
    body.dark #info-panel {{ background: #0c1627; border-color: #1a2f4e; }}
    body.dark .panel-header {{ background: #060e1c; }}
    body.dark .panel-section {{ border-color: #1a2f4e; }}
    body.dark .panel-section-title {{ color: #4a7fa8; }}
    body.dark .panel-stat {{ color: #94a3b8; }}
    body.dark .panel-stat-val {{ color: #e2e8f0; }}
    body.dark .panel-loop-item:hover {{ background: #152238; }}
    body.dark .panel-loop-item.active {{ background: #122040; border-color: #1a3870; }}
    body.dark .panel-loop-name {{ color: #c8d8f0; }}
    body.dark .panel-loop-sub {{ color: #64748b; }}
    body.dark .panel-detail-name {{ color: #94a3b8; }}
    body.dark .panel-field-label {{ color: #4a7fa8; }}
    body.dark .panel-field-value {{ color: #dde6f0; }}
    body.dark .panel-var-chip {{ background: #1a2640; border-color: #2a3f60; color: #64748b; }}
    body.dark .panel-var-arrow {{ color: #2a3f60; }}
    body.dark .panel-back {{ background: none; border: none; color: #60a5fa; }}
    body.dark .panel-back:hover {{ color: #93c5fd; text-decoration: underline; }}
    body.dark .panel-evidence-card {{ background: #0c1627; border-color: #1a2f4e; border-left-color: #dc2626; }}
    body.dark .panel-evidence-card.no-date {{ border-left-color: #d97706; }}
    body.dark .panel-evidence-source {{ color: #e2e8f0; }}
    body.dark .panel-evidence-date {{ color: #64748b; }}
    body.dark .panel-evidence-finding {{ color: #94a3b8; }}
    body.dark #cld-tooltip {{ background: #1a2640; border-color: #2a3f60; color: #cbd5e1; }}
    body.dark .tip-header {{ color: #e2e8f0; }}
    body.dark .tip-label {{ color: #475569; }}
    body.dark .tip-value {{ color: #e2e8f0; }}
    body.dark .tip-divider {{ border-color: #1e3358; }}
    body.dark .tip-pol-pos {{ color: #4ade80; }}
    body.dark .tip-pol-neg {{ color: #f87171; }}
    body.dark .tip-pol-unk {{ color: #475569; }}
    body.dark .tip-evidence {{ background: #071a10; border-left-color: #16a34a; color: #4ade80; }}
    body.dark .tip-evidence-missing {{ background: #1a0f00; border-left-color: #b45309; color: #fbbf24; }}
    body.dark .tip-inferred {{ color: #2e4d6e; }}
    body.dark .tip-loop-badge {{ background: #122040; color: #60a5fa; border-color: #1a3870; }}
    body.dark .panel-glossary-item:hover {{ background: #152238; border-color: #1a3870; }}
    body.dark .panel-glossary-def {{ color: #64748b; }}
    body.dark .panel-mech-item {{ border-left-color: #1a2f4e; }}
    body.dark .panel-mech-item:hover {{ background: #0c1a2e; border-left-color: #2a3f60; }}
    body.dark .glossary-toggle-btn {{ background: #0c1627; border-color: #1a2f4e; color: #60a5fa; }}
    body.dark .glossary-toggle-btn:hover {{ background: #152238; border-color: #1a3870; }}
    body.dark #panel-toggle {{ background: #1a2640; border-color: #2a3f60; color: #475569; }}
    /* SVG dark overrides (CSS beats SVG presentation attributes) */
    body.dark .map-variable-label  {{ fill: #b8cce8; }}
    body.dark .map-constant-label  {{ fill: #9ca3af; }}
    body.dark .exo-node rect       {{ fill: #1e3a5f; stroke: #60a5fa; }}
    body.dark .map-polarity {{ fill: #6699ff; }}
    body.dark .map-edge path {{ stroke: #6699ff; }}
    body.dark #map-arrow path,
    body.dark #map-arrow-inferred path {{ fill: #6699ff; }}
    body.dark #map-arrow-lit path {{ fill: #aabbff; }}
    body.dark .map-node.loop-lit text {{ fill: #ffffff; font-weight: 900; }}

    /* Text utility classes — CSS handles dark/light switch automatically */
    .tp  {{ color: #1e293b; }}                /* primary text   */
    .ts  {{ color: #475569; }}                /* secondary text */
    .tm  {{ color: #94a3b8; }}                /* muted text     */
    body.dark .tp {{ color: #dde6f0; }}
    body.dark .ts {{ color: #94a3b8; }}
    body.dark .tm {{ color: #64748b; }}
  </style>
</head>
<body>
  <div class="toolbar">
    <div class="toolbar-row1">
      <div class="brand">
        <div class="brand-mark">&#8635;</div>
        <div class="brand-text">
          <span class="brand-wordmark">LoopMap</span>
          <span class="brand-sub">Causal Intelligence</span>
        </div>
      </div>
      <div class="brand-divider"></div>
      <div class="legend">
        <span><span class="swatch solid"></span> explicit rel. ({explicit_count})</span>
        <span><span class="swatch dashed"></span> loop-inferred ({inferred_count})</span>
        <span><span style="color:#dc2626;font-size:14px;line-height:1">&#9632;</span>&thinsp;variable with relationship page</span>
        <span><span style="color:#1d4ed8;font-weight:700">↺</span> reinforcing</span>
        <span><span style="color:#7c3aed;font-weight:700">⇌</span> balancing</span>
      </div>
      <button id="btn-inferred" onclick="toggleInferred()">Hide inferred edges</button>
      <button id="btn-clear"    onclick="clearHighlight()">Clear highlight</button>
      <button id="btn-report"   onclick="openReport()">&#128196; Report</button>
      <button id="btn-dark"     onclick="toggleDark()">&#9728; Light mode</button>
      <div class="zoom-controls">
        <button onclick="zoomIn()"    title="Zoom in (scroll up)">+</button>
        <button onclick="zoomOut()"   title="Zoom out (scroll down)">−</button>
        <span id="zoom-level">100%</span>
        <button onclick="resetZoom()" title="Fit diagram to screen">Fit</button>
      </div>
    </div>
    <div class="loop-bar">
      <span class="loop-bar-label">Highlight loop →</span>
      {loop_buttons_html}
    </div>
    <div class="loop-info-bar" id="loop-info">
      Click a loop button above to trace its path on the diagram.
    </div>
  </div>

  <div id="cld-tooltip"></div>
  <div class="edit-mode-banner" id="edit-banner"></div>

  <!-- ── New Variable dialog ───────────────────────────────────────── -->
  <div id="dlg-variable" class="edit-dlg-overlay" onclick="if(event.target===this)closeVarDlg()">
    <div class="edit-dlg">
      <div class="edit-dlg-head">+ New Variable</div>
      <div class="edit-dlg-body">
        <label>Variable name *</label>
        <input id="dlg-var-name" type="text" placeholder="e.g. Oil Price" />
        <label>Type</label>
        <select id="dlg-var-type">
          <option value="stock">Stock (red box — accumulates)</option>
          <option value="flow">Flow / Rate (orange — rate of change)</option>
          <option value="auxiliary" selected>Auxiliary (plain text — connector)</option>
          <option value="constant">Constant (gray italic — fixed parameter)</option>
          <option value="exogenous">Exogenous (dashed box — external driver)</option>
        </select>
        <label>Unit</label>
        <input id="dlg-var-unit" type="text" placeholder="e.g. USD/barrel (optional)" />
        <label>Definition</label>
        <textarea id="dlg-var-def" placeholder="What does this variable measure?"></textarea>
      </div>
      <div class="edit-dlg-foot">
        <button onclick="closeVarDlg()">Cancel</button>
        <button class="primary" onclick="submitVariable()">Create variable</button>
      </div>
    </div>
  </div>

  <!-- ── New Relationship dialog ───────────────────────────────────── -->
  <div id="dlg-rel" class="edit-dlg-overlay" onclick="if(event.target===this)closeRelDlg()">
    <div class="edit-dlg">
      <div class="edit-dlg-head">+ New Relationship</div>
      <div class="edit-dlg-body">
        <label>From &#8594; To</label>
        <input id="dlg-rel-pair" type="text" readonly />
        <label>Polarity</label>
        <select id="dlg-rel-polarity">
          <option value="positive">Positive (+) &mdash; same direction</option>
          <option value="negative">Negative (&minus;) &mdash; opposite direction</option>
        </select>
        <label>Mechanism &mdash; why does A affect B? *</label>
        <textarea id="dlg-rel-mech" placeholder="Explain the causal pathway..."></textarea>
        <label>Confidence</label>
        <select id="dlg-rel-conf">
          <option value="Low">Low</option>
          <option value="Medium">Medium</option>
          <option value="High">High</option>
        </select>
      </div>
      <div class="edit-dlg-foot">
        <button onclick="closeRelDlg()">Cancel</button>
        <button class="primary" onclick="submitRelationship()">Create relationship</button>
      </div>
    </div>
  </div>

  <!-- ── Report modal ──────────────────────────────────────────────── -->
  <div id="report-modal" onclick="if(event.target===this)closeReport()">
    <div id="report-box">
      <div id="report-header">
        <div>
          <h2>&#128196; Causal Intelligence Report</h2>
          <span id="report-subtitle"></span>
        </div>
        <div class="report-actions">
          <button onclick="copyReport()" id="btn-copy-report">&#128203; Copy</button>
          <button onclick="exportPDF()">&#128196; Export PDF</button>
          <button id="report-close" onclick="closeReport()">&#10005;</button>
        </div>
      </div>
      <div id="report-content"></div>
    </div>
  </div>

  <div class="main-area">

    <!-- ── Left info panel ─────────────────────────────────────────── -->
    <div id="info-panel">
      <div class="panel-inner">
        <div class="panel-header">&#128270; Research Intelligence</div>
        <div class="panel-body" id="panel-body">
          <!-- populated by JS -->
        </div>
      </div>
      <button id="panel-toggle" onclick="togglePanel()" title="Toggle research panel">&#9664;</button>
    </div>

    <!-- ── Canvas wrapper ──────────────────────────────────────────── -->
    <div class="canvas-wrap">
      <div class="edit-tools-overlay">
        <span class="edit-tools-label">Edit Tools</span>
        <button id="btn-add-var" onclick="openAddVarDlg()" title="Add new variable">&#43;</button>
        <button id="btn-relate"  onclick="toggleRelateMode()" title="Relate two nodes">&#8596;</button>
        <button id="btn-delete"  onclick="toggleDeleteMode()" title="Delete node">&#10005;</button>
      </div>
      <div class="canvas" id="canvas">
        <svg id="main-svg" role="img" aria-label="Causal loop system map">
          <defs>
            <marker id="map-arrow" markerWidth="16" markerHeight="16" refX="14" refY="8" orient="auto">
              <path d="M2,2 L14,8 L2,14 Z" fill="#0000cc"></path>
            </marker>
            <marker id="map-arrow-inferred" markerWidth="14" markerHeight="14" refX="12" refY="7" orient="auto">
              <path d="M2,2 L12,7 L2,12 Z" fill="#0000cc"></path>
            </marker>
            <marker id="map-arrow-lit" markerWidth="18" markerHeight="18" refX="16" refY="9" orient="auto">
              <path d="M2,2 L16,9 L2,16 Z" fill="#0000ee"></path>
            </marker>
          </defs>
          <g id="zoom-layer">
            {inferred_svg}
            {explicit_svg}
            {node_svg}
          </g>
        </svg>
      </div>
    </div>

    <!-- ── Right evidence panel ─────────────────────────────────────── -->
    <div id="evidence-panel">
      <button id="panel-toggle-right" onclick="toggleEvidencePanel()" title="Toggle evidence panel">&#9654;</button>
      <div class="panel-header">&#128196; Evidence Sources</div>
      <div class="panel-body" id="evidence-body">
        <!-- populated by JS -->
      </div>
    </div>

  </div>

  <script>
    const LOOP_DATA     = {loop_js_data};
    const EVIDENCE_DATA = {evidence_js_data};
    const PROJECT_NAME  = {json.dumps(project_name)};
    const NODE_COUNT    = {len(nodes)};
    const EXPLICIT_COUNT = {explicit_count};
    const LOOP_COUNT    = {len(loop_records)};
    const VARIABLE_DATA      = {variable_js_data};
    const MECHANISM_DATA     = {mechanism_js_data};
    const NODE_POSITIONS_DATA = {node_positions_js};
    const EDGE_RAW_DATA       = {edge_raw_js_data};
    let activeLoop = null;
    let inferredShowing = true;

    /* ── Node drag: live position map + edge recalculator ──────────────── */
    var nodePosMap = {{}};
    Object.keys(NODE_POSITIONS_DATA).forEach(function(slug) {{
      var d = NODE_POSITIONS_DATA[slug];
      nodePosMap[slug] = {{x: d.x, y: d.y, isStock: d.isStock}};
    }});

    function edgeClearance(slug) {{
      return (nodePosMap[slug] && nodePosMap[slug].isStock) ? 90 : 28;
    }}
    function calcEdgePath(ed) {{
      var p1 = nodePosMap[ed.src], p2 = nodePosMap[ed.tgt];
      if (!p1 || !p2) return null;
      var dx = p2.x - p1.x, dy = p2.y - p1.y;
      var dist = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
      var nx = dx / dist, ny = dy / dist;
      var sx = p1.x + nx * edgeClearance(ed.src), sy = p1.y + ny * edgeClearance(ed.src);
      var ex = p2.x - nx * edgeClearance(ed.tgt), ey = p2.y - ny * edgeClearance(ed.tgt);
      var curve = (0.10 + 0.04 * (ed.curveIdx % 4)) * (ed.curveIdx % 2 === 0 ? 1 : -1);
      var cx = (sx + ex) / 2 - dy * curve, cy = (sy + ey) / 2 + dx * curve;
      var lx = (sx + cx + ex) / 3,         ly = (sy + cy + ey) / 3;
      return {{sx:sx, sy:sy, cx:cx, cy:cy, ex:ex, ey:ey, lx:lx, ly:ly}};
    }}
    function redrawEdgesForNode(slug) {{
      EDGE_RAW_DATA.forEach(function(ed) {{
        if (ed.src !== slug && ed.tgt !== slug) return;
        var pt = calcEdgePath(ed);
        if (!pt) return;
        var edgeEl = document.getElementById(ed.id);
        if (!edgeEl) return;
        var path = edgeEl.querySelector('path');
        var txt  = edgeEl.querySelector('.map-polarity');
        if (path) path.setAttribute('d',
          'M' + pt.sx.toFixed(1) + ',' + pt.sy.toFixed(1) +
          ' Q' + pt.cx.toFixed(1) + ',' + pt.cy.toFixed(1) +
          ' ' + pt.ex.toFixed(1) + ',' + pt.ey.toFixed(1));
        if (txt) {{
          txt.setAttribute('x', pt.lx.toFixed(1));
          txt.setAttribute('y', pt.ly.toFixed(1));
        }}
      }});
    }}

    var ndDragging = false, ndEl = null, ndSlug = '', ndMoved = false;
    var ndSvgX0 = 0, ndSvgY0 = 0, ndBx = 0, ndBy = 0;
    let panelCollapsed = false;
    let evidencePanelCollapsed = false;
    let darkMode = true;

    /* ── Dark mode ──────────────────────────────────────────────────── */
    function toggleDark() {{
      darkMode = !darkMode;
      document.body.classList.toggle('dark', darkMode);
      document.getElementById('btn-dark').innerHTML = darkMode ? '&#9728; Light mode' : '&#9790; Dark mode';
      showOverview();
    }}
    /* default: dark */
    document.body.classList.add('dark');

    /* ── Left panel toggle ──────────────────────────────────────────── */
    function togglePanel() {{
      panelCollapsed = !panelCollapsed;
      document.getElementById('info-panel').classList.toggle('collapsed', panelCollapsed);
      document.getElementById('panel-toggle').innerHTML = panelCollapsed ? '&#9654;' : '&#9664;';
    }}

    /* ── Right evidence panel ───────────────────────────────────────── */
    function toggleEvidencePanel() {{
      evidencePanelCollapsed = !evidencePanelCollapsed;
      document.getElementById('evidence-panel').classList.toggle('collapsed', evidencePanelCollapsed);
      document.getElementById('panel-toggle-right').innerHTML = evidencePanelCollapsed ? '&#9654;' : '&#9664;';
    }}

    function showEvidence(filterLoopId) {{
      var body = document.getElementById('evidence-body');
      if (!body) return;
      body.innerHTML = renderEvidence(filterLoopId || null);
    }}

    /* ── Panel rendering helpers ────────────────────────────────────── */
    function esc(s) {{ return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }}

    function renderOverview() {{
      var evCount = EVIDENCE_DATA.length;
      var html = '<div class="panel-section">'
        + '<div class="panel-section-title">System Overview</div>'
        + '<div class="panel-stat tp" style="font-weight:600">' + esc(PROJECT_NAME) + '</div>'
        + '<div style="height:6px"></div>'
        + stat('Variables', NODE_COUNT)
        + stat('Explicit relationships', EXPLICIT_COUNT)
        + stat('Feedback loops', LOOP_COUNT)
        + stat('Evidence sources', evCount)
        + '</div>';
      return html;
    }}

    function stat(label, val) {{
      return '<div class="panel-stat"><span>' + label + '</span><span class="panel-stat-val">' + val + '</span></div>';
    }}

    var LOOP_LIST_LIMIT = 4;

    function loopListItem(loop) {{
      var isR = loop.is_reinforcing;
      var icon = isR ? '&#8635;' : '&#8652;';
      var color = isR ? '#1d4ed8' : '#7c3aed';
      return '<div class="panel-loop-item" data-lid="' + esc(loop.id) + '" onclick="selectLoopFromPanel(this.dataset.lid)">'
        + '<span class="panel-loop-id" style="color:' + color + '">' + icon + ' ' + esc(loop.id) + '</span>'
        + '<span class="panel-loop-name">' + esc(loop.short_name) + '</span>'
        + (loop.narrative ? '<div class="panel-loop-sub">' + esc(loop.narrative.substring(0,80)) + (loop.narrative.length > 80 ? '&hellip;' : '') + '</div>' : '')
        + '</div>';
    }}

    function renderLoopList() {{
      var loops = Object.values(LOOP_DATA);
      var total = loops.length;
      var visible = loops.slice(0, LOOP_LIST_LIMIT);
      var hidden  = loops.slice(LOOP_LIST_LIMIT);
      var html = '<div class="panel-section"><div class="panel-section-title">Feedback Loops (' + total + ')</div>';
      visible.forEach(function(loop) {{ html += loopListItem(loop); }});
      if (hidden.length) {{
        html += '<div id="loop-list-overflow" style="display:none">';
        hidden.forEach(function(loop) {{ html += loopListItem(loop); }});
        html += '</div>'
          + '<button class="glossary-toggle-btn" id="loop-list-toggle-btn" onclick="toggleLoopList()">'
          + '&#8964; Show ' + hidden.length + ' more</button>';
      }}
      html += '</div>';
      return html;
    }}

    function toggleLoopList() {{
      var overflow = document.getElementById('loop-list-overflow');
      var btn      = document.getElementById('loop-list-toggle-btn');
      if (!overflow || !btn) return;
      var expanding = overflow.style.display === 'none';
      overflow.style.display = expanding ? '' : 'none';
      var hidden = Object.values(LOOP_DATA).length - LOOP_LIST_LIMIT;
      btn.innerHTML = expanding ? '&#8963; Show less' : '&#8964; Show ' + hidden + ' more';
    }}

    function renderEvidence(filterLoopId) {{
      if (!EVIDENCE_DATA.length) return '';
      var items = EVIDENCE_DATA;
      if (filterLoopId) {{
        items = EVIDENCE_DATA.filter(function(e) {{
          return !e.supports_loops || e.supports_loops === ''
            || e.supports_loops.toUpperCase().indexOf(filterLoopId.toUpperCase()) !== -1;
        }});
        if (!items.length) items = EVIDENCE_DATA;
      }}
      var html = '<div class="panel-section"><div class="panel-section-title">Evidence Sources'
        + (filterLoopId ? ' &middot; ' + esc(filterLoopId) : '') + '</div>';
      items.slice(0, 12).forEach(function(e) {{
        var noDate = !e.release_date || e.release_date.toLowerCase().indexOf('unknown') !== -1;
        html += '<div class="panel-evidence-card' + (noDate ? ' no-date' : '') + '">'
          + '<div class="panel-evidence-source">&#128196; ' + esc(e.source || e.title) + '</div>'
          + '<div class="panel-evidence-date">' + (noDate ? '&#9888; date unknown' : esc(e.release_date)) + (e.evidence_type ? ' &middot; ' + esc(e.evidence_type) : '') + '</div>'
          + (e.finding ? '<div class="panel-evidence-finding">' + esc(e.finding) + '</div>' : '')
          + '</div>';
      }});
      html += '</div>';
      return html;
    }}

    function renderLoopDetail(loopId) {{
      var loop = LOOP_DATA[loopId];
      if (!loop) return '';
      var isR = loop.is_reinforcing;
      var color = isR ? '#1d4ed8' : '#7c3aed';
      var typeLabel = isR ? '&#8635; Reinforcing' : '&#8652; Balancing';
      var typeClass = isR ? 'type-reinforcing' : 'type-balancing';

      var html = '<button class="panel-back" onclick="showOverview()">&#8592; All loops</button>'
        + '<div class="panel-detail-header">'
        + '<div class="panel-detail-id" style="color:' + color + '">' + esc(loop.id) + '</div>'
        + '<div class="panel-detail-name">' + esc(loop.short_name) + '</div>'
        + '<span class="panel-detail-type ' + typeClass + '">' + typeLabel + '</span>'
        + '</div>'
        + '<div class="panel-section">';

      if (loop.narrative) {{
        html += field('Narrative', loop.narrative);
      }}

      if (loop.variables_list && loop.variables_list.length) {{
        var chain = '<div class="panel-var-chain">';
        var unique = [];
        loop.variables_list.forEach(function(v) {{
          if (!unique.length || unique[unique.length-1] !== v) unique.push(v);
        }});
        unique.forEach(function(v, i) {{
          if (i > 0) chain += '<span class="panel-var-arrow">&#8594;</span>';
          chain += '<span class="panel-var-chip">' + esc(v) + '</span>';
        }});
        chain += '<span class="panel-var-arrow">&#8635;</span></div>';
        html += '<div class="panel-field"><div class="panel-field-label">Variable Chain</div>' + chain + '</div>';
      }}

      if (loop.dominant_period) html += field('Dominant Period', loop.dominant_period);
      if (loop.delay_points)    html += field('Delay Points', loop.delay_points);
      if (loop.leverage_points) html += field('Leverage Points', loop.leverage_points);
      if (loop.collapse_conditions) html += field('Collapse Conditions', loop.collapse_conditions);

      html += '</div>';
      return html;
    }}

    function field(label, value) {{
      if (!value) return '';
      return '<div class="panel-field">'
        + '<div class="panel-field-label">' + label + '</div>'
        + '<div class="panel-field-value">' + esc(value) + '</div>'
        + '</div>';
    }}

    /* ── Variable type badge ────────────────────────────────────────────── */
    var VAR_TYPE_CFG = {{
      stock:     {{ light: '#b91c1c', dark: '#fca5a5' }},
      flow:      {{ light: '#1d4ed8', dark: '#93c5fd' }},
      rate:      {{ light: '#1d4ed8', dark: '#93c5fd' }},
      auxiliary: {{ light: '#15803d', dark: '#86efac' }},
    }};
    function varTypeBadge(vtype) {{
      if (!vtype) return '';
      var cfg = VAR_TYPE_CFG[vtype.toLowerCase()];
      var color = cfg ? (darkMode ? cfg.dark : cfg.light) : (darkMode ? '#94a3b8' : '#6b7280');
      return '<span style="font-size:9px;font-weight:700;color:' + color
        + ';margin-left:5px;vertical-align:middle;letter-spacing:.02em">' + esc(vtype) + '</span>';
    }}

    /* ── Glossary (all variable files) ─────────────────────────────────── */
    var GLOSSARY_LIMIT = 5;

    function glossaryItem(v) {{
      return '<div class="panel-glossary-item" data-varlabel="' + esc(v.label) + '">'
        + '<div class="tp" style="font-weight:600;font-size:11px;margin-bottom:1px">'
        + esc(v.label) + varTypeBadge(v.variable_type) + '</div>'
        + (v.definition
          ? '<div class="panel-glossary-def">' + esc(v.definition.substring(0,90))
            + (v.definition.length > 90 ? '&hellip;' : '') + '</div>'
          : '')
        + '</div>';
    }}

    function renderGlossary() {{
      if (!VARIABLE_DATA || !VARIABLE_DATA.length) return '';
      var total = VARIABLE_DATA.length;
      var visible = VARIABLE_DATA.slice(0, GLOSSARY_LIMIT);
      var hidden  = VARIABLE_DATA.slice(GLOSSARY_LIMIT);
      var html = '<div class="panel-section" id="glossary-section">'
        + '<div class="panel-section-title">Component Glossary (' + total + ')</div>';
      visible.forEach(function(v) {{ html += glossaryItem(v); }});
      if (hidden.length) {{
        html += '<div id="glossary-overflow" style="display:none">';
        hidden.forEach(function(v) {{ html += glossaryItem(v); }});
        html += '</div>'
          + '<button class="glossary-toggle-btn" id="glossary-toggle-btn"'
          + ' onclick="toggleGlossary()">'
          + '&#8964; Show ' + hidden.length + ' more</button>';
      }}
      html += '</div>';
      return html;
    }}

    function toggleGlossary() {{
      var overflow = document.getElementById('glossary-overflow');
      var btn      = document.getElementById('glossary-toggle-btn');
      if (!overflow || !btn) return;
      var expanding = overflow.style.display === 'none';
      overflow.style.display = expanding ? '' : 'none';
      var hidden = VARIABLE_DATA.length - GLOSSARY_LIMIT;
      btn.innerHTML = expanding
        ? '&#8963; Show less'
        : '&#8964; Show ' + hidden + ' more';
      if (expanding) {{
        /* attach click handlers to newly revealed items */
        overflow.querySelectorAll('.panel-glossary-item').forEach(function(el) {{
          el.addEventListener('click', function() {{ showVariableDetail(el.dataset.varlabel); }});
        }});
      }}
    }}

    /* ── Mechanisms ─────────────────────────────────────────────────────── */
    var MECH_LIMIT = 4;

    function mechItem(m) {{
      return '<div class="panel-mech-item">'
        + '<div class="tp" style="font-weight:600;font-size:11px">' + esc(m.label) + '</div>'
        + (m.relationship
          ? '<div class="tm" style="font-size:10px;margin-top:1px">' + esc(m.relationship) + '</div>'
          : '')
        + (m.explanation
          ? '<div class="ts" style="font-size:10px;margin-top:3px;line-height:1.4">'
            + esc(m.explanation.substring(0,110))
            + (m.explanation.length > 110 ? '&hellip;' : '') + '</div>'
          : '')
        + '</div>';
    }}

    function renderMechanisms() {{
      if (!MECHANISM_DATA || !MECHANISM_DATA.length) return '';
      var total   = MECHANISM_DATA.length;
      var visible = MECHANISM_DATA.slice(0, MECH_LIMIT);
      var hidden  = MECHANISM_DATA.slice(MECH_LIMIT);
      var html = '<div class="panel-section">'
        + '<div class="panel-section-title">Causal Mechanisms (' + total + ')</div>';
      visible.forEach(function(m) {{ html += mechItem(m); }});
      if (hidden.length) {{
        html += '<div id="mech-overflow" style="display:none">';
        hidden.forEach(function(m) {{ html += mechItem(m); }});
        html += '</div>'
          + '<button class="glossary-toggle-btn" id="mech-toggle-btn" onclick="toggleMechanisms()">'
          + '&#8964; Show ' + hidden.length + ' more</button>';
      }}
      html += '</div>';
      return html;
    }}

    function toggleMechanisms() {{
      var overflow = document.getElementById('mech-overflow');
      var btn      = document.getElementById('mech-toggle-btn');
      if (!overflow || !btn) return;
      var expanding = overflow.style.display === 'none';
      overflow.style.display = expanding ? '' : 'none';
      var hidden = MECHANISM_DATA.length - MECH_LIMIT;
      btn.innerHTML = expanding ? '&#8963; Show less' : '&#8964; Show ' + hidden + ' more';
    }}

    /* ── Variable detail view ───────────────────────────────────────────── */
    function showVariableDetail(label) {{
      var norm = String(label||'').toLowerCase().replace(/[^a-z0-9]+/g,' ').trim();
      var rec = null;
      if (VARIABLE_DATA) {{
        for (var i = 0; i < VARIABLE_DATA.length; i++) {{
          var rn = String(VARIABLE_DATA[i].label||'').toLowerCase().replace(/[^a-z0-9]+/g,' ').trim();
          if (rn === norm) {{ rec = VARIABLE_DATA[i]; break; }}
        }}
      }}
      var html = '<button class="panel-back" onclick="showOverview()">&#8592; Overview</button>';
      if (!rec) {{
        html += '<div class="panel-section">'
          + '<div class="tp" style="font-weight:700;font-size:14px;margin-bottom:8px">' + esc(label) + '</div>'
          + '<div class="tm" style="font-size:11px">No variable definition file found for this node.</div>'
          + '</div>';
        document.getElementById('panel-body').innerHTML = html;
        return;
      }}
      html += '<div class="panel-section">';
      html += '<div class="tp" style="font-weight:700;font-size:15px;margin-bottom:6px">'
        + esc(rec.label) + varTypeBadge(rec.variable_type) + '</div>';
      if (rec.unit) html += '<div class="tm" style="font-size:10px;margin-bottom:8px">Unit: ' + esc(rec.unit) + '</div>';
      if (rec.definition)    html += field('Definition', rec.definition);
      if (rec.delays)        html += field('Delays', rec.delays);
      if (rec.related_loops) html += field('Related Loops', rec.related_loops);
      if (rec.inflows)       html += field('Inflows', rec.inflows);
      if (rec.outflows)      html += field('Outflows', rec.outflows);
      html += '</div>';
      document.getElementById('panel-body').innerHTML = html;
    }}

    function showOverview() {{
      document.getElementById('panel-body').innerHTML =
        renderOverview() + renderLoopList() + renderGlossary() + renderMechanisms();
      document.querySelectorAll('.panel-loop-item').forEach(function(el) {{
        if (el.dataset.lid === activeLoop) el.classList.add('active');
      }});
      document.querySelectorAll('.panel-glossary-item').forEach(function(el) {{
        el.addEventListener('click', function() {{ showVariableDetail(el.dataset.varlabel); }});
      }});
    }}

    function showLoopDetail(loopId) {{
      document.getElementById('panel-body').innerHTML = renderLoopDetail(loopId);
    }}

    function selectLoopFromPanel(loopId) {{
      var btn = document.querySelector('.loop-btn[data-loop="' + loopId + '"]');
      if (btn) highlightLoop(loopId, btn);
      showLoopDetail(loopId);
    }}

    /* initialise panels after DOM is ready */
    window.addEventListener('load', function() {{
      showOverview();
      showEvidence(null);
    }});

    /* ── Toggle inferred edges ──────────────────────────────────────── */
    function toggleInferred() {{
      inferredShowing = !inferredShowing;
      const btn = document.getElementById('btn-inferred');
      btn.textContent = inferredShowing ? 'Hide inferred edges' : 'Show inferred edges';
      document.querySelectorAll('.map-edge.inferred').forEach(function(el) {{
        if (!activeLoop) {{
          el.style.opacity = inferredShowing ? '0.45' : '0';
        }}
      }});
    }}

    /* ── Highlight a specific loop ──────────────────────────────────── */
    function highlightLoop(loopId, btn) {{
      if (activeLoop === loopId) {{ clearHighlight(); return; }}
      clearHighlight(false);
      activeLoop = loopId;
      const loop = LOOP_DATA[loopId];

      /* Dim everything */
      document.querySelectorAll('.map-edge, .map-node').forEach(function(el) {{
        el.style.opacity = '0.05';
      }});

      /* Brighten loop edges */
      document.querySelectorAll('[data-loops]').forEach(function(el) {{
        const loops = el.getAttribute('data-loops').split(' ');
        if (loops.indexOf(loopId) !== -1) {{
          el.style.opacity = '1';
          el.classList.add('loop-lit', 'flowing');
          const p = el.querySelector('path');
          if (p) {{
            p.style.strokeWidth = '2.5';
            p.setAttribute('marker-end', 'url(#map-arrow-lit)');
          }}
        }}
      }});

      /* Brighten loop nodes */
      loop.node_slugs.forEach(function(slug) {{
        document.querySelectorAll('[data-node="' + slug + '"]').forEach(function(el) {{
          el.style.opacity = '1';
          el.classList.add('loop-lit');
        }});
      }});

      /* Button state */
      document.querySelectorAll('.loop-btn').forEach(function(b) {{
        b.classList.toggle('active', b.dataset.loop === loopId);
      }});
      document.getElementById('btn-clear').style.display = '';

      /* Info panel */
      const typeLabel = loop.is_reinforcing ? '↺ Reinforcing' : '⇌ Balancing';
      document.getElementById('loop-info').innerHTML =
        '<strong>' + loop.name + '</strong>' +
        ' &nbsp;·&nbsp; <em>' + typeLabel + '</em>' +
        (loop.narrative ? ' &nbsp;·&nbsp; ' + loop.narrative : '');
      showLoopDetail(loopId);
      showEvidence(loopId);
    }}

    /* ── Clear all highlights ───────────────────────────────────────── */
    function clearHighlight(resetButtons) {{
      if (resetButtons === undefined) resetButtons = true;
      activeLoop = null;

      document.querySelectorAll('.map-edge').forEach(function(el) {{
        const isInferred = el.classList.contains('inferred');
        el.style.opacity = isInferred ? (inferredShowing ? '0.45' : '0') : '1';
        el.classList.remove('loop-lit', 'flowing');
        const p = el.querySelector('path');
        if (p) {{
          p.style.strokeWidth = '';
          const isInferredPath = el.classList.contains('inferred');
          p.setAttribute('marker-end',
            isInferredPath ? 'url(#map-arrow-inferred)' : 'url(#map-arrow)');
        }}
      }});

      document.querySelectorAll('.map-node').forEach(function(el) {{
        el.style.opacity = '';
        el.classList.remove('loop-lit');
      }});

      if (resetButtons) {{
        document.querySelectorAll('.loop-btn').forEach(function(b) {{
          b.classList.remove('active');
        }});
        document.getElementById('btn-clear').style.display = 'none';
        document.getElementById('loop-info').textContent =
          'Click a loop button above to trace its path on the diagram.';
        showOverview();
        showEvidence(null);
      }}
    }}

    /* ── Pan / Zoom ─────────────────────────────────────────────────── */
    (function() {{
      const svg    = document.getElementById('main-svg');
      const layer  = document.getElementById('zoom-layer');
      const canvas = document.getElementById('canvas');
      const lvlEl  = document.getElementById('zoom-level');
      const DIAGRAM_W = {width};
      const DIAGRAM_H = {height};
      let tx = 0, ty = 0, scale = 1;
      let dragging = false, dragX = 0, dragY = 0, txD = 0, tyD = 0;

      function applyTransform() {{
        layer.setAttribute('transform',
          'translate(' + tx.toFixed(2) + ',' + ty.toFixed(2) + ') scale(' + scale.toFixed(4) + ')');
        lvlEl.textContent = Math.round(scale * 100) + '%';
      }}

      function clamp(v, lo, hi) {{ return Math.max(lo, Math.min(hi, v)); }}

      function zoomAt(factor, cx, cy) {{
        const s = clamp(scale * factor, 0.06, 5);
        tx = cx - (cx - tx) * (s / scale);
        ty = cy - (cy - ty) * (s / scale);
        scale = s;
        applyTransform();
      }}

      window.zoomIn = function() {{
        zoomAt(1.25, canvas.offsetWidth / 2, canvas.offsetHeight / 2);
      }};
      window.zoomOut = function() {{
        zoomAt(1 / 1.25, canvas.offsetWidth / 2, canvas.offsetHeight / 2);
      }};
      window.resetZoom = function() {{
        const sx = canvas.offsetWidth  / DIAGRAM_W;
        const sy = canvas.offsetHeight / DIAGRAM_H;
        scale = Math.min(sx, sy) * 0.92;
        tx = (canvas.offsetWidth  - DIAGRAM_W * scale) / 2;
        ty = (canvas.offsetHeight - DIAGRAM_H * scale) / 2;
        applyTransform();
      }};

      /* Mouse wheel zoom centered on cursor */
      svg.addEventListener('wheel', function(e) {{
        e.preventDefault();
        const r = svg.getBoundingClientRect();
        zoomAt(e.deltaY < 0 ? 1.12 : 1 / 1.12, e.clientX - r.left, e.clientY - r.top);
      }}, {{ passive: false }});

      /* Drag to pan */
      svg.addEventListener('mousedown', function(e) {{
        if (e.button !== 0) return;
        dragging = true;
        dragX = e.clientX; dragY = e.clientY; txD = tx; tyD = ty;
        canvas.classList.add('dragging');
      }});
      window.addEventListener('mousemove', function(e) {{
        if (ndDragging) {{
          var r = svg.getBoundingClientRect();
          var sx = (e.clientX - r.left - tx) / scale;
          var sy = (e.clientY - r.top  - ty) / scale;
          var ddx = sx - ndSvgX0, ddy = sy - ndSvgY0;
          if (!ndMoved && (Math.abs(ddx) > 3 || Math.abs(ddy) > 3)) ndMoved = true;
          if (ndMoved) {{
            nodePosMap[ndSlug].x = ndBx + ddx;
            nodePosMap[ndSlug].y = ndBy + ddy;
            var orig = NODE_POSITIONS_DATA[ndSlug];
            ndEl.setAttribute('transform',
              'translate(' + (nodePosMap[ndSlug].x - orig.x).toFixed(2) +
              ',' + (nodePosMap[ndSlug].y - orig.y).toFixed(2) + ')');
            redrawEdgesForNode(ndSlug);
          }}
          return;
        }}
        if (!dragging) return;
        tx = txD + (e.clientX - dragX);
        ty = tyD + (e.clientY - dragY);
        applyTransform();
      }});
      window.addEventListener('mouseup', function() {{
        if (ndDragging) {{
          ndDragging = false;
          if (ndEl) {{ ndEl.style.cursor = ''; ndEl = null; }}
        }}
        dragging = false;
        canvas.classList.remove('dragging');
      }});

      /* Touch: single-finger pan, two-finger pinch-zoom */
      let lastDist = null, lastMid = null;
      svg.addEventListener('touchstart', function(e) {{
        e.preventDefault();
        if (e.touches.length === 1) {{
          dragging = true;
          dragX = e.touches[0].clientX; dragY = e.touches[0].clientY; txD = tx; tyD = ty;
        }} else if (e.touches.length === 2) {{
          dragging = false;
          lastDist = Math.hypot(e.touches[0].clientX - e.touches[1].clientX,
                                e.touches[0].clientY - e.touches[1].clientY);
          const r = svg.getBoundingClientRect();
          lastMid = {{
            x: (e.touches[0].clientX + e.touches[1].clientX) / 2 - r.left,
            y: (e.touches[0].clientY + e.touches[1].clientY) / 2 - r.top,
          }};
        }}
      }}, {{ passive: false }});
      svg.addEventListener('touchmove', function(e) {{
        e.preventDefault();
        if (e.touches.length === 1 && dragging) {{
          tx = txD + (e.touches[0].clientX - dragX);
          ty = tyD + (e.touches[0].clientY - dragY);
          applyTransform();
        }} else if (e.touches.length === 2 && lastDist) {{
          const d = Math.hypot(e.touches[0].clientX - e.touches[1].clientX,
                               e.touches[0].clientY - e.touches[1].clientY);
          zoomAt(d / lastDist, lastMid.x, lastMid.y);
          lastDist = d;
        }}
      }}, {{ passive: false }});
      svg.addEventListener('touchend', function() {{
        dragging = false; lastDist = null;
      }});

      /* Initial zoom: 69% centered */
      window.addEventListener('load', function() {{
        scale = 0.69;
        tx = (canvas.offsetWidth  - DIAGRAM_W * scale) / 2;
        ty = (canvas.offsetHeight - DIAGRAM_H * scale) / 2;
        applyTransform();
      }});
      window._getMapState = function() {{ return {{tx: tx, ty: ty, scale: scale}}; }};
    }})();

    /* ── Hover tooltip ──────────────────────────────────────────────── */
    (function() {{
      var tip = document.getElementById('cld-tooltip');

      function esc(s) {{
        return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
      }}

      function polClass(p) {{
        if (!p) return 'tip-pol-unk';
        var l = p.toLowerCase();
        return l === 'positive' ? 'tip-pol-pos' : l === 'negative' ? 'tip-pol-neg' : 'tip-pol-unk';
      }}

      function polLabel(p) {{
        if (!p) return '?';
        var l = p.toLowerCase();
        return l === 'positive' ? '+ Positive' : l === 'negative' ? '&minus; Negative' : '? Unknown';
      }}

      function row(label, value) {{
        if (!value || value === 'unknown' || value === '') return '';
        return '<div class="tip-row"><span class="tip-label">' + label + '</span>'
             + '<span class="tip-value">' + esc(value) + '</span></div>';
      }}

      function buildEdge(d) {{
        var h = '<div class="tip-header">' + esc(d.src) + ' &rarr; ' + esc(d.tgt) + '</div>'
              + '<hr class="tip-divider">'
              + '<div class="tip-row"><span class="tip-label">Polarity</span>'
              + '<span class="' + polClass(d.polarity) + '">' + polLabel(d.polarity) + '</span></div>'
              + row('Confidence', d.confidence)
              + row('Mechanism', d.mechanism)
              + row('Delay', d.delay);
        if (d.evidence) {{
          var missing = /none|needs sourcing/i.test(d.evidence);
          h += '<div class="' + (missing ? 'tip-evidence-missing' : 'tip-evidence') + '">'
            + (missing ? '&#9888; ' : '&#128196; ') + esc(d.evidence) + '</div>';
        }}
        if (d.inferred) {{
          h += '<div class="tip-inferred">Inferred from loop path &mdash; no explicit relationship file</div>';
        }}
        return h;
      }}

      function buildNode(d) {{
        var h = '<div class="tip-header">' + esc(d.label) + '</div>'
              + '<div style="color:#6b7280;font-size:11px;margin-bottom:3px">' + esc(d.node_type) + '</div>';
        if (d.loops && d.loops.length) {{
          h += '<hr class="tip-divider">'
            + '<div style="color:#6b7280;font-size:11px;margin-bottom:4px">Appears in loops</div>'
            + '<div class="tip-loops">';
          d.loops.forEach(function(lid) {{
            h += '<span class="tip-loop-badge">' + esc(lid) + '</span>';
          }});
          h += '</div>';
        }}
        return h;
      }}

      function place(e) {{
        var pad = 16, tw = tip.offsetWidth, th = tip.offsetHeight;
        var x = e.clientX + pad, y = e.clientY + pad;
        if (x + tw > window.innerWidth  - 8) x = e.clientX - tw - pad;
        if (y + th > window.innerHeight - 8) y = e.clientY - th - pad;
        tip.style.left = x + 'px';
        tip.style.top  = y + 'px';
      }}

      document.querySelectorAll('.map-edge, .map-node').forEach(function(el) {{
        el.addEventListener('mouseenter', function(e) {{
          var raw = el.getAttribute('data-tip');
          if (!raw) return;
          var d;
          try {{ d = JSON.parse(raw); }} catch(_) {{ return; }}
          tip.innerHTML = d.kind === 'edge' ? buildEdge(d) : buildNode(d);
          tip.classList.add('tip-visible');
          place(e);
        }});
        el.addEventListener('mousemove', place);
        el.addEventListener('mouseleave', function() {{
          tip.classList.remove('tip-visible');
        }});
      }});
    }})();

    /* ── Node click + drag: mousedown starts drag; mouseup opens detail if not dragged ── */
    (function() {{
      var clickStarted = false;
      var mainSvg = document.getElementById('main-svg');
      mainSvg.addEventListener('mousedown', function() {{ clickStarted = true; }});
      mainSvg.addEventListener('mousemove', function() {{ clickStarted = false; }});
      document.querySelectorAll('.map-node').forEach(function(el) {{
        el.addEventListener('mousedown', function(e) {{
          if (e.button !== 0) return;
          var slug = el.getAttribute('data-node');
          if (!slug || !nodePosMap[slug]) return;
          e.stopPropagation();
          clickStarted = true;
          ndDragging = true; ndEl = el; ndSlug = slug; ndMoved = false;
          var r = mainSvg.getBoundingClientRect();
          ndSvgX0 = (e.clientX - r.left - tx) / scale;
          ndSvgY0 = (e.clientY - r.top  - ty) / scale;
          ndBx = nodePosMap[slug].x;
          ndBy = nodePosMap[slug].y;
          el.style.cursor = 'grabbing';
        }});
        el.addEventListener('mouseup', function() {{
          if (!clickStarted || ndMoved) {{ clickStarted = false; return; }}
          clickStarted = false;
          if (typeof activeMode !== 'undefined' && activeMode) return;
          var raw = el.getAttribute('data-tip');
          if (!raw) return;
          var d;
          try {{ d = JSON.parse(raw); }} catch(_) {{ return; }}
          el.classList.add('bouncing');
          el.addEventListener('animationend', function() {{ el.classList.remove('bouncing'); }}, {{ once: true }});
          if (panelCollapsed) togglePanel();
          showVariableDetail(d.label);
        }});
      }});
    }})();

    /* ── Report generator ───────────────────────────────────────────── */
    (function() {{
      function esc(s) {{ return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }}
      function sec(title) {{
        return '<div class="rpt-section"><div class="rpt-h2">' + title + '</div>';
      }}
      function field(label, value) {{
        if (!value) return '';
        return '<div class="rpt-field"><span class="rpt-field-label">' + label + ': </span>'
          + '<span class="rpt-field-value">' + esc(value) + '</span></div>';
      }}

      function buildReport() {{
        var loops   = Object.values(LOOP_DATA);
        var now     = new Date().toLocaleDateString('en-GB', {{day:'2-digit',month:'short',year:'numeric'}});
        var rCount  = loops.filter(function(l){{return l.is_reinforcing;}}).length;
        var bCount  = loops.length - rCount;

        /* ── Cover ── */
        var html = '<div class="rpt-section">'
          + '<div class="rpt-h1">' + esc(PROJECT_NAME) + '</div>'
          + '<div class="rpt-meta">Causal Intelligence Report &nbsp;·&nbsp; Generated ' + now + '</div>';

        /* Executive summary paragraph */
        var loopTypes = [];
        if (rCount) loopTypes.push(rCount + ' reinforcing');
        if (bCount) loopTypes.push(bCount + ' balancing');
        html += '<div class="rpt-summary-text">This report documents the causal structure of <strong>'
          + esc(PROJECT_NAME) + '</strong>, comprising <strong>' + NODE_COUNT + ' variables</strong>, '
          + '<strong>' + EXPLICIT_COUNT + ' explicit relationships</strong>, and '
          + '<strong>' + loops.length + ' feedback loops</strong> ('
          + loopTypes.join(', ') + '). '
          + (EVIDENCE_DATA.length ? 'The analysis is grounded in <strong>' + EVIDENCE_DATA.length + ' primary evidence sources</strong>. ' : '')
          + (MECHANISM_DATA.length ? MECHANISM_DATA.length + ' causal mechanisms are documented.' : '')
          + '</div></div>';

        /* ── System stats ── */
        html += sec('System Overview')
          + '<div class="rpt-stats">'
          + '<div class="rpt-stat-box"><div class="rpt-stat-num">' + NODE_COUNT + '</div><div class="rpt-stat-lbl">Variables</div></div>'
          + '<div class="rpt-stat-box"><div class="rpt-stat-num">' + EXPLICIT_COUNT + '</div><div class="rpt-stat-lbl">Relationships</div></div>'
          + '<div class="rpt-stat-box"><div class="rpt-stat-num">' + loops.length + '</div><div class="rpt-stat-lbl">Feedback Loops</div></div>'
          + '<div class="rpt-stat-box"><div class="rpt-stat-num">' + EVIDENCE_DATA.length + '</div><div class="rpt-stat-lbl">Evidence Sources</div></div>'
          + '</div></div>';

        /* ── Feedback loop analysis ── */
        html += sec('Feedback Loop Analysis (' + loops.length + ')');
        loops.forEach(function(loop) {{
          var isR   = loop.is_reinforcing;
          var color = isR ? '#1d4ed8' : '#7c3aed';
          var icon  = isR ? '↺' : '⇌';
          html += '<div class="rpt-loop' + (isR ? '' : ' balancing') + '">'
            + '<div class="rpt-loop-head">'
            + '<span class="rpt-loop-id">' + icon + ' ' + esc(loop.id) + '</span>'
            + '<span class="rpt-loop-name">' + esc(loop.short_name) + '</span>'
            + '<span class="rpt-loop-badge ' + (isR?'r':'b') + '">' + (isR?'Reinforcing':'Balancing') + '</span>'
            + '</div>';
          if (loop.narrative) html += field('Narrative', loop.narrative);
          if (loop.dominant_period) html += field('Dominant period', loop.dominant_period);
          if (loop.variables && loop.variables.length) {{
            var chain = '<div class="rpt-field"><span class="rpt-field-label">Variable chain: </span>'
              + '<div class="rpt-chain">';
            loop.variables.forEach(function(v, i) {{
              if (i > 0) chain += '<span class="rpt-arrow">→</span>';
              chain += '<span class="rpt-chip">' + esc(v) + '</span>';
            }});
            chain += '<span class="rpt-arrow">↩</span></div></div>';
            html += chain;
          }}
          if (loop.delay_points)       html += field('Delay points', loop.delay_points);
          if (loop.leverage_points)    html += field('Leverage points', loop.leverage_points);
          if (loop.collapse_conditions) html += field('Collapse conditions', loop.collapse_conditions);
          html += '</div>';
        }});
        html += '</div>';

        /* ── Key variables (stocks first, then top auxiliaries) ── */
        if (VARIABLE_DATA && VARIABLE_DATA.length) {{
          var stocks = VARIABLE_DATA.filter(function(v){{return (v.variable_type||'').toLowerCase()==='stock';}});
          var aux    = VARIABLE_DATA.filter(function(v){{return (v.variable_type||'').toLowerCase()!=='stock';}});
          html += sec('Key Variables (' + VARIABLE_DATA.length + ')');
          html += '<div class="rpt-var-grid">';
          stocks.concat(aux).forEach(function(v) {{
            var vtype = (v.variable_type||'auxiliary');
            html += '<div class="rpt-var">'
              + '<div class="rpt-var-label">' + esc(v.label) + '</div>'
              + '<div class="rpt-var-type">' + esc(vtype) + (v.unit ? ' · ' + esc(v.unit) : '') + '</div>'
              + (v.definition ? '<div class="rpt-var-def">' + esc(v.definition.substring(0,120)) + (v.definition.length>120?'…':'') + '</div>' : '')
              + '</div>';
          }});
          html += '</div></div>';
        }}

        /* ── Causal mechanisms ── */
        if (MECHANISM_DATA && MECHANISM_DATA.length) {{
          html += sec('Causal Mechanisms (' + MECHANISM_DATA.length + ')');
          MECHANISM_DATA.forEach(function(m) {{
            html += '<div class="rpt-mech">'
              + '<div class="rpt-mech-label">' + esc(m.label) + '</div>'
              + (m.relationship ? '<div class="rpt-mech-rel">' + esc(m.relationship) + '</div>' : '')
              + (m.explanation  ? '<div class="rpt-mech-exp">' + esc(m.explanation) + '</div>' : '')
              + '</div>';
          }});
          html += '</div>';
        }}

        /* ── Strategic leverage points (aggregated across loops) ── */
        var leverageItems = loops.filter(function(l){{return l.leverage_points;}});
        if (leverageItems.length) {{
          html += sec('Strategic Leverage Points');
          leverageItems.forEach(function(l) {{
            html += '<div class="rpt-leverage">'
              + '<div class="rpt-leverage-loop">' + (l.is_reinforcing?'↺':'⇌') + ' ' + esc(l.id) + ' · ' + esc(l.short_name) + '</div>'
              + '<div class="rpt-field-value">' + esc(l.leverage_points) + '</div></div>';
          }});
          html += '</div>';
        }}

        /* ── Collapse / risk conditions ── */
        var collapseItems = loops.filter(function(l){{return l.collapse_conditions;}});
        if (collapseItems.length) {{
          html += sec('Loop Collapse Conditions & Risk Factors');
          collapseItems.forEach(function(l) {{
            html += '<div class="rpt-collapse">'
              + '<div class="rpt-collapse-loop">' + (l.is_reinforcing?'↺':'⇌') + ' ' + esc(l.id) + ' · ' + esc(l.short_name) + '</div>'
              + '<div class="rpt-field-value">' + esc(l.collapse_conditions) + '</div></div>';
          }});
          html += '</div>';
        }}

        /* ── Evidence base ── */
        if (EVIDENCE_DATA.length) {{
          html += sec('Evidence Base (' + EVIDENCE_DATA.length + ' sources)');
          EVIDENCE_DATA.forEach(function(e) {{
            var noDate = !e.release_date || e.release_date.toLowerCase().indexOf('unknown') !== -1;
            html += '<div class="rpt-ev">'
              + '<div class="rpt-ev-source">&#128196; ' + esc(e.source || e.title || 'Source') + '</div>'
              + '<div class="rpt-ev-date">' + (noDate ? '⚠ Date unknown' : esc(e.release_date))
              + (e.evidence_type ? ' · ' + esc(e.evidence_type) : '') + '</div>'
              + (e.finding ? '<div class="rpt-ev-finding">' + esc(e.finding) + '</div>' : '')
              + '</div>';
          }});
          html += '</div>';
        }}

        return html;
      }}

      window.openReport = function() {{
        document.getElementById('report-subtitle').textContent = PROJECT_NAME + '  ·  ' + NODE_COUNT + ' variables · ' + Object.keys(LOOP_DATA).length + ' loops';
        document.getElementById('report-content').innerHTML = buildReport();
        document.getElementById('report-modal').classList.add('open');
        document.body.style.overflow = 'hidden';
      }};

      window.closeReport = function() {{
        document.getElementById('report-modal').classList.remove('open');
        document.body.style.overflow = '';
      }};

      window.copyReport = function() {{
        var text = document.getElementById('report-content').innerText;
        navigator.clipboard.writeText(text).then(function() {{
          var btn = document.getElementById('btn-copy-report');
          btn.textContent = '✓ Copied';
          setTimeout(function(){{ btn.textContent = '📋 Copy'; }}, 2000);
        }});
      }};

      window.exportPDF = function() {{
        var now = new Date().toLocaleDateString('en-GB', {{day:'2-digit',month:'short',year:'numeric'}});
        var body = buildReport();
        var doc = '<!DOCTYPE html><html><head><meta charset="utf-8">'
          + '<title>Causal Intelligence Report — ' + PROJECT_NAME + '</title>'
          + '<style>'
          + '@page{{size:A4;margin:18mm 16mm 22mm 16mm;}}'
          + '*{{box-sizing:border-box;margin:0;padding:0;}}'
          + 'body{{font-family:Arial,Helvetica,sans-serif;font-size:10.5pt;color:#1e293b;line-height:1.55;}}'
          /* header */
          + '.pdf-header{{display:flex;justify-content:space-between;align-items:flex-start;'
          + '  padding-bottom:10px;border-bottom:3px solid #1d4ed8;margin-bottom:20px;}}'
          + '.pdf-brand{{font-size:16pt;font-weight:900;color:#1d4ed8;letter-spacing:-.03em;}}'
          + '.pdf-brand span{{color:#7c3aed;}}'
          + '.pdf-meta{{font-size:8pt;color:#94a3b8;text-align:right;line-height:1.6;}}'
          /* page number footer */
          + '@media print{{'
          + '  body::after{{content:"";display:block;}}'
          + '  .no-break{{page-break-inside:avoid;}}'
          + '}}'
          + '.rpt-section{{margin-bottom:20px;}}'
          + '.rpt-h1{{font-size:17pt;font-weight:900;letter-spacing:-.03em;color:#0f172a;margin-bottom:2px;}}'
          + '.rpt-meta{{font-size:8pt;color:#94a3b8;margin-bottom:14px;}}'
          + '.rpt-h2{{font-size:9pt;font-weight:800;text-transform:uppercase;letter-spacing:.08em;'
          + '  color:#1d4ed8;border-bottom:1.5px solid #dbeafe;padding-bottom:3px;margin-bottom:8px;}}'
          + '.rpt-stats{{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:4px;}}'
          + '.rpt-stat-box{{background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;'
          + '  padding:8px 10px;text-align:center;}}'
          + '.rpt-stat-num{{font-size:18pt;font-weight:900;color:#1d4ed8;line-height:1;}}'
          + '.rpt-stat-lbl{{font-size:7.5pt;color:#64748b;margin-top:1px;}}'
          + '.rpt-loop{{border:1px solid #e2e8f0;border-left:3px solid #1d4ed8;'
          + '  border-radius:6px;padding:10px 12px;margin-bottom:8px;page-break-inside:avoid;}}'
          + '.rpt-loop.balancing{{border-left-color:#7c3aed;}}'
          + '.rpt-loop-head{{display:flex;align-items:center;gap:7px;margin-bottom:5px;}}'
          + '.rpt-loop-id{{font-size:11pt;font-weight:900;color:#1d4ed8;}}'
          + '.rpt-loop.balancing .rpt-loop-id{{color:#7c3aed;}}'
          + '.rpt-loop-name{{font-size:10pt;font-weight:700;color:#0f172a;}}'
          + '.rpt-loop-badge{{font-size:7pt;font-weight:700;padding:2px 6px;border-radius:20px;'
          + '  text-transform:uppercase;letter-spacing:.05em;}}'
          + '.rpt-loop-badge.r{{background:#dbeafe;color:#1d4ed8;}}'
          + '.rpt-loop-badge.b{{background:#ede9fe;color:#6d28d9;}}'
          + '.rpt-field{{margin-bottom:4px;font-size:9.5pt;}}'
          + '.rpt-field-label{{font-size:7.5pt;font-weight:700;text-transform:uppercase;'
          + '  letter-spacing:.05em;color:#64748b;}}'
          + '.rpt-field-value{{color:#334155;}}'
          + '.rpt-chain{{display:flex;flex-wrap:wrap;gap:3px;align-items:center;margin-top:2px;}}'
          + '.rpt-chip{{font-size:7.5pt;background:#f1f5f9;border:1px solid #cbd5e1;'
          + '  border-radius:3px;padding:1px 5px;color:#334155;}}'
          + '.rpt-arrow{{font-size:8pt;color:#94a3b8;}}'
          + '.rpt-ev{{padding:6px 10px;border-left:2.5px solid #10b981;background:#f0fdf4;'
          + '  border-radius:0 5px 5px 0;margin-bottom:6px;page-break-inside:avoid;}}'
          + '.rpt-ev-source{{font-weight:700;font-size:9pt;color:#065f46;}}'
          + '.rpt-ev-date{{font-size:8pt;color:#64748b;}}'
          + '.rpt-ev-finding{{font-size:9pt;color:#1e293b;margin-top:2px;line-height:1.4;}}'
          + '.rpt-mech{{padding:5px 0;border-bottom:1px solid #f1f5f9;page-break-inside:avoid;}}'
          + '.rpt-mech:last-child{{border-bottom:none;}}'
          + '.rpt-mech-label{{font-weight:700;font-size:9.5pt;color:#1e293b;}}'
          + '.rpt-mech-rel{{font-size:8.5pt;color:#7c3aed;margin:1px 0;}}'
          + '.rpt-mech-exp{{font-size:9pt;color:#475569;line-height:1.35;}}'
          + '.rpt-var-grid{{display:grid;grid-template-columns:1fr 1fr;gap:5px;}}'
          + '.rpt-var{{background:#f8fafc;border:1px solid #e2e8f0;border-radius:5px;'
          + '  padding:6px 8px;page-break-inside:avoid;}}'
          + '.rpt-var-label{{font-weight:700;font-size:9.5pt;color:#1e293b;}}'
          + '.rpt-var-type{{font-size:7.5pt;color:#94a3b8;text-transform:uppercase;letter-spacing:.04em;}}'
          + '.rpt-var-def{{font-size:8.5pt;color:#475569;margin-top:2px;line-height:1.3;}}'
          + '.rpt-leverage{{background:#eff6ff;border-radius:5px;padding:7px 10px;margin-bottom:5px;page-break-inside:avoid;}}'
          + '.rpt-leverage-loop{{font-size:8pt;font-weight:700;color:#1d4ed8;margin-bottom:2px;}}'
          + '.rpt-collapse{{background:#fff7ed;border-radius:5px;padding:7px 10px;margin-bottom:5px;page-break-inside:avoid;}}'
          + '.rpt-collapse-loop{{font-size:8pt;font-weight:700;color:#c2410c;margin-bottom:2px;}}'
          + '.rpt-summary-text{{color:#334155;line-height:1.65;font-size:10pt;}}'
          + '</style></head><body>'
          + '<div class="pdf-header">'
          + '  <div>'
          + '    <div class="pdf-brand">Loop<span>Map</span></div>'
          + '    <div style="font-size:8pt;color:#94a3b8;margin-top:2px;">Causal Intelligence Report</div>'
          + '  </div>'
          + '  <div class="pdf-meta">'
          + '    <strong>' + PROJECT_NAME + '</strong><br>'
          + '    Generated ' + now + '<br>'
          + '    ' + NODE_COUNT + ' variables · ' + Object.keys(LOOP_DATA).length + ' loops · ' + EVIDENCE_DATA.length + ' sources'
          + '  </div>'
          + '</div>'
          + body
          + '<scr'+'ipt>window.onload=function(){{window.print();}};</scr'+'ipt>'
          + '</body></html>';
        var win = window.open('', '_blank');
        if (win) {{ win.document.write(doc); win.document.close(); }}
      }};

      document.addEventListener('keydown', function(e) {{
        if (e.key === 'Escape') {{
          closeReport();
          closeVarDlg();
          closeRelDlg();
        }}
      }});

      // ── Edit tools ───────────────────────────────────────────────────────────
      try {{
      var activeMode = null; // 'delete' | 'relate' | null
      var relateSrc  = null; // {{slug, label}} of first node in relate mode
      var serverAvailable = null;

      var EDIT_BTNS = ['btn-add-var', 'btn-relate', 'btn-delete'];

      // Check server availability once; disable buttons if unreachable
      (function() {{
        if (location.protocol === 'file:') {{
          EDIT_BTNS.forEach(function(id) {{
            var b = document.getElementById(id);
            if (b) {{ b.classList.add('no-server'); b.title = 'Start with: python cld_tool.py --serve'; }}
          }});
          return;
        }}
        fetch('/api/ping').then(function(r) {{
          serverAvailable = r.ok;
          if (!r.ok) markNoServer('Edit server not detected — restart with --serve');
        }}).catch(function() {{ serverAvailable = false; markNoServer('Edit server not reachable'); }});
      }})();

      function markNoServer(msg) {{
        EDIT_BTNS.forEach(function(id) {{
          var b = document.getElementById(id);
          if (b) {{ b.classList.add('no-server'); b.title = msg; }}
        }});
      }}

      function requireServer() {{
        if (serverAvailable === false || location.protocol === 'file:') {{
          alert('This action requires the local server.\\n\\nRun:  python cld_tool.py --project <folder> --serve');
          return false;
        }}
        return true;
      }}

      function setMode(mode) {{
        activeMode = mode;
        relateSrc = null;
        document.querySelectorAll('.map-node.node-selected').forEach(function(el) {{
          el.classList.remove('node-selected');
        }});
        document.getElementById('btn-relate').classList.toggle('active', mode === 'relate');
        document.getElementById('btn-delete').classList.toggle('active', mode === 'delete');
        document.body.classList.toggle('delete-mode', mode === 'delete');
        document.body.classList.toggle('relate-mode', mode === 'relate');
        var banner = document.getElementById('edit-banner');
        if (mode === 'delete') {{
          banner.textContent = '🗑 Delete mode — click any variable to delete it • click Delete again or press Esc to exit';
          banner.classList.add('visible');
        }} else if (mode === 'relate') {{
          banner.textContent = '↗ Relate mode — click first variable, then second to add relationship • click Relate again or press Esc to exit';
          banner.classList.add('visible');
        }} else {{
          banner.classList.remove('visible');
        }}
      }}


      // Delete a variable by label — called from the panel list buttons
      window.deleteNodeByLabel = function(label) {{
        if (!confirm('Delete "' + label + '" and all its relationships?\\nThis cannot be undone.')) return;
        fetch('/api/delete', {{
          method: 'POST',
          headers: {{'Content-Type': 'application/json'}},
          body: JSON.stringify({{label: label}})
        }}).then(function(r) {{
          if (!r.ok) {{ r.text().then(function(t) {{ alert('Error: ' + t); }}); return; }}
          var slug = label.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
          var nodeEl = document.querySelector('.map-node[data-node="' + slug + '"]');
          if (nodeEl) nodeEl.remove();
          if (typeof EDGE_RAW_DATA !== 'undefined') {{
            EDGE_RAW_DATA.forEach(function(ed) {{
              if (ed.src === slug || ed.tgt === slug) {{
                var edEl = document.getElementById(ed.id);
                if (edEl) edEl.remove();
              }}
            }});
          }}
          if (typeof nodePosMap !== 'undefined') {{ delete nodePosMap[slug]; }}
        }}).catch(function(err) {{ alert('Server not reachable: ' + err); }});
      }};

      window.openAddVarDlg = function() {{
        if (!requireServer()) return;
        document.getElementById('dlg-var-name').value = '';
        document.getElementById('dlg-var-type').selectedIndex = 2; // default: Auxiliary
        document.getElementById('dlg-var-unit').value = '';
        document.getElementById('dlg-var-def').value = '';
        document.getElementById('dlg-variable').classList.add('open');
        setTimeout(function() {{ document.getElementById('dlg-var-name').focus(); }}, 60);
      }};

      window.toggleDeleteMode = function() {{
        if (!requireServer()) return;
        setMode(activeMode === 'delete' ? null : 'delete');
      }};

      window.toggleRelateMode = function() {{
        if (!requireServer()) return;
        setMode(activeMode === 'relate' ? null : 'relate');
      }};

      // Escape exits any active mode
      document.addEventListener('keydown', function(e) {{
        if (e.key === 'Escape' && activeMode) setMode(null);
      }});

      // Mousedown capture — handles delete and relate modes
      document.getElementById('main-svg').addEventListener('mousedown', function(e) {{
        if (!activeMode || e.button !== 0) return;
        var nodeEl = e.target;
        while (nodeEl && nodeEl !== this) {{
          if (nodeEl.classList && nodeEl.classList.contains('map-node')) break;
          nodeEl = nodeEl.parentElement;
        }}
        if (!nodeEl || nodeEl === this) return;
        var slug = nodeEl.getAttribute('data-node');
        if (!slug) return;
        var tipRaw = nodeEl.getAttribute('data-tip');
        var label = slug;
        if (tipRaw) {{ try {{ label = JSON.parse(tipRaw).label || slug; }} catch(x) {{}} }}

        if (activeMode === 'delete') {{
          deleteNodeByLabel(label);
        }} else if (activeMode === 'relate') {{
          if (!relateSrc) {{
            relateSrc = {{slug: slug, label: label}};
            nodeEl.classList.add('node-selected');
          }} else if (relateSrc.slug === slug) {{
            nodeEl.classList.remove('node-selected');
            relateSrc = null;
          }} else {{
            var src = relateSrc;
            relateSrc = null;
            document.querySelectorAll('.map-node.node-selected').forEach(function(n) {{
              n.classList.remove('node-selected');
            }});
            document.getElementById('dlg-rel-pair').value = src.label + ' → ' + label;
            document.getElementById('dlg-rel-polarity').value = 'positive';
            document.getElementById('dlg-rel-mech').value = '';
            document.getElementById('dlg-rel-conf').value = 'Low';
            var dlg = document.getElementById('dlg-rel');
            dlg.dataset.src = src.label;
            dlg.dataset.tgt = label;
            dlg.classList.add('open');
            setTimeout(function() {{ document.getElementById('dlg-rel-mech').focus(); }}, 60);
          }}
        }}
      }}, true);

      window.closeVarDlg = function() {{ document.getElementById('dlg-variable').classList.remove('open'); }};
      window.closeRelDlg = function() {{
        document.getElementById('dlg-rel').classList.remove('open');
        relateSrc = null;
        document.querySelectorAll('.map-node.node-selected').forEach(function(n) {{ n.classList.remove('node-selected'); }});
      }};

      window.submitVariable = function() {{
        var name = document.getElementById('dlg-var-name').value.trim();
        if (!name) {{ alert('Variable name is required.'); return; }}
        var varType = document.getElementById('dlg-var-type').value;
        var unit    = document.getElementById('dlg-var-unit').value.trim();
        var def     = document.getElementById('dlg-var-def').value.trim();
        fetch('/api/variable', {{
          method: 'POST',
          headers: {{'Content-Type': 'application/json'}},
          body: JSON.stringify({{name: name, variable_type: varType, unit: unit, definition: def}})
        }}).then(function(r) {{
          if (!r.ok) {{ r.text().then(function(t) {{ alert('Error: ' + t); }}); return; }}
          closeVarDlg();
          var slug    = name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
          var tipData = JSON.stringify({{kind:'node', label: name, node_type:'Variable', loops:[]}});
          // Place near centroid of existing nodes
          var posVals = Object.values(nodePosMap);
          var bx = posVals.length ? posVals.reduce(function(s,n){{return s+n.x;}},0)/posVals.length : 800;
          var by = posVals.length ? posVals.reduce(function(s,n){{return s+n.y;}},0)/posVals.length : 600;
          var ang = Math.random() * 2 * Math.PI;
          var cx  = bx + Math.cos(ang) * (180 + Math.random() * 80);
          var cy  = by + Math.sin(ang) * (180 + Math.random() * 80);
          // Determine visual style from variable type
          var isBox = (varType === 'stock' || varType === 'flow' || varType === 'exogenous');
          var gCss  = {{stock:'stock-node', flow:'flow-node', exogenous:'exo-node'}}[varType] || 'variable-node';
          var tCss  = {{stock:'map-stock-label', flow:'map-flow-label', exogenous:'map-exo-label',
                        constant:'map-constant-label'}}[varType] || 'map-variable-label';
          var rxVal = varType === 'flow' ? '14' : '4';
          // Register in position maps so drag works immediately
          nodePosMap[slug]          = {{x: cx, y: cy, isStock: isBox}};
          NODE_POSITIONS_DATA[slug] = {{x: cx, y: cy, isStock: isBox}};
          var svgNS = 'http://www.w3.org/2000/svg';
          var g = document.createElementNS(svgNS, 'g');
          g.setAttribute('class', 'map-node ' + gCss);
          g.setAttribute('data-node', slug);
          g.setAttribute('data-tip', tipData);
          var txt = document.createElementNS(svgNS, 'text');
          if (isBox) {{
            var boxW = Math.max(90, name.length * 7.5 + 22);
            var boxH = 36;
            var rectEl = document.createElementNS(svgNS, 'rect');
            rectEl.setAttribute('x', (cx - boxW / 2).toFixed(1));
            rectEl.setAttribute('y', (cy - boxH / 2).toFixed(1));
            rectEl.setAttribute('width', boxW.toFixed(1));
            rectEl.setAttribute('height', boxH.toFixed(1));
            rectEl.setAttribute('rx', rxVal);
            g.appendChild(rectEl);
            txt.setAttribute('y', (cy + 5).toFixed(1));
          }} else {{
            txt.setAttribute('y', cy.toFixed(1));
          }}
          txt.setAttribute('x', cx.toFixed(1));
          txt.setAttribute('class', tCss);
          txt.textContent = name;
          g.appendChild(txt);
          document.getElementById('zoom-layer').appendChild(g);
          // Wire up drag and click-to-detail (same pattern as existing nodes)
          var nodeClicked = false;
          var mainSvg = document.getElementById('main-svg');
          g.addEventListener('mousedown', function(e) {{
            if (e.button !== 0) return;
            e.stopPropagation();
            nodeClicked = true;
            ndDragging = true; ndEl = g; ndSlug = slug; ndMoved = false;
            var ms = window._getMapState ? window._getMapState() : {{tx:0, ty:0, scale:1}};
            var r2 = mainSvg.getBoundingClientRect();
            ndSvgX0 = (e.clientX - r2.left - ms.tx) / ms.scale;
            ndSvgY0 = (e.clientY - r2.top  - ms.ty) / ms.scale;
            ndBx = nodePosMap[slug].x;
            ndBy = nodePosMap[slug].y;
            g.style.cursor = 'grabbing';
          }});
          g.addEventListener('mouseup', function() {{
            if (!nodeClicked || ndMoved) {{ nodeClicked = false; return; }}
            nodeClicked = false;
            if (typeof activeMode !== 'undefined' && activeMode) return;
            if (panelCollapsed) togglePanel();
            showVariableDetail(name);
          }});
        }}).catch(function(err) {{ alert('Server not reachable: ' + err); }});
      }};

      window.submitRelationship = function() {{
        var mech = document.getElementById('dlg-rel-mech').value.trim();
        if (!mech) {{ alert('Mechanism is required — explain why A affects B.'); return; }}
        var dlg = document.getElementById('dlg-rel');
        fetch('/api/relationship', {{
          method: 'POST',
          headers: {{'Content-Type': 'application/json'}},
          body: JSON.stringify({{
            source:     dlg.dataset.src,
            target:     dlg.dataset.tgt,
            polarity:   document.getElementById('dlg-rel-polarity').value,
            mechanism:  mech,
            confidence: document.getElementById('dlg-rel-conf').value
          }})
        }}).then(function(r) {{
          if (r.ok) {{ closeRelDlg(); }}
          else {{ r.text().then(function(t) {{ alert('Error: ' + t); }}); }}
        }}).catch(function(err) {{ alert('Server not reachable: ' + err); }});
      }};
      }} catch(editInitErr) {{ console.error('LoopMap edit-mode init error:', editInitErr); }}
    }})();
  </script>
</body>
</html>
"""
    path.write_text(html_doc, encoding="utf-8")


def write_html(payload: dict[str, object], path: Path) -> None:
    nodes = [node["id"] for node in payload["nodes"]]  # type: ignore[index]
    edge_rows = payload["edges"]  # type: ignore[assignment]
    loops = payload["loops"]  # type: ignore[assignment]
    edges = [
        Edge(
            source=str(edge["source"]),
            target=str(edge["target"]),
            polarity=str(edge["polarity"]),
            mechanism=str(edge["mechanism"]),
            delay=str(edge["delay"]),
            confidence=str(edge["confidence"]),
            related_loops=[str(name) for name in edge["related_loops"]],
            inferred_from_loop=bool(edge["inferred_from_loop"]),
        )
        for edge in edge_rows  # type: ignore[union-attr]
    ]
    lookup = edge_lookup(edges)

    loop_cards = []
    for loop in loops:  # type: ignore[union-attr]
        loop_svg = render_loop_svg(loop, lookup)
        loop_cards.append(
            "<section class=\"loop-card\">"
            f"<div class=\"loop-heading\"><h2>{html.escape(str(loop['name']))}</h2>"
            f"<span>{html.escape(str(loop['loop_type']))}</span></div>"
            f"{loop_svg}"
            f"<p>{html.escape(str(loop['narrative']))}</p>"
            f"<dl><dt>Dominant period</dt><dd>{html.escape(str(loop['dominant_period']))}</dd>"
            f"<dt>Delay points</dt><dd>{html.escape(str(loop['delay_points']))}</dd>"
            f"<dt>Leverage points</dt><dd>{html.escape(str(loop['leverage_points']))}</dd></dl>"
            "</section>"
        )

    relationship_svg = render_relationship_svg(edges)
    explicit_count = sum(1 for edge in edges if not edge.inferred_from_loop)
    inferred_count = sum(1 for edge in edges if edge.inferred_from_loop)

    html_doc = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Causal Loop Diagram</title>
  <style>
    body {{
      margin: 0;
      font-family: Arial, Helvetica, sans-serif;
      color: #20242a;
      background: #f5f7fa;
    }}
    header {{
      padding: 24px 32px 18px;
      background: #ffffff;
      border-bottom: 1px solid #dfe4ea;
    }}
    h1 {{
      margin: 0;
      font-size: 26px;
      font-weight: 700;
    }}
    .summary {{
      margin: 8px 0 0;
      color: #59636f;
      font-size: 14px;
    }}
    main {{
      padding: 20px;
      max-width: 1440px;
      margin: 0 auto;
    }}
    .loop-grid {{
      display: grid;
      grid-template-columns: 1fr;
      gap: 18px;
    }}
    .loop-card, .relationship-panel {{
      background: white;
      border: 1px solid #dfe4ea;
      border-radius: 8px;
      overflow: hidden;
    }}
    .loop-heading {{
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 12px;
      padding: 16px 18px 0;
    }}
    h2 {{
      margin: 0;
      font-size: 16px;
    }}
    .loop-heading span {{
      color: #586474;
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
    }}
    .loop-card p, .loop-card dl {{
      margin: 0;
      padding: 0 18px 16px;
      font-size: 13px;
      line-height: 1.4;
    }}
    .loop-card dl {{
      display: grid;
      grid-template-columns: 120px 1fr;
      gap: 6px 12px;
      padding-top: 0;
    }}
    dt {{
      color: #66717f;
      font-weight: 700;
    }}
    dd {{
      margin: 0;
    }}
    .legend, .section-label {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px 14px;
      font-size: 13px;
      color: #59636f;
    }}
    .legend {{
      margin: 0 0 16px;
    }}
    .legend b {{
      color: #20242a;
    }}
    .loop-svg, .relationship-svg {{
      display: block;
      width: 100%;
      height: auto;
    }}
    .node rect {{
      fill: #fbf4d6;
      stroke: #c99500;
      stroke-width: 1.7;
    }}
    .source-node rect, .target-node rect {{
      fill: #f8fafc;
      stroke: #7f8a99;
    }}
    .node-label {{
      dominant-baseline: middle;
      text-anchor: middle;
      font-size: 13px;
      font-weight: 700;
      fill: #20242a;
    }}
    .edge-label {{
      text-anchor: middle;
      font-size: 16px;
      font-weight: 700;
    }}
    .edge:hover line, .edge:hover path {{
      stroke-width: 3.8;
    }}
    .loop-type {{
      text-anchor: end;
      fill: #66717f;
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
    }}
    .relationship-panel {{
      margin-top: 20px;
    }}
    .relationship-panel header {{
      padding: 16px 18px 0;
      border: 0;
    }}
    .relationship-scroll {{
      overflow: auto;
    }}
    @media (max-width: 760px) {{
      .loop-card dl {{
        grid-template-columns: 1fr;
      }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>Causal Loop Diagram</h1>
    <p class="summary">{len(nodes)} variables, {explicit_count} explicit relationships, {inferred_count} loop-path links, {len(loops)} documented loops. Hover edges for mechanism details.</p>
  </header>
  <main>
    <div class="legend">
      <span><b style="color:#16834a">+</b> positive</span>
      <span><b style="color:#c13b34">-</b> negative</span>
      <span><b style="color:#66717f">?</b> inferred/unknown</span>
      <span>dashed = loop path link that needs relationship detail</span>
    </div>
    <section class="loop-grid">
      {''.join(loop_cards)}
    </section>
    <section class="relationship-panel">
      <header>
        <h2>Explicit Relationship Pages</h2>
        <p class="summary">This section shows only relationships with markdown pages, one row per causal claim.</p>
      </header>
      <div class="relationship-scroll">
        {relationship_svg}
      </div>
    </section>
  </main>
</body>
</html>
"""
    path.write_text(html_doc, encoding="utf-8")


def append_log(path: Path, outputs: list[Path], loops: list[Loop], root: Path) -> None:
    output_text = "; ".join(str(output.relative_to(root)) for output in outputs)
    loop_text = "; ".join(loop.name for loop in loops) if loops else "none"
    entry = f"""
## [{date.today().isoformat()}] tooling | Causal Loop Visualizer

- pages updated: cld_tool.py; {output_text}; log.md
- variables extracted: none; visualization generated from existing markdown variables and relationships
- loops discovered: {loop_text}
- contradictions found: none
"""
    with path.open("a", encoding="utf-8") as handle:
        handle.write(entry)


def validate_project(root: Path, relationships_dir: str, loops_dir: str) -> bool:
    """Lint all loop and relationship files. Returns True if no errors found."""
    REQUIRED_LOOP = ["loop_type", "variables", "narrative"]
    WARN_LOOP     = ["dominant_period", "delay_points", "leverage_points"]
    REQUIRED_REL  = ["source", "target"]
    WARN_REL      = ["polarity", "mechanism", "confidence"]
    VALID_TYPES   = {"reinforcing", "balancing"}
    VALID_POL     = {"positive", "negative", "unknown"}
    # Single-word or generic-sounding variable names that are likely too vague
    VAGUE_WORDS   = {"performance", "quality", "growth", "success", "efficiency",
                     "demand", "supply", "service", "business", "value", "impact",
                     "results", "output", "productivity", "competitiveness"}

    errors:   list[str] = []
    warnings: list[str] = []

    def e(msg: str) -> None: errors.append(msg)
    def w(msg: str) -> None: warnings.append(msg)

    print(f"\nValidating project: {root}\n")

    # ── Collect all loops for cross-loop checks ────────────────────────────────
    all_loop_variables: dict[str, list[str]] = {}   # filename -> variable list
    all_rel_polarities: dict[tuple[str, str], str] = {}  # (norm_src, norm_tgt) -> polarity

    # ── loops/ ────────────────────────────────────────────────────────────────
    loops_path = root / loops_dir
    if not loops_path.exists():
        e("loops/ directory not found - no loops will be rendered")
    else:
        loop_files = sorted(loops_path.glob("*.md"))
        if not loop_files:
            w("loops/ is empty - no loops to render")
        print(f"loops/  ({len(loop_files)} file{'s' if len(loop_files) != 1 else ''})")

        for path in loop_files:
            fields = read_fields(path)
            file_errors:   list[str] = []
            file_warnings: list[str] = []

            # Required fields
            for field_name in REQUIRED_LOOP:
                if not fields.get(field_name, "").strip():
                    file_errors.append(f"missing required field '{field_name}'")

            # Recommended fields (delay, leverage, period)
            for field_name in WARN_LOOP:
                if not fields.get(field_name, "").strip():
                    file_warnings.append(f"missing recommended field '{field_name}'")

            # Variables chain
            variables_raw = fields.get("variables", "")
            parsed_vars: list[str] = []
            if "→" in variables_raw:
                file_errors.append("'variables' uses a Unicode arrow - replace with ASCII ' -> '")
            elif variables_raw:
                parsed_vars = split_loop_variables(variables_raw)
                if len(parsed_vars) < 2:
                    file_errors.append(
                        f"'variables' parsed only {len(parsed_vars)} variable(s) - need >= 2"
                    )
                elif len(parsed_vars) == 2:
                    file_warnings.append(
                        "loop has only 2 variables - may be too simple; consider adding intermediate steps"
                    )

                # Self-loop detection: any variable appears consecutively.
                # CLD convention: "A -> B -> C -> A" closes the loop by repeating
                # the first variable at the end — that closing duplicate is intentional
                # and must not be flagged. Strip it before checking.
                check_vars = parsed_vars
                if (len(check_vars) > 1
                        and normalize_name(check_vars[0]) == normalize_name(check_vars[-1])):
                    check_vars = check_vars[:-1]
                for i in range(len(check_vars) - 1):
                    if normalize_name(check_vars[i]) == normalize_name(check_vars[i + 1]):
                        file_errors.append(
                            f"self-loop: '{check_vars[i]}' links to itself consecutively"
                            " - remove the duplicate entry"
                        )

                # Vague variable names
                for var in parsed_vars:
                    words = normalize_name(var).split()
                    if len(words) == 1 and words[0] in VAGUE_WORDS:
                        file_warnings.append(
                            f"variable '{var}' is a single vague word - "
                            f"be specific, e.g. 'Customer Satisfaction Score'"
                        )

                all_loop_variables[path.name] = parsed_vars

            # loop_type classification
            loop_type = fields.get("loop_type", "").strip().lower()
            if loop_type and loop_type not in VALID_TYPES:
                file_warnings.append(
                    f"loop_type '{fields['loop_type']}' not 'Reinforcing' or 'Balancing'"
                )

            _print_file_result(path.name, file_errors, file_warnings)
            for msg in file_errors:   e(f"{path.name}: {msg}")
            for msg in file_warnings: w(f"{path.name}: {msg}")

    # ── relationships/ ────────────────────────────────────────────────────────
    rel_path = root / relationships_dir
    print()
    if not rel_path.exists():
        w("relationships/ directory not found - only loop-inferred edges will appear")
        print("relationships/  (not found - skipped)")
    else:
        rel_files = sorted(rel_path.glob("*.md"))
        print(f"relationships/  ({len(rel_files)} file{'s' if len(rel_files) != 1 else ''})")

        for path in rel_files:
            fields = read_fields(path)
            file_errors:   list[str] = []
            file_warnings: list[str] = []

            for field_name in REQUIRED_REL:
                if not fields.get(field_name, "").strip():
                    file_errors.append(f"missing required field '{field_name}'")

            polarity = fields.get("polarity", "").strip().lower()
            mechanism = fields.get("mechanism", "").strip()

            if not polarity:
                file_warnings.append("missing 'polarity' field")
            elif polarity == "unknown":
                file_warnings.append(
                    "polarity is 'unknown' - specify Positive or Negative for loop math validation"
                )
            elif polarity not in VALID_POL:
                file_warnings.append(
                    f"polarity '{fields['polarity']}' not 'Positive', 'Negative', or 'Unknown'"
                )

            if not mechanism:
                file_warnings.append("missing 'mechanism' - explain WHY source changes target")
            elif len(mechanism) < 15:
                file_warnings.append(
                    f"mechanism is very short ({len(mechanism)} chars) - add more causal detail"
                )

            if not fields.get("confidence", "").strip():
                file_warnings.append("missing 'confidence' field")

            # Store polarity for cross-loop math check
            src = display_name(fields.get("source", ""))
            tgt = display_name(fields.get("target", ""))
            if src and tgt and polarity in {"positive", "negative"}:
                all_rel_polarities[(normalize_name(src), normalize_name(tgt))] = polarity

            _print_file_result(path.name, file_errors, file_warnings)
            for msg in file_errors:   e(f"{path.name}: {msg}")
            for msg in file_warnings: w(f"{path.name}: {msg}")

    # ── Cross-loop structural checks ───────────────────────────────────────────
    if len(all_loop_variables) > 1:
        print()
        print("cross-loop checks")

        # Connectivity: every loop should share >=1 variable with at least one other loop
        loop_names  = list(all_loop_variables.keys())
        loop_norm   = {
            name: {normalize_name(v) for v in vars_}
            for name, vars_ in all_loop_variables.items()
        }
        for name, var_set in loop_norm.items():
            connected = any(
                var_set & other_set
                for other_name, other_set in loop_norm.items()
                if other_name != name
            )
            if not connected:
                msg = f"{name}: loop shares no variables with any other loop - may be a separate system"
                print(f"  [WARN] {msg}")
                w(msg)

        # Polarity math: verify R/B classification for loops where all links are known
        for name, vars_ in all_loop_variables.items():
            if len(vars_) < 2:
                continue
            neg_count = 0
            unknown_count = 0
            for i, src in enumerate(vars_):
                tgt = vars_[(i + 1) % len(vars_)]
                key = (normalize_name(src), normalize_name(tgt))
                pol = all_rel_polarities.get(key)
                if pol == "negative":
                    neg_count += 1
                elif pol is None:
                    unknown_count += 1

            if unknown_count == 0:
                # All links have known polarity — validate R/B
                fields = read_fields((root / loops_dir / name))
                declared = fields.get("loop_type", "").strip().lower()
                # Even negatives = balancing, odd negatives = reinforcing
                expected = "balancing" if neg_count % 2 == 0 else "reinforcing"
                if declared and declared != expected:
                    msg = (
                        f"{name}: declared as '{declared}' but link polarities "
                        f"({neg_count} negative link(s)) suggest '{expected}' - check polarity signs"
                    )
                    print(f"  [WARN] {msg}")
                    w(msg)
                else:
                    print(f"  [OK]   {name}: R/B classification consistent ({neg_count} negative link(s))")
            else:
                print(
                    f"  [SKIP] {name}: {unknown_count} link(s) lack explicit polarity "
                    f"- add relationship files to enable R/B math check"
                )

    # ── Human validation checklist ─────────────────────────────────────────────
    print()
    print("Human validation checklist (cannot be automated):")
    print("  [ ] Variables are measurable - two people would interpret them the same way")
    print("  [ ] Each causal link is directional - A changes B, not just correlated")
    print("  [ ] Delays are realistic - check with domain experts or historical data")
    print("  [ ] CLD explains observed historical behavior (reproduce past events mentally)")
    print("  [ ] Stress-tested - what happens when a variable goes to zero or extreme?")
    print("  [ ] Reviewed by domain expert or stakeholder")
    print("  [ ] Missing external drivers identified (regulation, competitors, technology)")

    # ── Summary ───────────────────────────────────────────────────────────────
    print()
    if not errors and not warnings:
        print("Result: all checks passed. No issues found.")
        return True
    status = f"{len(errors)} error(s), {len(warnings)} warning(s)"
    if errors:
        print(f"Result: {status}. Fix errors before running the visualizer.")
        return False
    print(f"Result: {status}. Warnings are optional improvements.")
    return True


def _print_file_result(filename: str, file_errors: list[str], file_warnings: list[str]) -> None:
    if file_errors:
        print(f"  [ERR]  {filename}")
        for msg in file_errors:
            print(f"           ERROR: {msg}")
    elif file_warnings:
        print(f"  [WARN] {filename}")
        for msg in file_warnings:
            print(f"           WARN:  {msg}")
    else:
        print(f"  [OK]   {filename}")


def generate_project(root: Path, args) -> tuple:
    """Load all sources, regenerate all outputs, return output paths."""
    relationship_edges = load_relationships(root / args.relationships_dir)
    loops = load_loops(root / args.loops_dir)
    edges = merge_edges(relationship_edges, loops)
    payload = build_payload(edges, loops)

    json_output = root / args.json_output
    dot_output  = root / args.dot_output
    html_output = root / args.html_output
    map_output  = root / args.map_output
    write_json(payload, json_output)
    write_dot(edges, loops, dot_output)
    write_html(payload, html_output)
    evidence   = load_evidence(root / args.evidence_dir)
    variables  = load_variables(root / args.variables_dir)
    mechanisms = load_mechanisms(root / args.mechanisms_dir)
    write_system_map_html(payload, map_output, evidence, variables, mechanisms)
    return payload, edges, loops, json_output, dot_output, html_output, map_output


def _slugify_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def make_loopmap_handler(root: Path, args):
    """Return an HTTP handler class bound to the given project root and args."""

    class LoopMapHandler(http.server.BaseHTTPRequestHandler):
        def log_message(self, fmt, *a):  # suppress default access log
            pass

        def do_OPTIONS(self):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def do_GET(self):
            path = urllib.parse.urlparse(self.path).path
            if path == "/api/ping":
                self._json(200, {"ok": True})
            elif path in ("/", "/index.html"):
                map_path = root / args.map_output
                try:
                    self._regen()  # always serve the latest generated HTML
                    data = map_path.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
                    self.send_header("Pragma", "no-cache")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(data)
                except Exception as exc:
                    self._text(500, str(exc))
            else:
                self._text(404, "Not found")

        def do_POST(self):
            path = urllib.parse.urlparse(self.path).path
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                data = json.loads(body)
            except Exception:
                self._text(400, "Invalid JSON")
                return
            if path == "/api/variable":
                self._new_variable(data)
            elif path == "/api/relationship":
                self._new_relationship(data)
            elif path == "/api/delete":
                self._delete_node(data)
            else:
                self._text(404, "Not found")

        def _new_variable(self, data: dict) -> None:
            name = str(data.get("name", "")).strip()
            if not name:
                self._text(400, "name is required")
                return
            var_dir = root / args.variables_dir
            var_dir.mkdir(parents=True, exist_ok=True)
            slug = _slugify_name(name)
            fpath = var_dir / f"{slug}.md"
            if fpath.exists():
                self._text(409, f"Variable file already exists: {fpath.name}")
                return
            content = (
                f"# Variable: {name}\n\n"
                f"- label: {name}\n"
                f"- variable_type: {data.get('variable_type', 'auxiliary')}\n"
                f"- unit: {data.get('unit', '')}\n"
                f"- definition: {data.get('definition', '')}\n"
            )
            fpath.write_text(content, encoding="utf-8")
            print(f"[edit] Created {fpath.relative_to(root)}")
            try:
                self._regen()
                self._json(200, {"ok": True, "file": fpath.name})
            except Exception as exc:
                self._text(500, str(exc))

        def _new_relationship(self, data: dict) -> None:
            src = str(data.get("source", "")).strip()
            tgt = str(data.get("target", "")).strip()
            if not src or not tgt:
                self._text(400, "source and target are required")
                return
            rel_dir = root / args.relationships_dir
            rel_dir.mkdir(parents=True, exist_ok=True)
            filename = f"{_slugify_name(src)}--{_slugify_name(tgt)}.md"
            fpath = rel_dir / filename
            if fpath.exists():
                self._text(409, f"Relationship file already exists: {filename}")
                return
            mechanism = str(data.get("mechanism", "")).strip()
            content = (
                f"# Relationship: {src} → {tgt}\n\n"
                f"- source: {src}\n"
                f"- target: {tgt}\n"
                f"- polarity: {data.get('polarity', 'positive')}\n"
                f"- mechanism: {mechanism}\n"
                f"- confidence: {data.get('confidence', 'Low')}\n"
                f"- evidence: \n"
            )
            fpath.write_text(content, encoding="utf-8")
            print(f"[edit] Created {fpath.relative_to(root)}")
            try:
                self._regen()
                self._json(200, {"ok": True, "file": filename})
            except Exception as exc:
                self._text(500, str(exc))

        def _delete_node(self, data: dict) -> None:
            label = str(data.get("label", "")).strip()
            if not label:
                self._text(400, "label is required")
                return
            norm = normalize_name(label)
            slug = _slugify_name(label)
            deleted: list[str] = []

            # Delete variable file if it exists
            var_path = root / args.variables_dir / f"{slug}.md"
            if var_path.exists():
                var_path.unlink()
                deleted.append(str(var_path.relative_to(root)))

            # Delete any relationship files that reference this variable
            rel_dir = root / args.relationships_dir
            if rel_dir.exists():
                for rel_file in sorted(rel_dir.glob("*.md")):
                    fields = read_fields(rel_file)
                    src = normalize_name(fields.get("source", ""))
                    tgt = normalize_name(fields.get("target", ""))
                    if src == norm or tgt == norm:
                        rel_file.unlink()
                        deleted.append(str(rel_file.relative_to(root)))

            if not deleted:
                self._text(404, f"No files found for variable: {label!r}")
                return

            for f in deleted:
                print(f"[edit] Deleted {f}")
            try:
                self._regen()
                self._json(200, {"ok": True, "deleted": deleted})
            except Exception as exc:
                self._text(500, str(exc))

        def _regen(self) -> None:
            """Regenerate project by running cld_tool.py as a subprocess.
            Always uses the latest code on disk — no server restart needed."""
            script = str(Path(__file__).resolve())
            result = subprocess.run(
                [sys.executable, script, "--project", str(root), "--no-log"],
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr or result.stdout or "Regeneration failed")

        def _json(self, code: int, obj: dict) -> None:
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        def _text(self, code: int, msg: str) -> None:
            body = msg.encode()
            self.send_response(code)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

    return LoopMapHandler


def main() -> None:
    parser = argparse.ArgumentParser(description="Visualize causal loop markdown as JSON, DOT, and HTML.")
    parser.add_argument(
        "--project", default=None,
        help="Path to the research project folder containing loops/ and relationships/. "
             "Defaults to the folder containing this script.",
    )
    parser.add_argument("--relationships-dir", default="relationships")
    parser.add_argument("--loops-dir", default="loops")
    parser.add_argument("--evidence-dir", default="evidence")
    parser.add_argument("--variables-dir", default="variables")
    parser.add_argument("--mechanisms-dir", default="mechanisms")
    parser.add_argument("--json-output", default="causal_graph.json")
    parser.add_argument("--dot-output", default="causal_loop_diagram.dot")
    parser.add_argument("--html-output", default="causal_loop_diagram.html")
    parser.add_argument("--map-output", default="causal_loop_system_map.html")
    parser.add_argument("--no-log", action="store_true", help="Skip appending the tooling operation to log.md.")
    parser.add_argument("--validate", action="store_true", help="Lint all loop and relationship files and report issues without generating output.")
    parser.add_argument("--serve", action="store_true", help="Start a local HTTP server with live-edit mode.")
    parser.add_argument("--port", type=int, default=7654, help="Port for --serve mode (default: 7654).")
    args = parser.parse_args()

    root = Path(args.project).resolve() if args.project else Path(__file__).parent.resolve()

    if args.validate:
        ok = validate_project(root, args.relationships_dir, args.loops_dir)
        sys.exit(0 if ok else 1)

    if args.serve:
        payload, edges, loops, json_output, dot_output, html_output, map_output = generate_project(root, args)
        explicit_count = sum(1 for e in edges if not e.inferred_from_loop)
        inferred_count = sum(1 for e in edges if e.inferred_from_loop)
        print(f"Variables: {len(payload['nodes'])}")
        print(f"Relationships: {len(edges)} ({explicit_count} explicit, {inferred_count} inferred)")
        print(f"Loops: {len(loops)}")
        url = f"http://localhost:{args.port}/"
        handler = make_loopmap_handler(root, args)
        socketserver.TCPServer.allow_reuse_address = True
        with socketserver.TCPServer(("", args.port), handler) as httpd:
            print(f"\nLoopMap edit server: {url}")
            print("Open that URL in your browser. Edit mode available in the toolbar.")
            print("Press Ctrl+C to stop.\n")
            webbrowser.open(url)
            try:
                httpd.serve_forever()
            except KeyboardInterrupt:
                print("\nServer stopped.")
        return

    payload, edges, loops, json_output, dot_output, html_output, map_output = generate_project(root, args)

    if not args.no_log:
        append_log(root / "log.md", [json_output, dot_output, html_output, map_output], loops, root)

    explicit_count = sum(1 for edge in edges if not edge.inferred_from_loop)
    inferred_count = sum(1 for edge in edges if edge.inferred_from_loop)
    print(f"Variables: {len(payload['nodes'])}")
    print(f"Relationships: {len(edges)} ({explicit_count} explicit, {inferred_count} inferred from loop pages)")
    print(f"Loops: {len(loops)}")
    print(f"Wrote: {json_output.name}")
    print(f"Wrote: {dot_output.name}")
    print(f"Wrote: {html_output.name}")
    print(f"Wrote: {map_output.name}")


if __name__ == "__main__":
    main()
