"""FastAPI application implementing the frozen v1 REST and WebSocket boundary."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, AsyncIterator
import asyncio
import json
from uuid import uuid4

from fastapi import Body, FastAPI, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from redis.asyncio import Redis

from backend.application.investigator_service import InvestigatorService, ServiceError
from backend.application.simulator_client import SimulatorHttpClient
from backend.copilot.orchestrator import CopilotConfiguration, CopilotOrchestrator
from backend.copilot.provider import provider_from_settings
from backend.config import get_settings
from backend.contracts.api import (
    ApiError,
    CopilotFeedbackRequest,
    CopilotInteractionView,
    CopilotMessagePage,
    CursorPage,
    EvidenceDetailResponse,
    EvidenceProjectionResponse,
    HealthResponse,
    HumanReviewRequest,
    HumanReviewView,
    IdempotentCommandRequest,
    IncidentSummary,
    IncidentWorkspaceResponse,
    InjectScenarioRequest,
    MetricHistoryResponse,
    ResetSimulationRequest,
    ResourceVersion,
    SimulationStatus,
    SubmitCopilotQueryRequest,
    SubmitCopilotQueryResponse,
    SystemOverviewResponse,
)
from backend.contracts.enums import IncidentSeverity, MetricKey, SimulationAction
from backend.persistence.runtime_store import PostgresRuntimeStore
from backend.ingestion.app import RUNTIME_EPOCH_KEY, RUNTIME_UPDATES_CHANNEL

API_VERSION = "1.1.0"
ERROR_RESPONSES = {
    400: {"model": ApiError, "description": "Invalid command"},
    404: {"model": ApiError, "description": "Resource not found"},
    409: {"model": ApiError, "description": "Version or state conflict"},
    422: {"model": ApiError, "description": "Validation error"},
    503: {"model": ApiError, "description": "Dependency unavailable"},
}


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    if hasattr(application.state, "service"):
        yield
        return
    settings = get_settings()
    redis_client: Redis = Redis.from_url(settings.redis_url, decode_responses=True)
    store = PostgresRuntimeStore(settings.postgres_dsn)
    simulator = SimulatorHttpClient(settings.simulator_url)
    copilot = CopilotOrchestrator(
        provider_from_settings(settings),
        configuration=CopilotConfiguration(
            initial_max_output_tokens=settings.copilot_initial_max_output_tokens,
            follow_up_max_output_tokens=settings.copilot_follow_up_max_output_tokens,
            timeout_seconds=settings.copilot_timeout_seconds,
        ),
    )
    async def reset_runtime() -> None:
        await redis_client.set(RUNTIME_EPOCH_KEY, uuid4().hex)
        await redis_client.publish(
            RUNTIME_UPDATES_CHANNEL,
            json.dumps({"event_type": "system.overview.updated", "payload": {"reset": True}}),
        )

    service = InvestigatorService(
        store,
        simulator,
        copilot,
        runtime_reset=reset_runtime,
        settings=settings,
    )
    await service.initialize()

    async def relay_runtime_updates() -> None:
        pubsub = redis_client.pubsub()
        await pubsub.subscribe(RUNTIME_UPDATES_CHANNEL)
        try:
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                try:
                    envelope = json.loads(message["data"])
                    await service.broker.publish(
                        str(envelope["event_type"]),
                        dict(envelope.get("payload", {})),
                    )
                except (KeyError, TypeError, ValueError):
                    continue
        finally:
            await pubsub.aclose()

    relay_task = asyncio.create_task(relay_runtime_updates(), name="runtime-update-relay")
    application.state.redis = redis_client
    application.state.service = service
    try:
        yield
    finally:
        relay_task.cancel()
        await asyncio.gather(relay_task, return_exceptions=True)
        await service.wait_for_copilot_tasks()
        await simulator.aclose()
        await redis_client.aclose()
        del application.state.redis
        del application.state.service


app = FastAPI(
    title="AI Payment Incident Investigator API",
    version=API_VERSION,
    description="Synthetic-data hackathon MVP. All acting identity is server-side demo-operator.",
    lifespan=lifespan,
)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Content-Type", "X-Request-ID"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next: Any) -> Any:
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Cache-Control"] = "no-store"
    return response


def _error_payload(
    request: Request,
    *,
    code: str,
    message: str,
    retryable: bool,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    request_id = request.headers.get("X-Request-ID", f"req_{uuid4().hex}")
    return ApiError.model_validate(
        {
            "error": {
                "code": code,
                "message": message,
                "retryable": retryable,
                "request_id": request_id,
                "details": details,
            }
        }
    ).model_dump(mode="json")


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=_error_payload(
            request,
            code="VALIDATION_ERROR",
            message="Request validation failed",
            retryable=False,
            details={"errors": exc.errors(include_url=False, include_input=False)},
        ),
    )


@app.exception_handler(ServiceError)
async def service_error_handler(request: Request, exc: ServiceError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_payload(
            request,
            code=exc.code,
            message=exc.message,
            retryable=exc.retryable,
            details=exc.details,
        ),
    )


def _service(request: Request) -> InvestigatorService:
    service = getattr(request.app.state, "service", None)
    if service is None:
        raise ServiceError(503, "INTERNAL_ERROR", "Application service is not ready", retryable=True)
    return service


@app.get("/api/v1/health", response_model=HealthResponse, responses=ERROR_RESPONSES)
async def health(request: Request) -> HealthResponse | JSONResponse:
    service = _service(request)
    datastore_ready = await service.store.ping()
    redis_client: Redis | None = getattr(request.app.state, "redis", None)
    try:
        stream_ready = bool(redis_client and await redis_client.ping())
    except Exception:
        stream_ready = False
    result = HealthResponse(
        status="ok" if datastore_ready and stream_ready else "degraded",
        generated_at=datetime.now(UTC),
        datastore="available" if datastore_ready else "unavailable",
        stream="available" if stream_ready else "unavailable",
    )
    if result.status != "ok":
        return JSONResponse(status_code=503, content=result.model_dump(mode="json"))
    return result


@app.get("/api/v1/system/overview", response_model=SystemOverviewResponse, responses=ERROR_RESPONSES)
async def system_overview(request: Request) -> SystemOverviewResponse:
    return await _service(request).overview()


@app.get("/api/v1/metrics/history", response_model=MetricHistoryResponse, responses=ERROR_RESPONSES)
async def metric_history(
    request: Request,
    metric_key: MetricKey,
    start_at: datetime,
    end_at: datetime,
    incident_id: str | None = None,
) -> MetricHistoryResponse:
    del incident_id
    return await _service(request).metric_history(metric_key, start_at, end_at)


@app.get("/api/v1/incidents", response_model=CursorPage[IncidentSummary], responses=ERROR_RESPONSES)
async def list_incidents(
    request: Request,
    started_at_or_after: datetime | None = None,
    started_before: datetime | None = None,
    severity: list[IncidentSeverity] | None = Query(default=None),
    processing_region: list[str] | None = Query(default=None),
    payment_method: list[str] | None = Query(default=None),
    sort_by: str | None = None,
    sort_direction: str | None = None,
    cursor: str | None = None,
) -> CursorPage[IncidentSummary]:
    return await _service(request).list_incidents(
        started_at_or_after=started_at_or_after,
        started_before=started_before,
        severity=severity,
        processing_region=processing_region,
        payment_method=payment_method,
        sort_by=sort_by,
        sort_direction=sort_direction,
        cursor=cursor,
    )


@app.get("/api/v1/incidents/{incident_id}", response_model=IncidentWorkspaceResponse, responses=ERROR_RESPONSES)
async def incident_workspace(request: Request, incident_id: str) -> IncidentWorkspaceResponse:
    return await _service(request).incident(incident_id)


@app.get("/api/v1/incidents/{incident_id}/evidence", response_model=EvidenceProjectionResponse, responses=ERROR_RESPONSES)
async def incident_evidence(
    request: Request,
    incident_id: str,
    evidence_package_id: str | None = None,
    evidence_package_version: int | None = None,
) -> EvidenceProjectionResponse:
    return await _service(request).evidence(
        incident_id, evidence_package_id, evidence_package_version
    )


@app.get("/api/v1/incidents/{incident_id}/evidence/{evidence_id}", response_model=EvidenceDetailResponse, responses=ERROR_RESPONSES)
async def evidence_detail(
    request: Request, incident_id: str, evidence_id: str
) -> EvidenceDetailResponse:
    return await _service(request).evidence_detail(incident_id, evidence_id)


@app.get("/api/v1/incidents/{incident_id}/copilot/messages", response_model=CopilotMessagePage, responses=ERROR_RESPONSES)
async def copilot_messages(
    request: Request, incident_id: str, cursor: str | None = None
) -> CopilotMessagePage:
    if cursor not in {None, ""}:
        raise ServiceError(422, "VALIDATION_ERROR", "The supplied cursor is invalid")
    return await _service(request).copilot_messages(incident_id)


@app.post(
    "/api/v1/incidents/{incident_id}/copilot/initial-report",
    response_model=CopilotInteractionView,
    status_code=202,
    responses=ERROR_RESPONSES,
)
async def request_initial_copilot_report(
    request: Request, incident_id: str
) -> CopilotInteractionView:
    return await _service(request).request_initial_copilot_report(incident_id)


@app.post("/api/v1/incidents/{incident_id}/copilot/queries", response_model=SubmitCopilotQueryResponse, status_code=202, responses=ERROR_RESPONSES)
async def submit_copilot_query(
    request: Request, incident_id: str, payload: SubmitCopilotQueryRequest
) -> SubmitCopilotQueryResponse:
    return await _service(request).submit_copilot_query(incident_id, payload)


@app.get("/api/v1/incidents/{incident_id}/copilot/interactions/{interaction_id}", response_model=CopilotInteractionView, responses=ERROR_RESPONSES)
async def copilot_interaction(
    request: Request, incident_id: str, interaction_id: str
) -> CopilotInteractionView:
    return await _service(request).copilot_interaction(incident_id, interaction_id)


@app.post("/api/v1/incidents/{incident_id}/copilot/interactions/{interaction_id}/retry", response_model=CopilotInteractionView, responses=ERROR_RESPONSES)
async def retry_copilot_interaction(
    request: Request,
    incident_id: str,
    interaction_id: str,
    payload: IdempotentCommandRequest = Body(...),
) -> CopilotInteractionView:
    del payload
    return await _service(request).retry_copilot(incident_id, interaction_id)


@app.put("/api/v1/incidents/{incident_id}/human-review", response_model=HumanReviewView, responses=ERROR_RESPONSES)
async def update_human_review(
    request: Request, incident_id: str, payload: HumanReviewRequest
) -> HumanReviewView:
    return await _service(request).update_human_review(incident_id, payload)


@app.post("/api/v1/copilot/messages/{message_id}/feedback", response_model=ResourceVersion, responses=ERROR_RESPONSES)
async def submit_copilot_feedback(
    request: Request, message_id: str, payload: CopilotFeedbackRequest
) -> ResourceVersion:
    return await _service(request).submit_feedback(message_id, payload)


@app.get("/api/v1/simulation/status", response_model=SimulationStatus, responses=ERROR_RESPONSES)
async def simulation_status(request: Request) -> SimulationStatus:
    return await _service(request).simulation_status()


@app.post("/api/v1/simulation/start", response_model=SimulationStatus, responses=ERROR_RESPONSES)
async def simulation_start(request: Request, payload: IdempotentCommandRequest) -> SimulationStatus:
    return await _service(request).simulation_command(SimulationAction.START, payload.client_request_id)


@app.post("/api/v1/simulation/stop", response_model=SimulationStatus, responses=ERROR_RESPONSES)
async def simulation_stop(request: Request, payload: IdempotentCommandRequest) -> SimulationStatus:
    return await _service(request).simulation_command(SimulationAction.STOP, payload.client_request_id)


@app.post("/api/v1/simulation/scenarios/{scenario_id}/inject", response_model=SimulationStatus, responses=ERROR_RESPONSES)
async def simulation_inject(
    request: Request, scenario_id: str, payload: InjectScenarioRequest
) -> SimulationStatus:
    return await _service(request).simulation_command(
        SimulationAction.INJECT_DEPLOYMENT_REGRESSION,
        payload.client_request_id,
        scenario_id=scenario_id,
    )


@app.post("/api/v1/simulation/recovery", response_model=SimulationStatus, responses=ERROR_RESPONSES)
async def simulation_recovery(
    request: Request, payload: IdempotentCommandRequest
) -> SimulationStatus:
    return await _service(request).simulation_command(
        SimulationAction.TRIGGER_ROLLBACK_RECOVERY, payload.client_request_id
    )


@app.post("/api/v1/simulation/reset", response_model=SimulationStatus, responses=ERROR_RESPONSES)
async def simulation_reset(request: Request, payload: ResetSimulationRequest) -> SimulationStatus:
    return await _service(request).simulation_command(
        SimulationAction.RESET,
        payload.client_request_id,
        confirmation=payload.confirmation,
    )


@app.websocket("/api/v1/ws/updates")
async def websocket_updates(websocket: WebSocket) -> None:
    service: InvestigatorService | None = getattr(websocket.app.state, "service", None)
    if service is None:
        await websocket.close(code=1013, reason="Application service is not ready")
        return
    await websocket.accept()
    try:
        async with service.broker.subscribe() as queue:
            while True:
                await websocket.send_json(await queue.get())
    except WebSocketDisconnect:
        return
