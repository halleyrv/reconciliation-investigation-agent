# P2b Reconciliation engine and evaluation

Objective: a deterministic engine that links clean records and detects the 11 Phase 1 anomaly types from the ingested data, persisted transaction-safely and idempotently, and proven against the simulator ground truth. Spec: `docs/roadmap/phase-2-backend-and-reconciliation-engine.md` (sub-phase 2b and its amendments).
Branch: `feat/p2b-reconciliation-engine`. Delivery: work-unit commits, one draft PR, phase review, owner merges. Test runner: `pytest` through `uv run --locked`; integration tests on PostgreSQL from Docker Compose.

## Specs

Quoted verbatim from the phase file.

- **S1** "Implement deterministic matching: Exact matching. Partial matching. Duplicate detection. Refund matching. Fee discrepancy detection. Missing transaction detection." Amendment: "**Detection covers all 11 Phase 1 anomaly types** (catalog below), not only the six listed in the original text. "Partial matching" means one-to-many and many-to-one matching (a settlement batch against many payments, an order against a short payment)."
- **S2** Detection catalog (amendment), one rule per row: "Each type has its own matching rule class registered in the `MatchingEngine` (OCP, `project-structure.md`)." Types: `duplicate_payment`, `unauthorized_refund`, `fee_mismatch`, `missing_in_bank`, `missing_in_gateway`, `missing_in_orders`, `underpayment`, `settlement_delayed`, `amount_mismatch`, `reference_mismatch`, `sequence_violation`, `duplicate_refund`, `source_conflict`.
- **S3** "Do not use an LLM for financial calculations or transaction matching." "Decimal arithmetic" amendment: "`Decimal` is used only for intermediates such as basis-point fees, rounded once with `ROUND_HALF_EVEN`."
- **S4** Domain model scope (2b part): "`FeeSchedule`, `ReconciliationRun`, `MatchGroup`, `Discrepancy`". OD1: "an operator loads fee schedules through a CLI/API command, as a finance team would from the gateway contract. The demo script loads the values from `policies/` by hand-transcribed config, and a test asserts they equal the policy numbers". AS3 amendment: "business days are Monday to Friday minus the holiday calendar the simulator publishes in its settlement policy. The engine gets the calendar the same way as fee schedules (OD1): loaded by an operator, with a test that it equals the policy."
- **S5** AS1 "The backend never imports simulator code and never reads `ground_truth.json` outside the evaluation command". AS2 "Single currency (USD) and exact cents, so match tolerance is zero".
- **AC-2b.1** "Each of the 11 anomaly types has a unit test through the `MatchingEngine` with in-memory data, asserting type, involved records and `delta_minor`"
- **AC-2b.2** "One documented evaluation command compares the engine's output with `ground_truth.json` and writes a report. On seed 42 / 200 orders: discrepancy precision and recall are 100% per type, and link precision and recall for clean records are 100%"
- **AC-2b.3** "The same evaluation on a held-out seed never used during development, at 2,000 orders, is reported as measured. Any miss is listed with its cause. The phase is not done while a miss is unexplained or unaccepted by the owner"
- **AC-2b.4** "Every detected `delta_minor` equals the ground truth `expected_delta` converted to minor units"
- **AC-2b.5** "Re-running the same period and ruleset creates no new match groups or discrepancies. Fingerprints are identical"
- **AC-2b.6** "Two runs on fresh databases with the same input produce identical sets of fingerprints and deltas"
- **AC-2b.7** "A run that fails halfway leaves status `failed` and no partial match groups or discrepancies"
- **AC-2b.8** "`Money` rejects `float` and fractional minor units. Rounding exists in one function, tested at `.5` boundaries with `ROUND_HALF_EVEN`"
- **AC-2b.9** "Integration tests prove the database rejects a record in two match groups of the same run and overlapping fee schedule periods"

### Agent assumptions (owner to confirm at the 2b report)

