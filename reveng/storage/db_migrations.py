"""
Storage-owned ordered, idempotent schema migrations.

Call apply_migrations(conn) once at startup.  Each migration is applied exactly
once; the current version is tracked in the schema_versions table.
"""
from __future__ import annotations

import sqlite3

from reveng.storage.framework_log_schema import (
    CREATE_FRAMEWORK_LOGS,
    CREATE_FRAMEWORK_LOGS_INDICES,
)

# ---------------------------------------------------------------------------
# DDL strings
# ---------------------------------------------------------------------------

_CREATE_SCHEMA_VERSION = """
CREATE TABLE IF NOT EXISTS schema_versions (
    version    INTEGER PRIMARY KEY,
    applied_at TEXT    NOT NULL
)
"""

_CREATE_PROVIDERS = """
CREATE TABLE IF NOT EXISTS providers (
    id          TEXT PRIMARY KEY,
    kind        TEXT NOT NULL,
    label       TEXT NOT NULL,
    base_url    TEXT NOT NULL,
    api_key_env TEXT NOT NULL DEFAULT '',
    is_default  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
)
"""

_CREATE_AGENTS = """
CREATE TABLE IF NOT EXISTS agents (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    description   TEXT NOT NULL DEFAULT '',
    is_active     INTEGER NOT NULL DEFAULT 0,
    provider_id   TEXT NOT NULL REFERENCES providers(id),
    model         TEXT NOT NULL,
    system_prompt TEXT NOT NULL DEFAULT '',
    tool_bindings TEXT NOT NULL DEFAULT '[]',
    memory_config TEXT NOT NULL DEFAULT '{}',
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
)
"""

_CREATE_AGENTS_INDICES = """
CREATE INDEX IF NOT EXISTS idx_agents_is_active   ON agents(is_active);
CREATE INDEX IF NOT EXISTS idx_agents_provider_id ON agents(provider_id)
"""

_CREATE_ANALYSIS_RUNS = """
CREATE TABLE IF NOT EXISTS analysis_runs (
    id            TEXT PRIMARY KEY,
    status        TEXT NOT NULL,
    repo_path     TEXT NOT NULL,
    output_dir    TEXT NOT NULL,
    options       TEXT NOT NULL DEFAULT '{}',
    agent_id      TEXT REFERENCES agents(id),
    started_at    TEXT,
    finished_at   TEXT,
    error_message TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
)
"""

_CREATE_ANALYSIS_RUNS_INDICES = """
CREATE INDEX IF NOT EXISTS idx_analysis_runs_status     ON analysis_runs(status);
CREATE INDEX IF NOT EXISTS idx_analysis_runs_agent_id   ON analysis_runs(agent_id);
CREATE INDEX IF NOT EXISTS idx_analysis_runs_created_at ON analysis_runs(created_at DESC)
"""

_CREATE_AGENT_RUNS = """
CREATE TABLE IF NOT EXISTS agent_runs (
    id              TEXT PRIMARY KEY,
    agent_id        TEXT NOT NULL REFERENCES agents(id),
    analysis_run_id TEXT REFERENCES analysis_runs(id),
    status          TEXT NOT NULL,
    input_payload   TEXT NOT NULL DEFAULT '{}',
    output_payload  TEXT NOT NULL DEFAULT '{}',
    error_message   TEXT,
    started_at      TEXT,
    finished_at     TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
)
"""

_CREATE_AGENT_RUNS_INDICES = """
CREATE INDEX IF NOT EXISTS idx_agent_runs_agent_id        ON agent_runs(agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_runs_analysis_run_id ON agent_runs(analysis_run_id);
CREATE INDEX IF NOT EXISTS idx_agent_runs_status          ON agent_runs(status)
"""

_CREATE_RUN_OUTPUTS = """
CREATE TABLE IF NOT EXISTS run_outputs (
    id          TEXT PRIMARY KEY,
    run_id      TEXT NOT NULL,
    output_key  TEXT NOT NULL,
    output_type TEXT NOT NULL,
    value       TEXT NOT NULL,
    metadata    TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL
)
"""

_CREATE_RUN_OUTPUTS_INDICES = """
CREATE INDEX IF NOT EXISTS idx_run_outputs_run_id     ON run_outputs(run_id);
CREATE INDEX IF NOT EXISTS idx_run_outputs_output_key ON run_outputs(output_key)
"""

_CREATE_RUN_EVENTS = """
CREATE TABLE IF NOT EXISTS run_events (
    id         TEXT PRIMARY KEY,
    run_id     TEXT NOT NULL,
    run_type   TEXT NOT NULL DEFAULT 'analysis',
    event_type TEXT NOT NULL,
    payload    TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
)
"""

_CREATE_RUN_EVENTS_INDICES = """
CREATE INDEX IF NOT EXISTS idx_run_events_run_id            ON run_events(run_id);
CREATE INDEX IF NOT EXISTS idx_run_events_run_id_created_at ON run_events(run_id, created_at);
CREATE INDEX IF NOT EXISTS idx_run_events_event_type        ON run_events(event_type)
"""

