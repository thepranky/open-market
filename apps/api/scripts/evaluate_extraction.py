#!/usr/bin/env python3
"""
evaluate_extraction.py — Compare reviewed gold YAML against draft YAML + report.

Computes precision, recall, F1, source validity, and promotion safety metrics.
Outputs detailed per-market match diagnostics so false negatives can be debugged.

Partial vs full gold
--------------------
Full gold (``partial: false``):
  Every draft market not present in the gold set counts as a false positive.

Partial gold (``partial: true``):
  - TP  = reviewed gold items found in draft (by name, alias, expected_draft_names, expected_market_ids)
  - FN  = reviewed gold items NOT found in draft
  - FP  = draft items inside the explicitly reviewed scope/group that are not in gold
  - unjudged_candidates = draft items outside the reviewed scope

Matching (in priority order for each gold item)
-----------------------------------------------
1. Exact normalised name match.
2. Gold ``aliases`` list (normalised).
3. Gold ``expected_draft_names`` list (normalised) — explicit alternate names expected
   in the draft (handles extraction naming drift).
4. Gold ``expected_market_ids`` list — draft markets whose ``market_id`` is in this list.

Diagnostics
-----------
Every ``product_markets`` / ``geographic_markets`` result block contains:
  - ``matched_items``   — list of {gold_name, draft_name, match_type}
  - ``false_negatives`` — list of {gold_name, aliases, expected_draft_names,
                                   expected_market_ids, market_group,
                                   expected_definition_status,
                                   nearest_draft_candidates}
  - ``false_positives`` — list of {draft_name}
  - ``unjudged_items``  — list of {draft_name}

For every FN, up to 5 nearest draft candidates are reported by conservative
normalised token-overlap score.  They are *not* counted as matches; they exist
only to help identify naming drift.

Optional gold fields
--------------------
``expected_draft_names``: list[str]
    Alternate draft names the reviewer expects this market to appear under.

``expected_market_ids``: list[str]
    Draft ``market_id`` values the reviewer expects this market to map to.

Usage
-----
    cd apps/api

    .venv/bin/python scripts/evaluate_extraction.py \\
        --case-id eu_google_fitbit_2021 \\
        --gold-yaml ../../data/evals/gold/eu_google_fitbit_2021.gold.yaml \\
        --draft-yaml ../../data/drafts/eu/google_fitbit_2021.draft.yaml \\
        --report-json ../../data/source_text/google_fitbit_extraction_report.json \\
        --output-json ../../data/evals/results/eu_google_fitbit_2021.eval.json \\
        --output-markdown ../../data/evals/results/eu_google_fitbit_2021.eval.md
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

_API_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_API_DIR))
sys.path.insert(0, str(_API_DIR / "scripts"))

from validate_gold_quotes import validate_gold_passages
from app.utils.pdf_extractor import DEFAULT_CACHE_DIR

_MAX_CANDIDATES = 5  # nearest-draft-candidates limit per FN


# ---------------------------------------------------------------------------
# Name normalisation and token overlap (for diagnostics)
# ---------------------------------------------------------------------------

def _normalize_name(name: str) -> str:
    """Normalise a market name for matching: lowercase + strip."""
    return name.lower().strip()


_TOKEN_STOPWORDS: frozenset[str] = frozenset({
    "the", "a", "an", "of", "for", "and", "or", "to", "in", "at", "by", "on",
    "with", "from", "within", "relevant", "product", "market", "markets",
    "supply", "provision", "services", "service",
})


def _token_set(name: str) -> frozenset[str]:
    """Return significant tokens from *name* for overlap scoring."""
    return frozenset(
        w for w in re.findall(r"\b\w+\b", name.lower())
        if len(w) >= 3 and w not in _TOKEN_STOPWORDS
    )


def _token_overlap_score(a: str, b: str) -> float:
    """Jaccard-like token overlap score in [0, 1] — conservative, no fuzzy expansion."""
    ta, tb = _token_set(a), _token_set(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _nearest_draft_candidates(
    gold_name: str,
    draft_markets: list[dict],
    top_n: int = _MAX_CANDIDATES,
) -> list[dict]:
    """Return up to *top_n* draft markets with the highest token overlap with *gold_name*.

    Only candidates with overlap > 0 are included.  The result is sorted by
    score descending.  These are diagnostic hints — they are never counted as matches.
    """
    scored = []
    for dm in draft_markets:
        score = _token_overlap_score(gold_name, dm.get("name", ""))
        if score > 0:
            scored.append((score, dm.get("name", ""), dm.get("market_id", "")))
    scored.sort(key=lambda x: -x[0])
    return [
        {"draft_name": name, "market_id": mid, "overlap_score": round(score, 3)}
        for score, name, mid in scored[:top_n]
    ]


# ---------------------------------------------------------------------------
# Extended match logic
# ---------------------------------------------------------------------------

def _find_matching_market(
    gold_name: str,
    draft_markets: list[dict],
    aliases: dict[str, list[str]],
    expected_draft_names: Optional[list[str]] = None,
    expected_market_ids: Optional[list[str]] = None,
) -> Optional[tuple[dict, str]]:
    """Find a matching draft market, returning ``(draft_market, match_type)`` or None.

    Match types (in priority order):
    1. ``exact``              — normalised name equality
    2. ``alias``              — name matches a gold alias
    3. ``expected_draft_name``— name matches an expected_draft_names entry
    4. ``expected_market_id`` — draft market_id is in expected_market_ids
    """
    gold_norm = _normalize_name(gold_name)

    # 1. Exact name
    for dm in draft_markets:
        if _normalize_name(dm.get("name", "")) == gold_norm:
            return dm, "exact"

    # 2. Aliases from gold aliases map
    for alias in (aliases.get(gold_name) or []):
        alias_norm = _normalize_name(alias)
        for dm in draft_markets:
            if _normalize_name(dm.get("name", "")) == alias_norm:
                return dm, "alias"

    # 3. expected_draft_names
    for edn in (expected_draft_names or []):
        edn_norm = _normalize_name(edn)
        for dm in draft_markets:
            if _normalize_name(dm.get("name", "")) == edn_norm:
                return dm, "expected_draft_name"

    # 4. expected_market_ids
    for eid in (expected_market_ids or []):
        for dm in draft_markets:
            if str(dm.get("market_id", "")) == str(eid):
                return dm, "expected_market_id"

    return None


def _matches_any_gold(
    draft_m: dict,
    reviewed_gold: list[dict],
    aliases_map: dict[str, list[str]],
) -> bool:
    """Return True if *draft_m* matches any reviewed gold market by any strategy."""
    for gm in reviewed_gold:
        result = _find_matching_market(
            gm.get("name", ""),
            [draft_m],
            aliases_map,
            gm.get("expected_draft_names"),
            gm.get("expected_market_ids"),
        )
        if result is not None:
            return True
    return False


# ---------------------------------------------------------------------------
# Market evaluation (scope-aware + diagnostics)
# ---------------------------------------------------------------------------

def _build_reviewed_groups(
    gold_markets: list[dict],
    reviewed_scope: Optional[dict],
) -> frozenset[str]:
    """Return the set of ``market_group`` values in the reviewed scope."""
    groups: set[str] = set()
    for m in gold_markets:
        if m.get("reviewed"):
            g = m.get("market_group")
            if g is not None:
                groups.add(str(g))
    for g in ((reviewed_scope or {}).get("groups") or []):
        groups.add(str(g))
    return frozenset(groups)


def _evaluate_markets(
    gold_markets: list[dict],
    draft_markets: list[dict],
    market_type: str,
    is_partial: bool = False,
    reviewed_scope: Optional[dict] = None,
) -> dict:
    """Evaluate market extraction with diagnostics, extended matching, and partial semantics.

    Parameters
    ----------
    gold_markets:
        Markets from the gold YAML.
    draft_markets:
        Markets from the extraction draft YAML.
    market_type:
        ``"product"`` or ``"geographic"``.
    is_partial:
        Use partial-gold semantics when True.
    reviewed_scope:
        From ``_gold_metadata.reviewed_scope``; may contain ``groups`` list.

    Returns a dict with counters, metrics, and diagnostics lists.
    """
    aliases_map: dict[str, list[str]] = {
        m.get("name", ""): list(m.get("aliases") or [])
        for m in gold_markets
        if m.get("aliases")
    }
    reviewed_groups = (
        _build_reviewed_groups(gold_markets, reviewed_scope) if is_partial else frozenset()
    )

    # ---- TP / FN from reviewed gold ----------------------------------------
    tp = 0
    fn = 0
    reviewed_gold: list[dict] = []
    matched_items: list[dict] = []
    false_negatives: list[dict] = []

    for gold_m in gold_markets:
        gold_name = gold_m.get("name", "")
        if not gold_m.get("reviewed"):
            continue
        reviewed_gold.append(gold_m)

        result = _find_matching_market(
            gold_name,
            draft_markets,
            aliases_map,
            gold_m.get("expected_draft_names"),
            gold_m.get("expected_market_ids"),
        )

        if result is not None:
            draft_match, match_type = result
            tp += 1
            matched_items.append({
                "gold_name":  gold_name,
                "draft_name": draft_match.get("name", ""),
                "match_type": match_type,
            })
        else:
            fn += 1
            nearest = _nearest_draft_candidates(gold_name, draft_markets)
            false_negatives.append({
                "gold_name":                 gold_name,
                "aliases":                   list(gold_m.get("aliases") or []),
                "expected_draft_names":      list(gold_m.get("expected_draft_names") or []),
                "expected_market_ids":       list(gold_m.get("expected_market_ids") or []),
                "market_group":              gold_m.get("market_group"),
                "expected_definition_status": gold_m.get("expected_definition_status", ""),
                "nearest_draft_candidates":  nearest,
            })

    # ---- Classify unmatched draft markets ----------------------------------
    fp = 0
    unjudged = 0
    out_of_scope = 0
    false_positives_list: list[dict] = []
    unjudged_list: list[dict] = []

    for draft_m in draft_markets:
        if _matches_any_gold(draft_m, reviewed_gold, aliases_map):
            continue  # already counted as TP

        draft_name = draft_m.get("name", "")
        if not is_partial:
            fp += 1
            false_positives_list.append({"draft_name": draft_name})
        else:
            draft_group = draft_m.get("market_group")
            if (
                draft_group is not None
                and reviewed_groups
                and str(draft_group) in reviewed_groups
            ):
                fp += 1
                false_positives_list.append({"draft_name": draft_name})
            else:
                unjudged += 1
                unjudged_list.append({"draft_name": draft_name})

    # ---- Metrics -----------------------------------------------------------
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall    = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )

    result: dict = {
        "market_type":      market_type,
        "true_positives":   tp,
        "false_positives":  fp,
        "false_negatives":  fn,
        "precision":        round(precision, 3),
        "recall":           round(recall, 3),
        "f1":               round(f1, 3),
        # Diagnostics
        "matched_items":    matched_items,
        "false_negatives_detail": false_negatives,
        "false_positives_detail": false_positives_list,
        "unjudged_items":   unjudged_list,
    }

    if is_partial:
        result.update({
            "evaluated_candidates":    tp + fp,
            "unjudged_candidates":     unjudged,
            "out_of_scope_candidates": out_of_scope,
            "partial_precision":       round(precision, 3),
            "partial_recall":          round(recall, 3),
            "partial_f1":              round(f1, 3),
        })

    return result


# ---------------------------------------------------------------------------
# Promotion safety (unchanged)
# ---------------------------------------------------------------------------

def _check_promotion_safety(gold_yaml: dict, report: dict) -> dict:
    """Check for overpromotion: safe_to_promote markets also in uncertain/hold/manual."""
    cmc = report.get("canonical_merge_candidates", {})
    safe_markets = cmc.get("safe_to_promote", [])
    risky_pool = (
        cmc.get("uncertain_markets", [])
        + cmc.get("hold_pending_source_check", [])
        + cmc.get("manual_review", [])
    )

    risky = 0
    for safe_m in safe_markets:
        sn = _normalize_name(safe_m.get("name", ""))
        if any(_normalize_name(r.get("name", "")) == sn for r in risky_pool):
            risky += 1

    safety_score = 1.0 - (risky / len(safe_markets) if safe_markets else 0)
    return {
        "risky_promotions":    risky,
        "safe_promoted_count": len(safe_markets),
        "safety_score":        round(safety_score, 3),
        "overpromotion_risk":  "high" if risky > 0 else "low",
    }


# ---------------------------------------------------------------------------
# Main evaluation
# ---------------------------------------------------------------------------

def _evaluate_extraction(
    case_id: str,
    gold_yaml: dict,
    draft_yaml: dict,
    report: dict,
    cache_dir: Path = DEFAULT_CACHE_DIR,
) -> dict:
    """Run full extraction evaluation with diagnostics."""
    gold_meta      = gold_yaml.get("_gold_metadata") or {}
    is_partial     = bool(gold_meta.get("partial", False))
    reviewed_scope = gold_meta.get("reviewed_scope") or {}

    gold_pm  = gold_yaml.get("product_markets_considered", [])
    draft_pm = draft_yaml.get("product_markets_considered", [])
    pm_eval  = _evaluate_markets(
        gold_pm, draft_pm, "product",
        is_partial=is_partial, reviewed_scope=reviewed_scope,
    )

    gold_gm  = gold_yaml.get("geographic_markets_considered", [])
    draft_gm = draft_yaml.get("geographic_markets_considered", [])
    gm_eval  = _evaluate_markets(
        gold_gm, draft_gm, "geographic",
        is_partial=is_partial, reviewed_scope=reviewed_scope,
    )

    safety = _check_promotion_safety(gold_yaml, report)

    quote_report  = validate_gold_passages(gold_yaml, cache_dir)
    quote_validity: dict = {
        "total_checked": quote_report.total_checked,
        "passed":        quote_report.passed,
        "failures":      len(quote_report.failures),
        "warnings":      len(quote_report.warnings),
        "failure_details": [
            {
                "market_name":   f.market_name,
                "page":          f.page,
                "reason":        f.reason,
                "quote_snippet": f.quote_snippet[:120],
            }
            for f in quote_report.failures
        ],
    }
    quote_failures = len(quote_report.failures)

    # ---- Compute gold_reviewed_count early (used in gating guard below) ----
    gold_reviewed_count = sum(1 for m in gold_pm + gold_gm if m.get("reviewed"))

    # ---- Gating decision ---------------------------------------------------
    overpromotion = safety["overpromotion_risk"] == "high"
    evaluation_valid = True
    gold_review_status = (
        "no_reviewed_gold_items" if gold_reviewed_count == 0 else "has_reviewed_gold_items"
    )
    gating_reason = ""

    if overpromotion or quote_failures > 0:
        gating = "reject"
        if overpromotion:
            gating_reason = "Overpromotion risk is high."
        else:
            gating_reason = f"Quote validation failed: {quote_failures} failure(s)."

    elif is_partial and gold_reviewed_count == 0:
        # Zero reviewed gold entries in partial mode — evaluation has no signal.
        # Never auto-accept: there is nothing to compare against.
        gating = "insufficient_gold"
        evaluation_valid = False
        gold_review_status = "no_reviewed_gold_items"
        gating_reason = (
            "No reviewed gold items; mark at least one gold entry as reviewed "
            "before accepting."
        )

    elif is_partial:
        def _recall_if_applicable(ev: dict) -> Optional[float]:
            if ev["true_positives"] + ev["false_negatives"] > 0:
                return ev.get("partial_recall", 0.0)
            return None

        def _precision_if_applicable(ev: dict) -> Optional[float]:
            if ev["true_positives"] + ev["false_positives"] > 0:
                return ev.get("partial_precision", 0.0)
            return None

        recall_vals    = [v for v in (_recall_if_applicable(pm_eval),
                                       _recall_if_applicable(gm_eval)) if v is not None]
        precision_vals = [v for v in (_precision_if_applicable(pm_eval),
                                       _precision_if_applicable(gm_eval)) if v is not None]
        avg_recall    = sum(recall_vals)    / len(recall_vals)    if recall_vals    else 1.0
        avg_precision = sum(precision_vals) / len(precision_vals) if precision_vals else 1.0

        if avg_recall < 0.7:
            gating = "needs_review"
            gating_reason = f"Partial recall {avg_recall:.2f} below 0.70 threshold."
        elif avg_precision < 0.8 or safety["safety_score"] < 0.95:
            gating = "accept_with_caveat"
        else:
            gating = "auto_accept"

    else:
        pm_f1  = pm_eval.get("f1", 0.0)
        gm_f1  = gm_eval.get("f1", 0.0)
        avg_f1 = (pm_f1 + gm_f1) / 2

        if avg_f1 < 0.7:
            gating = "needs_review"
            gating_reason = f"Average F1 {avg_f1:.2f} below 0.70 threshold."
        elif safety["safety_score"] < 0.95:
            gating = "accept_with_caveat"
        else:
            gating = "auto_accept"

    if is_partial:
        f1_a = pm_eval.get("partial_f1", 0.0)
        f1_b = gm_eval.get("partial_f1", 0.0)
    else:
        f1_a = pm_eval.get("f1", 0.0)
        f1_b = gm_eval.get("f1", 0.0)
    overall_f1 = round((f1_a + f1_b) / 2, 3)

    return {
        "generated_at":        datetime.now(timezone.utc).isoformat(),
        "case_id":             case_id,
        "gold_partial":        is_partial,
        "gold_reviewed_count": gold_reviewed_count,
        "gold_review_status":  gold_review_status,
        "evaluation_valid":    evaluation_valid,
        "product_markets":     pm_eval,
        "geographic_markets":  gm_eval,
        "promotion_safety":    safety,
        "quote_validity":      quote_validity,
        "overall_f1":          overall_f1,
        "gating_decision":     gating,
        "gating_reason":       gating_reason,
    }


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------

def _format_eval_markdown(eval_result: dict) -> str:
    partial = eval_result.get("gold_partial", False)
    reviewed_count = eval_result.get("gold_reviewed_count", 0)
    evaluation_valid = eval_result.get("evaluation_valid", True)
    gating_reason = eval_result.get("gating_reason", "")

    lines = [
        f"# Extraction Evaluation — {eval_result['case_id']}",
        f"\nGenerated: {eval_result['generated_at']}",
        "\n## Summary",
        f"- Gold partial: {partial}",
        f"- Reviewed gold entries: {reviewed_count}",
        f"- **Gating decision: {eval_result['gating_decision'].upper()}**",
        f"- Overall F1: {eval_result['overall_f1']}",
    ]
    if not evaluation_valid:
        lines.append(
            "- **⚠ Evaluation is not valid for acceptance until at least one gold item is reviewed.**"
        )
    if gating_reason:
        lines.append(f"- Gating reason: {gating_reason}")
    if partial:
        lines.append("- *(Partial gold: precision/recall cover reviewed scope only)*")

    for section_label, key in (("Product Markets", "product_markets"),
                                ("Geographic Markets", "geographic_markets")):
        m = eval_result[key]
        lines.append(f"\n## {section_label}")
        lines.append(
            f"- TP: {m['true_positives']}, "
            f"FP: {m['false_positives']}, "
            f"FN: {m['false_negatives']}"
        )
        if partial:
            lines.append(
                f"- Unjudged: {m.get('unjudged_candidates', 0)}, "
                f"Out-of-scope: {m.get('out_of_scope_candidates', 0)}"
            )
            lines.append(
                f"- Partial Precision: {m.get('partial_precision', m['precision'])}, "
                f"Partial Recall: {m.get('partial_recall', m['recall'])}, "
                f"Partial F1: {m.get('partial_f1', m['f1'])}"
            )
        else:
            lines.append(
                f"- Precision: {m['precision']}, "
                f"Recall: {m['recall']}, F1: {m['f1']}"
            )

        # Matched items
        if m.get("matched_items"):
            lines.append("\n### Matched")
            for item in m["matched_items"]:
                lines.append(
                    f"  - ✓ `{item['gold_name']}` → `{item['draft_name']}` "
                    f"({item['match_type']})"
                )

        # False negatives with nearest candidates
        if m.get("false_negatives_detail"):
            lines.append("\n### False Negatives (gold not found in draft)")
            for fn in m["false_negatives_detail"]:
                lines.append(f"  - ✗ `{fn['gold_name']}`")
                if fn.get("aliases"):
                    lines.append(f"    aliases: {fn['aliases']}")
                if fn.get("expected_draft_names"):
                    lines.append(f"    expected_draft_names: {fn['expected_draft_names']}")
                if fn.get("nearest_draft_candidates"):
                    lines.append("    nearest draft candidates:")
                    for c in fn["nearest_draft_candidates"]:
                        lines.append(
                            f"      - `{c['draft_name']}` "
                            f"(overlap={c['overlap_score']}, id={c['market_id'] or '—'})"
                        )

        # False positives
        if m.get("false_positives_detail"):
            lines.append("\n### False Positives (draft not in gold)")
            for fp in m["false_positives_detail"]:
                lines.append(f"  - `{fp['draft_name']}`")

        # Unjudged
        if m.get("unjudged_items"):
            lines.append(f"\n### Unjudged ({len(m['unjudged_items'])} draft markets outside reviewed scope)")
            for u in m["unjudged_items"]:
                lines.append(f"  - `{u['draft_name']}`")

    safety = eval_result["promotion_safety"]
    lines.extend([
        "\n## Promotion Safety",
        f"- Safe promoted: {safety['safe_promoted_count']}",
        f"- Risky promotions: {safety['risky_promotions']}",
        f"- Promotion safety score: {safety['safety_score']}",
        f"- Overpromotion risk: {safety['overpromotion_risk'].upper()}",
        "\n## Quote Validity",
    ])
    qv = eval_result.get("quote_validity", {})
    lines.extend([
        f"- Checked: {qv.get('total_checked', 0)}",
        f"- Passed: {qv.get('passed', 0)}",
        f"- Failures: {qv.get('failures', 0)}",
        f"- Warnings (cache unavailable): {qv.get('warnings', 0)}",
    ])
    for detail in (qv.get("failure_details") or []):
        lines.append(
            f"  - [{detail['market_name']}] p.{detail['page']}: {detail['reason']}"
            f" — {detail['quote_snippet'][:80]!r}"
        )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate extraction quality by comparing gold YAML against draft"
    )
    parser.add_argument("--case-id",         required=True)
    parser.add_argument("--gold-yaml",       required=True)
    parser.add_argument("--draft-yaml",      required=True)
    parser.add_argument("--report-json",     required=True)
    parser.add_argument("--output-json")
    parser.add_argument("--output-markdown")
    parser.add_argument(
        "--cache-dir", default=str(DEFAULT_CACHE_DIR),
        help=f"PDF page cache directory (default: {DEFAULT_CACHE_DIR})",
    )
    args = parser.parse_args()

    try:
        with open(args.gold_yaml) as fh:
            gold_yaml = yaml.safe_load(fh)
        with open(args.draft_yaml) as fh:
            draft_yaml = yaml.safe_load(fh)
        with open(args.report_json) as fh:
            report = json.load(fh)
    except Exception as exc:
        print(f"Error loading files: {exc}", file=sys.stderr)
        return 1

    eval_result = _evaluate_extraction(
        args.case_id, gold_yaml, draft_yaml, report, Path(args.cache_dir)
    )

    if args.output_json:
        output_path = Path(args.output_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(output_path, "w", encoding="utf-8") as fh:
                json.dump(eval_result, fh, indent=2, ensure_ascii=False)
            print(f"Evaluation saved: {output_path}")
        except Exception as exc:
            print(f"Error writing JSON: {exc}", file=sys.stderr)
            return 1

    if args.output_markdown:
        output_path = Path(args.output_markdown)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(output_path, "w", encoding="utf-8") as fh:
                fh.write(_format_eval_markdown(eval_result))
            print(f"Markdown report saved: {output_path}")
        except Exception as exc:
            print(f"Error writing Markdown: {exc}", file=sys.stderr)
            return 1

    safety = eval_result["promotion_safety"]
    print(f"\n{'='*60}")
    print(f"Evaluation: {args.case_id}")
    print(f"Gating decision:         {eval_result['gating_decision'].upper()}")
    print(f"Overall F1:              {eval_result['overall_f1']}")
    print(f"Promotion safety score:  {safety['safety_score']}")
    print(f"Overpromotion risk:      {safety['overpromotion_risk'].upper()}")
    print(f"Reviewed gold entries:   {eval_result['gold_reviewed_count']}")
    if not eval_result.get("evaluation_valid", True):
        print(
            "WARNING: Evaluation is not valid for acceptance until at least "
            "one gold item is reviewed."
        )
    if eval_result.get("gating_reason"):
        print(f"Gating reason:           {eval_result['gating_reason']}")
    if eval_result.get("gold_partial"):
        pm = eval_result["product_markets"]
        gm = eval_result["geographic_markets"]
        print(
            f"Partial scope — unjudged PM: {pm.get('unjudged_candidates', 0)}, "
            f"GM: {gm.get('unjudged_candidates', 0)}"
        )
    print(f"{'='*60}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
