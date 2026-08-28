# AI Payment Incident Investigator

A synthetic-data hackathon MVP that detects technical payment incidents, identifies affected
traffic, deterministically ranks observed operational changes, and provides an evidence-grounded
investigation copilot. Business declines remain separate from technical failures throughout.

## Local prerequisites

- Python 3.13
- Node.js 22 and npm 10
- Docker Desktop with a healthy Linux engine

Copy `.env.example` to `.env` for local overrides. The checked-in example contains no credentials;
real provider keys must never be committed. The application uses synthetic data only and the fixed
server-side `demo-operator` principal—there is no login screen or browser-selected identity.

## Quick start

```powershell
Copy-Item .env.example .env
docker compose up --build -d
docker compose ps
```

Open `http://localhost:3000`. This starts the live frontend, FastAPI, PostgreSQL and Redis. The API
applies idempotent migrations and seeds the deterministic synthetic projection only when the store
is empty. See `docs/demo-guide.md` for the judge path, host-development alternative and shutdown.

`AMEX_POSTGRES_DSN` is a PostgreSQL connection string consumed by the backend; it is not a browser
hyperlink. The checked-in local value targets the Compose PostgreSQL service from the host. Inside
Compose the service injects its own `postgres`-hostname DSN.

## Contract generation

```powershell
.\.venv\Scripts\python.exe scripts\generate_contracts.py
```

This exports `backend/contracts/openapi.v1.json`, regenerates
`frontend/generated/api-types.ts`, and runs strict TypeScript validation. Pydantic/OpenAPI is the
sole public API source of truth; frontend aliases and repositories import the generated schemas.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest
cd frontend
npm.cmd run typecheck
npm.cmd run lint
npm.cmd test
npm.cmd run test:browser
```

With PostgreSQL and Redis running, the real transport/demo gate is:

```powershell
$env:AMEX_RUN_POSTGRES_TESTS="1"
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe scripts\verify_live_stack.py
```

## Redis-backed simulator

```powershell
docker compose up -d redis
.\.venv\Scripts\python.exe -m simulator.main start
.\.venv\Scripts\python.exe -m simulator.main inject
.\.venv\Scripts\python.exe -m simulator.main recover
.\.venv\Scripts\python.exe -m simulator.main reset
```

The commands emit only synthetic, schema-validated events. The reset command deletes only keys in
the `amex:synthetic:*` namespace; it never flushes the Redis database.

## Copilot provider and evaluation

The safe default is `AMEX_COPILOT_PROVIDER=disabled`, which returns a labelled deterministic
fallback without model prose. The provider-neutral implementation supports exactly one selected
runtime provider/model. The Claude Sonnet 5 versus GPT-5.6 Terra result is pending credentials; no
winner has been fabricated. Exact environment-variable names and commands are documented in
`docs/model-evaluation.md`.

Architecture, responsible-AI boundaries, business value, source traceability, component inventory
and stage evidence are under `docs/`.
