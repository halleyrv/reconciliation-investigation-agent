# PHASE 2 — Backend and Reconciliation Engine

Implement the backend and deterministic reconciliation engine.

Requirements:

- FastAPI.
- PostgreSQL.
- SQLAlchemy.
- Alembic migrations.
- Pydantic validation.

Create domain models for:

- ReconciliationCase.
- Order.
- Payment.
- BankTransaction.
- Refund.
- Fee.
- Authorization.
- Evidence.
- InvestigationEvent.
- HumanApproval.

Implement deterministic matching:

- Exact matching.
- Partial matching.
- Duplicate detection.
- Refund matching.
- Fee discrepancy detection.
- Missing transaction detection.

Requirements:

- Decimal arithmetic.
- Database constraints.
- Idempotent ingestion.
- Transaction-safe operations.
- Structured error handling.
- Pagination and filtering.
- Audit history.

Expose REST endpoints to create and inspect reconciliation cases.

Write unit and integration tests.

Do not use an LLM for financial calculations or transaction matching.

Do not implement LangGraph yet.

Run the complete test suite and report the results.

---

## Amendments

Changes approved by the owner after the original text above. The original is never edited.

| Date | Change | Approved by |
|------|--------|-------------|
| 2026-11-09 | **Split into three sub-phases**, each reported to the owner before the next starts: **2a Ingestion**, **2b Reconciliation engine and evaluation**, **2c Cases, audit and API**. Same scope, smaller review units. | Owner |
| 2026-11-09 | **Prerequisite:** ADR-0001 (modular monolith) and ADR-0002 (money as integer minor units) move to `Accepted` before 2a starts. ADR-0002's rounding mode is already approved in the Phase 1 amendments. | Owner |
| 2026-11-09 | Clarification: **"Decimal arithmetic"** means ADR-0002. Amounts are stored and carried as `BIGINT` minor units + currency. `Decimal` is used only for intermediates such as basis-point fees, rounded once with `ROUND_HALF_EVEN`. Decimal strings from the simulator are converted to minor units at ingestion and rejected if they have more than 2 decimals. | Owner |
| 2026-11-09 | **Domain model scope.** Phase 2 builds the models that Phase 2 produces: `ImportBatch`, the six source records (`Order`, `Payment`, `BankTransaction`, `Refund`, `Fee`, `Authorization`), `FeeSchedule`, `ReconciliationRun`, `MatchGroup`, `Discrepancy` and `Case` (as `ReconciliationCase`). `Evidence` moves to the investigation agent phase, `HumanApproval` to the resolution/approvals phase. `InvestigationEvent` is covered by domain events in `audit.events`. Building them now would create tables nothing writes. | Owner |
| 2026-11-09 | **Detection covers all 11 Phase 1 anomaly types** (catalog below), not only the six listed in the original text. "Partial matching" means one-to-many and many-to-one matching (a settlement batch against many payments, an order against a short payment). | Owner |
| 2026-11-09 | **Evaluation against the simulator ground truth** happens in 2b, not in a later phase. It is the only objective proof that the deterministic engine works. | Owner |
| 2026-11-09 | Add assumptions, open decisions, detection catalog, API surface and measurable acceptance criteria (section below). | Owner |
| 2026-11-09 | **OD1 decided:** fee schedules are loaded by an operator through a CLI/API command, with values transcribed from the gateway policy; a test asserts they equal the policy numbers. No LLM parses policy text, and the simulator interface (Phase 1) is unchanged. | Owner |

### Amendment 2026-11-09: assumptions, catalog and acceptance criteria

#### Assumptions

