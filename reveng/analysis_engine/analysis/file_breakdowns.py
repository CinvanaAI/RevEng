from __future__ import annotations

from collections import defaultdict
from typing import Any


def _group_edges_by_file(relation_map: dict) -> tuple[dict[str, list[dict]], dict[str, list[dict]], dict[str, dict]]:
    node_lookup: dict[str, dict] = {}
    for node in relation_map["nodes"]:
        node_lookup[node["node_id"]] = node

    inbound_by_file: dict[str, list[dict]] = defaultdict(list)
    outbound_by_file: dict[str, list[dict]] = defaultdict(list)

    for edge in relation_map["edges"]:
        source_node = node_lookup.get(edge["source_id"])
        target_node = node_lookup.get(edge["target_id"])

        if source_node:
            outbound_by_file[source_node["file_path"]].append(edge)
        if target_node:
            inbound_by_file[target_node["file_path"]].append(edge)

    return inbound_by_file, outbound_by_file, node_lookup


def _group_unresolved_by_file(relation_map: dict) -> tuple[dict[str, list[dict]], dict[str, list[dict]]]:
    unresolved_imports_by_file: dict[str, list[dict]] = defaultdict(list)
    unresolved_calls_by_file: dict[str, list[dict]] = defaultdict(list)

    for item in relation_map.get("unresolved_imports", []):
        unresolved_imports_by_file[item["source_file"]].append(item)

    for item in relation_map.get("unresolved_calls", []):
        unresolved_calls_by_file[item["source_file"]].append(item)

    return unresolved_imports_by_file, unresolved_calls_by_file


def _extract_defined_symbols(file_record: dict) -> list[dict[str, Any]]:
    symbols: list[dict[str, Any]] = []

    for fn in file_record.get("functions", []):
        symbols.append(
            {
                "symbol_type": fn["function_type"],
                "name": fn["name"],
                "scope": fn["enclosing_scope"],
                "lineno": fn["lineno"],
                "end_lineno": fn["end_lineno"],
                "args": fn.get("args", []),
            }
        )

    for cls in file_record.get("classes", []):
        symbols.append(
            {
                "symbol_type": "class",
                "name": cls["name"],
                "scope": cls["enclosing_scope"],
                "lineno": cls["lineno"],
                "end_lineno": cls["end_lineno"],
                "args": [],
            }
        )
        for method in cls.get("methods", []):
            symbols.append(
                {
                    "symbol_type": method["function_type"],
                    "name": method["name"],
                    "scope": method["enclosing_scope"],
                    "lineno": method["lineno"],
                    "end_lineno": method["end_lineno"],
                    "args": method.get("args", []),
                }
            )

    return symbols


def build_file_breakdowns(inventory: dict, relation_map: dict) -> dict:
    inbound_by_file, outbound_by_file, node_lookup = _group_edges_by_file(relation_map)
    unresolved_imports_by_file, unresolved_calls_by_file = _group_unresolved_by_file(relation_map)

    breakdowns: list[dict[str, Any]] = []

    for file_record in inventory["files"]:
        if "parse_error" in file_record:
            breakdowns.append(
                {
                    "path": file_record["path"],
                    "module_name": file_record["module_name"],
                    "parse_error": file_record["parse_error"],
                }
            )
            continue

        file_path = file_record["path"]

        inbound_edges = inbound_by_file.get(file_path, [])
        outbound_edges = outbound_by_file.get(file_path, [])

        inbound_serialized: list[dict[str, Any]] = []
        for edge in inbound_edges:
            source_node = node_lookup.get(edge["source_id"], {})
            inbound_serialized.append(
                {
                    "edge_type": edge["edge_type"],
                    "source_id": edge["source_id"],
                    "source_file": source_node.get("file_path"),
                    "evidence": edge["evidence"],
                    "lineno": edge["lineno"],
                    "end_lineno": edge["end_lineno"],
                }
            )

        outbound_serialized: list[dict[str, Any]] = []
        for edge in outbound_edges:
            target_node = node_lookup.get(edge["target_id"], {})
            outbound_serialized.append(
                {
                    "edge_type": edge["edge_type"],
                    "target_id": edge["target_id"],
                    "target_file": target_node.get("file_path"),
                    "evidence": edge["evidence"],
                    "lineno": edge["lineno"],
                    "end_lineno": edge["end_lineno"],
                }
            )

        received_calls = [edge for edge in inbound_serialized if edge["edge_type"] == "calls"]
        made_calls = [edge for edge in outbound_serialized if edge["edge_type"] == "calls"]
        import_edges = [edge for edge in outbound_serialized if edge["edge_type"] == "imports"]
        contain_edges = [edge for edge in outbound_serialized if edge["edge_type"] == "contains"]

        breakdowns.append(
            {
                "path": file_path,
                "module_name": file_record["module_name"],
                "main_block_present": file_record["main_block_present"],
                "defined_symbols": _extract_defined_symbols(file_record),
                "imports": file_record.get("imports", []),
                "top_level_statements": file_record.get("top_level_statements", []),
                "calls": file_record.get("calls", []),
                "assignments": file_record.get("assignments", []),
                "returns": file_record.get("returns", []),
                "raises": file_record.get("raises", []),
                "control_flow": file_record.get("control_flow", []),
                "decorators": file_record.get("decorators", []),
                "classes": file_record.get("classes", []),
                "outbound_import_edges": import_edges,
                "outbound_contains_edges": contain_edges,
                "outbound_call_edges": made_calls,
                "inbound_call_edges": received_calls,
                "all_inbound_edges": inbound_serialized,
                "all_outbound_edges": outbound_serialized,
                "unresolved_imports": unresolved_imports_by_file.get(file_path, []),
                "unresolved_calls": unresolved_calls_by_file.get(file_path, []),
            }
        )

    return {
        "repo_root": inventory["repo_root"],
        "scanned_at": inventory["scanned_at"],
        "file_count": inventory["file_count"],
        "breakdown_count": len(breakdowns),
        "files": breakdowns,
    }