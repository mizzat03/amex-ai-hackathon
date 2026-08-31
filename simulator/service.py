"""Application service for the separate simulator producer process."""

import asyncio
import json
from datetime import UTC, datetime, timedelta

from redis.asyncio import Redis
from redis.exceptions import (
    BusyLoadingError,
    ConnectionError as RedisConnectionError,
    TimeoutError as RedisTimeoutError,
)

from backend.config.settings import Settings
from backend.contracts.api import SimulationStatus
from backend.contracts.events import PaymentEvent
from backend.ingestion.redis_streams import RedisStreamPublisher
from simulator.operational_events.generator import deployment_event, rollback_event
from simulator.payment_events.generator import PaymentEventGenerator
from simulator.scenarios.state_machine import SimulatorStateMachine


class SimulatorService:
    SCENARIO_ID = "payment-gateway-v2.4.1-token-regression"
    STATE_KEY = "amex:synthetic:simulator:state:v1"
    BASELINE_READY_KEY = "amex:synthetic:baseline-ready:v1"
    RECOVERY_READY_KEY = "amex:synthetic:recovery-ready:v1"
    REDIS_STARTUP_MAX_ATTEMPTS = 10
    REDIS_STARTUP_BASE_DELAY_SECONDS = 0.25
    REDIS_STARTUP_MAX_DELAY_SECONDS = 5.0

    def __init__(self, client: Redis, settings: Settings) -> None:
        self.settings = settings
        self.client = client
        self.machine = SimulatorStateMachine()
        self.publisher = RedisStreamPublisher(client, settings)

    async def initialize(self) -> None:
        delay = self.REDIS_STARTUP_BASE_DELAY_SECONDS
        transient_errors = (BusyLoadingError, RedisConnectionError, RedisTimeoutError)
        for attempt in range(1, self.REDIS_STARTUP_MAX_ATTEMPTS + 1):
            try:
                stored = await self.client.get(self.STATE_KEY)
                if stored:
                    self.machine.restore(SimulationStatus.model_validate_json(stored))
                else:
                    await self._persist_status()
                return
            except transient_errors:
                if attempt == self.REDIS_STARTUP_MAX_ATTEMPTS:
                    raise
                await asyncio.sleep(delay)
                delay = min(self.REDIS_STARTUP_MAX_DELAY_SECONDS, delay * 2)

    async def ping(self) -> bool:
        return bool(await self.client.ping())

    async def baseline_ready(self) -> bool:
        return await self.client.get(self.BASELINE_READY_KEY) == "1"

    async def recovery_ready(self) -> bool:
        return await self.client.get(self.RECOVERY_READY_KEY) == "1"

    async def _persist_status(self) -> None:
        await self.client.set(
            self.STATE_KEY,
            json.dumps(self.machine.status().model_dump(mode="json")),
        )

    async def status(self) -> SimulationStatus:
        return self.machine.status()

    def _recent_batch(
        self,
        generator: PaymentEventGenerator,
        count: int,
        now: datetime,
    ) -> list[PaymentEvent]:
        """Distribute a tick's events up to, and never beyond, the producer clock."""
        interval_ms = max(
            1,
            int(self.settings.simulator_tick_seconds * 1000 / max(count - 1, 1)),
        )
        start_at = now - timedelta(milliseconds=interval_ms * max(count - 1, 0))
        return generator.generate_batch(count, start_at, interval_ms=interval_ms)

    async def start(self, client_request_id: str, now: datetime | None = None) -> SimulationStatus:
        now = (now or datetime.now(UTC)).astimezone(UTC)
        state = self.machine.start(client_request_id, now)
        if state.state.value != "PREWARMING":
            return state
        await self._persist_status()
        historical_start = now - timedelta(
            seconds=self.settings.baseline_window_seconds + self.settings.current_window_seconds
        )
        generator = PaymentEventGenerator(self.settings.demo_seed)
        required_baseline_count = max(
            self.settings.baseline_required_samples,
            self.settings.min_baseline_attempts,
        )
        baseline_count = required_baseline_count + max(
            self.settings.simulator_batch_size,
            required_baseline_count // 10,
        )
        baseline_interval_ms = max(
            1,
            int(self.settings.baseline_window_seconds * 1000 / baseline_count),
        )
        current_count = max(self.settings.min_current_attempts, self.settings.simulator_batch_size)
        current_interval_ms = max(
            1,
            int(self.settings.current_window_seconds * 1000 / current_count),
        )
        baseline = generator.generate_batch(
            baseline_count,
            historical_start,
            interval_ms=baseline_interval_ms,
        )
        current = generator.generate_batch(
            current_count,
            now - timedelta(seconds=self.settings.current_window_seconds),
            interval_ms=current_interval_ms,
        )
        await self.publisher.publish_payments([*baseline, *current])
        return state

    async def publish_healthy(self, count: int, now: datetime | None = None) -> int:
        now = (now or datetime.now(UTC)).astimezone(UTC)
        generator = PaymentEventGenerator(self.settings.demo_seed + 1)
        return len(await self.publisher.publish_payments(self._recent_batch(generator, count, now)))

    async def publish_injected(self, count: int, now: datetime | None = None) -> int:
        now = (now or datetime.now(UTC)).astimezone(UTC)
        generator = PaymentEventGenerator(self.settings.demo_seed + 4, injected=True)
        return len(await self.publisher.publish_payments(self._recent_batch(generator, count, now)))

    async def complete_prewarm(self) -> SimulationStatus:
        state = self.machine.complete_prewarm()
        await self._persist_status()
        return state

    async def complete_recovery(self) -> SimulationStatus:
        state = self.machine.complete_recovery()
        await self.client.delete(self.RECOVERY_READY_KEY)
        await self._persist_status()
        return state

    async def inject(self, client_request_id: str, now: datetime | None = None) -> SimulationStatus:
        now = (now or datetime.now(UTC)).astimezone(UTC)
        state = self.machine.inject(client_request_id, self.SCENARIO_ID)
        await self._persist_status()
        await self.publisher.publish_operational(deployment_event(now))
        generator = PaymentEventGenerator(self.settings.demo_seed + 2, injected=True)
        await self.publisher.publish_payments(self._recent_batch(generator, 600, now))
        return state

    async def recover(
        self, client_request_id: str, now: datetime | None = None
    ) -> SimulationStatus:
        now = (now or datetime.now(UTC)).astimezone(UTC)
        state = self.machine.recover(client_request_id)
        await self._persist_status()
        await self.publisher.publish_operational(rollback_event(now))
        generator = PaymentEventGenerator(self.settings.demo_seed + 3)
        await self.publisher.publish_payments(self._recent_batch(generator, 800, now))
        return state

    async def stop(self, client_request_id: str) -> SimulationStatus:
        state = self.machine.stop(client_request_id)
        await self._persist_status()
        return state

    async def reset(self, client_request_id: str, confirmation: str) -> SimulationStatus:
        self.machine.reset(client_request_id, confirmation)
        try:
            await self.publisher.reset_synthetic_demo_data()
        except asyncio.CancelledError:
            await self._recover_failed_reset()
            raise
        except Exception:
            await self._recover_failed_reset()
            raise
        state = self.machine.complete_reset()
        await self._persist_status()
        return state

    async def _recover_failed_reset(self) -> None:
        self.machine.fail_reset()
        try:
            await asyncio.shield(self._persist_status())
        except Exception:
            # The in-memory ERROR state remains actionable even if Redis is unavailable.
            pass
