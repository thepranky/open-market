#!/usr/bin/env python3
"""
apply_review_learning.py — aggregates review learning logs into proposed pipeline feedback.

Reads all data/review_learning/*.review_delta.yaml files, groups correction patterns by
correction_type + reusable_rule_candidate, and proposes concrete pipeline improvements.

NEVER modifies prompts, validators, schemas, or canonical data.
No LLM calls — all proposals are derived from correction pattern analysis.

Usage (from repo root):
    python apps/api/scripts/cases/apply_review_learning.py
"""

import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------

_SCRIPTS_DIR = Path(__file__).resolve().parent
_API_DIR = _SCRIPTS_DIR.parent
_REPO_ROOT = _API_DIR.parents[1]

_REVIEW_LEARNING_DIR = _REPO_ROOT / "data" / "review_learning"
_PROPOSALS_DIR = _REVIEW_LEARNING_DIR / "proposals"

# ---------------------------------------------------------------------------
# Priority / proposal classification tables
# ---------------------------------------------------------------------------

# These correction types are always high-priority regardless of occurrence count.
_ALWAYS_HIGH_PRIORITY: frozenset[str] = frozenset({
    "outcome_passage_misuse",
    "definition_status_mapping",
    "missing_market_added",
    "quote_or_locator_correction",
    "source_role_correction",
    "schema_policy_change",
})

# These become high-priority only when they occur >= threshold times across the corpus.
_HIGH_IF_REPEATED: frozenset[str] = frozenset({
    "support_linkage_correction",
    "market_removed",
})

_HIGH_IF_REPEATED_THRESHOLD = 2

# These are low-priority by default; become medium when they exceed the threshold.
_LOW_PRIORITY: frozenset[str] = frozenset({
    "metadata_completion",
    "note_cleanup",
})

_LOW_PRIORITY_THRESHOLD = 3

# Map suggested_follow_up → proposal_action label used in output.
_FOLLOW_UP_TO_PROPOSAL: dict[str, str] = {
    "validator_rule": "validator_rule_candidate",
    "prompt_update": "extraction_prompt_update",
    "eval_fixture": "eval_fixture_candidate",
    "docs_update": "docs_update",
}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class Occurrence:
    case_id: str
    object_type: str
    object_id: Optional[str]
    before: Any
    after: Any
    confidence: str


@dataclass
class Pattern:
    correction_type: str
    reusable_rule_candidate: str
    suggested_follow_up: str
    occurrences: list[Occurrence] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.occurrences)

    @property
    def case_ids(self) -> list[str]:
        seen: dict[str, bool] = {}
        for o in self.occurrences:
            seen[o.case_id] = True
        return list(seen)

    @property
    def priority(self) -> str:
        ct = self.correction_type
        if ct in _ALWAYS_HIGH_PRIORITY:
            return "high"
        if ct in _HIGH_IF_REPEATED and self.count >= _HIGH_IF_REPEATED_THRESHOLD:
            return "high"
        if ct in _LOW_PRIORITY:
            return "low" if self.count < _LOW_PRIORITY_THRESHOLD else "medium"
        return "medium"

    @property
    def proposal_action(self) -> str:
        return _FOLLOW_UP_TO_PROPOSAL.get(self.suggested_follow_up, "no_action")


# ---------------------------------------------------------------------------
# Loading and grouping
# ---------------------------------------------------------------------------


def load_review_logs(review_dir: Path) -> list[dict]:
    """Load all *.review_delta.yaml files from review_dir, sorted by filename."""
    logs: list[dict] = []
    for path in sorted(review_dir.glob("*.review_delta.yaml")):
        data = yaml.safe_load(path.read_text())
        if data:
            logs.append(data)
    return logs


