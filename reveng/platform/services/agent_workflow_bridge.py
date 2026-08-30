"""
Agent workflow bridge — platform seam for agent-authored workflow execution.

Mirrors the structure of analysis_bridge.py.  Owns the submit/execute lifecycle
for agent workflow runs: creates the DB record, hands off to the background
executor, and captures all status transitions, events, and outputs.

Only this file should call run_agent_workflow() from coordination.

Target resolution
-----------------
Targets are resolved per-tool from the per-file permission layer:

1. The workflow code is AST-scanned for capability_registry.<attr> accesses to
   identify the set of invoked capability IDs.
2. For each invoked capability, the set of root_paths that have at least one
   granted file-level permission is computed from agent_tool_file_permissions
   joined to agent_file_assignments.
3. Those per-capability root sets are intersected.  The result is the set of
   root paths the workflow may actually run against.
4. One run is submitted per target in the intersection.

Keycard/root visibility remains the broad boundary.  Per-tool file permissions
are the actual execution target source.
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from reveng.coordination.result_contract import new_run_id
from reveng.coordination.host_composition import build_default_host
from reveng.coordination.agent_workflow_runner import run_agent_workflow
from reveng.framework.runtime import WorkflowRuntime
from reveng.platform.services.agent_capability_access_service import (
    AgentCapabilityAccessService,
)
from reveng.platform.services.agent_keycard_service import AgentKeycardService
from reveng.platform.services.agent_service import AgentService
from reveng.platform.services.agent_tool_file_permission_service import (
    AgentToolFilePermissionService,
)
from reveng.agents.triggers import (
    AgentTriggerDefinition,
    EXPLICIT_PATHS,
    KEYCARD_ALL,
    MANUAL,
    TOOL_PERMISSION_INTERSECTION,
)
from reveng.platform.services.agent_workflow_service import AgentWorkflowService
from reveng.platform.services.event_service import EventService
from reveng.platform.services.output_service import OutputService
from reveng.platform.services.run_service import RunService
from reveng.storage.paths import agent_workflow_output_dir


# ---------------------------------------------------------------------------
# Target resolution helpers
# ---------------------------------------------------------------------------

def _extract_invoked_capability_ids(workflow_code: str) -> set[str]:
    """
    Return the set of capability IDs referenced as capability_registry.<attr>
    in the workflow source.

    Uses AST analysis — does not execute the code.
    """
    tree = ast.parse(workflow_code)
    ids: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "capability_registry"
        ):
            ids.add(node.attr)
    return ids


def _expand_permission_paths(paths: set[str]) -> set[str]:
    """Expand any directory paths in a set to their contained files (recursive).

    File paths are kept as-is.  Folder paths are replaced with the files inside
    them so that per-file trigger resolution is correct when a folder was used
    as the permission entry rather than individual files.
    """
    expanded: set[str] = set()
    for path_str in paths:
        p = Path(path_str)
        if p.is_dir():
            for f in p.rglob("*"):
                if f.is_file():
                    expanded.add(str(f.resolve()))
        else:
            expanded.add(path_str)
    return expanded


def _resolve_tool_permission_intersection(
    agent_id: str,
    invoked_capability_ids: set[str],
    agent_keycard_service: AgentKeycardService,
    agent_tool_file_permission_service: AgentToolFilePermissionService,
) -> list[str]:
    """
    Resolve targets via per-tool file permission intersection.

    For each invoked capability, fetches the set of absolute_path entries with
    granted permissions, then intersects those sets across all capabilities.
    Falls back to all keycard-visible entries when no capabilities are invoked.

    This is the implementation of trigger kind TOOL_PERMISSION_INTERSECTION.
    It was previously hardcoded as the only target resolution algorithm.
    """
    if not invoked_capability_ids:
        entries = agent_keycard_service.list_visible_file_paths(agent_id)
        if not entries:
            raise ValueError(
                "No keycard files assigned. Add files to the Keycard before running."
            )
        return entries

    per_cap_entry_sets: dict[str, set[str]] = {}
    for cap_id in sorted(invoked_capability_ids):
        granted = agent_tool_file_permission_service.list_permissions(
            agent_id, capability_id=cap_id
        )
        raw_entries = {perm.absolute_path for perm in granted}
        if not raw_entries:
            raise ValueError(
                f"Capability '{cap_id}' has no granted file permissions. "
                f"Grant file-level access for '{cap_id}' in the Tools Station before running."
            )
        per_cap_entry_sets[cap_id] = _expand_permission_paths(raw_entries)

    intersection: set[str] = set.intersection(*per_cap_entry_sets.values())
    if not intersection:
        cap_list = ", ".join(f"'{c}'" for c in sorted(per_cap_entry_sets))
        raise ValueError(
            f"No file entry has permissions granted for all invoked capabilities "
            f"({cap_list}). Ensure at least one common file has permitted access "
            f"for every tool the workflow invokes."
        )
    return sorted(intersection)


def _resolve_targets_for_trigger(
    trigger: AgentTriggerDefinition,
    agent_id: str,
    workflow_code: str,
    agent_keycard_service: AgentKeycardService,
    agent_tool_file_permission_service: AgentToolFilePermissionService,
) -> list[str]:
    """
    Dispatch target resolution based on the workflow's stored trigger kind.

    This is the single authoritative entry point for target resolution.
    The algorithm used is determined entirely by trigger.kind — no defaults
    are silently imposed here.
    """
    if trigger.kind == EXPLICIT_PATHS:
        paths = [str(p).strip() for p in trigger.config.get("paths", []) if str(p).strip()]
        if not paths:
            raise ValueError(
                "Trigger kind 'explicit_paths' has no paths configured. "
                "Add at least one absolute path in the Trigger section."
            )
        return sorted(paths)

    if trigger.kind == KEYCARD_ALL:
        entries = agent_keycard_service.list_visible_file_paths(agent_id)
        if not entries:
            raise ValueError(
                "Trigger kind 'keycard_all': no keycard files assigned. "
                "Add files to the Keycard before running."
            )
        return entries

    # TOOL_PERMISSION_INTERSECTION (default)
    invoked = _extract_invoked_capability_ids(workflow_code)
    return _resolve_tool_permission_intersection(
        agent_id, invoked, agent_keycard_service, agent_tool_file_permission_service
    )


def preview_workflow_targets(
    agent_id: str,
    *,
    agent_workflow_service: AgentWorkflowService,
    agent_keycard_service: AgentKeycardService,
    agent_tool_file_permission_service: AgentToolFilePermissionService,
) -> dict:
    """
    Compute the resolved target set for the first active workflow without
    submitting a run.  Safe to call on page load.

    Returns a dict with keys:
      targets: list[str]   — resolved entry paths (empty on error)
      error:   str | None  — human-readable error message, or None
      invoked_capabilities: list[str]  — capabilities found in the workflow code
    """
    try:
        active = agent_workflow_service.list_active_for_agent(agent_id)
        if not active:
            return {"targets": [], "error": "No active workflows. Add a workflow and enable it.", "invoked_capabilities": []}
        workflow = active[0]
        if not workflow.instruction_code.strip():
            return {"targets": [], "error": "Active workflow has no code.", "invoked_capabilities": []}
        targets = _resolve_targets_for_trigger(
            workflow.trigger,
            agent_id,
            workflow.instruction_code,
            agent_keycard_service,
            agent_tool_file_permission_service,
        )
        # Surface invoked capabilities for informational display (relevant for tool_permission_intersection)
        invoked = (
            sorted(_extract_invoked_capability_ids(workflow.instruction_code))
            if workflow.trigger.kind == TOOL_PERMISSION_INTERSECTION
            else []
        )
        return {"targets": targets, "error": None, "invoked_capabilities": invoked}
    except ValueError as exc:
        return {"targets": [], "error": str(exc), "invoked_capabilities": []}


# ---------------------------------------------------------------------------
# Sequential execution helper (manual trigger)
# ---------------------------------------------------------------------------

def _execute_runs_sequentially(
    run_contexts: list[dict],
    *,
    run_service: RunService,
    event_service: EventService,
    output_service: OutputService,
    agent_id: str,
    agent_service: AgentService,
    agent_capability_access_service: AgentCapabilityAccessService,
    capability_registry: Any | None = None,
) -> None:
    """
    Execute a pre-created list of run contexts one after another in a single
    background thread.

    Each context dict must have: run_id, instruction_code, target, output_path.
    The next run only starts after the previous one finishes (or fails).
    """
    for ctx in run_contexts:
        execute_agent_workflow_run(
            ctx["run_id"],
            ctx["instruction_code"],
            ctx["target"],
            ctx["output_path"],
            run_service=run_service,
            event_service=event_service,
            output_service=output_service,
            agent_id=agent_id,
            agent_service=agent_service,
            agent_capability_access_service=agent_capability_access_service,
            capability_registry=capability_registry,
        )


# ---------------------------------------------------------------------------
# Public submission entry point
# ---------------------------------------------------------------------------

def submit_agent_workflow_run(
    *,
    executor: Any,
    agent_id: str,
    firing_trigger: str = MANUAL,
    agent_service: AgentService,
    agent_workflow_service: AgentWorkflowService,
    agent_capability_access_service: AgentCapabilityAccessService,
    agent_keycard_service: AgentKeycardService,
    agent_tool_file_permission_service: AgentToolFilePermissionService,
    run_service: RunService,
    event_service: EventService,
    output_service: OutputService,
    capability_registry: Any | None = None,
) -> list[str]:
    """
    Validate, resolve targets, create run records, and submit to the executor
    for workflows assigned to the firing trigger.

    For MANUAL trigger: workflows run sequentially in stored manual run order
    (one background task, each workflow starts only after the previous finishes).
    For other triggers (future): workflows run concurrently (one task each).

    Returns a list of pre-created run_ids.  Callers can poll each run_id
    independently — all records exist before execution begins.

    Raises
    ------
    AgentInactiveError
        If the agent is not active.
    ValueError
        If no eligible workflows exist, all eligible workflows are empty, or
        no targets can be resolved.
    """
    agent_service.get_active_or_raise(agent_id)

    eligible = agent_workflow_service.list_for_activation_trigger(agent_id, firing_trigger)
    if not eligible:
        raise ValueError(
            f"No active workflows have '{firing_trigger}' assigned. "
            "Add a workflow and assign the trigger before running."
        )

    run_ids: list[str] = []
    run_contexts: list[dict] = []  # used for sequential manual execution

    for workflow in eligible:
        if not workflow.instruction_code.strip():
            continue

        output_filename = workflow.trigger.output_filename
        targets = _resolve_targets_for_trigger(
            workflow.trigger,
            agent_id,
            workflow.instruction_code,
            agent_keycard_service,
            agent_tool_file_permission_service,
        )
        invoked_cap_ids = (
            _extract_invoked_capability_ids(workflow.instruction_code)
            if workflow.trigger.kind == TOOL_PERMISSION_INTERSECTION
            else set()
        )

        for raw_target in targets:
            resolved_target = str(Path(raw_target).resolve())
            run_id = new_run_id()
            out_dir = agent_workflow_output_dir(agent_id, run_id).resolve()
            resolved_output_path = str(out_dir / output_filename)

            run_service.create(
                run_id=run_id,
                repo_path=resolved_target,
                output_dir=str(out_dir),
                options={
                    "workflow": True,
                    "workflow_id": workflow.id,
                    "workflow_name": workflow.display_name,
                    "firing_trigger": firing_trigger,
                    "output_filename": output_filename,
                    "invoked_capabilities": sorted(invoked_cap_ids),
                    "target_count": len(targets),
                },
                agent_id=agent_id,
            )
            event_service.append(
                run_id, "info",
                {"message": f"Workflow '{workflow.display_name}' queued via '{firing_trigger}' trigger. Target: {resolved_target}"},
            )
            run_ids.append(run_id)
            run_contexts.append({
                "run_id": run_id,
                "instruction_code": workflow.instruction_code,
                "target": resolved_target,
                "output_path": resolved_output_path,
            })

    if not run_ids:
        raise ValueError("All eligible workflows are empty. Add code before running.")

    shared_kwargs = dict(
        run_service=run_service,
        event_service=event_service,
        output_service=output_service,
        agent_id=agent_id,
        agent_service=agent_service,
        agent_capability_access_service=agent_capability_access_service,
        capability_registry=capability_registry,
    )

    if firing_trigger == MANUAL:
        # Sequential: one background task runs all contexts in order.
        executor.submit(_execute_runs_sequentially, run_contexts, **shared_kwargs)
    else:
        # Concurrent: each context gets its own background task.
        for ctx in run_contexts:
            executor.submit(
                execute_agent_workflow_run,
                ctx["run_id"],
                ctx["instruction_code"],
                ctx["target"],
                ctx["output_path"],
                **shared_kwargs,
            )

    return run_ids


# ---------------------------------------------------------------------------
# Background executor function
# ---------------------------------------------------------------------------

def execute_agent_workflow_run(
    run_id: str,
    instruction_code: str,
    target: str,
    output_path: str,
    *,
    run_service: RunService,
    event_service: EventService,
    output_service: OutputService,
    agent_id: str,
    agent_service: AgentService,
    agent_capability_access_service: AgentCapabilityAccessService,
    capability_registry: Any | None = None,
) -> None:
    """
    Execute the agent workflow in a background thread.

    Called by the ThreadPoolExecutor.  Does not raise — all exceptions are
    caught and stored as failure state so the web layer can surface them.
    """
    event_service.append(run_id, "status_change", {"old": "pending", "new": "running"})
    run_service.mark_running(run_id)

    try:
        agent_service.set_current_run(agent_id, run_id)
    except Exception:
        pass

    try:
        run_record = run_service.get_or_raise(run_id)
        output_dir = Path(run_record.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        permission_check = agent_capability_access_service.build_runtime_permission_check(
            agent_id
        )

        host = build_default_host(run_id=run_id, capability_registry=capability_registry)

        runtime = WorkflowRuntime(
            capability_registry=host.capabilities,
            output_dir=output_dir,
            run_id=run_id,
            workflow_id=None,
            cache=host.cache_policy,
            permission_check=permission_check,
        )

        result = run_agent_workflow(instruction_code, target, output_path, runtime)

        # Capture explicit run() return values
        for key, value in result.items():
            output_service.record(run_id, key, "inline_json", str(value))

        # Capture the output file if written
        if Path(output_path).exists():
            output_service.record(run_id, "output_file", "file_path", output_path)
            event_service.append(
                run_id, "output_ready",
                {"key": "output_file", "path": output_path},
            )

        # Capture any paths recorded via runtime.record_artifact
        for path in runtime.written_paths:
            output_service.record(run_id, "written_path", "file_path", path)

        run_service.mark_completed(run_id)
        event_service.append(run_id, "status_change", {"old": "running", "new": "completed"})

    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        run_service.mark_failed(run_id, error_msg)
        event_service.append(run_id, "status_change", {"old": "running", "new": "failed"})
        event_service.append(run_id, "error", {"message": error_msg})

    finally:
        try:
            agent_service.set_current_run(agent_id, None)
        except Exception:
            pass
