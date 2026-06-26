#!/usr/bin/env python3
"""
check_review_readiness.py — deterministic review-readiness gate for expansion drafts.

Reads a coverage plan YAML and one or more draft YAMLs for the same case,
then flags structural gaps that caused manual repair work on UK/EC Viasat:

  ERROR conditions (block promotion):
    • planned geographic-market sections → zero geographic_market entries
    • planned theory/competitive-assessment sections → zero theory_of_harm entries
    • source_role: not_set on any passage
    • exact duplicate quote_snippet across passages

  WARNING conditions (require human sign-off):
    • product markets present but zero geographic markets (when geo sections planned)
    • orphaned passages — not linked to any market, theory, or commitment
    • conclusion passages used as the only support for a theory_of_harm
    • planned sections present but matching extraction focus not found in draft names

Exit codes:
    0  all clear (no errors, no warnings)
    1  warnings only
    2  one or more errors

Usage (from repo root):
    # Auto-discover drafts from data/drafts/{jurisdiction}/
    apps/api/.venv/bin/python apps/api/scripts/check_review_readiness.py \\
        --case-id eu_viasat_inmarsat_2023

    # Explicit draft files
    apps/api/.venv/bin/python apps/api/scripts/check_review_readiness.py \\
        --case-id eu_viasat_inmarsat_2023 \\
        --draft data/drafts/eu/eu_viasat_inmarsat_2023.merged.draft.yaml

    # Also write a human-review packet
    apps/api/.venv/bin/python apps/api/scripts/check_review_readiness.py \\
        --case-id eu_viasat_inmarsat_2023 --packet
"""

from __future__ import annotations

import argparse
import datetime
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

import yaml

_API_DIR = Path(__file__).resolve().parents[2]
_REPO_ROOT = Path(__file__).resolve().parents[4]
_DRAFTS_DIR = _REPO_ROOT / "data" / "drafts"

sys.path.insert(0, str(_API_DIR / "scripts" / "cases"))
from pipeline_profile import PipelineProfile, select_profile

# ---------------------------------------------------------------------------
# Finding files
# ---------------------------------------------------------------------------


def _infer_jurisdiction(case_id: str) -> str:
    for prefix, jur in (("eu_", "eu"), ("uk_", "uk"), ("us_", "us")):
        if case_id.startswith(prefix):
            return jur
    return "eu"


def _find_coverage_plan(case_id: str) -> Optional[Path]:
    jurisdiction = _infer_jurisdiction(case_id)
    p = _DRAFTS_DIR / jurisdiction / f"{case_id}.coverage_plan.yaml"
    return p if p.exists() else None


def _find_draft_files(case_id: str) -> list[Path]:
    """Discover all draft YAMLs for a case across jurisdiction folders."""
    drafts: list[Path] = []
    for jur_dir in _DRAFTS_DIR.iterdir():
        if not jur_dir.is_dir():
            continue
        for f in jur_dir.glob(f"{case_id}.*.draft.yaml"):
            drafts.append(f)
    return sorted(drafts)


# ---------------------------------------------------------------------------
# Draft loading and merging
# ---------------------------------------------------------------------------


def _load_yaml(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f) or {}


def _merge_draft_data(draft_paths: list[Path]) -> dict:
    """
    Merge multiple draft YAMLs into one logical view.
    Lists (passages, markets, theories, etc.) are concatenated.
    Scalar fields (case_id, etc.) taken from first draft.
    """
    merged: dict[str, Any] = {}
    list_keys = (
        "product_markets_considered",
        "geographic_markets_considered",
        "theories_of_harm",
        "source_passages",
        "remedies_considered",
    )
    for path in draft_paths:
        data = _load_yaml(path)
        for k, v in data.items():
            if k in list_keys:
                if k not in merged:
                    merged[k] = []
                if isinstance(v, list):
                    merged[k].extend(v)
            elif k not in merged:
                merged[k] = v
    return merged


# ---------------------------------------------------------------------------
# Finding objects
# ---------------------------------------------------------------------------


def _is_not_set(val: Any) -> bool:
    if val is None:
        return True
    s = str(val).strip().lower()
    return s in ("not_set", "", "none", "null")


