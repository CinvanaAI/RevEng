from __future__ import annotations

import json
from pathlib import Path


def write_enriched_file_breakdown_outputs(enriched_breakdowns: dict, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / "enriched_file_breakdowns.json"
    md_path = output_dir / "enriched_file_breakdowns.md"

    json_path.write_text(
        json.dumps(enriched_breakdowns, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    md_path.write_text(build_enriched_file_breakdowns_markdown(enriched_breakdowns), encoding="utf-8")


def _write_list_section(lines: list[str], title: str, values: list[str]) -> None:
    lines.append(f"### {title}")
    lines.append("")
    if values:
        for value in values:
            lines.append(f"- {value}")
    else:
        lines.append("- None")
    lines.append("")


def build_enriched_file_breakdowns_markdown(enriched_breakdowns: dict) -> str:
    lines: list[str] = []

    lines.append("# Enriched File Breakdowns")
    lines.append("")
    lines.append(f"- Repo root: `{enriched_breakdowns['repo_root']}`")
    lines.append(f"- Scanned at: `{enriched_breakdowns['scanned_at']}`")
    lines.append(f"- Python files scanned: `{enriched_breakdowns['file_count']}`")
    lines.append(f"- Breakdown count: `{enriched_breakdowns['breakdown_count']}`")
    lines.append("")

    for file_record in enriched_breakdowns["files"]:
        lines.append(f"## {file_record['path']}")
        lines.append("")

        if "parse_error" in file_record:
            lines.append(f"Parse error: `{file_record['parse_error']}`")
            lines.append("")
            continue

        lines.append(f"- Module name: `{file_record['module_name']}`")
        lines.append(f"- Main block present: `{file_record['main_block_present']}`")
        lines.append("")

        _write_list_section(lines, "Defined Symbol Signatures", file_record.get("defined_symbol_signatures", []))
        _write_list_section(lines, "Observed Inputs", file_record.get("observed_inputs", []))
        _write_list_section(lines, "Observed Outputs", file_record.get("observed_outputs", []))
        _write_list_section(lines, "Observed Side Effects", file_record.get("observed_side_effects", []))
        _write_list_section(lines, "Unresolved Items", file_record.get("unresolved_items", []))
        _write_list_section(lines, "Unknown Candidates", file_record.get("unknown_candidates", []))

    return "\n".join(lines)