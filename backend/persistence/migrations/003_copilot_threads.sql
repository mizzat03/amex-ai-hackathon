BEGIN;

CREATE TABLE IF NOT EXISTS copilot_threads (
    thread_id TEXT PRIMARY KEY,
    incident_id TEXT NOT NULL UNIQUE
        REFERENCES incidents (incident_id) ON DELETE CASCADE,
    latest_evidence_package_id TEXT,
    latest_evidence_package_version INTEGER
        CHECK (latest_evidence_package_version IS NULL OR latest_evidence_package_version > 0),
    history_digest_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (thread_id, incident_id)
);

CREATE INDEX IF NOT EXISTS ix_copilot_threads_updated
    ON copilot_threads (updated_at DESC);

CREATE TABLE IF NOT EXISTS copilot_messages (
    message_id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    incident_id TEXT NOT NULL,
    sequence BIGINT NOT NULL CHECK (sequence > 0),
    role TEXT NOT NULL CHECK (role IN ('USER', 'ASSISTANT', 'SYSTEM')),
    content_type TEXT NOT NULL CHECK (
        content_type IN (
            'USER_QUESTION',
            'COPILOT_ANSWER',
            'DETERMINISTIC_FALLBACK',
            'EVIDENCE_VERSION_NOTICE',
            'LIFECYCLE_NOTICE'
        )
    ),
    content_json JSONB NOT NULL,
    interaction_id TEXT,
    client_request_id TEXT,
    response_to_message_id TEXT,
    evidence_package_id TEXT,
    evidence_package_version INTEGER
        CHECK (evidence_package_version IS NULL OR evidence_package_version > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (thread_id, incident_id)
        REFERENCES copilot_threads (thread_id, incident_id) ON DELETE CASCADE,
    FOREIGN KEY (response_to_message_id)
        REFERENCES copilot_messages (message_id) ON DELETE SET NULL,
    UNIQUE (thread_id, sequence)
);

CREATE INDEX IF NOT EXISTS ix_copilot_messages_thread_created
    ON copilot_messages (thread_id, sequence, created_at);
CREATE INDEX IF NOT EXISTS ix_copilot_messages_incident_created
    ON copilot_messages (incident_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_copilot_messages_package
    ON copilot_messages (incident_id, evidence_package_id, evidence_package_version)
    WHERE evidence_package_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_copilot_messages_thread_client_request
    ON copilot_messages (thread_id, client_request_id)
    WHERE client_request_id IS NOT NULL AND role = 'USER';
CREATE UNIQUE INDEX IF NOT EXISTS ux_copilot_messages_thread_interaction_role
    ON copilot_messages (thread_id, interaction_id, role)
    WHERE interaction_id IS NOT NULL AND role = 'ASSISTANT';

ALTER TABLE copilot_interactions
    ADD COLUMN IF NOT EXISTS thread_id TEXT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_copilot_interactions_thread'
    ) THEN
        ALTER TABLE copilot_interactions
            ADD CONSTRAINT fk_copilot_interactions_thread
            FOREIGN KEY (thread_id) REFERENCES copilot_threads (thread_id)
            ON DELETE SET NULL;
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS ix_copilot_interactions_thread_created
    ON copilot_interactions (thread_id, created_at DESC)
    WHERE thread_id IS NOT NULL;

-- Preserve compatible v1 interaction/message history under one deterministic
-- incident-owned thread. These inserts are safe to rerun and do not replace rows.
INSERT INTO copilot_threads (
    thread_id,
    incident_id,
    latest_evidence_package_id,
    latest_evidence_package_version,
    created_at,
    updated_at
)
SELECT
    'thr_legacy_' || substr(md5(incidents.incident_id), 1, 24),
    incidents.incident_id,
    latest.evidence_package_id,
    latest.evidence_package_version,
    COALESCE(latest.created_at, now()),
    COALESCE(latest.updated_at, now())
FROM incidents
LEFT JOIN LATERAL (
    SELECT
        interaction.evidence_package_id,
        interaction.evidence_package_version,
        interaction.created_at,
        interaction.updated_at
    FROM copilot_interactions AS interaction
    WHERE interaction.incident_id = incidents.incident_id
    ORDER BY interaction.created_at DESC
    LIMIT 1
) AS latest ON true
WHERE latest.evidence_package_id IS NOT NULL
   OR EXISTS (
       SELECT 1
       FROM runtime_resources AS resource
       WHERE resource.resource_type = 'copilot_messages'
         AND resource.resource_key = incidents.incident_id
   )
ON CONFLICT (incident_id) DO NOTHING;

UPDATE copilot_interactions AS interaction
SET thread_id = thread.thread_id
FROM copilot_threads AS thread
WHERE interaction.thread_id IS NULL
  AND interaction.incident_id = thread.incident_id;

INSERT INTO copilot_messages (
    message_id,
    thread_id,
    incident_id,
    sequence,
    role,
    content_type,
    content_json,
    interaction_id,
    evidence_package_id,
    evidence_package_version,
    created_at
)
SELECT
    COALESCE(item.value ->> 'message_id', 'msg_legacy_' || substr(md5(item.value::text), 1, 24)),
    thread.thread_id,
    thread.incident_id,
    item.ordinality,
    'ASSISTANT',
    CASE
        WHEN item.value ->> 'status' = 'DETERMINISTIC_FALLBACK'
            THEN 'DETERMINISTIC_FALLBACK'
        ELSE 'COPILOT_ANSWER'
    END,
    item.value,
    item.value ->> 'interaction_id',
    item.value ->> 'evidence_package_id',
    NULLIF(item.value ->> 'evidence_package_version', '')::integer,
    COALESCE(NULLIF(item.value ->> 'created_at', '')::timestamptz, now())
FROM copilot_threads AS thread
JOIN runtime_resources AS resource
  ON resource.resource_type = 'copilot_messages'
 AND resource.resource_key = thread.incident_id
CROSS JOIN LATERAL jsonb_array_elements(
    COALESCE(resource.payload_json -> 'items', '[]'::jsonb)
) WITH ORDINALITY AS item(value, ordinality)
ON CONFLICT DO NOTHING;

COMMIT;
