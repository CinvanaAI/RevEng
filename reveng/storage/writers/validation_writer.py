from __future__ import annotations

import json
from pathlib import Path


def write_validation_outputs(validation_report: dict, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / "validation_report.json"
    md_path = output_dir / "validation_report.md"

    json_path.write_text(
        json.dumps(validation_report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    md_path.write_text(
        build_validation_report_markdown(validation_report),
        encoding="utf-8",
    )


def build_validation_report_markdown(validation_report: dict) -> str:
    lines: list[str] = []

    error_count = validation_report["error_count"]
    warning_count = validation_report["warning_count"]

    lines.append("# Validation Report")
    lines.append("")
    lines.append(f"- Repo root: `{validation_report['repo_root']}`")
    lines.append(f"- Validated at: `{validation_report['validated_at']}`")
    lines.append(f"- Errors: `{error_count}`")
    lines.append(f"- Warnings: `{warning_count}`")
    lines.append("")

    STATUS_ICON = {"pass": "PASS", "warn": "WARN", "fail": "FAIL"}

    for check in validation_report["checks"]:
        icon = STATUS_ICON.get(check["status"], check["status"].upper())
        lines.append(f"## [{icon}] {check['check_id']}")
        lines.append("")
        lines.append(check["message"])
        if check["details"]:
            lines.append("")
            for detail in check["details"]:
                lines.append(f"- {detail}")
        lines.append("")

    return "\n".join(lines)
