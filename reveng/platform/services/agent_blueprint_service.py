"""
AgentBlueprintService — stored desired-state configuration for agents.

A blueprint records the full configuration intent for an agent: which
capabilities to grant, at what scope, which paths to add to the keycard,
and which workflows to create.  Storing this as a DB record replaces the
"write a script and run it" pattern: the desired state is durable, inspectable,
and idempotent when applied.

Blueprint JSON schema
---------------------
{
    "capabilities": [
        {"capability_id": "python.scan_repo", "scope": "global"},
        ...
    ],
    "keycard_folders": [
        {"root_path": "/path/to/repository", "absolute_path": "/path/to/repository",
         "global_eligibility": true},
        ...
    ],
    "workflows": [
        {
            "display_name": "Base Analysis",
            "instruction_code": "...",
            "trigger": {"kind": "explicit_paths", "config": {"paths": [...]}},
            "assigned_triggers": ["manual"]
        },
        ...
    ]
}

Applying a blueprint is fully idempotent — safe to call multiple times.
"""
from __future__ import annotations

import json
import uuid
from typing import Any

from reveng.storage.db_connection import get_db
from reveng.platform.utils import now_utc


class AgentBlueprintNotFoundError(KeyError):
    pass


class AgentBlueprintService:
    """
    Truth owner for agent_configuration_blueprints rows.

    Depends on other services to apply the blueprint — inject them on
    construction so tests can substitute fakes.
    """

    def __init__(
        self,
        *,
        agent_service,
        assignment_service,
        keycard_service,
        workflow_service,
    ) -> None:
        self._agent_svc = agent_service
        self._assignment_svc = assignment_service
        self._keycard_svc = keycard_service
        self._workflow_svc = workflow_service

    # -----------------------------------------------------------------------
    # Read
    # -----------------------------------------------------------------------

    def get(self, blueprint_id: str) -> dict[str, Any]:
        """Return the raw blueprint dict (includes all columns)."""
        with get_db() as conn:
            row = conn.execute(
                "SELECT * FROM agent_configuration_blueprints WHERE id = ?",
                (blueprint_id,),
            ).fetchone()
        if row is None:
            raise AgentBlueprintNotFoundError(f"Blueprint not found: {blueprint_id}")
        return self._row_to_dict(row)

    def list_for_agent(self, agent_id: str) -> list[dict[str, Any]]:
        """Return all blueprints for the agent, ordered by created_at."""
        with get_db() as conn:
            rows = conn.execute(
                "SELECT * FROM agent_configuration_blueprints WHERE agent_id = ? ORDER BY created_at ASC",
                (agent_id,),
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    # -----------------------------------------------------------------------
    # Write
    # -----------------------------------------------------------------------

    def create(
        self,
        agent_id: str,
        display_name: str,
        blueprint_data: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Persist a new blueprint record.

        blueprint_data must conform to the JSON schema documented in the
        module docstring.  The record is created but NOT applied — call
        apply() separately.
        """
        self._agent_svc.get_or_raise(agent_id)
        bp_id = str(uuid.uuid4())
        ts = now_utc()
        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO agent_configuration_blueprints
                    (id, agent_id, display_name, blueprint_json, applied_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, NULL, ?, ?)
                """,
                (bp_id, agent_id, display_name, json.dumps(blueprint_data), ts, ts),
            )
            conn.commit()
        return self.get(bp_id)

    def update(
        self,
        blueprint_id: str,
        *,
        display_name: str | None = None,
        blueprint_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Partial update — only supplied fields are changed."""
        existing = self.get(blueprint_id)
        ts = now_utc()
        with get_db() as conn:
            conn.execute(
                """
                UPDATE agent_configuration_blueprints
                SET display_name   = ?,
                    blueprint_json = ?,
                    updated_at     = ?
                WHERE id = ?
                """,
                (
                    display_name if display_name is not None else existing["display_name"],
                    json.dumps(blueprint_data) if blueprint_data is not None else existing["blueprint_json"],
                    ts,
                    blueprint_id,
                ),
            )
            conn.commit()
        return self.get(blueprint_id)

    def delete(self, blueprint_id: str) -> None:
        with get_db() as conn:
            conn.execute(
                "DELETE FROM agent_configuration_blueprints WHERE id = ?",
                (blueprint_id,),
            )
            conn.commit()

    # -----------------------------------------------------------------------
    # Apply
    # -----------------------------------------------------------------------

    def apply(self, blueprint_id: str) -> dict[str, Any]:
        """
        Apply the blueprint to its agent.

        Idempotent — safe to call multiple times.  Each step is attempted
        independently; errors are collected and raised together at the end so
        that a failure in one step does not block the others.

        Returns the updated blueprint dict (with applied_at set).
        """
        record = self.get(blueprint_id)
        agent_id = record["agent_id"]
        data = json.loads(record["blueprint_json"])

        errors: list[str] = []

        # Step 1: grant capabilities and set scope
        for cap_spec in data.get("capabilities", []):
            cap_id = cap_spec["capability_id"]
            scope = cap_spec.get("scope", "local")
            try:
                self._assignment_svc.grant(agent_id, cap_id)
            except Exception as exc:
                # Typically already granted — not an error
                pass
            try:
                self._assignment_svc.set_scope(agent_id, cap_id, scope)
            except Exception as exc:
                errors.append(f"set_scope({cap_id!r}, {scope!r}): {exc}")

        # Step 2: assign keycard folders and set global eligibility
        for folder_spec in data.get("keycard_folders", []):
            root_path = folder_spec["root_path"]
            absolute_path = folder_spec["absolute_path"]
            global_eligibility = folder_spec.get("global_eligibility", False)
            try:
                self._keycard_svc.assign_folder(
                    agent_id,
                    root_path=root_path,
                    absolute_path=absolute_path,
                )
            except Exception as exc:
                # Typically already assigned — not an error
                pass
            if global_eligibility:
                try:
                    self._keycard_svc.set_global_eligibility(
                        agent_id,
                        absolute_path=absolute_path,
                        enabled=True,
                    )
                except Exception as exc:
                    errors.append(f"set_global_eligibility({absolute_path!r}): {exc}")

        # Step 3: create workflows (idempotent by display_name)
        for wf_spec in data.get("workflows", []):
            self._create_or_update_workflow_by_display_name(agent_id, wf_spec, errors)

        ts = now_utc()
        with get_db() as conn:
            conn.execute(
                "UPDATE agent_configuration_blueprints SET applied_at = ?, updated_at = ? WHERE id = ?",
                (ts, ts, blueprint_id),
            )
            conn.commit()

        if errors:
            raise RuntimeError(
                f"Blueprint applied with {len(errors)} error(s):\n" + "\n".join(errors)
            )

        return self.get(blueprint_id)

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    def _create_or_update_workflow_by_display_name(
        self,
        agent_id: str,
        wf_spec: dict[str, Any],
        errors: list[str],
    ) -> None:
        """
        Ensure a workflow with the given display_name exists for the agent.

        If a workflow with that display_name already exists, update its code
        and trigger config.  If it does not exist, create it.  This makes
        re-applying a blueprint safe after code changes.
        """
        display_name = wf_spec["display_name"]
        instruction_code = wf_spec.get("instruction_code", "")
        trigger = wf_spec.get("trigger")
        assigned_triggers = wf_spec.get("assigned_triggers", ["manual"])

        try:
            existing = self._workflow_svc.list_for_agent(agent_id)
            match = next((wf for wf in existing if wf.display_name == display_name), None)
            if match is None:
                self._workflow_svc.create(
                    agent_id,
                    display_name=display_name,
                    instruction_code=instruction_code,
                    trigger=trigger,
                    assigned_triggers=assigned_triggers,
                )
            else:
                self._workflow_svc.update(
                    match.id,
                    instruction_code=instruction_code,
                    trigger=trigger,
                    assigned_triggers=assigned_triggers,
                )
        except Exception as exc:
            errors.append(f"workflow({display_name!r}): {exc}")

    @staticmethod
    def _row_to_dict(row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "agent_id": row["agent_id"],
            "display_name": row["display_name"],
            "blueprint_json": row["blueprint_json"],
            "blueprint_data": json.loads(row["blueprint_json"] or "{}"),
            "applied_at": row["applied_at"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }


__all__ = ["AgentBlueprintService", "AgentBlueprintNotFoundError"]
