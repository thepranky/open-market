#!/usr/bin/env python3
"""
compare_extractions.py — align two independent extractions and diff them.

Part of dual extraction (ROADMAP 5.9). Two cold extractions of the same source
(`draft_a`, `draft_b`) are aligned by market/theory name and diffed field by field
to produce a ConflictReport. A human then reviews only the conflicts, not the full
record.

Two layers:
  1. Deterministic — alignment via the existing reconciliation machinery
     (`_reconcile` / `_group_reconciliation` in extract_case_from_source), then
     value comparison of scalar/enum fields on aligned pairs. No LLM call.
  2. LLM (optional, injectable) — an *equivalence adjudicator* decides whether two
     differently-phrased values of an aligned field are equivalent (suppress) or a
     genuine conflict (raise). It classifies/normalizes only; it never resolves a
     genuine conflict by picking a value. Default is no adjudicator, in which case
     rename candidates are surfaced to the human (conservative).

The adjudicator is a callable so the core and its tests run deterministically with
no API key. See the spec at docs/specs/2026-06-25-case-dual-extraction.md.

Usage (from repo root):
    python apps/api/scripts/cases/extract/compare_extractions.py \\
        --case-id eu_sika_mbcc_2023 \\
        --draft-a data/drafts/eu/eu_sika_mbcc_2023.market_definition.draft_a.yaml \\
        --draft-b data/drafts/eu/eu_sika_mbcc_2023.market_definition.draft_b.yaml
"""

import argparse
import re
import sys
from pathlib import Path
from typing import Callable, Optional

import yaml

# ---------------------------------------------------------------------------
# Path setup — must precede local imports (mirrors ingest_case.py)
# ---------------------------------------------------------------------------

_SCRIPTS_DIR = Path(__file__).resolve().parent
_API_DIR = _SCRIPTS_DIR.parent.parent.parent
_REPO_ROOT = _API_DIR.parents[1]

