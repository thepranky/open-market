"""Vector similarity search against Postgres pgvector tables."""
import numpy as np

from app.core.config import settings
from app.core.pg_client import fetch
from app.services.embedding_service import embed_query


def _to_vec(values: list[float]) -> np.ndarray:
    """Convert a float list to a numpy array as required by pgvector's asyncpg codec."""
    return np.array(values, dtype=np.float32)


async def search_cases_semantic(query: str, top_k: int | None = None) -> list[dict]:
    """Embed query and return top-K cases by cosine similarity."""
    k = top_k or settings.semantic_top_k
    threshold = settings.semantic_similarity_threshold
    q_vec = _to_vec(embed_query(query))

    rows = await fetch(
        """
        SELECT
            case_id, case_name, jurisdiction, authority,
            decision_date, sector, outcome,
            1 - (embedding <=> $1::vector) AS similarity
        FROM case_embeddings
        WHERE 1 - (embedding <=> $1::vector) >= $2
        ORDER BY embedding <=> $1::vector
        LIMIT $3
        """,
        q_vec,
        threshold,
        k,
    )
    return [dict(r) for r in rows]


async def search_markets_semantic(name: str, top_k: int = 20) -> list[dict]:
    """Find (case_id, market) pairs semantically similar to the given name."""
    threshold = settings.semantic_similarity_threshold
    q_vec = _to_vec(embed_query(name))

    rows = await fetch(
        """
        SELECT
            case_id, market_id, market_name, definition_status, notes,
            1 - (embedding <=> $1::vector) AS similarity
        FROM market_embeddings
        WHERE 1 - (embedding <=> $1::vector) >= $2
        ORDER BY embedding <=> $1::vector
        LIMIT $3
        """,
        q_vec,
        threshold,
        top_k,
    )
    return [dict(r) for r in rows]


async def search_theories_semantic(name: str, top_k: int = 20) -> list[dict]:
    """Find (case_id, theory) pairs semantically similar to the given name."""
    threshold = settings.semantic_similarity_threshold
    q_vec = _to_vec(embed_query(name))

    rows = await fetch(
        """
        SELECT
            case_id, theory_id, theory_name, description,
            1 - (embedding <=> $1::vector) AS similarity
        FROM theory_embeddings
        WHERE 1 - (embedding <=> $1::vector) >= $2
        ORDER BY embedding <=> $1::vector
        LIMIT $3
        """,
        q_vec,
        threshold,
        top_k,
    )
    return [dict(r) for r in rows]
