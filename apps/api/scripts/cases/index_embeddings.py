"""
Embed all canonical cases and upsert into Postgres pgvector tables.

Run locally (from project root):
    GOOGLE_API_KEY=... DATABASE_URL=postgresql://... python apps/api/scripts/cases/index_embeddings.py

Run via Docker Compose:
    docker compose --profile embed up embed
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import numpy as np
from pgvector.asyncpg import register_vector

from app.shared.core.pg_client import close_pool, get_pool
from app.cases.services.case_service import get_all_cases
from app.cases.services.embedding_service import embed_text


def _vec(values: list[float]) -> np.ndarray:
    return np.array(values, dtype=np.float32)


def _case_embed_text(case) -> str:
    party_names = " ".join(p.name for p in (case.parties or []))
    parts = [
        case.case_name,
        party_names,
        case.ai_summary or "",
        " ".join(pm.name for pm in case.product_markets_considered),
        " ".join(pm.notes or "" for pm in case.product_markets_considered),
        " ".join(toh.name for toh in case.theories_of_harm),
        " ".join(toh.description or "" for toh in case.theories_of_harm),
        case.sector,
    ]
    return " ".join(p.strip() for p in parts if p.strip())


def _market_embed_text(pm) -> str:
    return " ".join(p for p in [pm.name, pm.notes or ""] if p)


def _theory_embed_text(toh) -> str:
    return " ".join(p for p in [toh.name, toh.description or ""] if p)


async def run() -> None:
    cases = get_all_cases()
    pool = await get_pool()

    print(f"Indexing {len(cases)} canonical cases into Postgres...")

    async with pool.acquire() as conn:
        await register_vector(conn)

        for case in cases:
            # Case-level embedding
            text = _case_embed_text(case)
            vec = _vec(embed_text(text))
            await conn.execute(
                """
                INSERT INTO case_embeddings
                    (case_id, case_name, jurisdiction, authority, decision_date,
                     sector, outcome, embed_text, embedding)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9::vector)
                ON CONFLICT (case_id) DO UPDATE SET
                    case_name     = EXCLUDED.case_name,
                    embed_text    = EXCLUDED.embed_text,
                    embedding     = EXCLUDED.embedding,
                    updated_at    = now()
                """,
                case.case_id,
                case.case_name,
                case.jurisdiction,
                case.authority,
                case.decision_date,
                case.sector,
                case.outcome.value,
                text,
                vec,
            )
            print(f"  [case] {case.case_id}")

            # Product market embeddings
            for pm in case.product_markets_considered:
                text = _market_embed_text(pm)
                vec = _vec(embed_text(text))
                await conn.execute(
                    """
                    INSERT INTO market_embeddings
                        (case_id, market_id, market_name, definition_status,
                         notes, embed_text, embedding)
                    VALUES ($1,$2,$3,$4,$5,$6,$7::vector)
                    ON CONFLICT (case_id, market_id) DO UPDATE SET
                        market_name       = EXCLUDED.market_name,
                        definition_status = EXCLUDED.definition_status,
                        notes             = EXCLUDED.notes,
                        embed_text        = EXCLUDED.embed_text,
                        embedding         = EXCLUDED.embedding,
                        updated_at        = now()
                    """,
                    case.case_id,
                    pm.market_id,
                    pm.name,
                    pm.definition_status.value,
                    pm.notes,
                    text,
                    vec,
                )

            # Theory of harm embeddings
            for toh in case.theories_of_harm:
                text = _theory_embed_text(toh)
                vec = _vec(embed_text(text))
                await conn.execute(
                    """
                    INSERT INTO theory_embeddings
                        (case_id, theory_id, theory_name, description,
                         embed_text, embedding)
                    VALUES ($1,$2,$3,$4,$5,$6::vector)
                    ON CONFLICT (case_id, theory_id) DO UPDATE SET
                        theory_name = EXCLUDED.theory_name,
                        description = EXCLUDED.description,
                        embed_text  = EXCLUDED.embed_text,
                        embedding   = EXCLUDED.embedding,
                        updated_at  = now()
                    """,
                    case.case_id,
                    toh.theory_id,
                    toh.name,
                    toh.description,
                    text,
                    vec,
                )

    await close_pool()
    print("Done.")


if __name__ == "__main__":
    asyncio.run(run())
