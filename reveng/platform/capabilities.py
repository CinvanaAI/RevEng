"""Platform-owned capability semantics and live capability registry projection."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Literal

from reveng.framework.artifacts import ArtifactRef
from reveng.framework.logging import FrameworkLogSink, emit_framework_log

if TYPE_CHECKING:
    from reveng.framework.runtime import WorkflowRuntime


ImplementationLogic = Callable[["CapabilityContext"], dict[str, Any]]
CombinationLogic = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True, slots=True)
class CapabilityContract:
    inputs: tuple[str, ...] = ()
    output: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CombinationSpec:
    component_capabilities: tuple[str, ...]
    execution_order: tuple[str, ...]
    combination_logic: CombinationLogic


@dataclass(frozen=True, slots=True)
class CapabilityDefinition:
    # Identity
    capability_id: str
    pack_id: str
    version: str
    display_name: str
    description: str
    capability_type: Literal["function", "composite"]
    # Contract
    contract: CapabilityContract
    # Implementation (function only — active when capability_type == "function")
    implementation_logic: ImplementationLogic | None = None
    # Composition (composite only — active when capability_type == "composite")
    combination: CombinationSpec | None = None
    # Optional metadata
    icon: str | None = None
    tags: tuple[str, ...] = ()
    # Full self-contained module text for this capability.  When provided,
    # sync_builtin_catalog() stores it as code_block instead of using
    # inspect.getsource().  Required for execution_source='generated_file'.
    capability_module_text: str | None = None


def validate_capability(
    definition: CapabilityDefinition,
    registry: CapabilityRegistry | None = None,
) -> list[str]:
    """
    Check whether *definition* conforms to the canonical capability object model.

    Returns a list of violation strings.  An empty list means the object is
    structurally lawful and safe to install.

    Pass *registry* to also verify that all referenced component capabilities
    already exist (relevant for combination capabilities).
    """
    violations: list[str] = []

    if not definition.capability_id:
        violations.append("capability_id must not be empty")
    if not definition.display_name:
        violations.append("display_name must not be empty")
    if definition.capability_type not in ("function", "composite"):
        violations.append(
            f"capability_type must be 'function' or 'composite', "
            f"got {definition.capability_type!r}"
        )
        return violations  # can't validate sections without a valid type

    if definition.capability_type == "function":
        if definition.implementation_logic is None:
            violations.append("function capability must have implementation_logic set")
        if definition.combination is not None:
            violations.append("function capability must not have combination set")
    else:  # composite
        if definition.implementation_logic is not None:
            violations.append("composite capability must not have implementation_logic set")
        if definition.combination is None:
            violations.append("composite capability must have combination set")
        else:
            spec = definition.combination
            if not spec.component_capabilities:
                violations.append("composite.component_capabilities must not be empty")
            if not spec.execution_order:
                violations.append("composite.execution_order must not be empty")
            extra = set(spec.execution_order) - set(spec.component_capabilities)
            if extra:
                violations.append(
                    f"composite.execution_order references IDs not in "
                    f"component_capabilities: {sorted(extra)}"
                )
            if registry is not None:
                for cid in spec.component_capabilities:
                    try:
                        registry.get(cid)
                    except KeyError:
                        violations.append(
                            f"component capability not found in registry: {cid!r}"
                        )

    return violations


class CapabilityRegistry:
    def __init__(
        self,
        *,
        framework_log_sink: FrameworkLogSink | None = None,
        run_id: str | None = None,
        workflow_id: str | None = None,
        trigger: str | None = None,
    ) -> None:
        self._definitions: dict[str, CapabilityDefinition] = {}
        self._framework_log_sink = framework_log_sink
        self._run_id = run_id
        self._workflow_id = workflow_id
        self._trigger = trigger

    def register(self, definition: CapabilityDefinition) -> None:
        if definition.capability_id in self._definitions:
            emit_framework_log(
                self._framework_log_sink,
                origin="platform.capability_registry",
                stage="registration",
                event_type="duplicate_registration_rejected",
                level="error",
                status="failed",
                run_id=self._run_id,
                workflow_id=self._workflow_id,
                capability_id=definition.capability_id,
                trigger=self._trigger or "CapabilityRegistry.register",
                message="Capability Platform rejected a duplicate capability registration attempt.",
                details={
                    "pack_id": definition.pack_id,
                    "capability_type": definition.capability_type,
                    "reason": "duplicate capability_id",
                },
            )
            raise ValueError(f"Capability already registered: {definition.capability_id}")
        emit_framework_log(
            self._framework_log_sink,
            origin="platform.capability_registry",
            stage="validation",
            event_type="capability_validation_started",
            level="info",
            status="started",
            run_id=self._run_id,
            workflow_id=self._workflow_id,
            capability_id=definition.capability_id,
            trigger=self._trigger or "CapabilityRegistry.register",
            message="Capability Platform started structural validation for a capability object.",
            details={
                "pack_id": definition.pack_id,
                "capability_type": definition.capability_type,
                "contract_inputs": list(definition.contract.inputs),
                "contract_output": list(definition.contract.output),
                "contract_constraints": list(definition.contract.constraints),
                "has_implementation_logic": definition.implementation_logic is not None,
                "has_combination": definition.combination is not None,
            },
        )
        violations = validate_capability(definition, registry=self)
        if violations:
            emit_framework_log(
                self._framework_log_sink,
                origin="platform.capability_registry",
                stage="validation",
                event_type="capability_validation_failed",
                level="error",
                status="failed",
                run_id=self._run_id,
                workflow_id=self._workflow_id,
                capability_id=definition.capability_id,
                trigger=self._trigger or "CapabilityRegistry.register",
                message="Capability Platform refused to install a structurally unlawful capability object.",
                details={
                    "pack_id": definition.pack_id,
                    "capability_type": definition.capability_type,
                    "violations": violations,
                },
            )
            raise ValueError(
                f"Refusing to install structurally unlawful capability "
                f"{definition.capability_id!r}:\n"
                + "\n".join(f"  - {v}" for v in violations)
            )
        self._definitions[definition.capability_id] = definition
        emit_framework_log(
            self._framework_log_sink,
            origin="platform.capability_registry",
            stage="registration",
            event_type="capability_registered",
            level="info",
            status="completed",
            run_id=self._run_id,
            workflow_id=self._workflow_id,
            capability_id=definition.capability_id,
            trigger=self._trigger or "CapabilityRegistry.register",
            message="Capability Platform installed a capability object into the live registry projection.",
            details={
                "pack_id": definition.pack_id,
                "capability_type": definition.capability_type,
                "registry_size": len(self._definitions),
                "tags": list(definition.tags),
            },
        )

    def get(self, capability_id: str) -> CapabilityDefinition:
        try:
            return self._definitions[capability_id]
        except KeyError as exc:
            raise KeyError(f"Unknown capability: {capability_id}") from exc

    def list_ids(self) -> list[str]:
        return sorted(self._definitions)

    def snapshot(self) -> list[CapabilityDefinition]:
        """Return all installed capability objects sorted by capability_id."""
        return sorted(self._definitions.values(), key=lambda d: d.capability_id)


@dataclass(slots=True)
class CapabilityContext:
    spec: CapabilityDefinition
    runtime: "WorkflowRuntime"
    inputs: dict[str, Any]

    def require(self, name: str) -> Any:
        if name not in self.inputs:
            raise KeyError(f"Missing required input '{name}' for {self.spec.capability_id}")
        return self.inputs[name]

    def get(self, name: str, default: Any = None) -> Any:
        return self.inputs.get(name, default)

    def read(self, value: Any) -> Any:
        if isinstance(value, ArtifactRef):
            return self.runtime.artifacts.read(value)
        return value

    def read_input(self, name: str) -> Any:
        return self.read(self.require(name))

    def cache_ready(self, path: str | Path, *, output_name: str) -> bool:
        resolved = Path(path)
        ready = self.runtime.cache.is_ready(
            Path(path),
            capability_id=self.spec.capability_id,
            output_name=output_name,
            inputs=self.inputs,
        )
        self.runtime._emit(
            stage="cache_decision",
            event_type="cache_readiness_checked",
            level="info",
            status="allowed" if ready else "observed",
            capability_id=self.spec.capability_id,
            trigger="CapabilityContext.cache_ready",
            message="Framework runtime evaluated whether a capability output path was cache-ready.",
            details={
                "output_name": output_name,
                "path": str(resolved),
                "cache_policy": type(self.runtime.cache).__name__,
                "cache_ready": ready,
            },
        )
        return ready

    def record_artifact(
        self,
        kind: str,
        value: Any,
        *,
        path: str | Path | None = None,
        views: dict[str, str | Path] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ArtifactRef:
        return self.runtime.record_artifact(
            kind,
            value,
            path=path,
            views=views,
            metadata=metadata,
            written=True,
        )

    def load_cached_json_artifact(
        self,
        kind: str,
        path: str | Path,
        *,
        views: dict[str, str | Path] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ArtifactRef:
        return self.runtime.load_cached_json_artifact(
            kind,
            path,
            views=views,
            metadata=metadata,
        )
