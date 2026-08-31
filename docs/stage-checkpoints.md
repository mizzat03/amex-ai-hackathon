# Stage checkpoints

## Stage 1 — Repository scaffold and contracts: COMPLETE

Implemented:

- Modular backend, simulator, frontend, runbook, test, script, and documentation scaffold.
- Central versioned environment configuration and controlled synthetic taxonomies.
- Strict internal payment and operational event schemas with UTC and outcome/code validation.
- Frozen frontend-facing Pydantic contracts and all `/api/v1` OpenAPI route definitions.
- Versioned OpenAPI export, generated TypeScript types, and a shared repository interface.
- Safe `.env.example`, secret/runtime ignores, typed error envelope, CORS allowlist, and security
  headers.

Verified:

- `.venv\\Scripts\\python.exe -m pytest` — 9 passed.
- `.venv\\Scripts\\python.exe -m compileall -q backend simulator` — passed.
- `python scripts/export_openapi.py` — OpenAPI written successfully.
- `npm run contracts:generate` — generated `frontend/generated/api-types.ts`.
- `npm run typecheck` — passed with strict TypeScript settings.
- `npm install` — 34 packages audited, zero reported vulnerabilities.

Configuration or limitations:

- The original PowerShell wrapper was replaced with cross-platform `scripts/generate_contracts.py`
  because the host disables unsigned PowerShell scripts.
- There is no Git identity and the repository has no commits, so a safe focused stage commit cannot
  be created. This documented checkpoint is the source-of-truth handoff.

Checkpoint:

- Documented checkpoint; no commit hash available.

Next:

- Stage 2 — Simulator and Redis ingestion.

## Stage 2 — Simulator and Redis ingestion: COMPLETE

Implemented:

- Separate deterministic Python simulator producer with healthy, injected-regression, recovery,
  stop, and confirmed-reset commands.
- Backend-authoritative state machine, progressive `available_actions`, allowlisted scenario, and
  idempotent command results.
- Distinct approved, business-decline, and technical-error outcomes; only
  `SG + MOBILE_WALLET + v2.4.1` receives the injected `TOKEN_VALIDATION_FAILED` regression.
- Separate structured deployment and rollback operational events.
- Redis Streams publisher, consumer groups, Pydantic revalidation, persisted event-ID
  deduplication, and callback dispatch.
- Accelerated healthy pre-warm events published through the same Redis stream consumed by the
  backend.
- Synthetic-only reset constrained to `amex:synthetic:*`.

Verified:

- `docker compose up -d redis` — pinned Redis 7.4.9 container healthy.
- `python -m pytest backend/tests/test_simulator.py backend/tests/test_redis_ingestion.py` — 6 passed.
- Real Redis integration covered payment/operational stream separation, consumer groups,
  deduplication, pre-warm, injection, recovery, stop, and synthetic reset.

Configuration or limitations:

- Stage 2 runs traffic in deterministic batches for fast tests. A continuous live cadence remains
  an orchestration concern for the later API/integration stage.
- The Docker engine had to be started on this workstation; no repository change was required.

Checkpoint:

- Documented checkpoint; no commit hash available because Git identity is not configured.

Next:

- Stage 3 — Metrics aggregation.

## Stage 3 — Metrics aggregation: COMPLETE

Implemented:

- Configurable fixed-duration event-time buckets with explicit allowed-lateness dispositions.
- Non-overlapping rolling current and healthy-baseline windows.
- Overall, controlled single-dimension and observed region/method/version-combination rollups.
- Separate approval, business-decline and technical-error counts/rates; technical errors by code;
  throughput; mean latency; and merged-observation P95 latency.
- Explicit `WARMING_UP`, `STALE`, `UNKNOWN`, and `HEALTHY` telemetry decisions.
- Versioned snapshots and bounded metric-history series at authoritative bucket resolution.

Verified:

- `python -m pytest backend/tests/test_metrics.py` — 7 passed.
- Tests cover count conservation, outcome separation, event-time assignment, accepted/dropped late
  events, merged P95, normal-path pre-warm readiness, missing telemetry, observed combinations,
  snapshot versioning, and history resolution.

Configuration or limitations:

- MVP buckets retain bounded latency observations so exact merged-window percentiles are easy to
  audit. A production deployment should use a mergeable distribution when volume requires it.

Checkpoint:

- Documented checkpoint; no commit hash available because Git identity is not configured.

Next:

- Stage 4 — Anomaly detection and incident lifecycle.

