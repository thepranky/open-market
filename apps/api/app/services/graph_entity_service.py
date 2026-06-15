"""
Aggregates entity data across all canonical YAML cases for entity-centric graph views.
All data served from the in-memory lru_cache — no database queries needed.
"""
from collections import defaultdict

from app.services.case_service import get_all_cases


def _top_level_sector(sector: str) -> str:
    """Return the broad sector group — the part before ' / ', e.g. 'digital / gaming' → 'digital'."""
    return sector.split("/")[0].strip()


def get_all_markets() -> list[dict]:
    """
    Returns one dict per unique market name (lowercased for dedup) with:
    market_name, case_count, definition_status_breakdown, dominant_status,
    case_ids, sectors.
    """
    agg: dict[str, dict] = {}

    for case in get_all_cases():
        for pm in case.product_markets_considered:
            key = pm.name.strip().lower()
            if key not in agg:
                agg[key] = {
                    "market_name": pm.name,
                    "case_ids": [],
                    "sectors": [],
                    "definition_status_breakdown": defaultdict(int),
                    "case_count": 0,
                }
            entry = agg[key]
            if case.case_id not in entry["case_ids"]:
                entry["case_ids"].append(case.case_id)
                entry["case_count"] += 1
                if case.sector not in entry["sectors"]:
                    entry["sectors"].append(case.sector)
            entry["definition_status_breakdown"][pm.definition_status.value] += 1

    result = []
    for entry in agg.values():
        breakdown = dict(entry["definition_status_breakdown"])
        result.append({
            "market_name": entry["market_name"],
            "case_count": entry["case_count"],
            "case_ids": entry["case_ids"],
            "sectors": entry["sectors"],
            "definition_status_breakdown": breakdown,
            "dominant_status": _dominant(breakdown),
        })

    return sorted(result, key=lambda x: x["case_count"], reverse=True)


def get_market_cases(market_name: str) -> list[dict]:
    """All cases that have a product market with this exact name (case-insensitive)."""
    name_lower = market_name.strip().lower()
    results = []
    for case in get_all_cases():
        for pm in case.product_markets_considered:
            if pm.name.strip().lower() == name_lower:
                results.append({
                    "case_id": case.case_id,
                    "case_name": case.case_name,
                    "jurisdiction": case.jurisdiction,
                    "authority": case.authority,
                    "decision_date": case.decision_date.isoformat(),
                    "outcome": case.outcome.value,
                    "market_id": pm.market_id,
                    "definition_status": pm.definition_status.value,
                    "notes": pm.notes,
                })
                break
    return results


def get_all_theories() -> list[dict]:
    """
    Returns one dict per unique theory name with:
    theory_name, case_count, case_ids, outcome_breakdown, sectors.
    """
    agg: dict[str, dict] = {}

    for case in get_all_cases():
        for toh in case.theories_of_harm:
            key = toh.name.strip().lower()
            if key not in agg:
                agg[key] = {
                    "theory_name": toh.name,
                    "case_ids": [],
                    "sectors": [],
                    "outcome_breakdown": defaultdict(int),
                    "case_count": 0,
                }
            entry = agg[key]
            if case.case_id not in entry["case_ids"]:
                entry["case_ids"].append(case.case_id)
                entry["case_count"] += 1
                entry["outcome_breakdown"][case.outcome.value] += 1
                if case.sector not in entry["sectors"]:
                    entry["sectors"].append(case.sector)

    result = []
    for entry in agg.values():
        result.append({
            "theory_name": entry["theory_name"],
            "case_count": entry["case_count"],
            "case_ids": entry["case_ids"],
            "sectors": entry["sectors"],
            "outcome_breakdown": dict(entry["outcome_breakdown"]),
        })

    return sorted(result, key=lambda x: x["case_count"], reverse=True)


def get_theory_cases(theory_name: str) -> list[dict]:
    """All cases that applied this theory (case-insensitive exact match)."""
    name_lower = theory_name.strip().lower()
    results = []
    for case in get_all_cases():
        for toh in case.theories_of_harm:
            if toh.name.strip().lower() == name_lower:
                results.append({
                    "case_id": case.case_id,
                    "case_name": case.case_name,
                    "jurisdiction": case.jurisdiction,
                    "authority": case.authority,
                    "decision_date": case.decision_date.isoformat(),
                    "outcome": case.outcome.value,
                    "theory_id": toh.theory_id,
                    "description": toh.description,
                })
                break
    return results


