"""Per-layer markdown renderers for the meaning output layer.

Each render function writes one markdown file for its layer.
Outputs are independent — not collapsed into a single canonical artifact.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _confidence_badge(level: str) -> str:
    return f"[{level.upper()}]" if level else "[?]"


def _confidence_summary(records: list[dict[str, Any]]) -> str:
    """Return a compact confidence distribution string."""
    from collections import Counter
    dist: Counter[str] = Counter(r.get("confidence", "unknown") for r in records)
    order = ["high", "medium", "low", "unknown"]
    parts = [f"{k.upper()}: {dist[k]}" for k in order if dist.get(k)]
    inferred = sum(1 for r in records if r.get("inferred"))
    result = ", ".join(parts) if parts else "none"
    if inferred:
        result += f"  ({inferred} inferred)"
    return result


def _derivation_note(derivation: dict[str, Any]) -> str:
    basis = derivation.get("basis", "")
    phase1 = derivation.get("phase1_approximation", False)
    note = f"derived via: {basis}"
    if phase1:
        note += " [PROVISIONAL: Phase 1 approximation]"
    return note


def _md_table(headers: list[str], rows: list[list[str]]) -> str:
    sep = " | ".join("---" for _ in headers)
    head = " | ".join(headers)
    lines = [f"| {head} |", f"| {sep} |"]
    for row in rows:
        lines.append("| " + " | ".join(str(c) for c in row) + " |")
    return "\n".join(lines)


def _meaning_dir(output_dir: Path) -> Path:
    d = output_dir / "meaning"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# Per-layer renderers
# ---------------------------------------------------------------------------

def render_abilities(records: list[dict[str, Any]], output_dir: Path) -> Path:
    md = _meaning_dir(output_dir)
    path = md / "abilities.md"
    from collections import Counter
    dims = Counter(r.get("dimension", "?") for r in records)
    dim_summary = ", ".join(f"{d}: {n}" for d, n in sorted(dims.items()))
    lines = ["# Ability Records\n"]
    lines.append(
        f"_{len(records)} abilities detected — Phase 1 Python-specific heuristics._  \n"
        f"_Confidence: {_confidence_summary(records)}_  \n"
        f"_Dimensions: {dim_summary}_\n"
    )
    for r in records:
        confidence = _confidence_badge(r.get("confidence", ""))
        deriv = _derivation_note(r.get("derivation", {}))
        lines.append(f"## {r.get('ability_id', '?')} {confidence}")
        lines.append(f"**Label:** {r.get('label', '')}")
        lines.append(f"**Dimension:** {r.get('dimension', '')}")
        lines.append(f"**Source files:** {', '.join(r.get('source_files', []))}")
        lines.append(f"_{deriv}_\n")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def render_actions(records: list[dict[str, Any]], output_dir: Path) -> Path:
    md = _meaning_dir(output_dir)
    path = md / "actions.md"
    lines = ["# Action Records\n"]
    lines.append(
        f"_{len(records)} actions — ability instantiations at specific call sites._  \n"
        f"_Confidence: {_confidence_summary(records)}_\n"
    )
    headers = ["action_id", "file_path", "scope", "ability", "confidence"]
    rows = [
        [
            r.get("action_id", "")[:16],
            r.get("file_path", ""),
            r.get("function_scope", ""),
            r.get("ability_id", ""),
            _confidence_badge(r.get("confidence", "")),
        ]
        for r in records
    ]
    lines.append(_md_table(headers, rows))
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def render_function_meanings(records: list[dict[str, Any]], output_dir: Path) -> Path:
    from collections import Counter
    md = _meaning_dir(output_dir)
    path = md / "function_meanings.md"
    bc_dist = Counter(r.get("behavior_class", "unknown") for r in records)
    bc_summary = ", ".join(
        f"{cls}: {bc_dist[cls]}"
        for cls in ("behaviorally_resolved", "coordinator", "pure_wrapper", "structurally_discovered")
        if bc_dist.get(cls)
    )
    lines = ["# Function Meaning Records\n"]
    lines.append(
        f"_{len(records)} functions aggregated from action records._  \n"
        f"_Confidence: {_confidence_summary(records)}_  \n"
        f"_Behavior classes: {bc_summary}_\n"
    )
    for r in records:
        status = r.get("resolution_status", "")
        bc = r.get("behavior_class", "")
        confidence = _confidence_badge(r.get("confidence", ""))
        qualifier = f" _({bc})_" if bc and bc != "behaviorally_resolved" else ""
        lines.append(f"## `{r.get('function_scope', '?')}` in `{r.get('file_path', '?')}` {confidence}{qualifier}")
        lines.append(f"**Label:** {r.get('label', '')}")
        abilities = r.get("ability_ids", [])
        if abilities:
            lines.append(f"**Abilities:** {', '.join(abilities)}")
        lines.append(f"**Actions:** {len(r.get('action_ids', []))} records")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def render_file_purposes(records: list[dict[str, Any]], output_dir: Path) -> Path:
    md = _meaning_dir(output_dir)
    path = md / "file_purposes.md"
    test_count = sum(1 for r in records if r.get("is_test"))
    lines = ["# File Purpose Records\n"]
    lines.append(
        f"_Structure-based; {len(records)} files ({test_count} test). "
        f"Does not require action records._  \n"
        f"_Confidence: {_confidence_summary(records)}_\n"
    )
    headers = ["file_path", "label", "abilities", "confidence"]
    rows = [
        [
            r.get("file_path", ""),
            r.get("label", "")[:60],
            str(len(r.get("ability_ids", []))),
            _confidence_badge(r.get("confidence", "")),
        ]
        for r in records
    ]
    lines.append(_md_table(headers, rows))
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def render_file_behaviors(records: list[dict[str, Any]], output_dir: Path) -> Path:
    md = _meaning_dir(output_dir)
    path = md / "file_behaviors.md"
    test_count = sum(1 for r in records if r.get("is_test"))
    lines = ["# File Behavior Records\n"]
    lines.append(
        f"_Action-based; {len(records)} files ({test_count} test). "
        f"Depends on function meaning records._  \n"
        f"_Confidence: {_confidence_summary(records)}_\n"
    )
    for r in records:
        confidence = _confidence_badge(r.get("confidence", ""))
        lines.append(f"## `{r.get('file_path', '?')}` {confidence}")
        lines.append(f"**Label:** {r.get('label', '')}")
        lines.append(f"**Functions:** {len(r.get('function_meaning_ids', []))}, "
                      f"**Actions:** {len(r.get('action_ids', []))}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def render_workflows(records: list[dict[str, Any]], output_dir: Path) -> Path:
    md = _meaning_dir(output_dir)
    path = md / "workflows.md"
    step_counts = [len(r.get("step_action_ids", [])) for r in records]
    avg_steps = (sum(step_counts) / len(step_counts)) if step_counts else 0
    lines = ["# Workflow Records\n"]
    lines.append(
        f"_{len(records)} workflows derived from flow map and action records._  \n"
        f"_Confidence: {_confidence_summary(records)}_  \n"
        f"_Average steps per workflow: {avg_steps:.1f}_\n"
    )
    for r in records:
        confidence = _confidence_badge(r.get("confidence", ""))
        lines.append(f"## `{r.get('workflow_id', '?')}` {confidence}")
        lines.append(f"**Entry point:** `{r.get('entry_point', '')}`")
        lines.append(f"**Label:** {r.get('label', '')}")
        lines.append(f"**Steps:** {len(r.get('step_action_ids', []))} actions")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def render_module_summaries(records: list[dict[str, Any]], output_dir: Path) -> Path:
    md = _meaning_dir(output_dir)
    path = md / "module_summaries.md"
    lines = ["# Module Summary Records\n"]
    lines.append("> **[PROVISIONAL]** Phase 1 structural approximations derived from cluster heuristics.\n")
    lines.append(f"_{len(records)} modules._\n")
    for r in records:
        confidence = _confidence_badge(r.get("confidence", ""))
        lines.append(f"## `{r.get('module_path', '?')}` {confidence} _[PROVISIONAL]_")
        lines.append(f"**Label:** {r.get('label', '')}")
        deriv = _derivation_note(r.get("derivation", {}))
        lines.append(f"_{deriv}_")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def render_subsystem_summaries(records: list[dict[str, Any]], output_dir: Path) -> Path:
    md = _meaning_dir(output_dir)
    path = md / "subsystem_summaries.md"
    lines = ["# Subsystem Summary Records\n"]
    lines.append("> **[PROVISIONAL]** Phase 1 structural approximations derived from path-prefix heuristics.\n")
    lines.append(f"_{len(records)} subsystems._\n")
    for r in records:
        confidence = _confidence_badge(r.get("confidence", ""))
        lines.append(f"## `{r.get('subsystem_id', '?')}` {confidence} _[PROVISIONAL]_")
        lines.append(f"**Label:** {r.get('label', '')}")
        lines.append(f"**Modules:** {', '.join(r.get('module_summary_ids', []))}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def render_system_summary(record: dict[str, Any], output_dir: Path) -> Path:
    md = _meaning_dir(output_dir)
    path = md / "system_summary.md"
    confidence = _confidence_badge(record.get("confidence", ""))
    pass_through = record.get("is_pass_through", False)
    lines = ["# System Summary\n"]
    lines.append(f"**Label:** {record.get('label', '')}")
    lines.append(f"**Confidence:** {confidence}")
    lines.append(f"**Pass-through compression:** {pass_through}")
    subs = record.get("subsystem_summary_ids", [])
    if subs:
        lines.append(f"**Subsystems:** {', '.join(subs)}")
    deriv = _derivation_note(record.get("derivation", {}))
    lines.append(f"\n_{deriv}_")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def render_system_map(data: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    """Write system_map.json (already written by caller) and system_map.md summary."""
    import json
    md = _meaning_dir(output_dir)
    json_path = md / "system_map.json"
    json_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    md_path = md / "system_map.md"
    system = data.get("system_summary_record", {})
    n_abilities = len(data.get("ability_records", []))
    n_actions = len(data.get("action_records", []))
    n_functions = len(data.get("function_meaning_records", []))
    n_file_purposes = len(data.get("file_purpose_records", []))
    n_file_behaviors = len(data.get("file_behavior_records", []))
    n_workflows = len(data.get("workflow_records", []))
    n_modules = len(data.get("module_summary_records", []))
    n_subsystems = len(data.get("subsystem_summary_records", []))

    lines = [
        "# System Map\n",
        f"**System:** {system.get('label', 'unknown')}\n",
        "## Layer Counts\n",
        _md_table(
            ["Layer", "Count"],
            [
                ["Abilities", str(n_abilities)],
                ["Actions", str(n_actions)],
                ["Function Meanings", str(n_functions)],
                ["File Purposes", str(n_file_purposes)],
                ["File Behaviors", str(n_file_behaviors)],
                ["Workflows", str(n_workflows)],
                ["Module Summaries (PROVISIONAL)", str(n_modules)],
                ["Subsystem Summaries (PROVISIONAL)", str(n_subsystems)],
            ],
        ),
    ]
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path
