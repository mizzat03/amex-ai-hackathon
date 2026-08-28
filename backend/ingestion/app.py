"""Health-checked Redis ingestion worker for live runtime projections."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

import redis.asyncio as redis
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from backend.application.runtime_pipeline import RuntimePipeline
from backend.config import get_settings
from backend.config.settings import Settings
from backend.contracts.api import SimulationStatus
from backend.contracts.enums import IncidentLifecycle, SimulationAction, SimulationState
from backend.contracts.events import OperationalEvent, PaymentEvent
from backend.ingestion.redis_streams import RedisStreamConsumer
from backend.persistence.runtime_store import PostgresRuntimeStore, RuntimeStore

RUNTIME_UPDATES_CHANNEL = "amex:runtime:updates:v1"
RUNTIME_EPOCH_KEY = "amex:synthetic:runtime-epoch:v1"
INGESTION_HEARTBEAT_KEY = "amex:synthetic:ingestion:heartbeat:v1"


class IngestionWorker:
    def __init__(self, client: redis.Redis, store: RuntimeStore, settings: Settings) -> None:
        self.client = client
        self.store = store
        self.settings = settings
        self.pipeline = self._new_pipeline()
        self.consumer = self._new_consumer()
        self.running = False
        self._epoch: str | None = None

    def _new_pipeline(self) -> RuntimePipeline:
        async def notify(event_type: str, payload: dict) -> None:
            await self.client.publish(
                RUNTIME_UPDATES_CHANNEL,
                json.dumps({"event_type": event_type, "payload": payload}),
            )

        return RuntimePipeline(self.store, self.settings, notify)

    def _new_consumer(self) -> RedisStreamConsumer:
        return RedisStreamConsumer(
            self.client,
            self.settings,
            consumer_name=f"ingestion-{uuid4().hex[:12]}",
            on_payment=lambda _event: None,
            on_operational=lambda _event: None,
            on_batch=self._commit_batch,
        )

    async def initialize(self) -> None:
        await self.pipeline.initialize()
        await self.client.setnx(RUNTIME_EPOCH_KEY, uuid4().hex)
        self._epoch = await self.client.get(RUNTIME_EPOCH_KEY)
        await self.consumer.ensure_groups()

    async def _commit_batch(
        self,
        payments: list[PaymentEvent],
        operations: list[OperationalEvent],
    ) -> None:
        epoch = await self.client.get(RUNTIME_EPOCH_KEY)
        if epoch != self._epoch:
            self.pipeline = self._new_pipeline()
            await self.pipeline.initialize()
            self._epoch = epoch
        snapshot = await self.pipeline.process_batch(
            payments,
            operations,
            as_of=datetime.now(UTC),
        )
        if snapshot is not None:
            await self._reconcile_simulation(snapshot.baseline_ready)

    async def _reconcile_simulation(self, baseline_ready: bool) -> None:
        payload = await self.store.get_resource("simulation", "current")
        if payload is None:
            return
        status = SimulationStatus.model_validate(payload)
        updated: SimulationStatus | None = None
        if status.state is SimulationState.PREWARMING and baseline_ready:
            await self.client.set("amex:synthetic:baseline-ready:v1", "1")
            updated = status.model_copy(
                update={
                    "state": SimulationState.RUNNING_HEALTHY,
                    "baseline_ready": True,
                    "available_actions": [
                        SimulationAction.INJECT_DEPLOYMENT_REGRESSION,
                        SimulationAction.STOP,
                        SimulationAction.RESET,
                    ],
                    "message": "Healthy baseline ready; live synthetic traffic is running",
                }
            )
        elif status.state is SimulationState.RECOVERING:
            incidents = await self.store.list_resources("incident_summary")
            if incidents and all(
                item.get("lifecycle") == IncidentLifecycle.RESOLVED.value for item in incidents
            ):
                await self.client.set("amex:synthetic:recovery-ready:v1", "1")
                updated = status.model_copy(
                    update={
                        "state": SimulationState.RUNNING_HEALTHY,
                        "baseline_ready": True,
                        "active_scenario_id": None,
                        "available_actions": [
                            SimulationAction.INJECT_DEPLOYMENT_REGRESSION,
                            SimulationAction.STOP,
                            SimulationAction.RESET,
                        ],
                        "message": "Recovery confirmed; healthy synthetic traffic is running",
                    }
                )
        if updated is not None:
            await self.store.put_resource("simulation", "current", updated.model_dump(mode="json"))
            await self.client.publish(
                RUNTIME_UPDATES_CHANNEL,
                json.dumps(
                    {
                        "event_type": "simulation.status.changed",
                        "payload": {"state": updated.state.value},
                    }
                ),
            )

    async def run(self) -> None:
        await self.initialize()
        self.running = True
        retry_delay = 0.25
        try:
            while True:
                try:
                    await self.consumer.consume_once(block_ms=1000, count=500)
                    await self.client.set(
                        INGESTION_HEARTBEAT_KEY,
                        datetime.now(UTC).isoformat(),
                        ex=10,
                    )
                    retry_delay = 0.25
                except asyncio.CancelledError:
                    raise
                except Exception:
                    self.running = False
                    await asyncio.sleep(retry_delay)
                    retry_delay = min(5.0, retry_delay * 2)
                    await self.consumer.ensure_groups()
                    self.running = True
        finally:
            self.running = False


def create_ingestion_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        settings = get_settings()
        client = redis.from_url(settings.redis_url, decode_responses=True)
        store = PostgresRuntimeStore(settings.postgres_dsn)
        worker = IngestionWorker(client, store, settings)
        application.state.redis = client
        application.state.worker = worker
        task = asyncio.create_task(worker.run(), name="redis-ingestion")
        try:
            yield
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await client.aclose()

    application = FastAPI(title="AMEX Runtime Ingestion", lifespan=lifespan)

    @application.get("/health")
    async def health() -> JSONResponse:
        worker: IngestionWorker = application.state.worker
        ready = worker.running
        return JSONResponse(
            {"status": "ok" if ready else "starting"},
            status_code=200 if ready else 503,
        )

    return application


app = create_ingestion_app()
