import json
import uuid
from datetime import date
from pathlib import Path

import pytest

from recon.knowledge.adapters.outbound.labeled_queries import load_labeled_queries
from recon.knowledge.application.retrieval_evaluation import (
    InvalidLabel,
    LabeledQuery,
    RelevantPassage,
    relevant_chunks,
)
from recon.knowledge.domain.document import Document, DocumentKind

ROOT = Path(__file__).parents[4]
DATASET = ROOT / "evaluation" / "retrieval" / "policy_queries.json"
POLICY = "# Refund Limits\n\nRefund window: 5 calendar days\n\nA second refund is not allowed.\n"


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


def _query(*relevant: RelevantPassage) -> LabeledQuery:
    return LabeledQuery(id="Q1", query="refund window?", relevant=relevant)


def _write(tmp_path: Path, queries: list[dict[str, object]]) -> Path:
    path = tmp_path / "queries.json"
    path.write_text(json.dumps({"schema_version": "1.0.0", "corpus": "x", "queries": queries}))
    return path


@pytest.mark.parametrize("max_chars", [200, 400, 800])
def test_every_labeled_passage_maps_to_a_chunk_at_every_compared_chunk_size(
    max_chars: int,
) -> None:
    dataset = load_labeled_queries(DATASET)
    corpus = _corpus(ROOT / dataset.corpus, max_chars)
    assert len(dataset.queries) >= 20
    assert {p.document for q in dataset.queries for p in q.relevant} == set(corpus)
    for query in dataset.queries:
        assert relevant_chunks(query, corpus)  # raises InvalidLabel for a passage it cannot map


def test_a_passage_maps_to_the_chunk_that_contains_it() -> None:
    corpus = {"refund_limits": _doc(POLICY, max_chars=40)}
    query = _query(RelevantPassage("refund_limits", "A second refund is not allowed."))
    assert relevant_chunks(query, corpus) == frozenset({("refund_limits", 1)})


@pytest.mark.parametrize(
    ("passage", "message"),
    [
        (RelevantPassage("refund_limits", "Refund window: 30 days"), "Q1: passage not found"),
        (RelevantPassage("dispute_handling", "Response window"), "Q1: unknown document"),
    ],
)
def test_a_label_that_does_not_match_the_corpus_is_rejected(
    passage: RelevantPassage, message: str
) -> None:
    with pytest.raises(InvalidLabel, match=message):
        relevant_chunks(_query(passage), {"refund_limits": _doc(POLICY)})


@pytest.mark.parametrize(
    ("relevant", "message"),
    [
        ((), "Q1: a query needs at least one relevant passage"),
        ((RelevantPassage("refund_limits", "window\n\nA second"),), "Q1: a passage stays in one"),
        ((RelevantPassage("refund_limits", " "),), "Q1: a passage needs text"),
    ],
)
def test_a_query_label_is_validated_on_its_own(
    relevant: tuple[RelevantPassage, ...], message: str
) -> None:
    with pytest.raises(InvalidLabel, match=message):
        _query(*relevant)


def test_the_loader_rejects_duplicate_query_ids(tmp_path: Path) -> None:
    query: dict[str, object] = {
        "id": "Q1",
        "query": "q",
        "relevant": [{"document": "d", "passage": "p"}],
    }
    with pytest.raises(InvalidLabel, match="duplicate query id Q1"):
        load_labeled_queries(_write(tmp_path, [query, query]))


def test_the_loader_rejects_a_malformed_file(tmp_path: Path) -> None:
    with pytest.raises(InvalidLabel, match="not a labeled query file"):
        load_labeled_queries(_write(tmp_path, [{"id": "Q1"}]))


def _doc(content: str, max_chars: int = 400) -> Document:
    return Document.first(
        id=uuid.uuid4(),
        key="refund_limits",
        kind=DocumentKind.POLICY,
        content=content,
        effective_from=date(2026, 10, 1),
        max_chunk_chars=max_chars,
    )
