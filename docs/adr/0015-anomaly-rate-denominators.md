# ADR-0015: Denominators for anomaly rates, prevalence and the "affected" share

- **Status:** Accepted (owner, 2026-11-09)
- **Date:** 2026-11-09
- **Related:** ADR-0011, ADR-0013, docs/roadmap/phase-1-financial-data-simulator.md (AS2, anomaly configuration, AC4, AC8), docs/roadmap/phase-2-backend-and-reconciliation-engine.md (AC-2b.2), docs/roadmap/phase-6-evaluation-and-benchmarking.md
- **Kind:** Business (what share of the data is anomalous, how "affected" is measured, what the large dataset represents) and technical (which population each rate applies to)

## Context

The spec says: "The rate of each anomaly type is configurable. With the defaults, about 15% of orders are affected." It defines neither what each rate is a fraction of, nor what "affected" means. Both choices fix how many instances of each type exist, and so what the evaluation metrics of Phase 2 (precision and recall per type, link precision and recall) and Phase 6 (false positive rate) can tell.

Settlement batches do not grow with orders: one per gateway and day, about 61-63 in a one-month period.

### Evidence status

| Aspect | Status |
|--------|--------|
| Rates are configurable; about 15% of orders affected with defaults; every type at least twice at 200 orders (AC4) | **Spec** |
| Rates for `delayed_settlement`, `incorrect_amount` and `missing_in_bank` apply to settlement batches; all others to orders; `missing_transaction` applies its rate to each direction | **Implemented** (`anomalies.py:Injector.count`). **Hypothesis** |
| Defaults: `0.04` for the two settlement types, `0.01` for the rest | **Implemented** when this ADR was proposed; since its acceptance the eight order-level types use `0.02` (Decision, point 3) |
| Counts follow the population | **Tested**: `test_anomaly_rates_apply_to_their_target_population`, `test_every_anomaly_type_appears_at_least_twice_in_200_orders` |
| What "affected" means | **Not defined** by the spec or the code when this ADR was proposed; defined by its Decision (point 2) |
| Measurements below | Read-only runs of the current code, seed 42; scripts not committed (ODD log L13) |

## 1. Rates per denominator

The same datasets measured against each possible denominator. "Named" means the entity appears in the `records` of a ground-truth anomaly.

| Run | Orders named | Payments named | Batches named (settlement-level anomaly) |
|-----|--------------|----------------|------------------------------------------|
| 200 orders, 1 month (61 batches) | 14 / 200 = 7.0% | 18 / 204 = 8.8% | 5 / 61 = 8.2% |
| 2,000 orders, 1 month (63 batches) | 140 / 2,000 = 7.0% | 180 / 2,040 = 8.8% | 7 / 63 = 11.1% |
| 2,000 orders, 10 months (584 batches) | 7.0% | 8.8% | 52 / 584 = 8.9% |

Each denominator answers a different question:

- **Orders:** "how many customer orders have a problem". It matches the spec's wording. Incorrect fees name the payment and the fee, not the order, so they are invisible here unless the definition follows the chain (see 3).
- **Payments:** about 2% larger than orders, because duplicates and missing-in-orders payments are added by the anomalies themselves. The denominator then depends on the rates (circular). Natural for gateway-side anomalies (fees), but it adds little over orders.
- **Settlement batches:** the only population where delayed settlements, incorrect amounts and missing payouts can happen. Applying an order rate to it saturates the batches at scale (first implementation: 50 of 62 batches anomalous at 2,000 orders, ODD log L5).

## 2. Directly affected vs without a clean link

Two different properties, measured on the same runs:

| Run | Orders without a clean expected link | Payments inside an anomalous batch | Batches containing any named record |
|-----|--------------------------------------|------------------------------------|-------------------------------------|
| 200 orders, 1 month | 13.0% | 4.9% | 27.9% |
| 2,000 orders, 1 month | 20.1% | 11.9% | **82.5%** |
| 2,000 orders, 10 months | 16.9% | 8.7% | 28.1% |

- **Directly affected:** the entity is part of an anomaly. Stable across scales (7.0% of orders).
- **Without a clean link:** the order's chain (order, payment, batch, bank credit) touches any anomaly, including a clean order that settled in an anomalous batch. It depends on how many orders share a batch.

## 3. What the spec's "about 15%" means

Proposed definition: **the share of orders directly affected, following the chain**: an order counts when it, its payment, its fee or its refund is named by an anomaly. It is measurable from the ground truth alone, independent of batch size, and comparable across runs.

Under that definition the current defaults give 16 of 200 = **8.0%** (the 14 named orders plus the 2 orders behind incorrect fees), not about 15%. Two honest readings:

