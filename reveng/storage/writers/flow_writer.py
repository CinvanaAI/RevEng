from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def _sanitize_flow_id_for_filename(flow_id: str) -> str:
    """Convert a flow ID to a safe filename."""
    safe = re.sub(r'[<>:"/\\|?*]+', "__", flow_id)
    return safe.replace(" ", "_")


def _build_flow_summary_markdown(flow_map: dict) -> str:
    lines: list[str] = []
    lines.append("# Flow Map")
    lines.append("")
    lines.append(f"Repo: {flow_map['repo_root']}")
    lines.append(f"Scanned: {flow_map['scanned_at']}")
    lines.append(f"Flows: {flow_map['flow_count']}")
    lines.append(f"Entrypoints identified: {flow_map['entrypoint_count']}")
    lines.append("")
    lines.append(f"**O/D/U Convention:** {flow_map['odu_convention']}")
    lines.append("")
    lines.append("---")
    lines.append("")

    if flow_map["flows"]:
        lines.append("## Flows")
        lines.append("")

        for flow in flow_map["flows"]:
            obs = flow["observed"]
            der = flow["derived"]

            lines.append(f"### {flow['flow_id']}")
            lines.append("")
            lines.append(f"- **Root node (observed):** `{flow['root_node_id']}`")
            lines.append(f"- **Root file (observed):** {flow['root_file']}")
            lines.append(f"- **Root cluster (observed):** {flow['root_cluster']}")
            lines.append(f"- **Direct callees (observed):** {obs['direct_callee_count']}")
            lines.append(f"- **Reachable nodes (derived):** {der['reachable_node_count']}")
            lines.append(f"- **Max depth reached (derived):** {der['max_depth_reached']}")
            lines.append(f"- **Cross-cluster flow (derived):** {der['is_cross_cluster_flow']}")

            if der["reachable_clusters"]:
                lines.append(
                    f"- **Reachable clusters (derived):** {', '.join(der['reachable_clusters'])}"
                )

            if der["cluster_crossings"]:
                lines.append("- **Cluster crossings (derived):**")
                for cx in der["cluster_crossings"]:
                    lines.append(
                        f"  - {cx['source_cluster']} → {cx['target_cluster']} "
                        f"| {cx['crossing_count']} crossing(s)"
                    )

            if flow["unknown"]:
                lines.append(f"- **Unknowns:** {'; '.join(flow['unknown'])}")

            lines.append("")

        lines.append("---")
        lines.append("")

    # Hub functions
    hub_nodes = [
        m for m in flow_map["function_metrics"].values()
        if m["derived"]["is_hub"]
    ]
    if hub_nodes:
        hub_nodes.sort(
            key=lambda m: m["observed"]["inbound_call_count"], reverse=True
        )
        lines.append("## Function Metrics — Hub Functions")
        lines.append("")
        for m in hub_nodes:
            lines.append(
                f"- `{m['node_id']}` "
                f"| inbound: {m['observed']['inbound_call_count']} "
                f"| outbound: {m['observed']['outbound_call_count']} "
                f"| flows: {m['derived']['flow_count']} "
                f"| cluster: {m['cluster_id']}"
            )
        lines.append("")
        lines.append("---")
        lines.append("")

    # Cluster flow matrix
    if flow_map["cluster_flow_matrix"]:
        lines.append("## Cluster Flow Matrix")
        lines.append("")
        lines.append(
            "| Source Cluster | Target Cluster | Call Edges (observed) | Flows Crossing (derived) |"
        )
        lines.append("|---|---|---|---|")
        for entry in flow_map["cluster_flow_matrix"]:
            lines.append(
                f"| {entry['source_cluster']} "
                f"| {entry['target_cluster']} "
                f"| {entry['observed']['cross_cluster_call_edge_count']} "
                f"| {entry['derived']['flow_crossing_count']} |"
            )
        lines.append("")
        lines.append("---")
        lines.append("")

    lines.append("## Repository-Level Unknowns")
    lines.append("")
    for item in flow_map["unknown"]:
        lines.append(f"- {item}")
    lines.append("")

    return "\n".join(lines)


def _build_flow_breakdown_markdown(flow: dict, flow_map: dict) -> str:
    obs = flow["observed"]
    der = flow["derived"]

    lines: list[str] = []
    lines.append(f"# Flow: {flow['flow_id']}")
    lines.append("")

    lines.append("## Root")
    lines.append("")
    lines.append(f"- **node_id:** `{flow['root_node_id']}`")
    lines.append(f"- **file:** {flow['root_file']}")
    lines.append(f"- **cluster:** {flow['root_cluster']}")
    lines.append("")

    lines.append("## Observed")
    lines.append("")
    lines.append(f"- **direct_callee_count:** {obs['direct_callee_count']}")
    lines.append(f"- **total_call_edges_from_root:** {obs['total_call_edges_from_root']}")
    lines.append("")

    if obs["direct_callees"]:
        lines.append("**Direct callees (depth 1):**")
        for callee in obs["direct_callees"]:
            lines.append(f"  - `{callee}`")
        lines.append("")

    lines.append("## Derived")
    lines.append("")
    lines.append(f"- **reachable_node_count:** {der['reachable_node_count']}")
    lines.append(f"- **max_depth_reached:** {der['max_depth_reached']}")
    lines.append(f"- **is_cross_cluster_flow:** {der['is_cross_cluster_flow']}")

    if der["reachable_clusters"]:
        lines.append(f"- **reachable_clusters:** {', '.join(der['reachable_clusters'])}")
    lines.append("")

    if der["cluster_crossings"]:
        lines.append("**Cluster crossings:**")
        for cx in der["cluster_crossings"]:
            lines.append(
                f"  - {cx['source_cluster']} → {cx['target_cluster']} "
                f"| {cx['crossing_count']} crossing(s)"
            )
        lines.append("")

    if der["flow_depth_histogram"]:
        lines.append("**Flow depth histogram:**")
        for depth_str, count in sorted(
            der["flow_depth_histogram"].items(), key=lambda x: int(x[0])
        ):
            lines.append(f"  - depth {depth_str}: {count} node(s)")
        lines.append("")

    if flow["unknown"]:
        lines.append("## Unknown")
        lines.append("")
        for item in flow["unknown"]:
            lines.append(f"- {item}")
        lines.append("")

    return "\n".join(lines)


def write_flow_outputs(flow_map: dict, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    # Write flow_map.json
    json_path = output_dir / "flow_map.json"
    json_path.write_text(
        json.dumps(flow_map, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # Write flow_map.md
    md_path = output_dir / "flow_map.md"
    md_path.write_text(
        _build_flow_summary_markdown(flow_map),
        encoding="utf-8",
    )

    # Write per-flow breakdown files
    breakdowns_dir = output_dir / "flow_breakdowns"
    breakdowns_dir.mkdir(parents=True, exist_ok=True)

    for flow in flow_map["flows"]:
        safe_name = _sanitize_flow_id_for_filename(flow["flow_id"])
        breakdown_path = breakdowns_dir / f"{safe_name}.md"
        breakdown_path.write_text(
            _build_flow_breakdown_markdown(flow, flow_map),
            encoding="utf-8",
        )
