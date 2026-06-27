#!/usr/bin/env python3
"""
repair_gold_quotes.py — Sync gold YAML linked_source_passages with verbatim
quote_snippets from the extraction draft YAML.

Problem this solves
-------------------
After human review, a gold YAML may contain hand-edited or paraphrased
``quote_snippet`` values.  The gold quote validator rejects these because they
are not verbatim in the cached PDF text.  This script replaces every
``linked_source_passages[].quote_snippet`` with the corresponding verbatim
passage from the extraction draft, then validates each candidate against the
page cache before including it.

Matching strategy (in priority order)
--------------------------------------
1. Market name (case-insensitive) → draft ``market_id`` → draft source_passages
   that carry ``supports_markets`` / ``supports_geographic_markets`` for that id.
2. Aliases listed on the gold market entry — same lookup as (1).
3. ``source_refs`` page-number fallback, filtered by normalised name-token overlap.
   Only passages whose quote contains at least one significant token from the
   market name or aliases are accepted; unrelated passages on the same page are
   dropped.
4. No match → ``linked_source_passages: []`` + reviewer_notes note.

After matching, candidates are:
  a. Validated against the page cache (when ``page_cache_map`` is provided):
     candidates that fail ``validate_quote_on_page`` are dropped.
  b. Sorted by priority: direct market-id match > fallback; then source_role
     precedence (conclusion > commission_assessment > market_investigation >
     notifying_party_view/precedent > background/unknown).
  c. Capped at ``max_passages`` (default 3).

If all candidates are dropped by validation, ``linked_source_passages`` is
cleared and a reviewer note is added.

What is preserved
-----------------
* ``reviewed``, ``reviewer_notes`` (unless forced to add a note), ``market_group``
* ``expected_promotion_action``, ``importance``, ``aliases``
* ``expected_definition_status``, ``market_type``, ``name``
* ``source_summary`` from the pre-existing passage on the same page (if any)
* All other gold-level keys not related to passages

Usage
-----
    cd apps/api

    # Write repaired file to a new path
    .venv/bin/python scripts/cases/evals/repair_gold_quotes.py \\
        --gold-yaml  ../../data/evals/gold/eu_google_fitbit_2021.gold.yaml \\
        --draft-yaml ../../data/drafts/eu/google_fitbit_2021.draft.yaml \\
        --output-yaml ../../data/evals/gold/eu_google_fitbit_2021.gold.repaired.yaml \\
        --cache-dir  ../../data/source_text

    # Repair in place
    .venv/bin/python scripts/cases/evals/repair_gold_quotes.py \\
        --gold-yaml  ../../data/evals/gold/eu_google_fitbit_2021.gold.yaml \\
        --draft-yaml ../../data/drafts/eu/google_fitbit_2021.draft.yaml \\
        --in-place \\
        --cache-dir  ../../data/source_text \\
        --max-passages-per-market 3
"""

import argparse
import copy
import re
import sys
from dataclasses import dataclass, field as dc_field
from pathlib import Path
from typing import Optional

import yaml

_API_DIR = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_API_DIR))
sys.path.insert(0, str(Path(__file__).parent))

from app.shared.utils.pdf_extractor import DEFAULT_CACHE_DIR, load_cache
from create_gold_draft import (
    _FoldedStr,
    _build_market_id_index,
    _build_passage_index,
    gold_yaml_dump,
)
from validate_gold_quotes import (
    load_gold_yaml,
    validate_quote_on_page,
)


# ---------------------------------------------------------------------------
# Source-role priority
# ---------------------------------------------------------------------------

# Lower number = higher priority (included before lower-priority passages).
_SOURCE_ROLE_PRIORITY: dict[str, int] = {
    "conclusion":          1,
    "commission_assessment": 2,
    "market_investigation": 3,
    "notifying_party_view": 4,
    "precedent":           4,
    "background":          5,
}
_DEFAULT_ROLE_PRIORITY = 3   # unknown / missing → treat as middle-tier


def _source_role_priority(role: str) -> int:
    return _SOURCE_ROLE_PRIORITY.get((role or "").strip().lower(), _DEFAULT_ROLE_PRIORITY)


