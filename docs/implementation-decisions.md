# Implementation decisions

These choices fill implementation-owned gaps. They do not replace or reinterpret the locked
product decisions in the five authoritative planning documents.

## ID-001 — Supplied document locations

The six supplied prompt/planning files are ignored root-level inputs whose titles match the
authoritative set, but their paths omit `docs/` and the copy-number suffixes shown in prose. They
were read in full from the repository root. New implementation documentation is stored under
`docs/` as required.

## ID-002 — Demo configuration v1

All window, baseline, volume, lateness, persistence, recovery, dimensional-analysis, RCA and
retention defaults live in `backend/config/settings.py`, are overridable through `AMEX_*`
environment variables, and carry `configuration_version=demo-config.v1`. These are conservative,
fast-running demo values and are not represented as universal production thresholds.

## ID-003 — Controlled synthetic taxonomy v1

- Regions: `SG`, `US`, `GB`, `AU`.
- Payment methods: `CARD`, `MOBILE_WALLET`, `TOKENIZED_CARD`.
- Channels: `MOBILE_APP`, `WEB`, `CARD_PRESENT`.
- Business declines: `INSUFFICIENT_FUNDS`, `EXPIRED_CREDENTIAL`, `DO_NOT_HONOR`.
- Technical errors: `TOKEN_VALIDATION_FAILED`, `GATEWAY_TIMEOUT`, `ISSUER_TIMEOUT`,
  `NETWORK_ERROR`, `RATE_LIMITED`, `INTERNAL_ERROR`.
- Services: `PAYMENT_GATEWAY`, `TOKEN_SERVICE`, `NETWORK_CONNECTOR`.

The payment schema forbids extra fields, validates UTC timestamps, and contains no PAN, CVV/CVC,
PIN, cardholder identity, or real merchant/customer data.

## ID-004 — Dependency policy

Direct dependencies are exactly pinned using the safe-version N-2 policy against registry release
history. Compatibility won over major-version novelty: TypeScript `5.8.2` is used because the
selected OpenAPI generator declares TypeScript `^5.x`; forcing TypeScript 6 would create an invalid
peer tree. npm reported zero vulnerabilities after Stage 1 installation. Transitive dependencies
are captured by `frontend/package-lock.json`.

## ID-005 — Frontend contract boundary

Pydantic models and exported OpenAPI are the sole API definitions. The generated TypeScript file is
checked in for a clean-checkout build. Frontend `types/` contains convenience aliases only, and both
fixture and future live adapters implement `InvestigatorRepository`.

## ID-006 — Security defaults

The API uses an origin allowlist, no credentialed cross-origin requests, a narrow method/header
allowlist, strict Pydantic `extra=forbid` input validation, a typed safe error envelope, and baseline
security headers. Model credentials are optional environment values and are absent from source.

## ID-007 — Redis transport and reset namespace

Payment and operational events use separate Redis Streams under `amex:synthetic:*`. A consumer
group validates each payload into its Pydantic contract and deduplicates by stable event ID before
dispatch. Reset scans and deletes only that explicit synthetic namespace—never `FLUSHDB`, an
unbounded wildcard, or unrelated keys.

The Redis server image is pinned to `redis:7.4.9-alpine`, a patched maintenance release. Security
patch status takes priority over mechanically stepping back to a known-vulnerable server patch.

## ID-008 — Metrics demo defaults and late events

Metrics use 10-second event-time buckets, a 60-second rolling current window and a preceding,
non-overlapping 300-second healthy baseline. Events up to 15 seconds behind the observed event-time
maximum are accepted into their original bucket and labelled late; older events are rejected from
authoritative aggregates and counted for audit. Window P95 is calculated from merged observations,
never averaged from bucket percentiles. These in-memory observations suit the bounded MVP; a
mergeable production distribution is a documented scaling option.

## ID-009 — Detector and lifecycle defaults

The primary detector uses a one-sided pooled two-proportion z-test at `alpha=0.01`, together with
minimum current/baseline volumes, at least eight current technical errors, and a two-percentage-
point practical increase. Detection requires two fresh completed buckets. Recovery uses a separate
one-sided 95% bound against the frozen pre-incident baseline, a 0.5-percentage-point residual
margin, a 2% absolute safety ceiling, and four fresh buckets—twice the default detection
persistence. Latency is an independent global rule requiring both 50 ms absolute and 50% relative
P95 increase.

## ID-010 — Scope drill-down and healthy canary traffic

The synthetic healthy mix includes a bounded `v2.4.1` canary population so the new version and its
controlled combinations have a defensible healthy baseline before the wider Singapore deployment.
The injected scenario increases `v2.4.1` share in SG and applies the fault only to
`SG + MOBILE_WALLET + v2.4.1`. Combination refinement requires an eligible child to retain at least
50% of its parent's excess errors and improve technical-failure concentration by at least 5%.

## ID-011 — RCA rule mapping v1

The service map is `PAYMENT_GATEWAY -> TOKEN_SERVICE, NETWORK_CONNECTOR`. The broad controlled
`TOKEN_VALIDATION_FAILED` mapping covers Payment Gateway or Token Service changes tagged
`TOKEN_VALIDATION`, `TOKEN_CONFIGURATION`, or `TOKEN_KEY_MANAGEMENT`; it does not encode a specific
deployment ID or expected demo answer. Timing, service relevance, version alignment, scope
alignment, error relevance, counterfactual concentration and later rollback/recovery remain
separate evidence facts. No weighted score or probability is produced.

## ID-012 — Evidence identity and runbook retrieval

