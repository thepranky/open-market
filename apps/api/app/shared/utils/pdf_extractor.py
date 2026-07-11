"""
pdf_extractor.py — PDF text extraction cache for Meridian source grounding.

Downloads PDFs and extracts text page-by-page using pdfplumber (falls back
to pypdf).  Results are cached in data/source_text/{source_document_id}.json
so repeated runs do not re-download.

Cache schema:
{
  "source_document_id": "eu_google_fitbit_decision",
  "source_url": "https://...",
  "page_count": 42,
  "pages": [{"page_number": 1, "text": "..."}, ...],
  "extracted_at": "2026-05-23T12:00:00+00:00"
}
"""
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx

try:
    import pdfplumber
    _HAS_PDFPLUMBER = True
except ImportError:
    _HAS_PDFPLUMBER = False

try:
    import pypdf
    _HAS_PYPDF = True
except ImportError:
    _HAS_PYPDF = False


# apps/api/app/shared/utils/pdf_extractor.py -> five levels up is the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[5]
DEFAULT_CACHE_DIR = _REPO_ROOT / "data" / "source_text"

_HEADERS = {
    "User-Agent": "Meridian-SourceGrounding/1.0 (open-source research tool)",
    # Required for EUR-Lex/cellar URLs (http://publications.europa.eu/resource/celex/*.pdf)
    # which content-negotiate between RDF and PDF based on Accept.
    "Accept": "application/pdf, application/octet-stream, */*;q=0.8",
}


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

def extract_pages_pdfplumber(pdf_bytes: bytes) -> list[dict]:
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return [
            {"page_number": i + 1, "text": page.extract_text() or ""}
            for i, page in enumerate(pdf.pages)
        ]


def extract_pages_pypdf(pdf_bytes: bytes) -> list[dict]:
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    return [
        {"page_number": i + 1, "text": page.extract_text() or ""}
        for i, page in enumerate(reader.pages)
    ]


def extract_pages(pdf_bytes: bytes) -> list[dict]:
    """Extract per-page text, preferring pdfplumber over pypdf."""
    if _HAS_PDFPLUMBER:
        return extract_pages_pdfplumber(pdf_bytes)
    if _HAS_PYPDF:
        return extract_pages_pypdf(pdf_bytes)
    raise RuntimeError(
        "No PDF library available. Install pdfplumber: pip install pdfplumber"
    )


# ---------------------------------------------------------------------------
# Cache I/O
# ---------------------------------------------------------------------------

def _cache_path(source_document_id: str, cache_dir: Path) -> Path:
    return cache_dir / f"{source_document_id}.json"


def load_cache(
    source_document_id: str,
    cache_dir: Path = DEFAULT_CACHE_DIR,
) -> Optional[dict]:
    """Return cached page data if present, else None."""
    path = _cache_path(source_document_id, cache_dir)
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return None


def save_cache(data: dict, cache_dir: Path = DEFAULT_CACHE_DIR) -> Path:
    """Persist cache entry and return its path."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = _cache_path(data["source_document_id"], cache_dir)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return path


# ---------------------------------------------------------------------------
# Fetch + extract
# ---------------------------------------------------------------------------

def fetch_and_extract(
    source_document_id: str,
    pdf_url: str,
    *,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    timeout: int = 60,
    force: bool = False,
    client: Optional[httpx.Client] = None,
) -> dict:
    """
    Return page-level text cache for the document.

    Reads from disk cache unless force=True.  Downloads and extracts when
    no cache exists.  Raises httpx.HTTPStatusError on non-2xx responses.
    """
    if not force:
        cached = load_cache(source_document_id, cache_dir)
        if cached is not None:
            return cached

    close_client = client is None
    if client is None:
        client = httpx.Client(follow_redirects=True, timeout=timeout)

    try:
        resp = client.get(pdf_url, headers=_HEADERS)
        resp.raise_for_status()
        pdf_bytes = resp.content
    finally:
        if close_client:
            client.close()

    pages = extract_pages(pdf_bytes)
    data = {
        "source_document_id": source_document_id,
        "source_url": pdf_url,
        "page_count": len(pages),
        "pages": pages,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
    }
    save_cache(data, cache_dir)
    return data


# ---------------------------------------------------------------------------
# Page access helpers
# ---------------------------------------------------------------------------

def get_page_text(cache: dict, page_number: int) -> Optional[str]:
    """Return text for a specific 1-indexed page, or None if not present."""
    for p in cache.get("pages", []):
        if p["page_number"] == page_number:
            return p.get("text")
    return None


def iter_pages(cache: dict):
    """Yield (page_number, text) for all pages in the cache."""
    for p in cache.get("pages", []):
        yield p["page_number"], p.get("text", "")