| ID | Assumption |
|----|-----------|
| AS1 | Input is only the simulator's output files (`*.csv` / `*.json` + `manifest.json`). The backend never imports simulator code and never reads `ground_truth.json` outside the evaluation command |
| AS2 | Single currency (USD) and exact cents, so match tolerance is zero |
| AS3 | Business days for settlement are Monday to Friday, no holidays, matching the simulator's T+2 rule (Phase 1 AS6). To be confirmed against the simulator implementation |
| AS4 | Domain events are written to each context's outbox in the same transaction as the state change and dispatched in-process (ADR-0001) |
| AS5 | Infrastructure that arrives in this phase, as Phase 0 planned: Docker Compose with PostgreSQL + pgvector, Alembic, backend hexagonal skeleton, FastAPI `/health` |

#### Owner decisions

| ID | Decision | Resolution |
|----|----------|------------|
| OD1 | Where the engine gets fee schedules from. The simulator publishes them only as Markdown policy text (Phase 1 AS10), and parsing that text is not allowed to an LLM | **Approved by the owner on 2026-11-09:** an operator loads fee schedules through a CLI/API command, as a finance team would from the gateway contract. The demo script loads the values from `policies/` by hand-transcribed config, and a test asserts they equal the policy numbers |

#### Detection catalog

Discrepancy type codes are proposed names for `ref.discrepancy_types`.

| # | Phase 1 anomaly | Discrepancy type | Detected by |
|---|-----------------|------------------|-------------|
| 1 | Duplicate payments | `duplicate_payment` | Two payments claiming the same order with the same amount |
| 2 | Unauthorized refunds | `unauthorized_refund` | Refund with no authorization that covers its amount and was approved before it |
| 3 | Incorrect fees | `fee_mismatch` | Fee differs from the `FeeSchedule` applied to the payment |
| 4 | Missing transactions (subtype = direction) | `missing_in_bank`, `missing_in_gateway`, `missing_in_orders` | Record with no counterpart in the other source |
| 5 | Partial payments | `underpayment` | Payment amount below the order total |
| 6 | Delayed settlements | `settlement_delayed` | Bank credit later than batch date + 2 business days |
| 7 | Incorrect amounts | `amount_mismatch` | Bank credit differs from the batch net (payments − refunds − fees) |
| 8 | Inconsistent transaction references | `reference_mismatch` | Reference claim that resolves to no record or to a contradictory one |
| 9 | Out-of-order events | `sequence_violation` | Timestamps break the order ≤ payment ≤ settlement ≤ value date sequence, or refund before payment |
| 10 | Duplicate refunds | `duplicate_refund` | Two refunds for the same payment and amount |
| 11 | Conflicting re-sent records | `source_conflict` | `SourceConflictDetected` from Ingestion (`ingestion.source_conflicts`) |

Each type has its own matching rule class registered in the `MatchingEngine` (OCP, `project-structure.md`).

