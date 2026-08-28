BEGIN;

CREATE TABLE IF NOT EXISTS runtime_resources (
    resource_type TEXT NOT NULL,
    resource_key TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    payload_json JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (resource_type, resource_key)
);

CREATE INDEX IF NOT EXISTS ix_runtime_resources_type_updated
    ON runtime_resources (resource_type, updated_at DESC);
CREATE INDEX IF NOT EXISTS ix_runtime_resources_payload_gin
    ON runtime_resources USING GIN (payload_json jsonb_path_ops);

CREATE TABLE IF NOT EXISTS incidents (
    incident_id TEXT PRIMARY KEY,
    lifecycle TEXT NOT NULL,
    severity TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    projection_json JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_incidents_lifecycle_started
    ON incidents (lifecycle, started_at DESC);

CREATE TABLE IF NOT EXISTS metric_history (
    metric_key TEXT NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    incident_id TEXT,
    value DOUBLE PRECISION,
    unavailable_reason TEXT,
    snapshot_version INTEGER NOT NULL CHECK (snapshot_version > 0),
    PRIMARY KEY (metric_key, observed_at, snapshot_version)
);
CREATE INDEX IF NOT EXISTS ix_metric_history_incident_time
    ON metric_history (incident_id, observed_at DESC);

CREATE TABLE IF NOT EXISTS detector_evaluations (
    evaluation_id TEXT PRIMARY KEY,
    incident_id TEXT,
    evaluated_at TIMESTAMPTZ NOT NULL,
    configuration_version TEXT NOT NULL,
    evaluation_json JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS operational_events (
    operational_event_id TEXT PRIMARY KEY,
    occurred_at TIMESTAMPTZ NOT NULL,
    event_json JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS investigation_results (
    incident_id TEXT NOT NULL,
    result_type TEXT NOT NULL CHECK (result_type IN ('DIMENSIONAL_ANALYSIS', 'RCA')),
    result_version INTEGER NOT NULL CHECK (result_version > 0),
    generated_at TIMESTAMPTZ NOT NULL,
    result_json JSONB NOT NULL,
    PRIMARY KEY (incident_id, result_type, result_version)
);

CREATE TABLE IF NOT EXISTS human_reviews (
    incident_id TEXT NOT NULL,
    review_version INTEGER NOT NULL CHECK (review_version > 0),
    hypothesis_id TEXT NOT NULL,
    status TEXT NOT NULL,
    note TEXT,
    reviewed_by TEXT NOT NULL CHECK (reviewed_by = 'demo-operator'),
    reviewed_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (incident_id, review_version)
);

CREATE TABLE IF NOT EXISTS copilot_interactions (
    interaction_id TEXT PRIMARY KEY,
    incident_id TEXT NOT NULL,
    evidence_package_id TEXT NOT NULL,
    evidence_package_version INTEGER NOT NULL CHECK (evidence_package_version > 0),
    status TEXT NOT NULL,
    provider TEXT,
    model_id TEXT,
    configuration_version TEXT NOT NULL,
    raw_output_json JSONB,
    validated_output_json JSONB,
    validation_audit_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_copilot_interactions_incident_created
    ON copilot_interactions (incident_id, created_at DESC);

CREATE TABLE IF NOT EXISTS copilot_feedback (
    message_id TEXT NOT NULL,
    feedback_version INTEGER NOT NULL CHECK (feedback_version > 0),
    feedback_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (message_id, feedback_version)
);

CREATE TABLE IF NOT EXISTS command_results (
    command_scope TEXT NOT NULL,
    client_request_id TEXT NOT NULL,
    response_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (command_scope, client_request_id)
);

CREATE TABLE IF NOT EXISTS websocket_events (
    sequence BIGSERIAL PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE,
    event_type TEXT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    payload_json JSONB NOT NULL
);

COMMIT;
