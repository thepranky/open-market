"""Fetch and normalize authoritative source text for jurisdiction verification."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

import httpx

from app.screening.models.jurisdiction_verification import FetchStatus
from app.shared.utils.pdf_extractor import extract_pages

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; CompMap-SourceFetcher/1.0; "
        "+https://github.com/open-market)"
    ),
    "Accept": "text/html,application/xhtml+xml,application/pdf,*/*;q=0.8",
}

_BOT_PROTECTED_STATUSES = {403}
_SSL_ERROR_MARKERS = ("CERTIFICATE_VERIFY_FAILED", "SSL:", "[SSL")


@dataclass
class SourceFetchResult:
    url: str
    final_url: Optional[str] = None
    content_type: Optional[str] = None
    fetch_status: FetchStatus = FetchStatus.unsupported
    text: str = ""
    retrieved_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    language: Optional[str] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.fetch_status == FetchStatus.ok and bool(self.text)


def normalize_text(text: str) -> str:
    """Collapse whitespace and normalize unicode for quote matching."""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace(" ", " ")
    text = text.replace("’", "'").replace("‘", "'")
    text = text.replace("“", '"').replace("”", '"')
    text = re.sub(r"\s+", " ", text).strip()
    return text


def html_to_text(html: str) -> str:
    cleaned = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.DOTALL | re.I)
    text = re.sub(r"<[^>]+>", " ", cleaned)
    return normalize_text(text)


def pdf_bytes_to_text(content: bytes) -> str:
    try:
        pages = extract_pages(content)
        return normalize_text("\n".join(page.get("text", "") for page in pages))
    except Exception:
        return ""


def bytes_to_text(content: bytes, content_type: str) -> Optional[str]:
    ct = (content_type or "").lower()
    # Check PDF magic bytes before the text/ catch-all — some servers serve PDFs
    # with Content-Type: text/plain.
    if content[:4] == b"%PDF" or "pdf" in ct:
        return pdf_bytes_to_text(content)
    if "html" in ct or ct.startswith("text/"):
        return html_to_text(content.decode("utf-8", errors="replace"))
    return None


def _token_set(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) > 1}


def token_overlap_ratio(left: str, right: str) -> float:
    a, b = _token_set(left), _token_set(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def quote_in_text(quote: str, text: str, *, min_recall: float = 0.85) -> bool:
    """Return True if quote appears exactly or its tokens are locally dense in text.

    The fuzzy path uses a sliding window (1.5× quote length) and checks that
    at least min_recall fraction of the quote's tokens appear in that window.
    Jaccard against the full document is not used because its denominator grows
    with document size, making the threshold effectively unreachable on real pages.
    """
    q = normalize_text(quote)
    t = normalize_text(text)
    if not q or not t:
        return False
    if q in t:
        return True
    q_toks = [tok for tok in re.findall(r"[a-z0-9]+", q.lower()) if len(tok) > 1]
    t_toks = [tok for tok in re.findall(r"[a-z0-9]+", t.lower()) if len(tok) > 1]
    if not q_toks or len(t_toks) < len(q_toks):
        return False
    q_set = frozenset(q_toks)
    window = len(q_toks) + len(q_toks) // 2  # 1.5× to absorb minor insertions
    if len(t_toks) <= window:
        # Target shorter than window — compare against the full token set
        return len(q_set & frozenset(t_toks)) / len(q_set) >= min_recall
    for i in range(len(t_toks) - window + 1):
        if len(q_set & frozenset(t_toks[i : i + window])) / len(q_set) >= min_recall:
            return True
    return False


def _guess_language(content_type: Optional[str], text: str) -> Optional[str]:
    if content_type:
        m = re.search(r"\blang=([a-z]{2,3})", content_type, re.I)
        if m:
            return m.group(1).lower()
    if "eur-lex" in text[:200].lower():
        return "en"
    return None


def fetch_source(
    url: str,
    *,
    client: Optional[httpx.Client] = None,
    timeout: float = 30.0,
) -> SourceFetchResult:
    """Fetch a URL and return normalized text with fetch status metadata."""
    close_client = client is None
    if client is None:
        client = httpx.Client(follow_redirects=True, timeout=timeout, headers=_HEADERS)

    result = SourceFetchResult(url=url)
    try:
        resp = client.get(url)
        result.final_url = str(resp.url)
        result.content_type = resp.headers.get("content-type", "")

        if resp.status_code in _BOT_PROTECTED_STATUSES:
            result.fetch_status = FetchStatus.bot_protected
            result.error = f"HTTP {resp.status_code}"
            return result

        if resp.status_code >= 400:
            result.fetch_status = FetchStatus.broken
            result.error = f"HTTP {resp.status_code}"
            return result

        text = bytes_to_text(resp.content, result.content_type)
        if text is None:
            result.fetch_status = FetchStatus.unsupported
            result.error = f"Unsupported content type: {result.content_type}"
            return result

        result.text = text
        result.fetch_status = FetchStatus.ok
        result.language = _guess_language(result.content_type, text)
        return result
    except httpx.ConnectError as exc:
        result.fetch_status = FetchStatus.broken
        result.error = str(exc)
        return result
    except httpx.RequestError as exc:
        msg = str(exc)
        if any(marker in msg for marker in _SSL_ERROR_MARKERS):
            result.fetch_status = FetchStatus.ssl_uncertain
        else:
            result.fetch_status = FetchStatus.broken
        result.error = msg
        return result
    finally:
        if close_client:
            client.close()


def cache_key_for_url(url: str) -> str:
    """Stable filesystem-safe key derived from URL host + path."""
    parsed = urlparse(url)
    slug = re.sub(r"[^a-z0-9]+", "_", f"{parsed.netloc}_{parsed.path}".lower()).strip("_")
    return slug[:120] or "source"
