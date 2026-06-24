#!/usr/bin/env python3
"""
create_review_learning_log.py — captures human-correction deltas for a promoted case.

Reads the original draft YAML, the optional LLM review JSON, and the promoted canonical
YAML. Writes a structured delta log to data/review_learning/ so human corrections become
reusable rules, validator warnings, prompt updates, and eval fixtures.

NEVER modifies data/cases/ or data/drafts/.
No LLM calls — all classification is deterministic.

Usage (from repo root):
    python apps/api/scripts/cases/create_review_learning_log.py \\
        --case-id eu_sika_dry_mix_2019 \\
        --focus market_definition
"""

import argparse
import json
import sys
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

_DRAFTS_DIR = _REPO_ROOT / "data" / "drafts"
_CASES_DIR = _REPO_ROOT / "data" / "cases"
_REVIEW_LEARNING_DIR = _REPO_ROOT / "data" / "review_learning"

# ---------------------------------------------------------------------------
# Draft-only fields — stripped at canonical promotion; absence in canonical
# is not a substantive correction.
# ---------------------------------------------------------------------------

# source_role is removed during canonical promotion — not a legal correction.
_DRAFT_ONLY_PASSAGE_FIELDS: frozenset[str] = frozenset({"source_role"})

# review_status and confidence_score are operational quality metadata that legitimately
# differ between draft and canonical based on the promotion workflow (e.g. the extraction
# script marks passages spot_checked/0.9 while the canonical may reset them to
# unreviewed/0.8 as a conservative policy).  They are not substantive legal corrections in
# v1.  Track these in a separate set so they can be re-enabled with proper upgrade-only
# logic later without touching _DRAFT_ONLY_PASSAGE_FIELDS.
_PASSAGE_QUALITY_FIELDS: frozenset[str] = frozenset({"review_status", "confidence_score"})

_DRAFT_ONLY_MARKET_FIELDS: frozenset[str] = frozenset({"verification", "market_importance"})
_DRAFT_ONLY_TOP_FIELDS: frozenset[str] = frozenset({"_draft_note"})

# Fields always added fresh during canonical promotion; their absence in the
# draft does not represent a missing-extraction failure.
_CANONICAL_ONLY_SECTIONS: frozenset[str] = frozenset({"similar_cases", "case_history"})
_CANONICAL_PROMOTION_SCALAR_FIELDS: frozenset[str] = frozenset(
    {"procedure_stage", "case_type", "authority_reference"}
)

# ---------------------------------------------------------------------------
# Outcome-passage detection
# ---------------------------------------------------------------------------

_OUTCOME_PHRASES = (
    "does not raise serious doubts",
    "does not significantly impede",
    "raises no serious doubts",
    "no serious doubts",
    "compatible with the internal market",
    "compatible with the common market",
    "no competition concerns",
)


def _is_outcome_passage(passage: dict) -> bool:
    quote = (passage.get("quote_snippet") or "").lower()
    return any(phrase in quote for phrase in _OUTCOME_PHRASES)


# ---------------------------------------------------------------------------
# Text normalisation — collapse whitespace so YAML block scalars compare cleanly
# ---------------------------------------------------------------------------


def _norm(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split())


# ---------------------------------------------------------------------------
# Correction record builder
# ---------------------------------------------------------------------------


def _correction(
    *,
    correction_type: str,
    object_type: str,
    before: Any,
    after: Any,
    inferred_reason: str,
    reusable_rule_candidate: str,
    suggested_follow_up: str,
    confidence: str,
    object_id: Optional[str] = None,
) -> dict:
    c: dict = {"correction_type": correction_type, "object_type": object_type}
    if object_id:
        c["object_id"] = object_id
    c["before"] = before
    c["after"] = after
    c["inferred_reason"] = inferred_reason
    c["reusable_rule_candidate"] = reusable_rule_candidate
    c["suggested_follow_up"] = suggested_follow_up
    c["confidence"] = confidence
    return c


