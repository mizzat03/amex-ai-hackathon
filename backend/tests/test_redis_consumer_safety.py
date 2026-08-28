import asyncio
from datetime import UTC, datetime

from backend.config.settings import Settings
from backend.ingestion.redis_streams import RedisStreamConsumer
from simulator.payment_events.generator import PaymentEventGenerator


class FakeStreamRedis:
    def __init__(self, stream: str, event_id: str, payload: str) -> None:
        self.stream = stream
        self.message = ("1-0", {"event_id": event_id, "payload": payload})
        self.dedupe: set[str] = set()
        self.acked: list[tuple[str, str, str]] = []

    async def xreadgroup(self, *_args, **_kwargs):
        return [(self.stream, [self.message])]

    async def xautoclaim(self, *_args, **_kwargs):
        return ("0-0", [])

    async def sismember(self, _key: str, value: str) -> bool:
        return value in self.dedupe

    async def sadd(self, _key: str, value: str) -> int:
        if value in self.dedupe:
            return 0
        self.dedupe.add(value)
        return 1

    async def xack(self, stream: str, group: str, message_id: str) -> int:
        self.acked.append((stream, group, message_id))
        return 1


def test_consumer_marks_deduplication_only_after_projection_succeeds() -> None:
    async def exercise() -> None:
        settings = Settings()
        event = PaymentEventGenerator(77).generate_batch(1, datetime.now(UTC))[0]
        client = FakeStreamRedis(
            settings.payment_stream,
            str(event.event_id),
            event.model_dump_json(),
        )
        attempts = 0

        async def fail_once(_event) -> None:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("projection transaction failed")

        consumer = RedisStreamConsumer(
            client,  # type: ignore[arg-type]
            settings,
            consumer_name="restart-safe",
            on_payment=fail_once,
            on_operational=lambda _event: None,
        )
        try:
            await consumer.consume_once(block_ms=1)
        except RuntimeError:
            pass
        else:
            raise AssertionError("the handler failure must propagate")

        assert client.dedupe == set()
        assert client.acked == []

        assert await consumer.consume_once(block_ms=1) == 1
        assert client.dedupe == {str(event.event_id)}
        assert len(client.acked) == 1

    asyncio.run(exercise())


def test_consumer_commits_a_typed_batch_before_acknowledging_entries() -> None:
    async def exercise() -> None:
        settings = Settings()
        event = PaymentEventGenerator(88).generate_batch(1, datetime.now(UTC))[0]
        client = FakeStreamRedis(
            settings.payment_stream,
            str(event.event_id),
            event.model_dump_json(),
        )
        committed: list[list] = []

        async def commit(payments, operations) -> None:
            assert operations == []
            assert client.acked == []
            committed.append(payments)

        consumer = RedisStreamConsumer(
            client,  # type: ignore[arg-type]
            settings,
            consumer_name="batch-safe",
            on_payment=lambda _event: None,
            on_operational=lambda _event: None,
            on_batch=commit,
        )

        assert await consumer.consume_once(block_ms=1) == 1
        assert committed == [[event]]
        assert len(client.acked) == 1

    asyncio.run(exercise())


def test_new_consumer_claims_abandoned_pending_entries_after_restart() -> None:
    async def exercise() -> None:
        settings = Settings()
        event = PaymentEventGenerator(99).generate_batch(1, datetime.now(UTC))[0]

        class RestartRedis(FakeStreamRedis):
            def __init__(self) -> None:
                super().__init__(
                    settings.payment_stream,
                    str(event.event_id),
                    event.model_dump_json(),
                )
                self.claimed = False

            async def xautoclaim(self, *_args, **_kwargs):
                if self.claimed:
                    return ("0-0", [])
                self.claimed = True
                return ("0-0", [self.message])

            async def xreadgroup(self, *_args, **_kwargs):
                return []

        client = RestartRedis()
        committed: list[list] = []
        consumer = RedisStreamConsumer(
            client,  # type: ignore[arg-type]
            settings,
            consumer_name="replacement-worker",
            on_payment=lambda _event: None,
            on_operational=lambda _event: None,
            on_batch=lambda payments, _operations: committed.append(payments),
        )

        assert await consumer.consume_once(block_ms=1) == 1
        assert committed == [[event]]
        assert client.dedupe == {str(event.event_id)}
        assert len(client.acked) == 1

    asyncio.run(exercise())
