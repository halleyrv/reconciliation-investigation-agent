# Financial Data Simulator

Generates reproducible synthetic financial datasets for one merchant: e-commerce orders, payment gateway captures, gateway fees, refunds, internal refund authorizations, gateway settlement batches and bank statement credits. It injects controlled anomalies and records each one in a ground truth file, so later phases can measure what they detect.

The simulator is independent of the rest of the system. It imports nothing from the backend and has no LangGraph or LLM dependency (enforced by `lint-imports` and by a test on its declared dependencies). Its only contract is the files it writes.

## Run it

From the repository root, after `uv sync --locked`:

```bash
# 200-order dataset (the committed sample)
uv run --locked simulate --config simulator/configs/default.yaml --seed 42 --out simulator/samples/orders-200-seed-42

# 2,000-order dataset (not committed; reproducible with this command)
uv run --locked simulate --config simulator/configs/orders-2000.yaml --seed 42 --out <dir>

# Check a run: schemas, CSV == JSON, manifest hashes, invariants, ground-truth coverage
uv run --locked simulate-verify <dir>
```

`simulate` exits with 2 on an invalid config. `simulate-verify` exits with 1 and lists every problem when a run does not verify.

Same seed and config produce byte-identical files (same SHA-256 in the manifest). A different seed produces different data.

## Output

| File | Content |
|------|---------|
| `<type>.csv`, `<type>.json` | One pair per record type: `orders`, `payments`, `fees`, `refunds`, `authorizations`, `settlements`, `bank_transactions`. Both hold the same records |
| `policies/*.md` | Fee schedule, refund authorization policy, settlement and cut-off policy. Their numbers come from the config |
| `ground_truth.json` | Injected anomalies and expected links for clean records |
| `manifest.json` | Simulator version, seed, resolved config, its SHA-256, and the SHA-256 of every other file |

Every field is a string. Money is a decimal string with exactly two places (`"123.45"`), never a JSON number; timestamps are UTC (`2026-10-03T14:22:05Z`); dates are ISO (`2026-10-07`). The JSON file wraps its records: `{"schema_version": "1.0.0", "record_type": "orders", "records": [...]}`.

## Data schemas

One JSON Schema (draft 2020-12) per record type and one for the ground truth, in [`src/simulator/schemas/`](src/simulator/schemas/). Each record schema defines the file and, under `$defs/record`, one row; CSV columns follow the order of its properties. CSV files are UTF-8 without a byte-order mark, comma-delimited, with LF line endings (including after the last row), one header row and RFC 4180 quoting only when a value holds a comma, a quote or a line break; every value is the same string as in the JSON file (ADR-0014). `simulate-verify` checks the encoding and line endings.

| Record type | ID | Links it claims |
|-------------|----|-----------------|
| `orders` | `ORD-000001` | none |
| `payments` | `PAY-000001` | `order_ref` (a claim by the gateway, not a verified link), `settlement_ref` |
| `fees` | `FEE-000001` | `payment_ref`, `settlement_ref` |
| `refunds` | `RFD-000001` | `payment_ref`, `settlement_ref` |
| `authorizations` | `AUT-000001` | `subject_ref` (the refund it approves) |
| `settlements` | `STL-000001` | none; one batch per gateway and capture day |
| `bank_transactions` | `BNK-` + 10 hex digits | the settlement ID inside the free-text `description` |

## How a clean dataset is built

- Orders are spread over the period, totals between 10.00 and 500.00 USD. Customer names and emails come from Faker, seeded from the run seed.
- Each order has one gateway payment for its full total, captured 30 s to 1 h after the order, and one processing fee: `amount × bps / 10000 + fixed`, rounded once to cents with `ROUND_HALF_EVEN`.
- `refund_rate` of the orders get a full or partial refund 1 to 5 days after the payment, each with an authorization approved 5 to 240 minutes before it.
- Each gateway settles one batch per capture day. A batch nets its payments minus their fees minus the refunds it absorbs (a refund goes to the first batch of its gateway on or after its date that stays positive; if none exists late in the period, the refund and its authorization are moved earlier, to the first batch since the payment that can absorb it). Fees are not returned on refunds.
- Each batch is paid as one bank credit, dated the batch date plus `settlement_lag_business_days`. Business days are Monday to Friday minus the configured `holidays` (ADR-0014); the settlement policy lists them.

## Configuration

| Key | Meaning |
|-----|---------|
| `orders` | Number of orders, integer ≥ 1 |
| `period.start`, `period.end` | Inclusive dates of the period, UTC |
| `currency` | ISO code; v1 uses `USD` |
| `gateways.<name>.percentage_bps` | Percentage fee in basis points, integer |
| `gateways.<name>.fixed_fee` | Fixed fee per payment, quoted decimal string |
| `settlement_lag_business_days` | Business days from batch date to bank value date |
| `holidays` | Fictional bank holidays, ISO dates (`"2026-10-09"`); optional, default none. Payouts skip them like weekends |
| `refund_rate` | Fraction of orders with a normal (authorized) refund, quoted decimal string |
| `anomaly_rates.<type>` | Rate per anomaly type, quoted decimal string; omitted types are `0` |

