from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .artifacts import ArtifactRef, ArtifactStore
    from .cache import CachePolicy, ExistsAndNonEmptyCachePolicy, NoCachePolicy
    from .host import RevEngHost, WorkflowRunResult
    from .logging import FrameworkLogRecord, emit_framework_log
    from .runtime import WorkflowRuntime
    from .workflows import WorkflowDefinition, WorkflowRegistry
    from reveng.platform.capabilities import (
        CapabilityContext,
        CapabilityContract,
        CapabilityDefinition,
        CapabilityRegistry,
        CombinationSpec,
        validate_capability,
    )


_LAZY_EXPORTS = {
    "ArtifactRef": "reveng.framework.artifacts",
    "ArtifactStore": "reveng.framework.artifacts",
    "CachePolicy": "reveng.framework.cache",
    "ExistsAndNonEmptyCachePolicy": "reveng.framework.cache",
    "NoCachePolicy": "reveng.framework.cache",
    "RevEngHost": "reveng.framework.host",
    "WorkflowRunResult": "reveng.framework.host",
    "FrameworkLogRecord": "reveng.framework.logging",
    "emit_framework_log": "reveng.framework.logging",
    "WorkflowRuntime": "reveng.framework.runtime",
    "WorkflowDefinition": "reveng.framework.workflows",
    "WorkflowRegistry": "reveng.framework.workflows",
    "CapabilityContext": "reveng.platform.capabilities",
    "CapabilityContract": "reveng.platform.capabilities",
    "CapabilityDefinition": "reveng.platform.capabilities",
    "CapabilityRegistry": "reveng.platform.capabilities",
    "CombinationSpec": "reveng.platform.capabilities",
    "validate_capability": "reveng.platform.capabilities",
}


def __getattr__(name: str):
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(name)
    module = import_module(module_name)
    return getattr(module, name)


__all__ = list(_LAZY_EXPORTS)
