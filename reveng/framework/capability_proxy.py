"""
CapabilityRegistryProxy — flat-namespace proxy for agent workflow code.

Exposes installed capabilities as plain callable attributes so that
agent-authored Python workflow code can call:

    capability_registry.resolve_path(path)
    capability_registry.scan_repo_for_function_sources(repo_root)

Each call dispatches through WorkflowRuntime.invoke(), keeping the full
permission enforcement path active.

Only flat-namespace capability IDs (no dots) are exposed as attributes.
Dotted capability IDs are not valid Python identifiers and therefore cannot
be accessed this way — use __getitem__ syntax instead:

    result = capability_registry["python.scan_repo"](repo_path=target)

Lazy construction
-----------------
Wrappers are NOT pre-built in __init__.  Each attribute access resolves the
capability on demand from the registry.  This eliminates the O(n) __init__
cost that would become catastrophic at large capability counts.
"""
from __future__ import annotations

from typing import Any, Callable

from reveng.framework.runtime import WorkflowRuntime
from reveng.platform.capabilities import CapabilityRegistry


def _make_capability_wrapper(
    runtime: WorkflowRuntime,
    capability_id: str,
    input_names: tuple[str, ...],
    output_keys: tuple[str, ...],
) -> Callable[..., Any]:
    """
    Return a callable that maps positional/keyword arguments to runtime.invoke().

    If the capability has exactly one output key, its value is returned directly.
    If it has multiple output keys, the full result dict is returned.
    """
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        inputs: dict[str, Any] = dict(zip(input_names, args))
        inputs.update(kwargs)
        result = runtime.invoke(capability_id, inputs)
        if len(output_keys) == 1:
            return result.get(output_keys[0])
        return result
    wrapper.__name__ = capability_id
    return wrapper


class CapabilityRegistryProxy:
    """
    Proxy that binds a flat capability namespace to a live WorkflowRuntime.

    Constructed once per workflow execution.  Wrappers are built lazily on
    first attribute access.  Attribute writes are blocked — the proxy is
    immutable after construction.
    """

    def __init__(self, runtime: WorkflowRuntime, registry: CapabilityRegistry) -> None:
        object.__setattr__(self, "_runtime", runtime)
        object.__setattr__(self, "_registry", registry)
        # No eager wrapper building — wrappers resolve lazily via __getattr__.

    def __getattr__(self, name: str) -> Any:
        """
        Lazily resolve a flat-namespace capability ID to a callable wrapper.

        Called only when normal attribute lookup fails (i.e., name is not in
        __dict__ or the class).  Rejects dunder names and names starting with
        '_' so that introspection tools do not trigger spurious DB lookups.
        """
        if name.startswith("_"):
            raise AttributeError(
                f"CapabilityRegistryProxy has no attribute {name!r}"
            )
        registry = object.__getattribute__(self, "_registry")
        try:
            defn = registry.get(name)
        except KeyError:
            raise AttributeError(
                f"No capability with id {name!r} registered in the capability registry"
            ) from None
        return _make_capability_wrapper(
            object.__getattribute__(self, "_runtime"),
            defn.capability_id,
            defn.contract.inputs,
            defn.contract.output,
        )

    def __getitem__(self, capability_id: str) -> Callable[..., Any]:
        """Return a callable wrapper for any registered capability, including dotted IDs."""
        registry = object.__getattribute__(self, "_registry")
        try:
            defn = registry.get(capability_id)
        except KeyError:
            raise KeyError(f"Capability not found in registry: {capability_id!r}") from None
        return _make_capability_wrapper(
            object.__getattribute__(self, "_runtime"),
            defn.capability_id,
            defn.contract.inputs,
            defn.contract.output,
        )

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("CapabilityRegistryProxy is read-only after construction.")
