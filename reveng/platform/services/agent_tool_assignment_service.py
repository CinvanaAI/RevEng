"""Agents-owned capability assignment truth with compatibility projection."""
from __future__ import annotations

import json
import uuid

from reveng.storage.db_connection import get_db
from reveng.platform.models.agent_capability_assignment import (
    AgentCapabilityAssignmentRecord,
)
from reveng.platform.services.agent_service import AgentService
from reveng.platform.services.agent_tool_file_permission_service import (
    AgentToolFilePermissionService,
)
from reveng.platform.utils import now_utc


class AgentCapabilityAssignmentService:
    """
    Persist and project agent-to-capability grants.

    Agents own the relationship that a specific agent has been granted a
    specific capability package. This service stores that truth durably and
    keeps the legacy `tool_bindings` / `tool_access.allowed_capability_ids`
    projections synchronized for current repo compatibility.
    """

    def __init__(
        self,
        *,
        agent_service: AgentService | None = None,
        tool_file_permission_service: AgentToolFilePermissionService | None = None,
    ) -> None:
        self._agent_service = agent_service or AgentService()
        self._tool_file_permissions = (
            tool_file_permission_service
            or AgentToolFilePermissionService(agent_service=self._agent_service)
        )

    def list_assignments(
        self,
        agent_id: str,
        *,
        include_revoked: bool = False,
    ) -> list[AgentCapabilityAssignmentRecord]:
        self._agent_service.get_or_raise(agent_id)
        with get_db() as conn:
            if include_revoked:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM agent_capability_assignments
                    WHERE agent_id = ?
                    ORDER BY assigned_at ASC, capability_id ASC
                    """,
                    (agent_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM agent_capability_assignments
                    WHERE agent_id = ? AND assignment_state = 'granted'
                    ORDER BY assigned_at ASC, capability_id ASC
                    """,
                    (agent_id,),
                ).fetchall()
        return [AgentCapabilityAssignmentRecord.from_row(row) for row in rows]

    def list_granted_capability_ids(self, agent_id: str) -> list[str]:
        return self._agent_service.list_granted_capability_ids(agent_id)

    def grant(self, agent_id: str, capability_id: str) -> AgentCapabilityAssignmentRecord:
        self._agent_service.get_or_raise(agent_id)
        normalized = capability_id.strip()
        if not normalized:
            raise ValueError("capability_id is required.")

        ts = now_utc()
        with get_db() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM agent_capability_assignments
                WHERE agent_id = ? AND capability_id = ?
                """,
                (agent_id, normalized),
            ).fetchone()
            if row is None:
                assignment_id = str(uuid.uuid4())
                conn.execute(
                    """
                    INSERT INTO agent_capability_assignments (
                        id,
                        agent_id,
                        capability_id,
                        assignment_state,
                        assigned_at,
                        revoked_at,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, 'granted', ?, NULL, ?, ?)
                    """,
                    (assignment_id, agent_id, normalized, ts, ts, ts),
                )
            else:
                conn.execute(
                    """
                    UPDATE agent_capability_assignments
                    SET assignment_state = 'granted',
                        assigned_at = ?,
                        revoked_at = NULL,
                        updated_at = ?
                    WHERE agent_id = ? AND capability_id = ?
                    """,
                    (ts, ts, agent_id, normalized),
                )
            conn.commit()

        self._sync_agent_tool_access_projection(agent_id)
        self._tool_file_permissions.sync_for_new_granted_tool(agent_id, normalized)
        return self.get_assignment_or_raise(agent_id, normalized)

    def revoke(self, agent_id: str, capability_id: str) -> None:
        self._agent_service.get_or_raise(agent_id)
        normalized = capability_id.strip()
        if not normalized:
            raise ValueError("capability_id is required.")

        ts = now_utc()
        with get_db() as conn:
            conn.execute(
                """
                UPDATE agent_capability_assignments
                SET assignment_state = 'revoked',
                    revoked_at = ?,
                    updated_at = ?
                WHERE agent_id = ? AND capability_id = ? AND assignment_state = 'granted'
                """,
                (ts, ts, agent_id, normalized),
            )
            conn.commit()

        self._sync_agent_tool_access_projection(agent_id)
        self._tool_file_permissions.clear_for_tool(agent_id, normalized)

    def replace_grants(self, agent_id: str, capability_ids: list[str]) -> list[str]:
        self._agent_service.get_or_raise(agent_id)
        desired = self._normalize_capability_ids(capability_ids)
        current = set(self.list_granted_capability_ids(agent_id))

        for capability_id in sorted(current - set(desired)):
            self.revoke(agent_id, capability_id)
        for capability_id in desired:
            if capability_id not in current:
                self.grant(agent_id, capability_id)

        self._sync_agent_tool_access_projection(agent_id)
        return self.list_granted_capability_ids(agent_id)

    def set_scope(self, agent_id: str, capability_id: str, scope: str) -> AgentCapabilityAssignmentRecord:
        """Set the scope ('local' or 'global') for a granted capability assignment."""
        if scope not in ("local", "global"):
            raise ValueError(f"Invalid scope {scope!r}. Must be 'local' or 'global'.")
        self._agent_service.get_or_raise(agent_id)
        normalized = capability_id.strip()
        ts = now_utc()
        with get_db() as conn:
            row = conn.execute(
                """
                SELECT assignment_state FROM agent_capability_assignments
                WHERE agent_id = ? AND capability_id = ?
                """,
                (agent_id, normalized),
            ).fetchone()
        if row is None or str(row["assignment_state"]) != "granted":
            raise ValueError(f"Capability {normalized!r} is not currently granted to agent {agent_id!r}.")
        with get_db() as conn:
            conn.execute(
                """
                UPDATE agent_capability_assignments
                SET scope = ?, updated_at = ?
                WHERE agent_id = ? AND capability_id = ?
                """,
                (scope, ts, agent_id, normalized),
            )
            conn.commit()
        return self.get_assignment_or_raise(agent_id, normalized)

    def get_assignment_or_raise(
        self,
        agent_id: str,
        capability_id: str,
    ) -> AgentCapabilityAssignmentRecord:
        with get_db() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM agent_capability_assignments
                WHERE agent_id = ? AND capability_id = ?
                """,
                (agent_id, capability_id),
            ).fetchone()
        if row is None:
            raise KeyError(
                f"Assignment not found for agent {agent_id!r} and capability {capability_id!r}"
            )
        return AgentCapabilityAssignmentRecord.from_row(row)

    def _sync_agent_tool_access_projection(self, agent_id: str) -> None:
        granted_ids = self.list_granted_capability_ids(agent_id)
        ts = now_utc()
        with get_db() as conn:
            conn.execute(
                """
                UPDATE agents
                SET tool_bindings = ?, updated_at = ?
                WHERE id = ?
                """,
                (json.dumps(granted_ids), ts, agent_id),
            )
            conn.commit()

        record = self._agent_service.get_or_raise(agent_id)
        self._agent_service.update_section(
            agent_id,
            "tool_access",
            {
                "allowed_capability_ids": granted_ids,
                "provider_id": record.provider_id,
                "model": record.model,
            },
        )

    def _normalize_capability_ids(self, capability_ids: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for value in capability_ids:
            capability_id = value.strip()
            if not capability_id or capability_id in seen:
                continue
            seen.add(capability_id)
            normalized.append(capability_id)
        return normalized


__all__ = ["AgentCapabilityAssignmentService"]
