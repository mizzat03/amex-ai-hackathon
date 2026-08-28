from fastapi.testclient import TestClient

from backend.contracts.api import SimulationStatus
from simulator.api import create_simulator_app


class FakeProcessService:
    async def status(self) -> SimulationStatus:
        return SimulationStatus(
            state="STOPPED",
            baseline_ready=False,
            available_actions=["START", "RESET"],
            message="ready",
        )

    async def start(self, client_request_id: str) -> SimulationStatus:
        return SimulationStatus(
            state="PREWARMING",
            baseline_ready=False,
            available_actions=["STOP"],
            message=f"warming {client_request_id}",
        )


def test_simulator_process_exposes_health_status_and_internal_commands() -> None:
    app = create_simulator_app(FakeProcessService())
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}
        assert client.get("/internal/v1/status").json()["state"] == "STOPPED"
        started = client.post(
            "/internal/v1/start",
            json={"client_request_id": "start-process-1"},
        )
        assert started.status_code == 200
        assert started.json()["state"] == "PREWARMING"
