#!/usr/bin/env python3
"""
run_eval_benchmark.py — Run quote validation + extraction evaluation across benchmark cases.

Relative paths in the benchmark config are resolved against a **base directory** that
defaults to the repo root (the directory containing both ``data/`` and ``apps/``
subdirectories, found by walking up from the config file).  Override with ``--base-dir``.

Usage::

    cd apps/api
    .venv/bin/python scripts/cases/evals/run_eval_benchmark.py \\
        --config ../../data/evals/benchmark.market_definition.yaml

    # Override summary output paths
    .venv/bin/python scripts/cases/evals/run_eval_benchmark.py \\
        --config ../../data/evals/benchmark.market_definition.yaml \\
        --output-json /tmp/summary.json \\
        --output-markdown /tmp/summary.md

Exit codes:
    0 — all cases passed
    1 — one or more cases failed (or configuration error)
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

_API_DIR = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_API_DIR))
sys.path.insert(0, str(_API_DIR / "scripts" / "cases"))

from evaluate_extraction import _evaluate_extraction, _format_eval_markdown
from validate_gold_quotes import load_gold_yaml


# ---------------------------------------------------------------------------
# Pass / fail criteria
# ---------------------------------------------------------------------------

_FAIL_GATING: frozenset[str] = frozenset({
    "reject", "needs_review", "insufficient_gold", "error",
})


def _case_passes(result: dict) -> bool:
    """Return True if a case result meets all benchmark pass criteria.

    Pass requires ALL of:
    - No quote validation failures (failures == 0).
    - At least one reviewed gold entry (gold_reviewed_count >= 1).
    - Evaluation marked valid (evaluation_valid == True).
    - Gating decision is not in the fail set (not reject / needs_review /
      insufficient_gold / error).
    - Overpromotion risk is not "high".

    Unjudged candidates are informational only and never cause a case to fail.
    """
    qv = result.get("quote_validity", {})
    if qv.get("failures", 0) > 0:
        return False
    if result.get("gold_reviewed_count", 0) == 0:
        return False
    if not result.get("evaluation_valid", True):
        return False
    if result.get("gating_decision", "") in _FAIL_GATING:
        return False
    ps = result.get("promotion_safety", {})
    if ps.get("overpromotion_risk", "") == "high":
        return False
    return True


def _case_summary_row(case_id: str, result: dict, passed: bool) -> dict:
    """Extract per-case summary fields from an evaluation result dict."""
    qv = result.get("quote_validity", {})
    pm = result.get("product_markets", {})
    gm = result.get("geographic_markets", {})
    ps = result.get("promotion_safety", {})
    return {
        "case_id":                case_id,
        "quote_checked":          qv.get("total_checked", 0),
        "quote_failures":         qv.get("failures", 0),
        "quote_warnings":         qv.get("warnings", 0),
        "reviewed_gold_count":    result.get("gold_reviewed_count", 0),
        "product_f1":             pm.get("f1", 0.0),
        "geographic_f1":          gm.get("f1", 0.0),
        "overall_f1":             result.get("overall_f1", 0.0),
        "promotion_safety_score": ps.get("safety_score", 0.0),
        "overpromotion_risk":     ps.get("overpromotion_risk", ""),
        "gating_decision":        result.get("gating_decision", ""),
        "passed":                 passed,
    }


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def _format_summary_markdown(
    rows: list[dict],
    overall_passed: bool,
    generated_at: str,
    focus: str = "market_definition",
) -> str:
    """Render the aggregate benchmark summary as a Markdown document."""
    status = "PASS" if overall_passed else "FAIL"
    passed_count = sum(1 for r in rows if r["passed"])
    total_count = len(rows)

    lines = [
        f"# Benchmark summary: {focus}",
        "",
        f"Generated: {generated_at}  ",
        f"Result: **{status}** ({passed_count}/{total_count} cases passed)",
        "",
        "## Per-case results",
        "",
        (
            "| Case | Reviewed | Quote✓ | Quote✗ | Warn |"
            " PM F1 | GM F1 | Overall F1 | Safety | Risk | Gating | Pass |"
        ),
        (
            "|------|----------|--------|--------|------|"
            "-------|-------|------------|--------|------|--------|------|"
        ),
    ]
    for r in rows:
        p = "✓" if r["passed"] else "✗"
        checked = r["quote_checked"]
        failures = r["quote_failures"]
        ok = checked - failures
        lines.append(
            f"| {r['case_id']}"
            f" | {r['reviewed_gold_count']}"
            f" | {ok}"
            f" | {failures}"
            f" | {r['quote_warnings']}"
            f" | {r['product_f1']:.3f}"
            f" | {r['geographic_f1']:.3f}"
            f" | {r['overall_f1']:.3f}"
            f" | {r['promotion_safety_score']:.2f}"
            f" | {r['overpromotion_risk']}"
            f" | {r['gating_decision']}"
            f" | {p} |"
        )

    lines.append("")
    if not overall_passed:
        lines.append(
            "> ⚠ Benchmark failed. "
            "Review per-case eval outputs in the configured output directory for details."
        )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Error sentinel
# ---------------------------------------------------------------------------

def _error_result(case_id: str, error: str) -> dict:
    """Return a minimal failed result dict for a case that could not be evaluated."""
    return {
        "case_id":            case_id,
        "error":              error,
        "generated_at":       datetime.now(timezone.utc).isoformat(),
        "gold_partial":       True,
        "gold_reviewed_count": 0,
        "gold_review_status": "error",
        "evaluation_valid":   False,
        "overall_f1":         0.0,
        "gating_decision":    "error",
        "gating_reason":      error,
        "quote_validity": {
            "total_checked": 0, "passed": 0,
            "failures": 0, "warnings": 0, "failure_details": [],
        },
        "product_markets": {
            "market_type": "product",
            "true_positives": 0, "false_positives": 0, "false_negatives": 0,
            "precision": 0.0, "recall": 0.0, "f1": 0.0,
            "matched_items": [], "false_negatives_detail": [],
            "false_positives_detail": [], "unjudged_items": [],
        },
        "geographic_markets": {
            "market_type": "geographic",
            "true_positives": 0, "false_positives": 0, "false_negatives": 0,
            "precision": 0.0, "recall": 0.0, "f1": 0.0,
            "matched_items": [], "false_negatives_detail": [],
            "false_positives_detail": [], "unjudged_items": [],
        },
        "promotion_safety": {
            "risky_promotions": 0, "safe_promoted_count": 0,
            "safety_score": 0.0, "overpromotion_risk": "unknown",
        },
    }


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def _resolve(p: str, base: Path) -> Path:
    """Resolve a config path against base; absolute paths pass through unchanged."""
    candidate = Path(p)
    if candidate.is_absolute():
        return candidate
    return (base / candidate).resolve()


def _find_repo_root(config_path: Path) -> Path:
    """Walk up from config_path to find the repo root.

    The repo root is identified as the first ancestor directory containing
    both a ``data/`` and an ``apps/`` subdirectory.  Falls back to the
    grandparent of the config file if no such directory is found.
    """
    candidate = config_path.resolve().parent
    while candidate.parent != candidate:
        if (candidate / "data").is_dir() and (candidate / "apps").is_dir():
            return candidate
        candidate = candidate.parent
    # Fallback: grandparent (data/evals/benchmark.yaml → data/ → repo root)
    return config_path.resolve().parent.parent


# ---------------------------------------------------------------------------
# Per-case runner
# ---------------------------------------------------------------------------

def _run_one_case(
    case_cfg: dict,
    base_dir: Path,
    cache_dir: Path,
    output_dir: Path,
) -> tuple[dict, bool]:
    """Evaluate a single benchmark case. Returns ``(result_dict, passed)``."""
    case_id = case_cfg.get("case_id", "unknown")

    gold_path   = _resolve(case_cfg["gold_yaml"],   base_dir)
    draft_path  = _resolve(case_cfg["draft_yaml"],  base_dir)
    report_path = _resolve(case_cfg["report_json"], base_dir)

    # Per-case cache_dir overrides the global default (used by fixture configs)
    effective_cache_dir = (
        _resolve(case_cfg["cache_dir"], base_dir)
        if "cache_dir" in case_cfg
        else cache_dir
    )

    missing = [str(p) for p in (gold_path, draft_path, report_path) if not p.exists()]
    if missing:
        err = f"Missing files: {', '.join(missing)}"
        print(f"  [{case_id}] ERROR: {err}", file=sys.stderr)
        return _error_result(case_id, err), False

    try:
        gold, load_err = load_gold_yaml(gold_path)
        if load_err:
            raise ValueError(load_err)
        with open(draft_path) as fh:
            draft = yaml.safe_load(fh)
        with open(report_path) as fh:
            report = json.load(fh)
    except Exception as exc:
        err = f"Load error: {exc}"
        print(f"  [{case_id}] ERROR: {err}", file=sys.stderr)
        return _error_result(case_id, err), False

    try:
        result = _evaluate_extraction(case_id, gold, draft, report, effective_cache_dir)
    except Exception as exc:
        err = f"Evaluation error: {exc}"
        print(f"  [{case_id}] ERROR: {err}", file=sys.stderr)
        return _error_result(case_id, err), False

    passed = _case_passes(result)

    # Write per-case output files (never mutate inputs)
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{case_id}.market_definition"

    json_out = output_dir / f"{stem}.eval.json"
    json_out.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")

    md_out = output_dir / f"{stem}.eval.md"
    try:
        md_out.write_text(_format_eval_markdown(result), encoding="utf-8")
    except Exception:
        md_out.write_text(f"# {case_id}\n\nFormatting error.\n", encoding="utf-8")

    status   = "PASS" if passed else "FAIL"
    gating   = result.get("gating_decision", "?")
    f1       = result.get("overall_f1", 0.0)
    reviewed = result.get("gold_reviewed_count", 0)
    qf       = result.get("quote_validity", {}).get("failures", 0)
    print(
        f"  [{case_id}] {status}"
        f"  gating={gating}"
        f"  f1={f1:.3f}"
        f"  reviewed={reviewed}"
        f"  quote_failures={qf}"
    )
    return result, passed


# ---------------------------------------------------------------------------
# Top-level runner
# ---------------------------------------------------------------------------

def run_benchmark(
    config_path: Path,
    base_dir: Optional[Path] = None,
    output_json_path: Optional[Path] = None,
    output_md_path: Optional[Path] = None,
) -> int:
    """Run all benchmark cases and write summary outputs.

    Returns 0 if all cases pass, 1 otherwise.
    ``base_dir`` overrides the auto-detected repo root (useful for tests).
    """
    config_path = Path(config_path).resolve()

    try:
        with open(config_path) as fh:
            config = yaml.safe_load(fh)
    except Exception as exc:
        print(f"ERROR: Cannot load config {config_path}: {exc}", file=sys.stderr)
        return 1

    if base_dir is None:
        base_dir = _find_repo_root(config_path)

    focus      = config.get("focus", "market_definition")
    cache_dir  = _resolve(config.get("cache_dir",  "data/source_text"), base_dir)
    output_dir = _resolve(config.get("output_dir", "data/evals/results"), base_dir)

    benchmarks = config.get("benchmarks") or []
    if not benchmarks:
        print("ERROR: No benchmark cases configured.", file=sys.stderr)
        return 1

    generated_at  = datetime.now(timezone.utc).isoformat()
    rows: list[dict] = []
    overall_passed = True

    print(f"Running {len(benchmarks)} benchmark case(s) [{focus}]…")
    for cfg in benchmarks:
        case_id = cfg.get("case_id", "unknown")
        print(f"\n→ {case_id}")
        result, passed = _run_one_case(cfg, base_dir, cache_dir, output_dir)
        if not passed:
            overall_passed = False
        rows.append(_case_summary_row(case_id, result, passed))

    # Aggregate summary
    summary = {
        "focus":          focus,
        "generated_at":   generated_at,
        "overall_passed": overall_passed,
        "cases_total":    len(rows),
        "cases_passed":   sum(1 for r in rows if r["passed"]),
        "cases_failed":   sum(1 for r in rows if not r["passed"]),
        "cases":          rows,
    }

    if output_json_path is None:
        output_json_path = output_dir / f"benchmark.{focus}.summary.json"
    if output_md_path is None:
        output_md_path = output_dir / f"benchmark.{focus}.summary.md"

    output_dir.mkdir(parents=True, exist_ok=True)
    output_json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    output_md_path.write_text(
        _format_summary_markdown(rows, overall_passed, generated_at, focus),
        encoding="utf-8",
    )

    verdict = "PASS" if overall_passed else "FAIL"
    print(
        f"\nBenchmark {verdict}: "
        f"{summary['cases_passed']}/{summary['cases_total']} cases passed."
    )
    print(f"Summary JSON:     {output_json_path}")
    print(f"Summary Markdown: {output_md_path}")

    return 0 if overall_passed else 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run market-definition benchmark: quote validation + extraction evaluation."
    )
    parser.add_argument(
        "--config", required=True,
        help=(
            "Path to the benchmark config YAML "
            "(e.g. data/evals/benchmark.market_definition.yaml)"
        ),
    )
    parser.add_argument(
        "--output-json", dest="output_json", default=None,
        help="Override path for the aggregate summary JSON file.",
    )
    parser.add_argument(
        "--output-markdown", dest="output_markdown", default=None,
        help="Override path for the aggregate summary Markdown file.",
    )
    parser.add_argument(
        "--base-dir", dest="base_dir", default=None,
        help=(
            "Repo root for resolving relative paths in the config "
            "(auto-detected from config location by default)."
        ),
    )
    args = parser.parse_args()

    base_dir    = Path(args.base_dir)   if args.base_dir        else None
    output_json = Path(args.output_json) if args.output_json    else None
    output_md   = Path(args.output_markdown) if args.output_markdown else None

    return run_benchmark(
        Path(args.config),
        base_dir=base_dir,
        output_json_path=output_json,
        output_md_path=output_md,
    )


if __name__ == "__main__":
    sys.exit(main())