# ---------------------------------------------------------------------------
# Check functions — each returns a list of issue dicts
# ---------------------------------------------------------------------------


def check_geo_market_coverage(
    draft: dict, plan: Optional[dict]
) -> list[dict]:
    """ERROR if geo sections planned but no geographic_market entries."""
    issues: list[dict] = []
    if plan is None:
        return issues
    planned_geo = plan.get("sections_planned", {}).get("geographic_market", [])
    if not planned_geo:
        return issues
    geos = draft.get("geographic_markets_considered", [])
    if not geos:
        issues.append(
            {
                "level": "error",
                "code": "missing_geo_markets",
                "message": (
                    f"{len(planned_geo)} geographic-market section(s) identified in source "
                    f"(e.g. p.{planned_geo[0]['page_start']}–{planned_geo[0]['page_end']}: "
                    f"{planned_geo[0]['heading']!r}) but draft has zero geographic_market entries."
                ),
                "sections": [
                    f"p.{s['page_start']}–{s['page_end']}: {s['heading']}"
                    for s in planned_geo
                ],
            }
        )
    return issues


def check_theory_coverage(
    draft: dict, plan: Optional[dict]
) -> list[dict]:
    """ERROR if theory sections planned but no theory_of_harm entries."""
    issues: list[dict] = []
    if plan is None:
        return issues
    planned_theories = plan.get("sections_planned", {}).get("theories", [])
    if not planned_theories:
        return issues
    theories = draft.get("theories_of_harm", [])
    if not theories:
        issues.append(
            {
                "level": "error",
                "code": "missing_theory_of_harm",
                "message": (
                    f"{len(planned_theories)} competitive-assessment section(s) identified in "
                    f"source (e.g. p.{planned_theories[0]['page_start']}–"
                    f"{planned_theories[0]['page_end']}: {planned_theories[0]['heading']!r}) "
                    f"but draft has zero theories_of_harm entries."
                ),
                "sections": [
                    f"p.{s['page_start']}–{s['page_end']}: {s['heading']}"
                    for s in planned_theories
                ],
            }
        )
    return issues


def check_source_role_not_set(draft: dict) -> list[dict]:
    """ERROR for any passage with source_role == not_set (or missing)."""
    issues: list[dict] = []
    passages = draft.get("source_passages", [])
    bad = [
        p.get("passage_id", f"idx:{i}")
        for i, p in enumerate(passages)
        if _is_not_set(p.get("source_role"))
    ]
    if bad:
        issues.append(
            {
                "level": "error",
                "code": "source_role_not_set",
                "message": (
                    f"{len(bad)} passage(s) have source_role: not_set. "
                    "Assign commission_assessment, market_investigation, "
                    "notifying_party_view, third_party_view, or conclusion."
                ),
                "passage_ids": bad,
            }
        )
    return issues


def check_duplicate_quotes(draft: dict) -> list[dict]:
    """ERROR for exact duplicate quote_snippet values across passages."""
    issues: list[dict] = []
    passages = draft.get("source_passages", [])
    seen: dict[str, list[str]] = defaultdict(list)
    for p in passages:
        snippet = (p.get("quote_snippet") or "").strip()
        if snippet:
            pid = p.get("passage_id", "unknown")
            seen[snippet].append(pid)
    dupes = {s: ids for s, ids in seen.items() if len(ids) > 1}
    for snippet, ids in dupes.items():
        issues.append(
            {
                "level": "error",
                "code": "duplicate_quote_snippet",
                "message": (
                    f"Quote snippet duplicated across {len(ids)} passages: "
                    f"{ids}. Snippet: {snippet[:80]!r}…"
                ),
                "passage_ids": ids,
            }
        )
    return issues


def check_product_geo_balance(
    draft: dict, plan: Optional[dict]
) -> list[dict]:
    """WARNING if product markets exist but zero geo markets where geo sections were planned."""
    issues: list[dict] = []
    products = draft.get("product_markets_considered", [])
    geos = draft.get("geographic_markets_considered", [])
    planned_geo = (
        plan.get("sections_planned", {}).get("geographic_market", []) if plan else []
    )
    if products and not geos and planned_geo:
        issues.append(
            {
                "level": "warning",
                "code": "product_markets_without_geo",
                "message": (
                    f"{len(products)} product market(s) extracted but zero geographic markets. "
                    "Source has planned geographic-market sections — check coverage."
                ),
            }
        )
    return issues


