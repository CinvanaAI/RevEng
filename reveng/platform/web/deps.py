"""FastAPI dependency injectors."""
from __future__ import annotations

from fastapi import Request

from reveng.execution_environment.agent_environment import (
    AgentEnvironmentAppearanceService,
    AgentEnvironmentService,
)
from reveng.execution_environment.capability_environment import CapabilityEnvironmentService
from reveng.platform.services.agent_keycard_service import AgentKeycardService
from reveng.platform.services.agent_service import AgentService
from reveng.platform.services.agent_workflow_service import AgentWorkflowService
from reveng.platform.services.agent_capability_access_service import (
    AgentCapabilityAccessService,
)
from reveng.platform.services.agent_tool_assignment_service import (
    AgentCapabilityAssignmentService,
)
from reveng.platform.services.agent_tool_file_permission_service import (
    AgentToolFilePermissionService,
)
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


def get_agent_service(request: Request) -> AgentService:
    return request.app.state.agent_service


def get_agent_workflow_service(request: Request) -> AgentWorkflowService:
    return request.app.state.agent_workflow_service


def get_agent_keycard_service(request: Request) -> AgentKeycardService:
    return request.app.state.agent_keycard_service


def get_agent_tool_file_permission_service(request: Request) -> AgentToolFilePermissionService:
    return request.app.state.agent_tool_file_permission_service


def get_agent_capability_access_service(request: Request) -> AgentCapabilityAccessService:
    return request.app.state.agent_capability_access_service


def get_agent_capability_assignment_service(request: Request) -> AgentCapabilityAssignmentService:
    return request.app.state.agent_capability_assignment_service


def get_agent_environment_service(request: Request) -> AgentEnvironmentService:
    return request.app.state.agent_environment_service


def get_agent_environment_appearance_service(request: Request) -> AgentEnvironmentAppearanceService:
    return request.app.state.agent_environment_appearance_service


def get_filesystem_explorer_service(request: Request) -> FilesystemExplorerService:
    return request.app.state.filesystem_explorer_service


def get_run_service(request: Request) -> RunService:
    return request.app.state.run_service


def get_event_service(request: Request) -> EventService:
    return request.app.state.event_service


def get_output_service(request: Request) -> OutputService:
    return request.app.state.output_service


def get_provider_service(request: Request) -> ProviderService:
    return request.app.state.provider_service


def get_capability_draft_service(request: Request) -> CapabilityDraftService:
    return request.app.state.capability_draft_service


def get_capability_catalog_service(request: Request) -> CapabilityCatalogService:
    return request.app.state.capability_catalog_service


def get_capability_environment_service(request: Request) -> CapabilityEnvironmentService:
    return request.app.state.capability_environment_service


def get_executor(request: Request):
    return request.app.state.executor


def get_shared_capability_registry(request: Request) -> SharedCapabilityRegistry:
    return request.app.state.shared_capability_registry


def get_capability_package_service(request: Request) -> CapabilityPackageService:
    return request.app.state.capability_package_service


def get_capability_surface_policy_service(request: Request) -> CapabilitySurfacePolicyService:
    return request.app.state.capability_surface_policy_service
