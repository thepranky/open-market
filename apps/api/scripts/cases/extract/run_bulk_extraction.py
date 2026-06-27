"""
run_bulk_extraction.py — resumable batch extraction for Phase I EC cases.

Reads all case index YAMLs with pdf_url set, skips Phase II and already-promoted
cases, and runs each through the full ingest_case.py pipeline (no LLM review).
Progress is tracked in a state file so the run can be interrupted and resumed.

Usage:
    python3 run_bulk_extraction.py [options]

Options:
    --jurisdiction eu       Index subfolder to process (default: eu)
    --provider gemini       LLM provider for extraction (default: gemini)
    --run-id NAME           Name for this run's state file (default: auto timestamp)
    --resume                Resume the most recent incomplete run
    --resume-id NAME        Resume a specific run by ID
    --dry-run               Print queue without running extraction
    --limit N               Stop after N cases (useful for testing)
    --delay N               Seconds between cases (default: 10)
    --force                 Re-run cases already marked done in state file
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[5]
_SCRIPT = Path(__file__).parent / "ingest_case.py"
_INDEX_DIR = _REPO_ROOT / "data" / "case_index"
_CASES_DIR = _REPO_ROOT / "data" / "cases"
_RUNS_DIR = _REPO_ROOT / "data" / "batch_runs"

_SKIP_OUTCOMES = {"cleared_with_conditions", "blocked", "annulled"}


def _load_state(run_id: str) -> dict:
    path = _RUNS_DIR / f"{run_id}.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {"run_id": run_id, "created_at": _now(), "cases": {}}


def _save_state(state: dict, run_id: str) -> None:
    _RUNS_DIR.mkdir(parents=True, exist_ok=True)
    path = _RUNS_DIR / f"{run_id}.json"
    with open(path, "w") as f:
        json.dump(state, f, indent=2)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _latest_run_id(jurisdiction: str) -> str | None:
    if not _RUNS_DIR.exists():
        return None
    runs = sorted(_RUNS_DIR.glob(f"{jurisdiction}_*.json"), reverse=True)
    return runs[0].stem if runs else None


def _build_queue(jurisdiction: str) -> list[dict]:
    """Return ordered list of cases eligible for extraction."""
    index_dir = _INDEX_DIR / jurisdiction
    cases_dir = _CASES_DIR / jurisdiction

    queue = []
    for path in sorted(index_dir.glob("*.yaml")):
        with open(path) as f:
            entry = yaml.safe_load(f)

        case_id = entry.get("case_id", path.stem)
        outcome = entry.get("outcome", "")
        pdf_url = entry.get("pdf_url")
        extraction_status = entry.get("extraction_status")
        pdf_language = entry.get("pdf_language") or "unknown"

        # Backfilled non-substantive entries are excluded before language routing.
        if extraction_status == "not_applicable":
            queue.append({
                "case_id": case_id,
                "skip_reason": "not_applicable",
                "pdf_language": pdf_language,
                "extraction_status": extraction_status,
            })
            continue

        # Skip Phase II — need manual review, already handled separately
        if outcome in _SKIP_OUTCOMES:
            queue.append({
                "case_id": case_id,
                "skip_reason": f"phase2 ({outcome})",
                "pdf_language": pdf_language,
                "extraction_status": extraction_status,
            })
            continue

        # Skip if no pdf_url (resolver failed or too old a decision)
        if not pdf_url:
            queue.append({
                "case_id": case_id,
                "skip_reason": "no_pdf_url",
                "pdf_language": pdf_language,
                "extraction_status": extraction_status,
            })
            continue

        # Already promoted to canonical
        if (cases_dir / f"{case_id}.yaml").exists():
            queue.append({
                "case_id": case_id,
                "skip_reason": "already_canonical",
                "pdf_language": pdf_language,
                "extraction_status": extraction_status,
            })
            continue

        queue.append({
            "case_id": case_id,
            "skip_reason": None,
            "pdf_language": pdf_language,
            "extraction_status": extraction_status,
        })

    return queue


def _language_counts(cases: list[dict]) -> Counter:
    return Counter(c.get("pdf_language") or "unknown" for c in cases)


def _format_counts(counts: Counter) -> str:
    return ", ".join(f"{lang}={count}" for lang, count in sorted(counts.items())) or "none"


def _run_case(case_id: str, jurisdiction: str, provider: str) -> tuple[str, str]:
    """
    Run ingest_case.py for one case. Returns (status, summary).
    status: 'done' | 'skipped' | 'failed'
    'skipped' = simplified-procedure notice with no market-analysis content.
    """
    cmd = [
        sys.executable, str(_SCRIPT),
        "--case-id", case_id,
        "--from-index",
        "--provider", provider,
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, cwd=_REPO_ROOT, timeout=900,
        )
    except subprocess.TimeoutExpired:
        return "failed", "TIMEOUT — case exceeded 15 min limit (stalled PDF fetch or API call)"

    output = result.stdout + result.stderr

    # Extract summary line — prefer RESULT: > Product markets: > ERROR:
    summary = ""
    for line in output.splitlines():
        if "RESULT:" in line:
            summary = line.strip()
            break
        if "Product markets:" in line and not summary:
            summary = line.strip()
        elif "ERROR:" in line and not summary:
            summary = line.strip()

    if result.returncode == 0:
        if "RESULT: SKIP" in summary:
            return "skipped", summary
        return "done", summary
    else:
        # Grab last meaningful error line
        for line in reversed(output.splitlines()):
            if line.strip() and not line.startswith(" "):
                summary = line.strip()[:120]
                break
        return "failed", summary


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Resumable bulk extraction for Phase I cases")
    parser.add_argument("--jurisdiction", default="eu")
    parser.add_argument("--provider", default="gemini")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--resume", action="store_true", help="Resume most recent run")
    parser.add_argument("--resume-id", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--delay", type=int, default=10)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    # Resolve run ID
    if args.resume_id:
        run_id = args.resume_id
    elif args.resume:
        run_id = _latest_run_id(args.jurisdiction)
        if not run_id:
            print("No previous run found — starting fresh.")
            run_id = f"{args.jurisdiction}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    elif args.run_id:
        run_id = args.run_id
    else:
        run_id = f"{args.jurisdiction}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    print(f"Run ID:   {run_id}")
    print(f"Provider: {args.provider}")
    print()

    state = _load_state(run_id)
    queue = _build_queue(args.jurisdiction)

    # Count queue stats
    total = len(queue)
    skippable = sum(1 for c in queue if c["skip_reason"])
    runnable = [c for c in queue if not c["skip_reason"]]

    print(f"Index entries:    {total}")
    print(f"  Skippable:      {skippable}  (not applicable / phase2 / no pdf / already canonical)")
    print(f"  To extract:     {len(runnable)}")
    print(f"  Languages:      {_format_counts(_language_counts(runnable))}")
    _terminal_statuses = ("done", "skipped")
    already_done = sum(
        1 for c in runnable
        if state["cases"].get(c["case_id"], {}).get("status") in _terminal_statuses and not args.force
    )
    pending = len(runnable) - already_done
    print(f"  Already done:   {already_done}")
    print(f"  Pending:        {pending}")
    print()

    if args.dry_run:
        pending_cases = [
            c for c in runnable
            if state["cases"].get(c["case_id"], {}).get("status") not in _terminal_statuses
            or args.force
        ]
        print(f"Pending languages: {_format_counts(_language_counts(pending_cases))}")
        print("DRY RUN — first 20 pending cases:")
        shown = 0
        for c in runnable:
            if state["cases"].get(c["case_id"], {}).get("status") in _terminal_statuses and not args.force:
                continue
            print(f"  {c['case_id']}  [{c.get('pdf_language') or 'unknown'}]")
            shown += 1
            if shown >= 20:
                print("  ...")
                break
        return

    done_count = sum(
        1 for c in runnable
        if state["cases"].get(c["case_id"], {}).get("status") == "done" and not args.force
    )
    skip_count = sum(
        1 for c in runnable
        if state["cases"].get(c["case_id"], {}).get("status") == "skipped" and not args.force
    )
    fail_count = sum(
        1 for c in runnable
        if state["cases"].get(c["case_id"], {}).get("status") == "failed"
    )
    processed = 0

    for c in runnable:
        case_id = c["case_id"]
        prev = state["cases"].get(case_id, {})

        if prev.get("status") in _terminal_statuses and not args.force:
            continue

        if args.limit and processed >= args.limit:
            print(f"\nReached --limit {args.limit}, stopping.")
            break

        processed += 1
        pct = (done_count + skip_count) / len(runnable) * 100 if runnable else 0
        print(f"[{done_count+skip_count+fail_count+1}/{len(runnable)}  {pct:.0f}%]  {case_id}")

        status, summary = _run_case(case_id, args.jurisdiction, args.provider)

        state["cases"][case_id] = {
            "status": status,
            "summary": summary,
            "timestamp": _now(),
        }
        state["last_updated"] = _now()
        _save_state(state, run_id)

        if status == "done":
            done_count += 1
            print(f"  ✓  {summary}")
        elif status == "skipped":
            skip_count += 1
            print(f"  —  {summary}")
        else:
            fail_count += 1
            print(f"  ✗  {summary}")

        if processed < pending:
            time.sleep(args.delay)

    # Final summary
    print()
    print(f"Run complete: {done_count} extracted, {skip_count} skipped (simplified), {fail_count} failed")
    print(f"State saved:  {_RUNS_DIR / run_id}.json")

    # Print failed cases for easy re-run
    failures = [
        cid for cid, v in state["cases"].items() if v.get("status") == "failed"
    ]
    if failures:
        print(f"\nFailed cases ({len(failures)}):")
        for cid in failures[:20]:
            print(f"  {cid}: {state['cases'][cid].get('summary','')[:80]}")
        if len(failures) > 20:
            print(f"  ... and {len(failures)-20} more (see state file)")
        print(f"\nTo retry failures: python3 {Path(__file__).name} --resume-id {run_id} --force")


if __name__ == "__main__":
    main()
