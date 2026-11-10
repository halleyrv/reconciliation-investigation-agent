# Reconciliation evaluation

- Run: `93ee173f-d4f2-4080-b9a9-34c40ad4b27e`, ruleset `v1`, period 2026-10-01 to 2026-10-31
- Ground truth: `simulator/samples/orders-200-seed-42/ground_truth.json`
- Result: **PASS**

## Discrepancies per type

| Type | Expected | Detected | Matched | Precision | Recall |
|------|----------|----------|---------|-----------|--------|
| `amount_mismatch` | 2 | 2 | 2 | 100.0% | 100.0% |
| `duplicate_payment` | 4 | 4 | 4 | 100.0% | 100.0% |
| `duplicate_refund` | 4 | 4 | 4 | 100.0% | 100.0% |
| `fee_mismatch` | 4 | 4 | 4 | 100.0% | 100.0% |
| `missing_in_bank` | 1 | 1 | 1 | 100.0% | 100.0% |
| `missing_in_gateway` | 2 | 2 | 2 | 100.0% | 100.0% |
| `missing_in_orders` | 2 | 2 | 2 | 100.0% | 100.0% |
| `reference_mismatch` | 4 | 4 | 4 | 100.0% | 100.0% |
| `sequence_violation` | 4 | 4 | 4 | 100.0% | 100.0% |
| `settlement_delayed` | 2 | 2 | 2 | 100.0% | 100.0% |
| `source_conflict` | 4 | 4 | 4 | 100.0% | 100.0% |
| `unauthorized_refund` | 4 | 4 | 4 | 100.0% | 100.0% |
| `underpayment` | 4 | 4 | 4 | 100.0% | 100.0% |

## Clean links

| Expected | Found | Matched | Precision | Recall |
|----------|-------|---------|-----------|--------|
| 158 | 158 | 158 | 100.0% | 100.0% |

## Delta mismatches

None.

## Missed discrepancies

None.

## Unexpected discrepancies

None.

## Missed links

None.

## Unexpected links

None.

