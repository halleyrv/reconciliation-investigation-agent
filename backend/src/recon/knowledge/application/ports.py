"""Ports of the Knowledge context: the retrieval models (ADR-0006), swappable so tests run on
fakes without a model, and the document store."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from recon.knowledge.domain.document import Document, DocumentKind

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


class DocumentRepository(Protocol):
    def latest(self, key: str) -> Document | None:
        """The highest version stored under ``key``."""
        ...

    def add(self, document: Document, embedding_model: str, embeddings: Sequence[Vector]) -> None:
        """Stores a version with one embedding per chunk, in chunk order, all or nothing."""
        ...


@dataclass(frozen=True, slots=True)
class ChunkHit:
    """A chunk found by a search, with what attributes it: its document version."""

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_key: str
    version: int
    ordinal: int
    section: str
    content: str
    score: float  # higher is more relevant; comparable only within one search


@dataclass(frozen=True, slots=True)
class RetrievalFilters:
    """Narrows a search to some documents; ``None`` does not narrow."""

    kinds: frozenset[DocumentKind] | None = None
    document_keys: frozenset[str] | None = None


NO_FILTERS = RetrievalFilters()


class ChunkSearch(Protocol):
    """First-stage searches over the current version of each document, best first."""

    def full_text(self, query: str, limit: int, filters: RetrievalFilters) -> list[ChunkHit]: ...

    def vector(
        self, query: Vector, model: str, limit: int, filters: RetrievalFilters
    ) -> list[ChunkHit]: ...
