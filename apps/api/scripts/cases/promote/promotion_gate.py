#!/usr/bin/env python3
"""Shared draft-to-canonical promotion gates."""

from __future__ import annotations

import datetime as dt
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_SCRIPTS_DIR = Path(__file__).resolve().parent
_API_DIR = _SCRIPTS_DIR.parent.parent.parent
_REPO_ROOT = _API_DIR.parent.parent

def default_promotion_python(api_dir: Path | None = None) -> str:
    """Prefer apps/api/.venv when present so promotion subprocesses match local dev."""
    root = api_dir or _API_DIR
    venv_python = root / ".venv" / "bin" / "python3"
    return str(venv_python) if venv_python.exists() else sys.executable


DEFAULT_PYTHON = default_promotion_python()


@dataclass(frozen=True)
class PromotionPaths:
    repo_root: Path = _REPO_ROOT
    drafts_dir: Path = _REPO_ROOT / "data" / "drafts"
    cases_dir: Path = _REPO_ROOT / "data" / "cases"
    batch_runs_dir: Path = _REPO_ROOT / "data" / "batch_runs"
    python: str = DEFAULT_PYTHON


@dataclass(frozen=True)
class PromotionCandidate:
    case_id: str
    jurisdiction: str
    draft_path: Path
    draft_kind: str
    review_status: str
    output_path: Path
    conflict_reports: tuple[Path, ...] = ()


@dataclass(frozen=True)
class PromotionPolicy:
    overwrite: bool = False
    procedure_stage: str | None = None
    block_source_integrity_warnings: bool = True
    allow_missing_conflict_reports: bool = True
    verbose: bool = False


@dataclass
class GateResult:
    status: str
    message: str = ""
    errors: int | None = None
    warnings: int | None = None
    reports_checked: int | None = None
    command: list[str] = field(default_factory=list)
    returncode: int | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"status": self.status}
        if self.message:
            data["message"] = self.message
        if self.errors is not None:
            data["errors"] = self.errors
        if self.warnings is not None:
            data["warnings"] = self.warnings
        if self.reports_checked is not None:
            data["reports_checked"] = self.reports_checked
        if self.command:
            data["command"] = " ".join(self.command)
        if self.returncode is not None:
            data["returncode"] = self.returncode
        return data


@dataclass
class PromotionOutcome:
    case_id: str
    status: str
    draft_path: Path
    draft_kind: str
    review_status: str
    output_path: Path
    timestamp: str
    message: str
    gates: dict[str, GateResult] = field(default_factory=dict)

    def to_dict(self, repo_root: Path | None = None) -> dict[str, Any]:
        root = repo_root or _REPO_ROOT
        data: dict[str, Any] = {
            "status": self.status,
            "draft_path": _display_path(self.draft_path, root),
            "draft_kind": self.draft_kind,
            "review_status": self.review_status,
            "output_path": _display_path(self.output_path, root),
            "timestamp": self.timestamp,
            "message": self.message,
        }
        for key, result in self.gates.items():
            data[key] = result.to_dict()
        return data


def utc_timestamp() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _display_path(path: Path, repo_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(repo_root.resolve()))
    except ValueError:
        return str(path)


def last_meaningful_line(output: str) -> str:
    for line in reversed(output.splitlines()):
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def parse_source_integrity_counts(output: str) -> tuple[int, int] | None:
    """Parse the final source-integrity summary as (errors, warnings)."""
    matches = list(re.finditer(r"(\d+)\s+error\(s\),\s*(\d+)\s+warning\(s\)", output))
    if not matches:
        return None
    match = matches[-1]
    return int(match.group(1)), int(match.group(2))


def unresolved_conflicts(report_path: Path) -> list[str]:
    """Return conflict fields whose `resolution` is missing or blank."""
    data = yaml.safe_load(report_path.read_text(encoding="utf-8")) or {}
    report = data.get("conflict_report", data)
    if not isinstance(report, dict) or "conflicts" not in report:
        raise ValueError(
            f"{report_path} is not a conflict report (missing 'conflicts' key)"
        )

    open_fields: list[str] = []
    for conflict in report.get("conflicts") or []:
        if not str(conflict.get("resolution") or "").strip():
            open_fields.append(str(conflict.get("field", "?")))
    return open_fields


def _run_capture(
    paths: PromotionPaths,
    cmd: list[str],
    *,
    verbose: bool = False,
) -> subprocess.CompletedProcess:
    if verbose:
        print(f"\n$ {' '.join(cmd)}", flush=True)
    result = subprocess.run(
        cmd,
        cwd=str(paths.repo_root),
        capture_output=True,
        text=True,
    )
    if verbose:
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
    return result


def _command_result_gate(
    *,
    status_key: str,
    paths: PromotionPaths,
    cmd: list[str],
    pass_message: str,
    fail_message: str,
    verbose: bool = False,
) -> GateResult:
    result = _run_capture(paths, cmd, verbose=verbose)
    if result.returncode == 0:
        return GateResult(
            "pass",
            pass_message,
            command=cmd,
            returncode=result.returncode,
        )
    output = (result.stderr or "") + (result.stdout or "")
    detail = last_meaningful_line(output) or fail_message
    return GateResult(
        status_key,
        detail,
        command=cmd,
        returncode=result.returncode,
    )


