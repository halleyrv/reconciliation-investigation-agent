# PHASE 5 — Evaluation and Benchmarking

Build a reproducible evaluation framework.

Create 30 labeled investigation cases:

- 10 exact matching cases.
- 10 discrepancy investigation cases.
- 10 multi-hop investigation cases.

For each case, define:

- Input records.
- Expected discrepancy.
- Expected financial impact.
- Expected evidence.
- Expected conclusion.
- Expected case status.

Implement three baselines:

1. Deterministic rules only.
2. Traditional RAG.
3. LangGraph investigation agent.

Evaluate:

- Matching accuracy.
- Discrepancy detection precision and recall.
- Evidence precision.
- Faithfulness.
- Tool selection accuracy.
- Resolution accuracy.
- False positive rate.
- Latency.
- Token consumption and estimated cost.

Use deterministic metrics wherever possible.

For LLM-based evaluation, document the evaluator's limitations and use human-reviewed ground truth.

Generate a comparative report with actual results.

Never fabricate benchmark results.

The evaluation must be reproducible using a single documented command.

---

## Amendments

Changes approved by the owner after the original text above. The original is never edited, so its heading keeps the original number.

| Date | Change | Approved by |
|------|--------|-------------|
| 2026-11-09 | **Renumbered: this is now Phase 6** (originally Phase 5), after Resolution (Phase 5) was added. | Owner |
