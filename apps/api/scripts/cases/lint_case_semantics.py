#!/usr/bin/env python3
"""
Semantic lint for canonical YAML case records (ROADMAP 4.5).

Deterministic legal-meaning checks that schema validation cannot express:
  - complaint_not_defined : complaint-only markets must not be `defined`
  - dangling_support_ref  : supports_* ids must resolve to entities in the record

Usage:
  python apps/api/scripts/cases/lint_case_semantics.py [--cases-dir data/cases]
                                                       [--case-id eu_..._2020]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.cases.loader.semantic_lint import lint_all


def main() -> None:
    parser = argparse.ArgumentParser(description="Semantic lint for Meridian case records")
    parser.add_argument("--cases-dir", default="data/cases")
    parser.add_argument("--case-id", default=None, help="Lint a single case by id")
    args = parser.parse_args()

    target = args.case_id or "all cases"
    print(f"Semantic lint: {target} in {args.cases_dir} ...\n")

    checked, issues, load_errors = lint_all(args.cases_dir, args.case_id)

    for msg in load_errors:
        print(f"LOAD ERROR: {msg}\n")

    for issue in issues:
        print(f"ERROR: {issue}")

    print(f"\nResults: {checked} case(s) checked, {len(issues)} issue(s)")

    if issues or load_errors:
        sys.exit(1)
    print("No semantic issues.")


if __name__ == "__main__":
    main()
