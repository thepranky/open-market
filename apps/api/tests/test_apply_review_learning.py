"""
Tests for apps/api/scripts/cases/review/apply_review_learning.py.

Covers: loading review logs, grouping patterns, priority classification,
proposal action mapping, proposal generation, markdown rendering,
and output file writing.
No network access; no LLM calls; isolated filesystem via tmp_path.
"""

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from apply_review_learning import (
    Pattern,
    Occurrence,
    generate_proposals,
    group_patterns,
    load_review_logs,
    render_markdown,
    write_proposals,
)


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _correction(
    correction_type: str,
    reusable_rule: str = "Some reusable rule.",
    suggested_follow_up: str = "prompt_update",
    object_type: str = "product_market",
    object_id: str = "pm_1",
    before: object = {"definition_status": "defined"},
    after: object = {"definition_status": "considered"},
    confidence: str = "high",
) -> dict:
    return {
        "correction_type": correction_type,
        "object_type": object_type,
        "object_id": object_id,
        "before": before,
        "after": after,
        "inferred_reason": "Test reason.",
        "reusable_rule_candidate": reusable_rule,
        "suggested_follow_up": suggested_follow_up,
        "confidence": confidence,
    }


def _review_log(
    case_id: str = "eu_test_2024",
    focus: str = "market_definition",
    corrections: list = None,
    llm_triage_status: str = None,
    llm_triage_rationale: str = None,
) -> dict:
    log: dict = {
        "schema_version": "1",
        "case_id": case_id,
        "focus": focus,
        "generated_at": "2026-05-31T10:00:00Z",
        "source_files": {"draft": "drafts/eu/test.yaml", "canonical": "cases/eu/test.yaml"},
        "summary": {
            "total_corrections": len(corrections or []),
            "by_type": {},
            "llm_triage_status": llm_triage_status or "auto_verified_candidate",
        },
        "corrections": corrections or [],
    }
    if llm_triage_rationale:
        log["llm_review_insights"] = {
            "triage_status": llm_triage_status or "needs_legal_review",
            "triage_rationale": llm_triage_rationale,
        }
    return log


def _write_log(tmp_dir: Path, log: dict, name: str = None) -> Path:
    if name is None:
        name = f"{log['case_id']}.{log['focus']}.review_delta.yaml"
    path = tmp_dir / name
    path.write_text(yaml.dump(log))
    return path


# ---------------------------------------------------------------------------
# load_review_logs
# ---------------------------------------------------------------------------


def test_load_review_logs_reads_all_delta_files(tmp_path):
    log1 = _review_log("eu_case_a_2024")
    log2 = _review_log("eu_case_b_2024")
    _write_log(tmp_path, log1)
    _write_log(tmp_path, log2)

    loaded = load_review_logs(tmp_path)
    assert len(loaded) == 2
    case_ids = {entry["case_id"] for entry in loaded}
    assert case_ids == {"eu_case_a_2024", "eu_case_b_2024"}


def test_load_review_logs_empty_directory(tmp_path):
    assert load_review_logs(tmp_path) == []


def test_load_review_logs_ignores_non_delta_files(tmp_path):
    _write_log(tmp_path, _review_log("eu_case_a_2024"))
    (tmp_path / "some_other_file.yaml").write_text("foo: bar")
    (tmp_path / "proposals").mkdir()
    (tmp_path / "proposals" / "proposals.yaml").write_text("foo: bar")

    loaded = load_review_logs(tmp_path)
    assert len(loaded) == 1
    assert loaded[0]["case_id"] == "eu_case_a_2024"


# ---------------------------------------------------------------------------
# group_patterns
# ---------------------------------------------------------------------------


def test_group_patterns_groups_same_type_and_rule():
    logs = [
        _review_log(corrections=[
            _correction("definition_status_mapping", "Rule A"),
            _correction("definition_status_mapping", "Rule A", object_id="pm_2"),
        ])
    ]
    patterns = group_patterns(logs)
    ds = [p for p in patterns if p.correction_type == "definition_status_mapping"]
    assert len(ds) == 1
    assert ds[0].count == 2


