"""Local ONNX models through fastembed (ADR-0006). The first use downloads the model into
``FASTEMBED_CACHE_PATH``; after that it runs offline."""

from collections.abc import Sequence

from fastembed import TextEmbedding
from fastembed.rerank.cross_encoder import TextCrossEncoder

from recon.knowledge.application.ports import Vector


class FastembedEmbeddings:
    def __init__(self, model: str) -> None:
        dimensions = {m["model"]: int(m["dim"]) for m in TextEmbedding.list_supported_models()}
        if model not in dimensions:
            raise ValueError(f"embedding model {model!r} is not supported by fastembed")
        self.model = model
        self.dimension = dimensions[model]
        self._model = TextEmbedding(model)

    # passage_embed / query_embed add the prefixes some models were trained with.
    def embed_passages(self, texts: Sequence[str]) -> list[Vector]:
        return [tuple(float(x) for x in v) for v in self._model.passage_embed(list(texts))]

    def embed_query(self, text: str) -> Vector:
        return tuple(float(x) for x in next(iter(self._model.query_embed(text))))


class FastembedReranker:
    def __init__(self, model: str) -> None:
        if model not in {m["model"] for m in TextCrossEncoder.list_supported_models()}:
            raise ValueError(f"reranker model {model!r} is not supported by fastembed")
        self.model = model
        self._model = TextCrossEncoder(model)

    def score(self, query: str, texts: list[str]) -> list[float]:
        return [float(s) for s in self._model.rerank(query, texts)]