## Stage 4 — Anomaly detection and incident lifecycle: COMPLETE

Implemented:

- One-sided two-proportion technical-error detector with volume, error-count, significance and
  practical-effect safeguards.
- Separate global P95 latency degradation rule with no misuse of the proportion test.
- Auditable evaluation records containing counts, rates, configuration, decision and reason.
- Thread-safe lifecycle state machine covering `WARMING_UP`, `HEALTHY`, `SUSPECTED`, `OPEN`,
  `RECOVERY_CANDIDATE`, and `RESOLVED`.
- Fresh-bucket-only persistence, frozen pre-incident baseline inputs, practical-impact severity,
  stable fingerprints, parent signal attachment, idempotent creation, cooldown and manual closure.
- Statistical recovery bounds and longer recovery persistence.

Verified:

- `python -m pytest backend/tests/test_anomaly_lifecycle.py` — 7 passed.
- Tests cover healthy false-positive resistance, suspected/open persistence, unchanged-evidence
  suppression, improvement without resolution, stronger recovery, telemetry non-decisions,
  concurrent idempotency, secondary latency and manual closure reasons.

Configuration or limitations:

- Evaluation and incident repositories are in-memory through the deterministic stages; Stage 9
  connects the same domain services to PostgreSQL persistence.

Checkpoint:

- Documented checkpoint; no commit hash available because Git identity is not configured.

Next:

- Stage 5 — Dimensional analysis.

## Stage 5 — Dimensional analysis: COMPLETE

Implemented:

- Deterministic single-dimension ranking followed by bounded seeded pairs and triples.
- Per-segment current/baseline counts and rates, expected/excess errors, excess share, traffic share,
  absolute increase, safe lift/new-pattern presentation and eligibility reasons.
- Simplicity-preserving child refinement using excess retention and concentration improvement.
- Current candidate-versus-complement comparisons and explicit concentration wording.
- Separate dominant normalized technical-error signature analysis.
- Complete, incomplete and insufficient-data results with retained rejected-candidate audit records.

Verified:

- `python -m pytest backend/tests/test_dimensional_analysis.py` — 4 passed.
- Primary scenario identifies `SG + MOBILE_WALLET + v2.4.1` as affected scope and
  `TOKEN_VALIDATION_FAILED` as a symptom, with no causal wording.
- Tests cover complement comparison, low-volume misleading correlation and unavailable
  combination caveats.

Configuration or limitations:

- The shortlist is deliberately bounded by the configured top-N seed count; evaluated and rejected
  candidates remain available in the result for audit.

Checkpoint:

- Documented checkpoint; no commit hash available because Git identity is not configured.

Next:

- Stage 6 — Deterministic RCA.

## Stage 6 — Deterministic RCA: COMPLETE

Implemented:

- Candidate generation from received deployment, configuration-change and eligible rollback events
  within the configured lookback and dependency map.
- Separate timing, service, version, scope, error-relevance, counterfactual and recovery evidence.
- Explicit supporting, contradictory, missing and not-applicable collections with raw values.
- Hard temporal/scope/service contradictions, qualitative evidence tiers, bounded deterministic
  ranking, observed alternatives and explicit `INSUFFICIENT_EVIDENCE`.
- Idempotent reruns keyed to analysis/event/configuration input versions; material rollback/recovery
  creates a new result version.
- Human review stored separately with fixed `demo-operator`, required notes and optimistic version
  conflicts.

Verified:

- `python -m pytest backend/tests/test_root_cause.py` — 5 passed.
- Primary observed `v2.4.1` deployment becomes the qualified leader while the Token Service
  alternative remains visible; no numeric confidence/probability exists.
- Tests cover insufficient evidence, hard contradictions, idempotent/material reruns and review
  validation/version conflict.

Configuration or limitations:

- Operational event and RCA repositories remain in-memory until the Stage 9 persistence adapter;
  result identities and version rules are already stable.

Checkpoint:

- Documented checkpoint; no commit hash available because Git identity is not configured.

Next:

- Stage 7 — Evidence builder and runbooks.

## Stage 7 — Evidence builder and runbooks: COMPLETE

Implemented:

- Canonical frozen Pydantic evidence packages with stable incident/package/evidence/hypothesis
  identities, immutable versions and idempotent upstream-version keys.
- Typed observed, derived, missing and limitation items with structured values, UTC periods,
  controlled scope, provenance, source versions and calculation lineage.
- Unchanged deterministic RCA hypotheses with separate supporting, contradictory, missing and
  not-applicable evidence references.