def test_group_patterns_separates_different_rules():
    logs = [
        _review_log(corrections=[
            _correction("definition_status_mapping", "Rule A"),
            _correction("definition_status_mapping", "Rule B", object_id="pm_2"),
        ])
    ]
    patterns = group_patterns(logs)
    ds = [p for p in patterns if p.correction_type == "definition_status_mapping"]
    assert len(ds) == 2


def test_group_patterns_aggregates_across_cases():
    log1 = _review_log("eu_case_a_2024", corrections=[
        _correction("definition_status_mapping", "Working assumption rule.")
    ])
    log2 = _review_log("eu_case_b_2024", corrections=[
        _correction("definition_status_mapping", "Working assumption rule.")
    ])
    patterns = group_patterns([log1, log2])
    ds = [p for p in patterns if p.correction_type == "definition_status_mapping"]
    assert len(ds) == 1
    assert ds[0].count == 2
    assert set(ds[0].case_ids) == {"eu_case_a_2024", "eu_case_b_2024"}


def test_group_patterns_sorts_high_priority_first():
    logs = [_review_log(corrections=[
        _correction("note_cleanup", "Note cleanup rule.", suggested_follow_up="prompt_update"),
        _correction("definition_status_mapping", "DS rule.", suggested_follow_up="prompt_update"),
        _correction("metadata_completion", "Meta rule.", suggested_follow_up="docs_update"),
    ])]
    patterns = group_patterns(logs)
    assert patterns[0].correction_type == "definition_status_mapping"
    assert patterns[-1].correction_type in {"note_cleanup", "metadata_completion"}


def test_group_patterns_empty_logs():
    assert group_patterns([]) == []


def test_group_patterns_empty_corrections():
    logs = [_review_log(corrections=[])]
    assert group_patterns(logs) == []


# ---------------------------------------------------------------------------
# Pattern priority classification
# ---------------------------------------------------------------------------


def test_priority_always_high_for_outcome_passage_misuse():
    p = Pattern("outcome_passage_misuse", "Rule", "validator_rule")
    p.occurrences.append(Occurrence("eu_test", "source_passage", "sp_1", None, None, "high"))
    assert p.priority == "high"


def test_priority_always_high_for_definition_status_mapping():
    p = Pattern("definition_status_mapping", "Rule", "prompt_update")
    p.occurrences.append(Occurrence("eu_test", "product_market", "pm_1", None, None, "high"))
    assert p.priority == "high"


def test_priority_always_high_for_missing_market_added():
    p = Pattern("missing_market_added", "Rule", "eval_fixture")
    p.occurrences.append(Occurrence("eu_test", "product_market", "pm_new", None, None, "high"))
    assert p.priority == "high"


def test_priority_support_linkage_medium_below_threshold():
    p = Pattern("support_linkage_correction", "Review linkage rules.", "prompt_update")
    p.occurrences.append(Occurrence("eu_test", "source_passage", "sp_1", None, None, "medium"))
    assert p.priority == "medium"


def test_priority_support_linkage_high_at_threshold():
    p = Pattern("support_linkage_correction", "Review linkage rules.", "prompt_update")
    for i in range(2):
        p.occurrences.append(Occurrence("eu_test", "source_passage", f"sp_{i}", None, None, "medium"))
    assert p.priority == "high"


def test_priority_metadata_completion_low_below_threshold():
    p = Pattern("metadata_completion", "Meta rule.", "docs_update")
    for i in range(2):
        p.occurrences.append(Occurrence("eu_test", "case", "eu_test", None, None, "high"))
    assert p.priority == "low"


def test_priority_metadata_completion_medium_at_threshold():
    p = Pattern("metadata_completion", "Meta rule.", "docs_update")
    for i in range(3):
        p.occurrences.append(Occurrence("eu_test", "case", "eu_test", None, None, "high"))
    assert p.priority == "medium"


def test_priority_note_cleanup_low():
    p = Pattern("note_cleanup", "Avoid draft language.", "prompt_update")
    p.occurrences.append(Occurrence("eu_test", "product_market", "pm_1", None, None, "low"))
    assert p.priority == "low"


# ---------------------------------------------------------------------------
# Proposal action mapping
# ---------------------------------------------------------------------------


def test_proposal_action_validator_rule():
    p = Pattern("outcome_passage_misuse", "Rule", "validator_rule")
    assert p.proposal_action == "validator_rule_candidate"


