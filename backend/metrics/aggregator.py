"""Fixed event-time buckets, non-overlapping windows, and versioned snapshots."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from math import ceil, floor
from typing import Any

from backend.config.settings import Settings
from backend.contracts.enums import PaymentOutcome, TelemetryState
from backend.contracts.events import PaymentEvent


class IngestDisposition(StrEnum):
    ACCEPTED = "ACCEPTED"
    ACCEPTED_LATE = "ACCEPTED_LATE"
    DROPPED_TOO_LATE = "DROPPED_TOO_LATE"


@dataclass(slots=True)
class AggregateCounter:
    total_attempts: int = 0
    approved_count: int = 0
    business_decline_count: int = 0
    technical_error_count: int = 0
    error_code_counts: dict[str, int] = field(default_factory=dict)
    latency_observations_ms: list[float] = field(default_factory=list)

    def add(self, event: PaymentEvent) -> None:
        self.total_attempts += 1
        self.latency_observations_ms.append(event.authorization_latency_ms)
        if event.outcome is PaymentOutcome.APPROVED:
            self.approved_count += 1
        elif event.outcome is PaymentOutcome.BUSINESS_DECLINE:
            self.business_decline_count += 1
        elif event.outcome is PaymentOutcome.TECHNICAL_ERROR:
            self.technical_error_count += 1
            self.error_code_counts[event.normalized_code] = (
                self.error_code_counts.get(event.normalized_code, 0) + 1
            )

    def merge(self, other: "AggregateCounter") -> None:
        self.total_attempts += other.total_attempts
        self.approved_count += other.approved_count
        self.business_decline_count += other.business_decline_count
        self.technical_error_count += other.technical_error_count
        self.latency_observations_ms.extend(other.latency_observations_ms)
        for code, count in other.error_code_counts.items():
            self.error_code_counts[code] = self.error_code_counts.get(code, 0) + count

    def clone(self) -> "AggregateCounter":
        return AggregateCounter(
            total_attempts=self.total_attempts,
            approved_count=self.approved_count,
            business_decline_count=self.business_decline_count,
            technical_error_count=self.technical_error_count,
            error_code_counts=dict(self.error_code_counts),
            latency_observations_ms=list(self.latency_observations_ms),
        )


@dataclass(slots=True)
class MetricBucket:
    start_at: datetime
    duration_seconds: int
    overall: AggregateCounter = field(default_factory=AggregateCounter)
    dimensions: dict[str, dict[str, AggregateCounter]] = field(
        default_factory=lambda: {
            "processing_region": {},
            "payment_method": {},
            "service_version": {},
        }
    )
    combinations: dict[tuple[str, str, str], AggregateCounter] = field(default_factory=dict)

    @property
    def end_at(self) -> datetime:
        return self.start_at + timedelta(seconds=self.duration_seconds)

    def add(self, event: PaymentEvent) -> None:
        self.overall.add(event)
        values = {
            "processing_region": event.processing_region,
            "payment_method": event.payment_method.value,
            "service_version": event.service_version,
        }
        for dimension, value in values.items():
            self.dimensions[dimension].setdefault(value, AggregateCounter()).add(event)
        combination = (
            event.processing_region,
            event.payment_method.value,
            event.service_version,
        )
        self.combinations.setdefault(combination, AggregateCounter()).add(event)


@dataclass(slots=True)
class WindowAggregate(AggregateCounter):
    start_at: datetime | None = None
    end_at: datetime | None = None
    duration_seconds: int = 0
    dimensions: dict[str, dict[str, AggregateCounter]] = field(
        default_factory=lambda: {
            "processing_region": {},
            "payment_method": {},
            "service_version": {},
        }
    )
    combinations: dict[tuple[str, str, str], AggregateCounter] = field(default_factory=dict)
    unavailable_reason: str | None = None

    @property
    def approval_rate(self) -> float | None:
        return self.approved_count / self.total_attempts if self.total_attempts else None

    @property
    def business_decline_rate(self) -> float | None:
        return self.business_decline_count / self.total_attempts if self.total_attempts else None

    @property
    def technical_error_rate(self) -> float | None:
        return self.technical_error_count / self.total_attempts if self.total_attempts else None

    @property
    def throughput(self) -> float | None:
        return self.total_attempts / self.duration_seconds if self.duration_seconds else None

    @property
    def average_authorization_latency_ms(self) -> float | None:
        if not self.latency_observations_ms:
            return None
        return sum(self.latency_observations_ms) / len(self.latency_observations_ms)

    @property
    def p95_authorization_latency_ms(self) -> float | None:
        if not self.latency_observations_ms:
            return None
        ordered = sorted(self.latency_observations_ms)
        rank = max(1, ceil(0.95 * len(ordered)))
        return ordered[rank - 1]


@dataclass(frozen=True, slots=True)
class MetricSnapshot:
    snapshot_version: int
    generated_at: datetime
    configuration_version: str
    bucket_evidence_end_at: datetime
    telemetry_state: TelemetryState
    baseline_ready: bool
    current: WindowAggregate
    baseline: WindowAggregate
    late_event_count: int


@dataclass(frozen=True, slots=True)
class MetricHistoryPoint:
    at: datetime
    value: float | None
    unavailable_reason: str | None


@dataclass(frozen=True, slots=True)
class MetricHistorySeries:
    metric_key: str
    resolution_seconds: int
    points: tuple[MetricHistoryPoint, ...]


class EventTimeAggregator:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._buckets: dict[datetime, MetricBucket] = {}
        self._max_occurred_at: datetime | None = None
        self._late_event_count = 0
        self._snapshot_version = 0
        self._snapshots: list[MetricSnapshot] = []

    @property
    def late_event_count(self) -> int:
        return self._late_event_count

    @property
    def latest_event_at(self) -> datetime | None:
        return self._max_occurred_at

    @staticmethod
    def _counter_state(counter: AggregateCounter) -> dict[str, Any]:
        return {
            "total_attempts": counter.total_attempts,
            "approved_count": counter.approved_count,
            "business_decline_count": counter.business_decline_count,
            "technical_error_count": counter.technical_error_count,
            "error_code_counts": dict(counter.error_code_counts),
            "latency_observations_ms": list(counter.latency_observations_ms),
        }

    @staticmethod
    def _counter_from_state(payload: dict[str, Any]) -> AggregateCounter:
        return AggregateCounter(
            total_attempts=int(payload.get("total_attempts", 0)),
            approved_count=int(payload.get("approved_count", 0)),
            business_decline_count=int(payload.get("business_decline_count", 0)),
            technical_error_count=int(payload.get("technical_error_count", 0)),
            error_code_counts={
                str(key): int(value)
                for key, value in dict(payload.get("error_code_counts", {})).items()
            },
            latency_observations_ms=[
                float(value) for value in payload.get("latency_observations_ms", [])
            ],
        )

    def export_state(self) -> dict[str, Any]:
        """Return a bounded JSON-compatible checkpoint for worker restarts."""
        retention_seconds = (
            self.settings.baseline_window_seconds
            + self.settings.current_window_seconds
            + self.settings.allowed_lateness_seconds
            + self.settings.bucket_duration_seconds
        )
        cutoff = (
            self._max_occurred_at - timedelta(seconds=retention_seconds)
            if self._max_occurred_at is not None
            else None
        )
        buckets = []
        for bucket in sorted(self._buckets.values(), key=lambda item: item.start_at):
            if cutoff is not None and bucket.end_at < cutoff:
                continue
            buckets.append(
                {
                    "start_at": bucket.start_at.isoformat(),
                    "duration_seconds": bucket.duration_seconds,
                    "overall": self._counter_state(bucket.overall),
                    "dimensions": {
                        dimension: {
                            value: self._counter_state(counter)
                            for value, counter in values.items()
                        }
                        for dimension, values in bucket.dimensions.items()
                    },
                    "combinations": [
                        {"values": list(values), "counter": self._counter_state(counter)}
                        for values, counter in bucket.combinations.items()
                    ],
                }
            )
        return {
            "max_occurred_at": (
                self._max_occurred_at.isoformat()
                if self._max_occurred_at is not None
                else None
            ),
            "late_event_count": self._late_event_count,
            "snapshot_version": self._snapshot_version,
            "buckets": buckets,
        }

    def import_state(self, payload: dict[str, Any]) -> None:
        """Restore a checkpoint created by :meth:`export_state`."""
        self._buckets.clear()
        for item in payload.get("buckets", []):
            bucket = MetricBucket(
                start_at=datetime.fromisoformat(item["start_at"]),
                duration_seconds=int(item["duration_seconds"]),
                overall=self._counter_from_state(item["overall"]),
                dimensions={
                    dimension: {
                        value: self._counter_from_state(counter)
                        for value, counter in values.items()
                    }
                    for dimension, values in item.get("dimensions", {}).items()
                },
                combinations={
                    tuple(combination["values"]): self._counter_from_state(
                        combination["counter"]
                    )
                    for combination in item.get("combinations", [])
                },
            )
            self._buckets[bucket.start_at] = bucket
        maximum = payload.get("max_occurred_at")
        self._max_occurred_at = datetime.fromisoformat(maximum) if maximum else None
        self._late_event_count = int(payload.get("late_event_count", 0))
        self._snapshot_version = int(payload.get("snapshot_version", 0))
        self._snapshots.clear()

    def bucket_start_for(self, occurred_at: datetime) -> datetime:
        utc = occurred_at.astimezone(UTC)
        seconds = self.settings.bucket_duration_seconds
        bucket_epoch = floor(utc.timestamp() / seconds) * seconds
        return datetime.fromtimestamp(bucket_epoch, tz=UTC)

    def ingest(self, event: PaymentEvent) -> IngestDisposition:
        occurred_at = event.occurred_at.astimezone(UTC)
        disposition = IngestDisposition.ACCEPTED
        if self._max_occurred_at is not None and occurred_at < self._max_occurred_at:
            lateness = (self._max_occurred_at - occurred_at).total_seconds()
            if lateness > self.settings.allowed_lateness_seconds:
                self._late_event_count += 1
                return IngestDisposition.DROPPED_TOO_LATE
            disposition = IngestDisposition.ACCEPTED_LATE
        if self._max_occurred_at is None or occurred_at > self._max_occurred_at:
            self._max_occurred_at = occurred_at
        start = self.bucket_start_for(occurred_at)
        bucket = self._buckets.setdefault(
            start, MetricBucket(start, self.settings.bucket_duration_seconds)
        )
        bucket.add(event)
        return disposition

    def snapshot(self, as_of: datetime) -> MetricSnapshot:
        as_of = as_of.astimezone(UTC)
        evidence_end = self.bucket_start_for(as_of)
        current_start = evidence_end - timedelta(seconds=self.settings.current_window_seconds)
        baseline_start = current_start - timedelta(seconds=self.settings.baseline_window_seconds)
        current = self._merge_window(current_start, evidence_end)
        baseline = self._merge_window(baseline_start, current_start)
        baseline_ready = (
            baseline.total_attempts >= self.settings.baseline_required_samples
            and baseline.total_attempts >= self.settings.min_baseline_attempts
        )
        telemetry_state = self._telemetry_state(as_of, current, baseline_ready)
        self._snapshot_version += 1
        snapshot = MetricSnapshot(
            snapshot_version=self._snapshot_version,
            generated_at=as_of,
            configuration_version=self.settings.configuration_version,
            bucket_evidence_end_at=evidence_end,
            telemetry_state=telemetry_state,
            baseline_ready=baseline_ready,
            current=current,
            baseline=baseline,
            late_event_count=self._late_event_count,
        )
        self._snapshots.append(snapshot)
        return snapshot

    def history(self, metric_key: str, start_at: datetime, end_at: datetime) -> MetricHistorySeries:
        attribute = {
            "technical_error_rate": "technical_error_rate",
            "approval_rate": "approval_rate",
            "business_decline_rate": "business_decline_rate",
            "throughput": "throughput",
            "average_authorization_latency": "average_authorization_latency_ms",
            "p95_authorization_latency": "p95_authorization_latency_ms",
        }.get(metric_key)
        if attribute is None:
            raise ValueError(f"unsupported metric key {metric_key}")
        points = tuple(
            MetricHistoryPoint(
                at=snapshot.generated_at,
                value=getattr(snapshot.current, attribute),
                unavailable_reason=snapshot.current.unavailable_reason,
            )
            for snapshot in self._snapshots
            if start_at <= snapshot.generated_at <= end_at
        )
        return MetricHistorySeries(metric_key, self.settings.bucket_duration_seconds, points)

    def _merge_window(self, start_at: datetime, end_at: datetime) -> WindowAggregate:
        result = WindowAggregate(
            start_at=start_at,
            end_at=end_at,
            duration_seconds=int((end_at - start_at).total_seconds()),
        )
        for bucket in self._buckets.values():
            if bucket.start_at < start_at or bucket.end_at > end_at:
                continue
            result.merge(bucket.overall)
            for dimension, values in bucket.dimensions.items():
                for value, counter in values.items():
                    result.dimensions[dimension].setdefault(value, AggregateCounter()).merge(counter)
            for combination, counter in bucket.combinations.items():
                result.combinations.setdefault(combination, AggregateCounter()).merge(counter)
        if result.total_attempts == 0:
            result.unavailable_reason = "no telemetry in window"
        return result

    def _telemetry_state(
        self, as_of: datetime, current: WindowAggregate, baseline_ready: bool
    ) -> TelemetryState:
        if self._max_occurred_at is None or current.total_attempts == 0:
            return TelemetryState.UNKNOWN
        age = (as_of - self._max_occurred_at).total_seconds()
        if age > self.settings.telemetry_stale_after_seconds:
            return TelemetryState.STALE
        if not baseline_ready or current.total_attempts < self.settings.min_current_attempts:
            return TelemetryState.WARMING_UP
        return TelemetryState.HEALTHY
