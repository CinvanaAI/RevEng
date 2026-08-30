from __future__ import annotations

import json
from pathlib import Path


def _sanitize_path_for_filename(file_path: str) -> str:
    return file_path.replace("/", "__").replace("\\", "__")


def _build_single_file_breakdown_markdown(file_record: dict) -> str:
    lines: list[str] = []
    lines.append(f"# File Breakdown: {file_record['path']}")
    lines.append("")

    if "parse_error" in file_record:
        lines.append(f"Parse error: `{file_record['parse_error']}`")
        lines.append("")
        return "\n".join(lines)

    lines.append(f"- Module name: `{file_record['module_name']}`")
    lines.append(f"- Main block present: `{file_record['main_block_present']}`")
    lines.append("")

    lines.append("## Defined Symbols")
    lines.append("")
    if file_record["defined_symbols"]:
        for symbol in file_record["defined_symbols"]:
            arg_text = ", ".join(symbol["args"]) if symbol["args"] else ""
            suffix = f"({arg_text})" if symbol["symbol_type"] != "class" else ""
            lines.append(
                f"- {symbol['symbol_type']}: {symbol['name']}{suffix} "
                f"[scope: {symbol['scope']}] "
                f"(lines {symbol['lineno']}-{symbol['end_lineno']})"
            )
    else:
        lines.append("- None")
    lines.append("")

    lines.append("## Outbound Import Edges")
    lines.append("")
    if file_record["outbound_import_edges"]:
        for edge in file_record["outbound_import_edges"]:
            lines.append(
                f"- -> `{edge['target_id']}` "
                f"[target_file: {edge['target_file']}] "
                f"[evidence: {edge['evidence']}] "
                f"(lines {edge['lineno']}-{edge['end_lineno']})"
            )
    else:
        lines.append("- None")
    lines.append("")

    lines.append("## Outbound Call Edges")
    lines.append("")
    if file_record["outbound_call_edges"]:
        for edge in file_record["outbound_call_edges"]:
            lines.append(
                f"- -> `{edge['target_id']}` "
                f"[target_file: {edge['target_file']}] "
                f"[evidence: {edge['evidence']}] "
                f"(lines {edge['lineno']}-{edge['end_lineno']})"
            )
    else:
        lines.append("- None")
    lines.append("")

    lines.append("## Inbound Call Edges")
    lines.append("")
    if file_record["inbound_call_edges"]:
        for edge in file_record["inbound_call_edges"]:
            lines.append(
                f"- <- `{edge['source_id']}` "
                f"[source_file: {edge['source_file']}] "
                f"[evidence: {edge['evidence']}] "
                f"(lines {edge['lineno']}-{edge['end_lineno']})"
            )
    else:
        lines.append("- None")
    lines.append("")

    lines.append("## Unresolved Imports")
    lines.append("")
    if file_record["unresolved_imports"]:
        for item in file_record["unresolved_imports"]:
            lines.append(
                f"- {item['import_text']} "
                f"(lines {item['lineno']}-{item['end_lineno']})"
            )
    else:
        lines.append("- None")
    lines.append("")

    lines.append("## Unresolved Calls")
    lines.append("")
    if file_record["unresolved_calls"]:
        for item in file_record["unresolved_calls"]:
            lines.append(
                f"- {item['called_name']} "
                f"[scope: {item['source_scope']}] "
                f"(lines {item['lineno']}-{item['end_lineno']})"
            )
    else:
        lines.append("- None")
    lines.append("")

    return "\n".join(lines)


def write_file_breakdown_per_file_outputs(
    file_breakdowns: dict,
    output_dir: Path,
) -> None:
    breakdowns_dir = output_dir / "file_breakdowns"
    breakdowns_dir.mkdir(parents=True, exist_ok=True)

    for file_record in file_breakdowns["files"]:
        safe_name = _sanitize_path_for_filename(file_record["path"])
        breakdown_path = breakdowns_dir / f"{safe_name}.md"
        breakdown_path.write_text(
            _build_single_file_breakdown_markdown(file_record),
            encoding="utf-8",
        )


