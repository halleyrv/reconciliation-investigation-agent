# ADR-0002: Money as integer minor units, single currency in v1

- **Status:** Accepted
- **Date:** 2026-11-09
- **Related:** docs/architecture/data-model.md (Conventions)

## Context

Financial calculations must be deterministic and exact (principle 2). Floating point cannot represent most decimal amounts exactly. Multi-currency support needs FX rates, rate sources and conversion timing, which is a domain of its own.

## Decision

- Store every amount as `amount_minor BIGINT` plus `currency CHAR(3)` referencing `ref.currencies`, whose `minor_unit` column holds the exponent.
- In the domain, `Money` is a frozen value object holding an `int` and a currency code. Operations between different currencies raise an error.
- v1 runs on a single currency. The currency column is still stored on every amount, so multi-currency needs no migration of existing rows.
- Intermediate results that produce fractions of a minor unit (for example basis-point fees) are computed with `decimal.Decimal` and rounded **once**, at the end, with a single documented rounding mode.

## Alternatives considered

| Alternative | Why not |
|-------------|---------|
| `NUMERIC(19,4)` | Exact, but invites sub-cent values to leak into stored balances. Integer minor units make "what is a valid amount" unambiguous |
| `float` | Not exact. Rejected outright |
| Multi-currency from v1 | Needs an FX context and rate snapshots. Out of scope for the core demonstration |

## Consequences

- **Positive:** Exact arithmetic, simple comparisons, the database can enforce `CHECK (amount_minor > 0)`.
- **Negative:** Every display and import must convert using the currency exponent.
- **Follow-ups:** The rounding mode is `ROUND_HALF_EVEN`, approved by the owner on 2026-11-09 through the Phase 1 amendment. In the backend it is applied by `ImpactCalculator` only. The simulator (an independent package) uses `Decimal` internally and exports amounts as decimal strings. Ingestion converts them to minor units and rejects amounts with more decimals than the currency allows. The single currency for v1 is USD.
