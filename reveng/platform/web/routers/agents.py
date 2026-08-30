"""
/api/agents — agent CRUD and active/inactive toggle.

All endpoints return JSON.  When an HTMX request comes in for the toggle
endpoint, the response also sets HX-Trigger so the UI can refresh the
relevant portion of the page.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from reveng.platform.services.agent_service import (
    AgentInactiveError,
    AgentNotFoundError,
    AgentService,
)
from reveng.platform.services.agent_capability_access_service import (
    AgentCapabilityAccessService,
)
from reveng.platform.services.agent_keycard_service import AgentKeycardService
from reveng.platform.services.capability_catalog_service import (
    CapabilityRecordNotFoundError,
)
from reveng.platform.services.agent_tool_file_permission_service import (
    AgentToolFilePermissionService,
)
from reveng.platform.services.event_service import EventService
from reveng.platform.services.output_service import OutputService
from reveng.platform.services.run_service import RunService
from reveng.platform.services.agent_workflow_service import AgentWorkflowNotFoundError, AgentWorkflowService
from reveng.platform.services.agent_tool_assignment_service import AgentCapabilityAssignmentService
from reveng.platform.web.deps import get_agent_service
from reveng.platform.web.deps import (
    get_agent_capability_access_service,
    get_agent_capability_assignment_service,
    get_agent_environment_service,
    get_agent_keycard_service,
    get_agent_tool_file_permission_service,
    get_agent_workflow_service,
    get_event_service,
    get_executor,
    get_output_service,
    get_run_service,
    get_shared_capability_registry,
)
from reveng.execution_environment.agent_environment.service import AgentEnvironmentService

router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class AgentCreate(BaseModel):
    name: str
    description: str = ""
    provider_id: str
    model: str
    system_prompt: str = ""
    tool_bindings: list[str] = []
    memory_config: dict = {}


class AgentUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    provider_id: str | None = None
    model: str | None = None
    system_prompt: str | None = None
    tool_bindings: list[str] | None = None
    memory_config: dict | None = None


class ActiveToggle(BaseModel):
    active: bool


class KeycardAssignFiles(BaseModel):
    root_path: str
    absolute_paths: list[str]


class KeycardAssignFolder(BaseModel):
    root_path: str
    absolute_path: str


class KeycardFileBody(BaseModel):
    absolute_path: str


class KeycardGlobalToggle(BaseModel):
    absolute_path: str
    enabled: bool


class ToolKeycardAssign(BaseModel):
    root_path: str
    absolute_path: str


class ToolFilePermissionToggle(BaseModel):
    capability_id: str
    absolute_path: str
    allowed: bool


class ToolScopeUpdate(BaseModel):
    scope: str  # 'local' | 'global'


class WorkflowCreate(BaseModel):
    display_name: str = "Workflow"
    instruction_code: str = ""


class WorkflowUpdate(BaseModel):
    display_name: str | None = None
    instruction_code: str | None = None
    is_active: bool | None = None
    assigned_triggers: list[str] | None = None


class ManualOrderUpdate(BaseModel):
    order: list[str]  # ordered list of workflow IDs


class TriggerUpdate(BaseModel):
    kind: str
    output_filename: str = "workflow_output.json"
    config: dict = {}


def _agent_dict(record) -> dict:
    return {
        "id": record.id,
        "name": record.name,
        "description": record.description,
        "is_active": record.is_active,
        "provider_id": record.provider_id,
        "model": record.model,
        "system_prompt": record.system_prompt,
        "tool_bindings": record.tool_bindings,
        "memory_config": record.memory_config,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


def _assignment_projection_dict(entry: dict) -> dict:
    return {
        "capability_id": entry.get("capability_id"),
        "package_object_id": entry.get("package_object_id"),
        "display_name": entry.get("display_name"),
        "description": entry.get("description"),
        "capability_type": entry.get("capability_type"),
        "pack_id": entry.get("pack_id"),
        "version": entry.get("version"),
        "icon": entry.get("icon"),
        "contract": entry.get("contract", {}),
        "tags": entry.get("tags", []),
        "lifecycle_state": entry.get("lifecycle_state"),
        "source_kind": entry.get("source_kind"),
        "source_ref": entry.get("source_ref"),
        "assignment_state": entry.get("assignment_state"),
        "available_for_assignment": entry.get("available_for_assignment"),
        "availability_state": entry.get("availability_state"),
    }


def _build_tool_projection_payload(state: dict) -> dict:
    assigned_ids = set(state["assigned_capability_ids"])
    installed_entries = state["installed_inventory_entries"]
    assigned_tools = [
        {
            **entry,
            "assignment_state": "granted",
        }
        for entry in state["assigned_installed_tools"]
    ]
    available_tools = [
        entry
        for entry in installed_entries
        if entry["capability_id"] not in assigned_ids
    ]
    return {
        "agent_id": state["agent_id"],
        "agent_name": state["agent_name"],
        "assigned_capability_ids": list(state["assigned_capability_ids"]),
        "installed_count": len(installed_entries),
        "assigned_tools": [
            _assignment_projection_dict(entry) for entry in assigned_tools
        ],
        "available_tools": [
            _assignment_projection_dict(entry) for entry in available_tools
        ],
        "unavailable_assignments": [
            _assignment_projection_dict(entry)
            for entry in state["unavailable_assignments"]
        ],
    }


def _keycard_file_dict(entry: dict) -> dict:
    return {
        "absolute_path": entry.get("absolute_path"),
        "root_path": entry.get("root_path"),
        "relative_path": entry.get("relative_path"),
        "global_tool_eligible": entry.get("global_tool_eligible"),
        "entry_kind": entry.get("entry_kind", "file"),
        "availability_state": entry.get("availability_state"),
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("")
def list_agents(svc: AgentService = Depends(get_agent_service)):
    agents = svc.list_all()
    return {"agents": [_agent_dict(a) for a in agents], "count": len(agents)}


@router.post("", status_code=201)
def create_agent(body: AgentCreate, svc: AgentService = Depends(get_agent_service)):
    try:
        agent = svc.create(
            name=body.name,
            description=body.description,
            provider_id=body.provider_id,
            model=body.model,
            system_prompt=body.system_prompt,
            tool_bindings=body.tool_bindings,
            memory_config=body.memory_config,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _agent_dict(agent)


@router.get("/hall")
def get_hall_context(
    agent_id: str | None = None,
    svc: AgentService = Depends(get_agent_service),
    keycard: AgentKeycardService = Depends(get_agent_keycard_service),
):
    """
    Return hall context: ordered agent list with per-agent counts, featured agent,
    prev/next pointers. Used by the agent_environment JS module to render the hall.
    """
    from dataclasses import asdict

    agents = sorted(svc.list_all(), key=lambda a: (a.name.casefold(), a.id))
    if not agents:
        return {
            "agents": [],
            "featured_agent_id": None,
            "prev_agent_id": None,
            "next_agent_id": None,
            "featured_index": 0,
            "featured_total": 0,
        }

    def _initials(name: str) -> str:
        parts = [p[:1].upper() for p in name.split() if p]
        return "".join(parts[:2]) if parts else "A"

    rows = []
    for a in agents:
        spec = svc.get_spec(a.id)
        tool_count = len(spec.tool_access.allowed_capability_ids)
        file_count = len(keycard.list_assignments(a.id))
        state = asdict(spec.current_state)
        rows.append({
            "id": a.id,
            "name": a.name,
            "description": a.description,
            "is_active": a.is_active,
            "initials": _initials(a.name),
            "tool_count": tool_count,
            "file_count": file_count,
            "current_state": state,
        })

    resolved_id = agent_id if agent_id else agents[0].id
    featured_index = next((i for i, a in enumerate(agents) if a.id == resolved_id), 0)
    prev_id = agents[(featured_index - 1) % len(agents)].id
    next_id = agents[(featured_index + 1) % len(agents)].id

    return {
        "agents": rows,
        "featured_agent_id": agents[featured_index].id,
        "prev_agent_id": prev_id,
        "next_agent_id": next_id,
        "featured_index": featured_index + 1,
        "featured_total": len(agents),
    }


@router.get("/{agent_id}/bay-context")
def get_bay_context(
    agent_id: str,
    svc: AgentService = Depends(get_agent_service),
    access: AgentCapabilityAccessService = Depends(get_agent_capability_access_service),
    keycard: AgentKeycardService = Depends(get_agent_keycard_service),
    tool_file_permissions: AgentToolFilePermissionService = Depends(
        get_agent_tool_file_permission_service
    ),
    workflow_svc: AgentWorkflowService = Depends(get_agent_workflow_service),
    run_svc: RunService = Depends(get_run_service),
):
    """
    Return full bay context for the agent environment JS module:
    agent info, spec state, tool projection with scope + file rows,
    keycard assignments, recent runs, workflows, workflow target preview.
    """
    from pathlib import Path as _Path
    from dataclasses import asdict

    try:
        agent = svc.get_or_raise(agent_id)
    except AgentNotFoundError:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")

    spec = svc.get_spec(agent_id)

    # Tool projection with scope and file rows
    state = access.get_assignment_state(agent_id)
    assigned_ids = set(state["assigned_capability_ids"])
    keycard_files = keycard.list_assignments(agent_id)
    permissions = tool_file_permissions.list_permissions(agent_id, include_revoked=True)
    allowed_matrix = {
        (record.capability_id, record.absolute_path): record
        for record in permissions
        if record.is_granted
    }
    assigned_tools = []
    for entry in state["assigned_installed_tools"]:
        scope = entry.get("scope", "local")
        file_rows = []
        for kf in keycard_files:
            file_rows.append({
                "absolute_path": kf.absolute_path,
                "root_path": kf.root_path,
                "relative_path": kf.relative_path,
                "global_tool_eligible": kf.global_tool_eligible,
                "entry_kind": kf.entry_kind if hasattr(kf, 'entry_kind') else "file",
                "availability_state": "present" if _Path(kf.absolute_path).exists() else "missing_on_disk",
                "tool_allowed": (entry["capability_id"], kf.absolute_path) in allowed_matrix,
                "direct_grant": (
                    (entry["capability_id"], kf.absolute_path) in allowed_matrix
                    and not kf.global_tool_eligible
                ),
            })
        assigned_tools.append({
            "capability_id": entry.get("capability_id"),
            "display_name": entry.get("display_name"),
            "capability_type": entry.get("capability_type"),
            "pack_id": entry.get("pack_id"),
            "version": entry.get("version"),
            "scope": scope,
            "file_rows": file_rows,
        })
    available_tools = [
        {
            "capability_id": e.get("capability_id"),
            "display_name": e.get("display_name"),
            "capability_type": e.get("capability_type"),
            "pack_id": e.get("pack_id"),
            "version": e.get("version"),
        }
        for e in state["installed_inventory_entries"]
        if e["capability_id"] not in assigned_ids
    ]
    unavailable = [
        {"capability_id": e.get("capability_id")}
        for e in state.get("unavailable_assignments", [])
    ]

    # Keycard assignments
    keycard_rows = []
    for kf in keycard_files:
        keycard_rows.append({
            "absolute_path": kf.absolute_path,
            "root_path": kf.root_path,
            "relative_path": kf.relative_path,
            "global_tool_eligible": kf.global_tool_eligible,
            "entry_kind": kf.entry_kind if hasattr(kf, 'entry_kind') else "file",
            "availability_state": "present" if _Path(kf.absolute_path).exists() else "missing_on_disk",
        })

    # Runs
    all_runs = run_svc.list_runs(limit=25)
    recent_runs = [r for r in all_runs if r.agent_id == agent_id][:8]
    workflow_runs = [r for r in recent_runs if r.options.get("workflow")][:5]

    def _run_dict(r):
        return {
            "id": r.id,
            "status": r.status,
            "started_at": r.started_at,
            "repo_path": r.repo_path,
            "agent_id": r.agent_id,
        }

    # Workflows
    workflows = [wf.to_dict() for wf in workflow_svc.list_for_agent(agent_id)]

    # Workflow target preview
    from reveng.platform.services.agent_workflow_bridge import preview_workflow_targets
    workflow_target_preview = preview_workflow_targets(
        agent_id,
        agent_workflow_service=workflow_svc,
        agent_keycard_service=keycard,
        agent_tool_file_permission_service=tool_file_permissions,
    )

    return {
        "agent": _agent_dict(agent),
        "spec_state": asdict(spec.current_state),
        "tool_projection": {
            "assigned_tools": assigned_tools,
            "local_tools": [t for t in assigned_tools if t["scope"] == "local"],
            "global_tools": [t for t in assigned_tools if t["scope"] == "global"],
            "available_tools": available_tools,
            "unavailable_assignments": unavailable,
            "installed_count": len(state["installed_inventory_entries"]),
        },
        "keycard": {
            "visible_files": keycard_rows,
            "visible_count": len(keycard_rows),
        },
        "runs": {
            "recent_runs": [_run_dict(r) for r in recent_runs],
            "workflow_runs": [_run_dict(r) for r in workflow_runs],
        },
        "workflows": workflows,
        "workflow_target_preview": {
            "targets": workflow_target_preview.get("targets", []),
            "error": workflow_target_preview.get("error"),
            "invoked_capabilities": workflow_target_preview.get("invoked_capabilities", []),
        },
    }


@router.get("/{agent_id}")
def get_agent(agent_id: str, svc: AgentService = Depends(get_agent_service)):
    try:
        return _agent_dict(svc.get_or_raise(agent_id))
    except AgentNotFoundError:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")


@router.patch("/{agent_id}")
def update_agent(
    agent_id: str,
    body: AgentUpdate,
    svc: AgentService = Depends(get_agent_service),
):
    try:
        agent = svc.update(
            agent_id,
            name=body.name,
            description=body.description,
            provider_id=body.provider_id,
            model=body.model,
            system_prompt=body.system_prompt,
            tool_bindings=body.tool_bindings,
            memory_config=body.memory_config,
        )
    except AgentNotFoundError:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _agent_dict(agent)


@router.delete("/{agent_id}", status_code=204)
def delete_agent(agent_id: str, svc: AgentService = Depends(get_agent_service)):
    try:
        svc.delete(agent_id)
    except AgentNotFoundError:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")


@router.patch("/{agent_id}/active")
def toggle_active(
    agent_id: str,
    body: ActiveToggle,
    svc: AgentService = Depends(get_agent_service),
):
    try:
        agent = svc.set_active(agent_id, body.active)
    except AgentNotFoundError:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
    return _agent_dict(agent)


@router.get("/{agent_id}/spec")
def get_agent_spec(agent_id: str, svc: AgentService = Depends(get_agent_service)):
    """Return the full structured AgentSpec for an agent."""
    try:
        spec = svc.get_spec(agent_id)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
    from dataclasses import asdict
    return asdict(spec)


@router.patch("/{agent_id}/sections/{section}")
def update_agent_section(
    agent_id: str,
    section: str,
    body: dict,
    svc: AgentService = Depends(get_agent_service),
):
    """
    Update a single section of an agent's structured internals.

    Body must be a JSON object matching the section's schema.
    """
    if section == "tool_access":
        raise HTTPException(
            status_code=409,
            detail=(
                "tool_access.allowed_capability_ids is derived from agent capability grants. "
                "Use the agent tools assignment endpoints instead of patching tool_access directly."
            ),
        )
    from reveng.agents.spec import ALL_SECTIONS
    if section not in ALL_SECTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown section: {section!r}. Valid sections: {ALL_SECTIONS}",
        )
    try:
        svc.get_or_raise(agent_id)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
    svc.update_section(agent_id, section, body)
    return {"agent_id": agent_id, "section": section, "updated": True}


@router.get("/{agent_id}/tools")
def get_agent_tools(
    agent_id: str,
    access: AgentCapabilityAccessService = Depends(get_agent_capability_access_service),
):
    try:
        projection = access.get_assignment_state(agent_id)
    except AgentNotFoundError:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
    return _build_tool_projection_payload(projection)


@router.post("/{agent_id}/tools/{capability_id}", status_code=201)
def grant_agent_tool(
    agent_id: str,
    capability_id: str,
    access: AgentCapabilityAccessService = Depends(get_agent_capability_access_service),
):
    try:
        result = access.grant_tool_to_agent(agent_id, capability_id)
    except AgentNotFoundError:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
    except CapabilityRecordNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"Installed capability not found: {capability_id}",
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {
        "assignment": result["assignment"],
        "capability": _assignment_projection_dict(result["capability"]),
    }


@router.delete("/{agent_id}/tools/{capability_id}", status_code=204)
def revoke_agent_tool(
    agent_id: str,
    capability_id: str,
    access: AgentCapabilityAccessService = Depends(get_agent_capability_access_service),
):
    try:
        access.revoke_tool_from_agent(agent_id, capability_id)
    except AgentNotFoundError:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")


@router.get("/{agent_id}/keycard")
def get_agent_keycard(
    agent_id: str,
    keycard: AgentKeycardService = Depends(get_agent_keycard_service),
):
    try:
        assignments = keycard.list_assignments(agent_id)
    except AgentNotFoundError:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
    return {
        "agent_id": agent_id,
        "visible_count": len(assignments),
        "global_enabled_count": sum(1 for item in assignments if item.global_tool_eligible),
        "visible_files": [
            _keycard_file_dict(
                {
                    "absolute_path": item.absolute_path,
                    "root_path": item.root_path,
                    "relative_path": item.relative_path,
                    "global_tool_eligible": item.global_tool_eligible,
                    "availability_state": "present" if item.exists_on_disk else "missing_on_disk",
                }
            )
            for item in assignments
        ],
    }


@router.post("/{agent_id}/keycard/files", status_code=201)
def assign_agent_keycard_files(
    agent_id: str,
    body: KeycardAssignFiles,
    keycard: AgentKeycardService = Depends(get_agent_keycard_service),
):
    try:
        assignments = keycard.assign_files(
            agent_id,
            root_path=body.root_path,
            absolute_paths=body.absolute_paths,
        )
    except AgentNotFoundError:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {
        "assigned_count": len(assignments),
        "assigned_files": [
            _keycard_file_dict(
                {
                    "absolute_path": item.absolute_path,
                    "root_path": item.root_path,
                    "relative_path": item.relative_path,
                    "global_tool_eligible": item.global_tool_eligible,
                    "availability_state": "present" if item.exists_on_disk else "missing_on_disk",
                }
            )
            for item in assignments
        ],
    }


@router.post("/{agent_id}/keycard/folders", status_code=201)
def assign_agent_keycard_folder(
    agent_id: str,
    body: KeycardAssignFolder,
    keycard: AgentKeycardService = Depends(get_agent_keycard_service),
):
    try:
        assignment = keycard.assign_folder(
            agent_id,
            root_path=body.root_path,
            absolute_path=body.absolute_path,
        )
    except AgentNotFoundError:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return _keycard_file_dict(
        {
            "absolute_path": assignment.absolute_path,
            "root_path": assignment.root_path,
            "relative_path": assignment.relative_path,
            "global_tool_eligible": assignment.global_tool_eligible,
            "entry_kind": assignment.entry_kind,
            "availability_state": "present" if assignment.exists_on_disk else "missing_on_disk",
        }
    )


@router.delete("/{agent_id}/keycard/files", status_code=204)
def remove_agent_keycard_file(
    agent_id: str,
    body: KeycardFileBody,
    keycard: AgentKeycardService = Depends(get_agent_keycard_service),
):
    try:
        keycard.remove_file(agent_id, body.absolute_path)
    except AgentNotFoundError:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")


@router.patch("/{agent_id}/keycard/files/global")
def toggle_agent_keycard_global(
    agent_id: str,
    body: KeycardGlobalToggle,
    keycard: AgentKeycardService = Depends(get_agent_keycard_service),
):
    try:
        assignment = keycard.set_global_eligibility(
            agent_id,
            body.absolute_path,
            enabled=body.enabled,
        )
    except AgentNotFoundError:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return _keycard_file_dict(
        {
            "absolute_path": assignment.absolute_path,
            "root_path": assignment.root_path,
            "relative_path": assignment.relative_path,
            "global_tool_eligible": assignment.global_tool_eligible,
            "availability_state": "present" if assignment.exists_on_disk else "missing_on_disk",
        }
    )


@router.patch("/{agent_id}/tool-file-permissions")
def toggle_agent_tool_file_permission(
    agent_id: str,
    body: ToolFilePermissionToggle,
    tool_file_permissions: AgentToolFilePermissionService = Depends(
        get_agent_tool_file_permission_service
    ),
):
    try:
        permission = tool_file_permissions.set_allowed(
            agent_id,
            body.capability_id,
            body.absolute_path,
            allowed=body.allowed,
        )
    except AgentNotFoundError:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {
        "agent_id": agent_id,
        "capability_id": body.capability_id,
        "absolute_path": body.absolute_path,
        "allowed": body.allowed,
        "permission": (
            {
                "capability_id": permission.capability_id,
                "absolute_path": permission.absolute_path,
                "permission_state": permission.permission_state,
                "source_kind": permission.source_kind,
            }
            if permission is not None
            else None
        ),
    }


# ---------------------------------------------------------------------------
# Per-tool Keycard assignment (direct, no global eligibility required)
# ---------------------------------------------------------------------------

@router.post("/{agent_id}/tools/{capability_id}/keycard", status_code=201)
def assign_to_tool_keycard(
    agent_id: str,
    capability_id: str,
    body: ToolKeycardAssign,
    keycard: AgentKeycardService = Depends(get_agent_keycard_service),
    tool_file_permissions: AgentToolFilePermissionService = Depends(
        get_agent_tool_file_permission_service
    ),
):
    """
    Add a file or folder to this agent's Keycard and grant it to this specific
    tool only.  Does not enable global eligibility — only the targeted tool gains
    access.  Works for both individual files and directories (recursive).
    """
    from pathlib import Path as _Path
    abs_path = _Path(body.absolute_path).expanduser().resolve()
    try:
        if abs_path.is_dir():
            keycard.assign_folder(agent_id, root_path=body.root_path, absolute_path=str(abs_path))
        else:
            keycard.assign_files(agent_id, root_path=body.root_path, absolute_paths=[str(abs_path)])
        permission = tool_file_permissions.grant_direct(agent_id, capability_id, str(abs_path))
    except AgentNotFoundError:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {
        "capability_id": capability_id,
        "absolute_path": permission.absolute_path,
        "permission_state": permission.permission_state,
        "source_kind": permission.source_kind,
    }


@router.delete("/{agent_id}/tools/{capability_id}/keycard", status_code=204)
def revoke_from_tool_keycard(
    agent_id: str,
    capability_id: str,
    body: KeycardFileBody,
    tool_file_permissions: AgentToolFilePermissionService = Depends(
        get_agent_tool_file_permission_service
    ),
):
    """
    Revoke this tool's access to a specific file or folder.  Does not remove
    the path from Keycard — only the per-tool permission record is revoked.
    """
    try:
        tool_file_permissions.set_allowed(
            agent_id,
            capability_id,
            body.absolute_path,
            allowed=False,
        )
    except AgentNotFoundError:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


# ---------------------------------------------------------------------------
# Tool scope (local / global)
# ---------------------------------------------------------------------------

@router.patch("/{agent_id}/tools/{capability_id}/scope")
def set_tool_scope(
    agent_id: str,
    capability_id: str,
    body: ToolScopeUpdate,
    assignments: AgentCapabilityAssignmentService = Depends(get_agent_capability_assignment_service),
):
    """
    Set the scope for a granted tool: 'local' uses per-tool Keycard assignments;
    'global' bypasses local and allows any globally-eligible file for the agent.
    Local assignments are preserved while global is active.
    """
    try:
        record = assignments.set_scope(agent_id, capability_id, body.scope)
    except AgentNotFoundError:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"capability_id": record.capability_id, "scope": record.scope}


# ---------------------------------------------------------------------------
# Agent workflow run trigger
# ---------------------------------------------------------------------------

@router.post("/{agent_id}/workflow/run", status_code=202)
def trigger_agent_workflow_run(
    agent_id: str,
    svc: AgentService = Depends(get_agent_service),
    workflow_svc: AgentWorkflowService = Depends(get_agent_workflow_service),
    access: AgentCapabilityAccessService = Depends(get_agent_capability_access_service),
    keycard: AgentKeycardService = Depends(get_agent_keycard_service),
    tool_file_permissions: AgentToolFilePermissionService = Depends(
        get_agent_tool_file_permission_service
    ),
    run_svc: RunService = Depends(get_run_service),
    event_svc: EventService = Depends(get_event_service),
    output_svc: OutputService = Depends(get_output_service),
    executor=Depends(get_executor),
    capability_registry=Depends(get_shared_capability_registry),
):
    """
    Trigger all active workflows for the agent.

    For each active workflow, targets are resolved by intersecting per-tool file
    permissions for each capability the workflow invokes.  One run is submitted
    per (active workflow × resolved target).

    Returns {run_ids, status: "pending"}.
    """
    from reveng.platform.services.agent_workflow_bridge import submit_agent_workflow_run

    try:
        run_ids = submit_agent_workflow_run(
            executor=executor,
            agent_id=agent_id,
            agent_service=svc,
            agent_workflow_service=workflow_svc,
            agent_capability_access_service=access,
            agent_keycard_service=keycard,
            agent_tool_file_permission_service=tool_file_permissions,
            run_service=run_svc,
            event_service=event_svc,
            output_service=output_svc,
            capability_registry=capability_registry,
        )
    except AgentNotFoundError:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
    except AgentInactiveError:
        raise HTTPException(
            status_code=409,
            detail="Agent is inactive. Activate the agent before running its workflow.",
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return {"run_ids": run_ids, "run_id": run_ids[0] if run_ids else None, "status": "pending"}


# ---------------------------------------------------------------------------
# Agent workflow CRUD
# ---------------------------------------------------------------------------

@router.get("/{agent_id}/workflows")
def list_agent_workflows(
    agent_id: str,
    workflow_svc: AgentWorkflowService = Depends(get_agent_workflow_service),
):
    """List all workflows (active and inactive) for the agent."""
    return [wf.to_dict() for wf in workflow_svc.list_for_agent(agent_id)]


@router.post("/{agent_id}/workflows", status_code=201)
def create_agent_workflow(
    agent_id: str,
    body: WorkflowCreate,
    workflow_svc: AgentWorkflowService = Depends(get_agent_workflow_service),
):
    """Create a new workflow for the agent."""
    wf = workflow_svc.create(
        agent_id,
        display_name=body.display_name,
        instruction_code=body.instruction_code,
    )
    return wf.to_dict()


@router.patch("/{agent_id}/workflows/{workflow_id}")
def update_agent_workflow(
    agent_id: str,
    workflow_id: str,
    body: WorkflowUpdate,
    workflow_svc: AgentWorkflowService = Depends(get_agent_workflow_service),
):
    """Update a workflow's name, code, active state, and/or trigger assignment."""
    try:
        wf = workflow_svc.update(
            workflow_id,
            display_name=body.display_name,
            instruction_code=body.instruction_code,
            is_active=body.is_active,
            assigned_triggers=body.assigned_triggers,
        )
    except AgentWorkflowNotFoundError:
        raise HTTPException(status_code=404, detail=f"Workflow not found: {workflow_id}")
    return wf.to_dict()


