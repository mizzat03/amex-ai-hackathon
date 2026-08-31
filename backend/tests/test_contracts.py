"""Contract-first tests for Stage 1's public and internal schemas."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.contracts.api import (
    ApiError,
    CopilotAnswerContent,
    CopilotMessage,
    CursorPage,
    HumanReviewRequest,
    MetricValue,
    ResetSimulationRequest,
    SubmitCopilotMessageRequest,
    SystemOverviewResponse,
)
from backend.contracts.enums import (
    EvidenceTier,
    IncidentLifecycle,
    PaymentOutcome,
    SimulationAction,
    TelemetryState,
)
from backend.contracts.events import PaymentEvent


def test_closed_contract_enums_match_frozen_values() -> None:
    assert [value.value for value in PaymentOutcome] == [
        "APPROVED",
        "BUSINESS_DECLINE",
        "TECHNICAL_ERROR",
    ]
    assert {value.value for value in TelemetryState} == {
        "WARMING_UP",
        "HEALTHY",
        "STALE",
        "UNKNOWN",
    }
    assert IncidentLifecycle.RECOVERY_CANDIDATE.value == "RECOVERY_CANDIDATE"
    assert EvidenceTier.INSUFFICIENT_EVIDENCE.value == "INSUFFICIENT_EVIDENCE"
    assert SimulationAction.INJECT_DEPLOYMENT_REGRESSION.value == (
        "INJECT_DEPLOYMENT_REGRESSION"
    )


def test_payment_event_rejects_sensitive_fields_and_naive_timestamps() -> None:
    payload = {
        "event_id": str(uuid4()),
        "event_type": "PAYMENT_AUTHORIZATION_COMPLETED",
        "schema_version": "payment-event.v1",
        "occurred_at": "2026-08-27T14:01:00",
        "emitted_at": "2026-08-27T14:01:00Z",
        "payment_id": "pay_01",
        "authorization_attempt_id": "auth_01",
        "attempt_number": 1,
        "amount_minor": 12500,
        "currency": "SGD",
        "merchant_id": "synthetic_merchant_01",
        "merchant_category_code": "5812",
        "merchant_country": "SG",
        "payment_method": "MOBILE_WALLET",
        "channel": "MOBILE_APP",
        "is_tokenized": True,
        "service": "PAYMENT_GATEWAY",
        "service_version": "v2.4.1",
        "environment": "DEMO",
        "processing_region": "SG",
        "outcome": "APPROVED",
        "normalized_code": "APPROVED",
        "authorization_latency_ms": 84,
        "trace_id": "trace_01",
        "pan": "should-never-be-accepted",
    }

    with pytest.raises(ValidationError):
        PaymentEvent.model_validate(payload)


def test_payment_event_enforces_outcome_code_consistency() -> None:
    event = PaymentEvent(
        event_id=uuid4(),
        occurred_at=datetime.now(UTC),
        emitted_at=datetime.now(UTC),
        payment_id="pay_01",
        authorization_attempt_id="auth_01",
        attempt_number=1,
        amount_minor=12500,
        currency="SGD",
        merchant_id="synthetic_merchant_01",
        merchant_category_code="5812",
        merchant_country="SG",
        payment_method="MOBILE_WALLET",
        channel="MOBILE_APP",
        is_tokenized=True,
        service="PAYMENT_GATEWAY",
        service_version="v2.4.1",
        environment="DEMO",
        processing_region="SG",
        outcome="TECHNICAL_ERROR",
        normalized_code="TOKEN_VALIDATION_FAILED",
        authorization_latency_ms=84,
        trace_id="trace_01",
    )
    assert event.schema_version == "payment-event.v1"

    with pytest.raises(ValidationError):
        PaymentEvent.model_validate(
            event.model_dump() | {"outcome": "APPROVED", "normalized_code": "INSUFFICIENT_FUNDS"}
        )


def test_null_metric_requires_unavailable_reason() -> None:
    with pytest.raises(ValidationError):
        MetricValue(value=None, unit="RATE")

    metric = MetricValue(value=None, unit="RATE", unavailable_reason="baseline warming")
    assert metric.value is None


def test_error_envelope_and_cursor_page_are_not_competing_shapes() -> None:
    error = ApiError.model_validate(
        {
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Request validation failed",
                "retryable": False,
                "request_id": "req_01",
            }
        }
    )
    assert error.error.code == "VALIDATION_ERROR"
    assert CursorPage[str](items=["inc_01"], next_cursor="opaque-token").next_cursor


def test_review_and_reset_commands_apply_server_contract_validation() -> None:
    with pytest.raises(ValidationError):
        HumanReviewRequest(
            hypothesis_id="hyp_01",
            status="REJECTED",
            note="   ",
            expected_version=1,
        )

    with pytest.raises(ValidationError):
        ResetSimulationRequest(client_request_id="req_01", confirmation="RESET_ALL")


def test_overview_keeps_telemetry_and_lifecycle_separate() -> None:
    fields = SystemOverviewResponse.model_fields
    assert "telemetry_state" in fields
    assert "detector_summary" in fields


def test_canonical_copilot_contract_is_all_role_strict_and_server_selects_evidence() -> None:
    submitted = SubmitCopilotMessageRequest(
        question="What evidence changed?",
        client_request_id="request-1",
        referenced_message_ids=["msg-prior"],
    )
    assert submitted.referenced_message_ids == ["msg-prior"]
    with pytest.raises(ValidationError):
        SubmitCopilotMessageRequest.model_validate(
            {
                **submitted.model_dump(),
                "evidence_package_id": "client-must-not-select-this",
            }
        )

    answer = CopilotAnswerContent(
        answer_kind="initial_report",
        headline="Deployment-aligned authorization failures",
        direct_answer="The deterministic evidence most strongly supports the deployment.",
        confidence="HIGH",
        supporting_points=[],
        contradictory_points=[],
        unknown_points=[],
        recommended_checks=[],
        citations=[],
        suggested_questions=["What would weaken this explanation?"],
    )
    message = CopilotMessage(
        message_id="msg-answer",
        thread_id="thr-1",
        incident_id="INC-1",
        sequence=1,
        role="ASSISTANT",
        content_type="COPILOT_ANSWER",
        content=answer,
        interaction_id="int-1",
        evidence_package_id="pkg-1",
        evidence_package_version=4,
        created_at=datetime.now(UTC),
    )
    assert message.content.type == "COPILOT_ANSWER"

    with pytest.raises(ValidationError):
        CopilotMessage.model_validate(
            {
                **message.model_dump(mode="json"),
                "role": "USER",
            }
        )
