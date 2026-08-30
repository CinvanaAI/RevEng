from __future__ import annotations

import json
from pathlib import Path


def write_repo_dossier_outputs(repo_dossier: dict, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / "repo_dossier.json"
    md_path = output_dir / "repo_dossier.md"

    json_path.write_text(
        json.dumps(repo_dossier, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    md_path.write_text(build_repo_dossier_markdown(repo_dossier), encoding="utf-8")


def _write_ranked_section(lines: list[str], title: str, items: list[dict], limit: int = 15) -> None:
    lines.append(f"## {title}")
    lines.append("")
    if items:
        for item in items[:limit]:
            if "count" in item:
                lines.append(f"- `{item['path']}` — {item['count']}")
            else:
                lines.append(f"- `{item['path']}`")
    else:
        lines.append("- None")
    lines.append("")


def _write_count_map_section(lines: list[str], title: str, mapping: dict[str, int]) -> None:
    lines.append(f"## {title}")
    lines.append("")
    if mapping:
        for key, value in sorted(mapping.items(), key=lambda item: (-item[1], item[0])):
            lines.append(f"- `{key}` — {value}")
    else:
        lines.append("- None")
    lines.append("")


def build_repo_dossier_markdown(repo_dossier: dict) -> str:
    lines: list[str] = []

    lines.append("# Repo Dossier")
    lines.append("")
    lines.append(f"- Repo root: `{repo_dossier['repo_root']}`")
    lines.append(f"- Scanned at: `{repo_dossier['scanned_at']}`")
    lines.append(f"- Python files scanned: `{repo_dossier['file_count']}`")
    lines.append(f"- Relation node count: `{repo_dossier['relation_node_count']}`")
    lines.append(f"- Relation edge count: `{repo_dossier['relation_edge_count']}`")
    lines.append(f"- Breakdown count: `{repo_dossier['breakdown_count']}`")
    lines.append(f"- Parse error count: `{repo_dossier['parse_error_count']}`")
    lines.append(f"- Unresolved import count: `{repo_dossier['unresolved_import_count']}`")
    lines.append(f"- Unresolved call count: `{repo_dossier['unresolved_call_count']}`")
    lines.append(f"- External import count: `{repo_dossier['external_import_count']}`")
    lines.append(f"- External call count: `{repo_dossier['external_call_count']}`")
    lines.append("")

    lines.append("## Files Grouped by Top-Level Folder")
    lines.append("")
    if repo_dossier["files_grouped_by_top_level_folder"]:
        for group in repo_dossier["files_grouped_by_top_level_folder"]:
            lines.append(f"- `{group['folder']}` — {group['file_count']} files")
    else:
        lines.append("- None")
    lines.append("")

    _write_count_map_section(lines, "Unresolved Call Categories", repo_dossier["unresolved_call_category_counts"])
    _write_count_map_section(lines, "External Call Categories", repo_dossier["external_call_category_counts"])

    _write_ranked_section(lines, "Files With No Symbols", repo_dossier["files_with_no_symbols"])
    _write_ranked_section(lines, "Files With Main Blocks", repo_dossier["files_with_main_blocks"])
    _write_ranked_section(lines, "Top Outbound Import Files", repo_dossier["top_outbound_import_files"])
    _write_ranked_section(lines, "Top Outbound Call Files", repo_dossier["top_outbound_call_files"])
    _write_ranked_section(lines, "Top Inbound Call Files", repo_dossier["top_inbound_call_files"])
    _write_ranked_section(lines, "Top Unresolved Call Files", repo_dossier["top_unresolved_call_files"])
    _write_ranked_section(lines, "Top Unresolved Import Files", repo_dossier["top_unresolved_import_files"])
    _write_ranked_section(lines, "Top Symbol Count Files", repo_dossier["top_symbol_count_files"])

    lines.append("## Top Defined Symbols By File")
    lines.append("")
    if repo_dossier["top_defined_symbols_by_file"]:
        for item in repo_dossier["top_defined_symbols_by_file"][:15]:
            lines.append(
                f"- `{item['path']}` — total_symbols={item['total_symbols']} "
                f"| symbol_type_counts={item['symbol_type_counts']}"
            )
    else:
        lines.append("- None")
    lines.append("")

    lines.append("## Repeated Symbol Names Across Files")
    lines.append("")
    if repo_dossier["repeated_symbol_names_across_files"]:
        for item in repo_dossier["repeated_symbol_names_across_files"][:25]:
            lines.append(
                f"- `{item['symbol_name']}` — {item['file_count']} files"
            )
    else:
        lines.append("- None")
    lines.append("")

    lines.append("## Files With Parse Errors")
    lines.append("")
    if repo_dossier["files_with_parse_errors"]:
        for item in repo_dossier["files_with_parse_errors"]:
            lines.append(f"- `{item['path']}` — {item['parse_error']}")
    else:
        lines.append("- None")
    lines.append("")

    arch = repo_dossier.get("architecture")
    if arch:
        lines.append("## Architecture Overview")
        lines.append("")
        lines.append(f"- Cluster count: `{arch['cluster_count']}`")
        lines.append(f"- Clustering depth: `{arch['clustering_depth']}`")
        lines.append(f"- Cross-cluster edge count: `{arch['cross_cluster_edge_count']}`")
        lines.append(f"- Flow count: `{arch['flow_count']}`")
        lines.append(f"- Hub function count: `{arch['hub_function_count']}`")
        lines.append("")

        lines.append("## Clusters")
        lines.append("")
        if arch["clusters"]:
            for cluster in arch["clusters"]:
                connected = ", ".join(cluster["connected_clusters"]) or "none"
                lines.append(
                    f"- `{cluster['cluster_id']}` — {cluster['cluster_type']}, "
                    f"{cluster['file_count']} files, "
                    f"entrypoint={cluster['is_likely_entrypoint']}, "
                    f"flows_rooted={cluster['flows_rooted_here']}, "
                    f"connected=[{connected}]"
                )
        else:
            lines.append("- None")
        lines.append("")

        lines.append("## Entry Flows")
        lines.append("")
        if arch["entry_flows"]:
            for flow in arch["entry_flows"][:20]:
                cross = "cross-cluster" if flow["is_cross_cluster_flow"] else "single-cluster"
                lines.append(
                    f"- `{flow['flow_id']}` — root_cluster={flow['root_cluster']}, "
                    f"reachable={flow['reachable_node_count']} nodes, "
                    f"depth={flow['max_depth_reached']}, "
                    f"clusters={flow['reachable_cluster_count']}, {cross}"
                )
        else:
            lines.append("- None")
        lines.append("")

        lines.append("## Hub Functions")
        lines.append("")
        if arch["hub_functions"]:
            for hub in arch["hub_functions"][:20]:
                lines.append(
                    f"- `{hub['node_id']}` — inbound={hub['inbound_call_count']}, "
                    f"outbound={hub['outbound_call_count']}, "
                    f"appears_in_flows={hub['appears_in_flow_count']}"
                )
        else:
            lines.append("- None")
        lines.append("")

        lines.append("## Cluster Flow Matrix")
        lines.append("")
        if arch["cluster_flow_matrix"]:
            for entry in arch["cluster_flow_matrix"]:
                lines.append(
                    f"- `{entry['source_cluster']}` → `{entry['target_cluster']}` — "
                    f"crossing_count={entry['observed']['cross_cluster_call_edge_count']}, "
                    f"flow_count={entry['derived']['flow_crossing_count']}"
                )
        else:
            lines.append("- None")
        lines.append("")

    return "\n".join(lines)