- Shared dashboard and minimised copilot projections, explicit citation allowlists, and safe
  deterministic fallback metadata.
- `COMPLETE`, `PARTIAL` and `INVALID` semantic validation behavior; invalid packages are blocked
  from authoritative dashboard/copilot projection.
- Three versioned synthetic runbooks with deterministic metadata retrieval and exact section
  resolution as procedural guidance.
- Parameterized PostgreSQL repository boundary and JSONB migration with unique/indexed package
  metadata and GIN payload index.
- Exported evidence-package JSON Schema.

Verified:

- `python -m pytest backend/tests/test_evidence_builder.py` — 6 passed.
- Tests cover citation resolution, hypothesis-reference integrity, idempotency, immutability,
  versioning, partial limitations, invalid blocking/fallback, provenance, runbook guidance and
  PostgreSQL JSONB/index requirements.

Configuration or limitations:

- The PostgreSQL adapter/migration is implemented, while live database orchestration is connected
  in Stage 9 after the required fixture-first frontend checkpoint.

Checkpoint:

- Documented checkpoint; no commit hash available because Git identity is not configured.

Next:

- Stage 8 — Frontend with typed fixtures and mandatory visual-selection checkpoint.

## Stage 8 — Frontend visual-selection checkpoint: COMPLETE

Implemented:

- Next.js App Router, strict TypeScript, Tailwind CSS semantic themes, Recharts, a local shadcn-style
  Radix component foundation, generated OpenAPI types and a fixture repository boundary.
- Approved consolidation of Variant B `Analyst Ledger` for Overview and Variant A `Command Deck`
  for the Incident Workspace, using one shared token and component system.
- Overview hierarchy with permanent technical-error punchline and excess-error count, tabbed large
  comparison chart, active-incident callout and available-action-driven demo controls.
- Filterable/sortable incident archive and evidence-first incident workspace with lifecycle, scope,
  error signature, deterministic RCA, aligned signal/event timeline, separate evidence groups,
  human review, non-modal resizable Copilot split pane, citation lineage and feedback.
- Required fixture-state gallery, light/dark tokens, reduced-motion handling, keyboard-safe overlays,
  visible focus, chart text summary and accessible data table.
- Temporary `/review/variant-*` routes and runtime variant props removed; `/fixture-states` remains
  isolated as the required regression harness.
- Updated component inventory in `docs/component-manifest.md` and four approved, visually inspected
  desktop/laptop light/dark screenshots under `docs/screenshots/`.

Verified:

- `npm run typecheck` — passed.
- `npm run lint` — passed with zero warnings or errors.
- `npm test -- --run` — 15 passed across 5 component test files after consolidation and live-state
  regression coverage.
- `npm run build` — passed; only the five intended application, harness and not-found routes were
  generated, with no `/review/*` route.
- `npm run test:browser` — 4 passed in Chromium with an explicit process exit code of 0, covering
  approved desktop/laptop screenshots, light/dark themes, keyboard dialog/Copilot controls, fixture
  states, horizontal overflow and automated axe checks across all approved pages in both themes.
- Four approved screenshots were visually inspected after deterministic Recharts rendering.

Configuration or limitations:

- Product routes now default to REST/WebSocket. Fixture mode is explicit and isolated to component,
  screenshot and required-state verification; live failures never render fixture facts.
- The Windows browser verifier uses a bounded hidden-server wrapper because Playwright 1.61 does not
  support graceful WebServer shutdown signals on Windows.

Checkpoint:

- User approved Variant B Overview and Variant A Incident Workspace with no additional visual
  feedback. Consolidation and every mandatory Stage 8 gate completed before Stage 9 began.
- No commit hash is available because Git identity is not configured.

Next:

- Stage 9 — Backend integration and live frontend data.

## Stage 9 — REST, WebSocket and persistence integration: COMPLETE

Implemented:

- PostgreSQL 17.9 and Redis 7.4 local Compose services, separate simulator and ingestion processes,
  idempotent migrations, parameterized psycopg access and dedicated review/feedback/Copilot/
  command/WebSocket audit tables. Startup and reset leave a genuinely empty `STOPPED` projection.
- Every frozen REST command/resource, safe non-2xx envelope, cursor checks, optimistic review
  conflict, server-side `demo-operator`, simulator idempotency and compact sequenced WebSocket
  invalidation.
- Shared fixture/HTTP repositories and live WebSocket reconciliation. Unknown events, reconnects
  and sequence gaps refetch authoritative REST state without component/layout changes.
