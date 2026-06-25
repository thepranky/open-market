"""Thin wrapper around Google text-embedding-004 for asymmetric retrieval."""
from google import genai
from google.genai import types as genai_types

from app.shared.core.config import settings

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(
            api_key=settings.google_api_key,
            http_options={"api_version": "v1"},
        )
    return _client


def embed_text(text: str) -> list[float]:
    """Embed a document for indexing. Returns a 768-dim float list."""
    client = _get_client()
    response = client.models.embed_content(
        model=settings.embedding_model,
        contents=text,
        config=genai_types.EmbedContentConfig(
            task_type="RETRIEVAL_DOCUMENT",
            output_dimensionality=settings.embedding_dimensions,
        ),
    )
    return response.embeddings[0].values


def embed_query(text: str) -> list[float]:
    """Embed a user query. Uses RETRIEVAL_QUERY for asymmetric recall."""
    client = _get_client()
    response = client.models.embed_content(
        model=settings.embedding_model,
        contents=text,
        config=genai_types.EmbedContentConfig(
            task_type="RETRIEVAL_QUERY",
            output_dimensionality=settings.embedding_dimensions,
        ),
    )
    return response.embeddings[0].values
