#!/usr/bin/env python3
"""
extract_case_from_source.py — source-first extraction/reconciliation for CompMap.

Loads the existing PDF text cache for a case, extracts a fresh draft CaseRecord
via Claude, then reconciles the draft against the existing YAML.

The output is always a draft + reconciliation report.  It never overwrites
the canonical YAML.  Draft outputs go under data/drafts/, never data/cases/.

Usage:
    cd apps/api

    # Full extraction with Claude:
    .venv/bin/python scripts/extract_case_from_source.py \\
        --case-id eu_google_fitbit_2021 \\
        --output ../../data/drafts/eu/google_fitbit_2021.draft.yaml \\
        --report-json ../../data/source_text/google_fitbit_extraction_report.json

    # Section-analysis only (no API call):
    .venv/bin/python scripts/extract_case_from_source.py \\
        --case-id eu_google_fitbit_2021 --no-claude
"""

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

import yaml

_API_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_API_DIR))
sys.path.insert(0, str(Path(__file__).parent))

from app.utils.pdf_extractor import DEFAULT_CACHE_DIR, iter_pages, load_cache
from check_source_integrity import quote_found_in_text
from repair_source_passages import _extract_section_map, _is_toc_page

_CASES_DIR = Path(__file__).resolve().parents[3] / "data" / "cases"
_DRAFTS_DIR = Path(__file__).resolve().parents[3] / "data" / "drafts"


def _resolve_canonical_yaml(case_id: str, cases_dir: Path) -> Optional[Path]:
    """Return the canonical YAML path for *case_id*, or None if not found.

    Only accepts files named exactly ``{case_id}.yaml``.  Files with ``.draft``
    anywhere in the path (stem or directory components) are always skipped —
    this prevents generated extraction drafts stored inside data/cases/ from
    being mistaken for canonical input records.
    """
    for p in cases_dir.rglob(f"{case_id}.yaml"):
        if p.stem != case_id:
            continue
        if any(".draft" in part for part in p.parts):
            continue
        return p
    return None

_MAX_CHUNK_PAGES = 12    # max PDF pages per section chunk
_MAX_INPUT_PAGES = 80    # hard cap on pages sent to Claude per call
_SIMILARITY_MATCH = 0.75  # "same proposition"
_SIMILARITY_RENAME = 0.45  # "similar — consider renaming"

_DEBUG_DIR = Path(__file__).resolve().parents[3] / "data" / "source_text" / "debug"

_VALID_OUTCOMES: frozenset[str] = frozenset({
    "cleared", "cleared_with_conditions", "blocked", "pending", "unknown",
})

# Precise market definition status values (old values kept for backward compat).
_VALID_MARKET_STATUSES: frozenset[str] = frozenset({
    "defined", "left_open", "discussed", "segmented", "unknown",      # legacy
    "considered", "not_conclusive", "possible_segmentation", "precedent_only",  # new
})

# Passage source-role classification values.
_VALID_SOURCE_ROLES: frozenset[str] = frozenset({
    "commission_assessment", "conclusion", "precedent",
    "notifying_party_view", "market_investigation", "background",
})

# Market importance classification — reviewable at canonical-merge time.
_VALID_MARKET_IMPORTANCE: frozenset[str] = frozenset({
    "core_assessed",        # Commission formally assessed this as a key relevant market
    "assessed_no_overlap",  # Assessed but parties do not overlap here
    "ancillary",            # Related market mentioned but not the primary focus
    "possible_segmentation",# Commission considered segmentation but left it open
    "precedent_only",       # Referenced from prior cases only, not assessed here
    "background",           # Mentioned in overview/background only, no formal analysis
    "incomplete_source",    # Conclusion expected but absent from supplied text chunks
})

# Reconciliation group labels — used for structured output grouping.
_RECON_GROUP: dict[str, str] = {
    "supported_as_is":  "matched",
    "should_be_renamed": "likely_rename",
    "unsupported_remove": "out_of_scope",
    "new_from_source":  "candidate_addition",
}

# Quote quality: natural sentence/excerpt boundary characters at end of quote.
_QUOTE_NATURAL_END_RE = re.compile(r'[.!?;:"\')\]]\s*$')
# A sentence break is a terminator followed by optional closers and whitespace then more content.
_QUOTE_SENTENCE_BREAK_RE = re.compile(r'[.!?]["\')\]]*\s+\S')
_QUOTE_MIN_TRUNCATION_LEN = 50  # quotes shorter than this are never flagged

# Strength ordering for geographic market definition statuses (higher = stronger).
_GEO_STATUS_STRENGTH: dict[str, int] = {
    "defined": 6, "left_open": 5, "considered": 4,
    "not_conclusive": 3, "possible_segmentation": 2, "precedent_only": 1, "unknown": 0,
}

_REQUIRED_SCHEMA_KEYS: frozenset[str] = frozenset({
    "product_markets", "geographic_markets", "theories_of_harm",
    "overall_outcome", "source_passages", "caveats",
})

# Default envelope merged under Claude's response before normalization.
# Guarantees every field exists even when Claude omits optional ones.
_DEFAULT_EXTRACTION_ENVELOPE: dict = {
    "product_markets": [],
    "geographic_markets": [],
    "theories_of_harm": [],
    "overall_outcome": "unknown",
    "source_passages": [],
    "caveats": [],
    "background_concepts": [],
    "case_history_events": [],
    "remedies": [],
}

# All list fields the extraction schema expects (including optional extras Claude may add).
_EXPECTED_LIST_FIELDS: tuple[str, ...] = (
    "product_markets",
    "geographic_markets",
    "theories_of_harm",
    "caveats",
    "background_concepts",
    "remedies",
    "source_passages",
    "case_history_events",
)

# Section-path keywords for each focused extraction mode.
# Matched case-insensitively against the full section_path string.
_FOCUS_TERMS: dict[str, tuple[str, ...]] = {
    "market_definition": (
        "relevant market",
        "market definition",
        "product market",
        "geographic market",
    ),
    "theories": (
        "competitive assessment",
        "horizontal",
        "vertical",
        "conglomerate",
        "data effect",
        "foreclosure",
        "effects on competition",
        "competitive effect",
    ),
    "remedies": (
        "commitment",
        "remedy",
        "remedies",
        "condition",
        "behavioural",
        "structural",
        "divestiture",
        "divestment",
        "conclusion",
    ),
    "case_history": (
        "procedure",
        "procedural",
        "background",
        "notification",
        "referral",
        "complaint",
        "history",
        "chronology",
        "article 22",
        "phase ii",
    ),
}

# Strings Claude sometimes returns instead of [] when nothing was found.
_NULL_LIKE_STRINGS: frozenset[str] = frozenset({
    "", "not found", "none", "n/a", "na", "null", "[]",
})

# Section-path terms that flag a chunk as relevant for market/theory extraction.
_RELEVANT_TERMS: frozenset[str] = frozenset({
    "market", "geographic", "product", "definition", "competitive",
    "assessment", "effects", "foreclosure", "theory", "harm",
    "commitment", "remedy", "condition", "advertising", "data",
    "wearable", "wear", "horizontal", "vertical", "conglomerate",
    "fitness", "digital", "online",
})

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ChunkInfo:
    """A section-bounded group of consecutive pages from one source document."""
    chunk_id: str
    section_path: str
    pages: list[dict]           # [{"page_number": N, "text": "..."}] — original; used for validation
    source_document_id: str = ""
    trimmed_pages: list[dict] = field(default_factory=list)  # prefix-trimmed; used for prompt/display
    effective_prefix: Optional[str] = None  # overrides section_path for batch grouping (spillover chunks)

    @property
    def page_numbers(self) -> list[int]:
        return [p["page_number"] for p in self.pages]

    @property
    def page_range(self) -> str:
        nums = self.page_numbers
        if not nums:
            return "?"
        return f"pp.{min(nums)}-{max(nums)}" if len(nums) > 1 else f"p.{nums[0]}"

    @property
    def full_text(self) -> str:
        """Original page text — used for quote validation."""
        return "\n\n".join(
            f"[Page {p['page_number']}]\n{p['text']}" for p in self.pages
        )

    @property
    def prompt_text(self) -> str:
        """Text for the extraction prompt — trimmed if section_prefix was applied, else full_text."""
        display_pages = self.trimmed_pages if self.trimmed_pages else self.pages
        return "\n\n".join(
            f"[Page {p['page_number']}]\n{p['text']}" for p in display_pages
        )


@dataclass
class ExtractedPassage:
    chunk_id: str
    page_number: int
    quote: str
    validated: bool = False
    source_document_id: str = ""
    rejection_reason: str = ""
    source_role: str = ""  # see _VALID_SOURCE_ROLES


@dataclass
class ExtractedMarket:
    name: str
    market_type: str          # "product" | "geographic"
    definition_status: str    # "defined" | "left_open" | "discussed" | "segmented" | "unknown"
    notes: str
    passages: list[ExtractedPassage] = field(default_factory=list)
    not_found: bool = False
    market_importance: str = ""  # one of _VALID_MARKET_IMPORTANCE; empty = unclassified


@dataclass
class ExtractedTheory:
    name: str
    theory_type: str     # "horizontal" | "vertical" | "conglomerate" | "data" | "other"
    theory_outcome: str  # "dismissed" | "upheld" | "remedied" | "unclear"
    notes: str
    passages: list[ExtractedPassage] = field(default_factory=list)
    not_found: bool = False


@dataclass
class ExtractionResult:
    product_markets: list[ExtractedMarket] = field(default_factory=list)
    geographic_markets: list[ExtractedMarket] = field(default_factory=list)
    theories: list[ExtractedTheory] = field(default_factory=list)
    overall_outcome: str = "unknown"
    caveats: list[str] = field(default_factory=list)
    background_concepts: list[str] = field(default_factory=list)
    passages_validated: int = 0
    passages_rejected: int = 0
    orphan_passages: int = 0  # source_passages not linked to any market/theory
    raw_response: str = ""
    section_label: str = ""  # set by section-batch extractor; used to scope caveats


@dataclass
class ReconciliationFinding:
    finding_type: str    # one of: supported_as_is | should_be_renamed |
    #                              unsupported_remove | new_from_source
    existing_id: str
    existing_name: str
    draft_name: str
    message: str
    similarity: float = 0.0
    group: str = ""   # "matched" | "likely_rename" | "out_of_scope" | "candidate_addition"
    # Draft market metadata — populated when the finding references a draft market.
    # Empty string / empty list when no draft market is involved (e.g. unsupported_remove).
    draft_market_type: str = ""          # "product" | "geographic" | "" for theories
    draft_market_importance: str = ""    # one of _VALID_MARKET_IMPORTANCE, or ""
    draft_definition_status: str = ""    # one of _VALID_MARKET_STATUSES, or ""
    draft_source_refs: list[str] = field(default_factory=list)  # page numbers cited


@dataclass
class SectionBatchResult:
    """Result of a single section batch extraction (one Claude call)."""
    prefix: str            # e.g. "8.6"
    section_label: str     # e.g. "8.6 Online advertising services"
    chunks: list[ChunkInfo]
    result: Optional[ExtractionResult]
    error: Optional[str]
    debug_path: Optional[Path]


@dataclass
class ExtractionReport:
    case_id: str
    yaml_path: Path
    chunks_used: list[ChunkInfo] = field(default_factory=list)
    result: Optional[ExtractionResult] = None
    findings: list[ReconciliationFinding] = field(default_factory=list)
    draft_yaml_path: Optional[Path] = None
    draft_record: Optional[dict] = None
    error: Optional[str] = None
    section_batches: list[SectionBatchResult] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Section chunking
# ---------------------------------------------------------------------------

def _is_relevant_section(section_path: str) -> bool:
    """Return True if a section is relevant for market/theory extraction."""
    lower = section_path.lower()
    return any(term in lower for term in _RELEVANT_TERMS)


def _is_focused_section(section_path: str, focus: str) -> bool:
    """Return True if the section path matches the given focus mode's keywords."""
    terms = _FOCUS_TERMS.get(focus)
    if not terms:
        return True
    lower = section_path.lower()
    return any(t in lower for t in terms)


def _build_chunks(
    page_cache: dict,
    section_map: Optional[dict[int, str]] = None,
    max_pages: int = _MAX_CHUNK_PAGES,
) -> list[ChunkInfo]:
    """
    Group pages into ordered ChunkInfo objects by section path.

    Pages with the same section_path are grouped together; large groups are
    split into sub-chunks of at most *max_pages* pages.  TOC pages are excluded.
    """
    if section_map is None:
        section_map = _extract_section_map(page_cache)

    doc_id = page_cache.get("source_document_id", "")

    # Collect non-TOC pages in order
    page_list: list[tuple[int, str, str]] = []
    for page_num, text in iter_pages(page_cache):
        if not text or _is_toc_page(text):
            continue
        section_path = section_map.get(page_num, "")
        page_list.append((page_num, text, section_path))

    # Group consecutive pages by section_path
    groups: list[tuple[str, list[dict]]] = []
    current_path: Optional[str] = None
    current_pages: list[dict] = []
    for page_num, text, section_path in page_list:
        if section_path != current_path:
            if current_pages:
                groups.append((current_path or "", current_pages))
            current_path = section_path
            current_pages = []
        current_pages.append({"page_number": page_num, "text": text})
    if current_pages:
        groups.append((current_path or "", current_pages))

    # Build ChunkInfo objects, splitting large groups
    chunks: list[ChunkInfo] = []
    for section_path, pages in groups:
        for i in range(0, len(pages), max_pages):
            sub = pages[i : i + max_pages]
            chunks.append(ChunkInfo(
                chunk_id=f"chunk_{len(chunks) + 1:03d}",
                section_path=section_path,
                pages=sub,
                source_document_id=doc_id,
            ))

    return chunks


def _select_relevant_chunks(
    chunks: list[ChunkInfo],
    max_total_pages: int = _MAX_INPUT_PAGES,
    focus: Optional[str] = None,
) -> list[ChunkInfo]:
    """
    Return relevant chunks up to *max_total_pages* total pages.

    When *focus* is set, only chunks whose section path matches that focus
    mode's keywords are included (no fallback).  Without a focus, chunks whose
    section path matches _RELEVANT_TERMS are preferred; falls back to all
    non-empty chunks when nothing matches.
    """
    if focus:
        candidates = [
            c for c in chunks if _is_focused_section(c.section_path, focus) and c.pages
        ]
    else:
        candidates = [c for c in chunks if _is_relevant_section(c.section_path) and c.pages]
        if not candidates:
            candidates = [c for c in chunks if c.pages]

    selected: list[ChunkInfo] = []
    total = 0
    for chunk in candidates:
        n = len(chunk.pages)
        if total + n > max_total_pages:
            break
        selected.append(chunk)
        total += n
    return selected


# ---------------------------------------------------------------------------
# Section-batch grouping
# ---------------------------------------------------------------------------

_SECTION_PREFIX_RE = re.compile(r'\b(\d+\.\d+)\b')

