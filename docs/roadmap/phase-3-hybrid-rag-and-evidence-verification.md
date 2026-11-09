# PHASE 4 — Hybrid RAG and Evidence Verification

Implement the financial policy retrieval system.

Requirements:

- PostgreSQL full-text search.
- pgvector semantic search.
- Hybrid retrieval.
- Reciprocal Rank Fusion or another justified fusion strategy.
- Cross-encoder reranking where appropriate.
- Document chunking with metadata.
- Source attribution.
- Document versioning.

Create synthetic financial policies covering:

- Refund authorization.
- Refund limits.
- Payment settlement periods.
- Gateway fees.
- Dispute handling.
- Transaction reconciliation.

Implement retrieval tools for the LangGraph agent.

The agent must distinguish:

- Retrieved facts.
- Policy interpretations.
- Hypotheses.
- Unknown information.

Every policy-based conclusion must include a source reference.

Evaluate retrieval quality using a labeled test dataset.

Do not claim that RAG guarantees factual correctness. Implement explicit evidence verification.

---

## Amendments

Changes approved by the owner after the original text above. The original is never edited, so its heading keeps the original number.

| Date | Change | Approved by |
|------|--------|-------------|
| 2026-11-09 | **Renumbered: this is now Phase 3** (originally Phase 4). Retrieval is built before the investigation agent, because the agent's `retrieve_policies` node and policy-search tool depend on it. | Owner |
| 2026-11-09 | Clarification: "Implement retrieval tools for the LangGraph agent" means retrieval is published as `knowledge.api.retrieve(query, filters)` with chunk IDs, document version and scores, tested without LangGraph. Phase 4 wraps it as an agent tool. LangGraph is not a dependency of this phase. | Owner |
| 2026-11-09 | Clarification: the policy corpus is the one the simulator already generates (Phase 1 AS10, invariant I9). This phase adds only policies the simulator does not produce (refund limits, dispute handling), generated from the same config. Dispute handling has no matching records in the simulator data, so it is retrievable but no case exercises it. | Owner |
| 2026-11-09 | The embedding model, reranker and `VECTOR(N)` are chosen in this phase by the retrieval evaluation (ADR-0006). | Owner |
