"""
Unit tests for check_review_readiness.py

No network access, no PDF downloads, no filesystem writes to real data.
All tests use synthetic fixture data.
"""

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from check_review_readiness import (
    check_conclusion_as_sole_support,
    check_duplicate_quotes,
    check_geo_market_coverage,
    check_orphaned_passages,
    check_planned_focus_coverage,
    check_product_geo_balance,
    check_source_role_not_set,
    check_theory_coverage,
    run_checks,
)
from pipeline_profile import load_profile


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _plan(geo_sections=1, theory_sections=1, remedies_sections=0):
    """Build a minimal coverage plan dict."""
    geo = [{"heading": "Geographic market definition", "page_start": 20, "page_end": 22, "section_path": "7 RELEVANT MARKETS > 7.1.3 Geographic market definition"}] * geo_sections
    theory = [{"heading": "Competitive Assessment", "page_start": 34, "page_end": 60, "section_path": "8 COMPETITIVE ASSESSMENT"}] * theory_sections
    remedies = [{"heading": "Commitments", "page_start": 70, "page_end": 75, "section_path": "XVI COMMITMENTS"}] * remedies_sections
    return {
        "case_id": "test_case",
        "sections_planned": {
            "market_definition": [{"heading": "Market Definition", "page_start": 16, "page_end": 33, "section_path": "7 RELEVANT MARKETS"}],
            "geographic_market": geo,
            "theories": theory,
            "remedies": remedies,
        },
    }


def _passage(pid, quote, role="commission_assessment", supports_markets=None, supports_geo=None, supports_theories=None):
    return {
        "passage_id": pid,
        "quote_snippet": quote,
        "source_role": role,
        "supports_markets": supports_markets or [],
        "supports_geographic_markets": supports_geo or [],
        "supports_theories": supports_theories or [],
        "supports_commitments": [],
    }


def _draft(product_markets=None, geo_markets=None, theories=None, passages=None):
    return {
        "case_id": "test_case",
        "product_markets_considered": product_markets or [],
        "geographic_markets_considered": geo_markets or [],
        "theories_of_harm": theories or [],
        "source_passages": passages or [],
    }


def _product_market(mid="pm_1"):
    return {"market_id": mid, "name": f"Market {mid}", "definition_status": "defined"}


def _geo_market(mid="gm_1"):
    return {"market_id": mid, "name": f"Geo Market {mid}", "definition_status": "defined"}


def _theory(tid="toh_1", supporting=None):
    return {"toh_id": tid, "name": "Horizontal effects", "theory_type": "horizontal", "supporting_passages": supporting or []}


# ---------------------------------------------------------------------------
# check_geo_market_coverage
# ---------------------------------------------------------------------------


class TestGeoMarketCoverage:

    def test_missing_geo_markets_with_planned_sections_is_error(self):
        draft = _draft(product_markets=[_product_market()])
        issues = check_geo_market_coverage(draft, _plan(geo_sections=1))
        assert len(issues) == 1
        assert issues[0]["level"] == "error"
        assert issues[0]["code"] == "missing_geo_markets"

    def test_geo_markets_present_is_clean(self):
        draft = _draft(geo_markets=[_geo_market()])
        issues = check_geo_market_coverage(draft, _plan(geo_sections=1))
        assert issues == []

    def test_no_plan_skips_check(self):
        draft = _draft(product_markets=[_product_market()])
        issues = check_geo_market_coverage(draft, None)
        assert issues == []

    def test_no_planned_geo_sections_skips_check(self):
        draft = _draft(product_markets=[_product_market()])
        issues = check_geo_market_coverage(draft, _plan(geo_sections=0))
        assert issues == []


# ---------------------------------------------------------------------------
# check_theory_coverage
# ---------------------------------------------------------------------------


class TestTheoryCoverage:

    def test_missing_theories_with_planned_sections_is_error(self):
        draft = _draft()
        issues = check_theory_coverage(draft, _plan(theory_sections=1))
        assert len(issues) == 1
        assert issues[0]["level"] == "error"
        assert issues[0]["code"] == "missing_theory_of_harm"

    def test_theories_present_is_clean(self):
        draft = _draft(theories=[_theory()])
        issues = check_theory_coverage(draft, _plan(theory_sections=1))
        assert issues == []

    def test_no_plan_skips_check(self):
        draft = _draft()
        issues = check_theory_coverage(draft, None)
        assert issues == []

    def test_no_planned_theory_sections_skips_check(self):
        draft = _draft()
        issues = check_theory_coverage(draft, _plan(theory_sections=0))
        assert issues == []


