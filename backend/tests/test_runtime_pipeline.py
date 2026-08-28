import asyncio
from datetime import UTC, datetime, timedelta

from backend.application.runtime_pipeline import RuntimePipeline
from backend.config.settings import Settings
from backend.persistence.runtime_store import InMemoryRuntimeStore
from simulator.operational_events.generator import deployment_event, rollback_event
from simulator.payment_events.generator import PaymentEventGenerator


def _settings() -> Settings:
    return Settings(
        bucket_duration_seconds=1,
        current_window_seconds=10,
        baseline_window_seconds=60,
        allowed_lateness_seconds=0,
        telemetry_stale_after_seconds=120,
        baseline_required_samples=200,
        min_current_attempts=80,
        min_baseline_attempts=200,
        min_current_technical_errors=5,
        min_absolute_error_rate_increase=0.005,
        detection_persistence_buckets=1,
        recovery_persistence_buckets=2,
        recovery_residual_margin=0.02,
        recovery_absolute_safety_ceiling=0.04,
        dimension_min_current_attempts=10,
        dimension_min_baseline_attempts=20,
        dimension_min_current_errors=3,
        dimension_min_excess_errors=2,
        dimension_min_rate_increase=0.005,
    )


def _traffic(
    generator: PaymentEventGenerator,
    start_at: datetime,
    seconds: int,
    per_second: int,
) -> list:
    return [
        event
        for second in range(seconds)
        for event in generator.generate_batch(per_second, start_at + timedelta(seconds=second))
    ]


def test_progressive_pipeline_projects_live_metrics_incident_evidence_and_recovery() -> None:
    async def exercise() -> None:
        settings = _settings()
        store = InMemoryRuntimeStore()
        pipeline = RuntimePipeline(store, settings)
        await pipeline.initialize()
        now = datetime(2026, 8, 28, 4, 0, tzinfo=UTC)
        healthy = PaymentEventGenerator(seed=101)

        baseline = _traffic(healthy, now - timedelta(seconds=70), 60, 10)
        current = _traffic(healthy, now - timedelta(seconds=10), 10, 20)
        await pipeline.process_batch([*baseline, *current], [], as_of=now)

        ready = await store.get_resource("overview", "current")
        assert ready is not None
        assert ready["baseline"]["ready"] is True
        assert ready["metrics"]["technical_error_rate"]["value"] is not None
        assert ready["latest_sample_at"] is not None
        assert ready["telemetry_stale_after_seconds"] == 120
        assert ready["active_incident_count"] == 0

        deployment = deployment_event(now)
        await pipeline.process_operational(deployment)
        injected = _traffic(PaymentEventGenerator(seed=202, injected=True), now, 10, 60)
        await pipeline.process_payments(injected, as_of=now + timedelta(seconds=11))

        incidents = await store.list_resources("incident_summary")
        assert len(incidents) == 1
        incident_id = incidents[0]["incident_id"]
        assert incidents[0]["lifecycle"] == "OPEN"
        assert incidents[0]["started_at"] != "2026-08-27T11:44:00Z"
        workspace = await store.get_resource("incident", incident_id)
        evidence = await store.get_resource("evidence", incident_id)
        assert workspace is not None
        assert evidence is not None
        assert evidence["items"]
        assert workspace["timeline"][0]["operational_event_id"] == str(deployment.event_id)

        await pipeline.process_operational(rollback_event(now + timedelta(seconds=12)))
        recovery_a = _traffic(healthy, now + timedelta(seconds=12), 10, 30)
        await pipeline.process_payments(recovery_a, as_of=now + timedelta(seconds=23))
        candidate = await store.get_resource("incident_summary", incident_id)
        assert candidate is not None
        assert candidate["lifecycle"] == "RECOVERY_CANDIDATE"

        recovery_b = _traffic(healthy, now + timedelta(seconds=23), 10, 30)
        await pipeline.process_payments(recovery_b, as_of=now + timedelta(seconds=34))
        resolved = await store.get_resource("incident_summary", incident_id)
        assert resolved is not None
        assert resolved["lifecycle"] == "RESOLVED"

        history = await store.get_resource("metric_history", "technical_error_rate")
        assert history is not None
        timestamps = [point["at"] for point in history["points"]]
        assert timestamps == sorted(timestamps)
        assert len(set(timestamps)) >= 4

    asyncio.run(exercise())


def test_pipeline_restores_window_and_incident_state_without_reprocessing_events() -> None:
    async def exercise() -> None:
        settings = _settings()
        store = InMemoryRuntimeStore()
        now = datetime(2026, 8, 28, 5, 0, tzinfo=UTC)
        healthy = PaymentEventGenerator(seed=101)
        pipeline = RuntimePipeline(store, settings)
        await pipeline.initialize()
        await pipeline.process_batch(
            [
                *_traffic(healthy, now - timedelta(seconds=70), 60, 10),
                *_traffic(healthy, now - timedelta(seconds=10), 10, 20),
            ],
            [],
            as_of=now,
        )
        injected = _traffic(PaymentEventGenerator(seed=202, injected=True), now, 10, 60)
        await pipeline.process_batch(
            injected,
            [deployment_event(now)],
            as_of=now + timedelta(seconds=11),
        )
        incident = (await store.list_resources("incident_summary"))[0]
        incident_id = incident["incident_id"]
        history_before = await store.get_resource("metric_history", "technical_error_rate")

        restarted = RuntimePipeline(store, settings)
        await restarted.initialize()
        assert (
            await restarted.process_batch(injected, [], as_of=now + timedelta(seconds=11)) is None
        )
        assert await store.get_resource("metric_history", "technical_error_rate") == history_before

        recovery_a = _traffic(healthy, now + timedelta(seconds=12), 10, 30)
        recovery_b = _traffic(healthy, now + timedelta(seconds=23), 10, 30)
        await restarted.process_batch(
            recovery_a,
            [rollback_event(now + timedelta(seconds=12))],
            as_of=now + timedelta(seconds=23),
        )
        await restarted.process_batch(recovery_b, [], as_of=now + timedelta(seconds=34))
        resolved = await store.get_resource("incident_summary", incident_id)
        assert resolved is not None
        assert resolved["lifecycle"] == "RESOLVED"

    asyncio.run(exercise())
