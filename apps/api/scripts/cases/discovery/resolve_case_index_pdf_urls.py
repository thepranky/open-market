#!/usr/bin/env python3
"""
resolve_case_index_pdf_urls.py — batch-resolve ``pdf_url`` across case-index
entries in every jurisdiction, through the shared resolver registry.

Adapters in ``pdf_resolvers.py`` own authority knowledge; this entrypoint owns
the cross-cutting batch concerns: loading entries through ``CaseIndexEntry`` so
resolver inputs match the schema, skipping existing PDFs, the outcome-relevance
filter, dry-run / overwrite behaviour, rate limiting, a surgical YAML write that
touches only the ``pdf_url`` line, and grouped reporting.

Exit code is 0 for ordinary unresolved cases (manual_required / not_found);
non-zero only for operational errors (bad jurisdiction, etc.).

Usage (from apps/api):
    .venv/bin/python scripts/cases/discovery/resolve_case_index_pdf_urls.py \\
        --jurisdiction us --dry-run --limit 5
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path
from typing import Callable, Optional

import yaml

_API_DIR = Path(__file__).resolve().parents[3]
_REPO_ROOT = _API_DIR.parents[1]
_INDEX_DIR = _REPO_ROOT / "data" / "case_index"

sys.path.insert(0, str(_API_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.cases.models.case_index import CaseIndexEntry  # noqa: E402
from pdf_resolvers import (  # noqa: E402
    PdfResolution,
    PdfResolver,
    build_default_resolvers,
    select_resolver,
)

_PDF_LINE_RE = re.compile(r"^pdf_url:.*$", re.MULTILINE)
_SOURCE_LINE_RE = re.compile(r"^(source_url:.*)$", re.MULTILINE)


def patch_pdf_url(yaml_text: str, pdf_url: str) -> str:
    """Insert or replace only the ``pdf_url`` line; leave every other byte intact.

    A new ``pdf_url`` is placed right after ``source_url`` (canonical order); if
    there is no ``source_url`` line it is appended at end of file.

    Lambda replacements are used so the URL is inserted literally — a value
    containing a ``\\1``-style sequence is never interpreted as a backreference.
    """
    if _PDF_LINE_RE.search(yaml_text):
        return _PDF_LINE_RE.sub(lambda _m: f"pdf_url: {pdf_url}", yaml_text, count=1)
    if _SOURCE_LINE_RE.search(yaml_text):
        return _SOURCE_LINE_RE.sub(
            lambda m: f"{m.group(1)}\npdf_url: {pdf_url}", yaml_text, count=1)
    if not yaml_text.endswith("\n"):
        yaml_text += "\n"
    return yaml_text + f"pdf_url: {pdf_url}\n"


def _new_counts() -> dict:
    return {
        "resolved": 0, "manual_required": 0, "not_found": 0, "error": 0,
        "skipped_existing": 0, "skipped_outcome": 0,
    }


def run(
    *,
    index_dir: Path,
    resolvers: list[PdfResolver],
    jurisdictions: list[str],
    authority: Optional[str],
    case_id: Optional[str],
    all_outcomes: bool,
    limit: Optional[int],
    overwrite: bool,
    delay: float,
    timeout: float,
    dry_run: bool,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict:
    """Resolve pdf_url across the given jurisdiction subdirs; return a count summary.

    Pure given ``resolvers`` and ``sleep_fn`` — tests inject a stub resolver and
    a no-op sleep, so no network or wall-clock time is needed.
    """
    counts = _new_counts()
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

            text = path.read_text(encoding="utf-8")
            data = yaml.safe_load(text) or {}
            try:
                entry = CaseIndexEntry.model_validate(data)
            except Exception as exc:  # noqa: BLE001 — surface, don't crash the batch
                counts["error"] += 1
                print(f"  ERR   {path.stem}  invalid entry: {exc}")
                continue

            if authority and entry.authority != authority:
                continue

            if entry.pdf_url and not overwrite:
                counts["skipped_existing"] += 1
                continue

            resolver = select_resolver(entry, resolvers)
            if resolver is None:
                counts["error"] += 1
                print(f"  ERR   {path.stem}  no resolver for {entry.jurisdiction}")
                continue

            outcome = getattr(entry.outcome, "value", entry.outcome)
            if (not all_outcomes and resolver.default_outcomes is not None
                    and outcome not in resolver.default_outcomes):
                counts["skipped_outcome"] += 1
                continue

            processed += 1
            sleep_fn(delay)
            res: PdfResolution = resolver.resolve(entry, timeout=timeout)
            counts[res.status] += 1
            _report(path.stem, outcome, res, dry_run)

            if res.status == "resolved" and res.pdf_url and not dry_run:
                path.write_text(patch_pdf_url(text, res.pdf_url), encoding="utf-8")

    return counts


def _report(case_id: str, outcome: str, res: PdfResolution, dry_run: bool) -> None:
    tag = {"resolved": "DRY " if dry_run else "→   ",
           "manual_required": "MAN ", "not_found": "MISS", "error": "ERR "}[res.status]
    if res.status == "resolved":
        print(f"  {tag} {case_id}  [{outcome}]  {res.reason}  {res.pdf_url}")
        return
    detail = ""
    if res.candidates:
        names = "; ".join(f"{c.label}({c.score})" for c in res.candidates[:4])
        detail = f"  candidates: {names}"
    print(f"  {tag} {case_id}  [{outcome}]  {res.reason}{detail}")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Batch-resolve pdf_url across case-index entries.")
    parser.add_argument("--index-dir", default=str(_INDEX_DIR))
    parser.add_argument("--jurisdiction", default="eu",
                        choices=["eu", "uk", "us", "all"],
                        help="Jurisdiction subdir to process (default: eu)")
    parser.add_argument("--authority", default=None,
                        help="Restrict to entries with this authority (e.g. DOJ)")
    parser.add_argument("--case-id", default=None,
                        help="Resolve a single case_id only")
    parser.add_argument("--all-outcomes", action="store_true",
                        help="Process every outcome, not just each adapter's default set")
    parser.add_argument("--limit", type=int, default=None,
                        help="Stop after N processed entries")
    parser.add_argument("--overwrite", action="store_true",
                        help="Re-resolve entries that already have a pdf_url")
    parser.add_argument("--delay", type=float, default=0.5,
                        help="Seconds between requests (default: 0.5)")
    parser.add_argument("--timeout", type=float, default=30.0,
                        help="Per-request timeout in seconds (default: 30)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report without writing any files")
    args = parser.parse_args(argv)

    jurisdictions = (["eu", "uk", "us"] if args.jurisdiction == "all"
                     else [args.jurisdiction])

    counts = run(
        index_dir=Path(args.index_dir),
        resolvers=build_default_resolvers(),
        jurisdictions=jurisdictions,
        authority=args.authority,
        case_id=args.case_id,
        all_outcomes=args.all_outcomes,
        limit=args.limit,
        overwrite=args.overwrite,
        delay=args.delay,
        timeout=args.timeout,
        dry_run=args.dry_run,
    )

    tag = " (dry run)" if args.dry_run else ""
    print(
        f"\nDone{tag}: resolved={counts['resolved']}  "
        f"manual_required={counts['manual_required']}  "
        f"not_found={counts['not_found']}  error={counts['error']}  "
        f"skipped_existing={counts['skipped_existing']}  "
        f"skipped_outcome={counts['skipped_outcome']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
