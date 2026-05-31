#!/usr/bin/env python3
"""
review_draft.py — LLM review / promotion triage for CompMap draft YAML records.

Sits after all deterministic checks (Stages 1-4) and before human promotion.
Produces:
  - data/drafts/{jurisdiction}/{case_id}.{focus}.llm_review.json
  - data/drafts/{jurisdiction}/{case_id}.{focus}.llm_review.md

NEVER writes to data/cases/. NEVER marks anything as lawyer_reviewed.
NEVER substitutes for human or legal review.

Usage (from repo root):
    python apps/api/scripts/review_draft.py \\
        --case-id eu_sika_dry_mix_2019 \\
        --focus market_definition \\
        [--max-cost 0.50] \\
        [--cache-dir data/source_text]
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------

_SCRIPTS_DIR = Path(__file__).resolve().parent
_API_DIR = _SCRIPTS_DIR.parent
_REPO_ROOT = _API_DIR.parents[1]

for _p in (str(_API_DIR), str(_SCRIPTS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_DRAFTS_DIR = _REPO_ROOT / "data" / "drafts"
_DEFAULT_CACHE_DIR = _REPO_ROOT / "data" / "source_text"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MODEL = "claude-sonnet-4-6"

# claude-sonnet-4-6 pricing per token
_INPUT_COST_PER_TOKEN = 3.0 / 1_000_000
_OUTPUT_COST_PER_TOKEN = 15.0 / 1_000_000
_MAX_OUTPUT_TOKENS = 4096

# How many chars of page text to include around each quote
_CONTEXT_WINDOW_CHARS = 400

# Hard cap: send at most this many passages to the reviewer
_MAX_PASSAGES_TO_REVIEWER = 30

_VALID_TRIAGE_STATUSES = frozenset({
    "auto_verified_candidate",
    "needs_light_review",
    "needs_legal_review",
    "blocked",
})

# ---------------------------------------------------------------------------
# Structured output tool schema
# ---------------------------------------------------------------------------

_PASSAGE_REVIEW_ITEM = {
    "type": "object",
    "required": ["passage_id", "support_verdict", "role_verdict"],
    "properties": {
        "passage_id": {"type": "string"},
        "linked_to": {
            "type": "array",
            "items": {"type": "string"},
            "description": "market_ids or theory names this passage is linked to in the draft",
        },
        "source_role_in_draft": {
            "type": "string",
            "description": "source_role as stated in the draft, or 'not_set' if absent",
        },
        "support_verdict": {
            "type": "string",
            "enum": ["strong", "partial", "weak", "none", "cannot_assess"],
            "description": (
                "strong: quote clearly supports the linked proposition; "
                "partial: supports partially or with caveats; "
                "weak: tangential; "
                "none: does not support; "
                "cannot_assess: insufficient context"
            ),
        },
        "role_verdict": {
            "type": "string",
            "enum": ["correct", "likely_wrong", "uncertain"],
            "description": "Your independent assessment of who is speaking in the quote",
        },
        "note": {
            "type": "string",
            "description": "Brief explanation, especially for non-strong or wrong-role findings",
        },
    },
}

_MARKET_REVIEW_ITEM = {
    "type": "object",
    "required": ["market_id", "definition_status_verdict", "scope_verdict", "passage_support_verdict"],
    "properties": {
        "market_id": {"type": "string"},
        "market_name": {"type": "string"},
        "market_type": {"type": "string", "enum": ["product", "geographic"]},
        "definition_status_verdict": {
            "type": "string",
            "enum": ["likely_correct", "likely_wrong", "uncertain"],
        },
        "definition_status_note": {"type": "string"},
        "scope_verdict": {
            "type": "string",
            "enum": ["appropriate", "too_broad", "too_narrow", "unsupported", "uncertain"],
        },
        "scope_note": {"type": "string"},
        "passage_support_verdict": {
            "type": "string",
            "enum": ["well_supported", "weakly_supported", "unsupported"],
        },
        "outcome_passage_misuse": {
            "type": "boolean",
            "description": (
                "True if ANY of the market's supporting passages are outcome/clearance "
                "conclusions (does not raise serious doubts, compatible with the internal "
                "market, cleared, authorised) rather than substantive market definition "
                "analysis. Applies to both supports_markets and supports_geographic_markets."
            ),
        },
        "outcome_passage_misuse_note": {"type": "string"},
    },
}

_REVIEW_TOOL_SCHEMA = {
    "name": "record_llm_review",
    "description": (
        "Record the structured LLM critic review of a CompMap draft YAML. "
        "This is a critic's assessment to assist human review — not a verification or approval."
    ),
    "input_schema": {
        "type": "object",
        "required": [
            "triage_status",
            "triage_rationale",
            "passage_reviews",
            "market_reviews",
            "theory_reviews",
            "gap_findings",
            "role_misuse_flags",
            "definition_status_flags",
        ],
        "properties": {
            "triage_status": {
                "type": "string",
                "enum": sorted(_VALID_TRIAGE_STATUSES),
                "description": (
                    "auto_verified_candidate: all passages strong, all statuses correct, no gaps. "
                    "needs_light_review: minor issues a domain-knowledgeable non-lawyer can check. "
                    "needs_legal_review: status misclassification, role misuse, or gaps needing legal judgment. "
                    "blocked: passages contradict propositions, fabricated claims, or fundamental problems."
                ),
            },
            "triage_rationale": {
                "type": "string",
                "description": "One or two sentences explaining the triage decision.",
            },
            "passage_reviews": {
                "type": "array",
                "items": _PASSAGE_REVIEW_ITEM,
                "description": "One entry per source_passage in the draft. Return [] if no passages.",
            },
            "market_reviews": {
                "type": "array",
                "items": _MARKET_REVIEW_ITEM,
                "description": (
                    "One entry per product or geographic market in the draft. "
                    "Return [] if no markets."
                ),
            },
            "theory_reviews": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["theory_name", "linkage_verdict"],
                    "properties": {
                        "theory_id": {"type": "string"},
                        "theory_name": {"type": "string"},
                        "linkage_verdict": {
                            "type": "string",
                            "enum": ["correct", "missing_passages", "improperly_linked", "cannot_assess"],
                        },
                        "note": {"type": "string"},
                    },
                },
                "description": "One entry per theory_of_harm. Return [] if no theories.",
            },
            "gap_findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["gap_type", "description", "confidence"],
                    "properties": {
                        "gap_type": {
                            "type": "string",
                            "enum": [
                                "missing_geographic_market",
                                "missing_product_market",
                                "missing_theory",
                                "missing_market_section",
                            ],
                        },
                        "description": {"type": "string"},
                        "source_evidence": {
                            "type": ["string", "null"],
                            "description": (
                                "A passage_id from this draft that supports the gap claim. "
                                "MUST be null if no supporting passage exists. "
                                "MUST reference an existing passage_id if non-null."
                            ),
                        },
                        "confidence": {
                            "type": "string",
                            "enum": ["source_backed", "speculative"],
                        },
                    },
                },
                "description": "Return [] if no gaps found.",
            },
            "role_misuse_flags": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["passage_id", "role_in_draft", "role_detected", "note"],
                    "properties": {
                        "passage_id": {"type": "string"},
                        "role_in_draft": {"type": "string"},
                        "role_detected": {"type": "string"},
                        "note": {"type": "string"},
                    },
                },
                "description": "Return [] if no role misuse detected.",
            },
            "definition_status_flags": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["market_id", "current_status", "suggested_status", "note"],
                    "properties": {
                        "market_id": {"type": "string"},
                        "current_status": {"type": "string"},
                        "suggested_status": {"type": "string"},
                        "note": {"type": "string"},
                    },
                },
                "description": "Return [] if all definition_status values appear correct.",
            },
        },
    },
}

_REVIEW_SYSTEM_PROMPT = """\
You are a competition law critic reviewing a DRAFT case record for the CompMap \
source-first legal research pipeline.

