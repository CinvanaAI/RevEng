from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .cache import ExistsAndNonEmptyCachePolicy
from .logging import FrameworkLogSink, emit_framework_log
from .runtime import WorkflowRuntime
from .workflows import WorkflowRegistry
from reveng.platform.capabilities import CapabilityRegistry


@dataclass(slots=True)
class WorkflowRunResult:
    outputs: dict[str, Any]
    written_paths: list[str]
    upstream_paths: list[str]


class RevEngHost:
    def __init__(
        self,
        *,
        capability_registry: CapabilityRegistry | None = None,
        workflow_registry: WorkflowRegistry | None = None,
        cache_policy: Any | None = None,
        provider: Any | None = None,
        framework_log_sink: FrameworkLogSink | None = None,
        run_id: str | None = None,
        workflow_id: str | None = None,
        bootstrap_trigger: str | None = None,
    ) -> None:
        self._framework_log_sink = framework_log_sink
        self.capabilities = capability_registry or CapabilityRegistry(
            framework_log_sink=framework_log_sink,
            run_id=run_id,
            workflow_id=workflow_id,
            trigger=bootstrap_trigger,
        )
        self.workflows = workflow_registry or WorkflowRegistry(
            framework_log_sink=framework_log_sink,
            run_id=run_id,
            trigger=bootstrap_trigger,
        )
        self.cache_policy = cache_policy or ExistsAndNonEmptyCachePolicy()
        self.provider = provider
        defaults_used: list[str] = []
        if capability_registry is None:
            defaults_used.append("capability_registry")
        if workflow_registry is None:
            defaults_used.append("workflow_registry")
        if cache_policy is None:
            defaults_used.append("cache_policy")
        emit_framework_log(
            self._framework_log_sink,
            origin="framework.host",
            stage="host_composition",
            event_type="host_initialized",
            level="warning" if defaults_used else "info",
            status="completed",
            run_id=run_id,
            workflow_id=workflow_id,
            trigger=bootstrap_trigger or "RevEngHost.__init__",
            message="Framework initialized the host shell and its core registries.",
            details={
                "defaults_used": defaults_used,
                "provider_configured": provider is not None,
            },
            compensating_for_smeared_responsibility=bool(defaults_used),
        )

    def run_workflow(
        self,
        workflow_id: str,
        *,
        inputs: dict[str, Any],
        output_dir: str | Path,
        run_id: str,
        permission_check: Callable[[str, dict[str, Any]], bool] | None = None,
    ) -> WorkflowRunResult:
        emit_framework_log(
            self._framework_log_sink,
            origin="framework.host",
            stage="workflow_lookup",
            event_type="workflow_lookup_started",
            level="info",
            status="started",
            run_id=run_id,
            workflow_id=workflow_id,
            trigger="RevEngHost.run_workflow",
            message="Framework started resolving the requested workflow.",
            details={
                "input_keys": sorted(inputs),
                "output_dir": str(Path(output_dir)),
            },
        )
        try:
            workflow = self.workflows.get(workflow_id)
        except KeyError:
            emit_framework_log(
                self._framework_log_sink,
                origin="framework.host",
                stage="workflow_lookup",
                event_type="workflow_lookup_failed",
                level="error",
                status="failed",
                run_id=run_id,
                workflow_id=workflow_id,
                trigger="RevEngHost.run_workflow",
                message="Framework could not resolve the requested workflow.",
                details={"known_workflow_ids": self.workflows.list_ids()},
            )
            raise
        emit_framework_log(
            self._framework_log_sink,
            origin="framework.host",
            stage="workflow_lookup",
            event_type="workflow_lookup_resolved",
            level="info",
            status="completed",
            run_id=run_id,
            workflow_id=workflow_id,
            trigger="RevEngHost.run_workflow",
            message="Framework resolved the requested workflow from the live registry.",
            details={"description": workflow.description},
        )
        runtime = WorkflowRuntime(
            capability_registry=self.capabilities,
            output_dir=Path(output_dir),
            run_id=run_id,
            workflow_id=workflow_id,
            cache=self.cache_policy,
            provider=self.provider,
            permission_check=permission_check,
            framework_log_sink=self._framework_log_sink,
        )
        emit_framework_log(
            self._framework_log_sink,
            origin="framework.host",
            stage="workflow_execution",
            event_type="workflow_execution_started",
            level="info",
            status="started",
            run_id=run_id,
            workflow_id=workflow_id,
            trigger="RevEngHost.run_workflow",
            message="Framework handed control to the workflow handler.",
            details={"provider_configured": self.provider is not None},
        )
        try:
            outputs = workflow.handler(runtime, inputs)
        except Exception as exc:
            emit_framework_log(
                self._framework_log_sink,
                origin="framework.host",
                stage="workflow_execution",
                event_type="workflow_execution_failed",
                level="error",
                status="failed",
                run_id=run_id,
                workflow_id=workflow_id,
                trigger="RevEngHost.run_workflow",
                message="Framework observed a workflow failure while executing the handler.",
                details={
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                },
            )
            raise
        emit_framework_log(
            self._framework_log_sink,
            origin="framework.host",
            stage="workflow_execution",
            event_type="workflow_execution_completed",
            level="info",
            status="completed",
            run_id=run_id,
            workflow_id=workflow_id,
            trigger="RevEngHost.run_workflow",
            message="Framework completed workflow execution and collected output paths.",
            details={
                "output_keys": sorted(outputs),
                "written_path_count": len(runtime.written_paths),
                "upstream_path_count": len(runtime.upstream_paths),
            },
        )
        return WorkflowRunResult(
            outputs=outputs,
            written_paths=runtime.written_paths,
            upstream_paths=runtime.upstream_paths,
        )
