from __future__ import annotations

from typing import Any


SIDE_EFFECT_CALL_SUFFIXES = {
    "append",
    "extend",
    "pop",
    "remove",
    "clear",
    "update",
    "setdefault",
    "add",
    "put",
    "put_nowait",
    "write",
    "write_text",
    "write_bytes",
    "mkdir",
    "unlink",
    "rmdir",
    "rename",
    "replace",
    "save",
    "commit",
    "flush",
    "send",
    "emit",
    "publish",
    "delete",
    "execute",
}

SIDE_EFFECT_EXACT_CALLS = {
    "print",
}


def _format_symbol_signature(symbol: dict[str, Any]) -> str:
    symbol_type = symbol.get("symbol_type", "")
    name = symbol.get("name", "")
    args = symbol.get("args", [])
    arg_text = ", ".join(args) if args else ""
    if symbol_type == "class":
        return f"class {name}"
    return f"{symbol_type} {name}({arg_text})"


def _build_observed_inputs(file_record: dict[str, Any]) -> list[str]:
    results: list[str] = []

    for symbol in file_record.get("defined_symbols", []):
        symbol_type = symbol.get("symbol_type", "")
        if symbol_type == "class":
            continue

        args = symbol.get("args", [])
        if args:
            results.append(
                f"{symbol_type} {symbol['name']} defines parameters: {', '.join(args)}"
            )

    for call in file_record.get("calls", []):
        called_name = call.get("called_name", "")
        if called_name == "input":
            results.append(
                f"input() call present in scope {call['enclosing_scope']} (lines {call['lineno']}-{call['end_lineno']})"
            )

    return results


def _build_observed_outputs(file_record: dict[str, Any]) -> list[str]:
    results: list[str] = []

    for item in file_record.get("returns", []):
        results.append(
            f"return <{item['value_type']}> present in scope {item['enclosing_scope']} "
            f"(lines {item['lineno']}-{item['end_lineno']})"
        )

    for item in file_record.get("raises", []):
        results.append(
            f"raise <{item['exception_type']}> present in scope {item['enclosing_scope']} "
            f"(lines {item['lineno']}-{item['end_lineno']})"
        )

    return results


def _build_observed_side_effects(file_record: dict[str, Any]) -> list[str]:
    results: list[str] = []

    for call in file_record.get("calls", []):
        called_name = call.get("called_name", "")
        suffix = called_name.split(".")[-1] if called_name else ""

        if called_name in SIDE_EFFECT_EXACT_CALLS or suffix in SIDE_EFFECT_CALL_SUFFIXES:
            results.append(
                f"{called_name} call present in scope {call['enclosing_scope']} "
                f"(lines {call['lineno']}-{call['end_lineno']})"
            )

    return results


def _build_unresolved_items(file_record: dict[str, Any]) -> list[str]:
    results: list[str] = []

    for item in file_record.get("unresolved_imports", []):
        results.append(
            f"unresolved import: {item['import_text']} "
            f"(lines {item['lineno']}-{item['end_lineno']})"
        )

    for item in file_record.get("unresolved_calls", []):
        variable_hint = item.get("variable_hint")
        hint_text = f" | variable_hint: {variable_hint}" if variable_hint else ""
        results.append(
            f"unresolved call: {item['called_name']} "
            f"[scope: {item['source_scope']} | category: {item.get('category', 'unclassified')}{hint_text}] "
            f"(lines {item['lineno']}-{item['end_lineno']})"
        )

    return results


def _build_unknown_candidates(file_record: dict[str, Any]) -> list[str]:
    results: list[str] = []

    calls_present = file_record.get("calls", [])
    outbound_call_edges = file_record.get("outbound_call_edges", [])
    unresolved_calls = file_record.get("unresolved_calls", [])
    imports_present = file_record.get("imports", [])
    outbound_import_edges = file_record.get("outbound_import_edges", [])
    unresolved_imports = file_record.get("unresolved_imports", [])

    if calls_present and not outbound_call_edges and unresolved_calls:
        results.append("Some call targets are unresolved from the static record.")

    if imports_present and not outbound_import_edges and unresolved_imports:
        results.append("Some import targets are unresolved from the static record.")

    if not file_record.get("defined_symbols", []) and file_record.get("top_level_statements", []):
        results.append("File has top-level statements but no defined symbols.")

    if file_record.get("calls", []) and not file_record.get("inbound_call_edges", []):
        results.append("Resolved inbound usage is not present in the current relation map.")

    return results


def build_enriched_file_breakdowns(file_breakdowns: dict) -> dict:
    enriched_files: list[dict[str, Any]] = []

    for file_record in file_breakdowns["files"]:
        if "parse_error" in file_record:
            enriched_files.append(dict(file_record))
            continue

        enriched = dict(file_record)
        enriched["observed_inputs"] = _build_observed_inputs(file_record)
        enriched["observed_outputs"] = _build_observed_outputs(file_record)
        enriched["observed_side_effects"] = _build_observed_side_effects(file_record)
        enriched["unresolved_items"] = _build_unresolved_items(file_record)
        enriched["unknown_candidates"] = _build_unknown_candidates(file_record)
        enriched["defined_symbol_signatures"] = [
            _format_symbol_signature(symbol)
            for symbol in file_record.get("defined_symbols", [])
        ]

        enriched_files.append(enriched)

    return {
        "repo_root": file_breakdowns["repo_root"],
        "scanned_at": file_breakdowns["scanned_at"],
        "file_count": file_breakdowns["file_count"],
        "breakdown_count": file_breakdowns["breakdown_count"],
        "files": enriched_files,
    }