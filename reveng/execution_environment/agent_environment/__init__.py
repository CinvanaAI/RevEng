"""Agent Environment application service and station registry."""

from .appearance import (
    DEFAULT_AGENT_ENVIRONMENT_SKIN_ID,
    AGENT_ENVIRONMENT_THEME_BY_ID,
    AGENT_ENVIRONMENT_THEME_DEFINITIONS,
    AgentEnvironmentAppearanceService,
    AgentEnvironmentThemeDefinition,
)
from .service import AgentEnvironmentService
from .stations import (
    AGENT_ENVIRONMENT_OBJECT,
    AGENT_ENVIRONMENT_STATIONS,
    AGENT_ENVIRONMENT_STATION_BY_ACTION,
    build_agent_environment_agent_href,
    build_agent_environment_entry_href,
)

__all__ = [
    "DEFAULT_AGENT_ENVIRONMENT_SKIN_ID",
    "AGENT_ENVIRONMENT_THEME_BY_ID",
    "AGENT_ENVIRONMENT_THEME_DEFINITIONS",
    "AgentEnvironmentAppearanceService",
    "AgentEnvironmentThemeDefinition",
    "AgentEnvironmentService",
    "AGENT_ENVIRONMENT_OBJECT",
    "AGENT_ENVIRONMENT_STATIONS",
    "AGENT_ENVIRONMENT_STATION_BY_ACTION",
    "build_agent_environment_agent_href",
    "build_agent_environment_entry_href",
]
