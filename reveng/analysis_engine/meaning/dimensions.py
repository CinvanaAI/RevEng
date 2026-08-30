from __future__ import annotations

from enum import Enum


class DimensionID(str, Enum):
    COMMUNICATION = "communication"
    PERSISTENCE = "persistence"
    ROUTING = "routing"
    INPUT_HANDLING = "input_handling"
    OUTPUT_GENERATION = "output_generation"
    SCHEDULING = "scheduling"
    STATE_MANAGEMENT = "state_management"
    ERROR_HANDLING = "error_handling"
    INTEGRATION = "integration"
    CONFIGURATION = "configuration"
    TRANSFORMATION = "transformation"
    SECURITY = "security"


DIMENSION_LABELS: dict[DimensionID, str] = {
    DimensionID.COMMUNICATION: "Communication",
    DimensionID.PERSISTENCE: "Persistence",
    DimensionID.ROUTING: "Routing / Dispatch",
    DimensionID.INPUT_HANDLING: "Input Handling",
    DimensionID.OUTPUT_GENERATION: "Output Generation",
    DimensionID.SCHEDULING: "Scheduling / Background",
    DimensionID.STATE_MANAGEMENT: "State Management",
    DimensionID.ERROR_HANDLING: "Error Handling / Recovery",
    DimensionID.INTEGRATION: "External Integration",
    DimensionID.CONFIGURATION: "Configuration",
    DimensionID.TRANSFORMATION: "Data Transformation",
    DimensionID.SECURITY: "Security / Cryptography",
}
