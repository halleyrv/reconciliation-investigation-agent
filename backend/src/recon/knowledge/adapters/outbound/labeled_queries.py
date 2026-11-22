"""Reads the labeled retrieval dataset (``evaluation/retrieval/policy_queries.json``)."""

import json
from dataclasses import dataclass
from pathlib import Path

from recon.knowledge.application.retrieval_evaluation import (
    InvalidLabel,
    LabeledQuery,
    RelevantPassage,
)


@dataclass(frozen=True, slots=True)
class LabeledDataset:
    corpus: str  # directory of the labeled documents, relative to the repository root
    queries: tuple[LabeledQuery, ...]


def load_labeled_queries(path: Path) -> LabeledDataset:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        queries = tuple(
            LabeledQuery(
                id=str(q["id"]),
                query=str(q["query"]),
                relevant=tuple(
                    RelevantPassage(str(p["document"]), str(p["passage"])) for p in q["relevant"]
                ),
            )
            for q in raw["queries"]
        )
        corpus = str(raw["corpus"])
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise InvalidLabel(f"{path} is not a labeled query file: {error!r}") from None
    seen: set[str] = set()
    for query in queries:
        if query.id in seen:
            raise InvalidLabel(f"duplicate query id {query.id}")
        seen.add(query.id)
    return LabeledDataset(corpus, queries)
