"""OpenAPI must remain the sole public contract source for generated TypeScript."""

from backend.api.app import app


def test_all_frozen_routes_are_versioned_and_present() -> None:
    paths = set(app.openapi()["paths"])
    expected = {
        "/api/v1/health",
        "/api/v1/system/overview",
        "/api/v1/metrics/history",
        "/api/v1/incidents",
        "/api/v1/incidents/{incident_id}",
        "/api/v1/incidents/{incident_id}/evidence",
        "/api/v1/incidents/{incident_id}/evidence/{evidence_id}",
        "/api/v1/incidents/{incident_id}/copilot/messages",
        "/api/v1/incidents/{incident_id}/copilot/queries",
        "/api/v1/incidents/{incident_id}/copilot/interactions/{interaction_id}",
        "/api/v1/incidents/{incident_id}/copilot/interactions/{interaction_id}/retry",
        "/api/v1/incidents/{incident_id}/human-review",
        "/api/v1/copilot/messages/{message_id}/feedback",
        "/api/v1/simulation/status",
        "/api/v1/simulation/start",
        "/api/v1/simulation/stop",
        "/api/v1/simulation/scenarios/{scenario_id}/inject",
        "/api/v1/simulation/recovery",
        "/api/v1/simulation/reset",
    }
    assert expected <= paths
    assert all(path.startswith("/api/v1") for path in paths)


def test_openapi_has_one_typed_error_envelope() -> None:
    schemas = app.openapi()["components"]["schemas"]
    assert "ApiError" in schemas
    assert "ErrorDetail" in schemas