def write_file_breakdown_outputs(file_breakdowns: dict, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / "file_breakdowns.json"
    md_path = output_dir / "file_breakdowns.md"

    json_path.write_text(
        json.dumps(file_breakdowns, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    md_path.write_text(build_file_breakdowns_markdown(file_breakdowns), encoding="utf-8")


def build_file_breakdowns_markdown(file_breakdowns: dict) -> str:
    lines: list[str] = []

    lines.append("# File Breakdowns")
    lines.append("")
    lines.append(f"- Repo root: `{file_breakdowns['repo_root']}`")
    lines.append(f"- Scanned at: `{file_breakdowns['scanned_at']}`")
    lines.append(f"- Python files scanned: `{file_breakdowns['file_count']}`")
    lines.append(f"- Breakdown count: `{file_breakdowns['breakdown_count']}`")
    lines.append("")

    for file_record in file_breakdowns["files"]:
        lines.append(f"## {file_record['path']}")
        lines.append("")

        if "parse_error" in file_record:
            lines.append(f"Parse error: `{file_record['parse_error']}`")
            lines.append("")
            continue

        lines.append(f"- Module name: `{file_record['module_name']}`")
        lines.append(f"- Main block present: `{file_record['main_block_present']}`")
        lines.append("")

        lines.append("### Defined Symbols")
        lines.append("")
        if file_record["defined_symbols"]:
            for symbol in file_record["defined_symbols"]:
                arg_text = ", ".join(symbol["args"]) if symbol["args"] else ""
                suffix = f"({arg_text})" if symbol["symbol_type"] != "class" else ""
                lines.append(
                    f"- {symbol['symbol_type']}: {symbol['name']}{suffix} "
                    f"[scope: {symbol['scope']}] "
                    f"(lines {symbol['lineno']}-{symbol['end_lineno']})"
                )
        else:
            lines.append("- None")
        lines.append("")

        lines.append("### Outbound Import Edges")
        lines.append("")
        if file_record["outbound_import_edges"]:
            for edge in file_record["outbound_import_edges"]:
                lines.append(
                    f"- -> `{edge['target_id']}` "
                    f"[target_file: {edge['target_file']}] "
                    f"[evidence: {edge['evidence']}] "
                    f"(lines {edge['lineno']}-{edge['end_lineno']})"
                )
        else:
            lines.append("- None")
        lines.append("")

        lines.append("### Outbound Call Edges")
        lines.append("")
        if file_record["outbound_call_edges"]:
            for edge in file_record["outbound_call_edges"]:
                lines.append(
                    f"- -> `{edge['target_id']}` "
                    f"[target_file: {edge['target_file']}] "
                    f"[evidence: {edge['evidence']}] "
                    f"(lines {edge['lineno']}-{edge['end_lineno']})"
                )
        else:
            lines.append("- None")
        lines.append("")

        lines.append("### Inbound Call Edges")
        lines.append("")
        if file_record["inbound_call_edges"]:
            for edge in file_record["inbound_call_edges"]:
                lines.append(
                    f"- <- `{edge['source_id']}` "
                    f"[source_file: {edge['source_file']}] "
                    f"[evidence: {edge['evidence']}] "
                    f"(lines {edge['lineno']}-{edge['end_lineno']})"
                )
        else:
            lines.append("- None")
        lines.append("")

        lines.append("### Top-level Statements")
        lines.append("")
        if file_record["top_level_statements"]:
            for stmt in file_record["top_level_statements"]:
                lines.append(
                    f"- {stmt['node_type']} "
                    f"(lines {stmt['lineno']}-{stmt['end_lineno']})"
                )
        else:
            lines.append("- None")
        lines.append("")

        lines.append("### Calls Present In File")
        lines.append("")
        if file_record["calls"]:
            for call in file_record["calls"]:
                lines.append(
                    f"- {call['called_name']} "
                    f"[scope: {call['enclosing_scope']}] "
                    f"(lines {call['lineno']}-{call['end_lineno']})"
                )
        else:
            lines.append("- None")
        lines.append("")

        lines.append("### Assignments")
        lines.append("")
        if file_record["assignments"]:
            for assign in file_record["assignments"]:
                target_text = ", ".join(assign["targets"]) if assign["targets"] else "(unresolved)"
                lines.append(
                    f"- {target_text} = <{assign['value_type']}> "
                    f"[scope: {assign['enclosing_scope']}] "
                    f"(lines {assign['lineno']}-{assign['end_lineno']})"
                )
        else:
            lines.append("- None")
        lines.append("")

        lines.append("### Returns")
        lines.append("")
        if file_record["returns"]:
            for ret in file_record["returns"]:
                lines.append(
                    f"- return <{ret['value_type']}> "
                    f"[scope: {ret['enclosing_scope']}] "
                    f"(lines {ret['lineno']}-{ret['end_lineno']})"
                )
        else:
            lines.append("- None")
        lines.append("")

        lines.append("### Raises")
        lines.append("")
        if file_record["raises"]:
            for item in file_record["raises"]:
                lines.append(
                    f"- raise <{item['exception_type']}> "
                    f"[scope: {item['enclosing_scope']}] "
                    f"(lines {item['lineno']}-{item['end_lineno']})"
                )
        else:
            lines.append("- None")
        lines.append("")

        lines.append("### Control Flow")
        lines.append("")
        if file_record["control_flow"]:
            for item in file_record["control_flow"]:
                lines.append(
                    f"- {item['node_type']} "
                    f"[scope: {item['enclosing_scope']}] "
                    f"(lines {item['lineno']}-{item['end_lineno']})"
                )
        else:
            lines.append("- None")
        lines.append("")

        lines.append("### Unresolved Imports")
        lines.append("")
        if file_record["unresolved_imports"]:
            for item in file_record["unresolved_imports"]:
                lines.append(
                    f"- {item['import_text']} "
                    f"(lines {item['lineno']}-{item['end_lineno']})"
                )
        else:
            lines.append("- None")
        lines.append("")

        lines.append("### Unresolved Calls")
        lines.append("")
        if file_record["unresolved_calls"]:
            for item in file_record["unresolved_calls"]:
                lines.append(
                    f"- {item['called_name']} "
                    f"[scope: {item['source_scope']}] "
                    f"(lines {item['lineno']}-{item['end_lineno']})"
                )
        else:
            lines.append("- None")
        lines.append("")

    return "\n".join(lines)