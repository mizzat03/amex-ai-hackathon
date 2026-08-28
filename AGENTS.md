# Repository Agent Guide

This file applies to the entire repository. A more deeply nested `AGENTS.md` may add
directory-specific instructions; it must not weaken the safety, privacy, data, or verification
requirements in this file.

## Project intent

This repository is a synthetic-data payment incident investigation MVP. Preserve these product
boundaries in every change:

- Keep technical payment failures distinct from legitimate business declines.
- Base findings, rankings, and copilot output on traceable evidence from the system.
- Label deterministic fallback output clearly; never present it as model-generated analysis.
- Use only synthetic data. Do not introduce real cardholder, merchant, customer, or production
  operational data.
- Keep the fixed server-side `demo-operator` principal. Do not add browser-selected identity or
  imply that the MVP provides production authentication.

Before changing a documented product decision, contract, or stage outcome, consult the relevant
files in `docs/` and the repository planning documents. Record intentional deviations in the
appropriate documentation.

## Secret-handling rules

These rules are mandatory and override convenience, debugging, and verification requests:

- Never open, read, print, search, grep, diff, or log `.env` files.
- Never read `.env.local`, `.env.production`, or any secret-bearing environment file.
- `.env.example` is safe to read.
- Treat secret values as opaque.
- Never place API keys in source code, frontend code, logs, screenshots, commits, or chat.
- Verify only whether required variables are present, never their values.

Also:

- Do not run environment-dump commands or include process environments in diagnostic output.
- Do not pass secret values as command-line arguments. Use the caller's existing environment or a
  secret manager without inspecting the values.
- Never weaken `.gitignore` coverage for secret-bearing files.
- Keep `.env.example` credential-free, with placeholders or empty values only. When configuration
  changes, update `.env.example` and setup documentation without copying from a local environment.
- Publicly exposed `NEXT_PUBLIC_*` variables must never contain secrets.
- If a task appears to require examining a secret value, stop and report that verification must be
  performed by the user or by a system that returns only presence/status metadata.

## Repository map and sources of truth

- `backend/`: FastAPI application, domain logic, copilot, persistence, and generated OpenAPI
  contract.
- `simulator/`: deterministic synthetic incident lifecycle and Redis-backed controls.
- `frontend/`: Next.js application. Follow `frontend/AGENTS.md` as well when working there.
- `tests/` and `backend/tests/`: integration and backend tests.
- `scripts/`: contract generation, browser-test orchestration, live-stack verification, and model
  evaluation utilities.
- `backend/contracts/openapi.v1.json`: generated API contract.
- `frontend/generated/api-types.ts`: generated frontend types. Do not hand-edit generated contract
  artifacts; change the Pydantic/API source and regenerate them.
- `backend/persistence/migrations/`: ordered, forward database migrations. Prefer additive,
  idempotent changes and preserve existing data.
- `docs/`: architecture, demo, responsible-AI, model-evaluation, checkpoints, screenshots, and
  traceability evidence.

Pydantic/OpenAPI is the public API source of truth. Keep frontend repository adapters and aliases
aligned with the generated schemas. If the API surface changes, regenerate contracts and include
both generated artifacts in the same change.

## Implementation expectations

- Preserve deterministic fixture and fallback behavior. Tests must not depend on network access,
  hosted model credentials, wall-clock races, or non-reproducible model prose.
- Keep copilot providers behind the provider-neutral interface. Provider output must pass the
  existing schema, citation, numeric, leader/tier, policy, timeout, budget, and fallback controls.
- Do not fabricate live model-evaluation results or select a winner without the required recorded
  evidence. Follow the pending-evaluation procedure when credentials are unavailable.
- Keep database queries parameterized. Do not construct SQL from untrusted strings.
- Restrict simulator cleanup to the documented synthetic namespace. Never flush an entire Redis
  database or delete unrelated keys.
- Maintain accessibility behavior, keyboard operation, light/dark themes, and supported desktop
  and laptop layouts when changing the frontend.
- Reuse the shared frontend colour, typography, spacing, and component-token system. Avoid
  reintroducing temporary design-variant review routes or mixing review fixtures into live paths.
- Keep logs useful but free of secrets, credentials, raw provider payloads containing sensitive
  metadata, and unnecessary user-controlled content.

## Working practices

- Inspect the working tree before editing. Preserve user changes and avoid broad rewrites unrelated
  to the task.
- Make the smallest coherent change that satisfies the request. Update relevant tests and
  documentation with the implementation.
- Prefer `rg` and `rg --files` for repository searches, while always excluding secret-bearing
  environment files according to the rules above.
- Use non-destructive commands. Do not reset databases, remove volumes, delete migrations, or
  discard working-tree changes unless the user explicitly requests it and the exact target has
  been verified.
- Do not commit, push, publish, deploy, or send external messages unless explicitly requested.
- Do not add real credentials to test fixtures. Use fake providers, monkeypatching, and explicit
  non-secret placeholders.
- When adding dependencies, justify the dependency, pin it consistently with project policy, and
  update the appropriate lock or manifest files.

## Local runtime

The supported integrated local runtime is Docker Compose with separate frontend, API, simulator,
ingestion, PostgreSQL, and Redis services:

```powershell
docker compose up --build -d
docker compose ps
```

Do not assume Docker is healthy merely because a command was issued. Use service health and the
documented live-stack verification. Do not run destructive Compose operations such as volume
removal unless explicitly authorized.

The safe copilot default is the disabled provider with a labelled deterministic fallback. Live
provider evaluation is optional and credential-dependent; consult `docs/model-evaluation.md`
without inspecting any secret-bearing environment file.

## Verification

Run the smallest relevant checks during development, then the complete applicable gate before
handoff. Standard commands from the repository root are:

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe scripts\generate_contracts.py
cd frontend
npm.cmd run typecheck
npm.cmd run lint
npm.cmd test
npm.cmd run test:browser
```

For changes requiring the real local data path, start PostgreSQL and Redis through Compose and use
the documented PostgreSQL-enabled test and live-stack commands. Never expose environment values in
test output.

Match verification effort to the change:

- Backend/domain/persistence: targeted tests, then the backend suite; use PostgreSQL integration
  coverage for persistence or migration changes.
- API schema: regenerate contracts, run Python tests, TypeScript validation, and affected frontend
  tests.
- Frontend: typecheck, lint, component tests, accessibility checks, and browser verification for
  changed user journeys.
- Compose/runtime: validate Compose configuration, service health, and `scripts/verify_live_stack.py`.
- Copilot: fake-provider tests, validation/fallback tests, and deterministic evaluation fixtures;
  do not require live keys for the standard test suite.

If a check cannot run, state exactly which check was skipped, why, and what remains unverified. Do
not claim a stage, checkpoint, evaluation, or test gate passed without corresponding evidence.

## Documentation and handoff

Keep operational documentation aligned with behavior. Update the relevant files when commands,
configuration names, APIs, architecture, migrations, component inventory, screenshots, or demo
steps change. Do not overwrite approved screenshots unless the associated UI was intentionally
changed and the full browser/accessibility gate has passed.

At handoff, summarize the behavior changed, files affected, checks run and their results, and any
remaining limitations. Never include secret values or environment-file contents in that summary.
