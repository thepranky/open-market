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

    .venv/bin/python scripts/cases/create_gold_draft.py \\
        --case-id eu_google_fitbit_2021 \\
        --draft-yaml ../../data/drafts/eu/google_fitbit_2021.draft.yaml \\
        --report-json ../../data/source_text/google_fitbit_extraction_report.json \\
        --output-gold-yaml ../../data/evals/gold/eu_google_fitbit_2021.gold.yaml

    # Include context-only markets as well
    .venv/bin/python scripts/cases/create_gold_draft.py \\
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

_API_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_API_DIR))

_EVALS_DIR = Path(__file__).resolve().parents[4] / "data" / "evals"


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


def _normalize_market_name(name: str) -> str:
    """Normalise a market name for exact matching: lowercase, trim, collapse whitespace."""
    return " ".join(name.lower().split())


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
# Auto-selection scoring
# ---------------------------------------------------------------------------

# Source role strength — values are EU competition-law procedure roles, not market terms.
_ROLE_SCORES: dict[str, float] = {
    "commission_conclusion":       1.0,
    "commission_assessment":       0.8,
    "commission_precedent":        0.7,
    "market_investigation_result": 0.6,
    "notifying_party_view":        0.4,
    "background":                  0.2,
    "context":                     0.2,
}
_ROLE_DEFAULT_SCORE: float = 0.3

# Market importance values as used in the draft schema.
_IMPORTANCE_SCORES: dict[str, float] = {
    "core_assessed":       1.0,
    "assessed_no_overlap": 0.7,
    "assessed_background": 0.4,
    "context_background":  0.2,
}
_IMPORTANCE_DEFAULT_SCORE: float = 0.5

# Definition status values — generic Commission outcome vocabulary.
_DEFINITION_STATUS_SCORES: dict[str, float] = {
    "defined":              1.0,
    "left_open":            0.9,
    "possible_segmentation": 0.8,
    "considered":           0.6,
    "not_defined":          0.4,
}
_DEFINITION_STATUS_DEFAULT_SCORE: float = 0.5

# Promotion-plan category review-worthiness — how useful each category is for a review set.
_CATEGORY_REVIEW_SCORES: dict[str, float] = {
    "uncertain_markets":         1.0,
    "safe_to_promote":           0.9,
    "manual_review":             0.8,
    "manual_review_geo_pairing": 0.7,
    "hold_pending_source_check": 0.6,
    "context_only":              0.2,
}
_CATEGORY_DEFAULT_SCORE: float = 0.5

# context_only is excluded from auto-selection unless no better candidates exist.
_AUTO_LOW_SIGNAL_CATEGORIES: frozenset[str] = frozenset({"context_only"})

# ---------------------------------------------------------------------------
# Pairing and centrality signals
# ---------------------------------------------------------------------------

# Generic linguistic / market-structure tokens stripped before pairing comparison.
# No industry-specific terms; only structural vocabulary that appears in any
# competition-law market name regardless of sector.
_PAIRING_STOPWORDS: frozenset[str] = frozenset({
    # conjunctions / prepositions
    "and", "or", "for", "the", "of", "in", "a", "an", "to", "by",
    "with", "as", "at", "on", "is", "are", "was", "were", "not",
    # generic market-structure terms that appear in almost every name
    "market", "markets", "overall", "total", "broader", "narrower",
    "primary", "secondary", "possible", "potential",
    "relevant", "defined", "definition", "scope", "segment", "segments",
    "supply", "demand",
    # generic geographic / jurisdictional qualifiers
    "national", "regional", "worldwide", "global", "domestic",
    "geographic", "geography", "geographical",
    # generic product/service qualifiers
    "product", "products", "service", "services",
    # generic assessment language
    "considered", "assessed", "possible", "separate",
    # parenthetical / abbreviation fragments that survive splitting
    "vs", "ie", "eg",
})
_PAIRING_MIN_TOKEN_LEN: int = 4  # tokens shorter than this are never significant
_PAIRING_BONUS_WEIGHT: float = 0.40   # max score added when a product/geo pair is detected
_CENTRALITY_BONUS_WEIGHT: float = 0.25  # max score from source_refs centrality signal
_CENTRALITY_REF_SCALE: float = 8.0     # source_ref count that saturates the centrality bonus
_DIVERSITY_SOFT_BONUS: float = 0.25    # added to effective score for different-status entries


_PAIRING_SPLIT_RE: re.Pattern = re.compile(r"[\s\-–—/,;:()\[\]]+")


