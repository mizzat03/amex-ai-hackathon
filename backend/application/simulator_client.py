"""Typed internal HTTP client for the separately deployed simulator process."""

from __future__ import annotations

from typing import Any

import httpx

from backend.contracts.api import SimulationStatus


class SimulatorTransportError(RuntimeError):
    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


class SimulatorHttpClient:
    SCENARIO_ID = "payment-gateway-v2.4.1-token-regression"

    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            transport=transport,
        )

    async def start(self, client_request_id: str) -> SimulationStatus:
        return await self._command("/internal/v1/start", client_request_id)

    async def inject(self, client_request_id: str) -> SimulationStatus:
        return await self._command("/internal/v1/inject", client_request_id)

    async def recover(self, client_request_id: str) -> SimulationStatus:
        return await self._command("/internal/v1/recover", client_request_id)

    async def stop(self, client_request_id: str) -> SimulationStatus:
        return await self._command("/internal/v1/stop", client_request_id)

    async def reset(self, client_request_id: str, confirmation: str) -> SimulationStatus:
        return await self._command(
            "/internal/v1/reset",
            client_request_id,
            confirmation=confirmation,
        )

    async def status(self) -> SimulationStatus:
        try:
            response = await self._client.get("/internal/v1/status")
            response.raise_for_status()
            return SimulationStatus.model_validate(response.json())
        except (httpx.HTTPError, ValueError) as exc:
            raise SimulatorTransportError(
                "simulator_http_failure",
                "The simulator process is temporarily unavailable.",
            ) from exc

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _command(
        self,
        path: str,
        client_request_id: str,
        **values: Any,
    ) -> SimulationStatus:
        payload = {"client_request_id": client_request_id, **values}
        try:
            response = await self._client.post(path, json=payload)
            response.raise_for_status()
            return SimulationStatus.model_validate(response.json())
        except (httpx.HTTPError, ValueError) as exc:
            # Never propagate response bodies from the internal process boundary.
            raise SimulatorTransportError(
                "simulator_http_failure",
                "The simulator command could not be completed.",
            ) from exc
