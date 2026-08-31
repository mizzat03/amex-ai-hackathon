"""Small Redis Streams transport with durable deduplication and typed validation."""

import inspect
from collections.abc import Awaitable, Callable
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import ResponseError

from backend.config.settings import Settings
from backend.contracts.events import OperationalEvent, PaymentEvent

PaymentHandler = Callable[[PaymentEvent], None | Awaitable[None]]
OperationalHandler = Callable[[OperationalEvent], None | Awaitable[None]]
BatchHandler = Callable[
    [list[PaymentEvent], list[OperationalEvent]],
    None | Awaitable[None],
]


class RedisStreamPublisher:
    def __init__(self, client: Redis, settings: Settings) -> None:
        self._client = client
        self._settings = settings

    async def publish_payment(self, event: PaymentEvent) -> str:
        return await self._client.xadd(
            self._settings.payment_stream,
            {"event_id": str(event.event_id), "payload": event.model_dump_json()},
        )

    async def publish_operational(self, event: OperationalEvent) -> str:
        return await self._client.xadd(
            self._settings.operational_stream,
            {"event_id": str(event.event_id), "payload": event.model_dump_json()},
        )

    async def publish_payments(self, events: list[PaymentEvent]) -> list[str]:
        async with self._client.pipeline(transaction=False) as pipeline:
            for event in events:
                pipeline.xadd(
                    self._settings.payment_stream,
                    {"event_id": str(event.event_id), "payload": event.model_dump_json()},
                )
            return await pipeline.execute()

    async def reset_synthetic_demo_data(self) -> int:
        """Delete only application keys in the explicit synthetic namespace."""
        keys = [key async for key in self._client.scan_iter(match="amex:synthetic:*")]
        return await self._client.unlink(*keys) if keys else 0


class RedisStreamConsumer:
    GROUP = "amex-backend-v1"
    DEDUPE_KEY = "amex:synthetic:ingestion:dedupe:v1"

    def __init__(
        self,
        client: Redis,
        settings: Settings,
        consumer_name: str,
        on_payment: PaymentHandler,
        on_operational: OperationalHandler,
        on_batch: BatchHandler | None = None,
    ) -> None:
        self._client = client
        self._settings = settings
        self._consumer_name = consumer_name
        self._on_payment = on_payment
        self._on_operational = on_operational
        self._on_batch = on_batch

    async def ensure_groups(self) -> None:
        for stream in (self._settings.payment_stream, self._settings.operational_stream):
            try:
                await self._client.xgroup_create(stream, self.GROUP, id="0", mkstream=True)
            except ResponseError as exc:
                if "BUSYGROUP" not in str(exc):
                    raise

    async def consume_once(self, block_ms: int = 1000, count: int = 200) -> int:
        entries: list[tuple[str, list[tuple[str, dict[str, str]]]]] = []
        for stream in (self._settings.payment_stream, self._settings.operational_stream):
            claimed = await self._client.xautoclaim(
                stream,
                self.GROUP,
                self._consumer_name,
                min_idle_time=self._settings.ingestion_claim_idle_ms,
                start_id="0-0",
                count=count,
            )
            claimed_messages = claimed[1]
            if claimed_messages:
                entries.append((stream, claimed_messages))
        new_entries = await self._client.xreadgroup(
            self.GROUP,
            self._consumer_name,
            streams={
                self._settings.payment_stream: ">",
                self._settings.operational_stream: ">",
            },
            count=count,
            block=block_ms,
        )
        entries.extend(new_entries)
        pending: list[tuple[str, str, str, PaymentEvent | OperationalEvent]] = []
        for stream, messages in entries:
            for message_id, fields in messages:
                event_id = fields["event_id"]
                already_processed = await self._client.sismember(self.DEDUPE_KEY, event_id)
                if already_processed:
                    await self._client.xack(stream, self.GROUP, message_id)
                    continue
                if stream == self._settings.payment_stream:
                    event: PaymentEvent | OperationalEvent = PaymentEvent.model_validate_json(
                        fields["payload"]
                    )
                elif stream == self._settings.operational_stream:
                    event = OperationalEvent.model_validate_json(fields["payload"])
                else:
                    raise ValueError(f"unexpected stream {stream}")
                pending.append((stream, message_id, event_id, event))

        payments = [event for *_, event in pending if isinstance(event, PaymentEvent)]
        operations = [event for *_, event in pending if isinstance(event, OperationalEvent)]
        if pending:
            if self._on_batch is not None:
                await self._dispatch(self._on_batch, payments, operations)
            else:
                for event in payments:
                    await self._dispatch(self._on_payment, event)
                for event in operations:
                    await self._dispatch(self._on_operational, event)
        for stream, message_id, event_id, _event in pending:
            # Mark only after the complete projection batch succeeds. A crash or
            # transaction failure therefore leaves every entry retryable.
            await self._client.sadd(self.DEDUPE_KEY, event_id)
            await self._client.xack(stream, self.GROUP, message_id)
        return len(pending)

    @staticmethod
    async def _dispatch(handler: Callable[..., Any], *values: Any) -> None:
        result = handler(*values)
        if inspect.isawaitable(result):
            await result
