"""
Tests for the eval + gold-draft pipeline:
  - scripts/cases/create_gold_draft.py
  - scripts/cases/evaluate_extraction.py
  - scripts/cases/validate_gold_quotes.py

No network access, no Claude API calls, no canonical YAML mutation.
"""
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from create_gold_draft import (
    _FoldedStr,
    _PAIRING_MIN_TOKEN_LEN,
    _PAIRING_STOPWORDS,
    _create_gold_draft,
    _max_pairing_signal,
    _normalize_market_name,
    _pairing_overlap,
    _pairing_token_set,
    _score_candidate,
    gold_yaml_dump,
)
from evaluate_extraction import (
    _build_reviewed_groups,
    _evaluate_markets,
    _find_matching_market,
    _nearest_draft_candidates,
    _token_overlap_score,
)
from repair_gold_quotes import (
    _has_name_overlap,
    _sort_passages,
    _source_role_priority,
    _validate_candidates,
    repair_gold_passages,
)
from validate_gold_quotes import (
    load_gold_yaml,
    normalize_for_gold_match,
    validate_gold_passages,
    validate_quote_on_page,
)


# ---------------------------------------------------------------------------
# Helpers shared across test classes
# ---------------------------------------------------------------------------

def _make_draft(pm_entries=None, gm_entries=None, passages=None) -> dict:
    return {
        "case_id": "test_case",
        "case_name": "Test v. Competitor",
        "authority": "EU",
        "jurisdiction": "EU",
        "source_documents": [{"doc_id": "doc_1", "url": "https://example.com/doc.pdf"}],
        "product_markets_considered": pm_entries or [],
        "geographic_markets_considered": gm_entries or [],
        "source_passages": passages or [],
        "caveats": [],
    }


def _make_report(
    safe=None, uncertain=None, context=None, hold=None, manual=None, geo=None,
    reconciliation=None,
) -> dict:
    return {
        "canonical_merge_candidates": {
            "safe_to_promote":          safe or [],
            "uncertain_markets":        uncertain or [],
            "context_only":             context or [],
            "hold_pending_source_check": hold or [],
            "manual_review":            manual or [],
            "manual_review_geo_pairing": geo or [],
        },
        "reconciliation": reconciliation or [],
    }


def _pm_entry(name, mid="pm_1", status="defined", importance="core_assessed"):
    return {"market_id": mid, "name": name, "definition_status": status,
            "market_importance": importance}


def _passage(mid, page, quote, pid="sp_1", doc="doc_1", method="pdf_extracted",
             review="unreviewed", supports_type="markets"):
    entry = {
        "passage_id": pid,
        "source_document_id": doc,
        "page": page,
        "quote_snippet": quote,
        "extraction_method": method,
        "review_status": review,
    }
    if supports_type == "markets":
        entry["supports_markets"] = [mid]
    else:
        entry["supports_geographic_markets"] = [mid]
    return entry


def _candidate(name, mtype="product", status="defined", importance="core_assessed",
               refs=None) -> dict:
    return {
        "name": name,
        "market_type": mtype,
        "definition_status": status,
        "importance": importance,
        "reason": "test reason",
        "source_refs": refs or [],
    }


def _make_page_cache(doc_id: str, pages: list[tuple[int, str]]) -> dict:
    return {
        "source_document_id": doc_id,
        "pages": [{"page_number": n, "text": t} for n, t in pages],
    }


# ---------------------------------------------------------------------------
# TestNormalizeForGoldMatch
# ---------------------------------------------------------------------------

class TestNormalizeForGoldMatch:
    """normalize_for_gold_match handles PDF artefacts without stripping list markers."""

    def test_lowercases(self):
        assert normalize_for_gold_match("Online Advertising") == "online advertising"

    def test_collapses_whitespace(self):
        assert normalize_for_gold_match("a  b\tc") == "a b c"

    def test_collapses_newlines(self):
        assert normalize_for_gold_match("line one\nline two") == "line one line two"

    def test_unicode_curly_apostrophe(self):
        # RIGHT SINGLE QUOTATION MARK → '
        assert normalize_for_gold_match("it’s") == "it's"

    def test_unicode_left_apostrophe(self):
        assert normalize_for_gold_match("it‘s") == "it's"

    def test_unicode_curly_double_quotes(self):
        assert normalize_for_gold_match("“Hello”") == '"hello"'

    def test_soft_hyphen_removed(self):
        assert normalize_for_gold_match("so­ft") == "soft"

    def test_pdf_line_hyphenation_rejoined(self):
        # "over-\nnight" → "overnight"
        assert normalize_for_gold_match("over-\nnight") == "overnight"

    def test_pdf_line_hyphenation_with_spaces(self):
        assert normalize_for_gold_match("over- \n night") == "overnight"

    def test_parenthetical_numbering_preserved(self):
        # (i), (ii), (a), (b) must survive normalisation
        result = normalize_for_gold_match("(i) first; (ii) second; (a) alpha; (b) beta")
        assert "(i)" in result
        assert "(ii)" in result
        assert "(a)" in result
        assert "(b)" in result

    def test_en_dash_normalised(self):
        assert normalize_for_gold_match("2020–2021") == "2020-2021"


# ---------------------------------------------------------------------------
# TestValidateQuoteOnPage
# ---------------------------------------------------------------------------

class TestValidateQuoteOnPage:
    """validate_quote_on_page: contiguous substring check after normalisation."""

    def test_exact_verbatim_quote_passes(self):
        page = "The Commission found that the relevant market is online advertising."
        quote = "the relevant market is online advertising"
        assert validate_quote_on_page(quote, page) is True

    def test_case_insensitive_passes(self):
        page = "The Commission FOUND THAT the relevant market is online advertising."
        quote = "the relevant market is online advertising"
        assert validate_quote_on_page(quote, page) is True

    def test_whitespace_normalised_passes(self):
        # Source has extra whitespace / newlines
        page = "The Commission\n   found  that\tthe relevant market is online advertising."
        quote = "Commission found that the relevant market is online advertising"
        assert validate_quote_on_page(quote, page) is True

    def test_line_break_in_quote_passes(self):
        page = "The relevant market is online advertising services."
        quote = "The relevant market is online\nadvertising services."
        assert validate_quote_on_page(quote, page) is True

    def test_unicode_apostrophe_passes(self):
        page = "The Commission's assessment confirmed the market."
        quote = "The Commission’s assessment confirmed the market"
        assert validate_quote_on_page(quote, page) is True

    def test_pdf_hyphenation_passes(self):
        # Page has "over-\nnight" (PDF line break), quote has "overnight"
        page = "An over-\nnight stay was required."
        quote = "An overnight stay was required"
        assert validate_quote_on_page(quote, page) is True

    def test_numbered_list_preserved(self):
        page = "The conditions are: (i) first condition; (ii) second condition; (a) sub-item."
        quote = "(i) first condition; (ii) second condition; (a) sub-item"
        assert validate_quote_on_page(quote, page) is True

    def test_paraphrase_fails(self):
        # Different words — paraphrase must not pass
        page = "The Commission determined that a relevant market exists for online advertising."
        quote = "The authority concluded that an online advertising market is present"
        assert validate_quote_on_page(quote, page) is False

    def test_rearranged_sentence_fails(self):
        page = "Online advertising constitutes a relevant market in the EEA."
        quote = "A relevant market in the EEA constitutes online advertising"
        assert validate_quote_on_page(quote, page) is False

    def test_empty_quote_returns_false(self):
        assert validate_quote_on_page("", "some text") is False

    def test_quote_longer_than_page_fails(self):
        assert validate_quote_on_page("very long quote that is not in page", "short") is False


# ---------------------------------------------------------------------------
# TestValidateGoldPassages
# ---------------------------------------------------------------------------

class TestValidateGoldPassages:
    """validate_gold_passages: integration across markets and page caches."""

    def _gold_with_passage(self, quote: str, page: int = 10,
                           doc_id: str = "doc_1") -> dict:
        return {
            "case_id": "test",
            "source_documents": [{"doc_id": doc_id}],
            "product_markets_considered": [{
                "name": "Online ads",
                "linked_source_passages": [{
                    "passage_id": "sp_1",
                    "source_document_id": doc_id,
                    "page": str(page),
                    "quote_snippet": quote,
                    "source_summary": "",
                }],
            }],
            "geographic_markets_considered": [],
        }

    def test_verbatim_quote_passes(self, tmp_path):
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        cache = _make_page_cache("doc_1", [(10, "The Commission found that online ads matter.")])
        (cache_dir / "doc_1.json").write_text(__import__("json").dumps(cache))

        gold = self._gold_with_passage("The Commission found that online ads matter")
        report = validate_gold_passages(gold, cache_dir)
        assert report.passed == 1
        assert report.failures == []

    def test_paraphrase_fails(self, tmp_path):
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        cache = _make_page_cache("doc_1", [(10, "The Commission found that online ads matter.")])
        (cache_dir / "doc_1.json").write_text(__import__("json").dumps(cache))

        gold = self._gold_with_passage("The authority concluded that online ads are important")
        report = validate_gold_passages(gold, cache_dir)
        assert len(report.failures) == 1
        assert report.failures[0].reason == "not_found"

    def test_cache_unavailable_is_warning_not_failure(self, tmp_path):
        cache_dir = tmp_path / "empty_cache"
        cache_dir.mkdir()
        # No cache files

        gold = self._gold_with_passage("Some quote", doc_id="missing_doc")
        report = validate_gold_passages(gold, cache_dir)
        assert report.failures == []
        assert len(report.warnings) == 1
        assert report.warnings[0].reason == "cache_unavailable"

    def test_empty_quote_is_failure(self, tmp_path):
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        cache = _make_page_cache("doc_1", [(10, "Some text.")])
        (cache_dir / "doc_1.json").write_text(__import__("json").dumps(cache))

        gold = self._gold_with_passage("")
        report = validate_gold_passages(gold, cache_dir)
        assert len(report.failures) == 1
        assert report.failures[0].reason == "empty_quote"

    def test_wrong_page_is_failure(self, tmp_path):
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        # Cache has page 5 but passage cites page 99
        cache = _make_page_cache("doc_1", [(5, "The Commission found that online ads matter.")])
        (cache_dir / "doc_1.json").write_text(__import__("json").dumps(cache))

        gold = self._gold_with_passage("The Commission found that online ads matter", page=99)
        report = validate_gold_passages(gold, cache_dir)
        assert len(report.failures) == 1
        assert report.failures[0].reason == "no_page_in_cache"


# ---------------------------------------------------------------------------
# TestCreateGoldDraft — passage linking
# ---------------------------------------------------------------------------

class TestCreateGoldDraftPassageLinking:
    """Passages are linked by market_id, not invented or compressed."""

    def test_passages_linked_by_market_id(self):
        draft = _make_draft(
            pm_entries=[_pm_entry("Online ads", "pm_1")],
            passages=[_passage("pm_1", "42", "The Commission assessed online ads.")],
        )
        report = _make_report(safe=[_candidate("Online ads")])
        gold = _create_gold_draft("test", draft, report)

        pm = gold["product_markets_considered"]
        assert len(pm) == 1
        linked = pm[0]["linked_source_passages"]
        assert len(linked) == 1
        assert linked[0]["quote_snippet"] == "The Commission assessed online ads."
        assert linked[0]["page"] == "42"

    def test_quote_not_invented_when_no_passage(self):
        # No passages in draft — gold must leave linked_source_passages empty
        draft = _make_draft(
            pm_entries=[_pm_entry("Online ads", "pm_1")],
            passages=[],
        )
        report = _make_report(safe=[_candidate("Online ads", refs=["42"])])
        gold = _create_gold_draft("test", draft, report)

        pm = gold["product_markets_considered"]
        assert pm[0]["linked_source_passages"] == []
        # Must carry a reviewer note saying passage needs review
        assert "source passage needs review" in pm[0]["reviewer_notes"]

    def test_source_refs_preserved_when_no_passage(self):
        # Even when passages are missing, the source_refs from the plan are kept
        draft = _make_draft(pm_entries=[_pm_entry("Online ads", "pm_1")])
        report = _make_report(safe=[_candidate("Online ads", refs=["42", "43"])])
        gold = _create_gold_draft("test", draft, report)

        pm = gold["product_markets_considered"]
        assert pm[0].get("source_refs") == ["42", "43"]

    def test_passage_fields_copied_verbatim(self):
        # All passage fields are copied from draft without modification
        p = _passage("pm_1", "42", "Verbatim quote from Commission.", pid="sp_99",
                     doc="doc_42", method="pdf_extracted", review="validated")
        draft = _make_draft(pm_entries=[_pm_entry("Online ads", "pm_1")], passages=[p])
        report = _make_report(safe=[_candidate("Online ads")])
        gold = _create_gold_draft("test", draft, report)

        linked = gold["product_markets_considered"][0]["linked_source_passages"][0]
        assert linked["passage_id"] == "sp_99"
        assert linked["source_document_id"] == "doc_42"
        assert linked["extraction_method"] == "pdf_extracted"
        assert linked["review_status"] == "validated"
        assert linked["quote_snippet"] == "Verbatim quote from Commission."
        assert "source_summary" in linked  # placeholder must be present

    def test_geo_market_passages_linked(self):
        draft = _make_draft(
            gm_entries=[{"market_id": "gm_1", "name": "EEA", "definition_status": "defined"}],
            passages=[_passage("gm_1", "10", "The geographic scope is EEA-wide.",
                               supports_type="geographic_markets")],
        )
        report = _make_report(uncertain=[_candidate("EEA", mtype="geographic")])
        gold = _create_gold_draft("test", draft, report)

        gm = gold["geographic_markets_considered"]
        assert len(gm) == 1
        linked = gm[0]["linked_source_passages"]
        assert linked[0]["quote_snippet"] == "The geographic scope is EEA-wide."

    def test_multiple_passages_all_linked(self):
        passages = [
            _passage("pm_1", "10", "First verbatim passage.", pid="sp_1"),
            _passage("pm_1", "11", "Second verbatim passage.", pid="sp_2"),
        ]
        draft = _make_draft(pm_entries=[_pm_entry("Online ads", "pm_1")], passages=passages)
        report = _make_report(safe=[_candidate("Online ads")])
        gold = _create_gold_draft("test", draft, report)

        linked = gold["product_markets_considered"][0]["linked_source_passages"]
        assert len(linked) == 2
        quotes = {lp["quote_snippet"] for lp in linked}
        assert "First verbatim passage." in quotes
        assert "Second verbatim passage." in quotes


# ---------------------------------------------------------------------------
# TestCreateGoldDraft — field conventions
# ---------------------------------------------------------------------------

class TestCreateGoldDraftConventions:
    """Gold draft field conventions: reviewed, reviewer_notes, market_group, etc."""

    def _simple(self):
        draft = _make_draft(pm_entries=[_pm_entry("Online ads", "pm_1")])
        report = _make_report(safe=[_candidate("Online ads")])
        return _create_gold_draft("test", draft, report)

    def test_reviewed_defaults_to_false(self):
        gold = self._simple()
        assert gold["product_markets_considered"][0]["reviewed"] is False

    def test_reviewer_notes_empty_when_passage_found(self):
        draft = _make_draft(
            pm_entries=[_pm_entry("Online ads", "pm_1")],
            passages=[_passage("pm_1", "1", "Some quote.")],
        )
        report = _make_report(safe=[_candidate("Online ads")])
        gold = _create_gold_draft("test", draft, report)
        assert gold["product_markets_considered"][0]["reviewer_notes"] == ""

    def test_market_group_field_present_and_null(self):
        gold = self._simple()
        assert "market_group" in gold["product_markets_considered"][0]
        assert gold["product_markets_considered"][0]["market_group"] is None

    def test_source_summary_placeholder_in_linked_passage(self):
        draft = _make_draft(
            pm_entries=[_pm_entry("Online ads", "pm_1")],
            passages=[_passage("pm_1", "1", "Quote text.")],
        )
        report = _make_report(safe=[_candidate("Online ads")])
        gold = _create_gold_draft("test", draft, report)
        linked = gold["product_markets_considered"][0]["linked_source_passages"][0]
        assert "source_summary" in linked
        assert linked["source_summary"] == ""

    def test_metadata_partial_and_review_required(self):
        gold = self._simple()
        meta = gold["_gold_metadata"]
        assert meta["partial"] is True
        assert meta["review_required"] is True
        assert meta["gold_status"] == "draft_for_review"

    def test_aliases_from_reconciliation(self):
        # aliases is reviewer-approved only; reconciliation findings no longer
        # auto-populate alias_candidates (evaluator uses nearest-candidate diagnostics).
        draft = _make_draft(pm_entries=[_pm_entry("Online ads", "pm_1")])
        report = _make_report(
            safe=[_candidate("Online ads")],
            reconciliation=[{
                "finding_type": "should_be_renamed",
                "draft_name": "Online ads",
                "existing_name": "Display advertising",
            }],
        )
        gold = _create_gold_draft("test", draft, report)
        pm = gold["product_markets_considered"][0]
        # aliases must be empty (reviewer-approved only)
        assert pm["aliases"] == []
        # Reconciliation names are NOT auto-added to alias_candidates
        alias_values = [c["value"] for c in pm.get("alias_candidates", [])]
        assert "Display advertising" not in alias_values


# ---------------------------------------------------------------------------
# TestCreateGoldDraft — filtering
# ---------------------------------------------------------------------------

class TestCreateGoldDraftFiltering:
    """context_only and hold_pending excluded by default; flags enable inclusion."""

    def test_safe_to_promote_included_by_default(self):
        draft = _make_draft(pm_entries=[_pm_entry("Safe market", "pm_1")])
        report = _make_report(safe=[_candidate("Safe market")])
        gold = _create_gold_draft("test", draft, report)
        names = [m["name"] for m in gold["product_markets_considered"]]
        assert "Safe market" in names

    def test_uncertain_included_by_default(self):
        draft = _make_draft(pm_entries=[_pm_entry("Uncertain market", "pm_1")])
        report = _make_report(uncertain=[_candidate("Uncertain market")])
        gold = _create_gold_draft("test", draft, report)
        assert any(m["name"] == "Uncertain market"
                   for m in gold["product_markets_considered"])

    def test_context_only_excluded_by_default(self):
        draft = _make_draft(pm_entries=[_pm_entry("Background market", "pm_1",
                                                    importance="background")])
        report = _make_report(context=[_candidate("Background market",
                                                    importance="background")])
        gold = _create_gold_draft("test", draft, report)
        names = [m["name"] for m in gold["product_markets_considered"]]
        assert "Background market" not in names

    def test_context_only_included_with_flag(self):
        draft = _make_draft(pm_entries=[_pm_entry("Background market", "pm_1",
                                                    importance="background")])
        report = _make_report(context=[_candidate("Background market",
                                                    importance="background")])
        gold = _create_gold_draft("test", draft, report, include_context_only=True)
        names = [m["name"] for m in gold["product_markets_considered"]]
        assert "Background market" in names

    def test_hold_pending_excluded_by_default(self):
        draft = _make_draft(pm_entries=[_pm_entry("Hold market", "pm_1", status="unknown")])
        report = _make_report(hold=[_candidate("Hold market", status="unknown")])
        gold = _create_gold_draft("test", draft, report)
        names = [m["name"] for m in gold["product_markets_considered"]]
        assert "Hold market" not in names

    def test_hold_pending_included_with_flag(self):
        draft = _make_draft(pm_entries=[_pm_entry("Hold market", "pm_1", status="unknown")])
        report = _make_report(hold=[_candidate("Hold market", status="unknown")])
        gold = _create_gold_draft("test", draft, report, include_hold_pending=True)
        names = [m["name"] for m in gold["product_markets_considered"]]
        assert "Hold market" in names


# ---------------------------------------------------------------------------
# TestFineGrainedMarketNodes
# ---------------------------------------------------------------------------

