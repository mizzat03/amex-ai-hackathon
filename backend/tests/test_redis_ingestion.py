"""Real Redis Streams round-trip tests.

Run with the Stage 2 Redis service available at AMEX_REDIS_URL (default localhost:6379).
"""

import asyncio
import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import redis.asyncio as redis

from backend.config import get_settings
from backend.config.settings import Settings
from backend.contracts.enums import SimulationState
from backend.contracts.events import OperationalEvent
from backend.ingestion.redis_streams import RedisStreamConsumer, RedisStreamPublisher
from simulator.payment_events.generator import PaymentEventGenerator
from simulator.service import SimulatorService

pytestmark = pytest.mark.skipif(
    os.getenv("AMEX_RUN_REDIS_TESTS") != "1",
    reason="Set AMEX_RUN_REDIS_TESTS=1 with the isolated Redis test service running",
)


def test_payment_and_operational_events_round_trip_through_separate_streams() -> None:
    async def exercise() -> None:
        settings = get_settings()
        client = redis.from_url(settings.redis_url, decode_responses=True)
        try:
            await client.ping()
            await client.delete(settings.payment_stream, settings.operational_stream)
            publisher = RedisStreamPublisher(client, settings)
            payment = PaymentEventGenerator(seed=7).generate_batch(1, datetime.now(UTC))[0]
            operation = OperationalEvent(
                event_id=uuid4(),
                event_type="DEPLOYMENT",
                occurred_at=datetime.now(UTC),
                emitted_at=datetime.now(UTC),
                affected_service="PAYMENT_GATEWAY",
                component="authorization-api",
                status="SUCCEEDED",
                change_categories=["TOKEN_VALIDATION", "RELEASE"],
                previous_version="v2.4.0",
                new_version="v2.4.1",
                affected_regions=["SG"],
                affected_payment_methods=["MOBILE_WALLET"],
                correlation_id="deployment-demo-1",
            )
            await publisher.publish_payment(payment)
            await publisher.publish_operational(operation)

            seen_payment = []
            seen_operation = []
            consumer = RedisStreamConsumer(
                client,
                settings,
                consumer_name="pytest-consumer",
                on_payment=seen_payment.append,
                on_operational=seen_operation.append,
            )
            await consumer.ensure_groups()
            processed = await consumer.consume_once(block_ms=100)
            assert processed == 2
            assert seen_payment == [payment]
            assert seen_operation == [operation]

            await publisher.publish_payment(payment)
            processed_duplicate = await consumer.consume_once(block_ms=100)
            assert processed_duplicate == 0
            assert seen_payment == [payment]
        finally:
            await client.aclose()

    asyncio.run(exercise())


def test_reset_deletes_only_allowlisted_synthetic_keys() -> None:
    async def exercise() -> None:
        settings = get_settings()
        client = redis.from_url(settings.redis_url, decode_responses=True)
        try:
            await client.set("outside:must-survive", "yes")
            await client.set("amex:synthetic:temporary", "delete-me")
            publisher = RedisStreamPublisher(client, settings)
            removed = await publisher.reset_synthetic_demo_data()
            assert removed >= 1
            assert await client.get("outside:must-survive") == "yes"
        finally:
            await client.delete("outside:must-survive")
            await client.aclose()

    asyncio.run(exercise())


def test_full_demo_sequence_uses_real_streams_and_prewarms_through_consumer() -> None:
    async def exercise() -> None:
        settings = Settings(baseline_required_samples=100)
        client = redis.from_url(settings.redis_url, decode_responses=True)
        payments = []
        operations = []
        try:
            publisher = RedisStreamPublisher(client, settings)
            await publisher.reset_synthetic_demo_data()
            service = SimulatorService(client, settings)
            status = await service.start("start-sequence")
            assert status.state is SimulationState.PREWARMING
            assert not status.baseline_ready

            consumer = RedisStreamConsumer(
                client,
                settings,
                consumer_name="pytest-sequence",
                on_payment=payments.append,
                on_operational=operations.append,
            )
            await consumer.ensure_groups()
            while len(payments) < 100:
                await consumer.consume_once(block_ms=100, count=250)
            assert len(payments) >= 100

            ready = await service.complete_prewarm()
            assert ready.state is SimulationState.RUNNING_HEALTHY

            injected = await service.inject("inject-sequence")
            assert injected.state is SimulationState.INCIDENT_ACTIVE
            recovered = await service.recover("recover-sequence")
            assert recovered.state is SimulationState.RECOVERING
            await service.stop("stop-sequence")
            reset = await service.reset("reset-sequence", "RESET_SYNTHETIC_DEMO")
            assert reset.state is SimulationState.STOPPED
            assert not reset.baseline_ready
        finally:
            await client.aclose()

    asyncio.run(exercise())
