# ADR-0010: Architecture and data modeling standards

- **Status:** Accepted
- **Date:** 2026-11-09
- **Related:** docs/architecture/README.md, ADR-0003, ADR-0004

## Context

This is a production-oriented portfolio project. Its code and schema need to show deliberate engineering, not just working features. Without written standards, boundaries and data quality erode as phases are added.

## Decision

The project adopts four standards. Their enforceable rules are listed in `docs/architecture/README.md`.

1. **Normalization:** 3NF minimum. Every denormalization is justified and documented in the register in `data-model.md`. JSONB only for snapshots, event payloads and transport messages. Operational data, snapshots and read models are kept separate.
2. **Pragmatic DDD:** explicit bounded contexts and context map. Small aggregates that own their invariants. Domain services and events only where they add value.
3. **Hexagonal architecture:** `domain`, `application` and `adapters` separated. Ports only with a real decoupling or testing need. LangGraph and SQLAlchemy stay out of the domain.
4. **SOLID without speculative abstraction:** composition over inheritance, and no generic repositories.

## Alternatives considered

| Alternative | Why not |
|-------------|---------|
| Layered architecture with ORM entities as the domain | Faster at first, but couples business rules to persistence and orchestration frameworks |
| Ports for every dependency | Ceremony without benefit. Abstractions with one implementation and no test need |

## Consequences

- **Positive:** Clear boundaries, testable domain, a schema that protects its own integrity.
- **Negative:** More code (mappers, explicit ports) and stricter reviews.
- **Follow-ups:** ADR-0003 and ADR-0004 follow directly from these standards. `import-linter` contracts are set up in Phase 0.
