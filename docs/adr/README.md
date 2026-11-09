# Architecture Decision Records

Every significant architecture or modeling decision has its own ADR here. `docs/architecture/` describes the system **as it is**. The ADRs record **why** it is that way, including decisions that were later replaced.

## Rules

1. One decision per file: `NNNN-short-kebab-title.md`, numbered in sequence and never reused.
2. Copy [0000-template.md](0000-template.md).
3. Once an ADR is `Accepted`, its content is never edited. To change the decision, write a new ADR and set the old one to `Superseded by ADR-NNNN`. The status line is the only part you update.
4. Code, migrations and the denormalization register link to ADRs by number (`ADR-0004`).
5. Add every new ADR to the index below in the same change, with its area and a one-line decision. When an ADR is superseded, update its status in the index too.

## Statuses

| Status | Meaning |
|--------|---------|
| `Proposed` | Written, waiting for the owner's approval. Nothing that depends on it is built yet |
| `Accepted` | Approved. Implementation may rely on it |
| `Rejected` | Considered and declined. Kept for the record |
| `Superseded by ADR-NNNN` | Replaced by a later decision |

## Index

Areas: **Architecture**, **Data**, **Agent**, **Retrieval**, **Controls** (approvals, execution, audit), **Security**.

| ADR | Area | Title | Decision in one line | Status | Date |
|-----|------|-------|----------------------|--------|------|
| [0001](0001-modular-monolith.md) | Architecture | Modular monolith with one schema per bounded context | One deployable; each context is a package with its own PostgreSQL schema, integrated via `api` modules and outbox events | Accepted | 2026-11-09 |
| [0002](0002-money-as-integer-minor-units.md) | Data | Money as integer minor units, single currency in v1 | `BIGINT` minor units + currency code; `Decimal` for intermediates, rounded once with `ROUND_HALF_EVEN` | Accepted | 2026-11-09 |
| [0003](0003-typed-table-per-source-record.md) | Data | One typed table per source record type | Each source record type gets its own constrained table; raw payload kept separately as a snapshot | Accepted | 2026-11-09 |
| [0004](0004-separate-orm-models-and-mappers.md) | Architecture | Separate ORM models and mappers | SQLAlchemy models live in adapters; mappers translate to plain-Python domain aggregates | Accepted | 2026-11-09 |
| [0005](0005-llm-provider-behind-port.md) | Agent | LLM provider behind a port | `HypothesisGenerator` port returns domain objects; Claude proposed as default, scripted fake in tests | Accepted | 2026-11-09 |
| [0006](0006-embeddings-and-reranker.md) | Retrieval | Local embedding model and reranker | Local open models behind ports; concrete models and `VECTOR(N)` chosen in Phase 3 by retrieval eval | Accepted | 2026-11-09 |
| [0007](0007-approval-policy.md) | Controls | Approval policy: four-eyes above a threshold | One approver up to a configurable threshold, two distinct approvers above it; proposer never approves | Accepted | 2026-11-09 |
| [0008](0008-action-execution-model.md) | Controls | Action execution through an adjustment ledger and outbox | Execution writes an adjustment entry + outbox event in one transaction; relay calls a fake gateway, at most once | Accepted | 2026-11-09 |
| [0009](0009-frontend-authentication.md) | Security | Seeded development users with roles for frontend auth | Seeded users with roles and a signed session; backend refuses dev auth outside `local`/`test` | Accepted | 2026-11-09 |
| [0010](0010-architecture-standards.md) | Architecture | Architecture and data modeling standards | 3NF + denormalization register, pragmatic DDD, hexagonal with justified ports, SOLID without generic repositories | Accepted | 2026-11-09 |