def _pairing_token_set(name: str) -> frozenset[str]:
    """Return the set of significant tokens from a market name for pairing comparison.

    Tokens shorter than ``_PAIRING_MIN_TOKEN_LEN`` and tokens in
    ``_PAIRING_STOPWORDS`` are excluded.  All remaining tokens are lowercased.
    No industry-specific filtering is applied.
    """
    tokens: set[str] = set()
    for tok in _PAIRING_SPLIT_RE.split(name.lower()):
        tok = tok.strip(".'\"")
        if len(tok) >= _PAIRING_MIN_TOKEN_LEN and tok not in _PAIRING_STOPWORDS:
            tokens.add(tok)
    return frozenset(tokens)


def _pairing_overlap(name_a: str, name_b: str) -> float:
    """Return a pairing signal in [0, 1] between two market names.

    Uses recall from the smaller token set: ``|intersection| / min(|A|, |B|)``.
    This answers "does the smaller name's core concept appear in the larger
    name?" — a high recall score means one market name is contained in the
    other, which is the dominant pairing pattern (geo scope of the same product
    market shares the product market's significant tokens).

    Returns 0.0 if either name yields an empty significant-token set.
    """
    set_a = _pairing_token_set(name_a)
    set_b = _pairing_token_set(name_b)
    if not set_a or not set_b:
        return 0.0
    intersection = set_a & set_b
    if not intersection:
        return 0.0
    return len(intersection) / min(len(set_a), len(set_b))


def _max_pairing_signal(entry: dict, others: list[tuple[float, dict, str]]) -> float:
    """Return the maximum pairing signal this entry has with any entry in ``others``.

    Checks (in priority order):
    1. ``market_group`` equality — authoritative pairing when present.
    2. Name token overlap via ``_pairing_overlap``.

    Both checks are neutral: no industry-specific keywords.
    """
    name = entry.get("name") or ""
    grp = entry.get("market_group")
    best: float = 0.0
    for _, other_entry, _ in others:
        # market_group match → perfect pair
        other_grp = other_entry.get("market_group")
        if grp and other_grp and grp == other_grp:
            return 1.0
        best = max(best, _pairing_overlap(name, other_entry.get("name") or ""))
    return best


def _score_candidate(
    entry: dict,
    category: str,
    raw_passages: list[dict],
) -> float:
    """Score a candidate for auto review-set selection using source-neutral signals.

    All signal names are drawn from EU competition-law procedure vocabulary or
    generic schema fields — no industry-specific terms.

    Score components (max 10.25):
      3.00 × has_linked_passages      — binary; unsourced candidates are strongly downranked
      2.00 × passage_count_score      — more passages → higher confidence
      2.00 × source_role_strength     — commission_conclusion > commission_assessment > background
      1.50 × importance_score         — core_assessed preferred
      1.00 × definition_status_score  — defined / left_open / possible_segmentation preferred
      0.50 × category_score           — uncertain_markets most review-worthy
      0.25 × centrality_score         — source_refs count from report; more refs → more central
    Pairing bonus (up to 0.40) is applied externally in ``_auto_select_review_set``.
    """
    has_passages = 1.0 if raw_passages else 0.0
    passage_count_score = min(len(raw_passages) / 3.0, 1.0)

    role_score: float = 0.0
    for sp in raw_passages:
        role = sp.get("source_role") or ""
        role_score = max(role_score, _ROLE_SCORES.get(role, _ROLE_DEFAULT_SCORE))

    importance = (entry.get("importance") or entry.get("market_importance") or "")
    importance_score = _IMPORTANCE_SCORES.get(importance, _IMPORTANCE_DEFAULT_SCORE)

    def_status = entry.get("definition_status") or ""
    status_score = _DEFINITION_STATUS_SCORES.get(def_status, _DEFINITION_STATUS_DEFAULT_SCORE)

    cat_score = _CATEGORY_REVIEW_SCORES.get(category, _CATEGORY_DEFAULT_SCORE)

    # Centrality: number of source pages cited in the report for this candidate.
    # More source references → candidate is discussed more broadly → more central.
    source_refs_count = len(entry.get("source_refs") or [])
    centrality_score = min(source_refs_count / _CENTRALITY_REF_SCALE, 1.0)

    return (
        3.0 * has_passages
        + 2.0 * passage_count_score
        + 2.0 * role_score
        + 1.5 * importance_score
        + 1.0 * status_score
        + 0.5 * cat_score
        + _CENTRALITY_BONUS_WEIGHT * centrality_score
    )