# ---------------------------------------------------------------------------
# Name-overlap filtering (for source_refs fallback)
# ---------------------------------------------------------------------------

# Common words that carry no discriminating signal for market-name matching.
_OVERLAP_STOPWORDS: frozenset[str] = frozenset({
    "the", "a", "an", "of", "for", "and", "or", "to", "in", "at", "by",
    "on", "with", "from", "within", "relevant", "product", "market",
    "markets", "supply", "provision", "services", "service",
})

_MIN_TOKEN_LEN = 4


def _name_tokens(name: str) -> frozenset[str]:
    """Return significant tokens from a market name for overlap checking."""
    return frozenset(
        w for w in re.findall(r'\b\w+\b', name.lower())
        if len(w) >= _MIN_TOKEN_LEN and w not in _OVERLAP_STOPWORDS
    )


def _has_name_overlap(quote: str, market_name: str, aliases: list[str]) -> bool:
    """Return True if *quote* contains at least one significant token from
    *market_name* or any of *aliases*.

    When no significant tokens can be extracted from the name (e.g. short
    acronyms like "EEA"), the function returns True — we cannot filter by
    a name that has no discriminating tokens.
    """
    quote_lower = quote.lower()
    for name in [market_name] + (aliases or []):
        tokens = _name_tokens(name)
        if not tokens:
            return True      # no discriminating tokens → accept
        if any(tok in quote_lower for tok in tokens):
            return True
    return False


# ---------------------------------------------------------------------------
# Repair result types
# ---------------------------------------------------------------------------

@dataclass
class MarketRepairResult:
    """Outcome of repairing one gold market entry."""
    market_name: str
    market_type: str
    passages_replaced: int       # passages written into the repaired file
    passages_cleared: int        # 1 when no match was found at all
    passages_dropped: int        # candidates dropped by validation or overlap filter
    match_strategy: str          # "market_id" | "alias" | "source_refs" | "none"
    dropped_reasons: list[str] = dc_field(default_factory=list)


@dataclass
class RepairReport:
    """Summary of the full repair run."""
    case_id: str
    markets_repaired: list[MarketRepairResult] = dc_field(default_factory=list)

    @property
    def total_replaced(self) -> int:
        return sum(r.passages_replaced for r in self.markets_repaired)

    @property
    def total_cleared(self) -> int:
        return sum(r.passages_cleared for r in self.markets_repaired)

    @property
    def total_dropped(self) -> int:
        return sum(r.passages_dropped for r in self.markets_repaired)


# ---------------------------------------------------------------------------
# Passage lookup helpers
# ---------------------------------------------------------------------------

def _build_page_to_passages(source_passages: list[dict]) -> dict[str, list[dict]]:
    """Return page (str) → [passage, …] for all draft passages with a quote."""
    idx: dict[str, list[dict]] = {}
    for sp in (source_passages or []):
        if not (sp.get("quote_snippet") or "").strip():
            continue
        page = str(sp.get("page", "")).strip()
        if page:
            idx.setdefault(page, []).append(sp)
    return idx


