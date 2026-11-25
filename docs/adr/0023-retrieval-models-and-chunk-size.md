# ADR-0023: Retrieval models and chunk size chosen by the labeled evaluation

- **Status:** Proposed
- **Date:** 2026-11-25
- **Related:** ADR-0006, docs/roadmap/phase-3-hybrid-rag-and-evidence-verification.md (S8), odd/tasks/p3-hybrid-rag-and-evidence-verification.md (D1-D4)
- **Kind:** Technical (retrieval quality)

## Context

ADR-0006 runs the embedding model and the reranker locally behind ports and leaves the concrete models, and with them `VECTOR(N)`, to a measurement. D2 adds the maximum chunk size to that measurement. D3 is the rule that picks the winner: beat the full-text-only baseline in MRR and recall@3 at the same chunk size; recall@3 >= 0.9; inspect every missed query by hand; a difference of one or two queries is not a win, and the simpler configuration wins a tie.

The dataset is the 26 labeled queries of `evaluation/retrieval/policy_queries.json` over the six sample policies. The runtime is fastembed 0.9.1 (D1). Its ONNX runtime has no Intel macOS wheel for Python 3.14, so the models run in Linux: CI and the `models` Compose service (D4).

## Measurement

`docker compose run --rm models uv run --locked recon-compare-retrieval` scored the full-text baseline (PostgreSQL `ts_rank_cd`, any stemmed query term matches), four embedding models alone, and each embedding with each of three rerankers. The reranker reorders the embedding's top 10. A query is missed when recall@3 < 1. These are the rows that decide (full output in the appendix):

| chunk | chunks | random recall@3 | retriever | recall@3 | MRR | missed at 3 |
|---|---|---|---|---|---|---|
| 800 | 7 | 0.43 | full-text | 1.000 | 0.897 | none |
| 800 | 7 | 0.43 | bge-small-en-v1.5 + ms-marco-MiniLM-L-6-v2 | 1.000 | 1.000 | none |
| 400 | 11 | 0.27 | full-text | 0.865 | 0.865 | Q08, Q13, Q17, Q22 |
| 400 | 11 | 0.27 | bge-small-en-v1.5 | 0.942 | 0.878 | Q07, Q13, Q15 |
| 400 | 11 | 0.27 | any of the 4 embeddings + ms-marco-MiniLM-L-6-v2 | 0.981 | 0.942 | Q04 |
| 400 | 11 | 0.27 | any of the 4 embeddings + bge-reranker-base | 0.962 | 0.933 | Q08 |
| 200 | 17 | 0.18 | full-text | 0.788 | 0.683 | Q04, Q08, Q13, Q17, Q19, Q22 |
| 200 | 17 | 0.18 | bge-small-en-v1.5 + ms-marco-MiniLM-L-6-v2 | 0.942 | 0.946 | Q07, Q19 |
| 200 | 17 | 0.18 | snowflake-arctic-embed-s + bge-reranker-base | 0.962 | 0.872 | Q19 |

Embedding models compared: `sentence-transformers/all-MiniLM-L6-v2` (384), `BAAI/bge-small-en-v1.5` (384), `snowflake/snowflake-arctic-embed-s` (384), `BAAI/bge-base-en-v1.5` (768). Rerankers: `Xenova/ms-marco-MiniLM-L-6-v2`, `jinaai/jina-reranker-v1-tiny-en`, `BAAI/bge-reranker-base`.

## Decision

- **Chunk size 400 characters** (`DEFAULT_MAX_CHUNK_CHARS`).
- **Embedding model `BAAI/bge-small-en-v1.5`, so `VECTOR(384)`.**
- **Reranker `Xenova/ms-marco-MiniLM-L-6-v2`**, over the first stage's top 10.

Why, by D3:

