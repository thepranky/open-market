#!/usr/bin/env python3
"""
run_controlled_case.py — one-command orchestrator for controlled case expansion.

Wraps the existing pipeline scripts (ingest_case, plan_coverage, merge_drafts,
check_review_readiness) into a single terminal command that produces either
READY_FOR_HUMAN_REVIEW or NOT_READY with actionable blockers.

Does NOT auto-promote.  The default end state is a review packet in
data/drafts/<jur>/<case_id>.review_packet.md.

Usage (from repo root):
    python apps/api/scripts/run_controlled_case.py \\
        --case-id us_example_co_2025 \\
        --source-url https://example.com/decision.pdf \\
        --case-name "FTC v. Example Co" \\
        --jurisdiction US \\
        --authority "United States District Court (S.D.N.Y.)" \\
        --procedure-stage federal_district_court \\
        --outcome blocked \\
        --decision-date 2025-01-15

    # Dry run (no writes):
    python apps/api/scripts/run_controlled_case.py \\
        --case-id us_example_co_2025 --source-url https://... \\
        --case-name "FTC v. Example Co" --jurisdiction US \\
        --authority "SDNY" --procedure-stage federal_district_court \\
        --outcome blocked --dry-run

    # Skip LLM extraction (validate existing drafts only):
    python apps/api/scripts/run_controlled_case.py \\
        --case-id us_example_co_2025 --source-url https://... \\
        --case-name "FTC v. Example Co" --jurisdiction US \\
        --authority "SDNY" --procedure-stage federal_district_court \\
        --outcome blocked --skip-llm-review
"""

from __future__ import annotations

import argparse
import datetime
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------

_SCRIPTS_DIR = Path(__file__).resolve().parent
_API_DIR = _SCRIPTS_DIR.parent
_REPO_ROOT = _API_DIR.parents[1]
_CASES_DIR = _REPO_ROOT / "data" / "cases"
_DRAFTS_DIR = _REPO_ROOT / "data" / "drafts"
_SOURCE_TEXT_DIR = _REPO_ROOT / "data" / "source_text"