_CREATE_AGENT_SECTIONS = """
CREATE TABLE IF NOT EXISTS agent_sections (
    agent_id   TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    section    TEXT NOT NULL,
    data       TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (agent_id, section)
)
"""

_CREATE_AGENT_SECTIONS_INDEX = """
CREATE INDEX IF NOT EXISTS idx_agent_sections_agent_id ON agent_sections(agent_id)
"""

_CREATE_CAPABILITY_BUNDLES = """
CREATE TABLE IF NOT EXISTS capability_bundles (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    lifecycle_state TEXT NOT NULL DEFAULT 'draft',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
)
"""

_CREATE_CAPABILITY_BUNDLES_INDEX = """
CREATE INDEX IF NOT EXISTS idx_capability_bundles_lifecycle_state
    ON capability_bundles(lifecycle_state)
"""

_CREATE_CAPABILITY_DRAFT_ITEMS = """
CREATE TABLE IF NOT EXISTS capability_draft_items (
    id                    TEXT PRIMARY KEY,
    bundle_id             TEXT NOT NULL REFERENCES capability_bundles(id) ON DELETE CASCADE,
    planned_capability_id TEXT NOT NULL,
    draft_data            TEXT NOT NULL DEFAULT '{}',
    item_state            TEXT NOT NULL DEFAULT 'draft',
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL
)
"""

_CREATE_CAPABILITY_DRAFT_ITEMS_INDEX = """
CREATE INDEX IF NOT EXISTS idx_capability_draft_items_bundle_id
    ON capability_draft_items(bundle_id)
"""

_ADD_BUNDLE_VERSION = """
ALTER TABLE capability_bundles ADD COLUMN version TEXT NOT NULL DEFAULT '1.0.0'
"""

_CREATE_BUNDLE_PUBLISH_HISTORY = """
CREATE TABLE IF NOT EXISTS bundle_publish_history (
    id           TEXT PRIMARY KEY,
    bundle_id    TEXT NOT NULL REFERENCES capability_bundles(id) ON DELETE CASCADE,
    version      TEXT NOT NULL,
    published_at TEXT NOT NULL,
    item_count   INTEGER NOT NULL DEFAULT 0
)
"""

_CREATE_BUNDLE_PUBLISH_HISTORY_INDEX = """
CREATE INDEX IF NOT EXISTS idx_bundle_publish_history_bundle_id
    ON bundle_publish_history(bundle_id)
"""

_RENAME_CAPABILITY_ENVIRONMENT_TABLES_TO_DRAFTS = """
ALTER TABLE capability_bundles RENAME TO capability_drafts;
DROP INDEX IF EXISTS idx_capability_bundles_lifecycle_state;
CREATE INDEX IF NOT EXISTS idx_capability_drafts_lifecycle_state
    ON capability_drafts(lifecycle_state);

ALTER TABLE capability_draft_items RENAME COLUMN bundle_id TO draft_id;
DROP INDEX IF EXISTS idx_capability_draft_items_bundle_id;
CREATE INDEX IF NOT EXISTS idx_capability_draft_items_draft_id
    ON capability_draft_items(draft_id);

ALTER TABLE bundle_publish_history RENAME TO capability_draft_publication_history;
ALTER TABLE capability_draft_publication_history RENAME COLUMN bundle_id TO draft_id;
DROP INDEX IF EXISTS idx_bundle_publish_history_bundle_id;
CREATE INDEX IF NOT EXISTS idx_capability_draft_publication_history_draft_id
    ON capability_draft_publication_history(draft_id)
"""

_CREATE_CAPABILITY_DRAFT_REVISIONS = """
CREATE TABLE IF NOT EXISTS capability_draft_revisions (
    id            TEXT PRIMARY KEY,
    draft_id      TEXT NOT NULL REFERENCES capability_drafts(id) ON DELETE CASCADE,
    version       TEXT NOT NULL,
    name          TEXT NOT NULL,
    description   TEXT NOT NULL DEFAULT '',
    saved_at      TEXT NOT NULL,
    item_count    INTEGER NOT NULL DEFAULT 0,
    snapshot_data TEXT NOT NULL DEFAULT '{}'
)
"""

_CREATE_CAPABILITY_DRAFT_REVISIONS_INDEX = """
CREATE INDEX IF NOT EXISTS idx_capability_draft_revisions_draft_id
    ON capability_draft_revisions(draft_id)
"""