# Matches section headings like "8.6 Title", "8.6. Title", "8.6.1 Title" at start of line.
# Requires an uppercase letter to follow so footnotes ("14 July 2020") are not matched.
_SECTION_TRIM_RE = re.compile(
    r'^(\d+(?:\.\d+)+)\.?[ \t]+[A-Z]',
    re.MULTILINE,
)


def _section_batch_prefix(section_path: str) -> str:
    """Extract the X.Y numeric prefix from the most specific part of section_path.

    When section_path uses '>' to express a hierarchy (e.g. '8 Markets > 8.3 OS'),
    the LAST component is used so that '8 Markets > 8.3 OS' returns '8.3' rather
    than '8.2' (the first numeric match in the full string).
    """
    last_component = section_path.split(">")[-1].strip()
    m = _SECTION_PREFIX_RE.search(last_component)
    if m:
        return m.group(1)
    # Fall back to first top-level integer in the last component
    m2 = re.search(r'\b(\d+)\b', last_component)
    return m2.group(1) if m2 else ""


def _section_label_for_batch(prefix: str, chunks: list[ChunkInfo]) -> str:
    """Find the most specific human-readable label for a section batch prefix."""
    for chunk in chunks:
        for part in chunk.section_path.split(">"):
            part = part.strip()
            if part.startswith(prefix + " ") or part.startswith(prefix + "."):
                return part
    # Fallback: tail of first chunk's section path
    if chunks:
        path = chunks[0].section_path
        return path.split(">")[-1].strip() if ">" in path else path.strip()
    return prefix


def _group_chunks_by_section_prefix(
    chunks: list[ChunkInfo],
) -> list[tuple[str, list[ChunkInfo]]]:
    """Group chunks by their X.Y section prefix, preserving document order."""
    seen: dict[str, list[ChunkInfo]] = {}
    order: list[str] = []
    for chunk in chunks:
        prefix = chunk.effective_prefix or _section_batch_prefix(chunk.section_path)
        if prefix not in seen:
            seen[prefix] = []
            order.append(prefix)
        seen[prefix].append(chunk)
    return [(prefix, seen[prefix]) for prefix in order]


def _is_subsection_of(heading_prefix: str, target_prefix: str) -> bool:
    """Return True if heading_prefix is the target section or a subsection of it.

    e.g. _is_subsection_of("8.6",   "8.6") → True
         _is_subsection_of("8.6.1", "8.6") → True
         _is_subsection_of("8.7",   "8.6") → False
         _is_subsection_of("8.60",  "8.6") → False  (dot required)
    """
    return heading_prefix == target_prefix or heading_prefix.startswith(target_prefix + ".")


def _trim_pages_for_prefix(
    pages: list[dict],
    section_prefix: str,
) -> list[dict]:
    """Trim leading and trailing spillover from pages for the given section prefix.

    Leading: content before the first target-section heading on the first page is removed.
    Trailing: content from the first non-subsection heading onwards is removed.

    Original page dicts are NOT mutated; returns new dicts with trimmed text.

    Fallback rules when trimming produces an empty result:
    - If the first heading on the first page is a non-target sibling (e.g. the 8.3
      heading at position 0 when looking for 8.2), there is no target content here —
      return [] to signal that the chunk should be excluded.
    - Otherwise (no heading at all on the first page) the chunk is a continuation of
      the target section and the original pages are returned intact.
    """
    if not pages or not section_prefix:
        return list(pages)

    result: list[dict] = []
    found_start = False
    first_page_starts_with_sibling = False  # True when first heading is a non-target sibling

    for i, page in enumerate(pages):
        text = page["text"]
        page_num = page["page_number"]

        if not found_start:
            # Find the first heading that is the target section or a subsection.
            start_pos = -1
            for m in _SECTION_TRIM_RE.finditer(text):
                if _is_subsection_of(m.group(1), section_prefix):
                    start_pos = m.start()
                    break
            if start_pos >= 0:
                text = text[start_pos:]
                found_start = True
            elif i == 0:
                # First page has no target heading — check if the first heading is
                # a non-target sibling (which means there is no target content here).
                first_m = next(iter(_SECTION_TRIM_RE.finditer(text)), None)
                if first_m is not None and not _is_subsection_of(first_m.group(1), section_prefix):
                    first_page_starts_with_sibling = True
                # Either way, treat as start (sibling-start chunks will be caught below).
                found_start = True
            else:
                continue  # page is before the section start — skip entirely

        # Trim from the first heading that is NOT the target or a subsection.
        end_pos = -1
        for m in _SECTION_TRIM_RE.finditer(text):
            if not _is_subsection_of(m.group(1), section_prefix):
                end_pos = m.start()
                break
        if end_pos >= 0:
            text = text[:end_pos].rstrip()
            if text:
                result.append({"page_number": page_num, "text": text})
            break  # everything after this heading belongs to another section

        result.append({"page_number": page_num, "text": text})

    if not result:
        # Trimming produced nothing. Distinguish two cases:
        #   - First heading was a sibling: no target content exists → signal exclusion with [].
        #   - No heading at all (continuation chunk): heading was on a prior page → keep full pages.
        if first_page_starts_with_sibling:
            return []
        return list(pages)
    return result


def _extract_spillover_pages(
    pages: list[dict],
    section_prefix: str,
) -> list[dict]:
    """Extract leading section-prefix text from the next-sibling chunk's pages.

    When the section map assigns a page to section 8.7 because the 8.7 heading
    appears on that page, any 8.6 text before that heading is "spillover" that
    should be included in the 8.6 extraction.  This function returns only that
    leading text (pages up to and excluding the first non-subsection heading).

    Unlike _trim_pages_for_prefix, this never falls back to returning the full
    pages — an empty result means "no spillover".
    """
    if not pages or not section_prefix:
        return []

    result: list[dict] = []
    found_target = False  # set once we've confirmed target-section content

    for i, page in enumerate(pages):
        text = page["text"]
        page_num = page["page_number"]

        # Scan all headings on this page in document order to find the first
        # non-target heading (which marks the end of any spillover content).
        end_pos = -1
        for m in _SECTION_TRIM_RE.finditer(text):
            if _is_subsection_of(m.group(1), section_prefix):
                found_target = True
            else:
                end_pos = m.start()
                break

        if i == 0 and not found_target:
            # First page, no target heading found yet.
            # Inspect the very first heading: if it is non-target at position 0
            # there is nothing to include; if it is non-target but preceded by
            # text, include only that text; if there is no heading at all,
            # treat the page as a target-section continuation.
            first_m = next(iter(_SECTION_TRIM_RE.finditer(text)), None)
            if first_m is None:
                # No heading → treat as continuation of the target section.
                found_target = True
                result.append({"page_number": page_num, "text": text})
                continue
            if not _is_subsection_of(first_m.group(1), section_prefix):
                # First heading is non-target — include only any text before it.
                leading = text[:first_m.start()].rstrip()
                if leading:
                    result.append({"page_number": page_num, "text": leading})
                return result  # done regardless of whether there was leading text

        # Trim at the first non-target heading (or include the full page if none).
        if end_pos >= 0:
            trimmed = text[:end_pos].rstrip()
            if trimmed:
                result.append({"page_number": page_num, "text": trimmed})
            break
        result.append({"page_number": page_num, "text": text})

    return result


def _is_truncated_quote(quote: str) -> bool:
    """Return True if *quote* appears to end mid-sentence.

    Only flags multi-sentence excerpts where the last sentence is cut off —
    i.e., the quote contains a sentence break somewhere (`.`, `!`, `?` followed
    by further text) AND does not end at a natural boundary.  Single-clause
    phrases with no mid-quote sentence break are never flagged.

    Quotes under _QUOTE_MIN_TRUNCATION_LEN characters are always excluded.
    """
    stripped = quote.strip()
    if len(stripped) < _QUOTE_MIN_TRUNCATION_LEN:
        return False
    # Only flag when the quote is a multi-sentence excerpt (has at least one
    # sentence break followed by further text).
    if not _QUOTE_SENTENCE_BREAK_RE.search(stripped):
        return False
    return not _QUOTE_NATURAL_END_RE.search(stripped)


def _apply_focus_guardrails(
    result: ExtractionResult,
    focus: Optional[str],
) -> ExtractionResult:
    """Strip out-of-scope proposition types from *result* based on *focus*.

    market_definition: drop theories_of_harm; force overall_outcome to "unknown"
                       so the run does not infer case outcome from training data.
    theories:          drop product/geographic markets; force overall_outcome to "unknown".
    """
    if focus == "market_definition":
        result.theories = []
        result.overall_outcome = "unknown"
    elif focus == "theories":
        result.product_markets = []
        result.geographic_markets = []
        result.overall_outcome = "unknown"
    return result


def _merge_geo_market_pair(
    base: "ExtractedMarket",
    incoming: "ExtractedMarket",
) -> "ExtractedMarket":
    """Merge two geographic market entries for the same geography.

    Keeps the stronger definition_status; appends *incoming* notes when they
    add information not already present in *base*.
    """
    base_strength = _GEO_STATUS_STRENGTH.get(base.definition_status, 0)
    incoming_strength = _GEO_STATUS_STRENGTH.get(incoming.definition_status, 0)

    if incoming_strength > base_strength:
        winner, other = incoming, base
    else:
        winner, other = base, incoming

    notes = winner.notes
    if other.notes and other.notes.strip() and other.notes.strip() not in notes:
        sep = " | " if notes.strip() else ""
        notes = notes.rstrip() + sep + other.notes.strip()

    # Combine passage lists (de-duplicate by quote prefix).
    seen_quotes: set[str] = {p.quote[:60] for p in winner.passages}
    extra_passages = [p for p in other.passages if p.quote[:60] not in seen_quotes]

    return ExtractedMarket(
        name=winner.name,
        market_type="geographic",
        definition_status=winner.definition_status,
        notes=notes,
        passages=winner.passages + extra_passages,
        not_found=winner.not_found and other.not_found,
    )


# ---------------------------------------------------------------------------
# Claude extraction prompt
# ---------------------------------------------------------------------------

_EXTRACTION_TASK = """\
TASK:
Extract the following from the supplied source text ONLY.
- Do NOT use training-data knowledge about this case.
- Do NOT invent quotes, page numbers, or conclusions absent from the text.
- For every item, cite the exact chunk_id and page_number from the supplied text.
- Copy quote text VERBATIM — do not paraphrase or summarise.
- If evidence is not in the supplied text, set "not_found": true.

CRITICAL - COMPLETE RESPONSE: You MUST return a complete JSON object with all
required top-level keys. NEVER return `{}`. If nothing is found, return empty
arrays and set caveats explaining why. Required keys: product_markets,
geographic_markets, theories_of_harm, overall_outcome, source_passages, caveats.

CRITICAL - LIST FIELDS: Every list field (product_markets, geographic_markets,
theories_of_harm, source_passages, caveats, background_concepts) MUST be a JSON
array — a real array, not a JSON-encoded string.  Return [] when nothing is found.
NEVER return a string like "not found", "none", "N/A", or "[{...}]".

CORRECT format (real arrays):
  "product_markets": [{"name": "Online ads", "definition_status": "left_open", ...}]
  "source_passages": [{"chunk_id": "chunk_001", "page_number": 42, "quote": "..."}]
  "caveats": []

WRONG format (strings — this will be rejected):
  "product_markets": "[{\"name\": \"Online ads\"}]"   ← string, not array
  "source_passages": "not found"                        ← string, use [] instead

STRICT RULES FOR MARKET ENTRIES:
Only create entries in product_markets / geographic_markets when the supplied text
contains FORMAL MARKET DEFINITION ANALYSIS - i.e., the authority explicitly:
  - defines a relevant product or geographic market,
  - leaves a market definition open while examining candidate definitions,
  - performs segmentation analysis (narrow vs. broad), OR
  - assesses precedents and concludes on market scope.

Do NOT create formal market entries based on:
  - industry background or overview sections (e.g. "Industry Overview", "The Parties")
  - factual descriptions of products or services a party sells
  - general descriptions of industry participants or sectors
  - mentions that a market "exists" without formal Commission/agency assessment language

If the supplied chunks are background or overview text only:
  - return product_markets: []
  - return geographic_markets: []
  - list any mentioned market-related concepts in background_concepts (strings only)
  - explain in caveats why no formal market entries were created

PRECISE MARKET DEFINITION STATUS:
Choose the most accurate definition_status for each market entry:
  - "defined": Commission conclusively defined the market
  - "left_open": Commission expressly stated it was unnecessary to conclude on market definition
  - "considered": Market discussed or examined but Commission reserved its conclusion
  - "not_conclusive": Analysis performed but no conclusion reached
  - "possible_segmentation": Segmentation was considered but not definitively resolved
  - "precedent_only": Referenced from prior cases only, not assessed in this decision
  - "unknown": Status cannot be determined from the supplied text
CRITICAL: Do NOT use "defined" if the text says the definition was "left open",
"not necessary to conclude", or "inconclusive". Use "left_open" or "not_conclusive".
CRITICAL — NO INFERRED CONCLUSIONS: If the supplied text does not contain the
Commission's explicit conclusion on a market, set definition_status to "unknown"
and market_importance to "incomplete_source". Do NOT infer "left_open" by analogy
with other markets or by guessing. Do NOT infer any conclusion from training data.
Add a caveat naming the market and explaining that its conclusion is absent from
the supplied chunks.

MARKET IMPORTANCE CLASSIFICATION:
For every product and geographic market entry, set market_importance:
  - "core_assessed": Commission formally assessed this as a key relevant market.
  - "assessed_no_overlap": Commission assessed it but the parties do not compete here.
  - "ancillary": Related market discussed but not the primary analytical focus.
  - "possible_segmentation": Segmentation analysis done but left open.
  - "precedent_only": Referenced from prior cases only; not assessed in this decision.
  - "background": Mentioned only in background or industry overview context.
  - "incomplete_source": The analysis exists but its conclusion is absent from the
    supplied chunks (use with definition_status "unknown").

SOURCE ROLE CLASSIFICATION:
For every passage, set source_role:
  - "commission_assessment": Commission actively analysing the market or competitive effect
  - "conclusion": Commission's explicit conclusion on a market definition or competitive effect
  - "precedent": Reference to a prior decision used as evidence (not a finding in this case)
  - "notifying_party_view": Statement by the notifying parties, merging firms, or their advisers
  - "market_investigation": Evidence from third-party responses, market testing, or surveys
  - "background": Factual background, industry description, or procedural context
IMPORTANT: Only "commission_assessment" and "conclusion" passages justify formal market
definitions. If a market entry is supported only by "notifying_party_view" or "precedent"
passages, set its definition_status to "precedent_only" or add an explanatory caveat.

VERBATIM QUOTES ONLY:
Copy passage text EXACTLY as it appears in the source. Do NOT paraphrase, summarise,
or rephrase. If you cannot find an exact verbatim quote, do not include the passage.

MARKET DEDUPLICATION AND HIERARCHY:
Do not create multiple entries for the same market at different hierarchical levels.
  - If segmentation is considered (e.g. search ads vs. display ads within online advertising),
    create one entry with definition_status "possible_segmentation" and explain in notes.
  - Distinguish the core market from geographic scope — do not create one entry per geography
    unless the Commission assessed them as genuinely separate relevant markets.
  - For each market, link all supporting passages via the nested "passages" array.

Use the record_extraction tool to return your findings."""

