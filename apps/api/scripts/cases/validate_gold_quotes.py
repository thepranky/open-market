#!/usr/bin/env python3
"""
validate_gold_quotes.py — Verify that every quote_snippet in a gold YAML is
verbatim (or near-verbatim after PDF normalisation) against the cached page text.

Rules
-----
* quote_snippet must appear as a **contiguous** substring of the source page
  text after normalisation for:
    - whitespace / line-breaks collapsed to a single space
    - Unicode apostrophes / curly quotes → ASCII equivalents
    - soft hyphens (U+00AD) removed
    - PDF end-of-line hyphenation re-joined
* Legal numbered lists such as (i), (ii), (a), (b) are preserved and must
  appear in the normalised quote.
* Semantic paraphrases are rejected — the check is contiguous substring, not
  fragment similarity.
* If no PDF cache is available for the source document, the passage is flagged
  as "cache_unavailable" (warning, not error).

Usage (standalone)
------------------
    cd apps/api
    .venv/bin/python scripts/cases/validate_gold_quotes.py \\
        --gold-yaml ../../data/evals/gold/eu_google_fitbit_2021.gold.yaml \\
        --cache-dir ../../data/source_text
"""

import argparse
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

_API_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_API_DIR))

from app.shared.utils.pdf_extractor import DEFAULT_CACHE_DIR, load_cache


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

# Unicode apostrophe / quote variants to collapse before matching.
_APOSTROPHE_CHARS = "‘’ʼ′ʻ`"
_OPEN_QUOTE_CHARS = "“«‹"
_CLOSE_QUOTE_CHARS = "”»›"


def normalize_for_gold_match(text: str) -> str:
    """Normalise *text* for near-verbatim quote matching.

    Applies, in order:
    1. NFKC Unicode normalisation (ligatures, compatibility chars).
    2. Apostrophe / quotation-mark variants → ASCII ' and ".
    3. En-dash / em-dash → hyphen.
    4. Soft hyphen (U+00AD) removal.
    5. PDF end-of-line hyphenation re-join:  ``word-⏎rest`` → ``wordrest``.
    6. Collapse all remaining whitespace (tabs, newlines, multiple spaces) to
       a single ASCII space.
    7. Lowercase.

    Parenthetical list markers such as ``(i)``, ``(ii)``, ``(a)``, ``(b)``
    are intentionally preserved — their characters survive all steps above.
    """
    # Step 1 — NFKC
    text = unicodedata.normalize("NFKC", text)

    # Step 2 — apostrophes / quotes
    for ch in _APOSTROPHE_CHARS:
        text = text.replace(ch, "'")
    for ch in _OPEN_QUOTE_CHARS:
        text = text.replace(ch, '"')
    for ch in _CLOSE_QUOTE_CHARS:
        text = text.replace(ch, '"')

    # Step 3 — dashes
    text = text.replace("–", "-").replace("—", "-")

    # Step 4 — soft hyphen
    text = text.replace("­", "")

    # Step 5 — PDF hyphenation: "word-\nrest" → "wordrest"
    text = re.sub(r"(\w)-[ \t]*\n[ \t]*(\w)", r"\1\2", text)

    # Step 6 — collapse whitespace
    text = re.sub(r"[ \t]*\n[ \t]*", " ", text)  # newlines → space first
    text = re.sub(r"\s+", " ", text)

    # Step 7 — lowercase
    return text.lower().strip()


# ---------------------------------------------------------------------------
# Validation result types
# ---------------------------------------------------------------------------

@dataclass
class QuoteCheckResult:
    """Result of checking one gold passage against its source page."""
    market_name: str
    page: str
    quote_snippet: str
    passed: bool
    reason: str          # "ok", "not_found", "cache_unavailable", "no_page_in_cache"
    source_document_id: str = ""


@dataclass
class GoldQuoteReport:
    """Aggregated report for a single gold YAML file."""
    case_id: str
    total_checked: int
    failures: list[QuoteCheckResult]
    warnings: list[QuoteCheckResult]  # cache_unavailable etc.
    passed: int

    @property
    def has_failures(self) -> bool:
        return bool(self.failures)


# ---------------------------------------------------------------------------
# Core validation
# ---------------------------------------------------------------------------

def validate_quote_on_page(
    quote: str,
    page_text: str,
) -> bool:
    """Return True if *quote* appears verbatim (after normalisation) in *page_text*.

    The check is a **contiguous substring** test, not fragment matching, so
    paraphrases and rearranged sentences will fail.
    """
    nq = normalize_for_gold_match(quote)
    nt = normalize_for_gold_match(page_text)
    if not nq:
        return False
    return nq in nt


