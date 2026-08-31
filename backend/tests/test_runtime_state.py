import asyncio
from datetime import timedelta
from pathlib import Path

from backend.application.investigator_service import InvestigatorService
from backend.config.settings import Settings
from backend.contracts.api import SimulationStatus
from backend.contracts.enums import MetricKey, SimulationAction
from backend.persistence.runtime_store import InMemoryRuntimeStore


def test_canonical_copilot_migration_is_additive_and_incident_scoped() -> None:
    migration = (
        Path(__file__).resolve().parents[1]
        / "persistence"
        / "migrations"
        / "003_copilot_threads.sql"
    ).read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS copilot_threads" in migration
    assert "incident_id TEXT NOT NULL UNIQUE" in migration
    assert "REFERENCES incidents (incident_id) ON DELETE CASCADE" in migration
    assert "CREATE TABLE IF NOT EXISTS copilot_messages" in migration
    assert "role TEXT NOT NULL CHECK (role IN ('USER', 'ASSISTANT', 'SYSTEM'))" in migration
    assert "UNIQUE (thread_id, sequence)" in migration
    assert "ux_copilot_messages_thread_client_request" in migration
    assert "ux_copilot_messages_thread_interaction_role" in migration
    assert "ADD COLUMN IF NOT EXISTS thread_id TEXT" in migration
    assert "DROP TABLE" not in migration.upper()


def test_in_memory_canonical_thread_store_is_unique_ordered_and_idempotent() -> None:
    async def exercise() -> None:
        store = InMemoryRuntimeStore()
        created_at = "2026-08-29T08:00:00Z"

        first = await store.get_or_create_copilot_thread("INC-THREAD", created_at)
        reopened = await store.get_or_create_copilot_thread("INC-THREAD", created_at)
        assert reopened == first

        user = {
            "message_id": "msg-user-1",
            "role": "USER",
            "content_type": "USER_QUESTION",
            "content": {"question": "What changed?"},
            "client_request_id": "request-1",
            "created_at": created_at,
        }
        inserted = await store.append_copilot_message(first["thread_id"], "INC-THREAD", user)
        replayed = await store.append_copilot_message(first["thread_id"], "INC-THREAD", user)
        assert replayed == inserted
        assert inserted["sequence"] == 1

        response = {
            "message_id": "msg-assistant-1",
            "role": "ASSISTANT",
            "content_type": "DETERMINISTIC_FALLBACK",
            "content": {"summary": "Fallback"},
            "interaction_id": "int-1",
            "response_to_message_id": "msg-user-1",
            "evidence_package_id": "pkg-1",
            "evidence_package_version": 1,
            "created_at": created_at,
        }
        fallback = await store.upsert_copilot_response(
            first["thread_id"], "INC-THREAD", response
        )
        response["content_type"] = "COPILOT_ANSWER"
        response["content"] = {"headline": "Validated answer"}
        validated = await store.upsert_copilot_response(
            first["thread_id"], "INC-THREAD", response
        )
        assert validated["message_id"] == fallback["message_id"]
        assert validated["sequence"] == 2
        assert validated["content_type"] == "COPILOT_ANSWER"

        page, next_sequence = await store.list_copilot_messages(
            first["thread_id"], "INC-THREAD", after_sequence=None, limit=1
        )
        assert [item["message_id"] for item in page] == ["msg-user-1"]
        assert next_sequence == 1
        second_page, final_cursor = await store.list_copilot_messages(
            first["thread_id"], "INC-THREAD", after_sequence=next_sequence, limit=2
        )
        assert [item["message_id"] for item in second_page] == ["msg-assistant-1"]
        assert final_cursor is None

        assert await store.get_copilot_message("INC-THREAD", "msg-assistant-1") == validated
        assert await store.get_copilot_message("INC-OTHER", "msg-assistant-1") is None

        digest = {"message_count": 2, "older_message_ids": ["msg-user-1"]}
        updated = await store.update_copilot_thread(
            first["thread_id"],
            "INC-THREAD",
            history_digest=digest,
            evidence_package_id="pkg-1",
            evidence_package_version=1,
            updated_at="2026-08-29T08:01:00Z",
        )
        assert updated["history_digest"] == digest
        assert updated["latest_evidence_package_version"] == 1

    asyncio.run(exercise())


