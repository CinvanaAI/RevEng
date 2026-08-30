"""Coordination seam for agent tool assignment against live capability truth."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from reveng.platform.services.agent_keycard_service import AgentKeycardService
from reveng.platform.services.agent_service import AgentInactiveError, AgentService
from reveng.platform.services.agent_tool_assignment_service import (
    AgentCapabilityAssignmentService,
)
from reveng.platform.services.agent_tool_file_permission_service import (
    AgentToolFilePermissionService,
)
from reveng.platform.services.capability_catalog_service import (
    CapabilityCatalogService,
    CapabilityRecordNotFoundError,
)


class AgentCapabilityAccessService:
    """
    Coordinate agent-side grants against Platform-owned installed capability truth.

    This service does not own package truth or agent truth. It validates and
    projects across those boundaries so Agent Environment and future runtime
    permission checks stay honest.
    """

    def __init__(
        self,
        *,
        agent_service: AgentService | None = None,
        assignment_service: AgentCapabilityAssignmentService | None = None,
        keycard_service: AgentKeycardService | None = None,
        tool_file_permission_service: AgentToolFilePermissionService | None = None,
        capability_catalog: CapabilityCatalogService | None = None,
    ) -> None:
        self._agent_service = agent_service or AgentService()
        self._tool_file_permissions = (
            tool_file_permission_service
            or AgentToolFilePermissionService(agent_service=self._agent_service)
        )
        self._keycards = (
            keycard_service
            or AgentKeycardService(
                agent_service=self._agent_service,
                tool_file_permission_service=self._tool_file_permissions,
            )
        )
        self._assignments = assignment_service or AgentCapabilityAssignmentService(
            agent_service=self._agent_service,
            tool_file_permission_service=self._tool_file_permissions,
        )
        self._catalog = capability_catalog or CapabilityCatalogService()

    def get_assignment_state(self, agent_id: str) -> dict[str, Any]:
        agent = self._agent_service.get_or_raise(agent_id)
        assignments = self._assignments.list_assignments(agent_id)
        assigned_ids = [a.capability_id for a in assignments if a.is_granted]
        scope_by_id = {a.capability_id: a.scope for a in assignments if a.is_granted}
        installed = self._catalog.list_installed_inventory_entries()
        installed_by_id = {
            entry["capability_id"]: dict(entry)
            for entry in installed
        }

        assigned_tools: list[dict[str, Any]] = []
        unavailable_assignments: list[dict[str, Any]] = []
        for capability_id in assigned_ids:
            entry = installed_by_id.get(capability_id)
            if entry is None:
                unavailable_assignments.append(
                    {
                        "capability_id": capability_id,
                        "assignment_state": "granted",
                        "availability_state": "missing_installed_package",
                    }
                )
                continue
            tool_entry = dict(entry)
            tool_entry["scope"] = scope_by_id.get(capability_id, "local")
            assigned_tools.append(tool_entry)

        return {
            "agent_id": agent.id,
            "agent_name": agent.name,
            "assigned_capability_ids": assigned_ids,
            "assigned_installed_tools": assigned_tools,
            "installed_inventory_entries": [dict(entry) for entry in installed],
            "unavailable_assignments": unavailable_assignments,
        }

    def count_installed_capabilities(self) -> int:
        return self._catalog.count_installed_capabilities()

    def grant_tool_to_agent(self, agent_id: str, capability_id: str) -> dict[str, Any]:
        self._agent_service.get_or_raise(agent_id)
        self._catalog.get_installed_record_or_raise(capability_id)
        assignment = self._assignments.grant(agent_id, capability_id)
        detail = self._catalog.get_installed_capability_detail(capability_id)
        return {
            "assignment": {
                "id": assignment.id,
                "agent_id": assignment.agent_id,
                "capability_id": assignment.capability_id,
                "assignment_state": assignment.assignment_state,
                "assigned_at": assignment.assigned_at,
            },
            "capability": detail,
        }

    def revoke_tool_from_agent(self, agent_id: str, capability_id: str) -> None:
        self._agent_service.get_or_raise(agent_id)
        self._assignments.revoke(agent_id, capability_id)

    def is_capability_allowed_for_agent(
        self,
        agent_id: str,
        capability_id: str,
        *,
        inputs: dict[str, Any] | None = None,
    ) -> bool:
        try:
            self._agent_service.get_active_or_raise(agent_id)
        except AgentInactiveError:
            return False
        assignments = self._assignments.list_assignments(agent_id)
        assignment = next((a for a in assignments if a.capability_id == capability_id and a.is_granted), None)
        if assignment is None:
            return False
        try:
            self._catalog.get_installed_record_or_raise(capability_id)
        except CapabilityRecordNotFoundError:
            return False
        if not self._is_file_scope_allowed(agent_id, capability_id, inputs or {}, scope=assignment.scope):
            return False
        return True

    def build_runtime_permission_check(
        self,
        agent_id: str,
    ) -> Callable[[str, dict[str, Any]], bool]:
        self._agent_service.get_or_raise(agent_id)

        def _check(capability_id: str, _inputs: dict[str, Any]) -> bool:
            return self.is_capability_allowed_for_agent(
                agent_id,
                capability_id,
                inputs=_inputs,
            )

        return _check

    def _is_file_scope_allowed(
        self,
        agent_id: str,
        capability_id: str,
        inputs: dict[str, Any],
        *,
        scope: str = "local",
    ) -> bool:
        if scope == "global":
            # Global scope: allow any file that is globally eligible for this agent.
            target_paths = self._extract_target_file_paths(inputs)
            if not target_paths:
                return True
            return all(
                self._keycards.is_file_globally_eligible(agent_id, path)
                for path in target_paths
            )

        # scan_repo must be explicitly constrained to a keyed file subset for agents.
        if capability_id == "python.scan_repo":
            constrained_paths = inputs.get("visible_file_paths", None)
            if constrained_paths is None:
                constrained_paths = inputs.get("allowed_file_paths", None)
            if constrained_paths is None:
                return False
            return all(
                self._tool_file_permissions.is_tool_allowed_on_file(
                    agent_id,
                    capability_id,
                    path,
                )
                for path in [str(Path(path).expanduser().resolve()) for path in constrained_paths]
            )

        target_paths = self._extract_target_file_paths(inputs)
        if not target_paths:
            return True
        return all(
            self._tool_file_permissions.is_tool_allowed_on_file(
                agent_id,
                capability_id,
                path,
            )
            for path in target_paths
        )

    def _extract_target_file_paths(self, inputs: dict[str, Any]) -> list[str]:
        target_paths: list[str] = []

        def _normalize_with_repo_root(value: str, repo_root: str | None) -> str:
            candidate = Path(value)
            if candidate.is_absolute():
                return str(candidate.expanduser().resolve())
            if repo_root:
                return str((Path(repo_root).expanduser().resolve() / candidate).resolve())
            return str(candidate.expanduser().resolve())

        if "file_path" in inputs:
            target_paths.append(_normalize_with_repo_root(str(inputs["file_path"]), inputs.get("repo_root")))

        file_record = inputs.get("file_record")
        if isinstance(file_record, dict) and file_record.get("path"):
            target_paths.append(
                _normalize_with_repo_root(
                    str(file_record["path"]),
                    inputs.get("repo_root"),
                )
            )

        file_records = inputs.get("file_records")
        if isinstance(file_records, list):
            for record in file_records:
                if isinstance(record, dict) and record.get("path"):
                    target_paths.append(
                        _normalize_with_repo_root(
                            str(record["path"]),
                            inputs.get("repo_root"),
                        )
                    )

        deduped: list[str] = []
        seen: set[str] = set()
        for path in target_paths:
            if path in seen:
                continue
            seen.add(path)
            deduped.append(path)
        return deduped


__all__ = ["AgentCapabilityAccessService"]
