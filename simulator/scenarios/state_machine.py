"""Backend-authoritative simulator lifecycle with idempotent commands."""

from datetime import datetime

from backend.contracts.api import SimulationStatus
from backend.contracts.enums import SimulationAction, SimulationState


class InvalidSimulationAction(ValueError):
    """Raised when a command is invalid for the current simulator state."""


_ACTIONS: dict[SimulationState, list[SimulationAction]] = {
    SimulationState.STOPPED: [SimulationAction.START, SimulationAction.RESET],
    SimulationState.PREWARMING: [SimulationAction.STOP],
    SimulationState.RUNNING_HEALTHY: [
        SimulationAction.INJECT_DEPLOYMENT_REGRESSION,
        SimulationAction.STOP,
        SimulationAction.RESET,
    ],
    SimulationState.INJECTING: [SimulationAction.STOP],
    SimulationState.INCIDENT_ACTIVE: [
        SimulationAction.TRIGGER_ROLLBACK_RECOVERY,
        SimulationAction.STOP,
        SimulationAction.RESET,
    ],
    SimulationState.RECOVERING: [SimulationAction.STOP, SimulationAction.RESET],
    SimulationState.RESETTING: [],
    SimulationState.ERROR: [SimulationAction.STOP, SimulationAction.RESET],
}


class SimulatorStateMachine:
    def __init__(self) -> None:
        self._state = SimulationState.STOPPED
        self._baseline_ready = False
        self._active_scenario_id: str | None = None
        self._started_at: datetime | None = None
        self._message: str | None = "Synthetic simulator is stopped"
        self._command_results: dict[str, SimulationStatus] = {}

    def status(self) -> SimulationStatus:
        return SimulationStatus(
            state=self._state,
            baseline_ready=self._baseline_ready,
            active_scenario_id=self._active_scenario_id,
            started_at=self._started_at,
            available_actions=list(_ACTIONS[self._state]),
            message=self._message,
        )

    def restore(self, status: SimulationStatus) -> None:
        """Restore the last durable simulator state after a process restart."""
        self._state = status.state
        self._baseline_ready = status.baseline_ready
        self._active_scenario_id = status.active_scenario_id
        self._started_at = status.started_at
        self._message = status.message
        self._command_results.clear()

    def _replay(self, request_id: str) -> SimulationStatus | None:
        return self._command_results.get(request_id)

    def _remember(self, request_id: str) -> SimulationStatus:
        result = self.status()
        self._command_results[request_id] = result.model_copy(deep=True)
        return result

    def _require(self, action: SimulationAction) -> None:
        if action not in _ACTIONS[self._state]:
            raise InvalidSimulationAction(
                f"{action.value} is not allowed while {self._state.value}"
            )

    def start(self, request_id: str, started_at: datetime) -> SimulationStatus:
        if replay := self._replay(request_id):
            return replay
        self._require(SimulationAction.START)
        self._state = SimulationState.PREWARMING
        self._started_at = started_at
        self._baseline_ready = False
        self._message = "Pre-warming healthy history through Redis Streams"
        return self._remember(request_id)

    def complete_prewarm(self) -> SimulationStatus:
        if self._state is not SimulationState.PREWARMING:
            raise InvalidSimulationAction("pre-warm can complete only from PREWARMING")
        self._state = SimulationState.RUNNING_HEALTHY
        self._baseline_ready = True
        self._message = "Healthy baseline ready; live synthetic traffic is running"
        return self.status()

    def inject(self, request_id: str, scenario_id: str) -> SimulationStatus:
        if replay := self._replay(request_id):
            return replay
        self._require(SimulationAction.INJECT_DEPLOYMENT_REGRESSION)
        if scenario_id != "payment-gateway-v2.4.1-token-regression":
            raise InvalidSimulationAction("scenario is not allowlisted")
        self._state = SimulationState.INCIDENT_ACTIVE
        self._active_scenario_id = scenario_id
        self._message = "Payment Gateway v2.4.1 regression is active"
        return self._remember(request_id)

    def recover(self, request_id: str) -> SimulationStatus:
        if replay := self._replay(request_id):
            return replay
        self._require(SimulationAction.TRIGGER_ROLLBACK_RECOVERY)
        self._state = SimulationState.RECOVERING
        self._message = "Synthetic rollback emitted; healthy traffic is resuming"
        return self._remember(request_id)

    def complete_recovery(self) -> SimulationStatus:
        if self._state is not SimulationState.RECOVERING:
            raise InvalidSimulationAction("recovery can complete only from RECOVERING")
        self._state = SimulationState.RUNNING_HEALTHY
        self._active_scenario_id = None
        self._message = "Recovery confirmed; healthy synthetic traffic is running"
        return self.status()

    def stop(self, request_id: str) -> SimulationStatus:
        if replay := self._replay(request_id):
            return replay
        self._require(SimulationAction.STOP)
        self._state = SimulationState.STOPPED
        self._message = "Synthetic simulator is stopped"
        return self._remember(request_id)

    def reset(self, request_id: str, confirmation: str) -> SimulationStatus:
        if replay := self._replay(request_id):
            return replay
        self._require(SimulationAction.RESET)
        if confirmation != "RESET_SYNTHETIC_DEMO":
            raise InvalidSimulationAction("invalid synthetic reset confirmation")
        self._state = SimulationState.RESETTING
        self._message = "Resetting allowlisted synthetic demo data"
        return self._remember(request_id)

    def complete_reset(self) -> SimulationStatus:
        if self._state is not SimulationState.RESETTING:
            raise InvalidSimulationAction("reset can complete only from RESETTING")
        self._state = SimulationState.STOPPED
        self._baseline_ready = False
        self._active_scenario_id = None
        self._started_at = None
        self._message = "Synthetic demo data reset complete"
        self._command_results.clear()
        return self.status()

    def fail_reset(self) -> SimulationStatus:
        if self._state is not SimulationState.RESETTING:
            raise InvalidSimulationAction("reset can fail only from RESETTING")
        self._state = SimulationState.ERROR
        self._baseline_ready = False
        self._message = "Synthetic demo reset did not complete; stop or retry reset"
        self._command_results.clear()
        return self.status()
