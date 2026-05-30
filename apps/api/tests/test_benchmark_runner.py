"""
Tests for scripts/run_eval_benchmark.py.

No network access; no Claude API calls; no canonical YAML mutation.
"""

import json
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from run_eval_benchmark import (
    _FAIL_GATING,
    _case_passes,
    _case_summary_row,
    _format_summary_markdown,
    run_benchmark,
)


# ---------------------------------------------------------------------------
# Shared result factory
# ---------------------------------------------------------------------------

def _make_result(
    *,
    case_id: str = "test_case",
    quote_checked: int = 5,
    quote_failures: int = 0,
    quote_warnings: int = 0,
    reviewed: int = 1,
    evaluation_valid: bool = True,
    gating: str = "auto_accept",
    overpromotion: str = "low",
    overall_f1: float = 1.0,
    product_f1: float = 1.0,
    geo_f1: float = 1.0,
    safety_score: float = 1.0,
    unjudged: int = 0,
) -> dict:
    """Build a minimal evaluation result dict for unit tests."""
    return {
        "case_id":            case_id,
        "generated_at":       "2026-01-01T00:00:00+00:00",
        "gold_partial":       True,
        "gold_reviewed_count": reviewed,
        "gold_review_status": (
            "has_reviewed_gold_items" if reviewed > 0 else "no_reviewed_gold_items"
        ),
        "evaluation_valid":   evaluation_valid,
        "overall_f1":         overall_f1,
        "gating_decision":    gating,
        "gating_reason":      "",
        "quote_validity": {
            "total_checked": quote_checked,
            "passed":        quote_checked - quote_failures,
            "failures":      quote_failures,
            "warnings":      quote_warnings,
            "failure_details": [],
        },
        "product_markets": {
            "market_type": "product",
            "true_positives": 1, "false_positives": 0, "false_negatives": 0,
            "precision": 1.0, "recall": 1.0, "f1": product_f1,
            "matched_items": [], "false_negatives_detail": [],
            "false_positives_detail": [],
            "unjudged_items": [{}] * unjudged,
        },
        "geographic_markets": {
            "market_type": "geographic",
            "true_positives": 0, "false_positives": 0, "false_negatives": 0,
            "precision": 1.0, "recall": 1.0, "f1": geo_f1,
            "matched_items": [], "false_negatives_detail": [],
            "false_positives_detail": [], "unjudged_items": [],
        },
        "promotion_safety": {
            "risky_promotions": 0, "safe_promoted_count": 0,
            "safety_score": safety_score, "overpromotion_risk": overpromotion,
        },
    }


# ---------------------------------------------------------------------------
# Integration fixture helpers
# ---------------------------------------------------------------------------

