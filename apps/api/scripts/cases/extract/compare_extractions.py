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
_MARKET_SCALAR_FIELDS = ("definition_status", "market_importance")
_RECORD_SCALAR_FIELDS = ("outcome", "decision_date", "deal_value")

# Market-list keys, paired with the human-facing label used in conflict field paths.
_MARKET_LISTS = (
    ("product_markets_considered", "product_markets"),
    ("geographic_markets_considered", "geographic_markets"),
    ("theories_of_harm", "theories"),
)

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


def _trivial_equivalent(value_a: str, value_b: str) -> bool:
    """True when two values differ only by whitespace, case, or a country abbreviation.

    Splits each value on an em/en dash so "Ready-mix concrete — DE" and
    "Ready-mix concrete — Germany" compare segment by segment.
    """
    if value_a.strip().lower() == value_b.strip().lower():
        return True
    segs_a = [s for s in _split_segments(value_a)]
    segs_b = [s for s in _split_segments(value_b)]
    if len(segs_a) != len(segs_b):
        return False
    return all(_canonical_country(a) == _canonical_country(b) for a, b in zip(segs_a, segs_b))


def _split_segments(value: str) -> list[str]:
    for dash in ("—", "–", " - "):
        if dash in value:
            return [s.strip() for s in value.split(dash)]
    return [value.strip()]


# ---------------------------------------------------------------------------
# Alignment + diff
# ---------------------------------------------------------------------------

def _index_markets_by_name(record: dict) -> dict[str, dict]:
    """Map normalized market/theory name → market dict, across all market lists."""
    index: dict[str, dict] = {}
    for list_key, _label in _MARKET_LISTS:
        for m in (record.get(list_key) or []):
            name = m.get("name", "")
            if name:
                index[_normalize_for_similarity(name)] = m
    return index


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
            "resolved_to": name_b or name_a, "resolved_by": "auto",
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


def compare_drafts(
    draft_a: dict,
    draft_b: dict,
    focus: Optional[str] = None,
    equivalence_fn: Optional[EquivalenceFn] = None,
) -> dict:
    """Align draft_a against draft_b and diff them; return ConflictReport fields.

    Alignment reuses `_reconcile` with draft_b as the baseline ("existing") and
    draft_a as the "draft", so the four reconciliation groups map to:
      matched            → aligned pair → deterministic scalar diff
      likely_rename      → aligned pair, names differ → rename candidate
      candidate_addition → present in A, missing in B → a_only conflict
      out_of_scope       → present in B, missing in A → b_only conflict
    """
    findings = _reconcile(draft_a, draft_b, focus=focus)
    grouped = _group_reconciliation(findings)

    index_a = _index_markets_by_name(draft_a)
    index_b = _index_markets_by_name(draft_b)

    agreed: list[str] = []
    conflicts: list[dict] = []
    auto_resolved: list[dict] = []

    # matched + likely_rename are both aligned pairs (same proposition in A and B);
    # they differ only in how confidently the matcher tied the names. Handle them
    # the same way: reconcile the name, then diff the scalar fields.
    for f in grouped.get("matched", []) + grouped.get("likely_rename", []):
        name_a = f.get("draft_name", "")
        name_b = f.get("existing_name", "")
        market_a = index_a.get(_normalize_for_similarity(name_a), {})
        market_b = index_b.get(_normalize_for_similarity(name_b), {})
        prefix = f"markets/{name_b or name_a}"
        _reconcile_name(
            name_a, name_b, f"{prefix}/name",
            equivalence_fn, agreed, conflicts, auto_resolved,
        )
        _diff_aligned_pair(market_a, market_b, prefix, agreed, conflicts)

    # candidate_addition → in A, not B.
    for f in grouped.get("candidate_addition", []):
        conflicts.append({
            "field": "markets",
            "kind": "a_only",
            "draft_a": f.get("draft_name", ""),
            "draft_b": None,
            "source_excerpt": None,
            "resolution": None,
        })

    # out_of_scope → in B, not A.
    for f in grouped.get("out_of_scope", []):
        conflicts.append({
            "field": "markets",
            "kind": "b_only",
            "draft_a": None,
            "draft_b": f.get("existing_name", ""),
            "source_excerpt": None,
            "resolution": None,
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
