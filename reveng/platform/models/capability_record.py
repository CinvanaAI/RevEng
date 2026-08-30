"""
Platform-owned stored capability records.

These records represent installed/live capability truth as durable platform
objects. They carry semantic fields plus binding references that the framework
runtime can resolve into executable callables.

execution_source routing
------------------------
'binding_ref'    — resolve implementation_ref via import machinery (builtins / bootstrap-regime)
'code_block'     — exec the stored code_block and invoke the declared entrypoint callable
'generated_file' — import from reveng/capabilities/packages/<id>/published/python/implementation.py
'composite_spec' — composite logic (no implementation_logic; combination field carries the spec)

Bootstrap-regime note
---------------------
Builtins use execution_source='binding_ref' because their source regime is a Python module
maintained in the codebase. This is a source-regime exception — they still resolve into the
same package model (same surfaces, same history, same dataclasses). The distinction is only
in how source is maintained (Python module vs stored code_block) and how execution is resolved.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from sqlite3 import Row
from typing import Any, Callable

from reveng.platform.capabilities import (
    CapabilityContract,
    CapabilityDefinition,
    CombinationSpec,
)
from reveng.framework.trusted_code import require_authored_code_execution_enabled


CapabilityBindingResolver = Callable[[str], Any]


def _make_code_block_callable(
    code_block: str,
    capability_id: str,
    entrypoint: str = "run",
) -> Callable:
    """
    Execute a stored code_block and return the declared entrypoint callable.

    The code_block must define a top-level function whose name matches the
    package's declared entrypoint (default: 'run'). The function accepts a
    CapabilityContext and returns dict[str, Any].

    Python's standard import system is available inside the exec'd code because
    the execution namespace is seeded with __builtins__.
    """
    require_authored_code_execution_enabled("stored capability code")
    if not code_block:
        raise ValueError(
            f"capability_id={capability_id!r} has execution_source='code_block' "
            "but code_block is empty"
        )
    ns: dict[str, Any] = {"__builtins__": __builtins__}
    try:
        exec(compile(code_block, f"<capability:{capability_id}>", "exec"), ns)
    except Exception as exc:
        raise ValueError(
            f"Failed to compile code_block for capability {capability_id!r}: {exc}"
        ) from exc
    fn = ns.get(entrypoint)
    if fn is None or not callable(fn):
        raise ValueError(
            f"code_block for capability {capability_id!r} must define a callable named {entrypoint!r}"
        )
    return fn


def _import_generated_callable(capability_id: str, entrypoint: str = "run") -> Callable:
    """
    Import the package-owned published Python artifact for a capability and
    return its declared entrypoint callable.

    Published Python artifacts live at:
        reveng/capabilities/packages/<safe_id>/published/python/implementation.py
    """
    require_authored_code_execution_enabled("generated capability code")
    import importlib

    # Sanitize capability_id into a valid Python module path component.
    safe_id = capability_id.replace(".", "_").replace("-", "_")
    module_path = f"reveng.capabilities.packages.{safe_id}.published.python.implementation"
    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        raise ImportError(
            f"Published Python artifact not found for capability {capability_id!r}. "
            f"Expected module: {module_path!r}. Publish the capability first to generate artifacts."
        ) from exc
    fn = getattr(module, entrypoint, None)
    if fn is None or not callable(fn):
        raise ValueError(
            f"Published Python artifact {module_path!r} must define a callable named {entrypoint!r}"
        )
    return fn


@dataclass
class CapabilityRecord:
    capability_id: str
    package_object_id: str | None
    pack_id: str
    version: str
    display_name: str
    description: str
    lifecycle_state: str
    capability_type: str
    contract: dict[str, Any]
    tags: list[str]
    icon: str | None
    implementation_ref: str | None
    combination_logic_ref: str | None
    component_capabilities: list[str]
    execution_order: list[str]
    source_kind: str
    source_ref: str
    created_at: str
    updated_at: str
    code_block: str = ""
    execution_source: str = "binding_ref"
    entrypoint: str = "run"
    publish_outputs: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.publish_outputs is None:
            self.publish_outputs = ["python_artifact", "text_summary"]

    @classmethod
    def from_row(cls, row: Row) -> "CapabilityRecord":
        import json as _json
        raw_keys = row.keys() if hasattr(row, "keys") else []
        return cls(
            capability_id=row["capability_id"],
            package_object_id=row["package_object_id"],
            pack_id=row["pack_id"],
            version=row["version"],
            display_name=row["display_name"],
            description=row["description"],
            lifecycle_state=row["lifecycle_state"],
            capability_type=row["capability_type"],
            contract=json.loads(row["contract_json"] or "{}"),
            tags=list(json.loads(row["tags_json"] or "[]")),
            icon=row["icon"],
            implementation_ref=row["implementation_ref"],
            combination_logic_ref=row["combination_logic_ref"],
            component_capabilities=list(json.loads(row["component_capabilities_json"] or "[]")),
            execution_order=list(json.loads(row["execution_order_json"] or "[]")),
            source_kind=row["source_kind"],
            source_ref=row["source_ref"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            code_block=row["code_block"] if row["code_block"] is not None else "",
            execution_source=row["execution_source"] if row["execution_source"] is not None else "binding_ref",
            entrypoint=row["entrypoint"] if "entrypoint" in raw_keys and row["entrypoint"] else "run",
            publish_outputs=_json.loads(row["publish_outputs_json"]) if "publish_outputs_json" in raw_keys and row["publish_outputs_json"] else ["python_artifact", "text_summary"],
        )

    def to_definition(
        self,
        *,
        resolve_binding_ref: CapabilityBindingResolver,
    ) -> CapabilityDefinition:
        contract = CapabilityContract(
            inputs=tuple(self.contract.get("inputs", [])),
            output=tuple(self.contract.get("output", [])),
            constraints=tuple(self.contract.get("constraints", [])),
        )

        # Route to the correct execution backend based on execution_source.
        # 'binding_ref': bootstrap-regime (builtins) — resolve from Python import machinery.
        # 'code_block': authored capabilities — exec stored code_block, invoke declared entrypoint.
        # 'generated_file': import from package-owned published Python artifact.
        # 'composite_spec': composite logic — no implementation_logic.
        execution_source = self.execution_source or "binding_ref"
        entrypoint = self.entrypoint or "run"

        if execution_source == "binding_ref":
            implementation_logic = (
                resolve_binding_ref(self.implementation_ref)
                if self.implementation_ref
                else None
            )
        elif execution_source == "code_block":
            implementation_logic = _make_code_block_callable(
                self.code_block, self.capability_id, entrypoint
            )
        elif execution_source == "generated_file":
            implementation_logic = _import_generated_callable(self.capability_id, entrypoint)
        else:
            # composite_spec or unknown — no implementation_logic
            implementation_logic = None

        combination = None
        if self.capability_type == "composite":
            if not self.combination_logic_ref:
                raise ValueError(
                    f"Stored combination capability missing combination_logic_ref: {self.capability_id!r}"
                )
            combination = CombinationSpec(
                component_capabilities=tuple(self.component_capabilities),
                execution_order=tuple(self.execution_order),
                combination_logic=resolve_binding_ref(self.combination_logic_ref),
            )

        return CapabilityDefinition(
            capability_id=self.capability_id,
            pack_id=self.pack_id,
            version=self.version,
            display_name=self.display_name,
            description=self.description,
            capability_type=self.capability_type,
            contract=contract,
            implementation_logic=implementation_logic,
            combination=combination,
            icon=self.icon,
            tags=tuple(self.tags),
        )

    def to_inventory_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "package_object_id": self.package_object_id,
            "display_name": self.display_name,
            "description": self.description,
            "capability_type": self.capability_type,
            "pack_id": self.pack_id,
            "version": self.version,
            "icon": self.icon,
            "contract": {
                "inputs": list(self.contract.get("inputs", [])),
                "output": list(self.contract.get("output", [])),
                "constraints": list(self.contract.get("constraints", [])),
            },
            "has_implementation_logic": bool(self.implementation_ref),
            "component_capabilities": list(self.component_capabilities),
            "execution_order": list(self.execution_order),
            "has_combination_logic": bool(self.combination_logic_ref),
            "tags": list(self.tags),
            "lifecycle_state": self.lifecycle_state,
            "source_kind": self.source_kind,
            "source_ref": self.source_ref,
            "code_block": self.code_block,
            "execution_source": self.execution_source,
            "entrypoint": self.entrypoint,
            "publish_outputs": list(self.publish_outputs),
        }


@dataclass
class CapabilityRecordEvent:
    id: str
    capability_id: str
    event_type: str
    source_kind: str
    source_ref: str
    snapshot_data: dict[str, Any]
    created_at: str

    @classmethod
    def from_row(cls, row: Row) -> "CapabilityRecordEvent":
        return cls(
            id=row["id"],
            capability_id=row["capability_id"],
            event_type=row["event_type"],
            source_kind=row["source_kind"],
            source_ref=row["source_ref"],
            snapshot_data=json.loads(row["snapshot_json"] or "{}"),
            created_at=row["created_at"],
        )


__all__ = [
    "CapabilityBindingResolver",
    "CapabilityRecord",
    "CapabilityRecordEvent",
]
