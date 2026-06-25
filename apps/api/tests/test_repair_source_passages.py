"""
Unit tests for scripts/cases/repair_source_passages.py

No network access, no PDF downloads, no filesystem writes to real YAML.
"""
import copy
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from repair_source_passages import (
    Candidate,
    PassageValidationResult,
    PropositionSearchResult,
    RepairReport,
    _check_mislabelled_propositions,
    _confidence_label,
    _detect_toh_subtype,
    _extract_keywords,
    _extract_section_map,
    _find_candidates,
    _find_unsupported,
    _is_toc_page,
    _proposition_keywords,
    _score_toh_subtype_signals,
    _section_coherence_score,
    _select_with_claude,
    _topic_words,
    _validate_passages,
    _write_yaml,
    repair_case,
    serialize_reports,
)
from check_source_integrity import quote_found_in_text


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_page_cache(
    pages: list[tuple[int, str]],
    doc_id: str = "test_doc",
) -> dict:
    return {
        "source_document_id": doc_id,
        "source_url": f"https://example.com/{doc_id}.pdf",
        "page_count": len(pages),
        "pages": [{"page_number": n, "text": t} for n, t in pages],
        "extracted_at": "2026-05-23T00:00:00+00:00",
    }


def _make_record(
    passages=None,
    markets=None,
    geo_markets=None,
    theories=None,
    sector="digital / platforms",
) -> dict:
    return {
        "case_id": "test_case",
        "case_name": "Acme / Widget",
        "authority": "European Commission",
        "sector": sector,
        "source_documents": [
            {
                "doc_id": "main_doc",
                "title": "Test Decision",
                "pdf_url": "https://example.com/decision.pdf",
                "doc_type": "decision",
            }
        ],
        "source_passages": passages or [],
        "product_markets_considered": markets or [
            {"market_id": "pm_1", "name": "Widget market", "definition_status": "defined",
             "notes": "Commission defined widget market for digital devices."}
        ],
        "geographic_markets_considered": geo_markets or [],
        "theories_of_harm": theories or [],
        "parties": [
            {"name": "Acme Corp", "role": "acquirer"},
            {"name": "Widget Ltd", "role": "target"},
        ],
    }


def _pvr(pid: str, status: str, doc_id: str = "main_doc") -> PassageValidationResult:
    return PassageValidationResult(
        passage_id=pid, source_document_id=doc_id,
        listed_page=1, status=status, found_on_page=None,
        message="test", original_quote="some quote",
    )


# ---------------------------------------------------------------------------
# _validate_passages
# ---------------------------------------------------------------------------

class TestValidatePassages:
    def _doc_map(self) -> dict:
        return {"main_doc": {"doc_id": "main_doc", "pdf_url": "https://example.com/d.pdf"}}

    def test_quote_found_on_correct_page(self):
        cache = _make_page_cache([
            (1, "Some preamble text here."),
            (14, "The Commission concludes that the relevant product market is wearable devices."),
        ])
        passages = [{
            "passage_id": "sp_1",
            "source_document_id": "main_doc",
            "page": "14",
            "quote_snippet": "relevant product market is wearable devices",
        }]
        results = _validate_passages(passages, self._doc_map(), {"main_doc": cache})
        assert len(results) == 1
        assert results[0].status == "ok"
        assert results[0].found_on_page == 14
        assert results[0].original_quote == "relevant product market is wearable devices"

    def test_quote_found_on_wrong_page(self):
        cache = _make_page_cache([
            (14, "This page talks about geographic markets only."),
            (21, "The Commission concludes that the relevant product market is wearable devices."),
        ])
        passages = [{
            "passage_id": "sp_1",
            "source_document_id": "main_doc",
            "page": "14",
            "quote_snippet": "relevant product market is wearable devices",
        }]
        results = _validate_passages(passages, self._doc_map(), {"main_doc": cache})
        assert results[0].status == "wrong_page"
        assert results[0].found_on_page == 21
        assert results[0].repaired_page == 21
        assert "21" in results[0].message

    def test_hallucinated_quote_flagged(self):
        cache = _make_page_cache([
            (1, "This document says nothing about widgets or the specific proposition."),
            (2, "More unrelated content about different topics entirely."),
        ])
        passages = [{
            "passage_id": "sp_1",
            "source_document_id": "main_doc",
            "page": "1",
            "quote_snippet": (
                "The Commission concludes that the relevant product market for "
                "wearable fitness devices is distinct from general-purpose smartwatches"
            ),
        }]
        results = _validate_passages(passages, self._doc_map(), {"main_doc": cache})
        assert results[0].status == "not_found"
        assert "hallucination" in results[0].message.lower()

    def test_original_quote_stored(self):
        """original_quote must be set even for not_found passages."""
        cache = _make_page_cache([(1, "Irrelevant text.")])
        original = "A quote that is definitely not in the PDF at all."
        passages = [{
            "passage_id": "sp_1",
            "source_document_id": "main_doc",
            "page": "1",
            "quote_snippet": original,
        }]
        results = _validate_passages(passages, self._doc_map(), {"main_doc": cache})
        assert results[0].original_quote == original

    def test_no_cache_returns_no_cache_status(self):
        passages = [{
            "passage_id": "sp_1",
            "source_document_id": "main_doc",
            "page": "5",
            "quote_snippet": "Some text",
        }]
        results = _validate_passages(passages, self._doc_map(), {"main_doc": None})
        assert results[0].status == "no_cache"

    def test_empty_quote_flagged_not_found(self):
        cache = _make_page_cache([(1, "Some page text here.")])
        passages = [{
            "passage_id": "sp_1",
            "source_document_id": "main_doc",
            "page": "1",
            "quote_snippet": "",
        }]
        results = _validate_passages(passages, self._doc_map(), {"main_doc": cache})
        assert results[0].status == "not_found"


# ---------------------------------------------------------------------------
# _find_unsupported — with passage_results
# ---------------------------------------------------------------------------

