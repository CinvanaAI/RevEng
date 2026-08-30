from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _check_files_accounted_for(
    inventory: dict,
    file_breakdowns: dict,
) -> dict[str, Any]:
    inv_paths = {f["path"] for f in inventory["files"]}
    bd_paths = {f["path"] for f in file_breakdowns["files"]}

    missing_from_breakdowns = sorted(inv_paths - bd_paths)
    extra_in_breakdowns = sorted(bd_paths - inv_paths)

    details: list[str] = []
    for p in missing_from_breakdowns:
        details.append(f"In inventory but missing from file_breakdowns: {p}")
    for p in extra_in_breakdowns:
        details.append(f"In file_breakdowns but missing from inventory: {p}")

    if details:
        return {
            "check_id": "files_accounted_for",
            "status": "fail",
            "message": f"{len(details)} file accounting mismatch(es) between inventory and file_breakdowns.",
            "details": details,
        }
    return {
        "check_id": "files_accounted_for",
        "status": "pass",
        "message": f"All {len(inv_paths)} inventory files present in file_breakdowns.",
        "details": [],
    }


def _check_line_ranges_valid(
    relation_map: dict,
    file_breakdowns: dict,
) -> dict[str, Any]:
    details: list[str] = []

    for node in relation_map.get("nodes", []):
        lineno = node.get("lineno")
        end_lineno = node.get("end_lineno")
        nid = node.get("node_id", "<unknown>")
        if lineno is not None and lineno < 1:
            details.append(f"Node {nid}: lineno={lineno} < 1")
        if lineno is not None and end_lineno is not None and end_lineno < lineno:
            details.append(f"Node {nid}: end_lineno={end_lineno} < lineno={lineno}")

    for file_record in file_breakdowns.get("files", []):
        if "parse_error" in file_record:
            continue
        fp = file_record.get("path", "<unknown>")
        for sym in file_record.get("defined_symbols", []):
            lineno = sym.get("lineno")
            end_lineno = sym.get("end_lineno")
            name = sym.get("name", "<unknown>")
            if lineno is not None and lineno < 1:
                details.append(f"Symbol {name} in {fp}: lineno={lineno} < 1")
            if lineno is not None and end_lineno is not None and end_lineno < lineno:
                details.append(
                    f"Symbol {name} in {fp}: end_lineno={end_lineno} < lineno={lineno}"
                )

    if details:
        return {
            "check_id": "line_ranges_valid",
            "status": "warn",
            "message": f"{len(details)} invalid line range(s) found.",
            "details": details,
        }
    return {
        "check_id": "line_ranges_valid",
        "status": "pass",
        "message": "All line ranges valid.",
        "details": [],
    }


def _check_referenced_files_exist(
    relation_map: dict,
    inventory: dict,
) -> dict[str, Any]:
    inv_paths = {f["path"] for f in inventory["files"]}
    node_file_map: dict[str, str] = {
        n["node_id"]: n["file_path"] for n in relation_map.get("nodes", [])
    }

    details: list[str] = []
    seen: set[str] = set()

    for edge in relation_map.get("edges", []):
        for id_key in ("source_id", "target_id"):
            nid = edge.get(id_key)
            if nid is None or nid in seen:
                continue
            seen.add(nid)
            fp = node_file_map.get(nid)
            if fp is not None and fp not in inv_paths:
                details.append(
                    f"Edge node {nid} references file not in inventory: {fp}"
                )

    if details:
        return {
            "check_id": "referenced_files_exist",
            "status": "warn",
            "message": f"{len(details)} edge node(s) reference file paths absent from inventory.",
            "details": details,
        }
    return {
        "check_id": "referenced_files_exist",
        "status": "pass",
        "message": "All edge-referenced file paths exist in inventory.",
        "details": [],
    }


