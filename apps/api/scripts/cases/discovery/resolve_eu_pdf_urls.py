"""
resolve_eu_pdf_urls.py — batch-populate pdf_url in EU case index YAMLs.

For each index entry that lacks a pdf_url, attempts to resolve the PDF via
the EUR-Lex cellar endpoint (works for all Phase I / non-opposition EC decisions).
Phase II cases (cleared_with_conditions, blocked) are skipped — they need manual URLs.

Usage:
    python apps/api/scripts/cases/discovery/resolve_eu_pdf_urls.py [--dry-run] [--limit N] [--jurisdiction eu]

Options:
    --dry-run       Print what would be written without modifying files.
    --limit N       Stop after resolving N URLs (useful for testing).
    --jurisdiction  Which jurisdiction subfolder to process (default: eu).
    --force         Re-resolve even if pdf_url is already set.
"""

import argparse
import re
import sys
import time
from pathlib import Path

import httpx
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[5]
_INDEX_DIR = _REPO_ROOT / "data" / "case_index"

_CELLAR_TEMPLATE = "http://publications.europa.eu/resource/celex/{celex}.ENG.pdf"
_HEADERS = {"Accept": "application/pdf, */*;q=0.5"}

# Outcomes that require manual PDF URL (not in EUR-Lex)
_MANUAL_OUTCOMES = {"cleared_with_conditions", "blocked", "annulled"}


def _resolve_celex(source_url: str, decision_date: str, timeout: int = 20) -> str | None:
    m = re.search(r"M\.(\d+)$", source_url or "")
    if not m:
        return None
    case_number = m.group(1)
    year = (decision_date or "")[:4]
    if not year.isdigit():
        return None
    celex = f"3{year}M{case_number}"
    url = _CELLAR_TEMPLATE.format(celex=celex)
    try:
        with httpx.Client(follow_redirects=True, timeout=timeout) as client:
            resp = client.head(url, headers=_HEADERS)
            if resp.status_code == 200 and "pdf" in resp.headers.get("content-type", ""):
                return str(resp.url)
    except Exception:
        pass
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch-resolve pdf_url for EU case index YAMLs")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--jurisdiction", default="eu")
    parser.add_argument("--force", action="store_true", help="Re-resolve even if pdf_url already set")
    args = parser.parse_args()

    index_dir = _INDEX_DIR / args.jurisdiction
    if not index_dir.exists():
        print(f"ERROR: {index_dir} does not exist", file=sys.stderr)
        sys.exit(1)

    files = sorted(index_dir.glob("*.yaml"))
    resolved = skipped_manual = skipped_already = skipped_no_url = failed = 0

    for path in files:
        with open(path) as fh:
            entry = yaml.safe_load(fh)

        outcome = entry.get("outcome", "")
        existing = entry.get("pdf_url")

        # Skip Phase II — need manual URL
        if outcome in _MANUAL_OUTCOMES:
            skipped_manual += 1
            continue

        # Skip if already resolved (unless --force)
        if existing and not args.force:
            skipped_already += 1
            continue

        source_url = entry.get("source_url", "")
        decision_date = entry.get("decision_date", "")

        if not source_url:
            skipped_no_url += 1
            continue

        pdf_url = _resolve_celex(source_url, decision_date)

        if pdf_url:
            resolved += 1
            print(f"  OK  {path.stem}: {pdf_url}")
            if not args.dry_run:
                entry["pdf_url"] = pdf_url
                with open(path, "w") as fh:
                    yaml.dump(entry, fh, allow_unicode=True, sort_keys=False)
        else:
            failed += 1
            print(f"  --  {path.stem}: no PDF found")

        # Polite rate limiting — EUR-Lex cellar handles HEAD requests fast
        # but we don't want to hammer it
        time.sleep(0.1)

        if args.limit and resolved >= args.limit:
            print(f"\nReached --limit {args.limit}, stopping.")
            break

    print(
        f"\nDone. resolved={resolved}  skipped_already={skipped_already}  "
        f"skipped_manual={skipped_manual}  skipped_no_url={skipped_no_url}  failed={failed}"
    )


if __name__ == "__main__":
    main()