for _p in (str(_API_DIR), str(_SCRIPTS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from pipeline_profile import select_profile, PipelineProfile


# ---------------------------------------------------------------------------
# Status model
# ---------------------------------------------------------------------------

READY = "READY_FOR_HUMAN_REVIEW"
NOT_READY = "NOT_READY"
FAILED = "FAILED"


@dataclass
class StageResult:
    name: str
    status: str          # "ok" | "warn" | "error" | "skip"
    message: str = ""
    details: list[str] = field(default_factory=list)


@dataclass
class RunResult:
    case_id: str
    status: str          # READY | NOT_READY | FAILED
    profile_id: str
    stages: list[StageResult] = field(default_factory=list)
    generated_files: list[Path] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    git_warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _infer_jurisdiction(case_id: str) -> str:
    for prefix, jur in (("eu_", "eu"), ("uk_", "uk"), ("us_", "us")):
        if case_id.startswith(prefix):
            return jur
    return "eu"


def _python() -> str:
    """Return the venv python path if it exists, otherwise sys.executable."""
    venv_python = _API_DIR / ".venv" / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)
    return sys.executable


def _script(name: str) -> str:
    return str(_SCRIPTS_DIR / name)


def _run_subprocess(cmd: list[str], *, capture: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=capture, text=True)


# ---------------------------------------------------------------------------
# Stage 1 — Canonical seed
# ---------------------------------------------------------------------------

def _build_seed(
    case_id: str,
    case_name: str,
    jurisdiction: str,
    authority: str,
    authority_reference: Optional[str],
    procedure_stage: str,
    outcome: str,
    decision_date: Optional[str],
    sector: Optional[str],
    parties: list[str],
    source_url: str,
) -> dict:
    """Build a minimal canonical seed dict."""
    doc_id = f"{case_id}_decision"
    seed: dict = {
        "case_id": case_id,
        "case_name": case_name,
        "authority": authority,
        "jurisdiction": jurisdiction.upper(),
        "outcome": outcome,
    }
    if decision_date:
        seed["decision_date"] = decision_date
    if sector:
        seed["sector"] = sector
    if authority_reference:
        seed["authority_reference"] = authority_reference

    party_list = []
    for i, p in enumerate(parties):
        if ":" in p:
            name, role = p.split(":", 1)
            party_list.append({"name": name.strip(), "role": role.strip()})
        else:
            role = "acquirer" if i == 0 else "target"
            party_list.append({"name": p.strip(), "role": role})
    if party_list:
        seed["parties"] = party_list

    seed["source_documents"] = [
        {
            "doc_id": doc_id,
            "title": case_name,
            "pdf_url": source_url,
            "doc_type": "court_opinion" if jurisdiction.lower() == "us" else "merger_decision",
            "retrieval_status": "direct",
        }
    ]
    seed["procedure_stage"] = procedure_stage
    return seed


class _StrDumper(yaml.SafeDumper):
    pass


def _str_representer(dumper: yaml.SafeDumper, data: str) -> yaml.ScalarNode:
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


_StrDumper.add_representer(str, _str_representer)


def _dump_yaml(data: dict) -> str:
    return yaml.dump(
        data, Dumper=_StrDumper,
        default_flow_style=False, allow_unicode=True,
        sort_keys=False, width=100,
    )


def stage_seed(
    case_id: str,
    seed_data: dict,
    jurisdiction: str,
    *,
    dry_run: bool,
    overwrite: bool,
) -> tuple[StageResult, Optional[Path]]:
    """Write canonical seed YAML; return (result, path)."""
    jur_lower = jurisdiction.lower()
    out_dir = _CASES_DIR / jur_lower
    seed_path = out_dir / f"{case_id}.yaml"

    if seed_path.exists() and not overwrite:
        return (
            StageResult("seed", "ok", f"Seed already exists: {seed_path} (skipped)"),
            seed_path,
        )

    if dry_run:
        return (
            StageResult("seed", "ok", f"[dry-run] Would write seed to {seed_path}"),
            None,
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    seed_path.write_text(_dump_yaml(seed_data))
    return StageResult("seed", "ok", f"Seed written: {seed_path}"), seed_path


# ---------------------------------------------------------------------------
# Stage 2 — Source fetch / cache
# ---------------------------------------------------------------------------

def stage_fetch_source(
    case_id: str,
    source_url: str,
    *,
    dry_run: bool,
    overwrite: bool,
) -> tuple[StageResult, Optional[Path]]:
    """Fetch and cache the source PDF."""
    doc_id = f"{case_id}_decision"
    cache_path = _SOURCE_TEXT_DIR / f"{doc_id}.json"

    if cache_path.exists() and not overwrite:
        return (
            StageResult("fetch_source", "ok", f"Source cache exists: {cache_path} (skipped)"),
            cache_path,
        )

    if dry_run:
        return (
            StageResult("fetch_source", "ok", f"[dry-run] Would fetch {source_url} → {cache_path}"),
            None,
        )

    try:
        from app.utils.pdf_extractor import fetch_and_extract, save_cache
        import httpx

        with httpx.Client(follow_redirects=True, timeout=90) as client:
            data = fetch_and_extract(doc_id, source_url, force=overwrite, client=client)
        saved = save_cache(data)
        page_count = data.get("page_count", len(data.get("pages", [])))
        return (
            StageResult("fetch_source", "ok", f"Fetched {page_count} pages → {saved}"),
            Path(saved),
        )
    except Exception as exc:
        return (
            StageResult("fetch_source", "error", f"Failed to fetch source: {exc}"),
            None,
        )


# ---------------------------------------------------------------------------
# Stage 3 — Profile selection
# ---------------------------------------------------------------------------

def stage_select_profile(
    case_id: str,
    profile_id: Optional[str],
    case_meta: Optional[dict],
) -> tuple[StageResult, Optional[PipelineProfile]]:
    try:
        profile = select_profile(case_id, profile_id=profile_id, case_meta=case_meta)
        return (
            StageResult(
                "select_profile", "ok",
                f"Profile: {profile.profile_id} ({profile.display_name})",
            ),
            profile,
        )
    except ValueError as exc:
        return (
            StageResult("select_profile", "error", str(exc)),
            None,
        )


# ---------------------------------------------------------------------------
# Stage 4 — Coverage plan
# ---------------------------------------------------------------------------

def stage_plan_coverage(
    case_id: str,
    profile: PipelineProfile,
    *,
    dry_run: bool,
) -> tuple[StageResult, Optional[Path]]:
    jurisdiction = _infer_jurisdiction(case_id)
    plan_path = _DRAFTS_DIR / jurisdiction / f"{case_id}.coverage_plan.yaml"

    cmd = [
        _python(), _script("plan_coverage.py"),
        "--case-id", case_id,
        "--profile", profile.profile_id,
    ]
    if dry_run:
        cmd.append("--dry-run")

    result = _run_subprocess(cmd)
    if result.returncode != 0:
        return (
            StageResult(
                "plan_coverage", "error",
                f"plan_coverage.py failed (exit {result.returncode})",
                details=[result.stderr.strip()],
            ),
            None,
        )

    out_path = None if dry_run else plan_path
    msg = "[dry-run] Coverage plan printed" if dry_run else f"Coverage plan: {plan_path}"
    return StageResult("plan_coverage", "ok", msg), out_path


# ---------------------------------------------------------------------------
# Stage 5 — Focused extraction
# ---------------------------------------------------------------------------

def stage_extract(
    case_id: str,
    focuses: list[str],
    *,
    dry_run: bool,
    skip_llm: bool,
    max_cost: Optional[float],
) -> tuple[StageResult, list[Path]]:
    """Run ingest_case.py for each focus. Returns (result, list of draft paths)."""
    if skip_llm:
        return StageResult("extract", "skip", "Extraction skipped (--skip-llm-review)"), []

    if dry_run:
        return (
            StageResult("extract", "ok", f"[dry-run] Would run extraction for focuses: {focuses}"),
            [],
        )

    all_drafts: list[Path] = []
    errors: list[str] = []
    jurisdiction = _infer_jurisdiction(case_id)

    for focus in focuses:
        cmd = [
            _python(), _script("ingest_case.py"),
            "--case-id", case_id,
            "--focus", focus,
        ]
        if max_cost is not None:
            cmd += ["--max-cost", str(max_cost)]

        result = _run_subprocess(cmd, capture=True)
        if result.returncode != 0:
            errors.append(f"focus={focus}: exit {result.returncode}: {result.stderr[:200]}")
            continue

        # Discover the draft written by this run
        draft_dir = _DRAFTS_DIR / jurisdiction
        if draft_dir.exists():
            candidates = sorted(draft_dir.glob(f"{case_id}.{focus}.*.draft.yaml"))
            if not candidates:
                candidates = sorted(draft_dir.glob(f"{case_id}.*{focus}*.draft.yaml"))
            all_drafts.extend(candidates)

    if errors:
        return (
            StageResult(
                "extract", "error" if not all_drafts else "warn",
                f"{len(errors)} focus(es) failed; {len(all_drafts)} draft(s) written",
                details=errors,
            ),
            all_drafts,
        )

    return (
        StageResult("extract", "ok", f"{len(focuses)} focus(es) run; {len(all_drafts)} draft(s) written"),
        all_drafts,
    )


# ---------------------------------------------------------------------------
# Stage 6 — Merge drafts
# ---------------------------------------------------------------------------

def stage_merge_drafts(
    case_id: str,
    draft_paths: list[Path],
    jurisdiction: str,
    *,
    dry_run: bool,
) -> tuple[StageResult, Optional[Path]]:
    """Merge all focus drafts into a single merged draft."""
    if not draft_paths:
        return (
            StageResult("merge_drafts", "skip", "No drafts to merge — skipping"),
            None,
        )

    merged_path = _DRAFTS_DIR / jurisdiction.lower() / f"{case_id}.merged.draft.yaml"

    if dry_run:
        return (
            StageResult("merge_drafts", "ok", f"[dry-run] Would merge {len(draft_paths)} draft(s)"),
            None,
        )

    cmd = [
        _python(), _script("merge_drafts.py"),
        "--case-id", case_id,
        "--output", str(merged_path),
    ] + [str(p) for p in draft_paths]

    result = _run_subprocess(cmd)
    if result.returncode != 0:
        return (
            StageResult(
                "merge_drafts", "error",
                f"merge_drafts.py failed (exit {result.returncode})",
                details=[result.stderr.strip()],
            ),
            None,
        )

    return StageResult("merge_drafts", "ok", f"Merged draft: {merged_path}"), merged_path


# ---------------------------------------------------------------------------
# Stage 7 — Review readiness
# ---------------------------------------------------------------------------

def stage_check_readiness(
    case_id: str,
    merged_draft: Optional[Path],
    draft_paths: list[Path],
    *,
    dry_run: bool,
) -> tuple[StageResult, Optional[Path], str]:
    """
    Run check_review_readiness.py --packet.
    Returns (stage_result, packet_path, readiness_status).
    readiness_status: "READY" | "WARN" | "FAIL" | "SKIP"
    """
    jurisdiction = _infer_jurisdiction(case_id)
    packet_path = _DRAFTS_DIR / jurisdiction / f"{case_id}.review_packet.md"

    # Determine which drafts to check
    check_paths: list[Path] = []
    if merged_draft and merged_draft.exists():
        check_paths = [merged_draft]
    elif draft_paths:
        check_paths = draft_paths

    if not check_paths:
        return (
            StageResult("check_readiness", "skip", "No drafts to check — skipping readiness"),
            None,
            "SKIP",
        )

    if dry_run:
        return (
            StageResult("check_readiness", "ok", "[dry-run] Would run check_review_readiness.py"),
            None,
            "SKIP",
        )

    cmd = [
        _python(), _script("check_review_readiness.py"),
        "--case-id", case_id,
        "--packet",
    ] + ["--draft=" + str(p) for p in check_paths]

    result = _run_subprocess(cmd)

    # Exit codes: 0=pass, 1=warnings, 2=errors
    if result.returncode == 0:
        readiness = "READY"
        status = "ok"
        msg = "Readiness: PASS"
    elif result.returncode == 1:
        readiness = "WARN"
        status = "warn"
        msg = "Readiness: WARN (warnings require human sign-off)"
    else:
        readiness = "FAIL"
        status = "error"
        msg = "Readiness: FAIL (errors must be fixed)"

    details = [line for line in result.stdout.strip().splitlines() if line.strip()][:10]
    out_packet = packet_path if packet_path.exists() else None
    return StageResult("check_readiness", status, msg, details=details), out_packet, readiness


# ---------------------------------------------------------------------------
# Git hygiene check
# ---------------------------------------------------------------------------

_UNTRACKED_WARN_PATTERNS = (
    "data/source_text/",
    "data/drafts/",
    "data/review_learning/",
    "data/evals/results/",
    ".pyc",
    "__pycache__",
    ".review_packet.md",
    ".coverage_plan.yaml",
)


def check_git_hygiene() -> list[str]:
    """Return warnings for generated artifacts appearing in git status."""
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True, text=True,
        cwd=str(_REPO_ROOT),
    )
    warnings = []
    for line in result.stdout.splitlines():
        path_part = line[3:].strip()
        for pattern in _UNTRACKED_WARN_PATTERNS:
            if pattern in path_part:
                warnings.append(
                    f"  {line.strip()}  ← do not commit (generated artifact)"
                )
                break
    return warnings


# ---------------------------------------------------------------------------
# Review packet writer
# ---------------------------------------------------------------------------

def write_run_report(
    result: RunResult,
    run_args: argparse.Namespace,
    out_path: Path,
) -> None:
    lines: list[str] = []
    ts = datetime.datetime.now().isoformat(timespec="seconds")
    lines += [
        f"# Controlled Case Run — {result.case_id}",
        f"Generated: {ts}",
        f"Status: **{result.status}**",
        "",
    ]

    lines += ["## Run Configuration", ""]
    lines.append(f"  case_id:       {result.case_id}")
    lines.append(f"  profile:       {result.profile_id}")
    lines.append(f"  source_url:    {getattr(run_args, 'source_url', 'n/a')}")
    focuses = getattr(run_args, 'focuses', None) or []
    lines.append(f"  focuses:       {', '.join(str(f) for f in focuses)}")
    lines.append(f"  dry_run:       {getattr(run_args, 'dry_run', False)}")
    lines.append(f"  skip_llm:      {getattr(run_args, 'skip_llm_review', False)}")
    lines.append("")

    lines += ["## Stage Summary", ""]
    for stage in result.stages:
        icon = {"ok": "✓", "warn": "⚠", "error": "✗", "skip": "–"}.get(stage.status, "?")
        lines.append(f"  {icon} [{stage.name}] {stage.message}")
        for d in stage.details[:5]:
            lines.append(f"      {d}")
    lines.append("")

    lines += ["## Generated Files", ""]
    if result.generated_files:
        for p in result.generated_files:
            try:
                rel = p.relative_to(_REPO_ROOT)
            except ValueError:
                rel = p
            lines.append(f"  - {rel}")
    else:
        lines.append("  (none — dry run or all stages skipped)")
    lines.append("")

    if result.blockers:
        lines += ["## Blockers", ""]
        for b in result.blockers:
            lines.append(f"  - {b}")
        lines.append("")

    lines += ["## Promotion Recommendation", ""]
    if result.status == READY:
        lines += [
            "  READY FOR HUMAN REVIEW — all checks pass.",
            "",
            "  Next steps:",
            f"    1. Review the packet: data/drafts/{_infer_jurisdiction(result.case_id)}/{result.case_id}.review_packet.md",
            "    2. Spot-check source passages against the PDF.",
            f"    3. When satisfied, run:",
            f"       python apps/api/scripts/promote_case_pipeline.py --case-id {result.case_id}",
        ]
    elif result.status == NOT_READY:
        lines += [
            "  NOT READY — resolve blockers listed above, then re-run:",
            f"    python apps/api/scripts/run_controlled_case.py --case-id {result.case_id} [original flags]",
        ]
    else:
        lines += [
            "  FAILED — source fetch or script execution failed.",
            "  Check error details in Stage Summary above.",
        ]
    lines.append("")

    lines += ["## Git Hygiene", ""]
    if result.git_warnings:
        lines.append("  The following generated files appear in `git status`.")
        lines.append("  DO NOT commit them:")
        lines.append("")
        lines.extend(result.git_warnings)
        lines.append("")
        lines.append("  Ensure these paths are covered by .gitignore:")
        lines.append("    data/source_text/  data/drafts/  data/review_learning/")
        lines.append("    data/evals/results/  *.pyc  __pycache__/")
    else:
        lines.append("  No unintended generated files detected in git status.")
    lines.append("")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines))