@router.delete("/{agent_id}/workflows/{workflow_id}", status_code=204)
def delete_agent_workflow(
    agent_id: str,
    workflow_id: str,
    workflow_svc: AgentWorkflowService = Depends(get_agent_workflow_service),
):
    """Delete a workflow."""
    try:
        workflow_svc.get(workflow_id)  # 404 check
    except AgentWorkflowNotFoundError:
        raise HTTPException(status_code=404, detail=f"Workflow not found: {workflow_id}")
    workflow_svc.delete(workflow_id)


# ---------------------------------------------------------------------------
# Trigger CRUD (per workflow)
# ---------------------------------------------------------------------------

@router.patch("/{agent_id}/workflows/{workflow_id}/trigger")
def update_workflow_trigger(
    agent_id: str,
    workflow_id: str,
    body: TriggerUpdate,
    workflow_svc: AgentWorkflowService = Depends(get_agent_workflow_service),
):
    """
    Update the trigger definition for a specific workflow.

    Accepted kinds: tool_permission_intersection, keycard_all, explicit_paths.
    For explicit_paths, supply config={"paths": ["path1", ...]}.
    """
    from reveng.agents.triggers import AgentTriggerDefinition, ALL_KINDS
    if body.kind not in ALL_KINDS:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown trigger kind '{body.kind}'. Valid kinds: {list(ALL_KINDS)}",
        )
    try:
        wf = workflow_svc.update(
            workflow_id,
            trigger=AgentTriggerDefinition(
                kind=body.kind,
                output_filename=body.output_filename,
                config=body.config,
            ).to_dict(),
        )
    except AgentWorkflowNotFoundError:
        raise HTTPException(status_code=404, detail=f"Workflow not found: {workflow_id}")
    return wf.to_dict()