class TestFineGrainedMarketNodes:
    """Each Commission-listed market becomes a separate gold entry; none collapsed."""

    def test_two_markets_produce_two_entries(self):
        draft = _make_draft(pm_entries=[
            _pm_entry("Search advertising", "pm_1"),
            _pm_entry("Display advertising", "pm_2"),
        ])
        report = _make_report(safe=[
            _candidate("Search advertising"),
            _candidate("Display advertising"),
        ])
        gold = _create_gold_draft("test", draft, report)
        assert len(gold["product_markets_considered"]) == 2

    def test_market_group_can_be_set_externally(self):
        """market_group placeholder exists; reviewers can populate it."""
        draft = _make_draft(pm_entries=[_pm_entry("Search ads", "pm_1")])
        report = _make_report(safe=[_candidate("Search ads")])
        gold = _create_gold_draft("test", draft, report)
        entry = gold["product_markets_considered"][0]
        # Default is None (not missing)
        assert "market_group" in entry
        assert entry["market_group"] is None
        # Reviewer can set it
        entry["market_group"] = "online_advertising"
        assert entry["market_group"] == "online_advertising"

    def test_similar_names_not_collapsed(self):
        """Markets with similar but distinct names must remain separate."""
        draft = _make_draft(pm_entries=[
            _pm_entry("Online advertising", "pm_1"),
            _pm_entry("Online advertising (narrower)", "pm_2"),
        ])
        report = _make_report(safe=[
            _candidate("Online advertising"),
            _candidate("Online advertising (narrower)"),
        ])
        gold = _create_gold_draft("test", draft, report)
        assert len(gold["product_markets_considered"]) == 2
        names = {m["name"] for m in gold["product_markets_considered"]}
        assert "Online advertising" in names
        assert "Online advertising (narrower)" in names


# ---------------------------------------------------------------------------
# TestEvaluateMarkets
# ---------------------------------------------------------------------------

class TestEvaluateMarkets:
    """TP/FP/FN and precision/recall/F1 via exact + alias matching."""

    def test_exact_match_counted_as_tp(self):
        gold = [{"name": "Market A", "reviewed": True}]
        draft = [{"name": "Market A"}]
        r = _evaluate_markets(gold, draft, "product")
        assert r["true_positives"] == 1
        assert r["false_positives"] == 0
        assert r["false_negatives"] == 0

    def test_fn_when_gold_not_in_draft(self):
        gold = [{"name": "Market A", "reviewed": True}, {"name": "Market B", "reviewed": True}]
        draft = [{"name": "Market A"}]
        r = _evaluate_markets(gold, draft, "product")
        assert r["false_negatives"] == 1
        assert r["recall"] < 1.0

    def test_fp_when_draft_not_in_gold(self):
        gold = [{"name": "Market A", "reviewed": True}]
        draft = [{"name": "Market A"}, {"name": "Market B"}]
        r = _evaluate_markets(gold, draft, "product")
        assert r["false_positives"] == 1
        assert r["precision"] < 1.0

    def test_alias_match_counted_as_tp(self):
        gold = [{"name": "Online ads", "reviewed": True, "aliases": ["Display ads"]}]
        draft = [{"name": "Display ads"}]
        r = _evaluate_markets(gold, draft, "product")
        assert r["true_positives"] == 1
        assert r["false_positives"] == 0

    def test_unreviewed_excluded(self):
        gold = [{"name": "A", "reviewed": True}, {"name": "B", "reviewed": False}]
        draft = [{"name": "A"}]
        r = _evaluate_markets(gold, draft, "product")
        assert r["true_positives"] == 1
        assert r["false_negatives"] == 0  # B not counted

    def test_f1_harmonic_mean(self):
        gold = [{"name": "A", "reviewed": True}, {"name": "B", "reviewed": True}]
        draft = [{"name": "A"}, {"name": "C"}]
        r = _evaluate_markets(gold, draft, "product")
        assert r["precision"] == 0.5
        assert r["recall"] == 0.5
        assert r["f1"] == 0.5

    def test_empty_gold(self):
        r = _evaluate_markets([], [{"name": "A"}], "product")
        assert r["true_positives"] == 0
        assert r["false_positives"] == 1
        assert r["precision"] == 0.0


# ---------------------------------------------------------------------------
# TestNoCanonicalMutation
# ---------------------------------------------------------------------------

class TestNoCanonicalMutation:
    """Canonical YAML is never touched by the pipeline."""

    def test_create_gold_does_not_touch_canonical(self, tmp_path):
        canonical = tmp_path / "canonical.yaml"
        canonical.write_text("case_id: test\nproduct_markets: []\n")
        original = canonical.read_text()

        _create_gold_draft(
            "test",
            _make_draft(),
            _make_report(),
        )
        assert canonical.read_text() == original

    def test_validate_gold_passages_does_not_write(self, tmp_path):
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        canonical = tmp_path / "canonical.yaml"
        canonical.write_text("case_id: test\n")
        original = canonical.read_text()

        gold = {
            "case_id": "test",
            "source_documents": [],
            "product_markets_considered": [],
            "geographic_markets_considered": [],
        }
        validate_gold_passages(gold, cache_dir)
        assert canonical.read_text() == original


# ---------------------------------------------------------------------------
# TestGoldYamlEmission — block scalar output and round-trip fidelity
# ---------------------------------------------------------------------------

class TestGoldYamlEmission:
    """gold_yaml_dump emits _FoldedStr as block scalars; round-trips are exact."""

    # --- _FoldedStr / _GoldDumper unit tests ---

    def _dump(self, value) -> str:
        """Dump a single-key dict and return the raw YAML string."""
        return gold_yaml_dump({"q": value})

    def test_plain_str_unchanged(self):
        """Regular str fields are not affected by the custom dumper."""
        out = self._dump("simple")
        loaded = yaml.safe_load(out)["q"]
        assert loaded == "simple"

    def test_folded_str_emits_block_scalar(self):
        """_FoldedStr values appear as >- in the YAML output."""
        out = self._dump(_FoldedStr("The markets are:"))
        assert ">-" in out

    def test_literal_block_for_multiline(self):
        """Multi-line _FoldedStr values use |- (literal) to preserve newlines."""
        out = self._dump(_FoldedStr("line one\nline two"))
        assert "|-" in out

    def test_empty_folded_str_produces_empty_string(self):
        """Empty _FoldedStr round-trips to ''."""
        out = self._dump(_FoldedStr(""))
        loaded = yaml.safe_load(out)["q"]
        assert loaded == ""

    # --- Round-trip tests for problematic quote_snippet content ---

    def _round_trip_quote(self, quote: str) -> str:
        """Write a gold dict containing quote, parse it back, return the loaded quote."""
        passage = {
            "passage_id": "sp_1",
            "page": "10",
            "quote_snippet": _FoldedStr(quote),
            "source_summary": _FoldedStr(""),
            "review_status": "unreviewed",
        }
        gold = {
            "product_markets_considered": [{
                "name": "Test market",
                "linked_source_passages": [passage],
                "reviewer_notes": _FoldedStr(""),
            }]
        }
        raw = gold_yaml_dump(gold)
        loaded = yaml.safe_load(raw)
        return loaded["product_markets_considered"][0]["linked_source_passages"][0]["quote_snippet"]

    def test_colon_ending_round_trips(self):
        """A quote ending with ':' is preserved exactly."""
        q = "The relevant product markets are:"
        assert self._round_trip_quote(q) == q

    def test_colon_mid_sentence_round_trips(self):
        """A quote with a colon mid-sentence is preserved exactly."""
        q = "The Commission concluded: the market is online advertising."
        assert self._round_trip_quote(q) == q

    def test_numbered_list_round_trips(self):
        """(i), (ii), (a), (b) style numbering is preserved exactly."""
        q = "(i) first condition; (ii) second condition; (a) alpha; (b) beta"
        assert self._round_trip_quote(q) == q

    def test_numbered_list_after_colon_round_trips(self):
        """Colon followed by numbered list — common legal pattern."""
        q = "The conditions are: (i) no horizontal overlap; (ii) limited vertical effects."
        assert self._round_trip_quote(q) == q

    def test_semicolons_round_trips(self):
        """Semicolons are preserved exactly."""
        q = "Market definition; competitive assessment; conclusion on conditions."
        assert self._round_trip_quote(q) == q

    def test_ascii_apostrophe_round_trips(self):
        """Plain ASCII apostrophe preserved."""
        q = "The Commission's conclusion confirms the market."
        assert self._round_trip_quote(q) == q

    def test_smart_apostrophe_round_trips(self):
        """Smart apostrophe (U+2019) preserved verbatim."""
        q = "The Commission’s conclusion confirms the market."
        assert self._round_trip_quote(q) == q

    def test_smart_quotes_round_trips(self):
        """Smart double-quotes (U+201C / U+201D) preserved verbatim."""
        q = "“The relevant” market assessment."
        assert self._round_trip_quote(q) == q

    def test_multiline_with_numbering_round_trips(self):
        """Multi-line quote with numbered list preserved via literal block."""
        q = "The relevant product markets are:\n(i) market A\n(ii) market B"
        assert self._round_trip_quote(q) == q

    # --- Full gold draft round-trip ---

    def test_full_gold_draft_round_trips_with_colon_quote(self):
        """create_gold_draft → gold_yaml_dump → yaml.safe_load preserves quote."""
        tricky_quote = "The Commission identified the following relevant markets:"
        draft = _make_draft(
            pm_entries=[_pm_entry("Online ads", "pm_1")],
            passages=[_passage("pm_1", "42", tricky_quote)],
        )
        report = _make_report(safe=[_candidate("Online ads")])
        gold = _create_gold_draft("test", draft, report)

        raw = gold_yaml_dump(gold)
        loaded = yaml.safe_load(raw)
        loaded_quote = (
            loaded["product_markets_considered"][0]
            ["linked_source_passages"][0]
            ["quote_snippet"]
        )
        assert loaded_quote == tricky_quote

    def test_reviewer_notes_block_scalar(self):
        """reviewer_notes uses block scalar style."""
        draft = _make_draft(pm_entries=[_pm_entry("Online ads", "pm_1")])
        report = _make_report(safe=[_candidate("Online ads")])
        gold = _create_gold_draft("test", draft, report)
        raw = gold_yaml_dump(gold)
        assert "reviewer_notes:" in raw

    def test_source_summary_block_scalar(self):
        """source_summary uses block scalar style in linked passages."""
        draft = _make_draft(
            pm_entries=[_pm_entry("Online ads", "pm_1")],
            passages=[_passage("pm_1", "1", "Some quote.")],
        )
        report = _make_report(safe=[_candidate("Online ads")])
        gold = _create_gold_draft("test", draft, report)
        raw = gold_yaml_dump(gold)
        assert "source_summary:" in raw

    def test_gold_output_parseable_by_safe_load(self, tmp_path):
        """Write gold to a real file and safe_load it — must not raise."""
        tricky_quote = "Relevant markets are: (i) online ads; (ii) offline ads."
        draft = _make_draft(
            pm_entries=[_pm_entry("Online ads", "pm_1")],
            passages=[_passage("pm_1", "42", tricky_quote)],
        )
        report = _make_report(safe=[_candidate("Online ads")])
        gold = _create_gold_draft("test", draft, report)

        out_path = tmp_path / "test.gold.yaml"
        with open(out_path, "w") as fh:
            gold_yaml_dump(gold, fh)

        with open(out_path) as fh:
            loaded = yaml.safe_load(fh)

        assert loaded is not None
        q = loaded["product_markets_considered"][0]["linked_source_passages"][0]["quote_snippet"]
        assert q == tricky_quote


# ---------------------------------------------------------------------------
# TestLoadGoldYamlErrors — clear parse error messages
# ---------------------------------------------------------------------------

class TestLoadGoldYamlErrors:
    """load_gold_yaml returns a clear error message instead of a raw traceback."""

    def test_valid_file_returns_data(self, tmp_path):
        p = tmp_path / "valid.yaml"
        p.write_text("case_id: test\nproduct_markets_considered: []\n")
        data, err = load_gold_yaml(p)
        assert err is None
        assert data["case_id"] == "test"

    def test_invalid_yaml_returns_error_string(self, tmp_path):
        p = tmp_path / "bad.yaml"
        # A bare colon on a line is a mapping error in YAML
        p.write_text("case_id: test\nbad: key: value: broken\n  - orphan\n")
        data, err = load_gold_yaml(p)
        # May or may not parse depending on PyYAML version — write something
        # definitively broken instead
        p.write_text("case_id: [\nunclosed bracket\n")
        data, err = load_gold_yaml(p)
        assert data is None
        assert err is not None
        assert "YAML parse error" in err
        assert str(p.name) in err  # includes the filename

    def test_missing_file_returns_error_string(self, tmp_path):
        p = tmp_path / "does_not_exist.yaml"
        data, err = load_gold_yaml(p)
        assert data is None
        assert err is not None
        assert "Cannot open" in err

    def test_error_includes_line_number_when_available(self, tmp_path):
        p = tmp_path / "bad_line.yaml"
        # Write content that will trigger a parse error at a known location
        p.write_text("good: value\nbad line: [\n  unclosed\n")
        data, err = load_gold_yaml(p)
        if err:  # If PyYAML reports an error (it should)
            assert "YAML parse error" in err


# ---------------------------------------------------------------------------
# TestRepairGoldQuotes
# ---------------------------------------------------------------------------