# ---------------------------------------------------------------------------
# Diff: top-level case fields
# ---------------------------------------------------------------------------


def _diff_case_metadata(draft: dict, canonical: dict, corrections: list) -> None:
    case_id = canonical.get("case_id", "")

    # outcome: placeholder → resolved value
    d_outcome = draft.get("outcome")
    c_outcome = canonical.get("outcome")
    if d_outcome != c_outcome and d_outcome is not None:
        corrections.append(
            _correction(
                correction_type="metadata_completion",
                object_type="case",
                object_id=case_id,
                before={"outcome": d_outcome},
                after={"outcome": c_outcome},
                inferred_reason=(
                    "Draft used 'unknown' as a placeholder outcome; human reviewer set "
                    "the actual outcome after verifying the conclusion section of the source decision."
                ),
                reusable_rule_candidate=(
                    "outcome: unknown is a promotion blocker — always resolve against "
                    "the conclusion section before promoting to data/cases/."
                ),
                suggested_follow_up="validator_rule",
                confidence="high",
            )
        )

    # Scalar promotion fields (procedure_stage, case_type, authority_reference)
    promotion_completions: dict = {}
    for field in sorted(_CANONICAL_PROMOTION_SCALAR_FIELDS):
        if field not in draft and field in canonical:
            promotion_completions[field] = canonical[field]

    if promotion_completions:
        corrections.append(
            _correction(
                correction_type="metadata_completion",
                object_type="case",
                object_id=case_id,
                before={f: None for f in promotion_completions},
                after=promotion_completions,
                inferred_reason=(
                    "Required fields absent from draft; set by the human reviewer "
                    "during canonical promotion."
                ),
                reusable_rule_candidate=(
                    "procedure_stage, case_type, and authority_reference must always be "
                    "explicitly resolved during the promotion checklist review."
                ),
                suggested_follow_up="docs_update",
                confidence="high",
            )
        )

    # metadata block — always added at promotion
    if "metadata" not in draft and "metadata" in canonical:
        meta = canonical["metadata"]
        corrections.append(
            _correction(
                correction_type="metadata_completion",
                object_type="metadata",
                object_id=case_id,
                before=None,
                after={
                    "overall_confidence": meta.get("overall_confidence"),
                    "review_status": meta.get("review_status"),
                    "created_date": meta.get("created_date"),
                },
                inferred_reason=(
                    "The metadata block (overall_confidence, review_status, dates) is not "
                    "written by the extraction script and is always created at promotion time."
                ),
                reusable_rule_candidate=(
                    "The metadata block is a required canonical section. It must be added "
                    "during promotion; its absence from drafts is expected."
                ),
                suggested_follow_up="docs_update",
                confidence="high",
            )
        )


# ---------------------------------------------------------------------------
# Diff: product and geographic markets
# ---------------------------------------------------------------------------