# ---------------------------------------------------------------------------
# check_source_role_not_set
# ---------------------------------------------------------------------------


class TestSourceRoleNotSet:

    def test_not_set_role_is_error(self):
        p = _passage("sp_1", "some text", role="not_set")
        draft = _draft(passages=[p])
        issues = check_source_role_not_set(draft)
        assert len(issues) == 1
        assert issues[0]["level"] == "error"
        assert issues[0]["code"] == "source_role_not_set"
        assert "sp_1" in issues[0]["passage_ids"]

    def test_none_role_is_error(self):
        p = _passage("sp_1", "some text", role=None)
        draft = _draft(passages=[p])
        issues = check_source_role_not_set(draft)
        assert len(issues) == 1

    def test_valid_role_is_clean(self):
        p = _passage("sp_1", "some text", role="commission_assessment")
        draft = _draft(passages=[p])
        issues = check_source_role_not_set(draft)
        assert issues == []

    def test_multiple_not_set_combined_into_one_issue(self):
        passages = [
            _passage("sp_1", "text one", role="not_set"),
            _passage("sp_2", "text two", role="not_set"),
            _passage("sp_3", "text three", role="commission_assessment"),
        ]
        draft = _draft(passages=passages)
        issues = check_source_role_not_set(draft)
        assert len(issues) == 1
        assert set(issues[0]["passage_ids"]) == {"sp_1", "sp_2"}


# ---------------------------------------------------------------------------
# check_duplicate_quotes
# ---------------------------------------------------------------------------


class TestDuplicateQuotes:

    def test_duplicate_snippet_is_error(self):
        snippet = "The Commission considers the market is worldwide."
        passages = [
            _passage("sp_1", snippet),
            _passage("sp_2", snippet),
        ]
        draft = _draft(passages=passages)
        issues = check_duplicate_quotes(draft)
        assert len(issues) == 1
        assert issues[0]["level"] == "error"
        assert issues[0]["code"] == "duplicate_quote_snippet"
        assert set(issues[0]["passage_ids"]) == {"sp_1", "sp_2"}

    def test_unique_snippets_is_clean(self):
        passages = [
            _passage("sp_1", "The market is global."),
            _passage("sp_2", "The parties overlap in IFC services."),
        ]
        draft = _draft(passages=passages)
        issues = check_duplicate_quotes(draft)
        assert issues == []

    def test_empty_snippets_not_flagged(self):
        passages = [
            _passage("sp_1", ""),
            _passage("sp_2", ""),
        ]
        draft = _draft(passages=passages)
        issues = check_duplicate_quotes(draft)
        assert issues == []

    def test_three_duplicates_in_one_issue(self):
        snippet = "Relevant product market is satellite capacity."
        passages = [
            _passage("sp_1", snippet),
            _passage("sp_2", snippet),
            _passage("sp_3", snippet),
        ]
        draft = _draft(passages=passages)
        issues = check_duplicate_quotes(draft)
        assert len(issues) == 1
        assert len(issues[0]["passage_ids"]) == 3


# ---------------------------------------------------------------------------
# check_product_geo_balance
# ---------------------------------------------------------------------------


class TestProductGeoBalance:

    def test_products_without_geo_where_planned_is_warning(self):
        draft = _draft(product_markets=[_product_market()])
        issues = check_product_geo_balance(draft, _plan(geo_sections=1))
        assert len(issues) == 1
        assert issues[0]["level"] == "warning"
        assert issues[0]["code"] == "product_markets_without_geo"

    def test_products_with_geo_is_clean(self):
        draft = _draft(product_markets=[_product_market()], geo_markets=[_geo_market()])
        issues = check_product_geo_balance(draft, _plan(geo_sections=1))
        assert issues == []

    def test_no_geo_plan_no_warning(self):
        draft = _draft(product_markets=[_product_market()])
        issues = check_product_geo_balance(draft, _plan(geo_sections=0))
        assert issues == []

    def test_no_products_no_warning(self):
        draft = _draft()
        issues = check_product_geo_balance(draft, _plan(geo_sections=1))
        assert issues == []


# ---------------------------------------------------------------------------
# check_orphaned_passages
# ---------------------------------------------------------------------------