_PASSAGE_ITEM_SCHEMA = {
    "type": "object",
    "required": ["chunk_id", "page_number", "quote"],
    "properties": {
        "chunk_id": {"type": "string"},
        "page_number": {"type": "integer"},
        "quote": {"type": "string"},
        "supports": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Proposition IDs this passage supports.",
        },
        "proposition_type": {
            "type": "string",
            "description": "Type of proposition supported (market, theory, remedy, etc.).",
        },
        "source_role": {
            "type": "string",
            "enum": sorted(_VALID_SOURCE_ROLES),
            "description": (
                "Who is speaking: commission_assessment/conclusion = Commission finding; "
                "notifying_party_view/precedent = contextual only, not a case finding."
            ),
        },
    },
}

_MARKET_ITEM_SCHEMA = {
    "type": "object",
    "required": ["name", "definition_status", "notes", "not_found", "passages"],
    "properties": {
        "name": {"type": "string"},
        "definition_status": {
            "type": "string",
            "enum": sorted(_VALID_MARKET_STATUSES),
            "description": (
                "defined=Commission concluded; left_open=Commission said unnecessary to decide; "
                "considered=discussed but no formal conclusion; not_conclusive=analysis inconclusive; "
                "possible_segmentation=segmentation considered, not resolved; "
                "precedent_only=from prior cases, not assessed here; unknown=cannot determine."
            ),
        },
        "market_importance": {
            "type": "string",
            "enum": sorted(_VALID_MARKET_IMPORTANCE),
            "description": (
                "core_assessed=key market formally analysed by Commission; "
                "assessed_no_overlap=assessed but parties don't overlap; "
                "ancillary=related but not primary focus; "
                "possible_segmentation=segmentation discussed but not resolved; "
                "precedent_only=referenced from prior cases only; "
                "background=background/overview mention only; "
                "incomplete_source=conclusion expected but missing from supplied text."
            ),
        },
        "notes": {"type": "string"},
        "not_found": {"type": "boolean"},
        "passages": {"type": "array", "items": _PASSAGE_ITEM_SCHEMA},
    },
}

_EXTRACTION_TOOL_SCHEMA = {
    "name": "record_extraction",
    "description": (
        "Record the structured extraction of product markets, geographic markets, "
        "and theories of harm from the supplied merger decision text."
    ),
    "input_schema": {
        "type": "object",
        "required": [
            "product_markets", "geographic_markets", "theories_of_harm",
            "overall_outcome", "source_passages", "caveats",
        ],
        "properties": {
            "product_markets": {
                "type": "array",
                "description": "Product markets identified or discussed. Return [] if none found — never a string.",
                "items": _MARKET_ITEM_SCHEMA,
            },
            "geographic_markets": {
                "type": "array",
                "description": "Geographic markets identified or discussed. Return [] if none found — never a string.",
                "items": _MARKET_ITEM_SCHEMA,
            },
            "theories_of_harm": {
                "type": "array",
                "description": "Theories of harm considered. Return [] if none found — never a string.",
                "items": {
                    "type": "object",
                    "required": ["name", "theory_type", "theory_outcome", "notes", "not_found", "passages"],
                    "properties": {
                        "name": {"type": "string"},
                        "theory_type": {
                            "type": "string",
                            "enum": ["horizontal", "vertical", "conglomerate", "data", "other"],
                        },
                        "theory_outcome": {
                            "type": "string",
                            "enum": ["dismissed", "upheld", "remedied", "unclear"],
                        },
                        "notes": {"type": "string"},
                        "not_found": {"type": "boolean"},
                        "passages": {"type": "array", "items": _PASSAGE_ITEM_SCHEMA},
                    },
                },
            },
            "overall_outcome": {
                "type": "string",
                "enum": sorted(_VALID_OUTCOMES),
            },
            "source_passages": {
                "type": "array",
                "items": _PASSAGE_ITEM_SCHEMA,
                "description": (
                    "All key passages cited as evidence across all markets and theories. "
                    "Return [] if no relevant passages found — never a string."
                ),
            },
            "caveats": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Notes where text was ambiguous or evidence was missing. Return [] if none — never a string.",
            },
            "background_concepts": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Market-related concepts mentioned in background or overview sections "
                    "but NOT subject to formal market definition analysis. "
                    "Use this for concepts from industry overview chunks that should NOT "
                    "appear in product_markets or geographic_markets. Return [] if none."
                ),
            },
        },
    },
}


def _format_chunks_for_prompt(chunks: list[ChunkInfo]) -> str:
    sep = "=" * 60
    parts: list[str] = []
    for chunk in chunks:
        section_label = f" — {chunk.section_path}" if chunk.section_path else ""
        parts.append(
            f"[{chunk.chunk_id}{section_label} ({chunk.page_range})]\n"
            + chunk.prompt_text  # trimmed if section_prefix was applied
        )
    return ("\n\n" + sep + "\n\n").join(parts)


def _build_extraction_prompt(chunks: list[ChunkInfo], case_context: dict) -> str:
    parties_str = ", ".join(
        f"{p.get('name', '')} ({p.get('role', '')})"
        for p in (case_context.get("parties") or [])
    )
    context_block = (
        "Case: " + case_context.get("case_name", "?") + "\n"
        + "Authority: " + case_context.get("authority", "?") + "\n"
        + "Parties: " + (parties_str or "?")
    )
    chunks_block = _format_chunks_for_prompt(chunks)
    return (
        "You are a competition law research assistant extracting structured "
        "information from merger decision text.\n\n"
        "CASE CONTEXT:\n" + context_block + "\n\n"
        "SUPPLIED SOURCE CHUNKS:\n" + chunks_block + "\n\n"
        + _EXTRACTION_TASK
    )


# ---------------------------------------------------------------------------
# Claude API call
# ---------------------------------------------------------------------------

def _call_claude_raw(prompt: str, anthropic_client):
    """Call Claude using tool_use; return the raw Anthropic message object."""
    return anthropic_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        tools=[_EXTRACTION_TOOL_SCHEMA],
        tool_choice={"type": "tool", "name": "record_extraction"},
        messages=[{"role": "user", "content": prompt}],
    )


def _call_claude(prompt: str, anthropic_client) -> str:
    """Call Claude using tool_use for structured JSON output; return JSON string."""
    message = _call_claude_raw(prompt, anthropic_client)
    for block in message.content:
        if getattr(block, "type", None) == "tool_use":
            return json.dumps(block.input)
    # Fallback: text content (e.g., error messages)
    for block in message.content:
        if getattr(block, "type", None) == "text":
            return block.text.strip()
    return ""


def _parse_extraction_response(
    response_text: str,
    debug_dir: Optional[Path] = None,
    case_id: str = "",
) -> dict:
    """Parse JSON from Claude's response, stripping any markdown fences.

    On failure, saves the raw response to debug_dir/{case_id}_claude_raw_response.txt
    and raises ValueError with the path included in the message.
    """
    text = response_text.strip()

    # Strip ```json ... ``` or ``` ... ``` fences
    fence_match = re.match(r"```(?:json)?\s*\n?([\s\S]+?)\n?```\s*$", text)
    if fence_match:
        text = fence_match.group(1).strip()

    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Extract first valid JSON object from text with surrounding explanatory content
    m = re.search(r"\{[\s\S]+\}", text)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass

    # All parsing failed — save raw response for debugging
    debug_path: Optional[Path] = None
    if debug_dir is not None and case_id:
        debug_dir.mkdir(parents=True, exist_ok=True)
        debug_path = debug_dir / f"{case_id}_claude_raw_response.txt"
        debug_path.write_text(response_text, encoding="utf-8")

    msg = "Could not parse JSON from Claude response"
    if debug_path:
        msg += f" — raw response saved to {debug_path}"
    raise ValueError(msg)


def _normalize_list_fields(raw: dict) -> tuple[dict, list[str]]:
    """
    Coerce null-like strings and JSON-stringified arrays in known list fields to [].

    Three cases for string values in a known list field:
    - Null-like ("not found", "none", "n/a", "[]", etc.) → []
    - JSON-array string (stripped value starts with "[") → parse via json.loads;
      use the result if it is a list, otherwise return a validation error
    - Any other substantive string → validation error (not coerced)

    Returns (normalized_copy, errors).  errors is non-empty only when a field
    contains a string that cannot be safely coerced to a list.
    """
    errors: list[str] = []
    normalized = dict(raw)
    for key in _EXPECTED_LIST_FIELDS:
        val = normalized.get(key)
        if val is None or isinstance(val, list):
            continue
        if isinstance(val, str):
            stripped = val.strip()
            if stripped.lower() in _NULL_LIKE_STRINGS:
                normalized[key] = []
            elif stripped.startswith("["):
                # Looks like a JSON-array string — attempt to parse it.
                try:
                    parsed = json.loads(stripped)
                except json.JSONDecodeError:
                    errors.append(
                        f"'{key}' must be an array; got an invalid JSON string: {stripped[:200]!r}"
                    )
                    continue
                if isinstance(parsed, list):
                    normalized[key] = parsed
                else:
                    errors.append(
                        f"'{key}' must be an array; JSON string parsed to "
                        f"{type(parsed).__name__}, not a list: {stripped[:200]!r}"
                    )
            else:
                errors.append(
                    f"'{key}' must be an array; got a substantive string: {val!r}"
                )
    return normalized, errors


def _validate_extraction_schema(raw: dict) -> list[str]:
    """Return a list of schema violation messages (empty when valid)."""
    errors: list[str] = []
    for key in _REQUIRED_SCHEMA_KEYS:
        if key not in raw:
            errors.append(f"Missing required key: '{key}'")
    for list_key in _EXPECTED_LIST_FIELDS:
        if list_key in raw and not isinstance(raw[list_key], list):
            errors.append(f"'{list_key}' must be a list, got {type(raw[list_key]).__name__}")
    if "overall_outcome" in raw and raw["overall_outcome"] not in _VALID_OUTCOMES:
        errors.append(
            f"'overall_outcome' must be one of {sorted(_VALID_OUTCOMES)}, "
            f"got {raw['overall_outcome']!r}"
        )
    return errors


# ---------------------------------------------------------------------------
# Repair retry helpers
# ---------------------------------------------------------------------------

def _should_attempt_repair(norm_errors: list[str], schema_errors: list[str]) -> bool:
    """Return True if ALL errors are due to list fields returned as strings.

    Only triggers repair when every schema error is a list-type error (i.e. a
    direct consequence of a stringified list field).  Errors about missing
    required keys or invalid enum values indicate a different problem that a
    format-only repair is unlikely to fix.
    """
    if not norm_errors:
        return False
    for err in schema_errors:
        if "must be a list" in err:
            continue
        return False  # unrelated error — repair unlikely to help
    return True


def _call_claude_repair(
    bad_response: str,
    validation_errors: list[str],
    anthropic_client,
) -> str:
    """One corrective Claude call to fix stringified-array format errors.

    Does NOT re-send source chunks — passes only the bad response text and the
    specific validation errors.  Returns the corrected JSON string.  Raises on
    API or parse failure.  Limited to one call; callers must not retry.
    """
    violations = "\n".join(f"  - {e}" for e in validation_errors)
    prompt = (
        "A previous extraction call returned JSON that violates the schema. "
        "Fix ONLY the format errors below — do NOT change any content values.\n\n"
        "VIOLATIONS:\n" + violations + "\n\n"
        "PREVIOUS RESPONSE TO FIX:\n" + bad_response + "\n\n"
        "CRITICAL — every list field MUST be a real JSON array, never a string:\n"
        "  WRONG: \"product_markets\": \"[{\\\"name\\\": \\\"X\\\"}]\"\n"
        "  RIGHT: \"product_markets\": [{\"name\": \"X\", ...}]\n\n"
        "Return the complete corrected object using the record_extraction tool."
    )
    return _call_claude(prompt, anthropic_client)


# ---------------------------------------------------------------------------
# Quote validation
# ---------------------------------------------------------------------------

def _validate_quote_against_chunks(
    quote: str,
    chunk_id: str,
    page_number: int,
    chunks: list[ChunkInfo],
) -> tuple[bool, str, Optional[int]]:
    """
    Return (valid, note, corrected_page).

    - (True, "", None)         — quote found verbatim on cited page; no correction needed
    - (True, note, int)        — quote found on adjacent page; page_number corrected
    - (False, reason, None)    — quote not found or invalid input

    Checks adjacent pages in the same chunk and CORRECTS the page number rather
    than rejecting when the quote is found nearby (handles off-by-one errors in
    the source document or page-break spans in the cache).
    """
    if not quote or not quote.strip():
        return False, "Empty quote", None

    chunk = next((c for c in chunks if c.chunk_id == chunk_id), None)
    if chunk is None:
        return False, f"chunk_id '{chunk_id}' not in supplied chunks", None

    # Check the cited page
    page = next((p for p in chunk.pages if p["page_number"] == page_number), None)
    if page is None:
        return False, (
            f"page {page_number} not in {chunk_id} "
            f"(available: {chunk.page_numbers})"
        ), None

    if quote_found_in_text(quote, page["text"]):
        return True, "", None

    # Check adjacent pages — correct the page number if found
    for p in chunk.pages:
        if p["page_number"] != page_number and quote_found_in_text(quote, p["text"]):
            return True, (
                f"page corrected from {page_number} to {p['page_number']}"
            ), p["page_number"]

    return False, "Quote not found in cited page or adjacent pages of chunk", None