class TestFindUnsupported:
    def test_market_with_valid_passage_is_not_unsupported(self):
        record = _make_record(
            passages=[{
                "passage_id": "sp_1",
                "source_document_id": "main_doc",
                "page": "1",
                "quote_snippet": "text",
                "supports_markets": ["pm_1"],
                "supports_geographic_markets": [],
                "supports_theories": [],
            }]
        )
        pvrs = [_pvr("sp_1", "ok")]
        result = _find_unsupported(record, pvrs)
        assert not result["product_market"]

    def test_hallucinated_passage_does_not_count_as_support(self):
        """A passage with status=not_found must NOT grant support to its proposition."""
        record = _make_record(
            passages=[{
                "passage_id": "sp_1",
                "source_document_id": "main_doc",
                "page": "1",
                "quote_snippet": "hallucinated text",
                "supports_markets": ["pm_1"],
                "supports_geographic_markets": [],
                "supports_theories": [],
            }]
        )
        pvrs = [_pvr("sp_1", "not_found")]
        result = _find_unsupported(record, pvrs)
        # pm_1 must be in unsupported — its only passage is hallucinated
        assert any(m["market_id"] == "pm_1" for m in result["product_market"])

    def test_invalidated_passage_ids_tracked(self):
        """Propositions whose only passages are hallucinated record the invalidated IDs."""
        record = _make_record(
            passages=[{
                "passage_id": "sp_1",
                "source_document_id": "main_doc",
                "page": "1",
                "quote_snippet": "hallucinated",
                "supports_markets": ["pm_1"],
                "supports_geographic_markets": [],
                "supports_theories": [],
            }]
        )
        pvrs = [_pvr("sp_1", "not_found")]
        result = _find_unsupported(record, pvrs)
        market = next(m for m in result["product_market"] if m["market_id"] == "pm_1")
        assert "sp_1" in market["_invalidated"]

    def test_market_with_no_passage_is_unsupported(self):
        record = _make_record(passages=[])
        result = _find_unsupported(record, [])
        assert any(m["market_id"] == "pm_1" for m in result["product_market"])

    def test_theory_with_no_passage_is_unsupported(self):
        record = _make_record(
            passages=[],
            theories=[{
                "theory_id": "toh_1",
                "name": "Foreclosure theory",
                "description": "The merged entity would foreclose rivals.",
            }]
        )
        result = _find_unsupported(record, [])
        assert any(t["theory_id"] == "toh_1" for t in result["theory_of_harm"])

    def test_wrong_page_counts_as_valid_support(self):
        """wrong_page means quote found but page number is wrong — still valid support."""
        record = _make_record(
            passages=[{
                "passage_id": "sp_1",
                "source_document_id": "main_doc",
                "page": "1",
                "quote_snippet": "text",
                "supports_markets": ["pm_1"],
                "supports_geographic_markets": [],
                "supports_theories": [],
            }]
        )
        pvrs = [_pvr("sp_1", "wrong_page")]
        result = _find_unsupported(record, pvrs)
        assert not result["product_market"]


# ---------------------------------------------------------------------------
# _confidence_label
# ---------------------------------------------------------------------------

class TestConfidenceLabel:
    def test_strong_at_or_above_threshold(self):
        assert _confidence_label(4) == "strong"
        assert _confidence_label(10) == "strong"

    def test_possible_between_thresholds(self):
        assert _confidence_label(2) == "possible"
        assert _confidence_label(3) == "possible"

    def test_weak_below_possible_threshold(self):
        assert _confidence_label(1) == "weak"
        assert _confidence_label(0) == "weak"


# ---------------------------------------------------------------------------
# _find_candidates — score, confidence, source_document_id
# ---------------------------------------------------------------------------

class TestFindCandidates:
    def test_returns_candidates_with_confidence_and_doc_id(self):
        cache = _make_page_cache([
            (1, "Preamble about the parties."),
            (5, (
                "The Commission considered the market for wearable fitness devices "
                "in detail. The relevant geographic scope is EEA-wide."
            )),
        ], doc_id="main_doc")
        keywords = ["wearable", "fitness", "devices", "Commission", "geographic"]
        candidates = _find_candidates(keywords, cache)
        assert len(candidates) >= 1
        c = candidates[0]
        assert c.page_number == 5
        assert c.score >= 1          # composite_score via property
        assert c.confidence in ("strong", "possible", "weak")
        assert c.source_document_id == "main_doc"
        assert c.support_type in ("direct_support", "contextual_support",
                                   "weak_keyword_match", "likely_wrong_section")
        assert isinstance(c.reason, str)
        assert isinstance(c.composite_score, int)

    def test_score_reflects_matched_term_count(self):
        cache = _make_page_cache([
            (1, "wearable fitness platform OS devices digital"),
        ], doc_id="doc1")
        keywords = ["wearable", "fitness", "platform", "digital"]
        candidates = _find_candidates(keywords, cache)
        # keyword_score == 4 (4 terms matched); no type signals → composite_score == 4
        assert candidates[0].keyword_score == 4
        assert candidates[0].score == 4

    def test_returns_empty_when_no_match(self):
        cache = _make_page_cache([(1, "Nothing useful here.")])
        candidates = _find_candidates(["XYZunmatchable", "ABCnothere"], cache)
        assert candidates == []

    def test_candidates_capped_at_max(self):
        pages = [(i + 1, f"Widget market analysis page {i + 1}") for i in range(20)]
        cache = _make_page_cache(pages)
        candidates = _find_candidates(["Widget", "market", "analysis"], cache, max_results=3)
        assert len(candidates) <= 3

    def test_strong_candidate_ranks_first(self):
        cache = _make_page_cache([
            (1, "wearable fitness"),           # 2 terms → possible
            (2, "wearable fitness platform OS devices digital"),  # 6 terms → strong
        ], doc_id="doc1")
        keywords = ["wearable", "fitness", "platform", "devices", "digital", "operating"]
        candidates = _find_candidates(keywords, cache)
        assert candidates[0].page_number == 2   # strong candidate first


# ---------------------------------------------------------------------------
# _proposition_keywords — uses full record
# ---------------------------------------------------------------------------

class TestPropositionKeywords:
    def _record(self) -> dict:
        return {
            "parties": [
                {"name": "Google LLC", "role": "acquirer"},
                {"name": "Fitbit Inc", "role": "target"},
            ],
            "sector": "digital / platforms",
            "authority": "European Commission",
            "case_name": "Google / Fitbit",
        }

    def test_includes_party_names(self):
        prop = {"name": "Wearable OS market", "notes": "Android-based platforms"}
        kws = _proposition_keywords(prop, self._record())
        kw_lower = [k.lower() for k in kws]
        assert "google" in kw_lower or "fitbit" in kw_lower

    def test_includes_sector_terms(self):
        prop = {"name": "Wearable market"}
        kws = _proposition_keywords(prop, self._record())
        kw_lower = [k.lower() for k in kws]
        assert "digital" in kw_lower or "platforms" in kw_lower

    def test_no_existing_quote_used(self):
        """The function should not accept an existing quote_snippet as input source."""
        # _proposition_keywords only takes prop dict and record; no quote param
        prop = {"name": "Market", "notes": "some notes"}
        kws = _proposition_keywords(prop, self._record())
        assert isinstance(kws, list)

    def test_deduplicates_keywords(self):
        prop = {"name": "wearable devices", "notes": "wearable fitness devices"}
        kws = _proposition_keywords(prop, self._record())
        kw_lower = [k.lower() for k in kws]
        # "wearable" should appear only once
        assert kw_lower.count("wearable") == 1


# ---------------------------------------------------------------------------
# Summary counters
# ---------------------------------------------------------------------------

