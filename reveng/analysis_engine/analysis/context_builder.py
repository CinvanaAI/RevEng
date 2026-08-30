from __future__ import annotations

from typing import Any


def build_per_file_context(cluster_map: dict, flow_map: dict) -> dict[str, dict]:
    """Build a per-file structural context dict from cluster_map and flow_map.

    Returns {file_path: context_dict}. Files absent from cluster_map (e.g. parse errors)
    are absent from the result. Callers should use .get(file_path, {}).
    """
    # a. Map file_path -> cluster record
    file_to_cluster_record: dict[str, dict] = {}
    for cluster in cluster_map.get("clusters", []):
        for file_path in cluster["observed"]["files"]:
            file_to_cluster_record[file_path] = cluster

    # b. Map file_path -> list of hub function node_ids
    file_to_hub_functions: dict[str, list[str]] = {}
    for metric in flow_map.get("function_metrics", {}).values():
        if metric["derived"]["is_hub"]:
            fp = metric["file_path"]
            file_to_hub_functions.setdefault(fp, []).append(metric["node_id"])

    # c. Map file_path -> set of flow_ids where functions in this file appear
    file_to_flow_ids: dict[str, set[str]] = {}
    for metric in flow_map.get("function_metrics", {}).values():
        fp = metric["file_path"]
        for fid in metric["derived"].get("appears_in_flows", []):
            file_to_flow_ids.setdefault(fp, set()).add(fid)

    # d. Map file_path -> cross-cluster edge summaries
    file_to_outbound: dict[str, dict[str, dict[str, int]]] = {}
    file_to_inbound: dict[str, dict[str, dict[str, int]]] = {}
    for edge in cluster_map.get("cross_cluster_edges", []):
        etype = edge["edge_type"]
        src_file = edge["source_file"]
        tgt_cluster = edge["target_cluster"]
        tgt_file = edge["target_file"]
        src_cluster = edge["source_cluster"]

        # outbound for source file
        ob = file_to_outbound.setdefault(src_file, {}).setdefault(
            tgt_cluster, {"imports": 0, "calls": 0}
        )
        ob[etype] = ob.get(etype, 0) + 1

        # inbound for target file
        ib = file_to_inbound.setdefault(tgt_file, {}).setdefault(
            src_cluster, {"imports": 0, "calls": 0}
        )
        ib[etype] = ib.get(etype, 0) + 1

    # e. Assemble per-file context
    result: dict[str, dict[str, Any]] = {}
    for file_path, cluster in file_to_cluster_record.items():
        obs = cluster["observed"]
        der = cluster["derived"]
        result[file_path] = {
            "cluster_id": cluster["cluster_id"],
            "cluster_type": der["cluster_type"],
            "is_likely_entrypoint": der["is_likely_entrypoint"],
            "cluster_file_count": obs["file_count"],
            "cluster_internal_call_edge_count": obs["internal_call_edge_count"],
            "cluster_connected_clusters": der["connected_clusters"],
            "hub_functions_in_file": sorted(
                file_to_hub_functions.get(file_path, [])
            ),
            "flow_ids_containing_file": sorted(
                file_to_flow_ids.get(file_path, set())
            ),
            "cross_cluster_outbound": file_to_outbound.get(file_path, {}),
            "cross_cluster_inbound": file_to_inbound.get(file_path, {}),
        }

    return result