- Live Overview, incident archive and investigation workspace data/actions, including evidence,
  citations, Copilot query/feedback and human review.
- Bounded PostgreSQL/Redis pipeline and simulator checkpoints, post-projection acknowledgement,
  abandoned-pending-entry claiming and duplicate-event suppression across process restarts.

Verified:

- `docker compose up -d postgres redis` — both services healthy during Stage 9 integration.
- `AMEX_RUN_POSTGRES_TESTS=1 python -m pytest` — PostgreSQL integration included in the passing
  suite.
- OpenAPI export, TypeScript regeneration and strict TypeScript — passed.
- Live production frontend against simulator/ingestion/FastAPI/PostgreSQL/Redis — the complete
  judge-path browser check passed in 29.3 seconds.
- REST API integration, persisted WebSocket sequence and frontend adapter/sequence-gap tests —
  passed.

Configuration or limitations:

- Fixture mode remains the deterministic component/design-state default; `.env.example` selects
  live mode for local product runs.
- The base Uvicorn install initially rejected WebSocket upgrades; pinned `websockets==17.0` fixed
  the runtime path and a real WebSocket sequence test subsequently passed.

Checkpoint:

- Documented checkpoint; no commit hash is available because Git identity is not configured.

Next:

- Stage 10 — AI investigation Copilot.

## Stage 10 — AI investigation Copilot: COMPLETE

Implemented:

- One provider-neutral contract with disabled, fake, Anthropic Messages and OpenAI Responses
  adapters; one selected runtime provider/model and no multi-provider routing.
- Incident/package-pinned initial and follow-up contexts, version-aware automatic-report cache,
  bounded recent history, versioned prompts/configuration and controlled progress events with no
  generated prose.
- Allowlisted incident-scoped read-only tools, native tool-call boundary, duplicate/write/cross-
  incident/result-size guards and persisted citable tool evidence.
- Strict response schema and deterministic incident/package, citation, numerical, leader/tier,
  alternative, recommendation, human-control and prohibited-execution validation.
- One structured repair, one temporary retry, timeout, circuit breaker, deterministic fallback,
  separate raw/validated audit persistence, structured feedback and graceful task draining.
- Fourteen labelled evaluation/regression scenarios and blinded Claude Sonnet 5 versus GPT-5.6
  Terra artifact runner with locked hard gates/rubric.

Verified:

- `python -m pytest backend/tests/test_copilot.py` — 10 passed.
- Full backend suite with real PostgreSQL and Redis gates — 77 passed.
- Tests cover schema, repair, fabricated numbers, citation rejection, prompt injection, incident
  isolation, read-only tool authorization/rounds, timeout/retry/fallback, caching and persistence.
- Mock-transport tests verify both live provider adapters' structured-output, balanced-reasoning,
  native-tool and usage-metadata request/response boundaries without credentials.
- Post-checkpoint runtime correction: OpenAI incomplete terminal states are no longer presented as
  schema failures. `copilot-config.v2` reserves a larger reasoning-plus-JSON budget, permits one
  bounded token-limit retry, records truthful audit metadata and exposes a retryable
  `provider_incomplete` fallback if the provider remains incomplete.
- Post-correction verification: 18 focused Copilot tests and the full 79-test backend suite passed
  (four environment-gated integration tests skipped); frontend component tests passed 18/18, and
  TypeScript, ESLint, production build and all six Compose health checks passed.
- Missing credential/model-variable check — all four absent; evaluation runner recorded
  `PENDING_CREDENTIALS`, made no provider calls and selected no winner.

Configuration or limitations:

- Real Claude Sonnet 5 versus GPT-5.6 Terra quality evaluation remains pending credentials and
  provider-resolved model IDs. Exact variable names and command are in `docs/model-evaluation.md`.
- Fake-provider and structural safety results are not represented as model-quality evidence.

Checkpoint:

- Documented checkpoint; no commit hash is available because Git identity is not configured.

Next:

- Stage 11 — End-to-end verification and demo polish.

## Stage 11 — End-to-end verification and demo polish: COMPLETE

Implemented:

- Full frontend/API/simulator/ingestion/PostgreSQL/Redis Compose topology, Dockerfiles, health
  dependencies, idempotent migrations, empty live startup and credential-safe provider injection.
- Reproducible setup/demo guide, host-development alternative and automated live-stack verifier.
- Judge-path browser automation covering reset, healthy prewarm, injection, investigation,
  deterministic AI fallback, persisted review and recovery.
