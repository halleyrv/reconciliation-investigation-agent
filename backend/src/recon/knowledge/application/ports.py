"""Ports to the retrieval models (ADR-0006): swappable, so tests run on fakes without a model."""

from collections.abc import Sequence
from typing import Protocol

type Vector = tuple[float, ...]


class EmbeddingProvider(Protocol):
    model: str
    dimension: int

    def embed_passages(self, texts: Sequence[str]) -> list[Vector]: ...

    def embed_query(self, text: str) -> Vector: ...


class Reranker(Protocol):
    model: str

    def score(self, query: str, texts: list[str]) -> list[float]:
        """One relevance score per text, in the order given; higher is more relevant."""
        ...
