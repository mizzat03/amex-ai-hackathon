import asyncio
import json

import httpx

from backend.application.simulator_client import SimulatorHttpClient, SimulatorTransportError


def _status(state: str) -> dict:
    actions = ["START", "RESET"] if state == "STOPPED" else ["STOP", "RESET"]
    return {
        "state": state,
        "baseline_ready": state == "RUNNING_HEALTHY",
        "active_scenario_id": None,
        "started_at": None,
        "available_actions": actions,
        "message": "safe status",
    }


def test_api_uses_typed_http_transport_to_command_the_separate_simulator() -> None:
    async def exercise() -> None:
        requests: list[tuple[str, dict]] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content) if request.content else {}
            requests.append((request.url.path, payload))
            state = {
                "/internal/v1/start": "PREWARMING",
                "/internal/v1/inject": "INCIDENT_ACTIVE",
                "/internal/v1/recover": "RECOVERING",
                "/internal/v1/stop": "STOPPED",
                "/internal/v1/reset": "STOPPED",
            }[request.url.path]
            return httpx.Response(200, json=_status(state))

        client = SimulatorHttpClient(
            "http://simulator:8010",
            transport=httpx.MockTransport(handler),
        )
        try:
            assert (await client.start("start-1")).state.value == "PREWARMING"
            assert (await client.inject("inject-1")).state.value == "INCIDENT_ACTIVE"
            assert (await client.recover("recover-1")).state.value == "RECOVERING"
            assert (await client.stop("stop-1")).state.value == "STOPPED"
            assert (await client.reset("reset-1", "RESET_SYNTHETIC_DEMO")).state.value == "STOPPED"
        finally:
            await client.aclose()

        assert requests[0] == ("/internal/v1/start", {"client_request_id": "start-1"})
        assert requests[-1][1]["confirmation"] == "RESET_SYNTHETIC_DEMO"

    asyncio.run(exercise())


def test_simulator_transport_failure_exposes_only_a_safe_category() -> None:
    async def exercise() -> None:
        async def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="internal stack and secret-bearing response")

        client = SimulatorHttpClient(
            "http://simulator:8010",
            transport=httpx.MockTransport(handler),
        )
        try:
            await client.start("start-failure")
        except SimulatorTransportError as exc:
            assert exc.reason_code == "simulator_http_failure"
            assert "secret-bearing" not in str(exc)
        else:
            raise AssertionError("transport failures must be surfaced safely")
        finally:
            await client.aclose()

    asyncio.run(exercise())
