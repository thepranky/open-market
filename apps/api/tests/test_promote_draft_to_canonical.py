"""
Tests for promote_draft_to_canonical.py.

Covers:
  - Stripping draft-only fields (_draft_note, market_importance, verification,
    source_role)
  - Preserving markets, passages, and theories
  - Using seed metadata (procedure_stage, metadata block)
  - Failing clearly when required fields are missing
  - Default metadata construction when no seed provides it
  - Pydantic validation of the promoted record
  - Dry-run does not write
  - Overwrite safety gate
  - Missing draft → clear error
  - Custom output path
"""

import datetime
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.promote_draft_to_canonical import (
    _DRAFT_MARKET_STRIP,
    _DRAFT_PASSAGE_STRIP,
    _DRAFT_TOP_STRIP,
    _SEED_NONEMPTY_FALLBACK_FIELDS,
    _apply_seed_nonempty_fallbacks,
    _dump_canonical_yaml,
    _strip_draft_fields_inplace,
    build_canonical,
    check_draft_warnings,
    find_canonical,
    find_draft,
    main,
    validate_canonical_dict,
)


# ---------------------------------------------------------------------------
# Fixtures — minimal draft and seed dicts
# ---------------------------------------------------------------------------

TODAY = "2026-06-01"


def _minimal_draft() -> dict:
    return {
        "_draft_note": "DRAFT — do not promote",
        "case_id": "eu_test_case_2020",
        "case_name": "Test Acquirer / Test Target",
        "authority": "European Commission",
        "jurisdiction": "EU",
        "sector": "industrials",
        "outcome": "cleared",
        "decision_date": "2020-01-15",
        "parties": [
            {"name": "Test Acquirer", "role": "acquirer"},
            {"name": "Test Target", "role": "target"},
        ],
        "source_documents": [
            {
                "doc_id": "eu_test_decision",
                "title": "Test Decision",
                "doc_type": "decision",
                "retrieval_status": "direct",
                "published_date": "2020-01-15",
            }
        ],
        "product_markets_considered": [
            {
                "market_id": "pm_1",
                "name": "Widget manufacturing",
                "definition_status": "defined",
                "notes": "The Commission defined the widget market.",
                "verification": {"status": "source_linked"},
                "market_importance": "core_assessed",
            }
        ],
        "geographic_markets_considered": [
            {
                "market_id": "gm_1",
                "name": "Widget manufacturing — EEA",
                "definition_status": "considered",
                "notes": "Considered EEA-wide.",
                "verification": {"status": "source_linked"},
                "market_importance": "core_assessed",
            }
        ],
        "theories_of_harm": [
            {
                "theory_id": "th_1",
                "name": "Horizontal overlap",
                "description": "Both parties active in widgets.",
            }
        ],
        "source_passages": [
            {
                "passage_id": "sp_1",
                "source_document_id": "eu_test_decision",
                "page": "5",
                "source_role": "commission_assessment",
                "quote_snippet": "The Commission defines the widget market.",
                "extraction_method": "pdf_extracted",
                "review_status": "unreviewed",
                "confidence_score": 0.7,
                "last_checked_date": "2026-06-01",
                "supports_markets": ["pm_1"],
                "supports_geographic_markets": [],
                "supports_theories": [],
            }
        ],
    }