1. 800 fails rule 1. Seven chunks for six documents turn chunk retrieval into document retrieval: the baseline already reaches recall@3 = 1.000, so nothing can beat it, and a random top 3 already scores 0.43.
2. At 400, embedding + ms-marco beats the baseline by three queries in recall@3 (0.981 against 0.865) and in MRR (0.942 against 0.865), and clears 0.9. Its only miss, Q04, is a retrieval miss and not a missing label: the chunk ranked first (`transaction_reconciliation` 1) says the payment equals the order total, not that refunds never exceed the captured amount. Both labeled chunks are ranked 2 and 4.
3. 200 against 400 is a tie: the best rows differ by one query (0.962 or 0.942 against 0.981). The simpler wins, which is 400: fewer chunks to embed and store, and the size the corpus already uses.
4. At 400, the four embeddings tie exactly once ms-marco reranks them, and alone `bge-small-en-v1.5` ties `all-MiniLM-L6-v2` (0.942). The smallest model wins the tie: `bge-small-en-v1.5` (0.067 GB).
5. ms-marco-MiniLM-L-6-v2 beats `bge-reranker-base` by one query at 400 and is 13 times smaller (0.08 GB against 1.04 GB), so it wins either way.

## Alternatives considered

| Alternative | Why not |
|-------------|---------|
| 800-character chunks | Document retrieval: the baseline already scores 1.000, and a chunk no longer points to one rule for evidence attribution |
| 200-character chunks | One query from 400, with 55% more chunks; no measured gain |
| `BAAI/bge-base-en-v1.5` (768) | Ties the small models after reranking, at twice the vector size and three times the model size |
| `BAAI/bge-reranker-base` | One query worse at 400, 13 times larger |
| No reranker | At 400 the embedding alone misses three queries, the reranked one misses one |

## Consequences

- **Positive:** The choice is measured and reproducible with one command. Both models are small (about 150 MB together), MIT and Apache-2.0 licensed, and run on CPU.
- **Negative:** The corpus is small. At 400 there are 11 chunks, and the reranker reorders 10 of them, so this evaluation cannot tell the embedding models apart once a reranker runs. Every difference between the leading configurations is one or two queries. The embedding choice matters more in T6, where its ranking also feeds the fusion with full-text.
- **Negative:** The models do not run natively on Intel macOS with Python 3.14 (D4). There, the real-model tests are skipped and the comparison runs in the `models` service. CI downloads both models on each run.
- **Follow-ups:** Re-run `recon-compare-retrieval` when the corpus or the dataset grows, and supersede this ADR if the winner changes. Changing the embedding model requires re-embedding every chunk (ADR-0006). T8 compares lexical, vector, hybrid and hybrid + rerank with these models.

## Appendix: full output (2026-11-25)