def check_orphaned_passages(
    draft: dict,
    profile: Optional[PipelineProfile] = None,
) -> list[dict]:
    """WARNING for passages not linked to any market, theory, or commitment.

    Profile-specific allow_roles are exempt from the orphan warning — e.g. US court
    opinions allow 'conclusion' and 'background' passages to stand alone.
    """
    issues: list[dict] = []
    passages = draft.get("source_passages", [])
    allowed_orphan_roles: frozenset[str] = (
        profile.allowed_orphan_roles() if profile is not None else frozenset()
    )
    orphans = []
    for p in passages:
        linked = (
            bool(p.get("supports_markets"))
            or bool(p.get("supports_geographic_markets"))
            or bool(p.get("supports_theories"))
            or bool(p.get("supports_commitments"))
        )
        if not linked:
            role = str(p.get("source_role") or "")
            if role not in allowed_orphan_roles:
                orphans.append(p.get("passage_id", "unknown"))
    if orphans:
        issues.append(
            {
                "level": "warning",
                "code": "orphaned_passages",
                "message": (
                    f"{len(orphans)} passage(s) are not linked to any market, theory, "
                    f"or commitment: {orphans[:10]}"
                    + (" …" if len(orphans) > 10 else "")
                ),
                "passage_ids": orphans,
            }
        )
    return issues


def check_conclusion_as_sole_support(draft: dict) -> list[dict]:
    """WARNING if a theory_of_harm is supported only by conclusion passages."""
    issues: list[dict] = []
    theories = draft.get("theories_of_harm", [])
    passages = draft.get("source_passages", [])
    passage_role: dict[str, str] = {
        p.get("passage_id", ""): (p.get("source_role") or "")
        for p in passages
    }

    for t in theories:
        toh_id = t.get("toh_id") or t.get("theory_id", "unknown")
        supporting_ids = t.get("supporting_passages") or []
        # Also collect from source_passages that reference this theory
        for p in passages:
            if toh_id in (p.get("supports_theories") or []):
                pid = p.get("passage_id", "")
                if pid and pid not in supporting_ids:
                    supporting_ids.append(pid)

        if not supporting_ids:
            continue
        roles = {passage_role.get(pid, "") for pid in supporting_ids}
        non_conclusion = roles - {"conclusion", ""}
        if not non_conclusion and "conclusion" in roles:
            issues.append(
                {
                    "level": "warning",
                    "code": "conclusion_only_support",
                    "message": (
                        f"Theory {toh_id!r} is supported only by conclusion passage(s) "
                        f"{supporting_ids}. Add substantive commission_assessment passages."
                    ),
                    "toh_id": toh_id,
                    "passage_ids": list(supporting_ids),
                }
            )
    return issues


def check_planned_focus_coverage(
    draft: dict, plan: Optional[dict], draft_paths: list[Path]
) -> list[dict]:
    """WARNING if planned sections exist but corresponding focus was not run."""
    issues: list[dict] = []
    if plan is None:
        return issues

    focus_map = {
        "market_definition": "market_definition",
        "geographic_market": "market_definition",
        "theories": "theories",
        "remedies": "remedies",
    }
    found_foci = set()
    for p in draft_paths:
        name = p.name
        # A merged draft is treated as covering all foci
        if ".merged." in name:
            found_foci.update(("market_definition", "theories", "remedies"))
            continue
        for focus in ("market_definition", "theories", "remedies", "outcome_metadata", "unit_assessment"):
            if f".{focus}." in name or f".{focus}_" in name:
                found_foci.add(focus)

    planned = plan.get("sections_planned", {})
    for section_type, focus in focus_map.items():
        if planned.get(section_type) and focus not in found_foci:
            issues.append(
                {
                    "level": "warning",
                    "code": "planned_section_not_extracted",
                    "message": (
                        f"Source has {len(planned[section_type])} {section_type!r} section(s) "
                        f"but no {focus!r} draft found among {[p.name for p in draft_paths]}."
                    ),
                    "section_type": section_type,
                    "focus_expected": focus,
                }
            )
    return issues