Money and rates must be quoted strings: a YAML float such as `0.30` is rejected, because it is already inexact when parsed. Unknown anomaly types are rejected.

An anomaly rate is a fraction of its target population: settlement batches for `delayed_settlement`, `incorrect_amount` and the `missing_in_bank` direction, orders for everything else. `missing_transaction` applies its rate to each of its three directions. The count is `rate × population`, rounded half-even. With the default config every anomaly type appears at least twice. On seed 42, 7.0% of the orders are named directly by an anomaly at both 200 and 2,000 orders; the share without a clean expected link is 13.0% at 200 and 20.1% at 2,000, because each anomalous batch holds more orders at scale. The choice of denominators is proposed in ADR-0015.

## Internal consistency invariants

A run with every anomaly rate at 0 satisfies all of them (checked by `simulate-verify`).

| ID | Invariant |
|----|-----------|
| I1 | Every payment references an existing order, and its amount equals the order total |
| I2 | Every refund references an existing payment, and the refunds of one payment never exceed its amount |
| I3 | Every refund has an authorization that covers its amount and was approved before the refund |
| I4 | Every payment has exactly one fee, equal to its gateway's schedule rounded once to cents |
| I5 | Every batch nets its members, has exactly one bank credit of that amount dated batch date + lag, and every payout names an existing batch |
| I6 | Order ≤ payment ≤ settlement batch ≤ bank value date, and every refund is after its payment |
| I7 | External IDs are unique per source |
| I8 | Every monetary value is positive with exactly 2 decimals |
| I9 | The numbers and bank holidays in the policy documents equal the config |
| I10 | Every order has exactly one payment (v1 scope: split payments are out of scope, ADR-0012) |

## Anomaly catalog

Each anomaly owns its records: no record belongs to two anomalies, and no payment, fee or refund of an anomaly sits inside a batch picked by a settlement-level anomaly (those batches are reserved before any other anomaly is injected). Each type breaks exactly the invariants listed, and no others.

| Type | Subtype | What is injected | Breaks | `expected_delta` |
|------|---------|------------------|--------|------------------|
| `duplicate_payment` | | A second gateway capture of the same order and amount | I10 | + payment amount |
| `unauthorized_refund` | | A refund with no authorization | I3 | − refund amount |
| `incorrect_fee` | | A fee 0.05 to 2.00 above the schedule | I4 | + overcharge (fee charged minus fee due) |
| `missing_transaction` | `missing_in_orders` | A gateway payment for an order the shop never sent | I1 | + payment amount |
| `missing_transaction` | `missing_in_bank` | A settlement batch with no bank credit | I5 | − batch net |
| `missing_transaction` | `missing_in_gateway` | A bank credit naming a batch the gateway never reported | I5 | + credit amount |
| `partial_payment` | | The customer paid 50% to 95% of the order total | I1 | paid − total |
| `delayed_settlement` | | The bank credit arrives 1 to 3 business days late | I5 | 0.00 |
| `incorrect_amount` | | The bank credit differs from the batch net | I5 | credit − net |
| `inconsistent_reference` | | The payment's `order_ref` is a variant of the real ID (`ORD000123`, `ord-000123`, `ORD_000123`) | I1, I10 | 0.00 |
| `out_of_order_event` | `payment_before_order` | The order is timestamped after its payment | I6 | 0.00 |
| `duplicate_refund` | | An authorized refund (60% to 100% of the payment) issued twice; the copy has no authorization | I2, I3 | − refund amount |
| `conflicting_resent_record` | `orders` | The shop re-sends an order with the same ID and a different customer email | I7 | 0.00 |

## Ground truth contract

`ground_truth.json` (schema `ground_truth.schema.json`, version `1.0.0`):

- `seed`: the run seed.
- `anomalies[]`: `anomaly_id` (`ANM-0001`), `type`, `subtype` (empty when the type has one form), `records` (the affected records as `{source, external_id}`, where `source` is a record type), `expected_delta` (signed decimal string: actual minus expected), `currency`, `description`, `injector`, and `invariants_broken`.
- `expected_links[]`: `order_id`, `payment_id`, `settlement_id`, `bank_transaction_id` for every order whose chain no anomaly touches. Normal refunds do not remove an order from this list.

An invariant violation is explained by an anomaly when they share at least one record. `simulate-verify` passes only when every violation is explained by exactly one anomaly that declares that invariant, and every anomaly breaks exactly the invariants it declares.
