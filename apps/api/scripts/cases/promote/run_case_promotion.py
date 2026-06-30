#!/usr/bin/env python3
"""Single-case draft-to-canonical promotion runner."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

_SCRIPTS_DIR = Path(__file__).resolve().parent
_API_DIR = _SCRIPTS_DIR.parent.parent.parent
_REPO_ROOT = _API_DIR.parent.parent

sys.path.insert(0, str(_API_DIR))

from scripts.cases.promote.promotion_gate import (  # noqa: E402
    GateResult,
    PromotionCandidate,
    PromotionPaths,
    PromotionPolicy,
    run_graph_seed,
    run_promotion_gate,
    unresolved_conflicts as _unresolved_conflicts,
)

PYTHON = sys.executable
_DRAFTS_DIR = _REPO_ROOT / "data" / "drafts"
_CASES_DIR = _REPO_ROOT / "data" / "cases"


def _infer_jurisdiction(case_id: str) -> str:
    for prefix, jurisdiction in (("eu_", "eu"), ("uk_", "uk"), ("us_", "us")):
        if case_id.startswith(prefix):
            return jurisdiction
    return "eu"


def find_merged_draft(case_id: str, drafts_dir: Path) -> Optional[Path]:
    """Return the merged draft path if it exists, else None."""
    jurisdiction = _infer_jurisdiction(case_id)
    path = drafts_dir / jurisdiction / f"{case_id}.merged.draft.yaml"
    return path if path.exists() else None


def unresolved_conflicts(report_path: Path) -> list[str]:
    """Compatibility helper; the implementation lives in promotion_gate.py."""
    return _unresolved_conflicts(report_path)


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    """Print and run a command from the repo root; return the result."""
    print(f"\n$ {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=str(_REPO_ROOT))


def _run_check(cmd: list[str]) -> None:
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


def check_draft_integrity(case_id: str) -> tuple[int, int]:
    """Run source integrity on the target draft only and return (errors, warnings)."""
    cmd = [
        PYTHON,
        "apps/api/scripts/cases/integrity/check_source_integrity.py",
        "--cases-dir",
        "data/drafts",
        "--case-id",
        case_id,
        "--no-cache",
    ]
    result = _run_capture(cmd)

    match = re.search(r"(\d+)\s+error\(s\),\s*(\d+)\s+warning\(s\)", result.stdout)
    if match:
        return int(match.group(1)), int(match.group(2))
    if result.returncode != 0:
        return 1, 0
    return 0, 0


def _display_gate(gate: GateResult | None) -> str:
    if gate is None:
        return "-"
    if gate.status == "pass":
        if gate.errors is not None and gate.warnings is not None:
            return f"PASS ({gate.errors} errors, {gate.warnings} warnings)"
        return "PASS"
    if gate.status == "skipped_no_reports":
        return "SKIP (no reports)"
    return f"FAIL ({gate.message})" if gate.message else "FAIL"


def _print_summary(
    status: dict[str, str],
    case_id: str,
    focus: str,
    *,
    aborted: bool = False,
    dry_run: bool = False,
    draft_path: Optional[str] = None,
) -> None:
    print(f"\n{'=' * 60}")
    print(f"Promotion Summary - {case_id}")
    if draft_path:
        print(f"Draft:  {draft_path}")
    if dry_run:
        print("(DRY RUN - no canonical changes written)")
    print(f"STATUS: {'ABORTED' if aborted else 'COMPLETE'}")
    print("-" * 60)
    labels: list[tuple[str, str]] = [
        ("draft_integrity", "Draft integrity"),
        ("candidate", "Canonical candidate"),
        ("validate_cases", "Canonical validation"),
        ("semantic_lint", "Semantic lint"),
        ("source_links", "Source links"),
        ("canonical_integrity", "Canonical source integrity"),
        ("conflict_report", "Conflict-report gate"),
        ("graph_seed", "Graph seed"),
    ]
    for key, label in labels:
        print(f"  {label:<28} {status.get(key, '-')}")
    print(f"{'=' * 60}\n")


def _resolve_draft(args: argparse.Namespace) -> tuple[Optional[str], str]:
    if args.draft:
        return args.draft, "explicit --draft"
    merged = find_merged_draft(args.case_id, _DRAFTS_DIR)
    if merged:
        return str(merged), "auto-detected merged draft"
    return None, f"focus={args.focus}"


def _dry_run_promote(args: argparse.Namespace, effective_draft: Optional[str]) -> int:
    promote_cmd = [
        PYTHON,
        "apps/api/scripts/cases/promote/promote_draft_to_canonical.py",
        "--case-id",
        args.case_id,
        "--dry-run",
    ]
    if effective_draft:
        promote_cmd += ["--draft", effective_draft]
    else:
        promote_cmd += ["--focus", args.focus]
    if args.procedure_stage:
        promote_cmd += ["--procedure-stage", args.procedure_stage]
    try:
        _run_check(promote_cmd)
    except subprocess.CalledProcessError:
        return 1
    return 0


def _status_from_outcome(outcome_status: str) -> str:
    if outcome_status == "promoted":
        return "PASS"
    if outcome_status == "skipped_exists":
        return "SKIP (already exists)"
    return "FAIL"


def _draft_kind(effective_draft: Optional[str], focus: str) -> str:
    if effective_draft and ".merged.draft.yaml" in Path(effective_draft).name:
        return "full-depth"
    if focus == "market_definition":
        return "market-definition"
    return focus.replace("_", "-")


def _should_check_legacy_draft_integrity(
    effective_draft: Optional[str],
    focus: str,
) -> bool:
    if effective_draft:
        return Path(effective_draft).name.endswith(".market_definition.draft.yaml")
    return focus == "market_definition"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Orchestrate full draft to canonical promotion."
    )
    parser.add_argument("--case-id", required=True)
    parser.add_argument(
        "--draft",
        help="Explicit path to the draft YAML to promote. Overrides auto-detection.",
    )
    parser.add_argument(
        "--focus",
        default="market_definition",
        help="Extraction focus for legacy draft lookup.",
    )
    parser.add_argument(
        "--conflict-report",
        help="Dual-extraction ConflictReport; all conflicts must have resolutions.",
    )
    parser.add_argument("--procedure-stage")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-graph-seed", action="store_true")
    args = parser.parse_args(argv)

    effective_draft, draft_source = _resolve_draft(args)
    status: dict[str, str] = {}

    print(f"\n{'=' * 60}")
    print(f"Meridian Promotion Pipeline: {args.case_id}")
    if effective_draft:
        print(f"draft={effective_draft}  ({draft_source})")
    else:
        print(f"focus={args.focus}  (no merged draft found)")
    if args.procedure_stage:
        print(f"procedure-stage={args.procedure_stage}")
    if args.dry_run:
        print("[DRY RUN]")
    print(f"{'=' * 60}")

    if _should_check_legacy_draft_integrity(effective_draft, args.focus):
        print("\n[1/7] Draft source integrity check (target draft only) ...")
        errors, warnings = check_draft_integrity(args.case_id)
        if errors > 0 or warnings > 0:
            status["draft_integrity"] = f"FAIL ({errors} error(s), {warnings} warning(s))"
            print(
                f"\nERROR: Draft source integrity failed - "
                f"{errors} error(s), {warnings} warning(s).\n"
                "Promotion aborted. Fix the draft before re-running.",
                file=sys.stderr,
            )
            _print_summary(
                status,
                args.case_id,
                args.focus,
                aborted=True,
                dry_run=args.dry_run,
                draft_path=effective_draft,
            )
            return 1
        status["draft_integrity"] = "PASS (0 errors, 0 warnings)"
    else:
        print("\n[1/7] Draft source integrity check skipped for merged draft.")
        status["draft_integrity"] = "SKIP (candidate source integrity gate)"

    if args.dry_run:
        print("\n[2/7] Promoting draft to canonical (dry run) ...")
        rc = _dry_run_promote(args, effective_draft)
        status["candidate"] = "PASS (dry run)" if rc == 0 else "FAIL"
        _print_summary(
            status,
            args.case_id,
            args.focus,
            aborted=rc != 0,
            dry_run=True,
            draft_path=effective_draft,
        )
        return rc

    jurisdiction = _infer_jurisdiction(args.case_id)
    if effective_draft:
        draft_path = Path(effective_draft)
        if not draft_path.is_absolute():
            draft_path = _REPO_ROOT / draft_path
        if draft_path.parent.name in {"eu", "uk", "us"}:
            jurisdiction = draft_path.parent.name
    else:
        draft_path = _DRAFTS_DIR / jurisdiction / f"{args.case_id}.{args.focus}.draft.yaml"

    conflict_reports = (Path(args.conflict_report),) if args.conflict_report else ()
    candidate = PromotionCandidate(
        case_id=args.case_id,
        jurisdiction=jurisdiction,
        draft_path=draft_path,
        draft_kind=_draft_kind(effective_draft, args.focus),
        review_status="operator",
        output_path=_CASES_DIR / jurisdiction / f"{args.case_id}.yaml",
        conflict_reports=conflict_reports,
    )
    paths = PromotionPaths(
        repo_root=_REPO_ROOT,
        drafts_dir=_DRAFTS_DIR,
        cases_dir=_CASES_DIR,
        python=PYTHON,
    )
    policy = PromotionPolicy(
        overwrite=args.overwrite,
        procedure_stage=args.procedure_stage,
    )

    print("\n[2/7] Candidate build and promotion gates ...")
    outcome = run_promotion_gate(candidate, paths=paths, policy=policy)
    status["candidate"] = _display_gate(outcome.gates.get("candidate"))
    status["validate_cases"] = _display_gate(outcome.gates.get("schema"))
    status["source_links"] = _display_gate(outcome.gates.get("source_links"))
    status["canonical_integrity"] = _display_gate(outcome.gates.get("source_integrity"))
    status["semantic_lint"] = _display_gate(outcome.gates.get("semantic_lint"))
    status["conflict_report"] = _display_gate(outcome.gates.get("conflict_gate"))

    if outcome.status != "promoted":
        status["candidate"] = _status_from_outcome(outcome.status)
        print(f"\nERROR: Promotion blocked - {outcome.status}: {outcome.message}", file=sys.stderr)
        _print_summary(status, args.case_id, args.focus, aborted=True, draft_path=effective_draft)
        return 1

    status["candidate"] = "PASS"

    if args.skip_graph_seed:
        status["graph_seed"] = "SKIP"
        _print_summary(status, args.case_id, args.focus, draft_path=effective_draft)
        return 0

    print("\n[7/7] Graph seed ...")
    graph_seed = run_graph_seed(paths)
    status["graph_seed"] = "PASS" if graph_seed.status == "pass" else "FAIL"
    if graph_seed.status != "pass":
        print(f"\nERROR: Graph seed failed - {graph_seed.message}", file=sys.stderr)
        _print_summary(status, args.case_id, args.focus, aborted=True, draft_path=effective_draft)
        return 1

    _print_summary(status, args.case_id, args.focus, draft_path=effective_draft)
    return 0


if __name__ == "__main__":
    sys.exit(main())
