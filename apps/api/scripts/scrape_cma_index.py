#!/usr/bin/env python3
"""
scrape_cma_index.py — Populate data/case_index/uk/ from the GOV.UK content API.

Uses the GOV.UK search API to list all CMA merger cases, then fetches the
content API for each case to get structured metadata (outcome, date, sector).
Writes one YAML file per closed merger case to data/case_index/uk/.

Usage:
    python apps/api/scripts/scrape_cma_index.py [--dry-run] [--limit N] [--overwrite]

Options:
    --dry-run    Print what would be written without writing any files.
    --limit N    Stop after N cases (useful for testing).
    --overwrite  Re-write files that already exist.
    --delay F    Seconds to sleep between content API fetches (default: 0.3).
"""
import argparse
import re
import sys
import time
from pathlib import Path
from typing import Optional

import requests
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
UK_INDEX_DIR = REPO_ROOT / "data" / "case_index" / "uk"
SEARCH_URL = "https://www.gov.uk/api/search.json"
CONTENT_URL = "https://www.gov.uk/api/content/cma-cases/{slug}"
CMA_CASE_BASE = "https://www.gov.uk/cma-cases/{slug}"

OUTCOME_MAP = {
    "mergers-phase-1-clearance": "cleared",
    "mergers-phase-1-clearance-with-undertakings": "cleared_with_conditions",
    "mergers-phase-1-found-not-to-qualify": "cleared",
    "mergers-phase-2-clearance": "cleared",
    "mergers-phase-2-clearance-with-remedies": "cleared_with_conditions",
    "mergers-phase-2-clearance-with-undertakings": "cleared_with_conditions",
    "mergers-phase-2-prohibition": "blocked",
    "mergers-phase-2-cancellation": "abandoned",
    "mergers-abandoned": "abandoned",
    "mergers-phase-1-reject-undertakings": "cleared_with_conditions",
    "mergers-phase-2-remittal": "referred",
}

SECTOR_MAP = {
    "digital-markets": "digital",
    "electronics-industry": "digital",
    "software-computer-services": "digital",
    "communications": "telecoms",
    "telecommunications": "telecoms",
    "broadcasting": "media_entertainment",
    "recreation-and-leisure": "media_entertainment",
    "publishing": "media_entertainment",
    "food-manufacturing": "agriculture",
    "agriculture-environment-and-natural-resources": "agriculture",
    "healthcare-and-medical-equipment": "pharma",
    "pharmaceuticals": "pharma",
    "transport": "transport",
    "aviation": "transport",
    "financial-services": "finance",
    "banking-insurance-and-finance": "finance",
    "energy": "energy",
    "construction": "construction",
    "retail-and-wholesale": "retail",
    "consumer-goods": "retail",
    "distribution-and-service-industries": "services",
    "manufacturing": "manufacturing",
    "defence": "defence",
    "housing": "construction",
    "waste-management": "services",
    "water": "energy",
}


def _sector_from_cma(market_sectors: list[str]) -> str:
    for s in market_sectors:
        if s in SECTOR_MAP:
            return SECTOR_MAP[s]
    return "other"


def _slug_to_case_id(slug: str, year: int) -> str:
    """
    Turn a CMA URL slug into a canonical case_id.

    'microsoft-slash-activision-blizzard-merger-inquiry' → 'uk_microsoft_activision_blizzard_2023'
    """
    s = slug
    for suffix in (
        "-merger-inquiry", "-merger-inquiries", "-anticipated-merger-inquiry",
        "-merger-and-acquisition", "-acquisition-inquiry",
    ):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
            break

    s = s.replace("-slash-", "_")
    s = re.sub(r"[^a-z0-9_]", "_", s.lower())
    s = re.sub(r"_+", "_", s).strip("_")

    if len(s) > 60:
        parts = s.split("_")
        rebuilt = []
        for p in parts:
            if len("_".join(rebuilt + [p])) > 55:
                break
            rebuilt.append(p)
        s = "_".join(rebuilt)

    return f"uk_{s}_{year}"


def _parse_parties(title: str) -> list[dict]:
    title_clean = re.sub(r"\s*(merger inquiry|merger inquiries|anticipated merger).*$", "",
                         title, flags=re.IGNORECASE).strip()
    parts = re.split(r"\s*/\s*", title_clean)
    if len(parts) < 2:
        return [{"name": title_clean, "role": "party"}]
    parties = [{"name": parts[0].strip(), "role": "acquirer"}]
    for p in parts[1:]:
        parties.append({"name": p.strip(), "role": "target"})
    return parties