def _validate_extraction(
    raw: dict,
    chunks: list[ChunkInfo],
    chunk_doc_map: dict[str, str],
) -> ExtractionResult:
    """
    Walk the raw Claude extraction, validate every passage quote, and return
    an ExtractionResult with only passages that pass validation.

    *chunk_doc_map*: chunk_id → source_document_id
    """
    validated_count = 0
    rejected_count = 0

    def _process_passages(raw_passages: list) -> list[ExtractedPassage]:
        nonlocal validated_count, rejected_count
        out: list[ExtractedPassage] = []
        for rp in raw_passages or []:
            if not isinstance(rp, dict):
                continue
            quote = (rp.get("quote") or "").strip()
            chunk_id = str(rp.get("chunk_id", "") or "")
            source_role = str(rp.get("source_role", "") or "")
            # Coerce unknown source roles to empty string rather than propagating invalid values.
            if source_role and source_role not in _VALID_SOURCE_ROLES:
                source_role = ""
            try:
                page_num = int(rp.get("page_number") or 0)
            except (TypeError, ValueError):
                page_num = 0

            # Reject passages missing required fields (item 2).
            if not chunk_id:
                out.append(ExtractedPassage(
                    chunk_id="", page_number=page_num, quote=quote,
                    validated=False, rejection_reason="Missing required field: chunk_id",
                    source_role=source_role,
                ))
                rejected_count += 1
                continue
            if not quote:
                out.append(ExtractedPassage(
                    chunk_id=chunk_id, page_number=page_num, quote="",
                    validated=False, rejection_reason="Missing required field: quote",
                    source_role=source_role,
                ))
                rejected_count += 1
                continue
            if page_num == 0:
                out.append(ExtractedPassage(
                    chunk_id=chunk_id, page_number=0, quote=quote,
                    validated=False, rejection_reason="Missing required field: page_number",
                    source_role=source_role,
                ))
                rejected_count += 1
                continue

            # Reject quotes that appear truncated/incomplete (end mid-sentence).
            if _is_truncated_quote(quote):
                out.append(ExtractedPassage(
                    chunk_id=chunk_id, page_number=page_num, quote=quote,
                    validated=False,
                    rejection_reason=(
                        "Quote appears truncated — does not end at a natural boundary "
                        f"(last chars: ...{quote[-30:]!r})"
                    ),
                    source_role=source_role,
                ))
                rejected_count += 1
                continue

            valid, note, corrected_page = _validate_quote_against_chunks(
                quote, chunk_id, page_num, chunks
            )
            actual_page = corrected_page if corrected_page is not None else page_num
            ep = ExtractedPassage(
                chunk_id=chunk_id,
                page_number=actual_page,
                quote=quote,
                validated=valid,
                source_document_id=chunk_doc_map.get(chunk_id, ""),
                rejection_reason="" if valid else note,
                source_role=source_role,
            )
            if valid:
                validated_count += 1
            else:
                rejected_count += 1
            out.append(ep)
        return out

    def _coerce_importance(val: object) -> str:
        s = str(val).strip() if val else ""
        return s if s in _VALID_MARKET_IMPORTANCE else ""

    product_markets: list[ExtractedMarket] = []
    for pm in raw.get("product_markets") or []:
        product_markets.append(ExtractedMarket(
            name=pm.get("name", ""),
            market_type="product",
            definition_status=pm.get("definition_status", "unknown"),
            notes=pm.get("notes", ""),
            passages=_process_passages(pm.get("passages") or []),
            not_found=bool(pm.get("not_found")),
            market_importance=_coerce_importance(pm.get("market_importance", "")),
        ))

    geographic_markets: list[ExtractedMarket] = []
    for gm in raw.get("geographic_markets") or []:
        geographic_markets.append(ExtractedMarket(
            name=gm.get("name", ""),
            market_type="geographic",
            definition_status=gm.get("definition_status", "unknown"),
            notes=gm.get("notes", ""),
            passages=_process_passages(gm.get("passages") or []),
            not_found=bool(gm.get("not_found")),
            market_importance=_coerce_importance(gm.get("market_importance", "")),
        ))

    theories: list[ExtractedTheory] = []
    for th in raw.get("theories_of_harm") or []:
        theories.append(ExtractedTheory(
            name=th.get("name", ""),
            theory_type=th.get("theory_type", "other"),
            theory_outcome=th.get("theory_outcome", "unclear"),
            notes=th.get("notes", ""),
            passages=_process_passages(th.get("passages") or []),
            not_found=bool(th.get("not_found")),
        ))

    # Detect orphan top-level source_passages (not referenced in any market/theory).
    nested_quotes: set[str] = set()
    for item_list in (product_markets, geographic_markets, theories):
        for item in item_list:
            for p in item.passages:
                nested_quotes.add(p.quote[:80])
    orphan_count = sum(
        1 for sp in (raw.get("source_passages") or [])
        if isinstance(sp, dict) and (sp.get("quote", "") or "")[:80] not in nested_quotes
    )

    return ExtractionResult(
        product_markets=product_markets,
        geographic_markets=geographic_markets,
        theories=theories,
        overall_outcome=raw.get("overall_outcome", "unknown"),
        caveats=list(raw.get("caveats") or []),
        background_concepts=list(raw.get("background_concepts") or []),
        passages_validated=validated_count,
        passages_rejected=rejected_count,
        orphan_passages=orphan_count,
    )


# ---------------------------------------------------------------------------
# Section-batch extraction helpers
# ---------------------------------------------------------------------------

def _save_section_debug(
    debug_dir: Path,
    debug_label: str,
    case_id: str,
    section_prefix: str,
    chunks: list[ChunkInfo],
    message,                             # raw Anthropic message object or None
    extra: Optional[dict] = None,
    token_estimate: Optional[int] = None,
    extraction_result: Optional["ExtractionResult"] = None,
) -> Path:
    """Save rich section debug metadata to a JSON file; return the path."""
    debug_dir.mkdir(parents=True, exist_ok=True)
    debug_path = debug_dir / f"{debug_label}.json"

    metadata: dict = {
        "debug_type": "section_extraction",
        "case_id": case_id,
        "section_prefix": section_prefix,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "token_estimate": token_estimate,
        "chunks_sent": [
            {
                "chunk_id": c.chunk_id,
                "page_range": c.page_range,
                "section_path": c.section_path,
                "page_count": len(c.pages),
            }
            for c in chunks
        ],
    }

    if extraction_result is not None:
        metadata["extracted_product_markets"] = len(extraction_result.product_markets)
        metadata["extracted_geographic_markets"] = len(extraction_result.geographic_markets)
        metadata["extracted_theories"] = len(extraction_result.theories)
        metadata["passages_validated"] = extraction_result.passages_validated
        metadata["passages_rejected"] = extraction_result.passages_rejected
        metadata["orphan_passages"] = extraction_result.orphan_passages

    if message is not None:
        metadata["model"] = getattr(message, "model", None)
        metadata["stop_reason"] = getattr(message, "stop_reason", None)
        metadata["content_block_types"] = [
            getattr(b, "type", None) for b in (message.content or [])
        ]
        for block in message.content or []:
            if getattr(block, "type", None) == "tool_use":
                metadata["raw_tool_input"] = block.input
                break
        for block in message.content or []:
            if getattr(block, "type", None) == "text":
                metadata["raw_text"] = getattr(block, "text", None)
                break

    if extra:
        metadata.update(extra)

    with open(debug_path, "w", encoding="utf-8") as fh:
        json.dump(metadata, fh, indent=2, ensure_ascii=False, default=str)
    return debug_path


def _extract_section_batch(
    prefix: str,
    chunks: list[ChunkInfo],
    case_context: dict,
    anthropic_client,
    debug_dir: Path,
    case_id: str,
) -> SectionBatchResult:
    """Run one Claude extraction call for a section batch; never raises.

    Returns a SectionBatchResult with either a validated ExtractionResult or
    an error string.  Failed sections save rich debug JSON but do not abort
    the overall run.
    """
    section_label = _section_label_for_batch(prefix, chunks)
    debug_label = f"{case_id}_section_{prefix.replace('.', '_')}"
    chunk_doc_map = {c.chunk_id: c.source_document_id for c in chunks}

    total_pages = sum(len(c.pages) for c in chunks)
    total_chars = sum(len(c.prompt_text) for c in chunks)
    approx_tokens = total_chars // 4
    print(
        f"  Section {prefix} ({section_label[:50]}): "
        f"{len(chunks)} chunks, {total_pages} pages, ~{approx_tokens:,} tokens"
    )

    prompt = _build_extraction_prompt(chunks, case_context)

    # API call
    message = None
    try:
        message = _call_claude_raw(prompt, anthropic_client)
    except Exception as exc:
        debug_path = _save_section_debug(
            debug_dir, debug_label, case_id, prefix, chunks, None,
            extra={"error": str(exc)},
            token_estimate=approx_tokens,
        )
        return SectionBatchResult(
            prefix=prefix, section_label=section_label, chunks=chunks,
            result=None, error=f"API error in section {prefix}: {exc}",
            debug_path=debug_path,
        )

    # Extract JSON string from message
    response_text = ""
    for block in message.content or []:
        if getattr(block, "type", None) == "tool_use":
            response_text = json.dumps(block.input)
            break
    if not response_text:
        for block in message.content or []:
            if getattr(block, "type", None) == "text":
                response_text = getattr(block, "text", "").strip()
                break

    # Parse JSON
    try:
        raw = _parse_extraction_response(response_text, debug_dir=None, case_id="")
    except ValueError:
        debug_path = _save_section_debug(
            debug_dir, debug_label, case_id, prefix, chunks, message,
            extra={"error": "json_parse_failed", "raw_response_text": response_text[:4000]},
            token_estimate=approx_tokens,
        )
        return SectionBatchResult(
            prefix=prefix, section_label=section_label, chunks=chunks,
            result=None, error=f"Section {prefix}: JSON parse failed — debug saved to {debug_path}",
            debug_path=debug_path,
        )

    # Empty-object guard
    if not raw:
        debug_path = _save_section_debug(
            debug_dir, debug_label, case_id, prefix, chunks, message,
            extra={"error": "empty_object"},
            token_estimate=approx_tokens,
        )
        return SectionBatchResult(
            prefix=prefix, section_label=section_label, chunks=chunks,
            result=None,
            error=f"Section {prefix}: Claude returned empty extraction object — debug saved to {debug_path}",
            debug_path=debug_path,
        )

    # Envelope + normalise + validate
    merged = dict(_DEFAULT_EXTRACTION_ENVELOPE)
    merged.update(raw)
    raw = merged
    raw, norm_errors = _normalize_list_fields(raw)
    schema_errors = _validate_extraction_schema(raw)
    all_errors = norm_errors + schema_errors
    if all_errors:
        if _should_attempt_repair(norm_errors, schema_errors):
            # Stringified-list-field errors — save original debug and attempt one repair call.
            print(f"  WARN: Section {prefix}: stringified list fields — attempting repair call")
            _save_section_debug(
                debug_dir, f"{debug_label}_schema_err", case_id, prefix, chunks, message,
                extra={"validation_errors": all_errors},
                token_estimate=approx_tokens,
            )
            try:
                repaired_text = _call_claude_repair(response_text, all_errors, anthropic_client)
                repaired_raw = _parse_extraction_response(repaired_text, debug_dir=None, case_id="")
            except Exception as exc:
                debug_path = _save_section_debug(
                    debug_dir, debug_label, case_id, prefix, chunks, message,
                    extra={"error": "repair_call_failed", "cause": str(exc),
                           "original_validation_errors": all_errors},
                    token_estimate=approx_tokens,
                )
                return SectionBatchResult(
                    prefix=prefix, section_label=section_label, chunks=chunks,
                    result=None,
                    error=(
                        f"Section {prefix} schema validation failed and repair call errored: {exc} "
                        f"— debug saved to {debug_path}"
                    ),
                    debug_path=debug_path,
                )

            if not repaired_raw:
                debug_path = _save_section_debug(
                    debug_dir, debug_label, case_id, prefix, chunks, message,
                    extra={"error": "repair_empty_object",
                           "original_validation_errors": all_errors},
                    token_estimate=approx_tokens,
                )
                return SectionBatchResult(
                    prefix=prefix, section_label=section_label, chunks=chunks,
                    result=None,
                    error=(
                        f"Section {prefix}: repair returned empty object "
                        f"— debug saved to {debug_path}"
                    ),
                    debug_path=debug_path,
                )

            r_merged = dict(_DEFAULT_EXTRACTION_ENVELOPE)
            r_merged.update(repaired_raw)
            repaired_raw = r_merged
            repaired_raw, r_norm_errors = _normalize_list_fields(repaired_raw)
            r_all_errors = r_norm_errors + _validate_extraction_schema(repaired_raw)
            if r_all_errors:
                debug_path = _save_section_debug(
                    debug_dir, debug_label, case_id, prefix, chunks, message,
                    extra={
                        "error": "repair_validation_failed",
                        "original_validation_errors": all_errors,
                        "repair_validation_errors": r_all_errors,
                        "repaired_text_preview": repaired_text[:2000],
                    },
                    token_estimate=approx_tokens,
                )
                return SectionBatchResult(
                    prefix=prefix, section_label=section_label, chunks=chunks,
                    result=None,
                    error=(
                        f"Section {prefix}: repair retry still failed: "
                        + "; ".join(r_all_errors)
                        + f" — debug saved to {debug_path}"
                    ),
                    debug_path=debug_path,
                )

            # Repair succeeded — save repaired debug and continue with repaired data.
            print(f"  Repair succeeded for section {prefix}")
            _save_section_debug(
                debug_dir, f"{debug_label}_repaired", case_id, prefix, chunks, message,
                extra={"repaired_from_errors": all_errors},
                token_estimate=approx_tokens,
            )
            raw = repaired_raw
            response_text = repaired_text

        else:
            # Non-stringified errors — cannot repair; fail immediately.
            debug_path = _save_section_debug(
                debug_dir, debug_label, case_id, prefix, chunks, message,
                extra={"validation_errors": all_errors},
                token_estimate=approx_tokens,
            )
            return SectionBatchResult(
                prefix=prefix, section_label=section_label, chunks=chunks,
                result=None,
                error=(
                    f"Section {prefix} schema validation failed: "
                    + "; ".join(all_errors)
                    + f" — debug saved to {debug_path}"
                ),
                debug_path=debug_path,
            )

    result = _validate_extraction(raw, chunks, chunk_doc_map)
    result.raw_response = response_text
    result.section_label = section_label  # used by merge to scope caveats

    # Save success debug with extraction counts.
    success_debug_path = _save_section_debug(
        debug_dir, f"{debug_label}_ok", case_id, prefix, chunks, message,
        token_estimate=approx_tokens,
        extraction_result=result,
    )
    return SectionBatchResult(
        prefix=prefix, section_label=section_label, chunks=chunks,
        result=result, error=None, debug_path=success_debug_path,
    )


