# PHASE 1 — Financial Data Simulator

Implement the Financial Data Simulator.

Requirements:

1. Generate synthetic e-commerce orders.
2. Generate payment gateway transactions.
3. Generate bank statement records.
4. Generate refunds.
5. Generate gateway fees.
6. Generate internal authorization records.
7. Generate financial policy documents.

Implement controlled anomaly generators:

- Duplicate payments.
- Unauthorized refunds.
- Incorrect fees.
- Missing transactions.
- Partial payments.
- Delayed settlements.
- Incorrect amounts.
- Inconsistent transaction references.
- Out-of-order events.
- Duplicate refunds.

Critical requirements:

- Use Faker where appropriate.
- Use Decimal for all monetary values.
- Support deterministic generation using random seeds.
- Preserve ground truth for every injected anomaly.
- Generate CSV and JSON exports.
- Make the simulator independent of the AI agent.
- Include data validation and tests.

Start with a small dataset of 200 orders and expand to 2,000 after validation.

Deliver:
- Source code.
- Data schemas.
- Sample datasets.
- Ground truth.
- Test suite.
- Documentation.

Do not implement LangGraph yet.

Before finishing, demonstrate that the generated records are internally consistent and that every injected anomaly can be identified from ground truth.

---

## Amendments

Changes approved by the owner after the original text above. The original is never edited.

| Date | Change | Approved by |
|------|--------|-------------|
| 2026-11-09 | Add anomaly 11: **Conflicting re-sent records**. A source sends the same record (same external ID) again with different data. Exercises the requirement to handle contradictory information (`ingestion.source_conflicts`). | Owner |
| 2026-11-09 | Clarification: **Missing transactions** carries a direction in the ground truth (missing in bank, missing in gateway, missing in orders), so a bank credit with no payment or order behind it is covered without a new anomaly type. | Agent default, not objected by owner |
| 2026-11-09 | Clarification: **Partial payments** means the customer paid less than the order total. Incomplete gateway settlements are covered by *Delayed settlements*. | Agent default, not objected by owner |
| 2026-11-09 | Clarification: monetary values are `Decimal` inside the simulator and are exported as decimal strings (for example `"123.45"`), never as JSON floats. Conversion to integer minor units happens at ingestion (ADR-0002). | Agent default, not objected by owner |
| 2026-11-09 | Add assumptions, interface, anomaly configuration, ground truth contract, consistency invariants and measurable acceptance criteria (section below). Approves `ROUND_HALF_EVEN` as the rounding mode for fees. | Owner |
| 2026-11-09 | **Settlement report** (ADR-0011): the gateway settlement report is a source record type (`settlements`, one per gateway and capture day, with its declared net). It is exported like every record type and is one of three independent views of a batch, with the movements and the bank credit. | Owner |
| 2026-11-09 | **Invariant I10** (ADR-0012): "Every order has exactly one payment". I1 keeps its original wording. Scope: v1 has exactly one payment per order; split payments are out of scope. Duplicate payments break I10. | Owner |
| 2026-11-09 | **2,000-order run period** (ADR-0015 point 4): the 2,000-order dataset is the same merchant with more history, over ten months (2026-01-01 to 2026-10-31), not a bigger merchant. AS2's one-month default stays for the 200-order run. | Owner |
| 2026-11-09 | **Business days** (ADR-0014): Monday to Friday minus a fictional, configurable holiday calendar. The default config lists 2 or 3 fictional holidays inside its period; the settlement policy lists them and I9 covers them. Money and date serialization stay as approved above. | Owner |

### Amendment 2026-11-09: assumptions and acceptance criteria

#### Assumptions

