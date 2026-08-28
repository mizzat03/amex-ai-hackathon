"""Structured operational events for the allowlisted deployment scenario."""

from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from backend.contracts.events import OperationalEvent


def deployment_event(at: datetime) -> OperationalEvent:
    at = at.astimezone(UTC)
    return OperationalEvent(
        event_id=uuid5(NAMESPACE_URL, f"amex-demo:deployment:{at.isoformat()}"),
        event_type="DEPLOYMENT",
        occurred_at=at,
        emitted_at=at,
        affected_service="PAYMENT_GATEWAY",
        component="authorization-api",
        status="SUCCEEDED",
        change_categories=["TOKEN_VALIDATION", "RELEASE"],
        previous_version="v2.4.0",
        new_version="v2.4.1",
        affected_regions=["SG"],
        affected_payment_methods=["MOBILE_WALLET"],
        correlation_id=f"deploy_{at.strftime('%Y%m%d%H%M%S')}",
    )


def rollback_event(at: datetime) -> OperationalEvent:
    at = at.astimezone(UTC)
    return OperationalEvent(
        event_id=uuid5(NAMESPACE_URL, f"amex-demo:rollback:{at.isoformat()}"),
        event_type="ROLLBACK",
        occurred_at=at,
        emitted_at=at,
        affected_service="PAYMENT_GATEWAY",
        component="authorization-api",
        status="SUCCEEDED",
        change_categories=["TOKEN_VALIDATION", "RELEASE"],
        from_version="v2.4.1",
        to_version="v2.4.0",
        affected_regions=["SG"],
        affected_payment_methods=["MOBILE_WALLET"],
        correlation_id=f"rollback_{at.strftime('%Y%m%d%H%M%S')}",
    )
