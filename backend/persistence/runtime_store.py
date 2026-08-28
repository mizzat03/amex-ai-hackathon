"""PostgreSQL-backed resource projections for the frozen API boundary."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

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
        with self._connect() as connection:
            connection.execute(
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
            for table_name in synthetic_tables:
                # Table names come solely from the fixed allowlist above; values are
                # never accepted from requests or environment configuration.
                connection.execute(f"DELETE FROM {table_name}")
            connection.execute(
                "SELECT setval(pg_get_serial_sequence('websocket_events', 'sequence'), 1, false)"
            )


class InMemoryRuntimeStore:
    """Test double with the same clone-on-read semantics as PostgreSQL JSONB."""

    def __init__(self) -> None:
        self._resources: dict[tuple[str, str], dict[str, Any]] = {}
        self._commands: dict[tuple[str, str], dict[str, Any]] = {}
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
        self._sequence = 0
