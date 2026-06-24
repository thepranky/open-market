from functools import lru_cache

from app.shared.core.config import settings
from app.cases.loader.yaml_loader import load_cases_dict
from app.cases.models import CaseRecord


@lru_cache(maxsize=1)
def _load_cases() -> dict[str, CaseRecord]:
    return load_cases_dict(settings.data_cases_path)


def get_all_cases() -> list[CaseRecord]:
    return list(_load_cases().values())


def get_case(case_id: str) -> CaseRecord | None:
    return _load_cases().get(case_id)


def search_cases(query: str) -> list[CaseRecord]:
    q = query.lower()
    results = []
    for case in _load_cases().values():
        haystack = " ".join([
            case.case_name,
            case.jurisdiction,
            case.authority,
            case.sector,
            case.outcome.value,
            " ".join(p.name for p in case.parties),
            " ".join(m.name for m in case.product_markets_considered),
            " ".join(m.name for m in case.geographic_markets_considered),
            " ".join(t.name for t in case.theories_of_harm),
            case.ai_summary or "",
        ]).lower()
        if q in haystack:
            results.append(case)
    return results


def invalidate_cache() -> None:
    _load_cases.cache_clear()
