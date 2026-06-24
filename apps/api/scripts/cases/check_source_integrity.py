#!/usr/bin/env python3
"""
check_source_integrity.py — source validation gate for CompMap YAML case records.

For each source document:
  - fetches the URL and records HTTP status / content-type
  - checks whether doc_type keywords appear in the URL path
  - flags pdf_url fields that resolve to HTML (redirect to landing page)
  - flags URLs that look like generic portals / search pages
  - checks whether title tokens appear in the URL (basic mismatch detection)

For each source passage:
  - confirms source_document_id exists in the record's source_documents
  - confirms quote_snippet is non-empty
  - where text can be extracted (HTML or PDF), searches for the quote
  - when a page-level cache is available (data/source_text/), checks that
    the quote appears on the listed page; if not, searches all pages and
    reports the suggested corrected page or flags as possible hallucination

Issue levels:
  ERROR   — broken link, dangling source_document_id, empty quote snippet,
             pdf_url returning HTML
  WARNING — quote not found in fetched text, URL looks like a generic page,
             doc_type keywords absent from URL path, possible title/URL mismatch,
             quote found on different page than listed (page-level cache),
             quote not found on any page (page-level cache — possible hallucination)
  INFO    — check passed; text extraction notes

Usage:
    cd apps/api
    .venv/bin/python scripts/cases/check_source_integrity.py [--cases-dir ../../data/cases]
                                                       [--case-id eu_daimler_geely_smart_2020]
                                                       [--cache-dir ../../data/source_text]
                                                       [--timeout 20] [--verbose]
"""

import argparse
import io
import json
import re
import sys
import unicodedata
from dataclasses import dataclass, field as dc_field
from enum import Enum
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import httpx
import yaml

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


DATA_DIR = Path(__file__).resolve().parents[4] / "data" / "cases"
_DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[4] / "data" / "source_text"

HEADERS = {
    "User-Agent": "CompMap-IntegrityChecker/1.0 (open-source research tool)"
}

# Keywords expected to appear somewhere in the URL for a given doc_type.
# A WARNING fires when *none* match.
_DOC_TYPE_URL_HINTS: dict[str, list[str]] = {
    "alj_decision":   ["alj", "initial", "initialdecision", "decision"],
    "complaint":      ["complaint"],
    "court_opinion":  ["opinion", "order", "judgment", "decision", "recap"],
    "decision":       ["decision", "m.", "cases"],
    "final_report":   ["final", "report", "report_", "-report"],
    "press_release":  ["press", "release", "news"],
}

# URL path/query patterns that suggest a portal or search page rather than
# a specific document. Only applied to pdf_url (not case_page_url).
_GENERIC_PATH_RX = re.compile(
    r"(/search|/browse|[?&](q|query|search)=|^/[^/]{0,30}$)",
    re.I,
)

# Authorities (EC, DOJ, CMA, CourtListener, …) often use opaque numeric file IDs
# in PDF download URLs, e.g. /file/1573131/dl or /202120/m9660_3314_3.pdf.
# Party names and doc-type keywords will never appear in these paths.
# When detected, skip the title-token and doc-type keyword URL checks —
# the opaque ID itself is sufficient evidence the URL is document-specific.
_OPAQUE_ID_RX = re.compile(
    r"(/file/\d{5,}|/media/\d{5,}|/\d{5,}/|[0-9a-f]{20,}|/dl$"
    r"|/m\d{4,}(?:_[\w]+){2,}\.pdf)",
    re.I,
)

# Stop-words excluded when comparing title tokens against the URL.
_TITLE_STOP: set[str] = {
    "about", "against", "and", "case", "commission", "corporation",
    "court", "decision", "district", "european", "federal", "final",
    "ftc", "initial", "into", "the", "matter", "opinion", "report",
    "with",
}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

class Level(str, Enum):
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"


