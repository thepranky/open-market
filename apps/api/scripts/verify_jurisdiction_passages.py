#!/usr/bin/env python3
"""Verify jurisdiction source_passages against authoritative source text.

Full implementation lands in PR 3 (passage gate). This stub defines the CLI surface.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = REPO_ROOT / "data" / "jurisdictions"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ground jurisdiction source_passages in linked authoritative sources.",
    )
    parser.add_argument(
        "--jurisdiction",
        "-j",
        help="Jurisdiction id to verify (default: all)",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Attempt safe auto-repairs where supported",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DATA_DIR,
        help=f"Jurisdiction YAML directory (default: {DATA_DIR})",
    )
    args = parser.parse_args()

    target = args.jurisdiction or "all"
    print(
        "verify_jurisdiction_passages: not implemented yet "
        f"(target={target}, data_dir={args.data_dir}). "
        "See PR 3 in docs/jurisdiction-verification-build.md.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
