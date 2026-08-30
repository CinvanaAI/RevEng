"""
FastAPI application factory.

Startup sequence:
  1. Resolve DB path (env REVENG_DB or default ./reveng_platform.db)
  2. init_db() + apply_migrations()
  3. seed_providers_from_env()
  4. Instantiate services, store in app.state
  5. Create module-level ThreadPoolExecutor for background analysis jobs

Do NOT use FastAPI BackgroundTasks for analysis runs — it is request-lifecycle
bound.  The module-level ThreadPoolExecutor is the right concurrency primitive:
long-running jobs survive beyond the HTTP response.
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from reveng.framework.env import load_env_file
from reveng.execution_environment.agent_environment import (
    AgentEnvironmentAppearanceService,
    AgentEnvironmentService,
)
from reveng.execution_environment.capability_environment import CapabilityEnvironmentService
from reveng.platform.services.agent_keycard_service import AgentKeycardService
from reveng.platform.services.agent_service import AgentService
from reveng.platform.services.agent_capability_access_service import (
    AgentCapabilityAccessService,
)
from reveng.platform.services.agent_tool_assignment_service import (
    AgentCapabilityAssignmentService,
)
from reveng.platform.services.agent_tool_file_permission_service import (
    AgentToolFilePermissionService,
)
from reveng.platform.services.agent_workflow_service import AgentWorkflowService
from reveng.platform.services.capability_catalog_service import CapabilityCatalogService
from reveng.platform.services.capability_surface_policy_service import CapabilitySurfacePolicyService
from reveng.platform.services.draft_service import CapabilityDraftService
from reveng.platform.services.event_service import EventService
from reveng.platform.services.filesystem_explorer_service import FilesystemExplorerService
from reveng.platform.services.output_service import OutputService
from reveng.platform.services.provider_service import ProviderService
from reveng.platform.services.run_service import RunService
from reveng.platform.services.shared_capability_registry import SharedCapabilityRegistry
from reveng.platform.services.capability_package_service import CapabilityPackageService
from reveng.platform.web.security import LocalRequestGuardMiddleware
from reveng.storage.system_db import ensure_system_db_ready

_STATIC_DIR = Path(__file__).parent / "ui" / "static"


def _resolve_capability_environment_asset_dir() -> Path:
    """Return the capability environment assets directory.

    Checks REVENG_CAPABILITY_ENV_ASSET_DIR first (set by the desktop launcher
    and in packaged builds to avoid fragile parents[] traversal).  Falls back
    to the source-tree location relative to this file.
    """
    env_val = os.environ.get("REVENG_CAPABILITY_ENV_ASSET_DIR", "")
    if env_val:
        return Path(env_val).expanduser().resolve()
    return (
        Path(__file__).resolve().parents[2]
        / "execution_environment"
        / "capability_environment"
        / "assets"
    )


def _resolve_db_path() -> Path:
    """Resolve the database file path.

    Priority:
    1. REVENG_DB env var (explicit override, always honoured)
    2. REVENG_LAUNCHER_ROOT / reveng_platform.db (set by desktop launcher)
    3. cwd() / reveng_platform.db (dev/CLI fallback)
    """
    if env_val := os.environ.get("REVENG_DB", ""):
        return Path(env_val).expanduser().resolve()
    if root := os.environ.get("REVENG_LAUNCHER_ROOT", ""):
        return Path(root) / "reveng_platform.db"
    return Path.cwd() / "reveng_platform.db"


def _resolve_env_file() -> Path:
    """Return the .env file path.

    Priority:
    1. REVENG_ENV_FILE env var (set by desktop launcher)
    2. REVENG_LAUNCHER_ROOT / .env (set by desktop launcher)
    3. cwd() / .env (dev/CLI fallback)
    """
    if env_val := os.environ.get("REVENG_ENV_FILE", ""):
        return Path(env_val).expanduser().resolve()
    if root := os.environ.get("REVENG_LAUNCHER_ROOT", ""):
        candidate = Path(root) / ".env"
        if candidate.exists():
            return candidate
    return Path.cwd() / ".env"


def _resolve_agent_environment_asset_dir() -> Path:
    return _resolve_db_path().parent / "agent_environment_assets"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ------------------------------------------------------------------ startup
    ensure_system_db_ready(_resolve_db_path())

    # Seed providers from env
    env_values = load_env_file(_resolve_env_file())
    provider_svc = ProviderService()
    provider_svc.seed_from_env(env_values)
    capability_catalog_svc = CapabilityCatalogService()
    capability_catalog_svc.sync_builtin_catalog()

    # Process-level shared lazy registry — created once, shared across all runs.
    # Capabilities are resolved from DB on first access and cached in-process.
    shared_capability_registry = SharedCapabilityRegistry(capability_catalog_svc)

    # Store services in app.state so routers and pages can access them
    app.state.agent_service = AgentService()
    app.state.agent_workflow_service = AgentWorkflowService()
    app.state.agent_tool_file_permission_service = AgentToolFilePermissionService(
        agent_service=app.state.agent_service,
    )
    app.state.agent_keycard_service = AgentKeycardService(
        agent_service=app.state.agent_service,
        tool_file_permission_service=app.state.agent_tool_file_permission_service,
    )
    app.state.agent_capability_assignment_service = AgentCapabilityAssignmentService(
        agent_service=app.state.agent_service,
        tool_file_permission_service=app.state.agent_tool_file_permission_service,
    )
    app.state.agent_capability_access_service = AgentCapabilityAccessService(
        agent_service=app.state.agent_service,
        assignment_service=app.state.agent_capability_assignment_service,
        keycard_service=app.state.agent_keycard_service,
        tool_file_permission_service=app.state.agent_tool_file_permission_service,
        capability_catalog=capability_catalog_svc,
    )
    app.state.filesystem_explorer_service = FilesystemExplorerService()
    app.state.agent_environment_appearance_service = AgentEnvironmentAppearanceService(
        agent_service=app.state.agent_service,
        asset_root=_resolve_agent_environment_asset_dir(),
    )
    app.state.run_service = RunService()
    app.state.event_service = EventService()
    app.state.output_service = OutputService()
    app.state.provider_service = provider_svc
    app.state.capability_catalog_service = capability_catalog_svc
    app.state.capability_package_service = CapabilityPackageService(catalog=capability_catalog_svc)
    app.state.shared_capability_registry = shared_capability_registry
    app.state.capability_draft_service = CapabilityDraftService(
        capability_catalog=capability_catalog_svc,
    )
    app.state.capability_surface_policy_service = CapabilitySurfacePolicyService()
    app.state.capability_environment_service = CapabilityEnvironmentService(
        draft_authority=app.state.capability_draft_service,
        capability_catalog=capability_catalog_svc,
    )
    app.state.agent_environment_service = AgentEnvironmentService(
        agent_service=app.state.agent_service,
        agent_capability_access=app.state.agent_capability_access_service,
        agent_keycard_service=app.state.agent_keycard_service,
        tool_file_permission_service=app.state.agent_tool_file_permission_service,
        agent_workflow_service=app.state.agent_workflow_service,
        filesystem_explorer_service=app.state.filesystem_explorer_service,
        appearance_service=app.state.agent_environment_appearance_service,
        provider_service=provider_svc,
        run_service=app.state.run_service,
    )

    # Background thread pool for analysis runs
    app.state.executor = ThreadPoolExecutor(
        max_workers=4,
        thread_name_prefix="reveng-analysis",
    )

    yield

    # ------------------------------------------------------------------ shutdown
    # Don't wait for running analyses — they own their DB connections
    app.state.executor.shutdown(wait=False)


def create_app() -> FastAPI:
    agent_environment_asset_dir = _resolve_agent_environment_asset_dir()
    agent_environment_asset_dir.mkdir(parents=True, exist_ok=True)

    app = FastAPI(
        title="RevEng Control Center",
        description="Agent platform and analysis runner for RevEng",
        version="0.2.0",
        lifespan=lifespan,
    )
    app.add_middleware(LocalRequestGuardMiddleware)

    # Static files (CSS, vendored JS)
    if _STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")
    _cap_env_asset_dir = _resolve_capability_environment_asset_dir()
    if _cap_env_asset_dir.exists():
        app.mount(
            "/environment-assets",
            StaticFiles(directory=str(_cap_env_asset_dir)),
            name="environment-assets",
        )
    app.mount(
        "/agent-environment-assets",
        StaticFiles(directory=str(agent_environment_asset_dir)),
        name="agent-environment-assets",
    )

    # One authoritative public UI: the server-rendered control center.
    @app.get("/", include_in_schema=False)
    def host_shell():
        return RedirectResponse(url="/capabilities")

    # API routers
    from reveng.platform.web.routers.agents import router as agents_router
    from reveng.platform.web.routers.capabilities import router as capabilities_router
    from reveng.platform.web.routers.runs import router as runs_router
    from reveng.platform.web.routers.providers import router as providers_router
    from reveng.platform.web.routers.capability_environment import router as cap_env_router

    app.include_router(agents_router, prefix="/api/agents", tags=["agents"])
    app.include_router(capabilities_router, prefix="/api/capabilities", tags=["capabilities"])
    app.include_router(runs_router, prefix="/api/runs", tags=["runs"])
    app.include_router(providers_router, prefix="/api/providers", tags=["providers"])
    app.include_router(
        cap_env_router,
        prefix="/api/capability-environment",
        tags=["capability-environment"],
    )

    # UI page routes
    from reveng.platform.web.ui.pages import router as ui_router
    app.include_router(ui_router, tags=["ui"])

    return app