class TestSummaryCounters:
    def _make_report(self) -> RepairReport:
        rpt = RepairReport(case_id="test", case_yaml_path=Path("/tmp/test.yaml"))
        rpt.passage_results = [
            _pvr("sp_1", "ok"),
            _pvr("sp_2", "wrong_page"),
            _pvr("sp_3", "not_found"),
            _pvr("sp_4", "not_found"),
            _pvr("sp_5", "no_cache"),
        ]
        rpt.proposition_results = [
            PropositionSearchResult("pm_1", "product_market", "Market A", "valid_support"),
            PropositionSearchResult("pm_2", "product_market", "Market B", "valid_support"),
            PropositionSearchResult("pm_3", "product_market", "Market C", "candidates_found",
                candidates=[
                    Candidate(1, "text", "doc",
                              match_terms=["kw1", "kw2", "kw3", "kw4"],
                              keyword_score=4, composite_score=4,
                              support_type="direct_support"),
                    Candidate(2, "text2", "doc",
                              match_terms=["kw1", "kw2"],
                              keyword_score=2, composite_score=2,
                              support_type="contextual_support"),
                ]),
            PropositionSearchResult("toh_1", "theory_of_harm", "Theory D", "candidates_found",
                candidates=[
                    Candidate(5, "theory text", "doc",
                              match_terms=["kw1"], keyword_score=1, composite_score=1,
                              support_type="weak_keyword_match"),
                ]),
            PropositionSearchResult("toh_2", "theory_of_harm", "Theory E", "no_candidates"),
        ]
        return rpt

    def test_passage_counters(self):
        rpt = self._make_report()
        assert rpt.existing_passages_ok == 1
        assert rpt.existing_passages_wrong_page == 1
        assert rpt.existing_passages_not_found == 2
        assert rpt.existing_passages_no_cache == 1

    def test_proposition_counters(self):
        rpt = self._make_report()
        assert rpt.propositions_total == 5
        assert rpt.propositions_with_valid_support == 2
        assert rpt.propositions_with_candidates == 2
        assert rpt.propositions_without_candidates == 1

    def test_candidate_passages_total(self):
        rpt = self._make_report()
        # pm_3 has 2 candidates, toh_1 has 1 → total = 3
        assert rpt.candidate_passages_total == 3

    def test_one_proposition_five_candidates_counted_correctly(self):
        """A proposition with 5 candidates counts as 1 proposition, 5 candidate passages."""
        rpt = RepairReport(case_id="test", case_yaml_path=Path("/tmp/test.yaml"))
        rpt.proposition_results = [
            PropositionSearchResult(
                "pm_1", "product_market", "Market", "candidates_found",
                candidates=[
                    Candidate(i + 1, "text", "doc",
                              match_terms=["kw1"], keyword_score=1, composite_score=1)
                    for i in range(5)
                ],
            )
        ]
        assert rpt.propositions_with_candidates == 1
        assert rpt.candidate_passages_total == 5

    def test_legacy_aliases_still_work(self):
        """Backward-compat properties must not raise AttributeError."""
        rpt = self._make_report()
        _ = rpt.passages_ok
        _ = rpt.passages_wrong_page
        _ = rpt.passages_not_found
        _ = rpt.passages_no_cache
        _ = rpt.propositions_already_supported
        _ = rpt.propositions_not_found


# ---------------------------------------------------------------------------
# _select_with_claude
# ---------------------------------------------------------------------------

class TestSelectWithClaude:
    def _mock_anthropic(self, response_text: str):
        ac = MagicMock()
        msg = MagicMock()
        msg.content = [MagicMock(text=response_text)]
        ac.messages.create.return_value = msg
        return ac

    def test_valid_selection_returns_candidate_and_quote(self):
        candidate_text = (
            "The Commission finds the relevant market for wearable fitness devices "
            "to be distinct from general-purpose smartwatches based on functionality."
        )
        candidates = [Candidate(
            page_number=14, text_window=candidate_text,
            source_document_id="doc1",
            match_terms=["wearable", "fitness"],
            keyword_score=2, composite_score=2,
            support_type="contextual_support",
        )]
        ac = self._mock_anthropic(
            "SELECTED: 1\nQUOTE: relevant market for wearable fitness devices"
        )
        selected, quote = _select_with_claude(
            "Wearable fitness devices market", "product_market", candidates, ac
        )
        assert selected is not None
        assert selected.page_number == 14
        assert quote is not None
        assert "wearable fitness devices" in quote.lower()

    def test_no_support_found_returns_none(self):
        candidates = [Candidate(5, "Some unrelated text.", "doc",
                                match_terms=["kw"], keyword_score=1, composite_score=1)]
        ac = self._mock_anthropic("no_support_found")
        selected, quote = _select_with_claude("Widget market", "product_market", candidates, ac)
        assert selected is None
        assert quote is None

    def test_invalid_index_returns_none(self):
        candidates = [Candidate(5, "Some text.", "doc",
                                match_terms=["kw"], keyword_score=1, composite_score=1)]
        ac = self._mock_anthropic("SELECTED: 99\nQUOTE: something")
        selected, quote = _select_with_claude("Widget market", "product_market", candidates, ac)
        assert selected is None

    def test_invented_quote_rejected(self):
        candidates = [Candidate(
            page_number=5,
            text_window="The parties overlap in cloud gaming services.",
            source_document_id="doc1",
            match_terms=["cloud"], keyword_score=1, composite_score=1,
        )]
        ac = self._mock_anthropic(
            "SELECTED: 1\nQUOTE: The Court finds market definition was contested in 2024"
        )
        selected, quote = _select_with_claude("Cloud gaming", "product_market", candidates, ac)
        assert selected is None or quote is None

    def test_empty_candidates_returns_none(self):
        ac = self._mock_anthropic("SELECTED: 1\nQUOTE: something")
        selected, quote = _select_with_claude("Market", "product_market", [], ac)
        assert selected is None
        assert quote is None


# ---------------------------------------------------------------------------
# Section extraction helpers
# ---------------------------------------------------------------------------

class TestExtractSectionMap:
    def _cache(self, pages: list[tuple[int, str]]) -> dict:
        return {
            "source_document_id": "doc1",
            "pages": [{"page_number": n, "text": t} for n, t in pages],
        }

    def test_extracts_numbered_headings(self):
        cache = self._cache([
            (1, "1 Introduction\nSome intro text."),
            (5, "8 Assessment\nProduct market analysis."),
            (10, "8.6 Online advertising\nThe Commission assessed online advertising."),
        ])
        smap = _extract_section_map(cache)
        assert "8" in smap[5] or "Assessment" in smap[5]
        assert "8.6" in smap[10] and "Online advertising" in smap[10]

    def test_hierarchical_path_accumulates(self):
        cache = self._cache([
            (1, "8 Product markets\nOverview."),
            (2, "8.6 Online advertising\nSection intro."),
            (3, "8.6.1 Product market definition\nThe relevant product market."),
        ])
        smap = _extract_section_map(cache)
        path = smap[3]
        # Full path must include all three levels
        assert "Online advertising" in path
        assert "Product market definition" in path

    def test_new_heading_pops_sibling(self):
        cache = self._cache([
            (1, "8.6 Online advertising\nContent."),
            (2, "8.7 Digital music\nContent."),
        ])
        smap = _extract_section_map(cache)
        assert "Online advertising" not in smap[2]
        assert "Digital music" in smap[2]

    def test_empty_cache_returns_empty_strings(self):
        cache = self._cache([(1, "No headings here — just prose text.")])
        smap = _extract_section_map(cache)
        assert smap[1] == ""


class TestTopicWords:
    def test_strips_section_number(self):
        words = _topic_words("8.6 Online advertising")
        assert "online" in words
        assert "advertising" in words
        assert "8" not in words

    def test_replaces_separators(self):
        words = _topic_words("Wear OS / platforms")
        assert "wear" in words
        assert "platforms" in words

    def test_filters_stop_words(self):
        words = _topic_words("Theory of harm analysis")
        assert "theory" in words
        assert "harm" in words
        # "analysis" is a stop word
        assert "analysis" not in words
        assert "of" not in words

    def test_short_texts_ok(self):
        words = _topic_words("EEA")
        # "EEA" has 3 chars — below the 3-char minimum in regex
        # Just check it doesn't raise
        assert isinstance(words, list)


