"""
Tests for check_source_links.py.

Covers:
  - collect_url_specs: extracts URLs with correct metadata (doc_type, field, doc_key)
  - classify_results: court-opinion policy (case_page_url warn when pdf_url passes)
  - classify_results: non-court-opinion failures are always errors
  - classify_results: court_opinion case_page_url is an error when pdf_url also fails
  - main(): integration test using mocked HTTP client
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.cases.integrity.check_source_links import (
    UrlSpec,
    classify_results,
    collect_url_specs,
    collect_urls,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ok_result(**kwargs) -> dict:
    base = {"status": 200, "ok": True, "content_type": "application/pdf",
            "final_url": "https://example.com/doc.pdf", "redirected": False, "error": None}
    base.update(kwargs)
    return base


def _fail_result(**kwargs) -> dict:
    base = {"status": 403, "ok": False, "content_type": "",
            "final_url": "https://example.com/page", "redirected": False, "error": None}
    base.update(kwargs)
    return base


def _court_opinion_doc(
    doc_id: str = "doc_1",
    pdf_url: str = "https://court.gov/doc.pdf",
    case_page_url: str | None = "https://docket.gov/case/123",
) -> dict:
    doc = {
        "doc_id": doc_id,
        "doc_type": "court_opinion",
        "pdf_url": pdf_url,
    }
    if case_page_url:
        doc["case_page_url"] = case_page_url
    return doc


def _ec_decision_doc(
    doc_id: str = "doc_ec",
    pdf_url: str = "https://ec.europa.eu/doc.pdf",
    case_page_url: str | None = "https://ec.europa.eu/case",
) -> dict:
    doc = {
        "doc_id": doc_id,
        "doc_type": "merger_decision",
        "pdf_url": pdf_url,
    }
    if case_page_url:
        doc["case_page_url"] = case_page_url
    return doc


# ---------------------------------------------------------------------------
# collect_url_specs
# ---------------------------------------------------------------------------

class TestCollectUrlSpecs:
    def test_extracts_pdf_url(self):
        record = {
            "case_id": "us_test_2025",
            "source_documents": [_court_opinion_doc(case_page_url=None)],
        }
        specs = collect_url_specs(record)
        assert len(specs) == 1
        assert specs[0].field == "pdf_url"
        assert specs[0].url == "https://court.gov/doc.pdf"
        assert specs[0].doc_type == "court_opinion"

    def test_extracts_case_page_url(self):
        record = {
            "case_id": "us_test_2025",
            "source_documents": [_court_opinion_doc()],
        }
        specs = collect_url_specs(record)
        fields = {s.field for s in specs}
        assert "case_page_url" in fields
        assert "pdf_url" in fields

    def test_doc_key_groups_same_doc(self):
        record = {
            "case_id": "us_test_2025",
            "source_documents": [_court_opinion_doc(doc_id="doc_1")],
        }
        specs = collect_url_specs(record)
        doc_keys = {s.doc_key for s in specs}
        assert doc_keys == {"us_test_2025/doc_1"}

    def test_doc_type_preserved_for_ec_decision(self):
        record = {
            "case_id": "eu_test_2020",
            "source_documents": [_ec_decision_doc()],
        }
        specs = collect_url_specs(record)
        for s in specs:
            assert s.doc_type == "merger_decision"

    def test_case_history_source_url(self):
        record = {
            "case_id": "eu_test_2020",
            "source_documents": [],
            "case_history": {
                "events": [
                    {"event_type": "filing", "source_url": "https://example.com/filing.pdf"}
                ]
            },
        }
        specs = collect_url_specs(record)
        assert len(specs) == 1
        assert specs[0].url == "https://example.com/filing.pdf"
        assert specs[0].field == "source_url"
        assert specs[0].doc_type == ""

    def test_no_urls_returns_empty(self):
        record = {"case_id": "eu_test_2020", "source_documents": []}
        assert collect_url_specs(record) == []

    def test_collect_urls_shim_returns_pairs(self):
        record = {
            "case_id": "us_test_2025",
            "source_documents": [_court_opinion_doc(case_page_url=None)],
        }
        pairs = collect_urls(record)
        assert len(pairs) == 1
        url, label = pairs[0]
        assert url == "https://court.gov/doc.pdf"
        assert "us_test_2025" in label


# ---------------------------------------------------------------------------
# classify_results — court-opinion policy
# ---------------------------------------------------------------------------

class TestClassifyResults:

    def _spec(self, field: str, doc_type: str = "court_opinion", doc_key: str = "case/doc") -> UrlSpec:
        return UrlSpec(
            url="https://example.com/" + field,
            label=f"case / doc / {field}",
            doc_type=doc_type,
            field=field,
            doc_key=doc_key,
        )

    def test_court_opinion_case_page_url_failure_is_warning_when_pdf_passed(self):
        """Failing case_page_url + passing pdf_url → warning, not error."""
        pdf_spec = self._spec("pdf_url")
        page_spec = self._spec("case_page_url")
        results = [
            (pdf_spec, _ok_result()),
            (page_spec, _fail_result()),
        ]
        errors, warnings = classify_results(results)
        assert len(errors) == 0
        assert len(warnings) == 1
        assert warnings[0][0].field == "case_page_url"

    def test_court_opinion_case_page_url_failure_is_error_when_pdf_also_failed(self):
        """Both pdf_url and case_page_url fail → case_page_url failure is an error."""
        pdf_spec = self._spec("pdf_url")
        page_spec = self._spec("case_page_url")
        results = [
            (pdf_spec, _fail_result()),
            (page_spec, _fail_result()),
        ]
        errors, warnings = classify_results(results)
        assert len(errors) == 2
        assert len(warnings) == 0

    def test_court_opinion_pdf_failure_is_always_error(self):
        """A failing pdf_url for court_opinion is always an error."""
        pdf_spec = self._spec("pdf_url")
        results = [(pdf_spec, _fail_result())]
        errors, warnings = classify_results(results)
        assert len(errors) == 1
        assert len(warnings) == 0

    def test_non_court_opinion_case_page_url_failure_is_error(self):
        """EC/CMA decision: a failing case_page_url is still an error."""
        pdf_spec = self._spec("pdf_url", doc_type="merger_decision")
        page_spec = self._spec("case_page_url", doc_type="merger_decision")
        results = [
            (pdf_spec, _ok_result()),
            (page_spec, _fail_result()),
        ]
        errors, warnings = classify_results(results)
        assert len(errors) == 1
        assert len(warnings) == 0
        assert errors[0][0].field == "case_page_url"

    def test_all_ok_returns_empty_errors_and_warnings(self):
        spec = self._spec("pdf_url")
        results = [(spec, _ok_result())]
        errors, warnings = classify_results(results)
        assert errors == []
        assert warnings == []

    def test_court_opinion_case_page_only_no_pdf_failure_is_error(self):
        """case_page_url failure with no pdf_url in same doc → error (pdf_url never passed)."""
        page_spec = self._spec("case_page_url")
        results = [(page_spec, _fail_result())]
        errors, warnings = classify_results(results)
        assert len(errors) == 1
        assert len(warnings) == 0

    def test_different_doc_key_isolation(self):
        """pdf_url passing for doc A must not shield case_page_url failure for doc B."""
        pdf_spec = self._spec("pdf_url", doc_key="case/doc_a")
        page_spec = UrlSpec(
            url="https://example.com/case_page_url",
            label="case / doc_b / case_page_url",
            doc_type="court_opinion",
            field="case_page_url",
            doc_key="case/doc_b",
        )
        results = [
            (pdf_spec, _ok_result()),
            (page_spec, _fail_result()),
        ]
        errors, warnings = classify_results(results)
        assert len(errors) == 1
        assert len(warnings) == 0


# ---------------------------------------------------------------------------
# main() integration — mocked HTTP
# ---------------------------------------------------------------------------

class TestMain:
    def _make_case_yaml(self, tmp_path: Path, docs: list[dict], case_id: str = "us_test_2025") -> None:
        record = {
            "case_id": case_id,
            "source_documents": docs,
            "procedure_stage": "federal_district_court",
            "metadata": {
                "extraction_method": "ai_extracted",
                "review_status": "unreviewed",
                "overall_confidence": 0.7,
                "created_date": "2025-01-01",
                "last_updated_date": "2025-01-01",
                "tags": [],
            },
        }
        jur_dir = tmp_path / "us"
        jur_dir.mkdir(parents=True, exist_ok=True)
        (jur_dir / f"{case_id}.yaml").write_text(yaml.dump(record))

    def _mock_client(self, url_ok_map: dict[str, bool]):
        """Return a mock httpx.Client context manager with per-URL responses."""
        client = MagicMock()
        client.__enter__ = lambda s: s
        client.__exit__ = MagicMock(return_value=False)

        def head_side_effect(url, **kwargs):
            ok = url_ok_map.get(url, True)
            resp = MagicMock()
            resp.status_code = 200 if ok else 403
            resp.headers = {"content-type": "application/pdf" if ok else "text/html"}
            resp.url = url
            return resp

        client.head = head_side_effect
        client.get = head_side_effect
        return client

    def test_court_opinion_passing_pdf_failing_case_page_returns_zero(self, tmp_path, capsys):
        from scripts.cases.integrity.check_source_links import main

        pdf_url = "https://court.gov/doc.pdf"
        page_url = "https://docket.gov/case/123"
        self._make_case_yaml(tmp_path, [_court_opinion_doc(pdf_url=pdf_url, case_page_url=page_url)])

        url_ok = {pdf_url: True, page_url: False}
        mock_client = self._mock_client(url_ok)

        with (
            patch("scripts.cases.integrity.check_source_links.DATA_DIR", tmp_path),
            patch("scripts.cases.integrity.check_source_links.httpx.Client", return_value=mock_client),
        ):
            rc = main([])

        assert rc == 0
        captured = capsys.readouterr()
        assert "not blocking" in captured.out or "warning" in captured.out.lower()

    def test_court_opinion_failing_pdf_returns_one(self, tmp_path, capsys):
        from scripts.cases.integrity.check_source_links import main

        pdf_url = "https://court.gov/doc.pdf"
        self._make_case_yaml(tmp_path, [_court_opinion_doc(pdf_url=pdf_url, case_page_url=None)])

        url_ok = {pdf_url: False}
        mock_client = self._mock_client(url_ok)

        with (
            patch("scripts.cases.integrity.check_source_links.DATA_DIR", tmp_path),
            patch("scripts.cases.integrity.check_source_links.httpx.Client", return_value=mock_client),
        ):
            rc = main([])

        assert rc == 1
        captured = capsys.readouterr()
        assert "BROKEN" in captured.out

    def test_ec_decision_failing_case_page_url_returns_one(self, tmp_path, capsys):
        from scripts.cases.integrity.check_source_links import main

        pdf_url = "https://ec.europa.eu/doc.pdf"
        page_url = "https://ec.europa.eu/cases/123"
        self._make_case_yaml(
            tmp_path,
            [_ec_decision_doc(pdf_url=pdf_url, case_page_url=page_url)],
            case_id="eu_test_2020",
        )

        url_ok = {pdf_url: True, page_url: False}
        mock_client = self._mock_client(url_ok)

        with (
            patch("scripts.cases.integrity.check_source_links.DATA_DIR", tmp_path),
            patch("scripts.cases.integrity.check_source_links.httpx.Client", return_value=mock_client),
        ):
            rc = main([])

        assert rc == 1
        captured = capsys.readouterr()
        assert "BROKEN" in captured.out

    def test_all_passing_returns_zero(self, tmp_path, capsys):
        from scripts.cases.integrity.check_source_links import main

        pdf_url = "https://court.gov/doc.pdf"
        page_url = "https://docket.gov/case/123"
        self._make_case_yaml(tmp_path, [_court_opinion_doc(pdf_url=pdf_url, case_page_url=page_url)])

        url_ok = {pdf_url: True, page_url: True}
        mock_client = self._mock_client(url_ok)

        with (
            patch("scripts.cases.integrity.check_source_links.DATA_DIR", tmp_path),
            patch("scripts.cases.integrity.check_source_links.httpx.Client", return_value=mock_client),
        ):
            rc = main([])

        assert rc == 0

    def test_no_yaml_files_returns_one(self, tmp_path, capsys):
        from scripts.cases.integrity.check_source_links import main

        with patch("scripts.cases.integrity.check_source_links.DATA_DIR", tmp_path):
            rc = main([])

        assert rc == 1

    def test_cases_dir_and_case_id_scope_to_one_case(self, tmp_path, capsys):
        from scripts.cases.integrity.check_source_links import main

        first_pdf = "https://court.gov/first.pdf"
        second_pdf = "https://court.gov/second.pdf"
        self._make_case_yaml(
            tmp_path,
            [_court_opinion_doc(pdf_url=first_pdf, case_page_url=None)],
            case_id="us_first_2025",
        )
        self._make_case_yaml(
            tmp_path,
            [_court_opinion_doc(pdf_url=second_pdf, case_page_url=None)],
            case_id="us_second_2025",
        )

        mock_client = self._mock_client({first_pdf: True, second_pdf: False})

        with patch("scripts.cases.integrity.check_source_links.httpx.Client", return_value=mock_client):
            rc = main([
                "--cases-dir",
                str(tmp_path),
                "--case-id",
                "us_first_2025",
            ])

        assert rc == 0

    def test_case_id_missing_returns_one(self, tmp_path, capsys):
        from scripts.cases.integrity.check_source_links import main

        rc = main([
            "--cases-dir",
            str(tmp_path),
            "--case-id",
            "us_missing_2025",
        ])

        assert rc == 1
        captured = capsys.readouterr()
        assert "No file found" in captured.err
