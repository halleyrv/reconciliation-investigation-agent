# Architecture Standards

This project follows four standards: a **normalized relational model (3NF minimum)**, **pragmatic DDD**, **hexagonal architecture**, and **SOLID without speculative abstraction**. This folder explains how each standard shows up in the code layout, in the PostgreSQL schema, and in the bounded contexts. Read it before you change a schema, add a port, or create a new module.

## Quick path

1. [bounded-contexts.md](bounded-contexts.md): what each context owns, how contexts talk to each other, and where each aggregate enforces its invariants.
2. [data-model.md](data-model.md): the relational model, the data categories, and the **denormalization register**.
3. [project-structure.md](project-structure.md): folder layout, layer rules, the port inventory, and SOLID conventions.

## The standards as enforceable rules

| # | Standard | Rule | Enforced by |
|---|----------|------|-------------|
| 1 | Normalization | 3NF by default. Every denormalization has an entry in the register with its reason and consistency strategy | Schema review + `data-model.md` register |
| 1 | Normalization | PK, FK, UNIQUE, CHECK, NOT NULL wherever the domain allows | Alembic migrations, integration tests on constraints |
| 1 | Normalization | JSONB only for immutable snapshots, event payloads and transport messages. Never for queryable business attributes | Schema review |
| 1 | Normalization | Operational data, snapshots and read models are separate (see `data-model.md`) | Schema naming (`read` schema), tests |
| 2 | DDD | One PostgreSQL schema per bounded context. A context writes only to its own schema | Repository adapters live inside their context; review |
| 2 | DDD | Invariants live in aggregate methods, never in use cases or adapters | Domain unit tests |
| 2 | DDD | Aggregates reference each other by ID only | Review; domain has no ORM relationships |
| 3 | Hexagonal | `domain` imports nothing outside the stdlib and `shared_kernel` | `import-linter` contracts in CI |
| 3 | Hexagonal | LangGraph, SQLAlchemy, FastAPI, Pydantic and LLM SDKs appear only in `adapters` | `import-linter` contracts in CI |
| 3 | Hexagonal | A port exists only when it has a second implementation or a test seam, and it is listed in the port inventory | Port inventory in `project-structure.md` |
| 4 | SOLID | No generic `Repository[T]`. Repositories expose business-named operations per aggregate | Review |
| 4 | SOLID | Composition over inheritance. Inheritance only for `Protocol` ports and exception hierarchies | Review |

## Decisions

This folder describes the system as it is. Why it is that way is recorded in the [Architecture Decision Records](../adr/README.md). These standards are ADR-0010.

## Checklist for any change

- [ ] The change writes only to the schema of the context that owns the data.
- [ ] Any new redundant column or JSONB attribute has a register entry.
- [ ] Any new invariant has a domain unit test on the aggregate.
- [ ] Any new port appears in the port inventory with its justification.
- [ ] Any decision with real alternatives has an ADR in `docs/adr/`, listed in its index.
- [ ] `import-linter` passes.
