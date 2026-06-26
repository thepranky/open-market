#!/usr/bin/env python3
"""
calibrate_dual_extraction.py — the calibration gate for dual extraction (ROADMAP 5.9).

Dual extraction skips human review on fields where two independent extractions
*agree*. That is only safe if agreement actually predicts correctness. This script
measures it, on the gold eval fixtures, before the workflow is trusted at scale:

  - Agreement precision = (agreed fields that match gold) / (agreed fields).
    The number that justifies skipping review. Target >= 0.98.
  - Conflict recall = (fields >=1 draft got wrong that were raised as a conflict) /
    (all fields >=1 draft got wrong). Quantifies the blind spot: a field both drafts
    get wrong the *same* way agrees, is skipped, and is invisible to the human.

Both metrics are measured against the SAME alignment the real workflow uses
(`align_drafts` from compare_extractions), so the gate measures the agreement
signal as actually produced, not a parallel re-implementation.

The score functions are pure and run with no API key (the unit tests drive them
directly). Producing the two drafts is the only step that calls a model; pass
`--reuse-drafts` to score drafts already on disk and skip extraction entirely.

Usage (from apps/api, .venv active):
    # Score gold fixtures, extracting two drafts per case (needs both API keys)
    .venv/bin/python scripts/cases/extract/calibrate_dual_extraction.py --golds

    # Same-model fallback, to confirm heterogeneous models recall more conflicts
    .venv/bin/python scripts/cases/extract/calibrate_dual_extraction.py --golds --dual-same-model

    # Re-score drafts already produced (no model calls)
    .venv/bin/python scripts/cases/extract/calibrate_dual_extraction.py --golds --reuse-drafts

Exit code: 0 if overall agreement precision >= threshold, 1 otherwise.
"""

import argparse
import sys
from pathlib import Path
from typing import Optional

import yaml

_SCRIPTS_DIR = Path(__file__).resolve().parent
_API_DIR = _SCRIPTS_DIR.parent.parent.parent
_REPO_ROOT = _API_DIR.parents[1]

