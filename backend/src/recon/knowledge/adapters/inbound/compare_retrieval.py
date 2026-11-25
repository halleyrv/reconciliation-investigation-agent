"""``recon-compare-retrieval``: scores the lexical baseline, each embedding model and each
embedding + reranker pair at each chunk size on the labeled dataset, so the models and the
chunk size are chosen by measurement (ADR-0006, D2, D3). Prints a Markdown table."""

import argparse
import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import date
from pathlib import Path

from recon.knowledge.adapters.outbound.labeled_queries import load_labeled_queries
from recon.knowledge.application.ports import EmbeddingProvider, Reranker, Vector
from recon.knowledge.application.ranking import rank_by_similarity, rerank
from recon.knowledge.application.retrieval_evaluation import (
    ChunkRef,
    LabeledQuery,
    evaluate,
    recall_at_k,
    relevant_chunks,
)
from recon.knowledge.domain.document import Document, DocumentKind

type Ranker = Callable[[str, Sequence[tuple[ChunkRef, str]]], list[ChunkRef]]

DATASET = Path("evaluation/retrieval/policy_queries.json")
# Small English models with permissive licenses that fastembed ships (D1).
EMBEDDINGS = [
    "sentence-transformers/all-MiniLM-L6-v2",
    "BAAI/bge-small-en-v1.5",
    "snowflake/snowflake-arctic-embed-s",
    "BAAI/bge-base-en-v1.5",
]
RERANKERS = [
    "Xenova/ms-marco-MiniLM-L-6-v2",
    "jinaai/jina-reranker-v1-tiny-en",
    "BAAI/bge-reranker-base",
]
RERANK_TOP = 10  # the reranker reorders the first stage's top 10


def _vector_ranker(model: EmbeddingProvider) -> Ranker:
    cache: dict[str, Vector] = {}

    def rank(query: str, chunks: Sequence[tuple[ChunkRef, str]]) -> list[ChunkRef]:
        missing = [body for _, body in chunks if body not in cache]
        cache.update(zip(missing, model.embed_passages(missing), strict=True))
        return rank_by_similarity(model.embed_query(query), [(r, cache[b]) for r, b in chunks])

    return rank


def _reranked(first: Ranker, model: Reranker) -> Ranker:
    def rank(query: str, chunks: Sequence[tuple[ChunkRef, str]]) -> list[ChunkRef]:
        bodies = dict(chunks)
        top = first(query, chunks)[:RERANK_TOP]
        return rerank(model, query, [(ref, bodies[ref]) for ref in top])

    return rank


def _corpus(directory: Path, max_chars: int) -> dict[str, Document]:
    return {
        path.stem: Document.first(
            id=uuid.uuid4(),
            key=path.stem,
            kind=DocumentKind.POLICY,
            content=path.read_text(encoding="utf-8"),
            effective_from=date(2026, 10, 1),
            max_chunk_chars=max_chars,
        )
        for path in sorted(directory.glob("*.md"))
    }


def _row(
    size: int,
    name: str,
    ranker: Ranker,
    queries: Sequence[LabeledQuery],
    corpus: Mapping[str, Document],
) -> str:
    chunks = [((d.key, c.ordinal), c.content) for d in corpus.values() for c in d.chunks]
    results = [(ranker(q.query, chunks), relevant_chunks(q, corpus)) for q in queries]
    at3, at5 = evaluate(results, k=3), evaluate(results, k=5)
    missed = [
        q.id
        for q, (ranked, rel) in zip(queries, results, strict=True)
        if recall_at_k(ranked, rel, 3) < 1
    ]
    return (
        f"| {size} | {name} | {at3.recall_at_k:.3f} | {at3.mrr:.3f} | {at3.ndcg_at_k:.3f}"
        f" | {at5.recall_at_k:.3f} | {', '.join(missed)} |"
    )


def run(
    argv: Sequence[str] | None,
    *,
    full_text: Ranker,
    embeddings: Callable[[str], EmbeddingProvider],
    reranker: Callable[[str], Reranker],
) -> int:
    parser = argparse.ArgumentParser(prog="recon-compare-retrieval", description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."), help="repository root")
    parser.add_argument("--chunk-sizes", type=int, nargs="+", default=[200, 400, 800])
    parser.add_argument("--embedding", nargs="*", default=EMBEDDINGS)
    parser.add_argument("--reranker", nargs="*", default=RERANKERS)
    args = parser.parse_args(argv)

    dataset = load_labeled_queries(args.root / DATASET)
    vector = {name: _vector_ranker(embeddings(name)) for name in args.embedding}
    rerankers = {name: reranker(name) for name in args.reranker}
    rankers: dict[str, Ranker] = {"full-text": full_text, **vector}
    for e, first in vector.items():
        rankers |= {f"{e} + {r}": _reranked(first, model) for r, model in rerankers.items()}

    print(f"{len(dataset.queries)} queries; a query is missed when recall@3 < 1.\n")
    print("| chunk | retriever | recall@3 | MRR | nDCG@3 | recall@5 | missed at 3 |")
    print("|---|---|---|---|---|---|---|")
    for size in args.chunk_sizes:
        corpus = _corpus(args.root / dataset.corpus, size)
        for name, ranker in rankers.items():
            print(_row(size, name, ranker, dataset.queries, corpus))
    return 0
