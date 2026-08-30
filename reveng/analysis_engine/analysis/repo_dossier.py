from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import PurePosixPath
from typing import Any


def _top_level_folder(file_path: str) -> str:
    path = PurePosixPath(file_path)
    if len(path.parts) <= 1:
        return "__root__"
    return path.parts[0]


def _sorted_ranked(items: list[dict[str, Any]], key_name: str) -> list[dict[str, Any]]:
    return sorted(items, key=lambda item: (-item[key_name], item["path"]))


def _count_symbol_names(file_breakdowns: dict) -> list[dict[str, Any]]:
    symbol_to_files: dict[str, set[str]] = defaultdict(set)

    for file_record in file_breakdowns["files"]:
        if "parse_error" in file_record:
            continue
        for symbol in file_record.get("defined_symbols", []):
            symbol_to_files[symbol["name"]].add(file_record["path"])

    results: list[dict[str, Any]] = []
    for name, paths in symbol_to_files.items():
        if len(paths) > 1:
            results.append(
                {
                    "symbol_name": name,
                    "file_count": len(paths),
                    "files": sorted(paths),
                }
            )

    return sorted(results, key=lambda item: (-item["file_count"], item["symbol_name"]))


def _group_files_by_top_folder(file_breakdowns: dict) -> list[dict[str, Any]]:
    groups: dict[str, list[str]] = defaultdict(list)

    for file_record in file_breakdowns["files"]:
        groups[_top_level_folder(file_record["path"])].append(file_record["path"])

    results = []
    for folder, files in groups.items():
        results.append(
            {
                "folder": folder,
                "file_count": len(files),
                "files": sorted(files),
            }
        )

    return sorted(results, key=lambda item: (-item["file_count"], item["folder"]))


def _rank_files(file_breakdowns: dict) -> dict[str, list[dict[str, Any]]]:
    no_symbol_files: list[dict[str, Any]] = []
    main_block_files: list[dict[str, Any]] = []
    outbound_import_rank: list[dict[str, Any]] = []
    outbound_call_rank: list[dict[str, Any]] = []
    inbound_call_rank: list[dict[str, Any]] = []
    unresolved_call_rank: list[dict[str, Any]] = []
    unresolved_import_rank: list[dict[str, Any]] = []
    symbol_count_rank: list[dict[str, Any]] = []

    for file_record in file_breakdowns["files"]:
        if "parse_error" in file_record:
            continue

        path = file_record["path"]
        defined_symbols = file_record.get("defined_symbols", [])
        outbound_import_edges = file_record.get("outbound_import_edges", [])
        outbound_call_edges = file_record.get("outbound_call_edges", [])
        inbound_call_edges = file_record.get("inbound_call_edges", [])
        unresolved_calls = file_record.get("unresolved_calls", [])
        unresolved_imports = file_record.get("unresolved_imports", [])

        if not defined_symbols:
            no_symbol_files.append({"path": path, "count": 0})

        if file_record.get("main_block_present"):
            main_block_files.append({"path": path, "count": 1})

        outbound_import_rank.append({"path": path, "count": len(outbound_import_edges)})
        outbound_call_rank.append({"path": path, "count": len(outbound_call_edges)})
        inbound_call_rank.append({"path": path, "count": len(inbound_call_edges)})
        unresolved_call_rank.append({"path": path, "count": len(unresolved_calls)})
        unresolved_import_rank.append({"path": path, "count": len(unresolved_imports)})
        symbol_count_rank.append({"path": path, "count": len(defined_symbols)})

    return {
        "files_with_no_symbols": _sorted_ranked(no_symbol_files, "count"),
        "files_with_main_blocks": sorted(main_block_files, key=lambda item: item["path"]),
        "top_outbound_import_files": _sorted_ranked(outbound_import_rank, "count"),
        "top_outbound_call_files": _sorted_ranked(outbound_call_rank, "count"),
        "top_inbound_call_files": _sorted_ranked(inbound_call_rank, "count"),
        "top_unresolved_call_files": _sorted_ranked(unresolved_call_rank, "count"),
        "top_unresolved_import_files": _sorted_ranked(unresolved_import_rank, "count"),
        "top_symbol_count_files": _sorted_ranked(symbol_count_rank, "count"),
    }


def _top_defined_symbols(file_breakdowns: dict) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    for file_record in file_breakdowns["files"]:
        if "parse_error" in file_record:
            continue

        symbol_counter = Counter()
        for symbol in file_record.get("defined_symbols", []):
            symbol_counter[symbol["symbol_type"]] += 1

        results.append(
            {
                "path": file_record["path"],
                "total_symbols": len(file_record.get("defined_symbols", [])),
                "symbol_type_counts": dict(sorted(symbol_counter.items())),
            }
        )

    return sorted(results, key=lambda item: (-item["total_symbols"], item["path"]))