```text
26 queries; a query is missed when recall@3 < 1.

| chunk | retriever | recall@3 | MRR | nDCG@3 | recall@5 | missed at 3 |
|---|---|---|---|---|---|---|
| 200 | full-text | 0.788 | 0.683 | 0.681 | 0.885 | Q04, Q08, Q13, Q17, Q19, Q22 |
| 200 | sentence-transformers/all-MiniLM-L6-v2 | 0.942 | 0.926 | 0.918 | 0.942 | Q07, Q19 |
| 200 | BAAI/bge-small-en-v1.5 | 0.942 | 0.897 | 0.894 | 0.942 | Q07, Q19 |
| 200 | snowflake/snowflake-arctic-embed-s | 0.808 | 0.710 | 0.698 | 0.904 | Q07, Q12, Q14, Q16, Q18, Q19 |
| 200 | BAAI/bge-base-en-v1.5 | 0.904 | 0.871 | 0.861 | 0.942 | Q07, Q08, Q19 |
| 200 | sentence-transformers/all-MiniLM-L6-v2 + Xenova/ms-marco-MiniLM-L-6-v2 | 0.942 | 0.942 | 0.929 | 0.962 | Q07, Q19 |
| 200 | sentence-transformers/all-MiniLM-L6-v2 + jinaai/jina-reranker-v1-tiny-en | 0.942 | 0.904 | 0.901 | 0.942 | Q07, Q19 |
| 200 | sentence-transformers/all-MiniLM-L6-v2 + BAAI/bge-reranker-base | 0.904 | 0.869 | 0.857 | 0.962 | Q04, Q08, Q19 |
| 200 | BAAI/bge-small-en-v1.5 + Xenova/ms-marco-MiniLM-L-6-v2 | 0.942 | 0.946 | 0.929 | 0.962 | Q07, Q19 |
| 200 | BAAI/bge-small-en-v1.5 + jinaai/jina-reranker-v1-tiny-en | 0.942 | 0.908 | 0.901 | 0.942 | Q07, Q19 |
| 200 | BAAI/bge-small-en-v1.5 + BAAI/bge-reranker-base | 0.923 | 0.873 | 0.869 | 0.962 | Q08, Q19 |
| 200 | snowflake/snowflake-arctic-embed-s + Xenova/ms-marco-MiniLM-L-6-v2 | 0.942 | 0.942 | 0.929 | 0.962 | Q07, Q19 |
| 200 | snowflake/snowflake-arctic-embed-s + jinaai/jina-reranker-v1-tiny-en | 0.942 | 0.923 | 0.915 | 0.942 | Q07, Q19 |
| 200 | snowflake/snowflake-arctic-embed-s + BAAI/bge-reranker-base | 0.962 | 0.872 | 0.891 | 0.962 | Q19 |
| 200 | BAAI/bge-base-en-v1.5 + Xenova/ms-marco-MiniLM-L-6-v2 | 0.942 | 0.942 | 0.929 | 0.962 | Q07, Q19 |
| 200 | BAAI/bge-base-en-v1.5 + jinaai/jina-reranker-v1-tiny-en | 0.942 | 0.904 | 0.901 | 0.942 | Q07, Q19 |
| 200 | BAAI/bge-base-en-v1.5 + BAAI/bge-reranker-base | 0.904 | 0.869 | 0.857 | 0.962 | Q04, Q08, Q19 |
| 400 | full-text | 0.865 | 0.865 | 0.833 | 1.000 | Q08, Q13, Q17, Q22 |
| 400 | sentence-transformers/all-MiniLM-L6-v2 | 0.942 | 0.897 | 0.884 | 1.000 | Q04, Q07, Q13 |
| 400 | BAAI/bge-small-en-v1.5 | 0.942 | 0.878 | 0.876 | 1.000 | Q07, Q13, Q15 |
| 400 | snowflake/snowflake-arctic-embed-s | 0.808 | 0.704 | 0.688 | 0.904 | Q07, Q13, Q15, Q16, Q18, Q19, Q21 |
| 400 | BAAI/bge-base-en-v1.5 | 0.981 | 0.897 | 0.911 | 1.000 | Q07 |
| 400 | sentence-transformers/all-MiniLM-L6-v2 + Xenova/ms-marco-MiniLM-L-6-v2 | 0.981 | 0.942 | 0.950 | 1.000 | Q04 |
| 400 | sentence-transformers/all-MiniLM-L6-v2 + jinaai/jina-reranker-v1-tiny-en | 0.962 | 0.955 | 0.939 | 1.000 | Q04, Q07 |
| 400 | sentence-transformers/all-MiniLM-L6-v2 + BAAI/bge-reranker-base | 0.962 | 0.933 | 0.932 | 1.000 | Q08 |
| 400 | BAAI/bge-small-en-v1.5 + Xenova/ms-marco-MiniLM-L-6-v2 | 0.981 | 0.942 | 0.950 | 1.000 | Q04 |
| 400 | BAAI/bge-small-en-v1.5 + jinaai/jina-reranker-v1-tiny-en | 0.962 | 0.955 | 0.939 | 1.000 | Q04, Q07 |
| 400 | BAAI/bge-small-en-v1.5 + BAAI/bge-reranker-base | 0.962 | 0.933 | 0.932 | 1.000 | Q08 |
| 400 | snowflake/snowflake-arctic-embed-s + Xenova/ms-marco-MiniLM-L-6-v2 | 0.981 | 0.942 | 0.950 | 1.000 | Q04 |
| 400 | snowflake/snowflake-arctic-embed-s + jinaai/jina-reranker-v1-tiny-en | 0.962 | 0.955 | 0.939 | 1.000 | Q04, Q07 |
| 400 | snowflake/snowflake-arctic-embed-s + BAAI/bge-reranker-base | 0.962 | 0.933 | 0.932 | 1.000 | Q08 |
| 400 | BAAI/bge-base-en-v1.5 + Xenova/ms-marco-MiniLM-L-6-v2 | 0.981 | 0.942 | 0.950 | 1.000 | Q04 |
| 400 | BAAI/bge-base-en-v1.5 + jinaai/jina-reranker-v1-tiny-en | 0.962 | 0.955 | 0.939 | 1.000 | Q04, Q07 |
| 400 | BAAI/bge-base-en-v1.5 + BAAI/bge-reranker-base | 0.962 | 0.933 | 0.932 | 1.000 | Q08 |
| 800 | full-text | 1.000 | 0.897 | 0.921 | 1.000 |  |
| 800 | sentence-transformers/all-MiniLM-L6-v2 | 0.981 | 0.962 | 0.957 | 1.000 | Q07 |
| 800 | BAAI/bge-small-en-v1.5 | 0.981 | 0.936 | 0.934 | 1.000 | Q07 |
| 800 | snowflake/snowflake-arctic-embed-s | 0.904 | 0.894 | 0.860 | 1.000 | Q07, Q15, Q18, Q19 |
| 800 | BAAI/bge-base-en-v1.5 | 1.000 | 0.962 | 0.965 | 1.000 |  |
| 800 | sentence-transformers/all-MiniLM-L6-v2 + Xenova/ms-marco-MiniLM-L-6-v2 | 1.000 | 1.000 | 0.994 | 1.000 |  |
| 800 | sentence-transformers/all-MiniLM-L6-v2 + jinaai/jina-reranker-v1-tiny-en | 0.981 | 0.955 | 0.949 | 1.000 | Q07 |
| 800 | sentence-transformers/all-MiniLM-L6-v2 + BAAI/bge-reranker-base | 1.000 | 1.000 | 0.997 | 1.000 |  |
| 800 | BAAI/bge-small-en-v1.5 + Xenova/ms-marco-MiniLM-L-6-v2 | 1.000 | 1.000 | 0.994 | 1.000 |  |
| 800 | BAAI/bge-small-en-v1.5 + jinaai/jina-reranker-v1-tiny-en | 0.981 | 0.955 | 0.949 | 1.000 | Q07 |
| 800 | BAAI/bge-small-en-v1.5 + BAAI/bge-reranker-base | 1.000 | 1.000 | 0.997 | 1.000 |  |
| 800 | snowflake/snowflake-arctic-embed-s + Xenova/ms-marco-MiniLM-L-6-v2 | 1.000 | 1.000 | 0.994 | 1.000 |  |
| 800 | snowflake/snowflake-arctic-embed-s + jinaai/jina-reranker-v1-tiny-en | 0.981 | 0.955 | 0.949 | 1.000 | Q07 |
| 800 | snowflake/snowflake-arctic-embed-s + BAAI/bge-reranker-base | 1.000 | 1.000 | 0.997 | 1.000 |  |
| 800 | BAAI/bge-base-en-v1.5 + Xenova/ms-marco-MiniLM-L-6-v2 | 1.000 | 1.000 | 0.994 | 1.000 |  |
| 800 | BAAI/bge-base-en-v1.5 + jinaai/jina-reranker-v1-tiny-en | 0.981 | 0.955 | 0.949 | 1.000 | Q07 |
| 800 | BAAI/bge-base-en-v1.5 + BAAI/bge-reranker-base | 1.000 | 1.000 | 0.997 | 1.000 |  |
```