# ---------------------------------------------------------------------------
# Run all checks
# ---------------------------------------------------------------------------


def run_checks(
    draft: dict,
    plan: Optional[dict],
    draft_paths: list[Path],
    profile: Optional[PipelineProfile] = None,
) -> list[dict]:
    issues: list[dict] = []
    issues.extend(check_geo_market_coverage(draft, plan))
    issues.extend(check_theory_coverage(draft, plan))
    issues.extend(check_source_role_not_set(draft))
    issues.extend(check_duplicate_quotes(draft))
    issues.extend(check_product_geo_balance(draft, plan))
    issues.extend(check_orphaned_passages(draft, profile=profile))
    issues.extend(check_conclusion_as_sole_support(draft))
    issues.extend(check_planned_focus_coverage(draft, plan, draft_paths))
    return issues


# ---------------------------------------------------------------------------
# Human-review packet
# ---------------------------------------------------------------------------


def _count_objects(draft: dict) -> dict[str, int]:
    return {
        "product_markets": len(draft.get("product_markets_considered", [])),
        "geographic_markets": len(draft.get("geographic_markets_considered", [])),
        "theories_of_harm": len(draft.get("theories_of_harm", [])),
        "remedies": len(draft.get("remedies_considered", [])),
        "source_passages": len(draft.get("source_passages", [])),
    }


def write_review_packet(
    case_id: str,
    draft: dict,
    plan: Optional[dict],
    draft_paths: list[Path],
    issues: list[dict],
    out_path: Path,
) -> None:
    errors = [i for i in issues if i["level"] == "error"]
    warnings = [i for i in issues if i["level"] == "warning"]
    counts = _count_objects(draft)

    lines: list[str] = []
    lines.append(f"# Review Packet — {case_id}")
    lines.append(f"Generated: {datetime.datetime.now().isoformat(timespec='seconds')}")
    lines.append("")

    def _rel(p: Path) -> str:
        try:
            return str(p.resolve().relative_to(_REPO_ROOT))
        except ValueError:
            return str(p)

    lines.append("## Files")
    for p in draft_paths:
        lines.append(f"  - {_rel(p)}")
    if plan:
        plan_path = _find_coverage_plan(case_id)
        if plan_path:
            lines.append(f"  - {_rel(plan_path)}  (coverage plan)")
    lines.append("")

    lines.append("## Coverage Plan Summary")
    if plan:
        for cat, sections in plan.get("sections_planned", {}).items():
            if sections:
                lines.append(f"  {cat}: {len(sections)} section(s)")
                for s in sections:
                    lines.append(
                        f"    • p.{s['page_start']}–{s['page_end']}: {s['heading']}"
                    )
    else:
        lines.append("  (no coverage plan found — run plan_coverage.py first)")
    lines.append("")

    lines.append("## Extraction Counts")
    for k, v in counts.items():
        lines.append(f"  {k}: {v}")
    lines.append("")

    lines.append(f"## Readiness: {'FAIL' if errors else ('WARN' if warnings else 'PASS')}")
    lines.append(f"  Errors:   {len(errors)}")
    lines.append(f"  Warnings: {len(warnings)}")
    lines.append("")

    if errors:
        lines.append("### Errors (must fix before promoting)")
        for i in errors:
            lines.append(f"  [{i['code']}] {i['message']}")
        lines.append("")

    if warnings:
        lines.append("### Warnings (require human sign-off)")
        for i in warnings:
            lines.append(f"  [{i['code']}] {i['message']}")
        lines.append("")

    lines.append("## Spot-check Priorities")
    if errors:
        lines.append("  1. Fix all errors above before spot-checking.")
    else:
        # Give top priorities based on counts
        if counts["geographic_markets"] == 0 and plan and plan.get("sections_planned", {}).get("geographic_market"):
            lines.append("  1. Verify geographic market extraction — plan shows sections present.")
        if counts["theories_of_harm"] == 0 and plan and plan.get("sections_planned", {}).get("theories"):
            lines.append("  2. Verify theories/competitive-assessment extraction.")
        if counts["source_passages"] > 0:
            lines.append(f"  • Review passage source_role assignments ({counts['source_passages']} passages).")
        if counts["theories_of_harm"] > 0:
            lines.append("  • Verify theory passage support is non-conclusion.")
    lines.append("")

    lines.append("## Promotion Recommendation")
    if errors:
        lines.append("  NOT READY — resolve errors above, then re-run.")
    elif warnings:
        lines.append("  REVIEW REQUIRED — no errors, but warnings need human sign-off.")
    else:
        lines.append("  READY — no errors or warnings. Run promote_case_pipeline.py.")
    lines.append("")

    out_path.write_text("\n".join(lines))
    print(f"Review packet written to: {out_path}")


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------