#### API surface

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/imports` | Import one simulator output directory. Idempotent by file hash |
| `GET` | `/imports/{id}` | Batch status, row counts, errors |
| `POST` | `/reconciliation-runs` | Run the engine for a period. Idempotent by `(period, ruleset_version)` |
| `GET` | `/reconciliation-runs/{id}` | Run status and summary |
| `GET` | `/discrepancies` | Filter by run, type, severity, minimum absolute delta. Paginated |
| `POST` | `/cases` | Open the case for a discrepancy. Idempotent: one case per discrepancy. The `DiscrepancyDetected` handler calls the same use case |
| `GET` | `/cases`, `/cases/{id}` | Filter by status, discrepancy type, run. Case detail includes its discrepancy and involved records |
| `GET` | `/cases/{id}/history` | The case's audit history |

Errors use Problem Details (RFC 9457). Lists use keyset pagination with a stable order.

#### Acceptance criteria

**2a Ingestion**

| ID | Criterion |
|----|-----------|
| AC-2a.1 | Importing the committed 200-order sample (seed 42) loads every record: row count per table equals the file's record count, and the sum of `amount_minor` per type equals the sum of the file's decimal strings × 100 |
| AC-2a.2 | Re-importing the same file creates no rows and returns the existing batch |
| AC-2a.3 | A re-sent record with the same external ID and a different payload creates one `source_conflicts` row and a `SourceConflictDetected` event. The canonical row is unchanged |
| AC-2a.4 | A file with one invalid row (schema violation, JSON float amount, more than 2 decimals) fails the whole batch: status `failed`, zero canonical rows, and an error naming file, line and field |
| AC-2a.5 | A file whose SHA-256 differs from `manifest.json` is rejected before any row is written |
| AC-2a.6 | Integration tests on real PostgreSQL prove the database itself rejects: two imports of the same file for one source, and a duplicate `(source_id, external_id)` |
| AC-2a.7 | `alembic upgrade head` from an empty database and `alembic downgrade base` both succeed. Every table lives in its context's schema |
| AC-2a.8 | `import-linter` contracts pass for backend layers and context independence: `domain` imports only stdlib and `shared_kernel` |

**2b Reconciliation engine and evaluation**

| ID | Criterion |
|----|-----------|
| AC-2b.1 | Each of the 11 anomaly types has a unit test through the `MatchingEngine` with in-memory data, asserting type, involved records and `delta_minor` |
| AC-2b.2 | One documented evaluation command compares the engine's output with `ground_truth.json` and writes a report. On seed 42 / 200 orders: discrepancy precision and recall are 100% per type, and link precision and recall for clean records are 100% |
| AC-2b.3 | The same evaluation on a held-out seed never used during development, at 2,000 orders, is reported as measured. Any miss is listed with its cause. The phase is not done while a miss is unexplained or unaccepted by the owner |
| AC-2b.4 | Every detected `delta_minor` equals the ground truth `expected_delta` converted to minor units |
| AC-2b.5 | Re-running the same period and ruleset creates no new match groups or discrepancies. Fingerprints are identical |
| AC-2b.6 | Two runs on fresh databases with the same input produce identical sets of fingerprints and deltas |
| AC-2b.7 | A run that fails halfway leaves status `failed` and no partial match groups or discrepancies |
| AC-2b.8 | `Money` rejects `float` and fractional minor units. Rounding exists in one function, tested at `.5` boundaries with `ROUND_HALF_EVEN` |
| AC-2b.9 | Integration tests prove the database rejects a record in two match groups of the same run and overlapping fee schedule periods |

**2c Cases, audit and API**

| ID | Criterion |
|----|-----------|
| AC-2c.1 | Every detected discrepancy has exactly one case. A second `POST /cases` for the same discrepancy returns the existing case with `200`, the first returns `201` |
| AC-2c.2 | Every endpoint in the API surface table exists and appears in the generated OpenAPI document |
| AC-2c.3 | List endpoints filter as specified. Walking every page returns each item exactly once, also when rows are inserted between page requests |
| AC-2c.4 | Errors return Problem Details: `422` validation, `404` not found, `409` stale version or idempotency conflict. No stack trace in any response |
| AC-2c.5 | Updating a case with a stale version returns `409` and changes nothing |
| AC-2c.6 | Every Phase 2 domain event appears in `audit.events` with its actor. The hash chain verifies. The application role's `UPDATE` and `DELETE` on `audit.events` are rejected by the database |
| AC-2c.7 | The backend has no LangGraph or LLM SDK dependency (lockfile and `import-linter`) |
| AC-2c.8 | `scripts/check.sh` passes, and the full test suite result (counts per type and duration) is reported to the owner |
| AC-2c.9 | The backend README lists only commands that were actually run. `data-model.md` matches the migrations, and any decision with real alternatives has an ADR |

#### Out of scope

| Excluded | Arrives in |
|----------|-----------|
| `Evidence`, findings, agent runs, LangGraph, LLM, Langfuse | Investigation agent phase |
| `HumanApproval`, proposed actions, adjustment ledger, authentication | Resolution/approvals phase |
| Policy documents in the database, retrieval | Knowledge/RAG phase |
| Read models beyond what the API queries need | When a consumer needs them |
| Frontend | Frontend phase |
