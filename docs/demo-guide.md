# Local setup and demo guide

## One-command stack

Prerequisites are Docker Desktop with a healthy Linux engine and free ports 3000, 5432, 6379 and
8100. From the repository root:

```powershell
Copy-Item .env.example .env
docker compose up --build -d
docker compose ps
```

`Copy-Item` creates an ignored local override file from the safe template. Keep `.env.example` in
the repository; it documents required variable names and non-secret defaults. Put any provider
credential only in the ignored `.env` file or a secret manager, never in `.env.example`.

Open `http://localhost:3000`. The checked-in Compose topology starts PostgreSQL 17.9, Redis 7.4.9,
a separate simulator, a separate ingestion worker, the FastAPI API and the live Next.js frontend.
The API is published at `http://localhost:8100/api/v1`; it continues to listen on port 8000 only
inside its container. Set `AMEX_API_HOST_PORT` if port 8100 is unavailable, then use the same port
for any host-side verification command.
Copilot is disabled unless one selected provider is explicitly configured; the deterministic
investigation remains fully usable.

PostgreSQL runs `backend/persistence/migrations/*.sql` on a fresh volume, including the additive
canonical Copilot thread/message migration, and runtime services also apply all idempotent
migrations during startup. Existing volumes are preserved. A fresh or reset
runtime stays empty and `STOPPED` until **Start healthy traffic** is selected; fixture projections
are never seeded into live storage. No real payment or credential data is seeded.

On a restart with a larger persisted Redis dataset, Redis may spend several seconds restoring its
AOF before accepting commands. Compose now waits for an exact `PONG` before starting dependent
services, and simulator initialization independently retries transient Redis loading, connection
and timeout errors with bounded backoff. Leave `docker compose up --build -d` running until it
finishes, then use `docker compose ps`; all six services should report `healthy` without manually
restarting the simulator.

To stop the stack without deleting its named PostgreSQL/Redis volumes:

```powershell
docker compose down
```

## Host-development alternative

```powershell
docker compose up -d postgres redis
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m uvicorn simulator.api:app --host 127.0.0.1 --port 8010
```

In separate terminals, start ingestion and the API:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.ingestion.app:app --host 127.0.0.1 --port 8020
.\.venv\Scripts\python.exe -m uvicorn backend.api.app:app --host 127.0.0.1 --port 8100
```

Then start the frontend:

```powershell
Set-Location frontend
npm.cmd ci
$env:NEXT_PUBLIC_AMEX_DATA_MODE="live"
$env:NEXT_PUBLIC_AMEX_API_URL="http://127.0.0.1:8100/api/v1"
npm.cmd run dev
```

## Judge path

1. On Overview, confirm technical error rate is the primary health verdict and business declines
   remain separate context.
2. Reset the synthetic demo, then start healthy traffic.
3. Inject the allowlisted deployment regression.
4. Open the active investigation and inspect Summary, Timeline and Evidence. Deterministic scope,
   signature and RCA remain authoritative before Copilot interpretation.
5. Select `Open Copilot`; confirm it focuses the Copilot tab and restores the one incident thread.
   Ask what weakens the leading hypothesis. With the model disabled, observe the persisted labelled
   deterministic fallback; the composer remains usable and no unvalidated prose or reason code appears.
6. On a validated fixture/provider response, expand citation `[1]`; readable value/scope/time and
   provenance appear first, with raw ID/source/calculation data nested under technical details.
7. Select Review and save a human decision. Attribution is fixed server-side to `demo-operator`.
8. Return to Overview and trigger rollback/recovery.

Automated equivalent:

```powershell
.\.venv\Scripts\python.exe scripts\verify_live_stack.py
```

The command records bounded local observations in `docs/e2e-observations.json`; these are not
production performance claims.
