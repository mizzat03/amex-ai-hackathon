"""Exercise the complete local judge path over real REST and WebSocket transports."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

import httpx
import websockets


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="http://127.0.0.1:8100/api/v1")
    parser.add_argument("--output", type=Path, default=Path("docs/e2e-observations.json"))
    return parser.parse_args()


async def verify(args: argparse.Namespace) -> None:
    timings: dict[str, list[float]] = {}

    async with httpx.AsyncClient(base_url=args.api_url, timeout=20) as client:
        async def request(method: str, path: str, **kwargs: Any) -> dict[str, Any]:
            started = perf_counter()
            response = await client.request(method, path, **kwargs)
            timings.setdefault(f"{method} {path}", []).append((perf_counter() - started) * 1000)
            response.raise_for_status()
            return response.json()

        async def wait_for_simulation_state(expected: str, *, attempts: int = 80) -> dict[str, Any]:
            status: dict[str, Any] = {}
            for _ in range(attempts):
                status = await request("GET", "/simulation/status")
                if status["state"] == expected:
                    return status
                await asyncio.sleep(0.25)
            raise AssertionError(
                f"Simulator did not reach {expected}; latest state was {status.get('state')}"
            )

        async def wait_for_active_incident(*, attempts: int = 80) -> dict[str, Any]:
            overview: dict[str, Any] = {}
            for _ in range(attempts):
                overview = await request("GET", "/system/overview")
                if overview["active_incidents"]:
                    return overview
                await asyncio.sleep(0.25)
            raise AssertionError("The injected scenario did not produce an active incident")

        ws_url = args.api_url.replace("http://", "ws://").replace("https://", "wss://") + "/ws/updates"
        async with websockets.connect(ws_url, open_timeout=10) as socket:
            health = await request("GET", "/health")
            assert health["datastore"] == health["stream"] == "available"

            initial_status = await request("GET", "/simulation/status")
            if "RESET" not in initial_status["available_actions"]:
                assert "STOP" in initial_status["available_actions"]
                stopped = await request(
                    "POST",
                    "/simulation/stop",
                    json={"client_request_id": f"e2e-stop-before-reset-{uuid4().hex}"},
                )
                assert stopped["state"] == "STOPPED"

            reset = await request(
                "POST",
                "/simulation/reset",
                json={
                    "client_request_id": f"e2e-reset-{uuid4().hex}",
                    "confirmation": "RESET_SYNTHETIC_DEMO",
                },
            )
            assert reset["state"] == "STOPPED"
            clean_overview = await request("GET", "/system/overview")
            clean_incidents = await request("GET", "/incidents")
            assert clean_overview["active_incident_count"] == 0
            assert clean_overview["active_incidents"] == []
            assert clean_incidents["items"] == []
            first_event = json.loads(await asyncio.wait_for(socket.recv(), timeout=5))

            started = await request(
                "POST",
                "/simulation/start",
                json={"client_request_id": f"e2e-start-{uuid4().hex}"},
            )
            assert started["state"] in {"PREWARMING", "RUNNING_HEALTHY"}
            await wait_for_simulation_state("RUNNING_HEALTHY")
            # The public projection and the simulator's persisted state are updated
            # asynchronously; give the command endpoint one tick to observe readiness.
            await asyncio.sleep(0.5)
            injected = await request(
                "POST",
                "/simulation/scenarios/payment-gateway-v2.4.1-token-regression/inject",
                json={"client_request_id": f"e2e-inject-{uuid4().hex}"},
            )
            assert injected["state"] == "INCIDENT_ACTIVE"

            overview = await wait_for_active_incident()
            assert overview["metrics"]["business_decline_rate"] != overview["metrics"]["technical_error_rate"]
            assert overview["punchline_metric"]["metric_key"] == "technical_error_rate"
            assert datetime.fromisoformat(
                overview["active_incidents"][0]["started_at"]
            ) >= datetime.fromisoformat(started["started_at"])
            incident_id = overview["active_incidents"][0]["incident_id"]
            workspace = await request("GET", f"/incidents/{incident_id}")
            evidence = await request("GET", f"/incidents/{incident_id}/evidence")
            assert workspace["rca_summary"]["leading_hypothesis"]["evidence_tier"] in {
                "MODERATE_EVIDENCE",
                "STRONG_EVIDENCE",
            }
            assert evidence["completeness"] in {"COMPLETE", "PARTIAL"}

            accepted = await request(
                "POST",
                f"/incidents/{incident_id}/copilot/queries",
                json={
                    "question": "What evidence weakens the leading hypothesis?",
                    "evidence_package_id": evidence["evidence_package_id"],
                    "evidence_package_version": evidence["evidence_package_version"],
                    "client_request_id": f"e2e-copilot-{uuid4().hex}",
                },
            )
            interaction: dict[str, Any] = {}
            for _ in range(160):
                interaction = await request(
                    "GET",
                    f"/incidents/{incident_id}/copilot/interactions/{accepted['interaction_id']}",
                )
                if interaction["status"] in {"VALIDATED", "FALLBACK", "FAILED"}:
                    break
                await asyncio.sleep(0.25)
            assert interaction["status"] in {"VALIDATED", "FALLBACK"}
            if interaction["status"] == "FALLBACK":
                assert interaction["deterministic_fallback"]["available"] is True

            review = await request(
                "PUT",
                f"/incidents/{incident_id}/human-review",
                json={
                    "hypothesis_id": workspace["rca_summary"]["leading_hypothesis"]["hypothesis_id"],
                    "status": "ACKNOWLEDGED",
                    "note": "E2E synthetic review",
                    "expected_version": workspace["human_review"]["version"],
                },
            )
            assert review["reviewed_by"] == "demo-operator"

            recovered = await request(
                "POST",
                "/simulation/recovery",
                json={"client_request_id": f"e2e-recovery-{uuid4().hex}"},
            )
            assert recovered["state"] == "RECOVERING"

            sequences = [int(first_event["sequence"])]
            while len(sequences) < 4:
                event = json.loads(await asyncio.wait_for(socket.recv(), timeout=5))
                sequences.append(int(event["sequence"]))
            assert sequences == sorted(sequences) and len(set(sequences)) == len(sequences)

    report = {
        "status": "PASS",
        "generated_at": datetime.now(UTC).isoformat(),
        "scenario": "healthy -> injected incident -> evidence investigation -> validated AI or controlled fallback -> human review -> recovery",
        "websocket_sequences": sequences,
        "observed_request_latency_ms": {
            key: {"count": len(values), "min": round(min(values), 2), "max": round(max(values), 2)}
            for key, values in timings.items()
        },
        "copilot_terminal_status": interaction["status"],
        "cost_observation": (
            "Deterministic fallback has no model-token cost."
            if interaction["status"] == "FALLBACK"
            else "A validated provider response was observed; this verifier does not inspect credential or billing data."
        ),
        "scope": "Single local synthetic run; measurements are observations, not production claims.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("Live REST/WebSocket demo verification passed.")


def main() -> None:
    asyncio.run(verify(arguments()))


if __name__ == "__main__":
    main()