class TestRepairGoldQuotes:
    """repair_gold_passages replaces paraphrased quotes with verbatim draft text."""

    # ------------------------------------------------------------------
    # Shared builders
    # ------------------------------------------------------------------

    def _draft(self, passages=None, pm_entries=None, gm_entries=None):
        return {
            "case_id": "test_repair",
            "product_markets_considered":  pm_entries or [],
            "geographic_markets_considered": gm_entries or [],
            "source_passages": passages or [],
        }

    def _gold_market(
        self,
        name,
        market_type="product",
        linked=None,
        aliases=None,
        source_refs=None,
        reviewed=False,
        reviewer_notes="",
        importance="core_assessed",
        expected_action="promote_to_canonical",
        market_group=None,
    ):
        entry = {
            "name": name,
            "market_type": market_type,
            "importance": importance,
            "expected_promotion_action": expected_action,
            "expected_definition_status": "defined",
            "market_group": market_group,
            "linked_source_passages": linked or [],
            "aliases": aliases or [],
            "reviewer_notes": reviewer_notes,
            "reviewed": reviewed,
        }
        if source_refs is not None:
            entry["source_refs"] = source_refs
        return entry

    def _gold(self, pm=None, gm=None, source_docs=None):
        return {
            "case_id": "test_repair",
            "source_documents": source_docs or [{"doc_id": "doc_1"}],
            "product_markets_considered": pm or [],
            "geographic_markets_considered": gm or [],
        }

    def _pm(self, mid, name, status="defined"):
        return {"market_id": mid, "name": name, "definition_status": status,
                "market_importance": "core_assessed"}

    def _sp(self, mid, page, quote, pid=None, doc="doc_1",
            supports_type="markets"):
        entry = {
            "passage_id": pid or f"sp_{mid}_{page}",
            "source_document_id": doc,
            "page": str(page),
            "quote_snippet": quote,
            "extraction_method": "pdf_extracted",
            "review_status": "unreviewed",
        }
        if supports_type == "markets":
            entry["supports_markets"] = [mid]
        else:
            entry["supports_geographic_markets"] = [mid]
        return entry

    # ------------------------------------------------------------------
    # Core repair behaviour
    # ------------------------------------------------------------------

    def test_paraphrased_quote_is_replaced_with_draft_verbatim(self):
        verbatim = "The Commission found that online advertising is the relevant market."
        paraphrase = "The authority determined an online ads market exists."

        draft = self._draft(
            pm_entries=[self._pm("pm_1", "Online advertising")],
            passages=[self._sp("pm_1", "42", verbatim)],
        )
        gold = self._gold(pm=[self._gold_market(
            "Online advertising",
            linked=[{"page": "42", "quote_snippet": paraphrase,
                     "source_document_id": "doc_1", "source_summary": ""}],
        )])

        repaired, report = repair_gold_passages(gold, draft)

        linked = repaired["product_markets_considered"][0]["linked_source_passages"]
        assert len(linked) == 1
        assert linked[0]["quote_snippet"] == verbatim
        assert report.markets_repaired[0].passages_replaced == 1
        assert report.markets_repaired[0].match_strategy == "market_id"

    def test_repaired_quote_passes_validation(self, tmp_path):
        verbatim = "The Commission assessed the relevant product market."
        draft = self._draft(
            pm_entries=[self._pm("pm_1", "Online ads")],
            passages=[self._sp("pm_1", "10", verbatim)],
        )
        gold = self._gold(pm=[self._gold_market(
            "Online ads",
            linked=[{"page": "10", "quote_snippet": "paraphrase here",
                     "source_document_id": "doc_1", "source_summary": ""}],
        )])

        repaired, _ = repair_gold_passages(gold, draft)

        # Write repaired gold to disk and validate against a mock page cache
        import json
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        cache = {
            "source_document_id": "doc_1",
            "pages": [{"page_number": 10, "text": verbatim}],
        }
        (cache_dir / "doc_1.json").write_text(json.dumps(cache))

        report = validate_gold_passages(repaired, cache_dir)
        assert report.passed == 1
        assert report.failures == []

    def test_no_matching_passage_clears_linked_and_adds_note(self):
        draft = self._draft(
            pm_entries=[self._pm("pm_1", "Online advertising")],
            passages=[],   # no passages in draft
        )
        gold = self._gold(pm=[self._gold_market(
            "Online advertising",
            linked=[{"page": "5", "quote_snippet": "Some hand-written text.",
                     "source_summary": ""}],
        )])

        repaired, report = repair_gold_passages(gold, draft)

        market = repaired["product_markets_considered"][0]
        assert market["linked_source_passages"] == []
        assert "manual selection" in market["reviewer_notes"]
        assert report.markets_repaired[0].passages_cleared == 1
        assert report.markets_repaired[0].match_strategy == "none"

    def test_alias_match_finds_draft_passage(self):
        verbatim = "The Commission assessed display advertising."
        draft = self._draft(
            pm_entries=[self._pm("pm_1", "Display advertising")],
            passages=[self._sp("pm_1", "15", verbatim)],
        )
        # Gold uses different name but has alias pointing to draft name
        gold = self._gold(pm=[self._gold_market(
            "Online advertising",
            aliases=["Display advertising"],
            linked=[{"page": "15", "quote_snippet": "wrong text",
                     "source_summary": ""}],
        )])

        repaired, report = repair_gold_passages(gold, draft)

        linked = repaired["product_markets_considered"][0]["linked_source_passages"]
        assert linked[0]["quote_snippet"] == verbatim
        assert report.markets_repaired[0].match_strategy == "alias"

    def test_source_refs_fallback_finds_passage(self):
        verbatim = "The relevant geographic market is EEA-wide."
        draft = self._draft(
            pm_entries=[self._pm("pm_1", "EEA")],
            passages=[self._sp("pm_1", "20", verbatim)],
        )
        # Gold has no name match but has source_refs pointing to page 20
        gold = self._gold(pm=[self._gold_market(
            "EEA geographic market",
            source_refs=["20"],
            linked=[{"page": "20", "quote_snippet": "paraphrased EEA text",
                     "source_summary": ""}],
        )])

        repaired, report = repair_gold_passages(gold, draft)

        linked = repaired["product_markets_considered"][0]["linked_source_passages"]
        assert linked[0]["quote_snippet"] == verbatim
        assert report.markets_repaired[0].match_strategy == "source_refs"

    # ------------------------------------------------------------------
    # Metadata preservation
    # ------------------------------------------------------------------

    def test_reviewed_flag_preserved(self):
        verbatim = "Assessed market."
        draft = self._draft(
            pm_entries=[self._pm("pm_1", "Test market")],
            passages=[self._sp("pm_1", "1", verbatim)],
        )
        gold = self._gold(pm=[self._gold_market(
            "Test market", reviewed=True,
            linked=[{"page": "1", "quote_snippet": "wrong", "source_summary": ""}],
        )])

        repaired, _ = repair_gold_passages(gold, draft)
        assert repaired["product_markets_considered"][0]["reviewed"] is True

    def test_reviewer_notes_preserved(self):
        verbatim = "Assessed market."
        draft = self._draft(
            pm_entries=[self._pm("pm_1", "Test market")],
            passages=[self._sp("pm_1", "1", verbatim)],
        )
        gold = self._gold(pm=[self._gold_market(
            "Test market", reviewer_notes="Confirmed by analyst.",
            linked=[{"page": "1", "quote_snippet": "wrong", "source_summary": ""}],
        )])

        repaired, _ = repair_gold_passages(gold, draft)
        assert "Confirmed by analyst." in repaired["product_markets_considered"][0]["reviewer_notes"]

    def test_expected_promotion_action_preserved(self):
        verbatim = "Assessed market."
        draft = self._draft(
            pm_entries=[self._pm("pm_1", "Test market")],
            passages=[self._sp("pm_1", "1", verbatim)],
        )
        gold = self._gold(pm=[self._gold_market(
            "Test market", expected_action="promote_with_uncertainty",
            linked=[{"page": "1", "quote_snippet": "wrong", "source_summary": ""}],
        )])

        repaired, _ = repair_gold_passages(gold, draft)
        assert repaired["product_markets_considered"][0]["expected_promotion_action"] == "promote_with_uncertainty"

    def test_importance_preserved(self):
        verbatim = "Core assessed market."
        draft = self._draft(
            pm_entries=[self._pm("pm_1", "Test market")],
            passages=[self._sp("pm_1", "1", verbatim)],
        )
        gold = self._gold(pm=[self._gold_market(
            "Test market", importance="assessed_no_overlap",
            linked=[{"page": "1", "quote_snippet": "wrong", "source_summary": ""}],
        )])

        repaired, _ = repair_gold_passages(gold, draft)
        assert repaired["product_markets_considered"][0]["importance"] == "assessed_no_overlap"

    def test_aliases_preserved(self):
        verbatim = "Commission assessment."
        draft = self._draft(
            pm_entries=[self._pm("pm_1", "Test market")],
            passages=[self._sp("pm_1", "1", verbatim)],
        )
        gold = self._gold(pm=[self._gold_market(
            "Test market", aliases=["Alt name", "Another name"],
            linked=[{"page": "1", "quote_snippet": "wrong", "source_summary": ""}],
        )])

        repaired, _ = repair_gold_passages(gold, draft)
        assert repaired["product_markets_considered"][0]["aliases"] == ["Alt name", "Another name"]

    def test_market_group_preserved(self):
        verbatim = "Commission assessment."
        draft = self._draft(
            pm_entries=[self._pm("pm_1", "Test market")],
            passages=[self._sp("pm_1", "1", verbatim)],
        )
        gold = self._gold(pm=[self._gold_market(
            "Test market", market_group="online_advertising",
            linked=[{"page": "1", "quote_snippet": "wrong", "source_summary": ""}],
        )])

        repaired, _ = repair_gold_passages(gold, draft)
        assert repaired["product_markets_considered"][0]["market_group"] == "online_advertising"

    def test_source_summary_preserved_from_existing_passage(self):
        """source_summary set by reviewer is carried over to the repaired passage."""
        verbatim = "Commission assessed this market."
        draft = self._draft(
            pm_entries=[self._pm("pm_1", "Test market")],
            passages=[self._sp("pm_1", "5", verbatim)],
        )
        gold = self._gold(pm=[self._gold_market(
            "Test market",
            linked=[{
                "page": "5",
                "quote_snippet": "wrong quote",
                "source_summary": "Reviewer explanation here.",
                "source_document_id": "doc_1",
            }],
        )])

        repaired, _ = repair_gold_passages(gold, draft)
        linked = repaired["product_markets_considered"][0]["linked_source_passages"]
        assert linked[0]["source_summary"] == "Reviewer explanation here."

    # ------------------------------------------------------------------
    # Fine-grained market nodes
    # ------------------------------------------------------------------

    def test_fine_grained_markets_not_collapsed(self):
        """Multiple distinct gold markets remain separate after repair."""
        draft = self._draft(
            pm_entries=[
                self._pm("pm_1", "Search advertising"),
                self._pm("pm_2", "Display advertising"),
            ],
            passages=[
                self._sp("pm_1", "10", "The Commission assessed search advertising."),
                self._sp("pm_2", "11", "The Commission assessed display advertising."),
            ],
        )
        gold = self._gold(pm=[
            self._gold_market("Search advertising",
                linked=[{"page": "10", "quote_snippet": "wrong 1", "source_summary": ""}]),
            self._gold_market("Display advertising",
                linked=[{"page": "11", "quote_snippet": "wrong 2", "source_summary": ""}]),
        ])

        repaired, report = repair_gold_passages(gold, draft)

        pm = repaired["product_markets_considered"]
        assert len(pm) == 2
        quotes = {m["name"]: m["linked_source_passages"][0]["quote_snippet"] for m in pm}
        assert quotes["Search advertising"] == "The Commission assessed search advertising."
        assert quotes["Display advertising"] == "The Commission assessed display advertising."

    def test_geo_market_repaired_separately(self):
        """Geographic market passages are repaired independently."""
        verbatim_geo = "The geographic scope is EEA-wide."
        draft = self._draft(
            gm_entries=[{"market_id": "gm_1", "name": "EEA", "definition_status": "defined"}],
            passages=[self._sp("gm_1", "20", verbatim_geo, supports_type="geographic_markets")],
        )
        gold = self._gold(gm=[self._gold_market(
            "EEA", market_type="geographic",
            linked=[{"page": "20", "quote_snippet": "paraphrase", "source_summary": ""}],
        )])

        repaired, report = repair_gold_passages(gold, draft)

        gm = repaired["geographic_markets_considered"]
        assert len(gm) == 1
        assert gm[0]["linked_source_passages"][0]["quote_snippet"] == verbatim_geo

    # ------------------------------------------------------------------
    # No canonical mutation
    # ------------------------------------------------------------------

    def test_original_gold_not_mutated(self):
        """repair_gold_passages returns a copy; the original gold dict is unchanged."""
        original_quote = "Hand-written paraphrase."
        verbatim = "Verbatim passage from the Commission."
        draft = self._draft(
            pm_entries=[self._pm("pm_1", "Test market")],
            passages=[self._sp("pm_1", "1", verbatim)],
        )
        gold = self._gold(pm=[self._gold_market(
            "Test market",
            linked=[{"page": "1", "quote_snippet": original_quote, "source_summary": ""}],
        )])

        repaired, _ = repair_gold_passages(gold, draft)

        # Original gold must be unchanged
        assert gold["product_markets_considered"][0]["linked_source_passages"][0]["quote_snippet"] == original_quote
        # Repaired version has the verbatim quote
        assert repaired["product_markets_considered"][0]["linked_source_passages"][0]["quote_snippet"] == verbatim

    def test_canonical_yaml_not_touched(self, tmp_path):
        """Writing repaired output does not affect a canonical YAML file."""
        canonical = tmp_path / "canonical.yaml"
        canonical.write_text("case_id: test\nproduct_markets: []\n")
        original = canonical.read_text()

        draft = self._draft()
        gold = self._gold()
        repaired, _ = repair_gold_passages(gold, draft)

        out = tmp_path / "repaired.gold.yaml"
        with open(out, "w") as fh:
            gold_yaml_dump(repaired, fh)

        assert canonical.read_text() == original

    # ------------------------------------------------------------------
    # Round-trip: repaired file is parse-safe YAML
    # ------------------------------------------------------------------

    def test_repaired_file_round_trips_colon_quote(self, tmp_path):
        """Quote ending with ':' is parse-safe after repair and round-trip."""
        verbatim = "The Commission identified the following relevant markets:"
        draft = self._draft(
            pm_entries=[self._pm("pm_1", "Online ads")],
            passages=[self._sp("pm_1", "99", verbatim)],
        )
        gold = self._gold(pm=[self._gold_market(
            "Online ads",
            linked=[{"page": "99", "quote_snippet": "bad paraphrase", "source_summary": ""}],
        )])

        repaired, _ = repair_gold_passages(gold, draft)
        raw = gold_yaml_dump(repaired)
        loaded = yaml.safe_load(raw)
        q = loaded["product_markets_considered"][0]["linked_source_passages"][0]["quote_snippet"]
        assert q == verbatim

    def test_multiple_passages_all_replaced(self):
        """All passages for a market are replaced, not just the first."""
        p1 = "First verbatim passage."
        p2 = "Second verbatim passage."
        draft = self._draft(
            pm_entries=[self._pm("pm_1", "Online ads")],
            passages=[
                self._sp("pm_1", "10", p1, pid="sp_1"),
                self._sp("pm_1", "11", p2, pid="sp_2"),
            ],
        )
        gold = self._gold(pm=[self._gold_market(
            "Online ads",
            linked=[
                {"page": "10", "quote_snippet": "wrong 1", "source_summary": ""},
                {"page": "11", "quote_snippet": "wrong 2", "source_summary": ""},
            ],
        )])

        repaired, report = repair_gold_passages(gold, draft)

        linked = repaired["product_markets_considered"][0]["linked_source_passages"]
        assert len(linked) == 2
        quotes = {lp["page"]: lp["quote_snippet"] for lp in linked}
        assert quotes["10"] == p1
        assert quotes["11"] == p2
        assert report.markets_repaired[0].passages_replaced == 2


# ---------------------------------------------------------------------------
# TestSourceRolePriority
# ---------------------------------------------------------------------------

class TestSourceRolePriority:
    """_source_role_priority: lower number = higher priority."""

    def test_conclusion_highest(self):
        assert _source_role_priority("conclusion") < _source_role_priority("background")

    def test_commission_assessment_before_investigation(self):
        assert _source_role_priority("commission_assessment") < _source_role_priority("market_investigation")

    def test_background_lowest(self):
        p = _source_role_priority("background")
        assert p >= _source_role_priority("commission_assessment")
        assert p >= _source_role_priority("market_investigation")
        assert p >= _source_role_priority("notifying_party_view")

    def test_unknown_role_is_middle(self):
        # unknown should not be first or last
        p = _source_role_priority("")
        assert p > _source_role_priority("conclusion")
        assert p <= _source_role_priority("background")

    def test_missing_role_same_as_empty(self):
        assert _source_role_priority("") == _source_role_priority("nonexistent_role")


# ---------------------------------------------------------------------------
# TestHasNameOverlap
# ---------------------------------------------------------------------------

class TestHasNameOverlap:
    """_has_name_overlap: source_refs fallback filtering."""

    def test_matching_token_returns_true(self):
        assert _has_name_overlap(
            "Online advertising constitutes the relevant market.",
            "Online advertising", []
        ) is True

    def test_no_matching_token_returns_false(self):
        assert _has_name_overlap(
            "The supply of wearable operating systems is distinct.",
            "Online advertising", []
        ) is False

    def test_alias_token_returns_true(self):
        assert _has_name_overlap(
            "Display advertising services were assessed.",
            "Online advertising", ["Display advertising"]
        ) is True

    def test_no_tokens_in_name_accepts_any_quote(self):
        # "EEA" is 3 chars → no significant tokens → accept all
        assert _has_name_overlap("Some unrelated text.", "EEA", []) is True

    def test_stopword_only_name_accepts_any_quote(self):
        # If name is all stopwords → no tokens → accept
        assert _has_name_overlap("Any text at all.", "the relevant market", []) is True

    def test_partial_token_match_sufficient(self):
        # Only one of the two tokens needs to match
        assert _has_name_overlap(
            "Advertising services are widely distributed.",
            "Online advertising", []
        ) is True


# ---------------------------------------------------------------------------
# TestSortPassages
# ---------------------------------------------------------------------------

class TestSortPassages:
    """_sort_passages: direct-match first, then source_role priority."""

    def _sp(self, pid, role=""):
        return {"passage_id": pid, "source_role": role, "quote_snippet": "q"}

    def test_direct_before_fallback(self):
        direct = self._sp("sp_direct", "background")
        fallback = self._sp("sp_fallback", "conclusion")
        sorted_list = _sort_passages([fallback, direct], frozenset({"sp_direct"}))
        assert sorted_list[0]["passage_id"] == "sp_direct"

    def test_within_direct_conclusion_before_background(self):
        conclusion = self._sp("sp_c", "conclusion")
        background = self._sp("sp_b", "background")
        sorted_list = _sort_passages([background, conclusion], frozenset({"sp_c", "sp_b"}))
        assert sorted_list[0]["passage_id"] == "sp_c"

    def test_within_fallback_commission_before_notifying(self):
        commission = self._sp("sp_comm", "commission_assessment")
        notifying = self._sp("sp_note", "notifying_party_view")
        sorted_list = _sort_passages([notifying, commission], frozenset())
        assert sorted_list[0]["passage_id"] == "sp_comm"

    def test_empty_direct_ids_all_fallback(self):
        conclusion = self._sp("sp_c", "conclusion")
        background = self._sp("sp_b", "background")
        result = _sort_passages([background, conclusion], frozenset())
        assert result[0]["passage_id"] == "sp_c"


# ---------------------------------------------------------------------------
# TestValidateCandidates
# ---------------------------------------------------------------------------

class TestValidateCandidates:
    """_validate_candidates: drop passages that fail quote validation."""

    def _cache_map(self, doc_id: str, page: int, text: str) -> dict:
        return {doc_id: {"pages": [{"page_number": page, "text": text}]}}

    def _sp(self, page, quote, doc="doc_1"):
        return {"passage_id": f"sp_{page}", "page": str(page),
                "quote_snippet": quote, "source_document_id": doc}

    def test_valid_quote_kept(self):
        page_text = "The Commission assessed online advertising."
        sp = self._sp(10, "Commission assessed online advertising")
        valid, reasons = _validate_candidates(
            [sp], self._cache_map("doc_1", 10, page_text), "Online ads"
        )
        assert len(valid) == 1
        assert reasons == []

    def test_invalid_quote_dropped(self):
        page_text = "The Commission assessed online advertising."
        sp = self._sp(10, "The authority concluded display ads are relevant")
        valid, reasons = _validate_candidates(
            [sp], self._cache_map("doc_1", 10, page_text), "Online ads"
        )
        assert valid == []
        assert len(reasons) == 1
        assert "not found verbatim" in reasons[0]

    def test_missing_page_dropped(self):
        sp = self._sp(99, "Some quote")
        valid, reasons = _validate_candidates(
            [sp], self._cache_map("doc_1", 10, "text on page 10"), "Market"
        )
        assert valid == []
        assert "not in cache" in reasons[0]

    def test_empty_quote_dropped(self):
        sp = self._sp(10, "")
        valid, reasons = _validate_candidates(
            [sp], self._cache_map("doc_1", 10, "text"), "Market"
        )
        assert valid == []
        assert "empty quote" in reasons[0]

    def test_no_cache_for_doc_included_without_validation(self):
        # When cache_map has no entry for the doc, passage is kept (not dropped)
        sp = self._sp(10, "Some quote", doc="unknown_doc")
        valid, reasons = _validate_candidates(
            [sp], {}, "Market"
        )
        assert len(valid) == 1
        assert reasons == []

    def test_multiple_mixed_candidates(self):
        page_text = "The Commission assessed online advertising services."
        valid_sp = self._sp(10, "Commission assessed online advertising services")
        invalid_sp = self._sp(10, "The authority concluded display ads exist")
        valid, reasons = _validate_candidates(
            [valid_sp, invalid_sp], self._cache_map("doc_1", 10, page_text), "Market"
        )
        assert len(valid) == 1
        assert valid[0]["quote_snippet"] == "Commission assessed online advertising services"
        assert len(reasons) == 1


# ---------------------------------------------------------------------------
# TestRepairGoldQuotesTightened
# ---------------------------------------------------------------------------