def _find_draft_passages(
    gold_market: dict,
    passage_index: dict[str, list[dict]],    # market_id → [passage]
    name_to_id: dict[str, str],              # lower name → market_id
    page_to_passages: dict[str, list[dict]], # page str → [passage]
) -> tuple[list[dict], str, frozenset[str]]:
    """Return ``(candidates, strategy, direct_passage_ids)``.

    *strategy* is one of ``"market_id"``, ``"alias"``, ``"source_refs"``,
    ``"none"``.  *direct_passage_ids* is the set of ``passage_id`` values
    (or ``page`` strings when no passage_id exists) that came from a direct
    market-id match; used downstream for priority sorting.

    Source-refs fallback applies name-token overlap filtering so that only
    passages whose quote contains a significant token from the market name or
    aliases are accepted.
    """
    market_name = (gold_market.get("name") or "").strip()
    aliases = list(gold_market.get("aliases") or [])

    # Strategy 1 & 2: name / alias → market_id → passage_index
    candidates_names = [market_name] + aliases
    for name_candidate in candidates_names:
        mid = name_to_id.get(name_candidate.lower().strip(), "")
        if mid and mid in passage_index:
            direct = passage_index[mid]
            strategy = "market_id" if name_candidate == market_name else "alias"
            direct_ids = frozenset(
                sp.get("passage_id") or sp.get("page", "") for sp in direct
            )
            return direct, strategy, direct_ids

    # Strategy 3: source_refs page-number fallback with name-overlap filter
    source_refs = list(gold_market.get("source_refs") or [])
    if source_refs:
        filtered: list[dict] = []
        for ref in source_refs:
            for sp in page_to_passages.get(str(ref), []):
                quote = sp.get("quote_snippet", "")
                if _has_name_overlap(quote, market_name, aliases):
                    filtered.append(sp)
        if filtered:
            return filtered, "source_refs", frozenset()

    return [], "none", frozenset()


def _sort_passages(
    passages: list[dict],
    direct_ids: frozenset[str],
) -> list[dict]:
    """Sort passages: direct market-id matches first, then by source_role priority.

    Within each tier, passage order is stable (preserves original index).
    """
    def _key(sp: dict) -> tuple:
        pid = sp.get("passage_id") or sp.get("page", "")
        is_direct = 0 if pid in direct_ids else 1
        role_pri = _source_role_priority(sp.get("source_role", ""))
        return (is_direct, role_pri)

    return sorted(passages, key=_key)


def _validate_candidates(
    candidates: list[dict],
    page_cache_map: dict[str, dict],
    market_name: str,
) -> tuple[list[dict], list[str]]:
    """Validate each candidate against the page cache.

    Returns ``(valid_passages, drop_reasons)`` where *drop_reasons* is a list
    of human-readable strings describing each dropped passage.
    """
    valid: list[dict] = []
    reasons: list[str] = []

    for sp in candidates:
        quote = (sp.get("quote_snippet") or "").strip()
        if not quote:
            reasons.append(f"p.{sp.get('page', '?')} — empty quote")
            continue

        doc_id = sp.get("source_document_id", "")
        page_cache = page_cache_map.get(doc_id) if doc_id else None
        if page_cache is None:
            # Fall back to the first available cache when doc_id is absent
            page_cache = next((c for c in page_cache_map.values() if c is not None), None)

        if page_cache is None:
            # No cache for this doc — include with a warning (not a hard drop)
            valid.append(sp)
            continue

        try:
            page_num = int(sp.get("page", 0))
        except (ValueError, TypeError):
            reasons.append(f"p.{sp.get('page', '?')} — invalid page number")
            continue

        page_text: Optional[str] = None
        for p in (page_cache.get("pages") or []):
            if p.get("page_number") == page_num:
                page_text = p.get("text", "")
                break

        if page_text is None:
            reasons.append(f"p.{page_num} — page not in cache")
            continue

        if validate_quote_on_page(quote, page_text):
            valid.append(sp)
        else:
            reasons.append(f"p.{page_num} — quote not found verbatim [{quote[:60]!r}]")

    return valid, reasons


# ---------------------------------------------------------------------------
# Core repair function
# ---------------------------------------------------------------------------

