# ADR-0015: Denominators for anomaly rates

- **Status:** Proposed
- **Date:** 2026-11-09
- **Related:** ADR-0011, ADR-0013, docs/roadmap/phase-1-financial-data-simulator.md (anomaly configuration, AC4, AC8), docs/roadmap/phase-2-backend-and-reconciliation-engine.md (AC-2b.2), docs/roadmap/phase-6-evaluation-and-benchmarking.md
- **Kind:** Business (what share of the data should be anomalous, and how "affected" is measured) and technical (which population each rate applies to)

## Context

The spec says: "The rate of each anomaly type is configurable. With the defaults, about 15% of orders are affected." It does not say what each rate is a fraction of, or what "affected" means. Both choices decide how many instances of each type exist, and therefore what the evaluation metrics of Phase 2 (precision and recall per type, link precision and recall) and Phase 6 (false positive rate) can tell us.

Settlement batches do not grow with orders: one per gateway and day, about 61-63 per month. Anything measured per batch behaves differently from anything measured per order as the dataset scales.

### Evidence status

| Aspect | Status |
|--------|--------|
| Rates are configurable; about 15% of orders affected with defaults; every type at least twice at 200 orders (AC4) | **Spec** |
| Rates for `delayed_settlement`, `incorrect_amount` and `missing_in_bank` apply to settlement batches; all others to orders; `missing_transaction` applies its rate to each of its three directions | **Implemented** (`anomalies.py:Injector.count`, `configs/*.yaml`). **Hypothesis**: not approved |
| Defaults: `0.04` for the two settlement types, `0.01` for the rest | **Implemented** |
| Counts follow the population | **Tested**: `test_anomaly_rates_apply_to_their_target_population` (1,000 orders), `test_every_anomaly_type_appears_at_least_twice_in_200_orders` |
| What "affected" means | **Not defined** by the spec or the code |
| The README claim "about 18% … at both 200 and 2,000" | **Outdated** after the overlap fix (`8721e15`); corrected in the README with the measurements below |

### Measurements on the current code (seed 42)

| | 200 orders | 2,000 orders |
|---|---|---|
| Payments / settlement batches | 204 / 61 | 2,040 / 63 |
| Anomalies | 25 | 207 |
| Instances per settlement type (delayed, incorrect amount, missing in bank) | 2, 2, 1 | 3, 3, 1 |
| Instances per order type | 2 | 20 |
| Orders directly named by an anomaly | 7.0% | 7.0% |
| Orders without a clean expected link (includes orders inside an anomalous batch) | 13.0% | 20.1% |

## Options compared

| Denominator | What it means | Effect on metrics |
|-------------|---------------|-------------------|
| **Orders, for every type** | `count = rate × orders` | Simple to explain and matches "x% of orders". At 2,000 orders it asks for 20 delayed settlements out of 63 batches; before this was fixed, 50 of 62 batches were anomalous and only 377 orders kept a clean link. Link precision and recall would then be measured on a small, unrepresentative clean set |
| **Payments, for every type** | `count = rate × payments` | Payments include the duplicates and missing-in-orders payments that the anomalies themselves add, so the population depends on the rates (circular). About 2% larger than orders, otherwise the same behavior as orders |
| **Each type's own target population (implemented)** | Orders for order-level anomalies, settlement batches for batch-level ones | Each rate means "share of the records it can hit". But batch-level types stay at 1-3 instances whatever the scale, so their per-type recall in Phase 2 moves in steps of 33-100%: one miss on `missing_in_bank` is 0% recall. And the share of orders without a clean link grows with scale (13.0% → 20.1%), because each anomalous batch holds more orders |

Two related variants:

- **Refund anomalies per refunded payment.** Unauthorized and duplicate refunds would scale with refunds, not orders. Not implemented; it matters only if the refund rate changes a lot.
- **Scale the period with the orders.** For example 2,000 orders over ten months keeps orders per batch constant, so batch-level types scale too and the affected share stays stable. It changes AS2 ("one calendar month, configurable") only in its default.

## Decision (proposed)

1. Keep **each type's own target population** as the denominator (implemented): it is the only option where every rate stays meaningful as the data grows.
2. Define **"affected" with two published numbers**, both written in the manifest: the share of orders directly named by an anomaly, and the share of orders without a clean expected link. The spec's "about 15%" needs the owner to say which one it means.
3. For the 2,000-order run, either **scale the period** so batch-level types reach a statistically useful count, or accept that per-type recall for those three types rests on 1-3 instances and say so in Phase 2 and Phase 6 reports.

Points 2 and 3 are business decisions for the owner.

## Alternatives considered

The options table above. Orders-for-every-type was the first implementation and was replaced because it saturated the batches at scale (ODD log L5).

## Impact on the data model

None for records. The manifest would gain the two affected-share numbers (point 2). Point 3 changes `configs/orders-2000.yaml` only.

## Impact on validations

None for invariants. AC4 is unaffected at 200 orders. Phase 2 AC-2b.2 ("precision and recall are 100% per type" on seed 42 / 200 orders) is evaluated on 1-2 instances for batch-level types; the owner should know that before relying on it.

## Tests needed

- Existing: counts follow the population; every type at least twice at 200.
- If point 2 is accepted: a test that the manifest's affected shares equal an independent count from the ground truth.
- If point 3 is accepted: a test that the 2,000-order config yields at least N instances per batch-level type, with N chosen by the owner.

## Dependencies

- ADR-0011: batch-level denominators need a batch identity (both options there provide it).
- ADR-0013: instance counts per type feed its expected totals.
- Phase 2 AC-2b.2 and Phase 6 metrics are read on populations this ADR defines.

## Consequences

- **Positive:** rates mean the same thing at any scale; the affected share becomes measurable instead of approximate.
- **Negative:** two numbers for "affected" instead of one; batch-level types remain rare unless the period scales.
- **Follow-ups:** owner decisions on points 2 and 3; manifest change if point 2 is accepted.