One stable evidence-package ID is derived per incident/schema, while every material upstream input
change creates a new immutable integer package version. Version-specific evidence IDs derive from
package ID, package version and stable logical key. Runbook retrieval uses deterministic tag
intersection over three small approved Markdown documents; semantic/vector retrieval is omitted
because the bounded corpus does not justify it. Runbook citations always carry document version
and section ID and are labelled as guidance rather than incident proof.

## ID-013 — Stage 8 visual concepts and fixture isolation

Superseded for product routing and composition by ID-018 after the mandatory user checkpoint.

The two review concepts share one component tree, one generated-contract fixture catalogue and one
fixture repository. Variant A (`Command Deck`) uses a persistent left rail and framed operational
panels. Variant B (`Analyst Ledger`) uses a compact top rail, editorial rules and a denser two-column
fact rhythm. This creates a real composition choice without allowing copy, data or behavior drift.
The default product routes temporarily render Variant A, but no consolidation is authoritative
until the mandatory visual-selection checkpoint is approved.

All Stage 8 commands remain local fixture operations. REST and WebSocket adapters are intentionally
not connected until Stage 9, after selection. Required rare states have a dedicated render gallery
in addition to interactive Copilot and review states in the product UI.

## ID-014 — Stage 8 package compatibility

The application stack uses exact conservative pins for Next.js 16.3.1, React 19.2.6, Recharts
3.9.2, Tailwind CSS 4.3.1 and Radix UI 1.6.5. npm 10.9.2 failed while building the newly published
Vitest 4 peer graph with an Arborist `edgesOut` null error. The test stack therefore uses the
established compatible Vitest 3.2.4, Vite React plugin 4.3.4 and JSDOM 26.1.0 line. This is a
tooling compatibility choice; it does not change runtime behavior. The regenerated lockfile holds
the complete transitive graph.

## ID-015 — Local persistence and live reconciliation

Stage 9 uses the pinned local Compose PostgreSQL/Redis services. PostgreSQL owns typed JSONB read
projections, reviews, feedback, Copilot audits, idempotent command results and monotonic WebSocket
sequence numbers. Synchronous psycopg calls run in worker threads because psycopg's async transport
is incompatible with the Windows Proactor loop used by this workstation. All SQL values remain
parameterized. The frontend keeps fixture and HTTP implementations behind one repository contract;
WebSocket messages are compact invalidations and REST remains authoritative.

## ID-016 — Copilot implementation limits

The provider-neutral configuration is `copilot-config.v1` with balanced reasoning, 1,800 initial
and 1,100 follow-up output-token ceilings, a 60,000-character context ceiling, 15-second call
timeout, one temporary retry, one structured repair, four read-only tool calls and a three-failure/
60-second circuit breaker. These are bounded local MVP defaults pending live evaluation, not
provider performance claims. Automatic reports cache by incident/package/configuration version;
follow-ups do not. Runtime defaults to a disabled provider and never routes between providers.

## ID-017 — Container and WebSocket runtime

The Docker observation in this historical decision is superseded by ID-019.

The API pins `websockets==17.0` because the base Uvicorn installation does not include a protocol
implementation. The full Compose file builds frontend/API images and waits on PostgreSQL/Redis/API
health. The Compose definition validated, but Docker Desktop's Linux engine returned an internal
500 during the final image build on this workstation. The equivalent host API plus the same local
PostgreSQL/Redis services passed the real REST/WebSocket and complete browser demo gates.

## ID-018 — Approved Stage 8 consolidation

The user approved Variant B for Overview and Variant A for the incident investigation workspace,
with no further visual feedback. Product routes now use one semantic token system and the approved
hierarchy. Copilot is a non-modal resizable split pane with session-scoped width persistence,
keyboard resizing and a full-width laptop presentation. Temporary variant-review routes and
switches are removed; `/fixture-states` is retained only as an isolated regression harness.

## ID-019 — Verified six-service local runtime and restart continuity

The final Compose topology is PostgreSQL, Redis, simulator, ingestion, API and frontend. A full
isolated `docker compose up --build -d` completed and all six health checks passed. Simulator state
is checkpointed in Redis; event-time aggregation, incident lifecycle, operational history and
processed-event IDs are checkpointed in PostgreSQL. The ingestion consumer acknowledges only after
projection and claims abandoned pending entries. These decisions allow simulator/worker restarts
without erasing a run or duplicating already projected events.

## ID-020 — Empty live state and explicit fixture mode

Startup and reset do not seed a demo incident. Live repositories are the product default and never
fall back silently to fixture facts. Fixture data is available only when
`NEXT_PUBLIC_AMEX_DATA_MODE=fixture` is explicitly set by the component, screenshot and state-gallery
verification harnesses. The reset allowlists preserve schemas, configuration and runbooks.

## ID-021 — Producer clock, scenario calibration and unknown RCA scope

Continuous batches are distributed over the producer tick and end at or before the producer clock.
Their deterministic identities include the event clock so new producer instances cannot repeat a
prior tick's IDs. Baseline seed headroom absorbs normal ingestion delay. The controlled regression
remains exclusive to `SG + MOBILE_WALLET + v2.4.1`, with a deterministic error rate calibrated to
clear the configured global detection floor. If dimensional gates do not establish an affected
scope, RCA treats scope alignment as unknown rather than inventing a hard contradiction; observed
error-relevance evidence can still produce a qualified moderate leader.

## ID-022 — Review projection separation and dependency warning

Human review updates write an `IncidentSummary` back to the list projection and an
`IncidentDetail` to the workspace projection; those shapes are not interchangeable. Successful
review navigation preserves incident-list query state and highlights the updated row, while failed
saves preserve form input. The final locked frontend build passed, while npm reported three known
transitive audit findings (one moderate, one high and one critical). No unreviewed automatic audit
fix was applied because it could change the approved dependency graph.
