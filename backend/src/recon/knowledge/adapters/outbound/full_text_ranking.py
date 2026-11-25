"""PostgreSQL full-text ranking over chunks passed in, with no table: the lexical baseline the
retrieval evaluation compares the models against (D3)."""

from collections.abc import Sequence

from sqlalchemy import Engine, text

from recon.knowledge.application.retrieval_evaluation import ChunkRef

# plainto_tsquery ANDs every term, so a paraphrased query rarely matches; OR keeps any chunk
# that shares a stemmed term, and ts_rank_cd ranks the ones that share more first.
_RANK = text(
    """
    WITH q AS (
        SELECT NULLIF(replace(plainto_tsquery('english', :query)::text, ' & ', ' | '), '')::tsquery
            AS terms
    )
    SELECT c.i
    FROM unnest(CAST(:bodies AS text[])) WITH ORDINALITY AS c(body, i), q
    WHERE to_tsvector('english', c.body) @@ q.terms
    ORDER BY ts_rank_cd(to_tsvector('english', c.body), q.terms) DESC, c.i
    """
)


def rank_by_full_text(
    engine: Engine, query: str, chunks: Sequence[tuple[ChunkRef, str]]
) -> list[ChunkRef]:
    """Matching chunks only, best first; equal ranks keep the order given."""
    with engine.connect() as connection:
        rows = connection.execute(_RANK, {"query": query, "bodies": [b for _, b in chunks]})
        return [chunks[i - 1][0] for (i,) in rows]
