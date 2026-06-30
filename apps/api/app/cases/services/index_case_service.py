from functools import lru_cache

from app.shared.core import config
from app.cases.loader.index_loader import load_all_index_cases
from app.cases.models.case_index import CaseIndexEntry


@lru_cache(maxsize=1)
def _load_index() -> dict[str, CaseIndexEntry]:
    entries: dict[str, CaseIndexEntry] = {}
    for _, result in load_all_index_cases(config.settings.data_case_index_path):
        if isinstance(result, CaseIndexEntry):
            entries[result.case_id] = result
    return entries


def get_all_indexed() -> list[CaseIndexEntry]:
    return list(_load_index().values())


def get_indexed_case(case_id: str) -> CaseIndexEntry | None:
    return _load_index().get(case_id)


def search_indexed(query: str) -> list[CaseIndexEntry]:
    q = query.lower()
    results = []
    for entry in _load_index().values():
        haystack = " ".join([
            entry.case_name,
            entry.jurisdiction,
            entry.authority,
            entry.sector,
            entry.outcome.value,
            " ".join(p.name for p in entry.parties),
            " ".join(r.concept_id for r in entry.concept_refs),
            entry.ai_summary or "",
        ]).lower()
        if q in haystack:
            results.append(entry)
    return results


def invalidate_cache() -> None:
    _load_index.cache_clear()
