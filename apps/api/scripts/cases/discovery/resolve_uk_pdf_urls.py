#!/usr/bin/env python3
"""
resolve_uk_pdf_urls.py — Patch pdf_url into CMA case_index/uk/ YAML files.

For each CMA case_index entry without a pdf_url, fetches the GOV.UK case page,
finds the best PDF (final report > provisional findings > main report), and
patches the field into the YAML.

Targets Phase 2 cases by default (blocked + cleared_with_conditions) since
Phase 1 clearances are brief decision letters without substantive analysis.

Usage:
    python apps/api/scripts/cases/discovery/resolve_uk_pdf_urls.py [--dry-run] [--all-outcomes]
                                                     [--limit N] [--overwrite] [--delay F]

Options:
    --dry-run       Print resolved URLs without writing any files.
    --all-outcomes  Include Phase 1 cleared cases too.
    --limit N       Stop after N cases written.
    --overwrite     Re-resolve cases that already have a pdf_url.
    --delay F       Seconds between HTTP requests (default: 0.5).
"""
import argparse
import re
import sys
import time
from pathlib import Path
from typing import Optional

import requests

REPO_ROOT = Path(__file__).resolve().parents[5]
UK_INDEX_DIR = REPO_ROOT / "data" / "case_index" / "uk"

# Outcomes that have substantive Phase 2 merger inquiry reports.
PHASE2_OUTCOMES = {"blocked", "cleared_with_conditions", "referred"}

# PDF asset hosts used by GOV.UK (old and new).
ASSET_HOSTS = (
    "assets.publishing.service.gov.uk",
    "assets.digital.cabinet-office.gov.uk",
)

# ---------------------------------------------------------------------------
# PDF ranking
# ---------------------------------------------------------------------------

# Filename substrings that identify the main inquiry report, in priority order.
# First match wins.
_REPORT_PATTERNS: list[tuple[int, re.Pattern]] = [
    # Score 100: explicit "final_report" or "final report" in name, not an order/undertaking
    (100, re.compile(r"final.report", re.IGNORECASE)),
    # Score 90: "inquiry_report" or "main_report"
    (90, re.compile(r"(inquiry.report|main.report)", re.IGNORECASE)),
    # Score 80: provisional findings report (standalone, not appendices)
    (80, re.compile(r"provisional.findings.report", re.IGNORECASE)),
    # Score 70: bare "provisional_findings" (not appendices, not notices)
    (70, re.compile(r"provisional.findings(?!.*(appendix|appendices|notice|summary))", re.IGNORECASE)),
    # Score 60: phase 1 full decision text (fallback for Phase 1 --all-outcomes mode)
    (60, re.compile(r"full.text.*(phase.1|phase1)", re.IGNORECASE)),
    # Score 50: any file containing "report" not classified above
    (50, re.compile(r"report", re.IGNORECASE)),
    # Score 45: Phase 1 full text decision (ftd = "full text decision", or bare "full_text")
    (45, re.compile(r"(ftd|full.?text.?decision|fulltext.decision|full.?text)", re.IGNORECASE)),
    # Score 42: Phase 1 decision documents — any filename with "decision" in it.
    # The disqualify list already excludes notices/orders/undertakings, so "decision" alone
    # reliably identifies the Phase 1 decision document.
    (42, re.compile(r"decision", re.IGNORECASE)),
    # Score 42: FNTQ = "Found Not To Qualify" — the Phase 1 clearance decision for mergers
    # that don't meet the jurisdictional threshold. Published as a standalone document.
    (42, re.compile(r"fntq", re.IGNORECASE)),
    # Score 38: non-confidential version published for the public — almost always the decision.
    (38, re.compile(r"non.confidential", re.IGNORECASE)),
    # Score 40: old Competition Commission numbered report files (e.g. "547.pdf", "41-08.pdf")
    # These are the CC's main inquiry publications identified by case number.
    (40, re.compile(r"^\d[\d\-]+\.pdf$", re.IGNORECASE)),
]

# Filename substrings that disqualify a PDF regardless of score.
_DISQUALIFY = re.compile(
    r"(final.order|interim.order|final.undertaking|interim.undertaking"
    r"|notice|summary|appendix|appendices|glossary|annex"
    r"|response|submission|working.paper|issues.statement"
    r"|survey|research|timetable|extension|cancellation"
    r"|explanatory.note|draft.final|draft_final"
    r"|terms.of.reference|ieo|directions|commencement"
    r"|derogation|revocation.order|revocation_order)",
    re.IGNORECASE,
)


def _score_pdf(url: str) -> int:
    """Return a priority score for a PDF URL. 0 = disqualified."""
    filename = url.rsplit("/", 1)[-1]
    if _DISQUALIFY.search(filename):
        return 0
    for score, pattern in _REPORT_PATTERNS:
        if pattern.search(filename):
            return score
    return 0  # no match