def _write_fixture(
    tmp_path: Path,
    *,
    case_id: str = "bench_case",
    gold_reviewed: bool = True,
    draft_includes_market: bool = True,
    report_risky: bool = False,
    include_quote_passage: bool = False,
    cache_text: str | None = None,
) -> Path:
    """Write minimal gold / draft / report / config files under tmp_path.

    Returns the path to the benchmark config YAML.

    The ``apps/`` subdirectory is created so that ``_find_repo_root`` can
    locate tmp_path as the repo root when needed, but callers also pass
    ``base_dir=tmp_path`` directly to bypass auto-detection.
    """
    gold_dir   = tmp_path / "data" / "evals" / "gold"
    draft_dir  = tmp_path / "data" / "drafts" / "eu"
    report_dir = tmp_path / "data" / "source_text"
    output_dir = tmp_path / "data" / "evals" / "results"
    config_dir = tmp_path / "data" / "evals"

    for d in (gold_dir, draft_dir, report_dir, output_dir, config_dir,
              tmp_path / "apps"):
        d.mkdir(parents=True, exist_ok=True)

    # Gold YAML
    passage = []
    if include_quote_passage:
        passage = [{
            "passage_id": "sp_1",
            "source_document_id": "test_doc",
            "page": "1",
            "quote_snippet": "The Commission found the relevant market is online advertising.",
            "source_summary": "",
        }]
    gold = {
        "_gold_metadata": {"partial": True},
        "case_id": case_id,
        "source_documents": [{"doc_id": "test_doc"}],
        "product_markets_considered": [{
            "name": "Online advertising",
            "reviewed": gold_reviewed,
            "linked_source_passages": passage,
        }],
        "geographic_markets_considered": [],
    }
    gold_path = gold_dir / f"{case_id}.market_definition.partial.gold.repaired.yaml"
    gold_path.write_text(yaml.dump(gold))

    # Draft YAML
    draft = {
        "product_markets_considered": (
            [{"name": "Online advertising", "market_id": "pm_1"}]
            if draft_includes_market else []
        ),
        "geographic_markets_considered": [],
        "source_passages": [],
    }
    draft_path = draft_dir / f"{case_id}.market_definition.draft.yaml"
    draft_path.write_text(yaml.dump(draft))

    # Report JSON
    report = {
        "canonical_merge_candidates": {
            "safe_to_promote": (
                [{"name": "Risky mkt", "market_type": "product"}]
                if report_risky else []
            ),
            "uncertain_markets":         [],
            "hold_pending_source_check": [],
            "manual_review":             [],
            "manual_review_geo_pairing": [],
        }
    }
    report_path = report_dir / f"{case_id}_report.json"
    report_path.write_text(json.dumps(report))

    # Optional: page cache for quote validation
    if cache_text is not None:
        cache = {
            "source_document_id": "test_doc",
            "pages": [{"page_number": 1, "text": cache_text}],
        }
        (report_dir / "test_doc.json").write_text(json.dumps(cache))

    # Benchmark config
    config = {
        "focus": "market_definition",
        "cache_dir": "data/source_text",
        "output_dir": "data/evals/results",
        "benchmarks": [{
            "case_id": case_id,
            "gold_yaml":   f"data/evals/gold/{case_id}.market_definition.partial.gold.repaired.yaml",
            "draft_yaml":  f"data/drafts/eu/{case_id}.market_definition.draft.yaml",
            "report_json": f"data/source_text/{case_id}_report.json",
        }],
    }
    config_path = config_dir / "benchmark.market_definition.yaml"
    config_path.write_text(yaml.dump(config))

    return config_path


# ---------------------------------------------------------------------------
# TestCasePasses — unit tests for _case_passes
# ---------------------------------------------------------------------------

class TestCasePasses:
    """_case_passes: pass / fail logic over evaluation result dicts."""

    def test_clean_result_passes(self):
        assert _case_passes(_make_result()) is True

    def test_quote_failure_fails(self):
        assert _case_passes(_make_result(quote_failures=1)) is False

    def test_zero_reviewed_gold_fails(self):
        assert _case_passes(_make_result(reviewed=0)) is False

    def test_evaluation_invalid_fails(self):
        assert _case_passes(_make_result(evaluation_valid=False)) is False

    def test_gating_reject_fails(self):
        assert _case_passes(_make_result(gating="reject")) is False

    def test_gating_needs_review_fails(self):
        assert _case_passes(_make_result(gating="needs_review")) is False

    def test_gating_insufficient_gold_fails(self):
        assert _case_passes(_make_result(gating="insufficient_gold")) is False

    def test_gating_error_fails(self):
        assert _case_passes(_make_result(gating="error")) is False

    def test_high_overpromotion_fails(self):
        assert _case_passes(_make_result(overpromotion="high")) is False

    def test_unjudged_candidates_do_not_fail(self):
        """Unjudged candidates are informational; they never cause a case to fail."""
        assert _case_passes(_make_result(unjudged=10)) is True

    def test_quote_warnings_do_not_fail(self):
        """Quote warnings (cache unavailable) do not fail a case."""
        assert _case_passes(_make_result(quote_warnings=5)) is True

    def test_low_f1_alone_does_not_fail(self):
        """Low F1 does not directly fail — gating_decision determines outcome."""
        assert _case_passes(_make_result(overall_f1=0.5, gating="auto_accept")) is True

    def test_auto_accept_with_one_reviewed_passes(self):
        assert _case_passes(_make_result(reviewed=1, gating="auto_accept")) is True

    def test_multiple_failures_all_caught(self):
        result = _make_result(
            quote_failures=1, reviewed=0,
            evaluation_valid=False, gating="reject", overpromotion="high",
        )
        assert _case_passes(result) is False