def repair_gold_passages(
    gold_yaml: dict,
    draft_record: dict,
    page_cache_map: Optional[dict[str, dict]] = None,
    max_passages: int = 3,
) -> tuple[dict, RepairReport]:
    """Replace linked_source_passages in *gold_yaml* with verbatim draft passages.

    Parameters
    ----------
    gold_yaml:
        The gold YAML dict to repair (not mutated).
    draft_record:
        The extraction draft YAML dict providing verbatim source_passages.
    page_cache_map:
        Optional ``{doc_id: page_cache}`` mapping used to validate candidates
        against PDF text.  When ``None``, validation is skipped and all
        matching candidates are included (useful for tests without real PDFs).
    max_passages:
        Maximum number of validated passages to include per market (default 3).

    Returns
    -------
    (repaired_gold, repair_report)
        *repaired_gold* is a deep copy of *gold_yaml* with passages replaced.
        *repair_report* summarises outcomes per market.
    """
    case_id = gold_yaml.get("case_id", "unknown")
    report = RepairReport(case_id=case_id)

    # Build draft indexes
    draft_passages = draft_record.get("source_passages") or []
    passage_index = _build_passage_index(draft_passages)
    name_to_id = _build_market_id_index(draft_record)
    page_to_passages = _build_page_to_passages(draft_passages)

    repaired = copy.deepcopy(gold_yaml)

    for list_key in ("product_markets_considered", "geographic_markets_considered"):
        for market in (repaired.get(list_key) or []):
            market_name = market.get("name", "")
            market_type = market.get("market_type", "")

            candidates, strategy, direct_ids = _find_draft_passages(
                market, passage_index, name_to_id, page_to_passages
            )

            if not candidates:
                _clear_passages(market, "source passage requires manual selection")
                report.markets_repaired.append(MarketRepairResult(
                    market_name=market_name,
                    market_type=market_type,
                    passages_replaced=0,
                    passages_cleared=1,
                    passages_dropped=0,
                    match_strategy="none",
                ))
                continue

            # Sort: direct matches first, then by source_role priority
            candidates = _sort_passages(candidates, direct_ids)

            # Validate against page cache (when available)
            dropped_reasons: list[str] = []
            if page_cache_map is not None:
                candidates, dropped_reasons = _validate_candidates(
                    candidates, page_cache_map, market_name
                )

            if not candidates:
                _clear_passages(
                    market,
                    "all candidate passages failed quote validation — manual selection required",
                )
                report.markets_repaired.append(MarketRepairResult(
                    market_name=market_name,
                    market_type=market_type,
                    passages_replaced=0,
                    passages_cleared=1,
                    passages_dropped=len(dropped_reasons),
                    match_strategy=strategy,
                    dropped_reasons=dropped_reasons,
                ))
                continue

            # Cap at max_passages
            candidates = candidates[:max_passages]

            # Build linked_source_passages from validated candidates
            linked: list[dict] = []
            for sp in candidates:
                linked.append({
                    "passage_id":         sp.get("passage_id", ""),
                    "source_document_id": sp.get("source_document_id", ""),
                    "page":               sp.get("page", ""),
                    "quote_snippet":      _FoldedStr(sp.get("quote_snippet") or ""),
                    "extraction_method":  sp.get("extraction_method", ""),
                    "review_status":      sp.get("review_status", "unreviewed"),
                    "source_summary":     _FoldedStr(
                        _get_existing_summary(market, sp.get("page", ""))
                    ),
                })

            market["linked_source_passages"] = linked
            market["reviewer_notes"] = _FoldedStr(market.get("reviewer_notes") or "")

            report.markets_repaired.append(MarketRepairResult(
                market_name=market_name,
                market_type=market_type,
                passages_replaced=len(linked),
                passages_cleared=0,
                passages_dropped=len(dropped_reasons),
                match_strategy=strategy,
                dropped_reasons=dropped_reasons,
            ))

    return repaired, report


def _clear_passages(market: dict, note: str) -> None:
    """Clear linked_source_passages and append *note* to reviewer_notes."""
    market["linked_source_passages"] = []
    existing = (market.get("reviewer_notes") or "").strip()
    if note not in existing:
        market["reviewer_notes"] = _FoldedStr(
            f"{existing}\n{note}".strip()
        )


