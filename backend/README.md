# Backend

The reconciliation backend: a modular monolith (ADR-0001) with one package and one PostgreSQL schema per bounded context. Phase 2a delivers the **Ingestion** context: it imports a simulator export into typed canonical tables, idempotently and in one transaction per file. Phase 2b adds the **Reconciliation** context (in progress): reference data, the deterministic matching engine and its runs.

Architecture rules live in [`docs/architecture/`](../docs/architecture/README.md); the 2a tasks and evidence in [`odd/tasks/p2a-ingestion.md`](../odd/tasks/p2a-ingestion.md).

## Run it

Every command below runs from the repository root and was run while building 2a and 2b.

```bash
docker compose up -d --wait db                          # PostgreSQL 18 + pgvector on 127.0.0.1:55432
uv run --locked alembic -c backend/alembic.ini upgrade head
uv run --locked recon-import simulator/samples/orders-200-seed-42
uv run --locked recon-reference backend/reference/gateway-policy-2026.json
uv run --locked recon-reconcile --from 2026-10-01 --to 2026-10-31
uv run --locked recon-evaluate simulator/samples/orders-200-seed-42 --from 2026-10-01 --to 2026-10-31 \
    --report docs/evaluation/p2b-seed-42-orders-200.md
uv run --locked alembic -c backend/alembic.ini downgrade base
```

`recon-import` prints one line per file:

```text
orders.json: completed, 204 records
payments.json: completed, 206 records
...
```

| Exit code | Meaning |
|-----------|---------|
| 0 | Every file completed (also when every file was already imported) |
| 1 | At least one file was rejected; each error shows its line and field |
| 2 | Nothing was imported: a file differs from `manifest.json` or is missing |

`recon-reference` loads the fee schedules and bank holidays the engine applies. An operator transcribes them by hand from the gateway's published policy into [`reference/gateway-policy-2026.json`](reference/gateway-policy-2026.json); a test checks that file against the policy text, and no code parses the policy (OD1). Loading is idempotent:

```text
fee schedules: 2 added, 0 already loaded
holidays: 7 added, 0 already loaded
calendar years: 1 added, 0 already loaded
```

`calendar_years` says which years the holiday list is complete for, so a year with no holidays is still known.

| Exit code | Meaning |
|-----------|---------|
| 0 | Loaded, or already loaded |
| 1 | Nothing loaded: a fee schedule overlaps a different one already loaded for the same gateway and fee type |
| 2 | Nothing loaded: the file is missing or does not match the format |

`recon-reconcile` runs the engine for an inclusive period and prints the run; running the same period and ruleset again returns the same run and writes nothing (AC-2b.5). The rules see every ingested record, and the run keeps what belongs to its period: a discrepancy goes to the period of the latest settlement batch date among its records, a match group to the period of its batch (ADR-0016). A period that shares a day with another live run of the same ruleset is refused, and so is a period whose last payouts are not in the imported bank data yet (its end plus the 2-business-day settlement lag): running it early would report its last batches as `missing_in_bank`:

```text
run 93ee173f-d4f2-4080-b9a9-34c40ad4b27e (v1, 2026-10-01 to 2026-10-31): completed
```

