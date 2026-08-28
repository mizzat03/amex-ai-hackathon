"""Health-checked internal HTTP process for continuous synthetic event production."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Protocol

import redis.asyncio as redis
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from backend.config import get_settings
from backend.contracts.api import IdempotentCommandRequest, ResetSimulationRequest, SimulationStatus
from backend.contracts.enums import SimulationState
from simulator.service import SimulatorService


class SimulatorProcessService(Protocol):
    async def status(self) -> SimulationStatus: ...

    async def start(self, client_request_id: str) -> SimulationStatus: ...

    async def inject(self, client_request_id: str) -> SimulationStatus: ...

    async def recover(self, client_request_id: str) -> SimulationStatus: ...

    async def stop(self, client_request_id: str) -> SimulationStatus: ...

    async def reset(self, client_request_id: str, confirmation: str) -> SimulationStatus: ...


async def _traffic_loop(service: SimulatorService) -> None:
    settings = service.settings
    retry_delay = 0.25
    while True:
        try:
            status = await service.status()
            if status.state is SimulationState.PREWARMING:
                if await service.baseline_ready():
                    await service.complete_prewarm()
            elif status.state is SimulationState.RUNNING_HEALTHY:
                await service.publish_healthy(settings.simulator_batch_size)
            elif status.state is SimulationState.INCIDENT_ACTIVE:
                await service.publish_injected(settings.simulator_batch_size)
            elif status.state is SimulationState.RECOVERING:
                await service.publish_healthy(settings.simulator_batch_size)
                if await service.recovery_ready():
                    await service.complete_recovery()
            retry_delay = 0.25
            await asyncio.sleep(settings.simulator_tick_seconds)
        except asyncio.CancelledError:
            raise
        except Exception:
            await asyncio.sleep(retry_delay)
            retry_delay = min(5.0, retry_delay * 2)


def create_simulator_app(service: SimulatorProcessService | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        if service is not None:
            application.state.service = service
            yield
            return
        settings = get_settings()
        client = redis.from_url(settings.redis_url, decode_responses=True)
        runtime_service = SimulatorService(client, settings)
        await runtime_service.initialize()
        application.state.service = runtime_service
        task = asyncio.create_task(_traffic_loop(runtime_service), name="simulator-traffic")
        try:
            yield
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await client.aclose()

    application = FastAPI(title="AMEX Synthetic Simulator", lifespan=lifespan)

    def current() -> SimulatorProcessService:
        return application.state.service

    @application.get("/health")
    async def health() -> JSONResponse:
        ping = getattr(current(), "ping", None)
        ready = True if ping is None else bool(await ping())
        return JSONResponse(
            {"status": "ok" if ready else "unavailable"},
            status_code=200 if ready else 503,
        )

    @application.get("/internal/v1/status", response_model=SimulationStatus)
    async def status() -> SimulationStatus:
        return await current().status()

    @application.post("/internal/v1/start", response_model=SimulationStatus)
    async def start(payload: IdempotentCommandRequest) -> SimulationStatus:
        return await current().start(payload.client_request_id)

    @application.post("/internal/v1/inject", response_model=SimulationStatus)
    async def inject(payload: IdempotentCommandRequest) -> SimulationStatus:
        return await current().inject(payload.client_request_id)

    @application.post("/internal/v1/recover", response_model=SimulationStatus)
    async def recover(payload: IdempotentCommandRequest) -> SimulationStatus:
        return await current().recover(payload.client_request_id)

    @application.post("/internal/v1/stop", response_model=SimulationStatus)
    async def stop(payload: IdempotentCommandRequest) -> SimulationStatus:
        return await current().stop(payload.client_request_id)

    @application.post("/internal/v1/reset", response_model=SimulationStatus)
    async def reset(payload: ResetSimulationRequest) -> SimulationStatus:
        return await current().reset(payload.client_request_id, payload.confirmation)

    return application


app = create_simulator_app()