- The spec ties the **defaults** to 15%: setting the default rates so the published number lands near 15% is configuring to the spec, not forcing results. The rates stay visible in the config and the measured share is reported, never adjusted after generation.
- Or the 15% was an estimate and the spec is amended to the measured value.

Which one is a business decision; the owner chose the first (Decision, point 3).

## 4. Why the share changes between 200 and 2,000

Order-level anomalies scale with orders, so the directly affected share is the same (7.0%). Settlement-level anomalies scale with batches, and a one-month period has about the same number of batches at any order count (61 vs 63). At 2,000 orders each batch holds about 32 orders instead of 3.3, so each anomalous batch removes ten times more orders from the clean links (13.0% → 20.1%), and almost every batch ends up containing some anomalous record (27.9% → 82.5%).

## 5. Does a longer period improve representativeness?

The 10-month run shows what it fixes and what it does not:

- **Fixes:** orders per batch return to the 200-order profile (3.4), batch-level types reach 23, 23 and 6 instances instead of 3, 3 and 1, and the share of dirty batches returns to 28%. Per-type recall for batch-level types stops moving in steps of 33-100%.
- **Does not fix:** it models a small merchant over a long time. If the goal is a larger merchant (many orders per batch), a longer period misrepresents it, and the right lever is the distribution instead: more gateways or several batches per day, or a minimum number of instances per type for evaluation, stated as such.

So the choice depends on what the 2,000-order dataset should represent, which is a business question: "the same merchant, more history" (longer period) or "a bigger merchant" (more orders per batch, plus a stated minimum of instances per type).

## 6. Prevalence is not a model metric

| Quantity | Belongs to | Denominator |
|----------|------------|-------------|
| Prevalence of type T | The dataset | Entities of T's target population (sections 1 and 3) |
| Recall of T | The engine or agent | Ground-truth instances of T |
| Precision of T | The engine or agent | Detections reported as T |
| False positive rate | The engine or agent | Clean entities of the same population (orders, payments or batches), not all records |

Consequences for evaluation:

- Precision depends on prevalence: with the same false positive rate, a rarer type shows lower precision. Reports must publish prevalence next to precision.
- A recall measured on 1 to 3 instances is not a rate. Reports must publish the instance count next to each per-type metric.
- The false positive rate needs a stated negative population per type; "clean links" is a link metric, not a negative population for every anomaly type.

## Decision

1. Keep each type's own target population as its denominator (implemented).
2. Define "affected" as in section 3, and publish both numbers in the manifest: directly affected orders (following the chain) and orders without a clean link.
3. **Decided by the owner on 2026-11-09: the defaults target 15%.** The eight order-level rates go from `0.01` to `0.02`; seed 42 gives 32 of 200 and 320 of 2,000 orders directly affected (16.0%). The share is published in the manifest (`affected_orders`) and pinned by a test as a measurement, never adjusted after generation.
4. **Decided by the owner on 2026-11-09: more history.** `configs/orders-2000.yaml` spans 2026-01-01 to 2026-10-31 (584 batches; 23, 23 and 6 batch-level instances on seed 42). The minimum instances per batch-level type is not set by the owner yet; the test uses 5 as a stated assumption.
5. Evaluation reports publish prevalence and instance counts next to every per-type metric (Phase 2 and Phase 6 amendments below).

## Alternatives considered

Sections 1 and 5 compare them: orders for every type (saturates batches at scale), payments for every type (circular, no gain), longer period vs bigger merchant.

## Impact on the data model

None for records. The manifest gains the two affected shares (point 2). Point 4 changes only `configs/orders-2000.yaml`, or the batch generation if a bigger merchant is chosen.

## Impact on validations

None for invariants. AC4 holds at 200 orders under any option.

## Tests needed

- The manifest's affected shares equal an independent count from the ground truth (point 2).
- The 2,000-order config yields at least N instances per batch-level type, with N chosen by the owner (point 4).
- No test may tune rates to a target share: the measured share is pinned as a regression value, never used to adjust rates or data after generation.

## Amendments this would require

- **Phase 1:** the definition of "affected" (point 2); the default-rate decision (point 3); AS2's default period for the large run (point 4).
- **Phase 2:** AC-2b.2 ("precision and recall are 100% per type" on seed 42 / 200 orders) reports instance counts and prevalence per type, and states that batch-level types rest on 1-2 instances at 200 orders.
- **Phase 6:** detection metrics are reported per type with prevalence and instance count; the false positive rate states its negative population per type.

## Dependencies

- ADR-0011: batch-level denominators need the batch identity it defines.
- ADR-0013: instance counts per type feed its expected totals.

## Consequences

- **Positive:** rates mean the same at any scale; "affected" becomes a measured number; evaluation metrics are read with their base rates.
- **Negative:** two affected numbers instead of one; Phase 2 and Phase 6 reports carry more columns.
- **Follow-ups:** owner decisions 3 and 4; the amendments above.
