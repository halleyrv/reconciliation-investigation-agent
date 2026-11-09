# AI Reconciliation & Investigation Agent

An AI-powered financial reconciliation and investigation system. It ingests records from independent sources (orders, payment gateway transactions, bank statements, refunds, fees and authorizations), detects discrepancies with a deterministic engine, investigates them with a LangGraph agent backed by hybrid RAG, and proposes resolutions that a human must approve.

All data is synthetic, produced by an independent Financial Data Simulator. No real customer or financial data is used.

## Status

Phase 0 (foundations) is in progress. There is no runnable code yet. Setup and check commands will be added here once they have actually been run.

See the [roadmap](docs/roadmap/README.md) for every phase and its status.

## Principles

- PostgreSQL is the source of truth.
- Financial calculations and transaction matching are deterministic. The LLM never does arithmetic or matching.
- The LLM never invents transactions, approvals or evidence, and every conclusion references its evidence.
- Every consequential action requires explicit human approval.
- Every operation is idempotent and every case has an auditable history.

## Documentation

| Topic | Document |
|-------|----------|
| Product brief | [docs/product-brief.md](docs/product-brief.md) |
| Roadmap and phase specs | [docs/roadmap/](docs/roadmap/README.md) |
| Architecture | [docs/architecture/](docs/architecture/README.md) |
| Architecture decisions (ADRs) | [docs/adr/](docs/adr/README.md) |
| Phase review process | [docs/process/phase-review.md](docs/process/phase-review.md) |
| Instructions for coding agents | [AGENTS.md](AGENTS.md) |
