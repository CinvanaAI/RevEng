"""
AgentService — CRUD for agents plus the single active-enforcement gate.

The active/inactive contract is:
  - Every new agent defaults to is_active=False.
  - set_active() is the only way to change it; it writes to DB immediately.
  - get_active_or_raise() is the single gate that every invocation path must
    pass through.  Any code that invokes an agent without calling this first
    is a bug.

Section API:
  - get_spec(agent_id) returns a full AgentSpec assembled from agent_sections.
    If sections have not been initialized yet (pre-existing agents), they are
    lazily seeded from the flat legacy columns.
  - update_section(agent_id, section, data_dict) writes a single section.
  - initialize_sections(agent_id) explicitly seeds all sections from flat fields.
"""
from __future__ import annotations

import json
import uuid

from reveng.agents.spec import ALL_SECTIONS, AgentSpec
from reveng.storage.db_connection import get_db
from reveng.platform.models.agent import (
    AgentRecord,
    section_to_dict,
    spec_from_section_rows,
)
from reveng.platform.utils import now_utc


class AgentNotFoundError(Exception):
    pass


class AgentInactiveError(Exception):
    pass


class AgentService:
    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create(
        self,
        *,
        name: str,
        description: str = "",
        provider_id: str,
        model: str,
        system_prompt: str = "",
        tool_bindings: list[str] | None = None,
        memory_config: dict | None = None,
    ) -> AgentRecord:
        agent_id = str(uuid.uuid4())
        ts = now_utc()
        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO agents
                    (id, name, description, is_active, provider_id, model,
                     system_prompt, tool_bindings, memory_config, created_at, updated_at)
                VALUES (?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    agent_id,
                    name,
                    description,
                    provider_id,
                    model,
                    system_prompt,
                    json.dumps([]),
                    json.dumps(memory_config or {}),
                    ts,
                    ts,
                ),
            )
            conn.commit()
        record = self.get_or_raise(agent_id)
        self.initialize_sections(agent_id, record=record)
        if tool_bindings is not None:
            from reveng.platform.services.agent_tool_assignment_service import (
                AgentCapabilityAssignmentService,
            )

            AgentCapabilityAssignmentService(agent_service=self).replace_grants(
                agent_id,
                tool_bindings,
            )
            record = self.get_or_raise(agent_id)
        return record

    def get(self, agent_id: str) -> AgentRecord | None:
        with get_db() as conn:
            row = conn.execute(
                "SELECT * FROM agents WHERE id = ?", (agent_id,)
            ).fetchone()
        return AgentRecord.from_row(row) if row else None

    def get_or_raise(self, agent_id: str) -> AgentRecord:
        record = self.get(agent_id)
        if record is None:
            raise AgentNotFoundError(f"Agent not found: {agent_id}")
        return record

    def list_all(self) -> list[AgentRecord]:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT * FROM agents ORDER BY created_at DESC"
            ).fetchall()
        return [AgentRecord.from_row(r) for r in rows]

    def update(
        self,
        agent_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        provider_id: str | None = None,
        model: str | None = None,
        system_prompt: str | None = None,
        tool_bindings: list[str] | None = None,
        memory_config: dict | None = None,
    ) -> AgentRecord:
        record = self.get_or_raise(agent_id)
        ts = now_utc()

        new_name = name if name is not None else record.name
        new_desc = description if description is not None else record.description
        new_pid = provider_id if provider_id is not None else record.provider_id
        new_model = model if model is not None else record.model
        new_sp = system_prompt if system_prompt is not None else record.system_prompt
        new_tb = json.dumps(record.tool_bindings)
        new_mc = json.dumps(memory_config) if memory_config is not None else json.dumps(record.memory_config)

        with get_db() as conn:
            conn.execute(
                """
                UPDATE agents
                SET name=?, description=?, provider_id=?, model=?,
                    system_prompt=?, tool_bindings=?, memory_config=?, updated_at=?
                WHERE id=?
                """,
                (new_name, new_desc, new_pid, new_model, new_sp, new_tb, new_mc, ts, agent_id),
            )
            conn.commit()

        updated = self.get_or_raise(agent_id)

        # Keep sections in sync with any flat-field changes
        spec = self.get_spec(agent_id)
        if name is not None or description is not None or system_prompt is not None:
            from reveng.agents.spec import AgentIdentity
            new_identity = AgentIdentity(
                name=updated.name,
                role=spec.identity.role,
                description=updated.description,
                system_prompt=updated.system_prompt,
            )
            spec = AgentSpec(
                identity=new_identity,
                tool_access=spec.tool_access,
                activation=spec.activation,
                current_state=spec.current_state,
                persistent_state=spec.persistent_state,
                recorded_memory=spec.recorded_memory,
                working_memory=spec.working_memory,
                notes=spec.notes,
                visibility_scope=spec.visibility_scope,
            )
            self.update_section(agent_id, "identity", section_to_dict(spec, "identity"))
        if provider_id is not None or model is not None:
            from reveng.agents.spec import AgentToolAccess
            new_tool_access = AgentToolAccess(
                allowed_capability_ids=self.list_granted_capability_ids(agent_id),
                provider_id=updated.provider_id,
                model=updated.model,
            )
            spec_for_ta = AgentSpec(
                identity=spec.identity,
                tool_access=new_tool_access,
                activation=spec.activation,
                current_state=spec.current_state,
            )
            self.update_section(agent_id, "tool_access",
                                section_to_dict(spec_for_ta, "tool_access"))

        if tool_bindings is not None:
            from reveng.platform.services.agent_tool_assignment_service import (
                AgentCapabilityAssignmentService,
            )

            AgentCapabilityAssignmentService(agent_service=self).replace_grants(
                agent_id,
                tool_bindings,
            )
            updated = self.get_or_raise(agent_id)

        return updated

    def delete(self, agent_id: str) -> None:
        self.get_or_raise(agent_id)
        with get_db() as conn:
            conn.execute("DELETE FROM agents WHERE id = ?", (agent_id,))
            conn.commit()

    # ------------------------------------------------------------------
    # Active / inactive control
    # ------------------------------------------------------------------

    def set_active(self, agent_id: str, active: bool) -> AgentRecord:
        """Toggle active status.  Persists immediately.  Returns updated record."""
        self.get_or_raise(agent_id)
        ts = now_utc()
        with get_db() as conn:
            conn.execute(
                "UPDATE agents SET is_active = ?, updated_at = ? WHERE id = ?",
                (1 if active else 0, ts, agent_id),
            )
            conn.commit()
        record = self.get_or_raise(agent_id)
        # Keep activation section in sync
        spec = self.get_spec(agent_id)
        updated_activation = {
            "is_active": active,
            "triggers": spec.activation.triggers,
        }
        self.update_section(agent_id, "activation", updated_activation)
        # Update current_state.activation_status
        updated_current_state = {
            "activation_status": "active" if active else "inactive",
            "current_run_id": spec.current_state.current_run_id,
            "last_activated_at": ts if active else spec.current_state.last_activated_at,
            "health": spec.current_state.health,
        }
        self.update_section(agent_id, "current_state", updated_current_state)
        return record

    def get_active_or_raise(self, agent_id: str) -> AgentRecord:
        """
        Load agent and raise AgentInactiveError if not active.

        This is the SINGLE enforcement gate.  Every code path that invokes an
        agent must call this first.
        """
        record = self.get_or_raise(agent_id)
        if not record.is_active:
            raise AgentInactiveError(
                f"Agent '{record.name}' ({agent_id}) is inactive and cannot be invoked. "
                "Activate it in the control center before running."
            )
        return record

    # ------------------------------------------------------------------
    # Section API
    # ------------------------------------------------------------------

    def get_spec(self, agent_id: str) -> AgentSpec:
        """
        Return the full AgentSpec for an agent.

        Lazily initializes sections from flat fields if they have not been
        seeded yet (backward-compatible migration path for pre-existing agents).
        """
        record = self.get_or_raise(agent_id)
        with get_db() as conn:
            rows = conn.execute(
                "SELECT section, data FROM agent_sections WHERE agent_id = ?",
                (agent_id,),
            ).fetchall()

        if not rows:
            # Lazy init: seed from flat fields
            self.initialize_sections(agent_id, record=record)
            with get_db() as conn:
                rows = conn.execute(
                    "SELECT section, data FROM agent_sections WHERE agent_id = ?",
                    (agent_id,),
                ).fetchall()

        return spec_from_section_rows(
            record,
            rows,
            granted_capability_ids=self.list_granted_capability_ids(agent_id),
        )

    def update_section(self, agent_id: str, section: str, data: dict) -> None:
        """
        Write a single section for an agent.  Creates or replaces.
        """
        ts = now_utc()
        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO agent_sections (agent_id, section, data, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(agent_id, section) DO UPDATE SET
                    data = excluded.data,
                    updated_at = excluded.updated_at
                """,
                (agent_id, section, json.dumps(data), ts),
            )
            conn.commit()

    def set_current_run(self, agent_id: str, run_id: str | None) -> None:
        """
        Update the current run pointer in the structured current_state section.

        This keeps the lightweight platform-visible run association honest
        without expanding Agents Domain semantics beyond what is currently
        implemented.
        """
        spec = self.get_spec(agent_id)
        self.update_section(
            agent_id,
            "current_state",
            {
                "activation_status": spec.current_state.activation_status,
                "current_run_id": run_id,
                "last_activated_at": spec.current_state.last_activated_at,
                "health": spec.current_state.health,
            },
        )

    def initialize_sections(
        self, agent_id: str, *, record: AgentRecord | None = None
    ) -> None:
        """
        Seed all sections from flat fields for an agent.

        Safe to call on agents that already have sections — missing sections
        are added, existing ones are left untouched.
        """
        if record is None:
            record = self.get_or_raise(agent_id)
        spec = record.default_spec(
            granted_capability_ids=self.list_granted_capability_ids(agent_id),
        )
        ts = now_utc()
        with get_db() as conn:
            for section in ALL_SECTIONS:
                # Only insert if not present
                existing = conn.execute(
                    "SELECT 1 FROM agent_sections WHERE agent_id = ? AND section = ?",
                    (agent_id, section),
                ).fetchone()
                if existing is None:
                    conn.execute(
                        """
                        INSERT INTO agent_sections (agent_id, section, data, updated_at)
                        VALUES (?, ?, ?, ?)
                        """,
                        (agent_id, section, json.dumps(section_to_dict(spec, section)), ts),
                    )
            conn.commit()

    def list_granted_capability_ids(self, agent_id: str) -> list[str]:
        """
        Return granted capability IDs from the assignment truth root.

        This does not consult legacy flat or section projections.
        """
        self.get_or_raise(agent_id)
        with get_db() as conn:
            rows = conn.execute(
                """
                SELECT capability_id
                FROM agent_capability_assignments
                WHERE agent_id = ? AND assignment_state = 'granted'
                ORDER BY assigned_at ASC, capability_id ASC
                """,
                (agent_id,),
            ).fetchall()
        return [str(row["capability_id"]) for row in rows]
