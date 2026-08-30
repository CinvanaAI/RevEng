from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _collect_unknowns(
    inventory: dict,
    relation_map: dict,
    cluster_map: dict,
    flow_map: dict,
    enriched_file_breakdowns: dict | None = None,
) -> dict[str, Any]:
    sections: list[dict[str, Any]] = []

    # --- Parse errors ---
    parse_errors = [
        f"{f['path']}: {f['parse_error']}"
        for f in inventory.get("files", [])
        if "parse_error" in f
    ]
    sections.append({
        "source": "inventory_parse_errors",
        "count": len(parse_errors),
        "items": parse_errors,
    })

    # --- Unresolved imports (summary only) ---
    unresolved_imports = relation_map.get("unresolved_imports", [])
    import_items = [
        f"{item.get('source_file', '')}: {item.get('import_text', '')} (line {item.get('lineno', '?')})"
        for item in unresolved_imports
    ]
    sections.append({
        "source": "unresolved_imports",
        "count": len(import_items),
        "items": import_items,
    })

    # --- Unresolved calls by category ---
    unresolved_calls = relation_map.get("unresolved_calls", [])
    call_items = [
        f"{item.get('source_file', '')} [{item.get('source_scope', '')}]: "
        f"{item.get('called_name', '')} — {item.get('category', 'unclassified')} "
        f"(line {item.get('lineno', '?')})"
        for item in unresolved_calls
        if item.get("category") not in ("builtin", "external")
    ]
    sections.append({
        "source": "unresolved_calls_unknown",
        "count": len(call_items),
        "items": call_items,
    })

    # --- Cluster-level unknowns ---
    cluster_top = cluster_map.get("unknown", [])
    cluster_items: list[str] = list(cluster_top)
    for cluster in cluster_map.get("clusters", []):
        cid = cluster["cluster_id"]
        for item in cluster.get("unknown", []):
            cluster_items.append(f"{cid}: {item}")
    sections.append({
        "source": "cluster_unknowns",
        "count": len(cluster_items),
        "items": cluster_items,
    })

    # --- Flow-level unknowns ---
    flow_top = flow_map.get("unknown", [])
    flow_items: list[str] = list(flow_top)
    for flow in flow_map.get("flows", []):
        fid = flow["flow_id"]
        for item in flow.get("unknown", []):
            flow_items.append(f"{fid}: {item}")
    sections.append({
        "source": "flow_unknowns",
        "count": len(flow_items),
        "items": flow_items,
    })

    # --- Per-file unknown candidates (from enriched breakdowns) ---
    if enriched_file_breakdowns is not None:
        file_unknown_items: list[str] = []
        for fr in enriched_file_breakdowns.get("files", []):
            if "parse_error" in fr:
                continue
            fp = fr.get("path", "")
            for item in fr.get("unknown_candidates", []):
                file_unknown_items.append(f"{fp}: {item}")
        sections.append({
            "source": "file_unknown_candidates",
            "count": len(file_unknown_items),
            "items": file_unknown_items,
        })

    total = sum(s["count"] for s in sections)

    return {
        "repo_root": inventory.get("repo_root", ""),
        "scanned_at": inventory.get("scanned_at", ""),
        "total_unknown_count": total,
        "sections": sections,
    }


def write_unknowns_outputs(
    unknowns: dict,
    output_dir: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / "unknowns.json"
    md_path = output_dir / "unknowns.md"

    json_path.write_text(
        json.dumps(unknowns, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    md_path.write_text(build_unknowns_markdown(unknowns), encoding="utf-8")


def build_unknowns_markdown(unknowns: dict) -> str:
    lines: list[str] = []

    lines.append("# Unknowns")
    lines.append("")
    lines.append(f"- Repo root: `{unknowns['repo_root']}`")
    lines.append(f"- Scanned at: `{unknowns['scanned_at']}`")
    lines.append(f"- Total unknown items: `{unknowns['total_unknown_count']}`")
    lines.append("")

    SECTION_TITLES = {
        "inventory_parse_errors": "Parse Errors",
        "unresolved_imports": "Unresolved Imports",
        "unresolved_calls_unknown": "Unresolved Calls (Unknown Category)",
        "cluster_unknowns": "Cluster Unknowns",
        "flow_unknowns": "Flow Unknowns",
        "file_unknown_candidates": "File Unknown Candidates",
    }

    for section in unknowns["sections"]:
        title = SECTION_TITLES.get(section["source"], section["source"])
        lines.append(f"## {title}")
        lines.append("")
        lines.append(f"Count: {section['count']}")
        lines.append("")
        if section["items"]:
            for item in section["items"]:
                lines.append(f"- {item}")
        else:
            lines.append("- None")
        lines.append("")

    return "\n".join(lines)


def build_unknowns(
    inventory: dict,
    relation_map: dict,
    cluster_map: dict,
    flow_map: dict,
    enriched_file_breakdowns: dict | None = None,
) -> dict[str, Any]:
    return _collect_unknowns(
        inventory, relation_map, cluster_map, flow_map, enriched_file_breakdowns
    )
