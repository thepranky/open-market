#!/usr/bin/env python3
"""
promote_case_pipeline.py — single-command orchestration for draft → canonical promotion.

Runs the full gate sequence in order:
  1. Draft source integrity — target draft only; 0 errors AND 0 warnings required
  2. promote_draft_to_canonical
  3. validate_cases       (canonical schema validation)
  4. lint_case_semantics  (deterministic legal-meaning lint, target case only)
  5. check_source_links   (canonical URL liveness)
  6. check_source_integrity --no-cache  (canonical quote/locator checks)
  7. graph/seed_graph
  8. create_review_learning_log
  9. apply_review_learning

Fails fast on any blocking error. Promotion is skipped if draft integrity has
any error or warning.

Usage (from repo root):
    # Promote an orchestrator-produced merged draft (preferred for controlled expansion)
    apps/api/.venv/bin/python apps/api/scripts/cases/promote/promote_case_pipeline.py \\
        --case-id eu_booking_etraveli_2023 \\
        --draft data/drafts/eu/eu_booking_etraveli_2023.merged.draft.yaml \\
        --overwrite

    # Legacy focus-based promotion
    apps/api/.venv/bin/python apps/api/scripts/cases/promote/promote_case_pipeline.py \\
        --case-id eu_daimler_geely_smart_2020 \\
        --focus market_definition \\
        --procedure-stage phase1 \\
        --overwrite

    # Dry run — shows draft integrity + promote output, skips downstream writes
    apps/api/.venv/bin/python apps/api/scripts/cases/promote/promote_case_pipeline.py \\
        --case-id eu_daimler_geely_smart_2020 \\
        --focus market_definition \\
        --procedure-stage phase1 \\
        --dry-run
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

_SCRIPTS_DIR = Path(__file__).resolve().parent
_API_DIR = _SCRIPTS_DIR.parent.parent.parent
_REPO_ROOT = _API_DIR.parent.parent

PYTHON = sys.executable

_DRAFTS_DIR = _REPO_ROOT / "data" / "drafts"


# ---------------------------------------------------------------------------
# Draft path helpers
# ---------------------------------------------------------------------------

def _infer_jurisdiction(case_id: str) -> str:
    for prefix, jur in (("eu_", "eu"), ("uk_", "uk"), ("us_", "us")):
        if case_id.startswith(prefix):
            return jur
    return "eu"


def find_merged_draft(case_id: str, drafts_dir: Path) -> Optional[Path]:
    """Return the merged draft path if it exists, else None."""
    jur = _infer_jurisdiction(case_id)
    p = drafts_dir / jur / f"{case_id}.merged.draft.yaml"
    return p if p.exists() else None


# ---------------------------------------------------------------------------
# Subprocess helpers
# ---------------------------------------------------------------------------

def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    """Print and run a command from the repo root; return the result."""
    print(f"\n$ {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=str(_REPO_ROOT))


def _run_check(cmd: list[str]) -> None:
    """Run a command and raise CalledProcessError on non-zero exit."""
    result = _run(cmd)
    if result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, cmd)


def _run_capture(cmd: list[str]) -> subprocess.CompletedProcess:
    """Run a command, capturing stdout/stderr and streaming them to the terminal."""
    print(f"\n$ {' '.join(cmd)}")
    result = subprocess.run(
        cmd,
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
    )
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    return result


# ---------------------------------------------------------------------------
# Draft integrity gate
# ---------------------------------------------------------------------------

def check_draft_integrity(case_id: str) -> tuple[int, int]:
    """
    Run source integrity on the target draft only (data/drafts/, case-specific).

    Returns (errors, warnings). Parses the "Total:" summary line so that
    warnings cause the same abort as errors.
    """
    cmd = [
        PYTHON, "apps/api/scripts/cases/integrity/check_source_integrity.py",
        "--cases-dir", "data/drafts",
        "--case-id", case_id,
        "--no-cache",
    ]
    result = _run_capture(cmd)

    m = re.search(r"(\d+)\s+error\(s\),\s*(\d+)\s+warning\(s\)", result.stdout)
    if m:
        return int(m.group(1)), int(m.group(2))

    # Fallback: non-zero exit without a parseable summary counts as 1 error.
    if result.returncode != 0:
        return 1, 0
    return 0, 0


# ---------------------------------------------------------------------------
# Summary printer
# ---------------------------------------------------------------------------

def _print_summary(
    status: dict[str, str],
    case_id: str,
    focus: str,
    *,
    aborted: bool = False,
    dry_run: bool = False,
    draft_path: Optional[str] = None,
) -> None:
    print(f"\n{'='*60}")
    print(f"Promotion Summary — {case_id}")
    if draft_path:
        print(f"Draft:  {draft_path}")
    if dry_run:
        print("(DRY RUN — no canonical changes written)")
    print(f"STATUS: {'ABORTED' if aborted else 'COMPLETE'}")
    print(f"{'─'*60}")
    _LABELS: list[tuple[str, str]] = [
        ("draft_integrity",    "Draft integrity"),
        ("promote",            "Promote to canonical"),
        ("validate_cases",     "Canonical validation"),
        ("semantic_lint",      "Semantic lint"),
        ("source_links",       "Source links"),
        ("canonical_integrity","Canonical source integrity"),
        ("graph_seed",         "Graph seed"),
        ("learning_log",       "Learning log"),
        ("proposals",          "Proposals path"),
    ]
    for key, label in _LABELS:
        val = status.get(key, "—")
        print(f"  {label:<28} {val}")
    print(f"{'='*60}\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Orchestrate full draft → canonical promotion pipeline."
    )
    parser.add_argument(
        "--case-id", required=True,
        help="Case ID, e.g. eu_daimler_geely_smart_2020",
    )
    parser.add_argument(
        "--draft",
        help="Explicit path to the draft YAML to promote (e.g. a merged draft). "
             "When supplied, overrides auto-detection and --focus for draft lookup.",
    )
    parser.add_argument(
        "--focus", default="market_definition",
        help="Extraction focus (default: market_definition). "
             "Ignored when --draft is supplied or a merged draft is auto-detected.",
    )
    parser.add_argument(
        "--procedure-stage",
        help="Override procedure_stage (phase1 | phase2)",
    )
    parser.add_argument(
        "--overwrite", action="store_true",
        help="Overwrite the existing canonical record",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Run draft integrity and promote --dry-run; skip downstream writes",
    )
    args = parser.parse_args(argv)

    # ------------------------------------------------------------------
    # Resolve draft path: explicit > auto-detected merged > focus-based
    # ------------------------------------------------------------------
    drafts_dir = _DRAFTS_DIR
    effective_draft: Optional[str] = None

    if args.draft:
        effective_draft = args.draft
        draft_source = "explicit --draft"
    else:
        merged = find_merged_draft(args.case_id, drafts_dir)
        if merged:
            effective_draft = str(merged)
            draft_source = "auto-detected merged draft"
        else:
            draft_source = f"focus={args.focus}"

    status: dict[str, str] = {}

    print(f"\n{'='*60}")
    print(f"Meridian Promotion Pipeline: {args.case_id}")
    if effective_draft:
        print(f"draft={effective_draft}  ({draft_source})")
    else:
        print(f"focus={args.focus}  (no merged draft found)")
    if args.procedure_stage:
        print(f"procedure-stage={args.procedure_stage}")
    if args.dry_run:
        print("[DRY RUN]")
    print(f"{'='*60}")

    # ------------------------------------------------------------------
    # 1. Draft source integrity — must pass with 0 errors AND 0 warnings
    # ------------------------------------------------------------------
    print("\n[1/9] Draft source integrity check (target draft only) …")
    errors, warnings = check_draft_integrity(args.case_id)

    if errors > 0 or warnings > 0:
        status["draft_integrity"] = f"FAIL ({errors} error(s), {warnings} warning(s))"
        print(
            f"\nERROR: Draft source integrity failed — "
            f"{errors} error(s), {warnings} warning(s).\n"
            "Promotion aborted. Fix the draft before re-running.",
            file=sys.stderr,
        )
        _print_summary(status, args.case_id, args.focus, aborted=True,
                       draft_path=effective_draft)
        return 1

    status["draft_integrity"] = "PASS (0 errors, 0 warnings)"

    # ------------------------------------------------------------------
    # 2. Promote draft → canonical
    # ------------------------------------------------------------------
    print("\n[2/9] Promoting draft to canonical …")
    promote_cmd = [
        PYTHON, "apps/api/scripts/cases/promote/promote_draft_to_canonical.py",
        "--case-id", args.case_id,
    ]
    if effective_draft:
        promote_cmd += ["--draft", effective_draft]
    else:
        promote_cmd += ["--focus", args.focus]
    if args.procedure_stage:
        promote_cmd += ["--procedure-stage", args.procedure_stage]
    if args.dry_run:
        promote_cmd.append("--dry-run")
    elif args.overwrite:
        promote_cmd.append("--overwrite")

    try:
        _run_check(promote_cmd)
        status["promote"] = "PASS (dry run)" if args.dry_run else "PASS"
    except subprocess.CalledProcessError:
        status["promote"] = "FAIL"
        _print_summary(status, args.case_id, args.focus, aborted=True, dry_run=args.dry_run,
                       draft_path=effective_draft)
        return 1

    if args.dry_run:
        _print_summary(status, args.case_id, args.focus, dry_run=True,
                       draft_path=effective_draft)
        return 0

    # ------------------------------------------------------------------
    # 3. Canonical schema validation
    # ------------------------------------------------------------------
    print("\n[3/9] Canonical schema validation …")
    try:
        _run_check([PYTHON, "apps/api/scripts/cases/integrity/validate_cases.py"])
        status["validate_cases"] = "PASS"
    except subprocess.CalledProcessError:
        status["validate_cases"] = "FAIL"
        _print_summary(status, args.case_id, args.focus, aborted=True,
                       draft_path=effective_draft)
        return 1

    # ------------------------------------------------------------------
    # 4. Semantic lint (deterministic legal-meaning checks, target case only)
    # ------------------------------------------------------------------
    print("\n[4/9] Semantic lint …")
    try:
        _run_check([
            PYTHON, "apps/api/scripts/cases/integrity/lint_case_semantics.py",
            "--cases-dir", "data/cases",
            "--case-id", args.case_id,
        ])
        status["semantic_lint"] = "PASS"
    except subprocess.CalledProcessError:
        status["semantic_lint"] = "FAIL"
        _print_summary(status, args.case_id, args.focus, aborted=True,
                       draft_path=effective_draft)
        return 1

    # ------------------------------------------------------------------
    # 5. Source links
    # ------------------------------------------------------------------
    print("\n[5/9] Canonical source links check …")
    try:
        _run_check([PYTHON, "apps/api/scripts/cases/integrity/check_source_links.py"])
        status["source_links"] = "PASS"
    except subprocess.CalledProcessError:
        status["source_links"] = "FAIL"
        _print_summary(status, args.case_id, args.focus, aborted=True,
                       draft_path=effective_draft)
        return 1

    # ------------------------------------------------------------------
    # 6. Canonical source integrity
    # ------------------------------------------------------------------
    print("\n[6/9] Canonical source integrity check …")
    try:
        _run_check([
            PYTHON, "apps/api/scripts/cases/integrity/check_source_integrity.py",
            "--no-cache",
        ])
        status["canonical_integrity"] = "PASS"
    except subprocess.CalledProcessError:
        status["canonical_integrity"] = "FAIL"
        _print_summary(status, args.case_id, args.focus, aborted=True,
                       draft_path=effective_draft)
        return 1

    # ------------------------------------------------------------------
    # 7. Graph seed
    # ------------------------------------------------------------------
    print("\n[7/9] Graph seed …")
    try:
        _run_check([PYTHON, "graph/seed_graph.py"])
        status["graph_seed"] = "PASS"
    except subprocess.CalledProcessError:
        status["graph_seed"] = "FAIL"
        _print_summary(status, args.case_id, args.focus, aborted=True,
                       draft_path=effective_draft)
        return 1

    # ------------------------------------------------------------------
    # 8. Create review learning log
    # ------------------------------------------------------------------
    print("\n[8/9] Creating review learning log …")
    try:
        _run_check([
            PYTHON, "apps/api/scripts/cases/review/create_review_learning_log.py",
            "--case-id", args.case_id,
            "--focus", args.focus,
        ])
    except subprocess.CalledProcessError:
        status["learning_log"] = "FAIL"
        _print_summary(status, args.case_id, args.focus, aborted=True,
                       draft_path=effective_draft)
        return 1

    learning_log_path = (
        _REPO_ROOT / "data" / "review_learning"
        / f"{args.case_id}.{args.focus}.review_delta.yaml"
    )
    status["learning_log"] = (
        str(learning_log_path.relative_to(_REPO_ROOT))
        if learning_log_path.exists()
        else "written (see data/review_learning/)"
    )

    # ------------------------------------------------------------------
    # 9. Apply review learning
    # ------------------------------------------------------------------
    print("\n[9/9] Applying review learning …")
    try:
        _run_check([PYTHON, "apps/api/scripts/cases/review/apply_review_learning.py"])
    except subprocess.CalledProcessError:
        status["proposals"] = "FAIL"
        _print_summary(status, args.case_id, args.focus, aborted=True,
                       draft_path=effective_draft)
        return 1

    status["proposals"] = "data/review_learning/proposals/"

    _print_summary(status, args.case_id, args.focus, draft_path=effective_draft)
    return 0


if __name__ == "__main__":
    sys.exit(main())
