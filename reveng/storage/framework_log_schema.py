from __future__ import annotations


CREATE_FRAMEWORK_LOGS = """
CREATE TABLE IF NOT EXISTS framework_logs (
    id                                           TEXT PRIMARY KEY,
    logged_at                                    TEXT NOT NULL,
    run_id                                       TEXT,
    workflow_id                                  TEXT,
    capability_id                                TEXT,
    origin                                       TEXT NOT NULL,
    stage                                        TEXT NOT NULL,
    event_type                                   TEXT NOT NULL,
    level                                        TEXT NOT NULL,
    status                                       TEXT NOT NULL,
    trigger                                      TEXT,
    message                                      TEXT NOT NULL,
    details                                      TEXT NOT NULL DEFAULT '{}',
    boundary_sensitive                           INTEGER NOT NULL DEFAULT 0,
    lawful_framework_behavior                    INTEGER NOT NULL DEFAULT 1,
    compensating_for_smeared_responsibility      INTEGER NOT NULL DEFAULT 0,
    architectural_drift_detected                 INTEGER NOT NULL DEFAULT 0
)
"""


CREATE_FRAMEWORK_LOGS_INDICES = """
CREATE INDEX IF NOT EXISTS idx_framework_logs_logged_at
    ON framework_logs(logged_at DESC);
CREATE INDEX IF NOT EXISTS idx_framework_logs_run_id_logged_at
    ON framework_logs(run_id, logged_at);
CREATE INDEX IF NOT EXISTS idx_framework_logs_workflow_id_logged_at
    ON framework_logs(workflow_id, logged_at);
CREATE INDEX IF NOT EXISTS idx_framework_logs_origin_stage
    ON framework_logs(origin, stage)
"""