def validate_gold_passages(
    gold_yaml: dict,
    cache_dir: Path = DEFAULT_CACHE_DIR,
) -> GoldQuoteReport:
    """Validate every linked_source_passages[].quote_snippet in *gold_yaml*.

    Loads PDF page caches keyed by source_document_id (if present on the
    passage) or by the gold file's source_documents list.  If the cache is
    unavailable, the passage is added to *warnings* rather than *failures*.
    """
    case_id = gold_yaml.get("case_id", "unknown")

    # Build doc_id → page_cache lookup from gold's source_documents
    source_docs = gold_yaml.get("source_documents") or []
    cache_map: dict[str, Optional[dict]] = {}
    for doc in source_docs:
        doc_id = doc.get("doc_id", "")
        if doc_id and doc_id not in cache_map:
            cache_map[doc_id] = load_cache(doc_id, cache_dir)

    failures: list[QuoteCheckResult] = []
    warnings: list[QuoteCheckResult] = []
    passed = 0

    for market_list_key in ("product_markets_considered", "geographic_markets_considered"):
        for market in (gold_yaml.get(market_list_key) or []):
            market_name = market.get("name", "")
            for passage in (market.get("linked_source_passages") or []):
                page_str = str(passage.get("page", ""))
                quote = passage.get("quote_snippet", "")
                doc_id = passage.get("source_document_id", "")

                if not quote:
                    # Empty quote is a validation error
                    failures.append(QuoteCheckResult(
                        market_name=market_name,
                        page=page_str,
                        quote_snippet=quote,
                        passed=False,
                        reason="empty_quote",
                        source_document_id=doc_id,
                    ))
                    continue

                # Resolve cache: prefer passage-level doc_id, then first available
                page_cache = cache_map.get(doc_id) if doc_id else None
                if page_cache is None and cache_map:
                    # Fall back to first loaded cache when passage has no doc_id
                    page_cache = next(
                        (c for c in cache_map.values() if c is not None), None
                    )

                if page_cache is None:
                    warnings.append(QuoteCheckResult(
                        market_name=market_name,
                        page=page_str,
                        quote_snippet=quote,
                        passed=False,
                        reason="cache_unavailable",
                        source_document_id=doc_id,
                    ))
                    continue

                # Find the cited page in the cache
                try:
                    target_page_num = int(page_str)
                except (ValueError, TypeError):
                    target_page_num = None

                page_text: Optional[str] = None
                if target_page_num is not None:
                    for p in (page_cache.get("pages") or []):
                        if p.get("page_number") == target_page_num:
                            page_text = p.get("text", "")
                            break

                if page_text is None:
                    failures.append(QuoteCheckResult(
                        market_name=market_name,
                        page=page_str,
                        quote_snippet=quote,
                        passed=False,
                        reason="no_page_in_cache",
                        source_document_id=doc_id,
                    ))
                    continue

                if validate_quote_on_page(quote, page_text):
                    passed += 1
                else:
                    failures.append(QuoteCheckResult(
                        market_name=market_name,
                        page=page_str,
                        quote_snippet=quote[:120],
                        passed=False,
                        reason="not_found",
                        source_document_id=doc_id,
                    ))

    return GoldQuoteReport(
        case_id=case_id,
        total_checked=passed + len(failures),
        failures=failures,
        warnings=warnings,
        passed=passed,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def load_gold_yaml(path: Path) -> "tuple[Optional[dict], Optional[str]]":
    """Load and parse a gold YAML file.

    Returns ``(data, None)`` on success, or ``(None, error_message)`` on any
    failure so callers receive a clear human-readable message rather than a
    raw traceback.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        return data, None
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        location = (
            f" at line {mark.line + 1}, column {mark.column + 1}" if mark else ""
        )
        problem = getattr(exc, "problem", None) or str(exc)
        return None, f"YAML parse error in '{path}'{location}: {problem}"
    except OSError as exc:
        return None, f"Cannot open '{path}': {exc}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate gold YAML quote_snippet fields against PDF cache text"
    )
    parser.add_argument("--gold-yaml", required=True, help="Path to gold YAML file")
    parser.add_argument(
        "--cache-dir", default=str(DEFAULT_CACHE_DIR),
        help=f"PDF page cache directory (default: {DEFAULT_CACHE_DIR})",
    )
    args = parser.parse_args()

    gold_yaml, err = load_gold_yaml(Path(args.gold_yaml))
    if err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 1

    report = validate_gold_passages(gold_yaml, Path(args.cache_dir))

    print(f"Gold quote validation: {report.case_id}")
    print(f"  Checked : {report.total_checked}")
    print(f"  Passed  : {report.passed}")
    print(f"  Failures: {len(report.failures)}")
    print(f"  Warnings: {len(report.warnings)}")

    if report.warnings:
        print("\nWarnings (cache unavailable):")
        for w in report.warnings:
            print(f"  [{w.market_name}] p.{w.page} — {w.reason}")

    if report.failures:
        print("\nFailures:")
        for f in report.failures:
            print(f"  [{f.market_name}] p.{f.page} — {f.reason}")
            print(f"    Quote: {f.quote_snippet[:100]!r}")
        return 1

    print("\nAll checked quotes validated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
