"""
AgentSpec — structured internal definition of an agent.

This is the Agents Domain representation of an agent.  It is owned by the
Agents Domain and persisted by Storage Substrate (AgentRecord in platform).

Design notes
------------
Each section is an independent dataclass with its own JSON serialization.
Sections are stored in the agent_sections table (one row per section per agent),
so they can be read, written, and evolved independently.

Sections marked PROVISIONAL have their shape defined but their semantics are
intentionally not enforced yet.  They exist so the structural home is ready
when behavioral layers arrive.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from sqlite3 import Row
from typing import Any

from reveng.agents.triggers import AgentTriggerDefinition, DEFAULT_ASSIGNED_TRIGGERS


# ---------------------------------------------------------------------------
# Section: identity
# The agent's stable self-description.  Stable — not provisional.
# ---------------------------------------------------------------------------

@dataclass
class AgentIdentity:
    name: str
    role: str           # free-text label e.g. "analyst", "summarizer" — type is provisional
    description: str
    system_prompt: str  # promoted from flat agents.system_prompt


# ---------------------------------------------------------------------------
# Section: tool_access
# Which capabilities and LLM provider the agent may use.  Stable.
# ---------------------------------------------------------------------------

@dataclass
class AgentToolAccess:
    allowed_capability_ids: list[str]   # projected from agent capability assignments
    provider_id: str                    # promoted from flat agents.provider_id
    model: str                          # promoted from flat agents.model


# ---------------------------------------------------------------------------
# Section: activation
# Controls whether the agent is live and under what conditions.
# is_active is stable (existing gate).  triggers are PROVISIONAL.
# ---------------------------------------------------------------------------

@dataclass
class AgentActivation:
    is_active: bool              # existing activation gate — enforced by AgentService
    triggers: list[dict]         # PROVISIONAL: stub list, never evaluated yet


# ---------------------------------------------------------------------------
# Section: current_state
# Inspectable runtime snapshot.  Written by the platform during runs.
# health is PROVISIONAL (always "unknown" for now).
# ---------------------------------------------------------------------------

@dataclass
class AgentCurrentState:
    activation_status: str       # "active" | "inactive" | "suspended"
    current_run_id: str | None   # set only when the platform associates a live run to this agent
    last_activated_at: str | None
    health: str                  # PROVISIONAL — always "unknown" for now


# ---------------------------------------------------------------------------
# Section: persistent_state  PROVISIONAL
# Durable key-value store.  Shape defined; no automated write path yet.
# ---------------------------------------------------------------------------

@dataclass
class AgentPersistentState:
    entries: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Section: recorded_memory  PROVISIONAL
# Durable memory records.  Shape defined; no capture mechanism yet.
# Each record: {key, content, recorded_at, source}
# ---------------------------------------------------------------------------

@dataclass
class AgentRecordedMemory:
    records: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Section: working_memory  PROVISIONAL
# In-flight context, cleared between sessions.  Always {} for now.
# ---------------------------------------------------------------------------

@dataclass
class AgentWorkingMemory:
    context: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Section: notes  PROVISIONAL
# Structured notes.  Shape defined; no editor yet.
# Each entry: {title, content, created_at}
# ---------------------------------------------------------------------------

@dataclass
class AgentNotes:
    entries: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Section: visibility_scope  PROVISIONAL
# What the agent is allowed to see.  Shape defined; not enforced yet.
# ---------------------------------------------------------------------------

@dataclass
class AgentVisibilityScope:
    allowed_scopes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Section: workflow
# Agent-owned workflow code and target-resolution trigger config.
# instruction_code: Python source stored verbatim.  Must define run(target, output_path).
# trigger: how the agent resolves its input target from File Permissions state.
# ---------------------------------------------------------------------------

@dataclass
class AgentWorkflowEntry:
    """
    One stored workflow for an agent.  Multiple entries can exist per agent.

    Persisted in the agent_workflows table (one row per entry).

    Fields:
      is_active         — global enable/disable switch for this workflow.
      assigned_triggers — which activation kinds fire this workflow (e.g. ["manual"]).
                          A workflow only runs when both is_active=True AND the
                          firing trigger kind is in assigned_triggers.
      trigger           — AgentTriggerDefinition: target resolution spec (how/where
                          the workflow runs when it fires).
    """
    id: str
    agent_id: str
    display_name: str
    instruction_code: str
    trigger: AgentTriggerDefinition
    assigned_triggers: list[str]
    is_active: bool
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: Row) -> "AgentWorkflowEntry":
        raw = json.loads(row["trigger_json"] or "{}")
        raw_assigned = row["assigned_triggers_json"] if "assigned_triggers_json" in row.keys() else None
        assigned = json.loads(raw_assigned or "null") or list(DEFAULT_ASSIGNED_TRIGGERS)
        return cls(
            id=row["id"],
            agent_id=row["agent_id"],
            display_name=row["display_name"],
            instruction_code=row["instruction_code"],
            trigger=AgentTriggerDefinition.from_dict(raw),
            assigned_triggers=assigned,
            is_active=bool(row["is_active"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "display_name": self.display_name,
            "instruction_code": self.instruction_code,
            "trigger": self.trigger.to_dict(),
            "assigned_triggers": self.assigned_triggers,
            "is_active": self.is_active,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class AgentWorkflow:
    instruction_code: str = ""
    trigger: dict = field(default_factory=lambda: {
        "mode": "repo_root_from_keycard",
        "output_filename": "workflow_output.json",
    })


# ---------------------------------------------------------------------------
# AgentSpec — the full structured agent definition
# ---------------------------------------------------------------------------

@dataclass
class AgentSpec:
    """
    Complete structured definition of an agent.

    Owned by Agents Domain.  Persisted by AgentRecord via agent_sections table.
    AgentSpec does not define behavior — it defines structure.
    Behavioral layers will be added on top of this shape.
    """
    identity: AgentIdentity
    tool_access: AgentToolAccess
    activation: AgentActivation
    current_state: AgentCurrentState
    persistent_state: AgentPersistentState = field(default_factory=AgentPersistentState)
    recorded_memory: AgentRecordedMemory = field(default_factory=AgentRecordedMemory)
    working_memory: AgentWorkingMemory = field(default_factory=AgentWorkingMemory)
    notes: AgentNotes = field(default_factory=AgentNotes)
    visibility_scope: AgentVisibilityScope = field(default_factory=AgentVisibilityScope)
    workflow: AgentWorkflow = field(default_factory=AgentWorkflow)


# ---------------------------------------------------------------------------
# Section names — canonical string keys used in agent_sections table
# ---------------------------------------------------------------------------

SECTION_IDENTITY = "identity"
SECTION_TOOL_ACCESS = "tool_access"
SECTION_ACTIVATION = "activation"
SECTION_CURRENT_STATE = "current_state"
SECTION_PERSISTENT_STATE = "persistent_state"
SECTION_RECORDED_MEMORY = "recorded_memory"
SECTION_WORKING_MEMORY = "working_memory"
SECTION_NOTES = "notes"
SECTION_VISIBILITY_SCOPE = "visibility_scope"
SECTION_WORKFLOW = "workflow"

ALL_SECTIONS = [
    SECTION_IDENTITY,
    SECTION_TOOL_ACCESS,
    SECTION_ACTIVATION,
    SECTION_CURRENT_STATE,
    SECTION_PERSISTENT_STATE,
    SECTION_RECORDED_MEMORY,
    SECTION_WORKING_MEMORY,
    SECTION_NOTES,
    SECTION_VISIBILITY_SCOPE,
    SECTION_WORKFLOW,
]
