BEGIN;

CREATE TABLE IF NOT EXISTS evidence_packages (
    evidence_package_id TEXT NOT NULL,
    incident_id TEXT NOT NULL,
    package_version INTEGER NOT NULL CHECK (package_version > 0),
    completeness TEXT NOT NULL CHECK (completeness IN ('COMPLETE', 'PARTIAL', 'INVALID')),
    schema_version TEXT NOT NULL,
    builder_configuration_version TEXT NOT NULL,
    generated_at TIMESTAMPTZ NOT NULL,
    package_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (evidence_package_id, package_version)
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_evidence_packages_incident_version
    ON evidence_packages (incident_id, package_version);

CREATE INDEX IF NOT EXISTS ix_evidence_packages_incident_generated
    ON evidence_packages (incident_id, generated_at DESC);

CREATE INDEX IF NOT EXISTS ix_evidence_packages_completeness
    ON evidence_packages (completeness, generated_at DESC);

CREATE INDEX IF NOT EXISTS ix_evidence_packages_json_gin
    ON evidence_packages USING GIN (package_json jsonb_path_ops);

COMMIT;