_CREATE_CAPABILITY_RECORDS = """
CREATE TABLE IF NOT EXISTS capability_records (
    capability_id              TEXT PRIMARY KEY,
    pack_id                    TEXT NOT NULL,
    version                    TEXT NOT NULL,
    display_name               TEXT NOT NULL,
    description                TEXT NOT NULL DEFAULT '',
    lifecycle_state            TEXT NOT NULL DEFAULT 'installed',
    capability_type            TEXT NOT NULL,
    contract_json              TEXT NOT NULL DEFAULT '{}',
    tags_json                  TEXT NOT NULL DEFAULT '[]',
    icon                       TEXT,
    implementation_ref         TEXT,
    combination_logic_ref      TEXT,
    component_capabilities_json TEXT NOT NULL DEFAULT '[]',
    execution_order_json       TEXT NOT NULL DEFAULT '[]',
    source_kind                TEXT NOT NULL DEFAULT 'builtin_pack',
    source_ref                 TEXT NOT NULL DEFAULT '',
    created_at                 TEXT NOT NULL,
    updated_at                 TEXT NOT NULL
)
"""

_CREATE_CAPABILITY_RECORDS_INDEX = """
CREATE INDEX IF NOT EXISTS idx_capability_records_lifecycle_state
    ON capability_records(lifecycle_state);
CREATE INDEX IF NOT EXISTS idx_capability_records_pack_id
    ON capability_records(pack_id);
CREATE INDEX IF NOT EXISTS idx_capability_records_source_kind
    ON capability_records(source_kind)
"""

_CREATE_CAPABILITY_PACKAGE_OBJECTS = """
CREATE TABLE IF NOT EXISTS capability_package_objects (
    id            TEXT PRIMARY KEY,
    capability_id TEXT NOT NULL,
    version       TEXT NOT NULL,
    package_kind  TEXT NOT NULL DEFAULT 'capability_snapshot',
    source_kind   TEXT NOT NULL DEFAULT '',
    source_ref    TEXT NOT NULL DEFAULT '',
    snapshot_json TEXT NOT NULL DEFAULT '{}',
    created_at    TEXT NOT NULL
)
"""

_CREATE_CAPABILITY_PACKAGE_OBJECTS_INDEX = """
CREATE INDEX IF NOT EXISTS idx_capability_package_objects_capability_id
    ON capability_package_objects(capability_id);
CREATE INDEX IF NOT EXISTS idx_capability_package_objects_created_at
    ON capability_package_objects(created_at DESC)
"""

_ADD_CAPABILITY_RECORD_PACKAGE_OBJECT_ID = """
ALTER TABLE capability_records ADD COLUMN package_object_id TEXT
"""

_CREATE_CAPABILITY_RECORD_EVENTS = """
CREATE TABLE IF NOT EXISTS capability_record_events (
    id            TEXT PRIMARY KEY,
    capability_id TEXT NOT NULL REFERENCES capability_records(capability_id) ON DELETE CASCADE,
    event_type    TEXT NOT NULL,
    source_kind   TEXT NOT NULL DEFAULT '',
    source_ref    TEXT NOT NULL DEFAULT '',
    snapshot_json TEXT NOT NULL DEFAULT '{}',
    created_at    TEXT NOT NULL
)
"""

_CREATE_CAPABILITY_RECORD_EVENTS_INDEX = """
CREATE INDEX IF NOT EXISTS idx_capability_record_events_capability_id
    ON capability_record_events(capability_id);
CREATE INDEX IF NOT EXISTS idx_capability_record_events_created_at
    ON capability_record_events(created_at DESC)
"""

_CREATE_CAPABILITY_PUBLICATION_CANDIDATES = """
CREATE TABLE IF NOT EXISTS capability_publication_candidates (
    id                     TEXT PRIMARY KEY,
    history_id             TEXT NOT NULL REFERENCES capability_draft_publication_history(id) ON DELETE CASCADE,
    draft_id               TEXT NOT NULL REFERENCES capability_drafts(id) ON DELETE CASCADE,
    draft_item_id          TEXT NOT NULL REFERENCES capability_draft_items(id) ON DELETE CASCADE,
    capability_id          TEXT NOT NULL,
    version                TEXT NOT NULL,
    publication_state      TEXT NOT NULL DEFAULT 'candidate',
    executable_ready       INTEGER NOT NULL DEFAULT 0,
    implementation_ref     TEXT,
    combination_logic_ref  TEXT,
    snapshot_json          TEXT NOT NULL DEFAULT '{}',
    created_at             TEXT NOT NULL
)
"""

_CREATE_CAPABILITY_PUBLICATION_CANDIDATES_INDEX = """
CREATE INDEX IF NOT EXISTS idx_capability_publication_candidates_draft_id
    ON capability_publication_candidates(draft_id);
CREATE INDEX IF NOT EXISTS idx_capability_publication_candidates_capability_id
    ON capability_publication_candidates(capability_id);
CREATE INDEX IF NOT EXISTS idx_capability_publication_candidates_history_id
    ON capability_publication_candidates(history_id)
"""

_CREATE_CAPABILITY_ENVIRONMENT_SETTINGS = """
CREATE TABLE IF NOT EXISTS capability_environment_settings (
    settings_id      TEXT PRIMARY KEY,
    enable_skins     INTEGER NOT NULL DEFAULT 0,
    selected_skin_id TEXT NOT NULL DEFAULT 'random',
    updated_at       TEXT NOT NULL
)
"""

