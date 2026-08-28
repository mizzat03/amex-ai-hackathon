---
runbook_id: token-validation
version: 1.0.0
title: Synthetic Token Validation Investigation
tags: token-validation, payment-gateway, mobile-wallet
---

## inspect-token-path — Inspect the token-validation path

Verify the failing flow's normalized error signature, region, payment method, service version and
time period against the incident evidence package. Compare affected-version traffic with its
current complement before treating version alignment as explanatory.

CAUTION: This procedure is guidance, not proof that a deployment caused the incident.

## compare-token-config — Compare controlled token configuration

Ask the service owner to compare approved, non-secret token-validation configuration metadata
between the affected version and the last healthy version. Do not paste keys, tokens, PAN, or raw
customer payloads into the investigation.

CAUTION: Configuration changes require human approval and are never executed by this product.
