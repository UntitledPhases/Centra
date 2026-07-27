-- ============================================================
-- SLICE-1 SCHEMA: Persistence + Guardrail Foundation
-- ============================================================
-- Partition legend:
--   PROTECTED  : runtime read-only config
--   PROPOSAL   : writable by non-promoter paths
--   DURABLE    : promoter-only write path; promotion_record required
--   EPHEMERAL  : runtime telemetry, validation, traces

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ============================================================
-- PROTECTED CONFIG LAYER (runtime read-only)
-- ============================================================

CREATE TABLE IF NOT EXISTS mission (
    mission_id    TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    description   TEXT NOT NULL,
    created_at    TEXT NOT NULL
    -- No update columns by design: protected state is immutable at runtime
);

CREATE TABLE IF NOT EXISTS policy (
    policy_id     TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    rules_json    TEXT NOT NULL,   -- JSON blob of rules
    version       INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS approval_rules (
    rule_id       TEXT PRIMARY KEY,
    policy_id     TEXT NOT NULL REFERENCES policy(policy_id),
    target_layer  TEXT NOT NULL,   -- 'durable' | 'proposal'
    conditions    TEXT NOT NULL,   -- JSON
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS authority_scope (
    scope_id      TEXT PRIMARY KEY,
    scope_name    TEXT NOT NULL,
    allowed_roles TEXT NOT NULL,   -- JSON array
    restrictions  TEXT NOT NULL,   -- JSON
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trusted_registry (
    registry_id   TEXT PRIMARY KEY,
    entry_name    TEXT NOT NULL,
    entry_type    TEXT NOT NULL,   -- 'tool' | 'data_source' | 'agent'
    trust_level   TEXT NOT NULL,
    metadata      TEXT,            -- JSON
    created_at    TEXT NOT NULL
);

-- ============================================================
-- AUTHORITATIVE ROOT BUDGET ENVELOPES
-- ============================================================

CREATE TABLE IF NOT EXISTS root_budget_envelopes (
    root_budget_envelope_id         TEXT PRIMARY KEY,
    task_id                         TEXT NOT NULL,   -- references root task
    max_total_tokens_or_compute_units INTEGER NOT NULL,
    max_total_subagents             INTEGER NOT NULL,
    max_total_wallclock             INTEGER NOT NULL,  -- seconds
    max_total_external_calls        INTEGER NOT NULL,
    created_at                      TEXT NOT NULL
    -- task_id FK added after tasks table; enforce in app layer for root tasks
);

-- ============================================================
-- PROPOSAL LAYER
-- ============================================================

CREATE TABLE IF NOT EXISTS tasks (
    -- Identity
    task_id                         TEXT PRIMARY KEY,
    parent_task_id                  TEXT,            -- NULL for root task
    -- Classification
    task_type                       TEXT NOT NULL,
    criticality_level               TEXT NOT NULL,
    status                          TEXT NOT NULL DEFAULT 'pending',
    promotion_target                TEXT NOT NULL,   -- 'durable' | 'proposal'
    -- Budget header (full, mandatory)
    max_depth                       INTEGER NOT NULL,
    max_subagents                   INTEGER NOT NULL,
    max_retries                     INTEGER NOT NULL,
    max_tokens_or_compute_units     INTEGER NOT NULL,
    validator_required              INTEGER NOT NULL DEFAULT 1,  -- 0|1 boolean
    allowed_tools                   TEXT NOT NULL,   -- JSON array
    allowed_data_sources            TEXT NOT NULL,   -- JSON array
    maintenance_ticket_id           TEXT,            -- NULL allowed; no maintenance mode in slice-1
    -- Timestamps
    created_at                      TEXT NOT NULL,
    expires_at                      TEXT NOT NULL,
    FOREIGN KEY (parent_task_id) REFERENCES tasks(task_id)
);

CREATE TABLE IF NOT EXISTS work_items (
    work_item_id        TEXT PRIMARY KEY,
    task_id             TEXT NOT NULL REFERENCES tasks(task_id),
    assigned_role       TEXT NOT NULL,   -- 'executor' | 'validator' | 'promoter'
    instructions        TEXT NOT NULL,
    input_artifact_refs TEXT,            -- JSON array of artifact_ids
    output_schema_ref   TEXT,            -- reference to expected output schema
    attempt_no          INTEGER NOT NULL DEFAULT 1,
    created_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS proposed_artifacts (
    artifact_id     TEXT PRIMARY KEY,
    task_id         TEXT NOT NULL REFERENCES tasks(task_id),
    run_id          TEXT,                -- may be set post-run
    artifact_type   TEXT NOT NULL,
    content_hash    TEXT NOT NULL,
    storage_uri     TEXT NOT NULL,
    schema_valid    INTEGER NOT NULL DEFAULT 0,  -- 0|1
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS proposed_observations (
    observation_id  TEXT PRIMARY KEY,
    task_id         TEXT NOT NULL REFERENCES tasks(task_id),
    artifact_id     TEXT REFERENCES proposed_artifacts(artifact_id),
    content_hash    TEXT NOT NULL,
    created_at      TEXT NOT NULL
);

-- ============================================================
-- EPHEMERAL LAYER (runtime telemetry, validation, traces)
-- ============================================================

CREATE TABLE IF NOT EXISTS runs (
    run_id          TEXT PRIMARY KEY,
    task_id         TEXT NOT NULL REFERENCES tasks(task_id),
    work_item_id    TEXT REFERENCES work_items(work_item_id),
    role            TEXT NOT NULL,   -- 'executor' | 'validator' | 'promoter'
    status          TEXT NOT NULL DEFAULT 'running',
    started_at      TEXT NOT NULL,
    expires_at      TEXT NOT NULL,
    attempt_no      INTEGER NOT NULL DEFAULT 1,
    parent_run_id   TEXT REFERENCES runs(run_id)
);

CREATE TABLE IF NOT EXISTS run_heartbeats (
    heartbeat_id    TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL REFERENCES runs(run_id),
    timestamp       TEXT NOT NULL,
    status          TEXT NOT NULL,
    progress_note   TEXT
);

CREATE TABLE IF NOT EXISTS validator_results (
    validator_result_id TEXT PRIMARY KEY,
    task_id             TEXT NOT NULL REFERENCES tasks(task_id),
    run_id              TEXT NOT NULL REFERENCES runs(run_id),
    validation_status   TEXT NOT NULL,  -- 'PASS' | 'FAIL' | 'ESCALATE'
    confidence_score    REAL,
    failed_constraints  TEXT,           -- JSON array
    grounding_status    TEXT NOT NULL,
    schema_status       TEXT NOT NULL,
    policy_status       TEXT NOT NULL,
    remediation_action  TEXT,
    notes               TEXT,
    created_at          TEXT NOT NULL,
    CHECK (validation_status IN ('PASS', 'FAIL', 'ESCALATE'))
);

CREATE TABLE IF NOT EXISTS promotion_records (
    promotion_record_id TEXT PRIMARY KEY,
    task_id             TEXT NOT NULL REFERENCES tasks(task_id),
    source_layer        TEXT NOT NULL,
    target_layer        TEXT NOT NULL,
    source_artifact_id  TEXT REFERENCES proposed_artifacts(artifact_id),
    target_object_id    TEXT,           -- ID of the created durable row
    executor_id         TEXT NOT NULL,  -- runtime string identifier
    validator_id        TEXT NOT NULL,  -- runtime string identifier
    validation_result_id TEXT NOT NULL REFERENCES validator_results(validator_result_id),
    approval_metadata   TEXT,           -- JSON
    artifact_input_hash TEXT,
    timestamp           TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dead_letter_entries (
    dead_letter_id  TEXT PRIMARY KEY,
    task_id         TEXT REFERENCES tasks(task_id),
    run_id          TEXT REFERENCES runs(run_id),
    failure_class   TEXT NOT NULL,  -- required
    reason          TEXT NOT NULL,  -- required
    retry_count     INTEGER NOT NULL DEFAULT 0,
    timestamp       TEXT NOT NULL
);

-- ============================================================
-- DURABLE LAYER (promoter-only write path)
-- promotion_record_id NOT NULL enforced at DB level
-- ============================================================

CREATE TABLE IF NOT EXISTS approved_artifacts (
    approved_artifact_id    TEXT PRIMARY KEY,
    source_artifact_id      TEXT NOT NULL REFERENCES proposed_artifacts(artifact_id),
    promotion_record_id     TEXT NOT NULL REFERENCES promotion_records(promotion_record_id),
    content_hash            TEXT NOT NULL,
    storage_uri             TEXT NOT NULL,
    created_at              TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS validated_observations (
    validated_observation_id    TEXT PRIMARY KEY,
    source_observation_id       TEXT NOT NULL REFERENCES proposed_observations(observation_id),
    promotion_record_id         TEXT NOT NULL REFERENCES promotion_records(promotion_record_id),
    content_hash                TEXT NOT NULL,
    created_at                  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS accepted_run_summaries (
    run_summary_id          TEXT PRIMARY KEY,
    task_id                 TEXT NOT NULL REFERENCES tasks(task_id),
    promotion_record_id     TEXT NOT NULL REFERENCES promotion_records(promotion_record_id),
    summary_artifact_id     TEXT NOT NULL REFERENCES approved_artifacts(approved_artifact_id),
    created_at              TEXT NOT NULL
);

-- ============================================================
-- INDEXES
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_tasks_parent       ON tasks(parent_task_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status        ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_work_items_task     ON work_items(task_id);
CREATE INDEX IF NOT EXISTS idx_runs_task           ON runs(task_id);
CREATE INDEX IF NOT EXISTS idx_runs_status         ON runs(status);
CREATE INDEX IF NOT EXISTS idx_heartbeats_run      ON run_heartbeats(run_id);
CREATE INDEX IF NOT EXISTS idx_heartbeats_ts       ON run_heartbeats(timestamp);
CREATE INDEX IF NOT EXISTS idx_validator_results_task ON validator_results(task_id);
CREATE INDEX IF NOT EXISTS idx_promotion_records_task ON promotion_records(task_id);
CREATE INDEX IF NOT EXISTS idx_approved_artifacts_task ON approved_artifacts(source_artifact_id);
CREATE INDEX IF NOT EXISTS idx_dead_letter_task    ON dead_letter_entries(task_id);
CREATE INDEX IF NOT EXISTS idx_root_budget_task    ON root_budget_envelopes(task_id);