# ---------------------------------------------------------------------------
# Manual Trigger area — run order
# ---------------------------------------------------------------------------

@router.get("/{agent_id}/manual-trigger")
def get_manual_trigger(
    agent_id: str,
    workflow_svc: AgentWorkflowService = Depends(get_agent_workflow_service),
):
    """
    Return the Manual Trigger state: ordered list of workflows with 'manual' assigned.

    Workflows in the stored order come first; any manual-assigned workflows not
    yet in the order are appended at the end.
    """
    from reveng.agents.triggers import MANUAL
    ordered = workflow_svc.list_for_activation_trigger(agent_id, MANUAL)
    stored_order = workflow_svc.get_manual_run_order(agent_id)
    return {
        "stored_order": stored_order,
        "workflows": [wf.to_dict() for wf in ordered],
    }


@router.put("/{agent_id}/manual-trigger/order")
def set_manual_trigger_order(
    agent_id: str,
    body: ManualOrderUpdate,
    workflow_svc: AgentWorkflowService = Depends(get_agent_workflow_service),
):
    """
    Persist the run order for manual-triggered workflows.

    body.order must be a list of workflow IDs.  This order determines sequential
    execution sequence when the manual trigger fires.
    """
    workflow_svc.set_manual_run_order(agent_id, body.order)
    return {"agent_id": agent_id, "order": body.order}