class TestSectionCoherenceScore:
    def test_full_overlap_gives_bonus(self):
        bonus, penalty, reason = _section_coherence_score(
            "8.6 Online advertising > 8.6.1 Product market definition",
            ["online", "advertising"],
        )
        assert bonus >= 3
        assert penalty == 0
        assert "match" in reason.lower()

    def test_zero_overlap_gives_penalty(self):
        bonus, penalty, reason = _section_coherence_score(
            "9.4 Wear OS > 9.4.3 Ability and incentives to foreclose",
            ["online", "advertising"],
        )
        assert bonus == 0
        assert penalty >= 3
        assert "mismatch" in reason.lower()

    def test_empty_section_path_returns_zeros(self):
        bonus, penalty, reason = _section_coherence_score("", ["online", "advertising"])
        assert bonus == 0 and penalty == 0

    def test_empty_prop_words_returns_zeros(self):
        bonus, penalty, reason = _section_coherence_score("8.6 Online advertising", [])
        assert bonus == 0 and penalty == 0


# ---------------------------------------------------------------------------
# Section-aware candidate ranking
# ---------------------------------------------------------------------------

class TestSectionAwareScoring:
    """
    Verifies acceptance criteria for section-aware candidate scoring.
    Uses fabricated page text that mimics EC decision structure.
    """

    def _make_cache(self, pages: list[tuple[int, str]], doc_id: str = "doc1") -> dict:
        return {
            "source_document_id": doc_id,
            "source_url": "https://example.com/doc.pdf",
            "page_count": len(pages),
            "pages": [{"page_number": n, "text": t} for n, t in pages],
            "extracted_at": "2026-05-23T00:00:00+00:00",
        }

    def test_online_advertising_market_not_direct_support_from_app_store_section(self):
        """
        pm_3 — Online advertising: a page inside the app-store product-market
        section must NOT be ranked as direct_support even if it contains
        generic market-definition language.
        """
        cache = self._make_cache([
            # Page 1: app-store section with market-definition heading → wrong section for online advertising
            (1, (
                "9.2 Play Store / app ecosystem\n"
                "9.2.1 Product market definition\n"
                "The Commission defines the relevant product market as the market "
                "for Android app distribution platforms. The market definition "
                "is distinct from iOS app stores."
            )),
            # Page 2: online advertising section → right section
            (2, (
                "8.6 Online advertising\n"
                "8.6.1 Product market definition\n"
                "The Commission defines the relevant product market for online "
                "advertising services including search advertising and display advertising."
            )),
        ])
        keywords = ["market", "Commission", "advertising", "product", "relevant"]
        candidates = _find_candidates(
            keywords, cache,
            proposition_type="product_market",
            prop_topic_words=_topic_words("Online advertising"),
        )
        assert len(candidates) >= 2
        # Page 2 (online advertising section) must rank above page 1 (app-store section)
        assert candidates[0].page_number == 2
        # App-store section must NOT be direct_support
        app_store_cand = next(c for c in candidates if c.page_number == 1)
        assert app_store_cand.support_type != "direct_support"

    def test_geographic_online_advertising_not_direct_support_from_music_section(self):
        """
        gm_2 — EEA (online advertising): a page from the digital music geographic
        market section must not be ranked as direct_support.
        """
        cache = self._make_cache([
            # Page 1: digital music geographic market section — wrong topic
            (1, (
                "8.7 Digital music\n"
                "8.7.2 Geographic market definition\n"
                "The relevant geographic market for digital music streaming is at "
                "least EEA-wide. Competitive conditions across the EEA are uniform."
            )),
            # Page 2: online advertising geographic market section — right topic
            (2, (
                "8.6 Online advertising\n"
                "8.6.2 Geographic market definition\n"
                "The relevant geographic market for online advertising is at least "
                "EEA-wide based on competitive conditions across the EEA member states."
            )),
        ])
        keywords = ["EEA", "geographic", "market", "advertising", "competitive"]
        candidates = _find_candidates(
            keywords, cache,
            proposition_type="geographic_market",
            prop_topic_words=_topic_words("EEA online advertising"),
        )
        assert len(candidates) >= 2
        # Online advertising section must rank above digital music section
        assert candidates[0].page_number == 2
        # Digital music section must NOT be direct_support
        music_cand = next(c for c in candidates if c.page_number == 1)
        assert music_cand.support_type != "direct_support"

    def test_data_advantage_ranks_above_wear_os_foreclosure(self):
        """
        toh_2 — Data advantage in digital advertising: a passage about Fitbit
        data / advertising must rank above Wear OS / foreclosure passages.
        """
        cache = self._make_cache([
            # Page 1: Wear OS / foreclosure section — wrong topic for data advantage
            (1, (
                "9.4 Wear OS / foreclosure\n"
                "9.4.3 Ability and incentives to foreclose\n"
                "The Commission assesses whether Google has the ability to foreclose "
                "rival smartwatch manufacturers through input foreclosure of Wear OS. "
                "The incentive to foreclose arises from the competitive harm to Google."
            )),
            # Page 2: data advantage / advertising section — right topic
            (2, (
                "9.1 Data advantage in digital advertising\n"
                "9.1.1 Ability to strengthen market position\n"
                "Fitbit data, including health and wellness data, would strengthen "
                "Google's position in digital advertising. The data advantage allows "
                "Google to personalise and target advertising. Search advertising and "
                "display advertising would benefit from Fitbit health data aggregation."
            )),
        ])
        keywords = ["Google", "Fitbit", "data", "advertising", "Commission"]
        candidates = _find_candidates(
            keywords, cache,
            proposition_type="theory_of_harm",
            prop_topic_words=_topic_words("Data advantage in digital advertising"),
        )
        assert len(candidates) >= 2
        # Data/advertising section must rank above Wear OS section
        assert candidates[0].page_number == 2

    def test_wear_os_foreclosure_ranks_ability_incentive_passage_correctly(self):
        """
        toh_1 — Wear OS / foreclosure: a Wear OS ability/incentive passage should
        rank above a data-advantage passage.
        """
        cache = self._make_cache([
            # Page 1: data advantage section — wrong for Wear OS theory
            (1, (
                "9.1 Data advantage\n"
                "Fitbit health data strengthens Google advertising position."
            )),
            # Page 2: Wear OS foreclosure — correct section
            (2, (
                "9.4 Wear OS / foreclosure\n"
                "9.4.3 Ability and incentives to foreclose\n"
                "Google has the ability to foreclose rival smartwatch manufacturers "
                "by degrading Wear OS interoperability. The incentive to foreclose "
                "is confirmed by the competitive advantage gained from foreclosure. "
                "Input foreclosure of third-party wearable devices is likely."
            )),
        ])
        keywords = ["Wear", "Google", "foreclose", "wearable", "Commission"]
        candidates = _find_candidates(
            keywords, cache,
            proposition_type="theory_of_harm",
            prop_topic_words=_topic_words("Wear OS foreclosure wearables"),
        )
        assert len(candidates) >= 2
        assert candidates[0].page_number == 2

    def test_generic_market_definition_heading_alone_insufficient_for_direct_support(self):
        """
        A page that is under a generic 'Product market definition' sub-heading
        for the WRONG market (app stores) must NOT be direct_support for an
        online advertising proposition.
        """
        cache = self._make_cache([
            (1, (
                "9.2 Play Store / app ecosystem\n"
                "9.2.1 Product market definition\n"
                "The relevant product market is defined as digital app distribution. "
                "Commission concludes that the relevant product market is narrow."
            )),
        ])
        candidates = _find_candidates(
            ["market", "product", "relevant", "Commission"],
            cache,
            proposition_type="product_market",
            prop_topic_words=_topic_words("Online advertising"),
        )
        assert len(candidates) >= 1
        assert candidates[0].support_type != "direct_support"


