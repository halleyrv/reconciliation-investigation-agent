# ADR-0003: One typed table per source record type

- **Status:** Accepted
- **Date:** 2026-11-09
- **Related:** ADR-0010, docs/architecture/data-model.md (`ingestion`)

## Context

Orders, payments, refunds, fees, bank transactions and authorizations have different attributes and different rules. Reconciliation queries them heavily, and integrity constraints differ per type.

## Decision

Each source record type has its own table in the `ingestion` schema, with typed columns and constraints. The original payload is kept separately in `raw_records` as an immutable snapshot.

## Alternatives considered

| Alternative | Why not |
|-------------|---------|
| One `financial_records` table with a type discriminator and JSONB attributes | Violates the normalization standard (ADR-0010): attributes would live in JSONB, without NOT NULL, CHECK or FK constraints |
| One wide table with nullable columns per type | Many columns that apply to only one type, plus CHECKs that are hard to read |

## Consequences

- **Positive:** Real constraints per type. Clear queries. Matching rules work with typed rows.
- **Negative:** Polymorphic references to "any record" need one FK column per type with `num_nonnulls(...) = 1`.
- **Follow-ups:** Accepted as a direct consequence of ADR-0010.
