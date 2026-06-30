import pytest
from pydantic import ValidationError

from app.cases.models.case_index import CaseIndexEntry
from case_index_builder import (
    CaseIndexParty,
    CaseIndexSeed,
    build_case_index_dict,
)


def _seed(**overrides):
    values = {
        "case_id": "us_example_2024",
        "case_name": "Example / Target",
        "jurisdiction": "US",
        "authority": "DOJ",
        "decision_date": "2024-01-15",
        "sector": "tech",
        "outcome": "cleared",
        "source_url": "https://www.justice.gov/atr/case/example-target",
        "parties": (
            CaseIndexParty(name="Example", role="acquirer"),
            CaseIndexParty(name="Target", role="target"),
        ),
    }
    values.update(overrides)
    return CaseIndexSeed(**values)


def test_build_case_index_dict_validates_and_returns_yaml_safe_dict():
    record = build_case_index_dict(_seed())

    assert record["decision_date"] == "2024-01-15"
    assert record["outcome"] == "cleared"
    assert record["case_type"] == "merger"
    assert record["ai_summary"] is None
    assert record["parties"] == [
        {"name": "Example", "role": "acquirer"},
        {"name": "Target", "role": "target"},
    ]
    assert record["concept_refs"] == []
    assert "pdf_url" not in record
    assert "pdf_language" not in record
    assert "extraction_status" not in record
    CaseIndexEntry.model_validate(record)


def test_build_case_index_dict_rejects_invalid_schema_values():
    with pytest.raises(ValidationError):
        build_case_index_dict(_seed(outcome="not_an_outcome"))


def test_build_case_index_dict_rejects_invalid_party_role():
    seed = _seed(parties=(CaseIndexParty(name="Bad Role", role="party"),))

    with pytest.raises(ValidationError):
        build_case_index_dict(seed)
