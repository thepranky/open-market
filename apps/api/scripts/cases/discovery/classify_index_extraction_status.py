#!/usr/bin/env python3
"""
classify_index_extraction_status.py — backfill `extraction_status` on case-index entries.

An index entry is one of:
  extracted      — a canonical CaseRecord already exists for the case_id
  not_applicable — simplified procedure / no market-analysis sections (nothing to extract)
  pending        — substantive, not yet extracted (default)

Simplified clearances are detected by page count: EU simplified-procedure decisions
are ~2 pages and the extraction pipeline already SKIPs them. Page count needs no LLM
call. It is a heuristic — the threshold is configurable, and any entry we cannot fetch
or have no PDF for stays `pending` (never hide a substantive case behind a failed
fetch).

The script is idempotent and resumable: without --reclassify, entries already marked
non-`pending` are left alone, so a long backfill can resume after interruption.

Usage (from apps/api):
    .venv/bin/python scripts/cases/discovery/classify_index_extraction_status.py \\
        --jurisdiction eu --limit 5 --dry-run
"""

import argparse
import io
import re
import sys
import urllib.request
from pathlib import Path
from typing import Callable, Optional

import yaml

_API_DIR = Path(__file__).resolve().parents[3]
_REPO_ROOT = _API_DIR.parents[1]
_INDEX_DIR = _REPO_ROOT / "data" / "case_index"
_CASES_DIR = _REPO_ROOT / "data" / "cases"

# (url) -> page count, or None if it could not be determined.
PageCountFn = Callable[[str], Optional[int]]

_FIELD_RE = re.compile(r"^extraction_status:.*$", re.MULTILINE)


def _fetch_page_count(url: str, timeout: int = 30) -> Optional[int]:
    """Download a PDF and return its page count, or None on any failure."""
    try:
        from pypdf import PdfReader
    except ImportError:  # pragma: no cover - environment fallback
        from PyPDF2 import PdfReader
    try:
        data = urllib.request.urlopen(url, timeout=timeout).read()
        return len(PdfReader(io.BytesIO(data)).pages)
    except Exception:  # noqa: BLE001 - any fetch/parse failure → unknown
        return None


def classify_entry(
    entry: dict,
    *,
    canonical_exists: bool,
    page_count_fn: PageCountFn,
    max_simplified_pages: int,
) -> str:
    """Classify one entry. Pure given its inputs.

    Returns "extracted" / "not_applicable" / "pending" (all *confident*), or
    "unknown" when the PDF could not be fetched or there is no URL — distinct from
    a confident "pending" (a real, substantial decision). The caller must never
    overwrite a settled status with an "unknown" result.
    """
    if canonical_exists:
        return "extracted"
    pdf_url = entry.get("pdf_url")
    if not pdf_url:
        return "unknown"
    pages = page_count_fn(pdf_url)
    if pages is None:
        return "unknown"
    return "not_applicable" if pages <= max_simplified_pages else "pending"


def _apply_status(path: Path, status: str) -> None:
    """Set the extraction_status line in place, preserving the rest of the file."""
    text = path.read_text(encoding="utf-8")
    line = f"extraction_status: {status}"
    if _FIELD_RE.search(text):
        text = _FIELD_RE.sub(line, text, count=1)
    else:
        if not text.endswith("\n"):
            text += "\n"
        text += line + "\n"
    path.write_text(text, encoding="utf-8")


def _canonical_exists(jurisdiction: str, case_id: str) -> bool:
    return (_CASES_DIR / jurisdiction / f"{case_id}.yaml").exists()


def run(
    *,
    index_dir: Path,
    jurisdictions: list[str],
    case_id: Optional[str],
    limit: Optional[int],
    max_simplified_pages: int,
    reclassify: bool,
    dry_run: bool,
    page_count_fn: PageCountFn,
    canonical_exists_fn: Callable[[str, str], bool] = _canonical_exists,
) -> dict:
    """Classify entries across the given jurisdictions; return a count summary."""
    counts = {"extracted": 0, "not_applicable": 0, "pending": 0, "unknown": 0, "skipped": 0}
    processed = 0
    for jur in jurisdictions:
        jur_dir = index_dir / jur
        if not jur_dir.is_dir():
            continue
        for path in sorted(jur_dir.glob("*.yaml")):
            if case_id and path.stem != case_id:
                continue
            if limit is not None and processed >= limit:
                return counts

            entry = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            has_status = "extraction_status" in entry
            current = entry.get("extraction_status", "pending")
            canonical = canonical_exists_fn(jur, path.stem)

            # Resume: a settled non-pending status is kept unless --reclassify, but
            # we still upgrade to `extracted` for free when a canonical now exists.
            if not reclassify and current != "pending" and not (canonical and current != "extracted"):
                counts["skipped"] += 1
                continue

            result = classify_entry(
                entry,
                canonical_exists=canonical,
                page_count_fn=page_count_fn,
                max_simplified_pages=max_simplified_pages,
            )
            processed += 1
            counts[result] += 1

            # An "unknown" (no URL / failed fetch) must never overwrite a settled
            # classification — a transient 404 during --reclassify would otherwise
            # silently downgrade a correct not_applicable/extracted to pending.
            if result == "unknown":
                print(f"  {path.stem:<55} {current} (kept; could not determine)")
                continue

            marker = "" if result == current else " *"
            print(f"  {path.stem:<55} {result}{marker}")
            if not dry_run and (result != current or not has_status):
                _apply_status(path, result)

    return counts


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill extraction_status on case-index entries")
    parser.add_argument("--index-dir", default=str(_INDEX_DIR))
    parser.add_argument("--jurisdiction", default="eu", choices=["eu", "uk", "us", "all"],
                        help="Jurisdiction subdir to classify (default: eu)")
    parser.add_argument("--case-id", default=None, help="Classify a single case_id only")
    parser.add_argument("--limit", type=int, default=None, help="Stop after N classified entries")
    parser.add_argument("--max-simplified-pages", type=int, default=3,
                        help="Page count at or below which a case is not_applicable (default: 3)")
    parser.add_argument("--reclassify", action="store_true",
                        help="Re-evaluate entries already marked non-pending")
    parser.add_argument("--dry-run", action="store_true", help="Report without writing")
    args = parser.parse_args(argv)

    jurisdictions = ["eu", "uk", "us"] if args.jurisdiction == "all" else [args.jurisdiction]
    counts = run(
        index_dir=Path(args.index_dir),
        jurisdictions=jurisdictions,
        case_id=args.case_id,
        limit=args.limit,
        max_simplified_pages=args.max_simplified_pages,
        reclassify=args.reclassify,
        dry_run=args.dry_run,
        page_count_fn=_fetch_page_count,
    )
    tag = " (dry run)" if args.dry_run else ""
    print(
        f"\nDone{tag}: {counts['extracted']} extracted, "
        f"{counts['not_applicable']} not_applicable, {counts['pending']} pending, "
        f"{counts['unknown']} unknown, {counts['skipped']} skipped"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
