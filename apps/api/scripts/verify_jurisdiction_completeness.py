#!/usr/bin/env python3
"""Verify structural completeness of jurisdiction YAML profiles."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = REPO_ROOT / "data" / "jurisdictions"
ARCHETYPES_PATH = DATA_DIR / "_archetypes.yaml"

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.jurisdiction_completeness import (
    build_sidecar_update,
    evaluate_all,
    load_sidecar,
    write_sidecar,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jurisdiction", "-j", help="Single jurisdiction id (default: all)")
    parser.add_argument("--write-sidecar", action="store_true", help="Write .verification.yaml sidecars")
    parser.add_argument("--json", action="store_true", help="Print JSON report")
    args = parser.parse_args()

    reports = evaluate_all(DATA_DIR, ARCHETYPES_PATH)
    if args.jurisdiction:
        reports = [r for r in reports if r.jurisdiction_id == args.jurisdiction]
        if not reports:
            print(f"Unknown jurisdiction: {args.jurisdiction}", file=sys.stderr)
            return 1

    failed = [r for r in reports if not r.passed]
    payload = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "jurisdiction_count": len(reports),
        "failed_count": len(failed),
        "results": [
            {
                "jurisdiction_id": r.jurisdiction_id,
                "passed": r.passed,
                "failures": [asdict(f) for f in r.failures],
            }
            for r in reports
        ],
    }

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Checked {len(reports)} jurisdictions — {len(failed)} failed")
        for report in failed[:20]:
            print(f"\n{report.jurisdiction_id}:")
            for failure in report.failures[:8]:
                print(f"  - [{failure.code}] {failure.message}")
        if len(failed) > 20:
            print(f"\n... and {len(failed) - 20} more failed jurisdictions")

    if args.write_sidecar:
        for report in reports:
            path = DATA_DIR / f"{report.jurisdiction_id}.verification.yaml"
            existing = load_sidecar(path)
            sidecar = build_sidecar_update(report, existing)
            sidecar.verified_at = datetime.now(timezone.utc)
            write_sidecar(path, sidecar)

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