def _diff_markets(
    draft_markets: list,
    canonical_markets: list,
    object_type: str,
    corrections: list,
    llm_review: Optional[dict],
) -> None:
    draft_by_id = {m["market_id"]: m for m in (draft_markets or [])}
    canon_by_id = {m["market_id"]: m for m in (canonical_markets or [])}

    for mid in draft_by_id:
        if mid not in canon_by_id:
            d = draft_by_id[mid]
            corrections.append(
                _correction(
                    correction_type="market_removed",
                    object_type=object_type,
                    object_id=mid,
                    before={"market_id": mid, "name": d.get("name"),
                            "definition_status": d.get("definition_status")},
                    after=None,
                    inferred_reason="Market present in draft was not retained in the canonical record.",
                    reusable_rule_candidate=(
                        "Review removed markets — they may indicate LLM over-extraction. "
                        "Add to eval fixture so future completeness metrics exclude them."
                    ),
                    suggested_follow_up="eval_fixture",
                    confidence="medium",
                )
            )

    for mid in canon_by_id:
        if mid not in draft_by_id:
            c = canon_by_id[mid]
            corrections.append(
                _correction(
                    correction_type="missing_market_added",
                    object_type=object_type,
                    object_id=mid,
                    before=None,
                    after={
                        "market_id": mid,
                        "name": c.get("name"),
                        "definition_status": c.get("definition_status"),
                    },
                    inferred_reason="Human reviewer identified a market that the LLM extraction missed.",
                    reusable_rule_candidate=(
                        "Add this market to the eval fixture gold standard to measure "
                        "extraction completeness for similar cases."
                    ),
                    suggested_follow_up="eval_fixture",
                    confidence="high",
                )
            )

    for mid in sorted(set(draft_by_id) & set(canon_by_id)):
        d = draft_by_id[mid]
        c = canon_by_id[mid]

        d_status = d.get("definition_status")
        c_status = c.get("definition_status")
        if d_status != c_status:
            corrections.append(
                _correction(
                    correction_type="definition_status_mapping",
                    object_type=object_type,
                    object_id=mid,
                    before={"definition_status": d_status},
                    after={"definition_status": c_status},
                    inferred_reason=_infer_definition_status_reason(d_status, c_status, d),
                    reusable_rule_candidate=_definition_status_rule(d_status, c_status),
                    suggested_follow_up="prompt_update",
                    confidence="high",
                )
            )

        d_notes = _norm(d.get("notes"))
        c_notes = _norm(c.get("notes"))
        if d_notes and c_notes and d_notes != c_notes:
            corrections.append(
                _correction(
                    correction_type="note_cleanup",
                    object_type=object_type,
                    object_id=mid,
                    before={"notes": (d.get("notes") or "").strip()},
                    after={"notes": (c.get("notes") or "").strip()},
                    inferred_reason=(
                        "Notes revised during canonical promotion "
                        "(e.g. 'draft' → 'record', wording clarification, added context)."
                    ),
                    reusable_rule_candidate=(
                        "Draft-specific language (e.g. 'in this draft') should be avoided "
                        "in extraction notes so they need no cleanup at promotion time."
                    ),
                    suggested_follow_up="prompt_update",
                    confidence="low",
                )
            )


def _infer_definition_status_reason(before: str, after: str, market: dict) -> str:
    name = market.get("name", "")
    if before == "defined" and after == "considered":
        return (
            f"Market '{name}': Commission used a working-assumption formula "
            "('for assessing the Transaction' / 'for the purpose of this decision') "
            "rather than a definitive determination. CompMap policy maps this to 'considered'."
        )
    if before == "considered" and after == "defined":
        return (
            f"Market '{name}': Authority made an explicit definitive product market "
            "determination, warranting upgrade from 'considered' to 'defined'."
        )
    if after == "left_open":
        return (
            f"Market '{name}': Authority explicitly left the market definition open "
            "rather than concluding — correct status is 'left_open'."
        )
    if after == "discussed":
        return (
            f"Market '{name}': Authority discussed but did not formally conclude on "
            "the market — correct status is 'discussed'."
        )
    return (
        f"Market '{name}': definition_status changed from '{before}' to '{after}' "
        "during human review."
    )


def _definition_status_rule(before: str, after: str) -> str:
    if before == "defined" and after == "considered":
        return (
            "When authority language uses 'for assessing the Transaction', "
            "'for the purpose of this decision', or 'should be considered as a separate "
            "product market', map definition_status to 'considered', not 'defined'. "
            "'defined' should be reserved for decisions that explicitly resolve the boundary."
        )
    if after == "left_open":
        return (
            "When authority explicitly states that market definition can be left open "
            "because competition concerns do not arise under any plausible definition, "
            "map definition_status to 'left_open'."
        )
    return "Update definition_status mapping table in extraction prompt."


# ---------------------------------------------------------------------------
# Diff: source passages
# ---------------------------------------------------------------------------


