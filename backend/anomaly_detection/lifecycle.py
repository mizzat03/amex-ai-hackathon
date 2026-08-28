"""Thread-safe explicit incident lifecycle, deduplication, cooldown, and recovery."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from statistics import NormalDist
from threading import RLock
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from backend.anomaly_detection.detector import DetectionEvaluation
from backend.config.settings import Settings
from backend.contracts.enums import IncidentLifecycle, IncidentSeverity, TelemetryState


@dataclass(slots=True)
class Incident:
    incident_id: str
    fingerprint: str
    metric_family: str
    scope: str
    lifecycle: IncidentLifecycle
    severity: IncidentSeverity
    started_at: datetime
    updated_at: datetime
    version: int = 1
    signal_scopes: set[str] = field(default_factory=set)
    closure_mode: str | None = None
    manual_closure_reason: str | None = None


@dataclass(frozen=True, slots=True)
class LifecycleTransition:
    lifecycle: IncidentLifecycle
    incident: Incident | None
    changed: bool
    reason: str


@dataclass(slots=True)
class _SignalState:
    lifecycle: IncidentLifecycle = IncidentLifecycle.WARMING_UP
    detection_count: int = 0
    recovery_count: int = 0
    last_evidence_end_at: datetime | None = None
    frozen_baseline_attempts: int | None = None
    frozen_baseline_errors: int | None = None
    incident_id: str | None = None
    cooldown_until: datetime | None = None


class IncidentLifecycleManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._states: dict[str, _SignalState] = {}
        self._incidents: dict[str, Incident] = {}
        self._evaluations: dict[str, DetectionEvaluation] = {}
        self._lock = RLock()

    @property
    def incident_count(self) -> int:
        return len(self._incidents)

    @property
    def evaluations(self) -> tuple[DetectionEvaluation, ...]:
        return tuple(self._evaluations.values())

    def export_state(self) -> dict[str, Any]:
        """Serialize only deterministic lifecycle state needed across restarts."""
        with self._lock:
            return {
                "signals": {
                    fingerprint: {
                        "lifecycle": state.lifecycle.value,
                        "detection_count": state.detection_count,
                        "recovery_count": state.recovery_count,
                        "last_evidence_end_at": (
                            state.last_evidence_end_at.isoformat()
                            if state.last_evidence_end_at
                            else None
                        ),
                        "frozen_baseline_attempts": state.frozen_baseline_attempts,
                        "frozen_baseline_errors": state.frozen_baseline_errors,
                        "incident_id": state.incident_id,
                        "cooldown_until": (
                            state.cooldown_until.isoformat() if state.cooldown_until else None
                        ),
                    }
                    for fingerprint, state in self._states.items()
                },
                "incidents": {
                    incident_id: {
                        "incident_id": incident.incident_id,
                        "fingerprint": incident.fingerprint,
                        "metric_family": incident.metric_family,
                        "scope": incident.scope,
                        "lifecycle": incident.lifecycle.value,
                        "severity": incident.severity.value,
                        "started_at": incident.started_at.isoformat(),
                        "updated_at": incident.updated_at.isoformat(),
                        "version": incident.version,
                        "signal_scopes": sorted(incident.signal_scopes),
                        "closure_mode": incident.closure_mode,
                        "manual_closure_reason": incident.manual_closure_reason,
                    }
                    for incident_id, incident in self._incidents.items()
                },
            }

    def import_state(self, payload: dict[str, Any]) -> None:
        """Restore lifecycle state from the typed JSON checkpoint."""
        with self._lock:
            self._states = {
                fingerprint: _SignalState(
                    lifecycle=IncidentLifecycle(item["lifecycle"]),
                    detection_count=int(item.get("detection_count", 0)),
                    recovery_count=int(item.get("recovery_count", 0)),
                    last_evidence_end_at=(
                        datetime.fromisoformat(item["last_evidence_end_at"])
                        if item.get("last_evidence_end_at")
                        else None
                    ),
                    frozen_baseline_attempts=item.get("frozen_baseline_attempts"),
                    frozen_baseline_errors=item.get("frozen_baseline_errors"),
                    incident_id=item.get("incident_id"),
                    cooldown_until=(
                        datetime.fromisoformat(item["cooldown_until"])
                        if item.get("cooldown_until")
                        else None
                    ),
                )
                for fingerprint, item in payload.get("signals", {}).items()
            }
            self._incidents = {
                incident_id: Incident(
                    incident_id=item["incident_id"],
                    fingerprint=item["fingerprint"],
                    metric_family=item["metric_family"],
                    scope=item["scope"],
                    lifecycle=IncidentLifecycle(item["lifecycle"]),
                    severity=IncidentSeverity(item["severity"]),
                    started_at=datetime.fromisoformat(item["started_at"]),
                    updated_at=datetime.fromisoformat(item["updated_at"]),
                    version=int(item.get("version", 1)),
                    signal_scopes=set(item.get("signal_scopes", [])),
                    closure_mode=item.get("closure_mode"),
                    manual_closure_reason=item.get("manual_closure_reason"),
                )
                for incident_id, item in payload.get("incidents", {}).items()
            }
            self._evaluations.clear()

    def apply(self, evaluation: DetectionEvaluation) -> LifecycleTransition:
        fingerprint = f"{evaluation.metric_family}:{evaluation.scope}"
        with self._lock:
            self._evaluations.setdefault(evaluation.evaluation_id, evaluation)
            state = self._states.setdefault(fingerprint, _SignalState())
            incident = self._incident_for(state)
            if state.last_evidence_end_at == evaluation.bucket_evidence_end_at:
                return LifecycleTransition(state.lifecycle, incident, False, "UNCHANGED_EVIDENCE")
            state.last_evidence_end_at = evaluation.bucket_evidence_end_at

            if evaluation.telemetry_state is not TelemetryState.HEALTHY:
                if incident is None:
                    state.lifecycle = IncidentLifecycle.WARMING_UP
                return LifecycleTransition(state.lifecycle, incident, False, evaluation.reason_code)

            if state.lifecycle is IncidentLifecycle.RESOLVED:
                if state.cooldown_until and evaluation.evaluated_at < state.cooldown_until:
                    return LifecycleTransition(state.lifecycle, incident, False, "COOLDOWN_ACTIVE")
                state = _SignalState(
                    lifecycle=IncidentLifecycle.HEALTHY,
                    last_evidence_end_at=evaluation.bucket_evidence_end_at,
                )
                self._states[fingerprint] = state
                incident = None

            if evaluation.is_anomaly:
                state.recovery_count = 0
                if state.lifecycle in {IncidentLifecycle.WARMING_UP, IncidentLifecycle.HEALTHY}:
                    state.lifecycle = IncidentLifecycle.SUSPECTED
                    state.detection_count = 1
                    state.frozen_baseline_attempts = evaluation.baseline_attempts
                    state.frozen_baseline_errors = evaluation.baseline_errors
                elif state.lifecycle is IncidentLifecycle.SUSPECTED:
                    state.detection_count += 1
                elif state.lifecycle is IncidentLifecycle.RECOVERY_CANDIDATE:
                    state.lifecycle = IncidentLifecycle.OPEN
                    state.detection_count = self.settings.detection_persistence_buckets
                if state.detection_count >= self.settings.detection_persistence_buckets:
                    if incident is None:
                        incident = self._open_incident(fingerprint, evaluation, state)
                    state.lifecycle = IncidentLifecycle.OPEN
                    incident.lifecycle = IncidentLifecycle.OPEN
                    incident.updated_at = evaluation.evaluated_at
                    incident.version += 1
                    return LifecycleTransition(state.lifecycle, incident, True, "INCIDENT_OPEN")
                return LifecycleTransition(state.lifecycle, None, True, "ANOMALY_SUSPECTED")

            if incident is not None and state.lifecycle in {
                IncidentLifecycle.OPEN,
                IncidentLifecycle.RECOVERY_CANDIDATE,
            }:
                if self._passes_recovery(evaluation, state):
                    state.recovery_count += 1
                    state.lifecycle = IncidentLifecycle.RECOVERY_CANDIDATE
                    incident.lifecycle = state.lifecycle
                    incident.updated_at = evaluation.evaluated_at
                    incident.version += 1
                    if state.recovery_count >= self.settings.recovery_persistence_buckets:
                        state.lifecycle = IncidentLifecycle.RESOLVED
                        incident.lifecycle = state.lifecycle
                        incident.closure_mode = "AUTOMATIC_RECOVERY"
                        state.cooldown_until = evaluation.evaluated_at + timedelta(
                            seconds=self.settings.cooldown_seconds
                        )
                        return LifecycleTransition(
                            state.lifecycle, incident, True, "RECOVERY_CONFIRMED"
                        )
                    return LifecycleTransition(
                        state.lifecycle, incident, True, "RECOVERY_CANDIDATE"
                    )
                state.recovery_count = 0
                state.lifecycle = IncidentLifecycle.OPEN
                incident.lifecycle = state.lifecycle
                incident.updated_at = evaluation.evaluated_at
                return LifecycleTransition(
                    state.lifecycle, incident, False, "RECOVERY_NOT_CONFIRMED"
                )

            state.lifecycle = IncidentLifecycle.HEALTHY
            state.detection_count = 0
            return LifecycleTransition(state.lifecycle, None, True, evaluation.reason_code)

    def manual_close(self, incident_id: str, reason: str) -> Incident:
        if not reason.strip():
            raise ValueError("manual closure requires a recorded reason")
        with self._lock:
            incident = self._incidents[incident_id]
            incident.lifecycle = IncidentLifecycle.RESOLVED
            incident.closure_mode = "MANUAL"
            incident.manual_closure_reason = reason.strip()
            incident.version += 1
            state = self._states[incident.fingerprint]
            state.lifecycle = IncidentLifecycle.RESOLVED
            state.cooldown_until = incident.updated_at + timedelta(
                seconds=self.settings.cooldown_seconds
            )
            return incident

    def _open_incident(
        self, fingerprint: str, evaluation: DetectionEvaluation, state: _SignalState
    ) -> Incident:
        if evaluation.scope != "GLOBAL":
            global_state = self._states.get(f"{evaluation.metric_family}:GLOBAL")
            parent = self._incident_for(global_state) if global_state else None
            if parent and parent.lifecycle is not IncidentLifecycle.RESOLVED:
                parent.signal_scopes.add(evaluation.scope)
                state.incident_id = parent.incident_id
                return parent
        incident_key = fingerprint + evaluation.bucket_evidence_end_at.isoformat()
        incident_id = f"inc_{uuid5(NAMESPACE_URL, incident_key).hex[:16]}"
        incident = self._incidents.get(incident_id)
        if incident is None:
            incident = Incident(
                incident_id=incident_id,
                fingerprint=fingerprint,
                metric_family=evaluation.metric_family,
                scope=evaluation.scope,
                lifecycle=IncidentLifecycle.OPEN,
                severity=self._severity(evaluation),
                started_at=evaluation.evaluated_at,
                updated_at=evaluation.evaluated_at,
                signal_scopes={evaluation.scope},
            )
            self._incidents[incident_id] = incident
        state.incident_id = incident_id
        return incident

    def _passes_recovery(self, evaluation: DetectionEvaluation, state: _SignalState) -> bool:
        if (
            evaluation.telemetry_state is not TelemetryState.HEALTHY
            or evaluation.current_attempts < self.settings.min_current_attempts
            or evaluation.baseline_attempts < self.settings.min_baseline_attempts
            or not state.frozen_baseline_attempts
            or state.frozen_baseline_errors is None
        ):
            return False
        current_rate = evaluation.current_errors / evaluation.current_attempts
        baseline_rate = state.frozen_baseline_errors / state.frozen_baseline_attempts
        z = NormalDist().inv_cdf(1 - self.settings.recovery_alpha)
        difference_se = (
            current_rate * (1 - current_rate) / evaluation.current_attempts
            + baseline_rate * (1 - baseline_rate) / state.frozen_baseline_attempts
        ) ** 0.5
        difference_upper = current_rate - baseline_rate + z * difference_se
        current_upper = (
            current_rate
            + z * (current_rate * (1 - current_rate) / evaluation.current_attempts) ** 0.5
        )
        return (
            difference_upper <= self.settings.recovery_residual_margin
            and current_upper <= self.settings.recovery_absolute_safety_ceiling
        )

    @staticmethod
    def _severity(evaluation: DetectionEvaluation) -> IncidentSeverity:
        delta = evaluation.absolute_increase or 0
        if delta >= 0.08 or evaluation.current_errors >= 50:
            return IncidentSeverity.HIGH
        if delta >= 0.04 or evaluation.current_errors >= 20:
            return IncidentSeverity.MEDIUM
        return IncidentSeverity.LOW

    def _incident_for(self, state: _SignalState | None) -> Incident | None:
        if state is None or state.incident_id is None:
            return None
        return self._incidents.get(state.incident_id)
