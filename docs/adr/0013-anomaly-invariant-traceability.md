# ADR-0013: Anomaly-to-invariant traceability matrix

- **Status:** Proposed
- **Date:** 2026-11-09
- **Related:** ADR-0011, ADR-0012, ADR-0014, docs/roadmap/phase-1-financial-data-simulator.md (I1-I9, AC3, anomaly configuration), docs/roadmap/phase-2-backend-and-reconciliation-engine.md (detection catalog), simulator/README.md (anomaly catalog)
- **Kind:** Technical (it follows from the invariant definitions); the anomaly descriptions themselves are business

## Context

The spec says "Each anomaly type declares which invariants it breaks, and it must break those and no others", and AC3 requires 100% explanation in both directions. It does not give the mapping. This ADR records it, why each relation holds, which anomalies cause more than one violation, and which extra violations are avoided on purpose.

### Evidence status

| Aspect | Status |
|--------|--------|
| Each type declares its invariants and breaks exactly those | **Spec** |
| The mapping below | **Implemented** as each injector's own declaration (`anomalies.py:INJECTORS`). **Hypothesis**: no approved table backs it |
| Declared = observed, every violation explained by exactly one anomaly | **Tested**: `test_every_violation_is_explained_by_exactly_one_anomaly_and_vice_versa` (seed 42, 200 orders); 1,000-seed sweep in the ODD log (not a committed test) |
| The mapping equals an expected table | **Not tested.** The tests compare the injectors with themselves (declared vs observed). If an injector declared and broke the wrong invariant, they would still pass |
| Rows for duplicate payment, partial payment, missing in orders, inconsistent reference | Depend on ADR-0012 (I1 wording) |
| I5 rows | Depend on ADR-0011 (batch source) and ADR-0014 (business days) |

## Decision (proposed)

Adopt this matrix as the contract between the anomaly catalog and the invariants. It is written for the **target state** after ADR-0012 (accepted): literal I1 plus I10. The code today still implements the per-order I1 (ADR-0012 option A), so four rows differ from what the injectors declare now; they are marked *changes*.

| Anomaly (subtype) | Breaks | Why it breaks it | Violations per instance |
|-------------------|--------|------------------|-------------------------|
| Duplicate payment | I10 (*changes*, today I1) | The order has two payments instead of one; each one alone equals the total, so literal I1 holds | 1 |
| Unauthorized refund | I3 | The refund has no authorization at all | 1 |
| Incorrect fee | I4 | The fee differs from the gateway schedule applied to the payment | 1 |
| Missing transaction (`missing_in_orders`) | I1 (*unchanged rule, literal wording*) | The payment references an order that does not exist. I10 is about orders, and this order does not exist | 1 |
| Missing transaction (`missing_in_bank`) | I5 | The batch has zero bank credits instead of exactly one | 1 |
| Missing transaction (`missing_in_gateway`) | I5 | A bank payout names a batch that does not exist | 1 |
| Partial payment | I1 (*literal wording*) | The single payment is below the order total; I10 holds (one payment) | 1 |
| Delayed settlement | I5 | The bank credit is dated after batch date + lag | 1 |
| Incorrect amount | I5 | The bank credit differs from the batch net | 1 |
| Inconsistent reference | I1, I10 (*changes*, today I1 twice) | The payment references an unknown order ID (I1); the real order has zero payments (I10) | **2** (two invariants) |
| Out-of-order event (`payment_before_order`) | I6 | The order is timestamped after its payment | 1 |
| Duplicate refund | I2, I3 | The two refunds exceed the payment (I2); the copy has no authorization (I3) | **2** (two invariants) |
| Conflicting re-sent record (`orders`) | I7 | The same order ID appears twice | 1 |

Expected totals on the 200-order sample (seed 42), target state: 25 anomalies, 29 violations (`I1: 6, I10: 4, I2: 2, I3: 4, I4: 2, I5: 7, I6: 2, I7: 2`). Today `simulate-verify` reports `I1: 10` because I1 and I10 are still one check.

This matrix stays **Proposed** until the owner approves it in its final form: it depends on ADR-0015's counts and on the holiday calendar of ADR-0014, which may move instances but not invariants.

### Extra violations avoided on purpose

Each anomaly could break more invariants than it declares. The injectors prevent that, which is a design choice worth reviewing, not a property of the data:

| Anomaly | Would also break | Prevented by |
|---------|------------------|--------------|
| Duplicate payment | I4, I5, I6 | The copy gets its own correct fee, is captured later on the same day and settles in the same batch |
| Partial payment | I4 | The fee is recomputed on the paid amount |
| Incorrect fee | I5 | The batch net is computed from the fee actually charged, so the report and bank agree with it |
| Duplicate refund, unauthorized refund | I8 (negative net), I5 | Refunds go only to batches that stay positive and are not reserved by a settlement-level anomaly |
| Conflicting re-sent record | I1, I6 | Only the customer email differs; total and timestamp are equal. If the amount differed, it would also break I1 |
| Delayed settlement | I6 | The credit moves later, never earlier than the batch |
| Incorrect amount | I8 | The new amount stays positive |
| Any order-level anomaly | I5 in a settlement-level anomaly's batch | Settlement-level batches are reserved before order-level injection (no overlap) |

### Invariants that some anomalies hide

Some checks cannot run when a reference does not resolve. The checker skips them, which is correct but hides information:

- I6 (`order ≤ payment`) is not checked for `missing_in_orders` and `inconsistent_reference` payments, because their order cannot be found.
- I6 (`batch ≤ bank value date`) is not checked for `missing_in_gateway` credits, because their batch does not exist.

### Coverage gaps against Phase 2

- Phase 2 catalog #9 also detects "refund before payment"; the simulator only injects `payment_before_order`, so that half of the rule has no ground truth to be evaluated against.
- I8 and I9 are never broken by any anomaly. They are proven only by tamper tests and by clean runs.

## Alternatives considered

| Alternative | Why not |
|-------------|---------|
| Let anomalies break whatever they naturally break, and declare all of it | Many anomalies would cascade into I5 and I4, and AC3's "exactly one anomaly per violation" would turn overlapping chains into ambiguity |
| One invariant per anomaly type | Invariants would become a restatement of the catalog instead of independent consistency rules; they would prove nothing |

## Impact on the data model

None.

## Impact on validations

`explain` (in `checks.py`) is the executable form of this matrix today, fed by the injectors' declarations. Adopting the matrix adds a fixed expected table to compare against.

## Tests needed

- **Missing, most important:** a test that asserts this matrix as a literal table written in the test itself, type by type: the invariants each type breaks and its number of violations per instance. It must not read the injectors' declarations: today a wrong declaration that the injector also implements would pass. Written together with the code change that introduces I10 (TDD), not before.
- A test that the anomalies listed as hiding checks do not create I6 violations.

## Dependencies

- ADR-0012 changes four rows (I1 wording, possible I10).
- ADR-0011 defines what I5 compares against.
- ADR-0014 defines the lag used by the delayed-settlement row.

## Consequences

- **Positive:** a reviewable contract between the simulator and the reconciliation engine; Phase 2 detectors can be checked against it.
- **Negative:** the matrix must be kept in sync with ADR-0012 and ADR-0014 outcomes.
- **Follow-ups:** the matrix test; decide whether Phase 1 should also inject "refund before payment".