def group_patterns(logs: list[dict]) -> list[Pattern]:
    """
    Group all corrections across logs by (correction_type, reusable_rule_candidate).
    Returns patterns sorted: high priority first, then by descending count, then alphabetically.
    """
    groups: dict[tuple[str, str], Pattern] = {}

    for log in logs:
        case_id = log.get("case_id", "unknown")
        for correction in log.get("corrections", []):
            ct = correction.get("correction_type", "other")
            rule = correction.get("reusable_rule_candidate") or ""
            follow_up = correction.get("suggested_follow_up") or "no_action"

            key = (ct, rule)
            if key not in groups:
                groups[key] = Pattern(
                    correction_type=ct,
                    reusable_rule_candidate=rule,
                    suggested_follow_up=follow_up,
                )
            groups[key].occurrences.append(
                Occurrence(
                    case_id=case_id,
                    object_type=correction.get("object_type", ""),
                    object_id=correction.get("object_id"),
                    before=correction.get("before"),
                    after=correction.get("after"),
                    confidence=correction.get("confidence", ""),
                )
            )

    _PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}

    def _sort_key(p: Pattern) -> tuple:
        return (_PRIORITY_ORDER.get(p.priority, 3), -p.count, p.correction_type)

    return sorted(groups.values(), key=_sort_key)


# ---------------------------------------------------------------------------
# Proposal generation
# ---------------------------------------------------------------------------


def generate_proposals(patterns: list[Pattern], logs: list[dict]) -> dict:
    """Build the full proposals data structure (no I/O)."""
    total_corrections = sum(len(log.get("corrections", [])) for log in logs)
    case_ids = [log["case_id"] for log in logs if "case_id" in log]

    llm_insights: list[dict] = []
    for log in logs:
        ins = log.get("llm_review_insights")
        if ins and ins.get("triage_rationale"):
            llm_insights.append({
                "case_id": log.get("case_id"),
                "triage_status": ins.get("triage_status"),
                "triage_rationale": ins.get("triage_rationale"),
            })

    proposals_list: list[dict] = []
    for p in patterns:
        evidence = [
            {
                "case_id": o.case_id,
                "object_type": o.object_type,
                "object_id": o.object_id,
                "before": o.before,
                "after": o.after,
                "confidence": o.confidence,
            }
            for o in p.occurrences
        ]
        proposals_list.append({
            "correction_type": p.correction_type,
            "reusable_rule_candidate": p.reusable_rule_candidate,
            "suggested_follow_up": p.suggested_follow_up,
            "proposal_action": p.proposal_action,
            "priority": p.priority,
            "count": p.count,
            "cases": p.case_ids,
            "evidence": evidence,
        })

    return {
        "schema_version": "1",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "cases_reviewed": case_ids,
        "total_corrections": total_corrections,
        "total_patterns": len(patterns),
        "llm_review_insights": llm_insights,
        "proposals": proposals_list,
    }


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


def _truncate(s: str, n: int = 200) -> str:
    if len(s) <= n:
        return s
    return s[:n] + "…"


def _change_summary(before: Any, after: Any) -> str:
    if isinstance(before, dict) and isinstance(after, dict):
        parts = []
        for k in sorted(set(list(before.keys()) + list(after.keys()))):
            bv = before.get(k)
            av = after.get(k)
            if bv != av:
                parts.append(f"`{k}`: `{bv}` → `{av}`")
        return "; ".join(parts) if parts else "(see YAML for full diff)"
    if before is None and isinstance(after, dict):
        return "added: " + str(sorted(after.keys()))
    return f"`{before}` → `{after}`"


def _render_pattern_block(p: dict) -> list[str]:
    lines: list[str] = []
    ct = p["correction_type"]
    count = p["count"]
    cases_str = ", ".join(f"`{c}`" for c in p["cases"])
    action = p["proposal_action"]
    rule = p["reusable_rule_candidate"]

    lines.append(f"### `{ct}` — {count} occurrence{'s' if count != 1 else ''} (cases: {cases_str})")
    lines.append("")
    lines.append(f"**Proposed action:** `{action}`  ")
    if rule:
        lines.append(f"**Rule candidate:** {_truncate(rule)}")
    lines.append("")
    for ev in p["evidence"]:
        oid = f" `{ev['object_id']}`" if ev.get("object_id") else ""
        change = _change_summary(ev.get("before"), ev.get("after"))
        lines.append(f"- Case `{ev['case_id']}`{oid} ({ev.get('object_type', '')}): {change}")
    lines.append("")
    return lines


