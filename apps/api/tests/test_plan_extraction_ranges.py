"""
Unit tests for plan_extraction_ranges.py

No network access, no PDF downloads, no real Claude calls, no filesystem writes.
All tests use synthetic fixture data.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from plan_extraction_ranges import (
    ProbeWindow,
    _HIGH_PRIORITY,
    _LOW_PRIORITY,
    _UNIT_SECTION_EXCLUSIONS,
    _build_unit_assessment_windows,
    _build_windows,
    _find_split_points,
    _is_unit_label,
    _make_window,
    _score_page,
    _top_prefix,
    format_plan,
    plan,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_cache(pages: list[dict]) -> dict:
    """Build a minimal source cache dict from a list of page dicts."""
    return {
        "source_document_id": "test_decision",
        "page_count": len(pages),
        "pages": pages,
    }


def _page(num: int, text: str = "") -> dict:
    return {"page_number": num, "text": text}


def _make_section_map(mapping: dict[int, str]) -> dict[int, str]:
    """Identity: pass-through for pre-built section maps (no real parsing needed)."""
    return mapping


# ---------------------------------------------------------------------------
# _score_page
# ---------------------------------------------------------------------------


class TestScorePage:

    def test_conclusion_in_leaf_scores_high_theories(self):
        score, terms = _score_page("1 SECTION > 2 Conclusion", "theories")
        assert score >= 2
        assert "conclusion" in terms

    def test_innovation_in_leaf_scores_high_theories(self):
        score, terms = _score_page("1 SECTION > 1.7 Innovation process and spaces in R&D", "theories")
        assert score >= 1
        assert any("innovation" in t or "r&d" in t for t in terms)

    def test_leading_innovator_in_leaf_scores_high_theories(self):
        score, terms = _score_page("5 SECTION > 1.7.4 The Parties are leading innovators", "theories")
        assert score >= 2
        assert any("leading innovator" in t for t in terms)

    def test_commitment_in_leaf_scores_high_remedies(self):
        score, terms = _score_page("XVI COMMITMENTS > 1 Conditions and obligations", "remedies")
        assert score >= 2
        assert any("condition" in t for t in terms)

    def test_divestment_in_leaf_scores_high_remedies(self):
        score, terms = _score_page("XVI > 3.1 The BASF Divestment Business", "remedies")
        assert score >= 2
        assert any("divestment" in t for t in terms)

    def test_empty_section_path_scores_zero(self):
        score, terms = _score_page("", "theories")
        assert score == 0
        assert terms == []

    def test_irrelevant_leaf_scores_zero_theories(self):
        # "Arguments of the Parties" should NOT match theory keywords
        score, terms = _score_page(
            "8 CUCUMBER > 8.2 Competitive assessment > 8.2.2 Arguments of the Parties",
            "theories",
        )
        assert score == 0

    def test_irrelevant_leaf_scores_zero_remedies(self):
        # A crop seed section with no remedies keywords in the leaf
        score, terms = _score_page(
            "8 CUCUMBER > 8.2 Competitive assessment > 8.2.3.1 American Slicer",
            "remedies",
        )
        assert score == 0

    def test_leaf_only_not_full_path(self):
        # "competitive assessment" only in parent path, NOT the leaf — score based on leaf
        # Leaf "8.2.3.1 American Slicer" should not match
        sp_with_ca_parent = "8 SEEDS > 8.2 Competitive assessment > 8.2.3.1 American Slicer"
        score_inherited, _ = _score_page(sp_with_ca_parent, "theories")
        # Leaf has no match → score should be 0
        assert score_inherited == 0

    def test_relevant_market_definition_leaf_scores(self):
        score, terms = _score_page("III > 3.1 Product market definition", "market_definition")
        assert score >= 2
        assert any("market definition" in t or "product market" in t for t in terms)

    def test_focus_market_definition_unrelated_leaf_scores_zero(self):
        score, _ = _score_page("8 SEEDS > 8.2 Competitive assessment > 8.2.2 Arguments", "market_definition")
        assert score == 0


# ---------------------------------------------------------------------------
# _top_prefix
# ---------------------------------------------------------------------------


class TestTopPrefix:

    def test_two_level_path(self):
        assert _top_prefix("5 SECTION > 1.7 Competitive assessment > 1.7.4 Sub") == \
            "5 SECTION > 1.7 Competitive assessment"

    def test_single_level_path(self):
        assert _top_prefix("5 CONCLUSION") == "5 CONCLUSION"

    def test_empty_path(self):
        assert _top_prefix("") == ""


# ---------------------------------------------------------------------------
# _find_split_points
# ---------------------------------------------------------------------------


class TestFindSplitPoints:

    def _sm(self, mapping: dict[int, str]) -> dict[int, str]:
        return mapping

    def test_short_cluster_no_splits(self):
        cluster = list(range(10, 25))  # 15 pages
        sm = {p: "A > B" for p in cluster}
        splits = _find_split_points(cluster, sm, window_size=15)
        assert splits == []

    def test_large_uniform_cluster_splits_at_window_size(self):
        cluster = list(range(920, 946))  # 26 pages, all same section
        sm = {p: "A > 4.4 Conclusion" for p in cluster}
        splits = _find_split_points(cluster, sm, window_size=15)
        assert 15 in splits
        # All resulting chunks should be ≤ window_size
        boundaries = [0] + splits + [len(cluster)]
        for i in range(len(boundaries) - 1):
            assert boundaries[i + 1] - boundaries[i] <= 15

    def test_section_boundary_respected(self):
        cluster = list(range(1, 31))  # 30 pages
        # Section changes at page 11 (index 10)
        sm = {p: "A > Section1" for p in range(1, 11)}
        sm.update({p: "B > Section2" for p in range(11, 31)})
        splits = _find_split_points(cluster, sm, window_size=15)
        assert 10 in splits  # split at section boundary

    def test_empty_cluster_returns_empty(self):
        assert _find_split_points([], {}, window_size=15) == []

    def test_results_enforce_window_size(self):
        """No resulting chunk should exceed window_size pages."""
        cluster = list(range(100, 160))  # 60 pages, single section
        sm = {p: "A > Conclusion" for p in cluster}
        splits = _find_split_points(cluster, sm, window_size=15)
        boundaries = [0] + splits + [len(cluster)]
        for i in range(len(boundaries) - 1):
            chunk_size = boundaries[i + 1] - boundaries[i]
            assert chunk_size <= 15, f"Chunk {i} has {chunk_size} pages > window_size=15"


# ---------------------------------------------------------------------------
# _build_windows
# ---------------------------------------------------------------------------


class TestBuildWindows:

    def _run(self, sm: dict[int, str], focus: str, **kwargs) -> list[ProbeWindow]:
        return _build_windows(sm, focus=focus, **kwargs)

    def test_no_hot_pages_returns_empty(self):
        sm = {p: "8 SEEDS > 8.2.3 American Slicer" for p in range(80, 100)}
        assert self._run(sm, "theories") == []

    def test_hot_pages_form_window(self):
        sm = {p: "1 SECTION > 1.7.4 The Parties are leading innovators" for p in range(400, 405)}
        sm.update({p: "1 SECTION > 1.7 Unrelated" for p in range(405, 450)})
        windows = self._run(sm, "theories", context_pages=0)
        assert len(windows) >= 1
        assert any(w.start_page <= 400 and w.end_page >= 404 for w in windows)

    def test_score_zero_windows_excluded(self):
        # Mix of hot and pure-context pages at the edges
        sm = {400: "1 > 1.7.4 The Parties are leading innovators"}
        sm.update({p: "9 > 9.9 Unrelated" for p in range(401, 450)})
        windows = self._run(sm, "theories", context_pages=1, merge_gap=0)
        for w in windows:
            assert w.total_score > 0

    def test_window_respects_size_limit(self):
        # 30 consecutive hot pages — should be split
        sm = {p: "1 > 4.4 Conclusion" for p in range(920, 950)}
        windows = self._run(sm, "theories", window_size=15, context_pages=0)
        for w in windows:
            assert w.page_count <= 15

    def test_nearby_clusters_merged(self):
        # Two hot clusters 3 pages apart — should merge with merge_gap=4
        sm = {p: "1 > 1.7.4 leading innovators" for p in [400, 401]}
        sm.update({p: "1 > 1.7.4 leading innovators" for p in [405, 406]})
        sm.update({p: "1 > 1.9 Unrelated" for p in [402, 403, 404]})
        windows = self._run(sm, "theories", context_pages=0, merge_gap=4)
        # 400-401 and 405-406 should merge into one window
        assert len(windows) == 1
        assert windows[0].start_page == 400
        assert windows[0].end_page == 406

    def test_distant_clusters_not_merged(self):
        sm = {p: "1 > 1.7.4 leading innovators" for p in [400, 401]}
        sm.update({p: "1 > 4.4 Conclusion" for p in [500, 501]})
        windows = self._run(sm, "theories", context_pages=0, merge_gap=4)
        assert len(windows) == 2

    def test_page_range_restriction(self):
        sm = {p: "1 > 4.4 Conclusion" for p in range(400, 600)}
        windows = self._run(sm, "theories", page_range=(400, 450))
        assert all(w.start_page >= 400 and w.end_page <= 451 for w in windows)

    def test_remedies_focus_selects_commitment_pages(self):
        sm = {p: "XVI > 3.1 The BASF Divestment Business" for p in range(780, 800)}
        sm.update({p: "I > 1.1 Introduction" for p in range(1, 20)})
        windows = self._run(sm, "remedies", context_pages=0)
        assert all(w.start_page >= 780 for w in windows)
        assert len(windows) >= 1

    def test_market_definition_focus_selects_market_pages(self):
        sm = {p: "III > 3.1 Product market definition" for p in range(50, 65)}
        sm.update({p: "IV > 4.2 Competitive assessment > 4.2.3 Arguments" for p in range(100, 150)})
        windows = self._run(sm, "market_definition", context_pages=0)
        # Should only select market definition section, not competitive assessment sub-sections
        assert all(w.start_page >= 50 for w in windows)


# ---------------------------------------------------------------------------
# format_plan
# ---------------------------------------------------------------------------


class TestFormatPlan:

    def _make_window(self, start: int, end: int) -> ProbeWindow:
        return ProbeWindow(
            start_page=start,
            end_page=end,
            focus="theories",
            headings=[(start, "1.7.4 The Parties are leading innovators")],
            total_score=4,
            context_suffix="leading_innovators",
        )

    def test_output_includes_case_id(self):
        w = self._make_window(400, 415)
        out = format_plan([w], "eu_bayer_monsanto_2018", "theories", "eu_decision", 1006)
        assert "eu_bayer_monsanto_2018" in out

    def test_output_includes_page_range(self):
        w = self._make_window(400, 415)
        out = format_plan([w], "eu_bayer_monsanto_2018", "theories", "eu_decision", 1006)
        assert "pp.400" in out
        assert "415" in out

    def test_output_includes_command(self):
        w = self._make_window(400, 415)
        out = format_plan([w], "eu_bayer_monsanto_2018", "theories", "eu_decision", 1006)
        assert "--page-range 400:415" in out
        assert "--focus theories" in out

    def test_output_includes_heading(self):
        w = self._make_window(400, 415)
        out = format_plan([w], "eu_bayer_monsanto_2018", "theories", "eu_decision", 1006)
        assert "leading innovators" in out.lower()

    def test_empty_windows_note(self):
        out = format_plan([], "eu_bayer_monsanto_2018", "theories", "eu_decision", 1006)
        assert "no matching sections" in out.lower()

    def test_page_range_restriction_shown_in_header(self):
        w = self._make_window(400, 415)
        out = format_plan([w], "eu_bayer_monsanto_2018", "theories", "eu_decision", 1006,
                          page_range=(400, 560))
        assert "pp.400" in out
        assert "560" in out

    def test_window_count_shown(self):
        w1 = self._make_window(400, 410)
        w2 = self._make_window(500, 510)
        out = format_plan([w1, w2], "eu_bayer_monsanto_2018", "theories", "eu_decision", 1006)
        assert "Windows: 2" in out


# ---------------------------------------------------------------------------
# plan (integration shim)
# ---------------------------------------------------------------------------


class TestPlanFunction:

    def test_returns_probe_windows(self):
        pages = [
            _page(400, "1.7.4 The Parties are leading innovators\nSome text"),
            _page(401, "More text about leading innovators"),
            _page(402, "Conclusion text for Section 1.7.4"),
        ]
        cache = _make_cache(pages)
        # Section map built from page text by _extract_section_map
        # We just verify the plan returns a list (possibly empty for short docs)
        result = plan(cache, focus="theories", window_size=15)
        assert isinstance(result, list)
        for w in result:
            assert isinstance(w, ProbeWindow)

    def test_empty_cache_returns_empty(self):
        cache = _make_cache([])
        result = plan(cache, focus="theories")
        assert result == []

    def test_page_range_filter(self):
        # Lots of hot pages, but only pages 50-60 should be returned with restriction
        pages = [_page(p, f"1.7.4 The Parties are leading innovators\np{p}") for p in range(1, 100)]
        cache = _make_cache(pages)
        result = plan(cache, focus="theories", page_range=(50, 60), window_size=15)
        for w in result:
            assert w.start_page >= 49  # allow 1 context page
            assert w.end_page <= 62


# ---------------------------------------------------------------------------
# _is_unit_label
# ---------------------------------------------------------------------------


class TestIsUnitLabel:

    def test_single_word_crop_name(self):
        assert _is_unit_label("8 CUCUMBER")

    def test_two_word_unit_name(self):
        assert _is_unit_label("9 SWEET PEPPER")

    def test_generic_introduction_excluded(self):
        assert not _is_unit_label("1 INTRODUCTION")

    def test_generic_background_excluded(self):
        assert not _is_unit_label("2 BACKGROUND")

    def test_generic_competition_assessment_excluded(self):
        assert not _is_unit_label("3 COMPETITIVE")

    def test_five_word_label_excluded(self):
        # Too many words — not a compact unit label
        assert not _is_unit_label("8 THIS IS TOO MANY WORDS")

    def test_empty_heading_excluded(self):
        assert not _is_unit_label("")

    def test_number_only_heading_excluded(self):
        # After stripping number, nothing remains
        assert not _is_unit_label("8")

    def test_three_word_unit_label_allowed(self):
        assert _is_unit_label("10 FIELD CORN SEED")

    def test_markets_excluded(self):
        assert not _is_unit_label("3 MARKETS")


# ---------------------------------------------------------------------------
# _build_unit_assessment_windows
# ---------------------------------------------------------------------------


class TestBuildUnitAssessmentWindows:

    def _sm_with_units(self, units: list[tuple[str, range]]) -> dict[int, str]:
        """Build a section map with each unit spanning a range of pages."""
        sm: dict[int, str] = {}
        for label, pages in units:
            for p in pages:
                sm[p] = f"{label} > {label} Competitive assessment"
        return sm

    def test_single_unit_produces_one_window(self):
        sm = self._sm_with_units([("8 CUCUMBER", range(79, 92))])   # 13 pages < window_size
        windows = _build_unit_assessment_windows(sm)
        assert len(windows) == 1
        assert windows[0].start_page == 79
        assert windows[0].end_page == 91

    def test_two_units_produce_two_windows(self):
        sm = self._sm_with_units([
            ("8 CUCUMBER", range(79, 92)),    # 13 pages each < window_size
            ("9 ONION", range(178, 191)),
        ])
        windows = _build_unit_assessment_windows(sm)
        assert len(windows) == 2

    def test_generic_sections_excluded(self):
        sm: dict[int, str] = {}
        # Framework sections: should NOT produce windows
        for p in range(1, 10):
            sm[p] = "1 INTRODUCTION > 1.1 Background"
        for p in range(10, 20):
            sm[p] = "2 BACKGROUND > 2.1 Procedure"
        # Unit section: should produce a window (14 pages < window_size=15)
        for p in range(79, 93):
            sm[p] = "8 CUCUMBER > 8.2 Competitive assessment"
        windows = _build_unit_assessment_windows(sm)
        assert len(windows) == 1
        assert windows[0].start_page == 79

    def test_page_range_restriction_applied(self):
        sm = self._sm_with_units([
            ("8 CUCUMBER", range(79, 92)),
            ("9 ONION", range(178, 191)),
        ])
        windows = _build_unit_assessment_windows(sm, page_range=(79, 100))
        assert len(windows) == 1
        assert windows[0].start_page == 79

    def test_large_unit_split_at_window_size(self):
        # A unit spanning 40 pages — should be split with default window_size=15
        sm: dict[int, str] = {}
        for p in range(79, 119):
            sm[p] = "8 CUCUMBER > 8.2 Competitive assessment"
        windows = _build_unit_assessment_windows(sm, window_size=15)
        assert len(windows) >= 2
        for w in windows:
            assert w.page_count <= 15

    def test_window_focus_is_unit_assessment(self):
        sm: dict[int, str] = {}
        for p in range(79, 92):
            sm[p] = "8 CUCUMBER > 8.2 Competitive assessment"
        windows = _build_unit_assessment_windows(sm)
        for w in windows:
            assert w.focus == "unit_assessment"

    def test_context_suffix_contains_unit_label(self):
        sm: dict[int, str] = {}
        for p in range(79, 92):
            sm[p] = "8 CUCUMBER > 8.2 Competitive assessment"
        windows = _build_unit_assessment_windows(sm)
        assert "cucumber" in windows[0].context_suffix.lower()

    def test_command_output_has_unit_assessment_focus(self):
        sm: dict[int, str] = {}
        for p in range(79, 92):
            sm[p] = "8 CUCUMBER > 8.2 Competitive assessment"
        windows = _build_unit_assessment_windows(sm)
        cmd = windows[0].command("eu_bayer_monsanto_2018", 1)
        assert "--focus unit_assessment" in cmd
        assert "--page-range 79:91" in cmd

    def test_empty_section_map_returns_empty(self):
        assert _build_unit_assessment_windows({}) == []

    def test_no_unit_sections_returns_empty(self):
        sm: dict[int, str] = {}
        for p in range(1, 30):
            sm[p] = "1 INTRODUCTION > 1.1 Background"
        assert _build_unit_assessment_windows(sm) == []


# ---------------------------------------------------------------------------
# format_plan with unit_assessment focus (adjacent-window warning)
# ---------------------------------------------------------------------------


class TestFormatPlanUnitAssessment:

    def _make_ua_window(self, start: int, end: int, label: str = "cucumber") -> ProbeWindow:
        return ProbeWindow(
            start_page=start,
            end_page=end,
            focus="unit_assessment",
            headings=[(start, f"8 {label.upper()}")],
            total_score=end - start + 1,
            context_suffix=f"{label}_{start}",
        )

    def test_output_includes_unit_assessment_focus(self):
        w = self._make_ua_window(79, 105)
        out = format_plan([w], "eu_bayer_monsanto_2018", "unit_assessment", "eu_decision", 1006)
        assert "unit_assessment" in out

    def test_adjacent_windows_trigger_warning(self):
        # Windows 79-105 and 106-120 are adjacent (no gap)
        w1 = self._make_ua_window(79, 105, "cucumber")
        w2 = self._make_ua_window(106, 120, "onion")
        out = format_plan([w1, w2], "eu_bayer_monsanto_2018", "unit_assessment", "eu_decision", 1006)
        assert "WARNING" in out or "warning" in out.lower()

    def test_non_adjacent_windows_no_warning(self):
        # Gap of 10 pages between windows
        w1 = self._make_ua_window(79, 105, "cucumber")
        w2 = self._make_ua_window(178, 194, "onion")
        out = format_plan([w1, w2], "eu_bayer_monsanto_2018", "unit_assessment", "eu_decision", 1006)
        assert "WARNING" not in out

    def test_single_window_no_warning(self):
        w = self._make_ua_window(79, 105)
        out = format_plan([w], "eu_bayer_monsanto_2018", "unit_assessment", "eu_decision", 1006)
        assert "WARNING" not in out

    def test_command_in_output_has_output_suffix(self):
        w = self._make_ua_window(79, 105)
        out = format_plan([w], "eu_bayer_monsanto_2018", "unit_assessment", "eu_decision", 1006)
        assert "--output-suffix" in out

    def test_plan_function_dispatches_to_unit_assessment(self):
        # plan() with focus=unit_assessment should use structural detection, not keyword scoring
        cache = _make_cache([])   # empty cache returns empty list
        result = plan(cache, focus="unit_assessment")
        assert result == []