for _p in (str(_API_DIR), str(_SCRIPTS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from extract_case_from_source import (  # noqa: E402
    _group_reconciliation,
    _normalize_for_similarity,
    _reconcile,
)

# Aligned-pair scalar fields compared by the deterministic layer. Market-level
# fields live on each market dict; top-level fields live on the record root.
_MARKET_SCALAR_FIELDS = ("definition_status", "market_importance", "commitment_type")
_RECORD_SCALAR_FIELDS = ("outcome", "decision_date", "deal_value")

# Market-list keys, paired with the human-facing label used in conflict field paths.
_MARKET_LISTS = (
    ("product_markets_considered", "product_markets"),
    ("geographic_markets_considered", "geographic_markets"),
    ("theories_of_harm", "theories"),
    ("commitments", "commitments"),
)

# Reconciliation findings carry a draft_market_type ("product" | "geographic" | ""
# for theories); map it to the right list + label so a name that exists in two
# lists (e.g. a product "Cement" and a geographic "Cement") never collides.
_TYPE_TO_LIST = {
    "product": ("product_markets_considered", "product_markets"),
    "geographic": ("geographic_markets_considered", "geographic_markets"),
    "theory": ("theories_of_harm", "theories"),
    "commitment": ("commitments", "commitments"),
}


def _list_for_type(market_type: str) -> tuple[str, str]:
    """(list_key, label) for a finding's draft_market_type ('' / absent → theory)."""
    return _TYPE_TO_LIST.get(market_type or "theory", _TYPE_TO_LIST["theory"])

# An equivalence adjudicator decides whether two differently-phrased values are the
# same thing. Returns True (equivalent → suppress) or False (genuine conflict).
EquivalenceFn = Callable[[str, str, str], bool]  # (value_a, value_b, source_excerpt) -> bool


# ---------------------------------------------------------------------------
# Whitelisted trivial normalizations (deterministic; logged as auto_resolved)
# ---------------------------------------------------------------------------

# Country-name abbreviations safe to normalize without LLM or human review.
_COUNTRY_ABBREV = {
    "de": "germany", "fr": "france", "uk": "united kingdom", "us": "united states",
    "nl": "netherlands", "es": "spain", "it": "italy", "be": "belgium",
    "at": "austria", "ie": "ireland", "se": "sweden", "pl": "poland",
}


def _canonical_country(token: str) -> str:
    t = token.strip().lower()
    return _COUNTRY_ABBREV.get(t, t)


# Punctuation that separates words but carries no meaning in a market name:
# hyphen, en/em dash, slash, comma. Folding these (and case/whitespace) to single
# spaces lets "end-customers" == "end customers" and "A / B" == "A , B" without an
# LLM call. Lexical differences (km vs kilometres, "or" vs "/") are NOT folded —
# those are left to the adjudicator/human, since expanding words risks suppressing
# a real conflict.
_PUNCT_SEPARATORS = re.compile(r"[\-–—/,]+")


def _punct_fold(value: str) -> str:
    """Lowercased form with cosmetic punctuation separators flattened to spaces."""
    return " ".join(_PUNCT_SEPARATORS.sub(" ", value.lower()).split())


def _trivial_equivalent(value_a: str, value_b: str) -> bool:
    """True when two values differ only cosmetically — safe to auto-resolve.

    Three cosmetic classes, in order:
      1. whitespace / case
      2. punctuation separators (hyphen, dash, slash, comma) — "end-customers" vs
         "end customers"
      3. a country abbreviation in a multi-segment value — "… — DE" vs "… — Germany"

    Country canonicalization is applied ONLY to multi-segment values: a lone value
    that happens to equal a country code (e.g. "IT" for IT services) must not be
    auto-equated to "Italy" — suppressing a real conflict is the dangerous
    direction, so single-segment values fall through to human review.
    """
    if value_a.strip().lower() == value_b.strip().lower():
        return True
    if _punct_fold(value_a) == _punct_fold(value_b):
        return True
    segs_a = _split_segments(value_a)
    segs_b = _split_segments(value_b)
    if len(segs_a) != len(segs_b) or len(segs_a) < 2:
        return False
    return all(_canonical_country(a) == _canonical_country(b) for a, b in zip(segs_a, segs_b))


def _expanded_form(value_a: str, value_b: str) -> str:
    """Canonical merged name for two trivially-equivalent values.

    For equal-length multi-segment values, prefer the expanded (non-abbreviation)
    country variant per segment so "Ready-mix concrete — DE" + "— Germany" resolves
    to "…— Germany". For a purely cosmetic (punctuation/whitespace) difference where
    the segment counts do not line up, keep the more descriptive (longer) form
    rather than risk dropping a segment.
    """
    segs_a = _split_segments(value_a)
    segs_b = _split_segments(value_b)
    if len(segs_a) != len(segs_b) or len(segs_a) < 2:
        a, b = value_a.strip(), value_b.strip()
        return b if len(b) > len(a) else a
    out: list[str] = []
    for sa, sb in zip(segs_a, segs_b):
        a_is_code = sa.strip().lower() in _COUNTRY_ABBREV
        b_is_code = sb.strip().lower() in _COUNTRY_ABBREV
        if a_is_code and not b_is_code:
            out.append(sb.strip())
        else:
            out.append(sa.strip())
    return " — ".join(out)


def _split_segments(value: str) -> list[str]:
    for dash in ("—", "–", " - "):
        if dash in value:
            return [s.strip() for s in value.split(dash)]
    return [value.strip()]


# ---------------------------------------------------------------------------
# Alignment + diff
# ---------------------------------------------------------------------------

def _index_markets_by_name(record: dict) -> dict[str, dict[str, dict]]:
    """Per-list map: list_key → {normalized name → market dict}.

    Keyed per list (not flat) so a product market and a geographic market that
    share a name do not overwrite each other in the lookup used for field diffs.
    """
    index: dict[str, dict[str, dict]] = {}
    for list_key, _label in _MARKET_LISTS:
        bucket: dict[str, dict] = {}
        for m in (record.get(list_key) or []):
            name = m.get("name", "") or m.get("title", "")
            if name:
                bucket[_normalize_for_similarity(name)] = m
        index[list_key] = bucket
    return index


def _list_and_label_for_name(record: dict, name: str) -> tuple[str, str]:
    """Find which market list contains *name* in *record*; return (list_key, label).

    Used for b_only (out_of_scope) findings, which do not carry a market type.
    Falls back to the product list when the name is not found (defensive only).
    """
    norm = _normalize_for_similarity(name)
    for list_key, label in _MARKET_LISTS:
        if any(
            _normalize_for_similarity(m.get("name", "") or m.get("title", "")) == norm
            for m in (record.get(list_key) or [])
        ):
            return list_key, label
    return _MARKET_LISTS[0]


def _diff_aligned_pair(
    market_a: dict,
    market_b: dict,
    field_prefix: str,
    agreed: list[str],
    conflicts: list[dict],
) -> None:
    """Deterministic scalar diff of one aligned market pair (A matched to B)."""
    for fld in _MARKET_SCALAR_FIELDS:
        va = str(market_a.get(fld) or "").strip()
        vb = str(market_b.get(fld) or "").strip()
        if not va and not vb:
            continue
        path = f"{field_prefix}/{fld}"
        if va == vb:
            agreed.append(path)
        else:
            conflicts.append({
                "field": path,
                "kind": "value_mismatch",
                "draft_a": va or None,
                "draft_b": vb or None,
                "source_excerpt": None,
                "resolution": None,
            })


def _reconcile_name(
    name_a: str,
    name_b: str,
    path: str,
    equivalence_fn: Optional[EquivalenceFn],
    agreed: list[str],
    conflicts: list[dict],
    auto_resolved: list[dict],
) -> None:
    """Reconcile the names of an aligned pair: agreed / auto-resolved / conflict.

    Order: exact (normalized) match → trivial normalization (whitespace, case,
    country abbreviation) → injected LLM adjudicator → surface as rename_candidate.
    """
    if _normalize_for_similarity(name_a) == _normalize_for_similarity(name_b):
        agreed.append(path)
        return
    if _trivial_equivalent(name_a, name_b):
        auto_resolved.append({
            "field": path, "draft_a": name_a, "draft_b": name_b,
            "resolved_to": _expanded_form(name_a, name_b), "resolved_by": "auto",
        })
        return
    if equivalence_fn is not None and equivalence_fn(name_a, name_b, ""):
        auto_resolved.append({
            "field": path, "draft_a": name_a, "draft_b": name_b,
            "resolved_to": name_b or name_a, "resolved_by": "llm",
        })
        return
    conflicts.append({
        "field": path, "kind": "rename_candidate",
        "draft_a": name_a, "draft_b": name_b,
        "source_excerpt": None, "resolution": None,
    })


def align_drafts(draft_a: dict, draft_b: dict, focus: Optional[str] = None) -> dict:
    """Structural alignment of A↔B markets — the single source of truth for pairing.

    Reuses `_reconcile` with draft_b as the baseline ("existing") and draft_a as the
    "draft", so the four reconciliation groups map to:
      matched / likely_rename → aligned pair (same proposition in A and B)
      candidate_addition      → present in A, missing in B (a_only)
      out_of_scope            → present in B, missing in A (b_only)

    Returns dicts carrying enough to both diff (compare_drafts) and merge-back
    (merge_drafts --from-conflict-report) without re-deriving the matching:
      pairs:  [{list_key, label, name_a, name_b}]
      a_only: [{list_key, label, name_a}]
      b_only: [{list_key, label, name_b}]
    """
    findings = _reconcile(draft_a, draft_b, focus=focus)
    grouped = _group_reconciliation(findings)

    pairs: list[dict] = []
    for f in grouped.get("matched", []) + grouped.get("likely_rename", []):
        list_key, label = _list_for_type(f.get("draft_market_type", ""))
        pairs.append({
            "list_key": list_key, "label": label,
            "name_a": f.get("draft_name", ""), "name_b": f.get("existing_name", ""),
        })

    a_only: list[dict] = []
    for f in grouped.get("candidate_addition", []):
        list_key, label = _list_for_type(f.get("draft_market_type", ""))
        a_only.append({"list_key": list_key, "label": label, "name_a": f.get("draft_name", "")})

    # out_of_scope findings carry no market type → derive list_key/label from B.
    b_only: list[dict] = []
    for f in grouped.get("out_of_scope", []):
        name_b = f.get("existing_name", "")
        list_key, label = _list_and_label_for_name(draft_b, name_b)
        b_only.append({"list_key": list_key, "label": label, "name_b": name_b})

    return {"pairs": pairs, "a_only": a_only, "b_only": b_only}


def compare_drafts(
    draft_a: dict,
    draft_b: dict,
    focus: Optional[str] = None,
    equivalence_fn: Optional[EquivalenceFn] = None,
) -> dict:
    """Align draft_a against draft_b and diff them; return ConflictReport fields."""
    align = align_drafts(draft_a, draft_b, focus=focus)
    index_a = _index_markets_by_name(draft_a)
    index_b = _index_markets_by_name(draft_b)

    agreed: list[str] = []
    conflicts: list[dict] = []
    auto_resolved: list[dict] = []

    # Aligned pairs: reconcile the name, then diff the scalar fields.
    for pair in align["pairs"]:
        list_key = pair["list_key"]
        market_a = index_a[list_key].get(_normalize_for_similarity(pair["name_a"]), {})
        market_b = index_b[list_key].get(_normalize_for_similarity(pair["name_b"]), {})
        prefix = f"{pair['label']}/{pair['name_b'] or pair['name_a']}"
        _reconcile_name(
            pair["name_a"], pair["name_b"], f"{prefix}/name",
            equivalence_fn, agreed, conflicts, auto_resolved,
        )
        _diff_aligned_pair(market_a, market_b, prefix, agreed, conflicts)

    # In A, not B.
    for item in align["a_only"]:
        conflicts.append({
            "field": item["label"], "kind": "a_only",
            "draft_a": item["name_a"], "draft_b": None,
            "source_excerpt": None, "resolution": None,
        })

    # In B, not A.
    for item in align["b_only"]:
        conflicts.append({
            "field": item["label"], "kind": "b_only",
            "draft_a": None, "draft_b": item["name_b"],
            "source_excerpt": None, "resolution": None,
        })

    # Top-level scalar record fields.
    for fld in _RECORD_SCALAR_FIELDS:
        va = str(draft_a.get(fld) or "").strip()
        vb = str(draft_b.get(fld) or "").strip()
        if not va and not vb:
            continue
        if va == vb:
            agreed.append(fld)
        else:
            conflicts.append({
                "field": fld,
                "kind": "value_mismatch",
                "draft_a": va or None,
                "draft_b": vb or None,
                "source_excerpt": None,
                "resolution": None,
            })

    return {
        "agreed_fields": agreed,
        "conflicts": conflicts,
        "auto_resolved": auto_resolved,
    }


def build_conflict_report(
    case_id: str,
    draft_a: dict,
    draft_b: dict,
    *,
    focus: Optional[str] = None,
    model_a: str = "",
    model_b: str = "",
    same_model: bool = False,
    equivalence_fn: Optional[EquivalenceFn] = None,
) -> dict:
    """Build the full ConflictReport dict for serialization to YAML."""
    diff = compare_drafts(draft_a, draft_b, focus=focus, equivalence_fn=equivalence_fn)
    return {
        "conflict_report": {
            "case_id": case_id,
            "focus": focus or "",
            "models": {
                "draft_a": model_a,
                "draft_b": model_b,
                "same_model": same_model,
            },
            "agreed_fields": diff["agreed_fields"],
            "conflicts": diff["conflicts"],
            "auto_resolved": diff["auto_resolved"],
        }
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Align and diff two independent extractions into a ConflictReport",
    )
    parser.add_argument("--case-id", required=True, help="Case ID (e.g. eu_sika_mbcc_2023)")
    parser.add_argument("--draft-a", required=True, help="Path to Draft A YAML")
    parser.add_argument("--draft-b", required=True, help="Path to Draft B YAML")
    parser.add_argument("--focus", default=None,
                        help="Extraction focus (limits which proposition types are compared)")
    parser.add_argument("--out", default=None,
                        help="ConflictReport output path (default: alongside Draft A as .conflicts.yaml)")
    args = parser.parse_args(argv)

    draft_a_path = Path(args.draft_a)
    draft_b_path = Path(args.draft_b)
    draft_a = yaml.safe_load(draft_a_path.read_text(encoding="utf-8"))
    draft_b = yaml.safe_load(draft_b_path.read_text(encoding="utf-8"))

    report = build_conflict_report(
        args.case_id, draft_a, draft_b, focus=args.focus,
    )

    out_path = (
        Path(args.out)
        if args.out
        else draft_a_path.parent / (draft_a_path.name.replace(".draft_a.yaml", ".conflicts.yaml"))
    )
    out_path.write_text(
        yaml.dump(report, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )

    cr = report["conflict_report"]
    print(f"Case:          {args.case_id}")
    print(f"Agreed fields: {len(cr['agreed_fields'])}")
    print(f"Conflicts:     {len(cr['conflicts'])}")
    print(f"Auto-resolved: {len(cr['auto_resolved'])}")
    print(f"Written:       {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
