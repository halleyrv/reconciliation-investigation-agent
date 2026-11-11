# P2c Cases, audit and API

Objective: one case per discrepancy, an append-only hash-chained audit history of every Phase 2 domain event, and the REST API of the phase, plus the run replacement and recovery work carried over from 2b. Spec: `docs/roadmap/phase-2-backend-and-reconciliation-engine.md` (sub-phase 2c and its amendments).
Branch: `feat/p2c-cases-audit-api`. Delivery (owner decision 2026-11-10, `AGENTS.md` quality-gate rules 4-6, chained-pr strategy `feature-branch-chain`): one small PR per task from a task branch cut from the updated phase branch into the phase branch; one final PR from the phase branch into `main` after the phase review and the owner report. Test runner: `pytest` through `uv run --locked`; integration tests on PostgreSQL from Docker Compose. Migrations 0001 and 0002 are on `main`: every schema change is a new revision.

## Specs

Quoted verbatim from the phase file.

- **S1** "Expose REST endpoints to create and inspect reconciliation cases." "Requirements: FastAPI. PostgreSQL. SQLAlchemy. Alembic migrations. Pydantic validation." "Structured error handling. Pagination and filtering. Audit history."
- **S2** API surface (amendment):

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

  "Errors use Problem Details (RFC 9457). Lists use keyset pagination with a stable order."
- **S3** Domain model scope: "`Case` (as `ReconciliationCase`)". "`InvestigationEvent` is covered by domain events in `audit.events`." AS4: "Domain events are written to each context's outbox in the same transaction as the state change and dispatched in-process (ADR-0001)".
- **S4** Carried over from 2b (amendments 2026-11-10): "**Replacing a completed run** (`DiscrepancySuperseded`, a rerun of a period under the same ruleset) **moves to 2c** with the case model". "**B7 accepted**: a run left `running` by a crash blocks its period until recovered; a recovery command or timeout arrives in 2c with run replacement." 2b L17: "statement coverage per bank statement (contiguous coverage instead of a high-water mark), with run replacement and `DiscrepancySuperseded`." 2a F4 (extended in 2b L13): "`recon-import` exits 1 with a traceback when the database is unreachable or unmigrated, which the README reserves for a rejected file; give infrastructure failures their own exit code and message".
- **S5** "Do not use an LLM for financial calculations or transaction matching." "Do not implement LangGraph yet." "Run the complete test suite and report the results."
- **AC-2c.1** "Every detected discrepancy has exactly one case. A second `POST /cases` for the same discrepancy returns the existing case with `200`, the first returns `201`"
- **AC-2c.2** "Every endpoint in the API surface table exists and appears in the generated OpenAPI document"
- **AC-2c.3** "List endpoints filter as specified. Walking every page returns each item exactly once, also when rows are inserted between page requests"
- **AC-2c.4** "Errors return Problem Details: `422` validation, `404` not found, `409` stale version or idempotency conflict. No stack trace in any response"
- **AC-2c.5** "Updating a case with a stale version returns `409` and changes nothing"
- **AC-2c.6** "Every Phase 2 domain event appears in `audit.events` with its actor. The hash chain verifies. The application role's `UPDATE` and `DELETE` on `audit.events` are rejected by the database"
- **AC-2c.7** "The backend has no LangGraph or LLM SDK dependency (lockfile and `import-linter`)"
- **AC-2c.8** "`scripts/check.sh` passes, and the full test suite result (counts per type and duration) is reported to the owner"
- **AC-2c.9** "The backend README lists only commands that were actually run. `data-model.md` matches the migrations, and any decision with real alternatives has an ADR"
- Out of scope (phase file): "`Evidence`, findings, agent runs, LangGraph, LLM, Langfuse"; "`HumanApproval`, proposed actions, adjustment ledger, authentication"; "Policy documents in the database, retrieval"; "Read models beyond what the API queries need"; "Frontend".

### Open decisions (owner)

- **D1** AC-2c.5 needs a case update, but the API surface has no update endpoint and the state machine transitions (`investigating`, `awaiting_approval`, `resolved`, `escalated`) belong to the agent and approval phases.
- **D2** AC-2c.6 records an actor per event, but authentication is out of scope.
- **D3** What a run replacement does to the cases of the discrepancies it supersedes.

## Tasks

| ID | Specs | Route | Status | Evidence |
|----|-------|-------|--------|----------|
| T1 | S3, AC-2c.1: Investigation context, `Case` aggregate, migration 0003 `investigation.cases`, idempotent `OpenCase`, `CaseOpened` in its outbox | inline | pending | |
| T2 | S3, AC-2c.1: in-process outbox dispatch; the `DiscrepancyDetected` handler calls `OpenCase` | inline | pending | |
| T3 | AC-2c.6: Audit context, `audit.events` with hash chain, consumer of every Phase 2 event with its actor, application role without `UPDATE`/`DELETE` | inline | pending | |
| T4 | S1, S2, AC-2c.2, AC-2c.3, AC-2c.4: imports, runs and discrepancies endpoints, Problem Details, keyset pagination | inline | pending | |
| T5 | S2, AC-2c.1, AC-2c.3, AC-2c.5: cases endpoints, detail, history, versioned update (D1) | inline | pending | |
| T6 | S4: run replacement with `DiscrepancySuperseded` (D3), stuck-run recovery, contiguous statement coverage, infrastructure exit codes | inline | pending | |
| T7 | AC-2c.7, AC-2c.8, AC-2c.9: dependency proof, docs, ADRs, phase review | inline + independent reviewer | pending | |

Route: inline. No writer trigger: each task builds on the previous one (cases → dispatch → audit → API), so there are no independent parallel units.

## Log

- **L1** (2026-11-10, owner) After the 2b report: "continua en que te quedaste?"; asked whether 2b is accepted and 2c starts on `feat/p2c-cases-audit-api`: "si".
- **L2** (2026-11-10) Baseline on the new branch: `scripts/check.sh` exit 0, 236 passed in 52.5 s. Existing: per-context outboxes (`ingestion`, `recon`) written in the state change's transaction, `shared_kernel.events.event_payload`, FastAPI `create_app` with `/health` only; no dispatcher yet. Feature document created with 7 tasks and 3 open decisions.
