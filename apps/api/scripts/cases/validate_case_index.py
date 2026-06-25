#!/usr/bin/env python3
"""
Validate all YAML case-index entries against CaseIndexEntry.

Usage:
  python apps/api/scripts/cases/validate_case_index.py [--index-dir data/case_index]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.cases.loader.index_loader import load_all_index_cases


def main():
    parser = argparse.ArgumentParser(description="Validate Meridian YAML case-index entries")
    parser.add_argument("--index-dir", default="data/case_index")
    args = parser.parse_args()

    print(f"Validating case index in {args.index_dir} ...\n")
    ok = 0
    errors = []
    for path, result in load_all_index_cases(args.index_dir):
        if isinstance(result, Exception):
            errors.append(f"{path}: {result}")
        else:
            ok += 1

    if errors:
        for msg in errors:
            print(f"ERROR: {msg}\n")

    print(f"Results: {ok} valid, {len(errors)} invalid")

    if errors:
        sys.exit(1)
    else:
        print("All case-index entries valid.")


if __name__ == "__main__":
    main()
