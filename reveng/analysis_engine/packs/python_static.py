from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from reveng.analysis_engine.analysis.cluster_builder import build_cluster_map
from reveng.analysis_engine.analysis.enricher import build_enriched_file_breakdowns
from reveng.analysis_engine.analysis.extractor import extract_file_record, module_name_from_path
from reveng.analysis_engine.analysis.file_breakdowns import build_file_breakdowns
from reveng.analysis_engine.analysis.flow_builder import build_flow_map
from reveng.analysis_engine.analysis.relations import build_relation_map
from reveng.analysis_engine.analysis.scanner import iter_python_files
from reveng.analysis_engine.analysis.context_builder import build_per_file_context
from reveng.platform.capabilities import (
    CapabilityContext,
    CapabilityContract,
    CapabilityDefinition,
    CapabilityRegistry,
)
from reveng.storage.paths import (
    cluster_map_json_path,
    enriched_json_path,
    file_breakdowns_json_path,
    flow_map_json_path,
    inventory_json_path,
    relation_map_json_path,
)
from reveng.storage.writers.cluster_writer import write_cluster_outputs
from reveng.storage.writers.enriched_writer import write_enriched_file_breakdown_outputs
from reveng.storage.writers.file_breakdown_writer import (
    write_file_breakdown_outputs,
    write_file_breakdown_per_file_outputs,
)
from reveng.storage.writers.flow_writer import write_flow_outputs
from reveng.storage.writers.relation_writer import write_relation_outputs
from reveng.storage.writers.writer import write_inventory_outputs

PACK_ID = "reveng.pack.python_static"

SCAN_RESULT_KIND = "python.scan_result.v1"
FILE_RECORD_KIND = "python.file_record.v1"
INVENTORY_KIND = "python.inventory.v1"
RELATION_MAP_KIND = "python.relation_map.v1"
FILE_BREAKDOWNS_KIND = "python.file_breakdowns.v1"
ENRICHED_BREAKDOWNS_KIND = "python.enriched_file_breakdowns.v1"
CLUSTER_MAP_KIND = "python.cluster_map.v1"
FLOW_MAP_KIND = "python.flow_map.v1"


def _json_views(path: Path, **extra: str | Path) -> dict[str, str | Path]:
    views: dict[str, str | Path] = {"markdown": path.with_suffix(".md")}
    views.update(extra)
    return views


def _scan_repo(context: CapabilityContext) -> dict[str, Any]:
    repo_root = Path(context.require("repo_path")).expanduser().resolve()
    if repo_root.is_file():
        repo_root = repo_root.parent
    visible_file_paths = context.get("visible_file_paths")
    allowed_paths = (
        {
            str(Path(path).expanduser().resolve())
            for path in visible_file_paths
        }
        if isinstance(visible_file_paths, list)
        else None
    )
    file_paths = sorted(
        str(path)
        for path in iter_python_files(repo_root)
        if allowed_paths is None or str(path.resolve()) in allowed_paths
    )
    scan_result = {
        "repo_root": str(repo_root),
        "file_paths": file_paths,
        "file_count": len(file_paths),
    }
    ref = context.record_artifact(SCAN_RESULT_KIND, scan_result)
    return {
        "scan_result": ref,
        "repo_root": str(repo_root),
        "file_count": len(file_paths),
    }


def _extract_file(context: CapabilityContext) -> dict[str, Any]:
    repo_root = Path(context.require("repo_root"))
    file_path = Path(context.require("file_path"))

    try:
        file_record = extract_file_record(repo_root, file_path)
    except SyntaxError as exc:
        rel_path = file_path.relative_to(repo_root).as_posix()
        file_record = {
            "path": rel_path,
            "module_name": module_name_from_path(repo_root, file_path),
            "parse_error": f"SyntaxError: {exc}",
        }

    ref = context.record_artifact(FILE_RECORD_KIND, file_record)
    return {"file_record": ref}


def _assemble_inventory(context: CapabilityContext) -> dict[str, Any]:
    path = inventory_json_path(context.runtime.output_dir)
    views = _json_views(path)

    if context.cache_ready(path, output_name="inventory"):
        ref = context.load_cached_json_artifact(
            INVENTORY_KIND,
            path,
            views=views,
            metadata={"cached": True},
        )
        return {"inventory": ref, "inventory_path": str(path), "cached": True}

    file_records = list(context.require("file_records"))
    scanned_at = context.get("scanned_at") or datetime.now(UTC).isoformat()
    inventory = {
        "repo_root": context.require("repo_root"),
        "scanned_at": scanned_at,
        "file_count": len(file_records),
        "files": file_records,
    }
    write_inventory_outputs(inventory, context.runtime.output_dir)
    ref = context.record_artifact(INVENTORY_KIND, inventory, path=path, views=views)
    return {"inventory": ref, "inventory_path": str(path), "cached": False}


