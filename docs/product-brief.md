# Product Brief

> The owner's original brief, kept verbatim. Agents never rewrite it. Later product-level decisions live in `docs/adr/`, and per-phase scope lives in `docs/roadmap/`.
>
> Added by the owner together with the brief: *"I suggest Hexagonal Architecture with Adaptors, ports, use case..etc. And use SOLID pattern when create code"* (formalized in ADR-0010).

---

# PROJECT: AI Reconciliation & Investigation Agent

## Role

Act as a Staff-level Software Architect and Senior AI Engineer.

You are helping me build a production-oriented portfolio project that demonstrates advanced software engineering and AI Agent development skills.

I am an experienced Senior Software Engineer with extensive experience in backend development, Python, Ruby on Rails, PostgreSQL, AWS, distributed systems and software architecture.

Do not treat this as a beginner tutorial or generate simplistic chatbot code.

## Product vision

Build an AI-powered financial reconciliation and investigation system.

The application receives financial records from multiple independent sources:

- E-commerce orders.
- Payment gateway transactions.
- Bank statements.
- Refunds.
- Payment gateway fees.
- Internal authorization records.

Its purpose is to identify financial discrepancies, investigate their causes, retrieve supporting evidence, calculate financial impact and propose resolutions.

The system must support human approval before any consequential financial action.

## Core architecture

### Backend
- Python
- FastAPI
- PostgreSQL
- SQLAlchemy
- Alembic
- Pydantic

### Agent orchestration
- LangGraph
- Tool calling
- Conditional routing
- Persistent checkpoints
- Human-in-the-loop
- Structured agent state

### Retrieval
- Hybrid RAG
- PostgreSQL full-text search
- pgvector
- Embeddings
- Reranking
- Source attribution

### Frontend
- Next.js
- React
- TypeScript

### Observability and testing
- Langfuse
- Pytest
- LangGraph tracing
- Evaluation datasets
- Docker Compose

## Critical engineering principles

1. PostgreSQL is the source of truth.
2. Financial calculations must be deterministic.
3. Never delegate arithmetic or transaction matching to an LLM.
4. The LLM must not invent transactions, approvals or evidence.
5. Every investigation conclusion must reference supporting evidence.
6. Every consequential action requires explicit human approval.
7. All operations must handle retries and idempotency.
8. Every case must have an auditable history.
9. Agent execution must be observable.
10. The system must gracefully handle missing or contradictory information.

## Synthetic data

We will build an independent Financial Data Simulator.

It will generate reproducible synthetic datasets containing:

- Orders.
- Payments.
- Bank transactions.
- Refunds.
- Fees.
- Authorizations.
- Financial policies.

The simulator must introduce controlled anomalies and preserve ground truth for evaluation.

Never use real customer or financial data.

## Development strategy

Build the system incrementally.

Do not implement the entire application in one step.

Each phase must include:

- Architecture decisions.
- Implementation.
- Unit tests.
- Integration tests where applicable.
- Documentation.
- Acceptance criteria.
- Code review.

Do not proceed to the next phase without reporting the current phase's results.

## Your first task

Do NOT write application code yet.

First:
1. Analyze the product requirements.
2. Propose the architecture.
3. Define bounded contexts and domain entities.
4. Design the PostgreSQL schema.
5. Define the Financial Data Simulator architecture.
6. Identify technical risks.
7. Propose a phased implementation plan.
8. Identify decisions requiring my approval.

Present the architecture and wait for my approval before implementing anything.

---

## Direction of later phases (agent's initial proposal, not owner-approved)

Kept for orientation only. The owner writes each phase in `docs/roadmap/`, and those files are the only authority on scope.

| Phase | Direction | Status |
|-------|-----------|--------|
| 0 | Foundations | Written in `docs/roadmap/` |
| 1 | Financial Data Simulator | Written in `docs/roadmap/` |
| 2 | Ingestion: idempotent imports into canonical tables | Proposal only |
| 3 | Deterministic reconciliation engine + precision/recall evaluation against ground truth (no AI) | Proposal only |
| 4 | Cases + Audit + API | Proposal only |
| 5 | Knowledge / hybrid RAG with retrieval evaluation | Proposal only |
| 6 | Investigation agent: LangGraph, read-only, grounding validator, checkpoints, Langfuse | Proposal only |
| 7 | Resolution + human-in-the-loop approvals + outbox execution | Proposal only |
| 8 | Frontend (Next.js) | Proposal only |
| 9 | Agent evaluation suite + hardening | Proposal only |