# ---------------------------------------------------------------------------
# TestCaseSummaryRow — unit tests for _case_summary_row
# ---------------------------------------------------------------------------

class TestCaseSummaryRow:
    """_case_summary_row: field extraction from result dict."""

    def test_extracts_case_id(self):
        row = _case_summary_row("my_case", _make_result(), True)
        assert row["case_id"] == "my_case"

    def test_extracts_quote_fields(self):
        row = _case_summary_row("c", _make_result(quote_checked=10, quote_failures=2,
                                                   quote_warnings=1), False)
        assert row["quote_checked"] == 10
        assert row["quote_failures"] == 2
        assert row["quote_warnings"] == 1

    def test_extracts_reviewed_count(self):
        row = _case_summary_row("c", _make_result(reviewed=3), True)
        assert row["reviewed_gold_count"] == 3

    def test_extracts_f1_scores(self):
        row = _case_summary_row("c", _make_result(overall_f1=0.8, product_f1=0.9,
                                                   geo_f1=0.7), True)
        assert row["overall_f1"] == 0.8
        assert row["product_f1"] == 0.9
        assert row["geographic_f1"] == 0.7

    def test_extracts_promotion_safety(self):
        row = _case_summary_row("c", _make_result(safety_score=0.5,
                                                   overpromotion="medium"), True)
        assert row["promotion_safety_score"] == 0.5
        assert row["overpromotion_risk"] == "medium"

    def test_extracts_gating_decision(self):
        row = _case_summary_row("c", _make_result(gating="reject"), False)
        assert row["gating_decision"] == "reject"

    def test_passed_field_reflects_arg(self):
        assert _case_summary_row("c", _make_result(), True)["passed"] is True
        assert _case_summary_row("c", _make_result(), False)["passed"] is False


# ---------------------------------------------------------------------------
# TestFormatSummaryMarkdown
# ---------------------------------------------------------------------------

class TestFormatSummaryMarkdown:
    """_format_summary_markdown: markdown output structure."""

    def _rows(self, *, passed: bool = True, gating: str = "auto_accept") -> list[dict]:
        result = _make_result(gating=gating)
        return [_case_summary_row("test_case", result, passed)]

    def test_contains_case_id(self):
        md = _format_summary_markdown(self._rows(), True, "2026-01-01T00:00:00+00:00")
        assert "test_case" in md

    def test_pass_verdict_when_all_pass(self):
        md = _format_summary_markdown(self._rows(passed=True), True, "2026-01-01T00:00:00+00:00")
        assert "PASS" in md

    def test_fail_verdict_when_any_fail(self):
        md = _format_summary_markdown(self._rows(passed=False), False, "2026-01-01T00:00:00+00:00")
        assert "FAIL" in md

    def test_warning_present_when_failed(self):
        md = _format_summary_markdown(self._rows(passed=False), False, "2026-01-01T00:00:00+00:00")
        assert "Benchmark failed" in md

    def test_no_warning_when_passed(self):
        md = _format_summary_markdown(self._rows(passed=True), True, "2026-01-01T00:00:00+00:00")
        assert "Benchmark failed" not in md

    def test_table_header_present(self):
        md = _format_summary_markdown(self._rows(), True, "2026-01-01T00:00:00+00:00")
        assert "| Case" in md
        assert "Gating" in md

    def test_multiple_cases(self):
        rows = [
            _case_summary_row("case_a", _make_result(case_id="case_a"), True),
            _case_summary_row("case_b", _make_result(case_id="case_b"), False),
        ]
        md = _format_summary_markdown(rows, False, "2026-01-01T00:00:00+00:00")
        assert "case_a" in md
        assert "case_b" in md


# ---------------------------------------------------------------------------
# TestRunBenchmarkIntegration — integration tests via run_benchmark()
# ---------------------------------------------------------------------------