def _merge_extraction_results(results: list[ExtractionResult]) -> ExtractionResult:
    """Merge per-section ExtractionResults into one combined result.

    Markets and theories are deduplicated conservatively (name similarity >= 0.75).
    When two items are similar, the one with more validated passages wins.
    """
    pm_list: list[ExtractedMarket] = []
    gm_list: list[ExtractedMarket] = []
    th_list: list[ExtractedTheory] = []
    caveats: list[str] = []
    background_concepts: list[str] = []
    overall_outcome = "unknown"
    passages_validated = 0
    passages_rejected = 0

    def _validated_count(item) -> int:
        return sum(1 for p in item.passages if p.validated)

    def _dedup_merge(incoming, existing_list: list, threshold: float = _SIMILARITY_MATCH) -> None:
        for item in incoming:
            best_sim = 0.0
            best_idx = -1
            for i, ex in enumerate(existing_list):
                sim = _similarity(item.name, ex.name)
                if sim > best_sim:
                    best_sim, best_idx = sim, i
            if best_sim >= threshold and best_idx >= 0:
                # Keep whichever has more validated passages
                if _validated_count(item) > _validated_count(existing_list[best_idx]):
                    existing_list[best_idx] = item
            else:
                existing_list.append(item)

    def _dedup_merge_geo(incoming: list[ExtractedMarket], existing_list: list[ExtractedMarket]) -> None:
        """Merge geographic markets, combining notes and keeping the stronger status."""
        for item in incoming:
            best_sim = 0.0
            best_idx = -1
            for i, ex in enumerate(existing_list):
                sim = _similarity(item.name, ex.name)
                if sim > best_sim:
                    best_sim, best_idx = sim, i
            if best_sim >= _SIMILARITY_MATCH and best_idx >= 0:
                existing_list[best_idx] = _merge_geo_market_pair(existing_list[best_idx], item)
            else:
                existing_list.append(item)

    for r in results:
        _dedup_merge(r.product_markets, pm_list)
        _dedup_merge_geo(r.geographic_markets, gm_list)
        _dedup_merge(r.theories, th_list)
        # Prefix each caveat with its section label so the merged list stays navigable.
        _lbl = r.section_label.strip() if r.section_label else ""
        for c in r.caveats:
            caveats.append(f"[{_lbl}] {c}" if _lbl and not c.startswith(f"[{_lbl}]") else c)
        background_concepts.extend(r.background_concepts)
        if r.overall_outcome != "unknown" and overall_outcome == "unknown":
            overall_outcome = r.overall_outcome
        passages_validated += r.passages_validated
        passages_rejected += r.passages_rejected

    return ExtractionResult(
        product_markets=pm_list,
        geographic_markets=gm_list,
        theories=th_list,
        overall_outcome=overall_outcome,
        caveats=caveats,
        # Deduplicate background_concepts preserving first-occurrence order
        background_concepts=list(dict.fromkeys(background_concepts)),
        passages_validated=passages_validated,
        passages_rejected=passages_rejected,
    )


# ---------------------------------------------------------------------------
# Draft YAML builder
# ---------------------------------------------------------------------------

def _build_draft_record(
    result: ExtractionResult,
    existing_record: dict,
) -> dict:
    """
    Build a draft YAML record from a validated ExtractionResult.

    Copies case-level metadata from the existing record.  All propositions are
    marked source_linked; only validated passages are included.
    """
    today = datetime.now().date().isoformat()

    draft: dict = {
        "_draft_note": (
            "DRAFT — generated by extract_case_from_source.py. "
            "Review and validate before merging into canonical YAML."
        ),
        "case_id": existing_record.get("case_id", ""),
        "case_name": existing_record.get("case_name", ""),
        "authority": existing_record.get("authority", ""),
        "jurisdiction": existing_record.get("jurisdiction", ""),
        "sector": existing_record.get("sector", ""),
        "outcome": result.overall_outcome,
        "decision_date": existing_record.get("decision_date"),
        "parties": existing_record.get("parties", []),
        "source_documents": existing_record.get("source_documents", []),
    }

    # Build proposition lists, track (prop_id, item) for passage collection.
    pm_with_ids: list[tuple[str, ExtractedMarket]] = []
    for pm in result.product_markets:
        if not pm.not_found:
            pm_with_ids.append((f"pm_{len(pm_with_ids) + 1}", pm))

    gm_with_ids: list[tuple[str, ExtractedMarket]] = []
    for gm in result.geographic_markets:
        if not gm.not_found:
            gm_with_ids.append((f"gm_{len(gm_with_ids) + 1}", gm))

    toh_with_ids: list[tuple[str, ExtractedTheory]] = []
    for th in result.theories:
        if not th.not_found:
            toh_with_ids.append((f"toh_{len(toh_with_ids) + 1}", th))

    def _market_entry(mid: str, m: "ExtractedMarket") -> dict:
        entry: dict = {
            "market_id": mid,
            "name": m.name,
            "definition_status": m.definition_status,
            "notes": m.notes,
            "verification": {"status": "source_linked"},
        }
        if m.market_importance:
            entry["market_importance"] = m.market_importance
        return entry

    draft["product_markets_considered"] = [
        _market_entry(mid, pm) for mid, pm in pm_with_ids
    ]
    draft["geographic_markets_considered"] = [
        _market_entry(mid, gm) for mid, gm in gm_with_ids
    ]
    draft["theories_of_harm"] = [
        {
            "theory_id": tid,
            "name": th.name,
            "description": th.notes,
            "verification": {"status": "source_linked"},
        }
        for tid, th in toh_with_ids
    ]

    # Collect validated passages only.
    passages: list[dict] = []
    sp_n = 0

    def _add_passages(
        with_ids: list[tuple[str, object]],
        support_pm: bool = False,
        support_gm: bool = False,
        support_toh: bool = False,
    ) -> None:
        nonlocal sp_n
        for prop_id, item in with_ids:
            for ep in item.passages:  # type: ignore[attr-defined]
                if not ep.validated:
                    continue
                sp_n += 1
                passages.append({
                    "passage_id": f"sp_{sp_n}",
                    "source_document_id": ep.source_document_id,
                    "page": str(ep.page_number),
                    "quote_snippet": ep.quote,
                    "extraction_method": "pdf_extracted",
                    "review_status": "unreviewed",
                    "confidence_score": 0.70,
                    "last_checked_date": today,
                    "supports_markets": [prop_id] if support_pm else [],
                    "supports_geographic_markets": [prop_id] if support_gm else [],
                    "supports_theories": [prop_id] if support_toh else [],
                })

    _add_passages(pm_with_ids, support_pm=True)
    _add_passages(gm_with_ids, support_gm=True)
    _add_passages(toh_with_ids, support_toh=True)

    draft["source_passages"] = passages
    return draft


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------

def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


# ---------------------------------------------------------------------------
# Enhanced reconciliation similarity helpers
# ---------------------------------------------------------------------------

# Domain synonym expansions applied before fuzzy matching.
# More specific patterns MUST come before broader ones (e.g. "wearable os" before bare "os").
# Plural forms (OSs → oss, oses) are handled by (?:es?|s)? suffixes.
_MARKET_SYNONYM_MAP: list[tuple[re.Pattern, str]] = [
    (re.compile(r'\bwearable\s+os(?:es?|s)?\b', re.I),         'wearable operating system'),
    (re.compile(r'\blicensable\s+os(?:es?|s)?\b', re.I),       'licensable operating system'),
    (re.compile(r'\bos(?:es?|s)?\b', re.I),                    'operating system'),
    (re.compile(r'\bplatform(?:s)?\b', re.I),                   'operating system'),
    (re.compile(r'\bwrist[-\s]?worn\b', re.I),                  'wearable'),
    (re.compile(r'\bad[-\s]?tech(?:nology)?\b', re.I),          'advertising technology'),
    (re.compile(r'\badtech\b', re.I),                           'advertising technology'),
    (re.compile(r'\bintermediation\b', re.I),                   'advertising'),
    (re.compile(r'\bapplication\s+store(?:s)?\b', re.I),        'app store'),
]

# Stop-words stripped before token Jaccard similarity for product markets.
_MARKET_STOPWORDS: frozenset[str] = frozenset({
    "the", "a", "an", "of", "for", "and", "or", "to", "in", "at",
    "by", "on", "with", "from", "within", "market", "markets", "relevant",
})

# Additional stop-words for geographic market context comparison.
# Strips geographic region and scope terms so only product/service tokens remain.
_GEO_STOPWORDS: frozenset[str] = _MARKET_STOPWORDS | frozenset({
    "eea", "eu", "uk", "us", "national", "worldwide", "global", "international",
    "geographic", "geographical", "scope", "geo", "regional", "area", "territory",
    "least", "along", "lines", "excluding", "china", "wide", "eeea",
})

# Minimum Jaccard overlap of product-context tokens to confirm a geographic rename.
_GEO_CONTEXT_MIN_OVERLAP: float = 0.30

# Device context patterns applied to NORMALIZED names (after synonym expansion).
# Used to detect conflicting device-class contexts (PC vs wearable, etc.).
_DEVICE_CONTEXTS: dict[str, re.Pattern] = {
    "pc": re.compile(
        r'\b(?:pc(?:s)?\b|personal\s+computer|desktop|laptop)', re.I
    ),
    "mobile": re.compile(
        r'\b(?:smart\s+mobile|mobile\s+devices?|smartphone|smart\s*phone|cell\s*phone)', re.I
    ),
    "wearable": re.compile(
        r'\b(?:wearable|smartwatch|fitness\s+tracker|wristband)', re.I
    ),
}

# Conflicting pairs: if one name has ctx_a and the other has ctx_b they conflict.
_CONFLICTING_DEVICE_PAIRS: list[frozenset[str]] = [
    frozenset({"pc", "wearable"}),
    frozenset({"pc", "mobile"}),
]

_DEVICE_CONTEXT_CONFLICT_FACTOR: float = 0.55  # similarity penalty when contexts conflict


def _normalize_for_similarity(name: str) -> str:
    """Lowercase and expand domain synonyms for fuzzy market-name matching."""
    s = name.lower()
    for pat, replacement in _MARKET_SYNONYM_MAP:
        s = pat.sub(replacement, s)
    return s


def _token_set(text: str, stopwords: frozenset[str]) -> set[str]:
    """Return a set of meaningful tokens from *text*, stripped of *stopwords*."""
    normalized = _normalize_for_similarity(text)
    tokens: set[str] = set()
    for w in re.findall(r'\b\w+\b', normalized):
        if len(w) <= 2 or w in stopwords:
            continue
        # Simple suffix normalization: "systems" → "system", "devices" → "device"
        if len(w) > 4 and w.endswith('s') and not w.endswith('ss'):
            w = w[:-1]
        tokens.add(w)
    return tokens


def _token_jaccard(a: str, b: str, stopwords: frozenset[str]) -> float:
    """Token-level Jaccard similarity with synonym normalization."""
    ta = _token_set(a, stopwords)
    tb = _token_set(b, stopwords)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _market_similarity(a: str, b: str) -> float:
    """Best of raw SequenceMatcher, synonym-normalized SequenceMatcher, and token Jaccard.

    Using the max of three strategies means any single strong signal (exact string
    match, synonym-expanded string match, or shared domain-token overlap) is enough
    to surface the similarity — important for names like 'Wearable OS / platforms'
    versus 'Supply of licensable OSs for wrist-worn wearable devices'.
    """
    raw = _similarity(a, b)
    norm = _similarity(_normalize_for_similarity(a), _normalize_for_similarity(b))
    jaccard = _token_jaccard(a, b, _MARKET_STOPWORDS)
    return max(raw, norm, jaccard)


def _geo_product_context_overlap(a: str, b: str) -> float:
    """Jaccard overlap of product/service tokens in two geographic market names.

    Geographic region terms (EEA, national, worldwide, etc.) are stripped via
    _GEO_STOPWORDS so only the product/service context contributes to the score.
    This prevents superficial matches where two geo markets share a region name
    or the words 'geographic scope' but describe entirely different products.
    """
    return _token_jaccard(a, b, _GEO_STOPWORDS)


def _detect_device_contexts(name: str) -> frozenset[str]:
    """Return the set of device-class labels present in the normalized *name*.

    Applies synonym normalization first so 'wrist-worn' → 'wearable' before matching.
    """
    normalized = _normalize_for_similarity(name)
    return frozenset(
        label for label, pat in _DEVICE_CONTEXTS.items() if pat.search(normalized)
    )


def _device_context_factor(a: str, b: str) -> float:
    """Return a similarity penalty when *a* and *b* describe different device classes.

    Only applies when at least one of the names has a detected device context and the
    contexts are in a known conflicting pair (e.g. PC vs wearable).  Returns
    _DEVICE_CONTEXT_CONFLICT_FACTOR (< 1.0) on conflict, 1.0 otherwise.

    This prevents 'OSs for PCs' from scoring as a strong rename candidate for
    'Wearable OS / platforms' purely on shared 'operating system' tokens.
    """
    ctx_a = _detect_device_contexts(a)
    ctx_b = _detect_device_contexts(b)
    if not ctx_a or not ctx_b:
        return 1.0
    for conflict in _CONFLICTING_DEVICE_PAIRS:
        if (ctx_a & conflict) and (ctx_b & conflict) and (ctx_a & conflict) != (ctx_b & conflict):
            return _DEVICE_CONTEXT_CONFLICT_FACTOR
    return 1.0


