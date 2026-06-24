#!/usr/bin/env python3
"""
EC competition merger registry scraper.

Data sources:
  1. EUR-Lex SPARQL (publications.europa.eu) — authoritative list of Phase I merger decisions,
     NACE sector codes, decision dates.
  2. Cellar DOC content (publications.europa.eu) — FormEx XML of OJ notification, used to
     extract the "Case M.NNNNN – PARTY A / PARTY B" title when work_title is absent.

Coverage: EC Phase I clearances (CDM type non-opposition_concentration_notified).
Phase II decisions (blocked / approved with remedies) are rare (~20-30/year) and are
intentionally excluded from bulk scraping; add them manually via the normal pipeline.

Output: one YAML file per case in data/case_index/eu/, conforming to CaseIndexEntry schema.
Existing files are never overwritten unless --force is passed.

Usage:
    python scripts/scrape_ec_registry.py --from-date 2020-01-01 --to-date 2023-12-31
    python scripts/scrape_ec_registry.py --from-date 2023-01-01 --dry-run
    python scripts/scrape_ec_registry.py --limit 50 --dry-run  # quick test
"""

import argparse
import io
import re
import sys
import time
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

import httpx
import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]
INDEX_DIR = REPO_ROOT / "data" / "case_index" / "eu"

SPARQL_ENDPOINT = "https://publications.europa.eu/webapi/rdf/sparql"
CELLAR_BASE = "https://publications.europa.eu/resource/cellar"

# English is language index 6 (alphabetical: BG=1 CS=2 DA=3 DE=4 EL=5 EN=6)
CELLAR_EN_LANG_IDX = "0006"

HEADERS = {
    "User-Agent": "CompMap-Scraper/1.0 (open-source research tool; contact: open-market)",
    "Accept": "application/sparql-results+json",
}

# NACE section letter → sector string used in CaseIndexEntry
NACE_SECTOR = {
    "A": "agriculture",
    "B": "extractives",
    "C": "manufacturing",
    "D": "energy",
    "E": "utilities",
    "F": "construction",
    "G": "retail",
    "H": "transport",
    "I": "hospitality",
    "J": "tech",
    "K": "financial",
    "L": "real_estate",
    "M": "professional_services",
    "N": "business_services",
    "O": "public_administration",
    "P": "education",
    "Q": "healthcare",
    "R": "media_entertainment",
    "S": "other_services",
    "T": "households",
    "U": "international_orgs",
}

# CDM type → Outcome string
CDM_OUTCOME = {
    "non-opposition_concentration_notified": "cleared",
    # Phase II types that may appear in future:
    "compatible_concentration": "cleared",
    "compatible_concentration_with_conditions": "cleared_with_conditions",
    "incompatible_concentration": "blocked",
}

_NOTIF_TITLE_RE = re.compile(
    r"Case\s+M\.\s*(\d+)\s*[-–]\s*(.+?)(?:\)\s*(?:Candidate|Subject|Simplified|$)|\s*$)",
    re.IGNORECASE,
)
_PARTIES_SPLIT_RE = re.compile(r"\s*/\s*")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ScrapedCase:
    case_number: str          # e.g. "11141"
    decision_celex: str       # e.g. "32023M11141"
    decision_date: str        # ISO date "YYYY-MM-DD"
    outcome: str              # from CDM_OUTCOME map
    nace_codes: list[str]     # e.g. ["M70.02.02"]
    notif_cellar_id: Optional[str] = None   # cellar UUID for notification
    title_from_sparql: Optional[str] = None  # work_title if available
    case_name: Optional[str] = None          # resolved after fetch
    parties: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# SPARQL helpers
# ---------------------------------------------------------------------------

