#!/usr/bin/env python3
"""
ingest_case.py — end-to-end ingestion orchestrator for Meridian.

Orchestrates the full pipeline for a single case:
  1. Fetch / cache source PDFs
  2. Claude extraction → draft YAML
  3. Structural validation of draft (enum values, referential integrity)
  4. Source integrity gate (quote grounding)
  5. Write review report

NOTE on schema validation: Full Pydantic validation (validate_cases.py) applies
only to canonical records in data/cases/ — drafts intentionally omit fields like
`metadata` and `procedure_stage` that are added during canonical promotion.
This script runs a targeted structural check (valid enums, passage references)
instead of full Pydantic validation.

Usage (from repo root):
    python apps/api/scripts/cases/extract/ingest_case.py \\
        --case-id eu_sika_mbcc_2023 \\
        --focus market_definition \\
        --max-cost 1.00
"""

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
import yaml

# ---------------------------------------------------------------------------
# Path setup — must precede all local imports
# ---------------------------------------------------------------------------

_SCRIPTS_DIR = Path(__file__).resolve().parent
_API_DIR = _SCRIPTS_DIR.parent.parent.parent
_REPO_ROOT = _API_DIR.parents[1]

for _p in (str(_API_DIR), str(_SCRIPTS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)
# cross-bucket flat sibling: check_source_integrity lives in integrity/
sys.path.insert(0, str(_SCRIPTS_DIR.parent / "integrity"))

# Load .env from repo root so GOOGLE_API_KEY / ANTHROPIC_API_KEY are available
# when the script is invoked directly (not via a shell that already exports them).
try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv(_REPO_ROOT / ".env", override=False)
except ImportError:
    pass

from app.shared.utils.pdf_extractor import DEFAULT_CACHE_DIR, fetch_and_extract
from check_source_integrity import Level, check_record
from extract_case_from_source import (
    ExtractionReport,
    LLMClient,
    _resolve_canonical_yaml,
    extract_case,
)

_CASES_DIR = _REPO_ROOT / "data" / "cases"
_DRAFTS_DIR = _REPO_ROOT / "data" / "drafts"
_INDEX_DIR = _REPO_ROOT / "data" / "case_index"

# Valid enum values used in draft structural check
_VALID_OUTCOMES = {
    "cleared", "cleared_with_conditions", "cleared_with_remedies",
    "blocked", "abandoned", "referred", "pending",
    "pending_litigation", "under_appeal", "annulled",
    "partially_annulled", "upheld_on_appeal", "unknown",
}
_VALID_DEFINITION_STATUSES = {
    "defined", "left_open", "discussed", "segmented",
    "considered", "not_conclusive", "possible_segmentation",
    "precedent_only", "unknown",
}
_VALID_REVIEW_STATUSES = {"unreviewed", "spot_checked", "lawyer_reviewed"}
_VALID_EXTRACTION_METHODS = {
    "ai_extracted", "manually_added", "imported_metadata", "pdf_extracted",
}


# ---------------------------------------------------------------------------
# Stage 1 — Fetch / cache source PDFs
# ---------------------------------------------------------------------------

def stage_fetch_pdfs(
    source_docs: list[dict],
    cache_dir: Path,
    refresh: bool,
    timeout: int = 90,
) -> list[dict]:
    """Fetch and cache PDFs for all source_documents with a pdf_url."""
    results = []
    with httpx.Client(follow_redirects=True, timeout=timeout) as client:
        for doc in source_docs:
            doc_id = doc.get("doc_id", "")
            pdf_url = doc.get("pdf_url")
            if not doc_id:
                results.append({"doc_id": doc_id, "status": "skip", "note": "missing doc_id"})
                continue
            if not pdf_url:
                results.append({"doc_id": doc_id, "status": "skip", "note": "no pdf_url"})
                continue
            cache_file = cache_dir / f"{doc_id}.json"
            if cache_file.exists() and not refresh:
                import json
                with open(cache_file) as fh:
                    cached = json.load(fh)
                results.append({
                    "doc_id": doc_id, "status": "cached",
                    "pages": cached.get("page_count", "?"),
                    "note": str(cache_file),
                })
                continue
            print(f"  Fetching {doc_id} …", end=" ", flush=True)
            try:
                data = fetch_and_extract(
                    doc_id, pdf_url,
                    cache_dir=cache_dir,
                    force=refresh,
                    client=client,
                )
                print(f"ok ({data['page_count']} pages)")
                results.append({"doc_id": doc_id, "status": "fetched", "pages": data["page_count"]})
            except Exception as exc:
                print(f"FAILED: {exc}")
                results.append({"doc_id": doc_id, "status": "error", "note": str(exc)})
    return results


# ---------------------------------------------------------------------------
# Stage 3 — Structural validation of draft
# ---------------------------------------------------------------------------

_OUTCOME_LANGUAGE_PATTERNS = (
    "does not raise serious doubts",
    "compatible with the internal market",
    "cleared",
    "authorised",
)


def _passage_has_outcome_language(quote: str) -> bool:
    lower = quote.lower()
    return any(pat in lower for pat in _OUTCOME_LANGUAGE_PATTERNS)


def stage_validate_draft(draft_record: dict) -> tuple[bool, list[str], list[str]]:
    """
    Check structural correctness of draft fields without full Pydantic validation.

    Validates: required top-level fields, enum values, passage referential integrity,
    and outcome-passage-to-market linkage (warns, does not block).

    Returns (ok, errors, warnings).  Errors block promotion; warnings require review.
    Full Pydantic validation (including required canonical fields like `metadata`)
    runs only at canonical promotion time via validate_cases.py.
    """
    errors: list[str] = []
    warnings: list[str] = []

    # Required structural fields
    for field in ("case_id", "source_documents"):
        if not draft_record.get(field):
            errors.append(f"Missing required field: '{field}'")

    # Outcome enum
    outcome = draft_record.get("outcome", "unknown")
    if outcome not in _VALID_OUTCOMES:
        errors.append(f"Invalid outcome '{outcome}' — must be one of {sorted(_VALID_OUTCOMES)}")

    # Market definition_status values
    for mlist_key in ("product_markets_considered", "geographic_markets_considered"):
        for m in (draft_record.get(mlist_key) or []):
            status = m.get("definition_status", "")
            if status and status not in _VALID_DEFINITION_STATUSES:
                mid = m.get("market_id", "?")
                errors.append(
                    f"{mlist_key}/{mid}: invalid definition_status '{status}'"
                )

    # Source passages: review_status, extraction_method, referential integrity,
    # and outcome-passage-to-market linkage.
    doc_ids = {d.get("doc_id") for d in (draft_record.get("source_documents") or []) if d.get("doc_id")}
    for sp in (draft_record.get("source_passages") or []):
        pid = sp.get("passage_id", "?")
        rs = sp.get("review_status", "")
        if rs and rs not in _VALID_REVIEW_STATUSES:
            errors.append(f"passage {pid}: invalid review_status '{rs}'")
        em = sp.get("extraction_method", "")
        if em and em not in _VALID_EXTRACTION_METHODS:
            errors.append(f"passage {pid}: invalid extraction_method '{em}'")
        ref = sp.get("source_document_id", "")
        if ref and ref not in doc_ids:
            errors.append(
                f"passage {pid}: source_document_id '{ref}' not found in source_documents"
            )

        # Clearance/outcome passage linked to market: warn (not block).
        # Note: source_role='conclusion' passages MAY link to markets — "Commission concludes
        # the relevant market is X" is a valid market-definition conclusion. Only warn when
        # the quote itself contains clearance/authorization language.
        has_market_link = bool(
            (sp.get("supports_markets") or []) or (sp.get("supports_geographic_markets") or [])
        )
        if has_market_link:
            quote = sp.get("quote_snippet", "") or ""
            if _passage_has_outcome_language(quote):
                warnings.append(
                    f"passage {pid}: quote contains outcome/clearance language but is linked "
                    "to a market entry. Remove supports_markets / supports_geographic_markets "
                    "and keep as an unlinked conclusion passage."
                )

    return len(errors) == 0, errors, warnings


# ---------------------------------------------------------------------------
# Stage 4 — Source integrity gate
# ---------------------------------------------------------------------------

def stage_integrity(
    draft_record: dict,
    cache_dir: Path,
    timeout: int = 20,
) -> tuple[int, int, list]:
    """Run check_record against the draft; return (error_count, warning_count, issues)."""
    with httpx.Client(follow_redirects=True, timeout=timeout) as client:
        issues = check_record(client, draft_record, timeout, cache_dir=cache_dir)
    errors = sum(1 for i in issues if i.level == Level.ERROR)
    warnings = sum(1 for i in issues if i.level == Level.WARNING)
    return errors, warnings, issues


# ---------------------------------------------------------------------------
# Stage 5 — Review report
# ---------------------------------------------------------------------------

def write_review_report(
    report_path: Path,
    *,
    case_id: str,
    focus: str,
    draft_path: Path,
    fetch_results: list[dict],
    extraction_report: ExtractionReport,
    extraction_mode: str = "single-batch",
    schema_ok: bool,
    schema_errors: list[str],
    schema_warnings: list[str] = [],
    integrity_errors: int,
    integrity_warnings: int,
    integrity_issues: list,
    llm_triage_status: Optional[str] = None,
    llm_review_path: Optional[Path] = None,
) -> None:
    from extract_case_from_source import (
        _MARKET_DEF_COVERAGE_MIN_RATIO,
        _MARKET_DEF_COVERAGE_MIN_DOC_PAGES,
    )
    lines: list[str] = []
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines += [
        f"# Ingestion Review: `{case_id}` — `{focus}`",
        "",
        f"Generated: {ts}  ",
        f"Draft: `{draft_path}`",
        "",
    ]

    # Coverage check: warn when market_definition extraction selected a small fraction
    # of the available pages for a long decision.
    cov = extraction_report.selection_coverage
    coverage_warn = (
        focus == "market_definition"
        and cov is not None
        and cov.get("total_non_toc_pages", 0) >= _MARKET_DEF_COVERAGE_MIN_DOC_PAGES
        and cov.get("ratio", 1.0) < _MARKET_DEF_COVERAGE_MIN_RATIO
    )

    blocking = bool(extraction_report.error) or not schema_ok or integrity_errors > 0
    if blocking:
        status = "BLOCKED"
    elif coverage_warn:
        status = "PASS (coverage warning)"
    elif integrity_warnings:
        status = "WARNINGS"
    else:
        status = "PASS"
    lines += [f"**Status: {status}**", ""]

    if coverage_warn:
        sel = cov["selected_pages"]
        tot = cov["total_non_toc_pages"]
        pct = int(round(cov["ratio"] * 100))
        _range_note = (
            f" (restricted to pp{cov['page_range'][0]}-{cov['page_range'][1]})"
            if cov.get("page_range") else ""
        )
        lines += [
            f"⚠ **Coverage warning:** {sel}/{tot} non-TOC pages selected ({pct}%){_range_note}. "
            "Market-definition content may be embedded in therapeutic-area or competitive-assessment "
            "sub-sections not matched by section-path keywords. "
            "Re-run with `--full-market-definition-pass` to widen extraction.",
            "",
        ]

    # Stage 1
    lines += ["## Stage 1 — PDF cache", ""]
    for r in fetch_results:
        icon = "✓" if r["status"] in ("cached", "fetched") else ("–" if r["status"] == "skip" else "✗")
        pages = f" ({r['pages']} pages)" if r.get("pages") else ""
        note = f" — {r['note']}" if r.get("note") and r["status"] not in ("cached", "fetched") else ""
        lines.append(f"- {icon} `{r['doc_id']}`: {r['status']}{pages}{note}")
    lines.append("")

    # Stage 2
    lines += ["## Stage 2 — Extraction", ""]
    lines += [f"Mode: `{extraction_mode}`", ""]
    if extraction_report.error:
        lines += [f"**ERROR:** {extraction_report.error}", ""]
    elif extraction_report.result:
        r = extraction_report.result
        if r.unit_assessments:
            total_findings = sum(len(ua.get("findings", [])) for ua in r.unit_assessments)
            lines += [
                f"- Unit assessments: {len(r.unit_assessments)}",
                f"- Findings: {total_findings}",
                f"- Passages validated: {r.passages_validated}",
                f"- Passages rejected: {r.passages_rejected}",
                "",
            ]
        else:
            lines += [
                f"- Product markets found: {len(r.product_markets)}",
                f"- Geographic markets found: {len(r.geographic_markets)}",
                f"- Theories of harm: {len(r.theories)}",
                f"- Commitments found: {len(r.commitments)}",
                f"- Passages validated: {r.passages_validated}",
                f"- Passages rejected: {r.passages_rejected}",
                "",
            ]
        if extraction_report.section_batches:
            succeeded = sum(1 for b in extraction_report.section_batches if b.result is not None)
            total = len(extraction_report.section_batches)
            lines.append(f"- Section batches: {succeeded}/{total} succeeded")
            lines.append("")
        if r.caveats:
            lines += ["**Caveats:**", ""]
            for c in r.caveats:
                lines.append(f"- {c}")
            lines.append("")
    else:
        lines += ["Skipped (--no-claude or no result)", ""]

    # Stage 3
    lines += ["## Stage 3 — Structural validation", ""]
    if schema_ok and not schema_warnings:
        lines += ["✓ No structural errors or warnings", ""]
    else:
        if not schema_ok:
            lines += [f"✗ {len(schema_errors)} error(s):", ""]
            for msg in schema_errors:
                lines.append(f"- {msg}")
            lines.append("")
        if schema_warnings:
            lines += [f"⚠ {len(schema_warnings)} warning(s):", ""]
            for msg in schema_warnings:
                lines.append(f"- {msg}")
            lines.append("")
    lines += [
        "_Note: Full Pydantic schema validation (validate_cases.py) applies only_",
        "_to canonical records. Run it after promoting draft to data/cases/._",
        "",
    ]

    # Stage 4
    lines += ["## Stage 4 — Source integrity", ""]
    if integrity_errors == 0 and integrity_warnings == 0:
        lines += ["✓ 0 errors, 0 warnings", ""]
    else:
        lines += [f"Errors: {integrity_errors}   Warnings: {integrity_warnings}", ""]
        for issue in integrity_issues:
            if issue.level in (Level.ERROR, Level.WARNING):
                lines.append(f"- [{issue.level.value}] `{issue.scope}`: {issue.message}")
                if issue.url:
                    lines.append(f"  - url: {issue.url}")
        lines.append("")

    # Promotion plan
    draft_rec = extraction_report.draft_record
    if draft_rec:
        try:
            from extract_case_from_source import (
                _build_canonical_merge_candidates,
                _serialize_promotion_plan,
            )
            plan = _serialize_promotion_plan(draft_rec)
            if plan:
                merge = _build_canonical_merge_candidates(plan)
                counts = merge.get("_counts", {})
                lines += ["## Promotion plan", ""]
                for action, count in sorted(counts.items()):
                    if count:
                        lines.append(f"- `{action}`: {count}")
                lines.append("")
                safe = merge.get("safe_to_promote", [])
                if safe:
                    lines += ["**Ready to promote to canonical:**", ""]
                    for m in safe:
                        refs = ", ".join(f"p.{p}" for p in m.get("source_refs", []))
                        lines.append(
                            f"- [{m['market_type']}] **{m['name']}**"
                            f" ({m['definition_status']})"
                            + (f" — {refs}" if refs else "")
                        )
                    lines.append("")
                holds = merge.get("hold_pending_source_check", [])
                if holds:
                    lines += ["**Hold — needs broader source run:**", ""]
                    for m in holds:
                        lines.append(f"- [{m['market_type']}] {m['name']}")
                    lines.append("")
        except Exception:
            pass

    # Reconciliation
    if extraction_report.findings:
        try:
            from extract_case_from_source import _group_reconciliation
            grouped = _group_reconciliation(extraction_report.findings)
            lines += ["## Reconciliation vs existing YAML", ""]
            labels = {
                "matched": "Matched",
                "likely_rename": "Possible rename",
                "candidate_addition": "New from source",
                "out_of_scope": "Unmatched in source",
            }
            for key, label in labels.items():
                items = grouped.get(key, [])
                if items:
                    lines += [f"**{label} ({len(items)}):**", ""]
                    for f in items:
                        name = f.get("existing_name") or f.get("draft_name") or "?"
                        lines.append(f"- {name}")
                    lines.append("")
        except Exception:
            pass

    # Stage 5 — LLM review (optional)
    if llm_triage_status is not None:
        lines += ["## Stage 5 — LLM review (triage)", ""]
        lines.append(f"Triage status: **`{llm_triage_status}`**")
        if llm_review_path:
            lines.append(f"Report: `{llm_review_path}`")
        lines.append("")

    # Next steps
    lines += ["## Next steps", ""]
    if blocking:
        lines.append("1. Fix the errors listed above before proceeding.")
    else:
        step = 1
        if llm_triage_status is not None:
            lines.append(f"{step}. Review LLM triage report at `{llm_review_path or 'see above'}`.")
            step += 1
        lines += [
            f"{step}. Review passages marked `unreviewed` against the source PDF.",
            f"{step + 1}. For passages that are verbatim and correctly located, set `review_status: spot_checked`.",
            f"{step + 2}. Promote markets with `promote_to_canonical` action to canonical YAML.",
            f"{step + 3}. Run `python apps/api/scripts/cases/integrity/validate_cases.py` after canonical promotion.",
            f"{step + 4}. Run `python apps/api/scripts/cases/integrity/check_source_integrity.py --no-cache` as final gate.",
        ]
    lines.append("")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Stage 5a — LLM review (optional)
# ---------------------------------------------------------------------------

def stage_llm_review(
    draft_path: Path,
    report_path: Path,
    cache_dir: Path,
    max_cost: float,
    provider: str = "anthropic",
    gemini_client=None,
) -> tuple[Optional[str], Optional[Path], Optional[Path]]:
    """
    Run the optional LLM review / triage stage after Stage 4 passes.

    Returns (triage_status, json_path, md_path).
    Returns (None, None, None) if the review cannot run (missing API key, etc.).
    Never raises — logs errors and returns None on failure.
    """
    try:
        from review_draft import run_llm_review as _run_llm_review
    except ImportError as exc:
        print(f"  WARN: Could not import review_draft: {exc}")
        return None, None, None

    json_out = draft_path.parent / (draft_path.stem.replace(".draft", "") + ".llm_review.json")
    md_out = draft_path.parent / (draft_path.stem.replace(".draft", "") + ".llm_review.md")

    anthropic_client = None
    if provider == "gemini":
        if gemini_client is None:
            print("  WARN: LLM review skipped — gemini_client not provided")
            return None, None, None
    else:
        try:
            import anthropic as _anthropic
            anthropic_client = _anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        except (ImportError, KeyError) as exc:
            print(f"  WARN: LLM review skipped — {exc}")
            return None, None, None

    print(f"Stage 5a — LLM review ({provider})")
    try:
        triage, validation_errors = _run_llm_review(
            draft_path=draft_path,
            review_md_path=report_path,
            json_out=json_out,
            md_out=md_out,
            cache_dir=cache_dir,
            anthropic_client=anthropic_client,
            gemini_model=gemini_client,
            provider=provider,
            max_cost=max_cost,
            skip_preflight=True,
        )
    except (ValueError, RuntimeError) as exc:
        print(f"  WARN: LLM review failed — {exc}")
        return None, None, None

    marker = {
        "auto_verified_candidate": "✓",
        "needs_light_review": "⚠",
        "needs_legal_review": "⚠",
        "blocked": "✗",
    }.get(triage, "?")
    print(f"  {marker} Triage: {triage}")
    if validation_errors:
        for ve in validation_errors:
            print(f"    WARN: {ve}")
    print(f"  JSON:    {json_out}")
    print(f"  MD:      {md_out}")
    print()
    return triage, json_out, md_out


# ---------------------------------------------------------------------------
# --from-index helpers
# ---------------------------------------------------------------------------

def _load_index_entry(case_id: str) -> Optional[dict]:
    """Find and load a case index YAML from data/case_index/."""
    for entry_path in _INDEX_DIR.rglob(f"{case_id}.yaml"):
        with open(entry_path) as fh:
            return yaml.safe_load(fh)
    return None


def _resolve_pdf_url_from_ec_portal(
    source_url: str, decision_date: str, timeout: int = 30
) -> Optional[str]:
    """
    Resolve the decision PDF URL for EC Phase I (non-opposition) merger decisions.

    Phase I decisions are published in EUR-Lex / cellar.  The CELEX identifier
    follows the pattern 3{YEAR}M{CASE_NUMBER} (e.g. M.11115 decided 2023 →
    32023M11115), and the cellar URL
        http://publications.europa.eu/resource/celex/{CELEX}.ENG.pdf
    content-negotiates to a PDF when requested with Accept: application/pdf.

    Phase II decisions (cleared with conditions, blocked) are NOT in EUR-Lex;
    their PDFs are on ec.europa.eu/competition/mergers/cases1/... — those
    require --pdf-url.  Returns None if resolution fails.
    """
    import re as _re
    m = _re.search(r"M\.(\d+)$", source_url)
    if not m:
        return None
    case_number = m.group(1)
    year = (decision_date or "")[:4]
    if not year.isdigit():
        return None
    celex = f"3{year}M{case_number}"
    cellar_url = f"http://publications.europa.eu/resource/celex/{celex}.ENG.pdf"
    try:
        _pdf_headers = {"Accept": "application/pdf, */*;q=0.5"}
        with httpx.Client(follow_redirects=True, timeout=timeout) as client:
            resp = client.head(cellar_url, headers=_pdf_headers)
            if resp.status_code == 200 and "pdf" in resp.headers.get("content-type", ""):
                return str(resp.url)  # resolved DOC_1 direct URL
    except Exception:
        pass
    return None


def _build_scaffold_from_index(index_entry: dict, pdf_url: str) -> dict:
    """Build a minimal extraction-ready scaffold record from a case index entry."""
    case_id = index_entry["case_id"]
    return {
        "case_id": case_id,
        "case_name": index_entry.get("case_name", ""),
        "jurisdiction": (index_entry.get("jurisdiction") or "unknown").upper(),
        "authority": index_entry.get("authority", ""),
        "sector": index_entry.get("sector", "unknown"),
        "outcome": index_entry.get("outcome", "unknown"),
        "decision_date": index_entry.get("decision_date", ""),
        "case_type": index_entry.get("case_type", "merger"),
        "parties": index_entry.get("parties", []),
        "source_documents": [
            {
                "doc_id": f"{case_id}_decision",
                "title": f"{index_entry.get('case_name', case_id)} — Decision",
                "doc_type": "decision",
                "case_page_url": index_entry.get("source_url", ""),
                "pdf_url": pdf_url,
            }
        ],
        "product_markets_considered": [],
        "geographic_markets_considered": [],
        "theories_of_harm": [],
        "source_passages": [],
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="End-to-end ingestion orchestrator for Meridian cases",
    )
    parser.add_argument("--case-id", required=True, help="Case ID (e.g. eu_sika_mbcc_2023)")
    parser.add_argument(
        "--focus", default="market_definition",
        choices=["market_definition", "theories", "remedies", "case_history", "outcome_metadata",
                 "unit_assessment"],
        help="Extraction focus (default: market_definition)",
    )
    parser.add_argument("--refresh-cache", action="store_true",
                        help="Re-download PDFs even if a cache file exists")
    parser.add_argument("--max-cost", type=float, default=1.00,
                        help="Max estimated API cost in USD (default: 1.00)")
    parser.add_argument("--report-md", default=None,
                        help="Override path for the review report Markdown file")
    parser.add_argument("--batch-by-section", action="store_true",
                        help="Run extraction in section-by-section batch mode (recommended for large cases)")
    parser.add_argument("--no-claude", action="store_true",
                        help="Skip Claude extraction; validate an existing draft if present")
    parser.add_argument("--cache-dir", default=str(DEFAULT_CACHE_DIR),
                        help=f"PDF text cache directory (default: {DEFAULT_CACHE_DIR})")
    parser.add_argument("--llm-review", action="store_true",
                        help=(
                            "Run LLM review / triage stage after Stage 4 passes. "
                            "Writes llm_review.json and llm_review.md to drafts/. "
                            "Requires ANTHROPIC_API_KEY. Does not promote to data/cases/."
                        ))
    parser.add_argument("--full-market-definition-pass", action="store_true",
                        help=(
                            "Merge page-text fallback with section-path selection regardless "
                            "of coverage thresholds. Use for long pharma or multi-section "
                            "decisions where market-definition content is embedded inside "
                            "therapeutic-area or competitive-assessment sub-sections."
                        ))
    parser.add_argument(
        "--page-range",
        default=None,
        metavar="START:END",
        help=(
            "Restrict extraction to pages START through END (inclusive). "
            "Useful for section-group iteration on large decisions "
            "(e.g. --page-range 64:309 to process Section VIII only). "
            "Coverage stats are relative to the restricted range. "
            "Compatible with --batch-by-section."
        ),
    )
    parser.add_argument(
        "--output-suffix",
        default=None,
        metavar="SUFFIX",
        help=(
            "Append SUFFIX to the draft and report file stems "
            "(e.g. --output-suffix section_viii → …section_viii.draft.yaml). "
            "Defaults to pp{START}-{END} when --page-range is used without this flag."
        ),
    )
    parser.add_argument(
        "--from-index",
        action="store_true",
        help=(
            "Ingest a case that has an index entry but no canonical YAML. "
            "Reads from data/case_index/ and builds a minimal scaffold for extraction. "
            "Requires --pdf-url or an auto-resolvable EUR-Lex CELEX URL."
        ),
    )
    parser.add_argument(
        "--pdf-url",
        default=None,
        metavar="URL",
        help=(
            "Decision PDF URL for --from-index ingestion. "
            "If omitted, the URL is derived automatically from the EUR-Lex CELEX pattern."
        ),
    )
    parser.add_argument(
        "--provider",
        default="anthropic",
        choices=["anthropic", "gemini"],
        help="LLM provider to use for extraction (default: anthropic)",
    )
    args = parser.parse_args()

    # Parse and validate --page-range
    page_range: Optional[tuple[int, int]] = None
    if args.page_range:
        parts = args.page_range.split(":")
        if len(parts) != 2 or not all(p.strip().lstrip("-").isdigit() for p in parts):
            print(
                f"ERROR: Invalid --page-range '{args.page_range}' — "
                "expected format START:END (e.g. --page-range 64:309)"
            )
            return 1
        pr_start, pr_end = int(parts[0]), int(parts[1])
        if pr_start < 1:
            print(f"ERROR: --page-range START must be >= 1 (got {pr_start})")
            return 1
        if pr_end < pr_start:
            print(
                f"ERROR: --page-range END ({pr_end}) must be >= START ({pr_start})"
            )
            return 1
        page_range = (pr_start, pr_end)

    # outcome_metadata defaults to pp.1-30 when no --page-range is given.
    if args.focus == "outcome_metadata" and page_range is None:
        page_range = (1, 30)

    # Derive output suffix: explicit --output-suffix takes precedence;
    # fall back to pp{start}-{end} when --page-range is given.
    output_suffix: Optional[str] = args.output_suffix
    if output_suffix is None and page_range is not None:
        output_suffix = f"pp{page_range[0]}-{page_range[1]}"

    cache_dir = Path(args.cache_dir)

    # Resolve canonical YAML (or build scaffold from index)
    scaffold_path: Optional[Path] = None
    if args.from_index:
        index_entry = _load_index_entry(args.case_id)
        if index_entry is None:
            print(f"ERROR: No index entry found for '{args.case_id}' under {_INDEX_DIR}")
            return 1
        pdf_url: Optional[str] = args.pdf_url or index_entry.get("pdf_url")
        if not pdf_url:
            source_url = index_entry.get("source_url", "")
            decision_date = index_entry.get("decision_date", "")
            print(f"  Resolving PDF URL for {args.case_id}…", end=" ", flush=True)
            pdf_url = _resolve_pdf_url_from_ec_portal(source_url, decision_date)
            if pdf_url:
                print("ok")
            else:
                print("failed (Phase II / not in EUR-Lex)")
                print(
                    f"ERROR: Could not auto-resolve PDF URL for '{args.case_id}'.\n"
                    f"  Phase II decisions are not in EUR-Lex — find the PDF at: {source_url}\n"
                    f"  Then re-run with: --from-index --pdf-url <url>"
                )
                return 1
        scaffold = _build_scaffold_from_index(index_entry, pdf_url)
        jur = (index_entry.get("jurisdiction") or "unknown").lower()
        scaffold_dir = _DRAFTS_DIR / jur
        scaffold_dir.mkdir(parents=True, exist_ok=True)
        scaffold_path = scaffold_dir / f"{args.case_id}.scaffold.yaml"
        with open(scaffold_path, "w", encoding="utf-8") as fh:
            yaml.dump(scaffold, fh, allow_unicode=True, default_flow_style=False, sort_keys=False)
        yaml_path = scaffold_path
        print(f"  Index:    {_INDEX_DIR / jur / f'{args.case_id}.yaml'}")
        print(f"  PDF URL:  {pdf_url}")
        print(f"  Scaffold: {scaffold_path}")
        print()
    else:
        yaml_path = _resolve_canonical_yaml(args.case_id, _CASES_DIR)
        if yaml_path is None:
            print(f"ERROR: No canonical YAML found for '{args.case_id}' under {_CASES_DIR}")
            return 1

    with open(yaml_path) as fh:
        record = yaml.safe_load(fh)

    jurisdiction = record.get("jurisdiction", "unknown").lower()
    source_docs: list[dict] = record.get("source_documents") or []

    # Determine output paths (suffix inserted before .draft/.review when set)
    draft_dir = _DRAFTS_DIR / jurisdiction
    draft_dir.mkdir(parents=True, exist_ok=True)
    _stem = f"{args.case_id}.{args.focus}"
    if output_suffix:
        _stem = f"{_stem}.{output_suffix}"
    draft_path = draft_dir / f"{_stem}.draft.yaml"
    report_path = (
        Path(args.report_md)
        if args.report_md
        else draft_dir / f"{_stem}.review.md"
    )

    print(f"Case:       {args.case_id}")
    print(f"YAML:       {yaml_path}")
    print(f"Focus:      {args.focus}")
    if page_range is not None:
        print(f"Page range: pp{page_range[0]}-{page_range[1]}")
    print(f"Draft out:  {draft_path}")
    print(f"Review:     {report_path}")
    print(f"Max cost:   ${args.max_cost:.2f}")
    print()

    # -----------------------------------------------------------------------
    # Stage 1 — PDF cache
    # -----------------------------------------------------------------------
    print("Stage 1 — PDF cache")
    fetch_results = stage_fetch_pdfs(source_docs, cache_dir, args.refresh_cache)
    cached_count = sum(1 for r in fetch_results if r["status"] in ("cached", "fetched"))
    fetch_errors = sum(1 for r in fetch_results if r["status"] == "error")
    print(f"  {cached_count} doc(s) ready, {fetch_errors} fetch error(s)")
    if cached_count == 0:
        print("ERROR: No PDF caches available — cannot proceed with extraction")
        return 1
    print()

    # -----------------------------------------------------------------------
    # Stage 2 — Claude extraction
    # -----------------------------------------------------------------------
    extraction_report = ExtractionReport(case_id=args.case_id, yaml_path=yaml_path)

    # Build LLM client upfront — needed for both Stage 2 and Stage 5a (LLM review).
    provider = args.provider
    _gemini_raw_client = None
    llm_client: Optional[LLMClient] = None
    if provider == "gemini":
        try:
            from google import genai as _genai
            _gemini_raw_client = _genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
            llm_client = LLMClient("gemini", _gemini_raw_client)
        except (ImportError, KeyError) as exc:
            print(f"  WARN: google-genai or GOOGLE_API_KEY not available ({exc})")
    else:
        try:
            import anthropic as _anthropic
            _ac = _anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
            llm_client = LLMClient("anthropic", _ac)
        except (ImportError, KeyError):
            pass  # handled per-stage below

    if args.no_claude:
        print("Stage 2 — Skipped (--no-claude)")
        if not draft_path.exists():
            print(f"  No draft found at {draft_path}; nothing to validate.")
            return 0
        print(f"  Using existing draft: {draft_path}")
    else:
        print(f"Stage 2 — LLM extraction ({provider})")
        if llm_client is None:
            print("  WARN: No LLM client available — falling back to --no-claude mode")

        if llm_client is not None:
            extraction_report = extract_case(
                yaml_path,
                cache_dir=cache_dir,
                output_path=draft_path,
                use_claude=True,
                llm_client=llm_client,
                focus=args.focus,
                max_cost=args.max_cost,
                batch_by_section=args.batch_by_section,
                full_market_def_pass=getattr(args, "full_market_definition_pass", False),
                page_range=page_range,
            )
            if extraction_report.error:
                print(f"  ERROR: {extraction_report.error}")
                write_review_report(
                    report_path, case_id=args.case_id, focus=args.focus,
                    draft_path=draft_path, fetch_results=fetch_results,
                    extraction_report=extraction_report,
                    extraction_mode="batch-by-section" if args.batch_by_section else "single-batch",
                    schema_ok=False, schema_errors=[extraction_report.error],
                    integrity_errors=0, integrity_warnings=0, integrity_issues=[],
                )
                # "No chunks matched" means no market-analysis sections exist in the PDF
                # (typically a 2-3 page simplified-procedure clearance notice).  These are
                # not extraction failures — there is genuinely nothing to extract.  Exit 0
                # so the bulk runner marks them as done and doesn't retry them.
                if "No chunks matched" in extraction_report.error:
                    total_pages = sum(
                        r["pages"] for r in fetch_results
                        if isinstance(r.get("pages"), int)
                    )
                    print(f"\nRESULT: SKIP — simplified procedure / no market-analysis sections ({total_pages} pages)")
                    return 0
                print(f"\nReview:     {report_path}")
                return 1
            r = extraction_report.result
            if r.unit_assessments:
                total_findings = sum(len(ua.get("findings", [])) for ua in r.unit_assessments)
                print(f"  Unit assessments: {len(r.unit_assessments)}")
                print(f"  Findings:         {total_findings}")
            else:
                print(f"  Product markets:  {len(r.product_markets)}")
                print(f"  Geo markets:      {len(r.geographic_markets)}")
            print(f"  Passages:         validated={r.passages_validated} rejected={r.passages_rejected}")
            if extraction_report.section_batches:
                succeeded = sum(1 for b in extraction_report.section_batches if b.result is not None)
                print(f"  Batches:          {succeeded}/{len(extraction_report.section_batches)} succeeded")
            cov = extraction_report.selection_coverage
            if cov:
                pct = int(round(cov["ratio"] * 100))
                warn = (
                    args.focus == "market_definition"
                    and cov["total_non_toc_pages"] >= 30
                    and cov["ratio"] < 0.25
                )
                prefix = "  WARN Coverage:" if warn else "  Coverage:      "
                _range_note = (
                    f" in pp{cov['page_range'][0]}-{cov['page_range'][1]}"
                    if cov.get("page_range") else ""
                )
                _doc_note = ""
                if cov.get("page_range") and cov.get("document_total_non_toc_pages"):
                    _doc_note = f" (doc total: {cov['document_total_non_toc_pages']})"
                print(
                    f"{prefix}  {cov['selected_pages']}/{cov['total_non_toc_pages']} pages"
                    f"{_range_note} ({pct}%){_doc_note}"
                    + (" — re-run with --full-market-definition-pass" if warn else "")
                )
            print(f"  Draft written:    {draft_path}")
        else:
            # Fell back from no-API-key; try to use existing draft
            if not draft_path.exists():
                print(f"  No draft found at {draft_path}; cannot validate without Claude.")
                return 1
            print(f"  Using existing draft: {draft_path}")
    print()

    # Load the draft for subsequent stages
    draft_record = yaml.safe_load(draft_path.read_text(encoding="utf-8"))

    # Patch protected index fields that the LLM may have set to 'unknown'.
    # Index values (scraped from EC register) are authoritative for these.
    if args.from_index and index_entry is not None:
        patched = False
        index_date = index_entry.get("decision_date", "")
        if index_date and (not draft_record.get("decision_date") or draft_record.get("decision_date") == "unknown"):
            draft_record["decision_date"] = index_date
            patched = True
        index_outcome = index_entry.get("outcome", "")
        if index_outcome and index_outcome != "unknown" and draft_record.get("outcome") in ("unknown", "", None):
            draft_record["outcome"] = index_outcome
            patched = True
        if patched:
            with open(draft_path, "w", encoding="utf-8") as _fh:
                yaml.dump(draft_record, _fh, allow_unicode=True, default_flow_style=False, sort_keys=False)
            print("  Patched draft: restored decision_date/outcome from index")

    # -----------------------------------------------------------------------
    # Stage 3 — Structural validation
    # -----------------------------------------------------------------------
    print("Stage 3 — Structural validation")
    schema_ok, schema_errors_list, schema_warnings_list = stage_validate_draft(draft_record)
    if schema_ok and not schema_warnings_list:
        print("  ✓ Valid")
    else:
        for msg in schema_errors_list:
            print(f"  ✗ {msg}")
        for msg in schema_warnings_list:
            print(f"  ⚠ WARN: {msg}")
    print()

    # -----------------------------------------------------------------------
    # Stage 4 — Source integrity
    # -----------------------------------------------------------------------
    print("Stage 4 — Source integrity")
    int_errors, int_warnings, int_issues = stage_integrity(draft_record, cache_dir)
    marker = "✓" if int_errors == 0 and int_warnings == 0 else ("⚠" if int_errors == 0 else "✗")
    print(f"  {marker} {int_errors} error(s), {int_warnings} warning(s)")
    for issue in int_issues:
        if issue.level in (Level.ERROR, Level.WARNING):
            print(f"    [{issue.level.value}] {issue.scope}: {issue.message[:100]}")
    print()

    # -----------------------------------------------------------------------
    # Stage 5a — LLM review (optional, only when Stage 4 passed)
    # -----------------------------------------------------------------------
    llm_triage: Optional[str] = None
    llm_json_path: Optional[Path] = None
    llm_md_path: Optional[Path] = None

    stage4_passed = not (bool(extraction_report.error) or not schema_ok or int_errors > 0)
    if getattr(args, "llm_review", False) and stage4_passed:
        llm_triage, llm_json_path, llm_md_path = stage_llm_review(
            draft_path=draft_path,
            report_path=report_path,
            cache_dir=cache_dir,
            max_cost=args.max_cost,
            provider=args.provider,
            gemini_client=_gemini_raw_client,
        )

    # -----------------------------------------------------------------------
    # Stage 5 — Review report
    # -----------------------------------------------------------------------
    print("Stage 5 — Review report")
    write_review_report(
        report_path,
        case_id=args.case_id,
        focus=args.focus,
        draft_path=draft_path,
        fetch_results=fetch_results,
        extraction_report=extraction_report,
        extraction_mode="batch-by-section" if args.batch_by_section else "single-batch",
        schema_ok=schema_ok,
        schema_errors=schema_errors_list,
        schema_warnings=schema_warnings_list,
        integrity_errors=int_errors,
        integrity_warnings=int_warnings,
        integrity_issues=int_issues,
        llm_triage_status=llm_triage,
        llm_review_path=llm_json_path,
    )
    print(f"  Written: {report_path}")
    print()

    # Final result
    failed = bool(extraction_report.error) or not schema_ok or int_errors > 0
    if failed:
        print("RESULT: BLOCKED — fix errors above before promoting to canonical")
        return 1
    _cov = extraction_report.selection_coverage
    _cov_warn = (
        args.focus == "market_definition"
        and _cov is not None
        and _cov.get("total_non_toc_pages", 0) >= 30
        and _cov.get("ratio", 1.0) < 0.25
    )
    if _cov_warn:
        _range_suffix = (
            f" in pp{_cov['page_range'][0]}-{_cov['page_range'][1]}"
            if _cov.get("page_range") else ""
        )
        print(
            f"RESULT: PASS (coverage warning) — "
            f"{_cov['selected_pages']}/{_cov['total_non_toc_pages']} pages selected"
            f"{_range_suffix}; re-run with --full-market-definition-pass before promoting"
        )
    elif int_warnings:
        print(f"RESULT: PASS with {int_warnings} warning(s) — review before promoting")
    else:
        print("RESULT: PASS — draft ready for human review")
    return 0


if __name__ == "__main__":
    sys.exit(main())