def _build_relation_map_capability(context: CapabilityContext) -> dict[str, Any]:
    path = relation_map_json_path(context.runtime.output_dir)
    views = _json_views(path)

    if context.cache_ready(path, output_name="relation_map"):
        ref = context.load_cached_json_artifact(
            RELATION_MAP_KIND,
            path,
            views=views,
            metadata={"cached": True},
        )
        return {"relation_map": ref, "relation_map_path": str(path), "cached": True}

    inventory = context.read_input("inventory")
    relation_map = build_relation_map(inventory)
    write_relation_outputs(relation_map, context.runtime.output_dir)
    ref = context.record_artifact(RELATION_MAP_KIND, relation_map, path=path, views=views)
    return {"relation_map": ref, "relation_map_path": str(path), "cached": False}


def _build_file_breakdowns_capability(context: CapabilityContext) -> dict[str, Any]:
    path = file_breakdowns_json_path(context.runtime.output_dir)
    views = _json_views(path, details_dir=context.runtime.output_dir / "file_breakdowns")

    if context.cache_ready(path, output_name="file_breakdowns"):
        ref = context.load_cached_json_artifact(
            FILE_BREAKDOWNS_KIND,
            path,
            views=views,
            metadata={"cached": True},
        )
        return {"file_breakdowns": ref, "file_breakdowns_path": str(path), "cached": True}

    inventory = context.read_input("inventory")
    relation_map = context.read_input("relation_map")
    file_breakdowns = build_file_breakdowns(inventory, relation_map)
    write_file_breakdown_outputs(file_breakdowns, context.runtime.output_dir)
    write_file_breakdown_per_file_outputs(file_breakdowns, context.runtime.output_dir)
    ref = context.record_artifact(FILE_BREAKDOWNS_KIND, file_breakdowns, path=path, views=views)
    return {"file_breakdowns": ref, "file_breakdowns_path": str(path), "cached": False}


def _build_enriched_breakdowns_capability(context: CapabilityContext) -> dict[str, Any]:
    path = enriched_json_path(context.runtime.output_dir)
    views = _json_views(path)

    if context.cache_ready(path, output_name="enriched_file_breakdowns"):
        ref = context.load_cached_json_artifact(
            ENRICHED_BREAKDOWNS_KIND,
            path,
            views=views,
            metadata={"cached": True},
        )
        return {"enriched_file_breakdowns": ref, "enriched_path": str(path), "cached": True}

    file_breakdowns = context.read_input("file_breakdowns")
    enriched = build_enriched_file_breakdowns(file_breakdowns)
    write_enriched_file_breakdown_outputs(enriched, context.runtime.output_dir)
    ref = context.record_artifact(
        ENRICHED_BREAKDOWNS_KIND,
        enriched,
        path=path,
        views=views,
    )
    return {"enriched_file_breakdowns": ref, "enriched_path": str(path), "cached": False}


def _build_cluster_map_capability(context: CapabilityContext) -> dict[str, Any]:
    path = cluster_map_json_path(context.runtime.output_dir)
    views = _json_views(path, details_dir=context.runtime.output_dir / "subsystem_breakdowns")

    if context.cache_ready(path, output_name="cluster_map"):
        ref = context.load_cached_json_artifact(
            CLUSTER_MAP_KIND,
            path,
            views=views,
            metadata={"cached": True},
        )
        return {"cluster_map": ref, "cluster_map_path": str(path), "cached": True}

    inventory = context.read_input("inventory")
    relation_map = context.read_input("relation_map")
    cluster_map = build_cluster_map(inventory, relation_map)
    write_cluster_outputs(cluster_map, context.runtime.output_dir)
    ref = context.record_artifact(CLUSTER_MAP_KIND, cluster_map, path=path, views=views)
    return {"cluster_map": ref, "cluster_map_path": str(path), "cached": False}


def _build_flow_map_capability(context: CapabilityContext) -> dict[str, Any]:
    path = flow_map_json_path(context.runtime.output_dir)
    views = _json_views(path, details_dir=context.runtime.output_dir / "flow_breakdowns")

    if context.cache_ready(path, output_name="flow_map"):
        ref = context.load_cached_json_artifact(
            FLOW_MAP_KIND,
            path,
            views=views,
            metadata={"cached": True},
        )
        return {"flow_map": ref, "flow_map_path": str(path), "cached": True}

    inventory = context.read_input("inventory")
    relation_map = context.read_input("relation_map")
    cluster_map = context.read_input("cluster_map")
    flow_map = build_flow_map(inventory, relation_map, cluster_map)
    write_flow_outputs(flow_map, context.runtime.output_dir)
    ref = context.record_artifact(FLOW_MAP_KIND, flow_map, path=path, views=views)
    return {"flow_map": ref, "flow_map_path": str(path), "cached": False}


