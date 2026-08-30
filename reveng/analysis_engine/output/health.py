"""Run health summary generator.

Produces run_health.md — a one-page operator summary of what happened in a
layered meaning run: record counts, inferred vs. evidence-backed, confidence
distribution, behaviorally quiet files, and validation violations.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any


def _conf_dist(records: list[dict[str, Any]]) -> dict[str, int]:
    c: Counter[str] = Counter(r.get("confidence", "unknown") for r in records)
    return dict(c)


def _inferred_count(records: list[dict[str, Any]]) -> int:
    return sum(1 for r in records if r.get("inferred"))


def _conf_dist_line(dist: dict[str, int]) -> str:
    order = ["high", "medium", "low", "unknown"]
    parts = [f"{k.upper()}: {dist.get(k, 0)}" for k in order if dist.get(k, 0)]
    return ", ".join(parts) if parts else "none"


def render_run_health(
    system_map_data: dict[str, Any],
    validation_data: dict[str, Any],
    output_dir: Path,
) -> Path:
    """Write run_health.md and return the path."""
    md_dir = output_dir / "meaning"
    md_dir.mkdir(parents=True, exist_ok=True)
    path = md_dir / "run_health.md"

    abilities = system_map_data.get("ability_records", [])
    actions = system_map_data.get("action_records", [])
    functions = system_map_data.get("function_meaning_records", [])
    file_purposes = system_map_data.get("file_purpose_records", [])
    file_behaviors = system_map_data.get("file_behavior_records", [])
    workflows = system_map_data.get("workflow_records", [])
    modules = system_map_data.get("module_summary_records", [])
    subsystems = system_map_data.get("subsystem_summary_records", [])
    system = system_map_data.get("system_summary_record") or {}

    meaning_v = validation_data.get("meaning_violations", [])
    crossref_v = validation_data.get("crossref_violations", [])
    total_violations = validation_data.get("total_violations", 0)

    # Behaviorally quiet files: files where all functions are structurally_discovered
    quiet_files: list[str] = []
    behaviorally_quiet_fps = {
        r.get("file_path") for r in functions
        if r.get("behavior_class") in ("pure_wrapper", "structurally_discovered")
    }
    has_resolved_fps = {
        r.get("file_path") for r in functions
        if r.get("behavior_class") in ("behaviorally_resolved", "coordinator")
    }
    quiet_files = sorted(behaviorally_quiet_fps - has_resolved_fps)

    # Behavior class distribution
    behavior_classes = Counter(r.get("behavior_class", "unknown") for r in functions)

    lines: list[str] = [
        "# Run Health Summary\n",
        "## Record Counts\n",
    ]

    layer_rows = [
        ("Abilities", len(abilities), _inferred_count(abilities), _conf_dist_line(_conf_dist(abilities))),
        ("Actions", len(actions), _inferred_count(actions), _conf_dist_line(_conf_dist(actions))),
        ("Function Meanings", len(functions), _inferred_count(functions), _conf_dist_line(_conf_dist(functions))),
        ("File Purposes", len(file_purposes), _inferred_count(file_purposes), _conf_dist_line(_conf_dist(file_purposes))),
        ("File Behaviors", len(file_behaviors), _inferred_count(file_behaviors), _conf_dist_line(_conf_dist(file_behaviors))),
        ("Workflows", len(workflows), _inferred_count(workflows), _conf_dist_line(_conf_dist(workflows))),
        ("Module Summaries [PROVISIONAL]", len(modules), _inferred_count(modules), _conf_dist_line(_conf_dist(modules))),
        ("Subsystem Summaries [PROVISIONAL]", len(subsystems), _inferred_count(subsystems), _conf_dist_line(_conf_dist(subsystems))),
    ]

    lines.append("| Layer | Total | Inferred | Confidence |")
    lines.append("| --- | --- | --- | --- |")
    for name, total, inferred, conf in layer_rows:
        lines.append(f"| {name} | {total} | {inferred} | {conf} |")
    lines.append("")

    # System summary
    lines.append("## System Summary\n")
    lines.append(f"**Label:** {system.get('label', '—')}")
    lines.append(f"**Confidence:** {system.get('confidence', '—').upper() if system.get('confidence') else '—'}")
    lines.append(f"**Pass-through:** {system.get('is_pass_through', False)}\n")

    # Function behavior class distribution
    lines.append("## Function Behavior Classes\n")
    lines.append("| Class | Count |")
    lines.append("| --- | --- |")
    for cls in ("behaviorally_resolved", "coordinator", "pure_wrapper", "structurally_discovered"):
        lines.append(f"| {cls} | {behavior_classes.get(cls, 0)} |")
    lines.append("")

    # Behaviorally quiet files
    if quiet_files:
        lines.append(f"## Behaviorally Quiet Files ({len(quiet_files)})\n")
        lines.append("_Files where all discovered functions have no own action records._\n")
        for fp in quiet_files[:30]:
            lines.append(f"- `{fp}`")
        if len(quiet_files) > 30:
            lines.append(f"- _... and {len(quiet_files) - 30} more_")
        lines.append("")

    # Validation violations
    lines.append("## Validation\n")
    if total_violations == 0:
        lines.append("✓ No violations found.\n")
    else:
        lines.append(f"**{total_violations} violation(s) found.**\n")
        if meaning_v:
            lines.append(f"### Layer Contract Violations ({len(meaning_v)})\n")
            for v in meaning_v[:20]:
                lines.append(f"- {v}")
            if len(meaning_v) > 20:
                lines.append(f"- _... and {len(meaning_v) - 20} more_")
            lines.append("")
        if crossref_v:
            lines.append(f"### Cross-layer Reference Violations ({len(crossref_v)})\n")
            for v in crossref_v[:20]:
                lines.append(f"- {v}")
            if len(crossref_v) > 20:
                lines.append(f"- _... and {len(crossref_v) - 20} more_")
            lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
    return path
