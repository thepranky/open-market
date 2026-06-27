"""
Tests for classify_index_extraction_status.py (case-index extraction_status backfill).

The page-counter is injected so these run with no network. Cover the pure classifier
decision table, the in-place line write, and the run loop (write / dry-run / resume /
canonical upgrade).
"""

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.cases.discovery.classify_index_extraction_status import (
    _apply_status,
    classify_entry,
    run,
)


def _const_pages(n):
    return lambda url: n


def _entry(case_id="eu_test_2022", pdf_url="http://x/doc"):
    return {
        "case_id": case_id, "case_name": "Test", "jurisdiction": "EU",
        "authority": "European Commission", "decision_date": "2022-01-01",
        "sector": "x", "outcome": "cleared", "case_type": "merger",
        "pdf_url": pdf_url,
    }


# ---- pure classifier -------------------------------------------------------

def test_canonical_exists_is_extracted():
    assert classify_entry(_entry(), canonical_exists=True,
                          page_count_fn=_const_pages(99), max_simplified_pages=3) == "extracted"


def test_short_pdf_is_not_applicable():
    assert classify_entry(_entry(), canonical_exists=False,
                          page_count_fn=_const_pages(2), max_simplified_pages=3) == "not_applicable"


def test_long_pdf_is_pending():
    assert classify_entry(_entry(), canonical_exists=False,
                          page_count_fn=_const_pages(30), max_simplified_pages=3) == "pending"


def test_missing_pdf_url_is_unknown():
    assert classify_entry(_entry(pdf_url=None), canonical_exists=False,
                          page_count_fn=_const_pages(2), max_simplified_pages=3) == "unknown"


def test_failed_fetch_is_unknown():
    # A None page count (fetch/parse failure) is unknown — never "simplified".
    assert classify_entry(_entry(), canonical_exists=False,
                          page_count_fn=lambda url: None, max_simplified_pages=3) == "unknown"


# ---- in-place write --------------------------------------------------------

def test_apply_status_appends_then_replaces(tmp_path):
    p = tmp_path / "e.yaml"
    p.write_text("case_id: eu_test_2022\nsector: x\n", encoding="utf-8")
    _apply_status(p, "not_applicable")
    assert "extraction_status: not_applicable" in p.read_text()
    # Other fields are untouched; a second apply replaces, does not duplicate.
    _apply_status(p, "pending")
    text = p.read_text()
    assert text.count("extraction_status:") == 1
    assert "extraction_status: pending" in text
    assert "case_id: eu_test_2022" in text


# ---- run loop --------------------------------------------------------------

def _write_index(tmp_path, jur, entries):
    d = tmp_path / jur
    d.mkdir(parents=True)
    for e in entries:
        (d / f"{e['case_id']}.yaml").write_text(yaml.dump(e, sort_keys=False), encoding="utf-8")
    return tmp_path


def test_run_writes_status_for_short_pdf(tmp_path):
    idx = _write_index(tmp_path, "eu", [_entry("eu_simplified_2022")])
    counts = run(index_dir=idx, jurisdictions=["eu"], case_id=None, limit=None,
                 max_simplified_pages=3, reclassify=False, dry_run=False,
                 page_count_fn=_const_pages(2))
    assert counts["not_applicable"] == 1
    written = yaml.safe_load((idx / "eu" / "eu_simplified_2022.yaml").read_text())
    assert written["extraction_status"] == "not_applicable"


def test_run_dry_run_does_not_write(tmp_path):
    idx = _write_index(tmp_path, "eu", [_entry("eu_simplified_2022")])
    run(index_dir=idx, jurisdictions=["eu"], case_id=None, limit=None,
        max_simplified_pages=3, reclassify=False, dry_run=True, page_count_fn=_const_pages(2))
    written = yaml.safe_load((idx / "eu" / "eu_simplified_2022.yaml").read_text())
    assert "extraction_status" not in written


def test_run_skips_already_classified_without_reclassify(tmp_path):
    e = _entry("eu_done_2022")
    e["extraction_status"] = "not_applicable"
    idx = _write_index(tmp_path, "eu", [e])
    # A page_count_fn that would raise if called proves the entry was skipped.
    def _boom(url):
        raise AssertionError("should not fetch an already-classified entry")
    counts = run(index_dir=idx, jurisdictions=["eu"], case_id=None, limit=None,
                 max_simplified_pages=3, reclassify=False, dry_run=False, page_count_fn=_boom)
    assert counts["skipped"] == 1


def test_run_upgrades_to_extracted_when_canonical_appears(tmp_path):
    # A settled not_applicable entry is upgraded for free (no fetch) once a canonical
    # record exists — even without --reclassify.
    e = _entry("eu_promoted_2022")
    e["extraction_status"] = "not_applicable"
    idx = _write_index(tmp_path, "eu", [e])
    counts = run(index_dir=idx, jurisdictions=["eu"], case_id=None, limit=None,
                 max_simplified_pages=3, reclassify=False, dry_run=False,
                 page_count_fn=lambda url: (_ for _ in ()).throw(AssertionError("no fetch")),
                 canonical_exists_fn=lambda jur, cid: True)
    assert counts["extracted"] == 1
    assert yaml.safe_load((idx / "eu" / "eu_promoted_2022.yaml").read_text())["extraction_status"] == "extracted"


def test_reclassify_corrects_a_misclassified_entry(tmp_path):
    # not_applicable entry that is actually a 30-page decision → corrected to pending.
    e = _entry("eu_mislabelled_2022")
    e["extraction_status"] = "not_applicable"
    idx = _write_index(tmp_path, "eu", [e])
    counts = run(index_dir=idx, jurisdictions=["eu"], case_id=None, limit=None,
                 max_simplified_pages=3, reclassify=True, dry_run=False,
                 page_count_fn=_const_pages(30), canonical_exists_fn=lambda jur, cid: False)
    assert counts["pending"] == 1
    assert yaml.safe_load((idx / "eu" / "eu_mislabelled_2022.yaml").read_text())["extraction_status"] == "pending"


def test_reclassify_failed_fetch_keeps_settled_status(tmp_path):
    # The data-loss guard: --reclassify + a failed fetch must NOT downgrade a good
    # not_applicable to pending.
    e = _entry("eu_simplified_2022")
    e["extraction_status"] = "not_applicable"
    idx = _write_index(tmp_path, "eu", [e])
    counts = run(index_dir=idx, jurisdictions=["eu"], case_id=None, limit=None,
                 max_simplified_pages=3, reclassify=True, dry_run=False,
                 page_count_fn=lambda url: None, canonical_exists_fn=lambda jur, cid: False)
    assert counts["unknown"] == 1
    assert yaml.safe_load((idx / "eu" / "eu_simplified_2022.yaml").read_text())["extraction_status"] == "not_applicable"