def _diff_passages(
    draft_passages: list,
    canonical_passages: list,
    corrections: list,
    llm_review: Optional[dict],
) -> None:
    draft_by_id = {p["passage_id"]: p for p in (draft_passages or [])}
    canon_by_id = {p["passage_id"]: p for p in (canonical_passages or [])}

    llm_notes: dict[str, dict] = {}
    if llm_review:
        for pr in llm_review.get("passage_reviews", []):
            llm_notes[pr["passage_id"]] = pr

    for pid in sorted(draft_by_id):
        if pid not in canon_by_id:
            continue  # passage removed: unusual; silently skipped in v1

        d = draft_by_id[pid]
        c = canon_by_id[pid]

        # supports_markets
        d_sm = set(d.get("supports_markets") or [])
        c_sm = set(c.get("supports_markets") or [])
        if d_sm != c_sm:
            removed = sorted(d_sm - c_sm)
            if removed and _is_outcome_passage(d):
                corrections.append(
                    _correction(
                        correction_type="outcome_passage_misuse",
                        object_type="source_passage",
                        object_id=pid,
                        before={"supports_markets": sorted(d_sm)},
                        after={"supports_markets": sorted(c_sm)},
                        inferred_reason=(
                            "Passage contains outcome/clearance language "
                            "('does not raise serious doubts') and must not be linked to "
                            "market entries — it confirms the outcome, not the market definition."
                        ),
                        reusable_rule_candidate=(
                            "Passages whose quote_snippet contains clearance language must "
                            "not appear in supports_markets or supports_geographic_markets. "
                            "Add an automated validator check for this pattern."
                        ),
                        suggested_follow_up="validator_rule",
                        confidence="high",
                    )
                )
            else:
                llm_note = (llm_notes.get(pid) or {}).get("note", "")
                corrections.append(
                    _correction(
                        correction_type="support_linkage_correction",
                        object_type="source_passage",
                        object_id=pid,
                        before={"supports_markets": sorted(d_sm)},
                        after={"supports_markets": sorted(c_sm)},
                        inferred_reason=(
                            "Human reviewer adjusted which product markets this passage supports."
                            + (f" LLM note: {llm_note}" if llm_note else "")
                        ),
                        reusable_rule_candidate=(
                            "Review support linkage rules for this passage type in the extraction prompt."
                        ),
                        suggested_follow_up="prompt_update",
                        confidence="medium",
                    )
                )

        # supports_geographic_markets
        d_sgm = set(d.get("supports_geographic_markets") or [])
        c_sgm = set(c.get("supports_geographic_markets") or [])
        if d_sgm != c_sgm:
            removed = sorted(d_sgm - c_sgm)
            if removed and _is_outcome_passage(d):
                corrections.append(
                    _correction(
                        correction_type="outcome_passage_misuse",
                        object_type="source_passage",
                        object_id=pid,
                        before={"supports_geographic_markets": sorted(d_sgm)},
                        after={"supports_geographic_markets": sorted(c_sgm)},
                        inferred_reason=(
                            "Outcome/clearance passage incorrectly linked to geographic market entries."
                        ),
                        reusable_rule_candidate=(
                            "Clearance passages must not be added to supports_geographic_markets."
                        ),
                        suggested_follow_up="validator_rule",
                        confidence="high",
                    )
                )
            else:
                llm_note = (llm_notes.get(pid) or {}).get("note", "")
                corrections.append(
                    _correction(
                        correction_type="support_linkage_correction",
                        object_type="source_passage",
                        object_id=pid,
                        before={"supports_geographic_markets": sorted(d_sgm)},
                        after={"supports_geographic_markets": sorted(c_sgm)},
                        inferred_reason=(
                            "Human reviewer adjusted geographic market support links."
                            + (f" LLM note: {llm_note}" if llm_note else "")
                        ),
                        reusable_rule_candidate=(
                            "Review geographic support linkage rules in the extraction prompt."
                        ),
                        suggested_follow_up="prompt_update",
                        confidence="medium",
                    )
                )

        # quote_snippet or page locator
        if _norm(d.get("quote_snippet")) != _norm(c.get("quote_snippet")) or d.get("page") != c.get("page"):
            if d.get("quote_snippet") and c.get("quote_snippet"):
                corrections.append(
                    _correction(
                        correction_type="quote_or_locator_correction",
                        object_type="source_passage",
                        object_id=pid,
                        before={"quote_snippet": (d.get("quote_snippet") or "").strip(),
                                "page": d.get("page")},
                        after={"quote_snippet": (c.get("quote_snippet") or "").strip(),
                               "page": c.get("page")},
                        inferred_reason=(
                            "Human reviewer corrected or trimmed the quote snippet or page locator."
                        ),
                        reusable_rule_candidate=(
                            "Review quote extraction precision and page locator accuracy in the "
                            "extraction prompt."
                        ),
                        suggested_follow_up="prompt_update",
                        confidence="medium",
                    )
                )

        # review_status and confidence_score are intentionally NOT compared here.
        # These are operational quality metadata that legitimately differ between draft
        # and canonical based on the promotion workflow — the extraction script sets them
        # by heuristic (spot_checked/0.9) while the canonical may reset them to more
        # conservative values (unreviewed/0.8) as a policy.  Treating those differences
        # as human corrections adds noise.  See _PASSAGE_QUALITY_FIELDS.


