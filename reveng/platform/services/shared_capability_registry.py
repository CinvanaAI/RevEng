"""
Process-level shared lazy capability registry.

Replaces the per-run full table scan in build_default_host().  A single
instance lives on app.state for the lifetime of the process and is shared
across all concurrent workflow runs.

Thread safety
-------------
The resolved-definition cache uses a threading.Lock on writes.  CPython dict
reads are safe under the GIL, but the Lock is held for the entire get() call
to prevent concurrent threads from triggering duplicate DB resolution for the
same capability_id.

Invalidation
-------------
Call invalidate(capability_id) after any single capability is updated.
Call invalidate_all() after a bulk operation such as seed_builtin_catalog() /
sync_builtin_catalog() or install_published_draft_items().

The caller (web route handler or service) is responsible for calling
invalidation — this registry does not subscribe to catalog changes.
"""
from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

from reveng.platform.capabilities import CapabilityDefinition, CapabilityRegistry

if TYPE_CHECKING:
    from reveng.platform.services.capability_catalog_service import CapabilityCatalogService


class SharedCapabilityRegistry(CapabilityRegistry):
    """
    Process-level lazy registry that subclasses CapabilityRegistry so that
    WorkflowRuntime and RevEngHost accept it without type changes.

    The parent class's _definitions dict is deliberately unused; all resolution
    goes through the per-capability DB lookup + shared cache.
    """

    def __init__(self, catalog_service: "CapabilityCatalogService") -> None:
        # Skip parent __init__ entirely to avoid building an empty _definitions
        # and emitting any framework log.  We manually set the fields we need.
        object.__setattr__(self, "_definitions", {})  # satisfies any isinstance checks
        object.__setattr__(self, "_framework_log_sink", None)
        object.__setattr__(self, "_run_id", None)
        object.__setattr__(self, "_workflow_id", None)
        object.__setattr__(self, "_trigger", None)
        object.__setattr__(self, "_catalog_svc", catalog_service)
        object.__setattr__(self, "_resolved", {})
        object.__setattr__(self, "_lock", threading.Lock())

    # ------------------------------------------------------------------
    # Core interface (overrides CapabilityRegistry)
    # ------------------------------------------------------------------

    def get(self, capability_id: str) -> CapabilityDefinition:
        """
        Return the definition for capability_id.  Resolves from DB on first
        access; subsequent accesses are served from the in-process cache.
        """
        lock: threading.Lock = object.__getattribute__(self, "_lock")
        resolved: dict = object.__getattribute__(self, "_resolved")
        with lock:
            if capability_id not in resolved:
                catalog: "CapabilityCatalogService" = object.__getattribute__(self, "_catalog_svc")
                record = catalog.get_installed_record(capability_id)
                if record is None:
                    raise KeyError(f"Unknown capability: {capability_id}")
                defn = record.to_definition(resolve_binding_ref=catalog.resolve_binding_ref)
                resolved[capability_id] = defn
            return resolved[capability_id]

    def list_ids(self) -> list[str]:
        """Return all installed capability IDs (lightweight DB query, no binding resolution)."""
        catalog: "CapabilityCatalogService" = object.__getattribute__(self, "_catalog_svc")
        return catalog.list_installed_capability_ids()

    def snapshot(self) -> list[CapabilityDefinition]:
        """
        Return all installed definitions sorted by capability_id.

        Triggers lazy resolution of any not-yet-cached definition.
        Prefer list_ids() when only IDs are needed.
        """
        return [self.get(cap_id) for cap_id in self.list_ids()]

    def register(self, definition: CapabilityDefinition) -> None:
        """
        Allow pre-population of the cache (e.g., from workflow pack registration
        or direct registration by callers that build a CapabilityDefinition in-process).

        Unlike the parent class, this does not reject duplicates — it simply
        overwrites the cache entry.
        """
        lock: threading.Lock = object.__getattribute__(self, "_lock")
        resolved: dict = object.__getattribute__(self, "_resolved")
        with lock:
            resolved[definition.capability_id] = definition

    # ------------------------------------------------------------------
    # Invalidation
    # ------------------------------------------------------------------

    def invalidate(self, capability_id: str) -> None:
        """
        Evict a single capability from the cache so it is re-resolved on next access.

        Also evicts the package-owned published Python artifact from sys.modules
        so that a capability with execution_source='generated_file' picks up any
        newly written module on the next resolution.
        """
        lock: threading.Lock = object.__getattribute__(self, "_lock")
        resolved: dict = object.__getattribute__(self, "_resolved")
        with lock:
            resolved.pop(capability_id, None)
        # Evict published Python artifact import cache so that a capability with
        # execution_source='generated_file' picks up any newly written module on
        # the next resolution.
        try:
            from reveng.platform.capability_published_artifacts import invalidate_published_python_cache
            invalidate_published_python_cache(capability_id)
        except Exception:
            pass

    def invalidate_all(self) -> None:
        """Evict all cached definitions (e.g., after seed_builtin_catalog / sync_builtin_catalog)."""
        lock: threading.Lock = object.__getattribute__(self, "_lock")
        resolved: dict = object.__getattribute__(self, "_resolved")
        with lock:
            resolved.clear()

    def cache_size(self) -> int:
        """Return the number of currently cached definitions (diagnostic use only)."""
        resolved: dict = object.__getattribute__(self, "_resolved")
        return len(resolved)


__all__ = ["SharedCapabilityRegistry"]