def _reconcile(
    draft_record: dict,
    existing_record: dict,
    focus: Optional[str] = None,
) -> list[ReconciliationFinding]:
    """
    Compare the draft to the existing YAML, classify each proposition.

    Finding types:
      supported_as_is   — existing prop matched a draft prop (similarity >= 0.75)
      should_be_renamed — similar prop found but name differs (0.45–0.75)
      unsupported_remove— existing prop has no match in draft (< 0.45)
      new_from_source   — draft prop not matched to any existing prop
    """
    findings: list[ReconciliationFinding] = []

    # Build market_id → page-number refs from source_passages so findings can
    # carry the draft market's cited pages without re-running extraction.
    _ref_map: dict[str, list[str]] = {}
    for _sp in (draft_record.get("source_passages") or []):
        _page = str(_sp.get("page", "") or "").strip()
        if not _page:
            continue
        for _mid in (_sp.get("supports_markets") or []):
            _ref_map.setdefault(_mid, []).append(_page)
        for _mid in (_sp.get("supports_geographic_markets") or []):
            _ref_map.setdefault(_mid, []).append(_page)
        for _mid in (_sp.get("supports_theories") or []):
            _ref_map.setdefault(_mid, []).append(_page)

    def _draft_meta(dr: dict) -> dict:
        """Extract draft market metadata from a draft item dict."""
        mid = str(dr.get("market_id") or dr.get("theory_id") or "")
        return {
            "draft_market_importance": str(dr.get("market_importance") or ""),
            "draft_definition_status": str(dr.get("definition_status") or ""),
            "draft_source_refs": list(dict.fromkeys(_ref_map.get(mid, []))),
        }

    def _match_list(
        existing_items: list[dict],
        draft_items: list[dict],
        id_field: str,
        item_label: str,
        is_geo: bool = False,
        market_type: str = "",
    ) -> None:
        matched_draft: set[int] = set()

        for ex in existing_items:
            ex_id = ex.get(id_field, "?")
            ex_name = ex.get("name", "")

            # Score all draft candidates upfront so we can sort and fall back.
            # For product markets: apply device-context conflict penalty so
            #   "OSs for PCs" can't steal the slot from "Supply of licensable OSs
            #   for wrist-worn wearable devices" on token Jaccard ties.
            # For geographic markets: include context-based boost so wearable/device
            #   context can outweigh raw string similarity from spurious region matches.
            scored: list[tuple[float, int, str, dict]] = []
            for j, dr in enumerate(draft_items):
                dr_name = dr.get("name", "")
                sim = _market_similarity(ex_name, dr_name)
                if is_geo:
                    ctx_boost = min(
                        _geo_product_context_overlap(ex_name, dr_name) * 0.85,
                        _SIMILARITY_MATCH - 0.01,
                    )
                    sim = max(sim, ctx_boost)
                elif market_type == "product":
                    sim *= _device_context_factor(ex_name, dr_name)
                scored.append((sim, j, dr_name, dr))

            # Sort descending by score; break ties by draft index (stability).
            scored.sort(key=lambda x: (-x[0], x[1]))

            if not scored:
                findings.append(ReconciliationFinding(
                    finding_type="unsupported_remove",
                    group=_RECON_GROUP["unsupported_remove"],
                    existing_id=ex_id, existing_name=ex_name, draft_name="",
                    message=f"No matching {item_label} found in source extraction. "
                            "Consider reviewing or removing.",
                    similarity=0.0,
                ))
                continue

            best_sim, best_j, best_name, best_dr = scored[0]

            if best_sim >= _SIMILARITY_MATCH:
                findings.append(ReconciliationFinding(
                    finding_type="supported_as_is",
                    group=_RECON_GROUP["supported_as_is"],
                    existing_id=ex_id, existing_name=ex_name,
                    draft_name=best_name,
                    message="Existing proposition matched by source extraction.",
                    similarity=best_sim,
                    draft_market_type=market_type,
                    **_draft_meta(best_dr),
                ))
                matched_draft.add(best_j)

            elif best_sim >= _SIMILARITY_RENAME:
                if is_geo:
                    # For geo markets: walk candidates in score order and pick the
                    # first one whose product-context overlap passes the gate.  This
                    # ensures we prefer a lower-scoring wearable candidate over a
                    # higher-scoring candidate that only shares a region word.
                    valid: Optional[tuple[float, int, str, dict]] = None
                    for s_sim, s_j, s_name, s_dr in scored:
                        if s_sim < _SIMILARITY_RENAME:
                            break  # all remaining are below threshold
                        if _geo_product_context_overlap(ex_name, s_name) >= _GEO_CONTEXT_MIN_OVERLAP:
                            valid = (s_sim, s_j, s_name, s_dr)
                            break

                    if valid is not None:
                        v_sim, v_j, v_name, v_dr = valid
                        findings.append(ReconciliationFinding(
                            finding_type="should_be_renamed",
                            group=_RECON_GROUP["should_be_renamed"],
                            existing_id=ex_id, existing_name=ex_name,
                            draft_name=v_name,
                            message=(
                                f"Source suggests a similar {item_label} with a "
                                f"different name: '{v_name}'"
                            ),
                            similarity=v_sim,
                            draft_market_type=market_type,
                            **_draft_meta(v_dr),
                        ))
                        matched_draft.add(v_j)
                    else:
                        # No candidate with matching product context in rename range.
                        # Leave all draft markets unmatched (they become candidates).
                        findings.append(ReconciliationFinding(
                            finding_type="unsupported_remove",
                            group=_RECON_GROUP["unsupported_remove"],
                            existing_id=ex_id, existing_name=ex_name, draft_name="",
                            message=(
                                f"No confident match for this {item_label} "
                                f"(closest draft candidate '{best_name}' has surface "
                                f"similarity {best_sim:.2f} but product contexts do not "
                                "overlap — manual review required)."
                            ),
                            similarity=best_sim,
                        ))
                else:
                    findings.append(ReconciliationFinding(
                        finding_type="should_be_renamed",
                        group=_RECON_GROUP["should_be_renamed"],
                        existing_id=ex_id, existing_name=ex_name,
                        draft_name=best_name,
                        message=(
                            f"Source suggests a similar {item_label} with a different "
                            f"name: '{best_name}'"
                        ),
                        similarity=best_sim,
                        draft_market_type=market_type,
                        **_draft_meta(best_dr),
                    ))
                    matched_draft.add(best_j)

            else:
                findings.append(ReconciliationFinding(
                    finding_type="unsupported_remove",
                    group=_RECON_GROUP["unsupported_remove"],
                    existing_id=ex_id, existing_name=ex_name, draft_name="",
                    message=f"No matching {item_label} found in source extraction. "
                            "Consider reviewing or removing.",
                    similarity=best_sim,
                ))

        for j, dr in enumerate(draft_items):
            if j not in matched_draft:
                findings.append(ReconciliationFinding(
                    finding_type="new_from_source",
                    group=_RECON_GROUP["new_from_source"],
                    existing_id="", existing_name="",
                    draft_name=dr.get("name", ""),
                    message=f"New {item_label} found in source, not in existing YAML.",
                    similarity=0.0,
                    draft_market_type=market_type,
                    **_draft_meta(dr),
                ))

    # When a focus mode is active, skip reconciling proposition types that were
    # out of scope for that extraction run — they would always appear as
    # unsupported_remove, which is misleading rather than actionable.
    _skip_markets = focus in ("theories", "remedies", "case_history")
    _skip_theories = focus in ("market_definition", "remedies", "case_history")

    if not _skip_markets:
        _match_list(
            existing_record.get("product_markets_considered") or [],
            draft_record.get("product_markets_considered") or [],
            "market_id", "product market",
            is_geo=False, market_type="product",
        )
        _match_list(
            existing_record.get("geographic_markets_considered") or [],
            draft_record.get("geographic_markets_considered") or [],
            "market_id", "geographic market",
            is_geo=True, market_type="geographic",
        )
    if not _skip_theories:
        _match_list(
            existing_record.get("theories_of_harm") or [],
            draft_record.get("theories_of_harm") or [],
            "theory_id", "theory of harm",
            is_geo=False, market_type="",
        )
    return findings


# ---------------------------------------------------------------------------
# Source-first promotion plan
# ---------------------------------------------------------------------------

# Recommended action values for the promotion plan.
_PROMOTION_ACTIONS: frozenset[str] = frozenset({
    "promote_to_canonical",
    "promote_with_uncertainty",
    "hold_pending_source_check",
    "keep_as_context_only",
    "exclude_from_canonical",
    "manual_review",
})


def _promotion_action(
    market_importance: str,
    definition_status: str,
    has_source_refs: bool,
) -> tuple[str, str]:
    """Return (recommended_action, reason) for a single draft market entry.

    Promotion decision rules (authoritative source-first logic):

    1. background                                  → exclude_from_canonical
    2. ancillary                                   → keep_as_context_only
    3. precedent_only                              → keep_as_context_only
    4. incomplete_source (explicit)                → hold_pending_source_check
    5. unknown status + no source refs             → hold_pending_source_check
    6. core_assessed + (defined|left_open|considered) + refs → promote_to_canonical
    7. core_assessed + possible_segmentation       → promote_with_uncertainty (needs review)
    8. core_assessed + other status                → manual_review
    9. core_assessed + no source refs              → manual_review
    10. assessed_no_overlap + source refs          → promote_to_canonical
    11. assessed_no_overlap + no source refs       → manual_review
    12. possible_segmentation (implicit)           → promote_with_uncertainty (needs review)
    13. has source refs but no recognised importance → manual_review
    14. fallback                                   → manual_review

    NOTE: These rules implement source-first canonicalisation. Reconciliation with
    existing canonical records is supplementary only and should not override these
    promotion decisions.
    """
    imp = (market_importance or "").strip()
    status = (definition_status or "").strip()
    unknown_status = status in ("unknown", "")

    # Statuses that are conclusive enough for core_assessed promotion
    _CONCLUSIVE_STATUSES = {"defined", "left_open", "considered"}

    # Rule 1: background — exclude regardless of status or refs
    if imp == "background":
        return (
            "exclude_from_canonical",
            "Mentioned only in background or overview context; "
            "no formal market definition analysis present.",
        )

    # Rule 2: ancillary
    if imp == "ancillary":
        return (
            "keep_as_context_only",
            "Related market mentioned but not the primary analytical focus; "
            "include in background_concepts rather than product/geo market lists.",
        )

    # Rule 3: precedent_only
    if imp == "precedent_only":
        return (
            "keep_as_context_only",
            "Referenced from prior cases only; not assessed in this decision. "
            "Do not add to canonical market lists.",
        )

    # Rule 4: incomplete_source (explicit)
    if imp == "incomplete_source":
        return (
            "hold_pending_source_check",
            "Commission conclusion is absent from the supplied source chunks; "
            "re-check with a broader section run before promoting.",
        )

    # Rule 5: unknown status without source refs — block until refs found
    if unknown_status and not has_source_refs:
        return (
            "hold_pending_source_check",
            "Definition status is unknown and no source passages support this market; "
            "re-check with a broader section run before promoting.",
        )

    # Rules 6–9: core_assessed (requires conclusive status + refs for promotion)
    if imp == "core_assessed":
        # Rule 7: core_assessed + possible_segmentation → needs explicit review
        if status == "possible_segmentation":
            return (
                "promote_with_uncertainty",
                "Commission formally assessed this market but left segmentation open. "
                "Review whether this should be a narrower market or candidate submarket "
                "before promoting to canonical.",
            )
        # Rule 6: core_assessed + conclusive status + refs → promote
        if status in _CONCLUSIVE_STATUSES and has_source_refs:
            return (
                "promote_to_canonical",
                f"Commission core_assessed this market with {status!r} definition; "
                "supported by cited source passages.",
            )
        # Rules 8–9: core_assessed but lacking status or refs → manual review
        if has_source_refs and status not in _CONCLUSIVE_STATUSES:
            return (
                "manual_review",
                f"Commission assessed this market but definition status is {status!r}; "
                "verify conclusion and refs before promoting to canonical.",
            )
        return (
            "manual_review",
            "Market classified as core_assessed but lacks source passages or conclusive "
            "definition status; manual review required before canonical promotion.",
        )

    # Rule 10–11: assessed_no_overlap
    if imp == "assessed_no_overlap":
        if has_source_refs:
            return (
                "promote_to_canonical",
                "Commission formally assessed this market (no party overlap); "
                "supported by cited source passages. Preserve no-overlap status in schema notes.",
            )
        return (
            "manual_review",
            f"Market classified as assessed_no_overlap but no source passages validated; "
            "verify quotes before promoting.",
        )

    # Rule 12: possible_segmentation (implicit importance classification)
    if status == "possible_segmentation":
        return (
            "promote_with_uncertainty",
            "Segmentation was considered but left open by the Commission. "
            "This may be a narrower market or candidate for submarket definition. "
            "Review before adding to canonical market list.",
        )

    # Rule 13: has refs but no recognised importance
    if has_source_refs:
        return (
            "manual_review",
            "Market has source citations but importance/assessment type is unclassified; "
            "review classification and Commission conclusion before deciding on promotion.",
        )

    # Rule 14: unknown status with unrecognised importance — hold for review
    if unknown_status:
        return (
            "hold_pending_source_check",
            "Definition status is unknown; cannot determine promotion without "
            "a clear Commission conclusion on market definition.",
        )

    return (
        "manual_review",
        "Insufficient information to determine promotion action automatically.",
    )


def _build_promotion_plan(
    draft_record: dict,
    ref_map: dict[str, list[str]],
) -> list[dict]:
    """Build a source-first promotion plan for all draft product and geographic markets.

    Works without an existing canonical YAML — it operates purely on the draft
    record and the source_passages citation map.

    Returns a list of dicts, one per draft market, ordered product then geographic.
    """
    plan: list[dict] = []

    def _process_market_list(items: list[dict], market_type: str) -> None:
        for m in items:
            mid = str(m.get("market_id") or "")
            importance = str(m.get("market_importance") or "")
            status = str(m.get("definition_status") or "")
            source_refs = list(dict.fromkeys(ref_map.get(mid, [])))
            action, reason = _promotion_action(importance, status, bool(source_refs))
            entry: dict = {
                "draft_name": m.get("name", ""),
                "draft_market_type": market_type,
                "market_importance": importance,
                "definition_status": status,
                "recommended_action": action,
                "reason": reason,
            }
            if source_refs:
                entry["source_refs"] = source_refs
            plan.append(entry)

    _process_market_list(
        draft_record.get("product_markets_considered") or [], "product"
    )
    _process_market_list(
        draft_record.get("geographic_markets_considered") or [], "geographic"
    )
    return plan


# ---------------------------------------------------------------------------
# Report serialisation
# ---------------------------------------------------------------------------

def _finding_to_dict(f: "ReconciliationFinding") -> dict:
    """Serialize a single finding to a JSON-safe dict, including draft metadata."""
    d: dict = {
        "group": f.group,
        "finding_type": f.finding_type,
        "existing_id": f.existing_id,
        "existing_name": f.existing_name,
        "draft_name": f.draft_name,
        "similarity": round(f.similarity, 3),
        "message": f.message,
    }
    # Draft market metadata — only include keys when they carry a value,
    # to keep the output lean for findings without a draft counterpart.
    if f.draft_market_type:
        d["draft_market_type"] = f.draft_market_type
    if f.draft_market_importance:
        d["draft_market_importance"] = f.draft_market_importance
    if f.draft_definition_status:
        d["draft_definition_status"] = f.draft_definition_status
    if f.draft_source_refs:
        d["draft_source_refs"] = f.draft_source_refs
    return d


def _group_reconciliation(findings: list[ReconciliationFinding]) -> dict:
    """Return reconciliation findings partitioned into the four review groups."""
    groups: dict[str, list[dict]] = {
        "matched": [],
        "likely_rename": [],
        "candidate_addition": [],
        "out_of_scope": [],
    }
    for f in findings:
        g = f.group or _RECON_GROUP.get(f.finding_type, "out_of_scope")
        groups.setdefault(g, []).append(_finding_to_dict(f))
    return groups


def _build_reconciliation_triage(findings: list[ReconciliationFinding]) -> dict:
    """Summarise candidate additions by market_importance, definition_status, and market_type.

    Enables source-first merge triage: 'how many core_assessed markets need review'
    vs 'how many are precedent_only or background and can be skipped for now'.
    """
    candidates = [f for f in findings if f.finding_type == "new_from_source"]
    by_importance: dict[str, int] = {}
    by_status: dict[str, int] = {}
    by_type: dict[str, int] = {}
    for f in candidates:
        imp = f.draft_market_importance or "unclassified"
        status = f.draft_definition_status or "unclassified"
        mtype = f.draft_market_type or "unclassified"
        by_importance[imp] = by_importance.get(imp, 0) + 1
        by_status[status] = by_status.get(status, 0) + 1
        by_type[mtype] = by_type.get(mtype, 0) + 1
    return {
        "total_candidate_additions": len(candidates),
        "by_market_importance": by_importance,
        "by_definition_status": by_status,
        "by_market_type": by_type,
    }


def _serialize_promotion_plan(draft_record: Optional[dict]) -> list[dict]:
    """Build and return the promotion plan for *draft_record*, or [] when no draft exists."""
    if not draft_record:
        return []
    # Rebuild ref_map from the draft's source_passages (same logic as in _reconcile).
    ref_map: dict[str, list[str]] = {}
    for sp in (draft_record.get("source_passages") or []):
        page = str(sp.get("page", "") or "").strip()
        if not page:
            continue
        for mid in (sp.get("supports_markets") or []):
            ref_map.setdefault(mid, []).append(page)
        for mid in (sp.get("supports_geographic_markets") or []):
            ref_map.setdefault(mid, []).append(page)
    return _build_promotion_plan(draft_record, ref_map)


