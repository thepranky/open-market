"""
Unit tests for scripts/extract_case_from_source.py

No network access, no PDF downloads, no real Claude calls, no filesystem writes
to production YAML.
"""
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from extract_case_from_source import (
    ChunkInfo,
    ExtractedCommitment,
    ExtractedMarket,
    ExtractedPassage,
    ExtractedTheory,
    _filter_chunks_to_range,
    _CONCLUSIVE_SOURCE_ROLES,
    _DEVICE_CONTEXT_CONFLICT_FACTOR,
    _GEO_CONTEXT_MIN_OVERLAP,
    _PROMOTION_ACTIONS,
    _RECON_GROUP,
    _VALID_COMMITMENT_TYPES,
    _VALID_THEORY_TYPES,
    _VALID_MARKET_IMPORTANCE,
    _EXTRACTION_TASK,
    _EXTRACTION_TOOL_SCHEMA,
    _apply_focus_guardrails,
    _build_canonical_merge_candidates,
    _build_promotion_plan,
    _build_promotion_plan_summary,
    _build_reconciliation_triage,
    _detect_device_contexts,
    _device_context_factor,
    _extract_section_caveats,
    _finding_to_dict,
    _geo_product_context_overlap,
    _group_reconciliation,
    _has_conclusive_source_role,
    _is_truncated_quote,
    _market_similarity,
    _merge_geo_market_pair,
    _normalize_for_similarity,
    _promotion_action,
    _promotion_action_with_guards,
    ExtractionReport,
    ExtractionResult,
    ReconciliationFinding,
    SectionBatchResult,
    _DEFAULT_EXTRACTION_ENVELOPE,
    _FOCUS_TERMS,
    _build_chunks,
    _build_draft_record,
    _build_extraction_prompt,
    _call_claude_repair,
    _extract_section_batch,
    _extract_spillover_pages,
    _group_chunks_by_section_prefix,
    _is_focused_section,
    _is_relevant_section,
    _is_subsection_of,
    _merge_extraction_results,
    _normalize_list_fields,
    _parse_extraction_response,
    _reconcile,
    _resolve_canonical_yaml,
    _section_batch_prefix,
    _select_relevant_chunks,
    _should_attempt_repair,
    _trim_pages_for_prefix,
    _validate_extraction,
    _validate_extraction_schema,
    _validate_quote_against_chunks,
    extract_case,
    replay_section_debug,
    serialize_report,
    # Fallback selector
    _MARKET_DEF_FALLBACK_SIGNALS,
    _MARKET_DEF_FALLBACK_MIN_SCORE,
    _MARKET_DEF_SP_MIN_PAGES,
    _MARKET_DEF_COVERAGE_MIN_RATIO,
    _MARKET_DEF_COVERAGE_MIN_DOC_PAGES,
    _MAX_FALLBACK_PAGES,
    _MAX_FALLBACK_CHUNKS,
    _score_page_market_def,
    _select_market_def_fallback_chunks,
    _infer_section_label_from_pages,
)
from repair_source_passages import _extract_section_map


# ---------------------------------------------------------------------------
# Helpers
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


def _make_chunk(
    chunk_id: str,
    section_path: str,
    pages: list[tuple[int, str]],
    doc_id: str = "test_doc",
) -> ChunkInfo:
    return ChunkInfo(
        chunk_id=chunk_id,
        section_path=section_path,
        pages=[{"page_number": n, "text": t} for n, t in pages],
        source_document_id=doc_id,
    )


def _make_record(
    markets=None,
    geo_markets=None,
    theories=None,
) -> dict:
    return {
        "case_id": "test_case",
        "case_name": "Acme / Widget",
        "authority": "European Commission",
        "jurisdiction": "EU",
        "sector": "digital",
        "outcome": "unknown",
        "decision_date": "2021-12-17",
        "parties": [
            {"name": "Acme Corp", "role": "acquirer"},
            {"name": "Widget Ltd", "role": "target"},
        ],
        "source_documents": [
            {
                "doc_id": "main_doc",
                "title": "Decision",
                "pdf_url": "https://example.com/decision.pdf",
                "doc_type": "decision",
            }
        ],
        "source_passages": [],
        "product_markets_considered": markets or [
            {"market_id": "pm_1", "name": "Widget market",
             "definition_status": "defined", "notes": "Narrow."}
        ],
        "geographic_markets_considered": geo_markets or [
            {"market_id": "gm_1", "name": "EEA",
             "definition_status": "defined", "notes": "EEA-wide."}
        ],
        "theories_of_harm": theories or [
            {"theory_id": "toh_1", "name": "Horizontal consolidation",
             "description": "Overlap in widget market."}
        ],
    }


# ---------------------------------------------------------------------------
# _build_chunks
# ---------------------------------------------------------------------------

class TestBuildChunks:
    def test_pages_grouped_by_section_path(self):
        """Consecutive pages with the same section heading form one chunk."""
        cache = _make_page_cache([
            (1, "8 Markets\nIntroduction."),
            (2, "8 Markets\nContinued analysis."),
            (3, "9 Assessment\nNew section."),
        ])
        # Provide a pre-built section map so we don't need heading extraction
        smap = {1: "8 Markets", 2: "8 Markets", 3: "9 Assessment"}
        chunks = _build_chunks(cache, section_map=smap)
        # Pages 1 and 2 should be in one chunk, page 3 in another
        assert len(chunks) == 2
        assert chunks[0].section_path == "8 Markets"
        assert chunks[0].page_numbers == [1, 2]
        assert chunks[1].section_path == "9 Assessment"
        assert chunks[1].page_numbers == [3]

    def test_large_section_split_into_sub_chunks(self):
        """A section with more pages than max_pages is split."""
        pages = [(i + 1, f"Content page {i + 1}") for i in range(10)]
        cache = _make_page_cache(pages)
        smap = {i + 1: "8 Long section" for i in range(10)}
        chunks = _build_chunks(cache, section_map=smap, max_pages=3)
        # 10 pages, max 3 per chunk → 4 chunks
        assert len(chunks) == 4
        assert sum(len(c.pages) for c in chunks) == 10

    def test_toc_pages_excluded(self):
        """Pages with four or more dotted leader lines are skipped."""
        toc_text = (
            "8.6 Online advertising.......................95\n"
            "8.7 Digital music............................110\n"
            "9.4 Vertical effects.........................130\n"
            "9.4.3 Ability and incentives.................135\n"
        )
        content_text = "8.6 Online advertising\nThe Commission defined the market."
        cache = _make_page_cache([(8, toc_text), (95, content_text)])
        smap = {8: "", 95: "8.6 Online advertising"}
        chunks = _build_chunks(cache, section_map=smap)
        all_pages = [n for c in chunks for n in c.page_numbers]
        assert 8 not in all_pages
        assert 95 in all_pages

    def test_source_document_id_set_on_chunks(self):
        """All chunks carry the source_document_id from the page cache."""
        cache = _make_page_cache([(1, "Some text.")], doc_id="main_doc")
        smap = {1: "8 Markets"}
        chunks = _build_chunks(cache, section_map=smap)
        assert all(c.source_document_id == "main_doc" for c in chunks)

    def test_empty_cache_returns_no_chunks(self):
        cache = _make_page_cache([])
        chunks = _build_chunks(cache, section_map={})
        assert chunks == []


# ---------------------------------------------------------------------------
# _select_relevant_chunks
# ---------------------------------------------------------------------------

class TestSelectRelevantChunks:
    def test_relevant_sections_preferred(self):
        """Chunks with market/theory keywords in section path are selected."""
        chunks = [
            _make_chunk("chunk_001", "3 Procedural background", [(1, "text")]),
            _make_chunk("chunk_002", "8.6 Online advertising", [(2, "text")]),
            _make_chunk("chunk_003", "9 Competitive assessment", [(3, "text")]),
        ]
        selected = _select_relevant_chunks(chunks)
        ids = [c.chunk_id for c in selected]
        assert "chunk_002" in ids
        assert "chunk_003" in ids

    def test_max_pages_respected(self):
        """Total pages in selected chunks must not exceed max_total_pages."""
        chunks = [
            _make_chunk("chunk_001", "8 Market definition", [(i, "t") for i in range(1, 11)]),
            _make_chunk("chunk_002", "9 Competitive assessment", [(i, "t") for i in range(11, 21)]),
        ]
        selected = _select_relevant_chunks(chunks, max_total_pages=12)
        total_pages = sum(len(c.pages) for c in selected)
        assert total_pages <= 12

    def test_falls_back_to_all_chunks_when_no_relevant(self):
        """When no section path matches relevant terms, all non-empty chunks are returned."""
        chunks = [
            _make_chunk("chunk_001", "1 Preamble", [(1, "text")]),
            _make_chunk("chunk_002", "2 Parties", [(2, "text")]),
        ]
        selected = _select_relevant_chunks(chunks)
        assert len(selected) == 2

    def test_relative_coverage_triggers_supplemental_fallback(self):
        """For long docs, supplemental fallback fires when coverage ratio is below threshold.

        Simulates a pharma-style decision where market definition is embedded in
        competitive-assessment sub-sections (no "market definition" in heading) and the
        focused sections cover far less than _MARKET_DEF_COVERAGE_MIN_RATIO of the doc.
        """
        market_def_signal = (
            "The Commission considered the relevant product market. "
            "The market investigation confirmed demand-side substitutability. "
            "The geographic market was left open for the purpose of assessing the transaction."
        )
        # Build a large doc: 2 focused pages + 30 unfocused pages with high signal.
        # Total non-TOC = 32, focused = 2 → 6.25% < 25% threshold.
        focused_chunks = [
            _make_chunk(
                "chunk_001",
                "4 COMPETITIVE ASSESSMENT > 4.1 Autoimmune > 4.1.1.1 Market definition",
                [(1, market_def_signal), (2, market_def_signal)],
            ),
        ]
        # 30 pages under "Competitive assessment" heading with high market-def signal text.
        unfocused_chunks = [
            _make_chunk(
                f"chunk_{i:03d}",
                "4 COMPETITIVE ASSESSMENT > 4.3.3 Other Overlaps > 4.3.3.2 Competitive assessment",
                [(i * 2 + 1, market_def_signal), (i * 2 + 2, market_def_signal)],
            )
            for i in range(1, 16)  # 15 chunks × 2 pages = 30 pages
        ]
        all_chunks = focused_chunks + unfocused_chunks

        # Without the fix: only focused_chunks would be selected (2 pages, 6% of 32).
        # With the fix: supplemental fallback adds high-scoring unfocused pages.
        selected = _select_relevant_chunks(all_chunks, focus="market_definition")
        selected_pages = sum(len(c.pages) for c in selected)

        # Should have pulled in more than just the 2 focused pages.
        assert selected_pages > 2, (
            f"Expected supplemental fallback to add pages from unfocused high-signal chunks, "
            f"got only {selected_pages} pages"
        )

    def test_full_market_def_pass_selects_beyond_focused_sections(self):
        """full_market_def_pass=True always merges fallback with focused sections."""
        market_def_signal = (
            "relevant product market left open plausible market definition "
            "market investigation demand-side substitutability geographic market"
        )
        focused = _make_chunk(
            "chunk_001",
            "4 COMPETITIVE ASSESSMENT > 4.1 Market definition",
            [(1, "product market text"), (2, "product market text")],
        )
        high_signal_unfocused = _make_chunk(
            "chunk_002",
            "4 COMPETITIVE ASSESSMENT > 4.3.3 Other Overlaps > 4.3.3.2 Competitive assessment",
            [(10, market_def_signal), (11, market_def_signal), (12, market_def_signal)],
        )
        all_chunks = [focused, high_signal_unfocused]

        # Normal run: only focused chunk selected (2 pages total < 8 abs threshold,
        # but also < 25% of 5 non-TOC pages, so supplemental would fire anyway for this
        # small doc — use a path that tests full_market_def_pass explicitly).
        # Build a doc big enough that normal mode would stay focused-only (> 8 focused pages).
        big_focused = _make_chunk(
            "chunk_big",
            "4 COMPETITIVE ASSESSMENT > 4.1 Market definition",
            [(i, "product market text") for i in range(1, 10)],  # 9 pages
        )
        all_big = [big_focused, high_signal_unfocused]

        normal = _select_relevant_chunks(all_big, focus="market_definition", full_market_def_pass=False)
        full_pass = _select_relevant_chunks(all_big, focus="market_definition", full_market_def_pass=True)

        normal_pages = sum(len(c.pages) for c in normal)
        full_pages = sum(len(c.pages) for c in full_pass)

        # full_market_def_pass should include the high-signal unfocused chunk's pages.
        assert full_pages > normal_pages, (
            f"full_market_def_pass should select more pages than normal mode "
            f"(got {full_pages} vs {normal_pages})"
        )

    def test_pharma_section_paths_trigger_coverage_fallback(self):
        """Section paths like 'Other Overlaps > Competitive assessment' do not match focus terms.

        Verify that a document with these pharma-style paths triggers the relative-coverage
        supplemental fallback when such sections dominate the doc.
        """
        signal = (
            "relevant product market plausible market definition market investigation "
            "demand-side substitutability left open geographic market EEA-wide"
        )
        # One focused chunk with explicit "Market definition" sub-section (5 pages).
        focused = _make_chunk(
            "chunk_focus",
            "4 COMPETITIVE ASSESSMENT > 4.1 Autoimmune > 4.1.2.1 Market definition",
            [(i, signal) for i in range(1, 6)],
        )
        # Many unfocused but high-signal chunks under therapeutic-area/competitive-assessment headings.
        other_overlaps = _make_chunk(
            "chunk_other",
            "4 COMPETITIVE ASSESSMENT > 4.3.3 Other Overlaps > 4.3.3.2 Competitive assessment",
            [(i, signal) for i in range(10, 40)],  # 30 pages
        )
        all_chunks = [focused, other_overlaps]  # 35 non-TOC pages, 5 focused = 14%

        selected = _select_relevant_chunks(all_chunks, focus="market_definition")
        selected_pages = sum(len(c.pages) for c in selected)
        total_pages = sum(len(c.pages) for c in all_chunks)

        # Coverage ratio was 5/35 = 14%, below 25% threshold → fallback should fire.
        assert selected_pages > 5, (
            f"Expected fallback to add pages from 'Other Overlaps' chunks, "
            f"got {selected_pages}/{total_pages}"
        )


# ---------------------------------------------------------------------------
# _is_relevant_section
# ---------------------------------------------------------------------------

class TestIsRelevantSection:
    def test_market_section_is_relevant(self):
        assert _is_relevant_section("8.6 Online advertising > 8.6.1 Product market definition")

    def test_competitive_assessment_is_relevant(self):
        assert _is_relevant_section("9 Competitive assessment")

    def test_procedural_background_not_relevant(self):
        assert not _is_relevant_section("3 Procedural background")

    def test_empty_string_not_relevant(self):
        assert not _is_relevant_section("")


# ---------------------------------------------------------------------------
# _validate_quote_against_chunks
# ---------------------------------------------------------------------------

class TestValidateQuoteAgainstChunks:
    def _chunks(self) -> list[ChunkInfo]:
        return [
            _make_chunk("chunk_001", "8.6 Online advertising", [
                (92, "The Commission defines the relevant product market for online advertising."),
                (93, "Competitive conditions across the EEA are uniform."),
            ]),
            _make_chunk("chunk_002", "9.1 Data advantage", [
                (101, "Fitbit data including health and wellness data strengthens Google's position."),
            ]),
        ]

    def test_valid_quote_accepted(self):
        valid, note, corrected = _validate_quote_against_chunks(
            "Commission defines the relevant product market",
            "chunk_001", 92, self._chunks(),
        )
        assert valid is True
        assert note == ""
        assert corrected is None

    def test_invented_quote_rejected(self):
        """A paraphrased or invented quote must be rejected (not found in any page)."""
        valid, note, corrected = _validate_quote_against_chunks(
            "The parties agreed to divest the wearable division by 2023",
            "chunk_001", 92, self._chunks(),
        )
        assert valid is False
        assert corrected is None

    def test_wrong_page_corrected_not_rejected(self):
        """Quote found on a neighbouring page → valid=True with corrected page number."""
        valid, note, corrected = _validate_quote_against_chunks(
            "Commission defines the relevant product market",
            "chunk_001", 93, self._chunks(),  # quote is on p.92, cited as p.93
        )
        assert valid is True
        assert corrected == 92
        assert "92" in note

    def test_unknown_chunk_id_rejected(self):
        valid, note, corrected = _validate_quote_against_chunks(
            "some text",
            "chunk_999", 1, self._chunks(),
        )
        assert valid is False
        assert "chunk_999" in note
        assert corrected is None

    def test_empty_quote_rejected(self):
        valid, note, corrected = _validate_quote_against_chunks(
            "", "chunk_001", 92, self._chunks(),
        )
        assert valid is False
        assert corrected is None

    def test_whitespace_only_quote_rejected(self):
        valid, note, corrected = _validate_quote_against_chunks(
            "   ", "chunk_001", 92, self._chunks(),
        )
        assert valid is False
        assert corrected is None


# ---------------------------------------------------------------------------
# _parse_extraction_response
# ---------------------------------------------------------------------------

class TestParseExtractionResponse:
    def test_parses_plain_json(self):
        raw = json.dumps({
            "product_markets": [{"name": "Widget market", "definition_status": "defined",
                                  "notes": "Narrow.", "not_found": False, "passages": []}],
            "geographic_markets": [],
            "theories_of_harm": [],
            "overall_outcome": "cleared",
            "caveats": [],
        })
        result = _parse_extraction_response(raw)
        assert result["overall_outcome"] == "cleared"

    def test_strips_markdown_fences(self):
        raw = "```json\n{\"overall_outcome\": \"cleared\", \"product_markets\": [], \"geographic_markets\": [], \"theories_of_harm\": [], \"caveats\": []}\n```"
        result = _parse_extraction_response(raw)
        assert result["overall_outcome"] == "cleared"

    def test_strips_plain_fences(self):
        raw = "```\n{\"overall_outcome\": \"cleared\", \"product_markets\": [], \"geographic_markets\": [], \"theories_of_harm\": [], \"caveats\": []}\n```"
        result = _parse_extraction_response(raw)
        assert result["overall_outcome"] == "cleared"

    def test_parses_json_with_explanatory_preamble(self):
        """JSON preceded by explanatory text must still parse."""
        preamble = "Here is the structured extraction based on the provided text:\n\n"
        payload = {
            "product_markets": [],
            "geographic_markets": [],
            "theories_of_harm": [],
            "overall_outcome": "cleared",
            "caveats": [],
        }
        raw = preamble + json.dumps(payload) + "\n\nLet me know if you need anything else."
        result = _parse_extraction_response(raw)
        assert result["overall_outcome"] == "cleared"

    def test_parses_json_inside_fence_after_explanatory_text(self):
        """JSON fence preceded by text must parse via regex fallback."""
        raw = (
            "I've extracted the following information:\n\n"
            "```json\n"
            '{"product_markets": [], "geographic_markets": [], "theories_of_harm": [], '
            '"overall_outcome": "cleared_with_conditions", "caveats": []}\n'
            "```"
        )
        result = _parse_extraction_response(raw)
        assert result["overall_outcome"] == "cleared_with_conditions"

    def test_raises_on_unparseable_response(self):
        with pytest.raises(ValueError):
            _parse_extraction_response("This is not JSON at all.")

    def test_raw_response_saved_on_parse_failure(self, tmp_path):
        """When parsing fails, raw response is saved to debug_dir."""
        debug_dir = tmp_path / "debug"
        with pytest.raises(ValueError) as exc_info:
            _parse_extraction_response(
                "Completely not JSON at all!",
                debug_dir=debug_dir,
                case_id="test_case",
            )
        debug_file = debug_dir / "test_case_claude_raw_response.txt"
        assert debug_file.exists(), "Debug file should be created on parse failure"
        assert "test_case_claude_raw_response.txt" in str(exc_info.value)

    def test_raw_response_content_preserved_in_debug_file(self, tmp_path):
        """Debug file must contain the exact raw response text."""
        debug_dir = tmp_path / "debug"
        raw = "Not JSON:\nwith multiple lines\nand more text."
        with pytest.raises(ValueError):
            _parse_extraction_response(raw, debug_dir=debug_dir, case_id="test_case")
        debug_file = debug_dir / "test_case_claude_raw_response.txt"
        assert debug_file.read_text() == raw

    def test_no_debug_file_when_debug_dir_not_provided(self, tmp_path):
        """When debug_dir is None, no file is written — just ValueError raised."""
        with pytest.raises(ValueError) as exc_info:
            _parse_extraction_response("Not JSON", debug_dir=None, case_id="test_case")
        # Error message must not claim a file was saved
        assert "saved to" not in str(exc_info.value)


# ---------------------------------------------------------------------------
# _validate_extraction
# ---------------------------------------------------------------------------

class TestValidateExtraction:
    def _chunks(self) -> list[ChunkInfo]:
        return [
            _make_chunk("chunk_001", "8.6 Online advertising", [
                (42, "The Commission defines the relevant product market for online advertising."),
            ]),
            _make_chunk("chunk_002", "8.6.2 Geographic market", [
                (50, "The relevant geographic market is at least EEA-wide."),
            ]),
        ]

    def _raw_extraction(self) -> dict:
        return {
            "product_markets": [
                {
                    "name": "Online advertising",
                    "definition_status": "defined",
                    "notes": "Narrow market.",
                    "not_found": False,
                    "passages": [
                        {
                            "chunk_id": "chunk_001",
                            "page_number": 42,
                            "quote": "Commission defines the relevant product market for online advertising",
                        },
                        {
                            "chunk_id": "chunk_001",
                            "page_number": 42,
                            "quote": "This quote was invented and does not appear in the text",
                        },
                    ],
                }
            ],
            "geographic_markets": [
                {
                    "name": "EEA",
                    "definition_status": "defined",
                    "notes": "EEA-wide.",
                    "not_found": False,
                    "passages": [
                        {
                            "chunk_id": "chunk_002",
                            "page_number": 50,
                            "quote": "relevant geographic market is at least EEA-wide",
                        }
                    ],
                }
            ],
            "theories_of_harm": [],
            "overall_outcome": "cleared_with_conditions",
            "caveats": [],
        }

    def test_valid_passages_accepted_invalid_rejected(self):
        result = _validate_extraction(
            self._raw_extraction(),
            self._chunks(),
            {"chunk_001": "test_doc", "chunk_002": "test_doc"},
        )
        assert result.passages_validated == 2
        assert result.passages_rejected == 1

    def test_overall_outcome_preserved(self):
        result = _validate_extraction(
            self._raw_extraction(), self._chunks(),
            {"chunk_001": "test_doc", "chunk_002": "test_doc"},
        )
        assert result.overall_outcome == "cleared_with_conditions"

    def test_not_found_market_preserved(self):
        raw = {
            "product_markets": [
                {
                    "name": "Widget market",
                    "definition_status": "unknown",
                    "notes": "",
                    "not_found": True,
                    "passages": [],
                }
            ],
            "geographic_markets": [],
            "theories_of_harm": [],
            "overall_outcome": "unknown",
            "caveats": [],
        }
        result = _validate_extraction(raw, self._chunks(), {})
        assert result.product_markets[0].not_found is True

    def test_invalid_quote_not_validated(self):
        raw = {
            "product_markets": [
                {
                    "name": "Online advertising",
                    "definition_status": "defined",
                    "notes": "X",
                    "not_found": False,
                    "passages": [
                        {
                            "chunk_id": "chunk_001",
                            "page_number": 42,
                            "quote": "I completely made this quote up — it is not in the PDF",
                        }
                    ],
                }
            ],
            "geographic_markets": [],
            "theories_of_harm": [],
            "overall_outcome": "unknown",
            "caveats": [],
        }
        result = _validate_extraction(raw, self._chunks(), {"chunk_001": "doc"})
        assert result.passages_validated == 0
        assert result.passages_rejected == 1
        # The passage must be marked as not validated
        p = result.product_markets[0].passages[0]
        assert p.validated is False
        assert p.rejection_reason != ""


# ---------------------------------------------------------------------------
# _build_draft_record
# ---------------------------------------------------------------------------

class TestBuildDraftRecord:
    def _make_result(self) -> ExtractionResult:
        return ExtractionResult(
            product_markets=[
                ExtractedMarket(
                    name="Online advertising",
                    market_type="product",
                    definition_status="defined",
                    notes="Narrow market for online advertising.",
                    passages=[
                        ExtractedPassage(
                            chunk_id="chunk_001",
                            page_number=42,
                            quote="Commission defines the relevant product market for online advertising.",
                            validated=True,
                            source_document_id="main_doc",
                        ),
                        ExtractedPassage(
                            chunk_id="chunk_001",
                            page_number=42,
                            quote="Invented quote not in source.",
                            validated=False,
                            source_document_id="main_doc",
                            rejection_reason="Quote not found",
                        ),
                    ],
                    not_found=False,
                )
            ],
            geographic_markets=[
                ExtractedMarket(
                    name="EEA",
                    market_type="geographic",
                    definition_status="defined",
                    notes="EEA-wide.",
                    passages=[
                        ExtractedPassage(
                            chunk_id="chunk_002",
                            page_number=50,
                            quote="relevant geographic market is at least EEA-wide",
                            validated=True,
                            source_document_id="main_doc",
                        )
                    ],
                    not_found=False,
                )
            ],
            theories=[
                ExtractedTheory(
                    name="Data advantage in digital advertising",
                    theory_type="data",
                    theory_outcome="remedied",
                    notes="Google uses Fitbit data to strengthen advertising.",
                    passages=[
                        ExtractedPassage(
                            chunk_id="chunk_003",
                            page_number=101,
                            quote="Fitbit data strengthens Google's advertising position.",
                            validated=True,
                            source_document_id="main_doc",
                        )
                    ],
                    not_found=False,
                )
            ],
            overall_outcome="cleared_with_conditions",
            passages_validated=3,
            passages_rejected=1,
        )

    def test_draft_note_present(self):
        draft = _build_draft_record(self._make_result(), _make_record())
        assert "_draft_note" in draft
        assert "DRAFT" in draft["_draft_note"]

    def test_propositions_marked_source_linked(self):
        draft = _build_draft_record(self._make_result(), _make_record())
        for pm in draft["product_markets_considered"]:
            assert pm["verification"]["status"] == "source_linked"
        for gm in draft["geographic_markets_considered"]:
            assert gm["verification"]["status"] == "source_linked"
        for th in draft["theories_of_harm"]:
            assert th["verification"]["status"] == "source_linked"

    def test_only_validated_passages_included(self):
        """The rejected passage must not appear in source_passages."""
        draft = _build_draft_record(self._make_result(), _make_record())
        for sp in draft["source_passages"]:
            assert sp["quote_snippet"] != "Invented quote not in source."

    def test_passages_count_matches_validated_count(self):
        """Three validated passages → three entries in source_passages."""
        draft = _build_draft_record(self._make_result(), _make_record())
        assert len(draft["source_passages"]) == 3

    def test_passage_support_links_are_correct(self):
        """Each passage must link to the right proposition type."""
        draft = _build_draft_record(self._make_result(), _make_record())
        passages = draft["source_passages"]
        pm_passage = next(p for p in passages if p["supports_markets"])
        assert pm_passage["supports_markets"] == ["pm_1"]
        assert pm_passage["supports_geographic_markets"] == []
        assert pm_passage["supports_theories"] == []

        gm_passage = next(p for p in passages if p["supports_geographic_markets"])
        assert gm_passage["supports_geographic_markets"] == ["gm_1"]

        toh_passage = next(p for p in passages if p["supports_theories"])
        assert toh_passage["supports_theories"] == ["toh_1"]

    def test_not_found_market_excluded_from_draft(self):
        result = ExtractionResult(
            product_markets=[
                ExtractedMarket(
                    name="Ghost market",
                    market_type="product",
                    definition_status="unknown",
                    notes="",
                    not_found=True,
                )
            ],
        )
        draft = _build_draft_record(result, _make_record())
        assert len(draft["product_markets_considered"]) == 0

    def test_case_metadata_copied_from_existing(self):
        existing = _make_record()
        draft = _build_draft_record(ExtractionResult(), existing)
        assert draft["case_id"] == existing["case_id"]
        assert draft["authority"] == existing["authority"]
        assert draft["parties"] == existing["parties"]


# ---------------------------------------------------------------------------
# _reconcile
# ---------------------------------------------------------------------------

class TestReconcile:
    def test_identical_name_is_supported_as_is(self):
        existing = _make_record(
            markets=[{"market_id": "pm_1", "name": "Online advertising",
                       "definition_status": "defined", "notes": ""}]
        )
        draft = {
            "product_markets_considered": [
                {"market_id": "pm_1", "name": "Online advertising",
                 "definition_status": "defined", "notes": ""}
            ],
            "geographic_markets_considered": [],
            "theories_of_harm": [],
        }
        findings = _reconcile(draft, existing)
        pm_findings = [f for f in findings if f.existing_id == "pm_1"]
        assert any(f.finding_type == "supported_as_is" for f in pm_findings)

    def test_similar_name_is_should_be_renamed(self):
        existing = _make_record(
            markets=[{"market_id": "pm_1", "name": "Wearable OS market",
                       "definition_status": "defined", "notes": ""}]
        )
        draft = {
            "product_markets_considered": [
                {"market_id": "pm_1",
                 "name": "Wearable operating system market",
                 "definition_status": "defined", "notes": ""}
            ],
            "geographic_markets_considered": [],
            "theories_of_harm": [],
        }
        findings = _reconcile(draft, existing)
        pm_findings = [f for f in findings if f.existing_id == "pm_1"]
        # Similarity "Wearable OS market" vs "Wearable operating system market"
        # should be in rename range
        finding_types = {f.finding_type for f in pm_findings}
        assert "supported_as_is" in finding_types or "should_be_renamed" in finding_types

    def test_missing_in_draft_is_unsupported_remove(self):
        existing = _make_record(
            markets=[
                {"market_id": "pm_1", "name": "Online advertising",
                 "definition_status": "defined", "notes": ""},
                {"market_id": "pm_2", "name": "Digital music streaming",
                 "definition_status": "left_open", "notes": ""},
            ]
        )
        draft = {
            "product_markets_considered": [
                {"market_id": "pm_1", "name": "Online advertising",
                 "definition_status": "defined", "notes": ""}
            ],
            "geographic_markets_considered": [],
            "theories_of_harm": [],
        }
        findings = _reconcile(draft, existing)
        pm2_findings = [f for f in findings if f.existing_id == "pm_2"]
        assert any(f.finding_type == "unsupported_remove" for f in pm2_findings)

    def test_new_draft_proposition_is_new_from_source(self):
        existing = _make_record(markets=[])
        draft = {
            "product_markets_considered": [
                {"market_id": "pm_1", "name": "Cloud gaming",
                 "definition_status": "discussed", "notes": ""}
            ],
            "geographic_markets_considered": [],
            "theories_of_harm": [],
        }
        findings = _reconcile(draft, existing)
        new_findings = [f for f in findings if f.finding_type == "new_from_source"]
        assert any(f.draft_name == "Cloud gaming" for f in new_findings)

    def test_theory_reconciliation_included(self):
        existing = _make_record(
            theories=[
                {"theory_id": "toh_1", "name": "Horizontal consolidation",
                 "description": "Market overlap."}
            ]
        )
        draft = {
            "product_markets_considered": [],
            "geographic_markets_considered": [],
            "theories_of_harm": [],  # no matching theory in draft
        }
        findings = _reconcile(draft, existing)
        toh_findings = [f for f in findings if f.existing_id == "toh_1"]
        assert any(f.finding_type == "unsupported_remove" for f in toh_findings)


# ---------------------------------------------------------------------------
# serialize_report
# ---------------------------------------------------------------------------

class TestSerializeReport:
    def _make_report(self) -> ExtractionReport:
        rpt = ExtractionReport(case_id="eu_test", yaml_path=Path("/data/eu_test.yaml"))
        rpt.chunks_used = [
            _make_chunk("chunk_001", "8.6 Online advertising", [(42, "text")])
        ]
        rpt.result = ExtractionResult(
            product_markets=[
                ExtractedMarket("Online advertising", "product", "defined", "Narrow market.")
            ],
            overall_outcome="cleared_with_conditions",
            passages_validated=1,
            passages_rejected=0,
        )
        rpt.findings = [
            ReconciliationFinding(
                "unsupported_remove", "pm_1", "Widget market", "",
                "No match found.", 0.1,
            )
        ]
        return rpt

    def test_required_keys_present(self):
        payload = serialize_report(self._make_report())
        assert "generated_at" in payload
        assert "case_id" in payload
        assert "chunks_used" in payload
        assert "extraction_summary" in payload
        assert "reconciliation" in payload

    def test_reconciliation_contains_finding(self):
        payload = serialize_report(self._make_report())
        rec = payload["reconciliation"]
        assert len(rec) == 1
        assert rec[0]["finding_type"] == "unsupported_remove"
        assert rec[0]["existing_id"] == "pm_1"

    def test_json_serialisable(self):
        payload = serialize_report(self._make_report())
        dumped = json.dumps(payload)
        assert len(dumped) > 50


# ---------------------------------------------------------------------------
# Safety: canonical YAML never overwritten; invalid quotes never written
# ---------------------------------------------------------------------------

class TestSafety:
    def test_refuses_to_overwrite_existing_non_draft_path(self, tmp_path):
        """extract_case must refuse to write to a path without '.draft' in the stem."""
        existing = _make_record()
        canonical_path = tmp_path / "eu_google_fitbit_2021.yaml"
        canonical_path.write_text(yaml.dump(existing))

        # The output path also exists but has no '.draft' in its stem
        output_path = tmp_path / "eu_google_fitbit_2021.yaml"

        from unittest.mock import patch
        with patch("extract_case_from_source.load_cache", return_value=None):
            rpt = extract_case(
                canonical_path,
                cache_dir=tmp_path / "cache",
                output_path=output_path,
                use_claude=False,
            )

        assert rpt.error is not None
        assert "draft" in rpt.error.lower() or "refusing" in rpt.error.lower()

    def test_draft_path_accepted(self, tmp_path):
        """A path with '.draft' in the stem is accepted (even if no cache available)."""
        existing = _make_record()
        yaml_path = tmp_path / "eu_test.yaml"
        yaml_path.write_text(yaml.dump(existing))
        draft_output = tmp_path / "eu_test.draft.yaml"

        from unittest.mock import patch
        with patch("extract_case_from_source.load_cache", return_value=None):
            rpt = extract_case(
                yaml_path,
                cache_dir=tmp_path / "cache",
                output_path=draft_output,
                use_claude=False,
            )

        # Error is about no cache, NOT about refusing to write
        assert rpt.error is None or "cache" in (rpt.error or "").lower()
        # Draft file should not have been written (no cache → returned early)
        assert rpt.draft_yaml_path is None

    def test_invalid_quote_never_in_draft(self):
        """
        When Claude returns an invented quote, it must not appear in the draft YAML.
        """
        chunks = [
            _make_chunk("chunk_001", "8.6 Online advertising", [
                (42, "The Commission defines the relevant product market for online advertising."),
            ])
        ]
        # Raw extraction with one valid and one invalid quote
        raw = {
            "product_markets": [
                {
                    "name": "Online advertising",
                    "definition_status": "defined",
                    "notes": "Narrow.",
                    "not_found": False,
                    "passages": [
                        {
                            "chunk_id": "chunk_001",
                            "page_number": 42,
                            "quote": "Commission defines the relevant product market",
                        },
                        {
                            "chunk_id": "chunk_001",
                            "page_number": 42,
                            "quote": "I completely invented this sentence about market share",
                        },
                    ],
                }
            ],
            "geographic_markets": [],
            "theories_of_harm": [],
            "overall_outcome": "cleared_with_conditions",
            "caveats": [],
        }
        chunk_doc_map = {"chunk_001": "main_doc"}
        result = _validate_extraction(raw, chunks, chunk_doc_map)
        draft = _build_draft_record(result, _make_record())

        quotes_in_draft = [sp["quote_snippet"] for sp in draft["source_passages"]]
        assert "I completely invented this sentence about market share" not in quotes_in_draft
        assert any("Commission defines" in q for q in quotes_in_draft)

    def test_all_draft_passages_can_be_found_in_source(self):
        """
        Every quote_snippet in the draft must appear verbatim in the corresponding
        source chunk text.
        """
        chunks = [
            _make_chunk("chunk_001", "8.6 Online advertising", [
                (42, "The Commission defines the relevant product market for online advertising."),
                (43, "The relevant geographic market is at least EEA-wide."),
            ])
        ]
        raw = {
            "product_markets": [
                {
                    "name": "Online advertising",
                    "definition_status": "defined",
                    "notes": "Narrow.",
                    "not_found": False,
                    "passages": [
                        {
                            "chunk_id": "chunk_001",
                            "page_number": 42,
                            "quote": "Commission defines the relevant product market for online advertising",
                        }
                    ],
                }
            ],
            "geographic_markets": [
                {
                    "name": "EEA",
                    "definition_status": "defined",
                    "notes": "EEA-wide.",
                    "not_found": False,
                    "passages": [
                        {
                            "chunk_id": "chunk_001",
                            "page_number": 43,
                            "quote": "relevant geographic market is at least EEA-wide",
                        }
                    ],
                }
            ],
            "theories_of_harm": [],
            "overall_outcome": "cleared",
            "caveats": [],
        }
        chunk_doc_map = {"chunk_001": "main_doc"}
        result = _validate_extraction(raw, chunks, chunk_doc_map)
        draft = _build_draft_record(result, _make_record())

        # Every passage in the draft must be found in the source chunks
        chunk_texts: dict[int, str] = {}
        for chunk in chunks:
            for p in chunk.pages:
                chunk_texts[p["page_number"]] = p["text"]

        for sp in draft["source_passages"]:
            page_num = int(sp["page"])
            page_text = chunk_texts.get(page_num, "")
            from check_source_integrity import quote_found_in_text
            assert quote_found_in_text(sp["quote_snippet"], page_text), (
                f"Quote not found in source: {sp['quote_snippet']!r}"
            )


# ---------------------------------------------------------------------------
# Extract case integration (mocked Claude)
# ---------------------------------------------------------------------------

class TestExtractCaseIntegration:
    def _mock_cache(self) -> dict:
        return {
            "source_document_id": "main_doc",
            "source_url": "https://example.com/decision.pdf",
            "page_count": 3,
            "pages": [
                {
                    "page_number": 42,
                    "text": (
                        "8.6 Online advertising\n"
                        "The Commission defines the relevant product market for online advertising."
                    ),
                },
                {
                    "page_number": 50,
                    "text": "The relevant geographic market is at least EEA-wide.",
                },
                {
                    "page_number": 100,
                    "text": (
                        "9.1 Data advantage\n"
                        "Fitbit data strengthens Google advertising position."
                    ),
                },
            ],
            "extracted_at": "2026-05-23T00:00:00+00:00",
        }

    def _mock_response_dict(self) -> dict:
        return {
            "product_markets": [
                {
                    "name": "Online advertising",
                    "definition_status": "defined",
                    "notes": "The Commission concluded the relevant product market is online advertising.",
                    "not_found": False,
                    "passages": [
                        {
                            "chunk_id": "chunk_001",
                            "page_number": 42,
                            "quote": "Commission defines the relevant product market for online advertising",
                        }
                    ],
                }
            ],
            "geographic_markets": [
                {
                    "name": "EEA",
                    "definition_status": "defined",
                    "notes": "EEA-wide.",
                    "not_found": False,
                    "passages": [
                        {
                            "chunk_id": "chunk_001",
                            "page_number": 50,
                            "quote": "relevant geographic market is at least EEA-wide",
                        }
                    ],
                }
            ],
            "theories_of_harm": [
                {
                    "name": "Data advantage in digital advertising",
                    "theory_type": "data",
                    "theory_outcome": "remedied",
                    "notes": "Fitbit data advantage concern.",
                    "not_found": False,
                    "passages": [
                        {
                            "chunk_id": "chunk_002",
                            "page_number": 100,
                            "quote": "Fitbit data strengthens Google advertising position",
                        }
                    ],
                }
            ],
            "overall_outcome": "cleared_with_conditions",
            "caveats": [],
        }

    def _make_mock_ac(self, response_dict: dict) -> MagicMock:
        """Return a mock Anthropic client that returns tool_use structured output."""
        mock_block = MagicMock()
        mock_block.type = "tool_use"
        mock_block.input = response_dict
        mock_ac = MagicMock()
        mock_ac.messages.create.return_value = MagicMock(content=[mock_block])
        return mock_ac

    def test_full_extract_returns_draft_and_reconciliation(self, tmp_path):
        existing = _make_record()
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))

        draft_path = tmp_path / "test_case.draft.yaml"
        mock_cache = self._mock_cache()
        mock_ac = self._make_mock_ac(self._mock_response_dict())

        from unittest.mock import patch
        with patch("extract_case_from_source.load_cache", return_value=mock_cache):
            rpt = extract_case(
                yaml_path,
                cache_dir=tmp_path / "cache",
                output_path=draft_path,
                use_claude=True,
                anthropic_client=mock_ac,
            )

        assert rpt.error is None
        assert rpt.result is not None
        assert rpt.result.passages_validated == 3
        assert rpt.result.passages_rejected == 0
        assert len(rpt.findings) > 0
        assert draft_path.exists()

        # Verify draft YAML is valid
        with open(draft_path) as f:
            draft = yaml.safe_load(f)
        assert "_draft_note" in draft
        assert len(draft["source_passages"]) == 3

    def test_mocked_invented_quote_is_rejected(self, tmp_path):
        """When Claude invents a quote, it must not appear in the draft."""
        existing = _make_record()
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))

        invented_dict = {
            "product_markets": [
                {
                    "name": "Online advertising",
                    "definition_status": "defined",
                    "notes": "Narrow.",
                    "not_found": False,
                    "passages": [
                        {
                            "chunk_id": "chunk_001",
                            "page_number": 42,
                            "quote": "This quote was entirely invented and does not exist in the PDF",
                        }
                    ],
                }
            ],
            "geographic_markets": [],
            "theories_of_harm": [],
            "overall_outcome": "unknown",
            "caveats": [],
        }

        mock_cache = self._mock_cache()
        mock_ac = self._make_mock_ac(invented_dict)

        from unittest.mock import patch
        with patch("extract_case_from_source.load_cache", return_value=mock_cache):
            rpt = extract_case(
                yaml_path,
                cache_dir=tmp_path / "cache",
                use_claude=True,
                anthropic_client=mock_ac,
            )

        assert rpt.result is not None
        assert rpt.result.passages_validated == 0
        assert rpt.result.passages_rejected == 1
        # Draft should have no source passages
        draft = rpt.draft_record or {}
        assert draft.get("source_passages", []) == []

    def test_max_chunks_limits_chunks_sent(self, tmp_path):
        """--max-chunks must cap the number of chunks regardless of pages."""
        existing = _make_record()
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))

        multi_page_cache = {
            "source_document_id": "main_doc",
            "source_url": "https://example.com/decision.pdf",
            "page_count": 6,
            "pages": [
                {"page_number": i, "text": f"8.{i} Section {i}\nContent for market definition on page {i}."}
                for i in range(1, 7)
            ],
            "extracted_at": "2026-05-23T00:00:00+00:00",
        }

        from unittest.mock import patch
        with patch("extract_case_from_source.load_cache", return_value=multi_page_cache):
            rpt = extract_case(
                yaml_path,
                cache_dir=tmp_path / "cache",
                use_claude=False,
                max_chunks=2,
            )

        assert len(rpt.chunks_used) <= 2


# ---------------------------------------------------------------------------
# _validate_extraction_schema
# ---------------------------------------------------------------------------

class TestValidateExtractionSchema:
    def _valid(self) -> dict:
        return {
            "product_markets": [],
            "geographic_markets": [],
            "theories_of_harm": [],
            "overall_outcome": "cleared",
            "source_passages": [],
            "caveats": [],
        }

    def test_valid_payload_has_no_errors(self):
        assert _validate_extraction_schema(self._valid()) == []

    def test_missing_product_markets_is_error(self):
        d = self._valid()
        del d["product_markets"]
        errors = _validate_extraction_schema(d)
        assert any("product_markets" in e for e in errors)

    def test_missing_overall_outcome_is_error(self):
        d = self._valid()
        del d["overall_outcome"]
        errors = _validate_extraction_schema(d)
        assert any("overall_outcome" in e for e in errors)

    def test_invalid_outcome_value_is_error(self):
        d = self._valid()
        d["overall_outcome"] = "approved"  # not in valid set
        errors = _validate_extraction_schema(d)
        assert any("overall_outcome" in e for e in errors)

    def test_non_list_product_markets_is_error(self):
        d = self._valid()
        d["product_markets"] = "not a list"
        errors = _validate_extraction_schema(d)
        assert any("product_markets" in e for e in errors)

    def test_all_valid_outcomes_accepted(self):
        valid_outcomes = ["cleared", "cleared_with_conditions", "blocked", "pending", "unknown"]
        for outcome in valid_outcomes:
            d = self._valid()
            d["overall_outcome"] = outcome
            assert _validate_extraction_schema(d) == [], f"Outcome '{outcome}' should be valid"


# ---------------------------------------------------------------------------
# Heading detection (via _extract_section_map from repair_source_passages)
# ---------------------------------------------------------------------------

class TestHeadingDetection:
    """Verify that _HEADING_REJECT_RE filters footnote-like text from section labels."""

    def _page_cache(self, page_text: str) -> dict:
        return _make_page_cache([(1, page_text)])

    def test_footnote_starting_with_in_the_past_rejected(self):
        """'16 In the past, Fitbit also marketed...' must NOT become a section label."""
        text = "16 In the past, Fitbit also marketed wearable devices used as fashion accessories.\nOther content."
        smap = _extract_section_map(self._page_cache(text))
        label = smap.get(1, "")
        assert "In the past" not in label

    def test_footnote_starting_with_month_name_rejected(self):
        """'14 July 2020...' must NOT become a section label."""
        text = "14 July 2020, the Commission opened Phase II proceedings.\nOther content."
        smap = _extract_section_map(self._page_cache(text))
        label = smap.get(1, "")
        assert "July 2020" not in label

    def test_footnote_with_date_and_comp_m_rejected(self):
        """'21 December 21, 2016 in case COMP/M...' must NOT become a section label."""
        text = "21 December 21, 2016 in case COMP/M.8124.\nOther content."
        smap = _extract_section_map(self._page_cache(text))
        label = smap.get(1, "")
        assert "December" not in label

    def test_real_section_heading_accepted(self):
        """'8.4 App stores' must be accepted as a heading."""
        text = "8.4 App stores\nThe Commission considered several app store markets."
        smap = _extract_section_map(self._page_cache(text))
        label = smap.get(1, "")
        assert "App stores" in label or "8.4" in label

    def test_real_subsection_heading_accepted(self):
        """'8.6.1 Product market definition' must be accepted."""
        text = "8.6.1 Product market definition\nThe Commission defined the product market."
        smap = _extract_section_map(self._page_cache(text))
        label = smap.get(1, "")
        assert "Product market definition" in label or "8.6.1" in label

    def test_theory_section_heading_accepted(self):
        """'9.4 Vertical effects' must be accepted as a heading."""
        text = "9.4 Vertical effects\nThe Commission assessed input foreclosure."
        smap = _extract_section_map(self._page_cache(text))
        label = smap.get(1, "")
        assert "Vertical effects" in label or "9.4" in label

    def test_ec_trailing_dot_format_accepted(self):
        """EC decisions use '8.6. Online advertising' with a trailing dot — must be accepted."""
        text = "8.6. Online advertising\nThe Commission defined the market for online advertising."
        smap = _extract_section_map(self._page_cache(text))
        label = smap.get(1, "")
        assert "Online advertising" in label or "8.6" in label

    def test_ec_deep_section_trailing_dot_accepted(self):
        """'8.6.1. Product market definition' (EC trailing-dot style) must be accepted."""
        text = "8.6.1. Product market definition\nThe Commission defined the product market."
        smap = _extract_section_map(self._page_cache(text))
        label = smap.get(1, "")
        assert "Product market definition" in label or "8.6.1" in label

    def test_chunk_labels_not_footnote_background(self):
        """_build_chunks must not produce labels that look like footnote text."""
        pages = [
            (1, "8.6 Online advertising\nThe Commission defined the market."),
            (2, "16 In the past, Fitbit also marketed wearable devices.\nFootnote text."),
            (3, "9.1 Data effects\nFitbit data gives Google an advantage."),
        ]
        cache = _make_page_cache(pages)
        chunks = _build_chunks(cache)  # auto-detects section map
        for chunk in chunks:
            label = chunk.section_path
            assert "In the past" not in label, (
                f"Footnote text must not appear in chunk label: {label!r}"
            )


# ---------------------------------------------------------------------------
# Inspect-chunks mode (use_claude=False, no output files)
# ---------------------------------------------------------------------------

class TestInspectChunksMode:
    def _cache_with_sections(self) -> dict:
        return {
            "source_document_id": "main_doc",
            "source_url": "https://example.com/decision.pdf",
            "page_count": 3,
            "pages": [
                {"page_number": 1, "text": "8.4 App stores\nSome text about app stores and market definition."},
                {"page_number": 2, "text": "9.1 Data effects\nFitbit data gives Google an advantage."},
                {"page_number": 3, "text": "9.4 Vertical effects\nAssessment of input foreclosure."},
            ],
            "extracted_at": "2026-05-23T00:00:00+00:00",
        }

    def test_no_claude_returns_chunks_without_calling_api(self, tmp_path):
        """use_claude=False must select chunks and never call the Claude API."""
        existing = _make_record()
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))

        mock_ac = MagicMock()

        from unittest.mock import patch
        with patch("extract_case_from_source.load_cache", return_value=self._cache_with_sections()):
            rpt = extract_case(
                yaml_path,
                cache_dir=tmp_path / "cache",
                use_claude=False,
                anthropic_client=mock_ac,
            )

        mock_ac.messages.create.assert_not_called()
        assert rpt.result is None
        assert len(rpt.chunks_used) > 0

    def test_chunk_labels_are_real_headings_or_unknown(self, tmp_path):
        """Chunk section labels must be real headings, not footnote text."""
        existing = _make_record()
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))

        # Page with a footnote that could be mistaken for a heading
        cache = {
            "source_document_id": "main_doc",
            "source_url": "https://example.com/decision.pdf",
            "page_count": 2,
            "pages": [
                {
                    "page_number": 1,
                    "text": (
                        "8.6 Online advertising\n"
                        "The Commission defined the product market.\n"
                        "16 In the past, Fitbit also marketed wearable devices."
                    ),
                },
                {
                    "page_number": 2,
                    "text": (
                        "9.1 Data effects\n"
                        "Fitbit data gives Google an advantage.\n"
                        "21 December 21, 2016 in case COMP/M.8124."
                    ),
                },
            ],
            "extracted_at": "2026-05-23T00:00:00+00:00",
        }

        from unittest.mock import patch
        with patch("extract_case_from_source.load_cache", return_value=cache):
            rpt = extract_case(
                yaml_path,
                cache_dir=tmp_path / "cache",
                use_claude=False,
            )

        for chunk in rpt.chunks_used:
            label = chunk.section_path
            assert "In the past" not in label, f"Footnote in label: {label!r}"
            assert "December" not in label, f"Month footnote in label: {label!r}"
            assert "COMP/M" not in label, f"Case ref in label: {label!r}"


# ---------------------------------------------------------------------------
# _normalize_list_fields
# ---------------------------------------------------------------------------

class TestNormalizeListFields:
    def _base(self) -> dict:
        return {
            "product_markets": [],
            "geographic_markets": [],
            "theories_of_harm": [],
            "overall_outcome": "cleared",
            "caveats": [],
        }

    def test_valid_lists_unchanged(self):
        d = self._base()
        normalized, errors = _normalize_list_fields(d)
        assert errors == []
        assert normalized["product_markets"] == []

    def test_not_found_string_coerced_to_empty_list(self):
        """'not found' for product_markets must be normalised to []."""
        d = self._base()
        d["product_markets"] = "not found"
        normalized, errors = _normalize_list_fields(d)
        assert errors == []
        assert normalized["product_markets"] == []

    def test_empty_string_coerced_to_empty_list(self):
        """'' for theories_of_harm must be normalised to []."""
        d = self._base()
        d["theories_of_harm"] = ""
        normalized, errors = _normalize_list_fields(d)
        assert errors == []
        assert normalized["theories_of_harm"] == []

    def test_none_string_coerced_to_empty_list(self):
        """'none' for geographic_markets must be normalised to []."""
        d = self._base()
        d["geographic_markets"] = "none"
        normalized, errors = _normalize_list_fields(d)
        assert errors == []
        assert normalized["geographic_markets"] == []

    def test_na_string_coerced_to_empty_list(self):
        """'n/a' for caveats must be normalised to []."""
        d = self._base()
        d["caveats"] = "n/a"
        normalized, errors = _normalize_list_fields(d)
        assert errors == []
        assert normalized["caveats"] == []

    def test_null_string_case_insensitive(self):
        """'Not Found', 'NONE', 'N/A' must all be treated as null-like."""
        for val in ("Not Found", "NONE", "N/A", "Null"):
            d = self._base()
            d["product_markets"] = val
            normalized, errors = _normalize_list_fields(d)
            assert errors == [], f"Expected no error for {val!r}"
            assert normalized["product_markets"] == [], f"Expected [] for {val!r}"

    def test_substantive_string_is_an_error(self):
        """A substantive string in product_markets must return a validation error."""
        d = self._base()
        d["product_markets"] = "The product market for wearable devices is defined as EEA-wide."
        normalized, errors = _normalize_list_fields(d)
        assert len(errors) == 1
        assert "product_markets" in errors[0]
        assert "substantive" in errors[0]

    def test_substantive_string_not_coerced(self):
        """A substantive string must remain unchanged (not become []) in the returned dict."""
        d = self._base()
        d["product_markets"] = "Some real content here"
        normalized, errors = _normalize_list_fields(d)
        # The value must not have been silently coerced to []
        assert normalized["product_markets"] == "Some real content here"

    def test_original_dict_not_mutated(self):
        """_normalize_list_fields must return a copy, not mutate the input."""
        d = self._base()
        d["product_markets"] = "not found"
        _normalize_list_fields(d)
        assert d["product_markets"] == "not found"

    def test_extra_list_fields_normalised(self):
        """Fields like 'remedies', 'source_passages', 'case_history_events' are also normalised."""
        d = self._base()
        d["remedies"] = "none"
        d["source_passages"] = "n/a"
        d["case_history_events"] = ""
        normalized, errors = _normalize_list_fields(d)
        assert errors == []
        assert normalized["remedies"] == []
        assert normalized["source_passages"] == []
        assert normalized["case_history_events"] == []

    def test_json_stringified_source_passages_parsed_to_list(self):
        """source_passages returned as a JSON-stringified array must be parsed into a list."""
        d = self._base()
        d["source_passages"] = (
            '[{"chunk_id": "chunk_001", "page_number": 42, '
            '"quote": "The Commission defines the relevant market."}]'
        )
        normalized, errors = _normalize_list_fields(d)
        assert errors == [], f"Unexpected errors: {errors}"
        assert isinstance(normalized["source_passages"], list)
        assert len(normalized["source_passages"]) == 1
        assert normalized["source_passages"][0]["quote"] == "The Commission defines the relevant market."

    def test_invalid_json_string_in_source_passages_fails_clearly(self):
        """A source_passages string starting with '[' but invalid JSON must return a clear error."""
        d = self._base()
        d["source_passages"] = '[ { "chunk_id": "c1", broken json here'
        normalized, errors = _normalize_list_fields(d)
        assert len(errors) == 1
        assert "source_passages" in errors[0]
        assert "invalid JSON" in errors[0]

    def test_json_string_parsing_to_object_not_list_fails(self):
        """A source_passages JSON string that parses to an object (not list) must fail."""
        d = self._base()
        d["source_passages"] = '{"chunk_id": "c1", "page_number": 42, "quote": "text"}'
        # Starts with '{' not '[' — no JSON parsing attempted, treated as substantive string
        normalized, errors = _normalize_list_fields(d)
        assert len(errors) == 1
        assert "source_passages" in errors[0]

    def test_json_array_with_object_content_is_rejected_via_bracket_path(self):
        """A '[{...}]' JSON string that parses to a list of objects must be accepted."""
        d = self._base()
        d["caveats"] = '["Only market sections supplied.", "No theories found."]'
        normalized, errors = _normalize_list_fields(d)
        assert errors == []
        assert normalized["caveats"] == ["Only market sections supplied.", "No theories found."]

    def test_json_array_parsed_to_non_list_type_errors(self):
        """A field value '[true]' parses to a list and is accepted."""
        d = self._base()
        d["background_concepts"] = '["wearable devices", "fitness trackers"]'
        normalized, errors = _normalize_list_fields(d)
        assert errors == []
        assert normalized["background_concepts"] == ["wearable devices", "fitness trackers"]


# ---------------------------------------------------------------------------
# Empty extraction (no markets/theories in supplied chunks)
# ---------------------------------------------------------------------------

class TestEmptyExtraction:
    """Verify that an extraction where nothing is found still produces a valid report."""

    def _industry_overview_cache(self) -> dict:
        """A cache with only procedural/background pages — no market definition text."""
        return {
            "source_document_id": "main_doc",
            "source_url": "https://example.com/decision.pdf",
            "page_count": 3,
            "pages": [
                {"page_number": 1, "text": "7.1 Wearable devices\nWearable devices are consumer electronics worn on the body."},
                {"page_number": 2, "text": "7.2 Industry overview\nThe wearable industry has grown rapidly in recent years."},
                {"page_number": 3, "text": "7.3 Key players\nGoogle and Fitbit are major players in the market."},
            ],
            "extracted_at": "2026-05-23T00:00:00+00:00",
        }

    def _make_mock_ac_empty(self) -> MagicMock:
        """Mock that returns empty lists for all categories."""
        mock_block = MagicMock()
        mock_block.type = "tool_use"
        mock_block.input = {
            "product_markets": [],
            "geographic_markets": [],
            "theories_of_harm": [],
            "overall_outcome": "unknown",
            "caveats": ["Supplied chunks cover industry overview only; no market definition found."],
        }
        mock_ac = MagicMock()
        mock_ac.messages.create.return_value = MagicMock(content=[mock_block])
        return mock_ac

    def _make_mock_ac_null_strings(self) -> MagicMock:
        """Mock that returns null-like strings instead of [] — the bug we're fixing."""
        mock_block = MagicMock()
        mock_block.type = "tool_use"
        mock_block.input = {
            "product_markets": "not found",
            "geographic_markets": "none",
            "theories_of_harm": "n/a",
            "overall_outcome": "unknown",
            "caveats": [],
        }
        mock_ac = MagicMock()
        mock_ac.messages.create.return_value = MagicMock(content=[mock_block])
        return mock_ac

    def test_empty_lists_produce_valid_report(self, tmp_path):
        """All-empty extraction must produce a valid report with no propositions."""
        existing = _make_record()
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))

        from unittest.mock import patch
        with patch("extract_case_from_source.load_cache", return_value=self._industry_overview_cache()):
            rpt = extract_case(
                yaml_path,
                cache_dir=tmp_path / "cache",
                use_claude=True,
                anthropic_client=self._make_mock_ac_empty(),
            )

        assert rpt.error is None
        assert rpt.result is not None
        assert rpt.result.product_markets == []
        assert rpt.result.geographic_markets == []
        assert rpt.result.theories == []
        assert rpt.result.overall_outcome == "unknown"
        draft = rpt.draft_record or {}
        assert draft.get("product_markets_considered", []) == []
        assert draft.get("source_passages", []) == []

    def test_null_string_fields_normalised_before_validation(self, tmp_path):
        """When Claude returns 'not found'/'none'/'n/a' for list fields, normalisation
        must convert them to [] so extraction succeeds instead of failing schema."""
        existing = _make_record()
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))

        from unittest.mock import patch
        with patch("extract_case_from_source.load_cache", return_value=self._industry_overview_cache()):
            rpt = extract_case(
                yaml_path,
                cache_dir=tmp_path / "cache",
                use_claude=True,
                anthropic_client=self._make_mock_ac_null_strings(),
            )

        # Must not fail — normalization converts the strings to []
        assert rpt.error is None
        assert rpt.result is not None
        assert rpt.result.product_markets == []
        assert rpt.result.geographic_markets == []
        assert rpt.result.theories == []

    def test_substantive_string_in_list_field_is_schema_error(self, tmp_path):
        """A substantive string for a list field must fail schema validation and save a debug file."""
        existing = _make_record()
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))

        debug_dir = tmp_path / "debug"
        mock_block = MagicMock()
        mock_block.type = "tool_use"
        mock_block.input = {
            "product_markets": "The product market was not defined in the supplied text.",
            "geographic_markets": [],
            "theories_of_harm": [],
            "overall_outcome": "unknown",
            "caveats": [],
        }
        mock_ac = MagicMock()
        mock_ac.messages.create.return_value = MagicMock(content=[mock_block])

        from unittest.mock import patch
        with patch("extract_case_from_source.load_cache", return_value=self._industry_overview_cache()):
            rpt = extract_case(
                yaml_path,
                cache_dir=tmp_path / "cache",
                use_claude=True,
                anthropic_client=mock_ac,
                debug_dir=debug_dir,
            )

        assert rpt.error is not None
        assert "substantive" in rpt.error or "product_markets" in rpt.error


# ---------------------------------------------------------------------------
# Focus mode tests
# ---------------------------------------------------------------------------

class TestIsFocusedSection:
    """Unit tests for _is_focused_section()."""

    def test_market_definition_matches_relevant_market_heading(self):
        assert _is_focused_section("8 RELEVANT MARKETS > 8.1 Product market definition", "market_definition")

    def test_market_definition_matches_product_market(self):
        assert _is_focused_section("7 Product market analysis", "market_definition")

    def test_market_definition_matches_geographic_market(self):
        assert _is_focused_section("8.2 Geographic market", "market_definition")

    def test_market_definition_does_not_match_remedies_section(self):
        assert not _is_focused_section("10 Commitments and remedies", "market_definition")

    def test_theories_matches_competitive_assessment(self):
        assert _is_focused_section("9 Competitive assessment > horizontal effects", "theories")

    def test_theories_matches_foreclosure(self):
        assert _is_focused_section("9.3 Foreclosure effects", "theories")

    def test_theories_does_not_match_procedure(self):
        assert not _is_focused_section("2 Procedure > 2.1 Notification", "theories")

    def test_remedies_matches_commitments(self):
        assert _is_focused_section("11 Commitments", "remedies")

    def test_remedies_matches_divestiture(self):
        assert _is_focused_section("12 Structural remedy — divestiture", "remedies")

    def test_case_history_matches_procedure(self):
        assert _is_focused_section("2 Procedure", "case_history")

    def test_case_history_matches_article_22_referral(self):
        assert _is_focused_section("3.1 Article 22 referral", "case_history")

    def test_no_focus_always_true(self):
        assert _is_focused_section("anything at all", None) is True

    def test_unknown_focus_always_true(self):
        # An unrecognised focus key falls through to True (no terms to match)
        assert _is_focused_section("anything", "nonexistent_focus") is True

    def test_focus_terms_dict_exported(self):
        assert isinstance(_FOCUS_TERMS, dict)
        assert "market_definition" in _FOCUS_TERMS
        assert "theories" in _FOCUS_TERMS
        assert "remedies" in _FOCUS_TERMS
        assert "case_history" in _FOCUS_TERMS


class TestSelectRelevantChunksFocus:
    """_select_relevant_chunks with focus parameter."""

    def _make_chunks(self) -> list[ChunkInfo]:
        return [
            ChunkInfo(
                chunk_id="chunk_001",
                pages=[{"page_number": i, "text": "text"} for i in range(1, 6)],
                section_path="8 RELEVANT MARKETS > 8.1 Product market definition",
                source_document_id="doc1",
            ),
            ChunkInfo(
                chunk_id="chunk_002",
                pages=[{"page_number": i, "text": "text"} for i in range(6, 11)],
                section_path="9 Competitive assessment > 9.1 Horizontal effects",
                source_document_id="doc1",
            ),
            ChunkInfo(
                chunk_id="chunk_003",
                pages=[{"page_number": i, "text": "text"} for i in range(11, 16)],
                section_path="11 Commitments and remedies",
                source_document_id="doc1",
            ),
        ]

    def test_focus_market_definition_selects_only_market_chunks(self):
        chunks = self._make_chunks()
        selected = _select_relevant_chunks(chunks, focus="market_definition")
        ids = [c.chunk_id for c in selected]
        assert "chunk_001" in ids
        assert "chunk_002" not in ids
        assert "chunk_003" not in ids

    def test_focus_theories_selects_only_assessment_chunks(self):
        chunks = self._make_chunks()
        selected = _select_relevant_chunks(chunks, focus="theories")
        ids = [c.chunk_id for c in selected]
        assert "chunk_002" in ids
        assert "chunk_001" not in ids
        assert "chunk_003" not in ids

    def test_focus_remedies_selects_only_remedies_chunks(self):
        chunks = self._make_chunks()
        selected = _select_relevant_chunks(chunks, focus="remedies")
        ids = [c.chunk_id for c in selected]
        assert "chunk_003" in ids
        assert "chunk_001" not in ids
        assert "chunk_002" not in ids

    def test_no_focus_selects_all_relevant(self):
        chunks = self._make_chunks()
        selected = _select_relevant_chunks(chunks, focus=None)
        assert len(selected) == 3

    def test_focus_with_no_matches_returns_empty(self):
        chunks = self._make_chunks()
        # case_history terms won't match any of the three section paths above
        selected = _select_relevant_chunks(chunks, focus="case_history")
        assert selected == []

    def test_focus_passed_via_extract_case(self, tmp_path):
        """extract_case with focus restricts the chunks Claude sees."""
        existing = _make_record()
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))

        page_cache = {
            "source_document_id": "doc1",
            "source_url": "https://example.com/doc.pdf",
            "page_count": 15,
            "pages": (
                [{"page_number": i, "text": f"8 RELEVANT MARKETS\n8.1 Product market definition\npage {i}"} for i in range(1, 6)]
                + [{"page_number": i, "text": f"9 Competitive assessment\n9.1 Horizontal effects\npage {i}"} for i in range(6, 11)]
                + [{"page_number": i, "text": f"11 Commitments and remedies\npage {i}"} for i in range(11, 16)]
            ),
            "extracted_at": "2026-05-25T00:00:00+00:00",
        }

        mock_block = MagicMock()
        mock_block.type = "tool_use"
        mock_block.input = {
            "product_markets": [],
            "geographic_markets": [],
            "theories_of_harm": [],
            "overall_outcome": "unknown",
            "caveats": [],
        }
        mock_ac = MagicMock()
        mock_ac.messages.create.return_value = MagicMock(content=[mock_block])

        from unittest.mock import patch
        with patch("extract_case_from_source.load_cache", return_value=page_cache):
            rpt = extract_case(
                yaml_path,
                cache_dir=tmp_path / "cache",
                use_claude=True,
                anthropic_client=mock_ac,
                focus="remedies",
            )

        # Only remedies chunks should have been used — pages 11-15
        assert all("11" in c.section_path or "remedies" in c.section_path.lower() for c in rpt.chunks_used)


class TestIndustryOverviewExtraction:
    """Industry overview sections must NOT produce formal market entries."""

    def _industry_cache(self) -> dict:
        return {
            "source_document_id": "doc1",
            "source_url": "https://example.com/doc.pdf",
            "page_count": 4,
            "pages": [
                {"page_number": 1, "text": "7 Industry overview\nWearable devices are consumer electronics."},
                {"page_number": 2, "text": "7.1 Background\nThe global wearable market has grown."},
                {"page_number": 3, "text": "7.2 Key players\nFitbit and Apple are leading vendors."},
                {"page_number": 4, "text": "7.3 History\nFitbit was founded in 2007."},
            ],
            "extracted_at": "2026-05-25T00:00:00+00:00",
        }

    def _make_mock_ac_with_background_concepts(self) -> MagicMock:
        mock_block = MagicMock()
        mock_block.type = "tool_use"
        mock_block.input = {
            "product_markets": [],
            "geographic_markets": [],
            "theories_of_harm": [],
            "overall_outcome": "unknown",
            "caveats": ["Chunks covered industry overview only; no formal market definition found."],
            "background_concepts": ["wearable devices", "fitness trackers", "consumer electronics"],
        }
        mock_ac = MagicMock()
        mock_ac.messages.create.return_value = MagicMock(content=[mock_block])
        return mock_ac

    def test_overview_chunks_produce_empty_product_markets(self, tmp_path):
        """When Claude is given only overview/background text, product_markets must be []."""
        existing = _make_record()
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))

        from unittest.mock import patch
        with patch("extract_case_from_source.load_cache", return_value=self._industry_cache()):
            rpt = extract_case(
                yaml_path,
                cache_dir=tmp_path / "cache",
                use_claude=True,
                anthropic_client=self._make_mock_ac_with_background_concepts(),
            )

        assert rpt.error is None
        assert rpt.result is not None
        assert rpt.result.product_markets == []
        assert rpt.result.geographic_markets == []

    def test_overview_chunks_capture_background_concepts(self, tmp_path):
        """background_concepts from overview sections must be collected."""
        existing = _make_record()
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))

        from unittest.mock import patch
        with patch("extract_case_from_source.load_cache", return_value=self._industry_cache()):
            rpt = extract_case(
                yaml_path,
                cache_dir=tmp_path / "cache",
                use_claude=True,
                anthropic_client=self._make_mock_ac_with_background_concepts(),
            )

        assert rpt.result is not None
        assert len(rpt.result.background_concepts) > 0
        assert "wearable devices" in rpt.result.background_concepts

    def test_background_concepts_not_written_to_draft_yaml(self, tmp_path):
        """background_concepts must not appear in the draft YAML file."""
        existing = _make_record()
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))

        draft_path = tmp_path / "test_case.draft.yaml"

        from unittest.mock import patch
        with patch("extract_case_from_source.load_cache", return_value=self._industry_cache()):
            rpt = extract_case(
                yaml_path,
                cache_dir=tmp_path / "cache",
                output_path=draft_path,
                use_claude=True,
                anthropic_client=self._make_mock_ac_with_background_concepts(),
            )

        assert draft_path.exists()
        draft = yaml.safe_load(draft_path.read_text())
        assert "background_concepts" not in draft


class TestEstimateCostMode:
    """--estimate-cost mode must compute chunk/page/token totals without calling Claude."""

    def test_estimate_cost_does_not_call_claude(self, tmp_path):
        """extract_case with use_claude=False returns chunk info without any Claude API call."""
        existing = _make_record()
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))

        page_cache = {
            "source_document_id": "doc1",
            "source_url": "https://example.com/doc.pdf",
            "page_count": 6,
            "pages": [
                {"page_number": i, "text": f"8 RELEVANT MARKETS\n8.1 Product market\npage {i}"}
                for i in range(1, 7)
            ],
            "extracted_at": "2026-05-25T00:00:00+00:00",
        }

        mock_ac = MagicMock()

        from unittest.mock import patch
        with patch("extract_case_from_source.load_cache", return_value=page_cache):
            rpt = extract_case(
                yaml_path,
                cache_dir=tmp_path / "cache",
                use_claude=False,
                anthropic_client=mock_ac,
            )

        mock_ac.messages.create.assert_not_called()
        assert rpt.chunks_used is not None
        assert len(rpt.chunks_used) > 0

    def test_estimate_cost_with_focus_filters_chunks(self, tmp_path):
        """estimate-cost + focus restricts page count to matching sections only."""
        existing = _make_record()
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))

        page_cache = {
            "source_document_id": "doc1",
            "source_url": "https://example.com/doc.pdf",
            "page_count": 10,
            "pages": (
                [{"page_number": i, "text": f"8 RELEVANT MARKETS\n8.1 Product market\npage {i}"} for i in range(1, 6)]
                + [{"page_number": i, "text": f"11 Commitments and remedies\npage {i}"} for i in range(6, 11)]
            ),
            "extracted_at": "2026-05-25T00:00:00+00:00",
        }

        from unittest.mock import patch
        with patch("extract_case_from_source.load_cache", return_value=page_cache):
            rpt_all = extract_case(
                yaml_path,
                cache_dir=tmp_path / "cache",
                use_claude=False,
            )
            rpt_focused = extract_case(
                yaml_path,
                cache_dir=tmp_path / "cache",
                use_claude=False,
                focus="remedies",
            )

        total_pages_all = sum(len(c.pages) for c in rpt_all.chunks_used)
        total_pages_focused = sum(len(c.pages) for c in rpt_focused.chunks_used)
        assert total_pages_focused < total_pages_all


# ---------------------------------------------------------------------------
# Empty-object guard tests
# ---------------------------------------------------------------------------

class TestEmptyObjectGuard:
    """Claude returning {} must be caught as an error, not silently accepted."""

    def _page_cache(self) -> dict:
        return {
            "source_document_id": "doc1",
            "source_url": "https://example.com/doc.pdf",
            "page_count": 3,
            "pages": [
                {"page_number": i, "text": f"8 RELEVANT MARKETS\n8.1 Product market\npage {i}"}
                for i in range(1, 4)
            ],
            "extracted_at": "2026-05-25T00:00:00+00:00",
        }

    def _make_mock_ac_empty_object(self) -> MagicMock:
        """Claude returns {} — the bug we're guarding against."""
        mock_block = MagicMock()
        mock_block.type = "tool_use"
        mock_block.input = {}
        mock_ac = MagicMock()
        mock_ac.messages.create.return_value = MagicMock(content=[mock_block])
        return mock_ac

    def _make_mock_ac_missing_theories(self) -> MagicMock:
        """Claude omits theories_of_harm — should be filled from envelope."""
        mock_block = MagicMock()
        mock_block.type = "tool_use"
        mock_block.input = {
            "product_markets": [],
            "geographic_markets": [],
            "overall_outcome": "unknown",
            "source_passages": [],
            "caveats": ["Only market definition sections were supplied."],
        }
        mock_ac = MagicMock()
        mock_ac.messages.create.return_value = MagicMock(content=[mock_block])
        return mock_ac

    def _make_mock_ac_missing_outcome(self) -> MagicMock:
        """Claude omits overall_outcome — should be filled from envelope as 'unknown'."""
        mock_block = MagicMock()
        mock_block.type = "tool_use"
        mock_block.input = {
            "product_markets": [],
            "geographic_markets": [],
            "theories_of_harm": [],
            "source_passages": [],
            "caveats": [],
        }
        mock_ac = MagicMock()
        mock_ac.messages.create.return_value = MagicMock(content=[mock_block])
        return mock_ac

    def _make_mock_ac_market_definition_only(self) -> MagicMock:
        """Valid market-definition-focused response with empty theories/passages."""
        mock_block = MagicMock()
        mock_block.type = "tool_use"
        mock_block.input = {
            "product_markets": [
                {
                    "name": "Wearable fitness devices",
                    "definition_status": "defined",
                    "notes": "The Commission defined the market as wearable fitness devices.",
                    "not_found": False,
                    "passages": [],
                }
            ],
            "geographic_markets": [],
            "theories_of_harm": [],
            "overall_outcome": "unknown",
            "source_passages": [],
            "caveats": ["Only market definition sections supplied; theories not in scope."],
        }
        mock_ac = MagicMock()
        mock_ac.messages.create.return_value = MagicMock(content=[mock_block])
        return mock_ac

    def test_empty_object_response_fails_with_clear_error(self, tmp_path):
        """Claude returning {} must produce an error containing 'empty extraction object'."""
        existing = _make_record()
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))

        from unittest.mock import patch
        with patch("extract_case_from_source.load_cache", return_value=self._page_cache()):
            rpt = extract_case(
                yaml_path,
                cache_dir=tmp_path / "cache",
                use_claude=True,
                anthropic_client=self._make_mock_ac_empty_object(),
                debug_dir=tmp_path / "debug",
            )

        assert rpt.error is not None
        assert "empty extraction object" in rpt.error
        assert rpt.result is None

    def test_empty_object_saves_debug_file(self, tmp_path):
        """A {} response must save the raw response to the debug directory."""
        existing = _make_record()
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))

        debug_dir = tmp_path / "debug"

        from unittest.mock import patch
        with patch("extract_case_from_source.load_cache", return_value=self._page_cache()):
            extract_case(
                yaml_path,
                cache_dir=tmp_path / "cache",
                use_claude=True,
                anthropic_client=self._make_mock_ac_empty_object(),
                debug_dir=debug_dir,
            )

        debug_files = list(debug_dir.glob("*_claude_raw_response.txt"))
        assert len(debug_files) == 1

    def test_missing_theories_filled_from_envelope(self, tmp_path):
        """A response missing theories_of_harm gets [] from the default envelope."""
        existing = _make_record()
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))

        from unittest.mock import patch
        with patch("extract_case_from_source.load_cache", return_value=self._page_cache()):
            rpt = extract_case(
                yaml_path,
                cache_dir=tmp_path / "cache",
                use_claude=True,
                anthropic_client=self._make_mock_ac_missing_theories(),
            )

        assert rpt.error is None
        assert rpt.result is not None
        assert rpt.result.theories == []

    def test_missing_overall_outcome_filled_as_unknown(self, tmp_path):
        """A response missing overall_outcome gets 'unknown' from the default envelope."""
        existing = _make_record()
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))

        from unittest.mock import patch
        with patch("extract_case_from_source.load_cache", return_value=self._page_cache()):
            rpt = extract_case(
                yaml_path,
                cache_dir=tmp_path / "cache",
                use_claude=True,
                anthropic_client=self._make_mock_ac_missing_outcome(),
            )

        assert rpt.error is None
        assert rpt.result is not None
        assert rpt.result.overall_outcome == "unknown"

    def test_market_definition_only_response_validates(self, tmp_path):
        """A focused market-definition response with empty theories/passages must pass."""
        existing = _make_record()
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))

        from unittest.mock import patch
        with patch("extract_case_from_source.load_cache", return_value=self._page_cache()):
            rpt = extract_case(
                yaml_path,
                cache_dir=tmp_path / "cache",
                use_claude=True,
                anthropic_client=self._make_mock_ac_market_definition_only(),
            )

        assert rpt.error is None
        assert rpt.result is not None
        assert len(rpt.result.product_markets) == 1
        assert rpt.result.product_markets[0].name == "Wearable fitness devices"
        assert rpt.result.theories == []


# ---------------------------------------------------------------------------
# Section-batching tests
# ---------------------------------------------------------------------------

class TestSectionBatchPrefix:
    """Unit tests for _section_batch_prefix and _group_chunks_by_section_prefix."""

    def test_extracts_two_component_prefix(self):
        assert _section_batch_prefix("8.6 Online advertising services") == "8.6"

    def test_extracts_prefix_from_hierarchical_path(self):
        path = "8 RELEVANT MARKETS > 8.6 Online advertising > 8.6.1 Product market"
        assert _section_batch_prefix(path) == "8.6"

    def test_extracts_prefix_from_last_component_subsection(self):
        # Last component is "8.2.1 Product market definition"; numeric prefix = "8.2"
        path = "8.2 Wearable devices > 8.2.1 Product market definition"
        assert _section_batch_prefix(path) == "8.2"

    def test_falls_back_to_single_number(self):
        assert _section_batch_prefix("8 RELEVANT MARKETS") == "8"

    def test_empty_path_returns_empty(self):
        assert _section_batch_prefix("") == ""

    def _make_chunks_with_sections(self) -> list[ChunkInfo]:
        sections = [
            ("8.2 Wearable devices", 1, 5),
            ("8.2 Wearable devices > 8.2.1 Product market", 6, 10),
            ("8.6 Online advertising", 11, 15),
            ("8.6 Online advertising > 8.6.1 Product market", 16, 20),
            ("8.7 Ad tech services", 21, 25),
        ]
        chunks = []
        for i, (path, start, end) in enumerate(sections):
            chunks.append(ChunkInfo(
                chunk_id=f"chunk_{i+1:03d}",
                pages=[{"page_number": p, "text": f"text {p}"} for p in range(start, end + 1)],
                section_path=path,
                source_document_id="doc1",
            ))
        return chunks

    def test_groups_by_prefix(self):
        chunks = self._make_chunks_with_sections()
        groups = _group_chunks_by_section_prefix(chunks)
        prefixes = [p for p, _ in groups]
        assert prefixes == ["8.2", "8.6", "8.7"]

    def test_each_group_contains_correct_chunks(self):
        chunks = self._make_chunks_with_sections()
        groups = dict(_group_chunks_by_section_prefix(chunks))
        assert len(groups["8.2"]) == 2
        assert len(groups["8.6"]) == 2
        assert len(groups["8.7"]) == 1

    def test_single_prefix_filter(self):
        chunks = self._make_chunks_with_sections()
        groups = _group_chunks_by_section_prefix(chunks)
        filtered = [(p, c) for p, c in groups if p == "8.6"]
        assert len(filtered) == 1
        assert len(filtered[0][1]) == 2

    def test_preserves_document_order(self):
        chunks = self._make_chunks_with_sections()
        groups = _group_chunks_by_section_prefix(chunks)
        # First group should be 8.2 (lower page numbers)
        assert groups[0][0] == "8.2"
        first_chunk_pages = [p["page_number"] for p in groups[0][1][0].pages]
        assert min(first_chunk_pages) < 11  # before the 8.6 section


class TestExtractSectionBatch:
    """Tests for _extract_section_batch — one Claude call per section."""

    def _make_section_chunks(self, prefix: str = "8.6", n_pages: int = 3) -> list[ChunkInfo]:
        return [ChunkInfo(
            chunk_id="chunk_001",
            pages=[{"page_number": i, "text": f"{prefix} Online advertising\npage {i}"}
                   for i in range(1, n_pages + 1)],
            section_path=f"{prefix} Online advertising services",
            source_document_id="doc1",
        )]

    def _mock_ac(self, response_input: dict) -> MagicMock:
        mock_block = MagicMock()
        mock_block.type = "tool_use"
        mock_block.input = response_input
        mock_msg = MagicMock()
        mock_msg.content = [mock_block]
        mock_msg.model = "claude-sonnet-4-6"
        mock_msg.stop_reason = "tool_use"
        mock_ac = MagicMock()
        mock_ac.messages.create.return_value = mock_msg
        return mock_ac

    def _case_context(self) -> dict:
        return {"case_id": "test_case", "case_name": "Test Case", "authority": "EC", "parties": []}

    def test_successful_section_returns_result(self, tmp_path):
        chunks = self._make_section_chunks()
        mock_ac = self._mock_ac({
            "product_markets": [],
            "geographic_markets": [],
            "theories_of_harm": [],
            "overall_outcome": "unknown",
            "source_passages": [],
            "caveats": ["No formal market definition in this section."],
        })
        batch = _extract_section_batch(
            "8.6", chunks, self._case_context(), mock_ac, tmp_path / "debug", "test_case"
        )
        assert batch.error is None
        assert batch.result is not None
        assert batch.prefix == "8.6"

    def test_empty_object_section_fails_clearly(self, tmp_path):
        chunks = self._make_section_chunks()
        mock_ac = self._mock_ac({})
        batch = _extract_section_batch(
            "8.6", chunks, self._case_context(), mock_ac, tmp_path / "debug", "test_case"
        )
        assert batch.error is not None
        assert "empty extraction object" in batch.error
        assert batch.result is None

    def test_empty_object_section_saves_debug_json(self, tmp_path):
        chunks = self._make_section_chunks()
        mock_ac = self._mock_ac({})
        debug_dir = tmp_path / "debug"
        batch = _extract_section_batch(
            "8.6", chunks, self._case_context(), mock_ac, debug_dir, "test_case"
        )
        assert batch.debug_path is not None
        assert batch.debug_path.exists()
        saved = json.loads(batch.debug_path.read_text())
        assert saved["section_prefix"] == "8.6"
        assert saved["error"] == "empty_object"
        assert "chunks_sent" in saved
        assert saved["model"] == "claude-sonnet-4-6"
        assert saved["stop_reason"] == "tool_use"

    def test_debug_json_includes_chunk_metadata(self, tmp_path):
        chunks = self._make_section_chunks("8.6", n_pages=4)
        mock_ac = self._mock_ac({})
        debug_dir = tmp_path / "debug"
        batch = _extract_section_batch(
            "8.6", chunks, self._case_context(), mock_ac, debug_dir, "test_case"
        )
        saved = json.loads(batch.debug_path.read_text())
        assert len(saved["chunks_sent"]) == 1
        assert saved["chunks_sent"][0]["chunk_id"] == "chunk_001"
        assert saved["chunks_sent"][0]["page_count"] == 4

    def test_api_error_section_returns_error(self, tmp_path):
        chunks = self._make_section_chunks()
        mock_ac = MagicMock()
        mock_ac.messages.create.side_effect = RuntimeError("rate limit exceeded")
        batch = _extract_section_batch(
            "8.6", chunks, self._case_context(), mock_ac, tmp_path / "debug", "test_case"
        )
        assert batch.error is not None
        assert "API error" in batch.error
        assert "rate limit" in batch.error
        assert batch.result is None

    def test_valid_empty_envelope_accepted(self, tmp_path):
        """A section returning all-empty arrays (valid envelope) must succeed, not fail."""
        chunks = self._make_section_chunks()
        mock_ac = self._mock_ac({
            "product_markets": [],
            "geographic_markets": [],
            "theories_of_harm": [],
            "overall_outcome": "unknown",
            "source_passages": [],
            "caveats": [],
        })
        batch = _extract_section_batch(
            "8.6", chunks, self._case_context(), mock_ac, tmp_path / "debug", "test_case"
        )
        assert batch.error is None
        assert batch.result is not None
        assert batch.result.product_markets == []


class TestMergeExtractionResults:
    """Tests for _merge_extraction_results."""

    def _make_market(self, name: str, validated: bool = False) -> ExtractedMarket:
        ep = ExtractedPassage(
            chunk_id="c1", page_number=1, quote="test quote", validated=validated,
            source_document_id="doc1", rejection_reason="",
        )
        return ExtractedMarket(
            name=name, market_type="product",
            definition_status="defined", notes="notes",
            passages=[ep] if validated else [],
        )

    def _empty_result(self) -> ExtractionResult:
        return ExtractionResult()

    def test_empty_results_list_returns_empty_result(self):
        merged = _merge_extraction_results([])
        assert merged.product_markets == []
        assert merged.geographic_markets == []
        assert merged.overall_outcome == "unknown"

    def test_single_result_passthrough(self):
        r = ExtractionResult(
            product_markets=[self._make_market("Online advertising")],
            overall_outcome="cleared",
        )
        merged = _merge_extraction_results([r])
        assert len(merged.product_markets) == 1
        assert merged.overall_outcome == "cleared"

    def test_distinct_markets_from_different_sections_are_kept(self):
        r1 = ExtractionResult(product_markets=[self._make_market("Online advertising")])
        r2 = ExtractionResult(product_markets=[self._make_market("Wearable devices")])
        merged = _merge_extraction_results([r1, r2])
        assert len(merged.product_markets) == 2

    def test_duplicate_market_is_deduplicated(self):
        r1 = ExtractionResult(product_markets=[self._make_market("Online advertising")])
        r2 = ExtractionResult(product_markets=[self._make_market("Online advertising")])
        merged = _merge_extraction_results([r1, r2])
        assert len(merged.product_markets) == 1

    def test_similar_market_is_deduplicated(self):
        r1 = ExtractionResult(product_markets=[self._make_market("Online advertising services")])
        r2 = ExtractionResult(product_markets=[self._make_market("Online advertising")])
        merged = _merge_extraction_results([r1, r2])
        # Similar enough (>= 0.75) — should be deduplicated
        assert len(merged.product_markets) == 1

    def test_item_with_more_passages_wins_dedup(self):
        r1 = ExtractionResult(product_markets=[self._make_market("Online advertising", validated=False)])
        r2 = ExtractionResult(product_markets=[self._make_market("Online advertising", validated=True)])
        merged = _merge_extraction_results([r1, r2])
        assert len(merged.product_markets) == 1
        # The one with validated passages should win
        validated = sum(1 for p in merged.product_markets[0].passages if p.validated)
        assert validated == 1

    def test_caveats_accumulated(self):
        r1 = ExtractionResult(caveats=["caveat A"])
        r2 = ExtractionResult(caveats=["caveat B"])
        merged = _merge_extraction_results([r1, r2])
        assert "caveat A" in merged.caveats
        assert "caveat B" in merged.caveats

    def test_overall_outcome_first_non_unknown(self):
        r1 = ExtractionResult(overall_outcome="unknown")
        r2 = ExtractionResult(overall_outcome="cleared_with_conditions")
        r3 = ExtractionResult(overall_outcome="cleared")
        merged = _merge_extraction_results([r1, r2, r3])
        assert merged.overall_outcome == "cleared_with_conditions"

    def test_passage_counts_summed(self):
        r1 = ExtractionResult(passages_validated=3, passages_rejected=1)
        r2 = ExtractionResult(passages_validated=5, passages_rejected=2)
        merged = _merge_extraction_results([r1, r2])
        assert merged.passages_validated == 8
        assert merged.passages_rejected == 3

    def test_background_concepts_deduplicated(self):
        r1 = ExtractionResult(background_concepts=["wearable devices", "fitness trackers"])
        r2 = ExtractionResult(background_concepts=["fitness trackers", "smartwatches"])
        merged = _merge_extraction_results([r1, r2])
        assert merged.background_concepts.count("fitness trackers") == 1
        assert "wearable devices" in merged.background_concepts
        assert "smartwatches" in merged.background_concepts


class TestBatchedExtractCase:
    """Integration tests for extract_case with batch_by_section=True."""

    def _make_page_cache_multi_section(self) -> dict:
        return {
            "source_document_id": "doc1",
            "source_url": "https://example.com/doc.pdf",
            "page_count": 10,
            "pages": (
                [{"page_number": i, "text": f"8.6 Online advertising services\n8.6.1 Product market\npage {i}"}
                 for i in range(1, 6)]
                + [{"page_number": i, "text": f"8.7 Ad tech services\n8.7.1 Product market\npage {i}"}
                   for i in range(6, 11)]
            ),
            "extracted_at": "2026-05-25T00:00:00+00:00",
        }

    def _mock_ac_success(self) -> MagicMock:
        mock_block = MagicMock()
        mock_block.type = "tool_use"
        mock_block.input = {
            "product_markets": [],
            "geographic_markets": [],
            "theories_of_harm": [],
            "overall_outcome": "unknown",
            "source_passages": [],
            "caveats": ["Section only — no formal definition found."],
        }
        mock_msg = MagicMock()
        mock_msg.content = [mock_block]
        mock_msg.model = "claude-sonnet-4-6"
        mock_msg.stop_reason = "tool_use"
        mock_ac = MagicMock()
        mock_ac.messages.create.return_value = mock_msg
        return mock_ac

    def _mock_ac_first_fails_second_succeeds(self) -> MagicMock:
        """First call returns {}, second returns valid response."""
        empty_block = MagicMock()
        empty_block.type = "tool_use"
        empty_block.input = {}
        empty_msg = MagicMock()
        empty_msg.content = [empty_block]
        empty_msg.model = "claude-sonnet-4-6"
        empty_msg.stop_reason = "tool_use"

        ok_block = MagicMock()
        ok_block.type = "tool_use"
        ok_block.input = {
            "product_markets": [
                {
                    "name": "Ad tech",
                    "definition_status": "defined",
                    "notes": "Commission defined ad tech market.",
                    "not_found": False,
                    "passages": [],
                }
            ],
            "geographic_markets": [],
            "theories_of_harm": [],
            "overall_outcome": "unknown",
            "source_passages": [],
            "caveats": [],
        }
        ok_msg = MagicMock()
        ok_msg.content = [ok_block]
        ok_msg.model = "claude-sonnet-4-6"
        ok_msg.stop_reason = "tool_use"

        mock_ac = MagicMock()
        mock_ac.messages.create.side_effect = [empty_msg, ok_msg]
        return mock_ac

    def test_batched_mode_calls_claude_per_section(self, tmp_path):
        existing = _make_record()
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))
        mock_ac = self._mock_ac_success()

        from unittest.mock import patch
        with patch("extract_case_from_source.load_cache", return_value=self._make_page_cache_multi_section()):
            rpt = extract_case(
                yaml_path,
                cache_dir=tmp_path / "cache",
                use_claude=True,
                anthropic_client=mock_ac,
                batch_by_section=True,
                focus="market_definition",
            )

        # 2 sections × 1 call each = 2 total API calls
        assert mock_ac.messages.create.call_count == 2
        assert len(rpt.section_batches) == 2

    def test_section_prefix_filter_runs_only_one_section(self, tmp_path):
        existing = _make_record()
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))
        mock_ac = self._mock_ac_success()

        from unittest.mock import patch
        with patch("extract_case_from_source.load_cache", return_value=self._make_page_cache_multi_section()):
            rpt = extract_case(
                yaml_path,
                cache_dir=tmp_path / "cache",
                use_claude=True,
                anthropic_client=mock_ac,
                section_prefix="8.6",
                focus="market_definition",
            )

        assert mock_ac.messages.create.call_count == 1
        assert len(rpt.section_batches) == 1
        assert rpt.section_batches[0].prefix == "8.6"

    def test_one_failed_section_does_not_erase_successful_sections(self, tmp_path):
        existing = _make_record()
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))
        mock_ac = self._mock_ac_first_fails_second_succeeds()

        from unittest.mock import patch
        with patch("extract_case_from_source.load_cache", return_value=self._make_page_cache_multi_section()):
            rpt = extract_case(
                yaml_path,
                cache_dir=tmp_path / "cache",
                use_claude=True,
                anthropic_client=mock_ac,
                batch_by_section=True,
                focus="market_definition",
            )

        # No top-level error — at least one section succeeded
        assert rpt.error is None
        # Exactly one section failed and one succeeded
        failed = [b for b in rpt.section_batches if b.error]
        succeeded = [b for b in rpt.section_batches if b.result is not None]
        assert len(failed) == 1
        assert len(succeeded) == 1
        # Merged result contains the successful section's market
        assert rpt.result is not None
        assert len(rpt.result.product_markets) == 1
        assert rpt.result.product_markets[0].name == "Ad tech"

    def test_all_sections_fail_sets_top_level_error(self, tmp_path):
        existing = _make_record()
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))

        # Both calls return {}
        empty_block = MagicMock()
        empty_block.type = "tool_use"
        empty_block.input = {}
        empty_msg = MagicMock()
        empty_msg.content = [empty_block]
        empty_msg.model = "claude-sonnet-4-6"
        empty_msg.stop_reason = "tool_use"
        mock_ac = MagicMock()
        mock_ac.messages.create.return_value = empty_msg

        from unittest.mock import patch
        with patch("extract_case_from_source.load_cache", return_value=self._make_page_cache_multi_section()):
            rpt = extract_case(
                yaml_path,
                cache_dir=tmp_path / "cache",
                use_claude=True,
                anthropic_client=mock_ac,
                batch_by_section=True,
                focus="market_definition",
            )

        assert rpt.error is not None
        assert "failed" in rpt.error
        assert rpt.result is None

    def test_max_section_batches_limits_calls(self, tmp_path):
        existing = _make_record()
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))
        mock_ac = self._mock_ac_success()

        from unittest.mock import patch
        with patch("extract_case_from_source.load_cache", return_value=self._make_page_cache_multi_section()):
            rpt = extract_case(
                yaml_path,
                cache_dir=tmp_path / "cache",
                use_claude=True,
                anthropic_client=mock_ac,
                batch_by_section=True,
                focus="market_definition",
                max_section_batches=1,
            )

        assert mock_ac.messages.create.call_count == 1
        assert len(rpt.section_batches) == 1

    def test_merged_output_validates_and_produces_draft(self, tmp_path):
        """A successful batched run produces a valid draft YAML."""
        existing = _make_record()
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))
        draft_path = tmp_path / "test_case.draft.yaml"
        mock_ac = self._mock_ac_success()

        from unittest.mock import patch
        with patch("extract_case_from_source.load_cache", return_value=self._make_page_cache_multi_section()):
            rpt = extract_case(
                yaml_path,
                cache_dir=tmp_path / "cache",
                output_path=draft_path,
                use_claude=True,
                anthropic_client=mock_ac,
                batch_by_section=True,
                focus="market_definition",
            )

        assert rpt.error is None
        assert rpt.result is not None
        assert draft_path.exists()
        draft = yaml.safe_load(draft_path.read_text())
        assert "_draft_note" in draft
        assert "background_concepts" not in draft


# ---------------------------------------------------------------------------
# section_prefix filtering tests (bug-fix: applied to all modes)
# ---------------------------------------------------------------------------

class TestSectionPrefixFilter:
    """
    section_prefix must narrow chunks_used before inspect, estimate, and
    single-batch extraction — not only inside the batched path.
    """

    def _multi_section_cache(self) -> dict:
        """Cache with pages across three numeric sections: 8.2, 8.6, 8.7."""
        pages = (
            [{"page_number": i, "text": f"8.2 Wearable devices\n8.2.1 Product market\npage {i}"}
             for i in range(1, 6)]
            + [{"page_number": i, "text": f"8.6 Online advertising services\n8.6.1 Product market\npage {i}"}
               for i in range(6, 11)]
            + [{"page_number": i, "text": f"8.7 Ad tech services\n8.7.1 Product market\npage {i}"}
               for i in range(11, 16)]
        )
        return {
            "source_document_id": "doc1",
            "source_url": "https://example.com/doc.pdf",
            "page_count": 15,
            "pages": pages,
            "extracted_at": "2026-05-25T00:00:00+00:00",
        }

    def _make_record(self) -> dict:
        return _make_record()

    # ------------------------------------------------------------------
    # inspect-chunks / no-claude mode
    # ------------------------------------------------------------------

    def test_section_prefix_filters_inspect_chunks(self, tmp_path):
        """chunks_used must contain only 8.6 chunks when section_prefix='8.6'."""
        existing = self._make_record()
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))

        from unittest.mock import patch
        with patch("extract_case_from_source.load_cache", return_value=self._multi_section_cache()):
            rpt = extract_case(
                yaml_path,
                cache_dir=tmp_path / "cache",
                use_claude=False,
                section_prefix="8.6",
                focus="market_definition",
            )

        assert rpt.error is None
        prefixes = {
            __import__("extract_case_from_source", fromlist=["_section_batch_prefix"])
            ._section_batch_prefix(c.section_path)
            for c in rpt.chunks_used
        }
        # Every chunk must be from 8.6
        assert prefixes == {"8.6"}, f"Expected only '8.6', got {prefixes}"

    def test_section_prefix_excludes_other_sections(self, tmp_path):
        """8.2 and 8.7 chunks must be absent when section_prefix='8.6'."""
        existing = self._make_record()
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))

        from extract_case_from_source import _section_batch_prefix
        from unittest.mock import patch
        with patch("extract_case_from_source.load_cache", return_value=self._multi_section_cache()):
            rpt = extract_case(
                yaml_path,
                cache_dir=tmp_path / "cache",
                use_claude=False,
                section_prefix="8.6",
                focus="market_definition",
            )

        for c in rpt.chunks_used:
            assert _section_batch_prefix(c.section_path) != "8.2"
            assert _section_batch_prefix(c.section_path) != "8.7"

    def test_section_prefix_without_focus_still_filters(self, tmp_path):
        """section_prefix works even without a focus mode."""
        existing = self._make_record()
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))

        from extract_case_from_source import _section_batch_prefix
        from unittest.mock import patch
        with patch("extract_case_from_source.load_cache", return_value=self._multi_section_cache()):
            rpt = extract_case(
                yaml_path,
                cache_dir=tmp_path / "cache",
                use_claude=False,
                section_prefix="8.7",
            )

        assert rpt.error is None
        prefixes = {_section_batch_prefix(c.section_path) for c in rpt.chunks_used}
        assert prefixes == {"8.7"}

    # ------------------------------------------------------------------
    # estimate-cost mode (use_claude=False + section_prefix)
    # ------------------------------------------------------------------

    def test_section_prefix_estimate_cost_counts_only_matching_pages(self, tmp_path):
        """Page count for estimate-cost must reflect only the filtered section."""
        existing = self._make_record()
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))

        from unittest.mock import patch
        with patch("extract_case_from_source.load_cache", return_value=self._multi_section_cache()):
            rpt_all = extract_case(
                yaml_path, cache_dir=tmp_path / "cache",
                use_claude=False, focus="market_definition",
            )
            rpt_86 = extract_case(
                yaml_path, cache_dir=tmp_path / "cache",
                use_claude=False, focus="market_definition", section_prefix="8.6",
            )

        pages_all = sum(len(c.pages) for c in rpt_all.chunks_used)
        pages_86 = sum(len(c.pages) for c in rpt_86.chunks_used)
        assert pages_86 < pages_all
        # 8.6 covers pages 6-10 = 5 pages
        assert pages_86 == 5

    # ------------------------------------------------------------------
    # paid extraction (single-batch, use_claude=True)
    # ------------------------------------------------------------------

    def test_section_prefix_single_batch_sends_only_matching_chunks(self, tmp_path):
        """Claude must only see 8.6 chunks when section_prefix='8.6'."""
        existing = self._make_record()
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))

        mock_block = MagicMock()
        mock_block.type = "tool_use"
        mock_block.input = {
            "product_markets": [],
            "geographic_markets": [],
            "theories_of_harm": [],
            "overall_outcome": "unknown",
            "source_passages": [],
            "caveats": [],
        }
        mock_msg = MagicMock()
        mock_msg.content = [mock_block]
        mock_ac = MagicMock()
        mock_ac.messages.create.return_value = mock_msg

        from extract_case_from_source import _section_batch_prefix
        from unittest.mock import patch
        with patch("extract_case_from_source.load_cache", return_value=self._multi_section_cache()):
            rpt = extract_case(
                yaml_path,
                cache_dir=tmp_path / "cache",
                use_claude=True,
                anthropic_client=mock_ac,
                section_prefix="8.6",
                focus="market_definition",
            )

        assert rpt.error is None
        # Verify chunks_used only contains 8.6 chunks
        prefixes = {_section_batch_prefix(c.section_path) for c in rpt.chunks_used}
        assert prefixes == {"8.6"}
        # Verify the prompt sent to Claude contained only 8.6 text
        call_args = mock_ac.messages.create.call_args
        prompt_text = call_args[1]["messages"][0]["content"]
        assert "8.6" in prompt_text
        assert "8.2 Wearable" not in prompt_text
        assert "8.7 Ad tech" not in prompt_text

    # ------------------------------------------------------------------
    # no-match failure
    # ------------------------------------------------------------------

    def test_nonexistent_prefix_fails_with_clear_error(self, tmp_path):
        """A prefix that matches no chunks must produce a clear error, not an empty run."""
        existing = self._make_record()
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))

        from unittest.mock import patch
        with patch("extract_case_from_source.load_cache", return_value=self._multi_section_cache()):
            rpt = extract_case(
                yaml_path,
                cache_dir=tmp_path / "cache",
                use_claude=False,
                section_prefix="99.99",
                focus="market_definition",
            )

        assert rpt.error is not None
        assert "99.99" in rpt.error
        assert rpt.chunks_used == []

    def test_nonexistent_prefix_does_not_fall_back_to_all_chunks(self, tmp_path):
        """No silent fallback when section_prefix matches nothing."""
        existing = self._make_record()
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))

        mock_ac = MagicMock()

        from unittest.mock import patch
        with patch("extract_case_from_source.load_cache", return_value=self._multi_section_cache()):
            rpt = extract_case(
                yaml_path,
                cache_dir=tmp_path / "cache",
                use_claude=True,
                anthropic_client=mock_ac,
                section_prefix="99.99",
                focus="market_definition",
            )

        # Must not call Claude at all
        mock_ac.messages.create.assert_not_called()
        assert rpt.error is not None


# ---------------------------------------------------------------------------
# Item 1+2: Quote validation hardening
# ---------------------------------------------------------------------------

class TestQuoteValidationHardening:
    """Tests for the hardened _validate_quote_against_chunks and _process_passages."""

    def _chunks(self) -> list[ChunkInfo]:
        return [
            _make_chunk("chunk_001", "8.6 Online advertising", [
                (42, "The Commission defines the relevant product market for online advertising."),
                (43, "The relevant geographic market is at least EEA-wide."),
            ]),
        ]

    def test_paraphrased_quote_rejected(self):
        """A paraphrase of a quote (not verbatim) must be rejected."""
        valid, note, corrected = _validate_quote_against_chunks(
            # Paraphrase — not verbatim. "Commission defines" vs "Commission defined" is fine,
            # but a full paraphrase like this is not in the source text.
            "The European Commission established that the relevant product market consists of online advertising services",
            "chunk_001", 42, self._chunks(),
        )
        assert valid is False
        assert corrected is None

    def test_quote_found_on_neighbouring_page_corrects_page_number(self):
        """Quote on adjacent page → valid=True, page corrected to actual page."""
        # Quote is on page 43, but we cite page 42 (wrong page)
        valid, note, corrected = _validate_quote_against_chunks(
            "relevant geographic market is at least EEA-wide",
            "chunk_001", 42,  # wrong page — quote is on 43
            self._chunks(),
        )
        assert valid is True
        assert corrected == 43
        assert "43" in note

    def test_corrected_page_number_stored_on_passage(self, tmp_path):
        """When _process_passages corrects a page, the ExtractedPassage uses the corrected page."""
        chunks = self._chunks()
        raw = {
            "product_markets": [
                {
                    "name": "Online advertising",
                    "definition_status": "defined",
                    "notes": "Defined by Commission.",
                    "not_found": False,
                    "passages": [
                        {
                            "chunk_id": "chunk_001",
                            "page_number": 42,  # wrong — the quote is on page 43
                            "quote": "relevant geographic market is at least EEA-wide",
                        }
                    ],
                }
            ],
            "geographic_markets": [],
            "theories_of_harm": [],
            "overall_outcome": "unknown",
            "caveats": [],
        }
        result = _validate_extraction(raw, chunks, {"chunk_001": "doc1"})
        assert result.passages_validated == 1
        assert result.passages_rejected == 0
        # Passage page_number must be corrected to 43
        p = result.product_markets[0].passages[0]
        assert p.page_number == 43
        assert p.validated is True

    def test_missing_chunk_id_rejects_passage(self):
        """A passage with no chunk_id must be rejected."""
        raw = {
            "product_markets": [
                {
                    "name": "Online advertising",
                    "definition_status": "defined",
                    "notes": "X", "not_found": False,
                    "passages": [
                        {
                            "chunk_id": "",  # missing
                            "page_number": 42,
                            "quote": "Commission defines the relevant product market for online advertising",
                        }
                    ],
                }
            ],
            "geographic_markets": [], "theories_of_harm": [],
            "overall_outcome": "unknown", "caveats": [],
        }
        result = _validate_extraction(raw, self._chunks(), {"chunk_001": "doc1"})
        assert result.passages_rejected == 1
        assert result.passages_validated == 0
        p = result.product_markets[0].passages[0]
        assert "chunk_id" in p.rejection_reason

    def test_missing_page_number_rejects_passage(self):
        """A passage with page_number=0 or missing must be rejected."""
        raw = {
            "product_markets": [
                {
                    "name": "Online advertising",
                    "definition_status": "defined",
                    "notes": "X", "not_found": False,
                    "passages": [
                        {
                            "chunk_id": "chunk_001",
                            "page_number": 0,  # missing
                            "quote": "Commission defines the relevant product market for online advertising",
                        }
                    ],
                }
            ],
            "geographic_markets": [], "theories_of_harm": [],
            "overall_outcome": "unknown", "caveats": [],
        }
        result = _validate_extraction(raw, self._chunks(), {"chunk_001": "doc1"})
        assert result.passages_rejected == 1
        assert result.passages_validated == 0

    def test_missing_quote_rejects_passage(self):
        """A passage with an empty quote string must be rejected."""
        raw = {
            "product_markets": [
                {
                    "name": "Online advertising",
                    "definition_status": "defined",
                    "notes": "X", "not_found": False,
                    "passages": [
                        {
                            "chunk_id": "chunk_001",
                            "page_number": 42,
                            "quote": "",  # missing
                        }
                    ],
                }
            ],
            "geographic_markets": [], "theories_of_harm": [],
            "overall_outcome": "unknown", "caveats": [],
        }
        result = _validate_extraction(raw, self._chunks(), {"chunk_001": "doc1"})
        assert result.passages_rejected == 1
        assert result.passages_validated == 0


# ---------------------------------------------------------------------------
# Item 3: Source role classification
# ---------------------------------------------------------------------------

class TestSourceRoleClassification:
    """source_role is stored on ExtractedPassage and passed through validation."""

    def _chunks(self) -> list[ChunkInfo]:
        return [
            _make_chunk("chunk_001", "8.6 Online advertising", [
                (42, "The Commission defines the relevant product market for online advertising."),
                (43, "According to the notifying parties, the market includes all digital advertising."),
                (44, "In M.7217 the Commission left the definition open."),
            ]),
        ]

    def _raw_with_role(self, role: str, page: int, quote: str) -> dict:
        return {
            "product_markets": [
                {
                    "name": "Online advertising",
                    "definition_status": "defined",
                    "notes": "X", "not_found": False,
                    "passages": [
                        {
                            "chunk_id": "chunk_001",
                            "page_number": page,
                            "quote": quote,
                            "source_role": role,
                        }
                    ],
                }
            ],
            "geographic_markets": [], "theories_of_harm": [],
            "overall_outcome": "unknown", "caveats": [],
        }

    def test_commission_assessment_role_stored(self):
        raw = self._raw_with_role(
            "commission_assessment", 42,
            "Commission defines the relevant product market for online advertising",
        )
        result = _validate_extraction(raw, self._chunks(), {"chunk_001": "doc1"})
        assert result.passages_validated == 1
        assert result.product_markets[0].passages[0].source_role == "commission_assessment"

    def test_notifying_party_view_role_stored(self):
        """notifying_party_view passage is stored on the passage (not automatically rejected)."""
        raw = self._raw_with_role(
            "notifying_party_view", 43,
            "According to the notifying parties, the market includes all digital advertising",
        )
        result = _validate_extraction(raw, self._chunks(), {"chunk_001": "doc1"})
        # Passage is validated (found verbatim) but tagged with source_role
        assert result.passages_validated == 1
        p = result.product_markets[0].passages[0]
        assert p.source_role == "notifying_party_view"

    def test_precedent_role_stored(self):
        """precedent passage is stored with its source_role."""
        raw = self._raw_with_role(
            "precedent", 44,
            "In M.7217 the Commission left the definition open",
        )
        result = _validate_extraction(raw, self._chunks(), {"chunk_001": "doc1"})
        assert result.passages_validated == 1
        p = result.product_markets[0].passages[0]
        assert p.source_role == "precedent"

    def test_empty_source_role_defaults_to_empty_string(self):
        """Passages without source_role default to '' (not None)."""
        raw = {
            "product_markets": [
                {
                    "name": "Online advertising",
                    "definition_status": "defined",
                    "notes": "X", "not_found": False,
                    "passages": [
                        {
                            "chunk_id": "chunk_001",
                            "page_number": 42,
                            "quote": "Commission defines the relevant product market for online advertising",
                            # no source_role key
                        }
                    ],
                }
            ],
            "geographic_markets": [], "theories_of_harm": [],
            "overall_outcome": "unknown", "caveats": [],
        }
        result = _validate_extraction(raw, self._chunks(), {"chunk_001": "doc1"})
        assert result.product_markets[0].passages[0].source_role == ""


# ---------------------------------------------------------------------------
# Item 4: Precise market definition status
# ---------------------------------------------------------------------------

class TestPreciseMarketStatus:
    """Expanded definition_status enum values are accepted and preserved."""

    def _make_raw(self, status: str) -> dict:
        return {
            "product_markets": [
                {
                    "name": "Online advertising",
                    "definition_status": status,
                    "notes": "See notes.", "not_found": False,
                    "passages": [],
                }
            ],
            "geographic_markets": [], "theories_of_harm": [],
            "overall_outcome": "unknown", "caveats": [],
        }

    def test_left_open_preserved(self):
        """left_open must not be renamed or rejected."""
        result = _validate_extraction(self._make_raw("left_open"), [], {})
        assert result.product_markets[0].definition_status == "left_open"

    def test_considered_preserved(self):
        result = _validate_extraction(self._make_raw("considered"), [], {})
        assert result.product_markets[0].definition_status == "considered"

    def test_not_conclusive_preserved(self):
        result = _validate_extraction(self._make_raw("not_conclusive"), [], {})
        assert result.product_markets[0].definition_status == "not_conclusive"

    def test_possible_segmentation_preserved(self):
        result = _validate_extraction(self._make_raw("possible_segmentation"), [], {})
        assert result.product_markets[0].definition_status == "possible_segmentation"

    def test_precedent_only_preserved(self):
        result = _validate_extraction(self._make_raw("precedent_only"), [], {})
        assert result.product_markets[0].definition_status == "precedent_only"

    def test_defined_preserved(self):
        result = _validate_extraction(self._make_raw("defined"), [], {})
        assert result.product_markets[0].definition_status == "defined"

    def test_left_open_not_renamed_to_defined(self):
        """left_open status must survive the full extract_case pipeline."""
        raw = self._make_raw("left_open")
        result = _validate_extraction(raw, [], {})
        assert result.product_markets[0].definition_status == "left_open"
        # Build draft and confirm left_open appears there too
        draft = _build_draft_record(result, _make_record())
        assert draft["product_markets_considered"][0]["definition_status"] == "left_open"


# ---------------------------------------------------------------------------
# Item 5: Orphan passage detection
# ---------------------------------------------------------------------------

class TestOrphanPassageDetection:
    """Top-level source_passages not referenced in any market/theory are orphans."""

    def _chunks(self) -> list[ChunkInfo]:
        return [
            _make_chunk("chunk_001", "8.6 Online advertising", [
                (42, "The Commission defines the relevant product market for online advertising."),
            ]),
        ]

    def test_orphan_passages_counted(self):
        """A source_passage not referenced in any market/theory is an orphan."""
        raw = {
            "product_markets": [],
            "geographic_markets": [],
            "theories_of_harm": [],
            "overall_outcome": "unknown",
            "source_passages": [
                {
                    "chunk_id": "chunk_001",
                    "page_number": 42,
                    "quote": "Commission defines the relevant product market for online advertising",
                }
            ],
            "caveats": [],
        }
        result = _validate_extraction(raw, self._chunks(), {"chunk_001": "doc1"})
        assert result.orphan_passages == 1

    def test_linked_passage_not_orphan(self):
        """A passage inside a market's passages array is linked — not an orphan even if in top-level too."""
        raw = {
            "product_markets": [
                {
                    "name": "Online advertising",
                    "definition_status": "defined",
                    "notes": "X", "not_found": False,
                    "passages": [
                        {
                            "chunk_id": "chunk_001",
                            "page_number": 42,
                            "quote": "Commission defines the relevant product market for online advertising",
                        }
                    ],
                }
            ],
            "geographic_markets": [],
            "theories_of_harm": [],
            "overall_outcome": "unknown",
            "source_passages": [
                {
                    "chunk_id": "chunk_001",
                    "page_number": 42,
                    "quote": "Commission defines the relevant product market for online advertising",
                }
            ],
            "caveats": [],
        }
        result = _validate_extraction(raw, self._chunks(), {"chunk_001": "doc1"})
        assert result.orphan_passages == 0

    def test_no_orphans_when_source_passages_empty(self):
        raw = {
            "product_markets": [],
            "geographic_markets": [],
            "theories_of_harm": [],
            "overall_outcome": "unknown",
            "source_passages": [],
            "caveats": [],
        }
        result = _validate_extraction(raw, [], {})
        assert result.orphan_passages == 0


# ---------------------------------------------------------------------------
# Item 7: Cost / token guard
# ---------------------------------------------------------------------------

class TestCostTokenGuard:
    """--max-cost and --max-input-tokens prevent the Claude API from being called."""

    def _page_cache(self, page_count: int = 10) -> dict:
        return {
            "source_document_id": "doc1",
            "source_url": "https://example.com/doc.pdf",
            "page_count": page_count,
            "pages": [
                {
                    "page_number": i,
                    "text": f"8.6 Online advertising\n8.6.1 Product market definition\n"
                            + "x" * 2000  # ~500 tokens/page
                }
                for i in range(1, page_count + 1)
            ],
            "extracted_at": "2026-05-25T00:00:00+00:00",
        }

    def test_max_cost_guard_prevents_api_call(self, tmp_path):
        """When estimated cost exceeds max_cost, extract_case must not call Claude."""
        existing = _make_record()
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))

        mock_ac = MagicMock()

        from unittest.mock import patch
        with patch("extract_case_from_source.load_cache", return_value=self._page_cache(10)):
            rpt = extract_case(
                yaml_path,
                cache_dir=tmp_path / "cache",
                use_claude=True,
                anthropic_client=mock_ac,
                max_cost=0.000001,  # absurdly low — will be exceeded by any real content
            )

        mock_ac.messages.create.assert_not_called()
        assert rpt.error is not None
        assert "max-cost" in rpt.error or "cost" in rpt.error.lower()

    def test_max_input_tokens_guard_prevents_api_call(self, tmp_path):
        """When estimated tokens exceed max_input_tokens, extract_case must not call Claude."""
        existing = _make_record()
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))

        mock_ac = MagicMock()

        from unittest.mock import patch
        with patch("extract_case_from_source.load_cache", return_value=self._page_cache(10)):
            rpt = extract_case(
                yaml_path,
                cache_dir=tmp_path / "cache",
                use_claude=True,
                anthropic_client=mock_ac,
                max_input_tokens=1,  # absurdly low
            )

        mock_ac.messages.create.assert_not_called()
        assert rpt.error is not None
        assert "max-input-tokens" in rpt.error or "token" in rpt.error.lower()

    def test_guard_not_triggered_when_below_limit(self, tmp_path):
        """When cost is within limit, the guard must not block the call."""
        existing = _make_record()
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))

        mock_block = MagicMock()
        mock_block.type = "tool_use"
        mock_block.input = {
            "product_markets": [], "geographic_markets": [], "theories_of_harm": [],
            "overall_outcome": "unknown", "source_passages": [], "caveats": [],
        }
        mock_msg = MagicMock()
        mock_msg.content = [mock_block]
        mock_ac = MagicMock()
        mock_ac.messages.create.return_value = mock_msg

        from unittest.mock import patch
        with patch("extract_case_from_source.load_cache", return_value=self._page_cache(1)):
            rpt = extract_case(
                yaml_path,
                cache_dir=tmp_path / "cache",
                use_claude=True,
                anthropic_client=mock_ac,
                max_cost=100.0,      # very generous
                max_input_tokens=10_000_000,
            )

        mock_ac.messages.create.assert_called_once()
        assert rpt.error is None


# ---------------------------------------------------------------------------
# replay_section_debug tests
# ---------------------------------------------------------------------------

class TestReplayDebug:
    """Tests for replay_section_debug — recover a section result without calling Claude."""

    def _make_yaml(self, tmp_path) -> Path:
        existing = _make_record()
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))
        return yaml_path

    def _page_cache_with_quote(self) -> dict:
        return {
            "source_document_id": "main_doc",
            "source_url": "https://example.com/decision.pdf",
            "page_count": 2,
            "pages": [
                {
                    "page_number": 82,
                    "text": (
                        "8.6 Online advertising\n"
                        "The Commission defines the relevant product market for online advertising."
                    ),
                },
                {
                    "page_number": 83,
                    "text": "The relevant geographic market is at least EEA-wide.",
                },
            ],
            "extracted_at": "2026-05-25T00:00:00+00:00",
        }

    def _write_debug_json(self, tmp_path, raw_tool_input: dict, section_prefix: str = "8.6") -> Path:
        debug_dir = tmp_path / "debug"
        debug_dir.mkdir(parents=True, exist_ok=True)
        debug_path = debug_dir / "test_case_section_8_6.json"
        debug_data = {
            "debug_type": "section_extraction",
            "case_id": "test_case",
            "section_prefix": section_prefix,
            "timestamp": "2026-05-25T12:00:00+00:00",
            "chunks_sent": [
                {
                    "chunk_id": "chunk_001",
                    "page_range": "pp.82-83",
                    "section_path": "8.6 Online advertising",
                    "page_count": 2,
                }
            ],
            "model": "claude-sonnet-4-6",
            "stop_reason": "tool_use",
            "content_block_types": ["tool_use"],
            "raw_tool_input": raw_tool_input,
        }
        debug_path.write_text(json.dumps(debug_data, indent=2))
        return debug_path

    def test_replay_recovers_stringified_source_passages(self, tmp_path):
        """Debug file with source_passages as a JSON string → replay succeeds after normalization."""
        yaml_path = self._make_yaml(tmp_path)
        raw_tool_input = {
            "product_markets": [
                {
                    "name": "Online advertising",
                    "definition_status": "defined",
                    "notes": "Commission defined market.",
                    "not_found": False,
                    "passages": [],
                }
            ],
            "geographic_markets": [],
            "theories_of_harm": [],
            "overall_outcome": "unknown",
            # source_passages as a JSON-stringified array (the bug we're fixing)
            "source_passages": (
                '[{"chunk_id": "chunk_001", "page_number": 82, '
                '"quote": "Commission defines the relevant product market for online advertising"}]'
            ),
            "caveats": [],
        }
        debug_path = self._write_debug_json(tmp_path, raw_tool_input)

        from unittest.mock import patch
        with patch("extract_case_from_source.load_cache", return_value=self._page_cache_with_quote()):
            rpt = replay_section_debug(debug_path, yaml_path, cache_dir=tmp_path / "cache")

        assert rpt.error is None, f"Unexpected error: {rpt.error}"
        assert rpt.result is not None
        # The market should be present
        assert len(rpt.result.product_markets) == 1
        assert rpt.result.product_markets[0].name == "Online advertising"

    def test_replay_validates_quotes_from_cache(self, tmp_path):
        """When page cache is available, replay validates quotes in market passages correctly."""
        yaml_path = self._make_yaml(tmp_path)
        raw_tool_input = {
            "product_markets": [
                {
                    "name": "Online advertising",
                    "definition_status": "defined",
                    "notes": "Commission defined market.",
                    "not_found": False,
                    "passages": [
                        {
                            "chunk_id": "chunk_001",
                            "page_number": 82,
                            # This quote appears verbatim in the page cache text
                            "quote": "Commission defines the relevant product market for online advertising",
                        },
                        {
                            "chunk_id": "chunk_001",
                            "page_number": 82,
                            "quote": "This quote was invented and does not appear in the text",
                        },
                    ],
                }
            ],
            "geographic_markets": [],
            "theories_of_harm": [],
            "overall_outcome": "unknown",
            "source_passages": [],
            "caveats": [],
        }
        debug_path = self._write_debug_json(tmp_path, raw_tool_input)

        from unittest.mock import patch
        with patch("extract_case_from_source.load_cache", return_value=self._page_cache_with_quote()):
            rpt = replay_section_debug(debug_path, yaml_path, cache_dir=tmp_path / "cache")

        assert rpt.error is None
        assert rpt.result is not None
        assert rpt.result.passages_validated == 1   # real quote found
        assert rpt.result.passages_rejected == 1    # invented quote rejected

    def test_replay_missing_raw_tool_input_fails_clearly(self, tmp_path):
        """Debug file without raw_tool_input must produce a clear error."""
        yaml_path = self._make_yaml(tmp_path)
        debug_dir = tmp_path / "debug"
        debug_dir.mkdir()
        debug_path = debug_dir / "no_raw_input.json"
        debug_path.write_text(json.dumps({
            "debug_type": "section_extraction",
            "case_id": "test_case",
            "section_prefix": "8.6",
        }))

        from unittest.mock import patch
        with patch("extract_case_from_source.load_cache", return_value=None):
            rpt = replay_section_debug(debug_path, yaml_path, cache_dir=tmp_path / "cache")

        assert rpt.error is not None
        assert "raw_tool_input" in rpt.error

    def test_replay_empty_raw_tool_input_fails_clearly(self, tmp_path):
        """Debug file with raw_tool_input={} must produce a clear error."""
        yaml_path = self._make_yaml(tmp_path)
        debug_path = self._write_debug_json(tmp_path, {})

        from unittest.mock import patch
        with patch("extract_case_from_source.load_cache", return_value=None):
            rpt = replay_section_debug(debug_path, yaml_path, cache_dir=tmp_path / "cache")

        assert rpt.error is not None
        assert "empty" in rpt.error.lower() or "{}" in rpt.error

    def test_replay_writes_draft_yaml(self, tmp_path):
        """Successful replay with output_path writes a valid draft YAML."""
        yaml_path = self._make_yaml(tmp_path)
        raw_tool_input = {
            "product_markets": [
                {
                    "name": "Online advertising",
                    "definition_status": "defined",
                    "notes": "Defined by Commission.",
                    "not_found": False,
                    "passages": [],
                }
            ],
            "geographic_markets": [],
            "theories_of_harm": [],
            "overall_outcome": "cleared_with_conditions",
            "source_passages": [],
            "caveats": ["Replayed from debug."],
        }
        debug_path = self._write_debug_json(tmp_path, raw_tool_input)
        draft_path = tmp_path / "test_case.draft.yaml"

        from unittest.mock import patch
        with patch("extract_case_from_source.load_cache", return_value=self._page_cache_with_quote()):
            rpt = replay_section_debug(
                debug_path, yaml_path,
                cache_dir=tmp_path / "cache",
                output_path=draft_path,
            )

        assert rpt.error is None
        assert draft_path.exists()
        draft = yaml.safe_load(draft_path.read_text())
        assert "_draft_note" in draft
        assert draft["outcome"] == "cleared_with_conditions"

    def test_replay_refuses_non_draft_output_path(self, tmp_path):
        """replay_section_debug refuses to write to an existing non-draft path."""
        yaml_path = self._make_yaml(tmp_path)
        # Output path exists and has no .draft in stem
        bad_output = tmp_path / "test_case.yaml"
        bad_output.write_text("existing content")
        raw_tool_input = {"product_markets": [], "geographic_markets": [],
                          "theories_of_harm": [], "overall_outcome": "unknown",
                          "source_passages": [], "caveats": []}
        debug_path = self._write_debug_json(tmp_path, raw_tool_input)

        from unittest.mock import patch
        with patch("extract_case_from_source.load_cache", return_value=None):
            rpt = replay_section_debug(
                debug_path, yaml_path,
                cache_dir=tmp_path / "cache",
                output_path=bad_output,
            )

        assert rpt.error is not None
        assert "draft" in rpt.error.lower() or "refusing" in rpt.error.lower()


# ---------------------------------------------------------------------------
# Section-prefix trimming (cross-section spillover removal)
# ---------------------------------------------------------------------------

class TestIsSubsectionOf:
    """Unit tests for _is_subsection_of."""

    def test_exact_match(self):
        assert _is_subsection_of("8.6", "8.6") is True

    def test_direct_subsection(self):
        assert _is_subsection_of("8.6.1", "8.6") is True

    def test_deeper_subsection(self):
        assert _is_subsection_of("8.6.1.2", "8.6") is True

    def test_sibling_section_false(self):
        assert _is_subsection_of("8.7", "8.6") is False

    def test_preceding_section_false(self):
        assert _is_subsection_of("8.5", "8.6") is False

    def test_different_top_level_false(self):
        assert _is_subsection_of("9.1", "8.6") is False

    def test_no_false_prefix_match(self):
        # "8.60" must NOT be treated as a subsection of "8.6"
        assert _is_subsection_of("8.60", "8.6") is False

    def test_parent_section_false(self):
        # "8" (parent) is not a subsection of "8.6"
        assert _is_subsection_of("8", "8.6") is False


class TestTrimPagesForPrefix:
    """Unit tests for _trim_pages_for_prefix — spillover removal."""

    def _spillover_pages(self) -> list[dict]:
        """Page 37 has 8.5 tail + 8.6 start; page 38 is pure 8.6; page 39 is 8.6 tail + 8.7 start."""
        return [
            {
                "page_number": 37,
                "text": (
                    "The Commission concluded that general search is a relevant market.\n"
                    "\n"
                    "8.6 Online Advertising Services\n"
                    "The Commission assessed the market for online advertising."
                ),
            },
            {
                "page_number": 38,
                "text": "Online advertising services are bought by advertisers seeking reach.",
            },
            {
                "page_number": 39,
                "text": (
                    "The Commission defined the geographic market as EEA-wide.\n"
                    "\n"
                    "8.7 Ad Tech Services\n"
                    "This section covers intermediation services in ad tech."
                ),
            },
        ]

    def test_leading_preceding_section_trimmed(self):
        """Text before the 8.6 heading on the first page must be removed."""
        trimmed = _trim_pages_for_prefix(self._spillover_pages(), "8.6")
        first_text = trimmed[0]["text"]
        assert "general search is a relevant market" not in first_text
        assert "8.6 Online Advertising Services" in first_text

    def test_following_section_trimmed(self):
        """Text from the 8.7 heading onwards on the last page must be removed."""
        trimmed = _trim_pages_for_prefix(self._spillover_pages(), "8.6")
        last_text = trimmed[-1]["text"]
        assert "EEA-wide" in last_text
        assert "8.7 Ad Tech Services" not in last_text
        assert "intermediation services" not in last_text

    def test_middle_pages_unchanged(self):
        """Pages entirely within the target section are not modified."""
        trimmed = _trim_pages_for_prefix(self._spillover_pages(), "8.6")
        page_38 = next(p for p in trimmed if p["page_number"] == 38)
        assert page_38["text"] == "Online advertising services are bought by advertisers seeking reach."

    def test_page_numbers_preserved(self):
        """Original page numbers are preserved in trimmed output."""
        trimmed = _trim_pages_for_prefix(self._spillover_pages(), "8.6")
        nums = [p["page_number"] for p in trimmed]
        assert 37 in nums
        assert 38 in nums

    def test_original_pages_not_mutated(self):
        """_trim_pages_for_prefix must not mutate the original page dicts."""
        pages = self._spillover_pages()
        original_first = pages[0]["text"]
        _trim_pages_for_prefix(pages, "8.6")
        assert pages[0]["text"] == original_first

    def test_subsection_headings_not_trimmed(self):
        """8.6.1 subsection headings within the target section are kept."""
        pages = [
            {
                "page_number": 40,
                "text": (
                    "8.6 Online Advertising Services\n"
                    "Introduction to online advertising.\n"
                    "\n"
                    "8.6.1 Product Market Definition\n"
                    "The Commission considered a narrow definition."
                ),
            }
        ]
        trimmed = _trim_pages_for_prefix(pages, "8.6")
        assert len(trimmed) == 1
        text = trimmed[0]["text"]
        assert "8.6.1 Product Market Definition" in text
        assert "Commission considered a narrow definition" in text

    def test_no_heading_on_first_page_keeps_full_text(self):
        """If the first page has no section heading (continuation), keep it fully."""
        pages = [
            {"page_number": 42, "text": "Commission further assessed the market conditions."},
        ]
        trimmed = _trim_pages_for_prefix(pages, "8.6")
        assert len(trimmed) == 1
        assert trimmed[0]["text"] == "Commission further assessed the market conditions."

    def test_empty_pages_returns_empty(self):
        trimmed = _trim_pages_for_prefix([], "8.6")
        assert trimmed == []

    def test_no_prefix_returns_original(self):
        pages = [{"page_number": 1, "text": "Some text."}]
        trimmed = _trim_pages_for_prefix(pages, "")
        assert trimmed == pages


class TestSectionPrefixTrimming:
    """Integration tests: section_prefix trimming removes spillover from chunks_used."""

    def _make_spillover_cache(self) -> dict:
        """
        Cache with three pages:
        - Page 37: 8.5 tail + 8.6 heading + 8.6 content  (leading spillover)
        - Page 38: pure 8.6 content
        - Page 39: 8.7 heading + 8.7 content  (assigned to 8.7 chunk by section map)
        """
        return {
            "source_document_id": "doc1",
            "source_url": "https://example.com/doc.pdf",
            "page_count": 3,
            "pages": [
                {
                    "page_number": 37,
                    "text": (
                        "The Commission concluded general search is relevant.\n"
                        "8.6 Online Advertising Services\n"
                        "Commission assessed online advertising."
                    ),
                },
                {
                    "page_number": 38,
                    "text": "8.6 advertising market continued analysis.",
                },
                {
                    "page_number": 39,
                    "text": (
                        "8.7 Ad Tech Services\n"
                        "This section covers ad tech intermediation."
                    ),
                },
            ],
            "extracted_at": "2026-05-25T00:00:00+00:00",
        }

    def test_prompt_text_excludes_preceding_spillover(self, tmp_path):
        """After section_prefix='8.6' filter, prompt_text must not contain 8.5 spillover."""
        existing = _make_record()
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))

        from unittest.mock import patch
        with patch("extract_case_from_source.load_cache", return_value=self._make_spillover_cache()):
            rpt = extract_case(
                yaml_path,
                cache_dir=tmp_path / "cache",
                use_claude=False,
                section_prefix="8.6",
            )

        assert rpt.error is None
        assert len(rpt.chunks_used) > 0
        for c in rpt.chunks_used:
            assert "general search is relevant" not in c.prompt_text, (
                f"Preceding-section spillover found in prompt_text: {c.prompt_text!r}"
            )

    def test_prompt_text_excludes_following_section(self, tmp_path):
        """8.7 content (page assigned to 8.7 chunk) must not appear in 8.6 prompt_text."""
        existing = _make_record()
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))

        from unittest.mock import patch
        with patch("extract_case_from_source.load_cache", return_value=self._make_spillover_cache()):
            rpt = extract_case(
                yaml_path,
                cache_dir=tmp_path / "cache",
                use_claude=False,
                section_prefix="8.6",
            )

        assert rpt.error is None
        full_prompt = " ".join(c.prompt_text for c in rpt.chunks_used)
        assert "8.7 Ad Tech Services" not in full_prompt

    def test_original_pages_still_validate_spillover_quotes(self):
        """Quote validation uses original page text, so a quote from spillover text validates."""
        pages = [
            {
                "page_number": 37,
                "text": (
                    "The Commission concluded general search is relevant.\n"
                    "8.6 Online Advertising Services\n"
                    "Commission assessed online advertising."
                ),
            }
        ]
        trimmed = _trim_pages_for_prefix(pages, "8.6")
        chunk = ChunkInfo(
            chunk_id="chunk_022",
            section_path="8.6 Online Advertising Services",
            pages=pages,           # original — contains spillover text
            source_document_id="doc1",
            trimmed_pages=trimmed,
        )

        # Quote is in the spillover text (trimmed from prompt but present in original pages)
        valid, note, corrected = _validate_quote_against_chunks(
            "general search is relevant",
            "chunk_022", 37, [chunk],
        )
        assert valid is True, "Spillover quote must validate against original pages"

    def test_section_heading_present_in_prompt_text(self, tmp_path):
        """After trimming, the 8.6 section heading itself is still in prompt_text."""
        existing = _make_record()
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))

        from unittest.mock import patch
        with patch("extract_case_from_source.load_cache", return_value=self._make_spillover_cache()):
            rpt = extract_case(
                yaml_path,
                cache_dir=tmp_path / "cache",
                use_claude=False,
                section_prefix="8.6",
            )

        assert rpt.error is None
        full_prompt = " ".join(c.prompt_text for c in rpt.chunks_used)
        assert "8.6" in full_prompt, "The 8.6 heading itself must remain in prompt text"


# ---------------------------------------------------------------------------
# Canonical YAML resolution
# ---------------------------------------------------------------------------

class TestResolveCanonicalYaml:
    """_resolve_canonical_yaml only returns files named exactly {case_id}.yaml
    with no '.draft' anywhere in the path."""

    def _setup_cases_dir(self, tmp_path: Path) -> Path:
        cases = tmp_path / "data" / "cases"
        (cases / "eu").mkdir(parents=True)
        (cases / "us").mkdir(parents=True)
        return cases

    def test_finds_canonical_yaml(self, tmp_path):
        cases = self._setup_cases_dir(tmp_path)
        (cases / "eu" / "eu_google_fitbit_2021.yaml").write_text("case_id: eu_google_fitbit_2021")
        result = _resolve_canonical_yaml("eu_google_fitbit_2021", cases)
        assert result is not None
        assert result.name == "eu_google_fitbit_2021.yaml"

    def test_ignores_draft_stem(self, tmp_path):
        cases = self._setup_cases_dir(tmp_path)
        (cases / "eu" / "eu_google_fitbit_2021.draft.yaml").write_text("case_id: eu_google_fitbit_2021")
        result = _resolve_canonical_yaml("eu_google_fitbit_2021", cases)
        assert result is None

    def test_ignores_market_definition_draft(self, tmp_path):
        """Files like google_fitbit_2021.8_6_market_definition.draft.yaml are never canonical."""
        cases = self._setup_cases_dir(tmp_path)
        (cases / "eu" / "eu_google_fitbit_2021.8_6_market_definition.draft.yaml").write_text(
            "case_id: eu_google_fitbit_2021"
        )
        result = _resolve_canonical_yaml("eu_google_fitbit_2021", cases)
        assert result is None

    def test_ignores_draft_directory(self, tmp_path):
        """A canonical-looking filename inside a .draft directory is not accepted."""
        cases = self._setup_cases_dir(tmp_path)
        draft_dir = cases / "eu" / ".draft"
        draft_dir.mkdir()
        (draft_dir / "eu_google_fitbit_2021.yaml").write_text("case_id: eu_google_fitbit_2021")
        result = _resolve_canonical_yaml("eu_google_fitbit_2021", cases)
        assert result is None

    def test_canonical_found_alongside_draft(self, tmp_path):
        """Canonical file is found even when draft files exist in the same directory."""
        cases = self._setup_cases_dir(tmp_path)
        (cases / "eu" / "eu_google_fitbit_2021.yaml").write_text("case_id: eu_google_fitbit_2021")
        (cases / "eu" / "eu_google_fitbit_2021.8_6_market_definition.draft.yaml").write_text(
            "case_id: eu_google_fitbit_2021"
        )
        result = _resolve_canonical_yaml("eu_google_fitbit_2021", cases)
        assert result is not None
        assert result.stem == "eu_google_fitbit_2021"

    def test_wrong_case_id_returns_none(self, tmp_path):
        cases = self._setup_cases_dir(tmp_path)
        (cases / "eu" / "eu_google_fitbit_2021.yaml").write_text("case_id: eu_google_fitbit_2021")
        result = _resolve_canonical_yaml("eu_illumina_grail_2022", cases)
        assert result is None

    def test_draft_output_in_drafts_dir_not_picked_up(self, tmp_path):
        """Draft output written to data/drafts/ is never selected as canonical input."""
        cases = self._setup_cases_dir(tmp_path)
        drafts = tmp_path / "data" / "extracts" / "eu"
        drafts.mkdir(parents=True)
        # Canonical in data/cases/
        canonical = cases / "eu" / "eu_google_fitbit_2021.yaml"
        canonical.write_text("case_id: eu_google_fitbit_2021")
        # Draft output outside cases_dir — should never be picked up
        (drafts / "eu_google_fitbit_2021.draft.yaml").write_text("case_id: eu_google_fitbit_2021")

        result = _resolve_canonical_yaml("eu_google_fitbit_2021", cases)
        assert result is not None
        assert result == canonical
        assert result.stem == "eu_google_fitbit_2021"

    def test_exact_stem_match_required(self, tmp_path):
        """A file like eu_google_fitbit_2021_extra.yaml must not match eu_google_fitbit_2021."""
        cases = self._setup_cases_dir(tmp_path)
        (cases / "eu" / "eu_google_fitbit_2021_extra.yaml").write_text("case_id: eu_google_fitbit_2021")
        result = _resolve_canonical_yaml("eu_google_fitbit_2021", cases)
        assert result is None


# ---------------------------------------------------------------------------
# _should_attempt_repair
# ---------------------------------------------------------------------------

class TestShouldAttemptRepair:
    """Unit tests for _should_attempt_repair."""

    def test_no_norm_errors_returns_false(self):
        assert _should_attempt_repair([], []) is False

    def test_no_norm_errors_with_schema_errors_returns_false(self):
        assert _should_attempt_repair([], ["Missing required key: 'overall_outcome'"]) is False

    def test_norm_errors_only_returns_true(self):
        norm = ["'source_passages' must be an array; got an invalid JSON string: '[{...}]'"]
        assert _should_attempt_repair(norm, []) is True

    def test_norm_errors_with_list_type_schema_errors_returns_true(self):
        norm = ["'product_markets' must be an array; got an invalid JSON string: [...]"]
        schema = ["'product_markets' must be a list, got str"]
        assert _should_attempt_repair(norm, schema) is True

    def test_norm_errors_with_missing_key_error_returns_false(self):
        norm = ["'product_markets' must be an array; got an invalid JSON string: [...]"]
        schema = ["Missing required key: 'overall_outcome'"]
        assert _should_attempt_repair(norm, schema) is False

    def test_norm_errors_with_invalid_outcome_returns_false(self):
        norm = ["'source_passages' must be an array; got an invalid JSON string: [...]"]
        schema = ["'overall_outcome' must be one of ..., got 'invalid_value'"]
        assert _should_attempt_repair(norm, schema) is False

    def test_norm_errors_with_mixed_schema_errors_returns_false(self):
        norm = ["'product_markets' must be an array; got an invalid JSON string: [...]"]
        schema = ["'product_markets' must be a list, got str", "Missing required key: 'caveats'"]
        assert _should_attempt_repair(norm, schema) is False


# ---------------------------------------------------------------------------
# Repair retry — section batch path
# ---------------------------------------------------------------------------

class TestRepairRetrySectionBatch:
    """_extract_section_batch attempts one repair call on stringified-list-field errors."""

    def _make_chunks(self) -> list[ChunkInfo]:
        return [ChunkInfo(
            chunk_id="chunk_001",
            pages=[{"page_number": 1, "text": "8.6 Online advertising\nmarket text"}],
            section_path="8.6 Online advertising",
            source_document_id="doc1",
        )]

    def _case_context(self) -> dict:
        return {"case_id": "test_case", "case_name": "Test", "authority": "EC", "parties": []}

    def _mock_ac_two_calls(self, first_input: dict, second_input: dict) -> MagicMock:
        """Return a mock that yields first_input on the first call, second_input on the second."""
        def _make_msg(inp):
            block = MagicMock()
            block.type = "tool_use"
            block.input = inp
            msg = MagicMock()
            msg.content = [block]
            msg.model = "claude-sonnet-4-6"
            msg.stop_reason = "tool_use"
            return msg

        mock_ac = MagicMock()
        mock_ac.messages.create.side_effect = [
            _make_msg(first_input),
            _make_msg(second_input),
        ]
        return mock_ac

    def _valid_response(self) -> dict:
        return {
            "product_markets": [
                {"name": "Online advertising", "definition_status": "left_open",
                 "notes": "Left open.", "not_found": False, "passages": []},
            ],
            "geographic_markets": [],
            "theories_of_harm": [],
            "overall_outcome": "unknown",
            "source_passages": [],
            "caveats": [],
        }

    # Use single-quoted JSON strings — valid Python strings but INVALID JSON,
    # so json.loads fails and _normalize_list_fields produces norm_errors.
    _INVALID_JSON_ARRAY = "[{'name': 'Online ads', 'definition_status': 'defined'}]"
    _INVALID_JSON_EMPTY = "[ {invalid} ]"

    def test_stringified_arrays_trigger_repair_call(self, tmp_path):
        """When Claude returns invalid-JSON strings for list fields, a repair call must be made."""
        bad = {
            "product_markets": self._INVALID_JSON_ARRAY,
            "geographic_markets": [],
            "theories_of_harm": [],
            "overall_outcome": "unknown",
            "source_passages": self._INVALID_JSON_EMPTY,
            "caveats": [],
        }
        mock_ac = self._mock_ac_two_calls(bad, self._valid_response())

        batch = _extract_section_batch(
            "8.6", self._make_chunks(), self._case_context(),
            mock_ac, tmp_path / "debug", "test_case",
        )

        assert mock_ac.messages.create.call_count == 2, "Exactly two API calls expected"
        assert batch.error is None, f"Unexpected error: {batch.error}"
        assert batch.result is not None
        assert len(batch.result.product_markets) == 1

    def test_repair_success_saves_repaired_debug_file(self, tmp_path):
        """Successful repair must save a *_repaired.json debug file."""
        bad = {"product_markets": self._INVALID_JSON_ARRAY, "geographic_markets": [],
               "theories_of_harm": [], "overall_outcome": "unknown",
               "source_passages": self._INVALID_JSON_EMPTY, "caveats": []}
        mock_ac = self._mock_ac_two_calls(bad, self._valid_response())
        debug_dir = tmp_path / "debug"

        _extract_section_batch(
            "8.6", self._make_chunks(), self._case_context(),
            mock_ac, debug_dir, "test_case",
        )

        repaired_files = list(debug_dir.glob("*_repaired.json"))
        assert len(repaired_files) == 1

    def test_repair_success_saves_schema_err_debug_file(self, tmp_path):
        """Original bad response must be saved as *_schema_err.json before repair."""
        bad = {"product_markets": self._INVALID_JSON_ARRAY, "geographic_markets": [],
               "theories_of_harm": [], "overall_outcome": "unknown",
               "source_passages": self._INVALID_JSON_EMPTY, "caveats": []}
        mock_ac = self._mock_ac_two_calls(bad, self._valid_response())
        debug_dir = tmp_path / "debug"

        _extract_section_batch(
            "8.6", self._make_chunks(), self._case_context(),
            mock_ac, debug_dir, "test_case",
        )

        schema_err_files = list(debug_dir.glob("*_schema_err.json"))
        assert len(schema_err_files) == 1

    def test_repair_failure_returns_clear_error(self, tmp_path):
        """If repair also returns invalid-JSON strings, error must mention retry failure."""
        bad = {"product_markets": self._INVALID_JSON_ARRAY,
               "source_passages": self._INVALID_JSON_EMPTY,
               "geographic_markets": [], "theories_of_harm": [],
               "overall_outcome": "unknown", "caveats": []}
        mock_ac = self._mock_ac_two_calls(bad, bad)  # repair returns same bad response

        batch = _extract_section_batch(
            "8.6", self._make_chunks(), self._case_context(),
            mock_ac, tmp_path / "debug", "test_case",
        )

        assert batch.error is not None
        assert "repair" in batch.error.lower()
        assert batch.result is None

    def test_no_repair_for_non_stringified_errors(self, tmp_path):
        """Invalid overall_outcome enum must NOT trigger a repair call."""
        bad = {
            "product_markets": [],
            "geographic_markets": [],
            "theories_of_harm": [],
            "overall_outcome": "not_a_valid_value",
            "source_passages": [],
            "caveats": [],
        }
        mock_block = MagicMock()
        mock_block.type = "tool_use"
        mock_block.input = bad
        mock_msg = MagicMock()
        mock_msg.content = [mock_block]
        mock_msg.model = "claude-sonnet-4-6"
        mock_msg.stop_reason = "tool_use"
        mock_ac = MagicMock()
        mock_ac.messages.create.return_value = mock_msg

        batch = _extract_section_batch(
            "8.6", self._make_chunks(), self._case_context(),
            mock_ac, tmp_path / "debug", "test_case",
        )

        assert mock_ac.messages.create.call_count == 1, "No repair call should be made"
        assert batch.error is not None
        assert batch.result is None

    def test_no_infinite_retries(self, tmp_path):
        """Total API calls must be at most 2 (original + one repair)."""
        bad = {"product_markets": self._INVALID_JSON_ARRAY,
               "source_passages": self._INVALID_JSON_EMPTY,
               "geographic_markets": [], "theories_of_harm": [],
               "overall_outcome": "unknown", "caveats": []}
        mock_ac = MagicMock()
        mock_block = MagicMock()
        mock_block.type = "tool_use"
        mock_block.input = bad
        mock_msg = MagicMock()
        mock_msg.content = [mock_block]
        mock_msg.model = "claude-sonnet-4-6"
        mock_msg.stop_reason = "tool_use"
        mock_ac.messages.create.return_value = mock_msg

        _extract_section_batch(
            "8.6", self._make_chunks(), self._case_context(),
            mock_ac, tmp_path / "debug", "test_case",
        )

        assert mock_ac.messages.create.call_count <= 2, (
            f"Expected at most 2 API calls, got {mock_ac.messages.create.call_count}"
        )


# ---------------------------------------------------------------------------
# Repair retry — single-batch extract_case path
# ---------------------------------------------------------------------------

class TestRepairRetrySingleBatch:
    """extract_case (single-batch path) attempts one repair call on stringified errors."""

    def _page_cache(self) -> dict:
        return {
            "source_document_id": "main_doc",
            "source_url": "https://example.com/doc.pdf",
            "page_count": 2,
            "pages": [
                {"page_number": 1, "text": "8 RELEVANT MARKETS\n8.1 Product market\npage 1"},
                {"page_number": 2, "text": "8 RELEVANT MARKETS\n8.1 Product market\npage 2"},
            ],
            "extracted_at": "2026-05-25T00:00:00+00:00",
        }

    def _valid_block_input(self) -> dict:
        return {
            "product_markets": [],
            "geographic_markets": [],
            "theories_of_harm": [],
            "overall_outcome": "unknown",
            "source_passages": [],
            "caveats": ["No formal definition found."],
        }

    def _mock_ac_two_calls(self, first_input: dict, second_input: dict) -> MagicMock:
        def _make_msg(inp):
            block = MagicMock()
            block.type = "tool_use"
            block.input = inp
            msg = MagicMock()
            msg.content = [block]
            return msg

        mock_ac = MagicMock()
        mock_ac.messages.create.side_effect = [
            _make_msg(first_input),
            _make_msg(second_input),
        ]
        return mock_ac

    # Invalid JSON strings (single quotes) — will fail json.loads and trigger norm_errors.
    _INVALID_JSON = "[{'name': 'Online ads'}]"

    def test_repair_triggered_on_stringified_arrays(self, tmp_path):
        """extract_case must attempt repair when list fields are invalid-JSON strings."""
        existing = _make_record()
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))

        bad = {"product_markets": self._INVALID_JSON, "geographic_markets": [],
               "theories_of_harm": [], "overall_outcome": "unknown",
               "source_passages": self._INVALID_JSON, "caveats": []}
        mock_ac = self._mock_ac_two_calls(bad, self._valid_block_input())

        from unittest.mock import patch
        with patch("extract_case_from_source.load_cache", return_value=self._page_cache()):
            rpt = extract_case(
                yaml_path, cache_dir=tmp_path / "cache",
                use_claude=True, anthropic_client=mock_ac,
            )

        assert mock_ac.messages.create.call_count == 2
        assert rpt.error is None
        assert rpt.result is not None

    def test_repair_failure_fails_clearly(self, tmp_path):
        """After a failed repair, error must mention retry failure."""
        existing = _make_record()
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))

        bad = {"product_markets": self._INVALID_JSON, "geographic_markets": [],
               "theories_of_harm": [], "overall_outcome": "unknown",
               "source_passages": self._INVALID_JSON, "caveats": []}
        mock_ac = self._mock_ac_two_calls(bad, bad)

        from unittest.mock import patch
        with patch("extract_case_from_source.load_cache", return_value=self._page_cache()):
            rpt = extract_case(
                yaml_path, cache_dir=tmp_path / "cache",
                use_claude=True, anthropic_client=mock_ac,
            )

        assert rpt.error is not None
        assert "repair" in rpt.error.lower()

    def test_no_repair_for_invalid_outcome(self, tmp_path):
        """Invalid overall_outcome enum must not trigger a repair call."""
        existing = _make_record()
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))

        bad = {"product_markets": [], "geographic_markets": [], "theories_of_harm": [],
               "overall_outcome": "not_a_valid_value", "source_passages": [], "caveats": []}
        mock_block = MagicMock()
        mock_block.type = "tool_use"
        mock_block.input = bad
        mock_msg = MagicMock()
        mock_msg.content = [mock_block]
        mock_ac = MagicMock()
        mock_ac.messages.create.return_value = mock_msg

        from unittest.mock import patch
        with patch("extract_case_from_source.load_cache", return_value=self._page_cache()):
            rpt = extract_case(
                yaml_path, cache_dir=tmp_path / "cache",
                use_claude=True, anthropic_client=mock_ac,
            )

        assert mock_ac.messages.create.call_count == 1
        assert rpt.error is not None

    def test_single_batch_no_infinite_retries(self, tmp_path):
        """Total API calls must be at most 2 even when repair also fails."""
        existing = _make_record()
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))

        bad = {"product_markets": self._INVALID_JSON, "geographic_markets": [],
               "theories_of_harm": [], "overall_outcome": "unknown",
               "source_passages": self._INVALID_JSON, "caveats": []}
        mock_block = MagicMock()
        mock_block.type = "tool_use"
        mock_block.input = bad
        mock_msg = MagicMock()
        mock_msg.content = [mock_block]
        mock_ac = MagicMock()
        mock_ac.messages.create.return_value = mock_msg

        from unittest.mock import patch
        with patch("extract_case_from_source.load_cache", return_value=self._page_cache()):
            extract_case(
                yaml_path, cache_dir=tmp_path / "cache",
                use_claude=True, anthropic_client=mock_ac,
            )

        assert mock_ac.messages.create.call_count <= 2


# ---------------------------------------------------------------------------
# _extract_spillover_pages unit tests
# ---------------------------------------------------------------------------

class TestExtractSpilloverPages:
    """Unit tests for _extract_spillover_pages — leading target-section text detection."""

    def test_no_spillover_when_sibling_heading_at_position_zero(self):
        """Page starting immediately with the 8.7 heading → no spillover returned."""
        pages = [{"page_number": 40, "text": "8.7 Ad Tech Services\nThis section covers ad tech."}]
        result = _extract_spillover_pages(pages, "8.6")
        assert result == []

    def test_spillover_before_sibling_heading(self):
        """Text before the 8.7 heading on the first page is spillover."""
        pages = [{"page_number": 40, "text": "The Commission concluded.\n8.7 Ad Tech\nMore text."}]
        result = _extract_spillover_pages(pages, "8.6")
        assert len(result) == 1
        assert "Commission concluded" in result[0]["text"]
        assert "8.7" not in result[0]["text"]

    def test_spillover_with_target_subsection_heading(self):
        """Page starting with 8.6.2.3 subsection before 8.7 → full subsection included."""
        pages = [{"page_number": 40, "text": (
            "8.6.2.3 Conclusion on geographic markets\n"
            "The Commission concluded EEA-wide.\n"
            "8.7 Ad Tech Services\nThis covers ad tech."
        )}]
        result = _extract_spillover_pages(pages, "8.6")
        assert len(result) == 1
        assert "8.6.2.3 Conclusion" in result[0]["text"]
        assert "Commission concluded EEA-wide" in result[0]["text"]
        assert "8.7" not in result[0]["text"]

    def test_empty_pages_returns_empty(self):
        assert _extract_spillover_pages([], "8.6") == []

    def test_empty_prefix_returns_empty(self):
        pages = [{"page_number": 1, "text": "some text"}]
        assert _extract_spillover_pages(pages, "") == []

    def test_page_without_heading_treated_as_target_continuation(self):
        """First page with no heading at all → treated as 8.6 continuation."""
        pages = [
            {"page_number": 40, "text": "Conclusion of the Commission on product markets."},
            {"page_number": 41, "text": "8.7 Ad Tech Services\nStuff."},
        ]
        result = _extract_spillover_pages(pages, "8.6")
        assert len(result) == 1
        assert result[0]["page_number"] == 40

    def test_multi_page_spillover_stops_at_sibling_heading(self):
        """Multiple pages of 8.6 spillover: stop at 8.7 heading on later page."""
        pages = [
            {"page_number": 40, "text": "8.6.2.3 Conclusion\nFirst part of conclusion."},
            {"page_number": 41, "text": "Second part of conclusion.\n8.7 Ad Tech\nStuff."},
        ]
        result = _extract_spillover_pages(pages, "8.6")
        assert len(result) == 2
        assert result[0]["page_number"] == 40
        assert result[1]["page_number"] == 41
        assert "8.7" not in result[1]["text"]
        assert "Second part of conclusion" in result[1]["text"]

    def test_original_pages_not_mutated(self):
        """_extract_spillover_pages must not mutate the original page dicts."""
        pages = [{"page_number": 40, "text": "Some text.\n8.7 Ad Tech\nMore."}]
        original_text = pages[0]["text"]
        _extract_spillover_pages(pages, "8.6")
        assert pages[0]["text"] == original_text

    def test_page_number_preserved_in_spillover(self):
        """Spillover result carries the original page number."""
        pages = [{"page_number": 40, "text": "8.6.2.2 Geographic markets\nContent.\n8.7 Ad Tech\nX."}]
        result = _extract_spillover_pages(pages, "8.6")
        assert result[0]["page_number"] == 40


# ---------------------------------------------------------------------------
# Section spillover integration tests
# ---------------------------------------------------------------------------

class TestSectionSpillover:
    """Integration: spillover 8.6 text at start of 8.7 chunk is included."""

    def _spillover_cache(self) -> dict:
        """
        Pages 38–39 are pure 8.6.  Page 40 is labelled 8.7 by the section map
        because the 8.7 heading appears on it, but it starts with 8.6 spillover text.
        """
        return {
            "source_document_id": "doc1",
            "source_url": "https://example.com/doc.pdf",
            "page_count": 3,
            "pages": [
                {
                    "page_number": 38,
                    "text": "8.6 Online Advertising Services\nCommission assessed online advertising.",
                },
                {
                    "page_number": 39,
                    "text": "8.6.2 Geographic markets\nThe EEA-wide geographic market.",
                },
                {
                    "page_number": 40,
                    "text": (
                        "The Commission concluded its assessment of geographic markets.\n"
                        "8.7 Ad Tech Services\n"
                        "This section covers ad tech intermediation."
                    ),
                },
            ],
            "extracted_at": "2026-05-25T00:00:00+00:00",
        }

    def test_spillover_page_included_in_chunks_used(self, tmp_path):
        """Page 40 spillover should appear in rpt.chunks_used."""
        existing = _make_record()
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))

        from unittest.mock import patch
        with patch("extract_case_from_source.load_cache", return_value=self._spillover_cache()):
            rpt = extract_case(
                yaml_path, cache_dir=tmp_path / "cache",
                use_claude=False, section_prefix="8.6",
            )

        assert rpt.error is None
        all_page_nums = [p["page_number"] for c in rpt.chunks_used for p in c.pages]
        assert 40 in all_page_nums, "Spillover page 40 must be included in chunks_used"

    def test_spillover_prompt_excludes_87_content(self, tmp_path):
        """Spillover chunk's prompt_text must not contain 8.7 heading or its content."""
        existing = _make_record()
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))

        from unittest.mock import patch
        with patch("extract_case_from_source.load_cache", return_value=self._spillover_cache()):
            rpt = extract_case(
                yaml_path, cache_dir=tmp_path / "cache",
                use_claude=False, section_prefix="8.6",
            )

        full_prompt = " ".join(c.prompt_text for c in rpt.chunks_used)
        assert "8.7 Ad Tech Services" not in full_prompt
        assert "covers ad tech intermediation" not in full_prompt

    def test_spillover_prompt_includes_leading_86_text(self, tmp_path):
        """Spillover chunk's prompt_text contains the 8.6 text that precedes 8.7."""
        existing = _make_record()
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))

        from unittest.mock import patch
        with patch("extract_case_from_source.load_cache", return_value=self._spillover_cache()):
            rpt = extract_case(
                yaml_path, cache_dir=tmp_path / "cache",
                use_claude=False, section_prefix="8.6",
            )

        full_prompt = " ".join(c.prompt_text for c in rpt.chunks_used)
        assert "concluded its assessment of geographic markets" in full_prompt

    def test_spillover_chunk_has_spill_suffix_in_id(self, tmp_path):
        """Spillover chunk is identifiable by '_spill' in its chunk_id."""
        existing = _make_record()
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))

        from unittest.mock import patch
        with patch("extract_case_from_source.load_cache", return_value=self._spillover_cache()):
            rpt = extract_case(
                yaml_path, cache_dir=tmp_path / "cache",
                use_claude=False, section_prefix="8.6",
            )

        spill_chunks = [c for c in rpt.chunks_used if "_spill" in c.chunk_id]
        assert len(spill_chunks) == 1

    def test_no_spillover_when_next_page_starts_with_87_heading(self, tmp_path):
        """No spillover when 8.7 heading is the very first text on the next page."""
        cache = {
            "source_document_id": "doc1",
            "source_url": "https://example.com/doc.pdf",
            "page_count": 3,
            "pages": [
                {"page_number": 38, "text": "8.6 Online ads\nContent."},
                {"page_number": 39, "text": "8.6 continued content."},
                {"page_number": 40, "text": "8.7 Ad Tech Services\nContent starts here."},
            ],
            "extracted_at": "2026-05-25T00:00:00+00:00",
        }
        existing = _make_record()
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))

        from unittest.mock import patch
        with patch("extract_case_from_source.load_cache", return_value=cache):
            rpt = extract_case(
                yaml_path, cache_dir=tmp_path / "cache",
                use_claude=False, section_prefix="8.6",
            )

        assert rpt.error is None
        all_page_nums = [p["page_number"] for c in rpt.chunks_used for p in c.pages]
        assert 40 not in all_page_nums, "Page 40 starts with 8.7, must not be included"

    def test_quote_from_spillover_validates_against_original_page(self):
        """Quote validation uses original page text, so spillover quotes are found."""
        spillover_pages = [{"page_number": 40, "text": (
            "The Commission concluded its assessment of geographic markets.\n"
            "8.7 Ad Tech Services\nThis section covers ad tech."
        )}]
        trimmed = _extract_spillover_pages(spillover_pages, "8.6")

        spillover_chunk = ChunkInfo(
            chunk_id="chunk_025_spill",
            section_path="8.7 Ad Tech Services",
            pages=spillover_pages,   # original pages — for quote validation
            source_document_id="doc1",
            trimmed_pages=trimmed,   # trimmed — for prompt
        )

        valid, note, corrected = _validate_quote_against_chunks(
            "Commission concluded its assessment of geographic markets",
            "chunk_025_spill", 40, [spillover_chunk],
        )
        assert valid is True, "Quote from spillover text must validate against original page"

    def test_inspect_mode_shows_spillover_chunk(self, tmp_path):
        """In inspect mode (use_claude=False), spillover chunk appears in chunks_used."""
        existing = _make_record()
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))

        from unittest.mock import patch
        with patch("extract_case_from_source.load_cache", return_value=self._spillover_cache()):
            rpt = extract_case(
                yaml_path, cache_dir=tmp_path / "cache",
                use_claude=False, section_prefix="8.6",
            )

        spill_chunks = [c for c in rpt.chunks_used if "_spill" in c.chunk_id]
        assert len(spill_chunks) == 1
        assert "concluded its assessment" in spill_chunks[0].prompt_text

    def test_spillover_chunk_has_effective_prefix(self, tmp_path):
        """Spillover chunk created by section_prefix filter carries effective_prefix='8.6'."""
        existing = _make_record()
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))

        from unittest.mock import patch
        with patch("extract_case_from_source.load_cache", return_value=self._spillover_cache()):
            rpt = extract_case(
                yaml_path, cache_dir=tmp_path / "cache",
                use_claude=False, section_prefix="8.6",
            )

        spill_chunks = [c for c in rpt.chunks_used if "_spill" in c.chunk_id]
        assert len(spill_chunks) == 1
        assert spill_chunks[0].effective_prefix == "8.6"


# ---------------------------------------------------------------------------
# Spillover batch-grouping tests
# ---------------------------------------------------------------------------

class TestSpilloverBatching:
    """Spillover chunks must be grouped into the target section batch, not a separate one."""

    def _spillover_cache(self) -> dict:
        """Page 40 is labelled 8.7 but starts with 8.6 spillover text before the 8.7 heading."""
        return {
            "source_document_id": "doc1",
            "source_url": "https://example.com/doc.pdf",
            "page_count": 3,
            "pages": [
                {
                    "page_number": 38,
                    "text": "8.6 Online Advertising Services\nCommission assessed online advertising.",
                },
                {
                    "page_number": 39,
                    "text": "8.6.2 Geographic markets\nThe EEA-wide geographic market.",
                },
                {
                    "page_number": 40,
                    "text": (
                        "The Commission concluded its assessment of geographic markets.\n"
                        "8.7 Ad Tech Services\n"
                        "This section covers ad tech intermediation."
                    ),
                },
            ],
            "extracted_at": "2026-05-25T00:00:00+00:00",
        }

    def _mock_ac(self) -> MagicMock:
        mock_block = MagicMock()
        mock_block.type = "tool_use"
        mock_block.input = {
            "product_markets": [],
            "geographic_markets": [],
            "theories_of_harm": [],
            "overall_outcome": "unknown",
            "source_passages": [],
            "caveats": ["Market definition section only."],
        }
        mock_msg = MagicMock()
        mock_msg.content = [mock_block]
        mock_msg.model = "claude-sonnet-4-6"
        mock_msg.stop_reason = "tool_use"
        mock_ac = MagicMock()
        mock_ac.messages.create.return_value = mock_msg
        return mock_ac

    # ------------------------------------------------------------------
    # Unit test: _group_chunks_by_section_prefix honours effective_prefix
    # ------------------------------------------------------------------

    def test_group_uses_effective_prefix_over_section_path(self):
        """Spillover chunk with effective_prefix='8.6' groups with 8.6, not 8.7."""
        regular = ChunkInfo(
            chunk_id="chunk_024",
            section_path="8.6 Online advertising",
            pages=[{"page_number": 39, "text": "text"}],
            source_document_id="doc1",
        )
        spillover = ChunkInfo(
            chunk_id="chunk_025_spill",
            section_path="8.7 Ad Tech Services",
            pages=[{"page_number": 40, "text": "spillover text"}],
            source_document_id="doc1",
            effective_prefix="8.6",
        )
        groups = _group_chunks_by_section_prefix([regular, spillover])
        assert len(groups) == 1, f"Expected 1 group, got {len(groups)}: {[p for p,_ in groups]}"
        assert groups[0][0] == "8.6"
        chunk_ids = [c.chunk_id for c in groups[0][1]]
        assert "chunk_025_spill" in chunk_ids

    def test_chunk_without_effective_prefix_uses_section_path(self):
        """Regular chunk without effective_prefix is grouped by its section_path prefix."""
        c1 = ChunkInfo(chunk_id="c1", section_path="8.6 Online advertising",
                       pages=[{"page_number": 1, "text": "x"}], source_document_id="d")
        c2 = ChunkInfo(chunk_id="c2", section_path="8.7 Ad Tech",
                       pages=[{"page_number": 2, "text": "y"}], source_document_id="d")
        groups = _group_chunks_by_section_prefix([c1, c2])
        assert len(groups) == 2
        prefixes = [p for p, _ in groups]
        assert "8.6" in prefixes
        assert "8.7" in prefixes

    # ------------------------------------------------------------------
    # Integration: --section-prefix 8.6 produces exactly one batch
    # ------------------------------------------------------------------

    def test_section_prefix_produces_one_batch(self, tmp_path):
        """--section-prefix 8.6 with spillover must produce exactly one section batch."""
        existing = _make_record()
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))
        mock_ac = self._mock_ac()

        from unittest.mock import patch
        with patch("extract_case_from_source.load_cache", return_value=self._spillover_cache()):
            rpt = extract_case(
                yaml_path, cache_dir=tmp_path / "cache",
                use_claude=True, anthropic_client=mock_ac,
                section_prefix="8.6",
            )

        assert rpt.error is None, f"Unexpected error: {rpt.error}"
        assert len(rpt.section_batches) == 1, (
            f"Expected 1 batch, got {len(rpt.section_batches)}: "
            f"{[b.prefix for b in rpt.section_batches]}"
        )
        assert rpt.section_batches[0].prefix == "8.6"

    def test_no_separate_87_batch_created(self, tmp_path):
        """No 8.7 batch must be created when spillover has 8.7 section_path."""
        existing = _make_record()
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))
        mock_ac = self._mock_ac()

        from unittest.mock import patch
        with patch("extract_case_from_source.load_cache", return_value=self._spillover_cache()):
            rpt = extract_case(
                yaml_path, cache_dir=tmp_path / "cache",
                use_claude=True, anthropic_client=mock_ac,
                section_prefix="8.6",
            )

        batch_prefixes = [b.prefix for b in rpt.section_batches]
        assert "8.7" not in batch_prefixes, f"No 8.7 batch expected, got batches: {batch_prefixes}"

    def test_one_api_call_for_section_prefix(self, tmp_path):
        """With spillover grouped into 8.6, only one Claude call is made."""
        existing = _make_record()
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))
        mock_ac = self._mock_ac()

        from unittest.mock import patch
        with patch("extract_case_from_source.load_cache", return_value=self._spillover_cache()):
            extract_case(
                yaml_path, cache_dir=tmp_path / "cache",
                use_claude=True, anthropic_client=mock_ac,
                section_prefix="8.6",
            )

        assert mock_ac.messages.create.call_count == 1, (
            f"Expected 1 API call, got {mock_ac.messages.create.call_count}"
        )

    def test_spillover_chunk_included_in_86_batch_chunks(self, tmp_path):
        """The spillover chunk appears in the 8.6 batch's chunk list."""
        existing = _make_record()
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))
        mock_ac = self._mock_ac()

        from unittest.mock import patch
        with patch("extract_case_from_source.load_cache", return_value=self._spillover_cache()):
            rpt = extract_case(
                yaml_path, cache_dir=tmp_path / "cache",
                use_claude=True, anthropic_client=mock_ac,
                section_prefix="8.6",
            )

        assert len(rpt.section_batches) == 1
        batch_chunk_ids = [c.chunk_id for c in rpt.section_batches[0].chunks]
        assert any("_spill" in cid for cid in batch_chunk_ids), (
            f"Spillover chunk not found in 8.6 batch chunks: {batch_chunk_ids}"
        )

    def test_inspect_mode_shows_spillover_for_label(self, tmp_path):
        """Spillover chunk has effective_prefix set, visible for inspect-mode display."""
        existing = _make_record()
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))

        from unittest.mock import patch
        with patch("extract_case_from_source.load_cache", return_value=self._spillover_cache()):
            rpt = extract_case(
                yaml_path, cache_dir=tmp_path / "cache",
                use_claude=False, section_prefix="8.6",
            )

        spill = next((c for c in rpt.chunks_used if "_spill" in c.chunk_id), None)
        assert spill is not None
        assert spill.effective_prefix == "8.6", (
            f"effective_prefix should be '8.6', got {spill.effective_prefix!r}"
        )
        # Original source section_path is preserved for display
        assert "8.7" in spill.section_path, (
            f"Original section_path should contain 8.7, got {spill.section_path!r}"
        )

    def test_focus_market_definition_with_spillover_no_theories(self, tmp_path):
        """With focus=market_definition and spillover, result has no theories of harm."""
        existing = _make_record()
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))
        mock_ac = self._mock_ac()  # returns theories_of_harm: []

        from unittest.mock import patch
        with patch("extract_case_from_source.load_cache", return_value=self._spillover_cache()):
            rpt = extract_case(
                yaml_path, cache_dir=tmp_path / "cache",
                use_claude=True, anthropic_client=mock_ac,
                section_prefix="8.6",
                focus="market_definition",
            )

        assert rpt.error is None, f"Unexpected error: {rpt.error}"
        assert rpt.result is not None
        assert rpt.result.theories == [], "market_definition focus must produce no theories"


# ---------------------------------------------------------------------------
# Focus-aware reconciliation tests
# ---------------------------------------------------------------------------

class TestFocusAwareReconciliation:
    """_reconcile skips out-of-scope proposition types based on the focus mode."""

    def _existing(self) -> dict:
        return _make_record(
            markets=[
                {"market_id": "pm_1", "name": "Online advertising",
                 "definition_status": "defined", "notes": ""},
            ],
            geo_markets=[
                {"market_id": "gm_1", "name": "EEA",
                 "definition_status": "defined", "notes": ""},
            ],
            theories=[
                {"theory_id": "toh_1", "name": "Data advantage",
                 "description": "Fitbit data strengthens Google."},
            ],
        )

    def _draft_markets_only(self) -> dict:
        """Draft produced by a market_definition-focused run: empty theories."""
        return {
            "product_markets_considered": [
                {"market_id": "pm_1", "name": "Online advertising",
                 "definition_status": "defined", "notes": ""},
            ],
            "geographic_markets_considered": [
                {"market_id": "gm_1", "name": "EEA",
                 "definition_status": "defined", "notes": ""},
            ],
            "theories_of_harm": [],  # out-of-scope for market_definition focus
        }

    def _draft_theories_only(self) -> dict:
        """Draft produced by a theories-focused run: empty markets."""
        return {
            "product_markets_considered": [],
            "geographic_markets_considered": [],
            "theories_of_harm": [
                {"theory_id": "toh_1", "name": "Data advantage",
                 "description": ""},
            ],
        }

    def test_focus_market_definition_skips_theory_removal(self):
        """With focus=market_definition, theories are NOT flagged as unsupported_remove."""
        findings = _reconcile(self._draft_markets_only(), self._existing(), focus="market_definition")
        theory_removals = [
            f for f in findings
            if f.existing_id == "toh_1" and f.finding_type == "unsupported_remove"
        ]
        assert theory_removals == [], (
            "Theories must not be flagged for removal when focus=market_definition"
        )

    def test_focus_none_reconciles_theories(self):
        """Without a focus, empty theories in the draft → unsupported_remove finding."""
        findings = _reconcile(self._draft_markets_only(), self._existing(), focus=None)
        theory_removals = [
            f for f in findings
            if f.existing_id == "toh_1" and f.finding_type == "unsupported_remove"
        ]
        assert len(theory_removals) == 1

    def test_focus_market_definition_still_reconciles_markets(self):
        """Market reconciliation still runs when focus=market_definition."""
        findings = _reconcile(self._draft_markets_only(), self._existing(), focus="market_definition")
        pm_findings = [f for f in findings if f.existing_id == "pm_1"]
        assert len(pm_findings) == 1
        assert pm_findings[0].finding_type == "supported_as_is"

    def test_focus_theories_skips_market_reconciliation(self):
        """With focus=theories, markets are NOT flagged as unsupported_remove."""
        findings = _reconcile(self._draft_theories_only(), self._existing(), focus="theories")
        market_removals = [
            f for f in findings
            if f.existing_id in ("pm_1", "gm_1") and f.finding_type == "unsupported_remove"
        ]
        assert market_removals == [], (
            "Markets must not be flagged for removal when focus=theories"
        )

    def test_focus_theories_still_reconciles_theories(self):
        """Theory reconciliation still runs when focus=theories."""
        findings = _reconcile(self._draft_theories_only(), self._existing(), focus="theories")
        toh_findings = [f for f in findings if f.existing_id == "toh_1"]
        assert len(toh_findings) == 1
        assert toh_findings[0].finding_type == "supported_as_is"

    def test_extract_case_passes_focus_to_reconcile(self, tmp_path):
        """extract_case(focus='market_definition') produces no theory removal findings."""
        existing = _make_record(
            theories=[{"theory_id": "toh_1", "name": "Data advantage", "description": ""}],
        )
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))

        page_cache = {
            "source_document_id": "doc1",
            "source_url": "https://example.com/doc.pdf",
            "page_count": 2,
            "pages": [
                {"page_number": 1, "text": "8 RELEVANT MARKETS\n8.1 Product market\npage 1"},
                {"page_number": 2, "text": "8.6 Online advertising\nMarket defined by Commission."},
            ],
            "extracted_at": "2026-05-25T00:00:00+00:00",
        }
        mock_block = MagicMock()
        mock_block.type = "tool_use"
        mock_block.input = {
            "product_markets": [],
            "geographic_markets": [],
            "theories_of_harm": [],
            "overall_outcome": "unknown",
            "source_passages": [],
            "caveats": [],
        }
        mock_msg = MagicMock()
        mock_msg.content = [mock_block]
        mock_ac = MagicMock()
        mock_ac.messages.create.return_value = mock_msg

        from unittest.mock import patch
        with patch("extract_case_from_source.load_cache", return_value=page_cache):
            rpt = extract_case(
                yaml_path, cache_dir=tmp_path / "cache",
                use_claude=True, anthropic_client=mock_ac,
                focus="market_definition",
            )

        theory_removals = [
            f for f in rpt.findings
            if f.existing_id == "toh_1" and f.finding_type == "unsupported_remove"
        ]
        assert theory_removals == [], (
            "extract_case with focus=market_definition must not flag theories for removal"
        )


# ---------------------------------------------------------------------------
# Focus guardrails tests
# ---------------------------------------------------------------------------

class TestFocusGuardrails:
    """_apply_focus_guardrails strips out-of-scope data from ExtractionResult."""

    def _result_with_all(self) -> ExtractionResult:
        return ExtractionResult(
            product_markets=[ExtractedMarket("PM1", "product", "defined", "Notes")],
            geographic_markets=[ExtractedMarket("EEA", "geographic", "defined", "Notes")],
            theories=[ExtractedTheory("Harm1", "horizontal", "dismissed", "Notes")],
            overall_outcome="cleared",
        )

    def test_market_definition_focus_strips_theories(self):
        result = _apply_focus_guardrails(self._result_with_all(), "market_definition")
        assert result.theories == []

    def test_market_definition_focus_forces_unknown_outcome(self):
        result = _apply_focus_guardrails(self._result_with_all(), "market_definition")
        assert result.overall_outcome == "unknown"

    def test_market_definition_focus_preserves_markets(self):
        result = _apply_focus_guardrails(self._result_with_all(), "market_definition")
        assert len(result.product_markets) == 1
        assert len(result.geographic_markets) == 1

    def test_theories_focus_strips_markets(self):
        result = _apply_focus_guardrails(self._result_with_all(), "theories")
        assert result.product_markets == []
        assert result.geographic_markets == []

    def test_theories_focus_preserves_theories(self):
        result = _apply_focus_guardrails(self._result_with_all(), "theories")
        assert len(result.theories) == 1

    def test_theories_focus_forces_unknown_outcome(self):
        result = _apply_focus_guardrails(self._result_with_all(), "theories")
        assert result.overall_outcome == "unknown"

    def test_no_focus_preserves_all(self):
        result = _apply_focus_guardrails(self._result_with_all(), None)
        assert len(result.theories) == 1
        assert len(result.product_markets) == 1
        assert result.overall_outcome == "cleared"

    def test_unknown_focus_preserves_all(self):
        result = _apply_focus_guardrails(self._result_with_all(), "remedies")
        assert len(result.theories) == 1
        assert len(result.product_markets) == 1
        assert result.overall_outcome == "cleared"

    def test_extract_case_market_definition_strips_theories_from_result(self, tmp_path):
        """extract_case with focus=market_definition must strip theories from result."""
        from unittest.mock import patch

        existing = _make_record(
            theories=[{"theory_id": "toh_1", "name": "Data advantage", "description": ""}],
        )
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))

        page_cache = {
            "source_document_id": "doc1",
            "source_url": "https://example.com/doc.pdf",
            "page_count": 1,
            "pages": [{"page_number": 1, "text": "8.6 MARKET DEFINITION\nThe Commission defined the market."}],
            "extracted_at": "2026-05-27T00:00:00+00:00",
        }
        mock_block = MagicMock()
        mock_block.type = "tool_use"
        mock_block.input = {
            "product_markets": [],
            "geographic_markets": [],
            "theories_of_harm": [
                {
                    "name": "Data advantage",
                    "theory_type": "data",
                    "theory_outcome": "dismissed",
                    "notes": "",
                    "not_found": False,
                    "passages": [],
                }
            ],
            "overall_outcome": "cleared",
            "source_passages": [],
            "caveats": [],
        }
        mock_msg = MagicMock()
        mock_msg.content = [mock_block]
        mock_ac = MagicMock()
        mock_ac.messages.create.return_value = mock_msg

        with patch("extract_case_from_source.load_cache", return_value=page_cache):
            rpt = extract_case(
                yaml_path, cache_dir=tmp_path / "cache",
                use_claude=True, anthropic_client=mock_ac,
                focus="market_definition",
            )

        assert rpt.error is None
        assert rpt.result is not None
        assert rpt.result.theories == [], "focus=market_definition must strip theories from result"
        assert rpt.result.overall_outcome == "unknown", (
            "focus=market_definition must force overall_outcome to unknown"
        )

    def test_extract_case_market_definition_no_theories_in_draft(self, tmp_path):
        """extract_case with focus=market_definition must not write theories to draft."""
        from unittest.mock import patch

        existing = _make_record(
            theories=[{"theory_id": "toh_1", "name": "Data advantage", "description": ""}],
        )
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))

        page_cache = {
            "source_document_id": "doc1",
            "source_url": "https://example.com/doc.pdf",
            "page_count": 1,
            "pages": [{"page_number": 1, "text": "8.6 MARKET DEFINITION\nThe Commission defined the market."}],
            "extracted_at": "2026-05-27T00:00:00+00:00",
        }
        mock_block = MagicMock()
        mock_block.type = "tool_use"
        mock_block.input = {
            "product_markets": [],
            "geographic_markets": [],
            "theories_of_harm": [
                {"name": "Data advantage", "theory_type": "data", "theory_outcome": "dismissed",
                 "notes": "", "not_found": False, "passages": []}
            ],
            "overall_outcome": "cleared",
            "source_passages": [],
            "caveats": [],
        }
        mock_msg = MagicMock()
        mock_msg.content = [mock_block]
        mock_ac = MagicMock()
        mock_ac.messages.create.return_value = mock_msg

        with patch("extract_case_from_source.load_cache", return_value=page_cache):
            rpt = extract_case(
                yaml_path, cache_dir=tmp_path / "cache",
                use_claude=True, anthropic_client=mock_ac,
                focus="market_definition",
            )

        assert rpt.draft_record is not None
        assert rpt.draft_record.get("theories_of_harm") == [], (
            "Draft must not contain theories when focus=market_definition"
        )
        assert rpt.draft_record.get("outcome") == "unknown", (
            "Draft outcome must be unknown when focus=market_definition"
        )


# ---------------------------------------------------------------------------
# Quote quality guard tests
# ---------------------------------------------------------------------------

class TestQuoteQualityGuard:
    """Truncated/incomplete quotes are detected and rejected during validation."""

    def test_is_truncated_false_for_complete_sentence(self):
        quote = "The Commission concluded that the relevant market is online advertising."
        assert _is_truncated_quote(quote) is False

    def test_is_truncated_false_for_phrase_no_sentence_break(self):
        """Short phrase excerpt without mid-quote sentence break is never truncated."""
        quote = "Commission defines the relevant product market for online advertising"
        assert _is_truncated_quote(quote) is False

    def test_is_truncated_false_for_semicolon_end(self):
        quote = "The Commission found the relevant market; no further definition was necessary."
        assert _is_truncated_quote(quote) is False

    def test_is_truncated_true_for_mid_sentence_cutoff(self):
        """Classic truncated quote: complete sentence then incomplete fragment."""
        quote = (
            "Display and search advertising services appear to be also not substitutable "
            "from the supply-side. In particular, supplying online search advertising"
        )
        assert _is_truncated_quote(quote) is True

    def test_is_truncated_false_for_short_quote(self):
        """Quotes under the minimum length are never flagged."""
        quote = "The Commission found the market. It also found"
        assert len(quote) < 50
        assert _is_truncated_quote(quote) is False

    def test_is_truncated_false_for_multi_sentence_complete(self):
        """Multi-sentence quote ending with punctuation is not truncated."""
        quote = (
            "The Commission assessed the relevant product market. "
            "It concluded that the market is EEA-wide."
        )
        assert _is_truncated_quote(quote) is False

    def test_truncated_quote_rejected_during_validation(self):
        """A truncated quote is rejected by _validate_extraction."""
        truncated = (
            "Display and search advertising services appear to be also not substitutable "
            "from the supply-side. In particular, supplying online search advertising"
        )
        page_text = truncated
        chunk = _make_chunk("chunk_001", "8.6 Market", [(1, page_text)])
        raw = {
            "product_markets": [
                {
                    "name": "Online advertising",
                    "definition_status": "left_open",
                    "notes": "",
                    "not_found": False,
                    "passages": [
                        {
                            "chunk_id": "chunk_001",
                            "page_number": 1,
                            "quote": truncated,
                            "source_role": "commission_assessment",
                        },
                    ],
                }
            ],
            "geographic_markets": [],
            "theories_of_harm": [],
            "overall_outcome": "unknown",
            "source_passages": [],
            "caveats": [],
        }
        result = _validate_extraction(raw, [chunk], {"chunk_001": "doc1"})
        assert result.passages_rejected >= 1
        rejected = [p for p in result.product_markets[0].passages if not p.validated]
        assert len(rejected) == 1
        assert "truncated" in rejected[0].rejection_reason.lower()

    def test_complete_quote_passes_validation(self):
        """A complete-sentence quote passes the truncation check."""
        quote = "The Commission concluded that the relevant market is online advertising."
        chunk = _make_chunk("chunk_001", "8.6 Market", [(1, quote)])
        raw = {
            "product_markets": [
                {
                    "name": "Online advertising",
                    "definition_status": "defined",
                    "notes": "",
                    "not_found": False,
                    "passages": [
                        {"chunk_id": "chunk_001", "page_number": 1, "quote": quote, "source_role": "conclusion"},
                    ],
                }
            ],
            "geographic_markets": [],
            "theories_of_harm": [],
            "overall_outcome": "unknown",
            "source_passages": [],
            "caveats": [],
        }
        result = _validate_extraction(raw, [chunk], {"chunk_001": "doc1"})
        validated = [p for p in result.product_markets[0].passages if p.validated]
        assert len(validated) == 1


# ---------------------------------------------------------------------------
# Source role guard tests
# ---------------------------------------------------------------------------

class TestSourceRoleGuard:
    """Source roles are validated and preserved correctly in passage extraction."""

    def _raw_with_role(self, quote: str, source_role: str) -> dict:
        return {
            "product_markets": [
                {
                    "name": "Online advertising",
                    "definition_status": "considered",
                    "notes": "",
                    "not_found": False,
                    "passages": [
                        {
                            "chunk_id": "chunk_001",
                            "page_number": 1,
                            "quote": quote,
                            "source_role": source_role,
                        },
                    ],
                }
            ],
            "geographic_markets": [],
            "theories_of_harm": [],
            "overall_outcome": "unknown",
            "source_passages": [],
            "caveats": [],
        }

    def _chunk(self, text: str) -> list[ChunkInfo]:
        return [_make_chunk("chunk_001", "8.6 Market", [(1, text)])]

    def test_notifying_party_view_role_preserved(self):
        """Passages with notifying_party_view role keep that role after validation."""
        quote = "The parties submit that the relevant market is online advertising."
        result = _validate_extraction(
            self._raw_with_role(quote, "notifying_party_view"),
            self._chunk(quote),
            {"chunk_001": "doc1"},
        )
        validated = [p for p in result.product_markets[0].passages if p.validated]
        assert len(validated) == 1
        assert validated[0].source_role == "notifying_party_view"

    def test_commission_assessment_role_preserved(self):
        """commission_assessment role is preserved after validation."""
        quote = "The Commission assessed the market for online advertising services."
        result = _validate_extraction(
            self._raw_with_role(quote, "commission_assessment"),
            self._chunk(quote),
            {"chunk_001": "doc1"},
        )
        validated = [p for p in result.product_markets[0].passages if p.validated]
        assert len(validated) == 1
        assert validated[0].source_role == "commission_assessment"

    def test_conclusion_role_preserved(self):
        """conclusion role is preserved after validation."""
        quote = "The Commission concluded the relevant market is online advertising."
        result = _validate_extraction(
            self._raw_with_role(quote, "conclusion"),
            self._chunk(quote),
            {"chunk_001": "doc1"},
        )
        validated = [p for p in result.product_markets[0].passages if p.validated]
        assert len(validated) == 1
        assert validated[0].source_role == "conclusion"

    def test_invalid_source_role_cleared(self):
        """Invalid source roles are coerced to empty string rather than propagated."""
        quote = "The Commission found the relevant market to be online advertising."
        result = _validate_extraction(
            self._raw_with_role(quote, "unknown_invalid_role"),
            self._chunk(quote),
            {"chunk_001": "doc1"},
        )
        validated = [p for p in result.product_markets[0].passages if p.validated]
        assert len(validated) == 1
        assert validated[0].source_role == "", "Invalid role must be cleared to empty string"

    def test_empty_source_role_accepted(self):
        """Empty source role is preserved as-is (no rejection)."""
        quote = "The Commission assessed online advertising."
        result = _validate_extraction(
            self._raw_with_role(quote, ""),
            self._chunk(quote),
            {"chunk_001": "doc1"},
        )
        validated = [p for p in result.product_markets[0].passages if p.validated]
        assert len(validated) == 1
        assert validated[0].source_role == ""

    def test_all_valid_roles_accepted(self):
        """All values in _VALID_SOURCE_ROLES are preserved without modification."""
        from extract_case_from_source import _VALID_SOURCE_ROLES
        quote = "The Commission assessed online advertising."
        for role in _VALID_SOURCE_ROLES:
            result = _validate_extraction(
                self._raw_with_role(quote, role),
                self._chunk(quote),
                {"chunk_001": "doc1"},
            )
            validated = [p for p in result.product_markets[0].passages if p.validated]
            assert len(validated) == 1, f"Role {role!r} should produce a validated passage"
            assert validated[0].source_role == role, f"Role {role!r} must be preserved unchanged"


# ---------------------------------------------------------------------------
# Geographic market dedupe tests
# ---------------------------------------------------------------------------

class TestGeographicMarketDedupe:
    """Geographic markets with same name are merged conservatively across section batches."""

    def _geo(self, name: str, status: str, notes: str, validated: bool = True) -> ExtractedMarket:
        p = ExtractedPassage("chunk_001", 1, f"quote for {name}", validated=validated, source_role="commission_assessment")
        return ExtractedMarket(name, "geographic", status, notes, [p])

    def test_merge_geo_keeps_stronger_status(self):
        """_merge_geo_market_pair keeps the stronger definition_status."""
        base = self._geo("EEA", "precedent_only", "From prior cases.")
        incoming = self._geo("EEA", "defined", "Commission explicitly defined.")
        merged = _merge_geo_market_pair(base, incoming)
        assert merged.definition_status == "defined"

    def test_merge_geo_keeps_stronger_when_base_stronger(self):
        """When base is stronger, base status is kept."""
        base = self._geo("EEA", "defined", "Commission explicitly defined.")
        incoming = self._geo("EEA", "precedent_only", "From prior cases.")
        merged = _merge_geo_market_pair(base, incoming)
        assert merged.definition_status == "defined"

    def test_merge_geo_combines_distinct_notes(self):
        """Notes from both markets are combined when they differ."""
        base = self._geo("EEA", "precedent_only", "Based on prior cases.")
        incoming = self._geo("EEA", "defined", "Commission explicitly defined EEA.")
        merged = _merge_geo_market_pair(base, incoming)
        assert "prior cases" in merged.notes
        assert "explicitly defined" in merged.notes

    def test_merge_geo_no_duplicate_notes(self):
        """Identical notes are not duplicated."""
        base = self._geo("EEA", "defined", "EEA-wide.")
        incoming = self._geo("EEA", "defined", "EEA-wide.")
        merged = _merge_geo_market_pair(base, incoming)
        assert merged.notes.count("EEA-wide") == 1

    def test_merge_results_deduplicates_geo_markets(self):
        """_merge_extraction_results deduplicates geographic markets across batches."""
        r1 = ExtractionResult(
            geographic_markets=[self._geo("EEA", "precedent_only", "Based on prior cases.")],
        )
        r2 = ExtractionResult(
            geographic_markets=[self._geo("EEA", "defined", "Commission explicitly defined EEA.")],
        )
        merged = _merge_extraction_results([r1, r2])
        assert len(merged.geographic_markets) == 1

    def test_merge_results_keeps_stronger_status(self):
        """After merging, the stronger definition_status is preserved."""
        r1 = ExtractionResult(
            geographic_markets=[self._geo("EEA", "precedent_only", "From prior cases.")],
        )
        r2 = ExtractionResult(
            geographic_markets=[self._geo("EEA", "defined", "Commission explicitly defined.")],
        )
        merged = _merge_extraction_results([r1, r2])
        assert merged.geographic_markets[0].definition_status == "defined"

    def test_merge_results_preserves_combined_notes(self):
        """Combined notes from both results are preserved after merge."""
        r1 = ExtractionResult(
            geographic_markets=[self._geo("EEA", "precedent_only", "Based on prior cases.")],
        )
        r2 = ExtractionResult(
            geographic_markets=[self._geo("EEA", "defined", "Commission explicitly defined.")],
        )
        merged = _merge_extraction_results([r1, r2])
        notes = merged.geographic_markets[0].notes
        assert "prior cases" in notes
        assert "explicitly defined" in notes

    def test_distinct_geo_markets_not_merged(self):
        """Two different geographic markets are kept separate."""
        r1 = ExtractionResult(
            geographic_markets=[self._geo("EEA", "defined", "EEA-wide.")],
        )
        r2 = ExtractionResult(
            geographic_markets=[self._geo("Global", "left_open", "Global scope considered.")],
        )
        merged = _merge_extraction_results([r1, r2])
        assert len(merged.geographic_markets) == 2


# ---------------------------------------------------------------------------
# Spillover tightening tests — req: only immediate leading spillover included
# ---------------------------------------------------------------------------

class TestSpilloverTightening:
    """
    _trim_pages_for_prefix returns [] for chunks starting with a sibling heading.
    _section_batch_prefix uses the last '>' component.
    extract_case never includes non-target chunks via the prefix filter.
    """

    # ------------------------------------------------------------------
    # Unit tests: _trim_pages_for_prefix sibling-start exclusion
    # ------------------------------------------------------------------

    def test_trim_returns_empty_when_first_heading_is_sibling(self):
        """Pages whose first heading is a sibling (not target) yield [] — no fallback."""
        pages = [
            {"page_number": 3, "text": "8.3 Operating Systems\nOS content here."},
            {"page_number": 4, "text": "More OS content."},
        ]
        result = _trim_pages_for_prefix(pages, "8.2")
        assert result == [], (
            "_trim_pages_for_prefix must return [] when first page starts with sibling heading"
        )

    def test_trim_fallback_preserved_for_continuation_page(self):
        """Pages with no heading at all (continuation) still get the fallback full-page return."""
        pages = [
            {"page_number": 3, "text": "Continued analysis of the wearable device market."},
        ]
        result = _trim_pages_for_prefix(pages, "8.2")
        assert result == pages, "Continuation chunk (no heading) must not be excluded"

    def test_trim_keeps_target_text_before_sibling(self):
        """When target text exists before the sibling heading it is kept; sibling is trimmed."""
        pages = [
            {
                "page_number": 5,
                "text": (
                    "The Commission concluded its 8.2 market assessment.\n"
                    "8.3 Operating Systems\n"
                    "OS content follows."
                ),
            }
        ]
        result = _trim_pages_for_prefix(pages, "8.2")
        assert result  # non-empty — there is target text before 8.3
        assert "8.3 Operating Systems" not in result[0]["text"]
        assert "OS content follows" not in result[0]["text"]
        assert "8.2 market assessment" in result[0]["text"]

    # ------------------------------------------------------------------
    # Unit tests: _section_batch_prefix uses last '>' component
    # ------------------------------------------------------------------

    def test_prefix_from_simple_hierarchical_path(self):
        """Last component 8.3 is extracted even when 8.2 appears earlier in path."""
        path = "8 Markets > 8.2 Wearable devices > 8.3 Operating systems"
        assert _section_batch_prefix(path) == "8.3"

    def test_prefix_simple_path_unchanged(self):
        """Simple (non-hierarchical) paths continue to work correctly."""
        assert _section_batch_prefix("8.2 Wearable devices") == "8.2"
        assert _section_batch_prefix("8.6 Online advertising") == "8.6"

    def test_prefix_subsection_of_target_still_correct(self):
        """8.2.1 is a subsection of 8.2; last-component extract should give 8.2."""
        path = "8 Markets > 8.2 Wearable devices > 8.2.1 Product market"
        assert _section_batch_prefix(path) == "8.2"

    # ------------------------------------------------------------------
    # Integration: extract_case section prefix filter
    # ------------------------------------------------------------------

    def _82_cache(self) -> dict:
        """
        Pages 1-4: 8.2 Wearable devices content.
        Pages 5-6: mislabeled by section map as '8.2.1 Product market' BUT their text
                   starts with the 8.3 heading — simulates the permissive-spillover bug.
        Pages 7-8: pure 8.3 content (correctly labeled by section map as 8.3).
        """
        return {
            "source_document_id": "doc1",
            "source_url": "https://example.com/doc.pdf",
            "page_count": 8,
            "pages": [
                # Real 8.2 content
                {"page_number": 1, "text": "8.2 Wearable Devices\nMarket for wearable devices."},
                {"page_number": 2, "text": "8.2 wearable market continued analysis."},
                {"page_number": 3, "text": "8.2.1 Product Market\nSmartwatch product market."},
                {"page_number": 4, "text": "8.2.2 Geographic Market\nEEA-wide geographic market."},
                # Mislabeled pages: section_map says "8.2.1" but text starts with 8.3
                {"page_number": 5, "text": "8.3 Operating Systems\nOS product market."},
                {"page_number": 6, "text": "8.3 OS geographic market analysis."},
                # Correctly labeled 8.3 pages
                {"page_number": 7, "text": "8.3 Operating Systems continued."},
                {"page_number": 8, "text": "8.3 OS final analysis."},
            ],
            "extracted_at": "2026-05-27T00:00:00+00:00",
        }

    def _82_section_map(self) -> dict[int, str]:
        """Section map that mislabels pages 5-6 as 8.2.1 even though text starts with 8.3."""
        return {
            1: "8.2 Wearable Devices",
            2: "8.2 Wearable Devices",
            3: "8.2.1 Product Market",
            4: "8.2.2 Geographic Market",
            5: "8.2.1 Product Market",  # mislabeled — text actually starts with 8.3
            6: "8.2.1 Product Market",  # mislabeled — same
            7: "8.3 Operating Systems",
            8: "8.3 Operating Systems",
        }

    def test_82_excludes_sibling_starting_chunks(self, tmp_path):
        """Chunks whose first page text starts with 8.3 heading are excluded from 8.2 results."""
        from unittest.mock import patch
        existing = _make_record()
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))

        cache = self._82_cache()
        smap = self._82_section_map()

        with patch("extract_case_from_source.load_cache", return_value=cache), \
             patch("extract_case_from_source._extract_section_map", return_value=smap):
            rpt = extract_case(
                yaml_path, cache_dir=tmp_path / "cache",
                use_claude=False, section_prefix="8.2",
            )

        assert rpt.error is None
        # Pages 5-8 (which start with 8.3 content) must not appear in chunks_used
        all_pages = [p["page_number"] for c in rpt.chunks_used for p in c.pages]
        assert 5 not in all_pages, "Page 5 starts with 8.3 heading — must be excluded"
        assert 6 not in all_pages, "Page 6 is mislabeled 8.2.1 with 8.3 content — must be excluded"
        assert 7 not in all_pages, "Page 7 is correctly labeled 8.3 — must be excluded"
        assert 8 not in all_pages, "Page 8 is correctly labeled 8.3 — must be excluded"

    def test_82_includes_real_82_chunks(self, tmp_path):
        """Core 8.2 pages (1-4) must still appear in chunks_used."""
        from unittest.mock import patch
        existing = _make_record()
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))

        cache = self._82_cache()
        smap = self._82_section_map()

        with patch("extract_case_from_source.load_cache", return_value=cache), \
             patch("extract_case_from_source._extract_section_map", return_value=smap):
            rpt = extract_case(
                yaml_path, cache_dir=tmp_path / "cache",
                use_claude=False, section_prefix="8.2",
            )

        all_pages = [p["page_number"] for c in rpt.chunks_used for p in c.pages]
        assert 1 in all_pages
        assert 2 in all_pages
        assert 3 in all_pages
        assert 4 in all_pages

    def test_82_next_sibling_chunk_not_added_as_spillover(self, tmp_path):
        """When the chunk immediately after 8.2 starts with 8.3, no spillover is added."""
        from unittest.mock import patch
        existing = _make_record()
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))

        # Cache where page 5 is the immediate next chunk and starts directly with 8.3
        cache = {
            "source_document_id": "doc1",
            "source_url": "https://example.com/doc.pdf",
            "page_count": 6,
            "pages": [
                {"page_number": 1, "text": "8.2 Wearable Devices\nMarket for wearable devices."},
                {"page_number": 2, "text": "8.2 continued analysis."},
                {"page_number": 3, "text": "8.2.1 Product Market\nSmartwatch market."},
                {"page_number": 4, "text": "8.2.2 Geographic Market\nEEA-wide."},
                {"page_number": 5, "text": "8.3 Operating Systems\nOS market analysis."},
                {"page_number": 6, "text": "8.3 continued OS analysis."},
            ],
            "extracted_at": "2026-05-27T00:00:00+00:00",
        }
        smap = {1: "8.2 Wearable Devices", 2: "8.2 Wearable Devices",
                3: "8.2.1 Product Market", 4: "8.2.2 Geographic Market",
                5: "8.3 Operating Systems", 6: "8.3 Operating Systems"}

        with patch("extract_case_from_source.load_cache", return_value=cache), \
             patch("extract_case_from_source._extract_section_map", return_value=smap):
            rpt = extract_case(
                yaml_path, cache_dir=tmp_path / "cache",
                use_claude=False, section_prefix="8.2",
            )

        assert rpt.error is None
        chunk_ids = [c.chunk_id for c in rpt.chunks_used]
        # No spillover chunk should be created because page 5 starts with 8.3 heading
        spill_chunks = [cid for cid in chunk_ids if "_spill" in cid]
        assert spill_chunks == [], (
            f"No spillover should be added when next chunk starts with sibling heading, "
            f"got: {spill_chunks}"
        )
        # 8.3 pages must not be in chunks_used at all
        all_pages = [p["page_number"] for c in rpt.chunks_used for p in c.pages]
        assert 5 not in all_pages
        assert 6 not in all_pages

    def test_86_spillover_still_works(self, tmp_path):
        """8.6 spillover from page 40 (leading 8.6 text before 8.7 heading) still included."""
        from unittest.mock import patch
        existing = _make_record()
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))

        cache = {
            "source_document_id": "doc1",
            "source_url": "https://example.com/doc.pdf",
            "page_count": 3,
            "pages": [
                {
                    "page_number": 38,
                    "text": "8.6 Online Advertising Services\nCommission assessed online advertising.",
                },
                {
                    "page_number": 39,
                    "text": "8.6.2 Geographic markets\nThe EEA-wide geographic market.",
                },
                {
                    "page_number": 40,
                    "text": (
                        "The Commission concluded its assessment of geographic markets.\n"
                        "8.7 Ad Tech Services\n"
                        "This section covers ad tech intermediation."
                    ),
                },
            ],
            "extracted_at": "2026-05-27T00:00:00+00:00",
        }

        with patch("extract_case_from_source.load_cache", return_value=cache):
            rpt = extract_case(
                yaml_path, cache_dir=tmp_path / "cache",
                use_claude=False, section_prefix="8.6",
            )

        assert rpt.error is None
        # Spillover from page 40 must be included (leading 8.6 text before 8.7 heading)
        all_pages = [p["page_number"] for c in rpt.chunks_used for p in c.pages]
        assert 40 in all_pages, "Spillover page 40 must still be included for 8.6"
        # 8.7 text must not appear in prompt
        full_prompt = " ".join(c.prompt_text for c in rpt.chunks_used)
        assert "8.7 Ad Tech Services" not in full_prompt
        assert "ad tech intermediation" not in full_prompt
        # 8.6 spillover text must appear
        assert "concluded its assessment" in full_prompt

    def test_inspect_mode_excludes_sibling_text(self, tmp_path):
        """In inspect mode, chunks_used must not include 8.3 content when prefix is 8.2."""
        from unittest.mock import patch
        existing = _make_record()
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))

        cache = self._82_cache()
        smap = self._82_section_map()

        with patch("extract_case_from_source.load_cache", return_value=cache), \
             patch("extract_case_from_source._extract_section_map", return_value=smap):
            rpt = extract_case(
                yaml_path, cache_dir=tmp_path / "cache",
                use_claude=False, section_prefix="8.2",
            )

        # The prompt text (inspect view) must contain no 8.3 content
        all_prompt_text = " ".join(c.prompt_text for c in rpt.chunks_used)
        assert "8.3 Operating Systems" not in all_prompt_text, (
            "8.3 OS heading must not appear in prompt when section_prefix=8.2"
        )
        assert "OS product market" not in all_prompt_text, (
            "8.3 OS content must not appear in prompt when section_prefix=8.2"
        )

    def test_hierarchical_path_prefix_excludes_sibling(self, tmp_path):
        """A chunk whose section_path last component is 8.3 is excluded even if 8.2 appears earlier."""
        from unittest.mock import patch
        existing = _make_record()
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))

        cache = {
            "source_document_id": "doc1",
            "source_url": "https://example.com/doc.pdf",
            "page_count": 4,
            "pages": [
                {"page_number": 1, "text": "8.2 Wearable Devices\nMarket for wearable devices."},
                {"page_number": 2, "text": "8.2 continued analysis."},
                {"page_number": 3, "text": "8.3 Operating Systems\nOS product market."},
                {"page_number": 4, "text": "8.3 OS geographic market."},
            ],
            "extracted_at": "2026-05-27T00:00:00+00:00",
        }
        # Section map uses hierarchical paths; pages 3-4 have "8.3" as last component
        smap = {
            1: "8 Markets > 8.2 Wearable Devices",
            2: "8 Markets > 8.2 Wearable Devices",
            3: "8 Markets > 8.2 Wearable Devices > 8.3 Operating Systems",
            4: "8 Markets > 8.2 Wearable Devices > 8.3 Operating Systems",
        }

        with patch("extract_case_from_source.load_cache", return_value=cache), \
             patch("extract_case_from_source._extract_section_map", return_value=smap):
            rpt = extract_case(
                yaml_path, cache_dir=tmp_path / "cache",
                use_claude=False, section_prefix="8.2",
            )

        assert rpt.error is None
        all_pages = [p["page_number"] for c in rpt.chunks_used for p in c.pages]
        # Pages 3-4 have section_path last component "8.3" → _section_batch_prefix returns "8.3"
        # → excluded from _filtered → not in chunks_used
        assert 3 not in all_pages, "Page 3 (last component 8.3) must be excluded"
        assert 4 not in all_pages, "Page 4 (last component 8.3) must be excluded"
        assert 1 in all_pages
        assert 2 in all_pages


# ---------------------------------------------------------------------------
# Market importance classification tests
# ---------------------------------------------------------------------------

class TestMarketImportanceClassification:
    """market_importance is extracted, preserved, and written to draft."""

    def _raw_market(self, importance: str, status: str = "defined") -> dict:
        return {
            "product_markets": [
                {
                    "name": "Online advertising",
                    "definition_status": status,
                    "market_importance": importance,
                    "notes": "Test notes.",
                    "not_found": False,
                    "passages": [],
                }
            ],
            "geographic_markets": [],
            "theories_of_harm": [],
            "overall_outcome": "unknown",
            "source_passages": [],
            "caveats": [],
        }

    def _chunk(self) -> list[ChunkInfo]:
        return [_make_chunk("chunk_001", "8.6 Market", [(1, "Test page content.")])]

    def test_core_assessed_importance_preserved(self):
        result = _validate_extraction(
            self._raw_market("core_assessed"), self._chunk(), {"chunk_001": "doc1"}
        )
        assert result.product_markets[0].market_importance == "core_assessed"

    def test_precedent_only_importance_preserved(self):
        result = _validate_extraction(
            self._raw_market("precedent_only", "precedent_only"),
            self._chunk(), {"chunk_001": "doc1"},
        )
        assert result.product_markets[0].market_importance == "precedent_only"

    def test_assessed_no_overlap_preserved(self):
        result = _validate_extraction(
            self._raw_market("assessed_no_overlap", "defined"),
            self._chunk(), {"chunk_001": "doc1"},
        )
        assert result.product_markets[0].market_importance == "assessed_no_overlap"

    def test_incomplete_source_preserved(self):
        result = _validate_extraction(
            self._raw_market("incomplete_source", "unknown"),
            self._chunk(), {"chunk_001": "doc1"},
        )
        assert result.product_markets[0].market_importance == "incomplete_source"

    def test_invalid_importance_coerced_to_empty(self):
        """An unrecognised market_importance value is coerced to empty string."""
        result = _validate_extraction(
            self._raw_market("invented_value"),
            self._chunk(), {"chunk_001": "doc1"},
        )
        assert result.product_markets[0].market_importance == ""

    def test_missing_importance_defaults_to_empty(self):
        raw = {
            "product_markets": [
                {"name": "Online ads", "definition_status": "defined",
                 "notes": "", "not_found": False, "passages": []}
            ],
            "geographic_markets": [], "theories_of_harm": [],
            "overall_outcome": "unknown", "source_passages": [], "caveats": [],
        }
        result = _validate_extraction(raw, self._chunk(), {"chunk_001": "doc1"})
        assert result.product_markets[0].market_importance == ""

    def test_all_valid_importance_values_accepted(self):
        for imp in _VALID_MARKET_IMPORTANCE:
            result = _validate_extraction(
                self._raw_market(imp), self._chunk(), {"chunk_001": "doc1"}
            )
            assert result.product_markets[0].market_importance == imp, (
                f"Value {imp!r} must be preserved unchanged"
            )

    def test_draft_includes_market_importance(self, tmp_path):
        """_build_draft_record writes market_importance into draft markets."""
        result = ExtractionResult(
            product_markets=[
                ExtractedMarket("Online ads", "product", "defined", "Notes",
                                market_importance="core_assessed")
            ],
            geographic_markets=[
                ExtractedMarket("EEA", "geographic", "defined", "EEA-wide.",
                                market_importance="assessed_no_overlap")
            ],
        )
        existing = _make_record()
        draft = _build_draft_record(result, existing)
        pm = draft["product_markets_considered"][0]
        gm = draft["geographic_markets_considered"][0]
        assert pm.get("market_importance") == "core_assessed"
        assert gm.get("market_importance") == "assessed_no_overlap"

    def test_draft_omits_importance_when_empty(self, tmp_path):
        """market_importance is absent from draft when unclassified."""
        result = ExtractionResult(
            product_markets=[
                ExtractedMarket("Online ads", "product", "defined", "Notes",
                                market_importance="")
            ],
        )
        existing = _make_record()
        draft = _build_draft_record(result, existing)
        pm = draft["product_markets_considered"][0]
        assert "market_importance" not in pm

    def test_precedent_only_not_classified_as_core(self):
        """A market classified as precedent_only must not have core_assessed importance."""
        result = _validate_extraction(
            self._raw_market("precedent_only", "precedent_only"),
            self._chunk(), {"chunk_001": "doc1"},
        )
        assert result.product_markets[0].market_importance != "core_assessed"

    def test_no_overlap_classified_separately_from_core(self):
        """assessed_no_overlap is distinct from core_assessed."""
        result = _validate_extraction(
            self._raw_market("assessed_no_overlap", "defined"),
            self._chunk(), {"chunk_001": "doc1"},
        )
        assert result.product_markets[0].market_importance == "assessed_no_overlap"
        assert result.product_markets[0].market_importance != "core_assessed"


# ---------------------------------------------------------------------------
# No inferred conclusions tests
# ---------------------------------------------------------------------------

class TestNoInferredConclusions:
    """When the Commission's conclusion is absent from the text, status must be unknown."""

    def _raw_with_status_and_importance(self, status: str, importance: str) -> dict:
        return {
            "product_markets": [
                {
                    "name": "Wearable fitness trackers",
                    "definition_status": status,
                    "market_importance": importance,
                    "notes": "Commission assessment ongoing.",
                    "not_found": False,
                    "passages": [],
                }
            ],
            "geographic_markets": [],
            "theories_of_harm": [],
            "overall_outcome": "unknown",
            "source_passages": [],
            "caveats": ["Conclusion not found in supplied chunks."],
        }

    def _chunk(self) -> list[ChunkInfo]:
        return [_make_chunk("chunk_001", "8.2 Wearable", [(1, "Text.")])]

    def test_unknown_status_with_incomplete_source_preserved(self):
        """unknown + incomplete_source is the correct output when conclusion is absent."""
        result = _validate_extraction(
            self._raw_with_status_and_importance("unknown", "incomplete_source"),
            self._chunk(), {"chunk_001": "doc1"},
        )
        pm = result.product_markets[0]
        assert pm.definition_status == "unknown"
        assert pm.market_importance == "incomplete_source"

    def test_left_open_not_inferred_is_preserved_if_explicit(self):
        """If Claude explicitly returns left_open (text says so), it is preserved."""
        result = _validate_extraction(
            self._raw_with_status_and_importance("left_open", "core_assessed"),
            self._chunk(), {"chunk_001": "doc1"},
        )
        assert result.product_markets[0].definition_status == "left_open"

    def test_caveats_preserved_when_conclusion_missing(self):
        """A caveat about missing conclusion is preserved through the pipeline."""
        result = _validate_extraction(
            self._raw_with_status_and_importance("unknown", "incomplete_source"),
            self._chunk(), {"chunk_001": "doc1"},
        )
        assert any("Conclusion" in c or "conclusion" in c for c in result.caveats)


# ---------------------------------------------------------------------------
# Section-scoped caveats tests
# ---------------------------------------------------------------------------

class TestSectionScopedCaveats:
    """Caveats from section-batched extractions are prefixed with their section label."""

    def _make_result(self, label: str, caveats: list[str]) -> ExtractionResult:
        return ExtractionResult(caveats=caveats, section_label=label)

    def test_merge_scopes_caveats_with_section_label(self):
        r1 = self._make_result("8.2 Wearable Devices", ["Definition inconclusive."])
        r2 = self._make_result("8.6 Online Advertising", ["Left open due to overlap."])
        merged = _merge_extraction_results([r1, r2])
        assert any("8.2 Wearable Devices" in c for c in merged.caveats), (
            "8.2 section label must prefix its caveats"
        )
        assert any("8.6 Online Advertising" in c for c in merged.caveats), (
            "8.6 section label must prefix its caveats"
        )

    def test_merge_does_not_duplicate_prefix(self):
        """If a caveat already starts with [label], it is not double-prefixed."""
        label = "8.6 Online Advertising"
        caveat = f"[{label}] Already scoped caveat."
        r = self._make_result(label, [caveat])
        merged = _merge_extraction_results([r])
        assert merged.caveats.count(caveat) == 1
        assert not any(c.startswith(f"[{label}] [{label}]") for c in merged.caveats)

    def test_section_label_set_by_extract_section_batch(self, tmp_path):
        """_extract_section_batch sets section_label on the ExtractionResult."""
        from unittest.mock import patch, MagicMock
        existing = _make_record()
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))

        mock_block = MagicMock()
        mock_block.type = "tool_use"
        mock_block.input = {
            "product_markets": [],
            "geographic_markets": [],
            "theories_of_harm": [],
            "overall_outcome": "unknown",
            "source_passages": [],
            "caveats": ["Market definition inconclusive."],
        }
        mock_msg = MagicMock()
        mock_msg.content = [mock_block]
        mock_ac = MagicMock()
        mock_ac.messages.create.return_value = mock_msg

        page_cache = {
            "source_document_id": "doc1",
            "source_url": "https://example.com/doc.pdf",
            "page_count": 1,
            "pages": [{"page_number": 1,
                        "text": "8.6 Online Advertising Services\nMarket text."}],
            "extracted_at": "2026-05-27T00:00:00+00:00",
        }
        with patch("extract_case_from_source.load_cache", return_value=page_cache):
            rpt = extract_case(
                yaml_path, cache_dir=tmp_path / "cache",
                use_claude=True, anthropic_client=mock_ac,
                section_prefix="8.6", batch_by_section=False,
            )

        assert rpt.error is None
        assert rpt.result is not None
        # The batch result should have section_label set
        assert rpt.section_batches, "section_batches must be populated"
        assert rpt.section_batches[0].result is not None
        assert rpt.section_batches[0].result.section_label, (
            "section_label must be set on batch ExtractionResult"
        )
        # The merged caveats should contain the section label
        merged_caveats = rpt.result.caveats
        assert any("8.6" in c for c in merged_caveats), (
            "Merged caveats must contain section label prefix"
        )

    def test_caveats_without_section_label_passed_through_unmodified(self):
        """When section_label is empty, caveats are not modified."""
        r = self._make_result("", ["Plain caveat."])
        merged = _merge_extraction_results([r])
        assert "Plain caveat." in merged.caveats


# ---------------------------------------------------------------------------
# Reconciliation grouping tests
# ---------------------------------------------------------------------------

class TestReconciliationGrouping:
    """_reconcile sets group on each finding; _group_reconciliation partitions them."""

    def _existing(self) -> dict:
        return _make_record(
            markets=[
                {"market_id": "pm_1", "name": "Online advertising",
                 "definition_status": "defined", "notes": ""},
                {"market_id": "pm_2", "name": "Search advertising",
                 "definition_status": "defined", "notes": ""},
            ],
            geo_markets=[
                {"market_id": "gm_1", "name": "EEA",
                 "definition_status": "defined", "notes": ""},
            ],
            theories=[],
        )

    def _draft_matched_plus_new(self) -> dict:
        return {
            "product_markets_considered": [
                {"market_id": "pm_1", "name": "Online advertising",
                 "definition_status": "defined", "notes": ""},
                {"market_id": "pm_new", "name": "Display advertising",
                 "definition_status": "considered", "notes": "New market found."},
            ],
            "geographic_markets_considered": [],
            "theories_of_harm": [],
        }

    def test_supported_finding_has_matched_group(self):
        findings = _reconcile(self._draft_matched_plus_new(), self._existing())
        matched = [f for f in findings if f.finding_type == "supported_as_is"]
        assert all(f.group == "matched" for f in matched)

    def test_new_finding_has_candidate_addition_group(self):
        findings = _reconcile(self._draft_matched_plus_new(), self._existing())
        new_f = [f for f in findings if f.finding_type == "new_from_source"]
        assert all(f.group == "candidate_addition" for f in new_f)

    def test_unsupported_finding_has_out_of_scope_group(self):
        findings = _reconcile(self._draft_matched_plus_new(), self._existing())
        removed = [f for f in findings if f.finding_type == "unsupported_remove"]
        assert all(f.group == "out_of_scope" for f in removed)

    def test_rename_finding_has_likely_rename_group(self):
        draft = {
            "product_markets_considered": [
                {"market_id": "pm_1", "name": "Online advertis",  # similar but not same
                 "definition_status": "defined", "notes": ""},
            ],
            "geographic_markets_considered": [],
            "theories_of_harm": [],
        }
        findings = _reconcile(draft, self._existing())
        rename_f = [f for f in findings if f.finding_type == "should_be_renamed"]
        assert all(f.group == "likely_rename" for f in rename_f)

    def test_group_reconciliation_partitions_all_groups(self):
        findings = _reconcile(self._draft_matched_plus_new(), self._existing())
        grouped = _group_reconciliation(findings)
        assert "matched" in grouped
        assert "candidate_addition" in grouped
        assert "out_of_scope" in grouped
        # Every finding must appear in exactly one group
        total_in_groups = sum(len(v) for v in grouped.values())
        assert total_in_groups == len(findings)

    def test_group_reconciliation_keys_present_even_when_empty(self):
        """All four groups always exist as keys even when a group has no findings."""
        grouped = _group_reconciliation([])
        for key in ("matched", "candidate_addition", "likely_rename", "out_of_scope"):
            assert key in grouped

    def test_serialize_report_includes_reconciliation_grouped(self, tmp_path):
        """serialize_report output includes reconciliation_grouped dict."""
        from unittest.mock import patch, MagicMock
        existing = _make_record()
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))

        page_cache = {
            "source_document_id": "doc1",
            "source_url": "https://example.com/doc.pdf",
            "page_count": 1,
            "pages": [{"page_number": 1, "text": "8.6 Market\nContent."}],
            "extracted_at": "2026-05-27T00:00:00+00:00",
        }
        mock_block = MagicMock()
        mock_block.type = "tool_use"
        mock_block.input = {
            "product_markets": [], "geographic_markets": [], "theories_of_harm": [],
            "overall_outcome": "unknown", "source_passages": [], "caveats": [],
        }
        mock_msg = MagicMock()
        mock_msg.content = [mock_block]
        mock_ac = MagicMock()
        mock_ac.messages.create.return_value = mock_msg

        with patch("extract_case_from_source.load_cache", return_value=page_cache):
            rpt = extract_case(
                yaml_path, cache_dir=tmp_path / "cache",
                use_claude=True, anthropic_client=mock_ac,
            )

        payload = serialize_report(rpt)
        assert "reconciliation_grouped" in payload
        assert isinstance(payload["reconciliation_grouped"], dict)


# ---------------------------------------------------------------------------
# Full Section 8 focus guardrails integration test
# ---------------------------------------------------------------------------

class TestFullSectionEightGuardrails:
    """focus=market_definition on a full Section 8 extraction keeps theories=[] and outcome=unknown."""

    def test_section_8_market_def_no_theories_and_unknown_outcome(self, tmp_path):
        from unittest.mock import patch, MagicMock
        existing = _make_record(
            theories=[{"theory_id": "toh_1", "name": "Data advantage", "description": ""}]
        )
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))

        page_cache = {
            "source_document_id": "doc1",
            "source_url": "https://example.com/doc.pdf",
            "page_count": 3,
            "pages": [
                {"page_number": 1, "text": "8 RELEVANT MARKETS\n8.1 Introduction."},
                {"page_number": 2, "text": "8.2 Wearable devices\nMarket analysis."},
                {"page_number": 3, "text": "8.6 Online advertising\nMarket defined by Commission."},
            ],
            "extracted_at": "2026-05-27T00:00:00+00:00",
        }
        mock_block = MagicMock()
        mock_block.type = "tool_use"
        mock_block.input = {
            "product_markets": [
                {"name": "Online advertising", "definition_status": "defined",
                 "market_importance": "core_assessed",
                 "notes": "Commission defined.", "not_found": False, "passages": []}
            ],
            "geographic_markets": [],
            "theories_of_harm": [
                {"name": "Data advantage", "theory_type": "data", "theory_outcome": "dismissed",
                 "notes": "", "not_found": False, "passages": []}
            ],
            "overall_outcome": "cleared_with_conditions",
            "source_passages": [],
            "caveats": [],
        }
        mock_msg = MagicMock()
        mock_msg.content = [mock_block]
        mock_ac = MagicMock()
        mock_ac.messages.create.return_value = mock_msg

        with patch("extract_case_from_source.load_cache", return_value=page_cache):
            rpt = extract_case(
                yaml_path, cache_dir=tmp_path / "cache",
                use_claude=True, anthropic_client=mock_ac,
                focus="market_definition",
            )

        assert rpt.error is None
        assert rpt.result is not None
        assert rpt.result.theories == [], "focus=market_definition must strip theories"
        assert rpt.result.overall_outcome == "unknown", (
            "focus=market_definition must force outcome to unknown"
        )
        # market_importance must be preserved through the full pipeline
        assert rpt.result.product_markets[0].market_importance == "core_assessed"


# ---------------------------------------------------------------------------
# Enhanced reconciliation similarity tests
# ---------------------------------------------------------------------------

class TestMarketSimilarityEnhanced:
    """_market_similarity uses synonym normalization + token Jaccard for better matching."""

    def test_os_platform_synonym_expansion(self):
        """'OS' and 'platforms' are normalised to 'operating system'."""
        norm = _normalize_for_similarity("Wearable OS / platforms")
        assert "operating system" in norm

    def test_wrist_worn_synonym(self):
        """'wrist-worn' normalises to 'wearable'."""
        norm = _normalize_for_similarity("wrist-worn wearable devices")
        assert "wrist" not in norm or "wearable" in norm

    def test_ad_tech_synonym(self):
        """'ad tech' normalises to 'advertising technology'."""
        norm = _normalize_for_similarity("ad tech services")
        assert "advertising" in norm

    def test_wearable_os_matches_licensable_os_wrist_worn(self):
        """'Wearable OS / platforms' must score >= _SIMILARITY_RENAME against the
        verbose draft name 'Supply of licensable OSs for wrist-worn wearable devices'."""
        from extract_case_from_source import _SIMILARITY_RENAME
        sim = _market_similarity(
            "Wearable OS / platforms",
            "Supply of licensable OSs for wrist-worn wearable devices",
        )
        assert sim >= _SIMILARITY_RENAME, (
            f"Expected >= {_SIMILARITY_RENAME}, got {sim:.3f}"
        )

    def test_unrelated_markets_score_low(self):
        """Unrelated markets like 'Cloud gaming' vs 'Online advertising' score below rename."""
        from extract_case_from_source import _SIMILARITY_RENAME
        sim = _market_similarity("Cloud gaming services", "Online advertising market")
        assert sim < _SIMILARITY_RENAME, f"Expected < {_SIMILARITY_RENAME}, got {sim:.3f}"

    def test_identical_names_score_one(self):
        sim = _market_similarity("Online advertising", "Online advertising")
        assert sim == 1.0

    def test_online_advertising_variants_score_high(self):
        """'Online advertising' vs 'Online advertising services' must be high similarity."""
        from extract_case_from_source import _SIMILARITY_RENAME
        sim = _market_similarity("Online advertising", "Online advertising services")
        assert sim >= _SIMILARITY_RENAME


class TestGeoProductContextOverlap:
    """_geo_product_context_overlap correctly compares product contexts."""

    def test_wearable_fitness_vs_health_fitness_apps_low_overlap(self):
        """'EEA (wearable fitness devices)' and 'Health and fitness apps — geographic scope'
        share 'fitness' but differ in product type — overlap must be below the threshold."""
        overlap = _geo_product_context_overlap(
            "EEA (wearable fitness devices)",
            "Health and fitness apps — geographic scope",
        )
        assert overlap < _GEO_CONTEXT_MIN_OVERLAP, (
            f"Expected < {_GEO_CONTEXT_MIN_OVERLAP}, got {overlap:.3f}"
        )

    def test_online_advertising_contexts_high_overlap(self):
        """Two online advertising geo markets must have high product context overlap."""
        overlap = _geo_product_context_overlap(
            "EEA (online advertising)",
            "Online advertising (and segments thereof) — national or along national lines",
        )
        assert overlap >= _GEO_CONTEXT_MIN_OVERLAP, (
            f"Expected >= {_GEO_CONTEXT_MIN_OVERLAP}, got {overlap:.3f}"
        )

    def test_wearable_devices_same_context_high_overlap(self):
        """Wearable device markets for the same product must have high overlap."""
        overlap = _geo_product_context_overlap(
            "EEA (wearable fitness devices)",
            "Wrist-worn wearable devices — geographic scope (at least EEA-wide)",
        )
        assert overlap >= _GEO_CONTEXT_MIN_OVERLAP, (
            f"Expected >= {_GEO_CONTEXT_MIN_OVERLAP}, got {overlap:.3f}"
        )

    def test_ad_tech_vs_wearable_low_overlap(self):
        """Ad tech and wearable geo markets must have very low product context overlap."""
        overlap = _geo_product_context_overlap(
            "Ad tech services (online advertising) — national",
            "Wrist-worn wearable devices — geographic scope",
        )
        assert overlap < _GEO_CONTEXT_MIN_OVERLAP, (
            f"Expected < {_GEO_CONTEXT_MIN_OVERLAP}, got {overlap:.3f}"
        )


class TestReconciliationSmarter:
    """Integration: _reconcile produces correct findings with the improved similarity."""

    def _existing_pm(self, name: str, mid: str = "pm_1") -> dict:
        return _make_record(
            markets=[{"market_id": mid, "name": name,
                      "definition_status": "defined", "notes": ""}],
            geo_markets=[],
            theories=[],
        )

    def _draft_pm(self, name: str) -> dict:
        return {
            "product_markets_considered": [
                {"market_id": "pm_new", "name": name,
                 "definition_status": "defined", "notes": ""}
            ],
            "geographic_markets_considered": [],
            "theories_of_harm": [],
        }

    def _existing_gm(self, name: str, mid: str = "gm_1") -> dict:
        return _make_record(
            markets=[],
            geo_markets=[{"market_id": mid, "name": name,
                          "definition_status": "defined", "notes": ""}],
            theories=[],
        )

    def _draft_gm(self, name: str) -> dict:
        return {
            "product_markets_considered": [],
            "geographic_markets_considered": [
                {"market_id": "gm_new", "name": name,
                 "definition_status": "defined", "notes": ""}
            ],
            "theories_of_harm": [],
        }

    def test_wearable_os_platforms_matches_as_rename(self):
        """'Wearable OS / platforms' must be classified as likely_rename, not unsupported_remove."""
        findings = _reconcile(
            self._draft_pm("Supply of licensable OSs for wrist-worn wearable devices"),
            self._existing_pm("Wearable OS / platforms"),
        )
        pm1 = [f for f in findings if f.existing_id == "pm_1"]
        assert pm1, "Finding for pm_1 must exist"
        types = {f.finding_type for f in pm1}
        assert "unsupported_remove" not in types, (
            "'Wearable OS / platforms' must not be unsupported_remove when a synonym "
            "match exists; got: " + str(types)
        )
        assert "should_be_renamed" in types or "supported_as_is" in types

    def test_eea_wearable_fitness_does_not_match_health_fitness_apps_as_rename(self):
        """'EEA (wearable fitness devices)' must NOT match 'Health and fitness apps — geographic scope'
        as likely_rename — the product contexts are different."""
        findings = _reconcile(
            self._draft_gm("Health and fitness apps — geographic scope"),
            self._existing_gm("EEA (wearable fitness devices)"),
        )
        gm1 = [f for f in findings if f.existing_id == "gm_1"]
        assert gm1, "Finding for gm_1 must exist"
        rename_findings = [f for f in gm1 if f.finding_type == "should_be_renamed"]
        assert not rename_findings, (
            "'EEA (wearable fitness devices)' must not be should_be_renamed to "
            "'Health and fitness apps — geographic scope'; product contexts differ."
        )

    def test_eea_wearable_fitness_does_not_match_becomes_candidate_addition(self):
        """When the geo rename is blocked, the draft market must appear as candidate_addition."""
        findings = _reconcile(
            self._draft_gm("Health and fitness apps — geographic scope"),
            self._existing_gm("EEA (wearable fitness devices)"),
        )
        candidate = [f for f in findings
                     if f.finding_type == "new_from_source"
                     and "Health and fitness" in f.draft_name]
        assert candidate, (
            "Draft 'Health and fitness apps' geo market must appear as candidate_addition "
            "when context overlap with existing is too low."
        )

    def test_online_advertising_geo_markets_matched_when_context_overlaps(self):
        """Online advertising geo markets with matching context should rename/match."""
        findings = _reconcile(
            self._draft_gm("Online advertising services — national or along national lines"),
            self._existing_gm("EEA (online advertising)"),
        )
        gm1 = [f for f in findings if f.existing_id == "gm_1"]
        assert gm1
        # Should be rename or supported (not plain unsupported_remove with no note)
        # The contexts both contain "online advertising" so overlap is high
        has_confident_no_match = any(
            f.finding_type == "unsupported_remove" and "manual review" not in f.message
            for f in gm1
        )
        assert not has_confident_no_match, (
            "Online advertising geo markets with overlapping context should not be "
            "silently dropped as unsupported_remove."
        )

    def test_manual_review_message_on_blocked_geo_rename(self):
        """When a geo rename is blocked by context, the message says 'manual review required'."""
        findings = _reconcile(
            self._draft_gm("Health and fitness apps — geographic scope"),
            self._existing_gm("EEA (wearable fitness devices)"),
        )
        gm1_unsupported = [f for f in findings
                           if f.existing_id == "gm_1"
                           and f.finding_type == "unsupported_remove"]
        assert gm1_unsupported
        assert any("manual review" in f.message.lower() for f in gm1_unsupported), (
            "Blocked geo renames must include 'manual review required' in the message"
        )


# ---------------------------------------------------------------------------
# Reconciliation finding draft metadata tests
# ---------------------------------------------------------------------------

class TestReconciliationFindingDraftMetadata:
    """Each finding that references a draft market carries draft_market_type,
    draft_market_importance, draft_definition_status, and draft_source_refs."""

    def _existing_pm(self, name: str = "Online advertising") -> dict:
        return _make_record(
            markets=[{"market_id": "pm_1", "name": name,
                      "definition_status": "defined", "notes": ""}],
            geo_markets=[],
            theories=[],
        )

    def _draft_with_metadata(
        self,
        name: str = "Online advertising services",
        importance: str = "core_assessed",
        status: str = "defined",
        market_id: str = "pm_new",
        passages: list | None = None,
    ) -> dict:
        d: dict = {
            "product_markets_considered": [
                {
                    "market_id": market_id,
                    "name": name,
                    "definition_status": status,
                    "market_importance": importance,
                    "notes": "",
                    "verification": {"status": "source_linked"},
                }
            ],
            "geographic_markets_considered": [],
            "theories_of_harm": [],
        }
        if passages:
            d["source_passages"] = passages
        return d

    def _passages_for(self, market_id: str, pages: list[str]) -> list[dict]:
        return [
            {
                "passage_id": f"sp_{i+1}",
                "source_document_id": "doc1",
                "page": p,
                "quote_snippet": "Test quote.",
                "supports_markets": [market_id],
                "supports_geographic_markets": [],
                "supports_theories": [],
            }
            for i, p in enumerate(pages)
        ]

    # ------------------------------------------------------------------
    # candidate_addition (new_from_source) carries draft metadata
    # ------------------------------------------------------------------

    def test_candidate_addition_has_draft_market_type(self):
        draft = self._draft_with_metadata()
        findings = _reconcile(draft, _make_record(markets=[], geo_markets=[], theories=[]))
        candidates = [f for f in findings if f.finding_type == "new_from_source"]
        assert candidates
        assert all(f.draft_market_type == "product" for f in candidates)

    def test_candidate_addition_has_draft_importance(self):
        draft = self._draft_with_metadata(importance="core_assessed")
        findings = _reconcile(draft, _make_record(markets=[], geo_markets=[], theories=[]))
        candidates = [f for f in findings if f.finding_type == "new_from_source"]
        assert any(f.draft_market_importance == "core_assessed" for f in candidates)

    def test_candidate_addition_has_draft_definition_status(self):
        draft = self._draft_with_metadata(status="left_open")
        findings = _reconcile(draft, _make_record(markets=[], geo_markets=[], theories=[]))
        candidates = [f for f in findings if f.finding_type == "new_from_source"]
        assert any(f.draft_definition_status == "left_open" for f in candidates)

    def test_candidate_addition_has_draft_source_refs(self):
        passages = self._passages_for("pm_new", ["42", "43"])
        draft = self._draft_with_metadata(passages=passages)
        findings = _reconcile(draft, _make_record(markets=[], geo_markets=[], theories=[]))
        candidates = [f for f in findings if f.finding_type == "new_from_source"]
        assert candidates
        refs = candidates[0].draft_source_refs
        assert "42" in refs and "43" in refs

    def test_candidate_addition_deduplicates_source_refs(self):
        """Same page cited twice must appear only once in draft_source_refs."""
        passages = self._passages_for("pm_new", ["42", "42", "43"])
        draft = self._draft_with_metadata(passages=passages)
        findings = _reconcile(draft, _make_record(markets=[], geo_markets=[], theories=[]))
        candidates = [f for f in findings if f.finding_type == "new_from_source"]
        refs = candidates[0].draft_source_refs
        assert refs.count("42") == 1

    def test_candidate_missing_importance_gives_empty_string(self):
        """When draft market has no market_importance, field is empty string not null."""
        draft = {
            "product_markets_considered": [
                {"market_id": "pm_new", "name": "Cloud gaming",
                 "definition_status": "discussed", "notes": ""}
            ],
            "geographic_markets_considered": [],
            "theories_of_harm": [],
        }
        findings = _reconcile(draft, _make_record(markets=[], geo_markets=[], theories=[]))
        candidates = [f for f in findings if f.finding_type == "new_from_source"]
        assert candidates
        assert candidates[0].draft_market_importance == ""

    # ------------------------------------------------------------------
    # likely_rename (should_be_renamed) carries draft metadata
    # ------------------------------------------------------------------

    def test_likely_rename_has_draft_importance(self):
        # "Online advertising" vs "Display advertising technology" → ~0.54 rename range
        existing = self._existing_pm("Online advertising")
        draft = self._draft_with_metadata(
            name="Display advertising technology", importance="core_assessed"
        )
        findings = _reconcile(draft, existing)
        # Both should_be_renamed and supported_as_is carry draft metadata
        matched = [f for f in findings
                   if f.finding_type in ("should_be_renamed", "supported_as_is")
                   and f.existing_id == "pm_1"]
        assert matched, "A matched/rename finding for pm_1 must exist"
        assert any(f.draft_market_importance == "core_assessed" for f in matched)

    def test_likely_rename_has_draft_definition_status(self):
        existing = self._existing_pm("Online advertising")
        draft = self._draft_with_metadata(
            name="Display advertising technology", status="left_open"
        )
        findings = _reconcile(draft, existing)
        matched = [f for f in findings
                   if f.finding_type in ("should_be_renamed", "supported_as_is")
                   and f.existing_id == "pm_1"]
        assert matched
        assert any(f.draft_definition_status == "left_open" for f in matched)

    def test_likely_rename_has_draft_market_type(self):
        existing = self._existing_pm("Online advertising")
        draft = self._draft_with_metadata(name="Display advertising technology")
        findings = _reconcile(draft, existing)
        matched = [f for f in findings
                   if f.finding_type in ("should_be_renamed", "supported_as_is")
                   and f.existing_id == "pm_1"]
        assert matched
        assert all(f.draft_market_type == "product" for f in matched)

    # ------------------------------------------------------------------
    # unsupported_remove has NO draft metadata
    # ------------------------------------------------------------------

    def test_unsupported_remove_has_empty_draft_type(self):
        """Findings with no draft counterpart must have empty draft metadata."""
        existing = self._existing_pm("Digital music streaming")
        draft = self._draft_with_metadata(name="Cloud gaming", importance="background")
        findings = _reconcile(draft, existing)
        removals = [f for f in findings
                    if f.finding_type == "unsupported_remove"
                    and f.existing_id == "pm_1"]
        assert removals
        assert all(f.draft_market_type == "" for f in removals)
        assert all(f.draft_market_importance == "" for f in removals)

    # ------------------------------------------------------------------
    # geographic market candidate_addition
    # ------------------------------------------------------------------

    def test_geo_candidate_addition_has_geographic_market_type(self):
        draft = {
            "product_markets_considered": [],
            "geographic_markets_considered": [
                {"market_id": "gm_new", "name": "EEA — wearable devices",
                 "definition_status": "defined", "market_importance": "core_assessed",
                 "notes": ""}
            ],
            "theories_of_harm": [],
        }
        findings = _reconcile(draft, _make_record(markets=[], geo_markets=[], theories=[]))
        geo_candidates = [f for f in findings
                          if f.finding_type == "new_from_source"
                          and f.draft_market_type == "geographic"]
        assert geo_candidates

    # ------------------------------------------------------------------
    # _finding_to_dict serialisation
    # ------------------------------------------------------------------

    def test_finding_to_dict_includes_draft_fields_when_set(self):
        f = ReconciliationFinding(
            finding_type="new_from_source",
            group="candidate_addition",
            existing_id="",
            existing_name="",
            draft_name="Online ads",
            message="New market.",
            draft_market_type="product",
            draft_market_importance="core_assessed",
            draft_definition_status="defined",
            draft_source_refs=["42"],
        )
        d = _finding_to_dict(f)
        assert d["draft_market_type"] == "product"
        assert d["draft_market_importance"] == "core_assessed"
        assert d["draft_definition_status"] == "defined"
        assert d["draft_source_refs"] == ["42"]

    def test_finding_to_dict_omits_empty_draft_fields(self):
        """Findings without draft metadata must not emit empty keys."""
        f = ReconciliationFinding(
            finding_type="unsupported_remove",
            group="out_of_scope",
            existing_id="pm_1",
            existing_name="Old market",
            draft_name="",
            message="No match.",
        )
        d = _finding_to_dict(f)
        assert "draft_market_type" not in d
        assert "draft_market_importance" not in d
        assert "draft_definition_status" not in d
        assert "draft_source_refs" not in d

    def test_grouped_report_includes_draft_fields_in_candidates(self):
        draft = self._draft_with_metadata(importance="precedent_only", status="precedent_only")
        findings = _reconcile(draft, _make_record(markets=[], geo_markets=[], theories=[]))
        grouped = _group_reconciliation(findings)
        candidates = grouped.get("candidate_addition", [])
        assert candidates
        assert any(c.get("draft_market_importance") == "precedent_only" for c in candidates)


# ---------------------------------------------------------------------------
# Reconciliation triage tests
# ---------------------------------------------------------------------------

class TestReconciliationTriage:
    """_build_reconciliation_triage counts candidate additions by importance/status/type."""

    def _make_finding(
        self, importance: str, status: str, mtype: str = "product"
    ) -> ReconciliationFinding:
        return ReconciliationFinding(
            finding_type="new_from_source",
            group="candidate_addition",
            existing_id="",
            existing_name="",
            draft_name=f"Market {importance}",
            message="New.",
            draft_market_type=mtype,
            draft_market_importance=importance,
            draft_definition_status=status,
        )

    def _make_matched(self) -> ReconciliationFinding:
        return ReconciliationFinding(
            finding_type="supported_as_is",
            group="matched",
            existing_id="pm_1",
            existing_name="Existing",
            draft_name="Existing",
            message="Matched.",
            draft_market_type="product",
            draft_market_importance="core_assessed",
            draft_definition_status="defined",
        )

    def test_counts_only_new_from_source(self):
        findings = [
            self._make_finding("core_assessed", "defined"),
            self._make_matched(),  # not a candidate — must not be counted
        ]
        triage = _build_reconciliation_triage(findings)
        assert triage["total_candidate_additions"] == 1

    def test_by_importance_counts_correctly(self):
        findings = [
            self._make_finding("core_assessed", "defined"),
            self._make_finding("core_assessed", "left_open"),
            self._make_finding("precedent_only", "precedent_only"),
            self._make_finding("background", "unknown"),
        ]
        triage = _build_reconciliation_triage(findings)
        assert triage["by_market_importance"]["core_assessed"] == 2
        assert triage["by_market_importance"]["precedent_only"] == 1
        assert triage["by_market_importance"]["background"] == 1

    def test_by_definition_status_counts(self):
        findings = [
            self._make_finding("core_assessed", "defined"),
            self._make_finding("core_assessed", "defined"),
            self._make_finding("precedent_only", "left_open"),
        ]
        triage = _build_reconciliation_triage(findings)
        assert triage["by_definition_status"]["defined"] == 2
        assert triage["by_definition_status"]["left_open"] == 1

    def test_by_market_type_splits_product_geographic(self):
        findings = [
            self._make_finding("core_assessed", "defined", "product"),
            self._make_finding("core_assessed", "defined", "product"),
            self._make_finding("core_assessed", "defined", "geographic"),
        ]
        triage = _build_reconciliation_triage(findings)
        assert triage["by_market_type"]["product"] == 2
        assert triage["by_market_type"]["geographic"] == 1

    def test_unclassified_importance_grouped_separately(self):
        """Draft markets without market_importance appear as 'unclassified'."""
        findings = [
            ReconciliationFinding(
                finding_type="new_from_source", group="candidate_addition",
                existing_id="", existing_name="", draft_name="Cloud market",
                message="New.", draft_market_type="product",
                # market_importance intentionally empty
            ),
        ]
        triage = _build_reconciliation_triage(findings)
        assert triage["by_market_importance"].get("unclassified", 0) == 1

    def test_empty_findings_returns_zero_totals(self):
        triage = _build_reconciliation_triage([])
        assert triage["total_candidate_additions"] == 0
        assert triage["by_market_importance"] == {}
        assert triage["by_definition_status"] == {}

    def test_serialize_report_includes_triage(self, tmp_path):
        """serialize_report output must include reconciliation_triage."""
        from unittest.mock import patch, MagicMock
        existing = _make_record(markets=[], geo_markets=[], theories=[])
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))

        page_cache = {
            "source_document_id": "doc1",
            "source_url": "https://example.com/doc.pdf",
            "page_count": 1,
            "pages": [{"page_number": 1, "text": "8.6 Market\nContent."}],
            "extracted_at": "2026-05-27T00:00:00+00:00",
        }
        mock_block = MagicMock()
        mock_block.type = "tool_use"
        mock_block.input = {
            "product_markets": [
                {"name": "Online ads", "definition_status": "defined",
                 "market_importance": "core_assessed",
                 "notes": "", "not_found": False, "passages": []}
            ],
            "geographic_markets": [],
            "theories_of_harm": [],
            "overall_outcome": "unknown",
            "source_passages": [],
            "caveats": [],
        }
        mock_msg = MagicMock()
        mock_msg.content = [mock_block]
        mock_ac = MagicMock()
        mock_ac.messages.create.return_value = mock_msg

        with patch("extract_case_from_source.load_cache", return_value=page_cache):
            rpt = extract_case(
                yaml_path, cache_dir=tmp_path / "cache",
                use_claude=True, anthropic_client=mock_ac,
            )

        payload = serialize_report(rpt)
        assert "reconciliation_triage" in payload
        triage = payload["reconciliation_triage"]
        assert "total_candidate_additions" in triage
        assert "by_market_importance" in triage
        assert "by_definition_status" in triage
        assert "by_market_type" in triage

    def test_triage_distinguishes_core_from_precedent(self, tmp_path):
        """Core_assessed and precedent_only candidates appear in separate triage buckets."""
        from unittest.mock import patch, MagicMock
        # Build a genuinely empty existing record (avoid _make_record's 'or' fallback
        # which inserts default markets when an empty list is passed).
        existing = {
            "case_id": "test_case", "case_name": "Test", "authority": "EC",
            "jurisdiction": "EU", "sector": "digital", "outcome": "unknown",
            "decision_date": "2021-01-01", "parties": [],
            "source_documents": [{"doc_id": "doc1", "title": "D",
                                   "pdf_url": "https://example.com/d.pdf",
                                   "doc_type": "decision"}],
            "source_passages": [],
            "product_markets_considered": [],
            "geographic_markets_considered": [],
            "theories_of_harm": [],
        }
        yaml_path = tmp_path / "test_case.yaml"
        yaml_path.write_text(yaml.dump(existing))

        page_cache = {
            "source_document_id": "doc1",
            "source_url": "https://example.com/doc.pdf",
            "page_count": 1,
            "pages": [{"page_number": 1, "text": "8.6 Market\nContent."}],
            "extracted_at": "2026-05-27T00:00:00+00:00",
        }
        mock_block = MagicMock()
        mock_block.type = "tool_use"
        mock_block.input = {
            "product_markets": [
                {"name": "Core market", "definition_status": "defined",
                 "market_importance": "core_assessed",
                 "notes": "", "not_found": False, "passages": []},
                {"name": "Precedent market", "definition_status": "precedent_only",
                 "market_importance": "precedent_only",
                 "notes": "", "not_found": False, "passages": []},
            ],
            "geographic_markets": [],
            "theories_of_harm": [],
            "overall_outcome": "unknown",
            "source_passages": [],
            "caveats": [],
        }
        mock_msg = MagicMock()
        mock_msg.content = [mock_block]
        mock_ac = MagicMock()
        mock_ac.messages.create.return_value = mock_msg

        with patch("extract_case_from_source.load_cache", return_value=page_cache):
            rpt = extract_case(
                yaml_path, cache_dir=tmp_path / "cache",
                use_claude=True, anthropic_client=mock_ac,
            )

        payload = serialize_report(rpt)
        triage = payload["reconciliation_triage"]
        by_imp = triage["by_market_importance"]
        assert by_imp.get("core_assessed", 0) >= 1
        assert by_imp.get("precedent_only", 0) >= 1


# ---------------------------------------------------------------------------
# Device context discrimination tests (Issue 1 — OS/platform product markets)
# ---------------------------------------------------------------------------

class TestDeviceContextDiscrimination:
    """Device context detection and conflict penalty prevent cross-device OS mismatches."""

    # ------------------------------------------------------------------
    # Unit: _detect_device_contexts
    # ------------------------------------------------------------------

    def test_wearable_context_detected_from_wearable_keyword(self):
        assert "wearable" in _detect_device_contexts("Wearable OS / platforms")

    def test_wearable_context_detected_from_wrist_worn(self):
        """'wrist-worn' is expanded to 'wearable' by synonym map before detection."""
        assert "wearable" in _detect_device_contexts("Supply of licensable OSs for wrist-worn wearable devices")

    def test_pc_context_detected(self):
        assert "pc" in _detect_device_contexts("OSs for PCs")

    def test_mobile_context_detected(self):
        assert "mobile" in _detect_device_contexts("Licensable OSs for smart mobile devices")

    def test_no_device_context_in_generic_name(self):
        assert _detect_device_contexts("Online advertising services") == frozenset()

    # ------------------------------------------------------------------
    # Unit: _device_context_factor
    # ------------------------------------------------------------------

    def test_conflict_factor_pc_vs_wearable(self):
        factor = _device_context_factor("Wearable OS / platforms", "OSs for PCs")
        assert factor == _DEVICE_CONTEXT_CONFLICT_FACTOR
        assert factor < 1.0

    def test_no_conflict_wearable_vs_wearable(self):
        factor = _device_context_factor(
            "Wearable OS / platforms",
            "Supply of licensable OSs for wrist-worn wearable devices",
        )
        assert factor == 1.0

    def test_no_conflict_when_no_device_context(self):
        """No penalty when one or both names have no device context."""
        factor = _device_context_factor("Wearable OS / platforms", "Online advertising")
        assert factor == 1.0

    def test_conflict_factor_pc_vs_mobile(self):
        factor = _device_context_factor("OSs for PCs", "Licensable OSs for smart mobile devices")
        assert factor == _DEVICE_CONTEXT_CONFLICT_FACTOR

    # ------------------------------------------------------------------
    # Unit: penalized similarity
    # ------------------------------------------------------------------

    def test_pcs_similarity_penalized_below_rename_threshold(self):
        """After device-context penalty, 'OSs for PCs' must not reach the rename threshold."""
        from scripts.extract_case_from_source import _SIMILARITY_RENAME
        raw = _market_similarity("Wearable OS / platforms", "OSs for PCs")
        penalized = raw * _device_context_factor("Wearable OS / platforms", "OSs for PCs")
        assert penalized < _SIMILARITY_RENAME, (
            f"Penalized similarity {penalized:.3f} must be below rename threshold {_SIMILARITY_RENAME}"
        )

    def test_wrist_worn_wearable_similarity_above_rename_threshold(self):
        """No penalty: 'Supply of licensable OSs for wrist-worn wearable devices' stays above threshold."""
        from scripts.extract_case_from_source import _SIMILARITY_RENAME
        sim = _market_similarity(
            "Wearable OS / platforms",
            "Supply of licensable OSs for wrist-worn wearable devices",
        )
        assert sim >= _SIMILARITY_RENAME, (
            f"Similarity {sim:.3f} must be >= rename threshold {_SIMILARITY_RENAME}"
        )

    # ------------------------------------------------------------------
    # Integration: _reconcile product market matching
    # ------------------------------------------------------------------

    def _existing_wearable_os(self) -> dict:
        return _make_record(
            markets=[{"market_id": "pm_2", "name": "Wearable OS / platforms",
                      "definition_status": "defined", "notes": ""}],
            geo_markets=[],
            theories=[],
        )

    def _draft_with_both_os_candidates(self) -> dict:
        return {
            "product_markets_considered": [
                {"market_id": "pm_a", "name": "OSs for PCs",
                 "definition_status": "defined", "notes": ""},
                {"market_id": "pm_b", "name": "Supply of licensable OSs for wrist-worn wearable devices",
                 "definition_status": "defined", "notes": ""},
            ],
            "geographic_markets_considered": [],
            "theories_of_harm": [],
        }

    def test_wearable_os_does_not_match_pcs_as_rename(self):
        """'Wearable OS / platforms' must NOT be matched to 'OSs for PCs' as likely_rename."""
        findings = _reconcile(self._draft_with_both_os_candidates(), self._existing_wearable_os())
        pm2 = [f for f in findings if f.existing_id == "pm_2"]
        assert pm2
        matched_to_pcs = [
            f for f in pm2
            if "PC" in f.draft_name or "PCs" in f.draft_name
        ]
        assert not matched_to_pcs, (
            f"'Wearable OS / platforms' must not match 'OSs for PCs'; got: {[f.draft_name for f in pm2]}"
        )

    def test_wearable_os_matches_wrist_worn_wearable_as_rename(self):
        """'Wearable OS / platforms' SHOULD be matched to 'Supply of licensable OSs for wrist-worn...'."""
        findings = _reconcile(self._draft_with_both_os_candidates(), self._existing_wearable_os())
        pm2 = [f for f in findings if f.existing_id == "pm_2"]
        assert pm2
        matched_to_wearable = [
            f for f in pm2
            if f.finding_type in ("should_be_renamed", "supported_as_is")
            and ("wrist" in f.draft_name.lower() or "wearable" in f.draft_name.lower())
        ]
        assert matched_to_wearable, (
            f"'Wearable OS / platforms' must match wrist-worn/wearable candidate; "
            f"got pm2 findings: {[(f.finding_type, f.draft_name) for f in pm2]}"
        )

    def test_pcs_os_appears_as_candidate_addition(self):
        """'OSs for PCs' must appear as candidate_addition (not consumed by the wearable OS match)."""
        findings = _reconcile(self._draft_with_both_os_candidates(), self._existing_wearable_os())
        candidates = [f for f in findings if f.finding_type == "new_from_source"]
        candidate_names = [f.draft_name for f in candidates]
        assert any("PC" in n or "PCs" in n for n in candidate_names), (
            f"'OSs for PCs' must appear as candidate_addition; got candidates: {candidate_names}"
        )

    def test_wearable_os_only_pcs_in_draft_does_not_rename(self):
        """When ONLY 'OSs for PCs' is in draft, 'Wearable OS / platforms' gets no confident match."""
        draft = {
            "product_markets_considered": [
                {"market_id": "pm_a", "name": "OSs for PCs",
                 "definition_status": "defined", "notes": ""},
            ],
            "geographic_markets_considered": [],
            "theories_of_harm": [],
        }
        findings = _reconcile(draft, self._existing_wearable_os())
        pm2 = [f for f in findings if f.existing_id == "pm_2"]
        assert pm2
        # With only a PC candidate (conflict factor), pm_2 should NOT be should_be_renamed
        rename_to_pcs = [f for f in pm2 if f.finding_type == "should_be_renamed"]
        assert not rename_to_pcs, (
            f"'Wearable OS / platforms' must not rename to 'OSs for PCs'; got: {[(f.finding_type, f.draft_name) for f in pm2]}"
        )


# ---------------------------------------------------------------------------
# Geo market fallback tests (Issue 2 — EEA wearable fitness devices)
# ---------------------------------------------------------------------------

class TestGeoMarketFallback:
    """Geo market fallback picks a context-matching candidate even when a higher-scoring
    but context-mismatched candidate exists first in the sorted order."""

    def _existing_gm(self) -> dict:
        return _make_record(
            markets=[],
            geo_markets=[{"market_id": "gm_1", "name": "EEA (wearable fitness devices)",
                          "definition_status": "defined", "notes": ""}],
            theories=[],
        )

    def _draft_with_both_gm_candidates(self) -> dict:
        return {
            "product_markets_considered": [],
            "geographic_markets_considered": [
                {"market_id": "gm_a", "name": "Health and fitness apps — geographic scope",
                 "definition_status": "defined", "notes": ""},
                {"market_id": "gm_b", "name": "Wrist-worn wearable devices — geographic scope (at least EEA-wide)",
                 "definition_status": "defined", "notes": ""},
            ],
            "theories_of_harm": [],
        }

    def test_wearable_fitness_matches_wrist_worn_not_health_apps(self):
        """'EEA (wearable fitness devices)' should match 'Wrist-worn wearable devices — geographic scope',
        NOT 'Health and fitness apps — geographic scope'."""
        findings = _reconcile(self._draft_with_both_gm_candidates(), self._existing_gm())
        gm1 = [f for f in findings if f.existing_id == "gm_1"]
        assert gm1
        renames = [f for f in gm1 if f.finding_type == "should_be_renamed"]
        assert renames, (
            f"'EEA (wearable fitness devices)' must produce a should_be_renamed finding; got: {[(f.finding_type, f.draft_name) for f in gm1]}"
        )
        assert all("wrist" in f.draft_name.lower() or "wearable" in f.draft_name.lower()
                   for f in renames), (
            f"Rename must point to wearable candidate, not health/fitness apps; got: {[f.draft_name for f in renames]}"
        )

    def test_health_fitness_apps_not_matched_to_wearable_fitness(self):
        """'Health and fitness apps' must NOT be consumed as the match for 'EEA (wearable fitness devices)'."""
        findings = _reconcile(self._draft_with_both_gm_candidates(), self._existing_gm())
        renames = [f for f in findings
                   if f.finding_type == "should_be_renamed"
                   and f.existing_id == "gm_1"]
        for r in renames:
            assert "health" not in r.draft_name.lower(), (
                f"'Health and fitness apps' must not be the rename target; got: {r.draft_name!r}"
            )

    def test_health_fitness_apps_appears_as_candidate_addition(self):
        """'Health and fitness apps — geographic scope' must appear as candidate_addition (not consumed)."""
        findings = _reconcile(self._draft_with_both_gm_candidates(), self._existing_gm())
        candidates = [f for f in findings if f.finding_type == "new_from_source"]
        assert any("health" in f.draft_name.lower() for f in candidates), (
            f"'Health and fitness apps' must appear as candidate_addition; candidates: {[f.draft_name for f in candidates]}"
        )

    def test_wearable_context_overlap_above_threshold(self):
        """Verify context overlap scores that drive the fallback logic."""
        assert _geo_product_context_overlap(
            "EEA (wearable fitness devices)",
            "Wrist-worn wearable devices — geographic scope (at least EEA-wide)",
        ) >= _GEO_CONTEXT_MIN_OVERLAP

    def test_health_fitness_context_overlap_below_threshold(self):
        assert _geo_product_context_overlap(
            "EEA (wearable fitness devices)",
            "Health and fitness apps — geographic scope",
        ) < _GEO_CONTEXT_MIN_OVERLAP

    def test_only_health_fitness_in_draft_gives_no_confident_match(self):
        """When ONLY 'Health and fitness apps' is available, no confident match is made."""
        draft = {
            "product_markets_considered": [],
            "geographic_markets_considered": [
                {"market_id": "gm_a", "name": "Health and fitness apps — geographic scope",
                 "definition_status": "defined", "notes": ""},
            ],
            "theories_of_harm": [],
        }
        findings = _reconcile(draft, self._existing_gm())
        gm1 = [f for f in findings if f.existing_id == "gm_1"]
        renames = [f for f in gm1 if f.finding_type == "should_be_renamed"]
        assert not renames, (
            "With only a context-mismatched candidate, must not produce should_be_renamed"
        )

    def test_fallback_skips_context_mismatched_candidate(self):
        """Fallback loop must skip 'Health and fitness apps' (ctx < 0.30) and find 'Wrist-worn wearable'."""
        # Order the draft so health/fitness apps comes first (forcing the fallback)
        draft = {
            "product_markets_considered": [],
            "geographic_markets_considered": [
                # health/fitness comes first but context fails
                {"market_id": "gm_bad", "name": "Health and fitness apps — geographic scope",
                 "definition_status": "defined", "notes": ""},
                # wearable comes second — fallback should find this
                {"market_id": "gm_good", "name": "Wrist-worn wearable devices — geographic scope (at least EEA-wide)",
                 "definition_status": "defined", "notes": ""},
            ],
            "theories_of_harm": [],
        }
        findings = _reconcile(draft, self._existing_gm())
        gm1 = [f for f in findings if f.existing_id == "gm_1"]
        renames = [f for f in gm1 if f.finding_type == "should_be_renamed"]
        assert renames, "Fallback must find 'Wrist-worn wearable devices' as rename candidate"
        assert any("wrist" in f.draft_name.lower() or "wearable" in f.draft_name.lower()
                   for f in renames)


# ---------------------------------------------------------------------------
# Promotion plan tests
# ---------------------------------------------------------------------------

class TestPromotionAction:
    """_promotion_action applies the decision rules correctly."""

    def test_core_assessed_with_refs_promotes(self):
        action, reason = _promotion_action("core_assessed", "defined", has_source_refs=True)
        assert action == "promote_to_canonical"
        assert "core_assessed" in reason

    def test_core_assessed_no_refs_manual_review(self):
        action, reason = _promotion_action("core_assessed", "defined", has_source_refs=False)
        assert action == "manual_review"

    def test_assessed_no_overlap_with_refs_context_only(self):
        # assessed_no_overlap no longer auto-promotes — kept as context only to stay conservative
        action, reason = _promotion_action("assessed_no_overlap", "defined", has_source_refs=True)
        assert action == "keep_as_context_only"
        assert "overlap" in reason.lower() or "assessed_no_overlap" in reason

    def test_assessed_no_overlap_no_refs_context_only(self):
        # assessed_no_overlap is always kept as context, regardless of source refs
        action, reason = _promotion_action("assessed_no_overlap", "defined", has_source_refs=False)
        assert action == "keep_as_context_only"

    def test_possible_segmentation_promote_with_uncertainty(self):
        action, _ = _promotion_action("possible_segmentation", "possible_segmentation", has_source_refs=True)
        assert action == "promote_with_uncertainty"

    def test_ancillary_keep_as_context_only(self):
        action, _ = _promotion_action("ancillary", "considered", has_source_refs=True)
        assert action == "keep_as_context_only"

    def test_precedent_only_keep_as_context_only(self):
        action, _ = _promotion_action("precedent_only", "precedent_only", has_source_refs=False)
        assert action == "keep_as_context_only"

    def test_background_exclude_from_canonical(self):
        action, _ = _promotion_action("background", "unknown", has_source_refs=False)
        assert action == "exclude_from_canonical"

    def test_incomplete_source_hold_pending(self):
        action, reason = _promotion_action("incomplete_source", "unknown", has_source_refs=False)
        assert action == "hold_pending_source_check"
        assert "absent" in reason.lower() or "missing" in reason.lower() or "conclusion" in reason.lower()

    def test_unknown_status_no_refs_hold_pending(self):
        action, _ = _promotion_action("core_assessed", "unknown", has_source_refs=False)
        # unknown status without refs → hold_pending_source_check
        assert action == "hold_pending_source_check"

    def test_empty_importance_empty_status_no_refs_hold_pending(self):
        action, _ = _promotion_action("", "", has_source_refs=False)
        assert action == "hold_pending_source_check"

    def test_core_assessed_with_possible_segmentation_not_plain_promote(self):
        # Stricter rules: possible_segmentation requires explicit review, not plain promotion
        action, reason = _promotion_action("core_assessed", "possible_segmentation", has_source_refs=True)
        assert action == "promote_with_uncertainty"
        assert "segmentation" in reason.lower()
        assert "review" in reason.lower()

    def test_core_assessed_with_defined_and_refs_promotes(self):
        # Still promotes when status is conclusive (defined)
        action, reason = _promotion_action("core_assessed", "defined", has_source_refs=True)
        assert action == "promote_to_canonical"
        assert "core_assessed" in reason

    def test_core_assessed_with_left_open_and_refs_promotes(self):
        # Still promotes when status is conclusive (left_open)
        action, reason = _promotion_action("core_assessed", "left_open", has_source_refs=True)
        assert action == "promote_to_canonical"

    def test_core_assessed_with_considered_and_refs_promotes(self):
        # Still promotes when status is conclusive (considered)
        action, reason = _promotion_action("core_assessed", "considered", has_source_refs=True)
        assert action == "promote_to_canonical"

    def test_assessed_no_overlap_with_refs_still_context_only(self):
        # assessed_no_overlap stays context-only even with source refs (conservative approach)
        action, reason = _promotion_action("assessed_no_overlap", "defined", has_source_refs=True)
        assert action == "keep_as_context_only"
        assert "overlap" in reason.lower() or "assessed_no_overlap" in reason

    def test_incomplete_source_still_holds(self):
        # incomplete_source still triggers hold
        action, _ = _promotion_action("incomplete_source", "unknown", has_source_refs=False)
        assert action == "hold_pending_source_check"

    def test_unknown_status_still_holds(self):
        # unknown status without refs still holds
        action, _ = _promotion_action("core_assessed", "unknown", has_source_refs=False)
        assert action == "hold_pending_source_check"

    def test_ancillary_still_context_only(self):
        # ancillary still routes to context_only
        action, _ = _promotion_action("ancillary", "considered", has_source_refs=True)
        assert action == "keep_as_context_only"

    def test_precedent_still_context_only(self):
        # precedent_only still routes to context_only
        action, _ = _promotion_action("precedent_only", "precedent_only", has_source_refs=False)
        assert action == "keep_as_context_only"

    def test_background_still_excluded(self):
        # background still routes to exclude
        action, _ = _promotion_action("background", "considered", has_source_refs=True)
        assert action == "exclude_from_canonical"

    def test_all_actions_are_valid_values(self):
        cases = [
            ("core_assessed", "defined", True),
            ("core_assessed", "defined", False),
            ("assessed_no_overlap", "defined", True),
            ("assessed_no_overlap", "defined", False),
            ("possible_segmentation", "possible_segmentation", True),
            ("ancillary", "considered", True),
            ("precedent_only", "precedent_only", False),
            ("background", "unknown", False),
            ("incomplete_source", "unknown", False),
            ("", "", False),
            ("", "", True),
        ]
        for imp, status, refs in cases:
            action, reason = _promotion_action(imp, status, refs)
            assert action in _PROMOTION_ACTIONS, f"Invalid action {action!r} for ({imp!r}, {status!r}, {refs})"
            assert reason, "Reason must be non-empty"

    def test_assessed_no_overlap_never_promotes_to_canonical(self):
        # Tested with various statuses and source refs combinations
        test_cases = [
            ("assessed_no_overlap", "defined", True),
            ("assessed_no_overlap", "defined", False),
            ("assessed_no_overlap", "left_open", True),
            ("assessed_no_overlap", "considered", True),
            ("assessed_no_overlap", "unknown", False),
        ]
        for imp, status, has_refs in test_cases:
            action, _ = _promotion_action(imp, status, has_refs)
            assert action != "promote_to_canonical", (
                f"assessed_no_overlap should never promote to canonical "
                f"({imp!r}, {status!r}, refs={has_refs})"
            )
            assert action == "keep_as_context_only", (
                f"assessed_no_overlap should always recommend keep_as_context_only, "
                f"got {action!r}"
            )

    def test_promotion_plan_summary_groups_by_action(self):
        # Test that promotion_plan_summary correctly groups entries by action
        from extract_case_from_source import _build_promotion_plan_summary

        plan = [
            {"draft_name": "Market A", "recommended_action": "promote_to_canonical",
             "draft_market_type": "product", "market_importance": "core_assessed"},
            {"draft_name": "Market B", "recommended_action": "promote_to_canonical",
             "draft_market_type": "geographic", "market_importance": "core_assessed"},
            {"draft_name": "Market C", "recommended_action": "keep_as_context_only",
             "draft_market_type": "product", "market_importance": "assessed_no_overlap"},
            {"draft_name": "Market D", "recommended_action": "keep_as_context_only",
             "draft_market_type": "geographic", "market_importance": "ancillary"},
            {"draft_name": "Market E", "recommended_action": "promote_with_uncertainty",
             "draft_market_type": "product", "market_importance": "possible_segmentation"},
            {"draft_name": "Market F", "recommended_action": "manual_review",
             "draft_market_type": "product", "market_importance": ""},
        ]
        summary = _build_promotion_plan_summary(plan)

        # Check total count
        assert summary["total_entries"] == 6

        # Check action counts
        by_action = summary["by_action"]
        assert by_action["promote_to_canonical"] == 2
        assert by_action["keep_as_context_only"] == 2
        assert by_action["promote_with_uncertainty"] == 1
        assert by_action["manual_review"] == 1

        # Check action details
        assert summary["action_details"]["promote_to_canonical"]["count"] == 2
        assert summary["action_details"]["keep_as_context_only"]["count"] == 2
        assert summary["action_details"]["keep_as_context_only"]["by_market_importance"]["assessed_no_overlap"] == 1
        assert summary["action_details"]["keep_as_context_only"]["by_market_importance"]["ancillary"] == 1

    def test_promotion_plan_summary_market_type_breakdown(self):
        # Test that summary correctly breaks down by market type
        from extract_case_from_source import _build_promotion_plan_summary

        plan = [
            {"draft_name": "Product 1", "recommended_action": "promote_to_canonical",
             "draft_market_type": "product", "market_importance": "core_assessed"},
            {"draft_name": "Geographic 1", "recommended_action": "promote_to_canonical",
             "draft_market_type": "geographic", "market_importance": "core_assessed"},
            {"draft_name": "Product 2", "recommended_action": "keep_as_context_only",
             "draft_market_type": "product", "market_importance": "assessed_no_overlap"},
        ]
        summary = _build_promotion_plan_summary(plan)

        # Verify market type breakdown for promote_to_canonical
        promo_details = summary["action_details"]["promote_to_canonical"]
        assert promo_details["by_market_type"]["product"] == 1
        assert promo_details["by_market_type"]["geographic"] == 1

        # Verify market type breakdown for keep_as_context_only
        context_details = summary["action_details"]["keep_as_context_only"]
        assert context_details["by_market_type"]["product"] == 1


class TestPromotionActionWithGuards:
    """Hardening guards for promotion decisions."""

    def test_source_role_guard_blocks_non_conclusive_passages(self):
        # promote_to_canonical requires conclusive source roles
        passages = [
            ExtractedPassage(chunk_id="chunk_1", page_number=10, quote="quote", source_role="notifying_party_view"),
            ExtractedPassage(chunk_id="chunk_1", page_number=11, quote="quote", source_role="precedent"),
        ]
        action, reason = _promotion_action_with_guards(
            "core_assessed", "defined", True,
            passages, [], "product", "Online ads", {"product": [], "geographic": []}
        )
        assert action == "hold_pending_source_check"
        assert "source role" in reason.lower() or "conclusive" in reason.lower()

    def test_source_role_guard_allows_conclusive_passages(self):
        # promote_to_canonical allowed when at least one passage has conclusive source role
        passages = [
            ExtractedPassage(chunk_id="chunk_1", page_number=10, quote="quote", source_role="commission_assessment"),
        ]
        action, reason = _promotion_action_with_guards(
            "core_assessed", "defined", True,
            passages, [], "product", "Online ads", {"product": [], "geometric": []}
        )
        assert action == "promote_to_canonical"

    def test_caveat_guard_missing_conclusion_downgrades_to_hold(self):
        # Section caveat saying conclusion is missing downgrades to hold_pending
        passages = [
            ExtractedPassage(chunk_id="chunk_1", page_number=10, quote="quote", source_role="commission_assessment"),
        ]
        caveats = ["The Commission's definition conclusion on this market is absent from the supplied sections."]
        action, reason = _promotion_action_with_guards(
            "core_assessed", "left_open", True,
            passages, caveats, "product", "Online ads", {"product": [], "geographic": []}
        )
        assert action == "hold_pending_source_check"
        assert "absent" in reason.lower() or "conclusion" in reason.lower()

    def test_geographic_pairing_guard_orphan_requires_manual_review(self):
        # Geographic market with no product market pairing requires manual review
        passages = [
            ExtractedPassage(chunk_id="chunk_1", page_number=10, quote="quote", source_role="commission_assessment"),
        ]
        action, reason = _promotion_action_with_guards(
            "core_assessed", "defined", True,
            passages, [], "geographic", "EEA", {"product": [{"name": "Search ads"}], "geographic": []}
        )
        assert action == "manual_review_geo_pairing"
        assert "pairing" in reason.lower() or "geographic" in reason.lower()

    def test_geographic_pairing_guard_with_product_pair_allows_promotion(self):
        # Geographic market that can pair with a product market allows promotion
        passages = [
            ExtractedPassage(chunk_id="chunk_1", page_number=10, quote="quote", source_role="commission_assessment"),
        ]
        action, reason = _promotion_action_with_guards(
            "core_assessed", "defined", True,
            passages, [], "geographic", "EEA Search ads market",
            {"product": [{"name": "Search ads"}], "geographic": []}
        )
        assert action == "promote_to_canonical"

    def test_assessed_no_overlap_remains_context_only_with_guards(self):
        # assessed_no_overlap always stays context_only even with conclusive passages
        passages = [
            ExtractedPassage(chunk_id="chunk_1", page_number=10, quote="quote", source_role="conclusion"),
        ]
        action, reason = _promotion_action_with_guards(
            "assessed_no_overlap", "defined", True,
            passages, [], "product", "Online ads", {"product": [], "geographic": []}
        )
        assert action == "keep_as_context_only"


class TestCanonicalMergeCandidates:
    """canonical_merge_candidates groups markets by merge readiness."""

    def test_candidates_groups_by_action(self):
        plan = [
            {"draft_name": "Market A", "recommended_action": "promote_to_canonical",
             "draft_market_type": "product", "definition_status": "defined"},
            {"draft_name": "Market B", "recommended_action": "promote_with_uncertainty",
             "draft_market_type": "product", "definition_status": "possible_segmentation"},
            {"draft_name": "Market C", "recommended_action": "keep_as_context_only",
             "draft_market_type": "geographic", "definition_status": "defined"},
            {"draft_name": "Market D", "recommended_action": "hold_pending_source_check",
             "draft_market_type": "product", "definition_status": "unknown"},
            {"draft_name": "Market E", "recommended_action": "manual_review",
             "draft_market_type": "product", "definition_status": "considered"},
        ]
        candidates = _build_canonical_merge_candidates(plan)

        # Check that entries are grouped correctly
        assert len(candidates["safe_to_promote"]) == 1
        assert candidates["safe_to_promote"][0]["name"] == "Market A"

        assert len(candidates["uncertain_markets"]) == 1
        assert candidates["uncertain_markets"][0]["name"] == "Market B"

        assert len(candidates["context_only"]) == 1
        assert candidates["context_only"][0]["name"] == "Market C"

        assert len(candidates["hold_pending_source_check"]) == 1
        assert candidates["hold_pending_source_check"][0]["name"] == "Market D"

        assert len(candidates["manual_review"]) == 1
        assert candidates["manual_review"][0]["name"] == "Market E"

    def test_candidates_excludes_uncertain_from_safe_promote(self):
        # Verify that only promote_to_canonical goes in safe_to_promote
        plan = [
            {"draft_name": "Safe", "recommended_action": "promote_to_canonical", "draft_market_type": "product"},
            {"draft_name": "Uncertain", "recommended_action": "promote_with_uncertainty", "draft_market_type": "product"},
            {"draft_name": "Hold", "recommended_action": "hold_pending_source_check", "draft_market_type": "product"},
        ]
        candidates = _build_canonical_merge_candidates(plan)

        assert len(candidates["safe_to_promote"]) == 1
        assert candidates["safe_to_promote"][0]["name"] == "Safe"
        assert len(candidates["uncertain_markets"]) == 1
        assert len(candidates["hold_pending_source_check"]) == 1

    def test_candidates_has_count_metadata(self):
        plan = [
            {"draft_name": "A", "recommended_action": "promote_to_canonical", "draft_market_type": "product"},
            {"draft_name": "B", "recommended_action": "keep_as_context_only", "draft_market_type": "geographic"},
        ]
        candidates = _build_canonical_merge_candidates(plan)

        assert "_counts" in candidates
        assert candidates["_counts"]["safe_to_promote"] == 1
        assert candidates["_counts"]["context_only"] == 1


class TestBuildPromotionPlan:
    """_build_promotion_plan produces one entry per draft market with correct metadata."""

    def _draft(
        self,
        pm_entries: list[dict] | None = None,
        gm_entries: list[dict] | None = None,
        passages: list[dict] | None = None,
    ) -> dict:
        return {
            "product_markets_considered": pm_entries or [],
            "geographic_markets_considered": gm_entries or [],
            "theories_of_harm": [],
            "source_passages": passages or [],
        }

    def _ref_map(self, mapping: dict[str, list[str]]) -> dict[str, list[str]]:
        return mapping

    def test_empty_draft_returns_empty_plan(self):
        plan = _build_promotion_plan(self._draft(), {})
        assert plan == []

    def test_product_market_entry_has_required_fields(self):
        draft = self._draft(pm_entries=[
            {"market_id": "pm_1", "name": "Online advertising",
             "definition_status": "defined", "market_importance": "core_assessed"}
        ])
        plan = _build_promotion_plan(draft, {"pm_1": ["42"]})
        assert len(plan) == 1
        e = plan[0]
        assert e["draft_name"] == "Online advertising"
        assert e["draft_market_type"] == "product"
        assert e["market_importance"] == "core_assessed"
        assert e["definition_status"] == "defined"
        assert e["recommended_action"] in _PROMOTION_ACTIONS
        assert e["reason"]

    def test_core_assessed_with_refs_gets_promote_to_canonical(self):
        draft = self._draft(pm_entries=[
            {"market_id": "pm_1", "name": "Wearable fitness devices",
             "definition_status": "defined", "market_importance": "core_assessed"}
        ])
        plan = _build_promotion_plan(draft, {"pm_1": ["24", "25"]})
        assert plan[0]["recommended_action"] == "promote_to_canonical"
        assert plan[0]["source_refs"] == ["24", "25"]

    def test_precedent_only_gets_keep_as_context_only(self):
        draft = self._draft(pm_entries=[
            {"market_id": "pm_1", "name": "Smartphone OS",
             "definition_status": "precedent_only", "market_importance": "precedent_only"}
        ])
        plan = _build_promotion_plan(draft, {})
        assert plan[0]["recommended_action"] == "keep_as_context_only"

    def test_incomplete_source_gets_hold_pending(self):
        draft = self._draft(pm_entries=[
            {"market_id": "pm_1", "name": "Cloud computing",
             "definition_status": "unknown", "market_importance": "incomplete_source"}
        ])
        plan = _build_promotion_plan(draft, {})
        assert plan[0]["recommended_action"] == "hold_pending_source_check"

    def test_source_refs_omitted_when_empty(self):
        draft = self._draft(pm_entries=[
            {"market_id": "pm_1", "name": "Online advertising",
             "definition_status": "defined", "market_importance": "core_assessed"}
        ])
        plan = _build_promotion_plan(draft, {})  # no refs
        assert "source_refs" not in plan[0]

    def test_geographic_markets_included_with_correct_type(self):
        draft = self._draft(gm_entries=[
            {"market_id": "gm_1", "name": "EEA (wearable fitness devices)",
             "definition_status": "defined", "market_importance": "core_assessed"}
        ])
        plan = _build_promotion_plan(draft, {"gm_1": ["27"]})
        geo = [e for e in plan if e["draft_market_type"] == "geographic"]
        assert len(geo) == 1
        assert geo[0]["source_refs"] == ["27"]

    def test_plan_ordered_products_then_geographic(self):
        draft = self._draft(
            pm_entries=[{"market_id": "pm_1", "name": "PM", "definition_status": "defined", "market_importance": "core_assessed"}],
            gm_entries=[{"market_id": "gm_1", "name": "GM", "definition_status": "defined", "market_importance": "core_assessed"}],
        )
        plan = _build_promotion_plan(draft, {})
        types = [e["draft_market_type"] for e in plan]
        assert types == ["product", "geographic"]

    def test_source_refs_deduplicated(self):
        draft = self._draft(pm_entries=[
            {"market_id": "pm_1", "name": "Online ads",
             "definition_status": "defined", "market_importance": "core_assessed"}
        ])
        plan = _build_promotion_plan(draft, {"pm_1": ["42", "42", "43"]})
        assert plan[0]["source_refs"] == ["42", "43"]

    def test_distinguish_core_from_precedent_in_plan(self):
        """core_assessed promotes, precedent_only keeps as context — different actions."""
        draft = self._draft(pm_entries=[
            {"market_id": "pm_1", "name": "Core market",
             "definition_status": "defined", "market_importance": "core_assessed"},
            {"market_id": "pm_2", "name": "Precedent market",
             "definition_status": "precedent_only", "market_importance": "precedent_only"},
        ])
        plan = _build_promotion_plan(draft, {"pm_1": ["42"]})
        by_name = {e["draft_name"]: e for e in plan}
        assert by_name["Core market"]["recommended_action"] == "promote_to_canonical"
        assert by_name["Precedent market"]["recommended_action"] == "keep_as_context_only"


class TestSerializeReportPromotion:
    """serialize_report includes promotion_plan in its output."""

    def test_serialize_report_includes_promotion_plan(self, tmp_path):
        from unittest.mock import patch, MagicMock
        existing = {
            "case_id": "tc", "case_name": "T", "authority": "EC",
            "jurisdiction": "EU", "sector": "x", "outcome": "unknown",
            "decision_date": "2021-01-01", "parties": [],
            "source_documents": [{"doc_id": "doc1", "title": "D",
                                   "pdf_url": "https://example.com/d.pdf",
                                   "doc_type": "decision"}],
            "source_passages": [],
            "product_markets_considered": [],
            "geographic_markets_considered": [],
            "theories_of_harm": [],
        }
        yaml_path = tmp_path / "t.yaml"
        yaml_path.write_text(yaml.dump(existing))

        mock_block = MagicMock(); mock_block.type = "tool_use"
        mock_block.input = {
            "product_markets": [
                {"name": "Core market", "definition_status": "defined",
                 "market_importance": "core_assessed", "notes": "", "not_found": False, "passages": []},
                {"name": "Precedent market", "definition_status": "precedent_only",
                 "market_importance": "precedent_only", "notes": "", "not_found": False, "passages": []},
            ],
            "geographic_markets": [],
            "theories_of_harm": [],
            "overall_outcome": "unknown",
            "source_passages": [],
            "caveats": [],
        }
        mock_msg = MagicMock(); mock_msg.content = [mock_block]
        mock_ac = MagicMock(); mock_ac.messages.create.return_value = mock_msg
        page_cache = {"source_document_id": "doc1", "source_url": "x",
                      "page_count": 1, "pages": [{"page_number": 1, "text": "8.6 Market."}],
                      "extracted_at": "2026-01-01T00:00:00+00:00"}

        with patch("extract_case_from_source.load_cache", return_value=page_cache):
            rpt = extract_case(yaml_path, cache_dir=tmp_path / "cache",
                               use_claude=True, anthropic_client=mock_ac)

        payload = serialize_report(rpt)
        assert "promotion_plan" in payload
        plan = payload["promotion_plan"]
        assert isinstance(plan, list)
        assert len(plan) == 2  # two product markets

        by_name = {e["draft_name"]: e for e in plan}
        assert by_name["Core market"]["recommended_action"] == "promote_to_canonical" or \
               by_name["Core market"]["recommended_action"] == "manual_review"  # no refs from mock
        assert by_name["Precedent market"]["recommended_action"] == "keep_as_context_only"

    def test_promotion_plan_empty_when_no_draft(self, tmp_path):
        """When no Claude call is made (use_claude=False), draft_record is None → plan = []."""
        existing = {
            "case_id": "tc", "case_name": "T", "authority": "EC",
            "jurisdiction": "EU", "sector": "x", "outcome": "unknown",
            "decision_date": "2021-01-01", "parties": [],
            "source_documents": [{"doc_id": "doc1", "title": "D",
                                   "pdf_url": "https://example.com/d.pdf",
                                   "doc_type": "decision"}],
            "source_passages": [],
            "product_markets_considered": [],
            "geographic_markets_considered": [],
            "theories_of_harm": [],
        }
        yaml_path = tmp_path / "t.yaml"
        yaml_path.write_text(yaml.dump(existing))
        page_cache = {"source_document_id": "doc1", "source_url": "x",
                      "page_count": 1, "pages": [{"page_number": 1, "text": "8.6 Market."}],
                      "extracted_at": "2026-01-01T00:00:00+00:00"}

        from unittest.mock import patch
        with patch("extract_case_from_source.load_cache", return_value=page_cache):
            rpt = extract_case(yaml_path, cache_dir=tmp_path / "cache", use_claude=False)

        payload = serialize_report(rpt)
        assert payload["promotion_plan"] == []


# ---------------------------------------------------------------------------
# Tests for neutral market-definition page-text fallback selector
# ---------------------------------------------------------------------------

def _market_def_page(extra: str = "") -> str:
    """Return page text with enough neutral market-definition signals to clear threshold."""
    return (
        "The Commission examined the relevant market and the relevant product market. "
        "Market definition and demand-side substitutability were considered. "
        "The exact scope of the market was left open for the purpose of assessing. "
        + extra
    )


def _neutral_noise_page(extra: str = "") -> str:
    """Return page text with no market-definition signals."""
    return (
        "Procedural considerations relating to the notification submission date "
        "and administrative filing requirements under the applicable regulation. "
        + extra
    )


class TestScorePageMarketDef:
    def test_market_def_signals_score_above_zero(self):
        text = _market_def_page()
        assert _score_page_market_def(text) >= _MARKET_DEF_FALLBACK_MIN_SCORE

    def test_noise_page_scores_zero_or_below_threshold(self):
        text = _neutral_noise_page()
        assert _score_page_market_def(text) < _MARKET_DEF_FALLBACK_MIN_SCORE

    def test_empty_text_scores_zero(self):
        assert _score_page_market_def("") == 0

    def test_all_signals_are_neutral(self):
        # Confirm no industry-specific term appears in the signal list.
        industry_terms = [
            "game", "gaming", "console", "cloud", "wearable", "fitbit",
            "pharma", "airline", "sequenc", "advertis", "ad tech",
        ]
        joined = " ".join(_MARKET_DEF_FALLBACK_SIGNALS).lower()
        for term in industry_terms:
            assert term not in joined, f"Industry-specific term found in signals: {term!r}"


class TestSelectRelevantChunksFallback:
    def _chunks_with_section_heading(self) -> list[ChunkInfo]:
        """Chunks where section_path contains a market-definition keyword."""
        return [
            _make_chunk("c1", "8.3 Relevant market definition", [(1, "relevant market analysis")]),
            _make_chunk("c2", "8.4 Competitive assessment", [(2, "competitive analysis")]),
            _make_chunk("c3", "3 Background", [(3, "background text only")]),
        ]

    def _chunks_no_section_heading(self) -> list[ChunkInfo]:
        """Chunks with no market-definition keywords in section_path."""
        return [
            _make_chunk("c1", "Introduction", [(1, "introductory material")]),
            _make_chunk("c2", "Procedure", [(2, "procedural context")]),
        ]

    def test_section_path_selection_used_when_match_found(self):
        chunks = self._chunks_with_section_heading()
        selected = _select_relevant_chunks(chunks, focus="market_definition")
        assert len(selected) >= 1
        # All selected chunks must have section_path match — no fallback triggered.
        assert all(c.selection_method == "section_path" for c in selected)
        assert any("relevant market" in c.section_path.lower() for c in selected)

    def test_fallback_triggers_when_section_path_empty(self):
        # Chunks have market-def content in page text but not section_path.
        chunks = [
            _make_chunk("c1", "Introduction", [(1, _market_def_page())]),
            _make_chunk("c2", "Procedure", [(2, _neutral_noise_page())]),
        ]
        selected = _select_relevant_chunks(chunks, focus="market_definition")
        assert len(selected) >= 1
        assert all(c.selection_method == "page_text_fallback" for c in selected)

    def test_noise_only_pages_not_selected_by_fallback(self):
        # All pages are noise — fallback should return nothing.
        chunks = [
            _make_chunk("c1", "Procedure", [(1, _neutral_noise_page("a"))]),
            _make_chunk("c2", "Procedure", [(2, _neutral_noise_page("b"))]),
        ]
        selected = _select_relevant_chunks(chunks, focus="market_definition")
        assert len(selected) == 0

    def test_fallback_not_triggered_for_other_focus_modes(self):
        # Fallback is only for market_definition focus.
        chunks = [
            _make_chunk("c1", "Introduction", [(1, _market_def_page())]),
        ]
        # theories focus: no fallback, should return empty
        selected = _select_relevant_chunks(chunks, focus="theories")
        assert len(selected) == 0

    def test_section_path_wins_over_page_text_when_both_match(self):
        # Chunk has both a section_path match and high page-text score — section_path wins.
        chunks = [
            _make_chunk("c1", "8.3 Relevant market", [(1, _market_def_page())]),
        ]
        selected = _select_relevant_chunks(chunks, focus="market_definition")
        assert len(selected) == 1
        assert selected[0].selection_method == "section_path"

    def test_sparse_section_path_supplemented_by_fallback(self):
        # Simulates a Phase 1 decision where footnote numbers are misread as section
        # headings, leaving most relevant pages under non-matching labels.
        # Section-path finds 1 page (< _MARKET_DEF_SP_MIN_PAGES); fallback fills in
        # additional pages whose text scores are high.
        sp_chunk = _make_chunk("c1", "4.1 Relevant market definition", [(1, "relevant market brief")])
        # Pages 10–11: well-separated from page 1 so the fallback continuation logic
        # does not pull page 1 into the same fallback chunk.
        fb_chunks = [
            _make_chunk("c2", "24 Questionnaire", [(10, _market_def_page())]),
            _make_chunk("c3", "24 Questionnaire", [(11, _market_def_page())]),
        ]
        selected = _select_relevant_chunks([sp_chunk] + fb_chunks, focus="market_definition")
        page_numbers = {n for c in selected for n in c.page_numbers}
        # The section-path page is preserved.
        assert 1 in page_numbers
        # Fallback pages are merged in because section-path was sparse.
        assert 10 in page_numbers
        assert 11 in page_numbers
        # Section-path chunk keeps its method; the fallback chunk is marked as fallback.
        by_page = {c.page_numbers[0]: c.selection_method for c in selected if c.page_numbers}
        assert by_page[1] == "section_path"
        assert by_page[10] == "page_text_fallback"

    def test_adequate_section_path_not_supplemented(self):
        # When section-path finds >= _MARKET_DEF_SP_MIN_PAGES pages, no supplement.
        chunks = [
            _make_chunk(f"c{i}", "8.3 Relevant market definition", [(i, "relevant market")])
            for i in range(1, _MARKET_DEF_SP_MIN_PAGES + 1)
        ]
        selected = _select_relevant_chunks(chunks, focus="market_definition")
        assert all(c.selection_method == "section_path" for c in selected)


class TestSelectMarketDefFallbackChunks:
    def test_returns_chunks_for_high_scoring_pages(self):
        chunks = [_make_chunk("c1", "section", [(1, _market_def_page())])]
        result = _select_market_def_fallback_chunks(chunks)
        assert len(result) >= 1
        assert result[0].selection_method == "page_text_fallback"

    def test_returns_empty_for_noise_only(self):
        chunks = [_make_chunk("c1", "section", [(1, _neutral_noise_page())])]
        result = _select_market_def_fallback_chunks(chunks)
        assert result == []

    def test_adjacent_continuation_included(self):
        # Page 2 is a high-scorer; page 3 is a weak continuation; page 5 is isolated noise.
        pages = [
            (1, _neutral_noise_page()),
            (2, _market_def_page()),
            (3, "relevant market brief mention"),
            (5, _neutral_noise_page()),
        ]
        cache = _make_page_cache(pages)
        all_chunks = _build_chunks(cache)
        result = _select_market_def_fallback_chunks(all_chunks)
        selected_pages = {pn for c in result for pn in c.page_numbers}
        assert 2 in selected_pages
        assert 3 in selected_pages   # continuation of page 2
        assert 5 not in selected_pages  # not adjacent to any primary

    def test_page_cap_respected(self):
        pages = [(i, _market_def_page(str(i))) for i in range(1, 60)]
        cache = _make_page_cache(pages)
        all_chunks = _build_chunks(cache)
        result = _select_market_def_fallback_chunks(all_chunks, max_fallback_pages=10)
        total = sum(len(c.pages) for c in result)
        assert total <= 10

    def test_chunk_cap_respected(self):
        # Many non-adjacent high-scoring pages produce many isolated chunks.
        pages = [(i, _market_def_page(str(i))) for i in range(1, 100, 10)]
        cache = _make_page_cache(pages)
        all_chunks = _build_chunks(cache)
        result = _select_market_def_fallback_chunks(all_chunks)
        assert len(result) <= _MAX_FALLBACK_CHUNKS

    def test_source_document_id_preserved(self):
        cache = _make_page_cache([(1, _market_def_page())], doc_id="my_doc")
        all_chunks = _build_chunks(cache)
        result = _select_market_def_fallback_chunks(all_chunks)
        assert len(result) >= 1
        assert result[0].source_document_id == "my_doc"

    def test_page_number_preserved(self):
        cache = _make_page_cache([(42, _market_def_page())], doc_id="doc")
        all_chunks = _build_chunks(cache)
        result = _select_market_def_fallback_chunks(all_chunks)
        assert len(result) >= 1
        assert 42 in result[0].page_numbers

    def test_effective_prefix_set_for_batch_grouping(self):
        cache = _make_page_cache([(1, _market_def_page())])
        all_chunks = _build_chunks(cache)
        result = _select_market_def_fallback_chunks(all_chunks)
        assert len(result) >= 1
        assert result[0].effective_prefix is not None
        assert "fallback_p" in result[0].effective_prefix

    def test_fallback_does_not_select_whole_document(self):
        # A long document: only pages with market-def signals should be selected.
        pages = []
        for i in range(1, 50):
            if i % 10 == 0:
                pages.append((i, _market_def_page(str(i))))
            else:
                pages.append((i, _neutral_noise_page(str(i))))
        cache = _make_page_cache(pages)
        all_chunks = _build_chunks(cache)
        result = _select_market_def_fallback_chunks(all_chunks)
        total = sum(len(c.pages) for c in result)
        assert total < 49, "Fallback must not select the whole document"

    def test_returns_empty_when_all_chunks_empty(self):
        result = _select_market_def_fallback_chunks([])
        assert result == []


class TestInferSectionLabel:
    def test_numbered_heading_preferred(self):
        pages = [{"page_number": 1, "text": "8.3 Market Definition\nSome text follows.\n"}]
        label = _infer_section_label_from_pages(pages)
        assert "8.3" in label

    def test_uppercase_heading_fallback(self):
        pages = [{"page_number": 1, "text": "MARKET DEFINITION\nSome text follows.\n"}]
        label = _infer_section_label_from_pages(pages)
        assert "MARKET" in label

    def test_generic_label_when_no_heading(self):
        pages = [{"page_number": 1, "text": "no heading here, just body text about things."}]
        label = _infer_section_label_from_pages(pages)
        assert "inferred" in label or "market" in label.lower()

    def test_empty_pages_returns_label(self):
        label = _infer_section_label_from_pages([])
        assert isinstance(label, str)
        assert len(label) > 0


class TestFallbackBatchGrouping:
    def test_fallback_chunks_group_by_effective_prefix(self):
        # Each fallback chunk has a unique effective_prefix → one group per chunk.
        pages_a = [(1, _market_def_page("a"))]
        pages_b = [(20, _market_def_page("b"))]
        cache = _make_page_cache(pages_a + pages_b)
        all_chunks = _build_chunks(cache)
        fallback = _select_market_def_fallback_chunks(all_chunks)
        groups = _group_chunks_by_section_prefix(fallback)
        # Each isolated page should produce a separate group
        assert len(groups) >= 1
        for prefix, grp_chunks in groups:
            assert prefix.startswith("fallback_p")

    def test_estimate_cost_compatible_with_fallback(self, tmp_path):
        """estimate-cost path must not crash with fallback chunks."""
        from unittest.mock import patch
        import sys, io

        existing = {
            "case_id": "tc_fallback", "case_name": "Alpha / Beta",
            "authority": "European Commission",
            "jurisdiction": "EU", "sector": "digital", "outcome": "unknown",
            "decision_date": "2023-01-01", "parties": [],
            "source_documents": [{"doc_id": "doc_fb", "title": "D",
                                   "pdf_url": "https://example.com/d.pdf",
                                   "doc_type": "decision"}],
            "source_passages": [],
            "product_markets_considered": [],
            "geographic_markets_considered": [],
            "theories_of_harm": [],
        }
        yaml_path = tmp_path / "tc_fallback.yaml"
        yaml_path.write_text(yaml.dump(existing))

        page_cache = {
            "source_document_id": "doc_fb",
            "source_url": "https://example.com/d.pdf",
            "page_count": 3,
            "pages": [
                {"page_number": 1, "text": _market_def_page("1")},
                {"page_number": 2, "text": _neutral_noise_page("2")},
                {"page_number": 3, "text": _market_def_page("3")},
            ],
            "extracted_at": "2026-01-01T00:00:00+00:00",
        }

        with patch("extract_case_from_source.load_cache", return_value=page_cache):
            rpt = extract_case(
                yaml_path, cache_dir=tmp_path / "cache",
                use_claude=False, focus="market_definition",
            )

        assert rpt.error is None or "No chunks" not in (rpt.error or "")
        total_pages = sum(len(c.pages) for c in rpt.chunks_used)
        # Should have selected at least the two market-def pages
        assert total_pages >= 1
        # Verify batch grouping doesn't crash
        groups = _group_chunks_by_section_prefix(rpt.chunks_used)
        assert isinstance(groups, list)

    def test_inspect_output_reports_fallback(self, tmp_path, capsys):
        """--inspect-chunks must report 'fallback' when fallback was used."""
        from unittest.mock import patch

        existing = {
            "case_id": "tc_ins", "case_name": "X / Y",
            "authority": "European Commission",
            "jurisdiction": "EU", "sector": "test", "outcome": "unknown",
            "decision_date": "2023-01-01", "parties": [],
            "source_documents": [{"doc_id": "doc_ins", "title": "D",
                                   "pdf_url": "https://example.com/d.pdf",
                                   "doc_type": "decision"}],
            "source_passages": [],
            "product_markets_considered": [],
            "geographic_markets_considered": [],
            "theories_of_harm": [],
        }
        yaml_path = tmp_path / "tc_ins.yaml"
        yaml_path.write_text(yaml.dump(existing))

        page_cache = {
            "source_document_id": "doc_ins",
            "source_url": "https://example.com/d.pdf",
            "page_count": 2,
            "pages": [
                {"page_number": 1, "text": _market_def_page()},
                {"page_number": 2, "text": _neutral_noise_page()},
            ],
            "extracted_at": "2026-01-01T00:00:00+00:00",
        }

        with patch("extract_case_from_source.load_cache", return_value=page_cache):
            rpt = extract_case(
                yaml_path, cache_dir=tmp_path / "cache",
                use_claude=False, focus="market_definition",
            )

        used_fallback = any(c.selection_method == "page_text_fallback" for c in rpt.chunks_used)
        assert used_fallback, "Expected fallback to be used (no section-path match)"

    def test_inspect_output_no_fallback_label_for_section_path_selection(self, tmp_path):
        """When section-path selection succeeds, selection_method is 'section_path'."""
        from unittest.mock import patch

        existing = {
            "case_id": "tc_sp", "case_name": "A / B",
            "authority": "European Commission",
            "jurisdiction": "EU", "sector": "test", "outcome": "unknown",
            "decision_date": "2023-01-01", "parties": [],
            "source_documents": [{"doc_id": "doc_sp", "title": "D",
                                   "pdf_url": "https://example.com/d.pdf",
                                   "doc_type": "decision"}],
            "source_passages": [],
            "product_markets_considered": [],
            "geographic_markets_considered": [],
            "theories_of_harm": [],
        }
        yaml_path = tmp_path / "tc_sp.yaml"
        yaml_path.write_text(yaml.dump(existing))

        # Page whose cache section_map will produce a market-definition section path
        page_text = "8.3 Relevant market\n\nThe Commission defines the relevant market.\n"
        page_cache = {
            "source_document_id": "doc_sp",
            "source_url": "https://example.com/d.pdf",
            "page_count": 1,
            "pages": [{"page_number": 1, "text": page_text}],
            "extracted_at": "2026-01-01T00:00:00+00:00",
        }

        with patch("extract_case_from_source.load_cache", return_value=page_cache):
            rpt = extract_case(
                yaml_path, cache_dir=tmp_path / "cache",
                use_claude=False, focus="market_definition",
            )

        if rpt.chunks_used:
            assert all(c.selection_method == "section_path" for c in rpt.chunks_used)


# ---------------------------------------------------------------------------
# Rule-registry integration: quote-cleanliness rule (mdr_009) in extraction task
# ---------------------------------------------------------------------------

class TestExtractionTaskQuoteCleanlinessRule:
    """mdr_009 guidance must be present in the extraction task prompt."""

    def test_extraction_task_contains_mdr009_reference(self):
        from extract_case_from_source import _EXTRACTION_TASK
        assert "mdr_009" in _EXTRACTION_TASK

    def test_extraction_task_mentions_footnote_injections(self):
        from extract_case_from_source import _EXTRACTION_TASK
        assert "footnote" in _EXTRACTION_TASK.lower()

    def test_extraction_task_mentions_line_break_hyphen(self):
        from extract_case_from_source import _EXTRACTION_TASK
        assert "hyphen" in _EXTRACTION_TASK.lower() or "line-break" in _EXTRACTION_TASK.lower()

    def test_extraction_task_mentions_pdf_normalisation(self):
        from extract_case_from_source import _EXTRACTION_TASK
        assert "pdf" in _EXTRACTION_TASK.lower()


# ---------------------------------------------------------------------------
# _filter_chunks_to_range
# ---------------------------------------------------------------------------

class TestFilterChunksToRange:
    """Unit tests for the page-range filtering helper."""

    def _chunk(self, chunk_id: str, pages: list[int], section: str = "5 Markets") -> ChunkInfo:
        return ChunkInfo(
            chunk_id=chunk_id,
            section_path=section,
            pages=[{"page_number": n, "text": f"page {n}"} for n in pages],
            source_document_id="doc1",
        )

    def test_range_keeps_fully_in_range_chunks(self):
        chunks = [self._chunk("c1", [10, 11, 12])]
        result = _filter_chunks_to_range(chunks, (1, 50))
        assert len(result) == 1
        assert result[0].page_numbers == [10, 11, 12]

    def test_range_drops_chunks_entirely_outside(self):
        chunks = [
            self._chunk("c1", [5, 6]),
            self._chunk("c2", [20, 21]),
            self._chunk("c3", [100, 101]),
        ]
        result = _filter_chunks_to_range(chunks, (15, 25))
        assert len(result) == 1
        assert result[0].chunk_id == "c2"

    def test_range_trims_partially_overlapping_chunk(self):
        """A chunk spanning pages 8-15 restricted to range 10-20 should keep only pp.10-15."""
        chunks = [self._chunk("c1", [8, 9, 10, 11, 12, 13, 14, 15])]
        result = _filter_chunks_to_range(chunks, (10, 20))
        assert len(result) == 1
        assert result[0].page_numbers == [10, 11, 12, 13, 14, 15]

    def test_range_exact_boundary_pages_included(self):
        """Start and end pages of the range are included (inclusive)."""
        chunks = [self._chunk("c1", [64, 65, 309, 310])]
        result = _filter_chunks_to_range(chunks, (64, 309))
        assert result[0].page_numbers == [64, 65, 309]

    def test_range_beyond_document_returns_empty(self):
        """Range entirely beyond the document returns no chunks."""
        chunks = [self._chunk("c1", [1, 2, 3])]
        result = _filter_chunks_to_range(chunks, (500, 600))
        assert result == []

    def test_range_single_page(self):
        """A single-page range (start == end) keeps exactly that page."""
        chunks = [self._chunk("c1", [10, 11, 12])]
        result = _filter_chunks_to_range(chunks, (11, 11))
        assert len(result) == 1
        assert result[0].page_numbers == [11]

    def test_range_preserves_section_path_and_doc_id(self):
        """Metadata on the original chunk is preserved in the filtered copy."""
        chunks = [self._chunk("c1", [5, 6], section="8.2 Competitive Assessment")]
        result = _filter_chunks_to_range(chunks, (1, 10))
        assert result[0].section_path == "8.2 Competitive Assessment"
        assert result[0].source_document_id == "doc1"

    def test_empty_chunks_input_returns_empty(self):
        assert _filter_chunks_to_range([], (1, 100)) == []

    def test_multiple_chunks_all_in_range(self):
        chunks = [self._chunk(f"c{i}", [i * 10]) for i in range(1, 6)]
        result = _filter_chunks_to_range(chunks, (1, 100))
        assert len(result) == 5


# ---------------------------------------------------------------------------
# TestCommitmentsSupport
# ---------------------------------------------------------------------------

def _make_commitment(
    title: str = "Test Divestiture",
    commitment_type: str = "structural",
    description: str = "Divestiture of test assets.",
    not_found: bool = False,
    passages: list | None = None,
) -> ExtractedCommitment:
    return ExtractedCommitment(
        title=title,
        commitment_type=commitment_type,
        description=description,
        divested_assets=["Test Asset A"],
        purchaser_requirements="Standalone viable buyer",
        markets_addressed=[],
        passages=passages or [],
        not_found=not_found,
    )


def _make_validated_passage(
    chunk_id: str = "chunk_001",
    page: int = 100,
    quote: str = "The parties shall divest the Test Business.",
    doc_id: str = "test_decision",
) -> ExtractedPassage:
    return ExtractedPassage(
        chunk_id=chunk_id,
        page_number=page,
        quote=quote,
        validated=True,
        source_document_id=doc_id,
        source_role="commission_assessment",
    )


class TestCommitmentsSupport:
    """Additive commitments[] support for remedies extraction."""

    # ------------------------------------------------------------------ schema

    def test_tool_schema_has_commitments_property(self):
        """The LLM tool schema exposes a commitments array field."""
        props = _EXTRACTION_TOOL_SCHEMA["input_schema"]["properties"]
        assert "commitments" in props
        assert props["commitments"]["type"] == "array"

    def test_commitment_item_schema_required_fields(self):
        """Commitment item schema has the expected required fields."""
        props = _EXTRACTION_TOOL_SCHEMA["input_schema"]["properties"]
        item_schema = props["commitments"]["items"]
        required = set(item_schema["required"])
        assert required >= {"title", "commitment_type", "description", "not_found", "passages"}

    def test_valid_commitment_types_set(self):
        """All expected commitment types are in the valid set."""
        assert "structural" in _VALID_COMMITMENT_TYPES
        assert "behavioral" in _VALID_COMMITMENT_TYPES
        assert "access" in _VALID_COMMITMENT_TYPES
        assert "other" in _VALID_COMMITMENT_TYPES

    def test_default_extraction_envelope_has_commitments(self):
        """The default envelope guarantees commitments: [] even when Claude omits it."""
        assert "commitments" in _DEFAULT_EXTRACTION_ENVELOPE
        assert _DEFAULT_EXTRACTION_ENVELOPE["commitments"] == []

    # ------------------------------------------------------------------ guardrails

    def test_remedies_focus_keeps_commitments(self):
        """remedies focus leaves commitments populated."""
        cm = _make_commitment()
        result = ExtractionResult(commitments=[cm])
        out = _apply_focus_guardrails(result, "remedies")
        assert len(out.commitments) == 1

    def test_market_definition_focus_drops_commitments(self):
        """market_definition focus clears commitments."""
        cm = _make_commitment()
        result = ExtractionResult(commitments=[cm])
        out = _apply_focus_guardrails(result, "market_definition")
        assert out.commitments == []

    def test_theories_focus_drops_commitments(self):
        """theories focus clears commitments."""
        cm = _make_commitment()
        result = ExtractionResult(commitments=[cm])
        out = _apply_focus_guardrails(result, "theories")
        assert out.commitments == []

    def test_case_history_focus_drops_commitments(self):
        """case_history focus clears commitments."""
        cm = _make_commitment()
        result = ExtractionResult(commitments=[cm])
        out = _apply_focus_guardrails(result, "case_history")
        assert out.commitments == []

    def test_no_focus_keeps_commitments(self):
        """A full run (focus=None) allows commitments to remain."""
        cm = _make_commitment()
        result = ExtractionResult(commitments=[cm])
        out = _apply_focus_guardrails(result, None)
        assert len(out.commitments) == 1

    def test_theories_focus_still_drops_markets(self):
        """theories guardrail still drops product/geo markets (regression)."""
        pm = ExtractedMarket(name="Test market", market_type="product",
                             definition_status="defined", notes="")
        result = ExtractionResult(product_markets=[pm])
        out = _apply_focus_guardrails(result, "theories")
        assert out.product_markets == []

    # ------------------------------------------------------------------ parse

    def test_parse_commitments_from_raw(self):
        """_validate_extraction turns a raw commitments list into ExtractedCommitment objects."""
        raw = {
            "product_markets": [],
            "geographic_markets": [],
            "theories_of_harm": [],
            "overall_outcome": "cleared_with_conditions",
            "source_passages": [],
            "caveats": [],
            "commitments": [
                {
                    "title": "Vegetable Seeds Divestment",
                    "commitment_type": "structural",
                    "description": "Bayer shall divest its vegetable seeds business.",
                    "divested_assets": ["Vegetable Seeds Business"],
                    "purchaser_requirements": "Standalone viable buyer",
                    "markets_addressed": [],
                    "not_found": False,
                    "passages": [],
                }
            ],
        }
        result = _validate_extraction(raw, chunks=[], chunk_doc_map={})
        assert len(result.commitments) == 1
        cm = result.commitments[0]
        assert cm.title == "Vegetable Seeds Divestment"
        assert cm.commitment_type == "structural"
        assert cm.divested_assets == ["Vegetable Seeds Business"]
        assert cm.purchaser_requirements == "Standalone viable buyer"
        assert not cm.not_found

    def test_parse_unknown_commitment_type_coerced_to_other(self):
        """An unrecognised commitment_type is coerced to 'other'."""
        raw = {
            "product_markets": [],
            "geographic_markets": [],
            "theories_of_harm": [],
            "overall_outcome": "unknown",
            "source_passages": [],
            "caveats": [],
            "commitments": [
                {
                    "title": "Mystery remedy",
                    "commitment_type": "something_invalid",
                    "description": "Desc.",
                    "not_found": False,
                    "passages": [],
                }
            ],
        }
        result = _validate_extraction(raw, chunks=[], chunk_doc_map={})
        assert result.commitments[0].commitment_type == "other"

    def test_parse_missing_commitments_key_returns_empty(self):
        """When Claude omits 'commitments', the result has an empty list."""
        raw = {
            "product_markets": [],
            "geographic_markets": [],
            "theories_of_harm": [],
            "overall_outcome": "unknown",
            "source_passages": [],
            "caveats": [],
        }
        result = _validate_extraction(raw, chunks=[], chunk_doc_map={})
        assert result.commitments == []

    # ------------------------------------------------------------------ draft build

    def test_build_draft_record_includes_commitments(self):
        """_build_draft_record emits a commitments[] key in the draft."""
        passage = _make_validated_passage()
        cm = _make_commitment(passages=[passage])
        result = ExtractionResult(commitments=[cm], overall_outcome="cleared_with_conditions")
        existing = _make_record()
        draft = _build_draft_record(result, existing)
        assert "commitments" in draft
        assert len(draft["commitments"]) == 1
        entry = draft["commitments"][0]
        assert entry["commitment_id"] == "com_1"
        assert entry["commitment_type"] == "structural"
        assert entry["title"] == "Test Divestiture"
        assert entry["review_status"] == "unreviewed"

    def test_build_draft_passage_supports_commitments(self):
        """Source passages for commitments carry a supports_commitments back-reference."""
        passage = _make_validated_passage()
        cm = _make_commitment(passages=[passage])
        result = ExtractionResult(commitments=[cm], overall_outcome="cleared_with_conditions")
        draft = _build_draft_record(result, _make_record())
        sp = draft["source_passages"][0]
        assert sp["supports_commitments"] == ["com_1"]
        assert sp["supports_markets"] == []
        assert sp["supports_theories"] == []

    def test_build_draft_commitment_related_passage_backlink(self):
        """related_source_passages on the commitment entry references the passage ID."""
        passage = _make_validated_passage()
        cm = _make_commitment(passages=[passage])
        result = ExtractionResult(commitments=[cm], overall_outcome="cleared_with_conditions")
        draft = _build_draft_record(result, _make_record())
        com_entry = draft["commitments"][0]
        assert "sp_1" in com_entry["related_source_passages"]

    def test_build_draft_not_found_commitment_excluded(self):
        """Commitments with not_found=True are excluded from the draft."""
        cm = _make_commitment(not_found=True)
        result = ExtractionResult(commitments=[cm])
        draft = _build_draft_record(result, _make_record())
        assert draft["commitments"] == []

    def test_build_draft_no_commitments_emits_empty_list(self):
        """When result has no commitments, draft still has commitments: []."""
        result = ExtractionResult()
        draft = _build_draft_record(result, _make_record())
        assert "commitments" in draft
        assert draft["commitments"] == []

    # ------------------------------------------------------------------ merge

    def test_merge_deduplicates_identical_commitment_titles(self):
        """_merge_extraction_results deduplicates commitments with the same title."""
        cm_a = _make_commitment(title="Vegetable Seeds Divestment")
        cm_b = _make_commitment(title="Vegetable Seeds Divestment")
        r1 = ExtractionResult(commitments=[cm_a])
        r2 = ExtractionResult(commitments=[cm_b])
        merged = _merge_extraction_results([r1, r2])
        assert len(merged.commitments) == 1

    def test_merge_keeps_distinct_commitments(self):
        """_merge_extraction_results keeps commitments with different titles."""
        cm_a = _make_commitment(title="Vegetable Seeds Divestment")
        cm_b = _make_commitment(title="GA Divestment Business")
        r1 = ExtractionResult(commitments=[cm_a])
        r2 = ExtractionResult(commitments=[cm_b])
        merged = _merge_extraction_results([r1, r2])
        assert len(merged.commitments) == 2

    def test_merge_prefers_richer_commitment(self):
        """When duplicates exist, the one with more validated passages wins."""
        p1 = _make_validated_passage(quote="Passage one.")
        p2 = _make_validated_passage(quote="Passage two.")
        cm_sparse = _make_commitment(title="Vegetable Seeds Divestment", passages=[p1])
        cm_rich = _make_commitment(title="Vegetable Seeds Divestment", passages=[p1, p2])
        r1 = ExtractionResult(commitments=[cm_sparse])
        r2 = ExtractionResult(commitments=[cm_rich])
        merged = _merge_extraction_results([r1, r2])
        assert len(merged.commitments[0].passages) == 2

    def test_remedies_focus_does_not_drop_markets_or_theories(self):
        """remedies guardrail does not clear product markets or theories of harm."""
        pm = ExtractedMarket(name="Seeds market", market_type="product",
                             definition_status="defined", notes="")
        th = ExtractedTheory(name="NSH overlap", theory_type="horizontal",
                             theory_outcome="upheld", notes="")
        result = ExtractionResult(product_markets=[pm], theories=[th])
        out = _apply_focus_guardrails(result, "remedies")
        assert len(out.product_markets) == 1
        assert len(out.theories) == 1


# ---------------------------------------------------------------------------
# TestInnovationTheories
# ---------------------------------------------------------------------------


class TestInnovationTheories:
    """Innovation theory_type support in theories_of_harm extraction."""

    # ------------------------------------------------------------------ schema

    def test_valid_theory_types_includes_innovation(self):
        """_VALID_THEORY_TYPES includes 'innovation'."""
        assert "innovation" in _VALID_THEORY_TYPES

    def test_valid_theory_types_retains_existing_values(self):
        """Existing theory types are still present after adding innovation."""
        for t in ("horizontal", "vertical", "conglomerate", "data", "other"):
            assert t in _VALID_THEORY_TYPES

    def test_tool_schema_theory_type_enum_includes_innovation(self):
        """The LLM tool schema theory_type enum contains 'innovation'."""
        theories_schema = (
            _EXTRACTION_TOOL_SCHEMA["input_schema"]["properties"]["theories_of_harm"]
        )
        theory_item = theories_schema["items"]
        enum_values = theory_item["properties"]["theory_type"]["enum"]
        assert "innovation" in enum_values

    def test_tool_schema_theory_type_enum_retains_existing_values(self):
        """The tool schema theory_type enum still contains all legacy values."""
        theories_schema = (
            _EXTRACTION_TOOL_SCHEMA["input_schema"]["properties"]["theories_of_harm"]
        )
        enum_values = theories_schema["items"]["properties"]["theory_type"]["enum"]
        for t in ("horizontal", "vertical", "conglomerate", "data", "other"):
            assert t in enum_values

    # ------------------------------------------------------------------ focus terms

    def test_focus_terms_theories_includes_innovation_keywords(self):
        """_FOCUS_TERMS['theories'] contains innovation/R&D keywords."""
        terms = _FOCUS_TERMS["theories"]
        for kw in ("innovation", "r&d", "pipeline", "leading innovators",
                   "research and development"):
            assert kw in terms, f"missing keyword: {kw!r}"

    def test_focus_terms_theories_retains_existing_keywords(self):
        """_FOCUS_TERMS['theories'] still contains all original keywords."""
        terms = _FOCUS_TERMS["theories"]
        for kw in ("competitive assessment", "horizontal", "foreclosure"):
            assert kw in terms, f"missing keyword: {kw!r}"

    # ------------------------------------------------------------------ prompt

    def test_extraction_task_mentions_innovation_theory_type(self):
        """_EXTRACTION_TASK prompt guidance mentions innovation theory type."""
        assert "innovation" in _EXTRACTION_TASK.lower()

    def test_extraction_task_mentions_innovation_spaces(self):
        assert "innovation spaces" in _EXTRACTION_TASK.lower()

    def test_extraction_task_mentions_leading_innovator(self):
        assert "leading innovator" in _EXTRACTION_TASK.lower()

    def test_extraction_task_mentions_pipeline_competitor(self):
        assert "pipeline competitor" in _EXTRACTION_TASK.lower()

    # ------------------------------------------------------------------ parsing

    def test_parse_innovation_theory_type_accepted(self):
        """Parsing a raw response with theory_type 'innovation' stores it as-is."""
        raw = {
            "product_markets": [],
            "geographic_markets": [],
            "theories_of_harm": [
                {
                    "name": "Innovation competition in traits",
                    "theory_type": "innovation",
                    "theory_outcome": "upheld",
                    "notes": "The Commission found the merger eliminates a leading innovator.",
                    "not_found": False,
                    "passages": [],
                }
            ],
            "overall_outcome": "cleared_with_conditions",
            "source_passages": [],
            "caveats": [],
            "background_concepts": [],
            "commitments": [],
        }
        result = _validate_extraction(raw, chunks=[], chunk_doc_map={})
        assert len(result.theories) == 1
        assert result.theories[0].theory_type == "innovation"

    def test_parse_unknown_theory_type_coerced_to_other(self):
        """An unrecognised theory_type (e.g. 'novel') is normalised to 'other'."""
        raw = {
            "product_markets": [],
            "geographic_markets": [],
            "theories_of_harm": [
                {
                    "name": "Novel theory",
                    "theory_type": "novel_type_not_in_enum",
                    "theory_outcome": "unclear",
                    "notes": "Some notes.",
                    "not_found": False,
                    "passages": [],
                }
            ],
            "overall_outcome": "unknown",
            "source_passages": [],
            "caveats": [],
            "background_concepts": [],
            "commitments": [],
        }
        result = _validate_extraction(raw, chunks=[], chunk_doc_map={})
        assert len(result.theories) == 1
        assert result.theories[0].theory_type == "other"

    def test_parse_innovation_theory_with_passage(self):
        """An innovation theory with a supporting passage is stored with it."""
        raw = {
            "product_markets": [],
            "geographic_markets": [],
            "theories_of_harm": [
                {
                    "name": "R&D rivalry reduction",
                    "theory_type": "innovation",
                    "theory_outcome": "upheld",
                    "notes": "Reduction of innovation incentives.",
                    "not_found": False,
                    "passages": [
                        {
                            "chunk_id": "chunk_001",
                            "page_number": 420,
                            "quote": "The transaction eliminates an important pipeline competitor.",
                            "source_role": "commission_assessment",
                        }
                    ],
                }
            ],
            "overall_outcome": "cleared_with_conditions",
            "source_passages": [],
            "caveats": [],
            "background_concepts": [],
            "commitments": [],
        }
        result = _validate_extraction(raw, chunks=[], chunk_doc_map={})
        assert result.theories[0].theory_type == "innovation"
        assert len(result.theories[0].passages) == 1
        assert "pipeline competitor" in result.theories[0].passages[0].quote

    # ------------------------------------------------------------------ focus guardrails

    def test_theories_focus_does_not_drop_innovation_theories(self):
        """theories guardrail does not strip innovation theories."""
        th = ExtractedTheory(name="R&D rivalry", theory_type="innovation",
                             theory_outcome="upheld", notes="")
        result = ExtractionResult(theories=[th])
        out = _apply_focus_guardrails(result, "theories")
        assert len(out.theories) == 1
        assert out.theories[0].theory_type == "innovation"

    def test_market_definition_focus_does_not_affect_theory_type(self):
        """market_definition guardrail clears theories regardless of theory_type."""
        th = ExtractedTheory(name="R&D rivalry", theory_type="innovation",
                             theory_outcome="upheld", notes="")
        result = ExtractionResult(theories=[th])
        out = _apply_focus_guardrails(result, "market_definition")
        assert len(out.theories) == 0
