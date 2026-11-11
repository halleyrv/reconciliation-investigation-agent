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

- **D1** (decided by the owner on 2026-11-10, L3) `PATCH /cases/{id}` changes only `priority` and `assignee_id`, expected version in `If-Match`, stale -> `409` and nothing changes; status transitions stay with phases 4 and 5. Phase-file amendment row added.
- **D2** AC-2c.6 records an actor per event, but authentication is out of scope.
- **D3** What a run replacement does to the cases of the discrepancies it supersedes.

### Agent assumptions (owner to confirm at the 2c report)

- **C1** A case opens with priority equal to its discrepancy's severity (`ref.discrepancy_types.default_severity`, B8).

## Tasks

| ID | Specs | Route | Status | Evidence |
|----|-------|-------|--------|----------|
| T1 | S3, AC-2c.1: Investigation context, `Case` aggregate, migration 0003 `investigation.cases`, idempotent `OpenCase`, `CaseOpened` in its outbox | inline | done | L4 |
| T2 | S3, AC-2c.1: in-process outbox dispatch; the `DiscrepancyDetected` handler calls `OpenCase` | inline | done | L6 |
| T3 | AC-2c.6: Audit context, `audit.events` with hash chain, consumer of every Phase 2 event with its actor, application role without `UPDATE`/`DELETE` | inline | pending | |
| T4 | S1, S2, AC-2c.2, AC-2c.3, AC-2c.4: imports, runs and discrepancies endpoints, Problem Details, keyset pagination | inline | pending | |
| T5 | S2, AC-2c.1, AC-2c.3, AC-2c.5: cases endpoints, detail, history, versioned update (D1) | inline | pending | |
| T6 | S4: run replacement with `DiscrepancySuperseded` (D3), stuck-run recovery, contiguous statement coverage, infrastructure exit codes | inline | pending | |
| T7 | AC-2c.7, AC-2c.8, AC-2c.9: dependency proof, docs, ADRs, phase review | inline + independent reviewer | pending | |

Route: inline. No writer trigger: each task builds on the previous one (cases → dispatch → audit → API), so there are no independent parallel units.

## Log

- **L1** (2026-11-10, owner) After the 2b report: "continua en que te quedaste?"; asked whether 2b is accepted and 2c starts on `feat/p2c-cases-audit-api`: "si".
- **L2** (2026-11-10) Baseline on the new branch: `scripts/check.sh` exit 0, 236 passed in 52.5 s. Existing: per-context outboxes (`ingestion`, `recon`) written in the state change's transaction, `shared_kernel.events.event_payload`, FastAPI `create_app` with `/health` only; no dispatcher yet. Feature document created with 7 tasks and 3 open decisions.
- **L3** (2026-11-10, owner) D1: proposed `PATCH /cases/{id}` for `priority` and `assignee_id` only, version in `If-Match`, stale -> `409`, status transitions left to phases 4 and 5, recorded as an amendment row: "si".
- **L4** (2026-11-10) T1. New context `recon.investigation`: `ReconciliationCase` (statuses of the state machine, `Priority`, version from 1, close time exactly when resolved or escalated), `CaseOpened`; `OpenCase` returns `Opened(case, created)`: an existing case as is, `DiscrepancyNotFound` for an unknown discrepancy, otherwise a new `open` case at version 1 with priority = the discrepancy's severity (assumption C1) and one `CaseOpened`. Port `DiscrepancyReader` returns a `DiscrepancyView` (anti-corruption layer); the SQL adapter reads `recon.discrepancies` read-only and imports no Reconciliation code. Migration 0003: `investigation.cases` (UNIQUE and FK on `discrepancy_id`, status, priority, version and close-time checks), `investigation.outbox`. `SqlAlchemyCases.add` inserts with `ON CONFLICT (discrepancy_id) DO NOTHING`; the loser of a race re-reads the winner. Contracts: Investigation layers; Investigation imports no Ingestion or Reconciliation domain, application or adapters; upstream contexts import nothing from Investigation; domain forbidden list extended. RED: `uv run --locked pytest -q backend/tests/unit/investigation` -> `ModuleNotFoundError: No module named 'recon.investigation'`; `.../integration/investigation` -> `ModuleNotFoundError: No module named 'recon.investigation.adapters.outbound.sql'`. GREEN: 3 unit tests (opens with event, second call returns it and writes nothing, unknown discrepancy refused) and 4 PostgreSQL tests (persisted row and outbox payload once, unknown refused, 4 concurrent openings -> 1 case and 1 event, the database rejects a second case and a dangling discrepancy). Mutation check: without `on_conflict_do_nothing` the concurrency test fails. The migrations test lists `investigation` among the context schemas. `data-model.md` investigation section matches 0003. Gate exit 0, 246 passed.
- **L5** (2026-11-10) Native assessment of T1 (`bedd8eb`, base `02fe401`), escalated by me through item 1 (migration 0003) -> `high`, `review_due`. Lenses risk, resilience, reliability; owner granted (lineage `review-96953f301c1d1a9f`, 24 files, 649 lines); approved, acknowledged, authority burned. Risk: no findings. Non-blocking advisories: R4 the race re-read relies on READ COMMITTED seeing the winner; R3 the table CHECK constraints are untested; R3 the `ReconciliationCase` invariants (version, close time) are untested; R3 the FK on `discrepancy_id` blocks deleting a discrepancy (relevant to run replacement, D3); R3 the lost-race branch of `OpenCase` has no unit proof; R3 priority is coupled to severity values (`Priority(severity)` raises on an unknown one). Follow-up tests for the three test gaps go with T2.
- **L6** (2026-11-10) T2. `bootstrap/outbox.py`: `OutboxRelay` drains `ingestion.outbox`, `recon.outbox` and `investigation.outbox` oldest first, one row per transaction with `FOR UPDATE SKIP LOCKED`; handlers run, then the row is marked published (at least once: a crash in between redelivers, so handlers are idempotent); a failing handler leaves its row unpublished, is reported as `FailedDelivery` and does not stop the others. `investigation/adapters/inbound/events.py`: `on_discrepancy_detected` turns the payload into `OpenCase(discrepancy_id)`. `recon-import` and `recon-reconcile` drain after their command and print undelivered events on stderr as warnings without changing the exit code (backend README). Events with no handler yet are marked published; the audit consumer (T3) handles every type. RED: `uv run --locked pytest -q backend/tests/unit/investigation backend/tests/integration/bootstrap` -> `ModuleNotFoundError` for `recon.investigation.adapters.inbound` and `recon.bootstrap.outbox`; then, with both modules but the CLI not wired, the end-to-end test failed on `assert 0 == 41` cases. One test defect on the way: identity IDs continue after `TRUNCATE`, so the failure test no longer asserts an event ID. GREEN: reconciling through the commands opens 41 cases, one per discrepancy, leaves every outbox row published and 41 `CaseOpened`; a second reconcile opens none; a failing handler leaves its event for the next drain, which delivers it once (`seen == [2, 1]`). T1 review follow-ups: the lost-race branch through an in-memory hook (`opened_concurrently`), the case invariants (4 cases), and 6 CHECK violations on PostgreSQL; they passed at once and pin existing behavior. Gate exit 0, 260 passed.