- **B1** One discrepancy per root cause, as the ground truth counts them (ADR-0013 multi-violation cases). Records already claimed by a more specific rule are not reported again by a generic one: the second refund of a `duplicate_refund` is not also an `unauthorized_refund`; a payment whose `order_ref` resolves only after normalization is a `reference_mismatch`, not `missing_in_orders` plus an unpaid order; the extra payment of a `duplicate_payment` is not an overpayment.
- **B2** Evaluation matches a detected discrepancy to a ground-truth anomaly by catalog type and the same set of `(source, external_id)` records. Ground-truth type names map to catalog codes (`incorrect_fee` -> `fee_mismatch`, `partial_payment` -> `underpayment`, `delayed_settlement` -> `settlement_delayed`, `incorrect_amount` -> `amount_mismatch`, `inconsistent_reference` -> `reference_mismatch`, `out_of_order_event` -> `sequence_violation`, `conflicting_resent_record` -> `source_conflict`, `missing_transaction` + subtype -> `missing_in_<subtype>`); the map lives only in the evaluation adapter.
- **B3** A clean link is one match group per order with the order, its payment, its settlement and the bank credit of that settlement; link precision and recall are computed against `expected_links` (158 on seed 42). The bank credit is tied to its settlement by the `STL-` reference in its description, a reference claim like `order_external_ref`.
- **B4** A run covers a `DATERANGE` period of order/batch dates; v1 runs over every record of the imported export within the period. The fingerprint is SHA-256 over type, sorted record identities and period.
- **B5** `match_group_members` and `discrepancy_records` add `settlement_id` and `authorization_id` columns (ADR-0011 added settlements after the model was written; the ground truth names authorizations as involved records). The holiday calendar is a `recon` table loaded by the operator command, like fee schedules.
- **B6** Ingestion exposes read queries in `recon.ingestion.api` for the canonical records; Reconciliation imports only that module and `shared_kernel` (context-independence contract, deferred from 2a).

## Tasks

| ID | Specs | Route | Status | Evidence |
|----|-------|-------|--------|----------|
| T1 | AC-2b.8 (one rounding function, `Money` float and fraction rejection) | inline | done | L3 |
| T2 | S1, S2, S3, AC-2b.1, AC-2b.4: reconciliation domain (`FeeSchedule`, business calendar, `MatchGroup`, `Discrepancy` + fingerprint) and `MatchingEngine` with clean linking and the 11 rules, unit tests in memory | inline | pending | |
| T3 | S4, B5, B6, AC-2b.5, AC-2b.7, AC-2b.9: migration `0002` (`recon` schema, `ref.discrepancy_types`), ingestion read API, run use case and PostgreSQL persistence, context-independence contract | inline | pending | |
| T4 | S4 (OD1, AS3): operator command loading fee schedules and holidays, test that they equal the published policy | inline | pending | |
| T5 | S5, AC-2b.2, AC-2b.4, AC-2b.6: evaluation command and report on seed 42 / 200 orders | inline | pending | |
| T6 | AC-2b.3: held-out seed at 2,000 orders, measured and every miss explained | inline | pending | |
| T7 | Docs (`data-model.md`, backend README, roadmap) and phase review (`docs/process/phase-review.md`) | inline + independent reviewer | pending | |

Route: inline. No writer trigger: each task builds on the previous one (rounding → engine → persistence → reference data → evaluation), so there are no independent parallel units.

## Log

- **L1** (2026-11-10, owner) "arranca 2b"
- **L2** (2026-11-10) Verified: 2a `done`, roadmap says "2b next"; no ADR is `Proposed`. Baseline gate on `feat/p2b-reconciliation-engine`: `scripts/check.sh` exit 0, 132 passed. Exploration: ground truth has 41 anomalies on seed 42 (4 per type except `missing_transaction` 5, `delayed_settlement` 2, `incorrect_amount` 2) and 158 `expected_links`; fees are 290 bps + 0.30 (gateway_a) and 250 bps + 0.25 (gateway_b), rounded once half-even; holidays 2026-10-09, 2026-10-20, 2026-10-28 on the sample.
- **L3** (2026-11-10) T1. `shared_kernel.money.round_to_minor(Decimal) -> int`: the backend's only rounding, `ROUND_HALF_EVEN` on an intermediate already in minor units (a fee is `amount_minor * bps / 10000 + fixed_minor`, which equals the simulator's cents formula scaled by 100). RED: `uv run --locked pytest -q backend/tests/unit/shared_kernel` -> `ImportError: cannot import name 'round_to_minor'`. GREEN: 27 passed (`.5` boundaries 0.5 -> 0, 1.5 -> 2, 2.5 -> 2, -2.5 -> -2; float, int and str rejected). `Money(Decimal(...))` passed at once: the existing `type(...) is not int` check already rejects fractional minor units, now pinned. Gate exit 0, 144 passed.
