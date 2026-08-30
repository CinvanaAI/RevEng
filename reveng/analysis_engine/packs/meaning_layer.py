"""Pack that registers all Task Agent (meaning layer) capabilities.

Registers 9 capabilities under meaning.* IDs:
  meaning.abilities.extract
  meaning.actions.derive
  meaning.functions.derive
  meaning.files.purpose
  meaning.files.behavior
  meaning.workflows.derive
  meaning.modules.summarize
  meaning.subsystems.summarize
  meaning.system.summarize
"""
from __future__ import annotations

from reveng.analysis_engine.agentic.tasks import (
    abilities,
    actions,
    file_behavior,
    file_purpose,
    function_meaning,
    modules,
    subsystems,
    system,
    workflows,
)
from reveng.platform.capabilities import CapabilityRegistry


def register(registry: CapabilityRegistry) -> None:
    abilities.register(registry)
    actions.register(registry)
    function_meaning.register(registry)
    file_purpose.register(registry)
    file_behavior.register(registry)
    workflows.register(registry)
    modules.register(registry)
    subsystems.register(registry)
    system.register(registry)