- Architecture/methodology, responsible-AI, business-value, source-traceability, model-evaluation
  and bounded local performance/cost-observation documentation.

Verified:

- `python scripts/verify_live_stack.py` — passed over real REST and WebSocket transports using local
  PostgreSQL/Redis; recorded monotonic sequences and bounded request observations.
- `docker compose --env-file .env.example -p amex-codex-verify up --build -d` — all six images built
  and all six service health checks passed.
- Approved fixture Chromium visual/interaction/axe suite — 4 passed and the live-only test skipped;
  live Chromium judge path — 1 passed and the four fixture-only checks skipped (29.3 seconds).
- Full backend suite with real PostgreSQL and Redis integration gates — 77 passed.
- Frontend TypeScript and lint — passed with zero errors or warnings; component tests — 15 passed;
  production build — passed with only the five intended routes.
- OpenAPI export/TypeScript regeneration and Python compile validation — passed.
- Post-checkpoint cold-start correction: Redis readiness now requires an exact `PONG`, simulator
  initialization has bounded transient-error backoff, 82 backend tests passed (four gated skips),
  and a real rebuild preserved the existing 504 MB Redis volume while all six services became
  healthy after its 26.9-second restore.

Configuration or limitations:

- The locked frontend build reports three known transitive npm audit findings (one moderate, one
  high and one critical). No automatic dependency rewrite was applied; this is a documented
  follow-up rather than a claim of a clean dependency audit.
- Live model comparison remains explicitly pending as permitted by the master procedure; there is
  no fabricated winner, latency or cost claim.

Checkpoint:

- Stages 9–11 are documented complete. No commit hash is available because the repository has no
  commits and Git identity is not configured.

Next:

- Supply live evaluation credentials/model IDs through a secret manager, run the locked blinded
  evaluation, record the reviewed winner, then configure that one provider/model for both modes.

## Post-Stage-10 canonical Copilot thread and tab workspace: COMPLETE (2026-08-29)

Implemented:

- One incident-owned canonical Copilot thread with ordered durable user, assistant, system and
  fallback messages, cursor pagination, incident-scoped idempotency and compatibility adapters.
- Immutable evidence-package pinning, historical citation hydration, bounded untrusted history,
  one evidence-version notice per transition and lifecycle-aware package selection.
- Provider-neutral structured answer validation, persisted deterministic fallback and an atomic
  retry response slot that replaces fallback without duplicating transcript entries.
- The approved incident workspace now uses Summary, Timeline, Evidence, Copilot and Review tabs;
  the old drawer, resize and conversation-reset presentation is absent. Temporary screenshot-state
  wiring is isolated under the fixture-state review route.
- PostgreSQL reset now skips repeat schema migration, truncates only the fixed synthetic-table
  allowlist, preserves mixed-resource configuration records and evaluates prewarm backlog using
  event time so repeated local demo runs do not stall.

Verified:

- Generated OpenAPI, evidence schema and TypeScript contracts completed successfully.
- Full backend suite: 102 passed and four environment-gated tests skipped; the PostgreSQL-enabled
  runtime-store round trip/reset gate passed separately.
- The exact v41 to v42 fake-provider journey passed: refresh persistence, one transition notice,
  v41 historical citation retention, controlled fallback and successful v42 retry without duplicate
  messages.
- Frontend TypeScript, ESLint and all 20 component tests passed. The production browser gate rebuilt
  the application and reported five passed checks with one live-only browser test skipped; axe found
  no violations in the approved fixture pages and Copilot tab.
- Both updated incident baselines and all six named Copilot screenshots were regenerated and
  visually inspected at the approved desktop/light and laptop/dark targets. Overview baselines were
  not rewritten.
- `scripts/verify_live_stack.py` passed over real local REST/WebSocket transports after reset,
  prewarm, injection, investigation, validated-or-fallback Copilot handling, review and recovery.
- Final Compose check reported PostgreSQL, Redis, simulator, ingestion, API and frontend healthy.

Configuration or limitations:

- The blinded Claude Sonnet 5 versus GPT-5.6 Terra comparison remains `PENDING_CREDENTIALS`; no
  model-quality winner is claimed. A validated runtime response observed by the provider-neutral live
  verifier is not a substitute for the locked repeated comparison and human rubric review.

Checkpoint:

- The canonical-thread brownfield plan is implemented and verified without creating a commit or
  inspecting secret-bearing environment files.
