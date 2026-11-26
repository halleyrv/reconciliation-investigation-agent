"""Model fakes for tests (port inventory): no download, no runtime, deterministic."""

import hashlib
import math
from collections.abc import Sequence

from recon.knowledge.application.ports import Vector


class HashEmbeddings:
    """A unit vector from the text's hash: equal texts match, unrelated texts do not."""

    model = "fake-hash"

    def __init__(self, dimension: int = 8) -> None:
        self.dimension = dimension

    def _vector(self, text: str) -> Vector:
        digest = hashlib.sha256(text.encode()).digest()
        raw = [digest[i % len(digest)] - 127.5 for i in range(self.dimension)]
        norm = math.sqrt(math.fsum(x * x for x in raw))
        return tuple(x / norm for x in raw)

    def embed_passages(self, texts: Sequence[str]) -> list[Vector]:
        return [self._vector(t) for t in texts]

    def embed_query(self, text: str) -> Vector:
        return self._vector(text)


class IdentityReranker:
    """Scores candidates in the order given, so reranking keeps the first-stage order."""

    model = "fake-identity"

    def score(self, query: str, texts: list[str]) -> list[float]:
        return [float(-i) for i in range(len(texts))]