# ---------------------------------------------------------------------------
# Main delta computation
# ---------------------------------------------------------------------------


def compute_review_delta(
    draft: dict,
    canonical: dict,
    llm_review: Optional[dict],
) -> tuple[list[dict], dict]:
    """Return (corrections, summary). Pure function; no I/O."""
    corrections: list[dict] = []

    _diff_case_metadata(draft, canonical, corrections)

    _diff_markets(
        draft.get("product_markets_considered") or [],
        canonical.get("product_markets_considered") or [],
        "product_market",
        corrections,
        llm_review,
    )

    _diff_markets(
        draft.get("geographic_markets_considered") or [],
        canonical.get("geographic_markets_considered") or [],
        "geographic_market",
        corrections,
        llm_review,
    )

    _diff_passages(
        draft.get("source_passages") or [],
        canonical.get("source_passages") or [],
        corrections,
        llm_review,
    )

    by_type: dict[str, int] = {}
    for c in corrections:
        ct = c["correction_type"]
        by_type[ct] = by_type.get(ct, 0) + 1

    summary: dict = {
        "total_corrections": len(corrections),
        "by_type": by_type,
    }

    if llm_review:
        summary["llm_triage_status"] = llm_review.get("triage_status", "")

    return corrections, summary


# ---------------------------------------------------------------------------
# File path helpers
# ---------------------------------------------------------------------------


def _jurisdiction(case_id: str) -> str:
    return case_id.split("_")[0].lower()


def _default_draft_path(case_id: str, focus: str) -> Path:
    return _DRAFTS_DIR / _jurisdiction(case_id) / f"{case_id}.{focus}.draft.yaml"


def _default_llm_review_path(case_id: str, focus: str) -> Path:
    return _DRAFTS_DIR / _jurisdiction(case_id) / f"{case_id}.{focus}.llm_review.json"


def _default_canonical_path(case_id: str) -> Path:
    return _CASES_DIR / _jurisdiction(case_id) / f"{case_id}.yaml"


def _default_output_path(case_id: str, focus: str) -> Path:
    return _REVIEW_LEARNING_DIR / f"{case_id}.{focus}.review_delta.yaml"


# ---------------------------------------------------------------------------
# Build and write log
# ---------------------------------------------------------------------------


