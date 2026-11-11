# Project Structure

A modular monolith: one Python package per bounded context, each split into `domain`, `application` and `adapters`. The composition root in `bootstrap` is the only place that knows concrete classes.

## Layout

```
backend/
  src/recon/
    shared_kernel/              Money, typed IDs, Clock and IdGenerator ports, UnitOfWork port, DomainEvent base
    ingestion/
      domain/                   ImportBatch, SourceRecord types, invariants, events. Stdlib only
      application/              use cases (commands, queries), ports used by them
      adapters/
        inbound/                FastAPI routers, CLI
        outbound/               SQLAlchemy ORM models, mappers, repositories, file parsers
      api.py                    published interface other contexts may import
    reconciliation/             same shape
    investigation/
      ...
      adapters/inbound/agent/   LangGraph graph, nodes, tools (thin: each calls a use case)
      adapters/outbound/llm/    LLM provider adapters
    knowledge/                  same shape (+ embeddings, reranker adapters)
    resolution/                 same shape
    audit/                      same shape
    bootstrap/                  composition root, settings, FastAPI app factory, DI wiring
  tests/
    unit/<context>/             domain + application with in-memory fakes. No DB, no network
    integration/<context>/      adapters against real PostgreSQL
    contract/                   import-linter config, event schema snapshots
  migrations/                   Alembic, one revision chain, schema-qualified tables
simulator/                      independent package. Imports nothing from backend
evaluation/                     offline: reads simulator ground truth + read models
frontend/                       Next.js
docs/architecture/              these documents
```

## Layer rules

| Layer | May import | Must not import |
|-------|-----------|-----------------|
| `domain` | stdlib, `shared_kernel.domain` | Anything else, including Pydantic, SQLAlchemy, LangGraph |
| `application` | its own `domain`, `shared_kernel`, other contexts' `api` | adapters of any context, frameworks |
| `adapters` | its own `application` and `domain`, frameworks and SDKs | other contexts' internals |
| `api.py` | its own `application` | adapters |
| `bootstrap` | everything | — |

`import-linter` (layers and independence contracts) enforces these rules in CI from Phase 0 on. A violation fails the build.

Consequences that are easy to miss:

- **Pydantic stays at the edge.** Request/response schemas live in inbound adapters. LLM structured-output schemas live in the agent adapter, which maps them to domain objects. Domain objects are frozen `dataclasses`.
- **SQLAlchemy stays in outbound adapters.** ORM models are separate classes. Mappers translate them to and from domain aggregates (ADR-0004).
- **LangGraph is an inbound adapter.** Its state holds IDs and validated domain DTOs, not ORM objects. Nodes contain no business rules; they call use cases. Swapping the orchestrator touches only `adapters/inbound/agent/`.

## Port inventory

A port exists only with a named reason. If a row cannot fill the "reason" column, the port is not created.

| Port | Owner | Reason | Implementations |
|------|-------|--------|-----------------|
| `UnitOfWork` | shared_kernel | Transaction boundary + outbox write; test seam | SQLAlchemy, in-memory fake |
| `Clock` | shared_kernel | Deterministic time in tests and simulator | system, fixed |
| `IdGenerator` | shared_kernel | Deterministic IDs in tests | uuid, sequence fake |
| `<Aggregate>Repository` (one per aggregate) | each context | Persistence; test seam | SQLAlchemy, in-memory fake |
| `SourceRecordReader` | reconciliation | The engine's input is Ingestion's data, read without importing Ingestion; test seam for runs | read-only SQL over `ingestion.*`, in-memory snapshot |
| `ReferenceDataRepository` | reconciliation | Fee schedules and holidays loaded by an operator (OD1); test seam | SQLAlchemy, in-memory fake |
| `ResultRepository` | reconciliation | Writes a run's `MatchGroup`s and `Discrepancy`s, which are aggregates the run does not contain; test seam | SQLAlchemy, in-memory fake |
| `RunOutputReader` | reconciliation | The evaluation use case scores a completed run's output against a known answer; test seam (not a cross-context read model) | SQL query, in-memory fake |
| `RunQueries` | reconciliation | The API reads run summaries and filtered, keyset-paginated discrepancies as views, not aggregates, without SQL in the HTTP adapter | SQL queries (tested through the API against PostgreSQL) |
| `CaseQueries` | investigation | The API reads case pages, case detail (discrepancy and records) and the audit history as views, without SQL in the HTTP adapter | SQL queries over `investigation`, `recon` and `audit` (tested through the API against PostgreSQL) |
| `HypothesisGenerator` | investigation | External LLM; test seam with scripted outputs | LLM adapter, scripted fake |
| `EmbeddingProvider` | knowledge | External model; swappable (ADR-0006) | provider adapter, hash-based fake |
| `Reranker` | knowledge | External model; swappable (ADR-0006) | provider adapter, identity fake |
| `ActionExecutor` | resolution | External side effect (fake gateway) | fake gateway adapter, recording fake |

**Not ports, on purpose:**

- FastAPI, Pydantic, LangGraph: inbound adapters drive the application. The application never calls them.
- Langfuse / tracing: a cross-cutting concern attached in adapters and bootstrap. The domain never traces.
- Read-model queries: plain query functions in the outbound adapter, exposed through `api.py`. They are not repositories because they return DTOs, not aggregates.

## Repository shape

One repository per aggregate. Methods carry business names. No generic `Repository[T]`, no `filter(**kwargs)`.

```python
class CaseRepository(Protocol):
    def get(self, case_id: CaseId) -> Case: ...
    def get_by_discrepancy(self, discrepancy_id: DiscrepancyId) -> Case | None: ...
    def add(self, case: Case) -> None: ...
    def save(self, case: Case) -> None: ...  # raises ConcurrencyConflict on version mismatch
```

## SOLID, applied

| Principle | How it shows up | What we avoid |
|-----------|-----------------|---------------|
| SRP | One use case per class/function (`OpenCase`, `RecordFinding`). Aggregates own their invariants | "Service" classes with ten unrelated methods |
| OCP | Matching rules and simulator anomaly injectors are strategies registered in a list. Adding one adds a class, nothing else changes | `if/elif` chains on rule type spread across modules |
| LSP | Fakes satisfy the same `Protocol` and pass the same contract tests as real adapters | Fakes that silently skip behavior, such as version checks |
| ISP | Small, aggregate-specific ports | One `Database` port with every method |
| DIP | Use cases depend on ports. `bootstrap` wires concretes | Use cases constructing adapters |

**Composition over inheritance:** inheritance is allowed only for `Protocol` ports, exception hierarchies and the `DomainEvent` base. Shared behavior is composed (a `MatchingEngine` holds a list of `MatchRule` objects) rather than inherited from a base class.

## Testing pyramid by layer

| Layer | Test type | Uses |
|-------|-----------|------|
| domain | unit | nothing but domain objects |
| application | unit | in-memory fakes of ports |
| adapters/outbound | integration | real PostgreSQL (Docker Compose) |
| adapters/inbound | integration | FastAPI test client / LangGraph with scripted LLM fake |
| fakes vs real | contract | the same test suite run against both implementations |
