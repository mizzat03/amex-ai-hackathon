"""Deterministic but varied synthetic authorization-attempt generator."""

import random
from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, uuid5

from backend.contracts.enums import BusinessDeclineCode, Channel, PaymentMethod, PaymentOutcome
from backend.contracts.events import PaymentEvent

_REGIONS = ("SG", "US", "GB", "AU")
_METHODS = (PaymentMethod.CARD, PaymentMethod.MOBILE_WALLET, PaymentMethod.TOKENIZED_CARD)
_CHANNEL_FOR_METHOD = {
    PaymentMethod.CARD: Channel.CARD_PRESENT,
    PaymentMethod.MOBILE_WALLET: Channel.MOBILE_APP,
    PaymentMethod.TOKENIZED_CARD: Channel.WEB,
}
_DECLINES = tuple(BusinessDeclineCode)
_BACKGROUND_ERRORS = ("GATEWAY_TIMEOUT", "NETWORK_ERROR", "ISSUER_TIMEOUT")


class PaymentEventGenerator:
    def __init__(self, seed: int, injected: bool = False) -> None:
        self._seed = seed
        self._random = random.Random(seed)
        self._injected = injected
        self._sequence = 0

    def generate_batch(
        self, count: int, start_at: datetime, *, interval_ms: int = 20
    ) -> list[PaymentEvent]:
        if start_at.tzinfo is None or start_at.utcoffset() is None:
            raise ValueError("start_at must be timezone-aware")
        if interval_ms < 1:
            raise ValueError("interval_ms must be positive")
        return [
            self._generate(start_at + timedelta(milliseconds=index * interval_ms))
            for index in range(count)
        ]

    def _generate(self, occurred_at: datetime) -> PaymentEvent:
        self._sequence += 1
        sequence = self._sequence
        region = self._random.choices(_REGIONS, weights=(25, 40, 20, 15), k=1)[0]
        method = self._random.choices(_METHODS, weights=(50, 30, 20), k=1)[0]
        if self._injected and region == "SG":
            service_version = self._random.choices(("v2.4.1", "v2.4.0"), weights=(70, 30), k=1)[0]
        elif self._injected:
            service_version = self._random.choices(
                ("v2.4.1", "v2.4.0", "v2.3.9"), weights=(20, 50, 30), k=1
            )[0]
        else:
            # A bounded healthy canary population gives the new version a defensible baseline
            # before the scenario's wider SG deployment event.
            service_version = self._random.choices(
                ("v2.4.1", "v2.4.0", "v2.3.9"), weights=(30, 40, 30), k=1
            )[0]
        target = (
            self._injected
            and region == "SG"
            and method is PaymentMethod.MOBILE_WALLET
            and service_version == "v2.4.1"
        )
        draw = self._random.random()
        if target and draw < 0.75:
            outcome = PaymentOutcome.TECHNICAL_ERROR
            code = "TOKEN_VALIDATION_FAILED"
            latency = max(12.0, self._random.gauss(48, 10))
        elif draw < (0.80 if target else 0.05):
            outcome = PaymentOutcome.BUSINESS_DECLINE
            code = self._random.choice(_DECLINES).value
            latency = max(20.0, self._random.gauss(88, 18))
        elif draw < (0.805 if target else 0.055):
            outcome = PaymentOutcome.TECHNICAL_ERROR
            code = self._random.choice(_BACKGROUND_ERRORS)
            latency = max(25.0, self._random.gauss(150, 40))
        else:
            outcome = PaymentOutcome.APPROVED
            code = "APPROVED"
            latency = max(18.0, self._random.gauss(82, 16))

        event_clock = occurred_at.astimezone(UTC).isoformat(timespec="microseconds")
        identity = f"amex-demo:{self._seed}:{event_clock}:{sequence}"
        return PaymentEvent(
            event_id=uuid5(NAMESPACE_URL, f"event:{identity}"),
            occurred_at=occurred_at.astimezone(UTC),
            emitted_at=occurred_at.astimezone(UTC),
            payment_id=f"pay_{uuid5(NAMESPACE_URL, f'payment:{identity}').hex[:20]}",
            authorization_attempt_id=f"auth_{uuid5(NAMESPACE_URL, f'auth:{identity}').hex[:20]}",
            attempt_number=1,
            amount_minor=self._random.randint(250, 75_000),
            currency={"SG": "SGD", "US": "USD", "GB": "GBP", "AU": "AUD"}[region],
            merchant_id=f"synthetic_merchant_{self._random.randint(1, 24):02d}",
            merchant_category_code=self._random.choice(("5411", "5812", "5732", "4111")),
            merchant_country=region,
            payment_method=method,
            channel=_CHANNEL_FOR_METHOD[method],
            is_tokenized=method is not PaymentMethod.CARD,
            service_version=service_version,
            processing_region=region,
            outcome=outcome,
            normalized_code=code,
            authorization_latency_ms=round(latency, 2),
            trace_id=f"trace_{uuid5(NAMESPACE_URL, f'trace:{identity}').hex}",
        )