_CREATE_AGENT_CAPABILITY_ASSIGNMENTS = """
CREATE TABLE IF NOT EXISTS agent_capability_assignments (
    id               TEXT PRIMARY KEY,
    agent_id         TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    capability_id    TEXT NOT NULL,
    assignment_state TEXT NOT NULL DEFAULT 'granted',
    assigned_at      TEXT NOT NULL,
    revoked_at       TEXT,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    UNIQUE(agent_id, capability_id)
)
"""

_CREATE_AGENT_CAPABILITY_ASSIGNMENTS_INDEX = """
CREATE INDEX IF NOT EXISTS idx_agent_capability_assignments_agent_id
    ON agent_capability_assignments(agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_capability_assignments_capability_id
    ON agent_capability_assignments(capability_id);
CREATE INDEX IF NOT EXISTS idx_agent_capability_assignments_state
  ON agent_capability_assignments(assignment_state)
"""

_CREATE_AGENT_FILE_ASSIGNMENTS = """
CREATE TABLE IF NOT EXISTS agent_file_assignments (
    id                  TEXT PRIMARY KEY,
    agent_id            TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    absolute_path       TEXT NOT NULL,
    root_path           TEXT NOT NULL,
    relative_path       TEXT NOT NULL,
    visibility_state    TEXT NOT NULL DEFAULT 'granted',
    global_tool_eligible INTEGER NOT NULL DEFAULT 0,
    assigned_at         TEXT NOT NULL,
    revoked_at          TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    UNIQUE(agent_id, absolute_path)
)
"""

_CREATE_AGENT_FILE_ASSIGNMENTS_INDEX = """
CREATE INDEX IF NOT EXISTS idx_agent_file_assignments_agent_id
    ON agent_file_assignments(agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_file_assignments_visibility_state
    ON agent_file_assignments(visibility_state);
CREATE INDEX IF NOT EXISTS idx_agent_file_assignments_global_eligibility
    ON agent_file_assignments(global_tool_eligible)
"""

_CREATE_AGENT_TOOL_FILE_PERMISSIONS = """
CREATE TABLE IF NOT EXISTS agent_tool_file_permissions (
    id               TEXT PRIMARY KEY,
    agent_id         TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    capability_id    TEXT NOT NULL,
    absolute_path    TEXT NOT NULL,
    permission_state TEXT NOT NULL DEFAULT 'granted',
    source_kind      TEXT NOT NULL DEFAULT 'manual',
    granted_at       TEXT NOT NULL,
    revoked_at       TEXT,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    UNIQUE(agent_id, capability_id, absolute_path)
)
"""

_CREATE_AGENT_TOOL_FILE_PERMISSIONS_INDEX = """
CREATE INDEX IF NOT EXISTS idx_agent_tool_file_permissions_agent_id
    ON agent_tool_file_permissions(agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_tool_file_permissions_capability_id
    ON agent_tool_file_permissions(capability_id);
CREATE INDEX IF NOT EXISTS idx_agent_tool_file_permissions_absolute_path
    ON agent_tool_file_permissions(absolute_path);
CREATE INDEX IF NOT EXISTS idx_agent_tool_file_permissions_state
    ON agent_tool_file_permissions(permission_state)
"""

_CREATE_AGENT_ENVIRONMENT_ASSETS = """
CREATE TABLE IF NOT EXISTS agent_environment_assets (
    id                TEXT PRIMARY KEY,
    environment_id    TEXT NOT NULL DEFAULT 'agent_environment',
    skin_id           TEXT NOT NULL,
    asset_scope       TEXT NOT NULL,
    owner_agent_id    TEXT REFERENCES agents(id) ON DELETE CASCADE,
    display_name      TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    stored_filename   TEXT NOT NULL,
    storage_path      TEXT NOT NULL,
    source_kind       TEXT NOT NULL DEFAULT 'uploaded',
    source_ref        TEXT,
    is_active         INTEGER NOT NULL DEFAULT 1,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    UNIQUE(skin_id, asset_scope, source_ref)
)
"""

_CREATE_AGENT_ENVIRONMENT_ASSETS_INDEX = """
CREATE INDEX IF NOT EXISTS idx_agent_environment_assets_skin_id
    ON agent_environment_assets(skin_id);
CREATE INDEX IF NOT EXISTS idx_agent_environment_assets_scope
    ON agent_environment_assets(asset_scope);
CREATE INDEX IF NOT EXISTS idx_agent_environment_assets_owner_agent_id
    ON agent_environment_assets(owner_agent_id);
"""

_CREATE_AGENT_ENVIRONMENT_AGENT_SKIN_PREFERENCES = """
CREATE TABLE IF NOT EXISTS agent_environment_agent_skin_preferences (
    id                TEXT PRIMARY KEY,
    agent_id          TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    skin_id           TEXT NOT NULL,
    background_mode   TEXT NOT NULL DEFAULT 'random',
    selected_asset_id TEXT REFERENCES agent_environment_assets(id),
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    UNIQUE(agent_id, skin_id)
)
"""