class TestRunBenchmarkIntegration:
    """Integration tests that write fixture files and call run_benchmark()."""

    def test_all_pass_returns_exit_0(self, tmp_path):
        """A benchmark with a passing case returns exit code 0."""
        config_path = _write_fixture(tmp_path)
        exit_code = run_benchmark(config_path, base_dir=tmp_path)
        assert exit_code == 0

    def test_all_pass_summary_json_written(self, tmp_path):
        """Summary JSON is written to the configured output directory."""
        config_path = _write_fixture(tmp_path)
        run_benchmark(config_path, base_dir=tmp_path)
        out = tmp_path / "data" / "evals" / "results" / "benchmark.market_definition.summary.json"
        assert out.exists()
        data = json.loads(out.read_text())
        assert data["overall_passed"] is True
        assert data["cases_total"] == 1

    def test_all_pass_summary_markdown_written(self, tmp_path):
        """Summary Markdown is written alongside the JSON."""
        config_path = _write_fixture(tmp_path)
        run_benchmark(config_path, base_dir=tmp_path)
        out = tmp_path / "data" / "evals" / "results" / "benchmark.market_definition.summary.md"
        assert out.exists()
        assert "PASS" in out.read_text()

    def test_per_case_eval_json_written(self, tmp_path):
        """Per-case eval.json is written for each benchmark case."""
        config_path = _write_fixture(tmp_path, case_id="my_case")
        run_benchmark(config_path, base_dir=tmp_path)
        out = tmp_path / "data" / "evals" / "results" / "my_case.market_definition.eval.json"
        assert out.exists()

    def test_per_case_eval_markdown_written(self, tmp_path):
        """Per-case eval.md is written for each benchmark case."""
        config_path = _write_fixture(tmp_path, case_id="my_case")
        run_benchmark(config_path, base_dir=tmp_path)
        out = tmp_path / "data" / "evals" / "results" / "my_case.market_definition.eval.md"
        assert out.exists()

    def test_insufficient_gold_returns_exit_1(self, tmp_path):
        """A case with no reviewed gold entries → benchmark fails (exit 1)."""
        config_path = _write_fixture(tmp_path, gold_reviewed=False)
        exit_code = run_benchmark(config_path, base_dir=tmp_path)
        assert exit_code == 1

    def test_insufficient_gold_summary_marks_failed(self, tmp_path):
        """Summary JSON reflects failure when no reviewed gold entries exist."""
        config_path = _write_fixture(tmp_path, gold_reviewed=False)
        run_benchmark(config_path, base_dir=tmp_path)
        out = tmp_path / "data" / "evals" / "results" / "benchmark.market_definition.summary.json"
        data = json.loads(out.read_text())
        assert data["overall_passed"] is False
        assert data["cases_failed"] == 1

    def test_quote_failure_returns_exit_1(self, tmp_path):
        """A case with a failing quote snippet → benchmark fails (exit 1)."""
        # Gold has a passage; cache has DIFFERENT text → quote validation fails
        config_path = _write_fixture(
            tmp_path,
            include_quote_passage=True,
            cache_text="Completely different text not matching the snippet.",
        )
        exit_code = run_benchmark(config_path, base_dir=tmp_path)
        assert exit_code == 1

    def test_quote_warning_does_not_fail(self, tmp_path):
        """A case with no cache (quote warnings only) still passes."""
        # No cache file → validate_gold_passages produces warnings, not failures
        config_path = _write_fixture(tmp_path)
        exit_code = run_benchmark(config_path, base_dir=tmp_path)
        assert exit_code == 0

    def test_unjudged_candidates_do_not_fail_benchmark(self, tmp_path):
        """Unjudged draft markets (not in gold) do not cause benchmark failure."""
        # Draft has 2 markets; gold only reviews 1 → 1 unjudged
        config_path = _write_fixture(tmp_path)
        # Add a second market to draft directly
        draft_path = tmp_path / "data" / "drafts" / "eu" / "bench_case.market_definition.draft.yaml"
        if draft_path.exists():
            draft = yaml.safe_load(draft_path.read_text())
            draft["product_markets_considered"].append({
                "name": "Extra unjudged market", "market_id": "pm_2"
            })
            draft_path.write_text(yaml.dump(draft))
        exit_code = run_benchmark(config_path, base_dir=tmp_path)
        assert exit_code == 0

    def test_missing_draft_file_fails_case(self, tmp_path):
        """A case with a missing draft file fails gracefully (exit 1)."""
        config_path = _write_fixture(tmp_path)
        # Remove draft file
        draft_path = tmp_path / "data" / "drafts" / "eu" / "bench_case.market_definition.draft.yaml"
        if draft_path.exists():
            draft_path.unlink()
        exit_code = run_benchmark(config_path, base_dir=tmp_path)
        assert exit_code == 1

    def test_missing_file_writes_summary_with_failure(self, tmp_path):
        """Even when a case file is missing, the summary JSON is written."""
        config_path = _write_fixture(tmp_path)
        draft_path = tmp_path / "data" / "drafts" / "eu" / "bench_case.market_definition.draft.yaml"
        if draft_path.exists():
            draft_path.unlink()
        run_benchmark(config_path, base_dir=tmp_path)
        out = tmp_path / "data" / "evals" / "results" / "benchmark.market_definition.summary.json"
        assert out.exists()
        data = json.loads(out.read_text())
        assert data["cases_failed"] == 1

    def test_output_json_override(self, tmp_path):
        """--output-json overrides the default summary JSON path."""
        config_path = _write_fixture(tmp_path)
        custom_json = tmp_path / "custom_summary.json"
        run_benchmark(config_path, base_dir=tmp_path, output_json_path=custom_json)
        assert custom_json.exists()

    def test_output_markdown_override(self, tmp_path):
        """--output-markdown overrides the default summary Markdown path."""
        config_path = _write_fixture(tmp_path)
        custom_md = tmp_path / "custom_summary.md"
        run_benchmark(config_path, base_dir=tmp_path, output_md_path=custom_md)
        assert custom_md.exists()

    def test_canonical_yaml_not_modified(self, tmp_path):
        """run_benchmark does not mutate the gold YAML file on disk."""
        import copy as _copy
        config_path = _write_fixture(tmp_path)
        gold_path = (
            tmp_path / "data" / "evals" / "gold"
            / "bench_case.market_definition.partial.gold.repaired.yaml"
        )
        original_text = gold_path.read_text()
        run_benchmark(config_path, base_dir=tmp_path)
        assert gold_path.read_text() == original_text

    def test_summary_json_structure(self, tmp_path):
        """Summary JSON contains all required top-level fields."""
        config_path = _write_fixture(tmp_path)
        run_benchmark(config_path, base_dir=tmp_path)
        out = tmp_path / "data" / "evals" / "results" / "benchmark.market_definition.summary.json"
        data = json.loads(out.read_text())
        for key in ("focus", "generated_at", "overall_passed", "cases_total",
                    "cases_passed", "cases_failed", "cases"):
            assert key in data, f"Missing key: {key}"

    def test_summary_case_row_fields(self, tmp_path):
        """Each case row in the summary JSON contains all required fields."""
        config_path = _write_fixture(tmp_path)
        run_benchmark(config_path, base_dir=tmp_path)
        out = tmp_path / "data" / "evals" / "results" / "benchmark.market_definition.summary.json"
        data = json.loads(out.read_text())
        row = data["cases"][0]
        for key in (
            "case_id", "quote_checked", "quote_failures", "quote_warnings",
            "reviewed_gold_count", "product_f1", "geographic_f1", "overall_f1",
            "promotion_safety_score", "overpromotion_risk", "gating_decision", "passed",
        ):
            assert key in row, f"Missing key in case row: {key}"

    def test_per_case_cache_dir_overrides_global(self, tmp_path):
        """Per-case cache_dir in the config is used instead of the global cache_dir.

        The global cache_dir points to a non-existent directory; the per-case
        cache_dir points to the real location.  Quote validation must still pass
        (warnings only, no failures), proving the per-case path is honoured.
        """
        config_path = _write_fixture(tmp_path)

        # Rewrite config: set a bogus global cache_dir; add per-case cache_dir
        # pointing to the real source_text directory.
        with open(config_path) as fh:
            cfg = yaml.safe_load(fh)
        cfg["cache_dir"] = "data/nonexistent_cache"
        cfg["benchmarks"][0]["cache_dir"] = "data/source_text"
        config_path.write_text(yaml.dump(cfg))

        exit_code = run_benchmark(config_path, base_dir=tmp_path)
        # The per-case cache_dir points to source_text (which has no cache for
        # the test doc), so we get warnings not failures → still passes.
        assert exit_code == 0
