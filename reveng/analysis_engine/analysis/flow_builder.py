from __future__ import annotations

from collections import Counter, deque
from pathlib import PurePosixPath
from typing import Any


MAX_FLOW_DEPTH = 8
HUB_THRESHOLD = 5

_CALLABLE_NODE_TYPES = {"function", "async_function", "method", "async_method"}

ODU_CONVENTION = (
    "Observed: entrypoint functions identified from main_block_files in cluster_map; "
    "direct callee lists and call edge counts drawn directly from relation_map edges. "
    "Derived: reachable_node_count, max_depth_reached, cluster_crossings, is_hub, "
    "is_cross_cluster_flow, and flow membership fields computed by BFS over the call graph. "
    "Unknown: calls made through stored function references, dynamic dispatch, "
    "higher-order function targets, and any call targets absent from relation_map edges."
)


def _build_call_graph(
    nodes: list[dict],
    edges: list[dict],
    node_lookup: dict[str, dict],
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Return (forward_graph, reverse_graph) for calls edges only.

    Both graphs are pre-populated with empty lists for every callable node_id
    so callers never need to guard .get(). Multi-call sites to the same target
    are represented as repeated entries in the forward_graph list.
    """
    forward: dict[str, list[str]] = {}
    reverse: dict[str, list[str]] = {}

    for node in nodes:
        if node["node_type"] in _CALLABLE_NODE_TYPES:
            nid = node["node_id"]
            forward.setdefault(nid, [])
            reverse.setdefault(nid, [])

    for edge in edges:
        if edge["edge_type"] != "calls":
            continue
        src = edge["source_id"]
        tgt = edge["target_id"]
        if src not in node_lookup or tgt not in node_lookup:
            continue
        forward.setdefault(src, []).append(tgt)
        reverse.setdefault(tgt, []).append(src)

    return forward, reverse


def _assign_nodes_to_clusters(
    nodes: list[dict],
    cluster_map: dict,
) -> dict[str, str]:
    """Return node_id -> cluster_id for all nodes."""
    file_to_cluster: dict[str, str] = {}
    for cluster in cluster_map["clusters"]:
        cid = cluster["cluster_id"]
        for file_path in cluster["observed"]["files"]:
            file_to_cluster[file_path] = cid

    result: dict[str, str] = {}
    for node in nodes:
        result[node["node_id"]] = file_to_cluster.get(
            node["file_path"], "__unassigned__"
        )
    return result


def _find_entrypoint_functions(
    cluster_map: dict,
    node_lookup: dict[str, dict],
    forward_graph: dict[str, list[str]],
    reverse_graph: dict[str, list[str]],
) -> list[str]:
    """Return sorted list of entrypoint function node_ids.

    Pass 1: functions in main_block_files.
    Pass 2 (fallback): callable nodes with no inbound call edges.
    Returns [] if neither pass yields candidates.
    """
    main_files: set[str] = set()
    for cluster in cluster_map["clusters"]:
        for f in cluster["observed"]["main_block_files"]:
            main_files.add(f)

    candidates: set[str] = set()
    if main_files:
        for nid, node in node_lookup.items():
            if (
                node["node_type"] in _CALLABLE_NODE_TYPES
                and node["file_path"] in main_files
            ):
                candidates.add(nid)

    if not candidates:
        for nid in forward_graph:
            if len(reverse_graph.get(nid, [])) == 0:
                candidates.add(nid)

    return sorted(candidates)


def _bfs_reachable(
    start_id: str,
    forward_graph: dict[str, list[str]],
    max_depth: int,
) -> dict[str, int]:
    """BFS from start_id over the call graph.

    Returns {node_id: depth} for all reachable nodes, excluding start_id itself.
    Cycle-safe via visited set. Respects max_depth cap.
    """
    visited: set[str] = {start_id}
    reachable: dict[str, int] = {}
    queue: deque[tuple[str, int]] = deque()

    for neighbor in forward_graph.get(start_id, []):
        if neighbor not in visited:
            queue.append((neighbor, 1))

    while queue:
        nid, depth = queue.popleft()
        if nid in visited:
            continue
        visited.add(nid)
        reachable[nid] = depth
        if depth < max_depth:
            for neighbor in forward_graph.get(nid, []):
                if neighbor not in visited:
                    queue.append((neighbor, depth + 1))

    return reachable


def _classify_flow_type(
    root_node_id: str,
    main_files: set[str],
    reverse_graph: dict[str, list[str]],
    is_cross_cluster_flow: bool,
    reachable_node_count: int,
    node_lookup: dict[str, dict],
) -> str:
    """Classify a flow as entry_point, pipeline, or library.

    - entry_point: root function lives in a main_block file
    - pipeline: root has no inbound calls, spans clusters, and reaches ≥3 nodes
    - library: callable root with callers elsewhere (likely a reusable utility)
    """
    root_file = node_lookup.get(root_node_id, {}).get("file_path", "")
    if root_file in main_files:
        return "entry_point"
    inbound_count = len(reverse_graph.get(root_node_id, []))
    if inbound_count == 0 and is_cross_cluster_flow and reachable_node_count >= 3:
        return "pipeline"
    return "library"


def _build_flow_record(
    root_node_id: str,
    bfs_result: dict[str, int],
    node_lookup: dict[str, dict],
    forward_graph: dict[str, list[str]],
    reverse_graph: dict[str, list[str]],
    node_to_cluster: dict[str, str],
    unresolved_calls: list[dict],
    main_files: set[str],
) -> dict[str, Any]:
    """Build a single FlowRecord dict for one entrypoint function."""
    root_node = node_lookup[root_node_id]
    root_file = root_node["file_path"]
    root_cluster = node_to_cluster.get(root_node_id, "__unassigned__")

    # flow_id: make filename-safe by replacing : and /
    flow_id = root_node_id.replace(":", "__").replace("/", "__")

    # --- Observed ---
    raw_callees = forward_graph.get(root_node_id, [])
    direct_callees = sorted(set(raw_callees))
    direct_callee_count = len(direct_callees)
    total_call_edges_from_root = len(raw_callees)

    # --- Derived ---
    reachable_node_count = len(bfs_result)
    max_depth_reached = max(bfs_result.values(), default=0)

    reachable_set = set(bfs_result.keys()) | {root_node_id}

    reachable_clusters = sorted({
        node_to_cluster.get(nid, "__unassigned__")
        for nid in bfs_result
    })

    is_cross_cluster_flow = any(
        node_to_cluster.get(nid, "__unassigned__") != root_cluster
        for nid in bfs_result
    )

    # Cluster crossings: call edges where both endpoints are in the reachable set
    # and they belong to different clusters
    crossing_counter: Counter[tuple[str, str]] = Counter()
    for nid in reachable_set:
        src_cluster = node_to_cluster.get(nid, "__unassigned__")
        for callee in forward_graph.get(nid, []):
            if callee not in reachable_set:
                continue
            tgt_cluster = node_to_cluster.get(callee, "__unassigned__")
            if src_cluster != tgt_cluster:
                crossing_counter[(src_cluster, tgt_cluster)] += 1

    cluster_crossings = [
        {
            "source_cluster": src,
            "target_cluster": tgt,
            "crossing_count": count,
        }
        for (src, tgt), count in sorted(crossing_counter.items())
    ]

    depth_counter: Counter[int] = Counter(bfs_result.values())
    flow_depth_histogram = {
        str(d): depth_counter[d]
        for d in sorted(depth_counter)
    }

    # Cross-file direct callees: direct callees whose file differs from root_file
    cross_file_direct_callees = sorted({
        callee for callee in direct_callees
        if node_lookup.get(callee, {}).get("file_path", root_file) != root_file
    })

    # Flow type classification
    flow_type = _classify_flow_type(
        root_node_id,
        main_files,
        reverse_graph,
        is_cross_cluster_flow,
        reachable_node_count,
        node_lookup,
    )

    # --- Unknown ---
    unknowns: list[str] = []
    unresolved_in_flow = sum(
        1 for uc in unresolved_calls
        if uc.get("source_file") == root_file
        or (
            "source_scope" in uc
            and any(
                uc["source_file"] == node_lookup[nid]["file_path"]
                for nid in bfs_result
                if nid in node_lookup
            )
        )
    )
    if unresolved_in_flow:
        unknowns.append(
            f"{unresolved_in_flow} unresolved call(s) originate from files in this "
            f"flow's reachable set; their targets are not represented in this flow."
        )

    return {
        "flow_id": flow_id,
        "root_node_id": root_node_id,
        "root_file": root_file,
        "root_cluster": root_cluster,
        "observed": {
            "direct_callee_count": direct_callee_count,
            "direct_callees": direct_callees,
            "total_call_edges_from_root": total_call_edges_from_root,
        },
        "derived": {
            "flow_type": flow_type,
            "reachable_node_count": reachable_node_count,
            "max_depth_reached": max_depth_reached,
            "is_cross_cluster_flow": is_cross_cluster_flow,
            "cross_file_direct_callees": cross_file_direct_callees,
            "reachable_node_ids": sorted(bfs_result.keys()),
            "reachable_clusters": reachable_clusters,
            "cluster_crossings": cluster_crossings,
            "flow_depth_histogram": flow_depth_histogram,
        },
        "unknown": unknowns,
    }


def _compute_function_metrics(
    nodes: list[dict],
    edges: list[dict],
    bfs_results: dict[str, dict[str, int]],
    flow_id_by_root: dict[str, str],
    node_to_cluster: dict[str, str],
    unresolved_calls: list[dict],
) -> dict[str, dict[str, Any]]:
    """Compute per-function metrics for all callable nodes."""
    inbound: Counter[str] = Counter()
    outbound: Counter[str] = Counter()
    for edge in edges:
        if edge["edge_type"] == "calls":
            outbound[edge["source_id"]] += 1
            inbound[edge["target_id"]] += 1

    # Build set of source_files that have unresolved calls, for unknown detection
    unresolved_files: set[str] = {uc["source_file"] for uc in unresolved_calls}

    metrics: dict[str, dict[str, Any]] = {}
    for node in nodes:
        if node["node_type"] not in _CALLABLE_NODE_TYPES:
            continue
        nid = node["node_id"]
        in_count = inbound.get(nid, 0)
        out_count = outbound.get(nid, 0)

        appears_in_flows: dict[str, int] = {}
        for root_id, bfs_result in bfs_results.items():
            if nid in bfs_result:
                flow_id = flow_id_by_root[root_id]
                appears_in_flows[flow_id] = bfs_result[nid]

        unknowns: list[str] = []
        if node["file_path"] in unresolved_files:
            unknowns.append(
                "This function's file has unresolved outbound calls; "
                "some callee relationships may be missing."
            )

        metrics[nid] = {
            "node_id": nid,
            "file_path": node["file_path"],
            "cluster_id": node_to_cluster.get(nid, "__unassigned__"),
            "observed": {
                "inbound_call_count": in_count,
                "outbound_call_count": out_count,
            },
            "derived": {
                "is_hub": in_count >= HUB_THRESHOLD,
                "appears_in_flows": sorted(appears_in_flows.keys()),
                "flow_count": len(appears_in_flows),
                "max_depth_in_flow": {
                    fid: depth for fid, depth in sorted(appears_in_flows.items())
                },
            },
            "unknown": unknowns,
        }

    return metrics


def _build_cluster_flow_matrix(
    cluster_map: dict,
    flows: list[dict],
    node_to_cluster: dict[str, str],
    edges: list[dict],
) -> list[dict[str, Any]]:
    """Build cluster-level call-flow matrix.

    One entry per (source_cluster, target_cluster) pair with cross-cluster call edges.
    """
    call_edge_counts: Counter[tuple[str, str]] = Counter()
    for edge in edges:
        if edge["edge_type"] != "calls":
            continue
        src_cluster = node_to_cluster.get(edge["source_id"], "__unassigned__")
        tgt_cluster = node_to_cluster.get(edge["target_id"], "__unassigned__")
        if src_cluster != tgt_cluster:
            call_edge_counts[(src_cluster, tgt_cluster)] += 1

    crossings_by_pair: dict[tuple[str, str], set[str]] = {}
    for flow in flows:
        flow_id = flow["flow_id"]
        for crossing in flow["derived"]["cluster_crossings"]:
            pair = (crossing["source_cluster"], crossing["target_cluster"])
            crossings_by_pair.setdefault(pair, set()).add(flow_id)

    result: list[dict[str, Any]] = []
    for pair, count in sorted(call_edge_counts.items()):
        src, tgt = pair
        flow_ids = sorted(crossings_by_pair.get(pair, set()))
        result.append({
            "source_cluster": src,
            "target_cluster": tgt,
            "observed": {
                "cross_cluster_call_edge_count": count,
            },
            "derived": {
                "flow_ids_crossing": flow_ids,
                "flow_crossing_count": len(flow_ids),
            },
            "unknown": [],
        })

    return result


def build_flow_map(
    inventory: dict,
    relation_map: dict,
    cluster_map: dict,
) -> dict[str, Any]:
    """Build the flow map artifact.

    Consumes relation_map (nodes, edges) and cluster_map (clusters, cross_cluster_edges).
    Returns a dict with flows, function_metrics, cluster_flow_matrix, and unknowns.
    """
    nodes: list[dict] = relation_map["nodes"]
    edges: list[dict] = relation_map["edges"]
    unresolved_calls: list[dict] = relation_map.get("unresolved_calls", [])

    node_lookup: dict[str, dict] = {n["node_id"]: n for n in nodes}

    forward_graph, reverse_graph = _build_call_graph(nodes, edges, node_lookup)
    node_to_cluster = _assign_nodes_to_clusters(nodes, cluster_map)

    top_level_unknowns: list[str] = [
        "Calls made through stored function references, dynamic dispatch, and "
        "higher-order function targets are not tracked and represent connections "
        "invisible to this analysis.",
        "Any call targets not resolved by static AST analysis are absent from "
        "this flow map (present in relation_map unresolved_calls).",
    ]

    # Edge case: empty call graph
    has_calls = any(
        len(targets) > 0 for targets in forward_graph.values()
    )
    if not has_calls:
        # Phase 13: no-main-file / zero-resolved-calls heuristic.
        # Look for callable nodes with well-known entry-point names.
        # If found, synthesize a minimal flow so the workflow agent has an anchor.
        # All sibling callable nodes in the same file are included in reachable_node_ids
        # so the workflow agent can find action records across the whole module.
        _ENTRY_CANDIDATE_NAMES = frozenset({
            "invoke", "run", "execute", "dispatch", "handle", "process",
        })
        entry_candidates = [
            nid for nid, node in sorted(node_lookup.items())
            if node["node_type"] in _CALLABLE_NODE_TYPES
            and node.get("name", "").lower() in _ENTRY_CANDIDATE_NAMES
        ]

        if entry_candidates:
            top_level_unknowns.append(
                "No resolved call edges found; one or more synthesized entry_point flows "
                "created from entry-candidate function names (Phase 13 heuristic) as "
                "anchors for the workflow agent."
            )
            synthetic_flows: list[dict[str, Any]] = []
            for eid in entry_candidates:
                root_node = node_lookup[eid]
                root_file = root_node["file_path"]
                # Include all other callable nodes in the same file as reachable
                file_siblings = sorted(
                    nid2 for nid2, n2 in node_lookup.items()
                    if n2["file_path"] == root_file
                    and n2["node_type"] in _CALLABLE_NODE_TYPES
                    and nid2 != eid
                )
                synthetic_flows.append({
                    "flow_id": eid.replace(":", "__").replace("/", "__"),
                    "root_node_id": eid,
                    "root_file": root_file,
                    "root_cluster": node_to_cluster.get(eid, "__unassigned__"),
                    "observed": {
                        "direct_callee_count": 0,
                        "direct_callees": [],
                        "total_call_edges_from_root": 0,
                    },
                    "derived": {
                        "flow_type": "entry_point",
                        "reachable_node_count": len(file_siblings),
                        "max_depth_reached": 0,
                        "is_cross_cluster_flow": False,
                        "cross_file_direct_callees": [],
                        "reachable_node_ids": file_siblings,
                        "reachable_clusters": [],
                        "cluster_crossings": [],
                        "flow_depth_histogram": {},
                    },
                    "unknown": [
                        f"Synthesized flow: no resolved call edges; all callable nodes "
                        f"in {root_file} included as reachable (Phase 13 heuristic)."
                    ],
                })
            fn_metrics = _compute_function_metrics(
                nodes, edges, {}, {}, node_to_cluster, unresolved_calls
            )
            return {
                "repo_root": relation_map["repo_root"],
                "scanned_at": relation_map["scanned_at"],
                "flow_count": len(synthetic_flows),
                "entrypoint_count": len(synthetic_flows),
                "odu_convention": ODU_CONVENTION,
                "flows": synthetic_flows,
                "function_metrics": fn_metrics,
                "cluster_flow_matrix": [],
                "unknown": top_level_unknowns,
            }

        top_level_unknowns.append(
            "No resolved call edges found in relation_map; "
            "flow traversal was not performed."
        )
        return {
            "repo_root": relation_map["repo_root"],
            "scanned_at": relation_map["scanned_at"],
            "flow_count": 0,
            "entrypoint_count": 0,
            "odu_convention": ODU_CONVENTION,
            "flows": [],
            "function_metrics": _compute_function_metrics(
                nodes, edges, {}, {}, node_to_cluster, unresolved_calls
            ),
            "cluster_flow_matrix": [],
            "unknown": top_level_unknowns,
        }

    main_files: set[str] = set()
    for cluster in cluster_map["clusters"]:
        for f in cluster["observed"]["main_block_files"]:
            main_files.add(f)

    entrypoint_ids = _find_entrypoint_functions(
        cluster_map, node_lookup, forward_graph, reverse_graph
    )

    # Edge case: no entrypoints
    if not entrypoint_ids:
        top_level_unknowns.append(
            "No entrypoint functions identified; flow analysis requires at least one "
            "function in a main_block file or a call-graph root."
        )
        function_metrics = _compute_function_metrics(
            nodes, edges, {}, {}, node_to_cluster, unresolved_calls
        )
        cluster_flow_matrix = _build_cluster_flow_matrix(
            cluster_map, [], node_to_cluster, edges
        )
        return {
            "repo_root": relation_map["repo_root"],
            "scanned_at": relation_map["scanned_at"],
            "flow_count": 0,
            "entrypoint_count": 0,
            "odu_convention": ODU_CONVENTION,
            "flows": [],
            "function_metrics": function_metrics,
            "cluster_flow_matrix": cluster_flow_matrix,
            "unknown": top_level_unknowns,
        }

    # Build flows — compute BFS once per entrypoint, share results
    flows: list[dict] = []
    bfs_results: dict[str, dict[str, int]] = {}
    flow_id_by_root: dict[str, str] = {}

    for root_id in entrypoint_ids:
        bfs_result = _bfs_reachable(root_id, forward_graph, MAX_FLOW_DEPTH)
        bfs_results[root_id] = bfs_result
        flow = _build_flow_record(
            root_id,
            bfs_result,
            node_lookup,
            forward_graph,
            reverse_graph,
            node_to_cluster,
            unresolved_calls,
            main_files,
        )
        flows.append(flow)
        flow_id_by_root[root_id] = flow["flow_id"]

    function_metrics = _compute_function_metrics(
        nodes, edges, bfs_results, flow_id_by_root, node_to_cluster, unresolved_calls
    )
    cluster_flow_matrix = _build_cluster_flow_matrix(
        cluster_map, flows, node_to_cluster, edges
    )

    return {
        "repo_root": relation_map["repo_root"],
        "scanned_at": relation_map["scanned_at"],
        "flow_count": len(flows),
        "entrypoint_count": len(entrypoint_ids),
        "odu_convention": ODU_CONVENTION,
        "flows": flows,
        "function_metrics": function_metrics,
        "cluster_flow_matrix": cluster_flow_matrix,
        "unknown": top_level_unknowns,
    }
