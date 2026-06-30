"""Compatibility tests for deprecated promotion script names."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.cases.promote import bulk_promote_pass, promote_case_pipeline


def test_old_case_promotion_wrapper_delegates_and_warns(monkeypatch, capsys):
    delegate = MagicMock(return_value=0)
    monkeypatch.setattr(promote_case_pipeline, "_run_main", delegate)

    rc = promote_case_pipeline.main(["--case-id", "eu_test_2020"])

    assert rc == 0
    delegate.assert_called_once_with(["--case-id", "eu_test_2020"])
    captured = capsys.readouterr()
    assert "DEPRECATED" in captured.err
    assert "run_case_promotion.py" in captured.err


def test_old_bulk_promotion_wrapper_delegates_and_warns(monkeypatch, capsys):
    delegate = MagicMock(return_value=0)
    monkeypatch.setattr(bulk_promote_pass, "_run_main", delegate)

    rc = bulk_promote_pass.main(["--dry-run"])

    assert rc == 0
    delegate.assert_called_once_with(["--dry-run"])
    captured = capsys.readouterr()
    assert "DEPRECATED" in captured.err
    assert "run_bulk_promotion.py" in captured.err


def test_old_import_paths_reexport_public_helpers():
    assert callable(promote_case_pipeline.check_draft_integrity)
    assert callable(promote_case_pipeline.find_merged_draft)
    assert callable(promote_case_pipeline.unresolved_conflicts)
    assert callable(bulk_promote_pass.review_status)
    assert callable(bulk_promote_pass.discover_candidates)
    assert callable(bulk_promote_pass.parse_source_integrity_counts)