_CREATE_AGENT_ENVIRONMENT_AGENT_SKIN_PREFERENCES_INDEX = """
CREATE INDEX IF NOT EXISTS idx_agent_environment_agent_skin_preferences_agent_id
    ON agent_environment_agent_skin_preferences(agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_environment_agent_skin_preferences_skin_id
    ON agent_environment_agent_skin_preferences(skin_id);
"""

_SEED_AGENT_CAPABILITY_ASSIGNMENTS_FROM_LEGACY = """
INSERT OR IGNORE INTO agent_capability_assignments (
    id,
    agent_id,
    capability_id,
    assignment_state,
    assigned_at,
    revoked_at,
    created_at,
    updated_at
)
SELECT
    lower(hex(randomblob(16))),
    agents.id,
    trim(CAST(json_each.value AS TEXT)),
    'granted',
    COALESCE(agents.updated_at, agents.created_at),
    NULL,
    COALESCE(agents.created_at, agents.updated_at),
    COALESCE(agents.updated_at, agents.created_at)
FROM agents, json_each(agents.tool_bindings)
WHERE trim(CAST(json_each.value AS TEXT)) <> ''
"""

_CREATE_CAPABILITY_COMPARISON_EVIDENCE = """
CREATE TABLE IF NOT EXISTS capability_comparison_evidence (
    id                     TEXT PRIMARY KEY,
    run_id                 TEXT NOT NULL,
    candidate_function_name TEXT NOT NULL,
    target_capability_id   TEXT NOT NULL,
    exact_text_match       INTEGER NOT NULL DEFAULT 0,
    normalized_text_match  INTEGER NOT NULL DEFAULT 0,
    ast_structural_match   INTEGER NOT NULL DEFAULT 0,
    function_name_match    INTEGER NOT NULL DEFAULT 0,
    similarity_score       REAL NOT NULL DEFAULT 0.0,
    feature_breakdown_json TEXT NOT NULL DEFAULT '{}',
    is_literal_duplicate   INTEGER NOT NULL DEFAULT 0,
    created_at             TEXT NOT NULL
)
"""

_CREATE_CAPABILITY_COMPARISON_EVIDENCE_INDICES = """
CREATE INDEX IF NOT EXISTS idx_comparison_evidence_run_id
    ON capability_comparison_evidence(run_id);
CREATE INDEX IF NOT EXISTS idx_comparison_evidence_candidate
    ON capability_comparison_evidence(candidate_function_name);
CREATE INDEX IF NOT EXISTS idx_comparison_evidence_target
    ON capability_comparison_evidence(target_capability_id)
"""

_CREATE_CAPABILITY_COMPARISON_WEB = """
CREATE TABLE IF NOT EXISTS capability_comparison_web (
    id                   TEXT PRIMARY KEY,
    capability_id_a      TEXT NOT NULL,
    capability_id_b      TEXT NOT NULL,
    comparison_kind      TEXT NOT NULL DEFAULT 'pairwise',
    exact_text_match     INTEGER NOT NULL DEFAULT 0,
    normalized_text_match INTEGER NOT NULL DEFAULT 0,
    ast_structural_match INTEGER NOT NULL DEFAULT 0,
    similarity_score     REAL NOT NULL DEFAULT 0.0,
    feature_breakdown_json TEXT NOT NULL DEFAULT '{}',
    compared_at          TEXT NOT NULL,
    UNIQUE(capability_id_a, capability_id_b, comparison_kind)
)
"""

_CREATE_CAPABILITY_COMPARISON_WEB_INDEX = """
CREATE INDEX IF NOT EXISTS idx_comparison_web_a ON capability_comparison_web(capability_id_a);
CREATE INDEX IF NOT EXISTS idx_comparison_web_b ON capability_comparison_web(capability_id_b)
"""

_ADD_CAPABILITY_RECORD_CODE_BLOCK = """
ALTER TABLE capability_records ADD COLUMN code_block TEXT NOT NULL DEFAULT ''
"""

_CREATE_AGENT_WORKFLOWS = """
CREATE TABLE IF NOT EXISTS agent_workflows (
    id               TEXT PRIMARY KEY,
    agent_id         TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    display_name     TEXT NOT NULL DEFAULT 'Workflow',
    instruction_code TEXT NOT NULL DEFAULT '',
    trigger_json     TEXT NOT NULL DEFAULT '{"mode":"repo_root_from_keycard","output_filename":"workflow_output.json"}',
    is_active        INTEGER NOT NULL DEFAULT 1,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
)
"""

_CREATE_AGENT_WORKFLOWS_INDEX = """
CREATE INDEX IF NOT EXISTS idx_agent_workflows_agent_id ON agent_workflows(agent_id)
"""

_ADD_AGENT_WORKFLOW_ASSIGNED_TRIGGERS = """
ALTER TABLE agent_workflows ADD COLUMN assigned_triggers_json TEXT NOT NULL DEFAULT '["manual"]'
"""