def _build_architecture_section(cluster_map: dict, flow_map: dict) -> dict:
    """Extract cluster/flow architectural overview for the dossier."""
    clusters = cluster_map.get("clusters", [])
    cross_cluster_edges = cluster_map.get("cross_cluster_edges", [])
    flows = flow_map.get("flows", [])
    function_metrics = flow_map.get("function_metrics", {})

    # Flows rooted per cluster
    flows_rooted: dict[str, int] = Counter()
    for flow in flows:
        if flow.get("root_cluster"):
            flows_rooted[flow["root_cluster"]] += 1

    cluster_summaries: list[dict[str, Any]] = []
    for cluster in sorted(clusters, key=lambda c: c["cluster_id"]):
        cid = cluster["cluster_id"]
        obs = cluster["observed"]
        der = cluster["derived"]
        cluster_summaries.append({
            "cluster_id": cid,
            "cluster_type": der["cluster_type"],
            "is_likely_entrypoint": der["is_likely_entrypoint"],
            "file_count": obs["file_count"],
            "connected_clusters": der["connected_clusters"],
            "flows_rooted_here": flows_rooted.get(cid, 0),
        })

    # Hub functions sorted by inbound_call_count desc, then node_id
    hub_functions: list[dict[str, Any]] = []
    for node_id, metric in function_metrics.items():
        if metric["derived"].get("is_hub"):
            hub_functions.append({
                "node_id": node_id,
                "file_path": metric["file_path"],
                "inbound_call_count": metric["observed"]["inbound_call_count"],
                "outbound_call_count": metric["observed"]["outbound_call_count"],
                "appears_in_flow_count": len(metric["derived"].get("appears_in_flows", [])),
            })
    hub_functions.sort(key=lambda h: (-h["inbound_call_count"], h["node_id"]))

    # Entry flows
    entry_flows: list[dict[str, Any]] = []
    for flow in flows:
        der = flow.get("derived", {})
        reachable_clusters = der.get("reachable_clusters", [])
        entry_flows.append({
            "flow_id": flow["flow_id"],
            "root_node_id": flow["root_node_id"],
            "root_cluster": flow.get("root_cluster", ""),
            "reachable_node_count": der.get("reachable_node_count", 0),
            "max_depth_reached": der.get("max_depth_reached", 0),
            "is_cross_cluster_flow": der.get("is_cross_cluster_flow", False),
            "reachable_cluster_count": len(reachable_clusters),
        })
    entry_flows.sort(key=lambda f: (-f["reachable_node_count"], f["flow_id"]))

    cluster_flow_matrix = flow_map.get("cluster_flow_matrix", [])

    return {
        "cluster_count": len(clusters),
        "clustering_depth": cluster_map.get("clustering_depth", 0),
        "cross_cluster_edge_count": len(cross_cluster_edges),
        "flow_count": len(flows),
        "hub_function_count": len(hub_functions),
        "clusters": cluster_summaries,
        "hub_functions": hub_functions,
        "entry_flows": entry_flows,
        "cluster_flow_matrix": cluster_flow_matrix,
    }


def build_repo_dossier(
    inventory: dict,
    relation_map: dict,
    file_breakdowns: dict,
    cluster_map: dict | None = None,
    flow_map: dict | None = None,
) -> dict:
    files_with_parse_errors = [
        {
            "path": file_record["path"],
            "parse_error": file_record["parse_error"],
        }
        for file_record in inventory["files"]
        if "parse_error" in file_record
    ]

    folder_groups = _group_files_by_top_folder(file_breakdowns)
    ranked = _rank_files(file_breakdowns)
    repeated_symbol_names = _count_symbol_names(file_breakdowns)
    top_defined_symbols = _top_defined_symbols(file_breakdowns)

    unresolved_call_category_counts = dict(
        sorted(
            Counter(
                item.get("category", "unclassified")
                for item in relation_map.get("unresolved_calls", [])
            ).items()
        )
    )

    external_call_category_counts = dict(
        sorted(
            Counter(
                item.get("category", "external")
                for item in relation_map.get("external_calls", [])
            ).items()
        )
    )

    dossier: dict[str, Any] = {
        "repo_root": inventory["repo_root"],
        "scanned_at": inventory["scanned_at"],
        "file_count": inventory["file_count"],
        "relation_node_count": relation_map["node_count"],
        "relation_edge_count": relation_map["edge_count"],
        "breakdown_count": file_breakdowns["breakdown_count"],
        "parse_error_count": len(files_with_parse_errors),
        "files_with_parse_errors": files_with_parse_errors,
        "files_grouped_by_top_level_folder": folder_groups,
        "files_with_no_symbols": ranked["files_with_no_symbols"],
        "files_with_main_blocks": ranked["files_with_main_blocks"],
        "top_outbound_import_files": ranked["top_outbound_import_files"],
        "top_outbound_call_files": ranked["top_outbound_call_files"],
        "top_inbound_call_files": ranked["top_inbound_call_files"],
        "top_unresolved_call_files": ranked["top_unresolved_call_files"],
        "top_unresolved_import_files": ranked["top_unresolved_import_files"],
        "top_symbol_count_files": ranked["top_symbol_count_files"],
        "top_defined_symbols_by_file": top_defined_symbols,
        "repeated_symbol_names_across_files": repeated_symbol_names,
        "unresolved_call_count": len(relation_map.get("unresolved_calls", [])),
        "unresolved_import_count": len(relation_map.get("unresolved_imports", [])),
        "external_import_count": len(relation_map.get("external_imports", [])),
        "external_call_count": len(relation_map.get("external_calls", [])),
        "unresolved_call_category_counts": unresolved_call_category_counts,
        "external_call_category_counts": external_call_category_counts,
    }

    if cluster_map is not None and flow_map is not None:
        dossier["architecture"] = _build_architecture_section(cluster_map, flow_map)

    return dossier