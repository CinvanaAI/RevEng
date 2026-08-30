from __future__ import annotations

from pathlib import Path
from typing import Any

from reveng.analysis_engine.analysis.repo_dossier import build_repo_dossier
from reveng.analysis_engine.analysis.validator import run_validation
from reveng.platform.capabilities import (
    CapabilityContext,
    CapabilityContract,
    CapabilityDefinition,
    CapabilityRegistry,
)
from reveng.storage.paths import (
    repo_dossier_json_path,
    unknowns_json_path,
    validation_report_json_path,
)
from reveng.storage.writers.repo_dossier_writer import write_repo_dossier_outputs
from reveng.storage.writers.unknowns_writer import build_unknowns, write_unknowns_outputs
from reveng.storage.writers.validation_writer import write_validation_outputs

PACK_ID = "reveng.pack.reporting"

REPO_DOSSIER_KIND = "report.repo_dossier.v1"
VALIDATION_REPORT_KIND = "report.validation.v1"
UNKNOWNS_KIND = "report.unknowns.v1"


def _json_views(path: Path) -> dict[str, str | Path]:
    return {"markdown": path.with_suffix(".md")}


def _build_repo_dossier_capability(context: CapabilityContext) -> dict[str, Any]:
    path = repo_dossier_json_path(context.runtime.output_dir)
    views = _json_views(path)

    if context.cache_ready(path, output_name="repo_dossier"):
        ref = context.load_cached_json_artifact(
            REPO_DOSSIER_KIND,
            path,
            views=views,
            metadata={"cached": True},
        )
        return {"repo_dossier": ref, "repo_dossier_path": str(path), "cached": True}

    inventory = context.read_input("inventory")
    relation_map = context.read_input("relation_map")
    file_breakdowns = context.read_input("file_breakdowns")
    cluster_map = context.read_input("cluster_map")
    flow_map = context.read_input("flow_map")
    repo_dossier = build_repo_dossier(
        inventory,
        relation_map,
        file_breakdowns,
        cluster_map=cluster_map,
        flow_map=flow_map,
    )
    write_repo_dossier_outputs(repo_dossier, context.runtime.output_dir)
    ref = context.record_artifact(REPO_DOSSIER_KIND, repo_dossier, path=path, views=views)
    return {"repo_dossier": ref, "repo_dossier_path": str(path), "cached": False}


def _build_validation_report_capability(context: CapabilityContext) -> dict[str, Any]:
    path = validation_report_json_path(context.runtime.output_dir)
    views = _json_views(path)

    if context.cache_ready(path, output_name="validation_report"):
        ref = context.load_cached_json_artifact(
            VALIDATION_REPORT_KIND,
            path,
            views=views,
            metadata={"cached": True},
        )
        report = context.runtime.artifacts.read(ref)
        checks = report.get("checks", [])
        error_count = sum(1 for item in checks if item.get("status") == "fail")
        warning_count = sum(1 for item in checks if item.get("status") == "warn")
        return {
            "validation_report": ref,
            "validation_report_path": str(path),
            "error_count": error_count,
            "warning_count": warning_count,
            "cached": True,
        }

    inventory = context.read_input("inventory")
    relation_map = context.read_input("relation_map")
    file_breakdowns = context.read_input("file_breakdowns")
    flow_map = context.read_input("flow_map")
    report = run_validation(inventory, relation_map, file_breakdowns, flow_map)
    write_validation_outputs(report, context.runtime.output_dir)
    ref = context.record_artifact(VALIDATION_REPORT_KIND, report, path=path, views=views)
    return {
        "validation_report": ref,
        "validation_report_path": str(path),
        "error_count": report["error_count"],
        "warning_count": report["warning_count"],
        "cached": False,
    }


def _build_unknowns_capability(context: CapabilityContext) -> dict[str, Any]:
    path = unknowns_json_path(context.runtime.output_dir)
    views = _json_views(path)

    if context.cache_ready(path, output_name="unknowns"):
        ref = context.load_cached_json_artifact(
            UNKNOWNS_KIND,
            path,
            views=views,
            metadata={"cached": True},
        )
        return {"unknowns": ref, "unknowns_path": str(path), "cached": True}

    inventory = context.read_input("inventory")
    relation_map = context.read_input("relation_map")
    cluster_map = context.read_input("cluster_map")
    flow_map = context.read_input("flow_map")
    enriched_file_breakdowns = context.read_input("enriched_file_breakdowns")
    unknowns = build_unknowns(
        inventory,
        relation_map,
        cluster_map,
        flow_map,
        enriched_file_breakdowns=enriched_file_breakdowns,
    )
    write_unknowns_outputs(unknowns, context.runtime.output_dir)
    ref = context.record_artifact(UNKNOWNS_KIND, unknowns, path=path, views=views)
    return {"unknowns": ref, "unknowns_path": str(path), "cached": False}


def register(registry: CapabilityRegistry) -> None:
    registry.register(
        CapabilityDefinition(
            capability_id="report.repo_dossier.build",
            pack_id=PACK_ID,
            version="1",
            display_name="Build Repo Dossier",
            description="Build the repo dossier summary artifact.",
            capability_type="function",
            contract=CapabilityContract(
                inputs=("inventory", "relation_map", "file_breakdowns", "cluster_map", "flow_map"),
                output=("repo_dossier", "repo_dossier_path", "cached"),
            ),
            implementation_logic=_build_repo_dossier_capability,
            tags=("report", "dossier"),
        )
    )
    registry.register(
        CapabilityDefinition(
            capability_id="report.validate",
            pack_id=PACK_ID,
            version="1",
            display_name="Validate Pipeline Outputs",
            description="Validate deterministic pipeline outputs.",
            capability_type="function",
            contract=CapabilityContract(
                inputs=("inventory", "relation_map", "file_breakdowns", "flow_map"),
                output=("validation_report", "validation_report_path", "error_count", "warning_count", "cached"),
            ),
            implementation_logic=_build_validation_report_capability,
            tags=("report", "validation"),
        )
    )
    registry.register(
        CapabilityDefinition(
            capability_id="report.unknowns.build",
            pack_id=PACK_ID,
            version="1",
            display_name="Aggregate Unknown Items",
            description="Aggregate unknowns across pipeline outputs.",
            capability_type="function",
            contract=CapabilityContract(
                inputs=("inventory", "relation_map", "cluster_map", "flow_map", "enriched_file_breakdowns"),
                output=("unknowns", "unknowns_path", "cached"),
            ),
            implementation_logic=_build_unknowns_capability,
            tags=("report", "unknowns"),
        )
    )