_ADD_AGENT_FILE_ASSIGNMENT_ENTRY_KIND = """
ALTER TABLE agent_file_assignments ADD COLUMN entry_kind TEXT NOT NULL DEFAULT 'file'
"""

_ADD_AGENT_CAPABILITY_ASSIGNMENT_SCOPE = """
ALTER TABLE agent_capability_assignments ADD COLUMN scope TEXT NOT NULL DEFAULT 'local'
"""

_CREATE_CAPABILITY_SOURCE_REGISTRATIONS = """
CREATE TABLE IF NOT EXISTS capability_source_registrations (
    source_ref      TEXT PRIMARY KEY,
    source_kind     TEXT NOT NULL DEFAULT 'builtin_pack',
    module_path     TEXT NOT NULL DEFAULT '',
    display_name    TEXT NOT NULL DEFAULT '',
    is_active       INTEGER NOT NULL DEFAULT 1,
    registered_at   TEXT NOT NULL,
    updated_at      TEXT NOT NULL
)
"""

_CREATE_CAPABILITY_SOURCE_REGISTRATIONS_INDEX = """
CREATE INDEX IF NOT EXISTS idx_capability_source_registrations_source_kind
    ON capability_source_registrations(source_kind);
CREATE INDEX IF NOT EXISTS idx_capability_source_registrations_is_active
    ON capability_source_registrations(is_active)
"""

_CREATE_AGENT_CONFIGURATION_BLUEPRINTS = """
CREATE TABLE IF NOT EXISTS agent_configuration_blueprints (
    id             TEXT PRIMARY KEY,
    agent_id       TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    display_name   TEXT NOT NULL DEFAULT '',
    blueprint_json TEXT NOT NULL DEFAULT '{}',
    applied_at     TEXT,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
)
"""

_CREATE_AGENT_CONFIGURATION_BLUEPRINTS_INDEX = """
CREATE INDEX IF NOT EXISTS idx_agent_configuration_blueprints_agent_id
    ON agent_configuration_blueprints(agent_id)
"""

_RENAME_CAPABILITY_TYPE_BASE_TO_FUNCTION = """
UPDATE capability_records SET capability_type = 'function' WHERE capability_type = 'base';
UPDATE capability_records SET capability_type = 'composite' WHERE capability_type = 'combination'
"""

_ADD_CAPABILITY_RECORD_EXECUTION_SOURCE = """
ALTER TABLE capability_records ADD COLUMN execution_source TEXT NOT NULL DEFAULT 'binding_ref'
"""

# Migration 63 is applied via _apply_normalize_capability_type_in_json_columns
# (Python-level JSON rewrite, not raw SQL).
_NORMALIZE_CAPABILITY_TYPE_JSON_PLACEHOLDER = "-- migration 63 handled in Python"

# ---------------------------------------------------------------------------
# Package-first rebuild migrations (64+)
# ---------------------------------------------------------------------------

_ADD_CAPABILITY_RECORD_ENTRYPOINT = """
ALTER TABLE capability_records ADD COLUMN entrypoint TEXT NOT NULL DEFAULT 'run'
"""

_ADD_CAPABILITY_RECORD_PUBLISH_OUTPUTS = """
ALTER TABLE capability_records ADD COLUMN publish_outputs_json TEXT NOT NULL DEFAULT '["python_artifact","text_summary"]'
"""

_CREATE_CAPABILITY_PUBLISHED_FORMS = """
CREATE TABLE IF NOT EXISTS capability_published_forms (
    id               TEXT PRIMARY KEY,
    capability_id    TEXT NOT NULL,
    form_kind        TEXT NOT NULL,
    artifact_path    TEXT NOT NULL DEFAULT '',
    publish_event_id TEXT NOT NULL DEFAULT '',
    created_at       TEXT NOT NULL,
    FOREIGN KEY (capability_id) REFERENCES capability_records(capability_id) ON DELETE CASCADE
)
"""

_CREATE_CAPABILITY_PUBLISHED_FORMS_INDICES = """
CREATE INDEX IF NOT EXISTS idx_capability_published_forms_capability_id
    ON capability_published_forms(capability_id);
CREATE INDEX IF NOT EXISTS idx_capability_published_forms_publish_event_id
    ON capability_published_forms(publish_event_id)
"""

_PRESERVE_CAPABILITY_DRAFT_REVISIONS = """
-- RevEng's draft service still exposes saved revision history and rollback.
-- Migration 68 was normalized before the first public release so a clean
-- install does not delete the table that owns that behavior.
SELECT 1
"""

_CREATE_CAPABILITY_SURFACE_POLICIES = """
CREATE TABLE IF NOT EXISTS capability_surface_policies (
    id               TEXT PRIMARY KEY,
    capability_id    TEXT,
    surface_name     TEXT NOT NULL,
    consumer_kind    TEXT NOT NULL,
    access_policy    TEXT NOT NULL,
    notes            TEXT NOT NULL DEFAULT '',
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
)
"""