def build_temp_candidate(
    candidate: PromotionCandidate,
    paths: PromotionPaths,
    policy: PromotionPolicy,
    temp_cases_dir: Path,
    *,
    verbose: bool | None = None,
) -> tuple[Path | None, GateResult]:
    gate_verbose = policy.verbose if verbose is None else verbose
    """Build canonical YAML under *temp_cases_dir* without touching data/cases."""
    out_path = temp_cases_dir / candidate.jurisdiction / f"{candidate.case_id}.yaml"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        paths.python,
        "apps/api/scripts/cases/promote/promote_draft_to_canonical.py",
        "--case-id",
        candidate.case_id,
        "--draft",
        str(candidate.draft_path),
        "--output",
        str(out_path),
        "--drafts-dir",
        str(paths.drafts_dir),
        "--cases-dir",
        str(paths.cases_dir),
    ]
    if policy.procedure_stage:
        cmd += ["--procedure-stage", policy.procedure_stage]

    result = _run_capture(paths, cmd, verbose=gate_verbose)
    if result.returncode != 0:
        output = (result.stderr or "") + (result.stdout or "")
        return None, GateResult(
            "candidate_error",
            last_meaningful_line(output) or "temporary canonicalization failed",
            command=cmd,
            returncode=result.returncode,
        )

    return out_path, GateResult(
        "pass",
        "temporary canonical candidate built",
        command=cmd,
        returncode=result.returncode,
    )


def run_schema_gate(
    paths: PromotionPaths,
    temp_cases_dir: Path,
    *,
    verbose: bool = False,
) -> GateResult:
    cmd = [
        paths.python,
        "apps/api/scripts/cases/integrity/validate_cases.py",
        "--cases-dir",
        str(temp_cases_dir),
    ]
    return _command_result_gate(
        status_key="blocked_schema",
        paths=paths,
        cmd=cmd,
        pass_message="schema validation passed",
        fail_message="schema validation failed",
        verbose=verbose,
    )


def run_source_links_gate(
    paths: PromotionPaths,
    case_id: str,
    temp_cases_dir: Path,
    *,
    verbose: bool = False,
) -> GateResult:
    cmd = [
        paths.python,
        "apps/api/scripts/cases/integrity/check_source_links.py",
        "--cases-dir",
        str(temp_cases_dir),
        "--case-id",
        case_id,
    ]
    return _command_result_gate(
        status_key="blocked_source_links",
        paths=paths,
        cmd=cmd,
        pass_message="source links passed",
        fail_message="source-link check failed",
        verbose=verbose,
    )


def run_source_integrity_gate(
    paths: PromotionPaths,
    case_id: str,
    temp_cases_dir: Path,
    *,
    block_warnings: bool = True,
    verbose: bool = False,
) -> GateResult:
    cmd = [
        paths.python,
        "apps/api/scripts/cases/integrity/check_source_integrity.py",
        "--cases-dir",
        str(temp_cases_dir),
        "--case-id",
        case_id,
        "--no-cache",
    ]
    result = _run_capture(paths, cmd, verbose=verbose)
    output = (result.stdout or "") + (result.stderr or "")
    counts = parse_source_integrity_counts(output)
    if counts is None:
        if result.returncode == 0:
            return GateResult(
                "pass",
                "source integrity passed",
                command=cmd,
                returncode=result.returncode,
            )
        return GateResult(
            "blocked_source_integrity",
            last_meaningful_line(output) or "source-integrity output was not parseable",
            command=cmd,
            returncode=result.returncode,
        )

    errors, warnings = counts
    blocks = errors > 0 or (block_warnings and warnings > 0)
    if blocks or result.returncode != 0:
        return GateResult(
            "blocked_source_integrity",
            f"{errors} error(s), {warnings} warning(s)",
            errors=errors,
            warnings=warnings,
            command=cmd,
            returncode=result.returncode,
        )

    return GateResult(
        "pass",
        "source integrity passed",
        errors=errors,
        warnings=warnings,
        command=cmd,
        returncode=result.returncode,
    )


def run_semantic_lint_gate(
    paths: PromotionPaths,
    case_id: str,
    temp_cases_dir: Path,
    *,
    verbose: bool = False,
) -> GateResult:
    cmd = [
        paths.python,
        "apps/api/scripts/cases/integrity/lint_case_semantics.py",
        "--cases-dir",
        str(temp_cases_dir),
        "--case-id",
        case_id,
    ]
    return _command_result_gate(
        status_key="blocked_semantic_lint",
        paths=paths,
        cmd=cmd,
        pass_message="semantic lint passed",
        fail_message="semantic lint failed",
        verbose=verbose,
    )


def _discover_conflict_reports(candidate: PromotionCandidate) -> tuple[Path, ...]:
    if candidate.conflict_reports:
        return candidate.conflict_reports
    return tuple(sorted(candidate.draft_path.parent.glob(f"{candidate.case_id}.*.conflicts.yaml")))


