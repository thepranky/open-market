#!/usr/bin/env python3
"""
create_gold_draft.py — Generate a partial gold YAML from extraction draft for human review.

Reads draft YAML and report JSON (which contains promotion_plan and
canonical_merge_candidates), then creates a proposed gold YAML containing only
review-worthy candidates, marked for review.

Gold quote convention
---------------------
* ``quote_snippet`` — verbatim source text only, copied from already-validated
  draft source_passages.  Never invented or compressed here.
* ``source_summary`` — optional human explanation of what the passage shows.
* ``reviewer_notes`` — review notes; must not contain source text.

If no validated draft passage is available for a market, ``linked_source_passages``
is left empty and ``reviewer_notes`` is set to ``"source passage needs review"``.

Usage
-----
    cd apps/api

    .venv/bin/python scripts/create_gold_draft.py \\
        --case-id eu_google_fitbit_2021 \\
        --draft-yaml ../../data/drafts/eu/google_fitbit_2021.draft.yaml \\
        --report-json ../../data/source_text/google_fitbit_extraction_report.json \\
        --output-gold-yaml ../../data/evals/gold/eu_google_fitbit_2021.gold.yaml

    # Include context-only markets as well
    .venv/bin/python scripts/create_gold_draft.py \\
        --case-id eu_google_fitbit_2021 \\
        --draft-yaml ../../data/drafts/eu/google_fitbit_2021.draft.yaml \\
        --report-json ../../data/source_text/google_fitbit_extraction_report.json \\
        --output-gold-yaml ../../data/evals/gold/eu_google_fitbit_2021.gold.yaml \\
        --include-context-only
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import IO, Optional

import yaml

_API_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_API_DIR))

_EVALS_DIR = Path(__file__).resolve().parents[3] / "data" / "evals"


# ---------------------------------------------------------------------------
# Safe YAML emission for gold files
# ---------------------------------------------------------------------------

class _FoldedStr(str):
    """String subtype that gold_yaml_dump always emits as a block scalar.

    * Single-line values  → folded block scalar ``>-`` (no trailing newline).
    * Multi-line values   → literal block scalar ``|-`` (newlines preserved).
    * Empty string        → YAML empty-string ``''`` (PyYAML default fallback).

    Use this wrapper for ``quote_snippet``, ``source_summary``, and
    ``reviewer_notes`` to guarantee parse-safe YAML regardless of colons,
    semicolons, parenthetical numbering, or quotation characters inside the
    value.
    """


class _GoldDumper(yaml.SafeDumper):
    """YAML SafeDumper that emits ``_FoldedStr`` instances as block scalars."""


def _folded_str_representer(dumper: _GoldDumper, data: str):
    if not data:
        # Empty strings: use plain '' so the file stays legible.
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="'")
    style = "|" if "\n" in data else ">"
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


_GoldDumper.add_representer(_FoldedStr, _folded_str_representer)


def gold_yaml_dump(data: dict, stream: Optional[IO] = None) -> Optional[str]:
    """Dump a gold YAML structure using parse-safe block scalar formatting.

    Equivalent to ``yaml.dump`` with ``SafeDumper`` but uses ``_GoldDumper``
    so that ``_FoldedStr``-wrapped fields are emitted as ``>-`` / ``|-``
    block scalars rather than single-quoted or plain inline scalars.
    """
    return yaml.dump(
        data,
        stream=stream,
        Dumper=_GoldDumper,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    )


# ---------------------------------------------------------------------------
# Passage index helpers
# ---------------------------------------------------------------------------

def _build_passage_index(source_passages: list[dict]) -> dict[str, list[dict]]:
    """Return a mapping of market_id → [passage, ...] from a draft's source_passages.

    Each passage dict in the index retains the original keys (passage_id, page,
    quote_snippet, source_document_id, extraction_method, review_status) so they
    can be copied verbatim into gold entries without modification.

    Only passages with a non-empty quote_snippet are indexed.
    """
    index: dict[str, list[dict]] = {}
    for sp in (source_passages or []):
        quote = (sp.get("quote_snippet") or "").strip()
        if not quote:
            continue
        for mid in (sp.get("supports_markets") or []):
            index.setdefault(mid, []).append(sp)
        for mid in (sp.get("supports_geographic_markets") or []):
            index.setdefault(mid, []).append(sp)
    return index


def _build_market_id_index(draft_record: dict) -> dict[str, str]:
    """Return name (lower) → market_id for all draft product/geo markets."""
    idx: dict[str, str] = {}
    for lst_key in ("product_markets_considered", "geographic_markets_considered"):
        for m in (draft_record.get(lst_key) or []):
            name = (m.get("name") or "").strip().lower()
            mid = str(m.get("market_id") or "")
            if name and mid:
                idx[name] = mid
    return idx


# ---------------------------------------------------------------------------
# Alias candidate helpers — truncation / clause detection for passage phrases
# ---------------------------------------------------------------------------

# Detect alias candidates that were cut mid-enumeration (e.g. "on the basis of: (i").
_ALIAS_TRUNCATED_RE: re.Pattern = re.compile(
    r"(?:"
    r"\(\w*$"       # ends with (i, (ii, (
    r"|:\s*\(\w*$"  # ends with ": (i" or ": ("
    r"|,\s*\(\w*$"  # ends with ", (i"
    r"|:\s*$"       # ends with bare colon
    r")"
)

# Parenthetical list enumeration markers — presence anywhere in an extracted alias
# indicates the regex captured text that spans multiple list items.
_ALIAS_ENUM_MARKER_RE: re.Pattern = re.compile(
    r"\(\s*(?:i{1,3}|iv|v|ix|x|[a-z])\s*\)", re.I
)

# Modal / auxiliary verb phrases that signal the extracted text is a clause, not a market name.
# Market names are noun phrases; they never contain these constructions.
_ALIAS_CLAUSE_RE: re.Pattern = re.compile(
    r"\b(?:should|would|could|must|shall|will|cannot|need not|"
    r"is not|are not|does not|do not|did not|"
    r"would not|should not|could not)\b",
    re.I,
)


def _is_truncated_alias(value: str) -> bool:
    """Return True if the alias candidate should be rejected because it is:
    - cut mid-enumeration (trailing colon / open parenthetical), or
    - contains parenthetical list markers (regex captured multiple list items), or
    - contains modal/auxiliary verbs indicating it is a clause, not a market name.
    """
    if _ALIAS_TRUNCATED_RE.search(value):
        return True
    if _ALIAS_ENUM_MARKER_RE.search(value):
        return True
    if _ALIAS_CLAUSE_RE.search(value):
        return True
    return False


# ---------------------------------------------------------------------------
# Alias candidate extraction
# ---------------------------------------------------------------------------

# Neutral phrase patterns that signal a market name follows in passage text.
# No industry-specific terms; patterns are grounded in EU competition-law phrasing.
_ALIAS_EXTRACTION_PATTERNS: tuple[re.Pattern, ...] = (
    # "the relevant [product/geographic] market is [a/an] X" → X
    re.compile(
        r'\bthe relevant (?:product |geographic )?market is (?:an? )?'
        r'([A-Za-z][^.;\n]{5,79}?)(?=\s*[.,;]|\s*$)',
        re.I | re.MULTILINE,
    ),
    # "[an/the] overall market for [the] X" → "overall market for X"
    re.compile(
        r'\b(?:an? |the )?overall market for (?:the )?([A-Za-z][^.;\n]{5,79}?)(?=\s*[.,;]|\s*$)',
        re.I | re.MULTILINE,
    ),
    # "relevant product market for [the] X" → X
    re.compile(
        r'\brelevant product market for (?:the )?([A-Za-z][^.;\n]{5,79}?)(?=\s*[.,;]|\s*$)',
        re.I | re.MULTILINE,
    ),
    # "relevant geographic market for [the] X" → X
    re.compile(
        r'\brelevant geographic market for (?:the )?([A-Za-z][^.;\n]{5,79}?)(?=\s*[.,;]|\s*$)',
        re.I | re.MULTILINE,
    ),
    # "market for [the] X" — exclude false positives like "for the purpose of"
    re.compile(
        r'\bmarket for (?!(?:the purpose|assessing ))(?:the )?([A-Za-z][^.;\n]{5,79}?)(?=\s*[.,;]|\s*$)',
        re.I | re.MULTILINE,
    ),
)

# Lowercased values that are too generic to be useful as alias candidates.
_ALIAS_GENERIC_VALUES: frozenset[str] = frozenset({
    "relevant market", "relevant markets",
    "relevant product market", "relevant geographic market",
    "relevant product markets", "relevant geographic markets",
    "product market", "product markets",
    "geographic market", "geographic markets",
    "overall market", "the market", "this market",
    "the relevant market", "a relevant market",
    "the product market", "the geographic market",
    "left open", "not defined",
})

_ALIAS_MIN_LENGTH: int = 8  # alias candidates shorter than this are filtered out


def _build_alias_candidates(
    market_name: str,
    raw_passages: list[dict],
) -> list[dict]:
    """Extract alias candidates from the market's own linked source passages.

    Only short noun phrases grounded in EU competition-law phrasing are extracted.
    Clause fragments, enumeration markers, and truncated values are rejected.
    Draft market names and reconciliation findings are NOT used as alias sources —
    the evaluator handles those via nearest-candidate diagnostics and expected_draft_names.

    Parameters
    ----------
    market_name:
        The gold entry's own name; excluded from candidates.
    raw_passages:
        Source passages linked to this market in the draft, for phrase extraction.
    """
    seen: set[str] = {market_name.lower().strip()}
    candidates: list[dict] = []

    def _add(value: str, **kwargs: object) -> None:
        clean = value.strip().rstrip(".,;:")
        key = clean.lower()
        if not clean or key in seen:
            return
        if len(clean) < _ALIAS_MIN_LENGTH:
            return
        if key in _ALIAS_GENERIC_VALUES:
            return
        seen.add(key)
        entry: dict = {"value": clean, "source": "source_passage", "status": "suggested"}
        for k, v in kwargs.items():
            if v:
                entry[k] = v
        candidates.append(entry)

    for sp in raw_passages:
        quote = (sp.get("quote_snippet") or "").strip()
        if not quote:
            continue
        page = sp.get("page", "")
        pid = sp.get("passage_id", "")
        for pat in _ALIAS_EXTRACTION_PATTERNS:
            for m in pat.finditer(quote):
                extracted = m.group(1).strip().rstrip(".,;:")
                if not extracted:
                    continue
                if _is_truncated_alias(extracted):
                    continue
                # Strip uninformative leading "the market for" prefix when present.
                cleaned = re.sub(r"^the market for\s+", "", extracted, flags=re.I).strip()
                if not cleaned:
                    continue
                _add(cleaned, page=page, passage_id=pid, quote_snippet=quote[:120])

    return candidates


# ---------------------------------------------------------------------------
# Core gold-draft builder
# ---------------------------------------------------------------------------

def _create_gold_draft(
    case_id: str,
    draft_record: dict,
    report: dict,
    include_context_only: bool = False,
    include_hold_pending: bool = False,
) -> dict:
    """Create a partial gold YAML from draft + report.

    Passage linking
    ~~~~~~~~~~~~~~~
    Passages are copied from the draft's validated ``source_passages`` keyed by
    ``market_id`` — **not** by page number.  Quote snippets are never modified
    or re-generated.  If no validated passage exists for a market, the entry
    gets ``linked_source_passages: []`` and a reviewer note.

    Fine-grained market nodes
    ~~~~~~~~~~~~~~~~~~~~~~~~~
    Each candidate from ``canonical_merge_candidates`` becomes its own entry;
    markets are never collapsed.  An optional ``market_group`` field is provided
    as an empty placeholder for reviewers to fill in when multiple Commission-
    listed markets belong to the same umbrella definition.
    """
    gold: dict = {
        "_gold_metadata": {
            "case_id": case_id,
            "gold_status": "draft_for_review",
            "partial": True,
            "review_required": True,
            "source_draft_path": str(Path(case_id).with_suffix(".draft.yaml")),
            "created_from_report": True,
        },
    }

    # Copy case-level metadata from draft
    for key in ("case_id", "case_name", "authority", "jurisdiction", "sector",
                "decision_date", "parties", "source_documents"):
        if key in draft_record:
            gold[key] = draft_record[key]

    # Get candidates from report
    candidates = report.get("canonical_merge_candidates", {})

    # Determine which categories to include
    included_categories = [
        "safe_to_promote",
        "uncertain_markets",
        "manual_review",
        "manual_review_geo_pairing",
    ]
    if include_context_only:
        included_categories.append("context_only")
    if include_hold_pending:
        included_categories.append("hold_pending_source_check")

    # ---- passage + name→id indexes ----------------------------------------
    passage_index = _build_passage_index(draft_record.get("source_passages") or [])
    name_to_id = _build_market_id_index(draft_record)

    # ---- category → action mapping ----------------------------------------
    category_to_action = {
        "safe_to_promote":          "promote_to_canonical",
        "uncertain_markets":        "promote_with_uncertainty",
        "context_only":             "keep_as_context_only",
        "hold_pending_source_check": "hold_pending_source_check",
        "manual_review":            "manual_review",
        "manual_review_geo_pairing": "manual_review_geo_pairing",
    }

    # ---- build market lists -----------------------------------------------
    gold_markets: dict[str, list] = {
        "product_markets_considered": [],
        "geographic_markets_considered": [],
    }

    for category in included_categories:
        for entry in (candidates.get(category) or []):
            market_type = entry.get("market_type", "")
            market_name = entry.get("name", "")
            list_key = (
                "product_markets_considered"
                if market_type == "product"
                else "geographic_markets_considered"
            )

            # Resolve market_id from draft by name
            market_id = name_to_id.get(market_name.lower().strip(), "")

            # Fetch passages from draft index (verbatim copy)
            raw_passages = passage_index.get(market_id, []) if market_id else []
            linked: list[dict] = []
            for sp in raw_passages:
                linked.append({
                    "passage_id":          sp.get("passage_id", ""),
                    "source_document_id":  sp.get("source_document_id", ""),
                    "page":                sp.get("page", ""),
                    # Block scalar: never altered, always parse-safe regardless
                    # of colons, semicolons, or parenthetical list markers.
                    "quote_snippet":       _FoldedStr(sp.get("quote_snippet") or ""),
                    "extraction_method":   sp.get("extraction_method", ""),
                    "review_status":       sp.get("review_status", "unreviewed"),
                    # Placeholder: human explanation goes here, NOT in quote_snippet.
                    "source_summary":      _FoldedStr(""),
                })

            # Determine reviewer notes based on passage availability
            if not linked:
                reviewer_notes_str = "source passage needs review"
            else:
                reviewer_notes_str = ""

            market_entry: dict = {
                "name":                     market_name,
                "market_type":              market_type,
                "expected_definition_status": entry.get("definition_status", ""),
                "expected_promotion_action": category_to_action.get(category, "manual_review"),
                "importance":               entry.get("importance", ""),
                # Fine-grained grouping: leave null unless reviewer fills it in.
                "market_group":             None,
                "linked_source_passages":   linked,
                # aliases is reviewer-approved only; auto-discovered names go in alias_candidates.
                "aliases":                  [],
                "alias_candidates":         _build_alias_candidates(market_name, raw_passages),
                # Block scalar: review notes must not contain source text.
                "reviewer_notes":           _FoldedStr(reviewer_notes_str),
                "reviewed":                 False,
            }

            # Preserve explicit source_refs from the promotion plan entry if
            # they exist but we could not resolve passages (avoids data loss).
            if entry.get("source_refs") and not linked:
                market_entry["source_refs"] = entry["source_refs"]

            gold_markets[list_key].append(market_entry)

    gold.update(gold_markets)
    return gold


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a partial gold YAML from extraction draft for human review"
    )
    parser.add_argument("--case-id", required=True, help="Case ID")
    parser.add_argument("--draft-yaml", required=True, help="Path to draft YAML")
    parser.add_argument("--report-json", required=True, help="Path to extraction report JSON")
    parser.add_argument("--output-gold-yaml", required=True, help="Output gold YAML path")
    parser.add_argument(
        "--include-context-only", action="store_true",
        help="Include context_only candidates (default: exclude)",
    )
    parser.add_argument(
        "--include-hold-pending", action="store_true",
        help="Include hold_pending_source_check candidates (default: exclude)",
    )
    args = parser.parse_args()

    try:
        with open(args.draft_yaml) as fh:
            draft_record = yaml.safe_load(fh)
    except Exception as exc:
        print(f"Error loading draft YAML: {exc}", file=sys.stderr)
        return 1

    try:
        with open(args.report_json) as fh:
            report = json.load(fh)
    except Exception as exc:
        print(f"Error loading report JSON: {exc}", file=sys.stderr)
        return 1

    gold = _create_gold_draft(
        args.case_id,
        draft_record,
        report,
        include_context_only=args.include_context_only,
        include_hold_pending=args.include_hold_pending,
    )

    output_path = Path(args.output_gold_yaml)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(output_path, "w", encoding="utf-8") as fh:
            gold_yaml_dump(gold, fh)
        print(f"Gold draft created: {output_path}")
        print(f"  Product markets  : {len(gold.get('product_markets_considered', []))}")
        print(f"  Geographic markets: {len(gold.get('geographic_markets_considered', []))}")
        print(f"  Review required  : {gold['_gold_metadata']['review_required']}")
        return 0
    except Exception as exc:
        print(f"Error writing gold YAML: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