| ID | Assumption |
|----|-----------|
| AS1 | Single currency: USD, 2 decimal places |
| AS2 | Period: one calendar month (configurable). All timestamps in UTC |
| AS3 | One merchant, one bank account |
| AS4 | Two fictional payment gateways (`gateway_a`, `gateway_b`). No real brand names |
| AS5 | Fees per gateway: percentage (basis points) + fixed amount per payment. Fees are not returned on refunds |
| AS6 | Settlement: one daily batch per gateway, paid T+2 business days, net of refunds and fees. One bank credit per batch |
| AS7 | Baseline: one full payment per order; ~8% of orders get a full or partial refund; every refund has an internal authorization |
| AS8 | Each source has its own ID format (`ORD-…`, `PAY-…`, `RFD-…`, `BNK-…`). Bank descriptions are free text that mention the batch reference |
| AS9 | Customer data comes from Faker, seeded from the run seed. No real data |
| AS10 | Policy documents are Markdown: fee schedule per gateway, refund authorization policy, settlement and cut-off policy. Their numbers are generated from the same config as the data |

#### Interface

- CLI: `simulate --config <file.yaml> --seed <int> --out <dir>`. The config holds order count, period and anomaly rates.
- Output: one CSV and one JSON file per record type, `policies/*.md`, `ground_truth.json` and `manifest.json` (simulator version, seed, config hash, SHA-256 of every file).
- Data schemas: one JSON Schema (draft 2020-12) per record type and for the ground truth, each with a `schema_version`. CSV columns match the schema.
- Monetary values are exported as decimal strings (`"123.45"`).

#### Anomaly configuration

- The rate of each anomaly type is configurable. With the defaults, about 15% of orders are affected.
- In v1 each affected record belongs to exactly one anomaly (no overlapping anomalies).
- Which records get an anomaly is decided deterministically from the seed.

#### Ground truth contract

Each anomaly entry has: `anomaly_id`, `type`, `subtype` (for example the direction of a missing transaction), the affected records as `{source, external_id}`, `expected_delta` (signed decimal string), `currency`, a short `description` and the `injector` that produced it.
The ground truth also lists the expected links for clean records (order ↔ payment ↔ settlement batch ↔ bank credit), so later phases can measure matching precision and recall.

#### Internal consistency invariants

Without anomalies, every generated dataset satisfies:

| ID | Invariant |
|----|-----------|
| I1 | Every payment references an existing order, and its amount equals the order total |
| I2 | Every refund references an existing payment, and the refunds of one payment never exceed its amount |
| I3 | Every refund has an authorization that covers its amount and was approved before the refund |
| I4 | Every fee equals its gateway's schedule applied to the payment, rounded once to cents (`ROUND_HALF_EVEN`, ADR-0002) |
| I5 | For each settlement batch: net = payments − refunds − fees, with exactly one bank credit of that amount, dated batch date + 2 business days |
| I6 | Time order: order ≤ payment ≤ settlement ≤ bank value date, and refund after payment |
| I7 | External IDs are unique per source |
| I8 | Every monetary value is positive with exactly 2 decimals |
| I9 | The numbers in the policy documents equal the config used to generate the data |

Each anomaly type declares which invariants it breaks, and it must break those and no others.

#### Acceptance criteria

| ID | Criterion |
|----|-----------|
| AC1 | Determinism: two runs with the same seed and config produce byte-identical files (same SHA-256 in the manifest). A different seed produces different data |
| AC2 | A run with anomalies disabled has zero invariant violations |
| AC3 | A run with anomalies: every invariant violation is explained by exactly one ground-truth anomaly, and every ground-truth anomaly causes at least one violation (100% in both directions) |
| AC4 | Every one of the 11 anomaly types appears at least twice in the 200-order dataset |
| AC5 | CSV and JSON hold the same records, and both validate against the JSON Schemas |
| AC6 | The simulator imports nothing from the backend and has no LangGraph or LLM dependency |
| AC7 | No `float` in any monetary path. JSON amounts are strings |
| AC8 | Scale gate: the 2,000-order run happens only after AC1–AC7 pass at 200 orders. Then AC1–AC7 are checked again at 2,000, and the runtime is recorded |
| AC9 | The 200-order sample dataset (seed 42) is committed. The 2,000-order dataset is reproducible with a documented command |
| AC10 | Simulator README: how to run it, config reference, anomaly catalog with the invariants each type breaks, and the ground truth contract |
