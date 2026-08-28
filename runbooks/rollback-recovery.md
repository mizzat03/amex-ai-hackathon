---
runbook_id: rollback-recovery
version: 1.0.0
title: Synthetic Rollback and Recovery Checks
tags: rollback, recovery, payment-gateway
---

## confirm-rollback — Confirm rollback state

Verify the rollback event status, from/to versions and controlled rollout scope. A started or
partial rollback is not successful recovery evidence.

## observe-fresh-recovery — Observe fresh recovery evidence

Wait for the backend recovery rule to pass on newly completed buckets for the configured stronger
persistence period. Improvement alone must remain open when the statistical bounds do not pass.

CAUTION: Never claim a rollback was executed unless a structured operational event records it.