class TestMislabelledPropositionWarning:
    def test_warning_set_when_all_top_candidates_mismatch(self):
        """When ≥2 top candidates are all likely_wrong_section, warning is set."""
        wrong = Candidate(1, "text", "doc",
                          support_type="likely_wrong_section",
                          keyword_score=2, composite_score=2)
        results = [
            PropositionSearchResult(
                "toh_1", "theory_of_harm", "Horizontal consolidation",
                "candidates_found",
                candidates=[
                    wrong,
                    Candidate(2, "text2", "doc",
                              support_type="likely_wrong_section",
                              keyword_score=2, composite_score=2),
                    Candidate(3, "text3", "doc",
                              support_type="likely_wrong_section",
                              keyword_score=1, composite_score=1),
                ],
            )
        ]
        _check_mislabelled_propositions(results)
        assert results[0].warning == "possible_mislabelled_proposition"

    def test_no_warning_when_some_candidates_match(self):
        """If any top candidate is not likely_wrong_section, no warning."""
        results = [
            PropositionSearchResult(
                "pm_1", "product_market", "Online advertising",
                "candidates_found",
                candidates=[
                    Candidate(1, "text", "doc",
                              support_type="direct_support",
                              keyword_score=5, composite_score=10),
                    Candidate(2, "text2", "doc",
                              support_type="likely_wrong_section",
                              keyword_score=2, composite_score=2),
                ],
            )
        ]
        _check_mislabelled_propositions(results)
        assert results[0].warning is None

    def test_no_warning_with_only_one_candidate(self):
        """Single candidate — not enough data to warn."""
        results = [
            PropositionSearchResult(
                "pm_1", "product_market", "M", "candidates_found",
                candidates=[
                    Candidate(1, "t", "d",
                              support_type="likely_wrong_section",
                              keyword_score=1, composite_score=1),
                ],
            )
        ]
        _check_mislabelled_propositions(results)
        assert results[0].warning is None

    def test_warning_appears_in_serialized_json(self):
        """Warning field propagates into the JSON report."""
        rpt = RepairReport(case_id="c1", case_yaml_path=Path("/tmp/c1.yaml"))
        rpt.proposition_results = [
            PropositionSearchResult(
                "toh_1", "theory_of_harm", "Horizontal consolidation",
                "candidates_found",
                candidates=[
                    Candidate(1, "t", "d",
                              support_type="likely_wrong_section",
                              keyword_score=1, composite_score=1),
                    Candidate(2, "t2", "d",
                              support_type="likely_wrong_section",
                              keyword_score=1, composite_score=1),
                    Candidate(3, "t3", "d",
                              support_type="likely_wrong_section",
                              keyword_score=1, composite_score=1),
                ],
                warning="possible_mislabelled_proposition",
            )
        ]
        payload = serialize_reports([rpt])
        prop = next(p for p in payload["cases"][0]["propositions"]
                    if p["proposition_id"] == "toh_1")
        assert prop["warning"] == "possible_mislabelled_proposition"


# ---------------------------------------------------------------------------
# Type-aware candidate scoring
# ---------------------------------------------------------------------------

class TestCandidateScoringTypeAware:
    """Verify that type-aware scoring ranks proposition-specific passages first."""

    def _cache_two_pages(self, text1: str, text2: str, doc_id: str = "doc1") -> dict:
        return {
            "source_document_id": doc_id,
            "source_url": "https://example.com/doc.pdf",
            "page_count": 2,
            "pages": [
                {"page_number": 1, "text": text1},
                {"page_number": 2, "text": text2},
            ],
            "extracted_at": "2026-05-23T00:00:00+00:00",
        }

    def test_product_market_definition_outranks_effects_passage(self):
        """
        For proposition_type='product_market', a passage with market-definition
        language must rank above a passage mentioning theory-of-harm terms
        that trigger penalty signals.
        """
        cache = self._cache_two_pages(
            # Page 1: market-definition language → type_bonus
            ("The Commission concludes that the relevant product market "
             "is defined as wearable fitness devices distinct from "
             "general-purpose smartwatches and the market definition is clear."),
            # Page 2: theory-of-harm language → penalty for product_market type
            ("The merged entity would have the ability to foreclose rivals "
             "through input foreclosure of wearable fitness devices, "
             "with technical tying of the operating system."),
        )
        keywords = ["wearable", "fitness", "devices", "Commission", "market"]
        candidates = _find_candidates(keywords, cache, proposition_type="product_market")
        assert len(candidates) >= 2
        assert candidates[0].page_number == 1
        assert candidates[0].support_type in ("direct_support", "contextual_support")
        assert candidates[1].support_type in ("weak_keyword_match", "likely_wrong_section",
                                               "contextual_support")

    def test_geographic_market_eea_outranks_generic_eea_mention(self):
        """
        For proposition_type='geographic_market', a passage with explicit
        geographic market scope language must rank above a generic mention.
        """
        cache = self._cache_two_pages(
            # Page 1: geographic market definition language
            ("The relevant geographic market is at least EEA-wide. "
             "Competitive conditions across the EEA are homogeneous "
             "with geographic market scope spanning all member states."),
            # Page 2: EEA mention without geographic-market framing
            ("The transaction involves parties operating across the EEA. "
             "The Commission has jurisdiction under the EU Merger Regulation."),
        )
        keywords = ["EEA", "market", "Commission", "geographic"]
        candidates = _find_candidates(keywords, cache, proposition_type="geographic_market")
        assert len(candidates) >= 2
        assert candidates[0].page_number == 1
        assert candidates[0].support_type in ("direct_support", "contextual_support")

    def test_theory_of_harm_foreclosure_outranks_market_definition_passage(self):
        """
        For proposition_type='theory_of_harm', a passage about foreclosure
        ability and incentive must outrank a market-definition passage.
        """
        cache = self._cache_two_pages(
            # Page 1: theory-of-harm language
            ("The Commission assessed whether the merged entity would have "
             "the ability to foreclose downstream rivals and the incentive "
             "to foreclose, leading to competitive harm through input foreclosure."),
            # Page 2: market definition only
            ("The relevant product market is defined as wearable fitness "
             "devices. The market definition is distinct from general-purpose "
             "smartwatches based on use case and consumer preference."),
        )
        keywords = ["Commission", "market", "merged", "entity", "fitness", "devices"]
        candidates = _find_candidates(keywords, cache, proposition_type="theory_of_harm")
        assert len(candidates) >= 2
        assert candidates[0].page_number == 1
        assert candidates[0].support_type in ("direct_support", "contextual_support")

    def test_weak_keyword_match_not_labelled_direct_support(self):
        """
        A passage with only generic keyword overlap and no type-specific
        signals must NOT be labelled direct_support or contextual_support.
        """
        cache = self._cache_two_pages(
            ("The parties submitted observations regarding the Commission "
             "review of the proposed transaction in the digital sector."),
            ("Second page with more generic procedural information."),
        )
        keywords = ["Commission", "digital", "sector", "parties"]
        candidates = _find_candidates(keywords, cache, proposition_type="product_market")
        assert len(candidates) >= 1
        top = candidates[0]
        assert top.support_type in ("weak_keyword_match", "likely_wrong_section")
        assert top.support_type != "direct_support"