def test_in_memory_evidence_history_resolves_exact_and_latest_eligible_packages() -> None:
    async def exercise() -> None:
        store = InMemoryRuntimeStore()
        base = {
            "incident_id": "INC-EVIDENCE",
            "evidence_package_id": "pkg-evidence",
            "schema_version": "evidence-package.v1",
            "builder_configuration_version": "demo-config.v1",
            "generated_at": "2026-08-29T08:00:00Z",
        }
        first = {**base, "package_version": 1, "completeness": "COMPLETE"}
        second = {**base, "package_version": 2, "completeness": "PARTIAL"}
        invalid = {**base, "package_version": 3, "completeness": "INVALID"}
        for package in (first, second, invalid):
            await store.save_evidence_package(package)

        assert await store.get_evidence_package("INC-EVIDENCE", "pkg-evidence", 1) == first
        assert await store.get_evidence_package("INC-OTHER", "pkg-evidence", 1) is None
        assert await store.get_latest_evidence_package("INC-EVIDENCE") == second

    asyncio.run(exercise())


class ResettableSimulator:
    SCENARIO_ID = "payment-gateway-v2.4.1-token-regression"

    async def status(self) -> SimulationStatus:
        return SimulationStatus(
            state="STOPPED",
            baseline_ready=False,
            available_actions=["START", "RESET"],
            message="Authoritative simulator status",
        )

    async def start(self, client_request_id: str) -> SimulationStatus:
        del client_request_id
        raise AssertionError("start is not exercised by these tests")

    async def inject(self, client_request_id: str) -> SimulationStatus:
        del client_request_id
        raise AssertionError("inject is not exercised by these tests")

    async def recover(self, client_request_id: str) -> SimulationStatus:
        del client_request_id
        raise AssertionError("recover is not exercised by these tests")

    async def stop(self, client_request_id: str) -> SimulationStatus:
        del client_request_id
        raise AssertionError("stop is not exercised by these tests")

    async def reset(self, client_request_id: str, confirmation: str) -> SimulationStatus:
        del client_request_id
        assert confirmation == "RESET_SYNTHETIC_DEMO"
        return SimulationStatus(
            state="STOPPED",
            baseline_ready=False,
            available_actions=["START", "RESET"],
            message="Synthetic demo data reset complete",
        )


def test_empty_store_initializes_to_stopped_without_seeded_telemetry_or_incidents() -> None:
    async def exercise() -> None:
        store = InMemoryRuntimeStore()
        service = InvestigatorService(store, ResettableSimulator())

        await service.initialize()

        status = await service.simulation_status()
        overview = await service.overview()
        incidents = await service.list_incidents()
        history = await service.metric_history(
            MetricKey.TECHNICAL_ERROR_RATE,
            overview.generated_at.replace(microsecond=0),
            overview.generated_at.replace(microsecond=0) + timedelta(minutes=1),
        )

        assert status.state.value == "STOPPED"
        assert status.available_actions == [SimulationAction.START, SimulationAction.RESET]
        assert overview.telemetry_state.value == "UNKNOWN"
        assert overview.active_incident_count == 0
        assert overview.active_incidents == []
        assert overview.latest_sample_at is None
        assert overview.metrics.technical_error_rate.value is None
        assert overview.metrics.technical_error_rate.unavailable_reason == "No telemetry yet"
        assert incidents.items == []
        assert history.points == []

    asyncio.run(exercise())


def test_missing_simulation_projection_recovers_from_authoritative_simulator() -> None:
    async def exercise() -> None:
        store = InMemoryRuntimeStore()
        service = InvestigatorService(store, ResettableSimulator())
        await service.initialize()
        await store.reset_synthetic_data()

        assert await store.get_resource("simulation", "current") is None

        status = await service.simulation_status()

        assert status.state.value == "STOPPED"
        assert status.message == "Authoritative simulator status"
        assert await store.get_resource("simulation", "current") == status.model_dump(
            mode="json"
        )

    asyncio.run(exercise())


