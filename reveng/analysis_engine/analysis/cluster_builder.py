from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any


# O/D/U convention for this layer:
# Observed  — file lists and edge lists taken directly from inventory and relation_map inputs.
# Derived   — cluster_type, cluster_type_basis, is_likely_entrypoint, and connected_clusters
#             inferred from file path structure, file names, and main_block presence.
# Unknown   — dynamic imports, runtime-conditional imports, and any connections not visible
#             from static AST analysis.
ODU_CONVENTION = (
    "Observed: file membership and edge counts drawn directly from inventory and relation_map. "
    "Derived: cluster_type and cluster_type_basis inferred from file path structure, file names, "
    "and main_block presence. is_likely_entrypoint is derived from main_block detection. "
    "connected_clusters is derived from cross-cluster edge analysis. "
    "Unknown: dynamic imports, runtime-conditional imports, and any connections not visible "
    "from static AST analysis."
)

# If any single cluster holds more than this fraction of all files, try a deeper split.
_SINGLE_CLUSTER_THRESHOLD = 0.75
_MAX_CLUSTER_DEPTH = 6


def _cluster_id_from_path(file_path: str, depth: int) -> str:
    """Return the cluster ID for a file at the given path depth.

    The cluster ID is the file's directory path truncated to `depth` segments.
    The filename itself is never included. Files at repo root always return '__root__'.

    Examples at depth=2:
      'run.py'                         -> '__root__'
      'reveng/scanner.py'              -> 'reveng'          (only 1 dir segment, depth capped)
      'src/api/routes.py'              -> 'src/api'
      'src/api/v2/handlers.py'         -> 'src/api'
    """
    parts = PurePosixPath(file_path).parts
    if len(parts) <= 1:
        return "__root__"
    dir_depth = min(depth, len(parts) - 1)
    return "/".join(parts[:dir_depth])


def _select_cluster_depth(inventory: dict) -> int:
    """Find the minimum depth that avoids a single cluster dominating the repo.

    Raises depth from 1 upward until no cluster holds more than
    _SINGLE_CLUSTER_THRESHOLD of all files, or until deeper splits become
    structurally impossible (all files are already at the current depth).
    """
    all_paths = [f["path"] for f in inventory["files"]]
    total = len(all_paths)

    if total == 0:
        return 1

    for depth in range(1, _MAX_CLUSTER_DEPTH + 1):
        counts: dict[str, int] = {}
        for path in all_paths:
            cid = _cluster_id_from_path(path, depth)
            counts[cid] = counts.get(cid, 0) + 1

        max_fraction = max(counts.values()) / total
        if max_fraction <= _SINGLE_CLUSTER_THRESHOLD:
            return depth

        # Check whether increasing depth would actually change any assignment.
        # A file can be split further only if it has more directory segments than
        # the current depth (i.e., it lives deeper in the tree).
        can_improve = any(
            len(PurePosixPath(p).parts) - 1 > depth
            for p in all_paths
        )
        if not can_improve:
            return depth

    return _MAX_CLUSTER_DEPTH


def _classify_structural_role(
    outbound_cross_count: int,
    inbound_cross_count: int,
    internal_call_count: int,
    has_main_blocks: bool,
) -> str:
    """Classify the structural role of a cluster based on call-flow ratios.

    This is augmentation metadata — it does not replace the path-prefix cluster_type.
    Classification is derived from edge counts; file content is never read.

    Roles:
    - entrypoint_driver  : has main-block files and outbound cross-cluster calls
    - orchestrator       : high outbound relative to inbound (calls many, called by few)
    - library            : high inbound relative to outbound (called by many, calls few)
    - utility            : moderate cross-cluster traffic in both directions
    - isolated           : low external traffic, mostly self-contained
    """
    if has_main_blocks and outbound_cross_count > 0:
        return "entrypoint_driver"
    total_cross = outbound_cross_count + inbound_cross_count
    if total_cross == 0:
        return "isolated"
    outbound_ratio = outbound_cross_count / total_cross
    if outbound_ratio >= 0.75:
        return "orchestrator"
    if outbound_ratio <= 0.25:
        return "library"
    return "utility"