def render_markdown(proposals: dict) -> str:
    lines: list[str] = []
    now = proposals["generated_at"]
    cases = proposals["cases_reviewed"]
    total = proposals["total_corrections"]
    n_patterns = proposals["total_patterns"]
    all_proposals = proposals["proposals"]

    high = [p for p in all_proposals if p["priority"] == "high"]
    medium = [p for p in all_proposals if p["priority"] == "medium"]
    low = [p for p in all_proposals if p["priority"] == "low"]
    eval_all = [p for p in all_proposals if p["proposal_action"] == "eval_fixture_candidate"]

    # Non-eval high patterns go into the high-priority pipeline changes section.
    high_non_eval = [p for p in high if p["proposal_action"] != "eval_fixture_candidate"]

    by_priority: dict[str, int] = {
        "high": len(high),
        "medium": len(medium),
        "low": len(low),
    }

    lines += [
        "# Review Learning Proposals",
        "",
        f"Generated: {now}  ",
        (
            f"Cases reviewed: {len(cases)}"
            f"  |  Total corrections: {total}"
            f"  |  Patterns identified: {n_patterns}"
        ),
        "",
        "---",
        "",
    ]

    # Summary
    lines += ["## Summary", ""]
    lines += [f"- **Cases reviewed:** {', '.join(f'`{c}`' for c in cases)}"]
    lines += [f"- **Total corrections captured:** {total}"]
    lines += [f"- **Distinct patterns:** {n_patterns}"]
    priority_parts = [f"{v} {k}" for k, v in sorted(by_priority.items()) if v]
    if priority_parts:
        lines += [f"- **Priority breakdown:** {', '.join(priority_parts)} patterns"]
    lines += [""]

    # High-priority pipeline changes (excludes eval fixtures, which have their own section)
    lines += ["## High-Priority Proposed Pipeline Changes", ""]
    if not high_non_eval:
        lines += [
            "> No high-priority pipeline changes in the current corpus.  ",
            "> The corrections found are mostly metadata completion and note cleanup — "
            "low-risk artefacts of the promotion workflow rather than substantive extraction failures.",
            "",
        ]
    else:
        by_action: dict[str, list[dict]] = {}
        for p in high_non_eval:
            by_action.setdefault(p["proposal_action"], []).append(p)
        for action in sorted(by_action):
            lines += [f"### {action.replace('_', ' ').title()}", ""]
            for p in by_action[action]:
                lines += _render_pattern_block(p)

    # Eval fixture candidates (all priorities)
    lines += ["## Eval Fixture Candidates", ""]
    if not eval_all:
        lines += ["> No eval fixture candidates in the current corpus.", ""]
    else:
        for p in eval_all:
            lines += _render_pattern_block(p)

    # LLM review insights
    insights = proposals.get("llm_review_insights", [])
    lines += ["## LLM Review Insights", ""]
    if not insights:
        lines += ["> No LLM review insights available in the current corpus.", ""]
    else:
        for ins in insights:
            case_id = ins.get("case_id", "")
            status = ins.get("triage_status", "")
            rationale = ins.get("triage_rationale", "")
            lines += [f"**Case `{case_id}`** — triage status: `{status}`", ""]
            if rationale:
                lines += [f"> {rationale}", ""]
            lines += [
                "**Implied proposals (require human judgement before acting):**",
                "- `review_prompt_update`: Clarify `considered` vs `defined` working-assumption "
                "language in the LLM review prompt.",
                "- `extraction_prompt_update`: Flag mixed passages (outcome + definition language "
                "in the same quote snippet) as a known difficult pattern.",
                "",
            ]

    # Low-priority / no-action
    low_medium_non_eval = [
        p for p in (medium + low)
        if p["proposal_action"] != "eval_fixture_candidate"
    ]
    lines += ["## Low-Priority / No-Action Items", ""]
    if not low_medium_non_eval:
        lines += ["> None.", ""]
    else:
        for p in low_medium_non_eval:
            ct = p["correction_type"]
            count = p["count"]
            rule = _truncate(p["reusable_rule_candidate"], 150)
            action = p["proposal_action"]
            priority = p["priority"]
            lines += [
                f"- **`{ct}`** ({count}x, priority: {priority}) → `{action}`  ",
                f"  Rule: {rule}",
                "",
            ]

    # Human approval checklist
    lines += [
        "## Human Approval Checklist",
        "",
        "Review and approve before applying any change to pipeline code or prompts:",
        "",
    ]
    checklist: list[str] = []
    if any(p["proposal_action"] == "extraction_prompt_update" for p in high_non_eval):
        checklist.append("[ ] Apply extraction prompt updates for high-priority patterns above")
    if any(p["proposal_action"] == "review_prompt_update" for p in all_proposals):
        checklist.append("[ ] Apply LLM review prompt updates for flagged patterns")
    if insights:
        checklist.append("[ ] Review LLM review prompt for `considered` vs `defined` mapping lesson")
    if any(p["proposal_action"] == "validator_rule_candidate" for p in all_proposals):
        checklist.append("[ ] Implement and test validator rules for approved candidates")
    if eval_all:
        checklist.append("[ ] Add approved eval fixtures to gold standard")
    if any(p["proposal_action"] == "docs_update" for p in all_proposals):
        checklist.append("[ ] Apply approved docs / promotion checklist updates")
    if any(p["proposal_action"] == "extraction_prompt_update" for p in low_medium_non_eval):
        checklist.append("[ ] Consider low-priority extraction prompt updates (note cleanup patterns)")
    checklist.append("[ ] Re-run review learning log after any prompt changes")
    checklist.append("[ ] Verify eval benchmark scores do not regress after changes")

    for item in checklist:
        lines.append(f"- {item}")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Write output