def _best_pdf(pdf_urls: list[str]) -> Optional[str]:
    """Return the highest-scoring PDF URL, or None."""
    scored = [(url, _score_pdf(url)) for url in pdf_urls]
    scored = [(url, s) for url, s in scored if s > 0]
    if not scored:
        # Fallback: if exactly one PDF survived disqualification, it IS the document.
        # This covers Phase 1 cases where the only PDF is named after the case (e.g. Acteon_Viking.pdf).
        survivors = [u for u in pdf_urls if not _DISQUALIFY.search(u.rsplit("/", 1)[-1])]
        if len(survivors) == 1:
            return survivors[0]
        return None
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[0][0]


# ---------------------------------------------------------------------------
# Fetch and parse
# ---------------------------------------------------------------------------

def _fetch_pdf_links(page_url: str, session: requests.Session) -> list[str]:
    """Fetch a GOV.UK case page and return all PDF asset links."""
    r = session.get(page_url, timeout=20)
    if r.status_code == 404:
        return []
    r.raise_for_status()
    html = r.text
    # Both href="..." and href='...'
    found = re.findall(r'''href=["']([^"']+\.pdf)["']''', html, re.IGNORECASE)
    # Keep only known asset hosts
    return [u for u in found if any(h in u for h in ASSET_HOSTS)]


# ---------------------------------------------------------------------------
# YAML patching
# ---------------------------------------------------------------------------

def _read_yaml_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _patch_pdf_url(yaml_text: str, pdf_url: str) -> str:
    """
    Insert or replace the pdf_url field in the YAML text.
    Inserts after the source_url line to keep fields grouped.
    If pdf_url already exists, replaces it.
    """
    # Replace existing pdf_url line
    if re.search(r"^pdf_url:", yaml_text, re.MULTILINE):
        return re.sub(
            r"^pdf_url:.*$",
            f"pdf_url: {pdf_url}",
            yaml_text,
            flags=re.MULTILINE,
        )
    # Insert after source_url line
    return re.sub(
        r"(^source_url:.*$)",
        rf"\1\npdf_url: {pdf_url}",
        yaml_text,
        flags=re.MULTILINE,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _parse_field(yaml_text: str, field: str) -> Optional[str]:
    m = re.search(rf"^{field}:\s*(.+)$", yaml_text, re.MULTILINE)
    return m.group(1).strip().strip("'\"") if m else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve and patch pdf_url into CMA case_index YAMLs.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--all-outcomes", action="store_true",
                        help="Include Phase 1 cleared cases (default: Phase 2 only)")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--overwrite", action="store_true",
                        help="Re-resolve cases that already have pdf_url")
    parser.add_argument("--delay", type=float, default=0.5)
    args = parser.parse_args()

    yamls = sorted(UK_INDEX_DIR.glob("*.yaml"))
    print(f"Found {len(yamls)} UK case_index entries")

    session = requests.Session()
    session.headers["User-Agent"] = (
        "Meridian-research-bot/1.0 (academic legal research; bhavyasharma1510@gmail.com)"
    )

    resolved = skipped_phase1 = skipped_exists = no_pdf = errors = 0

    for path in yamls:
        if args.limit and resolved >= args.limit:
            print(f"\n[limit {args.limit} reached — stopping]")
            break

        text = _read_yaml_text(path)
        outcome = _parse_field(text, "outcome")
        source_url = _parse_field(text, "source_url")
        existing_pdf = _parse_field(text, "pdf_url")
        case_id = _parse_field(text, "case_id")

        if not args.all_outcomes and outcome not in PHASE2_OUTCOMES:
            skipped_phase1 += 1
            continue

        if existing_pdf and not args.overwrite:
            skipped_exists += 1
            continue

        if not source_url:
            print(f"  WARN  {case_id}  no source_url — skipping")
            continue

        time.sleep(args.delay)
        try:
            pdf_links = _fetch_pdf_links(source_url, session)
        except Exception as e:
            print(f"  ERR   {case_id}  {e}")
            errors += 1
            continue

        best = _best_pdf(pdf_links)
        if not best:
            # Show the first few raw links to aid manual inspection
            raw_display = "; ".join(u.rsplit("/", 1)[-1] for u in pdf_links[:4])
            print(f"  MISS  {case_id}  [{outcome}]  ({len(pdf_links)} PDFs, none matched: {raw_display})")
            no_pdf += 1
            continue

        print(f"  {'DRY' if args.dry_run else '→  '}  {case_id}  [{outcome}]  {best.rsplit('/', 1)[-1]}")

        if not args.dry_run:
            patched = _patch_pdf_url(text, best)
            path.write_text(patched, encoding="utf-8")

        resolved += 1

    print(
        f"\nDone. resolved={resolved}  skipped_phase1={skipped_phase1}"
        f"  skipped_exists={skipped_exists}  no_pdf_found={no_pdf}  errors={errors}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
