#!/usr/bin/env python3
"""Orchestrate jurisdiction verification gates for CI and manual runs."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

API_DIR = Path(__file__).resolve().parents[2]
PYTHON = sys.executable


def _run(label: str, cmd: list[str]) -> int:
    print(f"\n=== {label} ===", flush=True)
    proc = subprocess.run(cmd, cwd=API_DIR)
    if proc.returncode != 0:
        print(f"FAILED: {label}", file=sys.stderr)
    return proc.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tier",
        choices=("push", "nightly", "full"),
        default="push",
        help="push: schema/completeness/regression; nightly: +passages/staleness offline; full: live passages all",
    )
    parser.add_argument("--jurisdiction", "-j", help="Limit passage/staleness gates to one jurisdiction")
    args = parser.parse_args()

    failures = 0

    failures += _run(
        "Schema model tests",
        [PYTHON, "-m", "pytest", "-q", "tests/test_jurisdiction_verification_model.py"],
    )
    failures += _run(
        "Completeness gate",
        [PYTHON, "scripts/screening/verify_jurisdiction_completeness.py", "--json"],
    )
    failures += _run(
        "Gold deal regression",
        [PYTHON, "-m", "pytest", "-q", "tests/test_jurisdiction_regression.py"],
    )

    if args.tier in ("nightly", "full"):
        passage_cmd = [PYTHON, "scripts/screening/verify_jurisdiction_passages.py", "--json"]
        if args.tier == "nightly":
            passage_cmd.append("--offline")
        if args.jurisdiction:
            passage_cmd.extend(["--jurisdiction", args.jurisdiction])
        failures += _run("Passage grounding gate", passage_cmd)

        staleness_cmd = [PYTHON, "scripts/screening/monitor_jurisdiction_staleness.py", "--json"]
        if args.jurisdiction:
            staleness_cmd.extend(["--jurisdiction", args.jurisdiction])
        failures += _run("Staleness monitor", staleness_cmd)

        failures += _run(
            "Verification unit tests",
            [
                PYTHON,
                "-m",
                "pytest",
                "-q",
                "tests/test_source_fetcher.py",
                "tests/test_jurisdiction_completeness.py",
                "tests/test_verify_jurisdiction_passages.py",
                "tests/test_monitor_jurisdiction_staleness.py",
                "tests/test_jurisdiction_data_service.py",
            ],
        )

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
