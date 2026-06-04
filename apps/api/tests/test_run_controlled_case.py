"""
Unit tests for run_controlled_case.py

No network access, no live Claude calls, no real disk writes in most cases.
LLM/source-fetch steps are mocked/faked throughout.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import run_controlled_case as rcc
from run_controlled_case import (
    FAILED,
    NOT_READY,
    READY,
    RunResult,
    StageResult,
    _build_seed,
    _infer_jurisdiction,
    build_stage_plan,
    check_git_hygiene,
    stage_check_readiness,
    stage_extract,
    stage_fetch_source,
    stage_merge_drafts,
    stage_plan_coverage,
    stage_seed,
    stage_select_profile,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _args(**kwargs):
    """Build a minimal fake namespace for run()."""
    ns = MagicMock()
    ns.case_id = kwargs.get("case_id", "us_test_co_2025")
    ns.source_url = kwargs.get("source_url", "https://example.com/decision.pdf")
    ns.case_name = kwargs.get("case_name", "FTC v. Test Co")
    ns.jurisdiction = kwargs.get("jurisdiction", "US")
    ns.authority = kwargs.get("authority", "SDNY")
    ns.procedure_stage = kwargs.get("procedure_stage", "federal_district_court")
    ns.outcome = kwargs.get("outcome", "blocked")
    ns.authority_reference = kwargs.get("authority_reference", None)
    ns.decision_date = kwargs.get("decision_date", None)
    ns.sector = kwargs.get("sector", None)
    ns.parties = kwargs.get("parties", None)
    ns.profile = kwargs.get("profile", None)
    ns.focuses = kwargs.get("focuses", None)
    ns.max_cost = kwargs.get("max_cost", None)
    ns.dry_run = kwargs.get("dry_run", False)
    ns.overwrite_drafts = kwargs.get("overwrite_drafts", False)
    ns.skip_llm_review = kwargs.get("skip_llm_review", False)
    ns.promote = kwargs.get("promote", False)
    return ns


# ---------------------------------------------------------------------------
# _infer_jurisdiction
# ---------------------------------------------------------------------------

class TestInferJurisdiction:
    def test_us_prefix(self):
        assert _infer_jurisdiction("us_example_2025") == "us"

    def test_eu_prefix(self):
        assert _infer_jurisdiction("eu_viasat_2023") == "eu"

    def test_uk_prefix(self):
        assert _infer_jurisdiction("uk_meta_giphy_2022") == "uk"

    def test_unknown_falls_back(self):
        assert _infer_jurisdiction("other_case") == "eu"


# ---------------------------------------------------------------------------
# _build_seed
# ---------------------------------------------------------------------------

class TestBuildSeed:
    def test_required_fields_present(self):
        seed = _build_seed(
            case_id="us_test_2025",
            case_name="FTC v. Test",
            jurisdiction="US",
            authority="SDNY",
            authority_reference=None,
            procedure_stage="federal_district_court",
            outcome="blocked",
            decision_date="2025-01-15",
            sector=None,
            parties=[],
            source_url="https://example.com/d.pdf",
        )
        assert seed["case_id"] == "us_test_2025"
        assert seed["jurisdiction"] == "US"
        assert seed["outcome"] == "blocked"
        assert seed["procedure_stage"] == "federal_district_court"
        assert len(seed["source_documents"]) == 1
        assert seed["source_documents"][0]["pdf_url"] == "https://example.com/d.pdf"
        assert seed["source_documents"][0]["doc_id"] == "us_test_2025_decision"

    def test_parties_parsed_with_colon_role(self):
        seed = _build_seed(
            case_id="us_test_2025",
            case_name="FTC v. Test",
            jurisdiction="US",
            authority="SDNY",
            authority_reference=None,
            procedure_stage="phase_1",
            outcome="cleared",
            decision_date=None,
            sector=None,
            parties=["Acquirer Corp:acquirer", "Target Ltd:target"],
            source_url="https://example.com/d.pdf",
        )
        assert seed["parties"][0] == {"name": "Acquirer Corp", "role": "acquirer"}
        assert seed["parties"][1] == {"name": "Target Ltd", "role": "target"}

    def test_parties_default_roles(self):
        seed = _build_seed(
            case_id="us_test_2025",
            case_name="FTC v. Test",
            jurisdiction="US",
            authority="SDNY",
            authority_reference=None,
            procedure_stage="phase_1",
            outcome="cleared",
            decision_date=None,
            sector="tech",
            parties=["BigCo", "SmallCo"],
            source_url="https://example.com/d.pdf",
        )
        assert seed["parties"][0]["role"] == "acquirer"
        assert seed["parties"][1]["role"] == "target"
        assert seed["sector"] == "tech"

    def test_no_authority_reference_if_none(self):
        seed = _build_seed(
            case_id="us_test_2025",
            case_name="Test",
            jurisdiction="US",
            authority="SDNY",
            authority_reference=None,
            procedure_stage="phase_1",
            outcome="cleared",
            decision_date=None,
            sector=None,
            parties=[],
            source_url="https://example.com/d.pdf",
        )
        assert "authority_reference" not in seed


# ---------------------------------------------------------------------------
# stage_seed — dry-run
# ---------------------------------------------------------------------------

class TestStageSeed:
    def test_dry_run_does_not_write(self, tmp_path):
        out_path = tmp_path / "us" / "us_test_2025.yaml"
        with patch.object(rcc, "_CASES_DIR", tmp_path):
            result, path = stage_seed(
                "us_test_2025",
                {"case_id": "us_test_2025"},
                "US",
                dry_run=True,
                overwrite=False,
            )
        assert not out_path.exists()
        assert result.status == "ok"
        assert path is None

    def test_writes_yaml_when_not_dry_run(self, tmp_path):
        with patch.object(rcc, "_CASES_DIR", tmp_path):
            result, path = stage_seed(
                "us_test_2025",
                {"case_id": "us_test_2025", "case_name": "Test"},
                "US",
                dry_run=False,
                overwrite=False,
            )
        assert result.status == "ok"
        assert path is not None and path.exists()
        loaded = yaml.safe_load(path.read_text())
        assert loaded["case_id"] == "us_test_2025"

    def test_skips_existing_without_overwrite(self, tmp_path):
        jur_dir = tmp_path / "us"
        jur_dir.mkdir()
        existing = jur_dir / "us_test_2025.yaml"
        existing.write_text("case_id: us_test_2025\n")
        with patch.object(rcc, "_CASES_DIR", tmp_path):
            result, path = stage_seed(
                "us_test_2025",
                {"case_id": "us_test_2025"},
                "US",
                dry_run=False,
                overwrite=False,
            )
        assert result.status == "ok"
        assert "skipped" in result.message


# ---------------------------------------------------------------------------
# stage_fetch_source — dry-run
# ---------------------------------------------------------------------------

class TestStageFetchSource:
    def test_dry_run_does_not_fetch(self, tmp_path):
        with patch.object(rcc, "_SOURCE_TEXT_DIR", tmp_path):
            result, path = stage_fetch_source(
                "us_test_2025",
                "https://example.com/d.pdf",
                dry_run=True,
                overwrite=False,
            )
        assert result.status == "ok"
        assert path is None
        assert "[dry-run]" in result.message

    def test_skips_if_cache_exists(self, tmp_path):
        existing = tmp_path / "us_test_2025_decision.json"
        existing.write_text("{}")
        with patch.object(rcc, "_SOURCE_TEXT_DIR", tmp_path):
            result, path = stage_fetch_source(
                "us_test_2025",
                "https://example.com/d.pdf",
                dry_run=False,
                overwrite=False,
            )
        assert result.status == "ok"
        assert "skipped" in result.message
        assert path == existing

    def test_returns_error_on_fetch_failure(self, tmp_path):
        with patch.object(rcc, "_SOURCE_TEXT_DIR", tmp_path):
            with patch("run_controlled_case.fetch_and_extract", side_effect=Exception("timeout"), create=True):
                # We need to patch the import inside the function
                with patch("httpx.Client") as mock_client:
                    mock_client.return_value.__enter__ = lambda s: s
                    mock_client.return_value.__exit__ = MagicMock(return_value=False)
                    # Patch the inner import
                    import importlib
                    with patch.dict("sys.modules", {"app.utils.pdf_extractor": MagicMock(
                        fetch_and_extract=MagicMock(side_effect=Exception("network timeout")),
                        save_cache=MagicMock(),
                    )}):
                        result, path = stage_fetch_source(
                            "us_test_2025",
                            "https://example.com/d.pdf",
                            dry_run=False,
                            overwrite=True,
                        )
        assert result.status == "error"
        assert path is None


# ---------------------------------------------------------------------------
# stage_select_profile
# ---------------------------------------------------------------------------

class TestStageSelectProfile:
    def test_us_case_selects_us_court_opinion(self):
        result, profile = stage_select_profile("us_test_co_2025", None, None)
        assert result.status == "ok"
        assert profile is not None
        assert profile.profile_id == "us_court_opinion"

    def test_eu_case_selects_ec_decision(self):
        result, profile = stage_select_profile("eu_test_co_2023", None, None)
        assert result.status == "ok"
        assert profile is not None
        assert profile.profile_id == "ec_decision"

    def test_explicit_profile_override(self):
        result, profile = stage_select_profile("us_test_co_2025", "ec_decision", None)
        assert profile is not None
        assert profile.profile_id == "ec_decision"

    def test_unknown_profile_returns_error(self):
        result, profile = stage_select_profile("us_test_co_2025", "nonexistent_xyz", None)
        assert result.status == "error"
        assert profile is None

    def test_case_meta_used_for_inference(self):
        meta = {"jurisdiction": "uk", "authority": "CMA", "procedure_stage": "phase_2"}
        result, profile = stage_select_profile("uk_test_2023", None, meta)
        assert profile is not None
        assert profile.profile_id == "cma_report"


# ---------------------------------------------------------------------------
# build_stage_plan
# ---------------------------------------------------------------------------

class TestBuildStagePlan:
    def test_default_plan_includes_all_stages(self):
        plan = build_stage_plan(
            has_source_cache=False,
            has_existing_drafts=False,
            dry_run=False,
            skip_llm=False,
            focuses=["market_definition"],
        )
        assert "seed" in plan
        assert "fetch_source" in plan
        assert "select_profile" in plan
        assert "plan_coverage" in plan
        assert "extract" in plan
        assert "merge_drafts" in plan
        assert "check_readiness" in plan

    def test_skip_llm_removes_extract(self):
        plan = build_stage_plan(
            has_source_cache=True,
            has_existing_drafts=True,
            dry_run=False,
            skip_llm=True,
            focuses=["market_definition"],
        )
        assert "extract" not in plan

    def test_dry_run_plan_has_same_stages(self):
        plan = build_stage_plan(
            has_source_cache=False,
            has_existing_drafts=False,
            dry_run=True,
            skip_llm=False,
            focuses=["market_definition"],
        )
        assert "seed" in plan
        assert "fetch_source" in plan


# ---------------------------------------------------------------------------
# stage_plan_coverage — subprocess mock
# ---------------------------------------------------------------------------

class TestStagePlanCoverage:
    def test_success(self, tmp_path):
        mock_profile = MagicMock()
        mock_profile.profile_id = "us_court_opinion"
        completed = subprocess.CompletedProcess([], 0, stdout="ok", stderr="")
        with patch("run_controlled_case._run_subprocess", return_value=completed):
            result, plan_path = stage_plan_coverage("us_test_2025", mock_profile, dry_run=False)
        assert result.status == "ok"

    def test_failure_returns_error(self):
        mock_profile = MagicMock()
        mock_profile.profile_id = "us_court_opinion"
        completed = subprocess.CompletedProcess([], 1, stdout="", stderr="no cache found")
        with patch("run_controlled_case._run_subprocess", return_value=completed):
            result, plan_path = stage_plan_coverage("us_test_2025", mock_profile, dry_run=False)
        assert result.status == "error"
        assert plan_path is None

    def test_dry_run(self):
        mock_profile = MagicMock()
        mock_profile.profile_id = "us_court_opinion"
        completed = subprocess.CompletedProcess([], 0, stdout="plan output", stderr="")
        with patch("run_controlled_case._run_subprocess", return_value=completed):
            result, plan_path = stage_plan_coverage("us_test_2025", mock_profile, dry_run=True)
        assert result.status == "ok"
        assert plan_path is None


# ---------------------------------------------------------------------------
# stage_check_readiness — exit code mapping
# ---------------------------------------------------------------------------

class TestStageCheckReadiness:
    def test_exit_0_returns_ready(self, tmp_path):
        merged = tmp_path / "merged.yaml"
        merged.write_text("case_id: us_test_2025\n")
        completed = subprocess.CompletedProcess([], 0, stdout="PASS", stderr="")
        with patch("run_controlled_case._run_subprocess", return_value=completed):
            with patch.object(rcc, "_DRAFTS_DIR", tmp_path):
                result, packet, status = stage_check_readiness(
                    "us_test_2025",
                    merged,
                    [],
                    dry_run=False,
                )
        assert status == "READY"
        assert result.status == "ok"

    def test_exit_1_returns_warn(self, tmp_path):
        merged = tmp_path / "merged.yaml"
        merged.write_text("case_id: us_test_2025\n")
        completed = subprocess.CompletedProcess([], 1, stdout="WARN", stderr="")
        with patch("run_controlled_case._run_subprocess", return_value=completed):
            with patch.object(rcc, "_DRAFTS_DIR", tmp_path):
                result, packet, status = stage_check_readiness(
                    "us_test_2025",
                    merged,
                    [],
                    dry_run=False,
                )
        assert status == "WARN"
        assert result.status == "warn"

    def test_exit_2_returns_fail(self, tmp_path):
        merged = tmp_path / "merged.yaml"
        merged.write_text("case_id: us_test_2025\n")
        completed = subprocess.CompletedProcess([], 2, stdout="FAIL", stderr="")
        with patch("run_controlled_case._run_subprocess", return_value=completed):
            with patch.object(rcc, "_DRAFTS_DIR", tmp_path):
                result, packet, status = stage_check_readiness(
                    "us_test_2025",
                    merged,
                    [],
                    dry_run=False,
                )
        assert status == "FAIL"
        assert result.status == "error"

    def test_no_drafts_returns_skip(self, tmp_path):
        result, packet, status = stage_check_readiness(
            "us_test_2025", None, [], dry_run=False,
        )
        assert status == "SKIP"
        assert result.status == "skip"

    def test_dry_run_returns_skip(self, tmp_path):
        result, packet, status = stage_check_readiness(
            "us_test_2025",
            tmp_path / "merged.yaml",
            [],
            dry_run=True,
        )
        assert status == "SKIP"


# ---------------------------------------------------------------------------
# stage_merge_drafts
# ---------------------------------------------------------------------------

class TestStageMergeDrafts:
    def test_no_drafts_returns_skip(self, tmp_path):
        with patch.object(rcc, "_DRAFTS_DIR", tmp_path):
            result, path = stage_merge_drafts("us_test_2025", [], "US", dry_run=False)
        assert result.status == "skip"
        assert path is None

    def test_dry_run(self, tmp_path):
        drafts = [tmp_path / "a.draft.yaml", tmp_path / "b.draft.yaml"]
        with patch.object(rcc, "_DRAFTS_DIR", tmp_path):
            result, path = stage_merge_drafts("us_test_2025", drafts, "US", dry_run=True)
        assert result.status == "ok"
        assert path is None

    def test_success(self, tmp_path):
        drafts = [tmp_path / "a.draft.yaml"]
        completed = subprocess.CompletedProcess([], 0, stdout="merged", stderr="")
        with patch("run_controlled_case._run_subprocess", return_value=completed):
            with patch.object(rcc, "_DRAFTS_DIR", tmp_path):
                result, path = stage_merge_drafts("us_test_2025", drafts, "US", dry_run=False)
        assert result.status == "ok"

    def test_merge_failure_returns_error(self, tmp_path):
        drafts = [tmp_path / "a.draft.yaml"]
        completed = subprocess.CompletedProcess([], 1, stdout="", stderr="merge failed")
        with patch("run_controlled_case._run_subprocess", return_value=completed):
            with patch.object(rcc, "_DRAFTS_DIR", tmp_path):
                result, path = stage_merge_drafts("us_test_2025", drafts, "US", dry_run=False)
        assert result.status == "error"
        assert path is None


# ---------------------------------------------------------------------------
# Full orchestrator — mocked pipeline
# ---------------------------------------------------------------------------

def _make_subprocess_ok():
    return subprocess.CompletedProcess([], 0, stdout="ok", stderr="")


def _make_subprocess_fail():
    return subprocess.CompletedProcess([], 2, stdout="FAIL readiness errors", stderr="")


_OK_FETCH = (StageResult("fetch_source", "ok", "cached"), Path("/tmp/fake.json"))
_OK_SEED = (StageResult("seed", "ok", "written"), Path("/tmp/seed.yaml"))


class TestOrchestratorRun:
    """Integration-style tests using mocks for expensive stages."""

    def _patch_all_subprocesses(self, readiness_exit=0):
        """Patch _run_subprocess to return ok for most stages, and readiness_exit for check."""
        def fake_subprocess(cmd, **kwargs):
            if "check_review_readiness.py" in " ".join(cmd):
                return subprocess.CompletedProcess([], readiness_exit, stdout="readiness out", stderr="")
            return subprocess.CompletedProcess([], 0, stdout="ok", stderr="")

        return patch("run_controlled_case._run_subprocess", side_effect=fake_subprocess)

    def _patch_fetch_ok(self, tmp_path):
        cache = tmp_path / "source" / "us_test_co_2025_decision.json"
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text("{}")
        return patch("run_controlled_case.stage_fetch_source", return_value=_OK_FETCH)

    def test_dry_run_does_not_write_seed_or_drafts(self, tmp_path):
        args = _args(dry_run=True)
        with patch.object(rcc, "_CASES_DIR", tmp_path / "cases"):
            with patch.object(rcc, "_DRAFTS_DIR", tmp_path / "drafts"):
                with patch.object(rcc, "_SOURCE_TEXT_DIR", tmp_path / "source"):
                    with self._patch_all_subprocesses():
                        with patch("run_controlled_case.check_git_hygiene", return_value=[]):
                            with self._patch_fetch_ok(tmp_path):
                                result = rcc.run(args)
        # No files should be written in cases or drafts dirs
        assert not list((tmp_path / "cases").rglob("*.yaml")) if (tmp_path / "cases").exists() else True
        # Result should not be FAILED
        assert result.status != FAILED

    def test_profile_inferred_from_case_id(self, tmp_path):
        args = _args(case_id="eu_test_co_2024", jurisdiction="EU")
        with patch.object(rcc, "_CASES_DIR", tmp_path / "cases"):
            with patch.object(rcc, "_DRAFTS_DIR", tmp_path / "drafts"):
                with patch.object(rcc, "_SOURCE_TEXT_DIR", tmp_path / "source"):
                    with self._patch_all_subprocesses():
                        with patch("run_controlled_case.check_git_hygiene", return_value=[]):
                            with patch("run_controlled_case.stage_fetch_source", return_value=_OK_FETCH):
                                result = rcc.run(args)
        assert result.profile_id == "ec_decision"

    def test_explicit_profile_override(self, tmp_path):
        args = _args(profile="cma_report")
        with patch.object(rcc, "_CASES_DIR", tmp_path / "cases"):
            with patch.object(rcc, "_DRAFTS_DIR", tmp_path / "drafts"):
                with patch.object(rcc, "_SOURCE_TEXT_DIR", tmp_path / "source"):
                    with self._patch_all_subprocesses():
                        with patch("run_controlled_case.check_git_hygiene", return_value=[]):
                            with patch("run_controlled_case.stage_fetch_source", return_value=_OK_FETCH):
                                result = rcc.run(args)
        assert result.profile_id == "cma_report"

    def test_failed_readiness_returns_not_ready(self, tmp_path):
        args = _args(skip_llm_review=True)
        drafts_dir = tmp_path / "drafts" / "us"
        drafts_dir.mkdir(parents=True)
        fake_draft = drafts_dir / "us_test_co_2025.market_definition.v1.draft.yaml"
        fake_draft.write_text("case_id: us_test_co_2025\n")

        with patch.object(rcc, "_CASES_DIR", tmp_path / "cases"):
            with patch.object(rcc, "_DRAFTS_DIR", tmp_path / "drafts"):
                with patch.object(rcc, "_SOURCE_TEXT_DIR", tmp_path / "source"):
                    with self._patch_all_subprocesses(readiness_exit=2):
                        with patch("run_controlled_case.check_git_hygiene", return_value=[]):
                            with patch("run_controlled_case.stage_fetch_source", return_value=_OK_FETCH):
                                result = rcc.run(args)
        assert result.status == NOT_READY

    def test_clean_readiness_returns_ready(self, tmp_path):
        args = _args(skip_llm_review=True)
        drafts_dir = tmp_path / "drafts" / "us"
        drafts_dir.mkdir(parents=True)
        fake_draft = drafts_dir / "us_test_co_2025.market_definition.v1.draft.yaml"
        fake_draft.write_text("case_id: us_test_co_2025\n")

        with patch.object(rcc, "_CASES_DIR", tmp_path / "cases"):
            with patch.object(rcc, "_DRAFTS_DIR", tmp_path / "drafts"):
                with patch.object(rcc, "_SOURCE_TEXT_DIR", tmp_path / "source"):
                    with self._patch_all_subprocesses(readiness_exit=0):
                        with patch("run_controlled_case.check_git_hygiene", return_value=[]):
                            with patch("run_controlled_case.stage_fetch_source", return_value=_OK_FETCH):
                                result = rcc.run(args)
        assert result.status == READY

    def test_source_fetch_failure_returns_failed(self, tmp_path):
        args = _args()
        with patch.object(rcc, "_CASES_DIR", tmp_path / "cases"):
            with patch.object(rcc, "_DRAFTS_DIR", tmp_path / "drafts"):
                with patch.object(rcc, "_SOURCE_TEXT_DIR", tmp_path / "source"):
                    with patch("run_controlled_case.check_git_hygiene", return_value=[]):
                        with patch(
                            "run_controlled_case.stage_fetch_source",
                            return_value=(StageResult("fetch_source", "error", "network failure"), None),
                        ):
                            result = rcc.run(args)
        assert result.status == FAILED


# ---------------------------------------------------------------------------
# Run report — git hygiene section present
# ---------------------------------------------------------------------------

class TestRunReport:
    def test_report_includes_git_hygiene_section(self, tmp_path):
        result = RunResult(
            case_id="us_test_co_2025",
            status=READY,
            profile_id="us_court_opinion",
            stages=[StageResult("seed", "ok", "Seed written")],
            generated_files=[tmp_path / "seed.yaml"],
            blockers=[],
            git_warnings=["  data/drafts/us/us_test_co_2025.merged.draft.yaml  ← do not commit"],
        )
        out = tmp_path / "run_report.md"
        args = _args()
        rcc.write_run_report(result, args, out)
        text = out.read_text()
        assert "Git Hygiene" in text
        assert "do not commit" in text

    def test_report_includes_generated_files(self, tmp_path):
        gen_file = tmp_path / "data" / "drafts" / "us" / "us_test_co_2025.merged.draft.yaml"
        gen_file.parent.mkdir(parents=True)
        gen_file.touch()
        result = RunResult(
            case_id="us_test_co_2025",
            status=READY,
            profile_id="us_court_opinion",
            stages=[],
            generated_files=[gen_file],
            blockers=[],
            git_warnings=[],
        )
        out = tmp_path / "run_report.md"
        args = _args()
        rcc.write_run_report(result, args, out)
        text = out.read_text()
        assert "Generated Files" in text
        assert "merged.draft.yaml" in text

    def test_not_ready_report_has_blockers(self, tmp_path):
        result = RunResult(
            case_id="us_test_co_2025",
            status=NOT_READY,
            profile_id="us_court_opinion",
            stages=[StageResult("check_readiness", "error", "Readiness: FAIL")],
            generated_files=[],
            blockers=["Readiness check has errors — see review packet for details"],
            git_warnings=[],
        )
        out = tmp_path / "run_report.md"
        args = _args()
        rcc.write_run_report(result, args, out)
        text = out.read_text()
        assert "NOT READY" in text or "Blockers" in text


# ---------------------------------------------------------------------------
# check_git_hygiene — does not crash, returns list
# ---------------------------------------------------------------------------

class TestStageExtract:
    """stage_extract records stderr and stdout in failure details."""

    def test_failed_focus_records_stderr_in_details(self, tmp_path):
        failed = subprocess.CompletedProcess(
            [], 1,
            stdout="",
            stderr="ModuleNotFoundError: No module named 'app'",
        )
        with patch("run_controlled_case._run_subprocess", return_value=failed):
            with patch.object(rcc, "_DRAFTS_DIR", tmp_path):
                result, drafts = stage_extract(
                    "eu_test_co_2023",
                    ["market_definition"],
                    dry_run=False, skip_llm=False, max_cost=None,
                )
        assert result.status == "error"
        assert any("ModuleNotFoundError" in d for d in result.details)

    def test_failed_focus_falls_back_to_stdout_when_stderr_empty(self, tmp_path):
        """When stderr is blank, stdout is used instead so the error is actionable."""
        failed = subprocess.CompletedProcess(
            [], 1,
            stdout="Traceback (most recent call last): ...\nValueError: bad input",
            stderr="",
        )
        with patch("run_controlled_case._run_subprocess", return_value=failed):
            with patch.object(rcc, "_DRAFTS_DIR", tmp_path):
                result, drafts = stage_extract(
                    "eu_test_co_2023",
                    ["market_definition"],
                    dry_run=False, skip_llm=False, max_cost=None,
                )
        assert result.status == "error"
        assert any("ValueError" in d or "bad input" in d for d in result.details)

    def test_skip_llm_returns_skip(self, tmp_path):
        result, drafts = stage_extract(
            "eu_test_co_2023",
            ["market_definition"],
            dry_run=False, skip_llm=True, max_cost=None,
        )
        assert result.status == "skip"
        assert drafts == []

    def test_dry_run_returns_ok(self, tmp_path):
        result, drafts = stage_extract(
            "eu_test_co_2023",
            ["market_definition"],
            dry_run=True, skip_llm=False, max_cost=None,
        )
        assert result.status == "ok"
        assert drafts == []


class TestCheckGitHygiene:
    def test_returns_list(self):
        warnings = check_git_hygiene()
        assert isinstance(warnings, list)

    def test_generated_path_triggers_warning(self):
        fake_status = "?? data/drafts/us/us_test_co_2025.merged.draft.yaml\n"
        with patch(
            "subprocess.run",
            return_value=subprocess.CompletedProcess([], 0, stdout=fake_status, stderr=""),
        ):
            warnings = check_git_hygiene()
        assert any("do not commit" in w for w in warnings)

    def test_canonical_case_path_does_not_trigger(self):
        fake_status = "M data/cases/us/us_tapestry_capri_2024.yaml\n"
        with patch(
            "subprocess.run",
            return_value=subprocess.CompletedProcess([], 0, stdout=fake_status, stderr=""),
        ):
            warnings = check_git_hygiene()
        assert not warnings


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------

class TestCLIParsing:
    def test_required_args_parsed(self):
        args = rcc._parse_args([
            "--case-id", "us_test_2025",
            "--source-url", "https://example.com/d.pdf",
            "--case-name", "FTC v. Test",
            "--jurisdiction", "US",
            "--authority", "SDNY",
            "--procedure-stage", "federal_district_court",
            "--outcome", "blocked",
        ])
        assert args.case_id == "us_test_2025"
        assert args.outcome == "blocked"
        assert args.dry_run is False

    def test_dry_run_flag(self):
        args = rcc._parse_args([
            "--case-id", "us_test_2025",
            "--source-url", "https://example.com/d.pdf",
            "--case-name", "FTC v. Test",
            "--jurisdiction", "US",
            "--authority", "SDNY",
            "--procedure-stage", "federal_district_court",
            "--outcome", "blocked",
            "--dry-run",
        ])
        assert args.dry_run is True

    def test_focuses_parsed_as_list(self):
        args = rcc._parse_args([
            "--case-id", "us_test_2025",
            "--source-url", "https://example.com/d.pdf",
            "--case-name", "FTC v. Test",
            "--jurisdiction", "US",
            "--authority", "SDNY",
            "--procedure-stage", "federal_district_court",
            "--outcome", "blocked",
            "--focuses", "outcome_metadata", "market_definition",
        ])
        assert args.focuses == ["outcome_metadata", "market_definition"]

    def test_parties_repeatable(self):
        args = rcc._parse_args([
            "--case-id", "us_test_2025",
            "--source-url", "https://example.com/d.pdf",
            "--case-name", "FTC v. Test",
            "--jurisdiction", "US",
            "--authority", "SDNY",
            "--procedure-stage", "federal_district_court",
            "--outcome", "blocked",
            "--parties", "BigCo:acquirer",
            "--parties", "SmallCo:target",
        ])
        assert args.parties == ["BigCo:acquirer", "SmallCo:target"]

    def test_missing_required_arg_raises(self):
        with pytest.raises(SystemExit):
            rcc._parse_args([
                "--case-id", "us_test_2025",
                # missing --source-url, --case-name, etc.
            ])
