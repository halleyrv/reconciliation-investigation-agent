# PHASE 3 — LangGraph Investigation Agent

Implement the AI investigation agent using LangGraph.

The agent must investigate existing reconciliation cases.

Implement these nodes:

- classify_discrepancy
- plan_investigation
- retrieve_transactions
- retrieve_evidence
- retrieve_policies
- analyze_case
- calculate_impact
- verify_findings
- human_review
- finalize_investigation

Implement tools for:

1. Searching transactions.
2. Searching refunds.
3. Retrieving internal authorization records.
4. Searching financial policies.
5. Calculating financial impact.
6. Retrieving case evidence.

Requirements:

- Typed graph state.
- Conditional routing.
- Bounded investigation loops.
- Tool execution validation.
- Structured outputs.
- Persistent checkpoints.
- Human-in-the-loop using LangGraph interrupts.
- Resume execution after human approval.
- Handle missing and contradictory evidence.
- Never invent financial records.
- Every conclusion must reference evidence IDs.

Use deterministic Python functions for calculations.

The LLM must investigate and explain, not independently modify financial records.

Implement tests for routing, tool selection, evidence grounding and interrupted execution.

Show the graph structure and explain each node.

---

## Amendments

Changes approved by the owner after the original text above. The original is never edited, so its heading keeps the original number.

| Date | Change | Approved by |
|------|--------|-------------|
| 2026-11-09 | **Renumbered: this is now Phase 4** (originally Phase 3). It runs after Hybrid RAG (Phase 3), whose `knowledge.api.retrieve` backs the `retrieve_policies` node and the policy-search tool. | Owner |
| 2026-11-09 | Clarification: in this phase `human_review` is a review of the **investigation** (accept, reject or send back the findings), not approval of a financial action. The decision is stored in `investigation.*` as a domain record with its actor, and the graph resumes by reading it. The LangGraph checkpoint is never the record of the decision. Approval of consequential actions arrives in Phase 5. | Owner |
| 2026-11-09 | Langfuse tracing arrives in this phase, as Phase 0 planned: every agent run has a trace ID stored on `investigation.agent_runs` (principle 9). | Owner |
| 2026-11-09 | The LLM provider and exact model ID are chosen and verified against current documentation in this phase (ADR-0005). | Owner |
