"""Published interface of the Knowledge context. Other contexts import only this module.

Callers receive a composed ``HybridRetrieval`` and call ``retrieve(query, filters)``."""

from recon.knowledge.application.hybrid_retrieval import (
    RERANK_DEPTH,
    RRF_K,
    HybridRetrieval,
    RetrievedChunk,
)
from recon.knowledge.application.ports import ChunkHit, RetrievalFilters

__all__ = [
    "RERANK_DEPTH",
    "RRF_K",
    "ChunkHit",
    "HybridRetrieval",
    "RetrievalFilters",
    "RetrievedChunk",
]
