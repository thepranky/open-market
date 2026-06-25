from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

from neo4j import AsyncGraphDatabase, AsyncSession

from .config import settings

_driver = None


def get_driver():
    global _driver
    if _driver is None:
        _driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
    return _driver


async def close_driver():
    global _driver
    if _driver is not None:
        await _driver.close()
        _driver = None


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    driver = get_driver()
    async with driver.session() as session:
        yield session


async def run_query(query: str, params: dict[str, Any] | None = None) -> list[dict]:
    async with get_session() as session:
        result = await session.run(query, params or {})
        return [dict(record) async for record in result]
