"""
Unit tests for pipeline_profile.py

No network access, no API calls.  Exercises profile loading, inference,
selection, and the coverage-planning integration.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from pipeline_profile import (
    PipelineProfile,
    list_profiles,
    load_profile,
    select_profile,
)
from plan_coverage import _classify_section_path, build_coverage_plan

_EMPTY_CACHE = {"source_document_id": "test_decision", "page_count": 0, "pages": []}


# ---------------------------------------------------------------------------
# load_profile / list_profiles
# ---------------------------------------------------------------------------


class TestLoadProfile:

    def test_load_ec_decision(self):
        p = load_profile("ec_decision")
        assert p.profile_id == "ec_decision"
        assert "eu" in p.jurisdictions

    def test_load_cma_report(self):
        p = load_profile("cma_report")
        assert p.profile_id == "cma_report"
        assert "uk" in p.jurisdictions

    def test_load_us_court_opinion(self):
        p = load_profile("us_court_opinion")
        assert p.profile_id == "us_court_opinion"
        assert "us" in p.jurisdictions

    def test_load_unknown_raises(self):
        with pytest.raises(ValueError, match="not found"):
            load_profile("nonexistent_profile_xyz")

    def test_list_profiles_returns_three(self):
        profiles = list_profiles()
        ids = {p.profile_id for p in profiles}
        assert "ec_decision" in ids
        assert "cma_report" in ids
        assert "us_court_opinion" in ids


# ---------------------------------------------------------------------------
# select_profile — explicit override
# ---------------------------------------------------------------------------


class TestSelectProfileExplicit:

    def test_explicit_ec_decision(self):
        p = select_profile("any_case_id", profile_id="ec_decision")
        assert p.profile_id == "ec_decision"

    def test_explicit_cma_report(self):
        p = select_profile("eu_case_2023", profile_id="cma_report")
        # explicit override beats prefix inference
        assert p.profile_id == "cma_report"

    def test_explicit_us_court_opinion(self):
        p = select_profile("eu_case_2023", profile_id="us_court_opinion")
        assert p.profile_id == "us_court_opinion"

    def test_explicit_invalid_raises(self):
        with pytest.raises(ValueError):
            select_profile("eu_case_2023", profile_id="bogus_profile")


# ---------------------------------------------------------------------------
# select_profile — inference from case_id prefix
# ---------------------------------------------------------------------------


class TestSelectProfileInference:

    def test_eu_prefix_infers_ec_decision(self):
        p = select_profile("eu_viasat_inmarsat_2023")
        assert p.profile_id == "ec_decision"

    def test_uk_prefix_infers_cma_report(self):
        p = select_profile("uk_some_merger_2022")
        assert p.profile_id == "cma_report"

    def test_us_prefix_infers_us_court_opinion(self):
        p = select_profile("us_tapestry_capri_2024")
        assert p.profile_id == "us_court_opinion"

    def test_unknown_prefix_raises(self):
        with pytest.raises(ValueError, match="Cannot infer"):
            select_profile("xx_unknown_case")


# ---------------------------------------------------------------------------
# select_profile — inference from case_meta
# ---------------------------------------------------------------------------


class TestSelectProfileFromMeta:

    def test_meta_jurisdiction_eu(self):
        p = select_profile("any_case", case_meta={"jurisdiction": "EU"})
        assert p.profile_id == "ec_decision"

    def test_meta_jurisdiction_uk(self):
        p = select_profile("any_case", case_meta={"jurisdiction": "UK"})
        assert p.profile_id == "cma_report"

    def test_meta_jurisdiction_us(self):
        p = select_profile("any_case", case_meta={"jurisdiction": "US"})
        assert p.profile_id == "us_court_opinion"

    def test_meta_overrides_prefix_inference(self):
        # case_id has eu_ prefix but meta says UK → meta wins
        p = select_profile("eu_case_2023", case_meta={"jurisdiction": "UK"})
        assert p.profile_id == "cma_report"


# ---------------------------------------------------------------------------
# Coverage keyword integration — US court theories headings
# ---------------------------------------------------------------------------


class TestUSCourtTheoryCoverage:
    """US court opinions use headings not present in EC/CMA vocabulary."""

    def _us_profile(self) -> PipelineProfile:
        return load_profile("us_court_opinion")

    def test_market_share_and_concentration_detected(self):
        cats = _classify_section_path(
            "IV. MERITS > B. Market Share and Concentration", profile=self._us_profile()
        )
        assert "theories" in cats

    def test_hhi_heading_detected(self):
        cats = _classify_section_path(
            "IV. MERITS > C. HHI Analysis", profile=self._us_profile()
        )
        assert "theories" in cats

    def test_pricing_heading_detected(self):
        cats = _classify_section_path(
            "IV. MERITS > D. Pricing", profile=self._us_profile()
        )
        assert "theories" in cats

    def test_final_analysis_heading_detected(self):
        cats = _classify_section_path(
            "IV. MERITS > F. Final Analysis", profile=self._us_profile()
        )
        assert "theories" in cats

    def test_likelihood_of_success_detected(self):
        cats = _classify_section_path(
            "II. LEGAL STANDARD > Likelihood of Success on the Merits", profile=self._us_profile()
        )
        assert "theories" in cats

    def test_preliminary_injunction_detected(self):
        cats = _classify_section_path(
            "I. PRELIMINARY INJUNCTION STANDARD", profile=self._us_profile()
        )
        assert "theories" in cats

    def test_section_7_clayton_act_detected(self):
        cats = _classify_section_path(
            "III. SECTION 7 ANALYSIS > Clayton Act Violation", profile=self._us_profile()
        )
        assert "theories" in cats

    def test_brown_shoe_practical_indicia_market_def(self):
        cats = _classify_section_path(
            "IV. MARKET DEFINITION > Brown Shoe Practical Indicia", profile=self._us_profile()
        )
        assert "market_definition" in cats

    def test_ssnip_test_market_def(self):
        cats = _classify_section_path(
            "IV. MARKET DEFINITION > SSNIP / Hypothetical Monopolist Test",
            profile=self._us_profile(),
        )
        assert "market_definition" in cats

    def test_unrelated_heading_not_detected(self):
        cats = _classify_section_path(
            "I. INTRODUCTION > A. Background",
            profile=self._us_profile(),
        )
        assert "theories" not in cats


# ---------------------------------------------------------------------------
# Coverage plan with US profile detects theory sections
# ---------------------------------------------------------------------------


class TestUSProfileCoveragePlan:

    def _us_profile(self) -> PipelineProfile:
        return load_profile("us_court_opinion")

    def test_us_style_theory_headings_planned(self):
        sm = {
            94: "IV. MERITS > B. Market Share and Concentration",
            95: "IV. MERITS > C. HHI Analysis",
            96: "IV. MERITS > D. Competitive Effects",
            97: "IV. MERITS > E. Pricing",
            98: "IV. MERITS > F. Final Analysis",
        }
        plan = build_coverage_plan(_EMPTY_CACHE, "us_tapestry_capri_2024",
                                   section_map=sm, profile=self._us_profile())
        assert plan["summary"]["theories"] > 0
        assert plan["profile_id"] == "us_court_opinion"

    def test_us_market_def_headings_planned(self):
        sm = {
            50: "III. RELEVANT MARKET > A. Product Market",
            51: "III. RELEVANT MARKET > A.1 Brown Shoe Practical Indicia",
            52: "III. RELEVANT MARKET > B. Geographic Market",
        }
        plan = build_coverage_plan(_EMPTY_CACHE, "us_tapestry_capri_2024",
                                   section_map=sm, profile=self._us_profile())
        assert plan["summary"]["market_definition"] > 0
        assert plan["summary"]["geographic_market"] > 0

    def test_ec_style_headings_still_work_with_ec_profile(self):
        ec_profile = load_profile("ec_decision")
        sm = {
            34: "8 COMPETITIVE ASSESSMENT > 8.1 Introduction",
            35: "8 COMPETITIVE ASSESSMENT > 8.2 Horizontal effects",
        }
        plan = build_coverage_plan(_EMPTY_CACHE, "eu_test_2023",
                                   section_map=sm, profile=ec_profile)
        assert plan["summary"]["theories"] > 0


# ---------------------------------------------------------------------------
# PipelineProfile helpers
# ---------------------------------------------------------------------------


class TestPipelineProfileHelpers:

    def test_keywords_for_returns_lowercase(self):
        p = load_profile("ec_decision")
        kws = p.keywords_for("theories")
        assert all(kw == kw.lower() for kw in kws)
        assert len(kws) > 0

    def test_allowed_orphan_roles_us_court_opinion(self):
        p = load_profile("us_court_opinion")
        roles = p.allowed_orphan_roles()
        assert "conclusion" in roles
        assert "background" in roles

    def test_allowed_orphan_roles_ec_decision_empty(self):
        p = load_profile("ec_decision")
        roles = p.allowed_orphan_roles()
        assert roles == frozenset()

    def test_source_role_prompt_block_contains_mandatory_text(self):
        p = load_profile("us_court_opinion")
        block = p.source_role_prompt_block()
        assert "MANDATORY" in block or "mandatory" in block.lower()
        assert "source_role" in block
        assert "commission_assessment" in block

    def test_source_role_prompt_block_all_roles_present(self):
        p = load_profile("ec_decision")
        block = p.source_role_prompt_block()
        for role in ("commission_assessment", "conclusion", "precedent",
                     "notifying_party_view", "market_investigation", "background"):
            assert role in block
