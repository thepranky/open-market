"""
Tests for the --dual-extract orchestration glue in ingest_case.py (ROADMAP 5.9).

These exercise stage_dual_extract without any live LLM calls: extract_case and the
secondary-client builder are monkeypatched. The comparison itself is covered by
test_compare_extractions.py; here we verify the orchestration wiring — secondary
provider selection, Draft B write, conflict-report emission, and graceful skip when
the secondary provider is unavailable.
"""

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import yaml

_API_DIR = Path(__file__).resolve().parents[1]
for _p in (str(_API_DIR), str(_API_DIR / "scripts" / "cases" / "extract"),
           str(_API_DIR / "scripts" / "cases" / "integrity")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_spec = importlib.util.spec_from_file_location(
    "ingest_case", str(_API_DIR / "scripts" / "cases" / "extract" / "ingest_case.py")
)
ingest_case = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ingest_case)


def _write_draft(path, status):
    path.write_text(yaml.dump({
        "case_id": "eu_test_2023",
        "outcome": "cleared",
        "product_markets_considered": [
            {"market_id": "pm_1", "name": "Cement", "definition_status": status},
        ],
        "geographic_markets_considered": [],
        "theories_of_harm": [],
        "source_passages": [],
    }), encoding="utf-8")


def test_dual_extract_writes_conflict_report(tmp_path, monkeypatch):
    draft_a = tmp_path / "eu_test_2023.market_definition.draft_a.yaml"
    draft_b = tmp_path / "eu_test_2023.market_definition.draft_b.yaml"
    conflicts = tmp_path / "eu_test_2023.market_definition.conflicts.yaml"
    _write_draft(draft_a, "defined")

    # Secondary client is "available"; extract_case writes a divergent Draft B.
    monkeypatch.setattr(ingest_case, "_build_llm_client", lambda provider: object())

    def fake_extract_case(yaml_path, *, output_path, **kwargs):
        _write_draft(output_path, "discussed")  # disagree with Draft A
        return SimpleNamespace(error=None)

    monkeypatch.setattr(ingest_case, "extract_case", fake_extract_case)

    result = ingest_case.stage_dual_extract(
        yaml_path=tmp_path / "canonical.yaml",
        cache_dir=tmp_path,
        draft_b_path=draft_b,
        conflicts_path=conflicts,
        case_id="eu_test_2023",
        focus="market_definition",
        primary_provider="anthropic",
        same_model=False,
        max_cost=2.0,
        batch_by_section=False,
        full_market_def_pass=False,
        page_range=None,
    )

    assert result == conflicts
    assert draft_b.exists()
    report = yaml.safe_load(conflicts.read_text())["conflict_report"]
    # Heterogeneous by default: B uses gemini when A uses anthropic.
    assert report["models"]["draft_a"].startswith("anthropic/")
    assert report["models"]["draft_b"].startswith("gemini/")
    assert report["models"]["same_model"] is False
    # The defined/discussed divergence is surfaced as a conflict.
    kinds = [c["kind"] for c in report["conflicts"]]
    assert "value_mismatch" in kinds


def test_dual_same_model_uses_primary_provider(tmp_path, monkeypatch):
    draft_a = tmp_path / "eu_test_2023.market_definition.draft_a.yaml"
    draft_b = tmp_path / "eu_test_2023.market_definition.draft_b.yaml"
    conflicts = tmp_path / "eu_test_2023.market_definition.conflicts.yaml"
    _write_draft(draft_a, "defined")

    seen_providers = []
    monkeypatch.setattr(
        ingest_case, "_build_llm_client",
        lambda provider: seen_providers.append(provider) or object(),
    )
    monkeypatch.setattr(
        ingest_case, "extract_case",
        lambda yaml_path, *, output_path, **kw: (_write_draft(output_path, "defined")
                                                 or SimpleNamespace(error=None)),
    )

    ingest_case.stage_dual_extract(
        yaml_path=tmp_path / "canonical.yaml", cache_dir=tmp_path,
        draft_b_path=draft_b, conflicts_path=conflicts,
        case_id="eu_test_2023", focus="market_definition",
        primary_provider="anthropic", same_model=True,
        max_cost=2.0, batch_by_section=False, full_market_def_pass=False, page_range=None,
    )
    assert seen_providers == ["anthropic"]  # same model, not gemini
    report = yaml.safe_load(conflicts.read_text())["conflict_report"]
    assert report["models"]["same_model"] is True


def test_dual_extract_skips_when_secondary_unavailable(tmp_path, monkeypatch):
    draft_a = tmp_path / "eu_test_2023.market_definition.draft_a.yaml"
    conflicts = tmp_path / "eu_test_2023.market_definition.conflicts.yaml"
    _write_draft(draft_a, "defined")

    monkeypatch.setattr(ingest_case, "_build_llm_client", lambda provider: None)

    result = ingest_case.stage_dual_extract(
        yaml_path=tmp_path / "canonical.yaml", cache_dir=tmp_path,
        draft_b_path=tmp_path / "eu_test_2023.market_definition.draft_b.yaml",
        conflicts_path=conflicts,
        case_id="eu_test_2023", focus="market_definition",
        primary_provider="anthropic", same_model=False,
        max_cost=2.0, batch_by_section=False, full_market_def_pass=False, page_range=None,
    )
    assert result is None
    assert not conflicts.exists()  # no report when Draft B could not be produced


def test_dual_extract_skips_when_draft_b_errors(tmp_path, monkeypatch):
    draft_a = tmp_path / "eu_test_2023.market_definition.draft_a.yaml"
    conflicts = tmp_path / "eu_test_2023.market_definition.conflicts.yaml"
    _write_draft(draft_a, "defined")

    monkeypatch.setattr(ingest_case, "_build_llm_client", lambda provider: object())
    monkeypatch.setattr(
        ingest_case, "extract_case",
        lambda yaml_path, *, output_path, **kw: SimpleNamespace(error="boom"),
    )

    result = ingest_case.stage_dual_extract(
        yaml_path=tmp_path / "canonical.yaml", cache_dir=tmp_path,
        draft_b_path=tmp_path / "eu_test_2023.market_definition.draft_b.yaml",
        conflicts_path=conflicts,
        case_id="eu_test_2023", focus="market_definition",
        primary_provider="anthropic", same_model=False,
        max_cost=2.0, batch_by_section=False, full_market_def_pass=False, page_range=None,
    )
    assert result is None
    assert not conflicts.exists()