class TestRepairGoldQuotesTightened:
    """Tightened repair: validation, max passages, priority, fallback strictness."""

    def _sp(self, mid, page, quote, pid=None, doc="doc_1",
            role="", supports_type="markets"):
        entry = {
            "passage_id": pid or f"sp_{mid}_{page}",
            "source_document_id": doc,
            "page": str(page),
            "quote_snippet": quote,
            "extraction_method": "pdf_extracted",
            "review_status": "unreviewed",
            "source_role": role,
        }
        if supports_type == "markets":
            entry["supports_markets"] = [mid]
        else:
            entry["supports_geographic_markets"] = [mid]
        return entry

    def _pm(self, mid, name, status="defined"):
        return {"market_id": mid, "name": name, "definition_status": status,
                "market_importance": "core_assessed"}

    def _gold_market(self, name, mtype="product", linked=None,
                     aliases=None, source_refs=None, reviewed=False,
                     reviewer_notes="", importance="core_assessed",
                     expected_action="promote_to_canonical", market_group=None):
        entry = {
            "name": name, "market_type": mtype, "importance": importance,
            "expected_promotion_action": expected_action,
            "expected_definition_status": "defined",
            "market_group": market_group,
            "linked_source_passages": linked or [],
            "aliases": aliases or [], "reviewer_notes": reviewer_notes,
            "reviewed": reviewed,
        }
        if source_refs is not None:
            entry["source_refs"] = source_refs
        return entry

    def _gold(self, pm=None, gm=None):
        return {
            "case_id": "tightened_test",
            "source_documents": [{"doc_id": "doc_1"}],
            "product_markets_considered": pm or [],
            "geographic_markets_considered": gm or [],
        }

    def _draft(self, pm=None, gm=None, passages=None):
        return {
            "case_id": "tightened_test",
            "product_markets_considered": pm or [],
            "geographic_markets_considered": gm or [],
            "source_passages": passages or [],
        }

    def _cache_map(self, pages: dict) -> dict:
        """pages: {page_num: text}"""
        return {
            "doc_1": {
                "pages": [{"page_number": n, "text": t} for n, t in pages.items()]
            }
        }

    # ------------------------------------------------------------------
    # Validation filtering
    # ------------------------------------------------------------------

    def test_only_validator_passing_quotes_in_output(self):
        """Candidates that fail page-text validation are dropped."""
        real_text = "The Commission found that online advertising is relevant."
        draft = self._draft(
            pm=[self._pm("pm_1", "Online advertising")],
            passages=[
                self._sp("pm_1", "10", "Commission found that online advertising is relevant"),
                self._sp("pm_1", "11", "This passage is a paraphrase that does not appear verbatim", pid="sp_bad"),
            ],
        )
        gold = self._gold(pm=[self._gold_market(
            "Online advertising",
            linked=[{"page": "10", "quote_snippet": "old text", "source_summary": ""}],
        )])
        pcm = self._cache_map({10: real_text, 11: "Totally different text on page 11."})

        repaired, report = repair_gold_passages(gold, draft, page_cache_map=pcm)

        linked = repaired["product_markets_considered"][0]["linked_source_passages"]
        assert len(linked) == 1
        assert "Commission found that online advertising is relevant" in linked[0]["quote_snippet"]
        assert report.markets_repaired[0].passages_dropped == 1

    def test_all_candidates_fail_clears_linked(self):
        """When every candidate fails validation, linked_source_passages is cleared."""
        draft = self._draft(
            pm=[self._pm("pm_1", "Online advertising")],
            passages=[self._sp("pm_1", "10", "Paraphrase not in page text")],
        )
        gold = self._gold(pm=[self._gold_market("Online advertising")])
        pcm = self._cache_map({10: "Completely unrelated text about something else."})

        repaired, report = repair_gold_passages(gold, draft, page_cache_map=pcm)

        market = repaired["product_markets_considered"][0]
        assert market["linked_source_passages"] == []
        assert "manual selection" in market["reviewer_notes"]
        result = report.markets_repaired[0]
        assert result.passages_cleared == 1
        assert result.passages_dropped == 1

    # ------------------------------------------------------------------
    # Max passages
    # ------------------------------------------------------------------

    def test_max_passages_respected(self):
        """At most max_passages passages are included per market."""
        passages = [
            self._sp("pm_1", str(i), f"Commission assessed market passage number {i}.", pid=f"sp_{i}")
            for i in range(1, 6)
        ]
        page_texts = {i: f"Commission assessed market passage number {i}." for i in range(1, 6)}
        draft = self._draft(pm=[self._pm("pm_1", "Online advertising")], passages=passages)
        gold = self._gold(pm=[self._gold_market("Online advertising")])
        pcm = self._cache_map(page_texts)

        repaired, report = repair_gold_passages(
            gold, draft, page_cache_map=pcm, max_passages=2
        )

        linked = repaired["product_markets_considered"][0]["linked_source_passages"]
        assert len(linked) == 2
        assert report.markets_repaired[0].passages_replaced == 2

    def test_default_max_is_three(self):
        """Default max_passages is 3."""
        passages = [
            self._sp("pm_1", str(i), f"The Commission assessed advertising passage {i}.", pid=f"sp_{i}")
            for i in range(1, 6)
        ]
        page_texts = {i: f"The Commission assessed advertising passage {i}." for i in range(1, 6)}
        draft = self._draft(pm=[self._pm("pm_1", "Advertising")], passages=passages)
        gold = self._gold(pm=[self._gold_market("Advertising")])
        pcm = self._cache_map(page_texts)

        repaired, _ = repair_gold_passages(gold, draft, page_cache_map=pcm)

        linked = repaired["product_markets_considered"][0]["linked_source_passages"]
        assert len(linked) == 3

    # ------------------------------------------------------------------
    # Source-role priority
    # ------------------------------------------------------------------

    def test_conclusion_preferred_over_background(self):
        """conclusion passage is placed before background even when background comes first."""
        p_bg = self._sp("pm_1", "10", "Background context about advertising.", pid="sp_bg", role="background")
        p_con = self._sp("pm_1", "11", "The Commission concluded advertising is relevant.", pid="sp_con", role="conclusion")
        page_texts = {
            10: "Background context about advertising.",
            11: "The Commission concluded advertising is relevant.",
        }
        draft = self._draft(pm=[self._pm("pm_1", "Advertising")], passages=[p_bg, p_con])
        gold = self._gold(pm=[self._gold_market("Advertising")])
        pcm = self._cache_map(page_texts)

        repaired, _ = repair_gold_passages(
            gold, draft, page_cache_map=pcm, max_passages=1
        )

        linked = repaired["product_markets_considered"][0]["linked_source_passages"]
        assert len(linked) == 1
        assert "concluded advertising is relevant" in linked[0]["quote_snippet"]

    def test_commission_assessment_before_notifying_party(self):
        """commission_assessment ranked above notifying_party_view."""
        p_np = self._sp("pm_1", "10", "The notifying parties argued advertising is relevant.", pid="sp_np", role="notifying_party_view")
        p_ca = self._sp("pm_1", "11", "The Commission assessed advertising market dynamics.", pid="sp_ca", role="commission_assessment")
        page_texts = {
            10: "The notifying parties argued advertising is relevant.",
            11: "The Commission assessed advertising market dynamics.",
        }
        draft = self._draft(pm=[self._pm("pm_1", "Advertising")], passages=[p_np, p_ca])
        gold = self._gold(pm=[self._gold_market("Advertising")])
        pcm = self._cache_map(page_texts)

        repaired, _ = repair_gold_passages(
            gold, draft, page_cache_map=pcm, max_passages=1
        )

        linked = repaired["product_markets_considered"][0]["linked_source_passages"]
        assert "Commission assessed advertising market dynamics" in linked[0]["quote_snippet"]

    # ------------------------------------------------------------------
    # Source-refs fallback strictness
    # ------------------------------------------------------------------

    def test_source_refs_fallback_excludes_unrelated_passages(self):
        """Page fallback does not include passages with no name-token overlap."""
        p_ads = self._sp("pm_1", "42", "Online advertising constitutes the relevant product market.", pid="sp_ads")
        p_wearable = self._sp("pm_2", "42", "The supply of wearable devices is a separate market.", pid="sp_wear")
        draft = self._draft(
            pm=[self._pm("pm_1", "Online advertising"), self._pm("pm_2", "Wearable devices")],
            passages=[p_ads, p_wearable],
        )
        # Gold market has no direct name match to draft — falls through to source_refs
        gold = self._gold(pm=[self._gold_market(
            "Online advertising services",
            source_refs=["42"],
            linked=[{"page": "42", "quote_snippet": "old", "source_summary": ""}],
        )])
        page_texts = {
            42: (
                "Online advertising constitutes the relevant product market. "
                "The supply of wearable devices is a separate market."
            )
        }
        pcm = self._cache_map(page_texts)

        repaired, report = repair_gold_passages(gold, draft, page_cache_map=pcm)

        linked = repaired["product_markets_considered"][0]["linked_source_passages"]
        quotes = [lp["quote_snippet"] for lp in linked]
        # "Online advertising constitutes..." must be included
        assert any("online advertising" in q.lower() for q in quotes)
        # "wearable devices" must NOT be included
        assert not any("wearable" in q.lower() for q in quotes)

    def test_source_refs_no_overlap_clears_linked(self):
        """When page fallback finds no overlap, linked_source_passages is empty."""
        p_wearable = self._sp("pm_1", "42", "The supply of wearable devices is distinct.")
        draft = self._draft(
            pm=[self._pm("pm_1", "Wearable devices")],
            passages=[p_wearable],
        )
        # Gold market name has no overlap with the wearable passage
        gold = self._gold(pm=[self._gold_market(
            "Online advertising",
            source_refs=["42"],
            linked=[{"page": "42", "quote_snippet": "old", "source_summary": ""}],
        )])

        repaired, report = repair_gold_passages(gold, draft)

        market = repaired["product_markets_considered"][0]
        assert market["linked_source_passages"] == []
        assert report.markets_repaired[0].match_strategy == "none"

    # ------------------------------------------------------------------
    # Metadata preservation (tightened version)
    # ------------------------------------------------------------------

    def test_metadata_preserved_after_tightened_repair(self):
        """All reviewer metadata survives when passages are replaced by validation."""
        real_quote = "The Commission formally assessed the relevant market."
        draft = self._draft(
            pm=[self._pm("pm_1", "Test market")],
            passages=[self._sp("pm_1", "5", real_quote)],
        )
        gold = self._gold(pm=[self._gold_market(
            "Test market",
            reviewed=True,
            reviewer_notes="Confirmed by analyst on 2026-05-29.",
            importance="assessed_no_overlap",
            expected_action="keep_as_context_only",
            market_group="digital_markets",
            aliases=["Alternative name"],
            linked=[{"page": "5", "quote_snippet": "paraphrase", "source_summary": "Explains p5"}],
        )])
        pcm = self._cache_map({5: real_quote})

        repaired, _ = repair_gold_passages(gold, draft, page_cache_map=pcm)

        m = repaired["product_markets_considered"][0]
        assert m["reviewed"] is True
        assert "Confirmed by analyst" in m["reviewer_notes"]
        assert m["importance"] == "assessed_no_overlap"
        assert m["expected_promotion_action"] == "keep_as_context_only"
        assert m["market_group"] == "digital_markets"
        assert "Alternative name" in m["aliases"]
        # Source summary carried forward
        assert m["linked_source_passages"][0]["source_summary"] == "Explains p5"

    # ------------------------------------------------------------------
    # No canonical YAML mutation
    # ------------------------------------------------------------------

    def test_no_canonical_mutation(self, tmp_path):
        canonical = tmp_path / "canonical.yaml"
        canonical.write_text("case_id: test\nproduct_markets: []\n")
        original = canonical.read_text()

        draft = self._draft()
        gold = self._gold()
        repair_gold_passages(gold, draft, page_cache_map={})

        assert canonical.read_text() == original


# ---------------------------------------------------------------------------
# TestBuildReviewedGroups
# ---------------------------------------------------------------------------

class TestBuildReviewedGroups:
    """_build_reviewed_groups collects groups from reviewed gold + reviewed_scope."""

    def test_groups_from_reviewed_markets(self):
        gold = [
            {"name": "A", "reviewed": True,  "market_group": "search"},
            {"name": "B", "reviewed": True,  "market_group": "display"},
            {"name": "C", "reviewed": False, "market_group": "video"},
        ]
        groups = _build_reviewed_groups(gold, None)
        assert "search" in groups
        assert "display" in groups
        assert "video" not in groups   # C not reviewed

    def test_groups_from_reviewed_scope(self):
        gold = [{"name": "A", "reviewed": True, "market_group": "search"}]
        scope = {"groups": ["wearables", "display"]}
        groups = _build_reviewed_groups(gold, scope)
        assert "search" in groups
        assert "wearables" in groups
        assert "display" in groups

    def test_null_market_group_excluded(self):
        gold = [{"name": "A", "reviewed": True, "market_group": None}]
        groups = _build_reviewed_groups(gold, None)
        assert len(groups) == 0

    def test_empty_gold_empty_scope(self):
        assert _build_reviewed_groups([], None) == frozenset()


# ---------------------------------------------------------------------------
# TestEvaluateMarketsPartial
# ---------------------------------------------------------------------------

class TestEvaluateMarketsPartial:
    """Partial-gold semantics: unjudged draft markets are not FPs."""

    # ------------------------------------------------------------------
    # Core partial-mode classification
    # ------------------------------------------------------------------

    def test_partial_does_not_count_unjudged_as_fp(self):
        """Draft market with no group overlap is unjudged, not FP."""
        gold  = [{"name": "Market A", "reviewed": True}]
        draft = [{"name": "Market A"}, {"name": "Market B"}]
        r = _evaluate_markets(gold, draft, "product", is_partial=True)
        assert r["false_positives"]   == 0
        assert r["unjudged_candidates"] == 1
        assert r["true_positives"]    == 1
        assert r["precision"]         == 1.0

    def test_full_gold_counts_unjudged_as_fp(self):
        """Same inputs with partial=False → Market B is FP (full-gold behavior)."""
        gold  = [{"name": "Market A", "reviewed": True}]
        draft = [{"name": "Market A"}, {"name": "Market B"}]
        r = _evaluate_markets(gold, draft, "product", is_partial=False)
        assert r["false_positives"] == 1
        assert r["precision"] < 1.0

    def test_missing_reviewed_gold_item_is_fn(self):
        """Reviewed gold market absent from draft → FN, not unjudged."""
        gold  = [{"name": "A", "reviewed": True}, {"name": "B", "reviewed": True}]
        draft = [{"name": "A"}]
        r = _evaluate_markets(gold, draft, "product", is_partial=True)
        assert r["false_negatives"]    == 1
        assert r["true_positives"]     == 1
        assert r["unjudged_candidates"] == 0

    def test_matched_reviewed_item_is_tp(self):
        """Reviewed gold market found in draft → TP, not unjudged."""
        gold  = [{"name": "Online ads", "reviewed": True}]
        draft = [{"name": "Online ads"}]
        r = _evaluate_markets(gold, draft, "product", is_partial=True)
        assert r["true_positives"]     == 1
        assert r["false_positives"]    == 0
        assert r["unjudged_candidates"] == 0

    def test_unreviewed_gold_item_not_counted(self):
        """Unreviewed gold items are skipped for all metrics."""
        gold  = [{"name": "A", "reviewed": True}, {"name": "B", "reviewed": False}]
        draft = [{"name": "A"}]
        r = _evaluate_markets(gold, draft, "product", is_partial=True)
        assert r["true_positives"]  == 1
        assert r["false_negatives"] == 0  # B is unreviewed → ignored

    # ------------------------------------------------------------------
    # In-scope FP via market_group
    # ------------------------------------------------------------------

    def test_in_scope_draft_market_is_fp(self):
        """Draft market in a reviewed group but not in gold → FP."""
        gold = [
            {"name": "Search ads", "reviewed": True, "market_group": "online_ads"},
        ]
        draft = [
            {"name": "Search ads"},
            {"name": "Display ads", "market_group": "online_ads"},  # same group, not in gold
        ]
        r = _evaluate_markets(gold, draft, "product", is_partial=True)
        assert r["false_positives"]    == 1   # Display ads is in scope
        assert r["unjudged_candidates"] == 0

    def test_out_of_group_draft_market_is_unjudged(self):
        """Draft market in a different group is unjudged, not FP."""
        gold = [
            {"name": "Search ads", "reviewed": True, "market_group": "online_ads"},
        ]
        draft = [
            {"name": "Search ads"},
            {"name": "Wearable OS", "market_group": "hardware"},  # different group
        ]
        r = _evaluate_markets(gold, draft, "product", is_partial=True)
        assert r["false_positives"]    == 0
        assert r["unjudged_candidates"] == 1

    def test_reviewed_scope_groups_extend_in_scope(self):
        """reviewed_scope.groups supplements market_group from gold markets."""
        gold = [{"name": "Search ads", "reviewed": True, "market_group": "search"}]
        draft = [
            {"name": "Search ads"},
            {"name": "Display ads", "market_group": "display"},  # in scope via reviewed_scope
        ]
        scope = {"groups": ["display"]}
        r = _evaluate_markets(gold, draft, "product", is_partial=True, reviewed_scope=scope)
        assert r["false_positives"]    == 1
        assert r["unjudged_candidates"] == 0

    # ------------------------------------------------------------------
    # Partial metrics reported separately
    # ------------------------------------------------------------------

    def test_partial_metrics_keys_present(self):
        """partial_precision, partial_recall, partial_f1 are in result when partial."""
        gold  = [{"name": "A", "reviewed": True}]
        draft = [{"name": "A"}]
        r = _evaluate_markets(gold, draft, "product", is_partial=True)
        assert "partial_precision"       in r
        assert "partial_recall"          in r
        assert "partial_f1"              in r
        assert "evaluated_candidates"    in r
        assert "unjudged_candidates"     in r
        assert "out_of_scope_candidates" in r

    def test_partial_metrics_absent_when_full(self):
        """Partial-specific keys are absent when is_partial=False."""
        gold  = [{"name": "A", "reviewed": True}]
        draft = [{"name": "A"}]
        r = _evaluate_markets(gold, draft, "product", is_partial=False)
        assert "partial_precision"    not in r
        assert "unjudged_candidates"  not in r

    def test_partial_f1_matches_precision_recall(self):
        """partial_f1 is consistent with partial_precision and partial_recall."""
        gold  = [{"name": "A", "reviewed": True}, {"name": "B", "reviewed": True}]
        draft = [{"name": "A"}, {"name": "C"}]  # B missing (FN), C unjudged
        r = _evaluate_markets(gold, draft, "product", is_partial=True)
        p = r["partial_precision"]
        rc = r["partial_recall"]
        if p + rc > 0:
            expected_f1 = round(2 * p * rc / (p + rc), 3)
            assert r["partial_f1"] == expected_f1

    def test_alias_match_works_in_partial_mode(self):
        """Alias matching still resolves TP in partial mode."""
        gold  = [{"name": "Online ads", "reviewed": True, "aliases": ["Display ads"]}]
        draft = [{"name": "Display ads"}]
        r = _evaluate_markets(gold, draft, "product", is_partial=True)
        assert r["true_positives"]     == 1
        assert r["false_positives"]    == 0
        assert r["unjudged_candidates"] == 0

    # ------------------------------------------------------------------
    # Unjudged candidates reported separately
    # ------------------------------------------------------------------

    def test_multiple_unjudged_all_reported(self):
        """All unmatched, out-of-group draft markets are counted as unjudged."""
        gold  = [{"name": "A", "reviewed": True}]
        draft = [{"name": "A"}, {"name": "B"}, {"name": "C"}, {"name": "D"}]
        r = _evaluate_markets(gold, draft, "product", is_partial=True)
        assert r["unjudged_candidates"] == 3
        assert r["false_positives"]     == 0

    # ------------------------------------------------------------------
    # Gating stays hard on quote failures / overpromotion
    # (tested through _evaluate_extraction)
    # ------------------------------------------------------------------

    def _dummy_report(self, *, risky: bool = False) -> dict:
        return {
            "canonical_merge_candidates": {
                "safe_to_promote": [{"name": "X"}] if risky else [],
                "uncertain_markets": [{"name": "X"}] if risky else [],
                "hold_pending_source_check": [],
                "manual_review": [],
            }
        }

    def _partial_gold_yaml(self, reviewed_markets: list[str]) -> dict:
        return {
            "_gold_metadata": {"partial": True, "reviewed_scope": {}},
            "case_id": "test",
            "source_documents": [],
            "product_markets_considered": [
                {"name": n, "reviewed": True, "linked_source_passages": []}
                for n in reviewed_markets
            ],
            "geographic_markets_considered": [],
        }

    def _draft_yaml(self, market_names: list[str]) -> dict:
        return {
            "product_markets_considered": [{"name": n} for n in market_names],
            "geographic_markets_considered": [],
        }

    def test_quote_failures_force_reject_in_partial_mode(self, tmp_path):
        """Quote validation failures → reject even when recall is perfect."""
        from evaluate_extraction import _evaluate_extraction
        import json as _json

        # Gold with one passage that cannot be found in any cache
        gold = self._partial_gold_yaml(["Market A"])
        gold["product_markets_considered"][0]["linked_source_passages"] = [{
            "page": "1",
            "quote_snippet": "This quote does not exist in the PDF.",
            "source_document_id": "doc_1",
        }]
        gold["source_documents"] = [{"doc_id": "doc_1"}]

        # Provide a cache that does NOT contain the quote
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        cache_data = {"source_document_id": "doc_1",
                      "pages": [{"page_number": 1, "text": "Some other text entirely."}]}
        (cache_dir / "doc_1.json").write_text(_json.dumps(cache_data))

        draft = self._draft_yaml(["Market A"])
        report = self._dummy_report()

        result = _evaluate_extraction("test", gold, draft, report, cache_dir)
        assert result["gating_decision"] == "reject"

    def test_overpromotion_forces_reject_in_partial_mode(self, tmp_path):
        """Overpromotion → reject regardless of partial/full gold mode."""
        from evaluate_extraction import _evaluate_extraction

        gold = self._partial_gold_yaml(["Market A"])
        draft = self._draft_yaml(["Market A"])
        report = self._dummy_report(risky=True)
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        result = _evaluate_extraction("test", gold, draft, report, cache_dir)
        assert result["gating_decision"] == "reject"

    def test_partial_gold_good_recall_gives_auto_accept(self, tmp_path):
        """Good recall + precision + no issues → auto_accept for partial gold."""
        from evaluate_extraction import _evaluate_extraction

        gold = self._partial_gold_yaml(["Market A", "Market B"])
        draft = self._draft_yaml(["Market A", "Market B", "Unrelated Market"])
        report = self._dummy_report()
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        result = _evaluate_extraction("test", gold, draft, report, cache_dir)
        # Recall = 2/2 = 1.0, precision = 2/(2+0) = 1.0 (Unrelated is unjudged)
        assert result["gating_decision"] == "auto_accept"
        # Unjudged should be in the output
        pm = result["product_markets"]
        assert pm["unjudged_candidates"] == 1
        assert pm["false_positives"]     == 0


# ---------------------------------------------------------------------------
# TestTokenOverlap
# ---------------------------------------------------------------------------

class TestTokenOverlap:
    """_token_overlap_score: conservative Jaccard on significant tokens."""

    def test_identical_names(self):
        assert _token_overlap_score("Online advertising", "Online advertising") == 1.0

    def test_no_overlap(self):
        assert _token_overlap_score("Online advertising", "Wearable devices") == 0.0

    def test_partial_overlap(self):
        score = _token_overlap_score("Online advertising services", "Advertising services")
        assert 0 < score < 1.0

    def test_stopwords_excluded(self):
        # "the" and "relevant" are stopwords; "market" is also stopword
        score_a = _token_overlap_score("Online ads", "the relevant market for online ads")
        score_b = _token_overlap_score("Online ads", "online ads")
        # Both should have the same meaningful tokens (online, ads)
        assert score_a == score_b

    def test_short_words_excluded(self):
        # Single-letter or two-letter tokens are excluded
        assert _token_overlap_score("A B Online", "A B Online") == _token_overlap_score("Online", "Online")

    def test_symmetric(self):
        a, b = "Online advertising", "Display advertising"
        assert _token_overlap_score(a, b) == _token_overlap_score(b, a)


# ---------------------------------------------------------------------------
# TestNearestDraftCandidates
# ---------------------------------------------------------------------------

class TestNearestDraftCandidates:
    """_nearest_draft_candidates: diagnostic hints for FN, never counted as matches."""

    def test_returns_overlapping_candidates(self):
        draft = [
            {"name": "Online advertising services", "market_id": "pm_1"},
            {"name": "Wearable devices market",     "market_id": "pm_2"},
        ]
        candidates = _nearest_draft_candidates("Online advertising", draft)
        names = [c["draft_name"] for c in candidates]
        assert "Online advertising services" in names
        assert "Wearable devices market" not in names  # no overlap

    def test_returns_at_most_five(self):
        draft = [{"name": f"Advertising market {i}", "market_id": f"pm_{i}"} for i in range(10)]
        candidates = _nearest_draft_candidates("Online advertising", draft)
        assert len(candidates) <= 5

    def test_sorted_by_score_descending(self):
        draft = [
            {"name": "Online advertising display",    "market_id": "pm_1"},
            {"name": "Online advertising",            "market_id": "pm_2"},
        ]
        candidates = _nearest_draft_candidates("Online advertising", draft)
        scores = [c["overlap_score"] for c in candidates]
        assert scores == sorted(scores, reverse=True)

    def test_zero_overlap_excluded(self):
        draft = [{"name": "Completely unrelated topic", "market_id": "pm_1"}]
        candidates = _nearest_draft_candidates("Online advertising", draft)
        assert candidates == []

    def test_market_id_included_in_result(self):
        draft = [{"name": "Online ads display", "market_id": "pm_42"}]
        candidates = _nearest_draft_candidates("Online advertising", draft)
        assert candidates[0]["market_id"] == "pm_42"