# ---------------------------------------------------------------------------
# JSON report serialisation
# ---------------------------------------------------------------------------

class TestSerializeReports:
    def _make_full_report(self) -> RepairReport:
        rpt = RepairReport(case_id="eu_test", case_yaml_path=Path("/data/eu_test.yaml"))
        rpt.passage_results = [
            PassageValidationResult(
                "sp_1", "doc1", 14, "not_found", None,
                "Quote not found — possible hallucination",
                original_quote="The Commission concludes X.",
            ),
            PassageValidationResult(
                "sp_2", "doc1", 21, "wrong_page", 25,
                "Quote found on page 25, not 21",
                original_quote="The geographic market is EEA-wide.",
                repaired_page=25,
            ),
        ]
        rpt.proposition_results = [
            PropositionSearchResult(
                "pm_1", "product_market", "Widget market",
                "candidates_found",
                invalidated_passage_ids=["sp_1"],
                candidates=[
                    Candidate(14, "text about widgets", "doc1",
                              match_terms=["widget", "market", "digital", "devices"],
                              keyword_score=4, composite_score=4,
                              support_type="direct_support",
                              reason="Definition language found: 'product market'"),
                ],
            ),
            PropositionSearchResult("gm_1", "geographic_market", "EEA", "valid_support"),
        ]
        return rpt

    def test_json_structure_is_correct(self):
        rpt = self._make_full_report()
        payload = serialize_reports([rpt])
        assert "generated_at" in payload
        assert "overall_summary" in payload
        assert len(payload["cases"]) == 1
        case = payload["cases"][0]
        assert case["case_id"] == "eu_test"
        assert "summary" in case
        assert "invalid_passages" in case
        assert "wrong_page_passages" in case
        assert "propositions" in case

    def test_summary_counters_in_json(self):
        rpt = self._make_full_report()
        payload = serialize_reports([rpt])
        s = payload["cases"][0]["summary"]
        assert s["existing_passages_not_found"] == 1
        assert s["existing_passages_wrong_page"] == 1
        assert s["propositions_total"] == 2
        assert s["propositions_with_valid_support"] == 1
        assert s["propositions_with_candidates"] == 1
        assert s["candidate_passages_total"] == 1

    def test_invalid_passages_contain_original_quote(self):
        rpt = self._make_full_report()
        payload = serialize_reports([rpt])
        inv = payload["cases"][0]["invalid_passages"]
        assert len(inv) == 1
        assert inv[0]["original_quote"] == "The Commission concludes X."
        assert inv[0]["status"] == "not_found"

    def test_candidates_have_snippet_and_confidence(self):
        rpt = self._make_full_report()
        payload = serialize_reports([rpt])
        prop = next(
            p for p in payload["cases"][0]["propositions"]
            if p["proposition_id"] == "pm_1"
        )
        assert prop["status"] == "candidates_found"
        assert len(prop["candidates"]) == 1
        cand = prop["candidates"][0]
        assert "snippet" in cand
        assert cand["confidence"] == "strong"
        assert "support_type" in cand
        assert cand["support_type"] == "direct_support"
        assert "reason" in cand
        assert "widget" in cand["matched_terms"] or "market" in cand["matched_terms"]
        assert cand["rank"] == 1
        assert "signal_phrases" in cand
        assert "penalty_phrases" in cand

    def test_invalidated_passage_ids_in_json(self):
        rpt = self._make_full_report()
        payload = serialize_reports([rpt])
        prop = next(
            p for p in payload["cases"][0]["propositions"]
            if p["proposition_id"] == "pm_1"
        )
        assert "sp_1" in prop["invalidated_passage_ids"]

    def test_recommended_action_for_candidates(self):
        rpt = self._make_full_report()
        payload = serialize_reports([rpt])
        prop = next(
            p for p in payload["cases"][0]["propositions"]
            if p["proposition_id"] == "pm_1"
        )
        assert prop["recommended_action"] == "review_candidates"

    def test_json_is_serialisable(self):
        rpt = self._make_full_report()
        payload = serialize_reports([rpt])
        dumped = json.dumps(payload)   # must not raise
        assert len(dumped) > 100

    def test_overall_summary_aggregates_across_cases(self):
        rpt1 = RepairReport(case_id="c1", case_yaml_path=Path("/tmp/c1.yaml"))
        rpt1.passage_results = [_pvr("sp_1", "not_found"), _pvr("sp_2", "ok")]
        rpt1.proposition_results = [
            PropositionSearchResult("pm_1", "product_market", "M", "candidates_found",
                candidates=[Candidate(1, "t", "d", match_terms=["k"],
                                      keyword_score=1, composite_score=1)])
        ]
        rpt2 = RepairReport(case_id="c2", case_yaml_path=Path("/tmp/c2.yaml"))
        rpt2.passage_results = [_pvr("sp_1", "not_found")]
        rpt2.proposition_results = [
            PropositionSearchResult("pm_1", "product_market", "M", "no_candidates")
        ]
        payload = serialize_reports([rpt1, rpt2])
        overall = payload["overall_summary"]
        assert overall["cases_processed"] == 2
        assert overall["existing_passages_not_found"] == 2
        assert overall["existing_passages_ok"] == 1
        assert overall["propositions_with_candidates"] == 1
        assert overall["propositions_without_candidates"] == 1


# ---------------------------------------------------------------------------
# check_source_integrity page-level integration
# ---------------------------------------------------------------------------

class TestIntegrityCheckerPageLevel:
    def setup_method(self):
        from check_source_integrity import check_passage, Level
        self.check_passage = check_passage
        self.Level = Level

    def _doc_map(self) -> dict:
        return {"doc1": {"doc_id": "doc1", "pdf_url": "https://example.com/d.pdf"}}

    def test_correct_page_generates_info(self):
        cache = _make_page_cache([(14, "The relevant product market is wearable devices.")])
        passage = {
            "passage_id": "sp_1",
            "source_document_id": "doc1",
            "page": "14",
            "quote_snippet": "relevant product market is wearable devices",
        }
        issues = self.check_passage(
            "test_case", passage, self._doc_map(), {},
            page_caches={"doc1": cache},
        )
        assert any(i.level == self.Level.INFO and "grounded" in i.message for i in issues)

    def test_wrong_page_generates_warning_with_suggestion(self):
        cache = _make_page_cache([
            (14, "Nothing related here."),
            (21, "The relevant product market is wearable devices and more."),
        ])
        passage = {
            "passage_id": "sp_1",
            "source_document_id": "doc1",
            "page": "14",
            "quote_snippet": "relevant product market is wearable devices",
        }
        issues = self.check_passage(
            "test_case", passage, self._doc_map(), {},
            page_caches={"doc1": cache},
        )
        warnings = [i for i in issues if i.level == self.Level.WARNING]
        assert any("21" in w.message for w in warnings)

    def test_hallucinated_quote_generates_warning(self):
        cache = _make_page_cache([
            (1, "This document contains no relevant text whatsoever."),
            (2, "More irrelevant content about something completely different."),
        ])
        passage = {
            "passage_id": "sp_1",
            "source_document_id": "doc1",
            "page": "1",
            "quote_snippet": (
                "The Commission concludes the relevant product market for "
                "wearable fitness devices is distinct from general smartwatches"
            ),
        }
        issues = self.check_passage(
            "test_case", passage, self._doc_map(), {},
            page_caches={"doc1": cache},
        )
        assert any(i.level == self.Level.WARNING and "hallucination" in i.message for i in issues)