def test_proposal_action_prompt_update():
    p = Pattern("definition_status_mapping", "Rule", "prompt_update")
    assert p.proposal_action == "extraction_prompt_update"


def test_proposal_action_eval_fixture():
    p = Pattern("missing_market_added", "Rule", "eval_fixture")
    assert p.proposal_action == "eval_fixture_candidate"


def test_proposal_action_docs_update():
    p = Pattern("metadata_completion", "Rule", "docs_update")
    assert p.proposal_action == "docs_update"


def test_proposal_action_unknown_follow_up_gives_no_action():
    p = Pattern("other", "Rule", "unknown_action")
    assert p.proposal_action == "no_action"


# ---------------------------------------------------------------------------
# generate_proposals
# ---------------------------------------------------------------------------


def test_generate_proposals_structure():
    logs = [_review_log(corrections=[
        _correction("definition_status_mapping", "Working assumption rule.")
    ])]
    patterns = group_patterns(logs)
    proposals = generate_proposals(patterns, logs)

    assert proposals["schema_version"] == "1"
    assert "generated_at" in proposals
    assert "eu_test_2024" in proposals["cases_reviewed"]
    assert proposals["total_corrections"] == 1
    assert proposals["total_patterns"] == 1
    assert len(proposals["proposals"]) == 1
    p = proposals["proposals"][0]
    assert p["correction_type"] == "definition_status_mapping"
    assert p["priority"] == "high"
    assert p["proposal_action"] == "extraction_prompt_update"
    assert p["count"] == 1
    assert len(p["evidence"]) == 1


def test_generate_proposals_includes_llm_insights():
    logs = [_review_log(
        corrections=[],
        llm_triage_rationale="Working assumption language found throughout.",
        llm_triage_status="needs_legal_review",
    )]
    patterns = group_patterns(logs)
    proposals = generate_proposals(patterns, logs)
    assert len(proposals["llm_review_insights"]) == 1
    ins = proposals["llm_review_insights"][0]
    assert ins["case_id"] == "eu_test_2024"
    assert "Working assumption" in ins["triage_rationale"]


def test_generate_proposals_omits_llm_insights_when_absent():
    logs = [_review_log(corrections=[])]
    proposals = generate_proposals(group_patterns(logs), logs)
    assert proposals["llm_review_insights"] == []


def test_generate_proposals_multiple_cases_total_corrections():
    log1 = _review_log("eu_a_2024", corrections=[
        _correction("definition_status_mapping", "Rule A"),
    ])
    log2 = _review_log("eu_b_2024", corrections=[
        _correction("note_cleanup", "Note rule.", suggested_follow_up="prompt_update"),
        _correction("metadata_completion", "Meta rule.", suggested_follow_up="docs_update"),
    ])
    patterns = group_patterns([log1, log2])
    proposals = generate_proposals(patterns, [log1, log2])
    assert proposals["total_corrections"] == 3
    assert set(proposals["cases_reviewed"]) == {"eu_a_2024", "eu_b_2024"}


# ---------------------------------------------------------------------------
# render_markdown
# ---------------------------------------------------------------------------


def test_render_markdown_has_required_sections():
    logs = [_review_log(corrections=[
        _correction("definition_status_mapping", "Working assumption rule.")
    ])]
    proposals = generate_proposals(group_patterns(logs), logs)
    md = render_markdown(proposals)

    assert "## Summary" in md
    assert "## High-Priority Proposed Pipeline Changes" in md
    assert "## Eval Fixture Candidates" in md
    assert "## LLM Review Insights" in md
    assert "## Low-Priority / No-Action Items" in md
    assert "## Human Approval Checklist" in md


def test_render_markdown_no_high_priority_shows_note():
    logs = [_review_log(corrections=[
        _correction("note_cleanup", "Avoid draft language.", suggested_follow_up="prompt_update"),
    ])]
    proposals = generate_proposals(group_patterns(logs), logs)
    md = render_markdown(proposals)

    assert "No high-priority pipeline changes" in md


def test_render_markdown_high_priority_correction_shown():
    logs = [_review_log(corrections=[
        _correction("definition_status_mapping", "Working assumption rule.")
    ])]
    proposals = generate_proposals(group_patterns(logs), logs)
    md = render_markdown(proposals)

    assert "definition_status_mapping" in md
    assert "extraction_prompt_update" in md
    assert "Working assumption rule." in md


