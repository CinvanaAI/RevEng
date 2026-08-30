from __future__ import annotations

import json
from pathlib import Path

from reveng.storage.writers.ai_writer import _write_list_section


def write_ai_repo_summary_outputs(
    ai_repo_summary: dict,
    output_dir: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / "ai_repo_summary.json"
    md_path = output_dir / "ai_repo_summary.md"

    json_path.write_text(
        json.dumps(ai_repo_summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    md_path.write_text(
        build_ai_repo_summary_markdown(ai_repo_summary),
        encoding="utf-8",
    )


def build_ai_repo_summary_markdown(ai_repo_summary: dict) -> str:
    lines: list[str] = []

    lines.append("# AI Repo Summary")
    lines.append("")
    lines.append(f"- Repo root: `{ai_repo_summary['repo_root']}`")
    lines.append(f"- Scanned at: `{ai_repo_summary['scanned_at']}`")
    env_file = ai_repo_summary.get("env_file")
    if env_file:
        lines.append(f"- Env file: `{env_file}`")
    lines.append("")

    obs = ai_repo_summary.get("observed", {})
    lines.append("## Observed")
    lines.append("")
    lines.append(f"- **file_count:** {obs.get('file_count', 0)}")
    lines.append(f"- **cluster_count:** {obs.get('cluster_count', 0)}")
    lines.append(f"- **flow_count:** {obs.get('flow_count', 0)}")
    lines.append(f"- **hub_function_count:** {obs.get('hub_function_count', 0)}")
    lines.append("")

    der = ai_repo_summary.get("derived", {})
    lines.append("## Derived")
    lines.append("")
    lines.append(f"- **system_type:** {der.get('system_type', 'unknown')}")
    lines.append("")

    primary = der.get("primary_purpose", "")
    if primary:
        lines.append(f"**Primary purpose:** {primary}")
        lines.append("")

    repo_summary = der.get("repo_summary", "")
    if repo_summary:
        lines.append(repo_summary)
        lines.append("")

    _write_list_section(lines, "Key Capabilities", der.get("key_capabilities", []))

    unknown = ai_repo_summary.get("unknown", [])
    if unknown:
        lines.append("## Unknown")
        lines.append("")
        for item in unknown:
            lines.append(f"- {item}")
        lines.append("")

    return "\n".join(lines)
