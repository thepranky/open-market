#!/usr/bin/env python3
"""
Validate all YAML case records against the canonical schema.

Usage:
  python apps/api/scripts/validate_cases.py [--cases-dir data/cases]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.cases.loader.validator import validate_all


def main():
    parser = argparse.ArgumentParser(description="Validate CompMap YAML case records")
    parser.add_argument("--cases-dir", default="data/cases")
    args = parser.parse_args()

    print(f"Validating cases in {args.cases_dir} ...\n")
    ok, error_count, error_messages = validate_all(args.cases_dir)

    if error_messages:
        for msg in error_messages:
            print(f"ERROR: {msg}\n")

    print(f"Results: {ok} valid, {error_count} invalid")

    if error_count > 0:
        sys.exit(1)
    else:
        print("All cases valid.")


if __name__ == "__main__":
    main()
