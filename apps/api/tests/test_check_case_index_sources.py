"""
Tests for check_case_index_sources.py.

Covers:
  - check_url_present: null vs non-null source_url
  - check_domain_official: allowlist accept/reject per jurisdiction; subdomain handling
  - check_ec_case_format: valid /cases/M.NNNNN, malformed paths, non-portal URLs
  - check_ftc_matter_format: 7-digit modern ID, NNN-NNNN legacy ID, bad slugs, non-FTC URLs
  - check_entry: end-to-end per-entry orchestration (null URL, bad domain, bad format, HTTP)
  - run_checks: loads real index YAML and returns one result per entry
  - main(): integration with mocked HTTP — pass/fail/warn exit codes
"""
import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.cases.models.case_index import CaseIndexEntry
from scripts.cases.check_case_index_sources import (
    check_domain_official,
    check_ec_case_format,
    check_entry,
    check_ftc_matter_format,
    check_url_present,
    main,
    run_checks,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _entry(
    case_id: str = "eu_test_2023",
    jurisdiction: str = "EU",
    source_url: str | None = "https://competition-cases.ec.europa.eu/cases/M.10000",
) -> CaseIndexEntry:
    return CaseIndexEntry(
        case_id=case_id,
        case_name="Test Case",
        jurisdiction=jurisdiction,
        authority="EC",
        decision_date=date(2023, 1, 1),
        sector="tech",
        outcome="cleared",
        source_url=source_url,
    )


def _mock_http_client(url_status: dict[str, int]) -> MagicMock:
    """Return a mock httpx.Client with per-URL status codes."""
    client = MagicMock()
    client.__enter__ = lambda s: s
    client.__exit__ = MagicMock(return_value=False)

    def _response(url, **kwargs):
        code = url_status.get(url, 200)
        resp = MagicMock()
        resp.status_code = code
        resp.headers = {"content-type": "text/html"}
        resp.url = url
        return resp

    client.head = _response
    client.get = _response
    return client


# ---------------------------------------------------------------------------
# check_url_present
# ---------------------------------------------------------------------------

class TestCheckUrlPresent:
    def test_null_url_is_warn(self):
        item = check_url_present(_entry(source_url=None))
        assert item.status == "WARN"
        assert "null" in item.message

    def test_present_url_is_pass(self):
        item = check_url_present(_entry(source_url="https://ec.europa.eu/doc"))
        assert item.status == "PASS"


# ---------------------------------------------------------------------------
# check_domain_official
# ---------------------------------------------------------------------------

class TestCheckDomainOfficial:

    # EU ---

    def test_eu_competition_portal_accepted(self):
        item = check_domain_official(
            "https://competition-cases.ec.europa.eu/cases/M.10000", "EU"
        )
        assert item.status == "PASS"

    def test_eu_ec_presscorner_accepted(self):
        item = check_domain_official(
            "https://ec.europa.eu/commission/presscorner/detail/en/ip_22_5364", "EU"
        )
        assert item.status == "PASS"

    def test_eu_eur_lex_accepted(self):
        item = check_domain_official(
            "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:12345", "EU"
        )
        assert item.status == "PASS"

    def test_eu_unofficial_domain_fails(self):
        item = check_domain_official("https://reuters.com/article/foo", "EU")
        assert item.status == "FAIL"
        assert "reuters.com" in item.message

    # UK ---

    def test_uk_gov_uk_accepted(self):
        item = check_domain_official(
            "https://www.gov.uk/cma-cases/adobe-slash-figma-merger-inquiry", "UK"
        )
        assert item.status == "PASS"

    def test_uk_assets_publishing_accepted(self):
        item = check_domain_official(
            "https://assets.publishing.service.gov.uk/media/123/doc.pdf", "UK"
        )
        assert item.status == "PASS"

    def test_uk_unofficial_domain_fails(self):
        item = check_domain_official("https://bbc.co.uk/news/foo", "UK")
        assert item.status == "FAIL"

    # US ---

    def test_us_ftc_gov_accepted(self):
        item = check_domain_official(
            "https://www.ftc.gov/legal-library/browse/cases-proceedings/2210077-foo", "US"
        )
        assert item.status == "PASS"

    def test_us_ftc_gov_without_www_accepted(self):
        item = check_domain_official("https://ftc.gov/some-page", "US")
        assert item.status == "PASS"

    def test_us_justice_gov_accepted(self):
        item = check_domain_official("https://www.justice.gov/atr/case/foo", "US")
        assert item.status == "PASS"

    def test_us_uscourts_subdomain_accepted(self):
        item = check_domain_official("https://sdny.uscourts.gov/cases/123", "US")
        assert item.status == "PASS"

    def test_us_unofficial_domain_fails(self):
        item = check_domain_official("https://law360.com/articles/foo", "US")
        assert item.status == "FAIL"

    # Port stripping ---

    def test_url_with_port_still_checked(self):
        item = check_domain_official("https://ec.europa.eu:443/doc", "EU")
        assert item.status == "PASS"


# ---------------------------------------------------------------------------
# check_ec_case_format
# ---------------------------------------------------------------------------

class TestCheckEcCaseFormat:
    def test_valid_ec_portal_url(self):
        item = check_ec_case_format(
            "https://competition-cases.ec.europa.eu/cases/M.10806"
        )
        assert item is not None
        assert item.status == "PASS"
        assert "M.10806" in item.message

    def test_valid_ec_portal_large_number(self):
        item = check_ec_case_format(
            "https://competition-cases.ec.europa.eu/cases/M.10188"
        )
        assert item is not None
        assert item.status == "PASS"

    def test_ec_portal_missing_m_prefix_fails(self):
        item = check_ec_case_format(
            "https://competition-cases.ec.europa.eu/cases/10806"
        )
        assert item is not None
        assert item.status == "FAIL"
        assert "M.<digits>" in item.message

    def test_ec_portal_extra_path_fails(self):
        item = check_ec_case_format(
            "https://competition-cases.ec.europa.eu/cases/M.10806/documents"
        )
        assert item is not None
        assert item.status == "FAIL"

    def test_non_portal_url_returns_none(self):
        assert check_ec_case_format("https://ec.europa.eu/commission/presscorner/detail/en/foo") is None

    def test_eur_lex_url_returns_none(self):
        assert check_ec_case_format("https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:12345") is None

    def test_non_ec_url_returns_none(self):
        assert check_ec_case_format("https://www.ftc.gov/foo") is None


# ---------------------------------------------------------------------------
# check_ftc_matter_format
# ---------------------------------------------------------------------------

class TestCheckFtcMatterFormat:
    def test_modern_7digit_format_accepted(self):
        item = check_ftc_matter_format(
            "https://www.ftc.gov/legal-library/browse/cases-proceedings/2210077-microsoftactivision-blizzard-matter"
        )
        assert item is not None
        assert item.status == "PASS"
        assert "2210077" in item.message

    def test_legacy_nnn_nnnn_format_accepted(self):
        item = check_ftc_matter_format(
            "https://www.ftc.gov/legal-library/browse/cases-proceedings/201-0144-illumina-inc-grail-inc-matter"
        )
        assert item is not None
        assert item.status == "PASS"
        assert "201-0144" in item.message

    def test_slug_without_matter_prefix_fails(self):
        # A plausible-looking but wrong slug
        item = check_ftc_matter_format(
            "https://www.ftc.gov/legal-library/browse/cases-proceedings/microsoft-corporation-activision-blizzard-inc"
        )
        assert item is not None
        assert item.status == "FAIL"
        assert "matter ID" in item.message

    def test_non_proceedings_ftc_url_returns_none(self):
        # FTC domain but not a cases-proceedings URL
        assert check_ftc_matter_format("https://ftc.gov/news-events/press-releases/2023/01/foo") is None

    def test_non_ftc_url_returns_none(self):
        assert check_ftc_matter_format("https://www.justice.gov/atr/case/foo") is None
        assert check_ftc_matter_format("https://competition-cases.ec.europa.eu/cases/M.10000") is None


# ---------------------------------------------------------------------------
# check_entry — orchestration
# ---------------------------------------------------------------------------

class TestCheckEntry:
    def test_null_url_returns_warn_no_further_checks(self):
        entry = _entry(source_url=None)
        result = check_entry(entry, client=None, timeout=10)
        assert result.status == "WARN"
        assert len(result.items) == 1
        assert result.items[0].status == "WARN"

    def test_unofficial_domain_returns_fail_stops_before_http(self):
        entry = _entry(
            jurisdiction="EU",
            source_url="https://reuters.com/article/eu-merger-foo",
        )
        result = check_entry(entry, client=None, timeout=10)
        assert result.status == "FAIL"
        domain_item = next(i for i in result.items if "domain" in i.message.lower() or "reuters" in i.message.lower())
        assert domain_item.status == "FAIL"
        # HTTP check was skipped — only presence + domain items present
        assert all("HTTP" not in i.message for i in result.items)

    def test_bad_ec_format_fails(self):
        entry = _entry(
            jurisdiction="EU",
            source_url="https://competition-cases.ec.europa.eu/cases/10806",  # missing M.
        )
        result = check_entry(entry, client=None, timeout=10)
        assert result.status == "FAIL"

    def test_bad_ftc_format_fails(self):
        entry = _entry(
            case_id="us_test",
            jurisdiction="US",
            source_url="https://www.ftc.gov/legal-library/browse/cases-proceedings/microsoft-foo",
        )
        result = check_entry(entry, client=None, timeout=10)
        assert result.status == "FAIL"

    def test_valid_ec_url_no_http_is_pass(self):
        entry = _entry(
            jurisdiction="EU",
            source_url="https://competition-cases.ec.europa.eu/cases/M.10806",
        )
        result = check_entry(entry, client=None, timeout=10)
        assert result.status == "PASS"

    def test_http_404_makes_fail(self):
        entry = _entry(
            jurisdiction="EU",
            source_url="https://competition-cases.ec.europa.eu/cases/M.10806",
        )
        mock_client = MagicMock()
        mock_client.head.return_value = MagicMock(
            status_code=404, headers={}, url="https://competition-cases.ec.europa.eu/cases/M.10806"
        )
        result = check_entry(entry, client=mock_client, timeout=10)
        assert result.status == "FAIL"
        http_item = next(i for i in result.items if "HTTP" in i.message)
        assert http_item.status == "FAIL"

    def test_http_200_makes_pass(self):
        entry = _entry(
            jurisdiction="EU",
            source_url="https://competition-cases.ec.europa.eu/cases/M.10806",
        )
        mock_client = MagicMock()
        mock_client.head.return_value = MagicMock(
            status_code=200, headers={}, url="https://competition-cases.ec.europa.eu/cases/M.10806"
        )
        result = check_entry(entry, client=mock_client, timeout=10)
        assert result.status == "PASS"

    def test_uk_gov_url_no_ec_ftc_format_checks(self):
        entry = _entry(
            case_id="uk_test",
            jurisdiction="UK",
            source_url="https://www.gov.uk/cma-cases/adobe-slash-figma-merger-inquiry",
        )
        result = check_entry(entry, client=None, timeout=10)
        assert result.status == "PASS"
        # No EC-format or FTC-format check items
        assert not any("EC case" in i.message or "FTC matter" in i.message for i in result.items)


# ---------------------------------------------------------------------------
# run_checks — integration against real index directory
# ---------------------------------------------------------------------------

class TestRunChecks:
    def test_loads_all_thirty_four_entries(self):
        index_dir = Path(__file__).resolve().parents[3] / "data" / "case_index"
        results = run_checks(index_dir, client=None, timeout=10)
        assert len(results) == 34

    def test_all_entries_have_case_id(self):
        index_dir = Path(__file__).resolve().parents[3] / "data" / "case_index"
        results = run_checks(index_dir, client=None, timeout=10)
        assert all(r.case_id for r in results)

    def test_no_yaml_load_failures(self):
        index_dir = Path(__file__).resolve().parents[3] / "data" / "case_index"
        results = run_checks(index_dir, client=None, timeout=10)
        load_fails = [r for r in results if any("YAML load error" in i.message for i in r.items)]
        assert load_fails == [], f"YAML load errors: {[r.case_id for r in load_fails]}"

    def test_broadcom_vmware_uses_m10806(self):
        """eu_broadcom_vmware_2023 should reference M.10806, not M.10939."""
        index_dir = Path(__file__).resolve().parents[3] / "data" / "case_index"
        results = run_checks(index_dir, client=None, timeout=10)
        bv = next(r for r in results if r.case_id == "eu_broadcom_vmware_2023")
        assert bv.url is not None
        assert "M.10806" in bv.url

    def test_ftc_matter_ids_valid_format(self):
        """FTC entries with a source_url must pass the matter-ID format check."""
        index_dir = Path(__file__).resolve().parents[3] / "data" / "case_index"
        results = run_checks(index_dir, client=None, timeout=10)
        ftc_with_url = [r for r in results if r.case_id.startswith("us_ftc") and r.url is not None]
        assert len(ftc_with_url) >= 2, "expected at least two FTC entries with source URLs"
        for r in ftc_with_url:
            ftc_items = [i for i in r.items if "FTC matter" in i.message]
            assert ftc_items, f"{r.case_id}: no FTC format check item found"
            assert all(i.status == "PASS" for i in ftc_items), \
                f"{r.case_id}: FTC format check failed: {[i.message for i in ftc_items]}"

    def test_all_eu_entries_pass_domain_check(self):
        index_dir = Path(__file__).resolve().parents[3] / "data" / "case_index"
        results = run_checks(index_dir, client=None, timeout=10)
        eu_results = [r for r in results if r.case_id.startswith("eu_")]
        for r in eu_results:
            domain_fails = [i for i in r.items if i.status == "FAIL" and "domain" in i.message.lower()]
            assert domain_fails == [], f"{r.case_id}: domain check failed: {domain_fails}"

    def test_no_fail_without_http(self):
        """All 34 entries should PASS or WARN with no-http checks (no live requests)."""
        index_dir = Path(__file__).resolve().parents[3] / "data" / "case_index"
        results = run_checks(index_dir, client=None, timeout=10)
        fails = [r for r in results if r.status == "FAIL"]
        assert fails == [], f"Unexpected failures: {[(r.case_id, [i.message for i in r.items if i.status == 'FAIL']) for r in fails]}"


# ---------------------------------------------------------------------------
# main() — exit codes and report output, mocked HTTP
# ---------------------------------------------------------------------------

class TestMain:
    """Integration tests using mocked HTTP and a real index YAML directory."""

    _INDEX_DIR = str(Path(__file__).resolve().parents[3] / "data" / "case_index")

    def test_no_http_flag_exits_zero(self, capsys):
        rc = main(["--no-http", "--index-dir", self._INDEX_DIR])
        assert rc == 0

    def test_no_http_flag_prints_summary(self, capsys):
        main(["--no-http", "--index-dir", self._INDEX_DIR])
        out = capsys.readouterr().out
        assert "Summary:" in out
        assert "PASS" in out

    def test_nonexistent_index_dir_returns_one(self, capsys):
        rc = main(["--no-http", "--index-dir", "/does/not/exist"])
        assert rc == 1

    def test_mocked_http_all_200_exits_zero(self, tmp_path, capsys):
        """Write a single valid EU entry; mock all HTTP as 200; expect exit 0."""
        eu_dir = tmp_path / "eu"
        eu_dir.mkdir()
        (eu_dir / "eu_test_2023.yaml").write_text(yaml.dump({
            "case_id": "eu_test_2023",
            "case_name": "Test Case",
            "jurisdiction": "EU",
            "authority": "EC",
            "decision_date": "2023-01-01",
            "sector": "tech",
            "outcome": "cleared",
            "source_url": "https://competition-cases.ec.europa.eu/cases/M.10000",
        }))
        url = "https://competition-cases.ec.europa.eu/cases/M.10000"
        mock_client = _mock_http_client({url: 200})
        with patch("scripts.cases.check_case_index_sources.httpx.Client", return_value=mock_client):
            rc = main(["--index-dir", str(tmp_path)])
        assert rc == 0

    def test_mocked_http_404_exits_one(self, tmp_path, capsys):
        """404 HTTP response should produce a FAIL and exit 1."""
        eu_dir = tmp_path / "eu"
        eu_dir.mkdir()
        (eu_dir / "eu_test_2023.yaml").write_text(yaml.dump({
            "case_id": "eu_test_2023",
            "case_name": "Test Case",
            "jurisdiction": "EU",
            "authority": "EC",
            "decision_date": "2023-01-01",
            "sector": "tech",
            "outcome": "cleared",
            "source_url": "https://competition-cases.ec.europa.eu/cases/M.10000",
        }))
        url = "https://competition-cases.ec.europa.eu/cases/M.10000"
        mock_client = _mock_http_client({url: 404})
        with patch("scripts.cases.check_case_index_sources.httpx.Client", return_value=mock_client):
            rc = main(["--index-dir", str(tmp_path)])
        assert rc == 1
        out = capsys.readouterr().out
        assert "FAIL" in out

    def test_null_url_produces_warn_exit_zero(self, tmp_path, capsys):
        """An entry with source_url=null should WARN but not cause exit 1."""
        uk_dir = tmp_path / "uk"
        uk_dir.mkdir()
        (uk_dir / "uk_test_2022.yaml").write_text(yaml.dump({
            "case_id": "uk_test_2022",
            "case_name": "Test",
            "jurisdiction": "UK",
            "authority": "Competition and Markets Authority",
            "decision_date": "2022-01-01",
            "sector": "media_entertainment",
            "outcome": "cleared",
            "source_url": None,
        }))
        rc = main(["--no-http", "--index-dir", str(tmp_path)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "WARN" in out

    def test_unofficial_domain_produces_fail_exit_one(self, tmp_path, capsys):
        """A non-official domain should FAIL even without HTTP checks."""
        eu_dir = tmp_path / "eu"
        eu_dir.mkdir()
        (eu_dir / "eu_test_2023.yaml").write_text(yaml.dump({
            "case_id": "eu_test_2023",
            "case_name": "Test",
            "jurisdiction": "EU",
            "authority": "EC",
            "decision_date": "2023-01-01",
            "sector": "tech",
            "outcome": "cleared",
            "source_url": "https://reuters.com/article/eu-merger-foo",
        }))
        rc = main(["--no-http", "--index-dir", str(tmp_path)])
        assert rc == 1
        out = capsys.readouterr().out
        assert "FAIL" in out
        assert "reuters.com" in out

    def test_bad_ec_format_produces_fail_exit_one(self, tmp_path, capsys):
        """EC portal URL with malformed case number should FAIL."""
        eu_dir = tmp_path / "eu"
        eu_dir.mkdir()
        (eu_dir / "eu_test_2023.yaml").write_text(yaml.dump({
            "case_id": "eu_test_2023",
            "case_name": "Test",
            "jurisdiction": "EU",
            "authority": "EC",
            "decision_date": "2023-01-01",
            "sector": "tech",
            "outcome": "cleared",
            "source_url": "https://competition-cases.ec.europa.eu/cases/10806",  # missing M.
        }))
        rc = main(["--no-http", "--index-dir", str(tmp_path)])
        assert rc == 1

    def test_bad_ftc_slug_produces_fail_exit_one(self, tmp_path, capsys):
        """FTC URL with unrecognised matter-ID slug should FAIL."""
        us_dir = tmp_path / "us"
        us_dir.mkdir()
        (us_dir / "us_test_2023.yaml").write_text(yaml.dump({
            "case_id": "us_test_2023",
            "case_name": "Test",
            "jurisdiction": "US",
            "authority": "FTC",
            "decision_date": "2023-01-01",
            "sector": "tech",
            "outcome": "cleared",
            "source_url": "https://www.ftc.gov/legal-library/browse/cases-proceedings/microsoft-corp-foo",
        }))
        rc = main(["--no-http", "--index-dir", str(tmp_path)])
        assert rc == 1