def _sparql(client: httpx.Client, query: str) -> list[dict]:
    """Run a SPARQL query and return bindings list."""
    resp = client.get(
        SPARQL_ENDPOINT,
        params={"query": query},
        headers=HEADERS,
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["results"]["bindings"]


def _fetch_decision_batch(
    client: httpx.Client,
    from_date: str,
    to_date: str,
    limit: int,
    offset: int,
) -> list[ScrapedCase]:
    """Fetch one page of merger decisions from EUR-Lex SPARQL."""
    # Request 4× the desired limit because each case can have multiple NACE code rows
    # in the SPARQL results (one row per NACE code per case).  We deduplicate below,
    # accumulating all NACE codes per case, and stop once we have `limit` unique cases.
    raw_limit = limit * 4
    query = f"""
PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
SELECT DISTINCT ?decisionCelex ?date ?nace ?notifTitle ?notif WHERE {{
  ?decision a cdm:non-opposition_concentration_notified .
  ?decision cdm:resource_legal_id_celex ?decisionCelex .
  ?decision cdm:work_date_document ?date .
  FILTER(?date >= "{from_date}"^^xsd:date && ?date <= "{to_date}"^^xsd:date)
  OPTIONAL {{ ?decision cdm:resource_legal_information_miscellaneous ?nace }}
  ?decision cdm:resource_legal_number_natural_celex ?caseNum .
  OPTIONAL {{
    ?notif cdm:resource_legal_number_natural_celex ?caseNum .
    ?notif cdm:resource_legal_id_celex ?notifCelex .
    FILTER(REGEX(STR(?notifCelex), "^5[0-9]{{4}}M[0-9]") && !CONTAINS(STR(?notifCelex), "("))
    ?notif cdm:work_has_resource-type <http://publications.europa.eu/resource/authority/resource-type/ANNOUNC> .
    OPTIONAL {{ ?notif cdm:work_title ?notifTitle }}
  }}
}} ORDER BY DESC(?date) LIMIT {raw_limit} OFFSET {offset}
""".strip()

    bindings = _sparql(client, query)

    # Build one ScrapedCase per celex, accumulating NACE codes across duplicate rows.
    case_map: dict[str, ScrapedCase] = {}
    order: list[str] = []  # preserve DESC(?date) ordering

    for b in bindings:
        celex = b["decisionCelex"]["value"]

        if celex not in case_map:
            date_val = b["date"]["value"]  # "YYYY-MM-DD"
            case_number = re.search(r"M(\d+)$", celex)
            if not case_number:
                continue
            notif_cellar_id: Optional[str] = None
            notif_uri = b.get("notif", {}).get("value", "")
            if notif_uri:
                notif_cellar_id = notif_uri.rstrip("/").split("/")[-1]
            title_from_sparql = b.get("notifTitle", {}).get("value") or None
            case_map[celex] = ScrapedCase(
                case_number=case_number.group(1),
                decision_celex=celex,
                decision_date=date_val,
                outcome="cleared",  # non-opposition_concentration_notified
                nace_codes=[],
                notif_cellar_id=notif_cellar_id,
                title_from_sparql=title_from_sparql,
            )
            order.append(celex)

        nace_raw = b.get("nace", {}).get("value", "")
        for code in re.findall(r"NACE=([A-Z0-9\.]+)", nace_raw):
            if code not in case_map[celex].nace_codes:
                case_map[celex].nace_codes.append(code)

    return [case_map[c] for c in order[:limit]]


# ---------------------------------------------------------------------------
# Case name resolution
# ---------------------------------------------------------------------------

def _parse_notif_title(raw_title: str) -> tuple[Optional[str], list[str]]:
    """
    Extract (case_name, parties_list) from a notification title string.
    Input:  "Prior notification of a concentration (Case M.11141 – WENDEL / TOPSCALE)"
    Output: ("WENDEL / TOPSCALE", ["WENDEL", "TOPSCALE"])
    """
    m = _NOTIF_TITLE_RE.search(raw_title)
    if not m:
        return None, []  # not a merger notification title; callers should fall back
    parties_str = m.group(2).strip().rstrip(")")
    parties = [p.strip() for p in _PARTIES_SPLIT_RE.split(parties_str) if p.strip()]
    case_name = " / ".join(parties)
    return case_name, parties


def _fetch_case_name_from_cellar(
    client: httpx.Client,
    cellar_id: str,
) -> tuple[Optional[str], list[str]]:
    """
    Download the English FormEx XML for a notification and extract the case name.
    Returns (case_name, parties_list) or (None, []) on failure.
    """
    url = f"{CELLAR_BASE}/{cellar_id}.{CELLAR_EN_LANG_IDX}.02/DOC_1"
    try:
        resp = client.get(url, timeout=30, headers={"Accept": "*/*"})
        resp.raise_for_status()
    except Exception:
        return None, []

    try:
        z = zipfile.ZipFile(io.BytesIO(resp.content))
    except zipfile.BadZipFile:
        return None, []

    for name in z.namelist():
        text = z.read(name).decode("utf-8", errors="ignore")
        # Look for "Case M.NNNNN – PARTY A / PARTY B" pattern (en-dash or hyphen)
        m = re.search(
            r"Case\s+M\.\s*(\d+)\s*[-–]\s*([^<\n)]{5,150})",
            text,
        )
        if m:
            parties_str = m.group(2).strip().rstrip(")")
            # Strip trailing XML noise
            parties_str = re.split(r"[\)<]", parties_str)[0].strip()
            parties = [p.strip() for p in _PARTIES_SPLIT_RE.split(parties_str) if p.strip()]
            if parties:
                return " / ".join(parties), parties

    return None, []


def resolve_case_name(
    client: httpx.Client,
    sc: ScrapedCase,
    *,
    fetch_cellar: bool = True,
) -> None:
    """Mutate sc to set sc.case_name and sc.parties."""
    # Try work_title from SPARQL first (no extra HTTP request)
    if sc.title_from_sparql:
        name, parties = _parse_notif_title(sc.title_from_sparql)
        if name:
            sc.case_name = name
            sc.parties = parties
            return

    # Fallback: fetch cellar notification content
    if fetch_cellar and sc.notif_cellar_id:
        name, parties = _fetch_case_name_from_cellar(client, sc.notif_cellar_id)
        if name:
            sc.case_name = name
            sc.parties = parties
            return

    # Final fallback: use CELEX as placeholder
    sc.case_name = f"M.{sc.case_number}"
    sc.parties = []


# ---------------------------------------------------------------------------
# Sector / case_id helpers
# ---------------------------------------------------------------------------

def nace_to_sector(nace_codes: list[str]) -> str:
    """Map NACE section letter(s) to a sector string."""
    for code in nace_codes:
        section = code[0].upper() if code else ""
        if section in NACE_SECTOR:
            return NACE_SECTOR[section]
    return "other"


def _slug(text: str) -> str:
    """Normalize a party name to a slug."""
    text = re.sub(r"[^a-zA-Z0-9\s]", "", text.lower())
    text = re.sub(r"\s+", "_", text.strip())
    return text[:30]


def make_case_id(sc: ScrapedCase) -> str:
    """Generate a case_id like eu_wendel_topscale_2023."""
    year = sc.decision_date[:4]
    if sc.parties:
        slug_parts = [_slug(p) for p in sc.parties[:3] if _slug(p)]
        return "eu_" + "_".join(slug_parts) + f"_{year}"
    return f"eu_ec_m{sc.case_number}_{year}"


# ---------------------------------------------------------------------------
# YAML generation
# ---------------------------------------------------------------------------

def build_yaml(sc: ScrapedCase, case_id: str) -> dict:
    """Produce the YAML dict for a CaseIndexEntry."""
    record: dict = {
        "case_id": case_id,
        "case_name": sc.case_name or f"M.{sc.case_number}",
        "jurisdiction": "EU",
        "authority": "European Commission",
        "decision_date": sc.decision_date,
        "sector": nace_to_sector(sc.nace_codes),
        "outcome": sc.outcome,
        "case_type": "merger",
        "source_url": f"https://competition-cases.ec.europa.eu/cases/M.{sc.case_number}",
        "ai_summary": None,
        "parties": [],
        "concept_refs": [],
    }

    if sc.parties:
        party_list = []
        for i, p in enumerate(sc.parties):
            role = "target" if i == len(sc.parties) - 1 else "acquirer"
            party_list.append({"name": p, "role": role})
        record["parties"] = party_list

    return record


def write_yaml(out_path: Path, record: dict) -> None:
    """Write the YAML record, using block scalars for multiline strings."""
    with out_path.open("w", encoding="utf-8") as f:
        yaml.dump(
            record,
            f,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        )


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def _load_existing_ids(index_dir: Path) -> set[str]:
    """Return set of case_ids already in the index (EU and canonical)."""
    ids: set[str] = set()
    # Case index
    for p in index_dir.glob("*.yaml"):
        ids.add(p.stem)
    # Also scan canonical cases to avoid duplicate case_ids
    canonical_dir = REPO_ROOT / "data" / "cases"
    for p in canonical_dir.glob("*.yaml"):
        ids.add(p.stem)
    return ids


def _load_existing_case_numbers(index_dir: Path) -> set[str]:
    """Return set of M.NNNNN case numbers already scraped."""
    numbers: set[str] = set()
    for p in index_dir.glob("*.yaml"):
        with p.open() as f:
            doc = yaml.safe_load(f)
        url = doc.get("source_url", "")
        m = re.search(r"M\.(\d+)$", url)
        if m:
            numbers.add(m.group(1))
    return numbers


# ---------------------------------------------------------------------------
# Main scraping loop
# ---------------------------------------------------------------------------

def scrape(
    *,
    from_date: str,
    to_date: str,
    limit: Optional[int],
    dry_run: bool,
    force: bool,
    batch_size: int = 100,
    delay: float = 0.5,
) -> None:
    INDEX_DIR.mkdir(parents=True, exist_ok=True)

    existing_numbers = _load_existing_case_numbers(INDEX_DIR)
    existing_ids = _load_existing_ids(INDEX_DIR)
    print(f"Existing index entries: {len(existing_numbers)} cases")

    total_written = 0
    total_skipped = 0
    offset = 0

    with httpx.Client(follow_redirects=True, timeout=60) as client:
        while True:
            page_limit = batch_size
            if limit is not None:
                remaining = limit - total_written - total_skipped
                if remaining <= 0:
                    break
                page_limit = min(batch_size, remaining + 20)  # slight overfetch

            print(f"\nFetching batch: offset={offset}, limit={page_limit}")
            try:
                cases = _fetch_decision_batch(
                    client, from_date, to_date, page_limit, offset
                )
            except Exception as e:
                print(f"SPARQL error: {e}", file=sys.stderr)
                break

            if not cases:
                print("No more results.")
                break

            for sc in cases:
                if limit is not None and (total_written + total_skipped) >= limit:
                    break

                if not force and sc.case_number in existing_numbers:
                    total_skipped += 1
                    continue

                # Resolve case name (may fetch cellar content)
                resolve_case_name(client, sc, fetch_cellar=not dry_run or sc.title_from_sparql is not None)
                time.sleep(delay)  # be polite

                case_id = make_case_id(sc)
                # Deduplicate case_id collisions by appending case number
                if case_id in existing_ids and not force:
                    case_id = f"eu_ec_m{sc.case_number}_{sc.decision_date[:4]}"

                record = build_yaml(sc, case_id)

                if dry_run:
                    print(f"  [DRY] {case_id}: {record['case_name']}  ({record['decision_date']}) [{record['sector']}]")
                    total_written += 1
                    continue

                out_path = INDEX_DIR / f"{case_id}.yaml"
                if out_path.exists() and not force:
                    total_skipped += 1
                    continue

                write_yaml(out_path, record)
                existing_ids.add(case_id)
                existing_numbers.add(sc.case_number)
                total_written += 1
                print(f"  WROTE {case_id}: {record['case_name']}")

            offset += len(cases)
            if len(cases) < page_limit:
                break  # last page

            time.sleep(delay)

    print(f"\nDone. Written: {total_written}  Skipped: {total_skipped}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scrape EC merger decisions from EUR-Lex into data/case_index/eu/"
    )
    parser.add_argument(
        "--from-date",
        default="2019-01-01",
        help="Start date for decisions (ISO format, default: 2019-01-01)",
    )
    parser.add_argument(
        "--to-date",
        default=date.today().isoformat(),
        help="End date for decisions (ISO format, default: today)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Stop after writing this many new entries (useful for testing)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be written without creating files",
    )
    parser.add_argument(
        "--force",
        action="store_false",
        help="Overwrite existing entries",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="SPARQL results per page (default: 100)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="Seconds to wait between cellar content fetches (default: 0.5)",
    )
    args = parser.parse_args(argv)

    scrape(
        from_date=args.from_date,
        to_date=args.to_date,
        limit=args.limit,
        dry_run=args.dry_run,
        force=args.force,
        batch_size=args.batch_size,
        delay=args.delay,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
