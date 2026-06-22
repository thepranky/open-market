#!/usr/bin/env python3
"""Monitor annual-adjustment jurisdictions for threshold drift."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = REPO_ROOT / "data" / "jurisdictions"
ANCHORS_PATH = DATA_DIR / "_staleness_anchors.yaml"

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.jurisdiction_verification import FreshnessStatus
from app.services.jurisdiction_staleness import evaluate_all, load_anchors, update_sidecar_freshness


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--write-sidecar", action="store_true")
    parser.add_argument("--jurisdiction", "-j", help="Limit the report to a single jurisdiction id")
    args = parser.parse_args()

    reports = evaluate_all(DATA_DIR, ANCHORS_PATH)
    if args.jurisdiction:
        reports = [r for r in reports if r.jurisdiction_id == args.jurisdiction]
    failed = [r for r in reports if r.freshness_status in {FreshnessStatus.drift_detected, FreshnessStatus.unknown}]

    payload = {
        "checked": len(reports),
        "failed": len(failed),
        "results": [
            {
                "jurisdiction_id": r.jurisdiction_id,
                "freshness_status": r.freshness_status.value,
                "drift": r.drift,
                "notes": r.notes,
            }
            for r in reports
        ],
    }

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Checked {len(reports)} annual-adjustment jurisdictions")
        for report in reports:
            print(f"  {report.jurisdiction_id}: {report.freshness_status.value}")
            for item in report.drift:
                print(f"    drift: {item}")

    if args.write_sidecar:
        anchors = load_anchors(ANCHORS_PATH)
        for report in reports:
            update_sidecar_freshness(DATA_DIR, report, anchors.get(report.jurisdiction_id))

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
