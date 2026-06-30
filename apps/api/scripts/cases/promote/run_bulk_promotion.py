#!/usr/bin/env python3
"""Bulk promotion runner for reviewed Meridian drafts."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = Path(__file__).resolve().parent
_API_DIR = _SCRIPTS_DIR.parent.parent.parent
_REPO_ROOT = _API_DIR.parent.parent

sys.path.insert(0, str(_API_DIR))

from scripts.cases.promote.promotion_gate import (  # noqa: E402
    GateResult,
    PromotionCandidate,
    PromotionOutcome,
    PromotionPaths,
    PromotionPolicy,
    default_promotion_python,
    run_graph_seed,
    run_promotion_gate,
    utc_timestamp,
)

_DRAFTS_DIR = _REPO_ROOT / "data" / "drafts"
_CASES_DIR = _REPO_ROOT / "data" / "cases"
_BATCH_RUNS_DIR = _REPO_ROOT / "data" / "batch_runs"

PYTHON = default_promotion_python(_API_DIR)

PROMOTABLE_MARKET_STATUSES = {"PASS", "WARNINGS"}
PROMOTABLE_FULL_DEPTH_STATUSES = {"PASS", "WARN"}


def _resolve_root_path(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return _REPO_ROOT / path


def review_status(review_md: Path) -> str:
    """Return PASS, WARNINGS, BLOCKED, ERROR, or UNKNOWN for old review files."""
    if not review_md.exists():
        return "NO_REVIEW"
    for line in review_md.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("**Status:"):
            inner = stripped.replace("**Status:", "").replace("**", "").strip()
            return inner.upper()
    return "UNKNOWN"


def parse_full_depth_readiness(packet_path: Path) -> str:
    """Return PASS, WARN, FAIL, NO_REVIEW, or UNKNOWN for review packets."""
    if not packet_path.exists():
        return "NO_REVIEW"
    for line in packet_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("## readiness:"):
            value = stripped.split(":", 1)[1].strip()
            if value:
                return value.split()[0].upper()
            return "UNKNOWN"
    return "UNKNOWN"


def count_markets(draft_yaml: Path) -> int:
    """Quick count of product_markets_considered entries without full parse."""
    count = 0
    in_markets = False
    for line in draft_yaml.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("product_markets_considered:"):
            in_markets = True
            continue
        if in_markets:
            if line.strip().startswith("- market_id:"):
                count += 1
            elif line and not line[0].isspace() and not line.startswith(" "):
                in_markets = False
    return count


def is_promotable(candidate: PromotionCandidate) -> bool:
    status = candidate.review_status
    if candidate.draft_kind == "market-definition":
        return status in PROMOTABLE_MARKET_STATUSES or status.startswith("PASS ")
    return status in PROMOTABLE_FULL_DEPTH_STATUSES


def _jurisdiction_dirs(drafts_dir: Path, jurisdiction: str | None) -> list[Path]:
    if jurisdiction:
        return [drafts_dir / jurisdiction]
    if not drafts_dir.exists():
        return []
    return [p for p in sorted(drafts_dir.iterdir()) if p.is_dir()]


def _market_candidates(
    drafts_dir: Path,
    cases_dir: Path,
    jurisdiction: str | None,
) -> list[PromotionCandidate]:
    candidates: list[PromotionCandidate] = []
    for jur_dir in _jurisdiction_dirs(drafts_dir, jurisdiction):
        if not jur_dir.exists():
            continue
        jur = jur_dir.name
        for draft in sorted(jur_dir.glob("*.market_definition.draft.yaml")):
            case_id = draft.name.replace(".market_definition.draft.yaml", "")
            review_md = draft.parent / f"{case_id}.market_definition.review.md"
            candidates.append(
                PromotionCandidate(
                    case_id=case_id,
                    jurisdiction=jur,
                    draft_path=draft,
                    draft_kind="market-definition",
                    review_status=review_status(review_md),
                    output_path=cases_dir / jur / f"{case_id}.yaml",
                )
            )
    return candidates


def _full_depth_case_id(draft: Path) -> str:
    if draft.name.endswith(".e2e.merged.draft.yaml"):
        return draft.name.removesuffix(".e2e.merged.draft.yaml")
    return draft.name.removesuffix(".merged.draft.yaml")


def _full_depth_review_packet(draft: Path, case_id: str) -> Path:
    e2e_packet = draft.parent / f"{case_id}.e2e.review_packet.md"
    if e2e_packet.exists():
        return e2e_packet
    return draft.parent / f"{case_id}.review_packet.md"


def _full_depth_candidates(
    drafts_dir: Path,
    cases_dir: Path,
    jurisdiction: str | None,
) -> list[PromotionCandidate]:
    by_case: dict[str, PromotionCandidate] = {}
    patterns = ["*.merged.draft.yaml", "*.e2e.merged.draft.yaml"]
    for jur_dir in _jurisdiction_dirs(drafts_dir, jurisdiction):
        if not jur_dir.exists():
            continue
        jur = jur_dir.name
        for pattern in patterns:
            for draft in sorted(jur_dir.glob(pattern)):
                if draft.name.endswith(".market_definition.draft.yaml"):
                    continue
                case_id = _full_depth_case_id(draft)
                packet = _full_depth_review_packet(draft, case_id)
                # The e2e pattern runs second and wins over the generic merged draft.
                by_case[case_id] = PromotionCandidate(
                    case_id=case_id,
                    jurisdiction=jur,
                    draft_path=draft,
                    draft_kind="full-depth",
                    review_status=parse_full_depth_readiness(packet),
                    output_path=cases_dir / jur / f"{case_id}.yaml",
                )
    return [by_case[k] for k in sorted(by_case)]


def discover_candidates(
    drafts_dir: Path,
    jurisdiction: str | None = None,
    draft_kind: str = "market-definition",
    cases_dir: Path | None = None,
) -> list[PromotionCandidate]:
    """Discover promotion candidates, preferring full-depth over market-definition."""
    cases_root = cases_dir or _CASES_DIR
    if draft_kind == "market-definition":
        return _market_candidates(drafts_dir, cases_root, jurisdiction)
    if draft_kind == "full-depth":
        return _full_depth_candidates(drafts_dir, cases_root, jurisdiction)
    if draft_kind != "all":
        raise ValueError(f"unsupported draft_kind: {draft_kind}")

    by_case = {
        c.case_id: c
        for c in _market_candidates(drafts_dir, cases_root, jurisdiction)
    }
    for candidate in _full_depth_candidates(drafts_dir, cases_root, jurisdiction):
        by_case[candidate.case_id] = candidate
    return [by_case[k] for k in sorted(by_case)]


def _empty_batch_state(
    *,
    run_id: str,
    command: str,
    jurisdiction: str | None,
    draft_kind: str,
) -> dict[str, Any]:
    now = utc_timestamp()
    return {
        "run_id": run_id,
        "created_at": now,
        "last_updated": now,
        "command": command,
        "jurisdiction": jurisdiction,
        "draft_kind": draft_kind,
        "cases": {},
    }


def write_batch_state(state: dict[str, Any], runs_dir: Path, run_id: str) -> Path:
    runs_dir.mkdir(parents=True, exist_ok=True)
    state["last_updated"] = utc_timestamp()
    out_path = runs_dir / f"{run_id}.json"
    out_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return out_path


def _skipped_outcome(
    candidate: PromotionCandidate,
    status: str,
    message: str,
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
    )


def _status_counts() -> dict[str, int]:
    return {
        "promoted": 0,
        "skipped_status": 0,
        "skipped_exists": 0,
        "skipped_markets": 0,
        "candidate_error": 0,
        "blocked_schema": 0,
        "blocked_source_links": 0,
        "blocked_source_integrity": 0,
        "blocked_semantic_lint": 0,
        "blocked_conflicts": 0,
        "promotion_error": 0,
        "errors": 0,
    }


def _record_outcome(
    *,
    state: dict[str, Any] | None,
    runs_dir: Path,
    run_id: str,
    outcome: PromotionOutcome,
    paths: PromotionPaths,
) -> Path | None:
    if state is None:
        return None
    state["cases"][outcome.case_id] = outcome.to_dict(paths.repo_root)
    return write_batch_state(state, runs_dir, run_id)


def _print_summary(
    counts: dict[str, int],
    *,
    graph_seed: GateResult | None,
    artifact_path: Path | None,
    paths: PromotionPaths,
) -> None:
    print(
        "\nDone. "
        f"promoted={counts['promoted']}  "
        f"skipped_status={counts['skipped_status']}  "
        f"skipped_exists={counts['skipped_exists']}  "
        f"skipped_markets={counts['skipped_markets']}"
    )
    print(
        "      "
        f"blocked_schema={counts['blocked_schema']}  "
        f"blocked_source_links={counts['blocked_source_links']}  "
        f"blocked_source_integrity={counts['blocked_source_integrity']}  "
        f"blocked_semantic_lint={counts['blocked_semantic_lint']}  "
        f"blocked_conflicts={counts['blocked_conflicts']}  "
        f"errors={counts['errors']}"
    )
    if graph_seed:
        status = "PASS" if graph_seed.status == "pass" else "FAILED"
        print(f"Graph seed: {status}")
        if graph_seed.status != "pass" and graph_seed.message:
            print(f"  {graph_seed.message}")
    if artifact_path:
        try:
            artifact_display = artifact_path.resolve().relative_to(paths.repo_root.resolve())
        except ValueError:
            artifact_display = artifact_path
        print(f"Batch artifact: {artifact_display}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bulk-promote reviewed Meridian drafts.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--jurisdiction", default=None, help="e.g. eu, uk, us")
    parser.add_argument("--max", type=int, default=None, dest="max_count")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--min-markets", type=int, default=1)
    parser.add_argument(
        "--draft-kind",
        choices=["market-definition", "full-depth", "all"],
        default="market-definition",
    )
    parser.add_argument("--drafts-dir", default=str(_DRAFTS_DIR))
    parser.add_argument("--cases-dir", default=str(_CASES_DIR))
    parser.add_argument("--batch-runs-dir", default=str(_BATCH_RUNS_DIR))
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--skip-graph-seed", action="store_true")
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print subprocess commands and gate output for each promoted case.",
    )
    args = parser.parse_args(argv)

    drafts_dir = _resolve_root_path(args.drafts_dir)
    cases_dir = _resolve_root_path(args.cases_dir)
    batch_runs_dir = _resolve_root_path(args.batch_runs_dir)
    run_id = args.run_id or "bulk_promote_" + dt.datetime.now(
        dt.timezone.utc
    ).strftime("%Y%m%d_%H%M%S")

    paths = PromotionPaths(
        repo_root=_REPO_ROOT,
        drafts_dir=drafts_dir,
        cases_dir=cases_dir,
        batch_runs_dir=batch_runs_dir,
        python=PYTHON,
    )
    policy = PromotionPolicy(overwrite=args.overwrite, verbose=args.verbose)

    candidates = discover_candidates(
        drafts_dir,
        args.jurisdiction,
        args.draft_kind,
        cases_dir=cases_dir,
    )
    print(f"Found {len(candidates)} draft YAMLs")

    state = None
    artifact_path: Path | None = None
    if not args.dry_run:
        command = " ".join(sys.argv if argv is None else ["run_bulk_promotion.py", *argv])
        state = _empty_batch_state(
            run_id=run_id,
            command=command,
            jurisdiction=args.jurisdiction,
            draft_kind=args.draft_kind,
        )

    counts = _status_counts()
    graph_seed: GateResult | None = None

    for candidate in candidates:
        if args.max_count and counts["promoted"] >= args.max_count:
            print(f"\n[max {args.max_count} reached - stopping]")
            break

        if not is_promotable(candidate):
            counts["skipped_status"] += 1
            outcome = _skipped_outcome(
                candidate,
                "skipped_status",
                f"review status is {candidate.review_status}",
            )
            print(f"  SKIP  {candidate.case_id}  [{candidate.review_status}]")
            artifact_path = _record_outcome(
                state=state,
                runs_dir=batch_runs_dir,
                run_id=run_id,
                outcome=outcome,
                paths=paths,
            )
            continue

        if not args.overwrite and candidate.output_path.exists():
            counts["skipped_exists"] += 1
            outcome = _skipped_outcome(candidate, "skipped_exists", "canonical record already exists")
            print(f"  EXISTS {candidate.case_id}")
            artifact_path = _record_outcome(
                state=state,
                runs_dir=batch_runs_dir,
                run_id=run_id,
                outcome=outcome,
                paths=paths,
            )
            continue

        market_count = count_markets(candidate.draft_path)
        if market_count < args.min_markets:
            counts["skipped_markets"] += 1
            outcome = _skipped_outcome(
                candidate,
                "skipped_markets",
                f"only {market_count} product market(s)",
            )
            print(f"  SKIP  {candidate.case_id}  [only {market_count} markets]")
            artifact_path = _record_outcome(
                state=state,
                runs_dir=batch_runs_dir,
                run_id=run_id,
                outcome=outcome,
                paths=paths,
            )
            continue

        if args.dry_run:
            counts["promoted"] += 1
            print(
                f"  DRY   {candidate.case_id}  [{candidate.review_status}] "
                f"- {market_count} markets - {candidate.draft_kind}"
            )
            continue

        print(
            f"  ->    {candidate.case_id}  [{candidate.review_status}] "
            f"- {market_count} markets - {candidate.draft_kind}",
            end="  ",
            flush=True,
        )
        outcome = run_promotion_gate(candidate, paths=paths, policy=policy)
        counts[outcome.status] = counts.get(outcome.status, 0) + 1
        if outcome.status == "promoted":
            print("OK")
        else:
            if outcome.status not in {
                "skipped_status",
                "skipped_exists",
                "skipped_markets",
            }:
                counts["errors"] += 1
            print(f"BLOCKED - {outcome.status}: {outcome.message}")

        artifact_path = _record_outcome(
            state=state,
            runs_dir=batch_runs_dir,
            run_id=run_id,
            outcome=outcome,
            paths=paths,
        )

    if not args.dry_run and counts["promoted"] > 0 and not args.skip_graph_seed:
        print("\nGraph seed ...", end=" ", flush=True)
        graph_seed = run_graph_seed(paths, verbose=args.verbose)
        if graph_seed.status == "pass":
            print("OK")
        else:
            print(f"FAIL - {graph_seed.message}")
            counts["errors"] += 1
        if state is not None:
            state["graph_seed"] = graph_seed.to_dict()
            artifact_path = write_batch_state(state, batch_runs_dir, run_id)
    elif not args.dry_run and args.skip_graph_seed:
        graph_seed = GateResult("skipped", "graph seed skipped by operator")
        if state is not None:
            state["graph_seed"] = graph_seed.to_dict()
            artifact_path = write_batch_state(state, batch_runs_dir, run_id)

    _print_summary(counts, graph_seed=graph_seed, artifact_path=artifact_path, paths=paths)

    return 0 if counts["errors"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