def test_initialize_restores_missing_simulation_projection_when_overview_exists() -> None:
    async def exercise() -> None:
        store = InMemoryRuntimeStore()
        service = InvestigatorService(store, ResettableSimulator())
        await service.initialize()
        overview = await store.get_resource("overview", "current")
        assert overview is not None
        await store.reset_synthetic_data()
        await store.put_resource("overview", "current", overview)

        await service.initialize(migrate=False)

        assert await store.get_resource("simulation", "current") is not None

    asyncio.run(exercise())


def test_initialize_upgrades_legacy_overview_missing_staleness_threshold() -> None:
    async def exercise() -> None:
        store = InMemoryRuntimeStore()
        await InvestigatorService(store, ResettableSimulator()).initialize()
        legacy_overview = await store.get_resource("overview", "current")
        assert legacy_overview is not None
        legacy_overview.pop("telemetry_stale_after_seconds")
        await store.put_resource("overview", "current", legacy_overview)

        service = InvestigatorService(
            store,
            ResettableSimulator(),
            settings=Settings(telemetry_stale_after_seconds=47),
        )
        await service.initialize()

        overview = await service.overview()
        persisted = await store.get_resource("overview", "current")
        assert overview.telemetry_stale_after_seconds == 47
        assert persisted is not None
        assert persisted["telemetry_stale_after_seconds"] == 47

    asyncio.run(exercise())


def test_confirmed_reset_clears_all_synthetic_resources_and_is_idempotent() -> None:
    async def exercise() -> None:
        class MigrationCountingStore(InMemoryRuntimeStore):
            def __init__(self) -> None:
                super().__init__()
                self.migration_calls = 0

            async def migrate(self) -> None:
                self.migration_calls += 1

        store = MigrationCountingStore()
        reset_signals: list[str] = []

        async def signal_reset() -> None:
            reset_signals.append("reset")

        service = InvestigatorService(
            store,
            ResettableSimulator(),
            runtime_reset=signal_reset,
        )
        await service.initialize()
        await store.put_resource("integration_configuration", "preserved", {"enabled": True})
        await store.put_resource("human_review", "INC-OLD", {"version": 3})
        await store.put_resource("copilot_feedback", "MSG-OLD:latest", {"version": 2})
        await store.put_resource("copilot_audit", "INT-OLD", {"status": "VALIDATED"})
        thread = await store.get_or_create_copilot_thread(
            "INC-OLD", "2026-08-29T08:00:00Z"
        )
        await store.append_copilot_message(
            thread["thread_id"],
            "INC-OLD",
            {
                "message_id": "MSG-OLD",
                "role": "USER",
                "content_type": "USER_QUESTION",
                "content": {"question": "Preserved only until confirmed reset"},
                "client_request_id": "request-old",
                "created_at": "2026-08-29T08:00:00Z",
            },
        )

        first = await service.simulation_command(
            SimulationAction.RESET,
            "reset-1",
            confirmation="RESET_SYNTHETIC_DEMO",
        )
        second = await service.simulation_command(
            SimulationAction.RESET,
            "reset-2",
            confirmation="RESET_SYNTHETIC_DEMO",
        )

        assert first.state.value == second.state.value == "STOPPED"
        assert (await service.list_incidents()).items == []
        assert await store.list_resources("incident") == []
        assert await store.list_resources("evidence") == []
        assert await store.list_resources("human_review") == []
        assert await store.list_resources("copilot_messages") == []
        assert await store.list_resources("copilot_feedback") == []
        assert await store.list_resources("copilot_audit") == []
        assert await store.get_copilot_thread("INC-OLD") is None
        assert await store.get_copilot_message("INC-OLD", "MSG-OLD") is None
        assert await store.get_resource("integration_configuration", "preserved") == {
            "enabled": True
        }
        assert (await service.overview()).metrics.technical_error_rate.value is None
        assert reset_signals == ["reset", "reset"]
        assert store.migration_calls == 1

    asyncio.run(exercise())
