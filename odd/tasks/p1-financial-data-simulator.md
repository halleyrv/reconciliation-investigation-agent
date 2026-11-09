# P1 Financial Data Simulator

Objective: an independent simulator that produces reproducible synthetic financial datasets with ground truth. Spec: `docs/roadmap/phase-1-financial-data-simulator.md` (including its 2026-11-09 amendments).
Branch: `feat/p1-financial-data-simulator`. Delivery: work-unit commits, one draft PR, phase review on it, owner merges. Test runner: `pytest` through `uv run --locked`.

## Specs

Quoted verbatim from the phase file. Assumptions AS1-AS10, invariants I1-I9 and the interface live in the phase file and are not repeated here.

- **S1** Record types: "1. Generate synthetic e-commerce orders. 2. Generate payment gateway transactions. 3. Generate bank statement records. 4. Generate refunds. 5. Generate gateway fees. 6. Generate internal authorization records. 7. Generate financial policy documents."
- **S2** Anomalies: "Duplicate payments. Unauthorized refunds. Incorrect fees. Missing transactions. Partial payments. Delayed settlements. Incorrect amounts. Inconsistent transaction references. Out-of-order events. Duplicate refunds." plus amendment "**Conflicting re-sent records**".
- **S3** "Use Faker where appropriate. Use Decimal for all monetary values. Support deterministic generation using random seeds. Preserve ground truth for every injected anomaly. Generate CSV and JSON exports. Make the simulator independent of the AI agent. Include data validation and tests."
- **S4** "Start with a small dataset of 200 orders and expand to 2,000 after validation."
- **S5** "Deliver: Source code. Data schemas. Sample datasets. Ground truth. Test suite. Documentation."
- **S6** "Before finishing, demonstrate that the generated records are internally consistent and that every injected anomaly can be identified from ground truth."
- **S7** Acceptance criteria AC1-AC10 of the 2026-11-09 amendment, verbatim in the phase file.

### Agent assumptions (to confirm with the owner)

- **A1** Settlement batches are emitted as a gateway settlement report (`settlements`, IDs `STL-…`). I5 and the ground-truth links need the batch to be a record with an external ID; the bank credit description mentions it.
- **A2** I1 is checked per order: the payments that reference an order sum to its total (baseline: exactly one full payment). This is how duplicate and partial payments become visible.
- **A3** Anomaly → invariant mapping: duplicate payment I1; unauthorized refund I3; incorrect fee I4; missing transaction I1 (`missing_in_orders`) or I5 (`missing_in_bank`, `missing_in_gateway` = bank credit with nothing behind it); partial payment I1; delayed settlement I5; incorrect amount I5 (bank credit ≠ settlement net); inconsistent reference I1; out-of-order events I6 (payment captured before the order was placed); duplicate refund I2 + I3; conflicting re-sent record I7.
- **A4** Business days are Monday-Friday, no holidays. Every CSV/JSON field is a string, so both formats hold identical values.

## Tasks

| ID | Specs | Route | Status | Evidence |
|----|-------|-------|--------|----------|
| T1 | S1, S3, AC1, AC7 | inline | done | L3 |
| T2 | S3, AC2, AC5 | inline | done | L3 |
| T3 | S2, AC3, AC4 | inline | done | L3, L4 |
| T4 | S4, S5, S6, AC6, AC8, AC9, AC10 | inline | pending | |
| T5 | Phase review | independent reviewer | pending | |

Route: inline. No writer trigger applies: each task builds on the previous one (generator → checker → injectors → datasets), so there are no independent parallel units.

## Log

- **L1** (2026-11-09, owner) "arranca la fase 1"
- **L2** (2026-11-09) Baseline gate on the new branch: `scripts/check.sh` exit 0, 1 passed. Dependencies added: `faker` 40.44.0, `pyyaml` 6.0.3, `jsonschema` 4.26.0 (runtime); `types-pyyaml`, `types-jsonschema` (dev).
- **L3** (2026-11-09) T1-T3 built as one work unit: generator, 13 injectors for the 11 anomaly types, exports, JSON Schemas, invariant checker, `simulate` and `simulate-verify`. TDD deviation, stated honestly: the record model, config and generator were written before their tests. RED was observed at suite level before the checker and CLI existed: `uv run --locked pytest -q` → `ModuleNotFoundError: No module named 'simulator.cli'`. First GREEN attempt: 27 passed, 1 failed (`test_record_counts_follow_the_config`: 184 expected links instead of 200, because normal refunds were marked as anomaly targets); fixed in `Sim.generate_refunds`. Then `scripts/check.sh` exit 0, 28 passed. Tests cover AC1 (same seed → identical manifest; seed 43 differs), AC2 (clean run: 0 violations), AC3 (`explain` returns no problems), AC4 (11 types, min 2 each, 3 missing-transaction directions), AC5 (schemas + CSV == JSON, plus negative tests), AC7 (all exported values are strings; float money in config rejected), and one tamper test per checker rule (I1-I9).
- **L4** (2026-11-09) Robustness sweep, not committed (scratch script): seeds 0-99 with `configs/default.yaml`, each run checked with `validate_files` + `explain`: 0 bad seeds, 26 s total.