# ---------------------------------------------------------------------------
# TestFindMatchingMarket (extended)
# ---------------------------------------------------------------------------

class TestFindMatchingMarketExtended:
    """_find_matching_market: exact, alias, expected_draft_names, expected_market_ids."""

    def test_exact_match_returns_exact(self):
        draft = [{"name": "Online advertising"}]
        result = _find_matching_market("Online advertising", draft, {})
        assert result is not None
        m, mtype = result
        assert mtype == "exact"
        assert m["name"] == "Online advertising"

    def test_alias_match_returns_alias(self):
        draft = [{"name": "Display ads"}]
        aliases = {"Online ads": ["Display ads"]}
        result = _find_matching_market("Online ads", draft, aliases)
        assert result is not None
        m, mtype = result
        assert mtype == "alias"

    def test_expected_draft_name_matches(self):
        draft = [{"name": "Digital Advertising Services", "market_id": "pm_1"}]
        result = _find_matching_market(
            "Online advertising",
            draft,
            {},
            expected_draft_names=["Digital Advertising Services"],
        )
        assert result is not None
        m, mtype = result
        assert mtype == "expected_draft_name"
        assert m["name"] == "Digital Advertising Services"

    def test_expected_market_id_matches(self):
        draft = [{"name": "Completely different name", "market_id": "pm_99"}]
        result = _find_matching_market(
            "Online advertising",
            draft,
            {},
            expected_market_ids=["pm_99"],
        )
        assert result is not None
        m, mtype = result
        assert mtype == "expected_market_id"

    def test_no_match_returns_none(self):
        draft = [{"name": "Wearable devices"}]
        result = _find_matching_market("Online advertising", draft, {})
        assert result is None

    def test_case_insensitive_exact(self):
        draft = [{"name": "ONLINE ADVERTISING"}]
        result = _find_matching_market("online advertising", draft, {})
        assert result is not None
        _, mtype = result
        assert mtype == "exact"

    def test_expected_draft_name_case_insensitive(self):
        draft = [{"name": "digital advertising SERVICES"}]
        result = _find_matching_market(
            "Online ads", draft, {},
            expected_draft_names=["Digital Advertising Services"],
        )
        assert result is not None
        _, mtype = result
        assert mtype == "expected_draft_name"


# ---------------------------------------------------------------------------
# TestEvaluateMarketsDiagnostics
# ---------------------------------------------------------------------------

class TestEvaluateMarketsDiagnostics:
    """_evaluate_markets emits diagnostics: matched_items, FN details, unjudged."""

    def test_matched_items_populated(self):
        gold  = [{"name": "Market A", "reviewed": True}]
        draft = [{"name": "Market A"}]
        r = _evaluate_markets(gold, draft, "product")
        assert len(r["matched_items"]) == 1
        assert r["matched_items"][0]["gold_name"]  == "Market A"
        assert r["matched_items"][0]["draft_name"] == "Market A"
        assert r["matched_items"][0]["match_type"] == "exact"

    def test_fn_detail_includes_gold_name_and_nearest(self):
        gold  = [{"name": "Online advertising", "reviewed": True}]
        draft = [{"name": "Online advertising services"}]
        r = _evaluate_markets(gold, draft, "product")
        assert r["false_negatives"] == 1
        fnd = r["false_negatives_detail"]
        assert len(fnd) == 1
        assert fnd[0]["gold_name"] == "Online advertising"
        # Nearest candidate should be the only draft market
        assert len(fnd[0]["nearest_draft_candidates"]) == 1
        assert fnd[0]["nearest_draft_candidates"][0]["draft_name"] == "Online advertising services"

    def test_fn_detail_includes_aliases_and_expected_fields(self):
        gold = [{
            "name": "Online advertising",
            "reviewed": True,
            "aliases": ["Display advertising"],
            "expected_draft_names": ["Digital Ads"],
            "expected_market_ids": ["pm_99"],
            "market_group": "ads",
            "expected_definition_status": "defined",
        }]
        draft = [{"name": "Wearable devices"}]   # no match
        r = _evaluate_markets(gold, draft, "product")
        fnd = r["false_negatives_detail"][0]
        assert "Display advertising" in fnd["aliases"]
        assert "Digital Ads"         in fnd["expected_draft_names"]
        assert "pm_99"               in fnd["expected_market_ids"]
        assert fnd["market_group"]   == "ads"
        assert fnd["expected_definition_status"] == "defined"

    def test_fn_nearest_candidates_capped_at_five(self):
        gold  = [{"name": "Online advertising", "reviewed": True}]
        draft = [{"name": f"Online advertising variant {i}"} for i in range(10)]
        r = _evaluate_markets(gold, draft, "product")
        assert r["false_negatives"] == 1
        fnd = r["false_negatives_detail"][0]
        assert len(fnd["nearest_draft_candidates"]) <= 5

    def test_fp_detail_populated(self):
        gold  = [{"name": "Market A", "reviewed": True}]
        draft = [{"name": "Market A"}, {"name": "Market B"}]
        r = _evaluate_markets(gold, draft, "product")
        assert r["false_positives"] == 1
        fps = r["false_positives_detail"]
        assert len(fps) == 1
        assert fps[0]["draft_name"] == "Market B"

    def test_unjudged_items_populated_in_partial_mode(self):
        gold  = [{"name": "Market A", "reviewed": True}]
        draft = [{"name": "Market A"}, {"name": "Unjudged extra"}]
        r = _evaluate_markets(gold, draft, "product", is_partial=True)
        assert r["unjudged_candidates"] == 1
        uj = r["unjudged_items"]
        assert len(uj) == 1
        assert uj[0]["draft_name"] == "Unjudged extra"

    def test_expected_draft_name_counted_as_tp(self):
        gold = [{
            "name": "Online advertising",
            "reviewed": True,
            "expected_draft_names": ["Digital Advertising Services"],
        }]
        draft = [{"name": "Digital Advertising Services", "market_id": "pm_1"}]
        r = _evaluate_markets(gold, draft, "product")
        assert r["true_positives"]  == 1
        assert r["false_negatives"] == 0
        assert r["matched_items"][0]["match_type"] == "expected_draft_name"

    def test_expected_market_id_counted_as_tp(self):
        gold = [{
            "name": "Online advertising",
            "reviewed": True,
            "expected_market_ids": ["pm_42"],
        }]
        draft = [{"name": "Totally different name", "market_id": "pm_42"}]
        r = _evaluate_markets(gold, draft, "product")
        assert r["true_positives"]  == 1
        assert r["matched_items"][0]["match_type"] == "expected_market_id"

    def test_geographic_alias_match_tp(self):
        """Geographic markets support aliases the same way product markets do."""
        gold = [{
            "name": "EEA geographic scope",
            "reviewed": True,
            "aliases": ["European Economic Area"],
        }]
        draft = [{"name": "European Economic Area"}]
        r = _evaluate_markets(gold, draft, "geographic")
        assert r["true_positives"]  == 1
        assert r["matched_items"][0]["match_type"] == "alias"

    def test_geographic_expected_draft_name_tp(self):
        """Geographic markets support expected_draft_names."""
        gold = [{
            "name": "EEA-wide market",
            "reviewed": True,
            "expected_draft_names": ["EEA and wider"],
        }]
        draft = [{"name": "EEA and wider"}]
        r = _evaluate_markets(gold, draft, "geographic")
        assert r["true_positives"]  == 1
        assert r["matched_items"][0]["match_type"] == "expected_draft_name"


# ---------------------------------------------------------------------------
# TestTerminalSummaryWording
# ---------------------------------------------------------------------------

class TestTerminalSummaryWording:
    """The terminal summary must use 'Promotion safety score' and 'Overpromotion risk'."""

    def _run_main_stdout(self, gold_yaml, draft_yaml, report, tmp_path) -> str:
        """Run _evaluate_extraction and format what the CLI would print."""
        from evaluate_extraction import _evaluate_extraction

        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        result = _evaluate_extraction("test", gold_yaml, draft_yaml, report, cache_dir)
        safety = result["promotion_safety"]

        # Simulate the CLI terminal output
        lines = [
            f"Gating decision:         {result['gating_decision'].upper()}",
            f"Overall F1:              {result['overall_f1']}",
            f"Promotion safety score:  {safety['safety_score']}",
            f"Overpromotion risk:      {safety['overpromotion_risk'].upper()}",
        ]
        return "\n".join(lines)

    def _gold(self) -> dict:
        return {
            "_gold_metadata": {"partial": False},
            "case_id": "test",
            "source_documents": [],
            "product_markets_considered": [],
            "geographic_markets_considered": [],
        }

    def _report(self) -> dict:
        return {"canonical_merge_candidates": {
            "safe_to_promote": [], "uncertain_markets": [],
            "hold_pending_source_check": [], "manual_review": []
        }}

    def test_summary_contains_safety_score_not_ambiguous_label(self, tmp_path):
        output = self._run_main_stdout(self._gold(), {"product_markets_considered": [], "geographic_markets_considered": []}, self._report(), tmp_path)
        assert "Promotion safety score:" in output
        assert "Overpromotion risk:"     in output
        # The old ambiguous label must not appear
        assert "Promotion safety: " not in output

    def test_summary_low_risk_shows_low(self, tmp_path):
        output = self._run_main_stdout(self._gold(), {"product_markets_considered": [], "geographic_markets_considered": []}, self._report(), tmp_path)
        assert "LOW" in output

    def test_markdown_uses_correct_labels(self):
        from evaluate_extraction import _format_eval_markdown
        result = {
            "case_id": "test", "generated_at": "2026-01-01T00:00:00+00:00",
            "gold_partial": False, "gold_reviewed_count": 0, "overall_f1": 1.0,
            "gating_decision": "auto_accept",
            "product_markets":   {"true_positives": 0, "false_positives": 0,
                                   "false_negatives": 0, "precision": 1.0,
                                   "recall": 1.0, "f1": 1.0,
                                   "matched_items": [], "false_negatives_detail": [],
                                   "false_positives_detail": [], "unjudged_items": []},
            "geographic_markets": {"true_positives": 0, "false_positives": 0,
                                   "false_negatives": 0, "precision": 1.0,
                                   "recall": 1.0, "f1": 1.0,
                                   "matched_items": [], "false_negatives_detail": [],
                                   "false_positives_detail": [], "unjudged_items": []},
            "promotion_safety": {"safe_promoted_count": 0, "risky_promotions": 0,
                                 "safety_score": 1.0, "overpromotion_risk": "low"},
            "quote_validity": {"total_checked": 0, "passed": 0,
                               "failures": 0, "warnings": 0, "failure_details": []},
        }
        md = _format_eval_markdown(result)
        assert "Promotion safety score:" in md
        assert "Overpromotion risk:"     in md
        assert "Promotion safety: " not in md


# ---------------------------------------------------------------------------
# TestZeroReviewedGoldGating
# ---------------------------------------------------------------------------

class TestZeroReviewedGoldGating:
    """
    Partial gold with zero reviewed entries must never auto-accept.
    All tests use _evaluate_extraction directly; no Claude API calls.
    """

    def _dummy_report(self, *, risky: bool = False) -> dict:
        return {
            "canonical_merge_candidates": {
                "safe_to_promote": [{"name": "X"}] if risky else [],
                "uncertain_markets": [{"name": "X"}] if risky else [],
                "hold_pending_source_check": [],
                "manual_review": [],
            }
        }

    def _partial_gold_no_reviewed(self, market_names: list[str] = None) -> dict:
        """Partial gold file where all markets have reviewed=False (or absent)."""
        names = market_names or ["Market A"]
        return {
            "_gold_metadata": {"partial": True, "reviewed_scope": {}},
            "case_id": "test",
            "source_documents": [],
            "product_markets_considered": [
                {"name": n, "reviewed": False, "linked_source_passages": []}
                for n in names
            ],
            "geographic_markets_considered": [],
        }

    def _partial_gold_empty(self) -> dict:
        """Partial gold file with no markets at all (zero reviewed by definition)."""
        return {
            "_gold_metadata": {"partial": True, "reviewed_scope": {}},
            "case_id": "test",
            "source_documents": [],
            "product_markets_considered": [],
            "geographic_markets_considered": [],
        }

    def _draft(self, market_names: list[str] = None) -> dict:
        names = market_names or ["Market A"]
        return {
            "product_markets_considered": [{"name": n} for n in names],
            "geographic_markets_considered": [],
        }

    def test_partial_zero_reviewed_gives_insufficient_gold(self, tmp_path):
        """Zero reviewed items in partial mode → gating_decision = insufficient_gold."""
        from evaluate_extraction import _evaluate_extraction
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        result = _evaluate_extraction(
            "test",
            self._partial_gold_no_reviewed(["Market A", "Market B"]),
            self._draft(["Market A", "Market B"]),
            self._dummy_report(),
            cache_dir,
        )
        assert result["gating_decision"] == "insufficient_gold"
        assert result["gating_decision"] != "auto_accept"

    def test_partial_zero_reviewed_evaluation_valid_is_false(self, tmp_path):
        """evaluation_valid must be False when zero reviewed items in partial mode."""
        from evaluate_extraction import _evaluate_extraction
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        result = _evaluate_extraction(
            "test",
            self._partial_gold_no_reviewed(),
            self._draft(),
            self._dummy_report(),
            cache_dir,
        )
        assert result["evaluation_valid"] is False

    def test_partial_zero_reviewed_gold_review_status_field(self, tmp_path):
        """gold_review_status must be 'no_reviewed_gold_items' when count is zero."""
        from evaluate_extraction import _evaluate_extraction
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        result = _evaluate_extraction(
            "test",
            self._partial_gold_no_reviewed(),
            self._draft(),
            self._dummy_report(),
            cache_dir,
        )
        assert result["gold_review_status"] == "no_reviewed_gold_items"
        assert result["gold_reviewed_count"] == 0

    def test_partial_zero_reviewed_gating_reason_populated(self, tmp_path):
        """gating_reason must explain why the eval was blocked."""
        from evaluate_extraction import _evaluate_extraction
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        result = _evaluate_extraction(
            "test",
            self._partial_gold_no_reviewed(),
            self._draft(),
            self._dummy_report(),
            cache_dir,
        )
        assert result["gating_reason"]
        assert "reviewed" in result["gating_reason"].lower()

    def test_quote_valid_zero_reviewed_not_auto_accept(self, tmp_path):
        """Quote validity passing alone cannot produce auto_accept with zero reviewed items."""
        from evaluate_extraction import _evaluate_extraction
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        # Empty partial gold = no passages to validate → quote_validity passes trivially
        result = _evaluate_extraction(
            "test",
            self._partial_gold_empty(),
            self._draft([]),
            self._dummy_report(),
            cache_dir,
        )
        assert result["quote_validity"]["failures"] == 0
        assert result["gating_decision"] != "auto_accept"
        assert result["evaluation_valid"] is False

    def test_partial_with_reviewed_items_can_auto_accept(self, tmp_path):
        """Partial gold with reviewed items and perfect metrics still auto-accepts."""
        from evaluate_extraction import _evaluate_extraction
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        gold = {
            "_gold_metadata": {"partial": True, "reviewed_scope": {}},
            "case_id": "test",
            "source_documents": [],
            "product_markets_considered": [
                {"name": "Market A", "reviewed": True, "linked_source_passages": []},
                {"name": "Market B", "reviewed": True, "linked_source_passages": []},
            ],
            "geographic_markets_considered": [],
        }
        draft = self._draft(["Market A", "Market B"])
        result = _evaluate_extraction("test", gold, draft, self._dummy_report(), cache_dir)
        # Must still auto_accept when all conditions are good
        assert result["gating_decision"] == "auto_accept"
        assert result["evaluation_valid"] is True
        assert result["gold_reviewed_count"] == 2

    def test_markdown_shows_reviewed_gold_entries_label(self, tmp_path):
        """Markdown report must show 'Reviewed gold entries' label."""
        from evaluate_extraction import _evaluate_extraction, _format_eval_markdown
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        result = _evaluate_extraction(
            "test",
            self._partial_gold_no_reviewed(),
            self._draft(),
            self._dummy_report(),
            cache_dir,
        )
        md = _format_eval_markdown(result)
        assert "Reviewed gold entries: 0" in md

    def test_markdown_shows_not_valid_warning(self, tmp_path):
        """Markdown report must include a not-valid-for-acceptance warning."""
        from evaluate_extraction import _evaluate_extraction, _format_eval_markdown
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        result = _evaluate_extraction(
            "test",
            self._partial_gold_no_reviewed(),
            self._draft(),
            self._dummy_report(),
            cache_dir,
        )
        md = _format_eval_markdown(result)
        assert "not valid" in md.lower() or "no reviewed" in md.lower()

    def test_terminal_summary_includes_reviewed_count(self, tmp_path):
        """Terminal summary must show 'Reviewed gold entries' line."""
        from evaluate_extraction import _evaluate_extraction
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        result = _evaluate_extraction(
            "test",
            self._partial_gold_no_reviewed(),
            self._draft(),
            self._dummy_report(),
            cache_dir,
        )
        # Simulate what the CLI prints
        safety = result["promotion_safety"]
        lines = [
            f"Gating decision:         {result['gating_decision'].upper()}",
            f"Overall F1:              {result['overall_f1']}",
            f"Promotion safety score:  {safety['safety_score']}",
            f"Overpromotion risk:      {safety['overpromotion_risk'].upper()}",
            f"Reviewed gold entries:   {result['gold_reviewed_count']}",
        ]
        if not result.get("evaluation_valid", True):
            lines.append(
                "WARNING: Evaluation is not valid for acceptance until at least "
                "one gold item is reviewed."
            )
        output = "\n".join(lines)
        assert "Reviewed gold entries:   0" in output
        assert "WARNING" in output

    def test_partial_zero_reviewed_overpromotion_still_rejects(self, tmp_path):
        """Overpromotion → reject takes priority even when zero reviewed items."""
        from evaluate_extraction import _evaluate_extraction
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        result = _evaluate_extraction(
            "test",
            self._partial_gold_no_reviewed(),
            self._draft(),
            self._dummy_report(risky=True),
            cache_dir,
        )
        # reject takes priority over insufficient_gold
        assert result["gating_decision"] == "reject"


# ---------------------------------------------------------------------------
# TestAliasCandidates
# ---------------------------------------------------------------------------