def _build_per_file_context_capability(context: CapabilityContext) -> dict[str, Any]:
    cluster_map = context.read_input("cluster_map")
    flow_map = context.read_input("flow_map")
    per_file_context = build_per_file_context(cluster_map, flow_map)
    return {"per_file_context": per_file_context}


def register(registry: CapabilityRegistry) -> None:
    registry.register(
        CapabilityDefinition(
            capability_id="python.scan_repo",
            pack_id=PACK_ID,
            version="1",
            display_name="Scan Python Repository",
            description="Discover Python files in a repository.",
            capability_type="function",
            contract=CapabilityContract(
                inputs=("repo_path", "visible_file_paths"),
                output=("scan_result", "repo_root", "file_count"),
            ),
            implementation_logic=_scan_repo,
            tags=("python", "scan"),
        )
    )
    registry.register(
        CapabilityDefinition(
            capability_id="python.extract_file",
            pack_id=PACK_ID,
            version="1",
            display_name="Extract Python File Record",
            description="Extract one Python file into a structural record.",
            capability_type="function",
            contract=CapabilityContract(
                inputs=("repo_root", "file_path", "allowed_file_paths"),
                output=("file_record",),
            ),
            implementation_logic=_extract_file,
            tags=("python", "ast"),
        )
    )
    registry.register(
        CapabilityDefinition(
            capability_id="python.inventory.assemble",
            pack_id=PACK_ID,
            version="1",
            display_name="Assemble Repo Inventory",
            description="Assemble the repo inventory artifact.",
            capability_type="function",
            contract=CapabilityContract(
                inputs=("repo_root", "file_records", "scanned_at"),
                output=("inventory", "inventory_path", "cached"),
            ),
            implementation_logic=_assemble_inventory,
            tags=("python", "inventory"),
        )
    )
    registry.register(
        CapabilityDefinition(
            capability_id="python.relations.build",
            pack_id=PACK_ID,
            version="1",
            display_name="Build Relation Graph",
            description="Build the relation graph from inventory data.",
            capability_type="function",
            contract=CapabilityContract(
                inputs=("inventory",),
                output=("relation_map", "relation_map_path", "cached"),
            ),
            implementation_logic=_build_relation_map_capability,
            tags=("python", "relations"),
        )
    )
    registry.register(
        CapabilityDefinition(
            capability_id="python.file_breakdowns.build",
            pack_id=PACK_ID,
            version="1",
            display_name="Build File Breakdowns",
            description="Build per-file breakdowns from inventory and relations.",
            capability_type="function",
            contract=CapabilityContract(
                inputs=("inventory", "relation_map"),
                output=("file_breakdowns", "file_breakdowns_path", "cached"),
            ),
            implementation_logic=_build_file_breakdowns_capability,
            tags=("python", "breakdowns"),
        )
    )
    registry.register(
        CapabilityDefinition(
            capability_id="python.file_breakdowns.enrich",
            pack_id=PACK_ID,
            version="1",
            display_name="Enrich File Breakdowns",
            description="Enrich file breakdowns with derived observations.",
            capability_type="function",
            contract=CapabilityContract(
                inputs=("file_breakdowns",),
                output=("enriched_file_breakdowns", "enriched_path", "cached"),
            ),
            implementation_logic=_build_enriched_breakdowns_capability,
            tags=("python", "breakdowns"),
        )
    )
    registry.register(
        CapabilityDefinition(
            capability_id="python.clusters.build",
            pack_id=PACK_ID,
            version="1",
            display_name="Build Subsystem Cluster Map",
            description="Build the subsystem cluster map.",
            capability_type="function",
            contract=CapabilityContract(
                inputs=("inventory", "relation_map"),
                output=("cluster_map", "cluster_map_path", "cached"),
            ),
            implementation_logic=_build_cluster_map_capability,
            tags=("python", "clusters"),
        )
    )
    registry.register(
        CapabilityDefinition(
            capability_id="python.flows.build",
            pack_id=PACK_ID,
            version="1",
            display_name="Build Flow Map",
            description="Build the flow map from relation and cluster data.",
            capability_type="function",
            contract=CapabilityContract(
                inputs=("inventory", "relation_map", "cluster_map"),
                output=("flow_map", "flow_map_path", "cached"),
            ),
            implementation_logic=_build_flow_map_capability,
            tags=("python", "flows"),
        )
    )
    registry.register(
        CapabilityDefinition(
            capability_id="python.context.per_file.build",
            pack_id=PACK_ID,
            version="1",
            display_name="Build Per-File Structural Context",
            description="Build per-file structural context from cluster and flow maps.",
            capability_type="function",
            contract=CapabilityContract(
                inputs=("cluster_map", "flow_map"),
                output=("per_file_context",),
            ),
            implementation_logic=_build_per_file_context_capability,
            tags=("python", "context"),
        )
    )
