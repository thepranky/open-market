#!/usr/bin/env python3
"""
resolve_uk_pdf_urls.py — DEPRECATED thin wrapper.

UK PDF resolution now lives in the shared, multi-jurisdiction resolver. This
shim translates the old CMA-only flags and forwards to
``resolve_case_index_pdf_urls.py``; it is kept for one release so existing
operator muscle memory keeps working.

    Use instead:
        python scripts/cases/discovery/resolve_case_index_pdf_urls.py \\
            --jurisdiction uk [--dry-run] [--all-outcomes] [--limit N]
            [--overwrite] [--delay F]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from resolve_case_index_pdf_urls import main as shared_main  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--all-outcomes", action="store_true",
                        help="Include Phase 1 cleared cases (default: Phase 2 only)")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--overwrite", action="store_true",
                        help="Re-resolve cases that already have a pdf_url")
    parser.add_argument("--delay", type=float, default=0.5)
    args = parser.parse_args()

    print(
        "DEPRECATED: resolve_uk_pdf_urls.py is a thin wrapper. "
        "Use resolve_case_index_pdf_urls.py --jurisdiction uk instead.\n",
        file=sys.stderr,
    )

    argv = ["--jurisdiction", "uk", "--delay", str(args.delay)]
    if args.dry_run:
        argv.append("--dry-run")
    if args.all_outcomes:
        argv.append("--all-outcomes")
    if args.limit:  # old script treated --limit 0 as "no limit" (falsy)
        argv += ["--limit", str(args.limit)]
    if args.overwrite:
        argv.append("--overwrite")
    return shared_main(argv)


if __name__ == "__main__":
    sys.exit(main())
