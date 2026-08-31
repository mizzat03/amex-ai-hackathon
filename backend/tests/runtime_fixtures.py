from backend.application.demo_projection import build_demo_projection
from backend.contracts.enums import MetricKey
from backend.persistence.runtime_store import RuntimeStore


async def seed_incident_fixture(store: RuntimeStore) -> None:
    """Explicit test-only seed; live initialization intentionally never calls this."""
    projection = build_demo_projection()
    await store.put_resource("overview", "current", projection.overview.model_dump(mode="json"))
    await store.put_resource(
        "metric_history",
        MetricKey.TECHNICAL_ERROR_RATE.value,
        projection.history.model_dump(mode="json"),
    )
    for summary in projection.incidents.items:
        await store.put_resource(
            "incident_summary", summary.incident_id, summary.model_dump(mode="json")
        )
    await store.put_resource(
        "incident", projection.workspace.incident_id, projection.workspace.model_dump(mode="json")
    )
    await store.put_resource(
        "evidence", projection.evidence.incident_id, projection.evidence.model_dump(mode="json")
    )
    await store.save_evidence_package(
        {
            **projection.evidence.model_dump(mode="json"),
            "package_version": projection.evidence.evidence_package_version,
            "schema_version": "evidence-package.v1",
            "builder_configuration_version": "demo-config.v1",
        }
    )
    await store.put_resource(
        "copilot_messages",
        projection.workspace.incident_id,
        projection.messages.model_dump(mode="json"),
    )
    await store.put_resource(
        "copilot_interaction",
        projection.interaction.interaction_id,
        projection.interaction.model_dump(mode="json"),
    )
    await store.put_resource(
        "simulation", "current", projection.simulation.model_dump(mode="json")
    )