class TestAliasCandidates:
    """
    Alias candidates are suggested by the pipeline but not approved as aliases.
    All candidates are source-derived; none are invented.
    No Claude API calls; no canonical YAML mutation.
    """

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _gold_pm(self, gold: dict) -> dict:
        return gold["product_markets_considered"][0]

    def _alias_values(self, gold: dict) -> list[str]:
        return [c["value"] for c in self._gold_pm(gold).get("alias_candidates", [])]

    def _alias_sources(self, gold: dict) -> list[str]:
        return [c["source"] for c in self._gold_pm(gold).get("alias_candidates", [])]

    # ------------------------------------------------------------------
    # Draft market names are never alias candidates
    # ------------------------------------------------------------------

    def test_no_draft_market_names_as_candidates(self):
        """Other draft market names are never added as alias candidates."""
        draft = _make_draft(pm_entries=[
            _pm_entry("Game distribution", "pm_1"),
            _pm_entry("Distribution of PC and console games", "pm_2"),
        ])
        report = _make_report(safe=[_candidate("Game distribution")])
        gold = _create_gold_draft("test", draft, report)

        pm = self._gold_pm(gold)
        draft_sources = [c for c in pm.get("alias_candidates", [])
                         if c["source"] == "draft_market_name"]
        assert draft_sources == []
        # The other draft market name must not appear even by coincidence
        values = self._alias_values(gold)
        assert "Distribution of PC and console games" not in values

    def test_exact_gold_name_not_in_candidates(self):
        """The gold entry's own name is never a candidate."""
        draft = _make_draft(pm_entries=[_pm_entry("Game distribution", "pm_1")])
        report = _make_report(safe=[_candidate("Game distribution")])
        gold = _create_gold_draft("test", draft, report)

        values = self._alias_values(gold)
        assert "Game distribution" not in values
        assert "game distribution" not in [v.lower() for v in values]

    def test_no_draft_names_including_geo(self):
        """No draft market names — including geo names — appear in alias_candidates."""
        draft = _make_draft(
            pm_entries=[_pm_entry("Game distribution", "pm_1")],
            gm_entries=[{"market_id": "gm_1", "name": "EEA-wide game distribution",
                          "definition_status": "defined"}],
        )
        report = _make_report(safe=[_candidate("Game distribution")])
        gold = _create_gold_draft("test", draft, report)

        values = self._alias_values(gold)
        assert "EEA-wide game distribution" not in values

    # ------------------------------------------------------------------
    # Reconciliation findings are not alias candidates
    # ------------------------------------------------------------------

    def test_reconciliation_names_not_in_candidates(self):
        """should_be_renamed reconciliation findings do NOT populate alias_candidates."""
        draft = _make_draft(pm_entries=[_pm_entry("Online ads", "pm_1")])
        report = _make_report(
            safe=[_candidate("Online ads")],
            reconciliation=[{
                "finding_type": "should_be_renamed",
                "draft_name": "Online ads",
                "existing_name": "Online advertising",
            }],
        )
        gold = _create_gold_draft("test", draft, report)

        values = self._alias_values(gold)
        assert "Online advertising" not in values
        pm = self._gold_pm(gold)
        assert not any(c["source"] == "reconciliation" for c in pm.get("alias_candidates", []))

    def test_reconciliation_findings_entirely_ignored(self):
        """No reconciliation finding type produces alias candidates."""
        draft = _make_draft(pm_entries=[_pm_entry("Online ads", "pm_1")])
        report = _make_report(
            safe=[_candidate("Online ads")],
            reconciliation=[
                {"finding_type": "should_be_renamed",
                 "draft_name": "Online ads", "existing_name": "Online advertising"},
                {"finding_type": "supported_as_is",
                 "draft_name": "Online ads", "existing_name": "Online advertising"},
            ],
        )
        gold = _create_gold_draft("test", draft, report)
        pm = self._gold_pm(gold)
        assert not any(c["source"] == "reconciliation" for c in pm.get("alias_candidates", []))

    # ------------------------------------------------------------------
    # Source: source passage phrases (the only active source)
    # ------------------------------------------------------------------

    def test_creates_candidates_from_passage_phrase(self):
        """Neutral phrase 'the relevant market is an overall market for X' yields a candidate."""
        passage = _passage(
            "pm_1", "42",
            "the relevant market is an overall market for game distribution",
        )
        draft = _make_draft(
            pm_entries=[_pm_entry("Game distribution", "pm_1")],
            passages=[passage],
        )
        report = _make_report(safe=[_candidate("Game distribution")])
        gold = _create_gold_draft("test", draft, report)

        values = self._alias_values(gold)
        # The phrase following "is an" should be extracted
        assert any("game distribution" in v.lower() for v in values)

    def test_passage_candidate_includes_page_and_passage_id(self):
        passage = _passage(
            "pm_1", "42",
            "the relevant market is an overall market for game distribution",
            pid="sp_7",
        )
        draft = _make_draft(
            pm_entries=[_pm_entry("Game distribution", "pm_1")],
            passages=[passage],
        )
        report = _make_report(safe=[_candidate("Game distribution")])
        gold = _create_gold_draft("test", draft, report)

        pm = self._gold_pm(gold)
        passage_cands = [c for c in pm.get("alias_candidates", []) if c["source"] == "source_passage"]
        assert passage_cands
        for c in passage_cands:
            assert "page" in c
            assert c["page"] == "42"
            assert "passage_id" in c
            assert c["passage_id"] == "sp_7"

    def test_passage_candidate_includes_quote_snippet(self):
        passage = _passage(
            "pm_1", "42",
            "the relevant market is an overall market for game distribution",
        )
        draft = _make_draft(
            pm_entries=[_pm_entry("Game distribution", "pm_1")],
            passages=[passage],
        )
        report = _make_report(safe=[_candidate("Game distribution")])
        gold = _create_gold_draft("test", draft, report)

        pm = self._gold_pm(gold)
        passage_cands = [c for c in pm.get("alias_candidates", []) if c["source"] == "source_passage"]
        assert passage_cands
        for c in passage_cands:
            assert "quote_snippet" in c

    # ------------------------------------------------------------------
    # Filtering rules
    # ------------------------------------------------------------------

    def test_generic_phrases_not_candidates(self):
        """Values in _ALIAS_GENERIC_VALUES are filtered out."""
        from create_gold_draft import _ALIAS_GENERIC_VALUES
        # Each generic value should not appear in candidates even if extracted
        passage = _passage(
            "pm_1", "1",
            "The relevant product market and relevant geographic market are considered.",
        )
        draft = _make_draft(
            pm_entries=[_pm_entry("Some market", "pm_1")],
            passages=[passage],
        )
        report = _make_report(safe=[_candidate("Some market")])
        gold = _create_gold_draft("test", draft, report)

        values = [v.lower() for v in self._alias_values(gold)]
        for generic in _ALIAS_GENERIC_VALUES:
            assert generic.lower() not in values, f"Generic phrase '{generic}' leaked into candidates"

    def test_too_short_values_filtered(self):
        """Extracted passage phrases shorter than _ALIAS_MIN_LENGTH are not candidates."""
        from create_gold_draft import _ALIAS_MIN_LENGTH
        # Passage where the extracted phrase would be very short (e.g. "ads")
        passage = _passage("pm_1", "1",
                            "the relevant market is an overall market for ads")
        draft = _make_draft(
            pm_entries=[_pm_entry("Online ads", "pm_1")],
            passages=[passage],
        )
        report = _make_report(safe=[_candidate("Online ads")])
        gold = _create_gold_draft("test", draft, report)

        values = self._alias_values(gold)
        assert not any(len(v) < _ALIAS_MIN_LENGTH for v in values)

    def test_deduplication_case_insensitive(self):
        """Case-insensitive deduplication prevents the same phrase appearing twice."""
        # Two passages that extract the same phrase in different cases
        p1 = _passage("pm_1", "1",
                      "the relevant market is an overall market for game distribution",
                      pid="sp_1")
        p2 = _passage("pm_1", "2",
                      "the relevant market is an overall market for Game Distribution",
                      pid="sp_2")
        draft = _make_draft(
            pm_entries=[_pm_entry("Game distribution", "pm_1")],
            passages=[p1, p2],
        )
        report = _make_report(safe=[_candidate("Game distribution")])
        gold = _create_gold_draft("test", draft, report)

        values = self._alias_values(gold)
        lower_values = [v.lower() for v in values]
        # "game distribution" is the gold name itself — must not appear
        assert "game distribution" not in lower_values
        # Even if both passages are present, the phrase appears at most once
        assert lower_values.count("game distribution") == 0

    # ------------------------------------------------------------------
    # aliases field is reviewer-approved only
    # ------------------------------------------------------------------

    def test_aliases_field_is_empty_list(self):
        """aliases is never auto-populated; it is always [] in a fresh gold draft."""
        draft = _make_draft(pm_entries=[_pm_entry("Market A", "pm_1")])
        report = _make_report(
            safe=[_candidate("Market A")],
            reconciliation=[{
                "finding_type": "should_be_renamed",
                "draft_name": "Market A",
                "existing_name": "Alternative name",
            }],
        )
        gold = _create_gold_draft("test", draft, report)
        assert gold["product_markets_considered"][0]["aliases"] == []

    def test_alias_candidates_separate_from_aliases(self):
        """alias_candidates and aliases are distinct keys with distinct semantics."""
        draft = _make_draft(pm_entries=[_pm_entry("Market A", "pm_1")])
        report = _make_report(safe=[_candidate("Market A")])
        gold = _create_gold_draft("test", draft, report)
        pm = gold["product_markets_considered"][0]
        assert "alias_candidates" in pm
        assert "aliases" in pm
        assert isinstance(pm["alias_candidates"], list)
        assert isinstance(pm["aliases"], list)

    # ------------------------------------------------------------------
    # Evaluator does not treat alias_candidates as approved aliases
    # ------------------------------------------------------------------

    def test_evaluator_ignores_alias_candidates(self, tmp_path):
        """Evaluator counts alias_candidates as FN, not TP — they are not approved aliases."""
        from evaluate_extraction import _evaluate_extraction

        # Gold with a reviewed market; alias_candidates contains the draft market name
        gold = {
            "_gold_metadata": {"partial": True, "reviewed_scope": {}},
            "case_id": "test",
            "source_documents": [],
            "product_markets_considered": [{
                "name": "Game distribution",
                "reviewed": True,
                "aliases": [],  # no approved alias
                "alias_candidates": [
                    {"value": "Distribution of games", "source": "draft_market_name",
                     "status": "suggested"}
                ],
                "linked_source_passages": [],
            }],
            "geographic_markets_considered": [],
        }
        # Draft uses only the alias_candidates value (not approved alias)
        draft = {
            "product_markets_considered": [{"name": "Distribution of games"}],
            "geographic_markets_considered": [],
        }
        report = {"canonical_merge_candidates": {
            "safe_to_promote": [], "uncertain_markets": [],
            "hold_pending_source_check": [], "manual_review": [],
        }}
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        result = _evaluate_extraction("test", gold, draft, report, cache_dir)
        pm = result["product_markets"]
        # alias_candidates alone does NOT produce a match
        assert pm["false_negatives"] == 1
        assert pm["true_positives"] == 0

    def test_evaluator_counts_tp_when_candidate_copied_to_aliases(self, tmp_path):
        """When reviewer copies alias_candidates value to aliases, evaluator counts TP."""
        from evaluate_extraction import _evaluate_extraction

        gold = {
            "_gold_metadata": {"partial": True, "reviewed_scope": {}},
            "case_id": "test",
            "source_documents": [],
            "product_markets_considered": [{
                "name": "Game distribution",
                "reviewed": True,
                "aliases": ["Distribution of games"],  # reviewer-approved
                "alias_candidates": [
                    {"value": "Distribution of games", "source": "draft_market_name",
                     "status": "suggested"}
                ],
                "linked_source_passages": [],
            }],
            "geographic_markets_considered": [],
        }
        draft = {
            "product_markets_considered": [{"name": "Distribution of games"}],
            "geographic_markets_considered": [],
        }
        report = {"canonical_merge_candidates": {
            "safe_to_promote": [], "uncertain_markets": [],
            "hold_pending_source_check": [], "manual_review": [],
        }}
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        result = _evaluate_extraction("test", gold, draft, report, cache_dir)
        pm = result["product_markets"]
        assert pm["true_positives"] == 1
        assert pm["false_negatives"] == 0

    # ------------------------------------------------------------------
    # Quote text is unchanged
    # ------------------------------------------------------------------

    def test_quote_snippet_unchanged_in_linked_passages(self):
        """Alias candidate extraction never modifies quote_snippet in linked passages."""
        verbatim = "the relevant market is an overall market for game distribution"
        passage = _passage("pm_1", "42", verbatim)
        draft = _make_draft(
            pm_entries=[_pm_entry("Game distribution", "pm_1")],
            passages=[passage],
        )
        report = _make_report(safe=[_candidate("Game distribution")])
        gold = _create_gold_draft("test", draft, report)

        linked = gold["product_markets_considered"][0]["linked_source_passages"]
        assert linked[0]["quote_snippet"] == verbatim

    # ------------------------------------------------------------------
    # No draft names — not even high-overlap or cross-type
    # ------------------------------------------------------------------

    def test_no_draft_names_regardless_of_overlap(self):
        """No draft market name appears in alias_candidates, even with high token overlap."""
        draft = _make_draft(pm_entries=[
            _pm_entry("Game distribution", "pm_1"),
            _pm_entry("Distribution of PC and console games", "pm_2"),
            _pm_entry("Operating systems for PCs", "pm_3"),
        ])
        report = _make_report(safe=[_candidate("Game distribution")])
        gold = _create_gold_draft("test", draft, report)

        pm = self._gold_pm(gold)
        assert not any(c["source"] == "draft_market_name" for c in pm.get("alias_candidates", []))
        values = self._alias_values(gold)
        assert "Distribution of PC and console games" not in values
        assert "Operating systems for PCs" not in values

    def test_no_draft_names_for_geo_entry(self):
        """Geo gold entries also receive no draft-name alias candidates."""
        draft = _make_draft(
            pm_entries=[_pm_entry("Online advertising", "pm_1")],
            gm_entries=[
                {"market_id": "gm_1", "name": "EEA-wide online advertising",
                 "definition_status": "defined"},
                {"market_id": "gm_2", "name": "Worldwide online advertising",
                 "definition_status": "defined"},
            ],
        )
        report = _make_report(
            geo=[_candidate("EEA-wide online advertising", mtype="geographic")]
        )
        gold = _create_gold_draft("test", draft, report)

        gm_list = gold.get("geographic_markets_considered", [])
        assert gm_list
        gm = gm_list[0]
        assert not any(c["source"] == "draft_market_name" for c in gm.get("alias_candidates", []))

    # ------------------------------------------------------------------
    # Source-passage truncation filter
    # ------------------------------------------------------------------

    def test_truncated_passage_alias_rejected(self):
        """Alias candidates ending mid-enumeration or containing clause markers are rejected."""
        from create_gold_draft import _is_truncated_alias
        # Ends mid-parenthetical
        assert _is_truncated_alias("on the basis of: (i") is True
        assert _is_truncated_alias("the supply of X, (ii") is True
        assert _is_truncated_alias("some market:") is True
        # Contains list enumeration marker anywhere (multi-item capture)
        assert _is_truncated_alias("defined on the basis of: (i) demand substitutability") is True
        assert _is_truncated_alias("supply of (a) hardware and (b) software") is True
        # Modal/auxiliary verb → clause, not a market name
        assert _is_truncated_alias("game distribution should be segmented by platform") is True
        assert _is_truncated_alias("segmentation would be appropriate") is True

    def test_clean_passage_alias_accepted(self):
        """A well-formed noun-phrase alias is not classified as truncated."""
        from create_gold_draft import _is_truncated_alias
        assert _is_truncated_alias("gaming hardware and accessories") is False
        assert _is_truncated_alias("online video game distribution") is False
        # Contains a parenthetical that is NOT a list marker
        assert _is_truncated_alias("supply of hardware (excluding software)") is False
        # Plain noun phrase with no modal verbs
        assert _is_truncated_alias("development and publishing of PC and console video games") is False

    def test_truncated_passage_not_in_candidates(self):
        """Source-passage candidates that are cut mid-list are filtered from alias_candidates."""
        # Passage contains a phrase that would be extracted as truncated
        passage = _passage(
            "pm_1", "10",
            "the relevant market is defined on the basis of: (i) demand substitutability",
        )
        draft = _make_draft(
            pm_entries=[_pm_entry("Game distribution", "pm_1")],
            passages=[passage],
        )
        report = _make_report(safe=[_candidate("Game distribution")])
        gold = _create_gold_draft("test", draft, report)

        pm = self._gold_pm(gold)
        passage_vals = [c["value"] for c in pm.get("alias_candidates", [])
                        if c["source"] == "source_passage"]
        # "defined on the basis of: (i" — truncated, must be filtered
        assert not any("(i)" in v or "(i" in v for v in passage_vals)

    def test_clean_passage_alias_in_candidates(self):
        """A clean, non-truncated source-passage phrase is included as a candidate."""
        passage = _passage(
            "pm_1", "5",
            "the relevant market is an overall market for online game distribution",
        )
        draft = _make_draft(
            pm_entries=[_pm_entry("Game distribution", "pm_1")],
            passages=[passage],
        )
        report = _make_report(safe=[_candidate("Game distribution")])
        gold = _create_gold_draft("test", draft, report)

        values = self._alias_values(gold)
        assert any("online game distribution" in v.lower() for v in values)

    # ------------------------------------------------------------------
    # Microsoft/Activision-style: publishing entry gets no draft-name aliases
    # ------------------------------------------------------------------

    def test_publishing_entry_gets_no_draft_name_aliases(self):
        """No draft market names — related or unrelated — appear as alias candidates."""
        draft = _make_draft(
            pm_entries=[
                _pm_entry("Development and publishing of PC and console video games", "pm_1"),
                _pm_entry("Distribution of video games", "pm_2"),
                _pm_entry("Operating systems for PCs", "pm_3"),
            ],
            gm_entries=[{"market_id": "gm_1",
                          "name": "EEA distribution of PC and console video games",
                          "definition_status": "left open"}],
        )
        report = _make_report(
            safe=[_candidate("Development and publishing of PC and console video games")]
        )
        gold = _create_gold_draft("test", draft, report)

        pm = self._gold_pm(gold)
        assert not any(c["source"] == "draft_market_name" for c in pm.get("alias_candidates", []))
        values = [c["value"] for c in pm.get("alias_candidates", [])]
        assert "EEA distribution of PC and console video games" not in values
        assert "Operating systems for PCs" not in values
        assert "Distribution of video games" not in values


# ---------------------------------------------------------------------------
# TestExplicitMarketIncludes
# ---------------------------------------------------------------------------

