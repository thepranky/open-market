#!/usr/bin/env python3
"""Deprecated wrapper for run_bulk_promotion.py."""

from __future__ import annotations

import sys
from pathlib import Path

_API_DIR = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_API_DIR))

from scripts.cases.promote.run_bulk_promotion import (  # noqa: E402,F401
    count_markets,
    discover_candidates,
    is_promotable,
    main as _run_main,
    parse_full_depth_readiness,
    review_status,
    write_batch_state,
)


def main(argv: list[str] | None = None) -> int:
    print(
        "DEPRECATED: bulk_promote_pass.py is deprecated; use run_bulk_promotion.py.",
        file=sys.stderr,
    )
    return _run_main(argv)


if __name__ == "__main__":
    sys.exit(main())
