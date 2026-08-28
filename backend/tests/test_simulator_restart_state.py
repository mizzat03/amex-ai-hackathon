import asyncio
from datetime import UTC, datetime

from backend.config.settings import Settings
from backend.contracts.enums import SimulationState
from simulator.service import SimulatorService


class FakeStateRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(self, key: str, value: str, **_kwargs) -> bool:
        self.values[key] = value
        return True

    async def ping(self) -> bool:
        return True


class FakePublisher:
    def __init__(self) -> None:
        self.payment_batches = []

    async def publish_payments(self, events):
        self.payment_batches.append(events)
        return [str(index) for index, _event in enumerate(events)]

    async def publish_operational(self, _event):
        return "1-0"

    async def reset_synthetic_demo_data(self):
        return 0


def test_simulator_restores_authoritative_state_after_process_restart() -> None:
    async def exercise() -> None:
        client = FakeStateRedis()
        settings = Settings(
            baseline_required_samples=100,
            min_baseline_attempts=1,
            min_current_attempts=1,
        )
        first = SimulatorService(client, settings)  # type: ignore[arg-type]
        first.publisher = FakePublisher()  # type: ignore[assignment]
        await first.initialize()
        await first.start("start-before-restart", datetime(2026, 8, 28, tzinfo=UTC))

        restarted = SimulatorService(client, settings)  # type: ignore[arg-type]
        restarted.publisher = FakePublisher()  # type: ignore[assignment]
        await restarted.initialize()

        assert (await restarted.status()).state is SimulationState.PREWARMING
        assert (await restarted.status()).started_at == datetime(2026, 8, 28, tzinfo=UTC)

    asyncio.run(exercise())


def test_simulator_batches_end_at_or_before_the_producer_clock() -> None:
    async def exercise() -> None:
        client = FakeStateRedis()
        settings = Settings(
            simulator_tick_seconds=1,
            simulator_batch_size=250,
            baseline_required_samples=100,
            min_baseline_attempts=1,
            min_current_attempts=1,
        )
        service = SimulatorService(client, settings)  # type: ignore[arg-type]
        publisher = FakePublisher()
        service.publisher = publisher  # type: ignore[assignment]
        await service.initialize()
        now = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)

        await service.publish_healthy(250, now)
        await service.publish_injected(250, now)
        service.machine.start("start-for-clock-test", now)
        service.machine.complete_prewarm()
        await service.inject("inject-with-bounded-clock", now)
        await service.recover("recover-with-bounded-clock", now)

        for batch in publisher.payment_batches:
            assert batch
            assert max(event.occurred_at for event in batch) <= now

    asyncio.run(exercise())


def test_start_seeds_baseline_headroom_for_normal_ingestion_delay() -> None:
    async def exercise() -> None:
        client = FakeStateRedis()
        settings = Settings(
            simulator_batch_size=250,
            baseline_required_samples=100,
            min_baseline_attempts=1,
            min_current_attempts=1,
        )
        service = SimulatorService(client, settings)  # type: ignore[arg-type]
        publisher = FakePublisher()
        service.publisher = publisher  # type: ignore[assignment]
        await service.initialize()

        await service.start("start-with-headroom", datetime(2026, 8, 28, 12, 0, tzinfo=UTC))

        assert len(publisher.payment_batches) == 1
        assert len(publisher.payment_batches[0]) >= (
            settings.baseline_required_samples + 2 * settings.simulator_batch_size
        )

    asyncio.run(exercise())