Your job is to find problems. Be skeptical. Do not confirm that everything looks correct \
unless you have explicitly checked every passage.

CRITICAL RULES:
1. Only cite passage_ids that exist in this draft. Never invent passage references.
2. Gap findings with no supporting passage_id MUST be marked confidence: speculative.
3. Only evaluate what the supplied quotes show. Do not use prior knowledge of this \
specific case to infer conclusions not present in the text.
4. Evaluate source_role INDEPENDENTLY — read the quote text and judge who is speaking. \
Do not trust the source_role label in the draft (it may be absent or wrong).
5. NEVER suggest anything should be marked as lawyer_reviewed.
6. Outcome / clearance passage rule (GENERAL): passages containing "does not raise \
serious doubts", "compatible with the internal market", "no competition concerns", \
"cleared", or "authorised" are outcome conclusions about the merger result. \
They are NEVER market definition support. \
If ANY outcome passage is linked to supports_markets or supports_geographic_markets \
for a given market entry, set outcome_passage_misuse = true — even if other \
non-outcome passages also support the market. \
Market definition and merger outcome are related but distinct: a clearance conclusion \
does not prove a product or geographic market was defined or considered.
7. definition_status semantics: \
"defined" requires the authority to have definitively concluded on market scope; \
"left_open" means the authority explicitly said it was unnecessary to conclude; \
"discussed" means the authority examined it without a final ruling. \
If the quote says "the Commission considers it unnecessary to conclude" or similar, \
that market should be "left_open", not "defined".
8. Geographic market check: if passages mention country-level or regional competitive \
assessments, check whether geographic market entries are present in the draft. \
Flag any apparent omissions.
9. EU Commission language patterns: \
"the Commission is of the view that X should be considered as a separate product market" \
is the Commission's conclusion (supports definition_status: defined). \
"the majority of respondents confirmed" is market investigation evidence (source_role: \
market_investigation). \
"in line with previous Commission decisions" cites precedent (source_role: precedent or \
commission_assessment depending on context). \
"does not raise serious doubts" is the clearance outcome (source_role: conclusion), \
not a market definition finding.