class TestOrphanedPassages:

    def test_unlinked_passage_is_warning(self):
        p = _passage("sp_1", "Some text", role="commission_assessment")
        draft = _draft(passages=[p])
        issues = check_orphaned_passages(draft)
        assert len(issues) == 1
        assert issues[0]["level"] == "warning"
        assert issues[0]["code"] == "orphaned_passages"
        assert "sp_1" in issues[0]["passage_ids"]

    def test_linked_passage_is_clean(self):
        p = _passage("sp_1", "Some text", role="commission_assessment", supports_markets=["pm_1"])
        draft = _draft(passages=[p])
        issues = check_orphaned_passages(draft)
        assert issues == []

    def test_geo_linked_is_clean(self):
        p = _passage("sp_1", "Some text", role="commission_assessment", supports_geo=["gm_1"])
        draft = _draft(passages=[p])
        issues = check_orphaned_passages(draft)
        assert issues == []

    def test_theory_linked_is_clean(self):
        p = _passage("sp_1", "Some text", role="commission_assessment", supports_theories=["toh_1"])
        draft = _draft(passages=[p])
        issues = check_orphaned_passages(draft)
        assert issues == []

    def test_conclusion_orphan_suppressed_by_us_court_profile(self):
        """US court opinion profile allows conclusion and background to be unlinked."""
        us_profile = load_profile("us_court_opinion")
        p = _passage("sp_1", "Court grants FTC's motion for a preliminary injunction.", role="conclusion")
        draft = _draft(passages=[p])
        issues = check_orphaned_passages(draft, profile=us_profile)
        assert issues == []

    def test_background_orphan_suppressed_by_us_court_profile(self):
        us_profile = load_profile("us_court_opinion")
        p = _passage("sp_1", "Tapestry and Capri are both luxury goods companies.", role="background")
        draft = _draft(passages=[p])
        issues = check_orphaned_passages(draft, profile=us_profile)
        assert issues == []

    def test_commission_assessment_orphan_still_warned_with_us_profile(self):
        """commission_assessment passages are never in the allow-list."""
        us_profile = load_profile("us_court_opinion")
        p = _passage("sp_1", "The court finds HHI exceeds 2500.", role="commission_assessment")
        draft = _draft(passages=[p])
        issues = check_orphaned_passages(draft, profile=us_profile)
        assert len(issues) == 1
        assert issues[0]["code"] == "orphaned_passages"

    def test_ec_profile_conclusion_orphan_is_warned(self):
        """EC profile does not allow any orphan roles."""
        ec_profile = load_profile("ec_decision")
        p = _passage("sp_1", "Commission clears the transaction.", role="conclusion")
        draft = _draft(passages=[p])
        issues = check_orphaned_passages(draft, profile=ec_profile)
        assert len(issues) == 1


# ---------------------------------------------------------------------------
# check_conclusion_as_sole_support
# ---------------------------------------------------------------------------


class TestConclusionAsSoleSupport:

    def test_conclusion_only_support_is_warning(self):
        theory = _theory("toh_1")
        passage = _passage("sp_1", "Commission concludes no SIEC.", role="conclusion", supports_theories=["toh_1"])
        draft = _draft(theories=[theory], passages=[passage])
        issues = check_conclusion_as_sole_support(draft)
        assert len(issues) == 1
        assert issues[0]["level"] == "warning"
        assert issues[0]["code"] == "conclusion_only_support"

    def test_mixed_roles_is_clean(self):
        theory = _theory("toh_1")
        p1 = _passage("sp_1", "Commission assessment text.", role="commission_assessment", supports_theories=["toh_1"])
        p2 = _passage("sp_2", "Commission concludes.", role="conclusion", supports_theories=["toh_1"])
        draft = _draft(theories=[theory], passages=[p1, p2])
        issues = check_conclusion_as_sole_support(draft)
        assert issues == []

    def test_no_supporting_passages_no_issue(self):
        theory = _theory("toh_1")
        draft = _draft(theories=[theory], passages=[])
        issues = check_conclusion_as_sole_support(draft)
        assert issues == []


# ---------------------------------------------------------------------------
# check_planned_focus_coverage
# ---------------------------------------------------------------------------


class TestPlannedFocusCoverage:

    def test_missing_theories_draft_is_warning(self, tmp_path):
        # draft_paths only contain market_definition drafts
        fake_draft_path = tmp_path / "eu_test_case.market_definition.draft.yaml"
        fake_draft_path.write_text("case_id: test_case\n")
        draft = _draft()
        plan = _plan(theory_sections=1)
        issues = check_planned_focus_coverage(draft, plan, [fake_draft_path])
        codes = [i["code"] for i in issues]
        assert "planned_section_not_extracted" in codes

    def test_matching_drafts_present_is_clean(self, tmp_path):
        md_path = tmp_path / "eu_test_case.market_definition.draft.yaml"
        th_path = tmp_path / "eu_test_case.theories.draft.yaml"
        md_path.write_text("case_id: test_case\n")
        th_path.write_text("case_id: test_case\n")
        draft = _draft()
        plan = _plan(theory_sections=1, geo_sections=1, remedies_sections=0)
        issues = check_planned_focus_coverage(draft, plan, [md_path, th_path])
        foci_issues = [i for i in issues if i["code"] == "planned_section_not_extracted"]
        # market_definition and geographic_market both map to focus "market_definition" which is present
        # theories maps to "theories" which is present
        assert foci_issues == []


