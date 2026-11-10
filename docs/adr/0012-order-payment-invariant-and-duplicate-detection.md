# ADR-0012: Order-payment invariant I1 and how duplicate payments become detectable

- **Status:** Accepted (owner, 2026-11-09)
- **Date:** 2026-11-09
- **Related:** ADR-0013, docs/roadmap/phase-1-financial-data-simulator.md (AS7, I1, AC3), docs/roadmap/phase-2-backend-and-reconciliation-engine.md (detection catalog #1, #5, #8)
- **Kind:** Business (what a correctly paid order is) and technical (how the invariant is checked)

## Context

The spec states:

- **I1:** "Every payment references an existing order, and its amount equals the order total".
- **AS7:** "Baseline: one full payment per order".
- **AC3:** "every ground-truth anomaly causes at least one violation".

Read literally, I1 is a property of each payment on its own. A duplicate payment is a second capture of the same order for the same amount: each copy references an existing order and equals its total, so **no invariant is violated**, and AC3 fails for that type. The literal I1 and AC3 cannot both hold while duplicate payments are an anomaly type. This ADR documents the conflict and the options. It changes no invariant: that needs the owner's approval.

### Evidence status

| Aspect | Status |
|--------|--------|
| I1 literal text, AS7 baseline, AC3 | **Spec** |
| Conflict between literal I1 and AC3 for duplicate payments | **Derived from the spec** (no code needed to see it) |
| The checker implements I1 per order: (a) the payment references an existing order; (b) the payments that reference each order sum to its total | **Implemented** in `checks.py:_i1`. This **changes the spec's semantics** without approval: it is a hypothesis, not a decision |
| Duplicate payment, partial payment, missing-in-orders and inconsistent reference are mapped to I1 | **Implemented** in `anomalies.py:INJECTORS` |
| Tests | `test_checker_detects_each_broken_invariant[I1]` (tampered payment amount), `test_every_violation_is_explained_by_exactly_one_anomaly_and_vice_versa` (seed 42). No test pins the I1 wording itself |

### Scenarios

| Scenario | Literal I1 (per payment) | Implemented I1 (per order sum) | Option B: literal I1 + new I10 "exactly one payment per order" |
|----------|--------------------------|--------------------------------|---------------------------------------------------------------|
| One full payment (baseline) | holds | holds | holds |
| Partial payment (paid < total) | violated: amount ≠ total | violated: sum ≠ total | I1 violated |
| Duplicate payment (two full captures) | **holds: no violation** | violated: sum = 2 × total | I10 violated |
| Legitimate split payment (two captures that add up to the total) | violated twice, a false positive | holds | I1 and I10 violated, a false positive |
| Missing in orders (payment for an unknown order) | violated | violated | I1 violated |
| Inconsistent reference (payment names a variant of the order ID) | violated (unknown order) | violated twice (unknown order; order with no payment) | I1 (payment) and I10 (order with zero payments) |

Split payments are not part of the v1 baseline (AS7), so the split-payment row is a future concern, not a current defect.

### Does the domain establish exactly one payment per order?

- **Phase 1 says it for the baseline.** AS7: "Baseline: one full payment per order". That is the simulator's clean data, not a general business law.
- **Partial payments do not contradict it.** The spec's partial payment ("the customer paid less than the order total") is one payment for less than the total. "Exactly one payment" holds; "amount equals total" (literal I1) breaks. So partial payments stay an I1 anomaly.
- **What it excludes are split payments:** several captures that together pay one order (installments, gift card plus card). They are not in the v1 spec, the baseline or the anomaly catalog.
- **Implications of admitting split payments later:** I10 would become "the payments of an order sum to its total", and duplicate detection would need a stronger key than "same order, same amount" (for example the capture instrument or a payment intent ID the gateway reports). That is a new decision, out of scope for v1.

## Decision


**Option B, accepted by the owner on 2026-11-09.** Keep I1 exactly as the spec writes it, and make the AS7 baseline explicit as a new invariant **I10: every order has exactly one payment**, with this scope: "v1: exactly one payment per order; split payments are out of scope". Duplicate payments map to I10.

Why: it changes no approved text, it names the rule that duplicate payments actually break (the order was paid more than once), and Phase 2 already detects duplicates by that rule ("two payments claiming the same order with the same amount", catalog #1). The cost is one more invariant and an inconsistent reference that breaks two invariants instead of one.

## Alternatives considered

| Alternative | Consequence |
|-------------|-------------|
| **A. Per-order sum (implemented today).** Reinterpret I1 as "the payments of each order sum to its total" | One invariant covers partial and duplicate payments and tolerates split payments. But it rewrites an approved invariant without approval, and it merges two business rules (amount and count) into one, so a report cannot say which one broke |
| **C. Literal I1 and drop duplicate payments from the AC3 requirement** | Violates AC3 as written; the anomaly would be in the ground truth with no observable symptom in the invariants |
| **D. Duplicate payment reuses the same external ID** | Then it breaks I7 (unique IDs), but that is the "conflicting re-sent record" anomaly, not a second capture. Gateways give each capture its own ID |
| **E. Detect duplicates only in Phase 2, outside the invariants** | The invariants stop being the proof of AC3 for one type; the simulator would need a second, ad hoc proof |

## Impact on the data model

None. The records already carry what both A and B need (`order_ref`, `amount`).

## Impact on validations

- Option B: the invariant table gains I10 (a phase 1 amendment by the owner); `_i1` returns to the literal per-payment check; a new `_i10` counts payments per order; the duplicate-payment injector declares I10; inconsistent reference declares I1 and I10; the README matrix and ADR-0013 change accordingly.
- Option A: no change, but the spec's I1 text must be amended to the per-order wording, so code and spec agree.

## Tests needed

- One test per invariant wording: a duplicate payment breaks I10 (B) or I1 (A) and nothing else; a partial payment breaks I1 only.
- A test that a single full payment satisfies both.
- If split payments are ever added, a test that they are not flagged.

## Dependencies

- ADR-0013: rows for duplicate payment, partial payment, missing in orders and inconsistent reference depend on this decision.
- Phase 2 catalog #1 already detects duplicates by count, which fits B.

## Consequences

- **Positive (B):** the spec's I1 stays as approved; each business rule has its own invariant and its own detector.
- **Negative (B):** one more invariant; code rework (checker, one injector declaration, tests, sample regeneration).
- **Follow-ups:** owner amendment to the Phase 1 invariant table for whichever option is chosen.