@dataclass
class Issue:
    level: Level
    case_id: str
    scope: str          # doc_id, passage_id, or "record"
    message: str
    url: Optional[str] = None

    def __str__(self) -> str:
        url_part = f"\n        url: {self.url}" if self.url else ""
        return f"  [{self.level.value:<7}] {self.scope}: {self.message}{url_part}"


@dataclass
class FetchResult:
    ok: bool
    status: Optional[int]
    content_type: str
    final_url: str
    content: Optional[bytes]
    error: Optional[str]


# ---------------------------------------------------------------------------
# Page-level cache helpers (used when data/source_text/ cache is available)
# ---------------------------------------------------------------------------

def _get_page_text(cache: dict, page_number: int) -> Optional[str]:
    """Return text for a specific 1-indexed page from a page cache dict, or None."""
    for p in cache.get("pages", []):
        if p["page_number"] == page_number:
            return p.get("text")
    return None


def _load_page_cache(doc_id: str, cache_dir: Path) -> Optional[dict]:
    """Return page cache for doc_id if the JSON file exists, else None."""
    path = cache_dir / f"{doc_id}.json"
    if path.exists():
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            return None
    return None


def find_quote_page(quote: str, page_cache: dict) -> Optional[int]:
    """
    Search all pages in *page_cache* for *quote*.

    Returns the first page_number where the quote is found, or None.
    """
    for page in page_cache.get("pages", []):
        ptext = page.get("text", "")
        if quote_found_in_text(quote, ptext):
            return page["page_number"]
    return None


# ---------------------------------------------------------------------------
# Text normalisation and quote matching
# ---------------------------------------------------------------------------