| Exit code | Meaning |
|-----------|---------|
| 0 | The run completed, now or before |
| 1 | The run failed, for example with no fee schedule or holiday calendar for its period (a December run also needs the next year's calendar for its due dates); it is recorded as `failed` with no partial output, and a new call may retry. If it could not even be marked failed, a second line says so and the run stays `running` |
| 2 | Nothing was run: an invalid period, a period overlapping another live run, a period whose last payouts are not imported yet, a run of it still in progress, or an unreachable database |

After `recon-import` or `recon-reconcile` exits 0, it delivers the events their run wrote (`ingestion.outbox`, `recon.outbox`, `investigation.outbox`) in-process: each `DiscrepancyDetected` opens its discrepancy's case in `investigation.cases`, one case per discrepancy (AC-2c.1). An event whose handler fails, or every event when the database fails during delivery, stays unpublished, is reported on stderr as a warning without changing the exit code, and is delivered by the next successful command.

Every delivered event is also appended to `audit.events` with its actor (`system` and the command or handler that wrote it, ADR-0018) and the aggregate it belongs to. Each entry's SHA-256 covers its content and the previous entry's hash, and a trigger rejects any `UPDATE` or `DELETE` of the table. A redelivered event is audited once. The trail is tamper-evident for changed or reordered entries, not for entries removed from its end, and not tamper-proof: the table owner can disable the trigger or `TRUNCATE` it and rebuild a chain that still verifies, until the application connects with its own `INSERT`/`SELECT`-only role (deployment follow-up).

`recon-evaluate` is the only code that reads `ground_truth.json` (AS1). It scores the completed run of the period against the export's known answer and writes a Markdown report: precision and recall per discrepancy type, clean-link precision and recall, and every missed, unexpected or wrong-delta finding. A detected discrepancy matches an expected one when type and involved records are equal; its delta is compared separately. The seed-42 report is [`docs/evaluation/p2b-seed-42-orders-200.md`](../docs/evaluation/p2b-seed-42-orders-200.md):

```text
discrepancies: 41 expected, 41 detected, 41 matched
links: 158 expected, 158 found, 158 matched
delta mismatches: 0
report: docs/evaluation/p2b-seed-42-orders-200.md (PASS)
```

| Exit code | Meaning |
|-----------|---------|
| 0 | Everything matched |
| 1 | The report lists misses, extras or wrong deltas |
| 2 | Nothing was evaluated: no completed run of the period, or no readable ground truth |

The database URL comes from `RECON_DATABASE_URL` (default: the Compose database, which uses trust auth on loopback and has no password).

## HTTP API

`recon.bootstrap.app:create_app` is the FastAPI application factory. No ASGI server is a dependency yet, so the API is exercised through `fastapi.testclient.TestClient` (`backend/tests/integration/api/`). This prints its paths:

```bash
uv run --locked python -c "from recon.bootstrap.app import create_app; print(sorted(create_app().openapi()['paths']))"
```

| Method | Path | Answer |
|--------|------|--------|
| `POST` | `/imports` | Body `{"directory": "<path>"}`. `200` with every batch (status, row count, errors). Re-posting the same export returns the same batches and writes nothing |
| `GET` | `/imports/{id}` | The batch with its stored errors |
| `POST` | `/reconciliation-runs` | Body `{"from": "2026-10-01", "to": "2026-10-31"}` (inclusive, ruleset `v1`). `200` with the run; a second identical POST returns the same run |
| `GET` | `/reconciliation-runs/{id}` | The run plus its match group count and discrepancies per type |
| `GET` | `/discrepancies` | Optional `run_id`, `type`, `severity` (`low`, `medium`, `high`), `min_abs_delta` (minor units, `abs(delta) >= value`); `limit` 1-200 (default 50); ordered by ID. Pass `next_cursor` back as `cursor` until it is `null` |
| `POST` | `/cases` | Body `{"discrepancy_id": "<uuid>"}`. `201` with the opened case, `200` with the existing one (one case per discrepancy; a run already opens them through `DiscrepancyDetected`). Unknown discrepancy `404` |
| `GET` | `/cases` | Optional `status`, `discrepancy_type`, `run_id`; `limit` and `cursor` as for `/discrepancies` |
| `GET` | `/cases/{id}` | The case, its discrepancy and its involved records (`type` and `id` of each source record). `ETag` is the case version |
| `PATCH` | `/cases/{id}` | Body with `priority` and/or `assignee_id` (`null` unassigns). Requires `If-Match: "<version>"` (missing or `*`: `428`; a weak `W/` tag: `412`, RFC 9110 compares strongly; stale: `409`; nothing changes) and `X-Actor-Id` (missing: `422`), recorded as a claimed, unverified `user` |
| `GET` | `/cases/{id}/history` | The case's events from `audit.events`, oldest first, each with its actor |

`POST /imports` reads only under the directory named by `RECON_IMPORT_ROOT`: when it is unset, or the path resolves outside it, nothing is read and the answer is `422`. Events a POST writes are delivered in-process like the CLI does; a delivery problem is logged as a warning and never changes the response. Every API write except `PATCH /cases/{id}` is recorded with the actor `system:api` (ADR-0018).

Errors are Problem Details (`application/problem+json`: `type`, `title`, `status`, `detail`), never a stack trace:

| Status | When |
|--------|------|
| `422` | Invalid request (field errors in `errors`), import path outside the root or not an export, manifest mismatch, period ending before it starts, malformed cursor, a run that failed (its ID in `run_id`) |
| `404` | Unknown batch, run or path |
| `409` | The period overlaps a live run, a run of it is still running, or its bank data does not reach the last payout due date |
| `500` | Anything unexpected, with a generic detail |

## What an import guarantees

| Rule | How |
|------|-----|
| Files match the export | Every file's SHA-256 is checked against `manifest.json` before any row is written |
| A file is imported once per source | Re-importing returns the existing batch; the database enforces `UNIQUE (source_id, file_sha256)` |
| A record is never overwritten | A re-sent external ID with a different payload creates a `source_conflicts` row and a `SourceConflictDetected` event in `ingestion.outbox`; the first record stays |
| One bad row rejects its whole file | The batch is `failed` with file, line and field, and no records of that file are stored |
| Money is exact | Decimal strings become integer minor units; a JSON number, a negative amount or more than 2 decimals is rejected (ADR-0002) |
| Concurrent imports are safe | Each file's transaction takes an advisory lock for its source |

Only the JSON files are read; their CSV twins carry the same records. In an error, `line` is the record's 1-based position in `records`, and line 0 means the file itself.

## Tests

```bash
uv run --locked pytest -q backend/tests                 # needs the Compose database
```

Unit tests (`backend/tests/unit`) use an in-memory unit of work. Integration tests (`backend/tests/integration`) create a fresh database per session, migrate it and drop it afterwards.
