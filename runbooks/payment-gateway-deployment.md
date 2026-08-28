---
runbook_id: payment-gateway-deployment
version: 1.0.0
title: Synthetic Payment Gateway Deployment Checks
tags: payment-gateway, deployment, regional-degradation
---

## verify-rollout-scope — Verify deployment rollout scope

Confirm the structured deployment version, region and payment-method scope against the affected
traffic. Look for healthy traffic on the same version and unhealthy traffic on other versions as
counter-evidence.

CAUTION: Temporal alignment alone does not establish causality.

## inspect-release-diff — Inspect the approved release diff

Have the Payment Gateway owner review token-validation and configuration changes between the prior
and deployed version. Record the result as a human note; do not rewrite deterministic RCA evidence.
