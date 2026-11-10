# Bounded Contexts

Seven contexts, each owning one PostgreSQL schema and one Python package. Contexts share only the `shared_kernel` (Money, IDs, Clock) and each other's published `api` module. Nothing else crosses a boundary.

## Context catalog

| Context | Owns (schema) | Responsibility | Does NOT do |
|---------|---------------|----------------|-------------|
| **Ingestion** | `ingestion` | Idempotent import of source files, parsing, canonical source records, lineage, conflicting re-sends | Link records across sources |
| **Reconciliation** | `recon` | Deterministic matching rules, fee schedules, match groups, discrepancy detection | Explain causes, open cases |
| **Investigation** | `investigation` | Cases, agent runs, evidence, findings, grounding validation | Calculate money, execute actions |
| **Knowledge** | `knowledge` | Policy and document corpus, chunking, embeddings, hybrid retrieval | Decide anything |
| **Resolution** | `resolution` | Proposed actions, approvals, execution, adjustment ledger, outbox | Investigate |
| **Audit** | `audit` | Append-only history of every domain event, with actor | Business decisions |
| **Evaluation** | none (offline) | Compare system output with simulator ground truth | Run in production paths |

Two more pieces sit outside the contexts:

- **`ref` schema (shared kernel):** reference data with attributes: currencies, source kinds, fee types, discrepancy types.
- **Simulator:** an independent package. Its only contract is files.

## Context map

```
Simulator ──files (Published Language)──▶ Ingestion
                                              │ canonical records (Published Language, read-only)
                                              ▼
                                        Reconciliation
                                              │ DiscrepancyDetected (event)
                                              ▼
Knowledge ◀──retrieve() (Open Host)── Investigation ──ProposeAction (command)──▶ Resolution
                                              ▲                                      │
                                              └──── ActionApproved / ActionRejected ─┘
                                                     ActionExecuted (events)

Audit ◀── every domain event (Conformist)
Evaluation ◀── ground truth files + read models (Conformist, offline)
```

| Upstream → Downstream | Pattern | Contract |
|-----------------------|---------|----------|
| Simulator → Ingestion | Published Language | Versioned file formats (CSV/JSON) + `manifest.json`. Ingestion never imports simulator code |
| Ingestion → Reconciliation | Published Language (Customer/Supplier) | Canonical record tables are read-only for Reconciliation. Cross-schema FKs point only upstream, to never-deleted rows (see `data-model.md` conventions) |
| Reconciliation → Investigation | Domain event + Anti-Corruption Layer | `DiscrepancyDetected{discrepancy_id, type, delta, currency}`. Investigation translates it into a `Case` |
| Investigation → Knowledge | Open Host Service | `knowledge.api.retrieve(query, filters) -> list[RetrievedChunk]` with chunk IDs and scores |
| Investigation → Reconciliation / Ingestion | Open Host Service (queries) | Read-only queries through each context's `api` module. The agent's tools wrap these |
| Investigation → Resolution | Command | `resolution.api.propose_action(case_id, action, idempotency_key)` |
| Resolution → Investigation | Domain events | `ActionApproved`, `ActionRejected`, `ActionExecuted` update the case |
| All → Audit | Conformist | Every domain event is written to the outbox in the same transaction. The audit consumer appends it |

**Integration rules**

1. A context writes only to its own schema.
2. A context imports only `shared_kernel` and other contexts' `api` modules, never their `domain`, `application` or `adapters`.
3. Domain events are stored in the emitting context's own `<schema>.outbox` table, in the same transaction as the state change. v1 dispatches them in-process. The outbox lets this move to a broker later without changing producers.

## Aggregates and invariants

Small aggregates, referenced by ID. A large collection never lives inside an aggregate. For example, a `ReconciliationRun` does **not** contain its match groups.

| Context | Aggregate (root) | Invariants it owns |
|---------|------------------|--------------------|
| Ingestion | `ImportBatch` | Status moves `pending → processing → completed / failed` only. A file hash is imported once per source. A completed batch is immutable |
| Ingestion | `SourceRecord` (Order, Payment, Refund, Fee, BankTransaction, Authorization) | Immutable once created. Amount is positive `Money` with the record's own currency. A re-send with a different payload never overwrites; it raises `SourceConflictDetected` |
| Reconciliation | `ReconciliationRun` | One live (running or completed) run per `(period, ruleset_version)` idempotency key, and live runs of one ruleset never share a day (ADR-0016); a failed run stays for the record and a new run may retry. Status moves `running → completed / failed` only |
| Reconciliation | `MatchGroup` | Members balance within the rule's tolerance (v1 `settlement_batch`: payments − refunds − fees = declared net = payout, tolerance zero). Members share one currency. A record belongs to at most one group per run |
| Reconciliation | `Discrepancy` | `delta = actual − expected`. Fingerprint is deterministic over type, involved records and period |
| Reconciliation | `FeeSchedule` | Validity periods of the same `(gateway, fee_type)` never overlap |
| Investigation | `Case` | State machine `open → investigating → awaiting_approval → resolved / escalated`. Optimistic version check on every change |
| Investigation | `Finding` | Has at least one evidence link. Every amount it states equals a `calculation` evidence value |
| Investigation | `AgentRun` | Ends exactly once. Records model, prompt version and trace ID |
| Knowledge | `Document` (with its chunks) | Chunk ordinals contiguous. One embedding model per document version. Content hash unique |
| Resolution | `ProposedAction` (with its approvals) | Cannot execute without an approval. Approver ≠ proposer. Executes at most once (idempotency key). Approved amount is frozen |

`Evidence` is an immutable entity owned by Investigation but not an aggregate root: it is created once and only referenced afterwards.

## Domain services (pure, no I/O)

| Service | Context | Why it is a service and not an aggregate method |
|---------|---------|---------------------------------------------------|
| `MatchingEngine` | Reconciliation | Operates over many records from different aggregates |
| `ImpactCalculator` | Reconciliation | Computes financial impact over a set of records and fee schedules |
| `GroundingValidator` | Investigation | Checks an LLM output against an evidence set the LLM did not produce |
| `ApprovalPolicy` | Resolution | Decides how many and which approvals an action needs (ADR-0007) |

## Domain events

| Event | Producer | Consumers |
|-------|----------|-----------|
| `BatchImported`, `SourceConflictDetected` | Ingestion | Reconciliation (trigger run), Audit |
| `DiscrepancyDetected`, `DiscrepancySuperseded` | Reconciliation | Investigation, Audit |
| `CaseOpened`, `FindingRecorded`, `CaseEscalated`, `CaseResolved` | Investigation | Audit, read models |
| `ActionProposed`, `ActionApproved`, `ActionRejected`, `ActionExecuted` | Resolution | Investigation, Audit |

Events are frozen dataclasses with an `event_version`. Their payload shape is a contract and changes only by adding a new version.
