#!/usr/bin/env python3
"""Report baseline source-coverage metrics for jurisdiction YAML profiles."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
DATA_DIR = REPO_ROOT / "data" / "jurisdictions"
ARCHETYPES_PATH = DATA_DIR / "_archetypes.yaml"
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "jurisdiction-verification-baseline.md"

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.screening.services.jurisdiction_baseline import compute_baseline_report, render_baseline_markdown


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print JSON instead of markdown summary")
    parser.add_argument("--write", action="store_true", help="Write markdown snapshot to docs/")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Markdown output path (default: {DEFAULT_OUTPUT})",
    )
    args = parser.parse_args()

    report = compute_baseline_report(DATA_DIR, ARCHETYPES_PATH)

    md = render_baseline_markdown(report)

    if args.json:
        print(json.dumps(report.model_dump(mode="json"), indent=2))
    else:
        print(md)

    if args.write:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(md)
        print(f"Wrote {args.output}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
