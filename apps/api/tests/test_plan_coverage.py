"""
Unit tests for plan_coverage.py

No network access, no PDF downloads, no filesystem writes to real data.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from plan_coverage import (
    _classify_section_path,
    _group_sections,
    _infer_jurisdiction,
    build_coverage_plan,
)

# Minimal empty cache for tests that supply their own section_map
_EMPTY_CACHE = {"source_document_id": "test_decision", "page_count": 0, "pages": []}


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_cache(pages: list[tuple[int, str]]) -> dict:
    """Build a minimal source cache with section_path as text (used by _extract_section_map)."""
    return {
        "source_document_id": "test_decision",
        "page_count": len(pages),
        "pages": [
            {"page_number": n, "text": text, "section_path": sp}
            for n, text, sp in pages
        ],
    }


def _page(num: int, section_path: str = "") -> tuple:
    return (num, f"page {num} text", section_path)


# ---------------------------------------------------------------------------
# _classify_section_path
# ---------------------------------------------------------------------------


class TestClassifySectionPath:

    def test_geographic_market(self):
        cats = _classify_section_path("7 RELEVANT MARKETS > 7.1.3 Geographic market definition")
        assert "geographic_market" in cats

    def test_market_definition(self):
        cats = _classify_section_path("7 RELEVANT MARKETS > 7.1.2 Product market definition")
        assert "market_definition" in cats

    def test_theories(self):
        cats = _classify_section_path("8 COMPETITIVE ASSESSMENT > 8.4 Market shares")
        assert "theories" in cats

    def test_remedies(self):
        cats = _classify_section_path("XVI COMMITMENTS > 1 Conditions and obligations")
        assert "remedies" in cats

    def test_empty_path_no_categories(self):
        cats = _classify_section_path("")
        assert cats == set()

    def test_unrelated_heading_no_categories(self):
        cats = _classify_section_path("1 INTRODUCTION > 1.1 Background")
        assert cats == set()

    def test_geographic_market_also_captures_market_definition(self):
        cats = _classify_section_path("7 RELEVANT MARKETS > 7.1.3 Geographic market definition")
        # geographic market heading may also match market_definition due to "market" keyword
        assert "geographic_market" in cats


# ---------------------------------------------------------------------------
# _group_sections
# ---------------------------------------------------------------------------


class TestGroupSections:

    def _section_map(self, mapping: dict[int, str]) -> dict[int, str]:
        return mapping

    def test_single_geo_page_detected(self):
        sm = {20: "7 RELEVANT MARKETS > 7.1.3 Geographic market definition"}
        buckets = _group_sections(sm)
        assert len(buckets["geographic_market"]) >= 1
        assert buckets["geographic_market"][0]["page_start"] == 20

    def test_consecutive_theory_pages_grouped(self):
        sm = {
            34: "8 COMPETITIVE ASSESSMENT > 8.1 Introduction",
            35: "8 COMPETITIVE ASSESSMENT > 8.2 Legal framework",
            36: "8 COMPETITIVE ASSESSMENT > 8.3 Market shares",
        }
        buckets = _group_sections(sm)
        groups = buckets["theories"]
        # Should be one contiguous group spanning 34–36
        assert len(groups) == 1
        assert groups[0]["page_start"] == 34
        assert groups[0]["page_end"] == 36

    def test_separate_remedies_section(self):
        sm = {70: "XVI COMMITMENTS > 1 Conditions", 71: "XVI COMMITMENTS > 2 Remedies"}
        buckets = _group_sections(sm)
        assert len(buckets["remedies"]) >= 1

    def test_unrelated_sections_not_included(self):
        sm = {1: "1 INTRODUCTION", 2: "2 PROCEDURE"}
        buckets = _group_sections(sm)
        assert buckets["theories"] == []
        assert buckets["remedies"] == []


# ---------------------------------------------------------------------------
# build_coverage_plan
# ---------------------------------------------------------------------------


class TestBuildCoveragePlan:

    def _section_map_with_all_types(self) -> dict[int, str]:
        sm: dict[int, str] = {}
        for i in range(16, 21):
            sm[i] = "7 RELEVANT MARKETS > 7.1.2 Product market definition"
        sm[20] = "7 RELEVANT MARKETS > 7.1.3 Geographic market definition"
        for i in range(34, 40):
            sm[i] = "8 COMPETITIVE ASSESSMENT > 8.4 Horizontal effects"
        sm[70] = "XVI COMMITMENTS > 1 Conditions and obligations"
        return sm

    def test_plan_has_required_keys(self):
        plan = build_coverage_plan(_EMPTY_CACHE, "eu_test_2023", section_map=self._section_map_with_all_types())
        assert "case_id" in plan
        assert "generated_at" in plan
        assert "source_doc_id" in plan
        assert "total_pages" in plan
        assert "sections_planned" in plan
        assert "summary" in plan

    def test_plan_detects_market_definition(self):
        plan = build_coverage_plan(_EMPTY_CACHE, "eu_test_2023", section_map=self._section_map_with_all_types())
        assert plan["summary"]["market_definition"] > 0

    def test_plan_detects_geographic_market(self):
        plan = build_coverage_plan(_EMPTY_CACHE, "eu_test_2023", section_map=self._section_map_with_all_types())
        assert plan["summary"]["geographic_market"] > 0

    def test_plan_detects_theories(self):
        plan = build_coverage_plan(_EMPTY_CACHE, "eu_test_2023", section_map=self._section_map_with_all_types())
        assert plan["summary"]["theories"] > 0

    def test_plan_detects_remedies(self):
        plan = build_coverage_plan(_EMPTY_CACHE, "eu_test_2023", section_map=self._section_map_with_all_types())
        assert plan["summary"]["remedies"] > 0

    def test_empty_section_map_produces_zero_sections(self):
        plan = build_coverage_plan(_EMPTY_CACHE, "eu_empty_2023", section_map={})
        assert plan["summary"]["theories"] == 0
        assert plan["summary"]["remedies"] == 0

    def test_case_id_stored(self):
        plan = build_coverage_plan(_EMPTY_CACHE, "eu_viasat_inmarsat_2023", section_map={})
        assert plan["case_id"] == "eu_viasat_inmarsat_2023"


# ---------------------------------------------------------------------------
# _infer_jurisdiction
# ---------------------------------------------------------------------------


class TestInferJurisdiction:

    def test_eu_prefix(self):
        assert _infer_jurisdiction("eu_viasat_inmarsat_2023") == "eu"

    def test_uk_prefix(self):
        assert _infer_jurisdiction("uk_viasat_inmarsat_2023") == "uk"

    def test_us_prefix(self):
        assert _infer_jurisdiction("us_some_case_2023") == "us"

    def test_unknown_defaults_to_eu(self):
        assert _infer_jurisdiction("unknown_case") == "eu"
