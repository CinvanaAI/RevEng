from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
from typing import Any, Callable

from .artifacts import ArtifactRef, ArtifactStore
from .logging import FrameworkLogSink, emit_framework_log
from reveng.platform.capabilities import (
    CapabilityContext,
    CapabilityDefinition,
    CapabilityRegistry,
)


class WorkflowRuntime:
    def __init__(
        self,
        *,
        capability_registry: CapabilityRegistry,
        output_dir: str | Path,
        run_id: str,
        workflow_id: str | None,
        cache: Any,
        provider: Any | None = None,
        permission_check: Callable[[str, dict[str, Any]], bool] | None = None,
        framework_log_sink: FrameworkLogSink | None = None,
    ) -> None:
        self.capability_registry = capability_registry
        self.output_dir = Path(output_dir).expanduser().resolve()
        self.run_id = run_id
        self.workflow_id = workflow_id
        self.cache = cache
        self.provider = provider
        self._permission_check = permission_check
        self._framework_log_sink = framework_log_sink
        self.artifacts = ArtifactStore()
        self._written_paths: list[str] = []
        self._upstream_paths: list[str] = []
        self._lock = Lock()
        emit_framework_log(
            self._framework_log_sink,
            origin="framework.runtime",
            stage="runtime_initialization",
            event_type="workflow_runtime_initialized",
            level="warning" if permission_check is None else "info",
            status="completed",
            run_id=self.run_id,
            workflow_id=self.workflow_id,
            trigger="WorkflowRuntime.__init__",
            message="Framework initialized workflow runtime state and boundary controls.",
            details={
                "output_dir": str(self.output_dir),
                "provider_configured": self.provider is not None,
                "permission_check_configured": self._permission_check is not None,
                "cache_policy": type(self.cache).__name__,
            },
            boundary_sensitive=self._permission_check is None,
            compensating_for_smeared_responsibility=self._permission_check is None,
            architectural_drift_detected=self._permission_check is None,
        )

    @property
    def written_paths(self) -> list[str]:
        with self._lock:
            return list(dict.fromkeys(self._written_paths))

    @property
    def upstream_paths(self) -> list[str]:
        with self._lock:
            return list(dict.fromkeys(self._upstream_paths))

    def invoke(self, capability_id: str, inputs: dict[str, Any]) -> dict[str, Any]:
        self._note_upstream_inputs(inputs)
        input_summary = self._summarize_inputs(inputs)

        if self._permission_check is not None:
            self._emit(
                stage="boundary",
                event_type="permission_check_started",
                level="info",
                status="started",
                capability_id=capability_id,
                trigger="WorkflowRuntime.invoke",
                message="Framework started a permission-boundary check for capability invocation.",
                details=input_summary,
                boundary_sensitive=True,
            )
            if not self._permission_check(capability_id, inputs):
                self._emit(
                    stage="boundary",
                    event_type="permission_check_denied",
                    level="error",
                    status="denied",
                    capability_id=capability_id,
                    trigger="WorkflowRuntime.invoke",
                    message="Framework denied capability invocation at the permission boundary.",
                    details=input_summary,
                    boundary_sensitive=True,
                )
                raise PermissionError(f"Permission denied for capability: {capability_id!r}")
            self._emit(
                stage="boundary",
                event_type="permission_check_allowed",
                level="info",
                status="allowed",
                capability_id=capability_id,
                trigger="WorkflowRuntime.invoke",
                message="Framework allowed capability invocation through the permission boundary.",
                details=input_summary,
                boundary_sensitive=True,
            )
        else:
            self._emit(
                stage="boundary",
                event_type="permission_check_missing",
                level="error",
                status="denied",
                capability_id=capability_id,
                trigger="WorkflowRuntime.invoke",
                message="Framework denied capability invocation because no permission check was wired.",
                details={
                    **input_summary,
                    "framework_allowed_to_proceed": False,
                },
                boundary_sensitive=True,
                compensating_for_smeared_responsibility=True,
                architectural_drift_detected=True,
            )
            raise PermissionError(
                f"Permission check missing for capability: {capability_id!r}"
            )

        self._emit(
            stage="invocation",
            event_type="capability_lookup_started",
            level="info",
            status="started",
            capability_id=capability_id,
            trigger="WorkflowRuntime.invoke",
            message="Framework started resolving the capability object from the live registry.",
            details=input_summary,
        )
        try:
            definition = self.capability_registry.get(capability_id)
        except KeyError:
            self._emit(
                stage="invocation",
                event_type="capability_lookup_failed",
                level="error",
                status="failed",
                capability_id=capability_id,
                trigger="WorkflowRuntime.invoke",
                message="Framework could not resolve the requested capability object.",
                details={"known_capability_ids": self.capability_registry.list_ids()},
            )
            raise
        self._emit(
            stage="invocation",
            event_type="capability_lookup_resolved",
            level="info",
            status="completed",
            capability_id=capability_id,
            trigger="WorkflowRuntime.invoke",
            message="Framework resolved the capability object and prepared invocation.",
            details={
                **input_summary,
                "capability_type": definition.capability_type,
                "pack_id": definition.pack_id,
            },
        )
        self._emit(
            stage="invocation",
            event_type="capability_invocation_started",
            level="info",
            status="started",
            capability_id=capability_id,
            trigger="WorkflowRuntime.invoke",
            message="Framework started capability execution.",
            details={
                **input_summary,
                "capability_type": definition.capability_type,
            },
        )

        try:
            if definition.capability_type == "function":
                context = CapabilityContext(spec=definition, runtime=self, inputs=inputs)
                result = definition.implementation_logic(context)
            else:
                result = self._invoke_combination(definition, inputs)
        except Exception as exc:
            self._emit(
                stage="invocation",
                event_type="capability_invocation_failed",
                level="error",
                status="failed",
                capability_id=capability_id,
                trigger="WorkflowRuntime.invoke",
                message="Framework observed a capability execution failure.",
                details={
                    "capability_type": definition.capability_type,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                },
            )
            raise

        self._emit(
            stage="invocation",
            event_type="capability_invocation_completed",
            level="info",
            status="completed",
            capability_id=capability_id,
            trigger="WorkflowRuntime.invoke",
            message="Framework completed capability execution.",
            details={
                "capability_type": definition.capability_type,
                "result_keys": sorted(result) if isinstance(result, dict) else [],
            },
        )
        return result

    def _invoke_combination(
        self,
        definition: CapabilityDefinition,
        inputs: dict[str, Any],
    ) -> dict[str, Any]:
        spec = definition.combination  # guaranteed non-None by validate_capability
        self._emit(
            stage="invocation",
            event_type="combination_execution_started",
            level="info",
            status="started",
            capability_id=definition.capability_id,
            trigger="WorkflowRuntime._invoke_combination",
            message="Framework started executing a combination capability.",
            details={
                "component_capabilities": list(spec.component_capabilities),
                "execution_order": list(spec.execution_order),
            },
        )
        merged: dict[str, Any] = {}
        per_component: dict[str, dict[str, Any]] = {}
        for component_id in spec.execution_order:
            component_result = self.invoke(component_id, inputs)
            per_component[component_id] = component_result
            merged.update(component_result)
            self._emit(
                stage="invocation",
                event_type="combination_component_merged",
                level="info",
                status="completed",
                capability_id=definition.capability_id,
                trigger="WorkflowRuntime._invoke_combination",
                message="Framework merged a component result into the combination payload.",
                details={
                    "component_id": component_id,
                    "component_result_keys": sorted(component_result),
                    "merged_key_count": len(merged),
                },
            )
        result = spec.combination_logic(
            {
                "merged": merged,
                "per_component": per_component,
                "execution_order": tuple(spec.execution_order),
            }
        )
        self._emit(
            stage="invocation",
            event_type="combination_logic_completed",
            level="info",
            status="completed",
            capability_id=definition.capability_id,
            trigger="WorkflowRuntime._invoke_combination",
            message="Framework applied combination logic to the collected component payloads.",
            details={
                "component_count": len(per_component),
                "result_keys": sorted(result) if isinstance(result, dict) else [],
            },
        )
        return result

    def _emit(
        self,
        *,
        stage: str,
        event_type: str,
        level: str,
        status: str,
        message: str,
        trigger: str,
        capability_id: str | None = None,
        details: dict[str, Any] | None = None,
        boundary_sensitive: bool = False,
        compensating_for_smeared_responsibility: bool = False,
        architectural_drift_detected: bool = False,
    ) -> None:
        emit_framework_log(
            self._framework_log_sink,
            origin="framework.runtime",
            stage=stage,
            event_type=event_type,
            level=level,
            status=status,
            run_id=self.run_id,
            workflow_id=self.workflow_id,
            capability_id=capability_id,
            trigger=trigger,
            message=message,
            details=details,
            boundary_sensitive=boundary_sensitive,
            compensating_for_smeared_responsibility=compensating_for_smeared_responsibility,
            architectural_drift_detected=architectural_drift_detected,
        )

    def record_artifact(
        self,
        kind: str,
        value: Any,
        *,
        path: str | Path | None = None,
        views: dict[str, str | Path] | None = None,
        metadata: dict[str, Any] | None = None,
        written: bool,
    ) -> ArtifactRef:
        ref = self.artifacts.put(
            kind,
            value,
            path=path,
            views=views,
            metadata=metadata,
        )
        if written:
            self._note_paths(path, views)
        self._emit(
            stage="artifact_tracking",
            event_type="artifact_recorded",
            level="info",
            status="completed",
            trigger="WorkflowRuntime.record_artifact",
            message="Framework recorded an artifact into runtime state and tracked its written paths.",
            details={
                "artifact_kind": kind,
                "artifact_path": str(path) if path is not None else None,
                "view_count": len(views or {}),
                "written": written,
            },
        )
        return ref

    def load_cached_json_artifact(
        self,
        kind: str,
        path: str | Path,
        *,
        views: dict[str, str | Path] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ArtifactRef:
        resolved = Path(path)
        self._note_upstream_path(resolved)
        ref = self.artifacts.put_loaded(
            kind,
            resolved,
            loader=self.load_json_path,
            views=views,
            metadata=metadata,
        )
        self._emit(
            stage="artifact_tracking",
            event_type="cached_artifact_loaded",
            level="info",
            status="completed",
            trigger="WorkflowRuntime.load_cached_json_artifact",
            message="Framework loaded a cached JSON artifact into runtime state.",
            details={
                "artifact_kind": kind,
                "artifact_path": str(resolved),
                "view_count": len(views or {}),
            },
        )
        return ref

    def read_input(self, value: Any) -> Any:
        if isinstance(value, ArtifactRef):
            return self.artifacts.read(value)
        return value

    def path_for(self, value: Any) -> str | None:
        if isinstance(value, ArtifactRef):
            return self.artifacts.path(value)
        return None

    def load_json_path(self, path: Path) -> Any:
        return json.loads(path.read_text(encoding="utf-8"))

    def _note_upstream_inputs(self, inputs: dict[str, Any]) -> None:
        for value in inputs.values():
            if isinstance(value, ArtifactRef):
                path = self.artifacts.path(value)
                if path:
                    self._note_upstream_path(path)

    def _note_upstream_path(self, path: str | Path) -> None:
        with self._lock:
            self._upstream_paths.append(str(path))

    def _note_paths(
        self,
        path: str | Path | None,
        views: dict[str, str | Path] | None,
    ) -> None:
        with self._lock:
            if path is not None:
                self._written_paths.append(str(path))
            for item in (views or {}).values():
                self._written_paths.append(str(item))

    def _summarize_inputs(self, inputs: dict[str, Any]) -> dict[str, Any]:
        artifact_input_count = 0
        artifact_paths: list[str] = []
        for value in inputs.values():
            if not isinstance(value, ArtifactRef):
                continue
            artifact_input_count += 1
            path = self.artifacts.path(value)
            if path:
                artifact_paths.append(path)
        return {
            "input_keys": sorted(inputs),
            "artifact_input_count": artifact_input_count,
            "artifact_input_paths": artifact_paths,
        }
