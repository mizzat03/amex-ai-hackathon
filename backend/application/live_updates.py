"""Compact WebSocket invalidations with persisted monotonic sequencing."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, AsyncIterator
from uuid import uuid4

from backend.contracts.api import WsEnvelope
from backend.persistence.runtime_store import RuntimeStore


class LiveUpdateBroker:
    def __init__(self, store: RuntimeStore, queue_size: int = 64) -> None:
        self._store = store
        self._queue_size = queue_size
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._lock = asyncio.Lock()

    async def publish(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        occurred_at = datetime.now(UTC)
        event_id = f"evt_{uuid4().hex}"
        sequence = await self._store.append_ws_event(
            event_id, event_type, occurred_at, payload
        )
        envelope = WsEnvelope[dict[str, Any]](
            event_id=event_id,
            event_type=event_type,
            occurred_at=occurred_at,
            sequence=sequence,
            payload=payload,
        ).model_dump(mode="json")
        async with self._lock:
            for queue in self._subscribers:
                if queue.full():
                    queue.get_nowait()
                queue.put_nowait(envelope)
        return envelope

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Queue[dict[str, Any]]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self._queue_size)
        async with self._lock:
            self._subscribers.add(queue)
        try:
            yield queue
        finally:
            async with self._lock:
                self._subscribers.discard(queue)