def _fetch_all_merger_slugs(delay: float) -> list[str]:
    """Page through the search API and return slugs of all CMA cases with 'merger' in the slug."""
    slugs = []
    start = 0
    page_size = 100
    while True:
        r = requests.get(
            SEARCH_URL,
            params={
                "filter_organisations": "competition-and-markets-authority",
                "filter_content_store_document_type": "cma_case",
                "count": page_size,
                "start": start,
            },
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        results = data.get("results", [])
        if not results:
            break
        for res in results:
            link = res.get("link", "")
            slug = link.replace("/cma-cases/", "")
            if "merger" in slug:
                slugs.append(slug)
        total = data.get("total", 0)
        start += page_size
        if start >= total:
            break
        time.sleep(delay)
    return slugs


def _fetch_case_detail(slug: str) -> Optional[dict]:
    url = CONTENT_URL.format(slug=slug)
    r = requests.get(url, timeout=15)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


def _build_record(slug: str, detail: dict) -> Optional[dict]:
    meta = detail.get("details", {}).get("metadata", {})
    case_type = meta.get("case_type")
    if case_type != "mergers":
        return None

    case_state = meta.get("case_state")
    outcome_type = meta.get("outcome_type")
    closed_date = meta.get("closed_date")

    if not outcome_type or outcome_type not in OUTCOME_MAP:
        return None

    outcome = OUTCOME_MAP[outcome_type]
    year = int(closed_date[:4]) if closed_date else None
    if year is None:
        return None

    title = detail.get("title", "")
    title_clean = re.sub(r"\s*(merger inquiry|merger inquiries).*$", "", title,
                         flags=re.IGNORECASE).strip()

    case_id = _slug_to_case_id(slug, year)
    parties = _parse_parties(title)
    market_sectors = meta.get("market_sector") or []
    sector = _sector_from_cma(market_sectors)

    return {
        "case_id": case_id,
        "case_name": title_clean,
        "jurisdiction": "UK",
        "authority": "Competition and Markets Authority",
        "decision_date": closed_date,
        "sector": sector,
        "outcome": outcome,
        "case_type": "merger",
        "source_url": CMA_CASE_BASE.format(slug=slug),
        "ai_summary": None,
        "parties": parties,
        "concept_refs": [],
    }


def _write_yaml(path: Path, record: dict) -> None:
    lines = [
        f"case_id: {record['case_id']}",
        f"case_name: {_yaml_str(record['case_name'])}",
        f"jurisdiction: {record['jurisdiction']}",
        f"authority: {record['authority']}",
        f"decision_date: '{record['decision_date']}'",
        f"sector: {record['sector']}",
        f"outcome: {record['outcome']}",
        f"case_type: {record['case_type']}",
        f"source_url: {record['source_url']}",
        "ai_summary: null",
        "parties:",
    ]
    for p in record["parties"]:
        lines.append(f"- name: {_yaml_str(p['name'])}")
        lines.append(f"  role: {p['role']}")
    lines.append("concept_refs: []")
    path.write_text("\n".join(lines) + "\n")


def _yaml_str(s: str) -> str:
    if any(c in s for c in ('"', "'", ":", "#", "[", "]", "{", "}", "&", "*", "!")):
        return '"' + s.replace('"', '\\"') + '"'
    return s


def main() -> int:
    parser = argparse.ArgumentParser(description="Scrape CMA merger decisions into case_index/uk/")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--delay", type=float, default=0.3)
    args = parser.parse_args()

    UK_INDEX_DIR.mkdir(parents=True, exist_ok=True)
    existing = {p.stem for p in UK_INDEX_DIR.glob("*.yaml")}

    print("Fetching CMA case list from GOV.UK search API...")
    slugs = _fetch_all_merger_slugs(args.delay)
    print(f"Found {len(slugs)} merger-related slugs")

    written = skipped_exists = skipped_no_outcome = skipped_non_merger = errors = 0

    for i, slug in enumerate(slugs):
        if args.limit and written >= args.limit:
            print(f"\n[limit {args.limit} reached — stopping]")
            break

        time.sleep(args.delay)
        try:
            detail = _fetch_case_detail(slug)
        except Exception as e:
            print(f"  ERR  {slug}: {e}")
            errors += 1
            continue

        if detail is None:
            skipped_no_outcome += 1
            continue

        record = _build_record(slug, detail)
        if record is None:
            meta = detail.get("details", {}).get("metadata", {})
            ct = meta.get("case_type")
            if ct != "mergers":
                skipped_non_merger += 1
            else:
                skipped_no_outcome += 1
            continue

        case_id = record["case_id"]

        if case_id in existing and not args.overwrite:
            skipped_exists += 1
            print(f"  EXISTS  {case_id}")
            continue

        if args.dry_run:
            print(f"  DRY  {case_id}  [{record['outcome']}]  {record['case_name'][:50]}")
            written += 1
            continue

        out_path = UK_INDEX_DIR / f"{case_id}.yaml"
        _write_yaml(out_path, record)
        existing.add(case_id)
        written += 1
        print(f"  →  {case_id}  [{record['outcome']}]")

    print(
        f"\nDone. written={written}  skipped_exists={skipped_exists}"
        f"  skipped_no_outcome={skipped_no_outcome}  skipped_non_merger={skipped_non_merger}"
        f"  errors={errors}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
