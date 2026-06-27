import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.cases.extract import run_bulk_extraction as bulk


def _write_index(root: Path, case_id: str, **fields) -> None:
    path = root / "eu" / f"{case_id}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "case_id": case_id,
        "case_name": "Test",
        "jurisdiction": "EU",
        "authority": "European Commission",
        "decision_date": "2026-01-01",
        "sector": "test",
        "outcome": "cleared",
        "pdf_url": f"https://example.com/{case_id}.pdf",
    }
    data.update(fields)
    path.write_text(yaml.dump(data), encoding="utf-8")


def test_build_queue_skips_not_applicable_before_language_handling(tmp_path, monkeypatch):
    index_dir = tmp_path / "case_index"
    cases_dir = tmp_path / "cases"
    monkeypatch.setattr(bulk, "_INDEX_DIR", index_dir)
    monkeypatch.setattr(bulk, "_CASES_DIR", cases_dir)
    _write_index(index_dir, "eu_pending_de", pdf_language="deu", extraction_status="pending")
    _write_index(
        index_dir,
        "eu_not_applicable_de",
        pdf_language="deu",
        extraction_status="not_applicable",
    )

    queue = bulk._build_queue("eu")
    by_id = {entry["case_id"]: entry for entry in queue}

    assert by_id["eu_pending_de"]["skip_reason"] is None
    assert by_id["eu_pending_de"]["pdf_language"] == "deu"
    assert by_id["eu_not_applicable_de"]["skip_reason"] == "not_applicable"


def test_dry_run_prints_pending_language_buckets(tmp_path, monkeypatch, capsys):
    index_dir = tmp_path / "case_index"
    cases_dir = tmp_path / "cases"
    runs_dir = tmp_path / "runs"
    monkeypatch.setattr(bulk, "_INDEX_DIR", index_dir)
    monkeypatch.setattr(bulk, "_CASES_DIR", cases_dir)
    monkeypatch.setattr(bulk, "_RUNS_DIR", runs_dir)
    _write_index(index_dir, "eu_pending_de", pdf_language="deu", extraction_status="pending")
    _write_index(index_dir, "eu_pending_fr", pdf_language="fra", extraction_status="pending")

    bulk.main(["--jurisdiction", "eu", "--dry-run"])

    out = capsys.readouterr().out
    assert "Pending languages: deu=1, fra=1" in out
    assert "eu_pending_de  [deu]" in out
