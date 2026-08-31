import asyncio
import os
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from backend.api.app import app
from backend.application.investigator_service import InvestigatorService
from backend.contracts.api import SimulationStatus
from backend.persistence.runtime_store import InMemoryRuntimeStore, PostgresRuntimeStore
from backend.tests.runtime_fixtures import seed_incident_fixture


class FakeRedis:
    async def ping(self) -> bool:
        return True


class FakeSimulator:
    SCENARIO_ID = "payment-gateway-v2.4.1-token-regression"

    async def status(self) -> SimulationStatus:
        return SimulationStatus(
            state="STOPPED",
            baseline_ready=False,
            available_actions=["START", "RESET"],
            message="Authoritative simulator status",
        )

    async def start(self, client_request_id: str) -> SimulationStatus:
        return SimulationStatus(
            state="RUNNING_HEALTHY",
            baseline_ready=True,
            started_at="2026-08-27T12:00:00Z",
            available_actions=["INJECT_DEPLOYMENT_REGRESSION", "STOP", "RESET"],
            message=f"Started by {client_request_id}",
        )

    async def inject(self, client_request_id: str) -> SimulationStatus:
        return SimulationStatus(
            state="INCIDENT_ACTIVE",
            baseline_ready=True,
            active_scenario_id=self.SCENARIO_ID,
            started_at="2026-08-27T12:00:00Z",
            available_actions=["TRIGGER_ROLLBACK_RECOVERY", "STOP", "RESET"],
            message=f"Injected by {client_request_id}",
        )

    async def recover(self, client_request_id: str) -> SimulationStatus:
        return SimulationStatus(
            state="RECOVERING",
            baseline_ready=True,
            active_scenario_id=self.SCENARIO_ID,
            started_at="2026-08-27T12:00:00Z",
            available_actions=["STOP", "RESET"],
            message=f"Recovery by {client_request_id}",
        )

    async def stop(self, client_request_id: str) -> SimulationStatus:
        return SimulationStatus(
            state="STOPPED",
            baseline_ready=True,
            available_actions=["START", "RESET"],
            message=f"Stopped by {client_request_id}",
        )

    async def reset(self, client_request_id: str, confirmation: str) -> SimulationStatus:
        assert confirmation == "RESET_SYNTHETIC_DEMO"
        return SimulationStatus(
            state="STOPPED",
            baseline_ready=False,
            available_actions=["START", "RESET"],
            message=f"Reset by {client_request_id}",
        )


@contextmanager
def api_client() -> Iterator[TestClient]:
    service = InvestigatorService(InMemoryRuntimeStore(), FakeSimulator())
    asyncio.run(service.initialize())
    asyncio.run(seed_incident_fixture(service.store))
    app.state.service = service
    app.state.redis = FakeRedis()
    try:
        with TestClient(app) as client:
            yield client
    finally:
        del app.state.redis
        del app.state.service


def test_frozen_retrieval_resources_and_safe_errors() -> None:
    with api_client() as client:
        health = client.get("/api/v1/health")
        assert health.status_code == 200
        assert health.json()["datastore"] == "available"
        overview = client.get("/api/v1/system/overview")
        assert overview.status_code == 200
        assert overview.json()["punchline_metric"]["metric_key"] == "technical_error_rate"
        history = client.get(
            "/api/v1/metrics/history",
            params={
                "metric_key": "technical_error_rate",
                "start_at": "2026-08-27T11:36:00Z",
                "end_at": "2026-08-27T11:53:00Z",
            },
        )
        assert history.status_code == 200
        assert history.json()["resolution_seconds"] == 60
        incidents = client.get("/api/v1/incidents", params={"severity": "HIGH"})
        assert incidents.status_code == 200
        assert [item["incident_id"] for item in incidents.json()["items"]] == ["INC-2026-0827-017"]
        incident_id = "INC-2026-0827-017"
        assert client.get(f"/api/v1/incidents/{incident_id}").status_code == 200
        evidence = client.get(f"/api/v1/incidents/{incident_id}/evidence")
        assert evidence.status_code == 200
        detail = client.get(f"/api/v1/incidents/{incident_id}/evidence/EV-SCOPE-001")
        assert detail.status_code == 200
        assert detail.json()["item"]["evidence_id"] == "EV-SCOPE-001"
        messages = client.get(f"/api/v1/incidents/{incident_id}/copilot/messages")
        assert messages.status_code == 200
        initial = client.post(f"/api/v1/incidents/{incident_id}/copilot/initial-report")
        assert initial.status_code == 503
        assert initial.json()["error"]["code"] == "COPILOT_UNAVAILABLE"
        missing = client.get("/api/v1/incidents/does-not-exist")
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "RESOURCE_NOT_FOUND"
        assert "trace" not in missing.text.lower()


