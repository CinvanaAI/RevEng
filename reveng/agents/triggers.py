"""
Agent trigger definitions — Agents Domain.

Two separate concepts live here:

1. Activation triggers  — WHEN does a workflow run?
   These are the assignments on each workflow (assigned_triggers list).
   Adding a new activation kind here (and adding a dispatch branch in the bridge)
   is what makes a new trigger type real.

   Supported activation kinds:
     manual
       Workflow is eligible when the operator clicks "Go Eat" (manual activation).
       Manual-assigned workflows run sequentially in the order stored in the
       agent's Manual Trigger section.  They do not all fire simultaneously.

2. Target resolution — HOW/WHERE does the workflow run?
   Expressed as AgentTriggerDefinition (kept separate from activation).
   These answer: given that the trigger fired, what file/path inputs does the
   workflow receive?

   Supported resolution kinds:
     tool_permission_intersection  (default — original hardcoded backend behavior)
       Intersects per-tool file permissions for all capability_registry calls in
       the workflow code.  Falls back to keycard-visible entries when none invoked.
     keycard_all
       Uses all Keycard-assigned file entries without capability filtering.
     explicit_paths
       Uses an explicit user-supplied list of absolute paths.
       Config: {"paths": ["path1", "path2"]}

Legacy migration
----------------
The pre-trigger format stored {"mode": "repo_root_from_keycard", "output_filename": "..."}
in trigger_json.  AgentTriggerDefinition.from_dict() transparently promotes that
to kind="tool_permission_intersection" on read — no DB migration required.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Activation trigger kind constants
# ---------------------------------------------------------------------------

MANUAL = "manual"

ALL_ACTIVATION_KINDS: tuple[str, ...] = (MANUAL,)
DEFAULT_ASSIGNED_TRIGGERS: list[str] = [MANUAL]

# ---------------------------------------------------------------------------
# Target resolution kind constants
# ---------------------------------------------------------------------------

TOOL_PERMISSION_INTERSECTION = "tool_permission_intersection"
KEYCARD_ALL = "keycard_all"
EXPLICIT_PATHS = "explicit_paths"

ALL_RESOLUTION_KINDS: tuple[str, ...] = (TOOL_PERMISSION_INTERSECTION, KEYCARD_ALL, EXPLICIT_PATHS)

# Backwards-compat alias — previously named ALL_KINDS
ALL_KINDS: tuple[str, ...] = ALL_RESOLUTION_KINDS

DEFAULT_KIND = TOOL_PERMISSION_INTERSECTION
DEFAULT_OUTPUT_FILENAME = "workflow_output.json"

# Maps legacy 'mode' strings to their canonical resolution kind equivalents.
_LEGACY_MODE_MAP: dict[str, str] = {
    "repo_root_from_keycard": TOOL_PERMISSION_INTERSECTION,
}


@dataclass
class AgentTriggerDefinition:
    """
    Agent-owned trigger definition.

    Serialised into the trigger_json column of agent_workflows.
    The bridge reads .kind to dispatch the right target resolution algorithm
    rather than running one hardcoded algorithm unconditionally.
    """
    kind: str = DEFAULT_KIND
    output_filename: str = DEFAULT_OUTPUT_FILENAME
    config: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "AgentTriggerDefinition":
        """
        Deserialise from a stored JSON dict.

        Handles the legacy format that used 'mode' instead of 'kind' and
        had no 'config' field.  Unknown kind values fall back to the default.
        """
        raw_kind = data.get("kind") or _LEGACY_MODE_MAP.get(
            data.get("mode", ""), DEFAULT_KIND
        )
        kind = raw_kind if raw_kind in ALL_KINDS else DEFAULT_KIND
        return cls(
            kind=kind,
            output_filename=data.get("output_filename", DEFAULT_OUTPUT_FILENAME),
            config=data.get("config") or {},
        )

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "output_filename": self.output_filename,
            "config": self.config,
        }


__all__ = [
    "AgentTriggerDefinition",
    # Activation kinds
    "MANUAL",
    "ALL_ACTIVATION_KINDS",
    "DEFAULT_ASSIGNED_TRIGGERS",
    # Resolution kinds
    "TOOL_PERMISSION_INTERSECTION",
    "KEYCARD_ALL",
    "EXPLICIT_PATHS",
    "ALL_RESOLUTION_KINDS",
    "ALL_KINDS",
    "DEFAULT_KIND",
    "DEFAULT_OUTPUT_FILENAME",
]
