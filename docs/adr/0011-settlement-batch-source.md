# ADR-0011: Settlement batches as a domain concept with the gateway settlement report as their source

- **Status:** Proposed
- **Date:** 2026-11-09
- **Related:** ADR-0003, ADR-0012, ADR-0013, ADR-0015, docs/roadmap/phase-1-financial-data-simulator.md (AS6, I5), docs/roadmap/phase-2-backend-and-reconciliation-engine.md (domain model scope, detection catalog #6 and #7), docs/architecture/data-model.md (`ingestion`)
- **Kind:** Business (whether the merchant receives a settlement report) and technical (how it is modeled and serialized)

## Context

Phase 1 AS6 says each gateway settles "one daily batch per gateway, paid T+2 business days, net of refunds and fees. One bank credit per batch", and invariant I5 checks "for each settlement batch: net = payments − refunds − fees". The ground truth must link "order ↔ payment ↔ settlement batch ↔ bank credit". So a settlement batch must exist as a concept with an identity.

The spec does not say where that identity comes from. Requirement 1 lists six record types plus policy documents, and none of them is a settlement report. The owner's guidance is to keep the concept separate from the input format, and not to reconcile a value against a number derived from the same movements being reconciled.

### Evidence status

| Aspect | Status |
|--------|--------|
| A settlement batch is a domain concept (AS6, I5, links) | **Spec** |
| A batch has an external ID that payments, fees, refunds and the bank credit refer to | **Hypothesis** (the spec names no ID) |
| The simulator writes `settlements.csv/.json` (`STL-000001`, gateway, `batch_date`, declared `net_amount`) | **Implemented** in `simulator/src/simulator/records.py`, `sim.py:build_settlements` |
| Payments, fees and refunds carry `settlement_ref`; the bank description names the batch ID | **Implemented** |
| I5 compares the declared net with the sum of the members, and with the bank credit (amount and date) | **Implemented** in `checks.py:_i5` |
| Tests | `test_checker_detects_each_broken_invariant[I5]` (tampered bank amount), `test_clean_run_has_zero_invariant_violations`, `test_expected_links_are_consistent_chains_untouched_by_anomalies` |
| Not covered by any test or anomaly | A declared net that differs from the sum of its members. No injector produces it, so this half of I5 is checked but never exercised by the ground truth |
| The Phase 2 domain model has a `Settlement` record | **Conflict:** the approved Phase 2 scope lists six source records and no settlement; `data-model.md` has only `payments.settlement_batch_ref` |

## Decision (proposed)

1. **Concept.** A settlement batch is a domain concept: one per gateway and capture day, with an identity, a batch date, a gateway and a net amount.
2. **Source.** Its reference source is the gateway settlement report, a source record type of its own. The report is what the gateway *declares* it paid, which is independent of both the movements and the bank statement. That gives three independent views of the same money: the movements (gateway transactions), the report (gateway's declared net) and the bank credit (what arrived).
3. **Format.** The report is one more record type in the simulator output, with its own schema. The concept does not depend on that format: if the report is unavailable, the batch is still identified by `settlement_ref` on the movements, and its net is derived (see the alternatives).

This is the option implemented today, but it is proposed here, not assumed correct because it exists.

## Alternatives considered

| Alternative | Why not (or why it stays open) |
|-------------|--------------------------------|
| **B. No settlement source.** The batch exists only as `settlement_ref` on payments, fees and refunds; its net is derived from them and compared with the bank credit | Matches the approved Phase 2 domain model as written. It is not circular: the derived net is compared against the bank, an independent source. But it loses the gateway's own declaration, so a gateway that reports one net and pays another cannot be told apart from a movement error. Viable fallback if the owner prefers not to amend Phase 2 |
| **C. Batch only in the ground truth.** No reference on the records; links point to a batch ID that no source mentions | The engine could not rebuild the batch from the data, so "a settlement batch against many payments" (Phase 2 partial matching) would be undetectable |
| **D. The bank credit is the batch.** One bank credit per batch, matched by amount | Makes `missing_in_bank` and `incorrect_amount` undefinable: with no credit or a wrong amount, the batch has no identity |

## Impact on the data model

- Simulator: no change if accepted (already implemented). If B is chosen, `settlements.*` and `settlements.schema.json` are removed, the ground truth links keep `settlement_id` as the shared `settlement_ref`, and the sample is regenerated.
- Backend (Phase 2): accepting this ADR requires a Phase 2 amendment adding `Settlement` as a seventh source record and `ingestion.settlements` to `data-model.md`, plus `settlement_batch_ref` on `fees` and `refunds` (today only on `payments`). Under B, only the last part applies.

## Impact on validations

- I5 keeps its two halves: declared net = members, and one bank credit equal to the declared net, dated batch date + lag. Under B, I5 reduces to "derived net = bank credit".
- An anomaly that makes the report contradict its members (for example "gateway report net differs from its transactions") becomes possible under this decision. It is not in the Phase 1 catalog and is not proposed here.

## Tests needed

- Existing: clean run satisfies I5; tampered bank credit breaks I5; links resolve to the batch and its credit.
- Missing: a tamper test that changes only `settlements.net_amount` and expects I5 on that settlement (proves the report half of I5 is checked).
- If B is chosen: a test that the batch is reconstructible from `settlement_ref` alone.

## Dependencies

- ADR-0013 (I5 rows of the matrix) and ADR-0015 (batch denominator) assume a batch identity, which both A and B provide.
- Phase 2 domain model scope (owner amendment) must change if A is accepted.

## Consequences

- **Positive:** three independent sources for the same money; matching a batch against many payments has a natural anchor.
- **Negative:** one more record type, schema and table; Phase 2 scope grows by one record.
- **Follow-ups:** Phase 2 amendment; the missing tamper test above.
