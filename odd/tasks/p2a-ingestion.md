# P2a Ingestion

Objective: idempotent, transaction-safe import of the simulator's output into typed canonical tables, with lineage and conflicting re-sends. Spec: `docs/roadmap/phase-2-backend-and-reconciliation-engine.md` (sub-phase 2a and its 2026-11-09 amendments).
Branch: `feat/p2a-ingestion`. Delivery: work-unit commits, one draft PR, phase review, owner merges. Test runner: `pytest` through `uv run --locked`; integration tests on PostgreSQL from Docker Compose.

## Specs

Quoted verbatim from the phase file.

- **S1** Stack: "FastAPI. PostgreSQL. SQLAlchemy. Alembic migrations. Pydantic validation." and AS5 "Infrastructure that arrives in this phase, as Phase 0 planned: Docker Compose with PostgreSQL + pgvector, Alembic, backend hexagonal skeleton, FastAPI `/health`"
- **S2** Amendment: "Amounts are stored and carried as `BIGINT` minor units + currency. `Decimal` is used only for intermediates such as basis-point fees, rounded once with `ROUND_HALF_EVEN`. Decimal strings from the simulator are converted to minor units at ingestion and rejected if they have more than 2 decimals."
- **S3** Domain model scope (2a part): "`ImportBatch`, the six source records (`Order`, `Payment`, `BankTransaction`, `Refund`, `Fee`, `Authorization`)" plus ADR-0011 "`Settlement` (the gateway settlement report) [...] with `ingestion.settlements`; refunds and fees carry `settlement_batch_ref`."
- **S4** AS1 "Input is only the simulator's output files (`*.csv` / `*.json` + `manifest.json`). The backend never imports simulator code and never reads `ground_truth.json` outside the evaluation command"; AS4 "Domain events are written to each context's outbox in the same transaction as the state change and dispatched in-process (ADR-0001)"
- **S5** "Idempotent ingestion. Transaction-safe operations. Structured error handling." "Database constraints."
- **AC-2a.1** "Importing the committed 200-order sample (seed 42) loads every record: row count per table equals the file's record count, and the sum of `amount_minor` per type equals the sum of the file's decimal strings × 100"
- **AC-2a.2** "Re-importing the same file creates no rows and returns the existing batch"
- **AC-2a.3** "A re-sent record with the same external ID and a different payload creates one `source_conflicts` row and a `SourceConflictDetected` event. The canonical row is unchanged"
- **AC-2a.4** "A file with one invalid row (schema violation, JSON float amount, more than 2 decimals) fails the whole batch: status `failed`, zero canonical rows, and an error naming file, line and field"
- **AC-2a.5** "A file whose SHA-256 differs from `manifest.json` is rejected before any row is written"
- **AC-2a.6** "Integration tests on real PostgreSQL prove the database itself rejects: two imports of the same file for one source, and a duplicate `(source_id, external_id)`"
- **AC-2a.7** "`alembic upgrade head` from an empty database and `alembic downgrade base` both succeed. Every table lives in its context's schema"
- **AC-2a.8** "`import-linter` contracts pass for backend layers and context independence: `domain` imports only stdlib and `shared_kernel`"

### Agent assumptions (owner to confirm at the 2a report)

- **A1** AC-2a.1 vs AC-2a.3: the sample's `orders.json` has 204 records with 4 re-sent IDs (ANM-0031..0034). Under AC-2a.3 a re-send creates no canonical row, so "row count per table equals the file's record count" is read as: `raw_records` = file record count; canonical rows = distinct external IDs; canonical + `source_conflicts` = file record count; the amount sum is over the canonical (first-seen) records.
- **A2** The JSON files are the ingestion format (AC-2a.4 names "JSON float amount"); the CSV twins are not imported. "Line" in an error is the 1-based record position in `records`.
- **A3** One `ImportBatch` per file, each in its own transaction. A directory import first verifies every file against `manifest.json` (AC-2a.5), then imports the files.
- **A4** Data sources by producing system, seeded by migration: `shop` (ecommerce: orders), `gateway` (gateway: payments, refunds, fees, settlements), `bank` (bank: bank_transactions), `back_office` (authorization: authorizations).
- **A5** A re-sent record with an identical payload is a no-op (no canonical row, no conflict).
- **A6** The CI and the local gate start PostgreSQL with Docker Compose, so `scripts/check.sh` keeps being the single check.

## Tasks

| ID | Specs | Route | Status | Evidence |
|----|-------|-------|--------|----------|
| T1 | S1, AC-2a.7 (skeleton), AC-2a.8 | inline | done | L3 |
| T2 | S2, S3, S4, AC-2a.2..AC-2a.5 (unit, in-memory fakes) | inline | pending | |
| T3 | S5, AC-2a.1..AC-2a.7 (PostgreSQL) | inline | pending | |
| T4 | Import CLI, `data-model.md`, backend README, roadmap status | inline | pending | |
| T5 | Phase review (`docs/process/phase-review.md`) | independent reviewer | pending | |

Route: inline. No writer trigger: each task builds on the previous one (skeleton → domain → persistence → entry point), so there are no independent parallel units.

## Log

- **L1** (2026-11-09, owner) "sigue con fase 2, es la que sigue me parece no?"
- **L2** (2026-11-09) Verified: Phase 1 `done`, Phase 2 `pending` and split into 2a/2b/2c; ADR-0001 and ADR-0002 already `Accepted` (prerequisite met). Baseline gate on `feat/p2a-ingestion`: `scripts/check.sh` exit 0, 60 passed.
- **L3** (2026-11-09) T1 skeleton. `backend/` workspace member `recon` (fastapi 0.162.2, sqlalchemy 2.1.8, alembic 1.20.1, psycopg 3.3.8, pydantic 2.14.3; dev `httpx2`, which Starlette 1.10 asks for instead of the deprecated `httpx` client). `compose.yaml`: `pgvector/pgvector:pg18` on `127.0.0.1:55432`, trust auth on loopback, so no password is committed. `scripts/check.sh` runs `docker compose up -d --wait db` before pytest, so CI and local keep one gate. RED: `uv run --locked pytest -q backend/tests` -> `ModuleNotFoundError: No module named 'recon.bootstrap'`. GREEN: `test_health_reports_ok` passed; gate exit 0, 61 passed. Contracts: layers `adapters > api > application > domain` and "domain and shared kernel use only the stdlib" KEPT; a probe module importing `sqlalchemy` in `ingestion/domain` broke the second, one importing `recon.ingestion.adapters` broke both (probe deleted). Context independence contract waits for the second context (2b). `--import-mode=importlib` was tried and dropped: it shadows the `simulator` package with the `simulator/` directory.
