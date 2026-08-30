from __future__ import annotations

import json
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any


def _sanitize_cluster_id_for_filename(cluster_id: str) -> str:
    """Convert a cluster ID to a safe filename by replacing path separators."""
    return cluster_id.replace("/", "__").replace("\\", "__")


def _cross_edge_summary_lines(
    cluster_id: str,
    cross_cluster_edges: list[dict[str, Any]],
) -> list[str]:
    """Produce grouped cross-cluster edge summary lines for one cluster."""
    lines: list[str] = []

    outbound = [e for e in cross_cluster_edges if e["source_cluster"] == cluster_id]
    inbound = [e for e in cross_cluster_edges if e["target_cluster"] == cluster_id]

    if outbound:
        lines.append("**Outbound cross-cluster edges (derived — based on cluster assignment):**")
        counts: Counter[tuple[str, str]] = Counter(
            (e["target_cluster"], e["edge_type"]) for e in outbound
        )
        for (target, etype), count in sorted(counts.items()):
            lines.append(f"  - → {target} | {etype} | {count} edge(s)")
        lines.append("")

    if inbound:
        lines.append("**Inbound cross-cluster edges (derived — based on cluster assignment):**")
        counts = Counter(
            (e["source_cluster"], e["edge_type"]) for e in inbound
        )
        for (source, etype), count in sorted(counts.items()):
            lines.append(f"  - ← {source} | {etype} | {count} edge(s)")
        lines.append("")

    return lines


def _build_cluster_summary_markdown(cluster_map: dict) -> str:
    lines: list[str] = []
    lines.append("# Subsystem Map")
    lines.append("")
    lines.append(f"Repo: {cluster_map['repo_root']}")
    lines.append(f"Scanned: {cluster_map['scanned_at']}")
    lines.append(f"Clusters: {cluster_map['cluster_count']}")
    lines.append(f"Clustering depth: {cluster_map['clustering_depth']}")
    lines.append(f"Cross-cluster edges: {len(cluster_map['cross_cluster_edges'])}")
    lines.append("")
    lines.append(f"**O/D/U Convention:** {cluster_map['odu_convention']}")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Clusters")
    lines.append("")

    for cluster in cluster_map["clusters"]:
        cid = cluster["cluster_id"]
        obs = cluster["observed"]
        der = cluster["derived"]
        unk = cluster["unknown"]

        lines.append(f"### {cid}")
        lines.append("")
        lines.append(f"- **Type (derived):** `{der['cluster_type']}`")
        lines.append(f"- **Type basis:** {der['cluster_type_basis']}")
        lines.append(f"- **Files (observed):** {obs['file_count']}")
        lines.append(f"- **Likely entrypoint (derived):** {der['is_likely_entrypoint']}")
        lines.append(f"- **Internal import edges (observed):** {obs['internal_import_edge_count']}")
        lines.append(f"- **Internal call edges (observed):** {obs['internal_call_edge_count']}")
        lines.append(f"- **Outbound cross-cluster edges (derived):** {der['outbound_cross_cluster_edge_count']}")
        lines.append(f"- **Inbound cross-cluster edges (derived):** {der['inbound_cross_cluster_edge_count']}")

        if der["connected_clusters"]:
            lines.append(f"- **Connected clusters (derived):** {', '.join(der['connected_clusters'])}")

        if obs["main_block_files"]:
            lines.append(f"- **Main block files (observed):** {', '.join(obs['main_block_files'])}")

        if unk:
            lines.append(f"- **Unknowns:** {'; '.join(unk)}")

        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## Repository-Level Unknowns")
    lines.append("")
    for item in cluster_map["unknown"]:
        lines.append(f"- {item}")
    lines.append("")

    return "\n".join(lines)


def _build_cluster_breakdown_markdown(
    cluster: dict,
    cross_cluster_edges: list[dict[str, Any]],
) -> str:
    cid = cluster["cluster_id"]
    obs = cluster["observed"]
    der = cluster["derived"]
    unk = cluster["unknown"]

    lines: list[str] = []
    lines.append(f"# Cluster: {cid}")
    lines.append("")

    lines.append("## Derived")
    lines.append("")
    lines.append(f"- **cluster_type:** `{der['cluster_type']}`")
    lines.append(f"- **cluster_type_basis:** {der['cluster_type_basis']}")
    lines.append(f"- **is_likely_entrypoint:** {der['is_likely_entrypoint']}")
    lines.append(f"- **outbound_cross_cluster_edge_count:** {der['outbound_cross_cluster_edge_count']}")
    lines.append(f"- **inbound_cross_cluster_edge_count:** {der['inbound_cross_cluster_edge_count']}")
    if der["connected_clusters"]:
        lines.append(f"- **connected_clusters:** {', '.join(der['connected_clusters'])}")
    lines.append("")

    lines.append("## Observed")
    lines.append("")
    lines.append(f"**file_count:** {obs['file_count']}")
    lines.append("")
    lines.append("**files:**")
    for f in obs["files"]:
        lines.append(f"  - {f}")
    lines.append("")

    if obs["main_block_files"]:
        lines.append("**main_block_files:**")
        for f in obs["main_block_files"]:
            lines.append(f"  - {f}")
        lines.append("")

    lines.append(f"**internal_import_edge_count:** {obs['internal_import_edge_count']}")
    lines.append(f"**internal_call_edge_count:** {obs['internal_call_edge_count']}")
    lines.append(f"**internal_contains_edge_count:** {obs['internal_contains_edge_count']}")
    lines.append("")

    cross_lines = _cross_edge_summary_lines(cid, cross_cluster_edges)
    if cross_lines:
        lines.append("## Cross-Cluster Edges")
        lines.append("")
        lines.extend(cross_lines)

    if unk:
        lines.append("## Unknown")
        lines.append("")
        for item in unk:
            lines.append(f"- {item}")
        lines.append("")

    return "\n".join(lines)


def write_cluster_outputs(cluster_map: dict, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    # Write subsystem_map.json
    json_path = output_dir / "subsystem_map.json"
    json_path.write_text(
        json.dumps(cluster_map, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # Write subsystem_map.md
    md_path = output_dir / "subsystem_map.md"
    md_path.write_text(
        _build_cluster_summary_markdown(cluster_map),
        encoding="utf-8",
    )

    # Write per-cluster breakdown files
    breakdowns_dir = output_dir / "subsystem_breakdowns"
    breakdowns_dir.mkdir(parents=True, exist_ok=True)

    for cluster in cluster_map["clusters"]:
        cluster_id = cluster["cluster_id"]
        safe_name = _sanitize_cluster_id_for_filename(cluster_id)
        breakdown_path = breakdowns_dir / f"{safe_name}.md"
        breakdown_path.write_text(
            _build_cluster_breakdown_markdown(cluster, cluster_map["cross_cluster_edges"]),
            encoding="utf-8",
        )