def test_review_feedback_copilot_idempotency_and_websocket_invalidation() -> None:
    with api_client() as client:
        incident_id = "INC-2026-0827-017"
        with client.websocket_connect("/api/v1/ws/updates") as websocket:
            review = client.put(
                f"/api/v1/incidents/{incident_id}/human-review",
                json={
                    "hypothesis_id": "HYP-DEPLOY-241",
                    "status": "ACKNOWLEDGED",
                    "note": "Reviewed against the versioned package.",
                    "expected_version": 1,
                },
            )
            assert review.status_code == 200
            assert review.json()["reviewed_by"] == "demo-operator"
            event = websocket.receive_json()
            assert event["event_type"] == "human_review.updated"
            assert event["sequence"] == 1
        incident_page = client.get("/api/v1/incidents?sort_by=started_at&sort_direction=desc")
        assert incident_page.status_code == 200
        assert incident_page.json()["items"][0]["human_review_status"] == "ACKNOWLEDGED"
        conflict = client.put(
            f"/api/v1/incidents/{incident_id}/human-review",
            json={
                "hypothesis_id": "HYP-DEPLOY-241",
                "status": "ACKNOWLEDGED",
                "expected_version": 1,
            },
        )
        assert conflict.status_code == 409
        query = {
            "question": "What evidence weakens the leading hypothesis?",
            "evidence_package_id": "EP-INC-017",
            "evidence_package_version": 3,
            "client_request_id": "query-1",
        }
        first = client.post(f"/api/v1/incidents/{incident_id}/copilot/queries", json=query)
        second = client.post(f"/api/v1/incidents/{incident_id}/copilot/queries", json=query)
        assert first.status_code == second.status_code == 202
        assert first.json() == second.json()
        interaction_id = first.json()["interaction_id"]
        assert (
            client.get(
                f"/api/v1/incidents/{incident_id}/copilot/interactions/{interaction_id}"
            ).json()["status"]
            == "QUEUED"
        )
        feedback = client.post(
            "/api/v1/copilot/messages/COP-MSG-017/feedback",
            json={"rating": "HELPFUL", "problem_types": []},
        )
        assert feedback.status_code == 200
        assert feedback.json()["version"] == 1


def test_canonical_copilot_routes_auto_create_thread_and_reject_bad_cursor() -> None:
    with api_client() as client:
        incident_id = "INC-2026-0827-017"
        created = client.get(f"/api/v1/incidents/{incident_id}/copilot/thread")
        reopened = client.get(f"/api/v1/incidents/{incident_id}/copilot/thread")
        assert created.status_code == reopened.status_code == 200
        assert created.json()["thread"]["thread_id"] == reopened.json()["thread"]["thread_id"]

        accepted = client.post(
            f"/api/v1/incidents/{incident_id}/copilot/messages",
            json={
                "question": "What evidence changed?",
                "client_request_id": "canonical-api-1",
                "referenced_message_ids": [],
            },
        )
        assert accepted.status_code == 202
        assert accepted.json()["thread_id"] == created.json()["thread"]["thread_id"]
        assert accepted.json()["evidence_package_version"] == 3

        messages = client.get(f"/api/v1/incidents/{incident_id}/copilot/messages")
        assert messages.status_code == 200
        assert [item["role"] for item in messages.json()["items"]] == ["USER"]
        malformed = client.get(
            f"/api/v1/incidents/{incident_id}/copilot/messages",
            params={"cursor": "not-a-cursor"},
        )
        assert malformed.status_code == 422
        assert malformed.json()["error"]["code"] == "VALIDATION_ERROR"


def test_allowlisted_simulation_commands_are_idempotent() -> None:
    with api_client() as client:
        started = client.post("/api/v1/simulation/start", json={"client_request_id": "start-1"})
        assert started.status_code == 200
        assert started.json()["state"] == "RUNNING_HEALTHY"
        repeated = client.post("/api/v1/simulation/start", json={"client_request_id": "start-1"})
        assert repeated.json() == started.json()
        blocked = client.post(
            "/api/v1/simulation/scenarios/not-allowlisted/inject",
            json={"client_request_id": "inject-bad"},
        )
        assert blocked.status_code == 400
        assert blocked.json()["error"]["code"] == "SCENARIO_NOT_ALLOWED"
        injected = client.post(
            f"/api/v1/simulation/scenarios/{FakeSimulator.SCENARIO_ID}/inject",
            json={"client_request_id": "inject-1"},
        )
        assert injected.status_code == 200
        assert injected.json()["state"] == "INCIDENT_ACTIVE"


def test_simulation_status_recovers_when_its_projection_is_missing() -> None:
    with api_client() as client:
        asyncio.run(app.state.service.store.reset_synthetic_data())

        response = client.get("/api/v1/simulation/status")

        assert response.status_code == 200
        assert response.json()["state"] == "STOPPED"
        persisted = asyncio.run(
            app.state.service.store.get_resource("simulation", "current")
        )
        assert persisted == response.json()


@pytest.mark.skipif(
    os.getenv("AMEX_RUN_POSTGRES_TESTS") != "1",
    reason="Set AMEX_RUN_POSTGRES_TESTS=1 with the local Compose database running",
)
def test_postgres_runtime_store_round_trip() -> None:
    async def exercise() -> None:
        store = PostgresRuntimeStore(
            os.getenv(
                "AMEX_POSTGRES_DSN",
                "postgresql://amex:amex@localhost:5432/amex_incidents",
            )
        )
        await store.migrate()
        await store.put_resource("integration_test", "round-trip", {"safe": True})
        await store.put_command("integration-reset-probe", "request-1", {"safe": True})
        assert await store.get_resource("integration_test", "round-trip") == {"safe": True}
        assert await store.get_command("integration-reset-probe", "request-1") == {"safe": True}
        try:
            await store.reset_synthetic_data()
            assert await store.get_command("integration-reset-probe", "request-1") is None
            assert await store.get_resource("integration_test", "round-trip") == {"safe": True}
            assert await store.ping()
        finally:
            # This opt-in test can share the local Compose database with the running
            # demo. Restore the clean projection so verification never leaves the UI
            # without overview or simulation status records.
            await InvestigatorService(store).initialize(migrate=False)

    asyncio.run(exercise())
