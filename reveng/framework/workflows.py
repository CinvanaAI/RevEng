from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

from .logging import FrameworkLogSink, emit_framework_log

if TYPE_CHECKING:
    from .runtime import WorkflowRuntime


WorkflowHandler = Callable[["WorkflowRuntime", dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True, slots=True)
class WorkflowDefinition:
    workflow_id: str
    description: str
    handler: WorkflowHandler


class WorkflowRegistry:
    def __init__(
        self,
        *,
        framework_log_sink: FrameworkLogSink | None = None,
        run_id: str | None = None,
        trigger: str | None = None,
    ) -> None:
        self._definitions: dict[str, WorkflowDefinition] = {}
        self._framework_log_sink = framework_log_sink
        self._run_id = run_id
        self._trigger = trigger

    def register(self, definition: WorkflowDefinition) -> None:
        if definition.workflow_id in self._definitions:
            emit_framework_log(
                self._framework_log_sink,
                origin="framework.workflow_registry",
                stage="registration",
                event_type="duplicate_workflow_rejected",
                level="error",
                status="failed",
                run_id=self._run_id,
                workflow_id=definition.workflow_id,
                trigger=self._trigger or "WorkflowRegistry.register",
                message="Framework rejected a duplicate workflow registration attempt.",
                details={"reason": "duplicate workflow_id"},
            )
            raise ValueError(f"Workflow already registered: {definition.workflow_id}")
        self._definitions[definition.workflow_id] = definition
        emit_framework_log(
            self._framework_log_sink,
            origin="framework.workflow_registry",
            stage="registration",
            event_type="workflow_registered",
            level="info",
            status="completed",
            run_id=self._run_id,
            workflow_id=definition.workflow_id,
            trigger=self._trigger or "WorkflowRegistry.register",
            message="Framework installed a workflow into the live workflow registry.",
            details={
                "description": definition.description,
                "registry_size": len(self._definitions),
            },
        )

    def get(self, workflow_id: str) -> WorkflowDefinition:
        try:
            return self._definitions[workflow_id]
        except KeyError as exc:
            raise KeyError(f"Unknown workflow: {workflow_id}") from exc

    def list_ids(self) -> list[str]:
        return sorted(self._definitions)