def _normalise(text: str) -> str:
    """Lowercase, ASCII-fold, strip punctuation, collapse whitespace."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def quote_found_in_text(quote: str, text: str, min_fragment: int = 28) -> bool:
    """
    Return True if *quote* appears approximately in *text*.

    Strategy:
    1. Fast-path: normalised quote is a direct substring of normalised text.
    2. Fragment search: slide a window of *min_fragment* chars across the
       normalised quote and look for each fragment in the normalised text.
       If two or more non-overlapping fragments match, the quote is found.
    """
    nq = _normalise(quote)
    nt = _normalise(text)

    if not nq or not nt:
        return False

    if nq in nt:
        return True

    if len(nq) < min_fragment:
        return False

    hits = 0
    step = max(1, min_fragment // 2)
    last_hit_end = 0
    for i in range(0, len(nq) - min_fragment + 1, step):
        fragment = nq[i : i + min_fragment]
        pos = nt.find(fragment, last_hit_end)
        if pos >= 0:
            hits += 1
            last_hit_end = pos + len(fragment)
            if hits >= 2:
                return True

    return False


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------

def _extract_html_text(content: bytes) -> str:
    html = content.decode("utf-8", errors="replace")
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.DOTALL | re.I)
    text = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", text).strip()


def _extract_pdf_text(content: bytes) -> Optional[str]:
    # Prefer pdfplumber — same extractor used by pdf_extractor.py / the cache builder,
    # so --no-cache results stay consistent with cached-mode results.
    if _HAS_PDFPLUMBER:
        try:
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                parts = [page.extract_text() or "" for page in pdf.pages]
            return "\n".join(parts)
        except Exception:
            pass
    if not _HAS_PYPDF:
        return None
    try:
        reader = pypdf.PdfReader(io.BytesIO(content))
        parts = [page.extract_text() or "" for page in reader.pages]
        return "\n".join(parts)
    except Exception:
        return None


def extract_text(content: bytes, content_type: str) -> Optional[str]:
    ct = content_type.lower()
    if "html" in ct:
        return _extract_html_text(content)
    if "pdf" in ct:
        return _extract_pdf_text(content)
    return None


# ---------------------------------------------------------------------------
# URL heuristics
# ---------------------------------------------------------------------------

def _pdf_url_looks_like_portal(final_url: str) -> bool:
    """True when a resolved URL resembles a portal/search page, not a document."""
    parsed = urlparse(final_url)
    path_and_query = parsed.path + ("?" + parsed.query if parsed.query else "")
    if _GENERIC_PATH_RX.search(path_and_query):
        return True
    path = parsed.path.rstrip("/")
    if not path:
        return True
    segments = [s for s in path.split("/") if s]
    # Suspicious if very short path with no digits and no long slug
    has_identifier = any(re.search(r"\d", s) or len(s) > 18 for s in segments)
    return len(segments) <= 1 and not has_identifier


def _url_uses_opaque_id(url: str) -> bool:
    """
    Return True when the URL uses an opaque numeric or hash-based file ID.

    Authorities such as the EC, DOJ, CMA, and CourtListener frequently assign
    internal numeric IDs to document downloads (e.g. /file/1573131/dl,
    /202120/m9660_3314_3.pdf).  Party names and doc-type keywords are never
    present in these paths, so title-token and doc-type keyword checks are
    inappropriate and would produce false-positive warnings.
    """
    return bool(_OPAQUE_ID_RX.search(urlparse(url).path))


def _doc_type_hints_in_url(doc_type: str, url: str) -> bool:
    """
    Return True when doc_type-related keywords appear in the URL, OR when the
    URL uses an opaque internal file ID (in which case the check is skipped).
    """
    if _url_uses_opaque_id(url):
        return True  # Opaque ID — keyword presence is not expected; skip check
    hints = _DOC_TYPE_URL_HINTS.get(doc_type)
    if not hints:
        return True
    url_lower = url.lower()
    return any(h in url_lower for h in hints)


def _title_tokens_in_url(title: str, url: str) -> bool:
    """
    Return True when at least one meaningful title token appears in the URL,
    OR when the URL uses an opaque internal file ID (check skipped).
    """
    if _url_uses_opaque_id(url):
        return True  # Opaque ID — title tokens are not expected in the path
    tokens = [
        t for t in re.findall(r"[a-zA-Z]{5,}", title)
        if t.lower() not in _TITLE_STOP
    ]
    if not tokens:
        return True  # Nothing meaningful to check
    url_lower = url.lower()
    return any(t.lower() in url_lower for t in tokens)


# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------

def fetch(client: httpx.Client, url: str, timeout: int) -> FetchResult:
    try:
        r = client.get(url, follow_redirects=True, timeout=timeout, headers=HEADERS)
        return FetchResult(
            ok=r.status_code < 400,
            status=r.status_code,
            content_type=r.headers.get("content-type", ""),
            final_url=str(r.url),
            content=r.content if r.status_code < 400 else None,
            error=None,
        )
    except httpx.TimeoutException:
        return FetchResult(False, None, "", url, None, "timeout")
    except httpx.RequestError as exc:
        return FetchResult(False, None, "", url, None, str(exc))


# ---------------------------------------------------------------------------
# Per-document checker
# ---------------------------------------------------------------------------

def check_document(
    client: httpx.Client,
    case_id: str,
    doc: dict,
    passage_count: int,
    timeout: int,
) -> tuple[list[Issue], Optional[str]]:
    """
    Validate one source document entry.

    Returns (issues, extracted_text_or_None).
    extracted_text is set only when passages are present and text was extractable.
    """
    issues: list[Issue] = []
    doc_id = doc.get("doc_id", "?")
    doc_type = doc.get("doc_type", "")
    title = doc.get("title", "")

    pdf_url = doc.get("pdf_url")
    case_page_url = doc.get("case_page_url")
    generic_url = doc.get("url")

    # The URL we actually use for integrity checking is the most specific one.
    primary_url = pdf_url or case_page_url or generic_url

    if not primary_url:
        issues.append(Issue(Level.ERROR, case_id, doc_id,
                            "No URL found (pdf_url, case_page_url, and url are all absent)"))
        return issues, None

    result = fetch(client, primary_url, timeout)

    if not result.ok:
        err = result.error or f"HTTP {result.status}"
        issues.append(Issue(Level.ERROR, case_id, doc_id,
                            f"Broken link ({err})", url=primary_url))
        return issues, None

    ct = result.content_type.split(";")[0].strip().lower()
    ct_display = ct or "unknown content-type"

    # pdf_url returning HTML instead of PDF
    if pdf_url and "html" in ct and "pdf" not in ct:
        issues.append(Issue(Level.WARNING, case_id, doc_id,
                            "pdf_url returned text/html, not application/pdf — "
                            "may be redirecting to a case landing page",
                            url=primary_url))

    # pdf_url resolving to a portal/search page
    if pdf_url and _pdf_url_looks_like_portal(result.final_url):
        issues.append(Issue(Level.WARNING, case_id, doc_id,
                            "pdf_url resolved to a URL that resembles a portal or "
                            "search page rather than a specific document",
                            url=result.final_url))

    # doc_type keyword in URL
    if not _doc_type_hints_in_url(doc_type, primary_url):
        issues.append(Issue(Level.WARNING, case_id, doc_id,
                            f"doc_type '{doc_type}' — none of its expected URL keywords "
                            f"appear in the URL path; the URL may point to the wrong document",
                            url=primary_url))

    # Title/URL consistency
    if title and not _title_tokens_in_url(title, primary_url):
        issues.append(Issue(Level.WARNING, case_id, doc_id,
                            f"No title token from \"{title[:60]}\" found in URL — "
                            "possible title/URL mismatch",
                            url=primary_url))

    # Text extraction (only when there are passages to check)
    extracted_text: Optional[str] = None
    if passage_count > 0 and result.content:
        extracted_text = extract_text(result.content, result.content_type)
        if extracted_text is None:
            if "pdf" in ct:
                if not _HAS_PYPDF:
                    issues.append(Issue(Level.INFO, case_id, doc_id,
                                        "PDF text extraction skipped — install pypdf to enable quote checks"))
                else:
                    issues.append(Issue(Level.WARNING, case_id, doc_id,
                                        "Could not extract text from PDF (possibly encrypted or image-only)"))
            else:
                issues.append(Issue(Level.INFO, case_id, doc_id,
                                    f"Text extraction not supported for content-type '{ct_display}'"))

    issues.append(Issue(Level.INFO, case_id, doc_id,
                        f"Link OK (HTTP {result.status}, {ct_display})"))
    return issues, extracted_text


# ---------------------------------------------------------------------------
# Per-passage checker
# ---------------------------------------------------------------------------

def check_passage(
    case_id: str,
    passage: dict,
    doc_map: dict[str, dict],
    text_map: dict[str, Optional[str]],
    page_caches: Optional[dict[str, dict]] = None,
) -> list[Issue]:
    """
    Validate one source_passage entry.

    When *page_caches* is provided (dict mapping doc_id → page cache dict),
    performs additional page-level grounding checks:
      - verifies the quote appears on the listed page number;
      - if not, searches all pages and suggests the correct page;
      - if not found anywhere, flags as a possible hallucination.
    """
    issues: list[Issue] = []
    pid = passage.get("passage_id", "?")
    doc_id = passage.get("source_document_id", "")
    quote = passage.get("quote_snippet", "")

    # Dangling reference
    if not doc_id:
        issues.append(Issue(Level.ERROR, case_id, pid,
                            "Missing source_document_id"))
        return issues

    if doc_id not in doc_map:
        issues.append(Issue(Level.ERROR, case_id, pid,
                            f"source_document_id '{doc_id}' not found in this "
                            "record's source_documents"))
        return issues

    # Empty quote
    if not quote or not quote.strip():
        issues.append(Issue(Level.ERROR, case_id, pid,
                            "quote_snippet is empty or blank"))
        return issues

    # --- Page-level grounding (when cache is available) ---
    if page_caches is not None:
        page_cache = page_caches.get(doc_id)
        listed_page_str = passage.get("page")
        if page_cache is not None and listed_page_str is not None:
            try:
                listed_page = int(listed_page_str)
            except (TypeError, ValueError):
                listed_page = None

            if listed_page is not None:
                page_text = _get_page_text(page_cache, listed_page)
                if page_text is None:
                    issues.append(Issue(Level.WARNING, case_id, pid,
                                        f"Listed page {listed_page} does not exist in "
                                        f"extracted cache (document has "
                                        f"{page_cache.get('page_count', '?')} pages)"))
                elif quote_found_in_text(quote, page_text):
                    issues.append(Issue(Level.INFO, case_id, pid,
                                        f"Quote grounded: found on listed page {listed_page}"))
                    return issues  # page-level check passed; skip whole-doc check
                else:
                    # Search all pages for the quote
                    found_page = find_quote_page(quote, page_cache)
                    if found_page is not None:
                        issues.append(Issue(Level.WARNING, case_id, pid,
                                            f"Quote not on listed page {listed_page} — "
                                            f"found on page {found_page} instead; "
                                            "run repair_source_passages.py to fix"))
                    else:
                        issues.append(Issue(Level.WARNING, case_id, pid,
                                            f"Quote not found on listed page {listed_page} "
                                            "or any other page in extracted text — "
                                            "possible hallucination; "
                                            "run repair_source_passages.py to investigate"))
                    return issues

    # --- Whole-document fallback check ---
    text = text_map.get(doc_id)
    if text is None:
        issues.append(Issue(Level.INFO, case_id, pid,
                            "Quote check skipped — no extracted text for "
                            f"'{doc_id}' (broken link or extraction failed)"))
        return issues

    if quote_found_in_text(quote, text):
        issues.append(Issue(Level.INFO, case_id, pid,
                            "Quote found in document text"))
    else:
        paragraph = passage.get("paragraph")
        review_status = passage.get("review_status", "")
        para_hint = (
            f" paragraph='{paragraph}'" if paragraph else ""
        )
        status_hint = (
            " review_status is spot_checked but quote unverifiable — downgrade to unreviewed."
            if review_status == "spot_checked" else ""
        )
        issues.append(Issue(Level.WARNING, case_id, pid,
                            f"Quote snippet not found in extracted document text "
                            f"(page={passage.get('page', '?')}{para_hint}) — "
                            "verify verbatim text against the linked source; "
                            "may be paraphrase, OCR/encoding variation, or wrong locator."
                            + status_hint))

    return issues


# ---------------------------------------------------------------------------
# Per-record entry point
# ---------------------------------------------------------------------------

def check_record(
    client: httpx.Client,
    record: dict,
    timeout: int,
    cache_dir: Optional[Path] = None,
) -> list[Issue]:
    issues: list[Issue] = []
    case_id = record.get("case_id", "?")
    source_docs: list[dict] = record.get("source_documents") or []
    passages: list[dict] = record.get("source_passages") or []

    doc_map = {d["doc_id"]: d for d in source_docs if d.get("doc_id")}

    # Build a map of which doc_ids have passages, for targeted fetching
    doc_passage_counts: dict[str, int] = {}
    for p in passages:
        did = p.get("source_document_id", "")
        doc_passage_counts[did] = doc_passage_counts.get(did, 0) + 1

    # Check each source document
    text_map: dict[str, Optional[str]] = {}
    for doc in source_docs:
        doc_id = doc.get("doc_id", "?")
        pcount = doc_passage_counts.get(doc_id, 0)
        doc_issues, extracted = check_document(client, case_id, doc, pcount, timeout)
        issues.extend(doc_issues)
        text_map[doc_id] = extracted

    # Load page-level caches when cache_dir is provided
    page_caches: Optional[dict[str, dict]] = None
    if cache_dir is not None:
        page_caches = {}
        for doc in source_docs:
            doc_id = doc.get("doc_id", "")
            if doc_id:
                loaded = _load_page_cache(doc_id, cache_dir)
                if loaded is not None:
                    page_caches[doc_id] = loaded

    # Check each source passage
    for passage in passages:
        issues.extend(check_passage(
            case_id, passage, doc_map, text_map, page_caches=page_caches
        ))

    return issues


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _classify(issues: list[Issue]) -> tuple[int, int, int]:
    errors = sum(1 for i in issues if i.level == Level.ERROR)
    warnings = sum(1 for i in issues if i.level == Level.WARNING)
    infos = sum(1 for i in issues if i.level == Level.INFO)
    return errors, warnings, infos


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Source integrity gate for CompMap YAML case records"
    )
    parser.add_argument(
        "--cases-dir",
        default=str(DATA_DIR),
        help=f"Path to data/cases directory (default: {DATA_DIR})",
    )
    parser.add_argument(
        "--case-id",
        default=None,
        help=(
            "Check only this case (e.g. eu_daimler_geely_smart_2020). "
            "Matches <cases-dir>/**/<case-id>.yaml and "
            "<cases-dir>/**/<case-id>.market_definition.draft.yaml."
        ),
    )
    parser.add_argument(
        "--timeout", type=int, default=20,
        help="HTTP request timeout in seconds (default: 20)",
    )
    parser.add_argument(
        "--cache-dir",
        default=str(_DEFAULT_CACHE_DIR),
        help=f"Path to source_text cache directory (default: {_DEFAULT_CACHE_DIR})",
    )
    parser.add_argument(
        "--no-cache", action="store_true",
        help="Disable page-level cache checks even if cache files exist",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Print INFO messages in addition to ERROR and WARNING",
    )
    args = parser.parse_args()

    cases_dir = Path(args.cases_dir)

    if args.case_id:
        candidates = [
            cases_dir / f"{args.case_id}.yaml",
            *cases_dir.rglob(f"{args.case_id}.yaml"),
            *cases_dir.rglob(f"{args.case_id}.market_definition.draft.yaml"),
        ]
        # Deduplicate while preserving order
        seen: set[Path] = set()
        yaml_files = []
        for p in candidates:
            if p.exists() and p not in seen:
                seen.add(p)
                yaml_files.append(p)
        if not yaml_files:
            print(
                f"No file found for case-id '{args.case_id}' under {cases_dir}.\n"
                f"Expected one of:\n"
                f"  {cases_dir}/**/{args.case_id}.yaml\n"
                f"  {cases_dir}/**/{args.case_id}.market_definition.draft.yaml",
                file=sys.stderr,
            )
            return 1
    else:
        yaml_files = sorted(cases_dir.rglob("*.yaml"))
        if not yaml_files:
            print(f"No YAML files found under {cases_dir}", file=sys.stderr)
            return 1

    cache_dir: Optional[Path] = None if args.no_cache else Path(args.cache_dir)
    cache_note = f" (page cache: {cache_dir})" if cache_dir else " (page cache: disabled)"

    print(f"CompMap Source Integrity Check{cache_note}")
    print(f"Checking {len(yaml_files)} case file(s) …\n")

    total_errors = total_warnings = 0

    with httpx.Client(follow_redirects=True) as client:
        for path in yaml_files:
            with open(path) as f:
                record = yaml.safe_load(f)

            case_id = record.get("case_id", path.stem)
            issues = check_record(client, record, args.timeout, cache_dir=cache_dir)
            errors, warnings, infos = _classify(issues)
            total_errors += errors
            total_warnings += warnings

            # Case-level header
            if errors:
                marker = "✗"
            elif warnings:
                marker = "⚠"
            else:
                marker = "✓"

            ndocs = len(record.get("source_documents") or [])
            npass = len(record.get("source_passages") or [])
            print(f"{marker} {case_id}  ({ndocs} doc(s), {npass} passage(s))  "
                  f"{errors} error(s), {warnings} warning(s)")

            for issue in issues:
                if issue.level == Level.ERROR:
                    print(str(issue))
                elif issue.level == Level.WARNING:
                    print(str(issue))
                elif args.verbose and issue.level == Level.INFO:
                    print(str(issue))

            print()

    print("─" * 60)
    print(f"Total: {len(yaml_files)} case(s) — "
          f"{total_errors} error(s), {total_warnings} warning(s)")

    if total_errors:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
