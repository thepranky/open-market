"""Tests for run_bulk_promotion.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.cases.promote.promotion_gate import GateResult, PromotionOutcome
from scripts.cases.promote.run_bulk_promotion import (
    discover_candidates,
    main,
    parse_full_depth_readiness,
    review_status,
)


def _write_market_draft(root: Path, case_id: str, status: str = "PASS", markets: int = 1) -> Path:
    draft = root / "eu" / f"{case_id}.market_definition.draft.yaml"
    draft.parent.mkdir(parents=True, exist_ok=True)
    market_lines = "\n".join(f"  - market_id: m{i}" for i in range(markets))
    draft.write_text(f"case_id: {case_id}\nproduct_markets_considered:\n{market_lines}\n", encoding="utf-8")
    (draft.parent / f"{case_id}.market_definition.review.md").write_text(
        f"**Status: {status}**\n",
        encoding="utf-8",
    )
    return draft


def _write_full_depth_draft(root: Path, case_id: str, readiness: str = "PASS") -> Path:
    draft = root / "eu" / f"{case_id}.e2e.merged.draft.yaml"
    draft.parent.mkdir(parents=True, exist_ok=True)
    draft.write_text(
        f"case_id: {case_id}\nproduct_markets_considered:\n  - market_id: m1\n",
        encoding="utf-8",
    )
    (draft.parent / f"{case_id}.e2e.review_packet.md").write_text(
        f"## Readiness: {readiness}\n",
        encoding="utf-8",
    )
    return draft


def _outcome(candidate, status: str = "promoted") -> PromotionOutcome:
    return PromotionOutcome(
        case_id=candidate.case_id,
        status=status,
        draft_path=candidate.draft_path,
        draft_kind=candidate.draft_kind,
        review_status=candidate.review_status,
        output_path=candidate.output_path,
        timestamp="2026-06-29 19:00 UTC",
        message="promoted after grounding gates" if status == "promoted" else status,
        gates={
            "source_integrity": GateResult(
                "pass" if status == "promoted" else "blocked_source_integrity",
                errors=0,
                warnings=0 if status == "promoted" else 1,
            )
        },
    )


def test_review_status_parses_market_definition_review(tmp_path):
    review = tmp_path / "review.md"
    review.write_text("**Status: WARNINGS**\n", encoding="utf-8")
    assert review_status(review) == "WARNINGS"


def test_parse_full_depth_readiness(tmp_path):
    packet = tmp_path / "review_packet.md"
    packet.write_text("## Readiness: WARN\n", encoding="utf-8")
    assert parse_full_depth_readiness(packet) == "WARN"


def test_discover_market_definition_candidates(tmp_path):
    drafts = tmp_path / "drafts"
    cases = tmp_path / "cases"
    _write_market_draft(drafts, "eu_market_2020")

    candidates = discover_candidates(drafts, "eu", "market-definition", cases_dir=cases)

    assert [c.case_id for c in candidates] == ["eu_market_2020"]
    assert candidates[0].draft_kind == "market-definition"
    assert candidates[0].review_status == "PASS"


def test_discover_full_depth_candidates(tmp_path):
    drafts = tmp_path / "drafts"
    cases = tmp_path / "cases"
    _write_full_depth_draft(drafts, "eu_full_2020", readiness="WARN")

    candidates = discover_candidates(drafts, "eu", "full-depth", cases_dir=cases)

    assert [c.case_id for c in candidates] == ["eu_full_2020"]
    assert candidates[0].draft_kind == "full-depth"
    assert candidates[0].review_status == "WARN"


def test_all_prefers_full_depth_over_market_definition(tmp_path):
    drafts = tmp_path / "drafts"
    cases = tmp_path / "cases"
    _write_market_draft(drafts, "eu_same_2020")
    _write_full_depth_draft(drafts, "eu_same_2020")

    candidates = discover_candidates(drafts, "eu", "all", cases_dir=cases)

    assert len(candidates) == 1
    assert candidates[0].draft_kind == "full-depth"
    assert candidates[0].draft_path.name.endswith(".e2e.merged.draft.yaml")


def test_dry_run_does_not_call_gates_or_write_artifact(tmp_path):
    drafts = tmp_path / "drafts"
    cases = tmp_path / "cases"
    runs = tmp_path / "runs"
    _write_full_depth_draft(drafts, "eu_full_2020")
    gate = MagicMock()

    with patch("scripts.cases.promote.run_bulk_promotion.run_promotion_gate", gate):
        rc = main([
            "--drafts-dir", str(drafts),
            "--cases-dir", str(cases),
            "--batch-runs-dir", str(runs),
            "--jurisdiction", "eu",
            "--draft-kind", "full-depth",
            "--dry-run",
        ])

    assert rc == 0
    gate.assert_not_called()
    assert not runs.exists()


def test_blocked_gate_writes_artifact_and_returns_nonzero(tmp_path):
    drafts = tmp_path / "drafts"
    cases = tmp_path / "cases"
    runs = tmp_path / "runs"
    _write_full_depth_draft(drafts, "eu_full_2020")

    def gate_side_effect(candidate, **kwargs):
        return _outcome(candidate, "blocked_source_integrity")

    with patch("scripts.cases.promote.run_bulk_promotion.run_promotion_gate", side_effect=gate_side_effect):
        rc = main([
            "--drafts-dir", str(drafts),
            "--cases-dir", str(cases),
            "--batch-runs-dir", str(runs),
            "--run-id", "test_run",
            "--jurisdiction", "eu",
            "--draft-kind", "full-depth",
            "--skip-graph-seed",
        ])

    assert rc == 1
    artifact = json.loads((runs / "test_run.json").read_text(encoding="utf-8"))
    assert artifact["cases"]["eu_full_2020"]["status"] == "blocked_source_integrity"


def test_graph_seed_runs_once_after_multiple_promotions(tmp_path):
    drafts = tmp_path / "drafts"
    cases = tmp_path / "cases"
    runs = tmp_path / "runs"
    _write_full_depth_draft(drafts, "eu_one_2020")
    _write_full_depth_draft(drafts, "eu_two_2020")

    def gate_side_effect(candidate, **kwargs):
        return _outcome(candidate, "promoted")

    graph_seed = MagicMock(return_value=GateResult("pass"))
    with (
        patch("scripts.cases.promote.run_bulk_promotion.run_promotion_gate", side_effect=gate_side_effect),
        patch("scripts.cases.promote.run_bulk_promotion.run_graph_seed", graph_seed),
    ):
        rc = main([
            "--drafts-dir", str(drafts),
            "--cases-dir", str(cases),
            "--batch-runs-dir", str(runs),
            "--run-id", "test_run",
            "--jurisdiction", "eu",
            "--draft-kind", "full-depth",
        ])

    assert rc == 0
    graph_seed.assert_called_once()
    artifact = json.loads((runs / "test_run.json").read_text(encoding="utf-8"))
    assert set(artifact["cases"]) == {"eu_one_2020", "eu_two_2020"}
    assert artifact["graph_seed"]["status"] == "pass"
