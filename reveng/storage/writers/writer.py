from __future__ import annotations

import json
from pathlib import Path


def write_inventory_outputs(inventory: dict, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / "repo_inventory.json"
    md_path = output_dir / "repo_inventory.md"

    json_path.write_text(
        json.dumps(inventory, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    md_path.write_text(build_markdown(inventory), encoding="utf-8")


def build_markdown(inventory: dict) -> str:
    lines: list[str] = []

    lines.append("# Repo Inventory")
    lines.append("")
    lines.append(f"- Repo root: `{inventory['repo_root']}`")
    lines.append(f"- Scanned at: `{inventory['scanned_at']}`")
    lines.append(f"- Python files scanned: `{inventory['file_count']}`")
    lines.append("")

    for file_record in inventory["files"]:
        lines.append(f"## {file_record['path']}")
        lines.append("")

        if "parse_error" in file_record:
            lines.append(f"Parse error: `{file_record['parse_error']}`")
            lines.append("")
            continue

        lines.append(f"- Module name: `{file_record['module_name']}`")
        lines.append(f"- Main block present: `{file_record['main_block_present']}`")
        lines.append("")

        lines.append("### Imports")
        lines.append("")
        if file_record["imports"]:
            for item in file_record["imports"]:
                if item["import_type"] == "import":
                    lines.append(
                        f"- import {', '.join(item['names'])} "
                        f"(lines {item['lineno']}-{item['end_lineno']})"
                    )
                else:
                    lines.append(
                        f"- from {item['module']} import {', '.join(item['names'])} "
                        f"(lines {item['lineno']}-{item['end_lineno']})"
                    )
        else:
            lines.append("- None")
        lines.append("")

        lines.append("### Classes")
        lines.append("")
        if file_record["classes"]:
            for cls in file_record["classes"]:
                lines.append(
                    f"- {cls['name']} "
                    f"[scope: {cls['enclosing_scope']}] "
                    f"(lines {cls['lineno']}-{cls['end_lineno']})"
                )
                if cls["methods"]:
                    for method in cls["methods"]:
                        lines.append(
                            f"  - {method['function_type']}: {method['name']}("
                            f"{', '.join(method['args'])}) "
                            f"[scope: {method['enclosing_scope']}] "
                            f"(lines {method['lineno']}-{method['end_lineno']})"
                        )
        else:
            lines.append("- None")
        lines.append("")

        lines.append("### Functions")
        lines.append("")
        if file_record["functions"]:
            for fn in file_record["functions"]:
                lines.append(
                    f"- {fn['function_type']}: {fn['name']}("
                    f"{', '.join(fn['args'])}) "
                    f"[scope: {fn['enclosing_scope']}] "
                    f"(lines {fn['lineno']}-{fn['end_lineno']})"
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

        lines.append("### Calls")
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

        lines.append("### Decorators")
        lines.append("")
        if file_record["decorators"]:
            for item in file_record["decorators"]:
                lines.append(
                    f"- {item['text']} "
                    f"[scope: {item['enclosing_scope']}] "
                    f"(lines {item['lineno']}-{item['end_lineno']})"
                )
        else:
            lines.append("- None")
        lines.append("")

    return "\n".join(lines)
