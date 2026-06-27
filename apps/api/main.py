from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.shared.core.config import settings
from app.shared.core.pg_client import close_pool
from app.cases.routers import cases, graph, indexed_cases, search, graph_entities
from app.screening.routers import jurisdictions
from app.shared.routers import health


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await close_pool()


app = FastAPI(
    title=settings.app_title,
    version=settings.app_version,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
        "http://web:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(cases.router)
app.include_router(indexed_cases.router)
app.include_router(search.router)
app.include_router(graph.router)
app.include_router(graph_entities.router)
app.include_router(jurisdictions.router)


@app.get("/")
def root():
    return {"name": settings.app_title, "version": settings.app_version, "docs": "/docs"}