# ---------------------------------------------------------------------------
# Terminal summary
# ---------------------------------------------------------------------------

def print_summary(result: RunResult, packet_path: Optional[Path]) -> None:
    sep = "─" * 60
    print(f"\n{sep}")
    print(f"  {result.case_id}  →  {result.status}")
    print(sep)

    for stage in result.stages:
        icon = {"ok": "✓", "warn": "⚠", "error": "✗", "skip": "–"}.get(stage.status, "?")
        print(f"  {icon}  {stage.name:<20}  {stage.message}")

    if result.blockers:
        print("\n  BLOCKERS:")
        for b in result.blockers:
            print(f"    • {b}")

    if packet_path:
        print(f"\n  Review packet: {packet_path.relative_to(_REPO_ROOT)}")

    print("\n  Next commands:")
    jur = _infer_jurisdiction(result.case_id)
    if result.status == READY:
        print(f"    # Spot-check then promote:")
        print(f"    python apps/api/scripts/promote_case_pipeline.py --case-id {result.case_id}")
    elif result.status == NOT_READY:
        print(f"    # Fix blockers then re-run:")
        print(f"    python apps/api/scripts/run_controlled_case.py \\")
        print(f"        --case-id {result.case_id} [original flags]")
    else:
        print("    # Investigate errors in the stage summary above, then re-run.")

    if result.git_warnings:
        print("\n  GIT WARNING — do not commit these files:")
        for w in result.git_warnings[:5]:
            print(f"    {w.strip()}")

    print(sep)


