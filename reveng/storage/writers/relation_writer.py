from __future__ import annotations

import json
from collections import Counter
from pathlib import Path


def write_relation_outputs(relation_map: dict, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / "relation_map.json"
    md_path = output_dir / "relation_map.md"

    json_path.write_text(
        json.dumps(relation_map, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    md_path.write_text(build_relation_markdown(relation_map), encoding="utf-8")


def build_relation_markdown(relation_map: dict) -> str:
    lines: list[str] = []

    unresolved_call_counter = Counter(
        item.get("category", "unclassified")
        for item in relation_map.get("unresolved_calls", [])
    )

    lines.append("# Relation Map")
    lines.append("")
    lines.append(f"- Repo root: `{relation_map['repo_root']}`")
    lines.append(f"- Scanned at: `{relation_map['scanned_at']}`")
    lines.append(f"- Python files scanned: `{relation_map['file_count']}`")
    lines.append(f"- Node count: `{relation_map['node_count']}`")
    lines.append(f"- Edge count: `{relation_map['edge_count']}`")
    lines.append(f"- Unresolved import count: `{len(relation_map.get('unresolved_imports', []))}`")
    lines.append(f"- Unresolved call count: `{len(relation_map.get('unresolved_calls', []))}`")
    lines.append(f"- External import count: `{len(relation_map.get('external_imports', []))}`")
    lines.append(f"- External call count: `{len(relation_map.get('external_calls', []))}`")
    lines.append("")

    lines.append("## Unresolved Call Categories")
    lines.append("")
    if unresolved_call_counter:
        for category, count in sorted(unresolved_call_counter.items(), key=lambda item: (-item[1], item[0])):
            lines.append(f"- `{category}` — {count}")
    else:
        lines.append("- None")
    lines.append("")

    lines.append("## Edges")
    lines.append("")
    if relation_map["edges"]:
        for edge in relation_map["edges"]:
            lines.append(
                f"- {edge['edge_type']}: `{edge['source_id']}` -> `{edge['target_id']}` "
                f"[evidence: {edge['evidence']}] "
                f"(lines {edge['lineno']}-{edge['end_lineno']})"
            )
    else:
        lines.append("- None")
    lines.append("")

    lines.append("## Unresolved Imports")
    lines.append("")
    if relation_map["unresolved_imports"]:
        for item in relation_map["unresolved_imports"]:
            lines.append(
                f"- {item['import_text']} "
                f"[source: {item['source_file']}] "
                f"(lines {item['lineno']}-{item['end_lineno']})"
            )
    else:
        lines.append("- None")
    lines.append("")

    lines.append("## Unresolved Calls")
    lines.append("")
    if relation_map["unresolved_calls"]:
        for item in relation_map["unresolved_calls"]:
            lines.append(
                f"- {item['called_name']} "
                f"[source: {item['source_file']} | scope: {item['source_scope']} | "
                f"kind: {item.get('resolution_kind', 'unresolved')} | category: {item.get('category', 'unclassified')}] "
                f"(lines {item['lineno']}-{item['end_lineno']})"
            )
    else:
        lines.append("- None")
    lines.append("")

    lines.append("## External Imports")
    lines.append("")
    if relation_map.get("external_imports"):
        for item in relation_map["external_imports"]:
            lines.append(
                f"- {item['import_text']} "
                f"[source: {item['source_file']}] "
                f"(lines {item['lineno']}-{item['end_lineno']})"
            )
    else:
        lines.append("- None")
    lines.append("")

    lines.append("## External Calls")
    lines.append("")
    if relation_map.get("external_calls"):
        for item in relation_map["external_calls"]:
            lines.append(
                f"- {item['called_name']} "
                f"[source: {item['source_file']} | scope: {item['source_scope']} | "
                f"kind: {item.get('resolution_kind', 'external')} | category: {item.get('category', 'external')}] "
                f"(lines {item['lineno']}-{item['end_lineno']})"
            )
    else:
        lines.append("- None")
    lines.append("")

    return "\n".join(lines)
