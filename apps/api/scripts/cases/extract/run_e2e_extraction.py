#!/usr/bin/env python3
"""
run_e2e_extraction.py — full-depth extraction orchestrator for case-index entries.

Runs per-focus dual extraction, merges completed Draft A files into one reviewable
draft, and writes the deterministic readiness packet. It does not resolve
conflicts or promote canonical data.
"""

from __future__ import annotations

import argparse
import datetime as dt
import subprocess
import sys
from pathlib import Path
from typing import Optional

import yaml

_SCRIPTS_DIR = Path(__file__).resolve().parent
_API_DIR = _SCRIPTS_DIR.parent.parent.parent
_REPO_ROOT = _API_DIR.parents[1]
_CASES_DIR = _REPO_ROOT / "data" / "cases"
_DRAFTS_DIR = _REPO_ROOT / "data" / "drafts"
_DEFAULT_CACHE_DIR = _REPO_ROOT / "data" / "source_text"

for _p in (
    str(_API_DIR),
    str(_SCRIPTS_DIR),
    str(_SCRIPTS_DIR.parent / "review"),
):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from check_review_readiness import (  # type: ignore
    _find_coverage_plan,
    run_checks,
    write_review_packet,
)
from merge_drafts import merge_drafts  # type: ignore
from pipeline_profile import PipelineProfile, select_profile

DUAL_FOCUSES = ("market_definition", "theories", "remedies")
SINGLE_FOCUSES = ("outcome_metadata",)
VALID_FOCUSES = DUAL_FOCUSES + SINGLE_FOCUSES


def _infer_jurisdiction(case_id: str) -> str:
    for prefix, jur in (("eu_", "eu"), ("uk_", "uk"), ("us_", "us")):
        if case_id.startswith(prefix):
            return jur
    return "unknown"


def _python() -> str:
    venv_python = _API_DIR / ".venv" / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)
    return sys.executable


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(_REPO_ROOT))
    except ValueError:
        return str(path)


def _state_path(case_id: str, jurisdiction: str) -> Path:
    return _DRAFTS_DIR / jurisdiction / f"{case_id}.e2e_state.yaml"


def _artifact_paths(case_id: str, jurisdiction: str, focus: str) -> dict[str, Path]:
    draft_dir = _DRAFTS_DIR / jurisdiction
    stem = f"{case_id}.{focus}"
    if focus in DUAL_FOCUSES:
        return {
            "draft_a": draft_dir / f"{stem}.draft_a.yaml",
            "draft_b": draft_dir / f"{stem}.draft_b.yaml",
            "conflicts": draft_dir / f"{stem}.conflicts.yaml",
            "review": draft_dir / f"{stem}.review.md",
        }
    return {
        "draft": draft_dir / f"{stem}.draft.yaml",
        "review": draft_dir / f"{stem}.review.md",
    }


def _load_state(path: Path) -> dict:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _new_state(case_id: str, focuses: list[str]) -> dict:
    return {
        "case_id": case_id,
        "started_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "focuses": {focus: "pending" for focus in focuses},
        "focus_errors": {},
        "merged_draft": None,
        "readiness_status": None,
    }


