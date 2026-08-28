"""Synthetic internal event contracts; these never contain cardholder secrets."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from backend.contracts.common import ContractModel
from backend.contracts.enums import (
    BusinessDeclineCode,
    ChangeCategory,
    Channel,
    OperationalEventType,
    OperationalStatus,
    PaymentMethod,
    PaymentOutcome,
    TechnicalErrorCode,
)


class PaymentEvent(ContractModel):
    event_id: UUID
    event_type: Literal["PAYMENT_AUTHORIZATION_COMPLETED"] = "PAYMENT_AUTHORIZATION_COMPLETED"
    schema_version: Literal["payment-event.v1"] = "payment-event.v1"
    occurred_at: datetime
    emitted_at: datetime
    payment_id: str = Field(min_length=1, max_length=80)
    authorization_attempt_id: str = Field(min_length=1, max_length=80)
    attempt_number: int = Field(ge=1, le=10)
    amount_minor: int = Field(ge=0, le=100_000_000)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    merchant_id: str = Field(min_length=1, max_length=80)
    merchant_category_code: str = Field(pattern=r"^\d{4}$")
    merchant_country: str = Field(pattern=r"^[A-Z]{2}$")
    payment_method: PaymentMethod
    channel: Channel
    is_tokenized: bool
    service: Literal["PAYMENT_GATEWAY"] = "PAYMENT_GATEWAY"
    service_version: str = Field(pattern=r"^v\d+\.\d+\.\d+$")
    environment: Literal["DEMO"] = "DEMO"
    processing_region: Literal["SG", "US", "GB", "AU"]
    outcome: PaymentOutcome
    normalized_code: str = Field(min_length=1, max_length=64)
    raw_response_code: str | None = Field(default=None, max_length=32)
    authorization_latency_ms: float = Field(ge=0, le=120_000)
    trace_id: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_outcome_code(self) -> "PaymentEvent":
        if self.outcome is PaymentOutcome.APPROVED and self.normalized_code != "APPROVED":
            raise ValueError("approved outcomes require normalized_code APPROVED")
        if self.outcome is PaymentOutcome.BUSINESS_DECLINE:
            if self.normalized_code not in {code.value for code in BusinessDeclineCode}:
                raise ValueError("business declines require a controlled business-decline code")
        if self.outcome is PaymentOutcome.TECHNICAL_ERROR:
            if self.normalized_code not in {code.value for code in TechnicalErrorCode}:
                raise ValueError("technical errors require a controlled technical-error code")
        return self


class OperationalEvent(ContractModel):
    event_id: UUID
    event_type: OperationalEventType
    schema_version: Literal["operational-event.v1"] = "operational-event.v1"
    occurred_at: datetime
    emitted_at: datetime
    affected_service: Literal["PAYMENT_GATEWAY", "TOKEN_SERVICE", "NETWORK_CONNECTOR"]
    component: str = Field(min_length=1, max_length=80)
    status: OperationalStatus
    change_categories: list[ChangeCategory] = []
    previous_version: str | None = Field(default=None, pattern=r"^v\d+\.\d+\.\d+$")
    new_version: str | None = Field(default=None, pattern=r"^v\d+\.\d+\.\d+$")
    from_version: str | None = Field(default=None, pattern=r"^v\d+\.\d+\.\d+$")
    to_version: str | None = Field(default=None, pattern=r"^v\d+\.\d+\.\d+$")
    affected_regions: list[Literal["SG", "US", "GB", "AU"]] = []
    affected_payment_methods: list[PaymentMethod] = []
    correlation_id: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_versions_for_event_type(self) -> "OperationalEvent":
        if self.event_type is OperationalEventType.DEPLOYMENT:
            if not self.previous_version or not self.new_version:
                raise ValueError("deployments require previous_version and new_version")
        if self.event_type is OperationalEventType.ROLLBACK:
            if not self.from_version or not self.to_version:
                raise ValueError("rollbacks require from_version and to_version")
        return self