def _select_with_diversity(
    scored: list[tuple[float, dict, str]],
    count: int,
) -> list[tuple[float, dict, str]]:
    """Select up to ``count`` entries with a soft diversity preference.

    For each slot after the first, entries whose ``definition_status`` differs
    from all already-selected statuses receive a soft bonus of
    ``_DIVERSITY_SOFT_BONUS`` when computing the effective score.  The entry
    with the highest *effective* score wins the slot.

    Because the bonus is soft (not a hard ordering), a same-status entry can
    still win if its base score exceeds the different-status candidate's score
    by more than ``_DIVERSITY_SOFT_BONUS``.  This lets pairing/centrality
    bonuses (which are larger) override diversity when warranted, while
    diversity still breaks genuine ties.
    """
    if not scored or count <= 0:
        return []

    selected = [scored[0]]
    selected_statuses: set[str] = {scored[0][1].get("definition_status") or ""}
    remaining = list(scored[1:])

    while len(selected) < count and remaining:
        def _effective(item: tuple[float, dict, str]) -> float:
            s, e, _ = item
            status = e.get("definition_status") or ""
            bonus = _DIVERSITY_SOFT_BONUS if status not in selected_statuses else 0.0
            return s + bonus

        best = max(remaining, key=_effective)
        selected.append(best)
        remaining.remove(best)
        selected_statuses.add(best[1].get("definition_status") or "")

    return selected


def _auto_select_review_set(
    candidates: dict,
    passage_index: dict[str, list[dict]],
    name_to_id: dict[str, str],
    product_count: int,
    geographic_count: int,
    excluded_norm_names: frozenset[str],
) -> tuple[list[tuple[float, dict, str]], list[tuple[float, dict, str]]]:
    """Score and select candidates for an auto review set.

    Uses a two-pass approach so that geographic pairing bonuses for geo
    candidates are computed against the *already-selected* product markets:

    Pass 1 — score all product candidates:
      base score (``_score_candidate``) + pairing bonus against all geo
      candidates.  Select top ``product_count`` via ``_select_with_diversity``.

    Pass 2 — score all geographic candidates:
      base score + pairing bonus against the *selected* product markets.
      The pairing bonus here rewards geo candidates that form a product/geo
      pair with an already-chosen product market.  Select top
      ``geographic_count`` by final score.

    Candidates in ``_AUTO_LOW_SIGNAL_CATEGORIES`` are held back as fallback.
    """
    raw_products:  list[tuple[float, dict, str]] = []  # (base_score, entry, category)
    raw_geos:      list[tuple[float, dict, str]] = []
    low_products:  list[tuple[float, dict, str]] = []
    low_geos:      list[tuple[float, dict, str]] = []

    for category, entries in candidates.items():
        if not isinstance(entries, list):
            continue
        is_low = category in _AUTO_LOW_SIGNAL_CATEGORIES
        for entry in entries:
            market_name = entry.get("name") or ""
            market_type = entry.get("market_type") or "product"
            norm = _normalize_market_name(market_name)
            if norm in excluded_norm_names:
                continue
            market_id = name_to_id.get(market_name.lower().strip(), "")
            raw_passages = passage_index.get(market_id, []) if market_id else []
            base = _score_candidate(entry, category, raw_passages)
            tup = (base, entry, category)
            if market_type == "geographic":
                (low_geos if is_low else raw_geos).append(tup)
            else:
                (low_products if is_low else raw_products).append(tup)

    # ---- Pass 1: product selection with geo-pairing bonus ----------------
    all_geos_for_pairing = raw_geos + low_geos  # use all geo candidates for product pairing
    scored_products: list[tuple[float, dict, str]] = [
        (base + _PAIRING_BONUS_WEIGHT * _max_pairing_signal(entry, all_geos_for_pairing),
         entry, category)
        for base, entry, category in raw_products
    ]
    scored_products.sort(key=lambda x: -x[0])
    selected_products = _select_with_diversity(scored_products, product_count)
    if len(selected_products) < product_count:
        # Fallback: low-signal products (with pairing bonus applied)
        low_scored = [
            (base + _PAIRING_BONUS_WEIGHT * _max_pairing_signal(entry, all_geos_for_pairing),
             entry, category)
            for base, entry, category in low_products
        ]
        low_scored.sort(key=lambda x: -x[0])
        selected_products.extend(low_scored[: product_count - len(selected_products)])

    # ---- Pass 2: geo selection with product-pairing bonus ----------------
    scored_geos: list[tuple[float, dict, str]] = [
        (base + _PAIRING_BONUS_WEIGHT * _max_pairing_signal(entry, selected_products),
         entry, category)
        for base, entry, category in raw_geos
    ]
    scored_geos.sort(key=lambda x: -x[0])
    selected_geos = scored_geos[:geographic_count]
    if len(selected_geos) < geographic_count:
        low_geo_scored = [
            (base + _PAIRING_BONUS_WEIGHT * _max_pairing_signal(entry, selected_products),
             entry, category)
            for base, entry, category in low_geos
        ]
        low_geo_scored.sort(key=lambda x: -x[0])
        selected_geos.extend(low_geo_scored[: geographic_count - len(selected_geos)])

    return selected_products, selected_geos