def _minimal_seed() -> dict:
    return {
        "case_id": "eu_test_case_2020",
        "case_name": "Test Acquirer / Test Target",
        "authority": "European Commission",
        "authority_reference": "M.9999",
        "jurisdiction": "EU",
        "decision_date": "2020-01-15",
        "case_type": "merger",
        "procedure_stage": "phase1",
        "sector": "industrials",
        "parties": [
            {"name": "Test Acquirer", "role": "acquirer"},
            {"name": "Test Target", "role": "target"},
        ],
        "outcome": "cleared",
        "remedies": [],
        "source_documents": [
            {
                "doc_id": "eu_test_decision",
                "title": "Test Decision",
                "doc_type": "decision",
                "authority_reference": "M.9999",
                "retrieval_status": "direct",
                "published_date": "2020-01-15",
            }
        ],
        "product_markets_considered": [],
        "geographic_markets_considered": [],
        "theories_of_harm": [],
        "source_passages": [],
        "metadata": {
            "extraction_method": "ai_extracted",
            "review_status": "unreviewed",
            "overall_confidence": 0.7,
            "created_date": "2026-05-01",
            "last_updated_date": "2026-05-01",
            "tags": ["industrials", "phase1", "cleared"],
        },
    }


# ---------------------------------------------------------------------------
# Tests — field stripping
# ---------------------------------------------------------------------------

class TestStripDraftFields:

    def test_strips_draft_note(self):
        d = {"_draft_note": "DRAFT", "case_id": "x"}
        _strip_draft_fields_inplace(d)
        assert "_draft_note" not in d

    def test_strips_market_importance_from_product_markets(self):
        d = {
            "product_markets_considered": [
                {"market_id": "pm_1", "name": "Widgets", "market_importance": "core_assessed"}
            ]
        }
        _strip_draft_fields_inplace(d)
        assert "market_importance" not in d["product_markets_considered"][0]

    def test_strips_market_importance_from_geographic_markets(self):
        d = {
            "geographic_markets_considered": [
                {"market_id": "gm_1", "name": "EEA", "market_importance": "core_assessed"}
            ]
        }
        _strip_draft_fields_inplace(d)
        assert "market_importance" not in d["geographic_markets_considered"][0]

    def test_strips_verification_from_markets(self):
        d = {
            "product_markets_considered": [
                {"market_id": "pm_1", "name": "Widgets",
                 "verification": {"status": "source_linked"}}
            ]
        }
        _strip_draft_fields_inplace(d)
        assert "verification" not in d["product_markets_considered"][0]

    def test_strips_source_role_from_passages(self):
        d = {
            "source_passages": [
                {"passage_id": "sp_1", "source_role": "commission_assessment",
                 "quote_snippet": "..."}
            ]
        }
        _strip_draft_fields_inplace(d)
        assert "source_role" not in d["source_passages"][0]

    def test_preserves_unrelated_market_fields(self):
        d = {
            "product_markets_considered": [
                {"market_id": "pm_1", "name": "Widgets",
                 "definition_status": "defined", "notes": "defined here",
                 "market_importance": "core_assessed"}
            ]
        }
        _strip_draft_fields_inplace(d)
        pm = d["product_markets_considered"][0]
        assert pm["market_id"] == "pm_1"
        assert pm["definition_status"] == "defined"
        assert pm["notes"] == "defined here"

    def test_no_error_on_empty_lists(self):
        d = {"product_markets_considered": [], "source_passages": []}
        _strip_draft_fields_inplace(d)  # should not raise

    def test_no_error_on_missing_lists(self):
        d = {"case_id": "x"}
        _strip_draft_fields_inplace(d)  # should not raise


# ---------------------------------------------------------------------------
# Tests — build_canonical
# ---------------------------------------------------------------------------

