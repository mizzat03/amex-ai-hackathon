import asyncio
from datetime import UTC, datetime

from backend.application.clean_projection import build_clean_projection
from backend.config.settings import Settings
from backend.ingestion.app import IngestionWorker, RUNTIME_EPOCH_KEY
from backend.persistence.runtime_store import InMemoryRuntimeStore
from backend.tests.runtime_fixtures import seed_incident_fixture
from simulator.payment_events.generator import PaymentEventGenerator


class EpochRedis:
    def __init__(self, epoch: str) -> None:
        self.epoch = epoch

    async def setnx(self, key: str, value: str) -> bool:
        assert key == RUNTIME_EPOCH_KEY
        del value
        return False

    async def get(self, key: str) -> str:
        assert key == RUNTIME_EPOCH_KEY
        return self.epoch

    async def xgroup_create(self, *_args, **_kwargs) -> None:
        return None

    async def publish(self, *_args, **_kwargs) -> int:
        return 1


class MidBatchEpochRedis(EpochRedis):
    def __init__(self) -> None:
        super().__init__("old-runtime")
        self.reads = 0

    async def get(self, key: str) -> str:
        assert key == RUNTIME_EPOCH_KEY
        self.reads += 1
        return "old-runtime" if self.reads <= 2 else "new-runtime"


def test_ingestion_reset_atomically_replaces_stale_overview_with_clean_projection() -> None:
    async def exercise() -> None:
        store = InMemoryRuntimeStore()
        await seed_incident_fixture(store)
        clean = build_clean_projection()

        await store.reset_ingestion_data(
            clean.overview.model_dump(mode="json"),
            clean.history.model_dump(mode="json"),
        )

        assert await store.get_resource("overview", "current") == clean.overview.model_dump(
            mode="json"
        )
        assert await store.get_resource(
            "metric_history", clean.history.metric_key.value
        ) == clean.history.model_dump(mode="json")
        assert await store.list_resources("incident_summary") == []

    asyncio.run(exercise())


def test_new_runtime_epoch_discards_stale_incident_projection_before_new_traffic() -> None:
    async def exercise() -> None:
        client = EpochRedis("old-runtime")
        store = InMemoryRuntimeStore()
        worker = IngestionWorker(client, store, Settings())  # type: ignore[arg-type]
        await worker.initialize()

        await seed_incident_fixture(store)
        clean_simulation = build_clean_projection().simulation.model_dump(mode="json")
        await store.put_resource("simulation", "current", clean_simulation)
        await store.put_resource(
            "integration_configuration",
            "preserved",
            {"enabled": True},
        )

        client.epoch = "new-runtime"
        event_at = datetime(2026, 8, 30, 14, 30, tzinfo=UTC)
        payment = PaymentEventGenerator(seed=404).generate_batch(1, event_at)[0]

        await worker._commit_batch([payment], [])

        overview = await store.get_resource("overview", "current")
        assert overview is not None
        assert overview["active_incident_count"] == 0
        assert overview["active_incidents"] == []
        assert await store.list_resources("incident_summary") == []
        assert await store.get_resource("simulation", "current") == clean_simulation
        assert await store.get_resource("integration_configuration", "preserved") == {
            "enabled": True
        }

    asyncio.run(exercise())


def test_epoch_change_during_batch_restores_clean_empty_overview() -> None:
    async def exercise() -> None:
        client = MidBatchEpochRedis()
        store = InMemoryRuntimeStore()
        worker = IngestionWorker(client, store, Settings())  # type: ignore[arg-type]
        await worker.initialize()

        await seed_incident_fixture(store)
        clean_simulation = build_clean_projection().simulation.model_dump(mode="json")
        await store.put_resource("simulation", "current", clean_simulation)
        event_at = datetime(2026, 8, 30, 14, 30, tzinfo=UTC)
        payment = PaymentEventGenerator(seed=405).generate_batch(1, event_at)[0]

        await worker._commit_batch([payment], [])

        overview = await store.get_resource("overview", "current")
        assert overview is not None
        assert overview["active_incident_count"] == 0
        assert overview["active_incidents"] == []
        assert await store.list_resources("incident_summary") == []
        assert await store.get_resource("simulation", "current") == clean_simulation

    asyncio.run(exercise())
