#!/usr/bin/env python3
"""
resolve_eu_pdf_urls.py — DEPRECATED thin wrapper.

EU PDF resolution now lives in the shared, multi-jurisdiction resolver. This
shim translates the old EU-only flags and forwards to
``resolve_case_index_pdf_urls.py``; it is kept for one release so existing
operator muscle memory keeps working.

    Use instead:
        python scripts/cases/discovery/resolve_case_index_pdf_urls.py \\
            --jurisdiction eu [--dry-run] [--limit N] [--overwrite]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from resolve_case_index_pdf_urls import main as shared_main  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--jurisdiction", default="eu")
    parser.add_argument("--force", action="store_true",
                        help="Re-resolve even if pdf_url already set")
    args = parser.parse_args()

    print(
        "DEPRECATED: resolve_eu_pdf_urls.py is a thin wrapper. "
        "Use resolve_case_index_pdf_urls.py --jurisdiction eu instead.\n",
        file=sys.stderr,
    )

    argv = ["--jurisdiction", args.jurisdiction]
    if args.dry_run:
        argv.append("--dry-run")
    if args.limit:
        argv += ["--limit", str(args.limit)]
    if args.force:
        argv.append("--overwrite")
    return shared_main(argv)


if __name__ == "__main__":
    sys.exit(main())