# ---------------------------------------------------------------------------


def write_proposals(
    proposals_dir: Path,
    proposals: dict,
    md: str,
) -> tuple[Path, Path]:
    proposals_dir.mkdir(parents=True, exist_ok=True)

    md_path = proposals_dir / "review_learning_proposals.md"
    yaml_path = proposals_dir / "review_learning_proposals.yaml"

    md_path.write_text(md)
    with yaml_path.open("w") as fh:
        yaml.dump(
            proposals,
            fh,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
            width=100,
        )

    return md_path, yaml_path


# ---------------------------------------------------------------------------
# Terminal summary
# ---------------------------------------------------------------------------


def _print_summary(proposals: dict, md_path: Path, yaml_path: Path) -> None:
    cases = proposals["cases_reviewed"]
    total = proposals["total_corrections"]
    n_patterns = proposals["total_patterns"]
    n_high = sum(1 for p in proposals["proposals"] if p["priority"] == "high")
    n_med = sum(1 for p in proposals["proposals"] if p["priority"] == "medium")
    n_low = sum(1 for p in proposals["proposals"] if p["priority"] == "low")

    print(f"\n=== Apply Review Learning: {len(cases)} case(s) ===")
    print(f"Cases: {', '.join(cases)}")
    print(f"Total corrections: {total}  |  Patterns: {n_patterns}")
    print(f"Priority: {n_high} high, {n_med} medium, {n_low} low")
    print(f"\nOutput:")
    print(f"  Markdown: {md_path}")
    print(f"  YAML:     {yaml_path}")
    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    logs = load_review_logs(_REVIEW_LEARNING_DIR)
    if not logs:
        print(
            "No review delta files found in data/review_learning/. "
            "Run create_review_learning_log.py first.",
            file=sys.stderr,
        )
        sys.exit(1)

    patterns = group_patterns(logs)
    proposals = generate_proposals(patterns, logs)
    md = render_markdown(proposals)
    md_path, yaml_path = write_proposals(_PROPOSALS_DIR, proposals, md)
    _print_summary(proposals, md_path, yaml_path)


if __name__ == "__main__":
    main()
