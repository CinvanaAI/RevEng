from __future__ import annotations

import json
from pathlib import Path


def write_ai_file_explanation_outputs(ai_results: dict, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / "ai_file_explanations.json"
    md_path = output_dir / "ai_file_explanations.md"

    json_path.write_text(
        json.dumps(ai_results, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    md_path.write_text(build_ai_file_explanations_markdown(ai_results), encoding="utf-8")


def _write_list_section(lines: list[str], title: str, values: list[str]) -> None:
    lines.append(f"### {title}")
    lines.append("")
    if values:
        for value in values:
            lines.append(f"- {value}")
    else:
        lines.append("- None")
    lines.append("")


def build_ai_file_explanations_markdown(ai_results: dict) -> str:
    lines: list[str] = []

    lines.append("# AI File Explanations")
    lines.append("")
    lines.append(f"- Repo root: `{ai_results['repo_root']}`")
    lines.append(f"- Scanned at: `{ai_results['scanned_at']}`")
    lines.append(f"- Files explained: `{ai_results['requested_file_count']}`")
    env_file = ai_results.get("env_file")
    if env_file:
        lines.append(f"- Env file: `{env_file}`")
    lines.append("")

    for item in ai_results["results"]:
        explanation = item["explanation"]

        lines.append(f"## {item['path']}")
        lines.append("")
        lines.append(f"- Module name: `{item['module_name']}`")
        lines.append("")

        _write_list_section(lines, "Defined Symbols Observed", explanation.get("defined_symbols_observed", []))
        _write_list_section(lines, "Top-level Statements Observed", explanation.get("top_level_statements_observed", []))
        _write_list_section(lines, "Calls Present Observed", explanation.get("calls_present_observed", []))
        _write_list_section(lines, "Assignments Observed", explanation.get("assignments_observed", []))
        _write_list_section(lines, "Returns Observed", explanation.get("returns_observed", []))
        _write_list_section(lines, "Raises Observed", explanation.get("raises_observed", []))
        _write_list_section(lines, "Control Flow Observed", explanation.get("control_flow_observed", []))
        _write_list_section(lines, "Visible Inputs Observed", explanation.get("visible_inputs_observed", []))
        _write_list_section(lines, "Visible Outputs Observed", explanation.get("visible_outputs_observed", []))
        _write_list_section(lines, "Visible Side Effects Observed", explanation.get("visible_side_effects_observed", []))
        _write_list_section(lines, "Resolved Inbound Relations Observed", explanation.get("resolved_inbound_relations_observed", []))
        _write_list_section(lines, "Resolved Outbound Relations Observed", explanation.get("resolved_outbound_relations_observed", []))
        _write_list_section(lines, "Unresolved Items Observed", explanation.get("unresolved_items_observed", []))
        _write_list_section(lines, "Unknowns", explanation.get("unknowns", []))

    return "\n".join(lines)