# ---------------------------------------------------------------------------
# Core gold-draft builder
# ---------------------------------------------------------------------------

def _create_gold_draft(
    case_id: str,
    draft_record: dict,
    report: dict,
    include_context_only: bool = False,
    include_hold_pending: bool = False,
    explicit_names: frozenset[str] = frozenset(),
    explicit_ids: frozenset[str] = frozenset(),
    auto_select: bool = False,
    review_product_count: int = 2,
    review_geographic_count: int = 1,
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

    Selection modes (mutually exclusive for Phase 1)
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    Default (``auto_select=False``):
        Phase 1 — promotion-filter categories (safe_to_promote, uncertain_markets,
        manual_review, manual_review_geo_pairing; optionally context_only /
        hold_pending_source_check via the include flags).
        Phase 2 — explicit name / id overrides.

    Auto-select (``auto_select=True``):
        Phase 1 — source-scored ranking across all candidates; picks the top
        ``review_product_count`` product markets and ``review_geographic_count``
        geographic markets.  context_only is used only as a fallback.
        Phase 2 — explicit name / id overrides (always applied regardless of mode).

    All auto-selected entries carry ``gold_selection_reason: "auto_review_set"``
    and ``gold_selection_score`` (numeric).  They are never marked reviewed.

    Explicit includes
    ~~~~~~~~~~~~~~~~~
    ``explicit_names`` and ``explicit_ids`` add markets by name (case-insensitive,
    whitespace-normalised) or draft market_id regardless of their promotion category.
    Already-included markets are not duplicated.  Unmatched requests print a warning
    to stderr.
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

    # Determine default included categories
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

    # ---- normalise explicit include sets ------------------------------------
    norm_explicit_names: frozenset[str] = frozenset(
        _normalize_market_name(n) for n in explicit_names
    )

    # ---- category → action mapping ----------------------------------------
    category_to_action = {
        "safe_to_promote":           "promote_to_canonical",
        "uncertain_markets":         "promote_with_uncertainty",
        "context_only":              "keep_as_context_only",
        "hold_pending_source_check": "hold_pending_source_check",
        "manual_review":             "manual_review",
        "manual_review_geo_pairing": "manual_review_geo_pairing",
    }

    # ---- build market lists -----------------------------------------------
    gold_markets: dict[str, list] = {
        "product_markets_considered": [],
        "geographic_markets_considered": [],
    }
    included_norm_names: set[str] = set()   # deduplication by normalised name
    matched_norm_names: set[str] = set()    # tracks which explicit names were found
    matched_ids: set[str] = set()           # tracks which explicit ids were found

    def _append_entry(
        market_name: str,
        market_type: str,
        entry: dict,
        category: str,
        selection_reason: str,
        gold_selection_score: Optional[float] = None,
    ) -> None:
        """Build and append a gold market entry; no-op if already included."""
        norm = _normalize_market_name(market_name)
        if norm in included_norm_names:
            return
        included_norm_names.add(norm)

        list_key = (
            "product_markets_considered"
            if market_type == "product"
            else "geographic_markets_considered"
        )
        market_id = name_to_id.get(market_name.lower().strip(), "")
        raw_passages = passage_index.get(market_id, []) if market_id else []
        linked: list[dict] = []
        for sp in raw_passages:
            linked.append({
                "passage_id":         sp.get("passage_id", ""),
                "source_document_id": sp.get("source_document_id", ""),
                "page":               sp.get("page", ""),
                # Block scalar: never altered, always parse-safe regardless
                # of colons, semicolons, or parenthetical list markers.
                "quote_snippet":      _FoldedStr(sp.get("quote_snippet") or ""),
                "extraction_method":  sp.get("extraction_method", ""),
                "review_status":      sp.get("review_status", "unreviewed"),
                # Placeholder: human explanation goes here, NOT in quote_snippet.
                "source_summary":     _FoldedStr(""),
            })

        reviewer_notes_str = "source passage needs review" if not linked else ""

        market_entry: dict = {
            "name":                       market_name,
            "market_type":                market_type,
            "expected_definition_status": entry.get("definition_status", ""),
            "expected_promotion_action":  category_to_action.get(category, "manual_review"),
            "importance":                 entry.get("importance", ""),
            # Fine-grained grouping: leave null unless reviewer fills it in.
            "market_group":               None,
            "linked_source_passages":     linked,
            # aliases is reviewer-approved only; alias_candidates from passages only.
            "aliases":                    [],
            "alias_candidates":           _build_alias_candidates(market_name, raw_passages),
            # Why this entry was included in the gold draft.
            "gold_selection_reason":      selection_reason,
            # Block scalar: review notes must not contain source text.
            "reviewer_notes":             _FoldedStr(reviewer_notes_str),
            "reviewed":                   False,
        }

        if gold_selection_score is not None:
            market_entry["gold_selection_score"] = round(gold_selection_score, 3)

        # Preserve explicit source_refs when passages could not be resolved.
        if entry.get("source_refs") and not linked:
            market_entry["source_refs"] = entry["source_refs"]

        gold_markets[list_key].append(market_entry)

    # ---- Phase 1: populate base entries ----------------------------------
    if auto_select:
        # Auto-select: score all candidates and pick the top N per type.
        # Explicit includes (Phase 2) will deduplicate against these.
        product_sel, geo_sel = _auto_select_review_set(
            candidates, passage_index, name_to_id,
            review_product_count, review_geographic_count,
            excluded_norm_names=frozenset(),  # nothing excluded yet
        )
        for score, entry, category in product_sel:
            _append_entry(
                entry.get("name", ""), "product", entry, category,
                "auto_review_set", gold_selection_score=score,
            )
        for score, entry, category in geo_sel:
            _append_entry(
                entry.get("name", ""), "geographic", entry, category,
                "auto_review_set", gold_selection_score=score,
            )
    else:
        # Default mode: include based on promotion-filter categories.
        for category in included_categories:
            for entry in (candidates.get(category) or []):
                _append_entry(
                    entry.get("name", ""),
                    entry.get("market_type", ""),
                    entry,
                    category,
                    "default_promotion_filter",
                )

    # ---- Phase 2: explicit includes from all report categories -----------
    if norm_explicit_names or explicit_ids:
        for category, entries in candidates.items():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                market_name = entry.get("name", "")
                market_type = entry.get("market_type", "")
                norm_name = _normalize_market_name(market_name)
                resolved_id = name_to_id.get(market_name.lower().strip(), "")

                matched_reason: Optional[str] = None
                if norm_name in norm_explicit_names:
                    matched_reason = "explicit_market_name"
                    matched_norm_names.add(norm_name)
                elif resolved_id and resolved_id in explicit_ids:
                    matched_reason = "explicit_market_id"
                    matched_ids.add(resolved_id)

                if matched_reason:
                    _append_entry(market_name, market_type, entry, category, matched_reason)

    # ---- Warn about unmatched explicit requests --------------------------
    unmatched_names = norm_explicit_names - matched_norm_names
    for norm_name in sorted(unmatched_names):
        print(
            f"WARNING: --include-market-name did not match any market: {norm_name!r}",
            file=sys.stderr,
        )
    unmatched_ids = explicit_ids - matched_ids
    for mid in sorted(unmatched_ids):
        print(
            f"WARNING: --include-market-id did not match any market: {mid!r}",
            file=sys.stderr,
        )

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
    parser.add_argument(
        "--include-market-name",
        action="append",
        dest="include_market_names",
        default=[],
        metavar="NAME",
        help=(
            "Include a specific market by name (case-insensitive, exact after whitespace "
            "normalisation) regardless of its promotion category. Repeatable."
        ),
    )
    parser.add_argument(
        "--include-market-id",
        action="append",
        dest="include_market_ids",
        default=[],
        metavar="ID",
        help=(
            "Include a specific market by its draft market_id regardless of its promotion "
            "category. Repeatable."
        ),
    )
    parser.add_argument(
        "--auto-select-review-set",
        action="store_true",
        dest="auto_select",
        help=(
            "Automatically select a small review set ranked by source-signal quality. "
            "Replaces the default promotion-filter selection. Explicit includes still apply."
        ),
    )
    parser.add_argument(
        "--review-product-count",
        type=int,
        default=2,
        metavar="N",
        help="Number of product markets to auto-select (default: 2). Used with --auto-select-review-set.",
    )
    parser.add_argument(
        "--review-geographic-count",
        type=int,
        default=1,
        metavar="N",
        help="Number of geographic markets to auto-select (default: 1). Used with --auto-select-review-set.",
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
        explicit_names=frozenset(args.include_market_names),
        explicit_ids=frozenset(args.include_market_ids),
        auto_select=args.auto_select,
        review_product_count=args.review_product_count,
        review_geographic_count=args.review_geographic_count,
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
