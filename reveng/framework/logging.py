from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal


FrameworkLogLevel = Literal["debug", "info", "warning", "error"]
FrameworkLogStatus = Literal[
    "started",
    "completed",
    "failed",
    "decision",
    "observed",
    "allowed",
    "denied",
]


@dataclass(frozen=True, slots=True)
class FrameworkLogRecord:
    origin: str
    stage: str
    event_type: str
    level: FrameworkLogLevel
    message: str
    status: FrameworkLogStatus
    run_id: str | None = None
    workflow_id: str | None = None
    capability_id: str | None = None
    trigger: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    boundary_sensitive: bool = False
    lawful_framework_behavior: bool = True
    compensating_for_smeared_responsibility: bool = False
    architectural_drift_detected: bool = False


FrameworkLogSink = Callable[[FrameworkLogRecord], None]


def emit_framework_log(
    sink: FrameworkLogSink | None,
    *,
    origin: str,
    stage: str,
    event_type: str,
    level: FrameworkLogLevel,
    message: str,
    status: FrameworkLogStatus,
    run_id: str | None = None,
    workflow_id: str | None = None,
    capability_id: str | None = None,
    trigger: str | None = None,
    details: dict[str, Any] | None = None,
    boundary_sensitive: bool = False,
    lawful_framework_behavior: bool = True,
    compensating_for_smeared_responsibility: bool = False,
    architectural_drift_detected: bool = False,
) -> None:
    if sink is None:
        return
    sink(
        FrameworkLogRecord(
            origin=origin,
            stage=stage,
            event_type=event_type,
            level=level,
            message=message,
            status=status,
            run_id=run_id,
            workflow_id=workflow_id,
            capability_id=capability_id,
            trigger=trigger,
            details=_normalize_mapping(details or {}),
            boundary_sensitive=boundary_sensitive,
            lawful_framework_behavior=lawful_framework_behavior,
            compensating_for_smeared_responsibility=compensating_for_smeared_responsibility,
            architectural_drift_detected=architectural_drift_detected,
        )
    )


def _normalize_mapping(data: dict[str, Any]) -> dict[str, Any]:
    return {str(key): _normalize_value(value) for key, value in data.items()}


def _normalize_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _normalize_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_normalize_value(item) for item in value]
    return repr(value)