_CREATE_CAPABILITY_SURFACE_POLICIES_INDEX = """
CREATE INDEX IF NOT EXISTS idx_capability_surface_policies_capability_id
    ON capability_surface_policies(capability_id);
CREATE INDEX IF NOT EXISTS idx_capability_surface_policies_surface_name
    ON capability_surface_policies(surface_name)
"""

# ---------------------------------------------------------------------------
# Migration list  — (version, sql)
# ---------------------------------------------------------------------------
# Each entry is applied once.  Use executescript() for multi-statement DDL.
# Migrations must never be re-ordered or modified after deployment.

_MIGRATIONS: list[tuple[int, str]] = [
    (1, _CREATE_PROVIDERS),
    (2, _CREATE_AGENTS),
    (3, _CREATE_AGENTS_INDICES),
    (4, _CREATE_ANALYSIS_RUNS),
    (5, _CREATE_ANALYSIS_RUNS_INDICES),
    (6, _CREATE_AGENT_RUNS),
    (7, _CREATE_AGENT_RUNS_INDICES),
    (8, _CREATE_RUN_OUTPUTS),
    (9, _CREATE_RUN_OUTPUTS_INDICES),
    (10, _CREATE_RUN_EVENTS),
    (11, _CREATE_RUN_EVENTS_INDICES),
    (12, _CREATE_AGENT_SECTIONS),
    (13, _CREATE_AGENT_SECTIONS_INDEX),
    (14, _CREATE_CAPABILITY_BUNDLES),
    (15, _CREATE_CAPABILITY_BUNDLES_INDEX),
    (16, _CREATE_CAPABILITY_DRAFT_ITEMS),
    (17, _CREATE_CAPABILITY_DRAFT_ITEMS_INDEX),
    (18, _ADD_BUNDLE_VERSION),
    (19, _CREATE_BUNDLE_PUBLISH_HISTORY),
    (20, _CREATE_BUNDLE_PUBLISH_HISTORY_INDEX),
    (21, CREATE_FRAMEWORK_LOGS),
    (22, CREATE_FRAMEWORK_LOGS_INDICES),
    (23, _RENAME_CAPABILITY_ENVIRONMENT_TABLES_TO_DRAFTS),
    (24, _CREATE_CAPABILITY_DRAFT_REVISIONS),
    (25, _CREATE_CAPABILITY_DRAFT_REVISIONS_INDEX),
    (26, _CREATE_CAPABILITY_RECORDS),
    (27, _CREATE_CAPABILITY_RECORDS_INDEX),
    (28, _CREATE_CAPABILITY_RECORD_EVENTS),
    (29, _CREATE_CAPABILITY_RECORD_EVENTS_INDEX),
    (30, _CREATE_CAPABILITY_PUBLICATION_CANDIDATES),
    (31, _CREATE_CAPABILITY_PUBLICATION_CANDIDATES_INDEX),
    (32, _CREATE_CAPABILITY_PACKAGE_OBJECTS),
    (33, _CREATE_CAPABILITY_PACKAGE_OBJECTS_INDEX),
    (34, _ADD_CAPABILITY_RECORD_PACKAGE_OBJECT_ID),
    (35, _CREATE_CAPABILITY_ENVIRONMENT_SETTINGS),
    (36, _CREATE_AGENT_CAPABILITY_ASSIGNMENTS),
    (37, _CREATE_AGENT_CAPABILITY_ASSIGNMENTS_INDEX),
    (38, _SEED_AGENT_CAPABILITY_ASSIGNMENTS_FROM_LEGACY),
    (39, _CREATE_AGENT_FILE_ASSIGNMENTS),
    (40, _CREATE_AGENT_FILE_ASSIGNMENTS_INDEX),
    (41, _CREATE_AGENT_TOOL_FILE_PERMISSIONS),
    (42, _CREATE_AGENT_TOOL_FILE_PERMISSIONS_INDEX),
    (43, _CREATE_AGENT_ENVIRONMENT_ASSETS),
    (44, _CREATE_AGENT_ENVIRONMENT_ASSETS_INDEX),
    (45, _CREATE_AGENT_ENVIRONMENT_AGENT_SKIN_PREFERENCES),
    (46, _CREATE_AGENT_ENVIRONMENT_AGENT_SKIN_PREFERENCES_INDEX),
    (47, _CREATE_CAPABILITY_COMPARISON_EVIDENCE),
    (48, _CREATE_CAPABILITY_COMPARISON_EVIDENCE_INDICES),
    (49, _CREATE_CAPABILITY_COMPARISON_WEB),
    (50, _CREATE_CAPABILITY_COMPARISON_WEB_INDEX),
    (51, _ADD_CAPABILITY_RECORD_CODE_BLOCK),
    (52, _CREATE_AGENT_WORKFLOWS),
    (53, _CREATE_AGENT_WORKFLOWS_INDEX),
    (54, _ADD_AGENT_WORKFLOW_ASSIGNED_TRIGGERS),
    (55, _ADD_AGENT_FILE_ASSIGNMENT_ENTRY_KIND),
    (56, _ADD_AGENT_CAPABILITY_ASSIGNMENT_SCOPE),
    (57, _CREATE_CAPABILITY_SOURCE_REGISTRATIONS),
    (58, _CREATE_CAPABILITY_SOURCE_REGISTRATIONS_INDEX),
    (59, _CREATE_AGENT_CONFIGURATION_BLUEPRINTS),
    (60, _CREATE_AGENT_CONFIGURATION_BLUEPRINTS_INDEX),
    (61, _RENAME_CAPABILITY_TYPE_BASE_TO_FUNCTION),
    (62, _ADD_CAPABILITY_RECORD_EXECUTION_SOURCE),
    (63, _NORMALIZE_CAPABILITY_TYPE_JSON_PLACEHOLDER),
    # Package-first rebuild
    (64, _ADD_CAPABILITY_RECORD_ENTRYPOINT),
    (65, _ADD_CAPABILITY_RECORD_PUBLISH_OUTPUTS),
    (66, _CREATE_CAPABILITY_PUBLISHED_FORMS),
    (67, _CREATE_CAPABILITY_PUBLISHED_FORMS_INDICES),
    (68, _PRESERVE_CAPABILITY_DRAFT_REVISIONS),
    (69, _CREATE_CAPABILITY_SURFACE_POLICIES),
    (70, _CREATE_CAPABILITY_SURFACE_POLICIES_INDEX),
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def apply_migrations(conn: sqlite3.Connection) -> None:
    """
    Apply all pending migrations in order.

    Safe to call multiple times — already-applied migrations are skipped.
    Must be called with the application-level connection (not a thread-local).
    """
    conn.execute(_CREATE_SCHEMA_VERSION)
    conn.commit()

    row = conn.execute("SELECT MAX(version) FROM schema_versions").fetchone()
    current_version: int = row[0] if row[0] is not None else 0

    from reveng.platform.utils import now_utc

    for version, sql in _MIGRATIONS:
        if version <= current_version:
            continue
        if version == 38:
            _apply_seed_agent_capability_assignments_from_legacy(conn)
        elif version == 63:
            _apply_normalize_capability_type_in_json_columns(conn)
        else:
            # executescript commits any open transaction, so use execute for simple DDL
            for statement in [s.strip() for s in sql.split(";") if s.strip()]:
                conn.execute(statement)
        conn.execute(
            "INSERT INTO schema_versions (version, applied_at) VALUES (?, ?)",
            (version, now_utc()),
        )
        conn.commit()


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table' AND name = ?
        """,
        (table_name,),
    ).fetchone()
    return row is not None


def _apply_seed_agent_capability_assignments_from_legacy(
    conn: sqlite3.Connection,
) -> None:
    # Some legacy test fixtures start from pre-agent schemas and only need the
    # draft-table migrations. In that case there is nothing to seed.
    if not _table_exists(conn, "agents"):
        return
    if not _table_exists(conn, "agent_capability_assignments"):
        return
    conn.execute(_SEED_AGENT_CAPABILITY_ASSIGNMENTS_FROM_LEGACY)


def _apply_normalize_capability_type_in_json_columns(
    conn: sqlite3.Connection,
) -> None:
    """
    Migration 63 — normalize 'base'→'function' and 'combination'→'composite' inside
    JSON blob columns that were not covered by the SQL UPDATE in migration 61.

    Tables updated:
      capability_package_objects.snapshot_json
      capability_draft_items.draft_data

    capability_record_events.snapshot_json is intentionally left unchanged — it is
    the immutable history ledger and old values there are read-only context, never
    re-executed.
    """
    import json as _json

    def _normalize_type(v: str) -> str:
        if v == "base":
            return "function"
        if v == "combination":
            return "composite"
        return v

    # capability_package_objects.snapshot_json
    if _table_exists(conn, "capability_package_objects"):
        rows = conn.execute(
            "SELECT id, snapshot_json FROM capability_package_objects"
        ).fetchall()
        for row in rows:
            raw = row[1] or "{}"
            try:
                snap = _json.loads(raw)
            except Exception:
                continue
            ct = snap.get("capability_type")
            if ct in ("base", "combination"):
                snap["capability_type"] = _normalize_type(ct)
                conn.execute(
                    "UPDATE capability_package_objects SET snapshot_json = ? WHERE id = ?",
                    (_json.dumps(snap), row[0]),
                )

    # capability_draft_items.draft_data
    if _table_exists(conn, "capability_draft_items"):
        rows = conn.execute(
            "SELECT id, draft_data FROM capability_draft_items"
        ).fetchall()
        for row in rows:
            raw = row[1] or "{}"
            try:
                data = _json.loads(raw)
            except Exception:
                continue
            ct = data.get("capability_type")
            if ct in ("base", "combination"):
                data["capability_type"] = _normalize_type(ct)
                conn.execute(
                    "UPDATE capability_draft_items SET draft_data = ? WHERE id = ?",
                    (_json.dumps(data), row[0]),
                )