def _classify_cluster_type(
    cluster_id: str,
    files: list[str],
    main_block_files: list[str],
) -> tuple[str, str]:
    """Return (cluster_type, cluster_type_basis). Both values are derived.

    Classification is heuristic: file path structure and names only.
    File content is not read. main_block_present comes from the inventory.

    For multi-segment cluster IDs (e.g. 'src/api/routes'), the last segment
    is used for name-based keyword matching.
    """
    if cluster_id == "__root__":
        if main_block_files:
            return (
                "entrypoint",
                "root-level files contain if __name__ == '__main__' blocks",
            )
        return "root_scripts", "root-level files with no detected main blocks"

    last_segment = PurePosixPath(cluster_id).name.lower()
    file_names = [PurePosixPath(f).name.lower() for f in files]

    if "test" in last_segment:
        return "test_suite", f"cluster name '{last_segment}' contains 'test'"

    test_count = sum(1 for n in file_names if n.startswith("test_") or n.endswith("_test.py"))
    if files and test_count > len(files) * 0.5:
        return "test_suite", "majority of files are named as test files"

    writer_count = sum(1 for n in file_names if "writer" in n or "output" in n)
    if files and writer_count > len(files) * 0.5:
        return "output_layer", "majority of files contain 'writer' or 'output' in name"

    config_keywords = {"config", "settings", "env", "constants", "conf"}
    config_count = sum(1 for n in file_names if any(kw in n for kw in config_keywords))
    if files and config_count > len(files) * 0.5:
        return "config_layer", "majority of files are configuration-related by name"

    if main_block_files:
        return "package_with_entrypoints", f"cluster '{last_segment}' contains files with main blocks"

    return "core_package", f"directory '{last_segment}' without specific role indicators in file names"


