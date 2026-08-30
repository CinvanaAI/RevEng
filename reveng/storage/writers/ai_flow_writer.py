from __future__ import annotations

import json
import re
from pathlib import Path

from reveng.storage.writers.ai_writer import _write_list_section


def _sanitize_flow_id_for_filename(flow_id: str) -> str:
    safe = re.sub(r'[<>:"/\\|?*]+', "__", flow_id)
    return safe.replace(" ", "_")


def write_ai_flow_explanation_outputs(
    ai_flow_results: dict,
    output_dir: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / "ai_flow_explanations.json"
    md_path = output_dir / "ai_flow_explanations.md"

    json_path.write_text(
        json.dumps(ai_flow_results, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    md_path.write_text(
        build_ai_flow_explanations_markdown(ai_flow_results),
        encoding="utf-8",
    )

    breakdowns_dir = output_dir / "ai_flow_breakdowns"
    breakdowns_dir.mkdir(parents=True, exist_ok=True)

    for result in ai_flow_results["results"]:
        safe_name = _sanitize_flow_id_for_filename(result["flow_id"])
        breakdown_path = breakdowns_dir / f"{safe_name}.md"
        breakdown_path.write_text(
            _build_ai_flow_breakdown_markdown(result),
            encoding="utf-8",
        )


def build_ai_flow_explanations_markdown(ai_flow_results: dict) -> str:
    lines: list[str] = []

    lines.append("# AI Flow Explanations")
    lines.append("")
    lines.append(f"- Repo root: `{ai_flow_results['repo_root']}`")
    lines.append(f"- Scanned at: `{ai_flow_results['scanned_at']}`")
    lines.append(f"- Flows explained: `{ai_flow_results['flow_count']}`")
    env_file = ai_flow_results.get("env_file")
    if env_file:
        lines.append(f"- Env file: `{env_file}`")
    lines.append("")

    for result in sorted(ai_flow_results["results"], key=lambda r: r["flow_id"]):
        lines.append(f"## {result['flow_id']}")
        lines.append("")
        lines.append(f"- **Root node:** `{result['root_node_id']}`")
        lines.append(f"- **Root cluster:** {result['root_cluster']}")
        lines.append("")

        der = result["derived"]
        if der["flow_summary"]:
            lines.append(der["flow_summary"])
            lines.append("")
        if der["entry_description"]:
            lines.append(f"**Entry:** {der['entry_description']}")
            lines.append("")
        _write_list_section(lines, "Key Steps", der["key_steps"])
        if der["exit_description"]:
            lines.append(f"**Exit:** {der['exit_description']}")
            lines.append("")

        if result["unknown"]:
            lines.append("**Unknown:**")
            for item in result["unknown"]:
                lines.append(f"- {item}")
            lines.append("")

    return "\n".join(lines)


def _build_ai_flow_breakdown_markdown(result: dict) -> str:
    lines: list[str] = []

    lines.append(f"# AI Flow Explanation: {result['flow_id']}")
    lines.append("")
    lines.append(f"- **Root node:** `{result['root_node_id']}`")
    lines.append(f"- **Root file:** {result['root_file']}")
    lines.append(f"- **Root cluster:** {result['root_cluster']}")
    lines.append("")

    obs = result["observed"]
    lines.append("## Observed")
    lines.append("")
    lines.append(f"- **direct_callee_count:** {obs['direct_callee_count']}")
    lines.append(f"- **reachable_node_count:** {obs['reachable_node_count']}")
    lines.append(f"- **max_depth_reached:** {obs['max_depth_reached']}")
    lines.append(f"- **is_cross_cluster_flow:** {obs['is_cross_cluster_flow']}")
    if obs["reachable_clusters"]:
        lines.append(f"- **reachable_clusters:** {', '.join(obs['reachable_clusters'])}")
    if obs["hub_functions_in_flow"]:
        lines.append(f"- **hub_functions_in_flow:** {', '.join(obs['hub_functions_in_flow'])}")
    lines.append("")

    der = result["derived"]
    lines.append("## Derived")
    lines.append("")
    if der["flow_summary"]:
        lines.append(der["flow_summary"])
        lines.append("")
    if der["entry_description"]:
        lines.append(f"**Entry:** {der['entry_description']}")
        lines.append("")
    _write_list_section(lines, "Key Steps", der["key_steps"])
    if der["exit_description"]:
        lines.append(f"**Exit:** {der['exit_description']}")
        lines.append("")

    if result["unknown"]:
        lines.append("## Unknown")
        lines.append("")
        for item in result["unknown"]:
            lines.append(f"- {item}")
        lines.append("")

    return "\n".join(lines)
