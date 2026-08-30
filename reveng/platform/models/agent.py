"""
AgentRecord — Storage Substrate row for an agent.

AgentRecord is a DB row.  It does not define what an agent IS — that is
AgentSpec (Agents Domain).  AgentRecord serializes/deserializes AgentSpec
sections and exposes the core fields needed for fast lookups (is_active).

The flat columns (provider_id, model, system_prompt, tool_bindings,
memory_config) are compatibility projections. Capability grants are owned by
agent_capability_assignments and projected back into the flat/section shapes;
these flat fields are no longer a semantic source of grant truth.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from sqlite3 import Row

from reveng.agents.spec import (
    AgentActivation,
    AgentCurrentState,
    AgentIdentity,
    AgentNotes,
    AgentPersistentState,
    AgentRecordedMemory,
    AgentSpec,
    AgentToolAccess,
    AgentVisibilityScope,
    AgentWorkingMemory,
    AgentWorkflow,
    ALL_SECTIONS,
    SECTION_ACTIVATION,
    SECTION_CURRENT_STATE,
    SECTION_IDENTITY,
    SECTION_NOTES,
    SECTION_PERSISTENT_STATE,
    SECTION_RECORDED_MEMORY,
    SECTION_TOOL_ACCESS,
    SECTION_VISIBILITY_SCOPE,
    SECTION_WORKING_MEMORY,
    SECTION_WORKFLOW,
)


@dataclass
class AgentRecord:
    id: str
    name: str
    description: str
    is_active: bool          # fast lookup column; also stored in activation section
    # Legacy flat fields — present in DB, superseded by sections
    provider_id: str
    model: str
    system_prompt: str
    tool_bindings: list[str]
    memory_config: dict
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: Row) -> AgentRecord:
        return cls(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            is_active=bool(row["is_active"]),
            provider_id=row["provider_id"],
            model=row["model"],
            system_prompt=row["system_prompt"],
            tool_bindings=json.loads(row["tool_bindings"]),
            memory_config=json.loads(row["memory_config"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def default_spec(
        self,
        *,
        granted_capability_ids: list[str] | None = None,
    ) -> AgentSpec:
        """
        Build a default AgentSpec from the legacy flat fields plus any
        assignment-derived capability grants.

        Called by AgentService when sections have not yet been initialized
        for this agent.
        """
        return AgentSpec(
            identity=AgentIdentity(
                name=self.name,
                role="",
                description=self.description,
                system_prompt=self.system_prompt,
            ),
            tool_access=AgentToolAccess(
                allowed_capability_ids=list(granted_capability_ids or []),
                provider_id=self.provider_id,
                model=self.model,
            ),
            activation=AgentActivation(
                is_active=self.is_active,
                triggers=[],
            ),
            current_state=AgentCurrentState(
                activation_status="active" if self.is_active else "inactive",
                current_run_id=None,
                last_activated_at=None,
                health="unknown",
            ),
        )


# ---------------------------------------------------------------------------
# Section serialization helpers
# ---------------------------------------------------------------------------

def section_to_dict(spec: AgentSpec, section: str) -> dict:
    """Return the JSON-serializable dict for a single section of AgentSpec."""
    if section == SECTION_IDENTITY:
        s = spec.identity
        return {"name": s.name, "role": s.role, "description": s.description,
                "system_prompt": s.system_prompt}
    if section == SECTION_TOOL_ACCESS:
        s = spec.tool_access
        return {"allowed_capability_ids": s.allowed_capability_ids,
                "provider_id": s.provider_id, "model": s.model}
    if section == SECTION_ACTIVATION:
        s = spec.activation
        return {"is_active": s.is_active, "triggers": s.triggers}
    if section == SECTION_CURRENT_STATE:
        s = spec.current_state
        return {"activation_status": s.activation_status,
                "current_run_id": s.current_run_id,
                "last_activated_at": s.last_activated_at,
                "health": s.health}
    if section == SECTION_PERSISTENT_STATE:
        return {"entries": spec.persistent_state.entries}
    if section == SECTION_RECORDED_MEMORY:
        return {"records": spec.recorded_memory.records}
    if section == SECTION_WORKING_MEMORY:
        return {"context": spec.working_memory.context}
    if section == SECTION_NOTES:
        return {"entries": spec.notes.entries}
    if section == SECTION_VISIBILITY_SCOPE:
        return {"allowed_scopes": spec.visibility_scope.allowed_scopes}
    if section == SECTION_WORKFLOW:
        return {
            "instruction_code": spec.workflow.instruction_code,
            "trigger": spec.workflow.trigger,
        }
    raise ValueError(f"Unknown section: {section!r}")


def spec_from_section_rows(
    record: AgentRecord,
    rows: list[Row],
    *,
    granted_capability_ids: list[str] | None = None,
) -> AgentSpec:
    """
    Assemble an AgentSpec from a set of agent_sections rows.

    Missing sections fall back to defaults derived from the flat AgentRecord
    fields. Capability grants are injected from the assignment truth root, not
    from legacy projection fields.
    """
    data: dict[str, dict] = {}
    for row in rows:
        data[row["section"]] = json.loads(row["data"])

    default = record.default_spec(granted_capability_ids=granted_capability_ids)

    def _get(section: str, default_obj: object) -> dict:
        return data.get(section, {})

    raw = data.get(SECTION_IDENTITY, {})
    identity = AgentIdentity(
        name=raw.get("name", default.identity.name),
        role=raw.get("role", default.identity.role),
        description=raw.get("description", default.identity.description),
        system_prompt=raw.get("system_prompt", default.identity.system_prompt),
    )

    raw = data.get(SECTION_TOOL_ACCESS, {})
    tool_access = AgentToolAccess(
        allowed_capability_ids=list(granted_capability_ids or []),
        provider_id=raw.get("provider_id", default.tool_access.provider_id),
        model=raw.get("model", default.tool_access.model),
    )

    raw = data.get(SECTION_ACTIVATION, {})
    activation = AgentActivation(
        is_active=raw.get("is_active", default.activation.is_active),
        triggers=raw.get("triggers", []),
    )

    raw = data.get(SECTION_CURRENT_STATE, {})
    current_state = AgentCurrentState(
        activation_status=raw.get("activation_status",
                                  default.current_state.activation_status),
        current_run_id=raw.get("current_run_id", None),
        last_activated_at=raw.get("last_activated_at", None),
        health=raw.get("health", "unknown"),
    )

    raw = data.get(SECTION_PERSISTENT_STATE, {})
    persistent_state = AgentPersistentState(entries=raw.get("entries", {}))

    raw = data.get(SECTION_RECORDED_MEMORY, {})
    recorded_memory = AgentRecordedMemory(records=raw.get("records", []))

    raw = data.get(SECTION_WORKING_MEMORY, {})
    working_memory = AgentWorkingMemory(context=raw.get("context", {}))

    raw = data.get(SECTION_NOTES, {})
    notes = AgentNotes(entries=raw.get("entries", []))

    raw = data.get(SECTION_VISIBILITY_SCOPE, {})
    visibility_scope = AgentVisibilityScope(
        allowed_scopes=raw.get("allowed_scopes", [])
    )

    raw = data.get(SECTION_WORKFLOW, {})
    workflow = AgentWorkflow(
        instruction_code=raw.get("instruction_code", ""),
        trigger=raw.get("trigger", {
            "mode": "repo_root_from_keycard",
            "output_filename": "workflow_output.json",
        }),
    )

    return AgentSpec(
        identity=identity,
        tool_access=tool_access,
        activation=activation,
        current_state=current_state,
        persistent_state=persistent_state,
        recorded_memory=recorded_memory,
        working_memory=working_memory,
        notes=notes,
        visibility_scope=visibility_scope,
        workflow=workflow,
    )