def _write_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(state, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _select_focuses(profile: PipelineProfile, override: Optional[str]) -> list[str]:
    if override:
        focuses = [f.strip() for f in override.split(",") if f.strip()]
    else:
        focuses = [f for f in profile.focus_defaults if f in VALID_FOCUSES]
    unknown = [f for f in focuses if f not in VALID_FOCUSES]
    if unknown:
        raise ValueError(f"Unsupported focus override(s): {', '.join(unknown)}")
    return list(dict.fromkeys(focuses))


def _build_ingest_cmd(args: argparse.Namespace, focus: str) -> list[str]:
    cmd = [
        _python(),
        str(_SCRIPTS_DIR / "ingest_case.py"),
        "--case-id",
        args.case_id,
        "--focus",
        focus,
        "--provider",
        args.provider,
        "--max-cost",
        f"{args.max_cost:.2f}",
        "--cache-dir",
        str(args.cache_dir),
    ]
    if args.from_index:
        cmd.append("--from-index")
    if args.pdf_url:
        cmd.extend(["--pdf-url", args.pdf_url])
    if focus in DUAL_FOCUSES:
        cmd.append("--dual-extract")
        if args.dual_same_model:
            cmd.append("--dual-same-model")
    if args.batch_by_section:
        cmd.append("--batch-by-section")
    page_range = args.page_range
    if focus == "outcome_metadata" and page_range is None:
        page_range = "1:30"
    if page_range:
        cmd.extend(["--page-range", page_range])
    return cmd


def _run_focus(args: argparse.Namespace, focus: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        _build_ingest_cmd(args, focus),
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
    )


def _completed_merge_input_paths(case_id: str, jurisdiction: str, state: dict) -> list[Path]:
    draft_paths = []
    for focus, status in state.get("focuses", {}).items():
        if status != "completed":
            continue
        paths = _artifact_paths(case_id, jurisdiction, focus)
        draft_path = paths["draft_a"] if focus in DUAL_FOCUSES else paths["draft"]
        if draft_path.exists():
            draft_paths.append(draft_path)
    return draft_paths


def _merge_completed_drafts(
    case_id: str,
    jurisdiction: str,
    state: dict,
) -> tuple[Optional[Path], list[str], list[Path]]:
    draft_paths = _completed_merge_input_paths(case_id, jurisdiction, state)
    if not draft_paths:
        return None, ["No completed draft files found to merge."], []

    merged, warnings = merge_drafts(draft_paths, case_id_override=case_id)
    out_path = _DRAFTS_DIR / jurisdiction / f"{case_id}.e2e.merged.draft.yaml"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        yaml.safe_dump(merged, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return out_path, warnings, draft_paths


def _run_readiness(
    case_id: str,
    jurisdiction: str,
    profile: PipelineProfile,
    merged_path: Path,
    draft_paths: list[Path],
) -> tuple[str, list[dict], Path]:
    draft = yaml.safe_load(merged_path.read_text(encoding="utf-8")) or {}
    plan_path = _find_coverage_plan(case_id)
    plan = yaml.safe_load(plan_path.read_text(encoding="utf-8")) if plan_path else None
    input_drafts = draft_paths or [merged_path]
    issues = run_checks(draft, plan, input_drafts, profile=profile)
    packet_path = _DRAFTS_DIR / jurisdiction / f"{case_id}.e2e.review_packet.md"
    write_review_packet(case_id, draft, plan, input_drafts, issues, packet_path)
    errors = [i for i in issues if i.get("level") == "error"]
    warnings = [i for i in issues if i.get("level") == "warning"]
    status = "FAIL" if errors else ("WARN" if warnings else "PASS")
    return status, issues, packet_path


def _write_summary(
    case_id: str,
    jurisdiction: str,
    profile: PipelineProfile,
    state: dict,
    merged_path: Optional[Path],
    packet_path: Optional[Path],
    merge_warnings: list[str],
    readiness_issues: list[dict],
) -> Path:
    summary_path = _DRAFTS_DIR / jurisdiction / f"{case_id}.e2e.summary.md"
    lines = [
        f"# E2E Extraction Summary — {case_id}",
        "",
        f"Profile: `{profile.profile_id}`",
        f"Generated: {dt.datetime.now(dt.timezone.utc).isoformat()}",
        "",
        "## Focuses",
    ]
    for focus, status in state.get("focuses", {}).items():
        paths = _artifact_paths(case_id, jurisdiction, focus)
        existing = [f"{name}: `{_rel(path)}`" for name, path in paths.items() if path.exists()]
        detail = "; ".join(existing) if existing else "no artifacts found"
        lines.append(f"- `{focus}`: **{status}** — {detail}")
        error = state.get("focus_errors", {}).get(focus)
        if error:
            lines.append(f"  - Error: `{error[:300]}`")

    lines.extend(["", "## Merge"])
    if merged_path is None:
        lines.append("- Merged draft: not written")
    else:
        lines.append(f"- Merged draft: `{_rel(merged_path)}`")
    for warning in merge_warnings:
        lines.append(f"- Warning: {warning}")

    lines.extend(["", "## Readiness"])
    lines.append(f"- Status: **{state.get('readiness_status') or 'not run'}**")
    if packet_path is not None:
        lines.append(f"- Packet: `{_rel(packet_path)}`")
    for issue in readiness_issues:
        lines.append(f"- {issue.get('level', 'issue').upper()}: {issue.get('code')} — {issue.get('message')}")

    lines.extend([
        "",
        "## Next Steps",
        "1. Resolve each completed dual-focus conflict report with `merge_drafts.py --from-conflict-report`.",
        "2. Re-merge the resolved per-focus drafts with `merge_drafts.py`.",
        "3. Re-run `check_review_readiness.py --packet` on the final merged draft.",
        "4. Promote with `run_case_promotion.py` after human sign-off.",
        "",
    ])
    summary_path.write_text("\n".join(lines), encoding="utf-8")
    return summary_path


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run full-depth per-focus extraction and readiness orchestration.",
    )
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--from-index", action="store_true")
    parser.add_argument("--pdf-url")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--max-cost", type=float, default=2.00)
    parser.add_argument("--provider", choices=["anthropic", "gemini"], default="anthropic")
    parser.add_argument("--dual-same-model", action="store_true")
    parser.add_argument("--batch-by-section", action="store_true")
    parser.add_argument("--page-range")
    parser.add_argument("--focuses")
    parser.add_argument("--profile")
    parser.add_argument("--cache-dir", default=str(_DEFAULT_CACHE_DIR))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    args.cache_dir = Path(args.cache_dir)

    profile = select_profile(args.case_id, profile_id=args.profile)
    focuses = _select_focuses(profile, args.focuses)
    jurisdiction = _infer_jurisdiction(args.case_id)
    state_path = _state_path(args.case_id, jurisdiction)
    state = _load_state(state_path) if args.resume else {}
    if not state:
        state = _new_state(args.case_id, focuses)
    for focus in focuses:
        state.setdefault("focuses", {}).setdefault(focus, "pending")
    state["profile_id"] = profile.profile_id

    if args.dry_run:
        print(f"Case:    {args.case_id}")
        print(f"Profile: {profile.profile_id}")
        print(f"State:   {_rel(state_path)}")
        for focus in focuses:
            if args.resume and state["focuses"].get(focus) == "completed":
                print(f"SKIP completed focus: {focus}")
                continue
            print(" ".join(_build_ingest_cmd(args, focus)))
        return 0

    _write_state(state_path, state)
    for focus in focuses:
        if args.resume and state["focuses"].get(focus) == "completed":
            print(f"Focus {focus}: skip (completed)")
            continue
        print(f"Focus {focus}: running")
        result = _run_focus(args, focus)
        if result.stdout:
            print(result.stdout)
        if result.returncode == 0:
            state["focuses"][focus] = "completed"
            state.get("focus_errors", {}).pop(focus, None)
        else:
            state["focuses"][focus] = "failed"
            state.setdefault("focus_errors", {})[focus] = (result.stderr or result.stdout or "").strip()
            if result.stderr:
                print(result.stderr, file=sys.stderr)
        _write_state(state_path, state)

    merged_path, merge_warnings, merged_inputs = _merge_completed_drafts(args.case_id, jurisdiction, state)
    packet_path = None
    readiness_issues: list[dict] = []
    if merged_path is not None:
        state["merged_draft"] = _rel(merged_path)
        readiness_status, readiness_issues, packet_path = _run_readiness(
            args.case_id,
            jurisdiction,
            profile,
            merged_path,
            merged_inputs,
        )
        state["readiness_status"] = readiness_status
        _write_state(state_path, state)

    summary_path = _write_summary(
        args.case_id,
        jurisdiction,
        profile,
        state,
        merged_path,
        packet_path,
        merge_warnings,
        readiness_issues,
    )
    print(f"State:   {_rel(state_path)}")
    if merged_path is not None:
        print(f"Merged:  {_rel(merged_path)}")
    if packet_path is not None:
        print(f"Packet:  {_rel(packet_path)}")
    print(f"Summary: {_rel(summary_path)}")

    failed = any(state.get("focuses", {}).get(focus) == "failed" for focus in focuses)
    return 1 if failed or merged_path is None else 0


if __name__ == "__main__":
    raise SystemExit(main())