def _format_issues(issues: list[dict]) -> str:
    lines: list[str] = []
    errors = [i for i in issues if i["level"] == "error"]
    warnings = [i for i in issues if i["level"] == "warning"]

    if not issues:
        lines.append("PASS — no readiness issues found.")
        return "\n".join(lines)

    status = "FAIL" if errors else "WARN"
    lines.append(f"Status: {status}  ({len(errors)} error(s), {len(warnings)} warning(s))")
    lines.append("")
    for i in issues:
        marker = "ERROR" if i["level"] == "error" else "WARN "
        lines.append(f"  [{marker}] {i['code']}: {i['message']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Check review readiness for a controlled case expansion draft."
    )
    parser.add_argument("--case-id", required=True, help="Case ID")
    parser.add_argument(
        "--draft",
        action="append",
        dest="drafts",
        metavar="PATH",
        help="Draft YAML path(s). May be repeated. Defaults to auto-discovery.",
    )
    parser.add_argument(
        "--coverage-plan",
        metavar="PATH",
        help="Coverage plan YAML path. Defaults to auto-discovery.",
    )
    parser.add_argument(
        "--packet",
        action="store_true",
        help="Write a human-review packet markdown file alongside the coverage plan.",
    )
    parser.add_argument(
        "--profile",
        help="Pipeline profile ID (ec_decision | cma_report | us_court_opinion). "
             "Inferred from case_id prefix when omitted.",
    )
    args = parser.parse_args(argv)

    case_id = args.case_id

    try:
        profile: Optional[PipelineProfile] = select_profile(case_id, profile_id=args.profile)
    except ValueError as exc:
        print(f"WARNING: could not select profile: {exc}", file=sys.stderr)
        profile = None

    # Resolve coverage plan
    if args.coverage_plan:
        plan_path = Path(args.coverage_plan)
        plan: Optional[dict] = _load_yaml(plan_path) if plan_path.exists() else None
    else:
        plan_path = _find_coverage_plan(case_id)
        plan = _load_yaml(plan_path) if plan_path else None

    if plan is None:
        print(
            "WARNING: no coverage plan found. Run plan_coverage.py first for full checks.",
            file=sys.stderr,
        )

    # Resolve draft files
    if args.drafts:
        draft_paths = [Path(d) for d in args.drafts]
    else:
        draft_paths = _find_draft_files(case_id)

    if not draft_paths:
        print(f"ERROR: no draft YAML files found for '{case_id}'.", file=sys.stderr)
        sys.exit(2)

    draft = _merge_draft_data(draft_paths)
    issues = run_checks(draft, plan, draft_paths, profile=profile)

    if profile is not None:
        print(f"Profile: {profile.profile_id} ({profile.display_name})")
    print(_format_issues(issues))

    if args.packet:
        jurisdiction = _infer_jurisdiction(case_id)
        out_dir = _DRAFTS_DIR / jurisdiction
        out_dir.mkdir(parents=True, exist_ok=True)
        packet_path = out_dir / f"{case_id}.review_packet.md"
        write_review_packet(case_id, draft, plan, draft_paths, issues, packet_path)

    errors = [i for i in issues if i["level"] == "error"]
    warnings = [i for i in issues if i["level"] == "warning"]

    if errors:
        sys.exit(2)
    elif warnings:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
