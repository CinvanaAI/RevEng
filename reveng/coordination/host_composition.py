"""Coordination-owned host composition for analysis workflows."""

from __future__ import annotations

from typing import Any

from reveng.framework.cache import ExistsAndNonEmptyCachePolicy
from reveng.framework.host import RevEngHost
from reveng.framework.logging import FrameworkLogSink, emit_framework_log
from reveng.platform.capabilities import CapabilityRegistry
from reveng.platform.services.capability_catalog_service import CapabilityCatalogService
from reveng.storage.system_db import ensure_system_db_ready
from reveng.analysis_engine.workflows import layered_breakdown, repo_analysis


def build_default_host(
    provider: Any | None = None,
    *,
    capability_registry: CapabilityRegistry | None = None,
    framework_log_sink: FrameworkLogSink | None = None,
    bootstrap_trigger: str | None = None,
    bootstrap_metadata: dict[str, Any] | None = None,
    run_id: str | None = None,
    workflow_id: str | None = None,
) -> RevEngHost:
    """
    Build the default RevEngHost.

    capability_registry
        Optional pre-built registry to use in place of the per-run eager hydration.
        Pass app.state.shared_capability_registry from the web layer for the lazy
        process-level registry path.  When None the legacy full-hydration path runs
        (used by the CLI and tests).
    """
    ensure_system_db_ready()
    emit_framework_log(
        framework_log_sink,
        origin="coordination.host_composition",
        stage="bootstrap",
        event_type="default_host_build_started",
        level="info",
        status="started",
        run_id=run_id,
        workflow_id=workflow_id,
        trigger=bootstrap_trigger or "build_default_host",
        message="Coordination started composing the default host across Storage, Capability Platform, and Framework.",
        details={
            "provider_configured": provider is not None,
            "bootstrap_metadata": bootstrap_metadata or {},
            "shared_registry": capability_registry is not None,
        },
    )
    host = RevEngHost(
        capability_registry=capability_registry,
        cache_policy=ExistsAndNonEmptyCachePolicy(),
        provider=provider,
        framework_log_sink=framework_log_sink,
        run_id=run_id,
        workflow_id=workflow_id,
        bootstrap_trigger=bootstrap_trigger,
    )
    capability_catalog = CapabilityCatalogService()
    _register_family(
        framework_log_sink,
        family_name="reveng.platform.capability_catalog",
        family_kind="capability_catalog",
        trigger=bootstrap_trigger,
        run_id=run_id,
        workflow_id=workflow_id,
        register_fn=capability_catalog.ensure_builtin_catalog,
        registry_count_fn=capability_catalog.count_installed_capabilities,
    )
    if capability_registry is None:
        # Legacy path: eager full hydration into a fresh per-run CapabilityRegistry.
        # Used by the CLI (run.py) and anywhere no shared registry is wired.
        _register_family(
            framework_log_sink,
            family_name="reveng.platform.capability_registry_projection",
            family_kind="capability_projection",
            trigger=bootstrap_trigger,
            run_id=run_id,
            workflow_id=workflow_id,
            register_fn=lambda: capability_catalog.hydrate_registry(host.capabilities),
            registry_count_fn=lambda: len(host.capabilities.list_ids()),
        )
    # When capability_registry is provided it is already the shared process-level
    # registry — no hydration step is needed.  Definitions resolve lazily on
    # first access via SharedCapabilityRegistry.get().
    _register_family(
        framework_log_sink,
        family_name="reveng.workflows.repo_analysis",
        family_kind="workflow_pack",
        trigger=bootstrap_trigger,
        run_id=run_id,
        workflow_id=workflow_id,
        register_fn=lambda: repo_analysis.register(host.workflows),
        registry_count_fn=lambda: len(host.workflows.list_ids()),
    )
    _register_family(
        framework_log_sink,
        family_name="reveng.workflows.layered_breakdown",
        family_kind="workflow_pack",
        trigger=bootstrap_trigger,
        run_id=run_id,
        workflow_id=workflow_id,
        register_fn=lambda: layered_breakdown.register(host.workflows),
        registry_count_fn=lambda: len(host.workflows.list_ids()),
    )
    emit_framework_log(
        framework_log_sink,
        origin="coordination.host_composition",
        stage="integrity",
        event_type="default_host_integrity_checked",
        level="info",
        status="completed",
        run_id=run_id,
        workflow_id=workflow_id,
        trigger=bootstrap_trigger or "build_default_host",
        message="Coordination completed bootstrap integrity checks for the default host.",
        details={
            "capability_count": len(host.capabilities.list_ids()),
            "workflow_count": len(host.workflows.list_ids()),
            "provider_configured": provider is not None,
            "shared_registry": capability_registry is not None,
        },
    )
    return host


def _register_family(
    sink: FrameworkLogSink | None,
    *,
    family_name: str,
    family_kind: str,
    trigger: str | None,
    run_id: str | None,
    workflow_id: str | None,
    register_fn,
    registry_count_fn,
) -> None:
    emit_framework_log(
        sink,
        origin="coordination.host_composition",
        stage="registration",
        event_type="registration_family_started",
        level="info",
        status="started",
        run_id=run_id,
        workflow_id=workflow_id,
        trigger=trigger or "build_default_host",
        message="Coordination started registering a family into the default host.",
        details={
            "family_name": family_name,
            "family_kind": family_kind,
        },
    )
    try:
        register_fn()
    except Exception as exc:
        emit_framework_log(
            sink,
            origin="coordination.host_composition",
            stage="registration",
            event_type="registration_family_failed",
            level="error",
            status="failed",
            run_id=run_id,
            workflow_id=workflow_id,
            trigger=trigger or "build_default_host",
            message="Coordination failed while registering a family into the default host.",
            details={
                "family_name": family_name,
                "family_kind": family_kind,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
        )
        raise
    emit_framework_log(
        sink,
        origin="coordination.host_composition",
        stage="registration",
        event_type="registration_family_completed",
        level="info",
        status="completed",
        run_id=run_id,
        workflow_id=workflow_id,
        trigger=trigger or "build_default_host",
        message="Coordination finished registering a family into the default host.",
        details={
            "family_name": family_name,
            "family_kind": family_kind,
            "registry_size": registry_count_fn(),
        },
    )


__all__ = ["build_default_host"]
