# Reconciliation evaluation

- Run: `b474990b-df14-4412-83b9-483137f5a0d8`, ruleset `v1`, period 2026-01-01 to 2026-10-31
- Ground truth: `ground_truth.json` of `uv run --locked simulate --config simulator/configs/orders-2000.yaml --seed 20261110 --out <dir>` (held-out seed, first used for this report; the export is not committed, the seed and config reproduce it byte for byte)
- Result: **PASS**

## Discrepancies per type

| Type | Expected | Detected | Matched | Precision | Recall |
|------|----------|----------|---------|-----------|--------|
| `amount_mismatch` | 23 | 23 | 23 | 100.0% | 100.0% |
| `duplicate_payment` | 40 | 40 | 40 | 100.0% | 100.0% |
| `duplicate_refund` | 40 | 40 | 40 | 100.0% | 100.0% |
| `fee_mismatch` | 40 | 40 | 40 | 100.0% | 100.0% |
| `missing_in_bank` | 6 | 6 | 6 | 100.0% | 100.0% |
| `missing_in_gateway` | 20 | 20 | 20 | 100.0% | 100.0% |
| `missing_in_orders` | 20 | 20 | 20 | 100.0% | 100.0% |
| `reference_mismatch` | 40 | 40 | 40 | 100.0% | 100.0% |
| `sequence_violation` | 40 | 40 | 40 | 100.0% | 100.0% |
| `settlement_delayed` | 23 | 23 | 23 | 100.0% | 100.0% |
| `source_conflict` | 40 | 40 | 40 | 100.0% | 100.0% |
| `unauthorized_refund` | 40 | 40 | 40 | 100.0% | 100.0% |
| `underpayment` | 40 | 40 | 40 | 100.0% | 100.0% |

## Clean links

| Expected | Found | Matched | Precision | Recall |
|----------|-------|---------|-----------|--------|
| 1491 | 1491 | 1491 | 100.0% | 100.0% |

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

