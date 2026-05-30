"""Tests for schema validation of sample YAML case records."""

import sys
from pathlib import Path

import pytest

# Resolve from repo root regardless of cwd
REPO_ROOT = Path(__file__).parent.parent.parent.parent
CASES_DIR = REPO_ROOT / "data" / "cases"
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.loader.yaml_loader import load_yaml_file
from app.loader.validator import validate_all
from app.models import CaseRecord, Outcome, RetrievalStatus, CaseHistoryStatus, VerificationStatus


def _sample_files():
    return sorted(p for p in CASES_DIR.rglob("*.yaml") if ".draft" not in p.stem)


@pytest.mark.parametrize("yaml_path", _sample_files(), ids=lambda p: p.stem)
def test_yaml_validates(yaml_path):
    case = load_yaml_file(yaml_path)
    assert isinstance(case, CaseRecord)
    assert case.case_id
    assert case.jurisdiction in {"EU", "UK", "US"}


def test_all_cases_valid():
    ok, errors, msgs = validate_all(str(CASES_DIR))
    assert errors == 0, f"Validation errors:\n" + "\n".join(msgs)
    assert ok >= 3


def test_google_fitbit_structure():
    path = CASES_DIR / "eu" / "eu_google_fitbit_2021.yaml"
    case = load_yaml_file(path)
    assert case.case_id == "eu_google_fitbit_2021"
    assert case.jurisdiction == "EU"
    assert case.outcome == Outcome.cleared_with_remedies
    assert len(case.product_markets_considered) >= 2
    assert len(case.source_passages) >= 1
    for passage in case.source_passages:
        assert 0.0 <= passage.confidence_score <= 1.0


def test_illumina_grail_blocked():
    path = CASES_DIR / "eu" / "eu_illumina_grail_2022.yaml"
    case = load_yaml_file(path)
    assert case.outcome == Outcome.blocked
    assert len(case.theories_of_harm) >= 1


def test_jetblue_spirit_blocked():
    path = CASES_DIR / "us" / "jetblue_spirit_2024.yaml"
    case = load_yaml_file(path)
    assert case.outcome == Outcome.blocked
    assert case.sector == "airlines / travel"
    assert len(case.source_documents) >= 1


def test_source_document_retrieval_status():
    path = CASES_DIR / "eu" / "eu_google_fitbit_2021.yaml"
    case = load_yaml_file(path)
    doc = case.source_documents[0]
    assert doc.retrieval_status == RetrievalStatus.direct
    assert doc.pdf_url is not None
    assert doc.pdf_url.endswith(".pdf")


def test_case_history_google_fitbit():
    path = CASES_DIR / "eu" / "eu_google_fitbit_2021.yaml"
    case = load_yaml_file(path)
    assert case.case_history is not None
    assert case.case_history.status == CaseHistoryStatus.final_no_known_challenge
    assert len(case.case_history.events) >= 1


def test_case_history_illumina_annulled():
    path = CASES_DIR / "eu" / "eu_illumina_grail_2022.yaml"
    case = load_yaml_file(path)
    assert case.case_history is not None
    assert case.case_history.status == CaseHistoryStatus.annulled
    assert any(e.event_type == "judgment" for e in case.case_history.events)


def test_proposition_verification_defaults():
    # ProductMarket verification is optional — should default to None
    path = CASES_DIR / "eu" / "eu_google_fitbit_2021.yaml"
    case = load_yaml_file(path)
    for market in case.product_markets_considered:
        # verification is Optional; when absent defaults to None
        assert market.verification is None or market.verification.verification_count >= 0


def test_new_outcome_values():
    from app.models import Outcome
    assert Outcome.cleared_with_conditions == "cleared_with_conditions"
    assert Outcome.annulled == "annulled"
    assert Outcome.under_appeal == "under_appeal"
    assert Outcome.upheld_on_appeal == "upheld_on_appeal"
    assert Outcome.unknown == "unknown"