def serialize_report(report: ExtractionReport, mode: str = "extract") -> dict:
    chunks_summary = [
        {
            "chunk_id": c.chunk_id,
            "section_path": c.section_path,
            "page_range": c.page_range,
            "page_count": len(c.pages),
            "source_document_id": c.source_document_id,
        }
        for c in report.chunks_used
    ]
    extraction_summary: dict = {}
    if report.result:
        r = report.result
        extraction_summary = {
            "product_markets_found": len(r.product_markets),
            "geographic_markets_found": len(r.geographic_markets),
            "theories_found": len(r.theories),
            "overall_outcome": r.overall_outcome,
            "passages_validated": r.passages_validated,
            "passages_rejected": r.passages_rejected,
            "caveats": r.caveats,
            "background_concepts": r.background_concepts,
        }
    section_batches_summary = [
        {
            "prefix": b.prefix,
            "section_label": b.section_label,
            "chunk_count": len(b.chunks),
            "page_count": sum(len(c.pages) for c in b.chunks),
            "success": b.result is not None,
            "error": b.error,
            "debug_path": str(b.debug_path) if b.debug_path else None,
        }
        for b in report.section_batches
    ]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tool": "extract_case_from_source",
        "mode": mode,
        "case_id": report.case_id,
        "yaml_path": str(report.yaml_path),
        "draft_yaml_path": str(report.draft_yaml_path) if report.draft_yaml_path else None,
        "error": report.error,
        "chunks_used": chunks_summary,
        "section_batches": section_batches_summary,
        "extraction_summary": extraction_summary,
        "promotion_plan": _serialize_promotion_plan(report.draft_record),
        "promotion_plan_note": (
            "promotion_plan is the authoritative source-first canonicalisation aid. "
            "Each market's recommended_action (promote_to_canonical, keep_as_context_only, etc.) "
            "is derived from the Commission's assessment in source documents. "
            "Reconciliation sections below are supplementary only and should not override these decisions."
        ),
        "reconciliation": [_finding_to_dict(f) for f in report.findings],
        "reconciliation_note": (
            "Reconciliation findings compare the extracted draft against any existing canonical YAML. "
            "These are supplementary context only. Use promotion_plan as the authoritative guide for "
            "canonicalisation decisions."
        ),
        "reconciliation_grouped": _group_reconciliation(report.findings),
        "reconciliation_triage": _build_reconciliation_triage(report.findings),
    }


# ---------------------------------------------------------------------------
# Main extraction function
# ---------------------------------------------------------------------------

def extract_case(
    yaml_path: Path,
    *,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    output_path: Optional[Path] = None,
    report_json: Optional[Path] = None,
    use_claude: bool = True,
    anthropic_client=None,
    max_input_pages: int = _MAX_INPUT_PAGES,
    max_chunks: Optional[int] = None,
    debug_dir: Optional[Path] = None,
    focus: Optional[str] = None,
    batch_by_section: bool = False,
    section_prefix: Optional[str] = None,
    max_section_batches: Optional[int] = None,
    max_cost: Optional[float] = None,
    max_input_tokens: Optional[int] = None,
) -> ExtractionReport:
    """
    Load the existing YAML and PDF text cache, extract a draft record via Claude,
    and reconcile the draft against the existing YAML.

    Never overwrites the canonical YAML.  *output_path* must contain ".draft"
    in its stem if provided.

    When *batch_by_section* is True or *section_prefix* is set, chunks are
    grouped by their X.Y section prefix and each group is sent as a separate
    Claude call.  Failed sections are recorded in report.section_batches but
    do not abort the run.
    """
    with open(yaml_path) as fh:
        existing_record: dict = yaml.safe_load(fh)

    case_id = existing_record.get("case_id", yaml_path.stem)
    report = ExtractionReport(case_id=case_id, yaml_path=yaml_path)

    # Safety gate: refuse to write unless path is clearly a draft.
    if output_path and output_path.exists() and ".draft" not in output_path.stem:
        report.error = (
            f"Refusing to overwrite '{output_path}' — path does not contain '.draft'. "
            "Use a path like 'case.draft.yaml' to write draft output."
        )
        return report

    # Load page caches
    source_docs = existing_record.get("source_documents") or []
    page_cache_map: dict[str, dict] = {}
    for doc in source_docs:
        doc_id = doc.get("doc_id", "")
        if doc_id:
            cache = load_cache(doc_id, cache_dir)
            if cache:
                page_cache_map[doc_id] = cache

    if not page_cache_map:
        report.error = (
            "No page caches available — run "
            "repair_source_passages.py --build-cache first"
        )
        return report

    # Build and select chunks
    all_chunks: list[ChunkInfo] = []
    for doc_id, cache in page_cache_map.items():
        smap = _extract_section_map(cache)
        all_chunks.extend(_build_chunks(cache, smap))

    all_chunks.sort(key=lambda c: min(c.page_numbers) if c.page_numbers else 0)
    selected = _select_relevant_chunks(
        all_chunks, max_total_pages=max_input_pages, focus=focus
    )
    if max_chunks is not None:
        selected = selected[:max_chunks]

    # Apply section prefix filter across ALL modes (inspect, estimate, single-batch, batched).
    if section_prefix is not None:
        _prefix = section_prefix.strip()
        _filtered = [c for c in selected if _section_batch_prefix(c.section_path) == _prefix]
        if not _filtered:
            report.error = f"No chunks matched section prefix '{_prefix}'"
            return report
        # Trim and build selected, excluding any chunk whose first page starts with a
        # non-target sibling heading (those chunks have no target content to contribute).
        # Original pages are preserved for quote validation; trimmed_pages feed the prompt.
        selected = []
        for c in _filtered:
            tp = _trim_pages_for_prefix(c.pages, _prefix)
            if not tp:
                # _trim_pages_for_prefix returns [] when the first heading on the first
                # page is a non-target sibling — this chunk has no target content.
                continue
            selected.append(ChunkInfo(
                chunk_id=c.chunk_id,
                section_path=c.section_path,
                pages=c.pages,
                source_document_id=c.source_document_id,
                trimmed_pages=tp,
            ))
        if not selected:
            report.error = (
                f"No chunks with target content matched section prefix '{_prefix}' "
                "(all matched chunks began with a sibling section heading)"
            )
            return report
        # Include spillover: the immediately following chunk (in document order) may
        # start with remaining target-section text before the next sibling heading.
        # E.g. page 40 is assigned to 8.7 by the section map because it contains the
        # 8.7 heading, but may begin with 8.6.2.3 text before that heading.
        # Use _last_page from selected (not _filtered) so the next-chunk lookup starts
        # at the right place even when some prefix-matched chunks were excluded above.
        _last_page = max(p["page_number"] for c in selected for p in c.pages)
        _next_chunk = next(
            (c for c in all_chunks if c.page_numbers and min(c.page_numbers) > _last_page),
            None,
        )
        if _next_chunk is not None:
            _spill = _extract_spillover_pages(_next_chunk.pages, _prefix)
            if _spill:
                _spill_page_nums = {p["page_number"] for p in _spill}
                _orig_pages = [p for p in _next_chunk.pages if p["page_number"] in _spill_page_nums]
                selected.append(ChunkInfo(
                    chunk_id=f"{_next_chunk.chunk_id}_spill",
                    section_path=_next_chunk.section_path,
                    pages=_orig_pages,
                    source_document_id=_next_chunk.source_document_id,
                    trimmed_pages=_spill,
                    effective_prefix=_prefix,
                ))

    report.chunks_used = selected

    if not use_claude:
        return report

    if anthropic_client is None:
        report.error = (
            "Claude client not available — pass anthropic_client or "
            "set ANTHROPIC_API_KEY"
        )
        return report

    if not selected:
        if focus:
            report.error = (
                f"No chunks matched focus '{focus}'. "
                "Try --inspect-chunks to see available section labels."
            )
        else:
            report.error = "No relevant chunks found — is the page cache populated?"
        return report

    _effective_debug_dir = debug_dir if debug_dir is not None else cache_dir / "debug"

    # Cost / token guard — abort before any API call if limit would be exceeded.
    if max_cost is not None or max_input_tokens is not None:
        _total_chars = sum(len(c.prompt_text) for c in selected)
        _approx_tokens = _total_chars // 4
        _est_cost = _approx_tokens / 1_000_000 * 3.0
        if max_input_tokens is not None and _approx_tokens > max_input_tokens:
            report.error = (
                f"Estimated {_approx_tokens:,} input tokens exceeds "
                f"--max-input-tokens={max_input_tokens:,} — not calling Claude"
            )
            return report
        if max_cost is not None and _est_cost > max_cost:
            report.error = (
                f"Estimated cost ${_est_cost:.4f} exceeds "
                f"--max-cost=${max_cost:.4f} — not calling Claude"
            )
            return report

    # -----------------------------------------------------------------------
    # Batched extraction path: one Claude call per section prefix
    # -----------------------------------------------------------------------
    if batch_by_section or section_prefix is not None:
        # selected is already prefix-filtered; just group whatever remains.
        groups = _group_chunks_by_section_prefix(selected)

        if max_section_batches is not None:
            groups = groups[:max_section_batches]

        total_pages = sum(len(c.pages) for chunks in (g for _, g in groups) for c in chunks)
        print(
            f"Batched extraction: {len(groups)} section groups, "
            f"{total_pages} total pages"
        )

        section_results: list[ExtractionResult] = []
        for prefix, group_chunks in groups:
            batch = _extract_section_batch(
                prefix, group_chunks, existing_record,
                anthropic_client, _effective_debug_dir, case_id,
            )
            report.section_batches.append(batch)
            if batch.error:
                print(f"  WARN: {batch.error}")
            elif batch.result is not None:
                section_results.append(batch.result)

        if not section_results:
            failed = [b.prefix for b in report.section_batches if b.error]
            report.error = (
                f"All {len(failed)} section batch(es) failed — "
                "see debug JSON files for details"
            )
            return report

        result = _merge_extraction_results(section_results)
        result.raw_response = f"batched ({len(section_results)}/{len(groups)} sections succeeded)"
        report.result = result

    # -----------------------------------------------------------------------
    # Single-batch extraction path (original)
    # -----------------------------------------------------------------------
    else:
        chunk_doc_map = {c.chunk_id: c.source_document_id for c in selected}

        total_pages = sum(len(c.pages) for c in selected)
        total_chars = sum(len(c.full_text) for c in selected)
        approx_tokens = total_chars // 4
        print(
            f"Claude call: {len(selected)} chunks, {total_pages} pages, "
            f"~{approx_tokens:,} tokens"
        )

        prompt = _build_extraction_prompt(selected, existing_record)
        try:
            response_text = _call_claude(prompt, anthropic_client)
        except Exception as exc:
            report.error = f"Claude API error: {exc}"
            return report

        # Parse
        try:
            raw = _parse_extraction_response(
                response_text, debug_dir=_effective_debug_dir, case_id=case_id
            )
        except ValueError as exc:
            report.error = f"Failed to parse Claude response: {exc}"
            return report

        # Empty-object guard
        if not raw:
            _effective_debug_dir.mkdir(parents=True, exist_ok=True)
            debug_path = _effective_debug_dir / f"{case_id}_claude_raw_response.txt"
            debug_path.write_text(response_text, encoding="utf-8")
            report.error = (
                f"Claude returned empty extraction object — raw response saved to {debug_path}"
            )
            return report

        # Envelope merge + normalise + validate
        merged = dict(_DEFAULT_EXTRACTION_ENVELOPE)
        merged.update(raw)
        raw = merged
        raw, norm_errors = _normalize_list_fields(raw)
        schema_errors = _validate_extraction_schema(raw)
        all_errors = norm_errors + schema_errors
        if all_errors:
            if _should_attempt_repair(norm_errors, schema_errors):
                print("  WARN: Stringified list fields detected — attempting repair call")
                _effective_debug_dir.mkdir(parents=True, exist_ok=True)
                err_path = _effective_debug_dir / f"{case_id}_claude_raw_response.txt"
                err_path.write_text(response_text, encoding="utf-8")
                try:
                    repaired_text = _call_claude_repair(response_text, all_errors, anthropic_client)
                    repaired_raw = _parse_extraction_response(
                        repaired_text, debug_dir=None, case_id=""
                    )
                except Exception as exc:
                    report.error = (
                        f"Schema validation failed and repair call errored: {exc}\n"
                        + "Original errors:\n"
                        + "\n".join(f"  - {e}" for e in all_errors)
                        + f"\nOriginal response saved to {err_path}"
                    )
                    return report

                if not repaired_raw:
                    report.error = (
                        "Schema validation failed; repair returned empty object.\n"
                        "Original errors:\n"
                        + "\n".join(f"  - {e}" for e in all_errors)
                        + f"\nOriginal response saved to {err_path}"
                    )
                    return report

                r_merged = dict(_DEFAULT_EXTRACTION_ENVELOPE)
                r_merged.update(repaired_raw)
                repaired_raw = r_merged
                repaired_raw, r_norm_errors = _normalize_list_fields(repaired_raw)
                r_all_errors = r_norm_errors + _validate_extraction_schema(repaired_raw)
                if r_all_errors:
                    repair_path = _effective_debug_dir / f"{case_id}_repair_response.txt"
                    repair_path.write_text(repaired_text, encoding="utf-8")
                    report.error = (
                        "Repair retry still failed:\n"
                        + "\n".join(f"  - {e}" for e in r_all_errors)
                        + f"\nRepaired response saved to {repair_path}"
                    )
                    return report

                print("  Repair succeeded")
                raw = repaired_raw
                response_text = repaired_text
            else:
                _effective_debug_dir.mkdir(parents=True, exist_ok=True)
                debug_path = _effective_debug_dir / f"{case_id}_claude_raw_response.txt"
                debug_path.write_text(response_text, encoding="utf-8")
                report.error = (
                    "Claude response failed schema validation:\n"
                    + "\n".join(f"  - {e}" for e in all_errors)
                    + f"\nRaw response saved to {debug_path}"
                )
                return report

        result = _validate_extraction(raw, selected, chunk_doc_map)
        result.raw_response = response_text
        report.result = result

    # Enforce focus-mode output constraints (strips out-of-scope types, forces outcome).
    result = _apply_focus_guardrails(result, focus)
    report.result = result

    # Build draft and reconcile
    draft = _build_draft_record(result, existing_record)
    report.draft_record = draft
    report.findings = _reconcile(draft, existing_record, focus=focus)

    # Write outputs
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as fh:
            yaml.dump(
                draft, fh,
                allow_unicode=True, default_flow_style=False, sort_keys=False,
            )
        report.draft_yaml_path = output_path

    if report_json:
        report_json.parent.mkdir(parents=True, exist_ok=True)
        payload = serialize_report(report)
        with open(report_json, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)

    return report


# ---------------------------------------------------------------------------
# Debug replay (re-run validation on a saved debug JSON without calling Claude)
# ---------------------------------------------------------------------------

