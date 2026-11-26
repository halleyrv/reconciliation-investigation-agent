from collections.abc import Sequence
from pathlib import Path

import pytest

from recon.knowledge.adapters.inbound.compare_retrieval import run
from recon.knowledge.adapters.outbound.fake_models import HashEmbeddings, IdentityReranker
from recon.knowledge.application.retrieval_evaluation import ChunkRef

ROOT = Path(__file__).parents[4]


def _nothing(query: str, chunks: Sequence[tuple[ChunkRef, str]]) -> list[ChunkRef]:
    return []


def test_compare_prints_one_row_per_chunk_size_and_retriever_with_its_misses(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = run(
        [
            "--root",
            str(ROOT),
            "--chunk-sizes",
            "200",
            "400",
            "--embedding",
            "fake-hash",
            "--reranker",
            "fake-identity",
        ],
        full_text=_nothing,
        embeddings=lambda name: HashEmbeddings(),
        reranker=lambda name: IdentityReranker(),
    )
    rows = [line for line in capsys.readouterr().out.splitlines() if line.startswith("| ")]
    assert exit_code == 0
    assert rows[0].split("|")[1:-1] == [
        " chunk ",
        " retriever ",
        " recall@3 ",
        " MRR ",
        " nDCG@3 ",
        " recall@5 ",
        " missed at 3 ",
    ]
    names = [(r.split("|")[1].strip(), r.split("|")[2].strip()) for r in rows[1:]]
    assert names == [
        (size, retriever)
        for size in ("200", "400")
        for retriever in ("full-text", "fake-hash", "fake-hash + fake-identity")
    ]
    # A ranker that returns nothing scores zero and misses every one of the 26 queries.
    full_text_200 = rows[1].split("|")
    assert [c.strip() for c in full_text_200[3:7]] == ["0.000", "0.000", "0.000", "0.000"]
    assert full_text_200[7].strip().split(", ")[0] == "Q01"
    assert len(full_text_200[7].split(",")) == 26


def test_a_perfect_ranker_scores_one_and_misses_nothing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from recon.knowledge.adapters.outbound.labeled_queries import load_labeled_queries

    dataset = load_labeled_queries(ROOT / "evaluation" / "retrieval" / "policy_queries.json")
    labels = {q.query: q for q in dataset.queries}

    def oracle(query: str, chunks: Sequence[tuple[ChunkRef, str]]) -> list[ChunkRef]:
        passages = [p.passage for p in labels[query].relevant]
        return [ref for ref, body in chunks if any(p in body for p in passages)]

    run(
        ["--root", str(ROOT), "--chunk-sizes", "400", "--embedding", "--reranker"],
        full_text=oracle,
        embeddings=lambda name: HashEmbeddings(),
        reranker=lambda name: IdentityReranker(),
    )
    [row] = [line for line in capsys.readouterr().out.splitlines() if "full-text" in line]
    assert [c.strip() for c in row.split("|")[3:8]] == ["1.000", "1.000", "1.000", "1.000", ""]