def _check_relation_map_not_empty(
    inventory: dict,
    relation_map: dict,
) -> dict[str, Any]:
    if inventory.get("file_count", 0) == 0:
        return {
            "check_id": "relation_map_not_empty",
            "status": "pass",
            "message": "No files in inventory; relation map emptiness not applicable.",
            "details": [],
        }

    any_imports_or_calls = any(
        f.get("imports") or f.get("calls")
        for f in inventory.get("files", [])
        if "parse_error" not in f
    )

    if not any_imports_or_calls:
        return {
            "check_id": "relation_map_not_empty",
            "status": "pass",
            "message": "No imports or calls found in any file; empty relation map is expected.",
            "details": [],
        }

    details: list[str] = []
    if relation_map.get("node_count", 0) == 0:
        details.append("relation_map node_count is 0 but files have imports/calls")
    if relation_map.get("edge_count", 0) == 0:
        details.append("relation_map edge_count is 0 but files have imports/calls")

    if details:
        return {
            "check_id": "relation_map_not_empty",
            "status": "fail",
            "message": "Relation map is unexpectedly empty.",
            "details": details,
        }
    return {
        "check_id": "relation_map_not_empty",
        "status": "pass",
        "message": (
            f"Relation map has {relation_map['node_count']} nodes and "
            f"{relation_map['edge_count']} edges."
        ),
        "details": [],
    }


def _check_breakdowns_align_with_inventory(
    inventory: dict,
    file_breakdowns: dict,
) -> dict[str, Any]:
    details: list[str] = []

    inv_count = inventory.get("file_count", 0)
    bd_count = file_breakdowns.get("breakdown_count", 0)
    if bd_count != inv_count:
        details.append(
            f"breakdown_count={bd_count} != inventory file_count={inv_count}"
        )

    inv_paths = {f["path"] for f in inventory["files"]}
    for file_record in file_breakdowns.get("files", []):
        fp = file_record.get("path", "")
        if fp not in inv_paths:
            details.append(f"Breakdown path not in inventory: {fp}")
        sym_count = len(file_record.get("defined_symbols", []))
        if sym_count < 0:
            details.append(f"Negative defined_symbols count for {fp}: {sym_count}")

    if details:
        return {
            "check_id": "breakdowns_align_with_inventory",
            "status": "fail",
            "message": f"{len(details)} alignment issue(s) between file_breakdowns and inventory.",
            "details": details,
        }
    return {
        "check_id": "breakdowns_align_with_inventory",
        "status": "pass",
        "message": f"file_breakdowns aligns with inventory ({bd_count} files).",
        "details": [],
    }


def _check_flow_records_cite_actual_nodes(
    flow_map: dict,
    relation_map: dict,
) -> dict[str, Any]:
    known_node_ids = {n["node_id"] for n in relation_map.get("nodes", [])}

    details: list[str] = []
    for flow in flow_map.get("flows", []):
        flow_id = flow.get("flow_id", "<unknown>")
        root = flow.get("root_node_id", "")
        if root and root not in known_node_ids:
            details.append(f"Flow {flow_id}: root_node_id '{root}' not in relation_map nodes")

        for callee in flow.get("observed", {}).get("direct_callees", []):
            if callee not in known_node_ids:
                details.append(
                    f"Flow {flow_id}: direct_callee '{callee}' not in relation_map nodes"
                )

    if details:
        return {
            "check_id": "flow_records_cite_actual_nodes",
            "status": "warn",
            "message": f"{len(details)} flow node reference(s) not found in relation_map.",
            "details": details,
        }
    return {
        "check_id": "flow_records_cite_actual_nodes",
        "status": "pass",
        "message": f"All flow node references validated against relation_map ({len(flow_map.get('flows', []))} flows).",
        "details": [],
    }


def run_validation(
    inventory: dict,
    relation_map: dict,
    file_breakdowns: dict,
    flow_map: dict,
) -> dict[str, Any]:
    checks = [
        _check_files_accounted_for(inventory, file_breakdowns),
        _check_line_ranges_valid(relation_map, file_breakdowns),
        _check_referenced_files_exist(relation_map, inventory),
        _check_relation_map_not_empty(inventory, relation_map),
        _check_breakdowns_align_with_inventory(inventory, file_breakdowns),
        _check_flow_records_cite_actual_nodes(flow_map, relation_map),
    ]

    error_count = sum(1 for c in checks if c["status"] == "fail")
    warning_count = sum(1 for c in checks if c["status"] == "warn")

    return {
        "repo_root": inventory.get("repo_root", ""),
        "validated_at": datetime.now(timezone.utc).isoformat(),
        "error_count": error_count,
        "warning_count": warning_count,
        "checks": checks,
    }
