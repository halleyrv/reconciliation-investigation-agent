# ADR-0001: Modular monolith with one schema per bounded context

- **Status:** Accepted
- **Date:** 2026-11-09
- **Related:** ADR-0010, docs/architecture/bounded-contexts.md

## Context

The system has seven bounded contexts with clear responsibilities. It is built and operated by one engineer, runs locally with Docker Compose, and handles synthetic data volumes. The contexts need hard boundaries, but distributed operation brings no benefit at this scale.

## Decision

Build one deployable backend. Each bounded context is a Python package with its own PostgreSQL schema. Contexts communicate through published `api` modules and domain events written to a per-context outbox.

## Alternatives considered

| Alternative | Why not |
|-------------|---------|
| Microservices per context | Adds network failures, distributed transactions and deployment overhead with no scaling need to justify them |
| Layered monolith without context packages | Boundaries erode quickly. Nothing stops cross-context coupling |

## Consequences

- **Positive:** Local transactions, simple deployment, fast tests. Boundaries are explicit in code and schema.
- **Negative:** Boundaries are enforced by `import-linter` and review, not by the network. A careless import is possible until CI catches it.
- **Follow-ups:** The outbox keeps extracting a context later possible without changing producers.
