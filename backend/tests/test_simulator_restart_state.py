import asyncio
from datetime import UTC, datetime

import pytest
from redis.exceptions import BusyLoadingError

from backend.config.settings import Settings
from backend.contracts.enums import SimulationAction, SimulationState
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


class LoadingStateRedis(FakeStateRedis):
    def __init__(self, failures: int) -> None:
        super().__init__()
        self.failures = failures
        self.get_attempts = 0

    async def get(self, key: str) -> str | None:
        self.get_attempts += 1
        if self.get_attempts <= self.failures:
            raise BusyLoadingError("Redis is loading the dataset in memory")
        return await super().get(key)


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


class CancelledResetPublisher(FakePublisher):
    async def reset_synthetic_demo_data(self):
        raise asyncio.CancelledError


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


def test_simulator_initialization_retries_while_redis_is_loading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> None:
        delays: list[float] = []

        async def no_wait(delay: float) -> None:
            delays.append(delay)

        monkeypatch.setattr(asyncio, "sleep", no_wait)
        client = LoadingStateRedis(failures=2)
        service = SimulatorService(client, Settings())  # type: ignore[arg-type]

        await service.initialize()

        assert client.get_attempts == 3
        assert delays == [0.25, 0.5]
        assert SimulatorService.STATE_KEY in client.values

    asyncio.run(exercise())


def test_cancelled_reset_cleanup_leaves_simulator_recoverable() -> None:
    async def exercise() -> None:
        client = FakeStateRedis()
        service = SimulatorService(client, Settings())  # type: ignore[arg-type]
        service.publisher = CancelledResetPublisher()  # type: ignore[assignment]
        await service.initialize()

        with pytest.raises(asyncio.CancelledError):
            await service.reset("cancelled-reset", "RESET_SYNTHETIC_DEMO")

        status = await service.status()
        assert status.state is SimulationState.ERROR
        assert status.available_actions == [SimulationAction.STOP, SimulationAction.RESET]

        service.publisher = FakePublisher()  # type: ignore[assignment]
        retried = await service.reset("cancelled-reset", "RESET_SYNTHETIC_DEMO")
        assert retried.state is SimulationState.STOPPED

    asyncio.run(exercise())


def test_simulator_initialization_stops_after_bounded_redis_loading_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> None:
        async def no_wait(_delay: float) -> None:
            return None

        monkeypatch.setattr(asyncio, "sleep", no_wait)
        client = LoadingStateRedis(failures=100)
        service = SimulatorService(client, Settings())  # type: ignore[arg-type]

        with pytest.raises(BusyLoadingError):
            await service.initialize()

        assert 1 < client.get_attempts < client.failures

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