def replay_section_debug(
    debug_path: Path,
    yaml_path: Path,
    *,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    output_path: Optional[Path] = None,
    debug_dir: Optional[Path] = None,
) -> ExtractionReport:
    """Re-run the normalisation/validation pipeline on a saved section debug JSON.

    Loads raw_tool_input from *debug_path*, reconstructs the relevant chunks
    from the page cache, and re-runs the full pipeline (envelope merge →
    normalise → validate schema → validate quotes → draft + reconcile)
    without calling Claude again.

    Useful for recovering from a section that failed validation due to a
    fixable parsing issue (e.g. source_passages returned as a JSON string).
    """
    with open(debug_path) as fh:
        debug_data = json.load(fh)

    with open(yaml_path) as fh:
        existing_record: dict = yaml.safe_load(fh)

    case_id = debug_data.get("case_id", yaml_path.stem)
    section_prefix = debug_data.get("section_prefix", "")
    report = ExtractionReport(case_id=case_id, yaml_path=yaml_path)

    # Safety gate: refuse to write unless path is clearly a draft.
    if output_path and output_path.exists() and ".draft" not in output_path.stem:
        report.error = (
            f"Refusing to overwrite '{output_path}' — path does not contain '.draft'. "
            "Use a path like 'case.draft.yaml' to write draft output."
        )
        return report

    raw_tool_input = debug_data.get("raw_tool_input")
    if raw_tool_input is None:
        report.error = f"No 'raw_tool_input' found in debug file: {debug_path}"
        return report
    if not raw_tool_input:
        report.error = (
            f"'raw_tool_input' in debug file is empty ({{}}) — nothing to replay: {debug_path}"
        )
        return report

    # Rebuild chunks from page cache so quote validation can run.
    source_docs = existing_record.get("source_documents") or []
    page_cache_map: dict[str, dict] = {}
    for doc in source_docs:
        doc_id = doc.get("doc_id", "")
        if doc_id:
            cache = load_cache(doc_id, cache_dir)
            if cache:
                page_cache_map[doc_id] = cache

    all_chunks: list[ChunkInfo] = []
    for doc_id, cache in page_cache_map.items():
        smap = _extract_section_map(cache)
        all_chunks.extend(_build_chunks(cache, smap))

    if section_prefix:
        chunks = [c for c in all_chunks if _section_batch_prefix(c.section_path) == section_prefix]
    else:
        chunks = all_chunks

    report.chunks_used = chunks

    if not page_cache_map:
        print(
            "WARN: No page caches available — quotes will not be validated. "
            "Run repair_source_passages.py --build-cache first for quote validation.",
            file=sys.stderr,
        )

    # Envelope merge + normalise + validate schema
    merged = dict(_DEFAULT_EXTRACTION_ENVELOPE)
    merged.update(raw_tool_input)
    raw: dict = merged
    raw, norm_errors = _normalize_list_fields(raw)
    all_errors = norm_errors + _validate_extraction_schema(raw)
    if all_errors:
        _eff_debug_dir = debug_dir if debug_dir is not None else cache_dir / "debug"
        _eff_debug_dir.mkdir(parents=True, exist_ok=True)
        debug_out = _eff_debug_dir / f"{case_id}_replay_{section_prefix.replace('.', '_')}_errors.json"
        with open(debug_out, "w", encoding="utf-8") as fh:
            json.dump({"validation_errors": all_errors, "replayed_from": str(debug_path)}, fh, indent=2)
        report.error = (
            "Replay validation failed:\n"
            + "\n".join(f"  - {e}" for e in all_errors)
            + f"\nDebug saved to {debug_out}"
        )
        return report

    chunk_doc_map = {c.chunk_id: c.source_document_id for c in chunks}
    result = _validate_extraction(raw, chunks, chunk_doc_map)
    result.raw_response = f"replayed from {debug_path.name}"
    report.result = result

    draft = _build_draft_record(result, existing_record)
    report.draft_record = draft
    report.findings = _reconcile(draft, existing_record)

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as fh:
            yaml.dump(draft, fh, allow_unicode=True, default_flow_style=False, sort_keys=False)
        report.draft_yaml_path = output_path

    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Source-first extraction and reconciliation for CompMap cases"
    )
    parser.add_argument("--case-id", required=True, help="Case ID to process")
    parser.add_argument(
        "--cases-dir", default=str(_CASES_DIR),
        help=f"Path to data/cases (default: {_CASES_DIR})",
    )
    parser.add_argument(
        "--cache-dir", default=str(DEFAULT_CACHE_DIR),
        help=f"Path to source_text cache (default: {DEFAULT_CACHE_DIR})",
    )
    parser.add_argument(
        "--output", metavar="PATH",
        help="Draft YAML output path (must contain .draft in stem)",
    )
    parser.add_argument(
        "--report-json", metavar="PATH",
        help="JSON reconciliation report path",
    )
    parser.add_argument(
        "--no-claude", action="store_true",
        help="Section-analysis only — list chunks without calling Claude",
    )
    parser.add_argument(
        "--inspect-chunks", action="store_true",
        help=(
            "Print selected chunk IDs, page ranges, section labels, and first 500 "
            "characters; do not call Claude or write any output files."
        ),
    )
    parser.add_argument(
        "--max-pages", type=int, default=_MAX_INPUT_PAGES,
        help=f"Max pages sent to Claude per call (default: {_MAX_INPUT_PAGES})",
    )
    parser.add_argument(
        "--max-chunks", type=int, default=None,
        help="Limit number of chunks passed to Claude (useful for testing)",
    )
    parser.add_argument(
        "--focus",
        choices=list(_FOCUS_TERMS),
        default=None,
        help="Restrict chunk selection to sections matching this extraction focus",
    )
    parser.add_argument(
        "--estimate-cost", action="store_true",
        help="Print chunk/page/token count for selected chunks; do not call Claude.",
    )
    parser.add_argument(
        "--batch-by-section", action="store_true",
        help="Run one Claude call per section prefix instead of one call for all chunks.",
    )
    parser.add_argument(
        "--section-prefix", metavar="PREFIX", default=None,
        help="Process only the section batch matching this prefix (e.g. '8.6').",
    )
    parser.add_argument(
        "--max-section-batches", type=int, default=None,
        help="Limit number of section batches (useful for testing).",
    )
    parser.add_argument(
        "--max-cost", type=float, default=None, metavar="DOLLARS",
        help="Abort if estimated Claude cost exceeds this amount (e.g. 0.50).",
    )
    parser.add_argument(
        "--max-input-tokens", type=int, default=None, metavar="TOKENS",
        help="Abort if estimated input token count exceeds this amount.",
    )
    parser.add_argument(
        "--replay-debug", metavar="PATH", default=None,
        help=(
            "Load a saved section debug JSON and re-run the validation pipeline "
            "without calling Claude. Pair with --case-id (to load the YAML) and "
            "optionally --output for the draft YAML."
        ),
    )
    args = parser.parse_args()

    cases_dir = Path(args.cases_dir)
    cache_dir = Path(args.cache_dir)

    yaml_path = _resolve_canonical_yaml(args.case_id, cases_dir)
    if yaml_path is None:
        print(
            f"No canonical YAML found for case_id '{args.case_id}' in {cases_dir}.\n"
            "Hint: canonical files must be named exactly {case_id}.yaml with no "
            "'.draft' in the path.  Draft outputs should go under data/drafts/, "
            "not data/cases/.",
            file=sys.stderr,
        )
        return 1

    # --replay-debug: re-run validation on a saved debug JSON without calling Claude.
    if args.replay_debug:
        debug_path = Path(args.replay_debug)
        output_path = Path(args.output) if args.output else None
        print(f"Case:    {args.case_id}")
        print(f"YAML:    {yaml_path}")
        print(f"Cache:   {cache_dir}")
        print(f"Mode:    replay-debug ({debug_path.name})")
        print()
        rpt = replay_section_debug(
            debug_path,
            yaml_path,
            cache_dir=cache_dir,
            output_path=output_path,
        )
        if rpt.error:
            print(f"ERROR: {rpt.error}", file=sys.stderr)
        if rpt.result:
            r = rpt.result
            print(f"Extraction (replayed):")
            print(f"  Product markets:    {len(r.product_markets)}")
            print(f"  Geographic markets: {len(r.geographic_markets)}")
            print(f"  Theories of harm:   {len(r.theories)}")
            print(f"  Passages validated: {r.passages_validated}")
            print(f"  Passages rejected:  {r.passages_rejected}")
            if r.caveats:
                print("Caveats:")
                for cav in r.caveats:
                    print(f"  - {cav}")
        if rpt.draft_yaml_path:
            print(f"\nDraft YAML:   {rpt.draft_yaml_path}")
        return 0 if not rpt.error else 1

    # --inspect-chunks / --estimate-cost imply no Claude call and no file output
    inspect_mode = args.inspect_chunks
    estimate_mode = args.estimate_cost
    use_claude = not args.no_claude and not inspect_mode and not estimate_mode
    anthropic_client = None

    if use_claude:
        try:
            import anthropic as _anthropic
            anthropic_client = _anthropic.Anthropic(
                api_key=os.environ["ANTHROPIC_API_KEY"]
            )
        except (ImportError, KeyError):
            print(
                "anthropic package or ANTHROPIC_API_KEY not available — "
                "falling back to --no-claude mode"
            )
            use_claude = False

    no_output = inspect_mode or estimate_mode
    output_path = Path(args.output) if args.output and not no_output else None
    report_json = Path(args.report_json) if args.report_json and not no_output else None

    print(f"Case:    {args.case_id}")
    print(f"YAML:    {yaml_path}")
    print(f"Cache:   {cache_dir}")
    if args.focus:
        print(f"Focus:   {args.focus}")
    if args.section_prefix:
        print(f"Section prefix: {args.section_prefix}")
    if inspect_mode:
        print("Mode:    inspect-chunks (no Claude call)")
    elif estimate_mode:
        print("Mode:    estimate-cost (no Claude call)")
    elif args.batch_by_section or args.section_prefix:
        batch_desc = f"batched by section"
        if args.section_prefix:
            batch_desc += f" (prefix: {args.section_prefix})"
        if args.max_section_batches:
            batch_desc += f", max {args.max_section_batches} batches"
        print(f"Mode:    {batch_desc}")
    else:
        print(f"Claude:  {'enabled' if use_claude else 'disabled (section-analysis only)'}")
    print()

    rpt = extract_case(
        yaml_path,
        cache_dir=cache_dir,
        output_path=output_path,
        report_json=report_json,
        use_claude=use_claude,
        anthropic_client=anthropic_client,
        max_input_pages=args.max_pages,
        max_chunks=args.max_chunks,
        focus=args.focus,
        batch_by_section=args.batch_by_section,
        section_prefix=args.section_prefix,
        max_section_batches=args.max_section_batches,
        max_cost=args.max_cost,
        max_input_tokens=args.max_input_tokens,
    )

    if rpt.error:
        print(f"ERROR: {rpt.error}", file=sys.stderr)

    if estimate_mode:
        total_pages = sum(len(c.pages) for c in rpt.chunks_used)
        est_tokens = total_pages * 400  # ~400 tokens per page of PDF text
        print(f"Chunks selected:  {len(rpt.chunks_used)}")
        print(f"Pages selected:   {total_pages}")
        print(f"Est. input tokens:{est_tokens:>8,}  (~400 tokens/page)")

        if args.batch_by_section or args.section_prefix:
            # chunks_used is already prefix-filtered; just re-group for display
            groups = _group_chunks_by_section_prefix(rpt.chunks_used)
            if args.max_section_batches:
                groups = groups[:args.max_section_batches]
            print(f"Section batches:  {len(groups)}")
            print()
            total_cost = 0.0
            for prefix, gchunks in groups:
                gpages = sum(len(c.pages) for c in gchunks)
                gtokens = gpages * 400
                gcost = gtokens / 1_000_000 * 3.0
                total_cost += gcost
                label = _section_label_for_batch(prefix, gchunks)
                print(f"  {prefix:6s}  {gpages:3d} pages  ~{gtokens:6,} tokens  ${gcost:.4f}  [{label[:55]}]")
            print(f"\nTotal est. cost:  ${total_cost:.4f}  (at $3/M tokens, Sonnet 4.6)")
        else:
            cost = est_tokens / 1_000_000 * 3.0
            print(f"Est. input cost:  ${cost:.4f}  (at $3/M tokens, Sonnet 4.6)")
            print()
            for c in rpt.chunks_used:
                label = c.section_path if c.section_path else "unknown"
                print(f"  {c.chunk_id}  {c.page_range}  ({len(c.pages)} pages)  [{label[:70]}]")
        return 0 if not rpt.error else 1

    if inspect_mode:
        sep = "-" * 72
        print(f"Selected chunks: {len(rpt.chunks_used)}\n")
        for c in rpt.chunks_used:
            label = c.section_path if c.section_path else "unknown"
            spill_note = f"  [spillover for {c.effective_prefix}]" if c.effective_prefix else ""
            print(f"{c.chunk_id}  {c.page_range}  [{label}]{spill_note}")
            preview = c.prompt_text[:500]  # trimmed text if section_prefix was applied
            if len(c.prompt_text) > 500:
                preview += " …"
            print(preview)
            print(sep)
        return 0 if not rpt.error else 1

    print(f"Chunks selected: {len(rpt.chunks_used)}")
    for c in rpt.chunks_used:
        label = f" [{c.section_path[:65]}]" if c.section_path else ""
        print(f"  {c.chunk_id}{label}: {c.page_range} ({len(c.pages)} pages)")

    if rpt.section_batches:
        succeeded = sum(1 for b in rpt.section_batches if b.result is not None)
        print(f"\nSection batches: {succeeded}/{len(rpt.section_batches)} succeeded")
        for b in rpt.section_batches:
            status = "ok" if b.result is not None else "FAIL"
            label = b.section_label[:60]
            print(f"  [{status}] {b.prefix:6s} {label}")
            if b.error:
                print(f"          {b.error[:100]}")

    if rpt.result:
        r = rpt.result
        print(f"\nExtraction:")
        print(f"  Product markets:    {len(r.product_markets)}")
        print(f"  Geographic markets: {len(r.geographic_markets)}")
        print(f"  Theories of harm:   {len(r.theories)}")
        print(f"  Overall outcome:    {r.overall_outcome}")
        print(f"  Passages validated: {r.passages_validated}")
        print(f"  Passages rejected:  {r.passages_rejected}")
        if r.caveats:
            print("\nCaveats:")
            for cav in r.caveats:
                print(f"  - {cav}")

        print(f"\nReconciliation ({len(rpt.findings)} findings):")
        markers = {
            "supported_as_is": "  ✓",
            "should_be_renamed": "  ~",
            "unsupported_remove": "  ✗",
            "new_from_source": "  +",
        }
        for f in rpt.findings:
            m = markers.get(f.finding_type, "  ?")
            name = f.existing_name or f.draft_name
            print(f"{m} [{f.existing_id or 'new'}] {name[:60]}")
            print(f"     {f.message[:90]}")

    if rpt.draft_yaml_path:
        print(f"\nDraft YAML:   {rpt.draft_yaml_path}")
    if report_json:
        print(f"Report JSON:  {report_json}")

    return 0 if not rpt.error else 1


if __name__ == "__main__":
    sys.exit(main())
