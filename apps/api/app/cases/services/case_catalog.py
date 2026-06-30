from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

from app.cases.models import CaseRecord
from app.cases.models.api_responses import CaseSearchHit, IndexedCaseDetail
from app.cases.models.case_index import CaseIndexEntry
from app.cases.services.case_service import get_all_cases, get_case
from app.cases.services.index_case_service import get_all_indexed, get_indexed_case

DataLayer = Literal["canonical", "indexed"]
CatalogScope = Literal["all", "canonical", "indexed"]


@dataclass(frozen=True)
class CatalogListQuery:
    scope: CatalogScope = "all"
    jurisdiction: str | None = None
    sector: str | None = None
    outcome: str | None = None
    theory: str | None = None
    year_from: int | None = None
    year_to: int | None = None


@dataclass(frozen=True)
class CatalogSearchQuery:
    q: str
    scope: CatalogScope = "all"
    jurisdiction: str | None = None
    year_from: int | None = None
    year_to: int | None = None


@dataclass(frozen=True)
class CatalogRecord:
    data_layer: DataLayer
    record: CaseRecord | CaseIndexEntry

    @property
    def record_status(self) -> str:
        if self.data_layer == "canonical":
            return "canonical_reviewed"
        return "indexed_metadata"

    @property
    def case_id(self) -> str:
        return self.record.case_id

    @property
    def case_name(self) -> str:
        return self.record.case_name

    @property
    def jurisdiction(self) -> str:
        return self.record.jurisdiction

    @property
    def authority(self) -> str:
        return self.record.authority

    @property
    def decision_date(self) -> date:
        return self.record.decision_date

    @property
    def sector(self) -> str:
        return self.record.sector

    @property
    def outcome_value(self) -> str:
        return self.record.outcome.value

    @property
    def case_type(self) -> str:
        return self.record.case_type

    @property
    def ai_summary(self) -> str | None:
        return self.record.ai_summary

    @property
    def canonical(self) -> CaseRecord:
        if not isinstance(self.record, CaseRecord):
            raise TypeError("CatalogRecord does not contain a canonical case")
        return self.record

    @property
    def indexed(self) -> CaseIndexEntry:
        if not isinstance(self.record, CaseIndexEntry):
            raise TypeError("CatalogRecord does not contain an indexed case")
        return self.record

    @property
    def source_url(self) -> str | None:
        if self.data_layer == "indexed":
            return self.indexed.source_url
        case = self.canonical
        return next(
            (d.case_page_url for d in case.source_documents if d.case_page_url),
            None,
        ) or next(
            (d.url for d in case.source_documents if d.url),
            None,
        )

    @property
    def product_market_count(self) -> int:
        if self.data_layer == "canonical":
            return len(self.canonical.product_markets_considered)
        return 0

    @property
    def theory_count(self) -> int:
        if self.data_layer == "canonical":
            return len(self.canonical.theories_of_harm)
        return 0

    @property
    def source_passage_count(self) -> int:
        if self.data_layer == "canonical":
            return len(self.canonical.source_passages)
        return 0

    @property
    def searchable_text(self) -> str:
        pieces = [
            self.case_name,
            self.jurisdiction,
            self.authority,
            self.sector,
            self.outcome_value,
            " ".join(p.name for p in self.record.parties),
            self.ai_summary or "",
        ]
        if self.data_layer == "canonical":
            case = self.canonical
            pieces.extend([
                " ".join(m.name for m in case.product_markets_considered),
                " ".join(m.name for m in case.geographic_markets_considered),
                " ".join(t.name for t in case.theories_of_harm),
            ])
        else:
            pieces.append(" ".join(r.concept_id for r in self.indexed.concept_refs))
        return " ".join(pieces).lower()


class CaseCatalog:
    def list(self, query: CatalogListQuery) -> list[CatalogRecord]:
        records: list[CatalogRecord] = []
        if query.scope in ("all", "canonical"):
            records.extend(CatalogRecord("canonical", case) for case in get_all_cases())
        if query.scope in ("all", "indexed"):
            records.extend(CatalogRecord("indexed", entry) for entry in get_all_indexed())
        return [record for record in records if self._matches_list_query(record, query)]

    def get(
        self,
        case_id: str,
        *,
        include_indexed: bool = True,
        data_layer: DataLayer | None = None,
    ) -> CatalogRecord | None:
        if data_layer == "canonical":
            case = get_case(case_id)
            return CatalogRecord("canonical", case) if case else None
        if data_layer == "indexed":
            if not include_indexed:
                return None
            entry = get_indexed_case(case_id)
            return CatalogRecord("indexed", entry) if entry else None

        case = get_case(case_id)
        if case:
            return CatalogRecord("canonical", case)
        if include_indexed:
            entry = get_indexed_case(case_id)
            if entry:
                return CatalogRecord("indexed", entry)
        return None

    def search(self, query: CatalogSearchQuery) -> list[CaseSearchHit]:
        q = query.q.strip().lower()
        if not q:
            return []
        records = self.list(CatalogListQuery(
            scope=query.scope,
            jurisdiction=query.jurisdiction,
            year_from=query.year_from,
            year_to=query.year_to,
        ))
        return [
            self.project_hit(record)
            for record in records
            if q in record.searchable_text
        ]

    def project_hit(self, record: CatalogRecord) -> CaseSearchHit:
        return CaseSearchHit(
            data_layer=record.data_layer,
            record_status=record.record_status,
            href=self.href_for(record),
            case_id=record.case_id,
            case_name=record.case_name,
            jurisdiction=record.jurisdiction,
            authority=record.authority,
            decision_date=record.decision_date,
            sector=record.sector,
            outcome=record.record.outcome,
            case_type=record.case_type,
            source_url=record.source_url,
            ai_summary=record.ai_summary,
            parties=record.record.parties,
            concept_refs=record.record.concept_refs,
            product_market_count=record.product_market_count,
            theory_count=record.theory_count,
            source_passage_count=record.source_passage_count,
        )

    def project_indexed_detail(self, record: CatalogRecord) -> IndexedCaseDetail:
        if record.data_layer != "indexed":
            raise TypeError("Indexed detail projection requires an indexed record")
        return IndexedCaseDetail.model_validate(record.indexed.model_dump())

    def href_for(self, record: CatalogRecord) -> str:
        if record.data_layer == "canonical":
            return f"/cases/{record.case_id}"
        return f"/indexed-cases/{record.case_id}"

    def _matches_list_query(
        self,
        record: CatalogRecord,
        query: CatalogListQuery,
    ) -> bool:
        if query.jurisdiction and record.jurisdiction.upper() != query.jurisdiction.upper():
            return False
        if query.sector and query.sector.lower() not in record.sector.lower():
            return False
        if query.outcome and record.outcome_value != query.outcome:
            return False
        if query.theory and not self._matches_theory(record, query.theory):
            return False
        if query.year_from is not None and record.decision_date.year < query.year_from:
            return False
        if query.year_to is not None and record.decision_date.year > query.year_to:
            return False
        return True

    def _matches_theory(self, record: CatalogRecord, theory: str) -> bool:
        if record.data_layer != "canonical":
            return False
        tl = theory.lower()
        return any(
            tl in t.name.lower() or tl in (t.description or "").lower()
            for t in record.canonical.theories_of_harm
        )


def get_case_catalog() -> CaseCatalog:
    return CaseCatalog()