def _get_existing_summary(market: dict, page: str) -> str:
    """Return any existing source_summary for the passage on *page* in *market*."""
    for p in (market.get("linked_source_passages") or []):
        if str(p.get("page", "")) == str(page):
            return (p.get("source_summary") or "").strip()
    return ""


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _load_page_cache_map(
    cache_dir: Path,
    gold_yaml: dict,
    draft_record: dict,
) -> dict[str, Optional[dict]]:
    """Load page caches for all source_documents in gold or draft."""
    doc_ids: set[str] = set()
    for record in (gold_yaml, draft_record):
        for doc in (record.get("source_documents") or []):
            did = doc.get("doc_id", "")
            if did:
                doc_ids.add(did)
    return {did: load_cache(did, cache_dir) for did in doc_ids}


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Repair gold YAML linked_source_passages with verbatim "
            "quote_snippets from the extraction draft"
        )
    )
    parser.add_argument("--gold-yaml",  required=True, help="Gold YAML to repair")
    parser.add_argument("--draft-yaml", required=True, help="Extraction draft YAML")
    parser.add_argument(
        "--report-json", default=None,
        help="Extraction report JSON (reserved for future use)",
    )
    parser.add_argument(
        "--output-yaml", default=None,
        help="Write repaired YAML to this path (required unless --in-place)",
    )
    parser.add_argument(
        "--in-place", action="store_true",
        help="Overwrite the gold file in place",
    )
    parser.add_argument(
        "--cache-dir", default=None,
        help=(
            "PDF page cache directory.  When provided, each candidate passage "
            "is validated against cached page text before inclusion.  "
            f"Default: {DEFAULT_CACHE_DIR}"
        ),
    )
    parser.add_argument(
        "--max-passages-per-market", type=int, default=3, metavar="N",
        help="Maximum validated passages to keep per market (default: 3)",
    )
    args = parser.parse_args()

    if not args.output_yaml and not args.in_place:
        print("ERROR: provide --output-yaml <path> or --in-place", file=sys.stderr)
        return 1
    if args.output_yaml and args.in_place:
        print("ERROR: --output-yaml and --in-place are mutually exclusive", file=sys.stderr)
        return 1

    gold_path = Path(args.gold_yaml)
    draft_path = Path(args.draft_yaml)
    output_path = gold_path if args.in_place else Path(args.output_yaml)

    gold_yaml, err = load_gold_yaml(gold_path)
    if err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 1

    try:
        with open(draft_path, encoding="utf-8") as fh:
            draft_record = yaml.safe_load(fh)
    except (yaml.YAMLError, OSError) as exc:
        print(f"ERROR: Cannot load draft YAML '{draft_path}': {exc}", file=sys.stderr)
        return 1

    # Build page cache map if --cache-dir was provided
    page_cache_map: Optional[dict] = None
    if args.cache_dir:
        cache_dir = Path(args.cache_dir)
        page_cache_map = _load_page_cache_map(cache_dir, gold_yaml, draft_record)
        loaded = sum(1 for v in page_cache_map.values() if v is not None)
        print(f"Cache: {loaded}/{len(page_cache_map)} doc(s) loaded from {cache_dir}")

    repaired, repair_report = repair_gold_passages(
        gold_yaml, draft_record, page_cache_map, args.max_passages_per_market
    )

    print(f"\nRepair: {repair_report.case_id}")
    for r in repair_report.markets_repaired:
        tag = f"[{r.market_type[:3]}]"
        if r.match_strategy == "none":
            print(f"  {tag} {r.market_name!r:48s}  CLEARED (no draft passage)")
        else:
            drop_note = f"  dropped={r.passages_dropped}" if r.passages_dropped else ""
            print(
                f"  {tag} {r.market_name!r:48s}  "
                f"{r.passages_replaced} passage(s) via {r.match_strategy}{drop_note}"
            )
            for reason in r.dropped_reasons:
                print(f"       DROP: {reason}")

    print(
        f"\nTotal: replaced={repair_report.total_replaced}  "
        f"cleared={repair_report.total_cleared}  "
        f"dropped={repair_report.total_dropped}"
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as fh:
        gold_yaml_dump(repaired, fh)
    print(f"\nRepaired gold written: {output_path}")

    _, reload_err = load_gold_yaml(output_path)
    if reload_err:
        print(f"ERROR: repaired file failed to reload: {reload_err}", file=sys.stderr)
        return 1
    print("Post-repair YAML parse: OK")

    if repair_report.total_cleared > 0:
        print(
            f"\nWARN: {repair_report.total_cleared} market(s) cleared — "
            "check reviewer_notes for details.",
            file=sys.stderr,
        )
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