# ---------------------------------------------------------------------------
# run_checks — integration: clean small case passes
# ---------------------------------------------------------------------------


class TestRunChecks:

    def test_clean_case_passes(self, tmp_path):
        """A well-formed draft with all required fields produces no issues."""
        passage = _passage(
            "sp_1",
            "The market for satellite capacity is worldwide.",
            role="commission_assessment",
            supports_markets=["pm_1"],
            supports_geo=["gm_1"],
        )
        draft = _draft(
            product_markets=[_product_market("pm_1")],
            geo_markets=[_geo_market("gm_1")],
            theories=[_theory("toh_1")],
            passages=[passage],
        )
        plan = _plan(geo_sections=1, theory_sections=1)
        # Give theory a supporting non-conclusion passage
        draft["source_passages"].append(
            _passage("sp_2", "Competitive effects text.", role="commission_assessment", supports_theories=["toh_1"])
        )
        # Paths: both market_definition and theories drafts present
        md_path = tmp_path / "eu_test_case.market_definition.draft.yaml"
        th_path = tmp_path / "eu_test_case.theories.draft.yaml"
        md_path.write_text("case_id: test_case\n")
        th_path.write_text("case_id: test_case\n")

        issues = run_checks(draft, plan, [md_path, th_path])
        errors = [i for i in issues if i["level"] == "error"]
        assert errors == [], f"Expected no errors, got: {errors}"

    def test_viasat_style_failures_all_flagged(self, tmp_path):
        """
        Simulates the Viasat failure pattern:
        - geographic sections planned, but zero geo markets extracted
        - theory sections planned, but zero theories extracted
        - a source_role: not_set passage
        - a duplicate quote snippet
        """
        snippet = "The Commission considers the relevant market is worldwide."
        passages = [
            _passage("sp_1", snippet, role="not_set"),
            _passage("sp_2", snippet, role="commission_assessment"),
        ]
        draft = _draft(
            product_markets=[_product_market("pm_1")],
            geo_markets=[],
            theories=[],
            passages=passages,
        )
        plan = _plan(geo_sections=1, theory_sections=1)
        md_path = tmp_path / "eu_test_case.market_definition.draft.yaml"
        md_path.write_text("case_id: test_case\n")

        issues = run_checks(draft, plan, [md_path])
        codes = {i["code"] for i in issues}
        assert "missing_geo_markets" in codes
        assert "missing_theory_of_harm" in codes
        assert "source_role_not_set" in codes
        assert "duplicate_quote_snippet" in codes

    def test_clean_us_style_packet_passes(self, tmp_path):
        """
        Simulates a clean US court-opinion draft:
        - geo markets present
        - theories present (with non-conclusion support)
        - all source_roles assigned
        - no duplicates
        - conclusion + background passages allowed to be unlinked (US profile)
        """
        us_profile = load_profile("us_court_opinion")

        conclusion_passage = _passage("sp_c", "Court grants preliminary injunction.", role="conclusion")
        background_passage = _passage("sp_b", "Tapestry acquired Coach in 2019.", role="background")
        market_passage = _passage(
            "sp_1", "The relevant market is the market for affordable luxury handbags.",
            role="commission_assessment", supports_markets=["pm_1"], supports_geo=["gm_1"]
        )
        theory_passage = _passage(
            "sp_2", "HHI post-merger exceeds 2500, creating a structural presumption.",
            role="commission_assessment", supports_theories=["toh_1"]
        )

        draft = _draft(
            product_markets=[_product_market("pm_1")],
            geo_markets=[_geo_market("gm_1")],
            theories=[_theory("toh_1")],
            passages=[conclusion_passage, background_passage, market_passage, theory_passage],
        )
        plan = _plan(geo_sections=1, theory_sections=1, remedies_sections=0)

        md_path = tmp_path / "us_test_case.market_definition.draft.yaml"
        th_path = tmp_path / "us_test_case.theories.draft.yaml"
        md_path.write_text("case_id: test_case\n")
        th_path.write_text("case_id: test_case\n")

        issues = run_checks(draft, plan, [md_path, th_path], profile=us_profile)
        errors = [i for i in issues if i["level"] == "error"]
        assert errors == [], f"Expected no errors with US profile, got: {errors}"
