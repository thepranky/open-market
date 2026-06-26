"""Tests for the deterministic case semantic lint (ROADMAP 4.5)."""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.cases.loader.semantic_lint import lint_case
from app.cases.models import (
    CaseMetadata,
    CaseRecord,
    DefinitionStatus,
    ExtractionMethod,
    GeographicMarket,
    Outcome,
    Party,
    PartyRole,
    ProductMarket,
    ReviewStatus,
    SourceDocument,
    SourcePassage,
)


def _doc(doc_id: str, doc_type: str) -> SourceDocument:
    return SourceDocument(doc_id=doc_id, title=doc_id, doc_type=doc_type)


def _passage(passage_id: str, doc_id: str, **supports) -> SourcePassage:
    return SourcePassage(
        passage_id=passage_id,
        source_document_id=doc_id,
        quote_snippet="x",
        extraction_method=ExtractionMethod.pdf_extracted,
        review_status=ReviewStatus.spot_checked,
        confidence_score=0.9,
        last_checked_date=date(2026, 6, 25),
        **supports,
    )


def _record(**overrides) -> CaseRecord:
    base = dict(
        case_id="us_test_2024",
        case_name="Test",
        jurisdiction="US",
        authority="FTC",
        decision_date=date(2024, 1, 1),
        procedure_stage="litigation",
        sector="x",
        parties=[Party(name="A", role=PartyRole.acquirer)],
        outcome=Outcome.blocked,
        metadata=CaseMetadata(
            extraction_method=ExtractionMethod.pdf_extracted,
            review_status=ReviewStatus.spot_checked,
            overall_confidence=0.9,
            created_date=date(2026, 6, 25),
            last_updated_date=date(2026, 6, 25),
        ),
    )
    base.update(overrides)
    return CaseRecord(**base)


# --- Rule 1: complaint_not_defined ----------------------------------------


def test_complaint_only_defined_market_flagged():
    record = _record(
        source_documents=[_doc("d1", "complaint")],
        product_markets_considered=[
            ProductMarket(market_id="m1", name="M1", definition_status=DefinitionStatus.defined)
        ],
        source_passages=[_passage("p1", "d1", supports_markets=["m1"])],
    )
    issues = lint_case(record)
    assert len(issues) == 1
    assert issues[0].rule == "complaint_not_defined"


def test_complaint_market_discussed_is_ok():
    record = _record(
        source_documents=[_doc("d1", "complaint")],
        product_markets_considered=[
            ProductMarket(market_id="m1", name="M1", definition_status=DefinitionStatus.discussed)
        ],
        source_passages=[_passage("p1", "d1", supports_markets=["m1"])],
    )
    assert lint_case(record) == []


def test_market_with_non_complaint_support_is_ok():
    # Defined market backed by a decision passage as well as a complaint passage.
    record = _record(
        source_documents=[_doc("d1", "complaint"), _doc("d2", "decision")],
        product_markets_considered=[
            ProductMarket(market_id="m1", name="M1", definition_status=DefinitionStatus.defined)
        ],
        source_passages=[
            _passage("p1", "d1", supports_markets=["m1"]),
            _passage("p2", "d2", supports_markets=["m1"]),
        ],
    )
    assert lint_case(record) == []


def test_geographic_complaint_only_defined_flagged():
    record = _record(
        source_documents=[_doc("d1", "complaint")],
        geographic_markets_considered=[
            GeographicMarket(market_id="g1", name="G1", definition_status=DefinitionStatus.defined)
        ],
        source_passages=[_passage("p1", "d1", supports_geographic_markets=["g1"])],
    )
    issues = lint_case(record)
    assert [i.rule for i in issues] == ["complaint_not_defined"]


# --- Rule 2: dangling_support_ref -----------------------------------------


def test_dangling_market_ref_flagged():
    record = _record(
        source_documents=[_doc("d1", "decision")],
        product_markets_considered=[
            ProductMarket(market_id="m1", name="M1", definition_status=DefinitionStatus.defined)
        ],
        source_passages=[_passage("p1", "d1", supports_markets=["m_missing"])],
    )
    issues = lint_case(record)
    assert len(issues) == 1
    assert issues[0].rule == "dangling_support_ref"
    assert "m_missing" in issues[0].message


def test_dangling_theory_ref_flagged():
    record = _record(
        source_documents=[_doc("d1", "decision")],
        source_passages=[_passage("p1", "d1", supports_theories=["t_missing"])],
    )
    issues = lint_case(record)
    assert len(issues) == 1
    assert issues[0].rule == "dangling_support_ref"
    assert "t_missing" in issues[0].message


def test_dangling_commitment_ref_flagged():
    record = _record(
        source_documents=[_doc("d1", "decision")],
        source_passages=[_passage("p1", "d1", supports_commitments=["c_missing"])],
    )
    issues = lint_case(record)
    assert len(issues) == 1
    assert issues[0].rule == "dangling_support_ref"
    assert "c_missing" in issues[0].message


def test_resolved_refs_are_ok():
    record = _record(
        source_documents=[_doc("d1", "decision")],
        product_markets_considered=[
            ProductMarket(market_id="m1", name="M1", definition_status=DefinitionStatus.defined)
        ],
        source_passages=[_passage("p1", "d1", supports_markets=["m1"])],
    )
    assert lint_case(record) == []