# ---------------------------------------------------------------------------
# Build stage plan (testable, pure)
# ---------------------------------------------------------------------------

def build_stage_plan(
    *,
    has_source_cache: bool,
    has_existing_drafts: bool,
    dry_run: bool,
    skip_llm: bool,
    focuses: list[str],
) -> list[str]:
    """Return the ordered list of stage names that will be executed."""
    stages = ["seed", "fetch_source", "select_profile", "plan_coverage"]
    if not skip_llm:
        stages.append("extract")
    elif has_existing_drafts:
        stages.append("use_existing_drafts")
    stages.extend(["merge_drafts", "check_readiness"])
    return stages


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def run(args: argparse.Namespace) -> RunResult:
    case_id = args.case_id
    jurisdiction = args.jurisdiction or _infer_jurisdiction(case_id)
    focuses = args.focuses or []

    result = RunResult(case_id=case_id, status=FAILED, profile_id="unknown")

    # ---- Stage 1: Canonical seed ----
    seed_data = _build_seed(
        case_id=case_id,
        case_name=args.case_name,
        jurisdiction=jurisdiction,
        authority=args.authority,
        authority_reference=getattr(args, "authority_reference", None),
        procedure_stage=args.procedure_stage,
        outcome=args.outcome,
        decision_date=getattr(args, "decision_date", None),
        sector=getattr(args, "sector", None),
        parties=getattr(args, "parties", None) or [],
        source_url=args.source_url,
    )
    s1, seed_path = stage_seed(
        case_id, seed_data, jurisdiction,
        dry_run=args.dry_run, overwrite=getattr(args, "overwrite_drafts", False),
    )
    result.stages.append(s1)
    if s1.status == "error":
        result.status = FAILED
        return result
    if seed_path:
        result.generated_files.append(seed_path)

    # ---- Stage 2: Source fetch ----
    s2, cache_path = stage_fetch_source(
        case_id, args.source_url,
        dry_run=args.dry_run, overwrite=getattr(args, "overwrite_drafts", False),
    )
    result.stages.append(s2)
    if s2.status == "error":
        result.status = FAILED
        return result
    if cache_path:
        result.generated_files.append(cache_path)

    # ---- Stage 3: Profile selection ----
    case_meta = {
        "jurisdiction": jurisdiction,
        "authority": args.authority,
        "procedure_stage": args.procedure_stage,
    }
    s3, profile = stage_select_profile(
        case_id, getattr(args, "profile", None), case_meta,
    )
    result.stages.append(s3)
    if profile is None:
        result.status = FAILED
        return result
    result.profile_id = profile.profile_id

    # Default focuses from profile if not supplied
    if not focuses:
        focuses = list(profile.focus_defaults) or ["outcome_metadata", "market_definition"]
        args.focuses = focuses

    # ---- Stage 4: Coverage plan ----
    s4, plan_path = stage_plan_coverage(case_id, profile, dry_run=args.dry_run)
    result.stages.append(s4)
    # In dry-run mode, plan_coverage failure is expected (no real cache written yet) — warn only
    if s4.status == "error" and not args.dry_run:
        result.blockers.append(f"Coverage planning failed: {s4.message}")
    if plan_path:
        result.generated_files.append(plan_path)

    # ---- Stage 5: Extraction ----
    skip_llm = getattr(args, "skip_llm_review", False)
    max_cost = getattr(args, "max_cost", None)
    s5, draft_paths = stage_extract(
        case_id, focuses,
        dry_run=args.dry_run, skip_llm=skip_llm, max_cost=max_cost,
    )
    result.stages.append(s5)
    if s5.status == "error":
        result.blockers.append(f"Extraction failed: {s5.message}")
    result.generated_files.extend(draft_paths)

    # If skipping LLM, discover existing drafts
    if skip_llm:
        jur_dir = _DRAFTS_DIR / jurisdiction.lower()
        if jur_dir.exists():
            draft_paths = sorted(
                p for p in jur_dir.glob(f"{case_id}.*.draft.yaml")
                if ".merged." not in p.name
            )

    # ---- Stage 6: Merge drafts ----
    s6, merged_path = stage_merge_drafts(
        case_id, draft_paths, jurisdiction, dry_run=args.dry_run,
    )
    result.stages.append(s6)
    if s6.status == "error":
        result.blockers.append(f"Merge failed: {s6.message}")
    if merged_path:
        result.generated_files.append(merged_path)

    # ---- Stage 7: Readiness check ----
    s7, packet_path, readiness = stage_check_readiness(
        case_id, merged_path, draft_paths, dry_run=args.dry_run,
    )
    result.stages.append(s7)
    if packet_path:
        result.generated_files.append(packet_path)

    # ---- Git hygiene ----
    result.git_warnings = check_git_hygiene()

    # ---- Determine final status ----
    if result.blockers:
        result.status = NOT_READY
    elif readiness == "FAIL":
        result.status = NOT_READY
        result.blockers.append("Readiness check has errors — see review packet for details")
    elif readiness in ("READY", "WARN"):
        result.status = READY
    elif readiness == "SKIP" and args.dry_run:
        result.status = READY  # dry run is always "ready" for display purposes
    else:
        result.status = NOT_READY
        result.blockers.append("Readiness check skipped — no drafts produced")

    # ---- Write run report ----
    if not args.dry_run:
        report_path = _DRAFTS_DIR / jurisdiction.lower() / f"{case_id}.run_report.md"
        write_run_report(result, args, report_path)
        result.generated_files.append(report_path)

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "One-command controlled case expansion orchestrator. "
            "Produces READY_FOR_HUMAN_REVIEW or NOT_READY with actionable blockers."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Required
    parser.add_argument("--case-id", required=True, help="Case ID (e.g. us_example_co_2025)")
    parser.add_argument("--source-url", required=True, help="PDF or web URL for the primary source document")
    parser.add_argument("--case-name", required=True, help="Human-readable case name (e.g. 'FTC v. Acme Corp')")
    parser.add_argument("--jurisdiction", required=True, help="Jurisdiction (US, EU, UK)")
    parser.add_argument("--authority", required=True, help="Issuing authority (court or commission)")
    parser.add_argument("--procedure-stage", required=True, help="Procedure stage (e.g. federal_district_court, phase_2)")
    parser.add_argument("--outcome", required=True, help="Case outcome (blocked, cleared, cleared_with_conditions, ...)")

    # Optional metadata
    parser.add_argument("--authority-reference", help="Authority reference number (e.g. M.12345)")
    parser.add_argument("--decision-date", help="Decision date (YYYY-MM-DD)")
    parser.add_argument("--sector", help="Industry sector")
    parser.add_argument(
        "--parties",
        action="append",
        metavar="NAME[:ROLE]",
        help="Party name with optional role (acquirer/target). Repeat for each party.",
    )

    # Extraction control
    parser.add_argument(
        "--profile",
        help="Pipeline profile ID (ec_decision | cma_report | us_court_opinion). Inferred if omitted.",
    )
    parser.add_argument(
        "--focuses",
        nargs="+",
        metavar="FOCUS",
        help="Extraction focuses (default: from profile). e.g. outcome_metadata market_definition theories",
    )
    parser.add_argument(
        "--max-cost",
        type=float,
        metavar="USD",
        help="Max estimated API cost in USD per extraction run (default: profile/script default)",
    )

    # Orchestration flags
    parser.add_argument("--dry-run", action="store_true", help="Print what would happen without writing files")
    parser.add_argument("--overwrite-drafts", action="store_true", help="Overwrite existing seed, cache, and drafts")
    parser.add_argument("--skip-llm-review", action="store_true", help="Skip Claude extraction; validate existing drafts only")

    # Promote gate (explicit opt-in only)
    parser.add_argument(
        "--promote",
        action="store_true",
        help=(
            "NOT IMPLEMENTED: use promote_case_pipeline.py explicitly after human review. "
            "This flag is accepted but does nothing — promotion requires a separate human-confirmed step."
        ),
    )

    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)

    if getattr(args, "promote", False):
        print(
            "NOTE: --promote is not implemented in this orchestrator. "
            "After reviewing the packet, run:\n"
            f"  python apps/api/scripts/promote_case_pipeline.py --case-id {args.case_id}",
            file=sys.stderr,
        )

    result = run(args)

    jur = _infer_jurisdiction(result.case_id)
    packet_path = _DRAFTS_DIR / jur / f"{result.case_id}.review_packet.md"
    print_summary(result, packet_path if packet_path.exists() else None)

    return 0 if result.status == READY else 1


if __name__ == "__main__":
    sys.exit(main())
