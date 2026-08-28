"""Deterministic simulator and state-machine specifications."""

from datetime import UTC, datetime

import pytest

from backend.contracts.enums import PaymentOutcome, SimulationAction, SimulationState
from simulator.payment_events.generator import PaymentEventGenerator
from simulator.scenarios.state_machine import InvalidSimulationAction, SimulatorStateMachine


def test_simulator_actions_are_progressive_and_backend_authoritative() -> None:
    machine = SimulatorStateMachine()
    assert machine.status().state is SimulationState.STOPPED
    assert machine.status().available_actions == [SimulationAction.START, SimulationAction.RESET]

    machine.start("start-1", datetime.now(UTC))
    assert machine.status().state is SimulationState.PREWARMING
    assert machine.status().available_actions == [SimulationAction.STOP]

    machine.complete_prewarm()
    assert machine.status().state is SimulationState.RUNNING_HEALTHY
    assert SimulationAction.INJECT_DEPLOYMENT_REGRESSION in machine.status().available_actions

    machine.inject("inject-1", "payment-gateway-v2.4.1-token-regression")
    assert machine.status().state is SimulationState.INCIDENT_ACTIVE
    assert machine.status().available_actions[0] is SimulationAction.TRIGGER_ROLLBACK_RECOVERY

    machine.recover("recover-1")
    assert machine.status().state is SimulationState.RECOVERING
    machine.stop("stop-1")
    assert machine.status().state is SimulationState.STOPPED


def test_simulator_commands_are_idempotent_and_invalid_actions_are_rejected() -> None:
    machine = SimulatorStateMachine()
    first = machine.start("same-request", datetime.now(UTC))
    replay = machine.start("same-request", datetime.now(UTC))
    assert replay == first

    with pytest.raises(InvalidSimulationAction):
        machine.inject("inject-too-soon", "payment-gateway-v2.4.1-token-regression")

    with pytest.raises(InvalidSimulationAction):
        machine.reset("reset-bad", "RESET_EVERYTHING")


def test_deterministic_generator_separates_outcomes_and_targets_only_approved_scope() -> None:
    generated_at = datetime(2026, 8, 27, 6, 0, tzinfo=UTC)
    healthy = PaymentEventGenerator(seed=20260827, injected=False).generate_batch(500, generated_at)
    injected = PaymentEventGenerator(seed=20260827, injected=True).generate_batch(500, generated_at)

    assert {event.outcome for event in healthy} == {
        PaymentOutcome.APPROVED,
        PaymentOutcome.BUSINESS_DECLINE,
        PaymentOutcome.TECHNICAL_ERROR,
    }
    regression_errors = [
        event for event in injected if event.normalized_code == "TOKEN_VALIDATION_FAILED"
    ]
    assert regression_errors
    assert all(event.processing_region == "SG" for event in regression_errors)
    assert all(event.payment_method.value == "MOBILE_WALLET" for event in regression_errors)
    assert all(event.service_version == "v2.4.1" for event in regression_errors)

    business_declines = [
        event for event in injected if event.outcome is PaymentOutcome.BUSINESS_DECLINE
    ]
    assert business_declines
    assert all(event.normalized_code != "TOKEN_VALIDATION_FAILED" for event in business_declines)


def test_separate_continuous_batches_do_not_reuse_event_ids() -> None:
    first_at = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
    second_at = datetime(2026, 8, 28, 12, 0, 1, tzinfo=UTC)

    first = PaymentEventGenerator(seed=20260828).generate_batch(25, first_at)
    second = PaymentEventGenerator(seed=20260828).generate_batch(25, second_at)

    assert {event.event_id for event in first}.isdisjoint(event.event_id for event in second)


def test_injected_scenario_clears_the_configured_global_detection_floor() -> None:
    injected = PaymentEventGenerator(seed=20260829, injected=True).generate_batch(
        5_000,
        datetime(2026, 8, 28, 12, 0, tzinfo=UTC),
    )

    technical_error_rate = sum(
        event.outcome is PaymentOutcome.TECHNICAL_ERROR for event in injected
    ) / len(injected)

    assert technical_error_rate > 0.035