# ---------------------------------------------------------------------------
# Dry-run does not modify files
# ---------------------------------------------------------------------------

class TestDryRunNoModification:
    def test_dry_run_does_not_write_yaml(self, tmp_path):
        record = _make_record()
        yaml_path = tmp_path / "test_case.yaml"
        with open(yaml_path, "w") as f:
            yaml.dump(record, f)

        original_mtime = yaml_path.stat().st_mtime

        cache = _make_page_cache([(1, "Some page content for testing.")])
        with patch("repair_source_passages.load_cache", return_value=None), \
             patch("repair_source_passages.fetch_and_extract", return_value=cache):
            repair_case(
                yaml_path,
                cache_dir=tmp_path / "cache",
                build_cache=False,
                dry_run=True,
            )

        assert yaml_path.stat().st_mtime == original_mtime

    def test_write_mode_updates_yaml(self, tmp_path):
        record = _make_record(passages=[{
            "passage_id": "sp_1",
            "source_document_id": "main_doc",
            "page": "14",
            "quote_snippet": "The relevant product market is wearable devices.",
            "extraction_method": "manually_added",
            "review_status": "spot_checked",
            "confidence_score": 0.9,
            "last_checked_date": "2025-01-01",
            "supports_markets": ["pm_1"],
            "supports_geographic_markets": [],
            "supports_theories": [],
        }])
        yaml_path = tmp_path / "test_case.yaml"
        with open(yaml_path, "w") as f:
            yaml.dump(record, f)

        # Cache says quote is on page 21, not 14
        cache = _make_page_cache([
            (14, "Nothing about wearables on this page."),
            (21, "The relevant product market is wearable devices and they are defined narrowly."),
        ])
        with patch("repair_source_passages.load_cache", return_value=cache):
            rpt = repair_case(
                yaml_path,
                cache_dir=tmp_path / "cache",
                build_cache=False,
                dry_run=False,
            )

        with open(yaml_path) as f:
            updated = yaml.safe_load(f)

        passages = updated.get("source_passages", [])
        assert len(passages) >= 1
        assert passages[0]["page"] == "21"
        assert passages[0]["review_status"] == "unreviewed"

    def test_hallucinated_passage_does_not_grant_support_after_repair(self, tmp_path):
        """Even in write mode, hallucinated quotes must not be written as valid support."""
        record = _make_record(passages=[{
            "passage_id": "sp_1",
            "source_document_id": "main_doc",
            "page": "1",
            "quote_snippet": "A completely invented quote that does not exist in the PDF.",
            "extraction_method": "manually_added",
            "review_status": "spot_checked",
            "confidence_score": 0.9,
            "last_checked_date": "2025-01-01",
            "supports_markets": ["pm_1"],
            "supports_geographic_markets": [],
            "supports_theories": [],
        }])
        yaml_path = tmp_path / "test_case.yaml"
        with open(yaml_path, "w") as f:
            yaml.dump(record, f)

        cache = _make_page_cache([(1, "Irrelevant content that never matches the invented quote.")])
        with patch("repair_source_passages.load_cache", return_value=cache):
            rpt = repair_case(
                yaml_path,
                cache_dir=tmp_path / "cache",
                build_cache=False,
                dry_run=False,
            )

        # The report must show sp_1 as not_found
        assert any(pvr.passage_id == "sp_1" and pvr.status == "not_found"
                   for pvr in rpt.passage_results)

        # The YAML should not have been updated with a wrong page for sp_1
        with open(yaml_path) as f:
            updated = yaml.safe_load(f)
        passages = updated.get("source_passages", [])
        sp1 = next((p for p in passages if p.get("passage_id") == "sp_1"), None)
        # sp_1 should still be page "1" (write-back only touches wrong_page, not not_found)
        assert sp1 is not None
        assert sp1["page"] == "1"


# ---------------------------------------------------------------------------
# JSON report can be written to disk
# ---------------------------------------------------------------------------

class TestReportJsonOutput:
    def test_report_json_written_to_disk(self, tmp_path):
        rpt = RepairReport(case_id="c1", case_yaml_path=Path("/tmp/c1.yaml"))
        rpt.passage_results = [_pvr("sp_1", "not_found")]
        rpt.proposition_results = [
            PropositionSearchResult("pm_1", "product_market", "Market", "no_candidates")
        ]

        report_path = tmp_path / "repair_report.json"
        payload = serialize_reports([rpt])
        with open(report_path, "w") as f:
            json.dump(payload, f, indent=2)

        assert report_path.exists()
        with open(report_path) as f:
            loaded = json.load(f)
        assert loaded["cases"][0]["case_id"] == "c1"
        assert "overall_summary" in loaded


# ---------------------------------------------------------------------------
# Hardened heading extraction — footnotes must not become section paths
# ---------------------------------------------------------------------------

class TestHardenedHeadingExtraction:
    def _cache(self, pages: list[tuple[int, str]]) -> dict:
        return {
            "source_document_id": "doc1",
            "pages": [{"page_number": n, "text": t} for n, t in pages],
        }

    def test_high_single_number_footnote_rejected(self):
        """'47 Replies to questionnaire...' must not become a section heading."""
        cache = self._cache([
            (1, (
                "8.6 Online advertising\n"
                "The Commission assessed online advertising markets.\n"
                "47 Replies to questionnaire QA on wearables, search and advertising, question C."
            )),
        ])
        smap = _extract_section_map(cache)
        path = smap[1]
        assert "Online advertising" in path
        assert "Replies" not in path
        assert "questionnaire" not in path

    def test_commission_decision_footnote_rejected(self):
        """'104 Commission decision of...' is a footnote reference, not a section heading."""
        cache = self._cache([
            (1, (
                "8 Assessment\n"
                "Some text.\n"
                "104 Commission decision of 11 March 2008 in case M.4731."
            )),
        ])
        smap = _extract_section_map(cache)
        path = smap[1]
        assert "Assessment" in path
        assert "Commission decision" not in path

    def test_guidelines_paragraph_footnote_rejected(self):
        """'320 Non-Horizontal Merger Guidelines, paragraph 40' is a footnote."""
        cache = self._cache([
            (1, (
                "9.4 Vertical effects\n"
                "Effects analysis.\n"
                "320 Non-Horizontal Merger Guidelines, paragraph 40."
            )),
        ])
        smap = _extract_section_map(cache)
        path = smap[1]
        assert "Vertical effects" in path
        assert "Guidelines" not in path

    def test_deep_section_numbers_still_accepted(self):
        """'9.4.3.2.2 As regards incentives' must be accepted regardless of depth."""
        cache = self._cache([
            (1, (
                "9 Effects\n"
                "9.4 Vertical effects\n"
                "9.4.3.2.2 As regards incentives\n"
                "The Commission assessed incentives."
            )),
        ])
        smap = _extract_section_map(cache)
        path = smap[1]
        assert "incentives" in path.lower()

    def test_section_number_25_accepted_26_rejected(self):
        """Section 25 is valid; a bare '26' is treated as footnote."""
        cache = self._cache([
            (1, "25 Conclusions\nSome text.\n26 References to earlier decisions."),
        ])
        smap = _extract_section_map(cache)
        path = smap[1]
        assert "Conclusions" in path
        assert "References" not in path


