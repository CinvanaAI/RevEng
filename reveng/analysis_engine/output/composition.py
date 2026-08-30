"""OutputComposer — assembles all meaning layer outputs into multiple products.

Design principle: output is abundant. Multiple independent per-layer outputs,
not collapsed into one canonical artifact. Each output is independently valid.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from reveng.analysis_engine.meaning.records import SystemMap
from reveng.analysis_engine.output.crossrefs import build_cross_reference_index
from reveng.analysis_engine.output.health import render_run_health
from reveng.analysis_engine.output.renderers import (
    render_abilities,
    render_actions,
    render_file_behaviors,
    render_file_purposes,
    render_function_meanings,
    render_module_summaries,
    render_subsystem_summaries,
    render_system_map,
    render_system_summary,
    render_workflows,
)


class OutputComposer:
    def __init__(self, output_dir: Path) -> None:
        self._output_dir = output_dir

    def compose(
        self,
        base_result: dict[str, Any],
        meaning_result: dict[str, Any],
        *,
        runtime: Any,
        validation_data: dict[str, Any] | None = None,
    ) -> SystemMap:
        """Compose all outputs from base analysis + meaning results.

        Reads all ArtifactRefs via runtime, writes per-layer markdown files,
        system_map.json + system_map.md, and crossref_index.json.

        Returns a dict of all written output paths.
        """
        # Resolve ArtifactRefs to plain data
        def _read(key: str, source: dict) -> Any:
            value = source.get(key)
            if value is None:
                return []
            try:
                return runtime.read_input(key) if hasattr(runtime, "read_input") else value
            except Exception:
                return value

        # Pull the data out — handle both plain lists and ArtifactRefs
        ability_records = self._resolve(meaning_result.get("ability_records"), runtime)
        action_records = self._resolve(meaning_result.get("action_records"), runtime)
        function_meanings = self._resolve(meaning_result.get("function_meaning_records"), runtime)
        file_purposes = self._resolve(meaning_result.get("file_purpose_records"), runtime)
        file_behaviors = self._resolve(meaning_result.get("file_behavior_records"), runtime)
        workflow_records = self._resolve(meaning_result.get("workflow_records"), runtime)
        module_summaries = self._resolve(meaning_result.get("module_summary_records"), runtime)
        subsystem_summaries = self._resolve(meaning_result.get("subsystem_summary_records"), runtime)
        system_summary = self._resolve(meaning_result.get("system_summary_record"), runtime)

        if not isinstance(system_summary, dict):
            system_summary = {}

        output_dir = self._output_dir

        # Write per-layer markdown files
        ability_md = render_abilities(ability_records, output_dir)
        action_md = render_actions(action_records, output_dir)
        function_md = render_function_meanings(function_meanings, output_dir)
        purpose_md = render_file_purposes(file_purposes, output_dir)
        behavior_md = render_file_behaviors(file_behaviors, output_dir)
        workflow_md = render_workflows(workflow_records, output_dir)
        module_md = render_module_summaries(module_summaries, output_dir)
        subsystem_md = render_subsystem_summaries(subsystem_summaries, output_dir)
        system_md = render_system_summary(system_summary, output_dir)

        # Write system_map.json + system_map.md
        system_map_data = {
            "ability_records": ability_records,
            "action_records": action_records,
            "function_meaning_records": function_meanings,
            "file_purpose_records": file_purposes,
            "file_behavior_records": file_behaviors,
            "workflow_records": workflow_records,
            "module_summary_records": module_summaries,
            "subsystem_summary_records": subsystem_summaries,
            "system_summary_record": system_summary,
        }
        system_map_path, system_map_md_path = render_system_map(system_map_data, output_dir)

        # Write crossref_index.json
        crossref = build_cross_reference_index(system_map_data)
        crossref_path = output_dir / "meaning" / "crossref_index.json"
        crossref_path.write_text(json.dumps(crossref, indent=2), encoding="utf-8")

        # Write meaning-layer validation violations (computed by the workflow before compose)
        if validation_data is None:
            validation_data = {"meaning_violations": [], "crossref_violations": [], "total_violations": 0}
        validation_path = output_dir / "meaning" / "validation_violations.json"
        validation_path.write_text(json.dumps(validation_data, indent=2), encoding="utf-8")

        # Write run_health.md
        health_path = render_run_health(system_map_data, validation_data, output_dir)

        output_paths = {
            "ability_records_md_path": str(ability_md),
            "action_records_md_path": str(action_md),
            "function_meanings_md_path": str(function_md),
            "file_purposes_md_path": str(purpose_md),
            "file_behaviors_md_path": str(behavior_md),
            "workflows_md_path": str(workflow_md),
            "module_summaries_md_path": str(module_md),
            "subsystem_summaries_md_path": str(subsystem_md),
            "system_summary_md_path": str(system_md),
            "system_map_path": str(system_map_path),
            "system_map_md_path": str(system_map_md_path),
            "crossref_index_path": str(crossref_path),
            "validation_violations_path": str(validation_path),
            "validation_violation_count": validation_data["total_violations"],
            "run_health_path": str(health_path),
        }

        return SystemMap(
            ability_records=ability_records if isinstance(ability_records, list) else [],
            action_records=action_records if isinstance(action_records, list) else [],
            function_meaning_records=function_meanings if isinstance(function_meanings, list) else [],
            file_purpose_records=file_purposes if isinstance(file_purposes, list) else [],
            file_behavior_records=file_behaviors if isinstance(file_behaviors, list) else [],
            workflow_records=workflow_records if isinstance(workflow_records, list) else [],
            module_summary_records=module_summaries if isinstance(module_summaries, list) else [],
            subsystem_summary_records=subsystem_summaries if isinstance(subsystem_summaries, list) else [],
            system_summary_record=system_summary if isinstance(system_summary, dict) else None,
            output_paths=output_paths,
        )

    def _resolve(self, value: Any, runtime: Any) -> Any:
        """Resolve an ArtifactRef to its data, or return value as-is if already plain."""
        if value is None:
            return []
        # ArtifactRef objects have a .kind attribute; resolve via read_input()
        if hasattr(value, "kind") or hasattr(value, "artifact_id"):
            try:
                return runtime.read_input(value)
            except Exception:
                return []
        return value
