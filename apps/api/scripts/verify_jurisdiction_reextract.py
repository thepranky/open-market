#!/usr/bin/env python3
"""Diff YAML threshold values against passage-based re-extraction."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = REPO_ROOT / "data" / "jurisdictions"

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.jurisdiction_regression import diff_reextract
from app.services.threshold_engine import load_all_jurisdictions, load_jurisdiction


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jurisdiction", "-j")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    args = parser.parse_args()

    rules = (
        [load_jurisdiction(args.jurisdiction, str(args.data_dir))]
        if args.jurisdiction
        else load_all_jurisdictions(str(args.data_dir))
    )

    reports = [diff_reextract(rule) for rule in rules]
    failed = [r for r in reports if not r.passed]

    payload = {
        "checked": len(reports),
        "failed": len(failed),
        "results": [
            {
                "jurisdiction_id": r.jurisdiction_id,
                "passed": r.passed,
                "mismatches": [asdict(m) for m in r.mismatches],
            }
            for r in reports
        ],
    }

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Checked {len(reports)} jurisdictions — {len(failed)} with mismatches")
        for report in failed[:15]:
            print(f"\n{report.jurisdiction_id}:")
            for mismatch in report.mismatches[:5]:
                print(f"  - {mismatch.condition_id}: {mismatch.message}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
