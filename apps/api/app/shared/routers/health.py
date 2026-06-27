from fastapi import APIRouter

from app.shared.core.pg_client import fetchrow

router = APIRouter()


@router.get("/health")
async def health():
    pg_ok = False
    try:
        row = await fetchrow("SELECT 1 AS ok")
        pg_ok = row is not None
    except Exception:
        pass
    return {"status": "ok", "postgres": "connected" if pg_ok else "unavailable"}
