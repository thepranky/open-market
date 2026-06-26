#!/usr/bin/env python3
"""
bulk_promote_pass.py — Promote all PASS/WARNINGS draft YAMLs to canonical.

Scans data/drafts/{jurisdiction}/ for *.market_definition.draft.yaml files,
checks their review.md for status, and promotes those that are PASS or WARNINGS
(i.e. not BLOCKED or ERROR).

Usage:
    python apps/api/scripts/cases/promote/bulk_promote_pass.py [--dry-run] [--jurisdiction eu]
                                                 [--max N] [--overwrite]

Options:
    --dry-run        Print what would be promoted without writing anything.
    --jurisdiction   Restrict to one jurisdiction folder (default: all).
    --max N          Stop after N promotions (useful for testing).
    --overwrite      Re-promote even if a canonical record already exists.
    --min-markets N  Skip drafts with fewer than N product markets (default: 1).
"""
import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[5]
DRAFTS_DIR = REPO_ROOT / "data" / "drafts"
CASES_DIR = REPO_ROOT / "data" / "cases"
PROMOTE_SCRIPT = Path(__file__).parent / "promote_draft_to_canonical.py"

# Use the venv Python so promote_draft_to_canonical.py has yaml/pydantic available.
_VENV_PYTHON = Path(__file__).resolve().parents[3] / ".venv" / "bin" / "python3"
PYTHON = str(_VENV_PYTHON) if _VENV_PYTHON.exists() else sys.executable


def review_status(review_md: Path) -> str:
    """Return the status line from a review.md: PASS, WARNINGS, BLOCKED, ERROR, or UNKNOWN."""
    if not review_md.exists():
        return "NO_REVIEW"
    for line in review_md.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("**Status:"):
            # e.g. "**Status: WARNINGS**" or "**Status: PASS**"
            inner = stripped.replace("**Status:", "").replace("**", "").strip()
            return inner.upper()
    return "UNKNOWN"


def canonical_exists(case_id: str) -> bool:
    for jur in ("eu", "uk", "us"):
        p = CASES_DIR / jur / f"{case_id}.yaml"
        if p.exists():
            return True
    return False


def count_markets(draft_yaml: Path) -> int:
    """Quick count of product_markets_considered entries without full parse."""
    count = 0
    in_markets = False
    for line in draft_yaml.read_text().splitlines():
        if line.strip().startswith("product_markets_considered:"):
            in_markets = True
            continue
        if in_markets:
            if line.strip().startswith("- market_id:"):
                count += 1
            elif line and not line[0].isspace() and not line.startswith(" "):
                in_markets = False
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description="Bulk-promote PASS draft YAMLs to canonical.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--jurisdiction", default=None, help="e.g. eu, uk, us")
    parser.add_argument("--max", type=int, default=None, dest="max_count")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--min-markets", type=int, default=1)
    args = parser.parse_args()

    jur_dirs = (
        [DRAFTS_DIR / args.jurisdiction]
        if args.jurisdiction
        else [d for d in DRAFTS_DIR.iterdir() if d.is_dir()]
    )

    def is_promotable(status: str) -> bool:
        return status in {"PASS", "WARNINGS"} or status.startswith("PASS ")

    candidates = []
    for jur_dir in sorted(jur_dirs):
        for draft in sorted(jur_dir.glob("*.market_definition.draft.yaml")):
            case_id = draft.name.replace(".market_definition.draft.yaml", "")
            review_md = draft.parent / f"{case_id}.market_definition.review.md"
            status = review_status(review_md)
            candidates.append((case_id, draft, status))

    print(f"Found {len(candidates)} draft YAMLs")

    promoted = skipped_exists = skipped_status = skipped_markets = errors = 0

    for case_id, draft, status in candidates:
        if args.max_count and promoted >= args.max_count:
            print(f"\n[max {args.max_count} reached — stopping]")
            break

        if not is_promotable(status):
            skipped_status += 1
            print(f"  SKIP  {case_id}  [{status}]")
            continue

        if not args.overwrite and canonical_exists(case_id):
            skipped_exists += 1
            print(f"  EXISTS {case_id}")
            continue

        market_count = count_markets(draft)
        if market_count < args.min_markets:
            skipped_markets += 1
            print(f"  SKIP  {case_id}  [only {market_count} markets]")
            continue

        if args.dry_run:
            print(f"  DRY   {case_id}  [{status}] — {market_count} markets")
            promoted += 1
            continue

        print(f"  →     {case_id}  [{status}] — {market_count} markets", end="  ", flush=True)
        cmd = [PYTHON, str(PROMOTE_SCRIPT), "--case-id", case_id]
        if args.overwrite:
            cmd.append("--overwrite")
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            print("OK")
            promoted += 1
        else:
            err_line = (result.stderr or result.stdout or "").strip().splitlines()
            print(f"FAIL — {err_line[-1] if err_line else 'unknown error'}")
            errors += 1

    print(
        f"\nDone. promoted={promoted}  skipped_status={skipped_status}"
        f"  skipped_exists={skipped_exists}  skipped_markets={skipped_markets}"
        f"  errors={errors}"
    )
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
