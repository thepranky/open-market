import subprocess
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.cases.extract import run_e2e_extraction as e2e


def test_script_executes_directly_with_help():
    script = Path(__file__).resolve().parents[1] / "scripts" / "cases" / "extract" / "run_e2e_extraction.py"

    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "Run full-depth per-focus extraction" in result.stdout


def _minimal_draft(case_id: str, status: str = "defined") -> dict:
    return {
        "case_id": case_id,
        "case_name": "Test Case",
        "authority": "European Commission",
        "jurisdiction": "EU",
        "sector": "test",
        "outcome": "cleared",
        "decision_date": "2025-01-01",
        "parties": [],
        "source_documents": [{"doc_id": f"{case_id}_decision", "pdf_url": "https://example.com/d.pdf"}],
        "product_markets_considered": [
            {"market_id": "pm_1", "name": "Widgets", "definition_status": status}
        ],
        "geographic_markets_considered": [],
        "theories_of_harm": [],
        "commitments": [],
        "source_passages": [],
    }


def test_artifact_paths_keep_focus_token(tmp_path, monkeypatch):
    monkeypatch.setattr(e2e, "_DRAFTS_DIR", tmp_path)

    paths = e2e._artifact_paths("eu_test_2025", "eu", "market_definition")

    assert paths["draft_a"] == tmp_path / "eu" / "eu_test_2025.market_definition.draft_a.yaml"
    assert paths["conflicts"] == tmp_path / "eu" / "eu_test_2025.market_definition.conflicts.yaml"


def test_build_ingest_cmd_dual_and_outcome_defaults(tmp_path):
    args = e2e.argparse.Namespace(
        case_id="eu_test_2025",
        provider="anthropic",
        max_cost=2.0,
        cache_dir=tmp_path / "cache",
        from_index=True,
        pdf_url="https://example.com/d.pdf",
        dual_same_model=True,
        batch_by_section=True,
        page_range=None,
    )

    dual_cmd = e2e._build_ingest_cmd(args, "market_definition")
    outcome_cmd = e2e._build_ingest_cmd(args, "outcome_metadata")

    assert "--dual-extract" in dual_cmd
    assert "--dual-same-model" in dual_cmd
    assert "--from-index" in dual_cmd
    assert "--pdf-url" in dual_cmd
    assert "--dual-extract" not in outcome_cmd
    assert outcome_cmd[-2:] == ["--page-range", "1:30"]


def test_main_runs_focuses_merges_and_writes_state(tmp_path, monkeypatch):
    monkeypatch.setattr(e2e, "_DRAFTS_DIR", tmp_path / "drafts")

    def fake_run_focus(args, focus):
        paths = e2e._artifact_paths(args.case_id, "eu", focus)
        paths["draft_a"].parent.mkdir(parents=True, exist_ok=True)
        paths["draft_a"].write_text(yaml.safe_dump(_minimal_draft(args.case_id)), encoding="utf-8")
        paths["draft_b"].write_text(yaml.safe_dump(_minimal_draft(args.case_id, "left_open")), encoding="utf-8")
        paths["conflicts"].write_text("conflict_report:\n  conflicts: []\n", encoding="utf-8")
        return subprocess.CompletedProcess(args=["ingest"], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(e2e, "_run_focus", fake_run_focus)
    monkeypatch.setattr(
        e2e,
        "_run_readiness",
        lambda case_id, jurisdiction, profile, merged_path, draft_paths: ("PASS", [], tmp_path / "packet.md"),
    )

    rc = e2e.main([
        "--case-id",
        "eu_test_2025",
        "--focuses",
        "market_definition,theories",
        "--cache-dir",
        str(tmp_path / "cache"),
    ])

    assert rc == 0
    state = yaml.safe_load((tmp_path / "drafts" / "eu" / "eu_test_2025.e2e_state.yaml").read_text())
    assert state["focuses"] == {"market_definition": "completed", "theories": "completed"}
    assert state["readiness_status"] == "PASS"
    assert (tmp_path / "drafts" / "eu" / "eu_test_2025.e2e.merged.draft.yaml").exists()
    assert (tmp_path / "drafts" / "eu" / "eu_test_2025.e2e.summary.md").exists()


def test_resume_skips_completed_focus(tmp_path, monkeypatch):
    monkeypatch.setattr(e2e, "_DRAFTS_DIR", tmp_path / "drafts")
    state_path = tmp_path / "drafts" / "eu" / "eu_test_2025.e2e_state.yaml"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        yaml.safe_dump({
            "case_id": "eu_test_2025",
            "started_at": "2026-06-27T10:00:00+00:00",
            "focuses": {"market_definition": "completed", "theories": "pending"},
            "focus_errors": {},
        }),
        encoding="utf-8",
    )
    completed = e2e._artifact_paths("eu_test_2025", "eu", "market_definition")["draft_a"]
    completed.write_text(yaml.safe_dump(_minimal_draft("eu_test_2025")), encoding="utf-8")
    seen = []

    def fake_run_focus(args, focus):
        seen.append(focus)
        path = e2e._artifact_paths(args.case_id, "eu", focus)["draft_a"]
        path.write_text(yaml.safe_dump(_minimal_draft(args.case_id)), encoding="utf-8")
        return subprocess.CompletedProcess(args=["ingest"], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(e2e, "_run_focus", fake_run_focus)
    monkeypatch.setattr(
        e2e,
        "_run_readiness",
        lambda case_id, jurisdiction, profile, merged_path, draft_paths: ("PASS", [], tmp_path / "packet.md"),
    )

    rc = e2e.main([
        "--case-id",
        "eu_test_2025",
        "--focuses",
        "market_definition,theories",
        "--resume",
    ])

    assert rc == 0
    assert seen == ["theories"]
