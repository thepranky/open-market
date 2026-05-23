from fastapi import APIRouter

from app.core.neo4j_client import run_query

router = APIRouter()


@router.get("/health")
async def health():
    neo4j_ok = False
    try:
        await run_query("RETURN 1 AS ok")
        neo4j_ok = True
    except Exception:
        pass
    return {"status": "ok", "neo4j": "connected" if neo4j_ok else "unavailable"}
