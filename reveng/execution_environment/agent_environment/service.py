"""Agent Environment application service."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from reveng.execution_environment.agent_environment.appearance import (
    DEFAULT_AGENT_ENVIRONMENT_SKIN_ID,
    AgentEnvironmentAppearanceService,
)
from reveng.execution_environment.agent_environment.stations import (
    AGENT_ENVIRONMENT_STATION_BY_ACTION,
    build_agent_environment_agent_href,
    build_agent_environment_entry_href,
)
from reveng.platform.services.agent_capability_access_service import (
    AgentCapabilityAccessService,
)
from reveng.platform.services.agent_keycard_service import AgentKeycardService
from reveng.platform.services.agent_service import AgentService
from reveng.platform.services.agent_tool_file_permission_service import (
    AgentToolFilePermissionService,
)
from reveng.platform.services.agent_workflow_service import AgentWorkflowService
from reveng.platform.services.filesystem_explorer_service import (
    FilesystemExplorerService,
)
from reveng.platform.services.provider_service import ProviderService
from reveng.platform.services.run_service import RunService


class AgentEnvironmentService:
    """Environment-local context assembly for Agent Environment."""

    def __init__(
        self,
        *,
        agent_service: AgentService,
        agent_capability_access: AgentCapabilityAccessService,
        agent_keycard_service: AgentKeycardService,
        tool_file_permission_service: AgentToolFilePermissionService,
        agent_workflow_service: AgentWorkflowService,
        filesystem_explorer_service: FilesystemExplorerService,
        appearance_service: AgentEnvironmentAppearanceService,
        provider_service: ProviderService,
        run_service: RunService,
    ) -> None:
        self._agents = agent_service
        self._agent_capability_access = agent_capability_access
        self._keycards = agent_keycard_service
        self._tool_file_permissions = tool_file_permission_service
        self._agent_workflow_service = agent_workflow_service
        self._explorer = filesystem_explorer_service
        self._appearance = appearance_service
        self._providers = provider_service
        self._runs = run_service

    def resolve_hall_agent_id(self, selected_agent_id: str | None) -> str | None:
        agents = self._ordered_agents()
        if not agents:
            return None
        if selected_agent_id:
            for agent in agents:
                if agent.id == selected_agent_id:
                    return agent.id
        return agents[0].id

    def build_hall_context(
        self,
        *,
        selected_agent_id: str | None,
        return_to: str,
        return_label: str,
        return_to_query: str,
    ) -> dict[str, Any]:
        agents = self._ordered_agents()
        theme = self._appearance.get_theme(DEFAULT_AGENT_ENVIRONMENT_SKIN_ID)
        shared_pool = self._appearance.list_shared_backgrounds(DEFAULT_AGENT_ENVIRONMENT_SKIN_ID)
        if not agents or not selected_agent_id:
            return {
                "environment_entry_href": build_agent_environment_entry_href(
                    return_to_query=return_to_query,
                ),
                "return_to": return_to,
                "return_label": return_label,
                "return_to_query": return_to_query,
                "theme": theme,
                "hall_stats": {
                    "total_agents": 0,
                    "active_agents": 0,
                    "shared_background_count": len(shared_pool),
                },
                "featured_agent": None,
                "featured_spec": None,
                "featured_provider": None,
                "featured_stage": {
                    "theme": theme,
                    "selected_asset": None,
                    "background_url": None,
                    "selection_source": "random",
                    "shared_pool_count": len(shared_pool),
                    "custom_pool_count": 0,
                    "preference": {"background_mode": "random", "selected_asset_id": None},
                },
                "featured_initials": "A",
                "featured_index": 0,
                "featured_total": 0,
                "featured_tool_count": 0,
                "featured_file_count": 0,
                "featured_enter_href": None,
                "featured_admin_href": None,
                "hall_prev_href": None,
                "hall_next_href": None,
                "hall_jump_rows": [],
                "environment_settings_href": self._environment_settings_href(return_to_query),
                "agents_admin_href": "/agents",
                "new_agent_href": "/agents/new",
            }
        featured_agent = self._agents.get_or_raise(selected_agent_id)
        featured_index = next(
            (index for index, agent in enumerate(agents) if agent.id == featured_agent.id),
            0,
        )
        previous_agent = agents[(featured_index - 1) % len(agents)]
        next_agent = agents[(featured_index + 1) % len(agents)]
        featured_spec = self._agents.get_spec(featured_agent.id)
        featured_provider = self._providers.get(featured_spec.tool_access.provider_id)
        featured_stage = self._appearance.resolve_agent_stage_background(
            featured_agent.id,
            DEFAULT_AGENT_ENVIRONMENT_SKIN_ID,
        )
        granted_count = len(featured_spec.tool_access.allowed_capability_ids)
        visible_count = len(self._keycards.list_assignments(featured_agent.id))

        return {
            "environment_entry_href": build_agent_environment_entry_href(
                return_to_query=return_to_query,
                agent_id=featured_agent.id,
            ),
            "return_to": return_to,
            "return_label": return_label,
            "return_to_query": return_to_query,
            "theme": theme,
            "hall_stats": {
                "total_agents": len(agents),
                "active_agents": sum(1 for agent in agents if agent.is_active),
                "shared_background_count": len(shared_pool),
            },
            "featured_agent": featured_agent,
            "featured_spec": featured_spec,
            "featured_provider": featured_provider,
            "featured_stage": featured_stage,
            "featured_initials": self._agent_initials(featured_agent.name),
            "featured_index": featured_index + 1,
            "featured_total": len(agents),
            "featured_tool_count": granted_count,
            "featured_file_count": visible_count,
            "featured_enter_href": build_agent_environment_agent_href(
                featured_agent.id,
                return_to_query=return_to_query,
            ),
            "featured_admin_href": f"/agents/{featured_agent.id}",
            "hall_prev_href": build_agent_environment_entry_href(
                return_to_query=return_to_query,
                agent_id=previous_agent.id,
            ),
            "hall_next_href": build_agent_environment_entry_href(
                return_to_query=return_to_query,
                agent_id=next_agent.id,
            ),
            "hall_jump_rows": [
                {
                    "agent": agent,
                    "href": build_agent_environment_entry_href(
                        return_to_query=return_to_query,
                        agent_id=agent.id,
                    ),
                    "is_current": agent.id == featured_agent.id,
                    "tool_count": len(self._agents.get_spec(agent.id).tool_access.allowed_capability_ids),
                    "file_count": len(self._keycards.list_assignments(agent.id)),
                }
                for agent in agents
            ],
            "environment_settings_href": self._environment_settings_href(return_to_query),
            "agents_admin_href": "/agents",
            "new_agent_href": "/agents/new",
        }

    def build_agent_bay_context(
        self,
        *,
        selected_agent_id: str,
        active_station: str | None,
        explorer_root_path: str | None,
        explorer_current_path: str | None,
        return_to: str,
        return_label: str,
        return_to_query: str,
    ) -> dict[str, Any]:
        agents = self._ordered_agents()
        granted_counts = {
            agent.id: len(self._agents.get_spec(agent.id).tool_access.allowed_capability_ids)
            for agent in agents
        }
        visible_counts = {
            agent.id: len(self._keycards.list_assignments(agent.id))
            for agent in agents
        }
        selected_agent = self._agents.get_or_raise(selected_agent_id)
        selected_spec = self._agents.get_spec(selected_agent.id)
        provider = self._providers.get(selected_spec.tool_access.provider_id)
        from reveng.platform.services.agent_workflow_bridge import preview_workflow_targets

        recent_runs = [
            run for run in self._runs.list_runs(limit=25) if run.agent_id == selected_agent.id
        ]
        workflow_runs = [run for run in recent_runs if run.options.get("workflow")]
        agent_workflows = self._agent_workflow_service.list_for_agent(selected_agent.id)
        workflow_target_preview = preview_workflow_targets(
            selected_agent.id,
            agent_workflow_service=self._agent_workflow_service,
            agent_keycard_service=self._keycards,
            agent_tool_file_permission_service=self._tool_file_permissions,
        )
        tool_projection = self._build_tools_projection(selected_agent.id)
        keycard_projection = self._build_keycard_projection(
            selected_agent.id,
            explorer_root_path=explorer_root_path,
            explorer_current_path=explorer_current_path,
            fallback_root_path=(recent_runs[0].repo_path if recent_runs else None),
            return_to_query=return_to_query,
        )
        appearance_projection = self._appearance.build_agent_appearance_context(
            selected_agent.id,
            DEFAULT_AGENT_ENVIRONMENT_SKIN_ID,
        )

        return {
            "active_station": (
                AGENT_ENVIRONMENT_STATION_BY_ACTION.get(active_station)
                if active_station is not None
                else None
            ),
            "environment_entry_href": build_agent_environment_entry_href(
                return_to_query=return_to_query,
                agent_id=selected_agent.id,
            ),
            "return_to": return_to,
            "return_label": return_label,
            "return_to_query": return_to_query,
            "theme": appearance_projection["theme"],
            "agent_environment_stats": {
                "total_agents": len(agents),
                "active_agents": sum(1 for agent in agents if agent.is_active),
                "selected_agent_tools": len(tool_projection["assigned_capability_ids"]),
                "selected_agent_local_tools": len(tool_projection["local_tools"]),
                "selected_agent_global_tools": len(tool_projection["global_tools"]),
                "selected_agent_files": keycard_projection["visible_count"],
                "installed_capability_count": tool_projection["installed_count"],
            },
            "selected_agent": selected_agent,
            "selected_spec": selected_spec,
            "selected_provider": provider,
            "selected_initials": self._agent_initials(selected_agent.name),
            "agent_workflows": agent_workflows,
            "recent_runs": recent_runs[:8],
            "workflow_runs": workflow_runs[:5],
            "workflow_target_preview": workflow_target_preview,
            "tools_open": active_station == "tools_station",
            "keycard_open": active_station == "keycard_station",
            "tools_box_href": build_agent_environment_agent_href(
                selected_agent.id,
                return_to_query=return_to_query,
                station="tools_station",
            ),
            "keycard_box_href": build_agent_environment_agent_href(
                selected_agent.id,
                return_to_query=return_to_query,
                station="keycard_station",
            ),
            "tools_close_href": build_agent_environment_agent_href(
                selected_agent.id,
                return_to_query=return_to_query,
            ),
            "keycard_close_href": build_agent_environment_agent_href(
                selected_agent.id,
                return_to_query=return_to_query,
            ),
            "back_to_hall_href": build_agent_environment_entry_href(
                return_to_query=return_to_query,
                agent_id=selected_agent.id,
            ),
            "inspect_agent_href": f"/agents/{selected_agent.id}",
            "environment_settings_href": self._environment_settings_href(return_to_query),
            "tool_projection": tool_projection,
            "keycard_projection": keycard_projection,
            "appearance_projection": appearance_projection,
        }

    def _build_tools_projection(self, agent_id: str) -> dict[str, Any]:
        state = self._agent_capability_access.get_assignment_state(agent_id)
        assigned_ids = set(state["assigned_capability_ids"])
        installed_entries = state["installed_inventory_entries"]
        keycard_files = self._keycards.list_assignments(agent_id)
        permissions = self._tool_file_permissions.list_permissions(agent_id, include_revoked=True)
        allowed_matrix = {
            (record.capability_id, record.absolute_path): record
            for record in permissions
            if record.is_granted
        }
        assigned_tools = [
            {
                **entry,
                "assignment_state": "granted",
                "scope": entry.get("scope", "local"),
                "file_rows": [
                    {
                        "absolute_path": assignment.absolute_path,
                        "root_path": assignment.root_path,
                        "relative_path": assignment.relative_path,
                        "global_tool_eligible": assignment.global_tool_eligible,
                        "entry_kind": assignment.entry_kind,
                        "availability_state": (
                            "present"
                            if Path(assignment.absolute_path).exists()
                            else "missing_on_disk"
                        ),
                        # tool_allowed: explicit permission record exists (regardless of global)
                        "tool_allowed": (
                            (entry["capability_id"], assignment.absolute_path) in allowed_matrix
                        ),
                        # direct_grant: allowed but NOT via global eligibility — per-tool only
                        "direct_grant": (
                            (entry["capability_id"], assignment.absolute_path) in allowed_matrix
                            and not assignment.global_tool_eligible
                        ),
                    }
                    for assignment in keycard_files
                ],
            }
            for entry in state["assigned_installed_tools"]
        ]
        local_tools = [t for t in assigned_tools if t.get("scope", "local") == "local"]
        global_tools = [t for t in assigned_tools if t.get("scope", "local") == "global"]
        return {
            "assigned_capability_ids": list(state["assigned_capability_ids"]),
            "assigned_tools": assigned_tools,
            "local_tools": local_tools,
            "global_tools": global_tools,
            "available_tools": [
                entry for entry in installed_entries if entry["capability_id"] not in assigned_ids
            ],
            "unavailable_assignments": list(state["unavailable_assignments"]),
            "installed_count": len(installed_entries),
        }

    def _build_keycard_projection(
        self,
        agent_id: str,
        *,
        explorer_root_path: str | None,
        explorer_current_path: str | None,
        fallback_root_path: str | None,
        return_to_query: str,
    ) -> dict[str, Any]:
        assignments = self._keycards.list_assignments(agent_id)
        visible_path_set = {assignment.absolute_path for assignment in assignments}
        visible_files = [
            {
                "absolute_path": assignment.absolute_path,
                "root_path": assignment.root_path,
                "relative_path": assignment.relative_path,
                "global_tool_eligible": assignment.global_tool_eligible,
                "entry_kind": assignment.entry_kind,
                "availability_state": (
                    "present" if Path(assignment.absolute_path).exists() else "missing_on_disk"
                ),
            }
            for assignment in assignments
        ]
        explorer = self._explorer.list_directory(
            root_path=explorer_root_path or fallback_root_path,
            current_path=explorer_current_path,
        )
        explorer_root = str(explorer["root_path"])
        explorer_current = str(explorer["current_path"])
        parent_path = explorer.get("parent_path")
        explorer_entries = []
        for entry in explorer["entries"]:
            entry_dict = dict(entry)
            entry_dict["is_visible"] = entry_dict["absolute_path"] in visible_path_set
            if entry_dict["entry_type"] == "directory":
                entry_dict["href"] = build_agent_environment_agent_href(
                    agent_id,
                    return_to_query=return_to_query,
                    station="keycard_station",
                    explorer_root_path=explorer_root,
                    explorer_current_path=str(entry_dict["absolute_path"]),
                )
            else:
                entry_dict["href"] = None
            explorer_entries.append(entry_dict)
        return {
            "visible_files": visible_files,
            "visible_count": len(visible_files),
            "global_enabled_count": sum(
                1 for assignment in assignments if assignment.global_tool_eligible
            ),
            "explorer": {
                "root_path": explorer_root,
                "current_path": explorer_current,
                "parent_path": parent_path,
                "parent_href": (
                    build_agent_environment_agent_href(
                        agent_id,
                        return_to_query=return_to_query,
                        station="keycard_station",
                        explorer_root_path=explorer_root,
                        explorer_current_path=str(parent_path),
                    )
                    if parent_path
                    else None
                ),
                "entries": explorer_entries,
            },
        }

    def _ordered_agents(self):
        return sorted(
            self._agents.list_all(),
            key=lambda agent: (agent.name.casefold(), agent.id),
        )

    def _environment_settings_href(self, return_to_query: str) -> str:
        if not return_to_query:
            return "/agents/environment-settings"
        return f"/agents/environment-settings?return={return_to_query}"

    def _agent_initials(self, name: str) -> str:
        parts = [part[:1].upper() for part in name.split() if part]
        if not parts:
            return "A"
        return "".join(parts[:2])


__all__ = ["AgentEnvironmentService"]