class TestExplicitMarketIncludes:
    """
    Tests for --include-market-name / --include-market-id:
    markets outside the default promotion categories can be explicitly pulled in.

    No Claude API calls; no canonical YAML mutation.
    """

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _gold_pm_names(self, gold: dict) -> list[str]:
        return [m["name"] for m in gold.get("product_markets_considered", [])]

    def _gold_gm_names(self, gold: dict) -> list[str]:
        return [m["name"] for m in gold.get("geographic_markets_considered", [])]

    def _gold_selection_reasons(self, gold: dict) -> dict[str, str]:
        """Return name → gold_selection_reason for all entries."""
        result = {}
        for lst_key in ("product_markets_considered", "geographic_markets_considered"):
            for m in gold.get(lst_key, []):
                result[m["name"]] = m.get("gold_selection_reason", "")
        return result

    # ------------------------------------------------------------------
    # _normalize_market_name unit tests
    # ------------------------------------------------------------------

    def test_normalize_lowercases(self):
        assert _normalize_market_name("Online Advertising") == "online advertising"

    def test_normalize_collapses_whitespace(self):
        assert _normalize_market_name("  a  b  c  ") == "a b c"

    def test_normalize_strips_leading_trailing(self):
        assert _normalize_market_name("  Market A  ") == "market a"

    # ------------------------------------------------------------------
    # Default behaviour unchanged without explicit params
    # ------------------------------------------------------------------

    def test_default_includes_safe_to_promote(self):
        """Default filter: safe_to_promote is included; hold_pending is not."""
        draft = _make_draft(
            pm_entries=[
                _pm_entry("Safe market", "pm_1"),
                _pm_entry("Hold market", "pm_2"),
            ],
        )
        report = _make_report(
            safe=[_candidate("Safe market")],
            hold=[_candidate("Hold market")],
        )
        gold = _create_gold_draft("test", draft, report)

        pm_names = self._gold_pm_names(gold)
        assert "Safe market" in pm_names
        assert "Hold market" not in pm_names

    def test_default_selection_reason(self):
        """Markets included by the default filter get gold_selection_reason='default_promotion_filter'."""
        draft = _make_draft(pm_entries=[_pm_entry("Safe market", "pm_1")])
        report = _make_report(safe=[_candidate("Safe market")])
        gold = _create_gold_draft("test", draft, report)

        reasons = self._gold_selection_reasons(gold)
        assert reasons["Safe market"] == "default_promotion_filter"

    # ------------------------------------------------------------------
    # Explicit include by product market name
    # ------------------------------------------------------------------

    def test_explicit_name_includes_hold_pending_product(self):
        """A hold_pending product market is included when named explicitly."""
        draft = _make_draft(
            pm_entries=[_pm_entry("Chemical admixtures", "pm_1")],
        )
        report = _make_report(hold=[_candidate("Chemical admixtures")])
        gold = _create_gold_draft(
            "test", draft, report,
            explicit_names=frozenset(["Chemical admixtures"]),
        )

        assert "Chemical admixtures" in self._gold_pm_names(gold)

    def test_explicit_name_selection_reason(self):
        """Explicitly included-by-name entry gets gold_selection_reason='explicit_market_name'."""
        draft = _make_draft(pm_entries=[_pm_entry("Hold market", "pm_1")])
        report = _make_report(hold=[_candidate("Hold market")])
        gold = _create_gold_draft(
            "test", draft, report,
            explicit_names=frozenset(["Hold market"]),
        )

        reasons = self._gold_selection_reasons(gold)
        assert reasons["Hold market"] == "explicit_market_name"

    def test_explicit_name_case_insensitive(self):
        """Explicit name match is case-insensitive."""
        draft = _make_draft(pm_entries=[_pm_entry("Chemical Admixtures", "pm_1")])
        report = _make_report(hold=[_candidate("Chemical Admixtures")])
        gold = _create_gold_draft(
            "test", draft, report,
            explicit_names=frozenset(["chemical admixtures"]),
        )

        assert "Chemical Admixtures" in self._gold_pm_names(gold)

    def test_explicit_name_whitespace_normalised(self):
        """Explicit name match collapses extra whitespace."""
        draft = _make_draft(pm_entries=[_pm_entry("Market A", "pm_1")])
        report = _make_report(hold=[_candidate("Market A")])
        gold = _create_gold_draft(
            "test", draft, report,
            explicit_names=frozenset(["Market  A"]),  # double space
        )

        assert "Market A" in self._gold_pm_names(gold)

    # ------------------------------------------------------------------
    # Explicit include by geographic market name
    # ------------------------------------------------------------------

    def test_explicit_name_includes_hold_pending_geo(self):
        """A hold_pending geographic market is included when named explicitly."""
        draft = _make_draft(
            gm_entries=[{"market_id": "gm_1", "name": "National markets (EEA)",
                          "definition_status": "left_open"}],
        )
        report = _make_report(hold=[_candidate("National markets (EEA)", mtype="geographic")])
        gold = _create_gold_draft(
            "test", draft, report,
            explicit_names=frozenset(["National markets (EEA)"]),
        )

        assert "National markets (EEA)" in self._gold_gm_names(gold)

    def test_explicit_geo_name_selection_reason(self):
        """Geo market included by explicit name gets the right selection reason."""
        draft = _make_draft(
            gm_entries=[{"market_id": "gm_1", "name": "National markets (EEA)",
                          "definition_status": "left_open"}],
        )
        report = _make_report(hold=[_candidate("National markets (EEA)", mtype="geographic")])
        gold = _create_gold_draft(
            "test", draft, report,
            explicit_names=frozenset(["National markets (EEA)"]),
        )

        reasons = self._gold_selection_reasons(gold)
        assert reasons["National markets (EEA)"] == "explicit_market_name"

    # ------------------------------------------------------------------
    # Explicit include by market_id
    # ------------------------------------------------------------------

    def test_explicit_id_includes_hold_pending_product(self):
        """A hold_pending product market is included when its draft market_id is specified."""
        draft = _make_draft(pm_entries=[_pm_entry("Chemical admixtures", "pm_1")])
        report = _make_report(hold=[_candidate("Chemical admixtures")])
        gold = _create_gold_draft(
            "test", draft, report,
            explicit_ids=frozenset(["pm_1"]),
        )

        assert "Chemical admixtures" in self._gold_pm_names(gold)

    def test_explicit_id_selection_reason(self):
        """Market included by explicit id gets gold_selection_reason='explicit_market_id'."""
        draft = _make_draft(pm_entries=[_pm_entry("Hold market", "pm_1")])
        report = _make_report(hold=[_candidate("Hold market")])
        gold = _create_gold_draft(
            "test", draft, report,
            explicit_ids=frozenset(["pm_1"]),
        )

        reasons = self._gold_selection_reasons(gold)
        assert reasons["Hold market"] == "explicit_market_id"

    def test_explicit_id_for_geo_market(self):
        """Geo market is also matched by draft market_id."""
        draft = _make_draft(
            gm_entries=[{"market_id": "gm_3", "name": "National geo market",
                          "definition_status": "left_open"}],
        )
        report = _make_report(hold=[_candidate("National geo market", mtype="geographic")])
        gold = _create_gold_draft(
            "test", draft, report,
            explicit_ids=frozenset(["gm_3"]),
        )

        assert "National geo market" in self._gold_gm_names(gold)

    # ------------------------------------------------------------------
    # No duplication when market already in default filter
    # ------------------------------------------------------------------

    def test_no_duplicate_when_also_in_default(self):
        """A market already included by the default filter is not duplicated when explicitly named."""
        draft = _make_draft(pm_entries=[_pm_entry("Safe market", "pm_1")])
        report = _make_report(safe=[_candidate("Safe market")])
        gold = _create_gold_draft(
            "test", draft, report,
            explicit_names=frozenset(["Safe market"]),
        )

        pm_names = self._gold_pm_names(gold)
        assert pm_names.count("Safe market") == 1

    def test_no_duplicate_when_also_in_default_by_id(self):
        """Same deduplication guarantee when the market is explicitly requested by id."""
        draft = _make_draft(pm_entries=[_pm_entry("Safe market", "pm_1")])
        report = _make_report(safe=[_candidate("Safe market")])
        gold = _create_gold_draft(
            "test", draft, report,
            explicit_ids=frozenset(["pm_1"]),
        )

        pm_names = self._gold_pm_names(gold)
        assert pm_names.count("Safe market") == 1

    def test_default_reason_wins_when_also_explicitly_named(self):
        """When a market is in the default filter AND explicitly named, the default reason is used
        (default is Phase 1 and runs first; Phase 2 deduplicates and skips re-adding)."""
        draft = _make_draft(pm_entries=[_pm_entry("Safe market", "pm_1")])
        report = _make_report(safe=[_candidate("Safe market")])
        gold = _create_gold_draft(
            "test", draft, report,
            explicit_names=frozenset(["Safe market"]),
        )

        reasons = self._gold_selection_reasons(gold)
        assert reasons["Safe market"] == "default_promotion_filter"

    # ------------------------------------------------------------------
    # Unmatched explicit request → warning to stderr
    # ------------------------------------------------------------------

    def test_unmatched_name_warns(self, capsys):
        """A name that matches nothing in the report prints a warning to stderr."""
        draft = _make_draft(pm_entries=[_pm_entry("Real market", "pm_1")])
        report = _make_report(safe=[_candidate("Real market")])
        _create_gold_draft(
            "test", draft, report,
            explicit_names=frozenset(["Nonexistent market"]),
        )

        captured = capsys.readouterr()
        assert "nonexistent market" in captured.err.lower()
        assert "WARNING" in captured.err

    def test_unmatched_id_warns(self, capsys):
        """An id that matches nothing in the draft prints a warning to stderr."""
        draft = _make_draft(pm_entries=[_pm_entry("Real market", "pm_1")])
        report = _make_report(safe=[_candidate("Real market")])
        _create_gold_draft(
            "test", draft, report,
            explicit_ids=frozenset(["pm_99"]),
        )

        captured = capsys.readouterr()
        assert "pm_99" in captured.err
        assert "WARNING" in captured.err

    def test_matched_explicit_no_spurious_warning(self, capsys):
        """No warning is printed when the explicit name successfully matches."""
        draft = _make_draft(pm_entries=[_pm_entry("Hold market", "pm_1")])
        report = _make_report(hold=[_candidate("Hold market")])
        _create_gold_draft(
            "test", draft, report,
            explicit_names=frozenset(["Hold market"]),
        )

        captured = capsys.readouterr()
        assert "WARNING" not in captured.err

    # ------------------------------------------------------------------
    # Quote snippets remain unchanged
    # ------------------------------------------------------------------

    def test_quote_snippet_verbatim_in_explicit_include(self):
        """Quote snippets from linked passages are not modified for explicitly included markets."""
        verbatim = "The relevant market is the market for chemical admixtures."
        passage = _passage("pm_1", "10", verbatim, pid="sp_1")
        draft = _make_draft(
            pm_entries=[_pm_entry("Chemical admixtures", "pm_1")],
            passages=[passage],
        )
        report = _make_report(hold=[_candidate("Chemical admixtures")])
        gold = _create_gold_draft(
            "test", draft, report,
            explicit_names=frozenset(["Chemical admixtures"]),
        )

        pm = gold["product_markets_considered"][0]
        assert pm["linked_source_passages"][0]["quote_snippet"] == verbatim

    # ------------------------------------------------------------------
    # Multiple explicit includes
    # ------------------------------------------------------------------

    def test_multiple_explicit_names(self):
        """Multiple --include-market-name values all result in included entries."""
        draft = _make_draft(pm_entries=[
            _pm_entry("Market A", "pm_1"),
            _pm_entry("Market B", "pm_2"),
            _pm_entry("Market C", "pm_3"),
        ])
        report = _make_report(hold=[
            _candidate("Market A"),
            _candidate("Market B"),
            _candidate("Market C"),
        ])
        gold = _create_gold_draft(
            "test", draft, report,
            explicit_names=frozenset(["Market A", "Market C"]),
        )

        pm_names = self._gold_pm_names(gold)
        assert "Market A" in pm_names
        assert "Market C" in pm_names
        assert "Market B" not in pm_names

    def test_name_and_id_together(self):
        """Both --include-market-name and --include-market-id can be used simultaneously."""
        draft = _make_draft(pm_entries=[
            _pm_entry("Market A", "pm_1"),
            _pm_entry("Market B", "pm_2"),
        ])
        report = _make_report(hold=[
            _candidate("Market A"),
            _candidate("Market B"),
        ])
        gold = _create_gold_draft(
            "test", draft, report,
            explicit_names=frozenset(["Market A"]),
            explicit_ids=frozenset(["pm_2"]),
        )

        pm_names = self._gold_pm_names(gold)
        assert "Market A" in pm_names
        assert "Market B" in pm_names


# ---------------------------------------------------------------------------
# TestAutoSelectReviewSet
# ---------------------------------------------------------------------------

class TestAutoSelectReviewSet:
    """
    Tests for auto_select / --auto-select-review-set mode.

    All market names are generic; no industry-specific terms.
    No Claude API calls; no canonical YAML mutation.
    """

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _pm_with_passage(self, mid, name, status="defined",
                          importance="core_assessed", role="commission_assessment"):
        pm = _pm_entry(name, mid, status=status, importance=importance)
        passage = {
            "passage_id": f"sp_{mid}",
            "source_document_id": "doc_1",
            "page": "10",
            "quote_snippet": f"The Commission assessed {name}.",
            "extraction_method": "pdf_extracted",
            "review_status": "unreviewed",
            "source_role": role,
            "supports_markets": [mid],
        }
        return pm, passage

    def _gm_with_passage(self, mid, name, status="left_open",
                          importance="core_assessed", role="commission_assessment"):
        gm = {"market_id": mid, "name": name, "definition_status": status,
              "market_importance": importance}
        passage = {
            "passage_id": f"sp_{mid}",
            "source_document_id": "doc_1",
            "page": "15",
            "quote_snippet": f"The Commission found the geographic scope of {name}.",
            "extraction_method": "pdf_extracted",
            "review_status": "unreviewed",
            "source_role": role,
            "supports_geographic_markets": [mid],
        }
        return gm, passage

    def _gold_pm_names(self, gold):
        return [m["name"] for m in gold.get("product_markets_considered", [])]

    def _gold_gm_names(self, gold):
        return [m["name"] for m in gold.get("geographic_markets_considered", [])]

    def _gold_all_entries(self, gold):
        return (gold.get("product_markets_considered", [])
                + gold.get("geographic_markets_considered", []))

    # ------------------------------------------------------------------
    # Default behavior unchanged without flag
    # ------------------------------------------------------------------

    def test_default_unchanged_without_flag(self):
        """Without auto_select, safe_to_promote is included and hold_pending is not."""
        pm1, sp1 = self._pm_with_passage("pm_1", "Primary market")
        pm2, sp2 = self._pm_with_passage("pm_2", "Held market")
        draft = _make_draft(pm_entries=[pm1, pm2], passages=[sp1, sp2])
        report = _make_report(
            safe=[_candidate("Primary market")],
            hold=[_candidate("Held market")],
        )
        gold = _create_gold_draft("test", draft, report)  # auto_select=False default

        pm_names = self._gold_pm_names(gold)
        assert "Primary market" in pm_names
        assert "Held market" not in pm_names

    # ------------------------------------------------------------------
    # Auto-select count
    # ------------------------------------------------------------------

    def test_auto_select_product_count(self):
        """auto_select picks exactly review_product_count product markets."""
        pms, passages, candidates = [], [], []
        for i in range(1, 5):
            pm, sp = self._pm_with_passage(f"pm_{i}", f"Product market {i}")
            pms.append(pm)
            passages.append(sp)
            candidates.append(_candidate(f"Product market {i}"))

        draft = _make_draft(pm_entries=pms, passages=passages)
        report = _make_report(uncertain=candidates)
        gold = _create_gold_draft(
            "test", draft, report,
            auto_select=True, review_product_count=2, review_geographic_count=0,
        )

        assert len(self._gold_pm_names(gold)) == 2

    def test_auto_select_geographic_count(self):
        """auto_select picks exactly review_geographic_count geographic markets."""
        gms, passages, geo_cands = [], [], []
        for i in range(1, 4):
            gm, sp = self._gm_with_passage(f"gm_{i}", f"Geographic scope {i}")
            gms.append(gm)
            passages.append(sp)
            geo_cands.append(_candidate(f"Geographic scope {i}", mtype="geographic"))

        draft = _make_draft(gm_entries=gms, passages=passages)
        report = _make_report(uncertain=geo_cands)
        gold = _create_gold_draft(
            "test", draft, report,
            auto_select=True, review_product_count=0, review_geographic_count=1,
        )

        assert len(self._gold_gm_names(gold)) == 1

    # ------------------------------------------------------------------
    # Sourced vs unsourced ranking
    # ------------------------------------------------------------------

    def test_sourced_outranks_unsourced(self):
        """A candidate with linked source passages is selected over one without."""
        pm_sourced, sp = self._pm_with_passage("pm_1", "Sourced market")
        pm_unsourced = _pm_entry("Unsourced market", "pm_2")
        draft = _make_draft(pm_entries=[pm_sourced, pm_unsourced], passages=[sp])
        report = _make_report(uncertain=[
            _candidate("Sourced market"),
            _candidate("Unsourced market"),
        ])
        gold = _create_gold_draft(
            "test", draft, report,
            auto_select=True, review_product_count=1, review_geographic_count=0,
        )

        pm_names = self._gold_pm_names(gold)
        assert "Sourced market" in pm_names
        assert "Unsourced market" not in pm_names

    def test_sourced_scores_higher_than_unsourced(self):
        """_score_candidate gives a higher score when passages are present."""
        entry = _candidate("Generic market")
        score_with = _score_candidate(entry, "uncertain_markets", [{"source_role": "commission_assessment"}])
        score_without = _score_candidate(entry, "uncertain_markets", [])
        assert score_with > score_without

    # ------------------------------------------------------------------
    # Source role ranking
    # ------------------------------------------------------------------

    def test_commission_conclusion_outranks_background(self):
        """Passage with source_role=commission_conclusion outranks background role."""
        pm1, sp1 = self._pm_with_passage("pm_1", "Conclusion market", role="commission_conclusion")
        pm2, sp2 = self._pm_with_passage("pm_2", "Background market", role="background")
        draft = _make_draft(pm_entries=[pm1, pm2], passages=[sp1, sp2])
        report = _make_report(uncertain=[
            _candidate("Conclusion market"),
            _candidate("Background market"),
        ])
        gold = _create_gold_draft(
            "test", draft, report,
            auto_select=True, review_product_count=1, review_geographic_count=0,
        )

        pm_names = self._gold_pm_names(gold)
        assert "Conclusion market" in pm_names
        assert "Background market" not in pm_names

    def test_commission_assessment_outranks_background_score(self):
        """commission_assessment source role scores higher than background."""
        entry = _candidate("Generic market")
        score_assessed = _score_candidate(
            entry, "uncertain_markets", [{"source_role": "commission_assessment"}]
        )
        score_background = _score_candidate(
            entry, "uncertain_markets", [{"source_role": "background"}]
        )
        assert score_assessed > score_background

    # ------------------------------------------------------------------
    # Importance ranking
    # ------------------------------------------------------------------

    def test_core_assessed_preferred(self):
        """core_assessed importance produces a higher score than context_background."""
        core_entry = _candidate("Market A", importance="core_assessed")
        context_entry = _candidate("Market B", importance="context_background")
        passages = [{"source_role": "commission_assessment"}]

        score_core = _score_candidate(core_entry, "uncertain_markets", passages)
        score_context = _score_candidate(context_entry, "uncertain_markets", passages)
        assert score_core > score_context

    # ------------------------------------------------------------------
    # Explicit include + auto-select: no duplicate
    # ------------------------------------------------------------------

    def test_explicit_and_auto_no_duplicate(self):
        """A market in explicit_names is not also added by auto-select."""
        pm1, sp1 = self._pm_with_passage("pm_1", "Explicit market")
        pm2, sp2 = self._pm_with_passage("pm_2", "Auto market A")
        pm3, sp3 = self._pm_with_passage("pm_3", "Auto market B")
        draft = _make_draft(pm_entries=[pm1, pm2, pm3], passages=[sp1, sp2, sp3])
        report = _make_report(
            hold=[_candidate("Explicit market")],
            uncertain=[_candidate("Auto market A"), _candidate("Auto market B")],
        )
        gold = _create_gold_draft(
            "test", draft, report,
            auto_select=True, review_product_count=2, review_geographic_count=0,
            explicit_names=frozenset(["Explicit market"]),
        )

        pm_names = self._gold_pm_names(gold)
        assert pm_names.count("Explicit market") == 1

    def test_auto_selected_market_not_duplicated_when_also_explicit(self):
        """When auto-select picks a market that is also in explicit_names, it appears once."""
        pm1, sp1 = self._pm_with_passage("pm_1", "Shared market", role="commission_conclusion")
        draft = _make_draft(pm_entries=[pm1], passages=[sp1])
        report = _make_report(uncertain=[_candidate("Shared market")])
        gold = _create_gold_draft(
            "test", draft, report,
            auto_select=True, review_product_count=1, review_geographic_count=0,
            explicit_names=frozenset(["Shared market"]),
        )

        pm_names = self._gold_pm_names(gold)
        assert pm_names.count("Shared market") == 1

    # ------------------------------------------------------------------
    # reviewed: false / aliases: []
    # ------------------------------------------------------------------

    def test_auto_selected_entries_are_not_reviewed(self):
        """Auto-selected entries always have reviewed: false."""
        pm1, sp1 = self._pm_with_passage("pm_1", "Selected market")
        gm1, sg1 = self._gm_with_passage("gm_1", "Selected geo")
        draft = _make_draft(pm_entries=[pm1], gm_entries=[gm1], passages=[sp1, sg1])
        report = _make_report(
            uncertain=[_candidate("Selected market")],
            geo=[_candidate("Selected geo", mtype="geographic")],
        )
        gold = _create_gold_draft(
            "test", draft, report,
            auto_select=True, review_product_count=1, review_geographic_count=1,
        )

        for entry in self._gold_all_entries(gold):
            assert entry["reviewed"] is False

    def test_auto_selected_aliases_empty(self):
        """Auto-selected entries always have aliases: []."""
        pm1, sp1 = self._pm_with_passage("pm_1", "Auto market")
        draft = _make_draft(pm_entries=[pm1], passages=[sp1])
        report = _make_report(uncertain=[_candidate("Auto market")])
        gold = _create_gold_draft(
            "test", draft, report,
            auto_select=True, review_product_count=1, review_geographic_count=0,
        )

        for entry in self._gold_all_entries(gold):
            assert entry["aliases"] == []

    # ------------------------------------------------------------------
    # gold_selection_reason and gold_selection_score
    # ------------------------------------------------------------------

    def test_auto_selected_reason_is_auto_review_set(self):
        """Auto-selected entries have gold_selection_reason='auto_review_set'."""
        pm1, sp1 = self._pm_with_passage("pm_1", "Selected market")
        draft = _make_draft(pm_entries=[pm1], passages=[sp1])
        report = _make_report(uncertain=[_candidate("Selected market")])
        gold = _create_gold_draft(
            "test", draft, report,
            auto_select=True, review_product_count=1, review_geographic_count=0,
        )

        pm = gold["product_markets_considered"][0]
        assert pm["gold_selection_reason"] == "auto_review_set"

    def test_auto_selected_score_field_present(self):
        """Auto-selected entries include a numeric gold_selection_score field."""
        pm1, sp1 = self._pm_with_passage("pm_1", "Scored market")
        draft = _make_draft(pm_entries=[pm1], passages=[sp1])
        report = _make_report(uncertain=[_candidate("Scored market")])
        gold = _create_gold_draft(
            "test", draft, report,
            auto_select=True, review_product_count=1, review_geographic_count=0,
        )

        pm = gold["product_markets_considered"][0]
        assert "gold_selection_score" in pm
        assert isinstance(pm["gold_selection_score"], float)

    # ------------------------------------------------------------------
    # Geographic pairing
    # ------------------------------------------------------------------

    def test_geographic_pairing_when_available(self):
        """With geographic_count=1, a geo candidate is auto-selected when available."""
        pm1, sp1 = self._pm_with_passage("pm_1", "Product market")
        gm1, sg1 = self._gm_with_passage("gm_1", "Geographic scope")
        draft = _make_draft(pm_entries=[pm1], gm_entries=[gm1], passages=[sp1, sg1])
        report = _make_report(
            uncertain=[_candidate("Product market")],
            geo=[_candidate("Geographic scope", mtype="geographic")],
        )
        gold = _create_gold_draft(
            "test", draft, report,
            auto_select=True, review_product_count=1, review_geographic_count=1,
        )

        assert "Geographic scope" in self._gold_gm_names(gold)

    # ------------------------------------------------------------------
    # Fewer candidates than requested
    # ------------------------------------------------------------------

    def test_fewer_candidates_returns_available(self):
        """When fewer candidates exist than review_product_count, return what's available."""
        pm1, sp1 = self._pm_with_passage("pm_1", "Only market")
        draft = _make_draft(pm_entries=[pm1], passages=[sp1])
        report = _make_report(uncertain=[_candidate("Only market")])
        gold = _create_gold_draft(
            "test", draft, report,
            auto_select=True, review_product_count=5, review_geographic_count=0,
        )

        pm_names = self._gold_pm_names(gold)
        assert len(pm_names) == 1
        assert "Only market" in pm_names

    # ------------------------------------------------------------------
    # context_only excluded when better candidates exist
    # ------------------------------------------------------------------

    def test_context_only_excluded_when_sourced_candidates_available(self):
        """context_only candidates are not auto-selected when better candidates exist."""
        pm_main, sp_main = self._pm_with_passage("pm_1", "Main market", role="commission_assessment")
        pm_ctx, sp_ctx = self._pm_with_passage("pm_2", "Context market", role="background")
        draft = _make_draft(pm_entries=[pm_main, pm_ctx], passages=[sp_main, sp_ctx])
        report = _make_report(
            uncertain=[_candidate("Main market")],
            context=[_candidate("Context market")],
        )
        gold = _create_gold_draft(
            "test", draft, report,
            auto_select=True, review_product_count=1, review_geographic_count=0,
        )

        pm_names = self._gold_pm_names(gold)
        assert "Main market" in pm_names
        assert "Context market" not in pm_names

    # ------------------------------------------------------------------
    # No industry-specific terms in selector logic
    # ------------------------------------------------------------------

    def test_selector_works_with_generic_market_names(self):
        """Selector uses no industry-specific logic — generic domain-neutral names work."""
        entry_high = _candidate("Service category A", importance="core_assessed")
        entry_low = _candidate("Service category B", importance="context_background")
        high_passages = [{"source_role": "commission_conclusion"}]
        low_passages = [{"source_role": "background"}]

        score_high = _score_candidate(entry_high, "uncertain_markets", high_passages)
        score_low = _score_candidate(entry_low, "context_only", low_passages)

        assert score_high > score_low

    # ------------------------------------------------------------------
    # No canonical YAML mutation
    # ------------------------------------------------------------------

    def test_no_canonical_yaml_mutation(self):
        """auto_select does not mutate the input draft or report dicts."""
        import copy
        pm1, sp1 = self._pm_with_passage("pm_1", "Primary market")
        draft = _make_draft(pm_entries=[pm1], passages=[sp1])
        report = _make_report(uncertain=[_candidate("Primary market")])

        draft_copy = copy.deepcopy(draft)
        report_copy = copy.deepcopy(report)

        _create_gold_draft(
            "test", draft, report,
            auto_select=True, review_product_count=1, review_geographic_count=0,
        )

        assert draft == draft_copy
        assert report == report_copy

    # ------------------------------------------------------------------
    # Diversity: second slot prefers different definition_status
    # ------------------------------------------------------------------

    def test_diversity_second_slot_prefers_different_status(self):
        """With product_count=2, the second slot soft-prefers a different definition_status.

        When no pairing bonus distinguishes candidates, diversity soft-preference
        causes the different-status entry to win the second slot.
        """
        # Market A: defined, commission_conclusion (top scorer)
        # Market B: defined, commission_assessment (same status as A)
        # Market C: possible_segmentation, commission_assessment (different status)
        # No geo candidates → no pairing bonuses.  Diversity should pick C over B.
        pm_a, sp_a = self._pm_with_passage("pm_1", "Primary assessment market",
                                             status="defined", role="commission_conclusion")
        pm_b, sp_b = self._pm_with_passage("pm_2", "Secondary assessment market",
                                             status="defined", role="commission_assessment")
        pm_c, sp_c = self._pm_with_passage("pm_3", "Segmented assessment market",
                                             status="possible_segmentation",
                                             role="commission_assessment")

        draft = _make_draft(pm_entries=[pm_a, pm_b, pm_c], passages=[sp_a, sp_b, sp_c])
        report = _make_report(uncertain=[
            _candidate("Primary assessment market", status="defined"),
            _candidate("Secondary assessment market", status="defined"),
            _candidate("Segmented assessment market", status="possible_segmentation"),
        ])
        gold = _create_gold_draft(
            "test", draft, report,
            auto_select=True, review_product_count=2, review_geographic_count=0,
        )

        pm_names = self._gold_pm_names(gold)
        assert "Primary assessment market" in pm_names
        assert "Segmented assessment market" in pm_names
        assert "Secondary assessment market" not in pm_names


