# Architecture and methodology

The system separates deterministic incident truth from generative investigation assistance.

```text
Synthetic simulator -> Redis Streams -> typed ingestion -> event-time metrics
    -> statistical detector/lifecycle -> dimensional analysis -> deterministic RCA
    -> immutable evidence package -> PostgreSQL projections -> FastAPI REST/WebSocket
    -> approved Next.js frontend
                                      \-> provider-neutral Copilot -> validation -> message/fallback
```

## Runtime boundaries

- The simulator is a separate process from both API and ingestion. It emits only schema-validated
  synthetic payment and operational events through Redis Streams. Event IDs remain deterministic
  for a seed and event clock without repeating across producer ticks, and emitted timestamps never
  exceed the producer clock.
- Reset is a backend-authoritative, idempotent operation restricted to allowlisted synthetic
  PostgreSQL resources and `amex:synthetic:*` Redis keys. It preserves migrations, configuration,
  runbooks, schemas and unrelated Redis keys. A fresh or reset system is genuinely empty and
  `STOPPED`; demo fixtures are never projected into the live runtime.
- Metrics use event-time buckets, non-overlapping current/healthy-baseline windows and explicit
  warming, stale, unknown and late-event states. Business declines never count as technical errors.
- Detection combines statistical significance, practical effect, volume gates and persistence.
  Recovery uses a separately configured stronger persistence rule.
- Dimensional analysis uses deterministic bounded single/pair/triple comparisons. RCA ranks only
  observed operational changes and preserves supporting, contradictory and missing evidence.
- Evidence packages are immutable, versioned and semantically validated before projection.
- PostgreSQL is authoritative for API projections, reviews, feedback, command idempotency,
  Copilot audits, bounded pipeline checkpoints and WebSocket sequence numbers. Redis is the event
  transport and stores the simulator's small restart checkpoint.
- The ingestion worker acknowledges Redis entries only after a projection commit, claims abandoned
  pending entries after a bounded idle time, and restores event-time windows, lifecycle state,
  operational history and processed-event IDs after restart. Duplicate delivery therefore does not
  duplicate incidents or metric history.
- The frontend reconciles compact WebSocket invalidations through authoritative REST reads; a
  reconnect or sequence gap triggers a broader refetch. Transitional simulator states also use a
  bounded polling safety net, while REST remains the only source of displayed live facts.

## Copilot boundary

Python owns context construction, provider calls, read-only tool authorization, validation,
persistence and delivery. The model receives only a bounded package projection, approved runbook
sections, bounded recent history and explicitly labelled tool results. It has no database, Redis,
raw-event, identity-selection or write/remediation access.

Provider output is held in a restricted audit field and never returned directly. Pydantic schema,
incident/package ownership, citations, numerical assertions, deterministic leader/tier and policy
checks must all pass. One repair is allowed; temporary provider calls retry once; then a circuit
breaker and deterministic fallback preserve usability.

## Scaling notes

The MVP intentionally favours inspectability: bounded in-memory latency observations, small
runbook metadata retrieval and JSONB read projections. Production scale would replace latency
lists with mergeable distributions, run consumers as durable workers, add real authentication and
tenant authorization, and establish retention/partitioning policies. Those are explicit follow-on
changes, not claims about the hackathon implementation.