def _dominant(breakdown: dict) -> str:
    if not breakdown:
        return "discussed"
    return max(breakdown, key=breakdown.get)


def get_all_sectors() -> list[dict]:
    """Top-level sector groups with case counts, derived from all canonical cases."""
    agg: dict[str, dict] = {}

    for case in get_all_cases():
        top = _top_level_sector(case.sector)
        if top not in agg:
            agg[top] = {
                "sector": top,
                "case_count": 0,
                "market_names": set(),
                "outcome_breakdown": defaultdict(int),
            }
        entry = agg[top]
        entry["case_count"] += 1
        entry["outcome_breakdown"][case.outcome.value] += 1
        for pm in case.product_markets_considered:
            entry["market_names"].add(pm.name.strip().lower())

    result = []
    for entry in agg.values():
        result.append({
            "sector": entry["sector"],
            "case_count": entry["case_count"],
            "market_count": len(entry["market_names"]),
            "outcome_breakdown": dict(entry["outcome_breakdown"]),
        })
    return sorted(result, key=lambda x: x["case_count"], reverse=True)


def get_sector_markets(sector: str) -> list[dict]:
    """Product markets from all canonical cases in the given top-level sector."""
    sector_lower = sector.strip().lower()
    agg: dict[str, dict] = {}

    for case in get_all_cases():
        if _top_level_sector(case.sector).lower() != sector_lower:
            continue
        for pm in case.product_markets_considered:
            key = pm.name.strip().lower()
            if key not in agg:
                agg[key] = {
                    "market_name": pm.name,
                    "case_count": 0,
                    "definition_status_breakdown": defaultdict(int),
                    "cases": [],
                }
            entry = agg[key]
            seen_ids = {c["case_id"] for c in entry["cases"]}
            if case.case_id not in seen_ids:
                entry["case_count"] += 1
                entry["cases"].append({
                    "case_id": case.case_id,
                    "case_name": case.case_name,
                    "outcome": case.outcome.value,
                    "definition_status": pm.definition_status.value,
                    "jurisdiction": case.jurisdiction,
                })
            entry["definition_status_breakdown"][pm.definition_status.value] += 1

    result = []
    for entry in agg.values():
        breakdown = dict(entry["definition_status_breakdown"])
        result.append({
            "market_name": entry["market_name"],
            "case_count": entry["case_count"],
            "dominant_status": _dominant(breakdown),
            "definition_status_breakdown": breakdown,
            "cases": entry["cases"],
        })
    return sorted(result, key=lambda x: x["case_count"], reverse=True)


def get_similar_markets_cooccurrence(market_name: str, limit: int = 10) -> list[dict]:
    """Markets that appear in the same cases as the given market, ranked by co-occurrence count."""
    name_lower = market_name.strip().lower()

    source_case_ids: set[str] = set()
    for case in get_all_cases():
        for pm in case.product_markets_considered:
            if pm.name.strip().lower() == name_lower:
                source_case_ids.add(case.case_id)
                break

    if not source_case_ids:
        return []

    agg: dict[str, dict] = {}
    for case in get_all_cases():
        if case.case_id not in source_case_ids:
            continue
        for pm in case.product_markets_considered:
            key = pm.name.strip().lower()
            if key == name_lower:
                continue
            if key not in agg:
                agg[key] = {
                    "market_name": pm.name,
                    "shared_case_ids": [],
                    "definition_status_breakdown": defaultdict(int),
                }
            entry = agg[key]
            if case.case_id not in entry["shared_case_ids"]:
                entry["shared_case_ids"].append(case.case_id)
            entry["definition_status_breakdown"][pm.definition_status.value] += 1

    result = []
    for entry in agg.values():
        breakdown = dict(entry["definition_status_breakdown"])
        result.append({
            "market_name": entry["market_name"],
            "shared_case_count": len(entry["shared_case_ids"]),
            "shared_case_ids": entry["shared_case_ids"],
            "case_count": len(entry["shared_case_ids"]),
            "dominant_status": _dominant(breakdown),
        })
    return sorted(result, key=lambda x: x["shared_case_count"], reverse=True)[:limit]
