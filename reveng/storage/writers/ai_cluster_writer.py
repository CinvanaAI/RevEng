from __future__ import annotations

import json
from pathlib import Path

from reveng.storage.writers.ai_writer import _write_list_section


def write_ai_cluster_summary_outputs(ai_cluster_results: dict, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / "ai_cluster_summaries.json"
    md_path = output_dir / "ai_cluster_summaries.md"

    json_path.write_text(
        json.dumps(ai_cluster_results, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    md_path.write_text(
        build_ai_cluster_summaries_markdown(ai_cluster_results),
        encoding="utf-8",
    )


def build_ai_cluster_summaries_markdown(ai_cluster_results: dict) -> str:
    lines: list[str] = []

    lines.append("# AI Cluster Summaries")
    lines.append("")
    lines.append(f"- Repo root: `{ai_cluster_results['repo_root']}`")
    lines.append(f"- Scanned at: `{ai_cluster_results['scanned_at']}`")
    lines.append(f"- Clusters summarised: `{ai_cluster_results['cluster_count']}`")
    env_file = ai_cluster_results.get("env_file")
    if env_file:
        lines.append(f"- Env file: `{env_file}`")
    lines.append("")

    for result in sorted(ai_cluster_results["results"], key=lambda r: r["cluster_id"]):
        cluster_id = result["cluster_id"]
        obs = result["observed"]
        der = result["derived"]
        unk = result["unknown"]

        lines.append(f"## {cluster_id}")
        lines.append("")

        lines.append("### Observed")
        lines.append("")
        lines.append(f"- **cluster_type:** {obs['cluster_type']}")
        lines.append(f"- **file_count:** {obs['file_count']}")
        lines.append(f"- **is_likely_entrypoint:** {obs['is_likely_entrypoint']}")
        lines.append(f"- **internal_import_edge_count:** {obs['internal_import_edge_count']}")
        lines.append(f"- **internal_call_edge_count:** {obs['internal_call_edge_count']}")
        lines.append(
            f"- **outbound_cross_cluster_edge_count:** {obs['outbound_cross_cluster_edge_count']}"
        )
        lines.append(
            f"- **inbound_cross_cluster_edge_count:** {obs['inbound_cross_cluster_edge_count']}"
        )
        lines.append("")

        _write_list_section(lines, "Connected Clusters", obs["connected_clusters"])
        _write_list_section(lines, "Hub Functions", obs["hub_function_node_ids"])
        _write_list_section(lines, "Flows Rooted Here", obs["flow_ids_rooted_here"])
        _write_list_section(
            lines,
            "Cross-Cluster Flows Passing Through",
            obs["cross_cluster_flow_ids_passing_through"],
        )

        lines.append("### Derived")
        lines.append("")
        lines.append(f"- **architectural_role:** {der['architectural_role']}")
        lines.append("")
        if der["purpose_statement"]:
            lines.append(der["purpose_statement"])
            lines.append("")
        _write_list_section(lines, "Responsibilities", der["responsibilities"])
        _write_list_section(
            lines, "Key Dependencies Observed", der["key_dependencies_observed"]
        )
        _write_list_section(
            lines, "Key Dependents Observed", der["key_dependents_observed"]
        )

        if unk:
            lines.append("### Unknown")
            lines.append("")
            for item in unk:
                lines.append(f"- {item}")
            lines.append("")

    return "\n".join(lines)
