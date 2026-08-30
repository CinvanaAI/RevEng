"""
Platform service for per-agent workflow storage.

Owns CRUD for agent_workflows rows, lazy migration from the legacy
single-workflow agent_sections data shape, and manual trigger run order.
"""
from __future__ import annotations

import json
import uuid

from reveng.agents.spec import AgentWorkflowEntry
from reveng.agents.triggers import (
    AgentTriggerDefinition,
    DEFAULT_ASSIGNED_TRIGGERS,
    MANUAL,
)
from reveng.storage.db_connection import get_db
from reveng.platform.utils import now_utc

_DEFAULT_TRIGGER_DICT = AgentTriggerDefinition().to_dict()

_SECTION_MANUAL_TRIGGER = "manual_trigger"


class AgentWorkflowNotFoundError(KeyError):
    pass


class AgentWorkflowService:
    """
    Truth owner for agent_workflows rows and manual trigger run order.

    Workflow activation rules:
      - is_active=True: global enable switch
      - assigned_triggers: list of activation kind strings that fire this workflow

    A workflow runs when is_active=True AND the firing trigger kind is in
    assigned_triggers.

    Manual trigger run order is stored in agent_sections (section="manual_trigger")
    as {"order": [workflow_id, ...]}.  Workflows with MANUAL in assigned_triggers
    that are not in the stored order are appended at the end during reads.
    """

    # -----------------------------------------------------------------------
    # Read
    # -----------------------------------------------------------------------

    def list_for_agent(self, agent_id: str) -> list[AgentWorkflowEntry]:
        """Return all workflows for the agent, ordered by created_at."""
        self._migrate_legacy_if_needed(agent_id)
        with get_db() as conn:
            rows = conn.execute(
                "SELECT * FROM agent_workflows WHERE agent_id = ? ORDER BY created_at ASC",
                (agent_id,),
            ).fetchall()
        return [AgentWorkflowEntry.from_row(r) for r in rows]

    def list_active_for_agent(self, agent_id: str) -> list[AgentWorkflowEntry]:
        """Return active workflows for the agent, ordered by created_at."""
        self._migrate_legacy_if_needed(agent_id)
        with get_db() as conn:
            rows = conn.execute(
                "SELECT * FROM agent_workflows WHERE agent_id = ? AND is_active = 1 ORDER BY created_at ASC",
                (agent_id,),
            ).fetchall()
        return [AgentWorkflowEntry.from_row(r) for r in rows]

    def list_for_activation_trigger(
        self, agent_id: str, trigger_kind: str
    ) -> list[AgentWorkflowEntry]:
        """
        Return active workflows that have trigger_kind in their assigned_triggers.

        For MANUAL: returns them in manual run order (stored order, with unlisted
        workflows appended at the end by created_at).
        For other kinds: returns them ordered by created_at.
        """
        all_active = self.list_active_for_agent(agent_id)
        matching = [wf for wf in all_active if trigger_kind in wf.assigned_triggers]

        if trigger_kind == MANUAL:
            order = self.get_manual_run_order(agent_id)
            order_index = {wf_id: i for i, wf_id in enumerate(order)}
            not_in_order = [wf for wf in matching if wf.id not in order_index]
            in_order = [wf for wf in matching if wf.id in order_index]
            in_order.sort(key=lambda wf: order_index[wf.id])
            return in_order + not_in_order

        return matching

    def get(self, workflow_id: str) -> AgentWorkflowEntry:
        with get_db() as conn:
            row = conn.execute(
                "SELECT * FROM agent_workflows WHERE id = ?",
                (workflow_id,),
            ).fetchone()
        if row is None:
            raise AgentWorkflowNotFoundError(f"Workflow not found: {workflow_id}")
        return AgentWorkflowEntry.from_row(row)

    # -----------------------------------------------------------------------
    # Write
    # -----------------------------------------------------------------------

    def create(
        self,
        agent_id: str,
        *,
        display_name: str = "Workflow",
        instruction_code: str = "",
        trigger: dict | None = None,
        assigned_triggers: list[str] | None = None,
    ) -> AgentWorkflowEntry:
        """Create a new active workflow entry for the agent."""
        wf_id = str(uuid.uuid4())
        ts = now_utc()
        raw_trigger = trigger if trigger is not None else _DEFAULT_TRIGGER_DICT
        trigger_dict = (
            raw_trigger.to_dict() if isinstance(raw_trigger, AgentTriggerDefinition)
            else AgentTriggerDefinition.from_dict(raw_trigger).to_dict()
        )
        eff_assigned = assigned_triggers if assigned_triggers is not None else list(DEFAULT_ASSIGNED_TRIGGERS)
        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO agent_workflows
                    (id, agent_id, display_name, instruction_code, trigger_json,
                     assigned_triggers_json, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    wf_id,
                    agent_id,
                    display_name,
                    instruction_code,
                    json.dumps(trigger_dict),
                    json.dumps(eff_assigned),
                    ts,
                    ts,
                ),
            )
            conn.commit()
        return self.get(wf_id)

    def update(
        self,
        workflow_id: str,
        *,
        display_name: str | None = None,
        instruction_code: str | None = None,
        trigger: dict | None = None,
        assigned_triggers: list[str] | None = None,
        is_active: bool | None = None,
    ) -> AgentWorkflowEntry:
        """Partial update — only supplied fields are changed."""
        existing = self.get(workflow_id)
        ts = now_utc()
        with get_db() as conn:
            conn.execute(
                """
                UPDATE agent_workflows
                SET display_name            = ?,
                    instruction_code        = ?,
                    trigger_json            = ?,
                    assigned_triggers_json  = ?,
                    is_active               = ?,
                    updated_at              = ?
                WHERE id = ?
                """,
                (
                    display_name if display_name is not None else existing.display_name,
                    instruction_code if instruction_code is not None else existing.instruction_code,
                    json.dumps(
                        AgentTriggerDefinition.from_dict(trigger).to_dict()
                        if trigger is not None
                        else existing.trigger.to_dict()
                    ),
                    json.dumps(
                        assigned_triggers if assigned_triggers is not None
                        else existing.assigned_triggers
                    ),
                    int(is_active) if is_active is not None else int(existing.is_active),
                    ts,
                    workflow_id,
                ),
            )
            conn.commit()
        return self.get(workflow_id)

    def delete(self, workflow_id: str) -> None:
        with get_db() as conn:
            conn.execute("DELETE FROM agent_workflows WHERE id = ?", (workflow_id,))
            conn.commit()

    # -----------------------------------------------------------------------
    # Manual trigger run order
    # -----------------------------------------------------------------------

    def get_manual_run_order(self, agent_id: str) -> list[str]:
        """
        Return the stored manual run order (list of workflow IDs).

        The stored order determines the sequential execution sequence when
        the manual trigger fires.  Workflows with MANUAL assigned but not in
        this list run after those in the list (in created_at order).
        """
        with get_db() as conn:
            row = conn.execute(
                "SELECT data FROM agent_sections WHERE agent_id = ? AND section = ?",
                (agent_id, _SECTION_MANUAL_TRIGGER),
            ).fetchone()
        if row is None:
            return []
        data = json.loads(row["data"] or "{}")
        return data.get("order", [])

    def set_manual_run_order(self, agent_id: str, order: list[str]) -> None:
        """
        Persist the manual trigger run order for the agent.

        order must be a list of workflow IDs.  Workflow IDs not belonging to
        this agent or not having MANUAL assigned are silently filtered out
        at read time — they do not need to be validated here.
        """
        ts = now_utc()
        data = json.dumps({"order": order})
        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO agent_sections (agent_id, section, data, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(agent_id, section) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at
                """,
                (agent_id, _SECTION_MANUAL_TRIGGER, data, ts),
            )
            conn.commit()

    # -----------------------------------------------------------------------
    # Legacy migration
    # -----------------------------------------------------------------------

    def _migrate_legacy_if_needed(self, agent_id: str) -> None:
        """
        If the agent has no rows in agent_workflows but has instruction_code in
        the agent_sections workflow section, promote it to a single active entry
        with the default assigned_triggers (["manual"]).

        One-time lazy migration — runs on first access, never again.
        """
        with get_db() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM agent_workflows WHERE agent_id = ?",
                (agent_id,),
            ).fetchone()[0]
            if count > 0:
                return
            row = conn.execute(
                "SELECT data FROM agent_sections WHERE agent_id = ? AND section = 'workflow'",
                (agent_id,),
            ).fetchone()

        if row is None:
            return

        data = json.loads(row["data"] or "{}")
        code = data.get("instruction_code", "")
        if not code.strip():
            return

        trigger = data.get("trigger") or _DEFAULT_TRIGGER_DICT
        self.create(
            agent_id,
            display_name="Workflow",
            instruction_code=code,
            trigger=trigger,
            assigned_triggers=list(DEFAULT_ASSIGNED_TRIGGERS),
        )


__all__ = ["AgentWorkflowService", "AgentWorkflowNotFoundError"]