for _p in (str(_API_DIR), str(_SCRIPTS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from compare_extractions import (  # noqa: E402
    _MARKET_LISTS,
    _MARKET_SCALAR_FIELDS,
    _RECORD_SCALAR_FIELDS,
    _index_markets_by_name,
    _normalize_for_similarity,
    align_drafts,
)

# Gold fixtures store the human-reviewed value of a market-scalar field under an
# `expected_<field>` key (e.g. `expected_definition_status`), distinct from the
# draft's own `<field>`. Map draft field name -> gold key when reading gold.
_GOLD_FIELD_ALIAS = {"definition_status": "expected_definition_status"}

# Sentinel: this draft did not align any of its markets to the gold market, so the
# field has no value at all — distinct from a found market whose field is empty.
_MISSING = object()


# ---------------------------------------------------------------------------
# Field tables (gold-keyed, so Draft A and Draft B are directly comparable)
# ---------------------------------------------------------------------------

def _gold_field_table(gold: dict, is_partial: bool) -> dict:
    """{field_path -> gold value} over the scoreable gold fields.

    Only fields the gold actually carries a value for are included — those are the
    propositions with a known-correct answer. For partial golds, only `reviewed`
    markets are scored (an unreviewed market has no binding gold value).
    """
    table: dict[str, object] = {}
    for list_key, label in _MARKET_LISTS:
        for m in gold.get(list_key) or []:
            if is_partial and not m.get("reviewed"):
                continue
            name = m.get("name", "")
            if not name:
                continue
            prefix = f"{label}/{name}"
            table[f"{prefix}/name"] = name
            for fld in _MARKET_SCALAR_FIELDS:
                v = str(m.get(_GOLD_FIELD_ALIAS.get(fld, fld)) or "").strip()
                if v:
                    table[f"{prefix}/{fld}"] = v
    for fld in _RECORD_SCALAR_FIELDS:
        v = str(gold.get(fld) or "").strip()
        if v:
            table[fld] = v
    return table


def _draft_field_table(draft: dict, gold: dict, focus: Optional[str]) -> dict:
    """{field_path -> draft value} keyed by GOLD market names.

    Aligns `draft` to `gold` with the same machinery the conflict report uses
    (`align_drafts`, gold as baseline) so a field path is shared across the two
    draft tables and the gold table. A gold market the draft never aligned to is
    simply absent (`_MISSING` at score time); a market it aligned to but left the
    field empty is present with value None.
    """
    align = align_drafts(draft, gold, focus=focus)
    index = _index_markets_by_name(draft)
    table: dict[str, object] = {}
    for pair in align["pairs"]:
        market = index[pair["list_key"]].get(_normalize_for_similarity(pair["name_a"]), {})
        prefix = f"{pair['label']}/{pair['name_b']}"
        table[f"{prefix}/name"] = pair["name_a"]
        for fld in _MARKET_SCALAR_FIELDS:
            table[f"{prefix}/{fld}"] = str(market.get(fld) or "").strip() or None
    for fld in _RECORD_SCALAR_FIELDS:
        v = str(draft.get(fld) or "").strip()
        if v:
            table[fld] = v
    return table


def _field_eq(path: str, x: object, y: object) -> bool:
    """Field-aware equality. Names match fuzzily (the report's name matcher); scalar
    and record fields match exactly modulo case/whitespace (the deterministic layer)."""
    if x is _MISSING or y is _MISSING:
        return False
    if x is None and y is None:
        return True
    if x is None or y is None:
        return False
    sx, sy = str(x).strip(), str(y).strip()
    if path.endswith("/name"):
        return _normalize_for_similarity(sx) == _normalize_for_similarity(sy)
    return sx.lower() == sy.lower()


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def score_case(
    draft_a: dict,
    draft_b: dict,
    gold: dict,
    *,
    focus: Optional[str] = None,
    is_partial: bool = False,
) -> dict:
    """Score one case: per scoreable gold field, classify agreement vs correctness.

    For each gold field with value `g`, with draft values `a`, `b`:
      - agreed      = both drafts found the market and a == b (skips human review)
      - error       = at least one of a, b != g (something is wrong here)
      - raised      = at least one draft has the market AND they did not agree, i.e.
                      the conflict report would surface it (value mismatch, or one
                      draft missing the market). Both-missing and both-wrong-the-
                      same-way are NOT raised — the blind spots.

    Returns counts plus the two lists that matter for a human reading the gate:
    `bad_agreements` (agreed yet wrong → the precision failures) and `blind_spots`
    (wrong yet never raised → the recall failures).
    """
    gold_t = _gold_field_table(gold, is_partial)
    a_t = _draft_field_table(draft_a, gold, focus)
    b_t = _draft_field_table(draft_b, gold, focus)

    agreed = agreed_correct = error = error_raised = 0
    bad_agreements: list[dict] = []
    blind_spots: list[dict] = []

    for key, g in gold_t.items():
        a = a_t.get(key, _MISSING)
        b = b_t.get(key, _MISSING)
        a_present = a is not _MISSING
        b_present = b is not _MISSING

        is_agreed = a_present and b_present and _field_eq(key, a, b)
        a_correct = a_present and _field_eq(key, a, g)
        b_correct = b_present and _field_eq(key, b, g)

        if is_agreed:
            agreed += 1
            if a_correct:
                agreed_correct += 1
            else:
                bad_agreements.append({"field": key, "agreed_value": a, "gold": g})

        if not (a_correct and b_correct):
            error += 1
            if (a_present or b_present) and not is_agreed:
                error_raised += 1
            else:
                blind_spots.append({
                    "field": key,
                    "draft_a": a if a_present else None,
                    "draft_b": b if b_present else None,
                    "gold": g,
                })

    return {
        "agreed": agreed,
        "agreed_correct": agreed_correct,
        "error": error,
        "error_raised": error_raised,
        "bad_agreements": bad_agreements,
        "blind_spots": blind_spots,
    }


def _ratio(num: int, denom: int) -> Optional[float]:
    return (num / denom) if denom else None


def _fmt_ratio(num: int, denom: int) -> str:
    r = _ratio(num, denom)
    return f"{r:.3f} ({num}/{denom})" if r is not None else "n/a (0)"


# ---------------------------------------------------------------------------
# Draft production (the only step that calls a model)
# ---------------------------------------------------------------------------

def _find_case_record(case_id: str) -> Optional[Path]:
    """Locate the canonical case record (the extraction input skeleton)."""
    for path in (_REPO_ROOT / "data" / "cases").rglob(f"{case_id}.yaml"):
        return path
    return None


def _extract_pair(
    *,
    case_id: str,
    cache_dir: Path,
    focus: Optional[str],
    same_model: bool,
    max_cost: float,
    primary_provider: str,
    out_a: Path,
    out_b: Path,
) -> bool:
    """Run two independent extractions of one case into `out_a` / `out_b`.

    Mirrors `ingest_case.stage_dual_extract`'s provider/temperature choices so
    calibration measures the same A/B pairing the real pipeline produces. Returns
    True on success, False if either client is unavailable or extraction errors.
    """
    from extract_case_from_source import extract_case
    from ingest_case import (
        _DUAL_SAME_MODEL_TEMPERATURE,
        _build_llm_client,
    )

    yaml_path = _find_case_record(case_id)
    if yaml_path is None:
        print(f"  WARN: no canonical record for {case_id}; skipping")
        return False

    secondary_provider = (
        primary_provider if same_model
        else ("gemini" if primary_provider == "anthropic" else "anthropic")
    )
    client_a = _build_llm_client(primary_provider)
    client_b = _build_llm_client(
        secondary_provider,
        temperature=_DUAL_SAME_MODEL_TEMPERATURE if same_model else None,
    )
    if client_a is None or client_b is None:
        print("  WARN: a provider client is unavailable; skipping")
        return False

    for client, out in ((client_a, out_a), (client_b, out_b)):
        report = extract_case(
            yaml_path, cache_dir=cache_dir, output_path=out,
            use_claude=True, llm_client=client, focus=focus, max_cost=max_cost,
        )
        if report.error:
            print(f"  WARN: extraction failed — {report.error}")
            return False
    return True


# ---------------------------------------------------------------------------
# Gold run
# ---------------------------------------------------------------------------

def _resolve(base: Path, rel: str) -> Path:
    p = Path(rel)
    return p if p.is_absolute() else base / p


def run_golds(
    *,
    config_path: Path,
    out_dir: Path,
    same_model: bool,
    reuse_drafts: bool,
    max_cost: float,
    primary_provider: str,
) -> dict:
    """Score every gold in the benchmark config; return aggregate metrics."""
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    base_dir = _REPO_ROOT
    focus = config.get("focus")
    tag = "same" if same_model else "het"
    out_dir.mkdir(parents=True, exist_ok=True)

    tot_agreed = tot_agreed_correct = tot_error = tot_error_raised = 0
    rows: list[dict] = []

    for bench in config.get("benchmarks", []):
        case_id = bench["case_id"]
        gold = yaml.safe_load(_resolve(base_dir, bench["gold_yaml"]).read_text(encoding="utf-8"))
        is_partial = bool((gold.get("_gold_metadata") or {}).get("partial"))

        out_a = out_dir / f"{case_id}.{tag}.draft_a.yaml"
        out_b = out_dir / f"{case_id}.{tag}.draft_b.yaml"

        if not (reuse_drafts and out_a.exists() and out_b.exists()):
            cache_dir = _resolve(base_dir, bench["cache_dir"])
            print(f"Extracting {case_id} ({tag}) ...")
            if not _extract_pair(
                case_id=case_id, cache_dir=cache_dir, focus=focus,
                same_model=same_model, max_cost=max_cost,
                primary_provider=primary_provider, out_a=out_a, out_b=out_b,
            ):
                rows.append({"case_id": case_id, "skipped": True})
                continue

        draft_a = yaml.safe_load(out_a.read_text(encoding="utf-8"))
        draft_b = yaml.safe_load(out_b.read_text(encoding="utf-8"))
        s = score_case(draft_a, draft_b, gold, focus=focus, is_partial=is_partial)

        tot_agreed += s["agreed"]
        tot_agreed_correct += s["agreed_correct"]
        tot_error += s["error"]
        tot_error_raised += s["error_raised"]
        rows.append({"case_id": case_id, "score": s})

    return {
        "tag": tag,
        "rows": rows,
        "agreement_precision": _ratio(tot_agreed_correct, tot_agreed),
        "conflict_recall": _ratio(tot_error_raised, tot_error),
        "totals": {
            "agreed": tot_agreed, "agreed_correct": tot_agreed_correct,
            "error": tot_error, "error_raised": tot_error_raised,
        },
    }


def _print_report(result: dict) -> None:
    print()
    print(f"Calibration gate — models: {result['tag']}")
    print("-" * 64)
    for row in result["rows"]:
        if row.get("skipped"):
            print(f"  {row['case_id']:<40} SKIPPED (no drafts)")
            continue
        s = row["score"]
        print(
            f"  {row['case_id']:<40} "
            f"precision {_fmt_ratio(s['agreed_correct'], s['agreed'])}, "
            f"recall {_fmt_ratio(s['error_raised'], s['error'])}"
        )
        for bad in s["bad_agreements"]:
            print(f"      ! agreed-but-wrong  {bad['field']}: {bad['agreed_value']!r} vs gold {bad['gold']!r}")
        for blind in s["blind_spots"]:
            print(f"      ? blind-spot        {blind['field']}: a={blind['draft_a']!r} b={blind['draft_b']!r} gold {blind['gold']!r}")
    t = result["totals"]
    print("-" * 64)
    print(f"  Agreement precision: {_fmt_ratio(t['agreed_correct'], t['agreed'])}")
    print(f"  Conflict recall:     {_fmt_ratio(t['error_raised'], t['error'])}")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Calibration gate for dual extraction")
    parser.add_argument("--golds", action="store_true",
                        help="Run over the gold benchmark fixtures (required mode)")
    parser.add_argument("--config", default=None,
                        help="Benchmark config (default: data/evals/benchmark.market_definition.ci.yaml)")
    parser.add_argument("--dual-same-model", action="store_true",
                        help="Produce Draft B on the same provider (temperature-varied) — the fallback pairing")
    parser.add_argument("--reuse-drafts", action="store_true",
                        help="Score drafts already in --out-dir; do not call any model")
    parser.add_argument("--out-dir", default=None,
                        help="Where draft_a/draft_b live (default: data/evals/results/calibration)")
    parser.add_argument("--primary-provider", default="anthropic", choices=("anthropic", "gemini"),
                        help="Provider for Draft A (default: anthropic)")
    parser.add_argument("--max-cost", type=float, default=3.0, help="Per-extraction cost cap")
    parser.add_argument("--threshold", type=float, default=0.98,
                        help="Minimum agreement precision to pass (default: 0.98)")
    args = parser.parse_args(argv)

    if not args.golds:
        parser.error("--golds is required (it is the only mode)")

    config_path = (
        Path(args.config) if args.config
        else _REPO_ROOT / "data" / "evals" / "benchmark.market_definition.ci.yaml"
    )
    out_dir = (
        Path(args.out_dir) if args.out_dir
        else _REPO_ROOT / "data" / "evals" / "results" / "calibration"
    )

    result = run_golds(
        config_path=config_path, out_dir=out_dir,
        same_model=args.dual_same_model, reuse_drafts=args.reuse_drafts,
        max_cost=args.max_cost, primary_provider=args.primary_provider,
    )
    _print_report(result)

    precision = result["agreement_precision"]
    if precision is None:
        print("\nNo agreed fields scored — cannot evaluate the gate.")
        return 1
    if precision < args.threshold:
        print(f"\nFAIL: agreement precision {precision:.3f} < threshold {args.threshold:.3f}")
        return 1
    print(f"\nPASS: agreement precision {precision:.3f} >= threshold {args.threshold:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