def run_conflict_gate(
    candidate: PromotionCandidate,
    *,
    allow_missing: bool = True,
) -> GateResult:
    reports = _discover_conflict_reports(candidate)
    if not reports:
        status = "skipped_no_reports" if allow_missing else "blocked_conflicts"
        return GateResult(status, "no conflict reports found", reports_checked=0)

    unresolved: list[str] = []
    for report in reports:
        try:
            open_fields = unresolved_conflicts(report)
        except ValueError as exc:
            return GateResult(
                "blocked_conflicts",
                str(exc),
                reports_checked=len(reports),
            )
        for field_name in open_fields:
            unresolved.append(f"{report.name}: {field_name}")

    if unresolved:
        sample = ", ".join(unresolved[:5])
        more = "" if len(unresolved) <= 5 else f" (+{len(unresolved) - 5} more)"
        return GateResult(
            "blocked_conflicts",
            f"{len(unresolved)} unresolved conflict(s): {sample}{more}",
            reports_checked=len(reports),
        )

    return GateResult(
        "pass",
        "all conflict reports resolved",
        reports_checked=len(reports),
    )


def run_graph_seed(paths: PromotionPaths, *, verbose: bool = False) -> GateResult:
    cmd = [paths.python, "graph/seed_graph.py"]
    return _command_result_gate(
        status_key="failed",
        paths=paths,
        cmd=cmd,
        pass_message="graph seed passed",
        fail_message="graph seed failed",
        verbose=verbose,
    )


def run_promotion_gate(
    candidate: PromotionCandidate,
    *,
    paths: PromotionPaths,
    policy: PromotionPolicy,
) -> PromotionOutcome:
    """Gate a draft through a temporary canonical candidate, then write it."""
    gates: dict[str, GateResult] = {}
    timestamp = utc_timestamp()

    if candidate.output_path.exists() and not policy.overwrite:
        return PromotionOutcome(
            case_id=candidate.case_id,
            status="skipped_exists",
            draft_path=candidate.draft_path,
            draft_kind=candidate.draft_kind,
            review_status=candidate.review_status,
            output_path=candidate.output_path,
            timestamp=timestamp,
            message="canonical record already exists",
            gates=gates,
        )

    with tempfile.TemporaryDirectory(prefix=f"{candidate.case_id}_promotion_") as tmp:
        temp_cases_dir = Path(tmp) / "cases"

        temp_path, build_gate = build_temp_candidate(candidate, paths, policy, temp_cases_dir)
        gates["candidate"] = build_gate
        if temp_path is None:
            return _blocked_outcome(candidate, "candidate_error", build_gate.message, gates)

        gate_verbose = policy.verbose
        gate_calls = [
            ("schema", lambda: run_schema_gate(paths, temp_cases_dir, verbose=gate_verbose)),
            (
                "source_links",
                lambda: run_source_links_gate(
                    paths,
                    candidate.case_id,
                    temp_cases_dir,
                    verbose=gate_verbose,
                ),
            ),
            (
                "source_integrity",
                lambda: run_source_integrity_gate(
                    paths,
                    candidate.case_id,
                    temp_cases_dir,
                    block_warnings=policy.block_source_integrity_warnings,
                    verbose=gate_verbose,
                ),
            ),
            (
                "semantic_lint",
                lambda: run_semantic_lint_gate(
                    paths,
                    candidate.case_id,
                    temp_cases_dir,
                    verbose=gate_verbose,
                ),
            ),
            (
                "conflict_gate",
                lambda: run_conflict_gate(
                    candidate,
                    allow_missing=policy.allow_missing_conflict_reports,
                ),
            ),
        ]

        for name, gate_call in gate_calls:
            gate = gate_call()
            gates[name] = gate
            if gate.status not in {"pass", "skipped_no_reports"}:
                return _blocked_outcome(candidate, gate.status, gate.message, gates)

        try:
            candidate.output_path.parent.mkdir(parents=True, exist_ok=True)
            if candidate.output_path.exists() and not policy.overwrite:
                return _blocked_outcome(
                    candidate,
                    "skipped_exists",
                    "canonical record already exists",
                    gates,
                )
            shutil.copy2(temp_path, candidate.output_path)
        except Exception as exc:
            return _blocked_outcome(candidate, "promotion_error", str(exc), gates)

    return PromotionOutcome(
        case_id=candidate.case_id,
        status="promoted",
        draft_path=candidate.draft_path,
        draft_kind=candidate.draft_kind,
        review_status=candidate.review_status,
        output_path=candidate.output_path,
        timestamp=utc_timestamp(),
        message="promoted after grounding gates",
        gates=gates,
    )


def _blocked_outcome(
    candidate: PromotionCandidate,
    status: str,
    message: str,
    gates: dict[str, GateResult],
) -> PromotionOutcome:
    return PromotionOutcome(
        case_id=candidate.case_id,
        status=status,
        draft_path=candidate.draft_path,
        draft_kind=candidate.draft_kind,
        review_status=candidate.review_status,
        output_path=candidate.output_path,
        timestamp=utc_timestamp(),
        message=message,
        gates=dict(gates),
    )