def build_cluster_map(inventory: dict, relation_map: dict) -> dict:
    """Group files into clusters and produce the subsystem map artifact.

    Each cluster record has explicit 'observed', 'derived', and 'unknown' keys
    following the O/D/U convention documented in ODU_CONVENTION.

    Clustering depth is selected adaptively: the minimum depth at which no single
    cluster holds more than _SINGLE_CLUSTER_THRESHOLD of all files. The chosen
    depth is recorded in the output as 'clustering_depth'.
    """
    # --- Derived: select depth before any clustering ---
    depth = _select_cluster_depth(inventory)

    # --- Observed: build file-level index from inventory ---
    file_main_blocks: dict[str, bool] = {}
    for file_record in inventory["files"]:
        path = file_record["path"]
        if "parse_error" not in file_record:
            file_main_blocks[path] = file_record.get("main_block_present", False)
        else:
            file_main_blocks[path] = False

    parse_error_paths: set[str] = {
        rec["path"] for rec in inventory["files"] if "parse_error" in rec
    }

    # --- Observed: assign files to clusters at the selected depth ---
    file_to_cluster: dict[str, str] = {
        file_record["path"]: _cluster_id_from_path(file_record["path"], depth)
        for file_record in inventory["files"]
    }

    clusters_files: dict[str, list[str]] = {}
    for file_path, cluster_id in file_to_cluster.items():
        clusters_files.setdefault(cluster_id, []).append(file_path)

    # --- Observed: build node lookup and partition edges ---
    node_lookup: dict[str, dict[str, Any]] = {
        node["node_id"]: node for node in relation_map["nodes"]
    }

    internal_edges_by_cluster: dict[str, list[dict[str, Any]]] = {}
    cross_cluster_edges: list[dict[str, Any]] = []

    for edge in relation_map["edges"]:
        source_node = node_lookup.get(edge["source_id"])
        target_node = node_lookup.get(edge["target_id"])

        if not source_node or not target_node:
            continue

        source_cluster = file_to_cluster.get(source_node["file_path"])
        target_cluster = file_to_cluster.get(target_node["file_path"])

        if source_cluster is None or target_cluster is None:
            continue

        if source_cluster == target_cluster:
            internal_edges_by_cluster.setdefault(source_cluster, []).append(edge)
        else:
            # 'contains' edges are always intra-file and therefore always internal.
            # Guard here in case future edge types change that assumption.
            if edge["edge_type"] != "contains":
                cross_cluster_edges.append({
                    "edge_type": edge["edge_type"],
                    "source_file": source_node["file_path"],
                    "source_cluster": source_cluster,
                    "target_file": target_node["file_path"],
                    "target_cluster": target_cluster,
                    "evidence": edge["evidence"],
                    "lineno": edge["lineno"],
                    "end_lineno": edge["end_lineno"],
                })

    cross_cluster_edges.sort(
        key=lambda e: (e["source_cluster"], e["target_cluster"], e["source_file"])
    )

    # --- Build cluster records ---
    cluster_records: list[dict[str, Any]] = []

    for cluster_id, files in sorted(clusters_files.items()):
        sorted_files = sorted(files)
        main_block_files = sorted(f for f in files if file_main_blocks.get(f, False))

        # Derived: classify type
        cluster_type, type_basis = _classify_cluster_type(cluster_id, sorted_files, main_block_files)

        # Observed: internal edges
        internal_edges = internal_edges_by_cluster.get(cluster_id, [])
        internal_import_count = sum(1 for e in internal_edges if e["edge_type"] == "imports")
        internal_call_count = sum(1 for e in internal_edges if e["edge_type"] == "calls")
        internal_contains_count = sum(1 for e in internal_edges if e["edge_type"] == "contains")

        # Derived: cross-cluster edges involving this cluster
        cluster_cross = [
            e for e in cross_cluster_edges
            if e["source_cluster"] == cluster_id or e["target_cluster"] == cluster_id
        ]
        outbound_cross_count = sum(1 for e in cluster_cross if e["source_cluster"] == cluster_id)
        inbound_cross_count = sum(1 for e in cluster_cross if e["target_cluster"] == cluster_id)

        connected: list[str] = sorted({
            e["target_cluster"] if e["source_cluster"] == cluster_id else e["source_cluster"]
            for e in cluster_cross
        })

        # Unknown: parse errors within this cluster
        unknowns: list[str] = []
        errored = sorted(f for f in sorted_files if f in parse_error_paths)
        if errored:
            unknowns.append(
                f"Parse errors prevented full analysis of: {', '.join(errored)}"
            )

        structural_role = _classify_structural_role(
            outbound_cross_count,
            inbound_cross_count,
            internal_call_count,
            bool(main_block_files),
        )

        cluster_records.append({
            "cluster_id": cluster_id,
            "observed": {
                "files": sorted_files,
                "file_count": len(sorted_files),
                "internal_import_edge_count": internal_import_count,
                "internal_call_edge_count": internal_call_count,
                "internal_contains_edge_count": internal_contains_count,
                "main_block_files": main_block_files,
            },
            "derived": {
                "cluster_type": cluster_type,
                "cluster_type_basis": type_basis,
                "is_likely_entrypoint": bool(main_block_files) or cluster_id == "__root__",
                "structural_role": structural_role,
                "outbound_cross_cluster_edge_count": outbound_cross_count,
                "inbound_cross_cluster_edge_count": inbound_cross_count,
                "connected_clusters": connected,
            },
            "unknown": unknowns,
        })

    return {
        "repo_root": inventory["repo_root"],
        "scanned_at": inventory["scanned_at"],
        "cluster_count": len(cluster_records),
        "clustering_depth": depth,
        "odu_convention": ODU_CONVENTION,
        "clusters": cluster_records,
        "cross_cluster_edges": cross_cluster_edges,
        "unknown": [
            "Dynamic imports are not tracked and represent connections invisible to this analysis.",
            "Imports inside function bodies or conditional blocks are recorded but their "
            "runtime activation is unknown.",
        ],
    }
