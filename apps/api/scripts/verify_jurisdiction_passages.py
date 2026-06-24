#!/usr/bin/env python3
"""Verify jurisdiction source_passages against authoritative source text."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = REPO_ROOT / "data" / "jurisdictions"

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.screening.services.jurisdiction_passages import build_offline_fetch, verify_and_optional_write
from app.screening.services.source_fetcher import fetch_source
from app.screening.services.threshold_engine import load_all_jurisdictions, load_jurisdiction


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jurisdiction", "-j", help="Single jurisdiction id (default: all)")
    parser.add_argument("--offline", action="store_true", help="Use local HTML/text fixtures only")
    parser.add_argument("--write-sidecar", action="store_true", help="Write .verification.yaml sidecars")
    parser.add_argument("--json", action="store_true", help="Print JSON report")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    args = parser.parse_args()

    if args.offline:
        fetch_fn = build_offline_fetch(
            Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "jurisdiction_sources"
        )
    else:
        fetch_fn = fetch_source

    if args.jurisdiction:
        rules = [load_jurisdiction(args.jurisdiction, str(args.data_dir))]
    else:
        rules = load_all_jurisdictions(str(args.data_dir))

    reports = [
        verify_and_optional_write(
            rule,
            args.data_dir,
            fetch_fn=fetch_fn,
            write_sidecar_file=args.write_sidecar,
        )
        for rule in rules
    ]

    # Three honest buckets: confirmed (number grounded), grounded-only, and
    # unverified (no authoritative condition could be checked — e.g. no passages).
    confirmed = [r for r in reports if r.numbers_confirmed]
    grounded_only = [r for r in reports if r.passages_grounded and not r.numbers_confirmed]
    unverified = [r for r in reports if not r.conditions_verified]
    failed = [r for r in reports if not r.numbers_confirmed]
    payload = {
        "checked": len(reports),
        "confirmed": len(confirmed),
        "grounded_only": len(grounded_only),
        "unverified": len(unverified),
        "failed": len(failed),
        "results": [
            {
                "jurisdiction_id": r.jurisdiction_id,
                "passages_grounded": r.passages_grounded,
                "numbers_confirmed": r.numbers_confirmed,
                "unverified": not r.conditions_verified,
                "failures": [asdict(f) for f in r.failures],
            }
            for r in reports
        ],
    }

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(
            f"Checked {len(reports)} jurisdictions — "
            f"{len(confirmed)} confirmed, {len(grounded_only)} grounded-only, "
            f"{len(unverified)} unverified, {len(failed)} not numbers-confirmed"
        )
        if args.verbose or len(reports) <= 5:
            for report in failed:
                print(f"\n{report.jurisdiction_id}:")
                for failure in report.failures[:10]:
                    print(f"  - [{failure.code}] {failure.message}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