def build_review_log(
    case_id: str,
    focus: str,
    draft_path: Optional[Path] = None,
    llm_review_path: Optional[Path] = None,
    canonical_path: Optional[Path] = None,
    output_path: Optional[Path] = None,
) -> tuple[Path, dict]:
    """Build the review delta YAML and write it. Returns (output_path, log_dict)."""
    if draft_path is None:
        draft_path = _default_draft_path(case_id, focus)
    if llm_review_path is None:
        llm_review_path = _default_llm_review_path(case_id, focus)
    if canonical_path is None:
        canonical_path = _default_canonical_path(case_id)
    if output_path is None:
        output_path = _default_output_path(case_id, focus)

    if not draft_path.exists():
        raise FileNotFoundError(f"Draft not found: {draft_path}")
    if not canonical_path.exists():
        raise FileNotFoundError(f"Canonical case not found: {canonical_path}")

    draft = yaml.safe_load(draft_path.read_text())
    canonical = yaml.safe_load(canonical_path.read_text())

    llm_review: Optional[dict] = None
    if llm_review_path.exists():
        llm_review = json.loads(llm_review_path.read_text())
    else:
        print(
            f"[info] LLM review JSON not found at {llm_review_path}; proceeding without it.",
            file=sys.stderr,
        )

    corrections, summary = compute_review_delta(draft, canonical, llm_review)

    def _rel(p: Path) -> str:
        try:
            return str(p.relative_to(_REPO_ROOT))
        except ValueError:
            return str(p)

    log: dict = {
        "schema_version": "1",
        "case_id": case_id,
        "focus": focus,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_files": {
            "draft": _rel(draft_path),
            "llm_review": _rel(llm_review_path) if llm_review_path.exists() else None,
            "canonical": _rel(canonical_path),
        },
        "summary": summary,
    }

    # Attach LLM triage insights so lessons survive even when no diff correction was generated
    if llm_review:
        log["llm_review_insights"] = {
            "triage_status": llm_review.get("triage_status"),
            "triage_rationale": llm_review.get("triage_rationale"),
        }

    log["corrections"] = corrections

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w") as fh:
        yaml.dump(
            log,
            fh,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
            width=100,
        )

    return output_path, log


# ---------------------------------------------------------------------------
# Terminal summary
# ---------------------------------------------------------------------------


def _print_summary(output_path: Path, log: dict) -> None:
    summary = log["summary"]
    total = summary["total_corrections"]

    print(f"\n=== Review Learning Log: {log['case_id']} ({log['focus']}) ===")
    print(f"Output: {output_path}")
    print(f"Total corrections: {total}")

    if total:
        print("\nBy type:")
        for ct, count in sorted(summary.get("by_type", {}).items()):
            print(f"  {ct:<30} {count}")

    triage = summary.get("llm_triage_status")
    if triage:
        print(f"\nLLM triage status: {triage}")
    insights = log.get("llm_review_insights", {})
    rationale = insights.get("triage_rationale")
    if rationale:
        lines = rationale.strip().splitlines()
        print(f"LLM triage rationale: {lines[0][:120]}" + ("…" if len(rationale) > 120 else ""))

    if log.get("corrections"):
        print("\nCorrections:")
        for c in log["corrections"]:
            oid = c.get("object_id", "")
            fu = c.get("suggested_follow_up", "")
            conf = c.get("confidence", "")
            print(f"  [{c['correction_type']:<30} | {c['object_type']:<20} | {oid:<12}]  "
                  f"follow_up={fu}  confidence={conf}")
    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a review learning log by diffing draft → canonical."
    )
    parser.add_argument("--case-id", required=True, help="Case ID, e.g. eu_sika_dry_mix_2019")
    parser.add_argument("--focus", required=True, help="Focus area, e.g. market_definition")
    parser.add_argument("--draft", type=Path, help="Override draft YAML path")
    parser.add_argument("--llm-review", type=Path, dest="llm_review", help="Override LLM review JSON path")
    parser.add_argument("--canonical", type=Path, help="Override canonical YAML path")
    parser.add_argument("--output", type=Path, help="Override output YAML path")
    args = parser.parse_args()

    try:
        output_path, log = build_review_log(
            case_id=args.case_id,
            focus=args.focus,
            draft_path=args.draft,
            llm_review_path=args.llm_review,
            canonical_path=args.canonical,
            output_path=args.output,
        )
        _print_summary(output_path, log)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
