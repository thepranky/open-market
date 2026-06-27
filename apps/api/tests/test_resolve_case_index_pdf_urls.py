"""
Tests for resolve_case_index_pdf_urls.py — the shared batch CLI.

A stub resolver is injected so the cross-cutting batch logic is exercised with no
network: surgical pdf_url write + field ordering, dry-run, overwrite, skip
existing, the outcome-relevance filter, and that ordinary misses are non-fatal.
"""

import sys
from pathlib import Path
from typing import Optional

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "cases" / "discovery"))

from pdf_resolvers import PdfCandidate, PdfResolution  # noqa: E402
from resolve_case_index_pdf_urls import patch_pdf_url, run  # noqa: E402


class _StubResolver:
    """Returns a fixed PdfResolution for any handled entry."""

    name = "stub"

    def __init__(self, resolution: PdfResolution, *, jurisdiction="US",
                 default_outcomes: Optional[set] = None):
        self._res = resolution
        self.jurisdiction = jurisdiction
        self.authority = None
        self.default_outcomes = default_outcomes

    def can_handle(self, entry):
        return entry.jurisdiction == self.jurisdiction

    def resolve(self, entry, *, timeout):
        return self._res


_RESOLVED = PdfResolution.resolved("stub", "https://x/doc.pdf", "ok")


def _entry(case_id="us_test_2022", outcome="blocked", pdf_url=None):
    e = {
        "case_id": case_id, "case_name": "Test", "jurisdiction": "US",
        "authority": "DOJ", "decision_date": "2022-01-01", "sector": "x",
        "outcome": outcome, "case_type": "merger",
        "source_url": "https://www.justice.gov/atr/case/x",
        "concept_refs": [],
    }
    if pdf_url:
        e["pdf_url"] = pdf_url
    return e


def _write(tmp_path, jur, entries):
    d = tmp_path / jur
    d.mkdir(parents=True)
    for e in entries:
        (d / f"{e['case_id']}.yaml").write_text(yaml.dump(e, sort_keys=False),
                                                encoding="utf-8")
    return tmp_path


def _run(tmp_path, resolver, **over):
    kw = dict(index_dir=tmp_path, resolvers=[resolver], jurisdictions=["us"],
              authority=None, case_id=None, all_outcomes=False, limit=None,
              overwrite=False, delay=0.0, timeout=5.0, dry_run=False,
              sleep_fn=lambda _s: None)
    kw.update(over)
    return run(**kw)


# ------------------------------------------------------------- surgical write

def test_patch_inserts_after_source_url():
    text = "case_id: x\nsource_url: http://s\nconcept_refs: []\n"
    out = patch_pdf_url(text, "http://p")
    lines = out.splitlines()
    assert lines[lines.index("source_url: http://s") + 1] == "pdf_url: http://p"
    assert "concept_refs: []" in out  # nothing else disturbed


def test_patch_replaces_existing_pdf_url():
    text = "source_url: http://s\npdf_url: http://old\n"
    out = patch_pdf_url(text, "http://new")
    assert out.count("pdf_url:") == 1
    assert "pdf_url: http://new" in out


def test_patch_appends_when_no_source_url():
    out = patch_pdf_url("case_id: x\n", "http://p")
    assert out.endswith("pdf_url: http://p\n")


def test_patch_inserts_url_with_backreference_literally():
    # A URL containing a \1-style sequence must be written verbatim, not treated
    # as an re.sub backreference.
    text = "source_url: http://s\n"
    out = patch_pdf_url(text, r"http://x/\1_doc.pdf")
    assert r"pdf_url: http://x/\1_doc.pdf" in out


# ------------------------------------------------------------- run loop

def test_run_writes_resolved_pdf_url(tmp_path):
    _write(tmp_path, "us", [_entry()])
    counts = _run(tmp_path, _StubResolver(_RESOLVED))
    assert counts["resolved"] == 1
    written = yaml.safe_load((tmp_path / "us" / "us_test_2022.yaml").read_text())
    assert written["pdf_url"] == "https://x/doc.pdf"


def test_run_dry_run_does_not_write(tmp_path):
    _write(tmp_path, "us", [_entry()])
    counts = _run(tmp_path, _StubResolver(_RESOLVED), dry_run=True)
    assert counts["resolved"] == 1
    assert "pdf_url" not in yaml.safe_load(
        (tmp_path / "us" / "us_test_2022.yaml").read_text())


def test_run_skips_existing_without_overwrite(tmp_path):
    _write(tmp_path, "us", [_entry(pdf_url="https://x/old.pdf")])

    def _boom(*a, **k):
        raise AssertionError("must not resolve an entry that already has a pdf_url")

    r = _StubResolver(_RESOLVED)
    r.resolve = _boom
    counts = _run(tmp_path, r)
    assert counts["skipped_existing"] == 1


def test_run_overwrite_replaces_existing(tmp_path):
    _write(tmp_path, "us", [_entry(pdf_url="https://x/old.pdf")])
    counts = _run(tmp_path, _StubResolver(_RESOLVED), overwrite=True)
    assert counts["resolved"] == 1
    written = yaml.safe_load((tmp_path / "us" / "us_test_2022.yaml").read_text())
    assert written["pdf_url"] == "https://x/doc.pdf"


def test_run_outcome_filter_skips_off_default(tmp_path):
    # default_outcomes={blocked}; a 'cleared' entry is skipped unless --all-outcomes.
    _write(tmp_path, "us", [_entry(outcome="cleared")])
    r = _StubResolver(_RESOLVED, default_outcomes={"blocked"})
    counts = _run(tmp_path, r)
    assert counts["skipped_outcome"] == 1
    assert counts["resolved"] == 0


def test_run_all_outcomes_overrides_filter(tmp_path):
    _write(tmp_path, "us", [_entry(outcome="cleared")])
    r = _StubResolver(_RESOLVED, default_outcomes={"blocked"})
    counts = _run(tmp_path, r, all_outcomes=True)
    assert counts["resolved"] == 1


def test_run_manual_required_is_nonfatal_and_unwritten(tmp_path):
    _write(tmp_path, "us", [_entry()])
    manual = PdfResolution.manual("stub", "ambiguous",
                                  [PdfCandidate("u", "Complaint", "s", 0, "r")])
    counts = _run(tmp_path, _StubResolver(manual))
    assert counts["manual_required"] == 1
    assert "pdf_url" not in yaml.safe_load(
        (tmp_path / "us" / "us_test_2022.yaml").read_text())


def test_run_limit_caps_processing(tmp_path):
    _write(tmp_path, "us", [_entry("us_a_2022"), _entry("us_b_2022"),
                            _entry("us_c_2022")])
    counts = _run(tmp_path, _StubResolver(_RESOLVED), limit=2)
    assert counts["resolved"] == 2


def test_run_case_id_targets_single_entry(tmp_path):
    _write(tmp_path, "us", [_entry("us_a_2022"), _entry("us_b_2022")])
    counts = _run(tmp_path, _StubResolver(_RESOLVED), case_id="us_b_2022")
    assert counts["resolved"] == 1
    assert "pdf_url" not in yaml.safe_load(
        (tmp_path / "us" / "us_a_2022.yaml").read_text())
