import asyncio
from datetime import timedelta

from backend.application.investigator_service import InvestigatorService
from backend.contracts.api import SimulationStatus
from backend.contracts.enums import MetricKey, SimulationAction
from backend.persistence.runtime_store import InMemoryRuntimeStore


class ResettableSimulator:
    SCENARIO_ID = "payment-gateway-v2.4.1-token-regression"

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


def test_confirmed_reset_clears_all_synthetic_resources_and_is_idempotent() -> None:
    async def exercise() -> None:
        store = InMemoryRuntimeStore()
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
        assert await store.get_resource("integration_configuration", "preserved") == {
            "enabled": True
        }
        assert (await service.overview()).metrics.technical_error_rate.value is None
        assert reset_signals == ["reset", "reset"]

    asyncio.run(exercise())
