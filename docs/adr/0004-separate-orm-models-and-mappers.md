# ADR-0004: Separate ORM models and mappers

- **Status:** Accepted
- **Date:** 2026-11-09
- **Related:** ADR-0010, docs/architecture/project-structure.md

## Context

The standards (ADR-0010) require the domain to stay independent of SQLAlchemy. Domain aggregates are frozen dataclasses with invariants enforced in their methods.

## Decision

SQLAlchemy ORM models live in each context's `adapters/outbound` package as separate classes. Explicit mapper functions translate between ORM models and domain aggregates. Repositories return domain aggregates, never ORM objects.

## Alternatives considered

| Alternative | Why not |
|-------------|---------|
| SQLAlchemy imperative mapping onto domain classes | Less code, but SQLAlchemy instruments the domain classes at runtime (attribute tracking, lazy loading). The domain stops being plain Python in practice |
| ORM models used as domain entities | Couples the domain directly to the ORM. Rejected by ADR-0010 |

## Consequences

- **Positive:** The domain is testable with no database and no ORM import. Schema changes are absorbed in mappers.
- **Negative:** More code: one ORM model and one mapper per aggregate. Mappers need tests.
- **Follow-ups:** Contract tests run the same repository suite against the SQLAlchemy and in-memory implementations.