# ---------------------------------------------------------------------------
# TOC page exclusion
# ---------------------------------------------------------------------------

class TestTocPageExclusion:
    def _cache(self, pages: list[tuple[int, str]]) -> dict:
        return {
            "source_document_id": "doc1",
            "source_url": "https://example.com/doc.pdf",
            "page_count": len(pages),
            "pages": [{"page_number": n, "text": t} for n, t in pages],
            "extracted_at": "2026-05-23T00:00:00+00:00",
        }

    def test_is_toc_page_detects_dotted_leaders(self):
        toc = (
            "Table of Contents\n"
            "8.6 Online advertising.......................95\n"
            "8.7 Digital music............................110\n"
            "9.4 Vertical effects.........................130\n"
            "9.4.3 Ability and incentives.................135\n"
        )
        assert _is_toc_page(toc) is True

    def test_is_toc_page_rejects_normal_content(self):
        content = (
            "8.6 Online advertising\n"
            "Dr. Smith noted that online advertising differs from search."
        )
        assert _is_toc_page(content) is False

    def test_toc_page_excluded_from_candidates(self):
        """A page with dotted leaders must not appear as a candidate."""
        toc_text = (
            "Table of Contents\n"
            "8.6 Online advertising.......................95\n"
            "8.7 Digital music............................110\n"
            "9.4 Vertical effects.........................130\n"
            "9.4.3 Ability and incentives.................135\n"
        )
        content_text = (
            "8.6 Online advertising\n"
            "The Commission defines the relevant product market for online advertising."
        )
        cache = self._cache([(8, toc_text), (95, content_text)])
        candidates = _find_candidates(
            ["market", "product", "advertising", "Commission"],
            cache,
            proposition_type="product_market",
            prop_topic_words=_topic_words("Online advertising"),
        )
        page_nums = [c.page_number for c in candidates]
        assert 8 not in page_nums
        assert 95 in page_nums

    def test_normal_page_with_few_incidental_dots_included(self):
        """A content page with a couple of abbreviation dots is not excluded."""
        content = (
            "8.6 Online advertising\n"
            "Dr. Smith and Prof. Jones concluded the market is EEA-wide."
        )
        cache = self._cache([(10, content)])
        candidates = _find_candidates(
            ["advertising", "market", "Smith"],
            cache,
            proposition_type="product_market",
        )
        assert len(candidates) >= 1
        assert candidates[0].page_number == 10


# ---------------------------------------------------------------------------
# Theory-of-harm subtype detection and scoring
# ---------------------------------------------------------------------------

class TestTohSubtypeDetection:
    def test_data_advantage_detected(self):
        assert _detect_toh_subtype("Data advantage in digital advertising") == "data_advantage"

    def test_foreclosure_vertical_detected_from_wear_os(self):
        assert _detect_toh_subtype("Wear OS foreclosure app ecosystem") == "foreclosure_vertical"

    def test_foreclosure_vertical_detected_from_foreclos(self):
        assert _detect_toh_subtype("Vertical foreclosure of rival manufacturers") == "foreclosure_vertical"

    def test_horizontal_detected(self):
        assert _detect_toh_subtype("Horizontal consolidation wearables fitness OS") == "horizontal"

    def test_generic_fallback(self):
        assert _detect_toh_subtype("Some other theory") == "generic"


class TestTohSubtypeScoring:
    def _cache(self, pages: list[tuple[int, str]]) -> dict:
        return {
            "source_document_id": "doc1",
            "source_url": "https://example.com/doc.pdf",
            "page_count": len(pages),
            "pages": [{"page_number": n, "text": t} for n, t in pages],
            "extracted_at": "2026-05-23T00:00:00+00:00",
        }

    def test_data_advantage_prop_ranks_data_page_above_wear_os_page(self):
        """Without section headings, subtype signals alone must rank the data/advertising
        page above the Wear OS foreclosure page for a data-advantage proposition."""
        cache = self._cache([
            (1, (
                "Google has the ability to foreclose rivals through Wear OS. "
                "Input foreclosure of wearable device manufacturers is likely. "
                "The incentive to foreclose companion app developers exists."
            )),
            (2, (
                "Fitbit data including health and wellness data strengthens "
                "Google's position in digital advertising. Health data aggregation "
                "enables better personalisation and targeting of search advertising."
            )),
        ])
        keywords = ["Google", "Fitbit", "data", "advertising", "digital"]
        candidates = _find_candidates(
            keywords, cache,
            proposition_type="theory_of_harm",
            prop_topic_words=_topic_words("Data advantage in digital advertising"),
            prop_name="Data advantage in digital advertising",
        )
        assert len(candidates) >= 2
        assert candidates[0].page_number == 2

    def test_foreclosure_vertical_prop_ranks_wear_os_page_above_data_page(self):
        """Without section headings, subtype signals rank Wear OS page above data page
        for a foreclosure_vertical proposition."""
        cache = self._cache([
            (1, (
                "Fitbit health data aggregation strengthens Google advertising position."
            )),
            (2, (
                "Google has the ability to foreclose via Wear OS. "
                "Interoperability degradation and app gallery restrictions "
                "create incentive to foreclose companion app developers."
            )),
        ])
        keywords = ["Google", "Wear", "foreclose", "ability", "incentive"]
        candidates = _find_candidates(
            keywords, cache,
            proposition_type="theory_of_harm",
            prop_topic_words=_topic_words("Wear OS foreclosure app ecosystem"),
            prop_name="Wear OS foreclosure app ecosystem",
        )
        assert len(candidates) >= 2
        assert candidates[0].page_number == 2

    def test_horizontal_prop_classifies_foreclosure_page_as_wrong_section(self):
        """For a horizontal-consolidation proposition, foreclosure language
        triggers penalty signals that classify the candidate as likely_wrong_section."""
        cache = self._cache([
            (1, (
                "9 Competitive assessment\n"
                "9.4 Vertical effects\n"
                "9.4.3 Ability and incentives to foreclose\n"
                "Google has the ability to foreclose rival smartwatch makers "
                "via input foreclosure of Wear OS. The incentive to foreclose "
                "arises from the competitive harm to Google's wearable ecosystem."
            )),
            (2, (
                "9 Competitive assessment\n"
                "9.4 Vertical effects\n"
                "9.4.2 Wear OS access restrictions\n"
                "The Commission assessed whether Google would restrict Wear OS access "
                "and foreclose rivals. Input foreclosure by degrading interoperability "
                "of companion apps would harm rivals."
            )),
            (3, (
                "9 Competitive assessment\n"
                "9.4 Vertical effects\n"
                "9.4.1 Overview of foreclosure theory\n"
                "This section assesses the foreclosure theory. Ability to foreclose "
                "and incentive to foreclose are assessed for Wear OS rival manufacturers."
            )),
        ])
        keywords = ["Google", "wearable", "ability", "foreclose", "Commission"]
        candidates = _find_candidates(
            keywords, cache,
            proposition_type="theory_of_harm",
            prop_topic_words=_topic_words("Horizontal consolidation wearables"),
            prop_name="Horizontal consolidation wearables fitness OS",
        )
        prop_result = PropositionSearchResult(
            "toh_1", "theory_of_harm", "Horizontal consolidation wearables",
            "candidates_found", candidates=candidates,
        )
        _check_mislabelled_propositions([prop_result])
        assert prop_result.warning == "possible_mislabelled_proposition"