class TestBuildCanonical:

    def test_preserves_markets(self):
        draft = _minimal_draft()
        seed = _minimal_seed()
        result = build_canonical(draft, seed, procedure_stage_override=None, today=TODAY)
        assert len(result["product_markets_considered"]) == 1
        assert result["product_markets_considered"][0]["name"] == "Widget manufacturing"

    def test_preserves_geographic_markets(self):
        draft = _minimal_draft()
        seed = _minimal_seed()
        result = build_canonical(draft, seed, procedure_stage_override=None, today=TODAY)
        assert len(result["geographic_markets_considered"]) == 1
        assert result["geographic_markets_considered"][0]["name"] == "Widget manufacturing — EEA"

    def test_preserves_theories(self):
        draft = _minimal_draft()
        seed = _minimal_seed()
        result = build_canonical(draft, seed, procedure_stage_override=None, today=TODAY)
        assert len(result["theories_of_harm"]) == 1
        assert result["theories_of_harm"][0]["theory_id"] == "th_1"

    def test_preserves_passages(self):
        draft = _minimal_draft()
        seed = _minimal_seed()
        result = build_canonical(draft, seed, procedure_stage_override=None, today=TODAY)
        assert len(result["source_passages"]) == 1
        assert result["source_passages"][0]["passage_id"] == "sp_1"

    def test_uses_seed_procedure_stage(self):
        draft = _minimal_draft()
        seed = _minimal_seed()
        result = build_canonical(draft, seed, procedure_stage_override=None, today=TODAY)
        assert result["procedure_stage"] == "phase1"

    def test_uses_seed_metadata(self):
        draft = _minimal_draft()
        seed = _minimal_seed()
        result = build_canonical(draft, seed, procedure_stage_override=None, today=TODAY)
        assert result["metadata"]["tags"] == ["industrials", "phase1", "cleared"]
        assert result["metadata"]["created_date"] == "2026-05-01"

    def test_cli_procedure_stage_overrides_seed(self):
        draft = _minimal_draft()
        seed = _minimal_seed()
        result = build_canonical(draft, seed, procedure_stage_override="phase2", today=TODAY)
        assert result["procedure_stage"] == "phase2"

    def test_cli_procedure_stage_used_when_no_seed(self):
        draft = _minimal_draft()
        result = build_canonical(draft, None, procedure_stage_override="phase1", today=TODAY)
        assert result["procedure_stage"] == "phase1"

    def test_strips_draft_note(self):
        draft = _minimal_draft()
        seed = _minimal_seed()
        result = build_canonical(draft, seed, procedure_stage_override=None, today=TODAY)
        assert "_draft_note" not in result

    def test_strips_draft_fields_from_markets(self):
        draft = _minimal_draft()
        seed = _minimal_seed()
        result = build_canonical(draft, seed, procedure_stage_override=None, today=TODAY)
        pm = result["product_markets_considered"][0]
        assert "market_importance" not in pm
        assert "verification" not in pm

    def test_strips_source_role_from_passages(self):
        draft = _minimal_draft()
        seed = _minimal_seed()
        result = build_canonical(draft, seed, procedure_stage_override=None, today=TODAY)
        assert "source_role" not in result["source_passages"][0]

    def test_default_metadata_when_no_seed(self):
        draft = _minimal_draft()
        # Remove metadata from draft (it doesn't have it normally, but ensure clean)
        draft.pop("metadata", None)
        result = build_canonical(draft, None, procedure_stage_override="phase1", today=TODAY)
        assert "metadata" in result
        assert result["metadata"]["extraction_method"] == "ai_extracted"
        assert result["metadata"]["review_status"] == "unreviewed"
        assert result["metadata"]["created_date"] == TODAY

    def test_default_metadata_when_seed_lacks_metadata(self):
        draft = _minimal_draft()
        seed = {k: v for k, v in _minimal_seed().items() if k != "metadata"}
        seed.pop("metadata", None)
        result = build_canonical(draft, seed, procedure_stage_override=None, today=TODAY)
        assert result["metadata"]["extraction_method"] == "ai_extracted"

    def test_fails_when_procedure_stage_missing_and_no_seed(self):
        draft = _minimal_draft()
        with pytest.raises(ValueError, match="procedure_stage"):
            build_canonical(draft, None, procedure_stage_override=None, today=TODAY)

    def test_fails_when_procedure_stage_missing_and_seed_lacks_it(self):
        draft = _minimal_draft()
        seed = {k: v for k, v in _minimal_seed().items() if k != "procedure_stage"}
        with pytest.raises(ValueError, match="procedure_stage"):
            build_canonical(draft, seed, procedure_stage_override=None, today=TODAY)

    # ------------------------------------------------------------------
    # theories_of_harm non-regression tests
    # ------------------------------------------------------------------

    def test_seed_theories_preserved_when_draft_omits_field(self):
        """Draft with no theories_of_harm key must not wipe canonical theories."""
        draft = _minimal_draft()
        draft.pop("theories_of_harm", None)

        seed = _minimal_seed()
        seed["theories_of_harm"] = [
            {"theory_id": "th_seed", "name": "Seed theory", "description": "From canonical."}
        ]

        result = build_canonical(draft, seed, procedure_stage_override=None, today=TODAY)
        assert len(result["theories_of_harm"]) == 1
        assert result["theories_of_harm"][0]["theory_id"] == "th_seed"

    def test_seed_theories_preserved_when_draft_has_empty_list(self):
        """Draft with theories_of_harm: [] must not wipe canonical theories."""
        draft = _minimal_draft()
        draft["theories_of_harm"] = []

        seed = _minimal_seed()
        seed["theories_of_harm"] = [
            {"theory_id": "th_seed", "name": "Seed theory", "description": "From canonical."}
        ]

        result = build_canonical(draft, seed, procedure_stage_override=None, today=TODAY)
        assert len(result["theories_of_harm"]) == 1
        assert result["theories_of_harm"][0]["theory_id"] == "th_seed"

    def test_draft_theories_win_when_both_are_non_empty(self):
        """When the draft has its own theories, they take precedence over seed."""
        draft = _minimal_draft()
        # draft already has th_1 from _minimal_draft
        seed = _minimal_seed()
        seed["theories_of_harm"] = [
            {"theory_id": "th_seed", "name": "Seed theory", "description": "From canonical."}
        ]

        result = build_canonical(draft, seed, procedure_stage_override=None, today=TODAY)
        assert len(result["theories_of_harm"]) == 1
        assert result["theories_of_harm"][0]["theory_id"] == "th_1"

    def test_draft_theories_used_when_seed_is_empty(self):
        """When seed theories_of_harm is empty, draft theories are used."""
        draft = _minimal_draft()
        seed = _minimal_seed()
        seed["theories_of_harm"] = []

        result = build_canonical(draft, seed, procedure_stage_override=None, today=TODAY)
        assert len(result["theories_of_harm"]) == 1
        assert result["theories_of_harm"][0]["theory_id"] == "th_1"

    def test_draft_theories_used_when_no_seed(self):
        """Without a seed, draft theories are always used."""
        draft = _minimal_draft()
        result = build_canonical(draft, None, procedure_stage_override="phase1", today=TODAY)
        assert len(result["theories_of_harm"]) == 1
        assert result["theories_of_harm"][0]["theory_id"] == "th_1"


