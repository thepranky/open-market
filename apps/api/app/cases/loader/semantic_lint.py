"""Deterministic semantic lint for canonical case YAML (ROADMAP 4.5).

A third validation layer beside schema (`validator.py`) and source-integrity
(`check_source_integrity.py`). It catches legal-meaning errors that pass Pydantic
but encode the wrong legal weight or wire identifiers incorrectly — "lawyer rules"
from DDR-A that no other gate enforces.

Rules (both ERROR):

  1. complaint_not_defined — a product/geographic market whose supporting passages
     all reference complaint-type documents (and none reference a non-complaint
     document) must not be `definition_status: defined`. Allegations are contested
     claims, not findings.
  2. dangling_support_ref — every market/theory/commitment id named in a passage's
     `supports_*` list must exist in the record.

Pure module: no I/O beyond reading YAML via the loader, so it can be reused per-draft
by the dual-extraction comparison (ROADMAP 5.9).
"""

from dataclasses import dataclass

from app.cases.loader.yaml_loader import load_all_cases
from app.cases.models import CaseRecord, DefinitionStatus

# doc_type substring marking a document as a complaint (allegations, not findings).
_COMPLAINT_MARKER = "complaint"


@dataclass(frozen=True)
class Issue:
    case_id: str
    rule: str
    message: str

    def __str__(self) -> str:
        return f"[{self.rule}] {self.case_id}: {self.message}"


def _complaint_doc_ids(record: CaseRecord) -> set[str]:
    return {
        d.doc_id
        for d in record.source_documents
        if _COMPLAINT_MARKER in d.doc_type.lower()
    }


def _check_complaint_not_defined(record: CaseRecord) -> list[Issue]:
    """Rule 1: complaint-only markets must not be `defined`."""
    complaint_docs = _complaint_doc_ids(record)
    if not complaint_docs:
        return []

    issues: list[Issue] = []
    # Keep product / geographic id namespaces separate: a passage supports a product
    # market via supports_markets and a geographic market via supports_geographic_markets.
    markets = [
        ("product market", m, "supports_markets")
        for m in record.product_markets_considered
    ] + [
        ("geographic market", m, "supports_geographic_markets")
        for m in record.geographic_markets_considered
    ]

    for kind, market, support_field in markets:
        if market.definition_status != DefinitionStatus.defined:
            continue

        supporting_docs: set[str] = set()
        for passage in record.source_passages:
            if market.market_id in getattr(passage, support_field):
                supporting_docs.add(passage.source_document_id)

        # Only flag markets actually grounded in passages, all of which are complaints.
        if supporting_docs and supporting_docs <= complaint_docs:
            issues.append(
                Issue(
                    case_id=record.case_id,
                    rule="complaint_not_defined",
                    message=(
                        f"{kind} '{market.market_id}' has definition_status=defined but is "
                        f"supported only by complaint document(s) {sorted(supporting_docs)}; "
                        f"complaint allegations are not findings — use 'discussed'."
                    ),
                )
            )

    return issues


def _check_dangling_support_refs(record: CaseRecord) -> list[Issue]:
    """Rule 2: every supports_* id must resolve to an entity in the record."""
    product_ids = {m.market_id for m in record.product_markets_considered}
    geo_ids = {m.market_id for m in record.geographic_markets_considered}
    theory_ids = {t.theory_id for t in record.theories_of_harm}
    commitment_ids = {c.commitment_id for c in record.commitments}

    issues: list[Issue] = []
    for passage in record.source_passages:
        for field, ids, valid in (
            ("supports_markets", passage.supports_markets, product_ids),
            ("supports_geographic_markets", passage.supports_geographic_markets, geo_ids),
            ("supports_theories", passage.supports_theories, theory_ids),
            ("supports_commitments", passage.supports_commitments, commitment_ids),
        ):
            for ref in ids:
                if ref not in valid:
                    issues.append(
                        Issue(
                            case_id=record.case_id,
                            rule="dangling_support_ref",
                            message=(
                                f"passage '{passage.passage_id}' {field} references "
                                f"'{ref}', which does not exist in the record."
                            ),
                        )
                    )

    return issues


def lint_case(record: CaseRecord) -> list[Issue]:
    """Run all semantic rules against a single record."""
    return _check_complaint_not_defined(record) + _check_dangling_support_refs(record)


def lint_all(
    cases_dir: str, case_id: str | None = None
) -> tuple[int, list[Issue], list[str]]:
    """Lint every case under cases_dir (or just case_id).

    Returns (cases_checked, issues, load_errors).
    """
    checked = 0
    issues: list[Issue] = []
    load_errors: list[str] = []

    for path, result in load_all_cases(cases_dir):
        if isinstance(result, Exception):
            load_errors.append(f"{path}: {type(result).__name__}: {result}")
            continue
        if case_id is not None and result.case_id != case_id:
            continue
        checked += 1
        issues.extend(lint_case(result))

    return checked, issues, load_errors
