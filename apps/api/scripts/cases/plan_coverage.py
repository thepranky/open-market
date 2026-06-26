#!/usr/bin/env python3
"""
plan_coverage.py — build a lightweight coverage plan from a cached source document.

Identifies likely section groups (market_definition, geographic_market, theories,
remedies) using section-path heuristics and writes a coverage plan YAML that the
readiness checker can consume.  No Claude calls, no draft writes.

Usage (from repo root):
    apps/api/.venv/bin/python apps/api/scripts/plan_coverage.py \\
        --case-id eu_viasat_inmarsat_2023

    # Specify jurisdiction explicitly (default: inferred from case_id prefix)
    apps/api/.venv/bin/python apps/api/scripts/plan_coverage.py \\
        --case-id eu_viasat_inmarsat_2023 --jurisdiction eu

    # Dry run — print plan, do not write file
    apps/api/.venv/bin/python apps/api/scripts/plan_coverage.py \\
        --case-id eu_viasat_inmarsat_2023 --dry-run
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path
from typing import Optional

import yaml

_API_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_API_DIR))
sys.path.insert(0, str(Path(__file__).parent))

from app.shared.utils.pdf_extractor import DEFAULT_CACHE_DIR
from pipeline_profile import PipelineProfile, select_profile
from repair_source_passages import _extract_section_map

_REPO_ROOT = Path(__file__).resolve().parents[4]
_CASES_DIR = _REPO_ROOT / "data" / "cases"
_DRAFTS_DIR = _REPO_ROOT / "data" / "drafts"

# ---------------------------------------------------------------------------
# Default section-type keyword classifiers (EC-centric baseline).
# Used when no profile is supplied.  When a profile IS supplied its keywords
# fully replace the per-category defaults below.
# ---------------------------------------------------------------------------

_MARKET_DEF_KEYWORDS = (
    "relevant market",
    "market definition",
    "product market",
    "market for the supply",
)

_GEO_MARKET_KEYWORDS = (
    "geographic market",
    "geographic scope",
    "geographic dimension",
)

_THEORIES_KEYWORDS = (
    "competitive assessment",
    "assessment of competitive effects",
    "competitive effects",
    "theory of harm",
    "theories of harm",
    "horizontal effects",
    "vertical effects",
    "conglomerate effects",
    "non-horizontal",
    "innovation competition",
    "coordinated effects",
)

_REMEDIES_KEYWORDS = (
    "commitment",
    "remedy",
    "remedies",
    "divestment",
    "divestiture",
    "condition",
    "obligation",
)


def _classify_section_path(
    section_path: str,
    profile: Optional[PipelineProfile] = None,
) -> set[str]:
    """Return a set of category labels for a section path.

    When a profile is supplied its keywords are used for each category;
    the module-level defaults are used otherwise.
    """
    lp = section_path.lower()
    categories: set[str] = set()

    if profile is not None:
        geo_kw = profile.keywords_for("geographic_market") or _GEO_MARKET_KEYWORDS
        mkt_kw = profile.keywords_for("market_definition") or _MARKET_DEF_KEYWORDS
        th_kw = profile.keywords_for("theories") or _THEORIES_KEYWORDS
        rem_kw = profile.keywords_for("remedies") or _REMEDIES_KEYWORDS
    else:
        geo_kw = _GEO_MARKET_KEYWORDS
        mkt_kw = _MARKET_DEF_KEYWORDS
        th_kw = _THEORIES_KEYWORDS
        rem_kw = _REMEDIES_KEYWORDS

    if any(kw in lp for kw in geo_kw):
        categories.add("geographic_market")
    if any(kw in lp for kw in mkt_kw):
        categories.add("market_definition")
    if any(kw in lp for kw in th_kw):
        categories.add("theories")
    if any(kw in lp for kw in rem_kw):
        categories.add("remedies")
    return categories


# ---------------------------------------------------------------------------
# Section grouping — merge consecutive pages in the same section type
# ---------------------------------------------------------------------------


def _group_sections(
    section_map: dict[int, str],
    profile: Optional[PipelineProfile] = None,
) -> dict[str, list[dict]]:
    """
    Group consecutive page ranges by category.

    Returns a dict: category -> list of {"heading", "page_start", "page_end", "section_path"}.
    Overlapping categories (e.g. a page matching both market_definition and geo) are
    recorded in each matching category.
    """
    all_pages = sorted(section_map.keys())
    buckets: dict[str, list[dict]] = {
        "market_definition": [],
        "geographic_market": [],
        "theories": [],
        "remedies": [],
    }

    # For each category, detect contiguous runs of pages that match
    for category in buckets:
        current_run: list[int] = []
        current_path: str = ""
        for pn in all_pages:
            sp = section_map.get(pn, "")
            if category in _classify_section_path(sp, profile=profile):
                if not current_run or pn - current_run[-1] <= 2:
                    current_run.append(pn)
                    current_path = sp
                else:
                    # flush existing run
                    _flush_run(buckets[category], current_run, current_path)
                    current_run = [pn]
                    current_path = sp
            else:
                if current_run:
                    _flush_run(buckets[category], current_run, current_path)
                    current_run = []
                    current_path = ""
        if current_run:
            _flush_run(buckets[category], current_run, current_path)

    return buckets


def _flush_run(bucket: list[dict], run: list[int], section_path: str) -> None:
    leaf = section_path.split(" > ")[-1] if section_path else ""
    bucket.append(
        {
            "heading": leaf,
            "page_start": min(run),
            "page_end": max(run),
            "section_path": section_path,
        }
    )


# ---------------------------------------------------------------------------
# Source-cache / case resolution
# ---------------------------------------------------------------------------


def _resolve_cache_path(case_id: str) -> Optional[Path]:
    """Find the source cache JSON for a case by reading its canonical YAML."""
    for yaml_path in _CASES_DIR.rglob(f"{case_id}.yaml"):
        try:
            with open(yaml_path) as f:
                case_data = yaml.safe_load(f)
            for doc in case_data.get("source_documents", []):
                doc_id = doc.get("doc_id")
                if doc_id:
                    p = DEFAULT_CACHE_DIR / f"{doc_id}.json"
                    if p.exists():
                        return p
        except Exception:
            continue
    # Fall back to source_text directory by naming convention
    guesses = [
        DEFAULT_CACHE_DIR / f"{case_id}_decision.json",
        DEFAULT_CACHE_DIR / f"{case_id}.json",
    ]
    for g in guesses:
        if g.exists():
            return g
    return None


def _infer_jurisdiction(case_id: str) -> str:
    """Infer jurisdiction folder from case_id prefix."""
    for prefix, jur in (("eu_", "eu"), ("uk_", "uk"), ("us_", "us")):
        if case_id.startswith(prefix):
            return jur
    return "eu"


# ---------------------------------------------------------------------------
# YAML dumper
# ---------------------------------------------------------------------------


class _PlanDumper(yaml.SafeDumper):
    pass


def _str_representer(dumper: yaml.SafeDumper, data: str) -> yaml.ScalarNode:
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


_PlanDumper.add_representer(str, _str_representer)


def _dump(plan: dict) -> str:
    return yaml.dump(
        plan,
        Dumper=_PlanDumper,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
        width=100,
    )


# ---------------------------------------------------------------------------
# Core planning function
# ---------------------------------------------------------------------------


def build_coverage_plan(
    source_cache: dict,
    case_id: str,
    section_map: Optional[dict[int, str]] = None,
    profile: Optional[PipelineProfile] = None,
) -> dict:
    """
    Build and return a coverage plan dict from a source cache.
    Pure function — no I/O.

    section_map may be supplied directly (e.g. in tests) to bypass text parsing.
    profile, if supplied, overrides the default EC-centric coverage keywords.
    """
    doc_id = source_cache.get("source_document_id", "unknown")
    total_pages = source_cache.get("page_count", len(source_cache.get("pages", [])))
    if section_map is None:
        section_map = _extract_section_map(source_cache)

    sections = _group_sections(section_map, profile=profile)

    plan: dict = {
        "case_id": case_id,
        "generated_at": datetime.date.today().isoformat(),
        "source_doc_id": doc_id,
        "total_pages": total_pages,
        "sections_planned": {
            cat: entries for cat, entries in sections.items()
        },
        "summary": {
            cat: len(entries) for cat, entries in sections.items()
        },
    }
    if profile is not None:
        plan["profile_id"] = profile.profile_id
    return plan


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Build a coverage plan YAML from a cached source document."
    )
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--case-id", help="Case ID (resolves source cache automatically)")
    src.add_argument("--source-cache", help="Path to source cache JSON file")
    parser.add_argument("--jurisdiction", help="Override jurisdiction folder (eu/uk/us)")
    parser.add_argument(
        "--profile",
        help="Pipeline profile ID (ec_decision | cma_report | us_court_opinion). "
             "Inferred from case_id prefix when omitted.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print plan, do not write file")
    args = parser.parse_args(argv)

    if args.source_cache:
        cache_path = Path(args.source_cache)
        case_id = cache_path.stem.replace("_decision", "").replace("_source", "")
    else:
        case_id = args.case_id
        cache_path = _resolve_cache_path(case_id)
        if cache_path is None:
            print(f"ERROR: no cached source found for '{case_id}'.", file=sys.stderr)
            print("       Run ingest_case.py first to populate the source cache.", file=sys.stderr)
            sys.exit(1)

    try:
        profile = select_profile(case_id, profile_id=args.profile)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    with open(cache_path) as f:
        cache = json.load(f)

    plan = build_coverage_plan(cache, case_id, profile=profile)

    yaml_text = _dump(plan)

    if args.dry_run:
        print(yaml_text)
        return

    jurisdiction = args.jurisdiction or _infer_jurisdiction(case_id)
    out_dir = _DRAFTS_DIR / jurisdiction
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{case_id}.coverage_plan.yaml"
    out_path.write_text(yaml_text)
    print(f"Coverage plan written to: {out_path}")
    print(f"  profile:                  {profile.profile_id}")
    print(f"  market_definition sections: {plan['summary']['market_definition']}")
    print(f"  geographic_market sections: {plan['summary']['geographic_market']}")
    print(f"  theories sections:          {plan['summary']['theories']}")
    print(f"  remedies sections:          {plan['summary']['remedies']}")


if __name__ == "__main__":
    main()