def test_render_markdown_llm_insights_present():
    logs = [_review_log(
        corrections=[],
        llm_triage_rationale="Considered vs defined issue throughout.",
        llm_triage_status="needs_legal_review",
    )]
    proposals = generate_proposals(group_patterns(logs), logs)
    md = render_markdown(proposals)

    assert "Considered vs defined issue throughout." in md
    assert "review_prompt_update" in md


def test_render_markdown_eval_fixture_no_candidates_message():
    logs = [_review_log(corrections=[
        _correction("note_cleanup", "Note rule.", suggested_follow_up="prompt_update"),
    ])]
    proposals = generate_proposals(group_patterns(logs), logs)
    md = render_markdown(proposals)

    assert "No eval fixture candidates" in md


def test_render_markdown_checklist_has_docs_update():
    logs = [_review_log(corrections=[
        _correction("metadata_completion", "Meta rule.", suggested_follow_up="docs_update",
                    object_type="case", object_id="eu_test"),
    ])]
    proposals = generate_proposals(group_patterns(logs), logs)
    md = render_markdown(proposals)

    assert "docs / promotion checklist" in md.lower() or "docs_update" in md


def test_render_markdown_substantive_corrections_before_metadata():
    """High-priority corrections must appear before low-priority items in the markdown."""
    logs = [_review_log(corrections=[
        _correction("note_cleanup", "Note rule.", suggested_follow_up="prompt_update"),
        _correction("definition_status_mapping", "DS rule.", suggested_follow_up="prompt_update"),
    ])]
    proposals = generate_proposals(group_patterns(logs), logs)
    md = render_markdown(proposals)

    high_section_pos = md.index("## High-Priority Proposed Pipeline Changes")
    low_section_pos = md.index("## Low-Priority / No-Action Items")
    ds_pos = md.index("definition_status_mapping")
    note_pos = md.index("note_cleanup")

    assert ds_pos > high_section_pos
    assert note_pos > low_section_pos


# ---------------------------------------------------------------------------
# write_proposals — file output
# ---------------------------------------------------------------------------


def test_write_proposals_creates_both_files(tmp_path):
    proposals_dir = tmp_path / "proposals"
    logs = [_review_log(corrections=[
        _correction("definition_status_mapping", "Working assumption rule.")
    ])]
    proposals = generate_proposals(group_patterns(logs), logs)
    md = render_markdown(proposals)

    md_path, yaml_path = write_proposals(proposals_dir, proposals, md)

    assert md_path.exists()
    assert yaml_path.exists()
    assert md_path.name == "review_learning_proposals.md"
    assert yaml_path.name == "review_learning_proposals.yaml"


def test_write_proposals_yaml_is_valid(tmp_path):
    proposals_dir = tmp_path / "proposals"
    logs = [_review_log(corrections=[
        _correction("definition_status_mapping", "Working assumption rule.")
    ])]
    proposals = generate_proposals(group_patterns(logs), logs)
    md = render_markdown(proposals)
    _, yaml_path = write_proposals(proposals_dir, proposals, md)

    loaded = yaml.safe_load(yaml_path.read_text())
    assert loaded["schema_version"] == "1"
    assert "proposals" in loaded
    assert isinstance(loaded["proposals"], list)


def test_write_proposals_does_not_modify_source_files(tmp_path):
    """Script must only write inside the proposals dir — no other files created."""
    proposals_dir = tmp_path / "proposals"
    # Create a sibling directory to simulate data/cases/ being nearby
    cases_dir = tmp_path / "cases"
    cases_dir.mkdir()
    sentinel = cases_dir / "sentinel.yaml"
    sentinel.write_text("case_id: sentinel")

    logs = [_review_log(corrections=[_correction("note_cleanup", "Rule.")])]
    proposals = generate_proposals(group_patterns(logs), logs)
    md = render_markdown(proposals)
    write_proposals(proposals_dir, proposals, md)

    # Sentinel must be unchanged
    assert sentinel.read_text() == "case_id: sentinel"
    # Only the two expected files were created in proposals dir
    created = sorted(proposals_dir.iterdir())
    assert len(created) == 2
    names = {f.name for f in created}
    assert names == {"review_learning_proposals.md", "review_learning_proposals.yaml"}