TRIAGE CALIBRATION:
- auto_verified_candidate: all passages are strong authority findings, all \
definition_status values are unambiguously supported, no gaps, no misuse.
- needs_light_review: minor issues (weak support, scope uncertainty, possible gaps) \
that a domain-knowledgeable non-lawyer can check against the source.
- needs_legal_review: definition_status misclassification, source_role misuse, \
missing key market segments, or theory gaps requiring legal judgment.
- blocked: passages contradict the propositions they support; claims look fabricated; \
fundamental structural problems.

Return empty arrays (never null) for sections with no findings."""


# ---------------------------------------------------------------------------
# Draft discovery
# ---------------------------------------------------------------------------

def _find_draft_path(case_id: str, focus: str, drafts_dir: Path) -> Optional[Path]:
    """Search jurisdiction subdirectories for the draft YAML."""
    fname = f"{case_id}.{focus}.draft.yaml"
    for p in drafts_dir.rglob(fname):
        return p
    return None


# ---------------------------------------------------------------------------
# Preflight check
# ---------------------------------------------------------------------------

def _check_preflight(
    draft_path: Path,
    review_md_path: Path,
) -> Optional[str]:
    """
    Return an error string if preflight fails, None if clear to proceed.

    Rules:
    - draft_path must exist
    - review_md_path must exist (deterministic stages were run)
    - review_md_path must show Status: PASS (Stage 4 passed)
    """
    if not draft_path.exists():
        return f"Draft not found: {draft_path}"
    if not review_md_path.exists():
        return (
            f"Review report not found: {review_md_path}\n"
            "Run ingest_case.py (Stages 1-4) before running LLM review."
        )
    content = review_md_path.read_text(encoding="utf-8")
    if "**Status: PASS**" not in content:
        status_line = next(
            (line for line in content.splitlines() if "**Status:" in line), "unknown"
        )
        return (
            f"Deterministic checks did not pass ({status_line.strip()}). "
            "Fix all errors before running LLM review."
        )
    return None


# ---------------------------------------------------------------------------
# Context window extraction
# ---------------------------------------------------------------------------

def _get_page_context(
    quote: str,
    doc_id: str,
    page_str: Optional[str],
    cache_dir: Path,
) -> Optional[str]:
    """Return page text surrounding the quote (±CONTEXT_WINDOW_CHARS chars), or None."""
    if not page_str:
        return None
    try:
        page_num = int(page_str)
    except (TypeError, ValueError):
        return None

    cache_file = cache_dir / f"{doc_id}.json"
    if not cache_file.exists():
        return None

    try:
        cache = json.loads(cache_file.read_text(encoding="utf-8"))
    except Exception:
        return None

    for page in cache.get("pages", []):
        if page.get("page_number") == page_num:
            text = page.get("text", "")
            if not text:
                return None
            needle = quote[:60].lower().strip()
            pos = text.lower().find(needle)
            if pos >= 0:
                start = max(0, pos - _CONTEXT_WINDOW_CHARS)
                end = min(len(text), pos + len(quote) + _CONTEXT_WINDOW_CHARS)
                return text[start:end]
            # Quote not at exact position — return page start as fallback
            return text[: _CONTEXT_WINDOW_CHARS * 4]
    return None


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

def _format_markets(
    markets: list[dict],
    market_type: str,
    passages_by_market: dict[str, list[str]],
) -> str:
    if not markets:
        return f"  (no {market_type} markets in draft)\n"
    lines = []
    for m in markets:
        mid = m.get("market_id", "?")
        name = m.get("name", "?")
        status = m.get("definition_status", "?")
        importance = m.get("market_importance", "")
        pids = passages_by_market.get(mid, [])
        pids_str = ", ".join(pids) if pids else "none"
        lines.append(
            f"  {mid}: {name!r} [{status}]"
            + (f" ({importance})" if importance else "")
            + f" — passages: {pids_str}"
        )
        notes = m.get("notes", "")
        if notes:
            # Truncate long notes
            notes_short = notes[:200] + ("…" if len(notes) > 200 else "")
            lines.append(f"    notes: {notes_short}")
    return "\n".join(lines) + "\n"


def _format_theories(theories: list[dict]) -> str:
    if not theories:
        return "  (no theories of harm in draft)\n"
    lines = []
    for th in theories:
        tid = th.get("theory_id") or th.get("market_id") or "?"
        name = th.get("name", "?")
        outcome = th.get("theory_outcome", "")
        passages = th.get("source_passages") or th.get("passages") or []
        pids = [p.get("passage_id", p) if isinstance(p, dict) else str(p) for p in passages]
        pids_str = ", ".join(pids) if pids else "none"
        lines.append(f"  {tid}: {name!r} [{outcome}] — passages: {pids_str}")
    return "\n".join(lines) + "\n"


def _build_review_prompt(draft: dict, cache_dir: Path) -> str:
    """Build the user-turn prompt for the LLM review call."""
    case_id = draft.get("case_id", "?")
    case_name = draft.get("case_name", "?")
    authority = draft.get("authority", "?")
    jurisdiction = draft.get("jurisdiction", "?")
    decision_date = draft.get("decision_date", "?")
    focus = "market_definition"  # primary focus for now

    passages_raw: list[dict] = draft.get("source_passages") or []
    product_markets: list[dict] = draft.get("product_markets_considered") or []
    geo_markets: list[dict] = draft.get("geographic_markets_considered") or []
    theories: list[dict] = draft.get("theories_of_harm") or []

    # Build reverse map: market_id → [passage_id, ...]
    passages_by_market: dict[str, list[str]] = {}
    for sp in passages_raw:
        pid = sp.get("passage_id", "?")
        for mid in (sp.get("supports_markets") or []):
            passages_by_market.setdefault(mid, []).append(pid)
        for mid in (sp.get("supports_geographic_markets") or []):
            passages_by_market.setdefault(mid, []).append(pid)

    # Build set of all passage_ids for validation
    all_passage_ids = {sp.get("passage_id", "") for sp in passages_raw}

    # Cap passages sent to reviewer
    passages_to_review = passages_raw[:_MAX_PASSAGES_TO_REVIEWER]
    capped = len(passages_raw) > _MAX_PASSAGES_TO_REVIEWER

    lines: list[str] = [
        f"CASE: {case_id}",
        f"CASE NAME: {case_name}",
        f"AUTHORITY: {authority} ({jurisdiction})",
        f"DECISION DATE: {decision_date}",
        f"FOCUS: {focus}",
        f"TOTAL SOURCE PASSAGES: {len(passages_raw)}"
        + (f" (reviewer receives first {_MAX_PASSAGES_TO_REVIEWER})" if capped else ""),
        "",
        "PRODUCT MARKETS IN DRAFT:",
        _format_markets(product_markets, "product", passages_by_market),
        "GEOGRAPHIC MARKETS IN DRAFT:",
        _format_markets(geo_markets, "geographic", passages_by_market),
        "THEORIES OF HARM IN DRAFT:",
        _format_theories(theories),
        "=" * 60,
        "SOURCE PASSAGES (with page context where available):",
        "",
    ]

    for sp in passages_to_review:
        pid = sp.get("passage_id", "?")
        doc_id = sp.get("source_document_id", "")
        page = sp.get("page")
        quote = sp.get("quote_snippet", "")
        role = sp.get("source_role", "not_set")
        supports_m = sp.get("supports_markets") or []
        supports_g = sp.get("supports_geographic_markets") or []
        supports_t = sp.get("supports_theories") or []
        all_supports = (
            [f"product:{m}" for m in supports_m]
            + [f"geo:{g}" for g in supports_g]
            + [f"theory:{t}" for t in supports_t]
        )

        lines.append(f"--- {pid} ---")
        lines.append(f"  doc: {doc_id}   page: {page}   source_role_in_draft: {role}")
        lines.append(f"  supports: {', '.join(all_supports) or 'none'}")
        lines.append(f"  quote: {quote!r}")

        ctx = _get_page_context(quote, doc_id, page, cache_dir)
        if ctx:
            lines.append(f"  [page context]:\n{ctx}")
        lines.append("")

    lines += [
        "=" * 60,
        "",
        "INSTRUCTIONS:",
        "Review every passage, every market, and every theory above.",
        "Use the record_llm_review tool to return your findings.",
        "Do not mark anything as lawyer_reviewed.",
        "Do not write to data/cases/.",
        "Return empty arrays for sections with no findings.",
    ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Claude API call
# ---------------------------------------------------------------------------

def _estimate_cost_usd(prompt: str, max_output: int = _MAX_OUTPUT_TOKENS) -> float:
    """Rough cost estimate before making the API call."""
    system_tokens = len(_REVIEW_SYSTEM_PROMPT) // 4
    prompt_tokens = len(prompt) // 4
    return (system_tokens + prompt_tokens) * _INPUT_COST_PER_TOKEN + max_output * _OUTPUT_COST_PER_TOKEN


def _call_claude_review(prompt: str, anthropic_client) -> dict:
    """Call Claude with the review tool schema; return the raw input dict."""
    message = anthropic_client.messages.create(
        model=_MODEL,
        max_tokens=_MAX_OUTPUT_TOKENS,
        system=_REVIEW_SYSTEM_PROMPT,
        tools=[_REVIEW_TOOL_SCHEMA],
        tool_choice={"type": "tool", "name": "record_llm_review"},
        messages=[{"role": "user", "content": prompt}],
    )
    for block in message.content:
        if getattr(block, "type", None) == "tool_use":
            return block.input
    raise ValueError("Claude did not call the record_llm_review tool")


# ---------------------------------------------------------------------------
# Output validation
# ---------------------------------------------------------------------------

def _validate_review_output(
    review: dict,
    known_passage_ids: set[str],
) -> list[str]:
    """
    Return a list of validation errors. Empty means the output is clean.

    Checks:
    - triage_status is a valid enum value
    - gap_findings: non-null source_evidence must reference a known passage_id
    - gap_findings: null source_evidence must have confidence: speculative
    - output does not contain 'lawyer_reviewed'
    """
    errors: list[str] = []

    status = review.get("triage_status", "")
    if status not in _VALID_TRIAGE_STATUSES:
        errors.append(
            f"Invalid triage_status {status!r} — must be one of {sorted(_VALID_TRIAGE_STATUSES)}"
        )

    for gf in review.get("gap_findings") or []:
        ev = gf.get("source_evidence")
        conf = gf.get("confidence", "")
        desc = gf.get("description", "")[:60]
        if ev is not None and ev not in known_passage_ids:
            errors.append(
                f"gap_finding source_evidence {ev!r} is not a known passage_id "
                f"(description: {desc!r})"
            )
        if ev is None and conf != "speculative":
            errors.append(
                f"gap_finding with null source_evidence must have confidence: speculative "
                f"(got {conf!r}, description: {desc!r})"
            )

    # Flat scan for the forbidden string
    raw_json = json.dumps(review)
    if "lawyer_reviewed" in raw_json:
        errors.append(
            "Output contains forbidden string 'lawyer_reviewed' — remove before writing"
        )

    return errors


# ---------------------------------------------------------------------------
# JSON / Markdown output
# ---------------------------------------------------------------------------

def write_llm_review_json(
    output_path: Path,
    review: dict,
    case_id: str,
    focus: str,
    model: str,
    generated_at: str,
) -> None:
    """Write the structured review to a JSON file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    envelope = {
        "schema_version": "1",
        "case_id": case_id,
        "focus": focus,
        "generated_at": generated_at,
        "llm_model": model,
    }
    envelope.update(review)
    output_path.write_text(
        json.dumps(envelope, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def write_llm_review_md(
    output_path: Path,
    review: dict,
    case_id: str,
    focus: str,
    model: str,
    generated_at: str,
    json_path: Path,
    validation_errors: list[str],
) -> None:
    """Write a human-readable markdown review report."""
    triage = review.get("triage_status", "unknown")
    rationale = review.get("triage_rationale", "")
    passage_reviews = review.get("passage_reviews") or []
    market_reviews = review.get("market_reviews") or []
    theory_reviews = review.get("theory_reviews") or []
    gap_findings = review.get("gap_findings") or []
    role_flags = review.get("role_misuse_flags") or []
    status_flags = review.get("definition_status_flags") or []

    lines: list[str] = [
        f"# LLM Review: `{case_id}` — `{focus}`",
        "",
        f"Generated: {generated_at}  ",
        f"Model: `{model}`  ",
        f"JSON: `{json_path}`",
        "",
        f"**Triage: `{triage}`**",
        "",
        f"> {rationale}" if rationale else "",
        "",
    ]

    if validation_errors:
        lines += ["## ⚠ Validation warnings", ""]
        for err in validation_errors:
            lines.append(f"- {err}")
        lines.append("")

    # 1. Passage-to-proposition review
    lines += ["## 1. Passage-to-proposition review", ""]
    if passage_reviews:
        lines.append("| Passage | Linked to | Role in draft | Support | Role check | Note |")
        lines.append("|---------|-----------|---------------|---------|------------|------|")
        for pr in passage_reviews:
            pid = pr.get("passage_id", "?")
            linked = ", ".join(pr.get("linked_to") or []) or "—"
            role = pr.get("source_role_in_draft", "not_set")
            support = pr.get("support_verdict", "?")
            role_v = pr.get("role_verdict", "?")
            note = (pr.get("note") or "").replace("|", "\\|")[:80]
            # Mark problems with warning emoji
            support_cell = f"⚠ {support}" if support in ("weak", "none") else support
            role_cell = f"⚠ {role_v}" if role_v == "likely_wrong" else role_v
            lines.append(f"| `{pid}` | {linked} | {role} | {support_cell} | {role_cell} | {note} |")
        lines.append("")
    else:
        lines += ["No passages reviewed.", ""]

    # 2. Market scope review
    lines += ["## 2. Market scope review", ""]
    if market_reviews:
        lines.append("| Market | Type | definition_status | Scope | Passage support |")
        lines.append("|--------|------|-------------------|-------|-----------------|")
        for mr in market_reviews:
            mid = mr.get("market_id", "?")
            name = (mr.get("market_name") or "?")[:50]
            mtype = mr.get("market_type", "?")
            ds = mr.get("definition_status_verdict", "?")
            scope = mr.get("scope_verdict", "?")
            psup = mr.get("passage_support_verdict", "?")
            ds_cell = f"⚠ {ds}" if ds == "likely_wrong" else ds
            scope_cell = f"⚠ {scope}" if scope in ("too_broad", "too_narrow", "unsupported") else scope
            psup_cell = f"⚠ {psup}" if psup in ("weakly_supported", "unsupported") else psup
            lines.append(f"| `{mid}` {name} | {mtype} | {ds_cell} | {scope_cell} | {psup_cell} |")
        lines.append("")

        # Definition status flags inline
        if status_flags:
            lines += ["**Definition status flags:**", ""]
            for dsf in status_flags:
                mid = dsf.get("market_id", "?")
                cur = dsf.get("current_status", "?")
                sug = dsf.get("suggested_status", "?")
                note = dsf.get("note", "")
                lines.append(f"- `{mid}`: `{cur}` → suggest `{sug}` — {note}")
            lines.append("")
    else:
        lines += ["No markets reviewed.", ""]

    # 3. Gap findings
    lines += ["## 3. Gap findings", ""]
    source_backed = [gf for gf in gap_findings if gf.get("confidence") == "source_backed"]
    speculative = [gf for gf in gap_findings if gf.get("confidence") == "speculative"]
    if source_backed:
        lines += ["**Source-backed:**", ""]
        for gf in source_backed:
            ev = gf.get("source_evidence")
            ev_str = f" (passage `{ev}`)" if ev else ""
            lines.append(f"- [{gf.get('gap_type', '?')}] {gf.get('description', '?')}{ev_str}")
        lines.append("")
    if speculative:
        lines += ["**Speculative (no source citation):**", ""]
        for gf in speculative:
            lines.append(f"- [{gf.get('gap_type', '?')}] {gf.get('description', '?')}")
        lines.append("")
    if not gap_findings:
        lines += ["No gap findings.", ""]

    # 4. Theory-of-harm review
    lines += ["## 4. Theory-of-harm review", ""]
    if theory_reviews:
        lines.append("| Theory | Linkage | Note |")
        lines.append("|--------|---------|------|")
        for tr in theory_reviews:
            name = (tr.get("theory_name") or "?")[:60]
            lv = tr.get("linkage_verdict", "?")
            note = (tr.get("note") or "").replace("|", "\\|")[:80]
            lv_cell = f"⚠ {lv}" if lv in ("missing_passages", "improperly_linked") else lv
            lines.append(f"| {name} | {lv_cell} | {note} |")
        lines.append("")
    else:
        lines += ["No theories of harm in draft.", ""]

    # 5. Outcome / serious-doubts passage misuse
    lines += ["## 5. Outcome / serious-doubts passage misuse", ""]
    misused = [mr for mr in market_reviews if mr.get("outcome_passage_misuse")]
    if misused:
        for mr in misused:
            mid = mr.get("market_id", "?")
            name = mr.get("market_name", "?")
            note = mr.get("outcome_passage_misuse_note", "")
            lines.append(f"- `{mid}` **{name}**: {note}")
        lines.append("")
    else:
        lines += ["No outcome/serious-doubts passage misuse detected.", ""]

    # 6. Source role misuse flags
    if role_flags:
        lines += ["## 6. Source role flags", ""]
        for rf in role_flags:
            pid = rf.get("passage_id", "?")
            role_in = rf.get("role_in_draft", "?")
            detected = rf.get("role_detected", "?")
            note = rf.get("note", "")
            lines.append(f"- `{pid}`: draft says `{role_in}` — detected `{detected}`. {note}")
        lines.append("")

    # Triage summary
    lines += [
        "---",
        "",
        "## Triage recommendation",
        "",
        f"**`{triage}`**",
        "",
        f"{rationale}",
        "",
    ]

    # Disclaimer
    lines += [
        "---",
        "",
        "_This review was generated by an LLM and must not substitute for human or legal_",
        "_verification. Do not promote to `data/cases/` based on this output alone._",
        "_Do not set `review_status: spot_checked` or any promotion status based on this report._",
        "",
    ]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Public entry point for ingest_case.py integration
# ---------------------------------------------------------------------------

def run_llm_review(
    draft_path: Path,
    review_md_path: Path,
    json_out: Path,
    md_out: Path,
    cache_dir: Path,
    anthropic_client,
    max_cost: float = 0.50,
    skip_preflight: bool = False,
) -> tuple[str, list[str]]:
    """
    Run the LLM review for a validated draft.

    Returns (triage_status, validation_errors).
    Raises ValueError on preflight failure or cost overrun.
    Raises RuntimeError on API or parse failure.
    """
    if not skip_preflight:
        err = _check_preflight(draft_path, review_md_path)
        if err:
            raise ValueError(err)

    draft = yaml.safe_load(draft_path.read_text(encoding="utf-8"))
    case_id = draft.get("case_id", draft_path.stem)
    focus = draft_path.stem.split(".")[-2] if draft_path.stem.count(".") >= 2 else "market_definition"

    passages_raw: list[dict] = draft.get("source_passages") or []
    known_passage_ids = {sp.get("passage_id", "") for sp in passages_raw}

    prompt = _build_review_prompt(draft, cache_dir)

    estimated = _estimate_cost_usd(prompt)
    if estimated > max_cost:
        raise ValueError(
            f"Estimated cost ${estimated:.3f} exceeds max_cost ${max_cost:.2f}. "
            "Use --max-cost to raise the limit."
        )

    print(f"  Estimated cost: ${estimated:.3f}")

    try:
        review = _call_claude_review(prompt, anthropic_client)
    except Exception as exc:
        raise RuntimeError(f"LLM review API call failed: {exc}") from exc

    validation_errors = _validate_review_output(review, known_passage_ids)

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    write_llm_review_json(json_out, review, case_id, focus, _MODEL, generated_at)
    write_llm_review_md(
        md_out, review, case_id, focus, _MODEL, generated_at,
        json_out, validation_errors,
    )

    triage = review.get("triage_status", "unknown")
    return triage, validation_errors


# ---------------------------------------------------------------------------
# Main (standalone CLI)
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="LLM review / promotion triage for CompMap draft YAML records",
    )
    parser.add_argument("--case-id", required=True, help="Case ID (e.g. eu_sika_dry_mix_2019)")
    parser.add_argument(
        "--focus", default="market_definition",
        choices=["market_definition", "theories", "remedies", "case_history"],
    )
    parser.add_argument("--max-cost", type=float, default=0.50,
                        help="Max estimated API cost in USD (default: 0.50)")
    parser.add_argument("--cache-dir", default=str(_DEFAULT_CACHE_DIR),
                        help=f"PDF text cache directory (default: {_DEFAULT_CACHE_DIR})")
    args = parser.parse_args()

    cache_dir = Path(args.cache_dir)

    # Locate draft
    draft_path = _find_draft_path(args.case_id, args.focus, _DRAFTS_DIR)
    if draft_path is None:
        print(
            f"ERROR: Draft not found for '{args.case_id}.{args.focus}' "
            f"under {_DRAFTS_DIR}",
            file=sys.stderr,
        )
        return 1

    jurisdiction = draft_path.parent.name
    draft_dir = draft_path.parent
    review_md_path = draft_dir / f"{args.case_id}.{args.focus}.review.md"
    json_out = draft_dir / f"{args.case_id}.{args.focus}.llm_review.json"
    md_out = draft_dir / f"{args.case_id}.{args.focus}.llm_review.md"

    print(f"Case:       {args.case_id}")
    print(f"Focus:      {args.focus}")
    print(f"Draft:      {draft_path}")
    print(f"Review:     {review_md_path}")
    print(f"JSON out:   {json_out}")
    print(f"MD out:     {md_out}")
    print(f"Max cost:   ${args.max_cost:.2f}")
    print()

    # Preflight
    err = _check_preflight(draft_path, review_md_path)
    if err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 1

    # Load Anthropic client
    try:
        import anthropic as _anthropic
        anthropic_client = _anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    except ImportError:
        print(
            "ERROR: anthropic package not installed. "
            "Run: pip install anthropic",
            file=sys.stderr,
        )
        return 1
    except KeyError:
        print(
            "ERROR: ANTHROPIC_API_KEY environment variable not set.",
            file=sys.stderr,
        )
        return 1

    print("Running LLM review …")
    try:
        triage, validation_errors = run_llm_review(
            draft_path=draft_path,
            review_md_path=review_md_path,
            json_out=json_out,
            md_out=md_out,
            cache_dir=cache_dir,
            anthropic_client=anthropic_client,
            max_cost=args.max_cost,
            skip_preflight=True,  # already checked above
        )
    except (ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"  Triage:     {triage}")
    if validation_errors:
        print(f"  WARN: {len(validation_errors)} validation warning(s):")
        for ve in validation_errors:
            print(f"    - {ve}")
    print(f"  JSON:       {json_out}")
    print(f"  Markdown:   {md_out}")
    print()
    print(f"RESULT: {triage.upper()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
