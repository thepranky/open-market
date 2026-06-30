#!/usr/bin/env python3
"""Deprecated wrapper for run_case_promotion.py."""

from __future__ import annotations

import sys
from pathlib import Path

_API_DIR = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_API_DIR))

from scripts.cases.promote.run_case_promotion import (  # noqa: E402,F401
    check_draft_integrity,
    find_merged_draft,
    main as _run_main,
    unresolved_conflicts,
)


def main(argv: list[str] | None = None) -> int:
    print(
        "DEPRECATED: promote_case_pipeline.py is deprecated; use run_case_promotion.py.",
        file=sys.stderr,
    )
    return _run_main(argv)


if __name__ == "__main__":
    sys.exit(main())