# ---------------------------------------------------------------------------
# Tests — draft quality warnings
# ---------------------------------------------------------------------------

class TestDraftWarnings:

    def _passage(self, passage_id: str, source_role: str) -> dict:
        return {
            "passage_id": passage_id,
            "source_document_id": "doc_1",
            "page": "1",
            "source_role": source_role,
            "quote_snippet": "...",
            "extraction_method": "pdf_extracted",
            "review_status": "unreviewed",
            "confidence_score": 0.7,
            "last_checked_date": TODAY,
            "supports_markets": [],
            "supports_geographic_markets": [],
            "supports_theories": [],
        }

    def test_no_warnings_for_classified_passages(self):
        draft = {"source_passages": [self._passage("sp_1", "commission_assessment")]}
        assert check_draft_warnings(draft) == []

    def test_warns_for_not_set_source_role(self):
        draft = {"source_passages": [self._passage("sp_1", "not_set")]}
        warnings = check_draft_warnings(draft)
        assert len(warnings) == 1
        assert "not_set" in warnings[0]
        assert "sp_1" in warnings[0]

    def test_warns_lists_all_not_set_passages(self):
        draft = {
            "source_passages": [
                self._passage("sp_1", "not_set"),
                self._passage("sp_2", "commission_assessment"),
                self._passage("sp_3", "not_set"),
            ]
        }
        warnings = check_draft_warnings(draft)
        assert len(warnings) == 1
        assert "sp_1" in warnings[0]
        assert "sp_3" in warnings[0]
        assert "sp_2" not in warnings[0]

    def test_no_warnings_for_empty_passages(self):
        assert check_draft_warnings({"source_passages": []}) == []
        assert check_draft_warnings({}) == []

    def test_apply_seed_nonempty_fallbacks_unit(self):
        """Direct unit test for the fallback function."""
        record = {"theories_of_harm": []}
        seed = {"theories_of_harm": [{"theory_id": "th_1", "name": "T"}]}
        _apply_seed_nonempty_fallbacks(record, seed)
        assert record["theories_of_harm"][0]["theory_id"] == "th_1"

    def test_apply_seed_nonempty_fallbacks_no_overwrite_when_draft_has_content(self):
        draft_theories = [{"theory_id": "th_draft", "name": "Draft T"}]
        record = {"theories_of_harm": draft_theories}
        seed = {"theories_of_harm": [{"theory_id": "th_seed", "name": "Seed T"}]}
        _apply_seed_nonempty_fallbacks(record, seed)
        assert record["theories_of_harm"][0]["theory_id"] == "th_draft"

    def test_seed_nonempty_fallback_fields_contains_theories_of_harm(self):
        assert "theories_of_harm" in _SEED_NONEMPTY_FALLBACK_FIELDS


