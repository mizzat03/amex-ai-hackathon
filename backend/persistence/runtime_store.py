"""PostgreSQL-backed resource projections for the frozen API boundary."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from psycopg import Connection, connect
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


class RuntimeStore(Protocol):
    async def migrate(self) -> None: ...

    async def ping(self) -> bool: ...

    async def get_resource(
        self, resource_type: str, resource_key: str
    ) -> dict[str, Any] | None: ...

    async def list_resources(self, resource_type: str) -> list[dict[str, Any]]: ...

    async def put_resource(
        self, resource_type: str, resource_key: str, payload: dict[str, Any], version: int = 1
    ) -> None: ...

    async def get_command(
        self, command_scope: str, client_request_id: str
    ) -> dict[str, Any] | None: ...

    async def put_command(
        self, command_scope: str, client_request_id: str, payload: dict[str, Any]
    ) -> None: ...

    async def append_ws_event(
        self, event_id: str, event_type: str, occurred_at: datetime, payload: dict[str, Any]
    ) -> int: ...

    async def save_human_review(self, incident_id: str, payload: dict[str, Any]) -> None: ...

    async def save_feedback(
        self, message_id: str, version: int, payload: dict[str, Any]
    ) -> None: ...

    async def save_copilot_interaction(
        self,
        audit: dict[str, Any],
        raw_output: dict[str, Any] | None,
        validated_output: dict[str, Any] | None,
    ) -> None: ...

    async def get_or_create_copilot_thread(
        self, incident_id: str, created_at: datetime | str
    ) -> dict[str, Any]: ...

    async def get_copilot_thread(self, incident_id: str) -> dict[str, Any] | None: ...

    async def update_copilot_thread(
        self,
        thread_id: str,
        incident_id: str,
        *,
        history_digest: dict[str, Any],
        evidence_package_id: str | None,
        evidence_package_version: int | None,
        updated_at: datetime | str,
    ) -> dict[str, Any]: ...

    async def append_copilot_message(
        self, thread_id: str, incident_id: str, message: dict[str, Any]
    ) -> dict[str, Any]: ...

    async def upsert_copilot_response(
        self, thread_id: str, incident_id: str, message: dict[str, Any]
    ) -> dict[str, Any]: ...

    async def list_copilot_messages(
        self,
        thread_id: str,
        incident_id: str,
        *,
        after_sequence: int | None,
        limit: int,
    ) -> tuple[list[dict[str, Any]], int | None]: ...

    async def get_copilot_message(
        self, incident_id: str, message_id: str
    ) -> dict[str, Any] | None: ...

    async def accept_copilot_request(
        self,
        *,
        thread_id: str,
        incident_id: str,
        command_scope: str,
        client_request_id: str,
        user_message: dict[str, Any],
        transition_message: dict[str, Any] | None,
        interaction: dict[str, Any],
        request_record: dict[str, Any],
        response: dict[str, Any],
        evidence_package_id: str,
        evidence_package_version: int,
        updated_at: datetime | str,
    ) -> dict[str, Any]: ...

    async def save_evidence_package(self, package: dict[str, Any]) -> None: ...

    async def get_evidence_package(
        self, incident_id: str, evidence_package_id: str, package_version: int
    ) -> dict[str, Any] | None: ...

    async def get_latest_evidence_package(
        self,
        incident_id: str,
        completeness: tuple[str, ...] = ("COMPLETE", "PARTIAL"),
    ) -> dict[str, Any] | None: ...

    async def reset_ingestion_data(
        self,
        clean_overview: dict[str, Any],
        clean_metric_history: dict[str, Any],
    ) -> None: ...

    async def reset_synthetic_data(self) -> None: ...


class PostgresRuntimeStore:
    """Parameterized psycopg store with blocking driver calls isolated in worker threads."""

    def __init__(self, dsn: str, migrations_dir: Path | None = None) -> None:
        self._dsn = dsn
        self._migrations_dir = migrations_dir or Path(__file__).with_name("migrations")

    def _connect(self) -> Connection[dict[str, Any]]:
        return connect(self._dsn, autocommit=True, row_factory=dict_row)

    async def migrate(self) -> None:
        await asyncio.to_thread(self._migrate_sync)

    def _migrate_sync(self) -> None:
        with self._connect() as connection:
            for migration_path in sorted(self._migrations_dir.glob("*.sql")):
                connection.execute(migration_path.read_text(encoding="utf-8"))

    async def ping(self) -> bool:
        return await asyncio.to_thread(self._ping_sync)

    def _ping_sync(self) -> bool:
        try:
            with self._connect() as connection:
                row = connection.execute("SELECT 1 AS ready").fetchone()
                return bool(row and row["ready"] == 1)
        except Exception:
            return False

    async def get_resource(self, resource_type: str, resource_key: str) -> dict[str, Any] | None:
        return await asyncio.to_thread(self._get_resource_sync, resource_type, resource_key)

    def _get_resource_sync(self, resource_type: str, resource_key: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload_json
                FROM runtime_resources
                WHERE resource_type = %s AND resource_key = %s
                """,
                (resource_type, resource_key),
            ).fetchone()
        return dict(row["payload_json"]) if row else None

    async def list_resources(self, resource_type: str) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._list_resources_sync, resource_type)

    def _list_resources_sync(self, resource_type: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload_json
                FROM runtime_resources
                WHERE resource_type = %s
                ORDER BY updated_at DESC, resource_key ASC
                """,
                (resource_type,),
            ).fetchall()
        return [dict(row["payload_json"]) for row in rows]

    async def put_resource(
        self, resource_type: str, resource_key: str, payload: dict[str, Any], version: int = 1
    ) -> None:
        await asyncio.to_thread(
            self._put_resource_sync, resource_type, resource_key, payload, version
        )

    def _put_resource_sync(
        self, resource_type: str, resource_key: str, payload: dict[str, Any], version: int
    ) -> None:
        with self._connect() as connection, connection.transaction():
            owner = connection.execute(
                """
                INSERT INTO runtime_resources (
                    resource_type, resource_key, version, payload_json, updated_at
                ) VALUES (%s, %s, %s, %s, now())
                ON CONFLICT (resource_type, resource_key) DO UPDATE SET
                    version = EXCLUDED.version,
                    payload_json = EXCLUDED.payload_json,
                    updated_at = now()
                """,
                (resource_type, resource_key, version, Jsonb(payload)),
            )
            if resource_type == "incident":
                incident = dict(payload["incident"])
                connection.execute(
                    """
                    INSERT INTO incidents (
                        incident_id, lifecycle, severity, started_at, updated_at, projection_json
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (incident_id) DO UPDATE SET
                        lifecycle = EXCLUDED.lifecycle,
                        severity = EXCLUDED.severity,
                        started_at = EXCLUDED.started_at,
                        updated_at = EXCLUDED.updated_at,
                        projection_json = EXCLUDED.projection_json
                    """,
                    (
                        resource_key,
                        incident["lifecycle"],
                        incident["severity"],
                        incident["started_at"],
                        incident["updated_at"],
                        Jsonb(payload),
                    ),
                )

    async def get_command(
        self, command_scope: str, client_request_id: str
    ) -> dict[str, Any] | None:
        return await asyncio.to_thread(self._get_command_sync, command_scope, client_request_id)

    def _get_command_sync(
        self, command_scope: str, client_request_id: str
    ) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT response_json
                FROM command_results
                WHERE command_scope = %s AND client_request_id = %s
                """,
                (command_scope, client_request_id),
            ).fetchone()
        return dict(row["response_json"]) if row else None

    async def put_command(
        self, command_scope: str, client_request_id: str, payload: dict[str, Any]
    ) -> None:
        await asyncio.to_thread(self._put_command_sync, command_scope, client_request_id, payload)

    def _put_command_sync(
        self, command_scope: str, client_request_id: str, payload: dict[str, Any]
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO command_results (command_scope, client_request_id, response_json)
                VALUES (%s, %s, %s)
                ON CONFLICT (command_scope, client_request_id) DO NOTHING
                """,
                (command_scope, client_request_id, Jsonb(payload)),
            )

    async def append_ws_event(
        self, event_id: str, event_type: str, occurred_at: datetime, payload: dict[str, Any]
    ) -> int:
        return await asyncio.to_thread(
            self._append_ws_event_sync, event_id, event_type, occurred_at, payload
        )

    def _append_ws_event_sync(
        self, event_id: str, event_type: str, occurred_at: datetime, payload: dict[str, Any]
    ) -> int:
        with self._connect() as connection:
            row = connection.execute(
                """
                INSERT INTO websocket_events (event_id, event_type, occurred_at, payload_json)
                VALUES (%s, %s, %s, %s)
                RETURNING sequence
                """,
                (event_id, event_type, occurred_at, Jsonb(payload)),
            ).fetchone()
        if row is None:
            raise RuntimeError("websocket event insert did not return a sequence")
        return int(row["sequence"])

    async def save_human_review(self, incident_id: str, payload: dict[str, Any]) -> None:
        await asyncio.to_thread(self._save_human_review_sync, incident_id, payload)

    def _save_human_review_sync(self, incident_id: str, payload: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO human_reviews (
                    incident_id, review_version, hypothesis_id, status, note,
                    reviewed_by, reviewed_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (incident_id, review_version) DO NOTHING
                """,
                (
                    incident_id,
                    payload["version"],
                    payload["hypothesis_id"],
                    payload["status"],
                    payload.get("note"),
                    payload["reviewed_by"],
                    payload["updated_at"],
                ),
            )

    async def save_feedback(self, message_id: str, version: int, payload: dict[str, Any]) -> None:
        await asyncio.to_thread(self._save_feedback_sync, message_id, version, payload)

    def _save_feedback_sync(self, message_id: str, version: int, payload: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO copilot_feedback (
                    message_id, feedback_version, feedback_json, created_at
                ) VALUES (%s, %s, %s, now())
                ON CONFLICT (message_id, feedback_version) DO NOTHING
                """,
                (message_id, version, Jsonb(payload)),
            )

    async def save_copilot_interaction(
        self,
        audit: dict[str, Any],
        raw_output: dict[str, Any] | None,
        validated_output: dict[str, Any] | None,
    ) -> None:
        await asyncio.to_thread(
            self._save_copilot_interaction_sync, audit, raw_output, validated_output
        )

    def _save_copilot_interaction_sync(
        self,
        audit: dict[str, Any],
        raw_output: dict[str, Any] | None,
        validated_output: dict[str, Any] | None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO copilot_interactions (
                    interaction_id, incident_id, evidence_package_id,
                    evidence_package_version, status, provider, model_id,
                    configuration_version, raw_output_json, validated_output_json,
                    validation_audit_json, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (interaction_id) DO UPDATE SET
                    status = EXCLUDED.status,
                    provider = EXCLUDED.provider,
                    model_id = EXCLUDED.model_id,
                    raw_output_json = EXCLUDED.raw_output_json,
                    validated_output_json = EXCLUDED.validated_output_json,
                    validation_audit_json = EXCLUDED.validation_audit_json,
                    updated_at = EXCLUDED.updated_at
                """,
                (
                    audit["interaction_id"],
                    audit["incident_id"],
                    audit["evidence_package_id"],
                    audit["evidence_package_version"],
                    audit["status"],
                    audit["provider"],
                    audit["model_id"],
                    audit["configuration_version"],
                    Jsonb(raw_output) if raw_output is not None else None,
                    Jsonb(validated_output) if validated_output is not None else None,
                    Jsonb(audit),
                    audit["created_at"],
                    audit["completed_at"],
                ),
            )

    @staticmethod
    def _thread_payload(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "thread_id": row["thread_id"],
            "incident_id": row["incident_id"],
            "latest_evidence_package_id": row.get("latest_evidence_package_id"),
            "latest_evidence_package_version": row.get("latest_evidence_package_version"),
            "history_digest": dict(row.get("history_digest_json") or {}),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _message_payload(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "message_id": row["message_id"],
            "thread_id": row["thread_id"],
            "incident_id": row["incident_id"],
            "sequence": int(row["sequence"]),
            "role": row["role"],
            "content_type": row["content_type"],
            "content": dict(row["content_json"]),
            "interaction_id": row.get("interaction_id"),
            "client_request_id": row.get("client_request_id"),
            "response_to_message_id": row.get("response_to_message_id"),
            "evidence_package_id": row.get("evidence_package_id"),
            "evidence_package_version": row.get("evidence_package_version"),
            "created_at": row["created_at"],
        }

    async def get_or_create_copilot_thread(
        self, incident_id: str, created_at: datetime | str
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._get_or_create_copilot_thread_sync, incident_id, created_at
        )

    def _get_or_create_copilot_thread_sync(
        self, incident_id: str, created_at: datetime | str
    ) -> dict[str, Any]:
        with self._connect() as connection, connection.transaction():
            connection.execute(
                """
                INSERT INTO copilot_threads (thread_id, incident_id, created_at, updated_at)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (incident_id) DO NOTHING
                """,
                (f"thr_{uuid4().hex}", incident_id, created_at, created_at),
            )
            row = connection.execute(
                """
                SELECT thread_id, incident_id, latest_evidence_package_id,
                       latest_evidence_package_version, history_digest_json,
                       created_at, updated_at
                FROM copilot_threads
                WHERE incident_id = %s
                """,
                (incident_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("canonical copilot thread could not be created")
        return self._thread_payload(row)

    async def get_copilot_thread(self, incident_id: str) -> dict[str, Any] | None:
        return await asyncio.to_thread(self._get_copilot_thread_sync, incident_id)

    def _get_copilot_thread_sync(self, incident_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT thread_id, incident_id, latest_evidence_package_id,
                       latest_evidence_package_version, history_digest_json,
                       created_at, updated_at
                FROM copilot_threads
                WHERE incident_id = %s
                """,
                (incident_id,),
            ).fetchone()
        return self._thread_payload(row) if row else None

    async def update_copilot_thread(
        self,
        thread_id: str,
        incident_id: str,
        *,
        history_digest: dict[str, Any],
        evidence_package_id: str | None,
        evidence_package_version: int | None,
        updated_at: datetime | str,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._update_copilot_thread_sync,
            thread_id,
            incident_id,
            history_digest,
            evidence_package_id,
            evidence_package_version,
            updated_at,
        )

    def _update_copilot_thread_sync(
        self,
        thread_id: str,
        incident_id: str,
        history_digest: dict[str, Any],
        evidence_package_id: str | None,
        evidence_package_version: int | None,
        updated_at: datetime | str,
    ) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                """
                UPDATE copilot_threads
                SET history_digest_json = %s,
                    latest_evidence_package_id = %s,
                    latest_evidence_package_version = %s,
                    updated_at = %s
                WHERE thread_id = %s AND incident_id = %s
                RETURNING thread_id, incident_id, latest_evidence_package_id,
                          latest_evidence_package_version, history_digest_json,
                          created_at, updated_at
                """,
                (
                    Jsonb(history_digest),
                    evidence_package_id,
                    evidence_package_version,
                    updated_at,
                    thread_id,
                    incident_id,
                ),
            ).fetchone()
        if row is None:
            raise KeyError("canonical copilot thread does not belong to incident")
        return self._thread_payload(row)

    async def append_copilot_message(
        self, thread_id: str, incident_id: str, message: dict[str, Any]
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._append_copilot_message_sync, thread_id, incident_id, message
        )

    def _append_copilot_message_sync(
        self, thread_id: str, incident_id: str, message: dict[str, Any]
    ) -> dict[str, Any]:
        with self._connect() as connection, connection.transaction():
            owner = connection.execute(
                """
                SELECT thread_id FROM copilot_threads
                WHERE thread_id = %s AND incident_id = %s
                FOR UPDATE
                """,
                (thread_id, incident_id),
            ).fetchone()
            if owner is None:
                raise KeyError("canonical copilot thread does not belong to incident")
            client_request_id = message.get("client_request_id")
            if client_request_id is not None:
                existing = connection.execute(
                    """
                    SELECT * FROM copilot_messages
                    WHERE thread_id = %s AND incident_id = %s
                      AND client_request_id = %s AND role = 'USER'
                    """,
                    (thread_id, incident_id, client_request_id),
                ).fetchone()
                if existing is not None:
                    return self._message_payload(existing)
            sequence_row = connection.execute(
                """
                SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence
                FROM copilot_messages WHERE thread_id = %s
                """,
                (thread_id,),
            ).fetchone()
            if sequence_row is None:
                raise RuntimeError("message sequence could not be allocated")
            connection.execute(
                """
                INSERT INTO copilot_messages (
                    message_id, thread_id, incident_id, sequence, role, content_type,
                    content_json, interaction_id, client_request_id,
                    response_to_message_id, evidence_package_id,
                    evidence_package_version, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                (
                    message["message_id"],
                    thread_id,
                    incident_id,
                    int(sequence_row["next_sequence"]),
                    message["role"],
                    message["content_type"],
                    Jsonb(message["content"]),
                    message.get("interaction_id"),
                    client_request_id,
                    message.get("response_to_message_id"),
                    message.get("evidence_package_id"),
                    message.get("evidence_package_version"),
                    message["created_at"],
                ),
            )
            row = connection.execute(
                "SELECT * FROM copilot_messages WHERE message_id = %s AND incident_id = %s",
                (message["message_id"], incident_id),
            ).fetchone()
            if row is None and client_request_id is not None:
                row = connection.execute(
                    """
                    SELECT * FROM copilot_messages
                    WHERE thread_id = %s AND client_request_id = %s AND role = 'USER'
                    """,
                    (thread_id, client_request_id),
                ).fetchone()
        if row is None:
            raise RuntimeError("copilot message could not be appended")
        return self._message_payload(row)

    async def upsert_copilot_response(
        self, thread_id: str, incident_id: str, message: dict[str, Any]
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._upsert_copilot_response_sync, thread_id, incident_id, message
        )

    def _upsert_copilot_response_sync(
        self, thread_id: str, incident_id: str, message: dict[str, Any]
    ) -> dict[str, Any]:
        interaction_id = str(message["interaction_id"])
        with self._connect() as connection, connection.transaction():
            owner = connection.execute(
                """
                SELECT thread_id FROM copilot_threads
                WHERE thread_id = %s AND incident_id = %s
                FOR UPDATE
                """,
                (thread_id, incident_id),
            ).fetchone()
            if owner is None:
                raise KeyError("canonical copilot thread does not belong to incident")
            existing = connection.execute(
                """
                SELECT * FROM copilot_messages
                WHERE thread_id = %s AND incident_id = %s
                  AND interaction_id = %s AND role = 'ASSISTANT'
                """,
                (thread_id, incident_id, interaction_id),
            ).fetchone()
            if existing is not None:
                row = connection.execute(
                    """
                    UPDATE copilot_messages
                    SET content_type = %s, content_json = %s,
                        evidence_package_id = %s, evidence_package_version = %s
                    WHERE message_id = %s AND incident_id = %s
                    RETURNING *
                    """,
                    (
                        message["content_type"],
                        Jsonb(message["content"]),
                        message.get("evidence_package_id"),
                        message.get("evidence_package_version"),
                        existing["message_id"],
                        incident_id,
                    ),
                ).fetchone()
            else:
                sequence_row = connection.execute(
                    """
                    SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence
                    FROM copilot_messages WHERE thread_id = %s
                    """,
                    (thread_id,),
                ).fetchone()
                if sequence_row is None:
                    raise RuntimeError("message sequence could not be allocated")
                row = connection.execute(
                    """
                    INSERT INTO copilot_messages (
                        message_id, thread_id, incident_id, sequence, role, content_type,
                        content_json, interaction_id, response_to_message_id,
                        evidence_package_id, evidence_package_version, created_at
                    ) VALUES (%s, %s, %s, %s, 'ASSISTANT', %s, %s, %s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (
                        message["message_id"],
                        thread_id,
                        incident_id,
                        int(sequence_row["next_sequence"]),
                        message["content_type"],
                        Jsonb(message["content"]),
                        interaction_id,
                        message.get("response_to_message_id"),
                        message.get("evidence_package_id"),
                        message.get("evidence_package_version"),
                        message["created_at"],
                    ),
                ).fetchone()
        if row is None:
            raise RuntimeError("copilot response could not be stored")
        return self._message_payload(row)

    async def list_copilot_messages(
        self,
        thread_id: str,
        incident_id: str,
        *,
        after_sequence: int | None,
        limit: int,
    ) -> tuple[list[dict[str, Any]], int | None]:
        return await asyncio.to_thread(
            self._list_copilot_messages_sync,
            thread_id,
            incident_id,
            after_sequence,
            limit,
        )

    def _list_copilot_messages_sync(
        self,
        thread_id: str,
        incident_id: str,
        after_sequence: int | None,
        limit: int,
    ) -> tuple[list[dict[str, Any]], int | None]:
        if not 1 <= limit <= 100:
            raise ValueError("message page limit must be between 1 and 100")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM copilot_messages
                WHERE thread_id = %s AND incident_id = %s AND sequence > %s
                ORDER BY sequence ASC
                LIMIT %s
                """,
                (thread_id, incident_id, after_sequence or 0, limit + 1),
            ).fetchall()
        has_more = len(rows) > limit
        selected = rows[:limit]
        next_sequence = int(selected[-1]["sequence"]) if has_more and selected else None
        return [self._message_payload(row) for row in selected], next_sequence

    async def get_copilot_message(
        self, incident_id: str, message_id: str
    ) -> dict[str, Any] | None:
        return await asyncio.to_thread(
            self._get_copilot_message_sync, incident_id, message_id
        )

    def _get_copilot_message_sync(
        self, incident_id: str, message_id: str
    ) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM copilot_messages
                WHERE incident_id = %s AND message_id = %s
                """,
                (incident_id, message_id),
            ).fetchone()
        return self._message_payload(row) if row else None

    async def accept_copilot_request(
        self,
        *,
        thread_id: str,
        incident_id: str,
        command_scope: str,
        client_request_id: str,
        user_message: dict[str, Any],
        transition_message: dict[str, Any] | None,
        interaction: dict[str, Any],
        request_record: dict[str, Any],
        response: dict[str, Any],
        evidence_package_id: str,
        evidence_package_version: int,
        updated_at: datetime | str,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._accept_copilot_request_sync,
            thread_id,
            incident_id,
            command_scope,
            client_request_id,
            user_message,
            transition_message,
            interaction,
            request_record,
            response,
            evidence_package_id,
            evidence_package_version,
            updated_at,
        )

    def _accept_copilot_request_sync(
        self,
        thread_id: str,
        incident_id: str,
        command_scope: str,
        client_request_id: str,
        user_message: dict[str, Any],
        transition_message: dict[str, Any] | None,
        interaction: dict[str, Any],
        request_record: dict[str, Any],
        response: dict[str, Any],
        evidence_package_id: str,
        evidence_package_version: int,
        updated_at: datetime | str,
    ) -> dict[str, Any]:
        with self._connect() as connection, connection.transaction():
            owner = connection.execute(
                """
                SELECT thread_id FROM copilot_threads
                WHERE thread_id = %s AND incident_id = %s
                FOR UPDATE
                """,
                (thread_id, incident_id),
            ).fetchone()
            if owner is None:
                raise KeyError("canonical copilot thread does not belong to incident")
            cached = connection.execute(
                """
                SELECT response_json FROM command_results
                WHERE command_scope = %s AND client_request_id = %s
                """,
                (command_scope, client_request_id),
            ).fetchone()
            if cached is not None:
                return dict(cached["response_json"])

            def insert_message(message: dict[str, Any]) -> None:
                next_row = connection.execute(
                    """
                    SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence
                    FROM copilot_messages WHERE thread_id = %s
                    """,
                    (thread_id,),
                ).fetchone()
                if next_row is None:
                    raise RuntimeError("message sequence could not be allocated")
                connection.execute(
                    """
                    INSERT INTO copilot_messages (
                        message_id, thread_id, incident_id, sequence, role, content_type,
                        content_json, interaction_id, client_request_id,
                        response_to_message_id, evidence_package_id,
                        evidence_package_version, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (
                        message["message_id"],
                        thread_id,
                        incident_id,
                        int(next_row["next_sequence"]),
                        message["role"],
                        message["content_type"],
                        Jsonb(message["content"]),
                        message.get("interaction_id"),
                        message.get("client_request_id"),
                        message.get("response_to_message_id"),
                        message.get("evidence_package_id"),
                        message.get("evidence_package_version"),
                        message["created_at"],
                    ),
                )

            if transition_message is not None:
                insert_message(transition_message)
            insert_message(user_message)
            for resource_type, resource_key, payload in (
                ("copilot_interaction", interaction["interaction_id"], interaction),
                ("copilot_request", interaction["interaction_id"], request_record),
            ):
                connection.execute(
                    """
                    INSERT INTO runtime_resources (
                        resource_type, resource_key, version, payload_json, updated_at
                    ) VALUES (%s, %s, 1, %s, now())
                    ON CONFLICT (resource_type, resource_key) DO UPDATE SET
                        payload_json = EXCLUDED.payload_json,
                        updated_at = now()
                    """,
                    (resource_type, resource_key, Jsonb(payload)),
                )
            connection.execute(
                """
                UPDATE copilot_threads
                SET latest_evidence_package_id = %s,
                    latest_evidence_package_version = %s,
                    updated_at = %s
                WHERE thread_id = %s AND incident_id = %s
                """,
                (
                    evidence_package_id,
                    evidence_package_version,
                    updated_at,
                    thread_id,
                    incident_id,
                ),
            )
            connection.execute(
                """
                INSERT INTO command_results (
                    command_scope, client_request_id, response_json
                ) VALUES (%s, %s, %s)
                """,
                (command_scope, client_request_id, Jsonb(response)),
            )
        return deepcopy(response)

    async def save_evidence_package(self, package: dict[str, Any]) -> None:
        await asyncio.to_thread(self._save_evidence_package_sync, package)

    def _save_evidence_package_sync(self, package: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO evidence_packages (
                    evidence_package_id, incident_id, package_version, completeness,
                    schema_version, builder_configuration_version, generated_at, package_json
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (evidence_package_id, package_version) DO NOTHING
                """,
                (
                    package["evidence_package_id"],
                    package["incident_id"],
                    package["package_version"],
                    package["completeness"],
                    package["schema_version"],
                    package["builder_configuration_version"],
                    package["generated_at"],
                    Jsonb(package),
                ),
            )

    async def get_evidence_package(
        self, incident_id: str, evidence_package_id: str, package_version: int
    ) -> dict[str, Any] | None:
        return await asyncio.to_thread(
            self._get_evidence_package_sync,
            incident_id,
            evidence_package_id,
            package_version,
        )

    def _get_evidence_package_sync(
        self, incident_id: str, evidence_package_id: str, package_version: int
    ) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT package_json
                FROM evidence_packages
                WHERE incident_id = %s
                  AND evidence_package_id = %s
                  AND package_version = %s
                """,
                (incident_id, evidence_package_id, package_version),
            ).fetchone()
        return dict(row["package_json"]) if row else None

    async def get_latest_evidence_package(
        self,
        incident_id: str,
        completeness: tuple[str, ...] = ("COMPLETE", "PARTIAL"),
    ) -> dict[str, Any] | None:
        return await asyncio.to_thread(
            self._get_latest_evidence_package_sync, incident_id, completeness
        )

    def _get_latest_evidence_package_sync(
        self, incident_id: str, completeness: tuple[str, ...]
    ) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT package_json
                FROM evidence_packages
                WHERE incident_id = %s AND completeness = ANY(%s)
                ORDER BY package_version DESC, generated_at DESC
                LIMIT 1
                """,
                (incident_id, list(completeness)),
            ).fetchone()
        return dict(row["package_json"]) if row else None

    async def reset_ingestion_data(
        self,
        clean_overview: dict[str, Any],
        clean_metric_history: dict[str, Any],
    ) -> None:
        """Remove projections that an in-flight pre-reset ingestion batch can recreate."""
        await asyncio.to_thread(
            self._reset_ingestion_data_sync,
            clean_overview,
            clean_metric_history,
        )

    def _reset_ingestion_data_sync(
        self,
        clean_overview: dict[str, Any],
        clean_metric_history: dict[str, Any],
    ) -> None:
        ingestion_resource_types = (
            "overview",
            "metric_history",
            "incident_summary",
            "incident",
            "evidence",
            "copilot_messages",
            "pipeline_state",
        )
        with self._connect() as connection, connection.transaction():
            connection.execute(
                "DELETE FROM runtime_resources WHERE resource_type = ANY(%s)",
                (list(ingestion_resource_types),),
            )
            connection.execute("DELETE FROM evidence_packages")
            connection.execute("DELETE FROM incidents")
            for resource_type, resource_key, payload in (
                ("overview", "current", clean_overview),
                (
                    "metric_history",
                    str(clean_metric_history["metric_key"]),
                    clean_metric_history,
                ),
            ):
                connection.execute(
                    """
                    INSERT INTO runtime_resources (
                        resource_type, resource_key, version, payload_json, updated_at
                    ) VALUES (%s, %s, 1, %s, now())
                    """,
                    (resource_type, resource_key, Jsonb(payload)),
                )

    async def reset_synthetic_data(self) -> None:
        """Delete only the application's allowlisted synthetic runtime records."""
        await asyncio.to_thread(self._reset_synthetic_data_sync)

    def _reset_synthetic_data_sync(self) -> None:
        synthetic_resource_types = (
            "overview",
            "metric_history",
            "incident_summary",
            "incident",
            "evidence",
            "copilot_messages",
            "copilot_interaction",
            "copilot_request",
            "copilot_retry_used",
            "copilot_tool_evidence",
            "copilot_feedback",
            "feedback_audit",
            "copilot_audit",
            "human_review",
            "simulation",
            "pipeline_state",
        )
        synthetic_tables = (
            "copilot_messages",
            "copilot_threads",
            "evidence_packages",
            "incidents",
            "metric_history",
            "detector_evaluations",
            "operational_events",
            "investigation_results",
            "human_reviews",
            "copilot_interactions",
            "copilot_feedback",
            "command_results",
            "websocket_events",
        )
        with self._connect() as connection, connection.transaction():
            connection.execute(
                "DELETE FROM runtime_resources WHERE resource_type = ANY(%s)",
                (list(synthetic_resource_types),),
            )
            # These tables contain synthetic runtime data only. Truncating the fixed
            # allowlist together avoids a slow row-by-row purge after a busy demo and
            # satisfies all foreign-key relationships without an unbounded CASCADE.
            connection.execute(
                f"TRUNCATE TABLE {', '.join(synthetic_tables)} RESTART IDENTITY"
            )


class InMemoryRuntimeStore:
    """Test double with the same clone-on-read semantics as PostgreSQL JSONB."""

    def __init__(self) -> None:
        self._resources: dict[tuple[str, str], dict[str, Any]] = {}
        self._commands: dict[tuple[str, str], dict[str, Any]] = {}
        self._copilot_threads: dict[str, dict[str, Any]] = {}
        self._copilot_messages: dict[str, dict[str, Any]] = {}
        self._evidence_packages: dict[tuple[str, str, int], dict[str, Any]] = {}
        self._copilot_lock = asyncio.Lock()
        self._sequence = 0

    async def migrate(self) -> None:
        return None

    async def ping(self) -> bool:
        return True

    async def get_resource(self, resource_type: str, resource_key: str) -> dict[str, Any] | None:
        payload = self._resources.get((resource_type, resource_key))
        return deepcopy(payload) if payload is not None else None

    async def list_resources(self, resource_type: str) -> list[dict[str, Any]]:
        return [
            deepcopy(payload)
            for (stored_type, _), payload in self._resources.items()
            if stored_type == resource_type
        ]

    async def put_resource(
        self, resource_type: str, resource_key: str, payload: dict[str, Any], version: int = 1
    ) -> None:
        del version
        self._resources[(resource_type, resource_key)] = deepcopy(payload)

    async def get_command(
        self, command_scope: str, client_request_id: str
    ) -> dict[str, Any] | None:
        payload = self._commands.get((command_scope, client_request_id))
        return deepcopy(payload) if payload is not None else None

    async def put_command(
        self, command_scope: str, client_request_id: str, payload: dict[str, Any]
    ) -> None:
        self._commands.setdefault((command_scope, client_request_id), deepcopy(payload))

    async def append_ws_event(
        self, event_id: str, event_type: str, occurred_at: datetime, payload: dict[str, Any]
    ) -> int:
        del event_id, event_type, occurred_at, payload
        self._sequence += 1
        return self._sequence

    async def save_human_review(self, incident_id: str, payload: dict[str, Any]) -> None:
        await self.put_resource("human_review", incident_id, payload, int(payload["version"]))

    async def save_feedback(self, message_id: str, version: int, payload: dict[str, Any]) -> None:
        await self.put_resource("feedback_audit", f"{message_id}:{version}", payload, version)

    async def save_copilot_interaction(
        self,
        audit: dict[str, Any],
        raw_output: dict[str, Any] | None,
        validated_output: dict[str, Any] | None,
    ) -> None:
        payload = {
            "audit": deepcopy(audit),
            "raw_output": deepcopy(raw_output),
            "validated_output": deepcopy(validated_output),
        }
        await self.put_resource("copilot_audit", audit["interaction_id"], payload)

    async def get_or_create_copilot_thread(
        self, incident_id: str, created_at: datetime | str
    ) -> dict[str, Any]:
        async with self._copilot_lock:
            thread = self._copilot_threads.get(incident_id)
            if thread is None:
                thread = {
                    "thread_id": f"thr_{uuid4().hex}",
                    "incident_id": incident_id,
                    "latest_evidence_package_id": None,
                    "latest_evidence_package_version": None,
                    "history_digest": {},
                    "created_at": created_at,
                    "updated_at": created_at,
                }
                self._copilot_threads[incident_id] = thread
            return deepcopy(thread)

    async def get_copilot_thread(self, incident_id: str) -> dict[str, Any] | None:
        thread = self._copilot_threads.get(incident_id)
        return deepcopy(thread) if thread is not None else None

    async def update_copilot_thread(
        self,
        thread_id: str,
        incident_id: str,
        *,
        history_digest: dict[str, Any],
        evidence_package_id: str | None,
        evidence_package_version: int | None,
        updated_at: datetime | str,
    ) -> dict[str, Any]:
        async with self._copilot_lock:
            thread = self._copilot_threads.get(incident_id)
            if thread is None or thread["thread_id"] != thread_id:
                raise KeyError("canonical copilot thread does not belong to incident")
            thread.update(
                {
                    "history_digest": deepcopy(history_digest),
                    "latest_evidence_package_id": evidence_package_id,
                    "latest_evidence_package_version": evidence_package_version,
                    "updated_at": updated_at,
                }
            )
            return deepcopy(thread)

    def _owned_thread(self, thread_id: str, incident_id: str) -> dict[str, Any]:
        thread = self._copilot_threads.get(incident_id)
        if thread is None or thread["thread_id"] != thread_id:
            raise KeyError("canonical copilot thread does not belong to incident")
        return thread

    async def append_copilot_message(
        self, thread_id: str, incident_id: str, message: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._copilot_lock:
            self._owned_thread(thread_id, incident_id)
            client_request_id = message.get("client_request_id")
            if client_request_id is not None:
                existing = next(
                    (
                        item
                        for item in self._copilot_messages.values()
                        if item["thread_id"] == thread_id
                        and item["role"] == "USER"
                        and item.get("client_request_id") == client_request_id
                    ),
                    None,
                )
                if existing is not None:
                    return deepcopy(existing)
            existing_by_id = self._copilot_messages.get(str(message["message_id"]))
            if existing_by_id is not None:
                if existing_by_id["incident_id"] != incident_id:
                    raise KeyError("copilot message belongs to another incident")
                return deepcopy(existing_by_id)
            sequence = 1 + max(
                (
                    int(item["sequence"])
                    for item in self._copilot_messages.values()
                    if item["thread_id"] == thread_id
                ),
                default=0,
            )
            stored = {
                **deepcopy(message),
                "thread_id": thread_id,
                "incident_id": incident_id,
                "sequence": sequence,
            }
            self._copilot_messages[str(message["message_id"])] = stored
            return deepcopy(stored)

    async def upsert_copilot_response(
        self, thread_id: str, incident_id: str, message: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._copilot_lock:
            self._owned_thread(thread_id, incident_id)
            interaction_id = message.get("interaction_id")
            existing = next(
                (
                    item
                    for item in self._copilot_messages.values()
                    if item["thread_id"] == thread_id
                    and item["role"] == "ASSISTANT"
                    and item.get("interaction_id") == interaction_id
                ),
                None,
            )
            if existing is not None:
                existing.update(
                    {
                        "content_type": message["content_type"],
                        "content": deepcopy(message["content"]),
                        "evidence_package_id": message.get("evidence_package_id"),
                        "evidence_package_version": message.get(
                            "evidence_package_version"
                        ),
                    }
                )
                return deepcopy(existing)
            sequence = 1 + max(
                (
                    int(item["sequence"])
                    for item in self._copilot_messages.values()
                    if item["thread_id"] == thread_id
                ),
                default=0,
            )
            stored = {
                **deepcopy(message),
                "thread_id": thread_id,
                "incident_id": incident_id,
                "sequence": sequence,
                "role": "ASSISTANT",
            }
            self._copilot_messages[str(message["message_id"])] = stored
            return deepcopy(stored)

    async def list_copilot_messages(
        self,
        thread_id: str,
        incident_id: str,
        *,
        after_sequence: int | None,
        limit: int,
    ) -> tuple[list[dict[str, Any]], int | None]:
        if not 1 <= limit <= 100:
            raise ValueError("message page limit must be between 1 and 100")
        self._owned_thread(thread_id, incident_id)
        messages = sorted(
            (
                item
                for item in self._copilot_messages.values()
                if item["thread_id"] == thread_id
                and int(item["sequence"]) > (after_sequence or 0)
            ),
            key=lambda item: int(item["sequence"]),
        )
        selected = messages[:limit]
        next_sequence = (
            int(selected[-1]["sequence"])
            if len(messages) > limit and selected
            else None
        )
        return deepcopy(selected), next_sequence

    async def get_copilot_message(
        self, incident_id: str, message_id: str
    ) -> dict[str, Any] | None:
        message = self._copilot_messages.get(message_id)
        if message is None or message["incident_id"] != incident_id:
            return None
        return deepcopy(message)

    async def accept_copilot_request(
        self,
        *,
        thread_id: str,
        incident_id: str,
        command_scope: str,
        client_request_id: str,
        user_message: dict[str, Any],
        transition_message: dict[str, Any] | None,
        interaction: dict[str, Any],
        request_record: dict[str, Any],
        response: dict[str, Any],
        evidence_package_id: str,
        evidence_package_version: int,
        updated_at: datetime | str,
    ) -> dict[str, Any]:
        async with self._copilot_lock:
            thread = self._owned_thread(thread_id, incident_id)
            command_key = (command_scope, client_request_id)
            cached = self._commands.get(command_key)
            if cached is not None:
                return deepcopy(cached)

            def insert_message(message: dict[str, Any]) -> None:
                existing = self._copilot_messages.get(str(message["message_id"]))
                if existing is not None:
                    return
                sequence = 1 + max(
                    (
                        int(item["sequence"])
                        for item in self._copilot_messages.values()
                        if item["thread_id"] == thread_id
                    ),
                    default=0,
                )
                self._copilot_messages[str(message["message_id"])] = {
                    **deepcopy(message),
                    "thread_id": thread_id,
                    "incident_id": incident_id,
                    "sequence": sequence,
                }

            if transition_message is not None:
                insert_message(transition_message)
            insert_message(user_message)
            self._resources[("copilot_interaction", interaction["interaction_id"])] = deepcopy(
                interaction
            )
            self._resources[("copilot_request", interaction["interaction_id"])] = deepcopy(
                request_record
            )
            thread.update(
                {
                    "latest_evidence_package_id": evidence_package_id,
                    "latest_evidence_package_version": evidence_package_version,
                    "updated_at": updated_at,
                }
            )
            self._commands[command_key] = deepcopy(response)
            return deepcopy(response)

    async def save_evidence_package(self, package: dict[str, Any]) -> None:
        key = (
            str(package["incident_id"]),
            str(package["evidence_package_id"]),
            int(package["package_version"]),
        )
        self._evidence_packages.setdefault(key, deepcopy(package))

    async def get_evidence_package(
        self, incident_id: str, evidence_package_id: str, package_version: int
    ) -> dict[str, Any] | None:
        package = self._evidence_packages.get(
            (incident_id, evidence_package_id, package_version)
        )
        return deepcopy(package) if package is not None else None

    async def get_latest_evidence_package(
        self,
        incident_id: str,
        completeness: tuple[str, ...] = ("COMPLETE", "PARTIAL"),
    ) -> dict[str, Any] | None:
        candidates = [
            package
            for (stored_incident, _, _), package in self._evidence_packages.items()
            if stored_incident == incident_id and package["completeness"] in completeness
        ]
        if not candidates:
            return None
        latest = max(
            candidates,
            key=lambda package: (int(package["package_version"]), package["generated_at"]),
        )
        return deepcopy(latest)

    async def reset_ingestion_data(
        self,
        clean_overview: dict[str, Any],
        clean_metric_history: dict[str, Any],
    ) -> None:
        ingestion_resource_types = {
            "overview",
            "metric_history",
            "incident_summary",
            "incident",
            "evidence",
            "copilot_messages",
            "pipeline_state",
        }
        self._resources = {
            key: payload
            for key, payload in self._resources.items()
            if key[0] not in ingestion_resource_types
        }
        self._copilot_threads.clear()
        self._copilot_messages.clear()
        self._evidence_packages.clear()
        self._resources[("overview", "current")] = deepcopy(clean_overview)
        self._resources[
            ("metric_history", str(clean_metric_history["metric_key"]))
        ] = deepcopy(clean_metric_history)

    async def reset_synthetic_data(self) -> None:
        synthetic_resource_types = {
            "overview",
            "metric_history",
            "incident_summary",
            "incident",
            "evidence",
            "copilot_messages",
            "copilot_interaction",
            "copilot_request",
            "copilot_retry_used",
            "copilot_tool_evidence",
            "copilot_feedback",
            "feedback_audit",
            "copilot_audit",
            "human_review",
            "simulation",
            "pipeline_state",
        }
        self._resources = {
            key: payload
            for key, payload in self._resources.items()
            if key[0] not in synthetic_resource_types
        }
        self._commands.clear()
        self._copilot_threads.clear()
        self._copilot_messages.clear()
        self._evidence_packages.clear()
        self._sequence = 0