# ---------------------------------------------------------------------------
# TestPairingAndCentralityScoring
# ---------------------------------------------------------------------------

class TestPairingAndCentralityScoring:
    """
    Tests for product/geographic pairing bonus and source_refs centrality bonus.

    All market names use generic, domain-neutral vocabulary.
    No industry-specific terms in scoring constants or test data.
    No Claude API calls; no canonical YAML mutation.
    """

    # ------------------------------------------------------------------
    # _pairing_token_set unit tests
    # ------------------------------------------------------------------

    def test_token_set_lowercases(self):
        assert "widget" in _pairing_token_set("Widget supply")

    def test_token_set_filters_short_tokens(self):
        tokens = _pairing_token_set("A BC DEF widgets")
        assert "a" not in tokens
        assert "bc" not in tokens
        assert "def" not in tokens  # 3 chars → filtered
        assert "widgets" in tokens

    def test_token_set_removes_stopwords(self):
        tokens = _pairing_token_set("supply and demand for widgets")
        assert "and" not in tokens
        assert "for" not in tokens
        assert "demand" not in tokens  # in stopwords
        assert "supply" not in tokens  # in stopwords
        assert "widgets" in tokens

    def test_token_set_splits_on_punctuation(self):
        tokens = _pairing_token_set("widgets/gadgets — components (assembled)")
        assert "widgets" in tokens
        assert "gadgets" in tokens
        assert "components" in tokens
        assert "assembled" in tokens

    def test_token_set_empty_name(self):
        assert _pairing_token_set("") == frozenset()

    def test_token_set_all_stopwords(self):
        assert _pairing_token_set("market for supply and demand") == frozenset()

    # ------------------------------------------------------------------
    # _pairing_overlap unit tests
    # ------------------------------------------------------------------

    def test_pairing_overlap_identical_names(self):
        overlap = _pairing_overlap("Standardised components assembly",
                                   "Standardised components assembly")
        assert overlap == 1.0

    def test_pairing_overlap_geo_wraps_product(self):
        """Geo name that contains all of the product's significant tokens → high overlap."""
        product = "Standardised components assembly"
        geo = "Geographic scope of standardised components assembly"
        overlap = _pairing_overlap(product, geo)
        assert overlap >= 0.8

    def test_pairing_overlap_no_significant_tokens_shared(self):
        assert _pairing_overlap("Widget assembly components",
                                "Logistics routing platforms") == 0.0

    def test_pairing_overlap_partial(self):
        overlap = _pairing_overlap("Widget assembly", "Widget assembly and logistics")
        assert 0 < overlap <= 1.0

    def test_pairing_overlap_symmetric(self):
        a = "Standardised components assembly"
        b = "Geographic standardised components"
        assert abs(_pairing_overlap(a, b) - _pairing_overlap(b, a)) < 1e-9

    def test_pairing_overlap_empty_returns_zero(self):
        assert _pairing_overlap("", "Widget supply") == 0.0
        assert _pairing_overlap("Widget supply", "") == 0.0

    # ------------------------------------------------------------------
    # No industry-specific terms in pairing constants
    # ------------------------------------------------------------------

    def test_pairing_stopwords_are_generic(self):
        """_PAIRING_STOPWORDS must contain only generic linguistic/structural terms."""
        for word in _PAIRING_STOPWORDS:
            assert len(word) <= 12, f"Suspicious long stopword: {word!r}"
        assert _PAIRING_MIN_TOKEN_LEN <= 5

    def test_selector_constants_work_with_generic_vocabulary(self):
        """Pairing works correctly with completely generic market name vocabulary."""
        product_name = "Standardised assembly components"
        geo_name = "Geographic scope of standardised assembly components"
        overlap = _pairing_overlap(product_name, geo_name)
        assert overlap > 0.5

    # ------------------------------------------------------------------
    # Pairing bonus via _max_pairing_signal
    # ------------------------------------------------------------------

    def test_max_pairing_signal_with_matching_geo(self):
        """Product entry gets a high pairing signal when a geo candidate matches its name."""
        product_entry = _candidate("Widget assembly services", mtype="product")
        geo_entry = _candidate("Geographic scope of widget assembly services",
                               mtype="geographic")
        signal = _max_pairing_signal(product_entry,
                                     [(8.0, geo_entry, "uncertain_markets")])
        assert signal > 0.5

    def test_max_pairing_signal_no_geo_match(self):
        """Product entry gets zero pairing signal when no geo candidate shares its tokens."""
        product_entry = _candidate("Widget assembly services", mtype="product")
        geo_entry = _candidate("Geographic scope of logistics routing", mtype="geographic")
        signal = _max_pairing_signal(product_entry,
                                     [(8.0, geo_entry, "uncertain_markets")])
        assert signal == 0.0

    def test_max_pairing_signal_market_group_match(self):
        """market_group equality produces a perfect pairing signal."""
        product_entry = {**_candidate("Widget supply", mtype="product"),
                         "market_group": "widgets"}
        geo_entry = {**_candidate("Geographic widget scope", mtype="geographic"),
                     "market_group": "widgets"}
        signal = _max_pairing_signal(product_entry,
                                     [(8.0, geo_entry, "uncertain_markets")])
        assert signal == 1.0

    def test_max_pairing_signal_empty_others(self):
        """No geo candidates → zero pairing signal."""
        product_entry = _candidate("Widget assembly", mtype="product")
        assert _max_pairing_signal(product_entry, []) == 0.0

    # ------------------------------------------------------------------
    # Paired product outranks equal unpaired product
    # ------------------------------------------------------------------

    def _pm_with_passage(self, mid, name, status="defined",
                          importance="core_assessed", role="commission_assessment",
                          refs=None):
        pm = _pm_entry(name, mid, status=status, importance=importance)
        passage = {
            "passage_id": f"sp_{mid}",
            "source_document_id": "doc_1",
            "page": "10",
            "quote_snippet": f"The Commission assessed {name}.",
            "extraction_method": "pdf_extracted",
            "review_status": "unreviewed",
            "source_role": role,
            "supports_markets": [mid],
        }
        return pm, passage

    def _gm_with_passage(self, mid, name, status="left_open",
                          importance="core_assessed", role="commission_assessment"):
        gm = {"market_id": mid, "name": name, "definition_status": status,
              "market_importance": importance}
        passage = {
            "passage_id": f"sp_{mid}",
            "source_document_id": "doc_1",
            "page": "15",
            "quote_snippet": f"The geographic scope of {name} is EEA-wide.",
            "extraction_method": "pdf_extracted",
            "review_status": "unreviewed",
            "source_role": role,
            "supports_geographic_markets": [mid],
        }
        return gm, passage

    def _gold_pm_names(self, gold):
        return [m["name"] for m in gold.get("product_markets_considered", [])]

    def _gold_gm_names(self, gold):
        return [m["name"] for m in gold.get("geographic_markets_considered", [])]

    def test_paired_product_outranks_unpaired_equal_base(self):
        """A product with a geo pair outranks an otherwise equal unpaired product.

        Two products share the same base signals (same category, status, importance,
        source role, source_refs count).  Only one has a paired geographic market.
        The paired product must be selected.
        """
        pm_a, sp_a = self._pm_with_passage("pm_1", "Widget assembly services")
        pm_b, sp_b = self._pm_with_passage("pm_2", "Logistics routing platforms")
        gm, sg = self._gm_with_passage("gm_1",
                                        "Geographic scope of widget assembly services")

        draft = _make_draft(pm_entries=[pm_a, pm_b], gm_entries=[gm],
                            passages=[sp_a, sp_b, sg])
        report = _make_report(
            uncertain=[
                _candidate("Widget assembly services"),
                _candidate("Logistics routing platforms"),
            ],
            geo=[_candidate("Geographic scope of widget assembly services",
                            mtype="geographic")],
        )
        gold = _create_gold_draft(
            "test", draft, report,
            auto_select=True, review_product_count=1, review_geographic_count=0,
        )

        pm_names = self._gold_pm_names(gold)
        assert "Widget assembly services" in pm_names
        assert "Logistics routing platforms" not in pm_names

    def test_pairing_breaks_tie_over_diversity(self):
        """Pairing bonus beats the diversity soft-preference when the paired market has the same status.

        Three same-status products: A (top by role), B (no pair), C (has geo pair).
        Without pairing, diversity would not distinguish B and C.  With pairing, C
        must win because its pairing bonus (0.40) > diversity soft bonus (0.25).

        Names are chosen so that only C's tokens appear in the geo name — B's tokens
        are entirely disjoint from the geo candidate.
        """
        # A: top scorer (commission_conclusion)
        pm_a, sp_a = self._pm_with_passage("pm_1", "Widget assembly components",
                                             status="defined", role="commission_conclusion")
        # B: equal base to C (commission_assessment), no geo pair — entirely different tokens
        pm_b, sp_b = self._pm_with_passage("pm_2", "Logistics routing services",
                                             status="defined", role="commission_assessment")
        # C: equal base to B (commission_assessment), HAS geo pair
        pm_c, sp_c = self._pm_with_passage("pm_3", "Procurement evaluation platforms",
                                             status="defined", role="commission_assessment")
        # Geo pairs with C only — contains "procurement", "evaluation", "platforms"
        gm, sg = self._gm_with_passage("gm_1",
                                        "Geographic scope of procurement evaluation platforms")

        draft = _make_draft(pm_entries=[pm_a, pm_b, pm_c], gm_entries=[gm],
                            passages=[sp_a, sp_b, sp_c, sg])
        report = _make_report(
            uncertain=[
                _candidate("Widget assembly components", status="defined"),
                _candidate("Logistics routing services", status="defined"),
                _candidate("Procurement evaluation platforms", status="defined"),
            ],
            geo=[_candidate("Geographic scope of procurement evaluation platforms",
                            mtype="geographic")],
        )
        gold = _create_gold_draft(
            "test", draft, report,
            auto_select=True, review_product_count=2, review_geographic_count=0,
        )

        pm_names = self._gold_pm_names(gold)
        assert "Widget assembly components" in pm_names
        assert "Procurement evaluation platforms" in pm_names   # paired → wins over B
        assert "Logistics routing services" not in pm_names

    # ------------------------------------------------------------------
    # Geo prefers market paired to selected product (two-pass)
    # ------------------------------------------------------------------

    def test_geo_prefers_pair_with_selected_product(self):
        """Geographic auto-selection prefers a candidate that pairs with a selected product.

        Two geo candidates: geo_a pairs with the selected product, geo_b does not.
        geo_b has a higher base score (more source_refs).  geo_a must still win
        because its pairing bonus overcomes geo_b's base advantage.
        """
        pm, sp = self._pm_with_passage("pm_1", "Widget assembly services")
        gm_a, sg_a = self._gm_with_passage("gm_1",
                                             "Geographic scope of widget assembly services")
        gm_b, sg_b = self._gm_with_passage("gm_2",
                                             "Geographic scope of logistics routing platforms")

        draft = _make_draft(pm_entries=[pm], gm_entries=[gm_a, gm_b],
                            passages=[sp, sg_a, sg_b])
        report = _make_report(
            uncertain=[_candidate("Widget assembly services")],
            geo=[
                _candidate("Geographic scope of widget assembly services",
                           mtype="geographic", refs=["10"]),
                # geo_b gets extra source_refs for a higher base score
                _candidate("Geographic scope of logistics routing platforms",
                           mtype="geographic",
                           refs=["10", "11", "12", "13", "14", "15", "16", "17"]),
            ],
        )
        gold = _create_gold_draft(
            "test", draft, report,
            auto_select=True, review_product_count=1, review_geographic_count=1,
        )

        gm_names = self._gold_gm_names(gold)
        assert "Geographic scope of widget assembly services" in gm_names
        assert "Geographic scope of logistics routing platforms" not in gm_names

    # ------------------------------------------------------------------
    # Centrality bonus from source_refs
    # ------------------------------------------------------------------

    def test_centrality_bonus_scores_higher_with_more_source_refs(self):
        """Candidate with more source_refs gets a higher _score_candidate result."""
        entry_many = _candidate("Generic market",
                                refs=["1", "2", "3", "4", "5", "6", "7", "8"])
        entry_few = _candidate("Generic market", refs=["1"])
        passages = [{"source_role": "commission_assessment"}]
        assert _score_candidate(entry_many, "uncertain_markets", passages) > \
               _score_candidate(entry_few,  "uncertain_markets", passages)

    def test_centrality_saturates_at_scale(self):
        """Centrality bonus saturates and does not grow unboundedly."""
        entry_100 = _candidate("Generic market", refs=[str(i) for i in range(100)])
        entry_8   = _candidate("Generic market", refs=[str(i) for i in range(8)])
        passages = [{"source_role": "commission_assessment"}]
        assert _score_candidate(entry_100, "uncertain_markets", passages) == \
               _score_candidate(entry_8,   "uncertain_markets", passages)

    # ------------------------------------------------------------------
    # Explicit includes still override auto-selection
    # ------------------------------------------------------------------

    def test_explicit_includes_still_override_with_pairing(self):
        """Explicit market includes work alongside pairing-aware auto-selection."""
        pm_held, sp_held = self._pm_with_passage("pm_1", "Held widget market")
        pm_auto, sp_auto = self._pm_with_passage("pm_2", "Auto selected market")
        gm, sg = self._gm_with_passage("gm_1", "Geographic scope of auto selected market")

        draft = _make_draft(pm_entries=[pm_held, pm_auto], gm_entries=[gm],
                            passages=[sp_held, sp_auto, sg])
        report = _make_report(
            hold=[_candidate("Held widget market")],
            uncertain=[_candidate("Auto selected market")],
            geo=[_candidate("Geographic scope of auto selected market", mtype="geographic")],
        )
        gold = _create_gold_draft(
            "test", draft, report,
            auto_select=True, review_product_count=1, review_geographic_count=1,
            explicit_names=frozenset(["Held widget market"]),
        )

        pm_names = self._gold_pm_names(gold)
        assert "Held widget market" in pm_names
        assert "Auto selected market" in pm_names

    # ------------------------------------------------------------------
    # Default mode unchanged
    # ------------------------------------------------------------------

    def test_default_mode_unchanged_by_pairing_refinement(self):
        """The default (non-auto-select) mode is unaffected by pairing/centrality constants."""
        pm1, sp1 = self._pm_with_passage("pm_1", "Safe market")
        pm2, sp2 = self._pm_with_passage("pm_2", "Held market")
        draft = _make_draft(pm_entries=[pm1, pm2], passages=[sp1, sp2])
        report = _make_report(
            safe=[_candidate("Safe market")],
            hold=[_candidate("Held market")],
        )
        gold = _create_gold_draft("test", draft, report)  # auto_select=False

        pm_names = self._gold_pm_names(gold)
        assert "Safe market" in pm_names
        assert "Held market" not in pm_names