# ---------------------------------------------------------------------------
# Tests — Pydantic validation
# ---------------------------------------------------------------------------

class TestPydanticValidation:

    def test_promoted_record_validates(self):
        draft = _minimal_draft()
        seed = _minimal_seed()
        result = build_canonical(draft, seed, procedure_stage_override=None, today=TODAY)
        ok, msg = validate_canonical_dict(result)
        assert ok, f"Validation failed: {msg}"

    def test_record_missing_procedure_stage_fails_validation(self):
        draft = _minimal_draft()
        seed = _minimal_seed()
        result = build_canonical(draft, seed, procedure_stage_override=None, today=TODAY)
        del result["procedure_stage"]
        ok, msg = validate_canonical_dict(result)
        assert not ok
        assert "procedure_stage" in msg

    def test_record_missing_metadata_fails_validation(self):
        draft = _minimal_draft()
        seed = _minimal_seed()
        result = build_canonical(draft, seed, procedure_stage_override=None, today=TODAY)
        del result["metadata"]
        ok, msg = validate_canonical_dict(result)
        assert not ok
        assert "metadata" in msg


# ---------------------------------------------------------------------------
# Tests — CLI integration (using tmp_path)
# ---------------------------------------------------------------------------

class TestCLI:

    def _write_draft(self, tmp_path: Path, draft: dict) -> Path:
        jur = draft.get("jurisdiction", "EU").lower()
        draft_dir = tmp_path / "drafts" / jur
        draft_dir.mkdir(parents=True)
        p = draft_dir / f"{draft['case_id']}.market_definition.draft.yaml"
        p.write_text(yaml.dump(draft, default_flow_style=False, allow_unicode=True))
        return p

    def _write_seed(self, tmp_path: Path, seed: dict) -> Path:
        jur = seed.get("jurisdiction", "EU").lower()
        cases_dir = tmp_path / "cases" / jur
        cases_dir.mkdir(parents=True)
        p = cases_dir / f"{seed['case_id']}.yaml"
        p.write_text(yaml.dump(seed, default_flow_style=False, allow_unicode=True))
        return p

    def test_writes_canonical_yaml(self, tmp_path):
        draft = _minimal_draft()
        seed = _minimal_seed()
        self._write_draft(tmp_path, draft)
        self._write_seed(tmp_path, seed)

        rc = main([
            "--case-id", "eu_test_case_2020",
            "--focus", "market_definition",
            "--overwrite",
            "--drafts-dir", str(tmp_path / "drafts"),
            "--cases-dir", str(tmp_path / "cases"),
        ])
        assert rc == 0
        out = tmp_path / "cases" / "eu" / "eu_test_case_2020.yaml"
        assert out.exists()
        loaded = yaml.safe_load(out.read_text())
        assert loaded["procedure_stage"] == "phase1"
        assert "_draft_note" not in loaded

    def test_dry_run_does_not_write(self, tmp_path):
        draft = _minimal_draft()
        seed = _minimal_seed()
        self._write_draft(tmp_path, draft)
        seed_path = self._write_seed(tmp_path, seed)

        rc = main([
            "--case-id", "eu_test_case_2020",
            "--focus", "market_definition",
            "--dry-run",
            "--drafts-dir", str(tmp_path / "drafts"),
            "--cases-dir", str(tmp_path / "cases"),
        ])
        assert rc == 0
        # Seed file should not have been overwritten with canonical content
        loaded = yaml.safe_load(seed_path.read_text())
        # The seed has empty product_markets; dry-run should not have written
        # the draft's markets into the seed
        assert loaded["product_markets_considered"] == []

    def test_requires_overwrite_when_canonical_exists(self, tmp_path):
        draft = _minimal_draft()
        seed = _minimal_seed()
        self._write_draft(tmp_path, draft)
        self._write_seed(tmp_path, seed)

        rc = main([
            "--case-id", "eu_test_case_2020",
            "--focus", "market_definition",
            # --overwrite NOT passed
            "--drafts-dir", str(tmp_path / "drafts"),
            "--cases-dir", str(tmp_path / "cases"),
        ])
        assert rc == 1

    def test_fails_when_draft_missing(self, tmp_path):
        seed = _minimal_seed()
        self._write_seed(tmp_path, seed)
        # No draft file written

        rc = main([
            "--case-id", "eu_test_case_2020",
            "--focus", "market_definition",
            "--drafts-dir", str(tmp_path / "drafts"),
            "--cases-dir", str(tmp_path / "cases"),
        ])
        assert rc == 1

    def test_custom_output_path(self, tmp_path):
        draft = _minimal_draft()
        seed = _minimal_seed()
        self._write_draft(tmp_path, draft)
        self._write_seed(tmp_path, seed)
        custom_out = tmp_path / "custom_output.yaml"

        rc = main([
            "--case-id", "eu_test_case_2020",
            "--focus", "market_definition",
            "--output", str(custom_out),
            "--drafts-dir", str(tmp_path / "drafts"),
            "--cases-dir", str(tmp_path / "cases"),
        ])
        assert rc == 0
        assert custom_out.exists()
        loaded = yaml.safe_load(custom_out.read_text())
        assert loaded["case_id"] == "eu_test_case_2020"

    def test_procedure_stage_from_cli(self, tmp_path):
        draft = _minimal_draft()
        # seed without procedure_stage
        seed = {k: v for k, v in _minimal_seed().items() if k != "procedure_stage"}
        self._write_draft(tmp_path, draft)
        self._write_seed(tmp_path, seed)
        out = tmp_path / "out.yaml"

        rc = main([
            "--case-id", "eu_test_case_2020",
            "--focus", "market_definition",
            "--procedure-stage", "phase2",
            "--output", str(out),
            "--drafts-dir", str(tmp_path / "drafts"),
            "--cases-dir", str(tmp_path / "cases"),
        ])
        assert rc == 0
        loaded = yaml.safe_load(out.read_text())
        assert loaded["procedure_stage"] == "phase2"

    def test_fails_when_procedure_stage_missing_everywhere(self, tmp_path):
        draft = _minimal_draft()
        seed = {k: v for k, v in _minimal_seed().items() if k != "procedure_stage"}
        self._write_draft(tmp_path, draft)
        self._write_seed(tmp_path, seed)

        rc = main([
            "--case-id", "eu_test_case_2020",
            "--focus", "market_definition",
            "--overwrite",
            "--drafts-dir", str(tmp_path / "drafts"),
            "--cases-dir", str(tmp_path / "cases"),
        ])
        assert rc == 1

    def test_no_overwrite_flag_needed_for_new_canonical(self, tmp_path):
        """If no canonical exists yet, promotion should succeed without --overwrite."""
        draft = _minimal_draft()
        # Draft exists but no seed/canonical
        self._write_draft(tmp_path, draft)
        (tmp_path / "cases" / "eu").mkdir(parents=True)
        out = tmp_path / "cases" / "eu" / "eu_test_case_2020.yaml"
        # File does not exist — no --overwrite needed

        rc = main([
            "--case-id", "eu_test_case_2020",
            "--focus", "market_definition",
            "--procedure-stage", "phase1",
            "--drafts-dir", str(tmp_path / "drafts"),
            "--cases-dir", str(tmp_path / "cases"),
        ])
        assert rc == 0
        assert out.exists()

    def test_not_set_source_role_warns_but_does_not_block(self, tmp_path, capsys):
        """Passages with source_role=not_set emit a warning but promotion succeeds."""
        draft = _minimal_draft()
        # Replace passage with a not_set source_role
        draft["source_passages"][0]["source_role"] = "not_set"

        seed = _minimal_seed()
        self._write_draft(tmp_path, draft)
        self._write_seed(tmp_path, seed)
        out = tmp_path / "out.yaml"

        rc = main([
            "--case-id", "eu_test_case_2020",
            "--focus", "market_definition",
            "--output", str(out),
            "--drafts-dir", str(tmp_path / "drafts"),
            "--cases-dir", str(tmp_path / "cases"),
        ])
        assert rc == 0, "Promotion should succeed despite not_set source_role"
        captured = capsys.readouterr()
        assert "not_set" in captured.err
        assert "sp_1" in captured.err

    def test_seed_theories_not_wiped_via_cli(self, tmp_path):
        """CLI: draft with empty theories_of_harm must not wipe canonical theories."""
        draft = _minimal_draft()
        draft["theories_of_harm"] = []

        seed = _minimal_seed()
        seed["theories_of_harm"] = [
            {"theory_id": "th_seed", "name": "Seed theory", "description": "From canonical."}
        ]
        self._write_draft(tmp_path, draft)
        self._write_seed(tmp_path, seed)
        out = tmp_path / "out.yaml"

        rc = main([
            "--case-id", "eu_test_case_2020",
            "--focus", "market_definition",
            "--output", str(out),
            "--drafts-dir", str(tmp_path / "drafts"),
            "--cases-dir", str(tmp_path / "cases"),
        ])
        assert rc == 0
        loaded = yaml.safe_load(out.read_text())
        assert len(loaded["theories_of_harm"]) == 1
        assert loaded["theories_of_harm"][0]["theory_id"] == "th_seed"


# ---------------------------------------------------------------------------
# Tests — YAML output format
# ---------------------------------------------------------------------------

class TestYamlOutput:

    def test_long_notes_use_block_scalar(self):
        long_notes = "A" * 100
        d = {"notes": long_notes}
        out = _dump_canonical_yaml(d)
        assert "|" in out

    def test_short_notes_use_plain_scalar(self):
        short = "Short note."
        d = {"notes": short}
        out = _dump_canonical_yaml(d)
        # Should not be a block scalar for short strings
        assert "|\n" not in out

    def test_date_written_as_string(self):
        d = {"decision_date": datetime.date(2020, 1, 15)}
        out = _dump_canonical_yaml(d)
        assert "2020-01-15" in out
        assert "!!" not in out
