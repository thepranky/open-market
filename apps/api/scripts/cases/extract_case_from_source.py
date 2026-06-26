#!/usr/bin/env python3
"""
extract_case_from_source.py — source-first extraction/reconciliation for Meridian.

Loads the existing PDF text cache for a case, extracts a fresh draft CaseRecord
via Claude, then reconciles the draft against the existing YAML.

The output is always a draft + reconciliation report.  It never overwrites
the canonical YAML.  Draft outputs go under data/drafts/, never data/cases/.

Usage:
    cd apps/api

    # Full extraction with Claude:
    .venv/bin/python scripts/cases/extract_case_from_source.py \\
        --case-id eu_google_fitbit_2021 \\
        --output ../../data/drafts/eu/google_fitbit_2021.draft.yaml \\
        --report-json ../../data/source_text/google_fitbit_extraction_report.json

    # Section-analysis only (no API call):
    .venv/bin/python scripts/cases/extract_case_from_source.py \\
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

_API_DIR = Path(__file__).resolve().parents[2]
_REPO_ROOT = _API_DIR.parents[1]
sys.path.insert(0, str(_API_DIR))
sys.path.insert(0, str(Path(__file__).parent))

try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv(_REPO_ROOT / ".env", override=False)
except ImportError:
    pass

from app.shared.utils.pdf_extractor import DEFAULT_CACHE_DIR, iter_pages, load_cache
from check_source_integrity import quote_found_in_text
from pipeline_profile import select_profile
from repair_source_passages import _extract_section_map, _is_toc_page

_CASES_DIR = Path(__file__).resolve().parents[4] / "data" / "cases"
_DRAFTS_DIR = Path(__file__).resolve().parents[4] / "data" / "drafts"


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

_DEBUG_DIR = Path(__file__).resolve().parents[4] / "data" / "source_text" / "debug"

_VALID_OUTCOMES: frozenset[str] = frozenset({
    "cleared", "cleared_with_conditions", "blocked", "pending", "unknown",
})

_VALID_COMMITMENT_TYPES: frozenset[str] = frozenset({
    "structural", "behavioral", "access", "other",
})

_VALID_THEORY_TYPES: frozenset[str] = frozenset({
    "horizontal", "vertical", "conglomerate", "data", "innovation", "other",
})

_VALID_PROCEDURE_STAGES: frozenset[str] = frozenset({
    "phase1", "phase2", "unknown",
})

# Precise market definition status values (old values kept for backward compat).
_VALID_MARKET_STATUSES: frozenset[str] = frozenset({
    "defined", "left_open", "discussed", "segmented", "unknown",      # legacy
    "considered", "not_conclusive", "segmented", "precedent_only",  # new
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
    "segmented",# Commission considered segmentation but left it open
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
    "not_conclusive": 3, "segmented": 2, "precedent_only": 1, "unknown": 0,
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
    "commitments": [],
}

# All list fields the extraction schema expects (including optional extras Claude may add).
_EXPECTED_LIST_FIELDS: tuple[str, ...] = (
    "product_markets",
    "geographic_markets",
    "theories_of_harm",
    "caveats",
    "background_concepts",
    "remedies",
    "commitments",
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
        "innovation",
        "innovation spaces",
        "r&d",
        "pipeline",
        "leading innovators",
        "pipeline products",
        "research and development",
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
    # outcome_metadata: empty tuple → _is_focused_section returns True for all sections,
    # so all pages in the (defaulted) pp.1-30 range are processed.
    "outcome_metadata": (),
    # unit_assessment: empty tuple → all pages in the supplied --page-range pass through.
    # Section-heading filtering would miss competitive-assessment tables; the caller
    # always supplies a narrow --page-range to scope the target crop/route/unit section.
    "unit_assessment": (),
}

# ---------------------------------------------------------------------------
# Neutral market-definition page-text fallback
# ---------------------------------------------------------------------------

# Neutral signals for the market-definition fallback selector.
# These reflect EU competition-law methodology and structure only.
# No industry-specific terms are included here.
_MARKET_DEF_FALLBACK_SIGNALS: tuple[str, ...] = (
    "relevant market",
    "relevant markets",
    "market definition",
    "product market",
    "product markets",
    "geographic market",
    "geographic markets",
    "relevant product market",
    "relevant geographic market",
    "demand-side substitut",
    "supply-side substitut",
    "substitutab",
    "competitive conditions",
    "plausible market definition",
    "exact scope of the market",
    "left open",
    "for the purpose of assessing",
    "no need to conclude on the exact market",
    "commission's assessment",
    "commission precedent",
    "notifying party",
    "market investigation",
    "definition of the relevant",
)

_MARKET_DEF_FALLBACK_MIN_SCORE: int = 2      # min signal hits for a primary candidate page
_MARKET_DEF_FALLBACK_CONTINUATION_MIN: int = 1  # min hits for an adjacent continuation page
_MAX_FALLBACK_PAGES: int = 40                # hard cap on total fallback pages
_MAX_FALLBACK_CHUNKS: int = 8                # hard cap on number of fallback chunks returned
# If section-path selection yields fewer than this many pages for market_definition focus,
# supplement with page-text fallback. Handles documents where footnote numbers are
# misread as section headings, leaving relevant pages under unrecognised labels.
_MARKET_DEF_SP_MIN_PAGES: int = 20
# For long decisions (≥ this many non-TOC pages), also trigger supplemental fallback when
# the section-path selection covers less than this fraction of the document.  Prevents
# section-path matching from silently returning partial coverage on long pharma/tech
# decisions where market-definition content is embedded in therapeutic-area or
# competitive-assessment sub-sections that lack "market definition" in their heading.
_MARKET_DEF_COVERAGE_MIN_RATIO: float = 0.25
_MARKET_DEF_COVERAGE_MIN_DOC_PAGES: int = 30  # only apply ratio check above this size

# Matches a first uppercase/heading-like line to infer a synthetic section label.
_FALLBACK_HEADING_RE = re.compile(
    r'^[ \t]*([A-Z][A-Z\s\-/]{4,})[ \t]*$',
    re.MULTILINE,
)

# Section-path regex patterns — defined early so they can be used in the fallback
# selector functions below as well as in the section-batch grouping helpers later.
_SECTION_PREFIX_RE = re.compile(r'\b(\d+\.\d+)\b')

# Matches section headings like "8.6 Title", "8.6. Title", "8.6.1 Title" at start of line.
# Requires an uppercase letter to follow so footnotes ("14 July 2020") are not matched.
_SECTION_TRIM_RE = re.compile(
    r'^(\d+(?:\.\d+)+)\.?[ \t]+[A-Z]',
    re.MULTILINE,
)


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
    selection_method: str = "section_path"  # "section_path" | "page_text_fallback"

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
    theory_type: str     # "horizontal" | "vertical" | "conglomerate" | "data" | "innovation" | "other"
    theory_outcome: str  # "dismissed" | "upheld" | "remedied" | "unclear"
    notes: str
    passages: list[ExtractedPassage] = field(default_factory=list)
    not_found: bool = False


@dataclass
class ExtractedCommitment:
    title: str
    commitment_type: str  # "structural" | "behavioral" | "access" | "other"
    description: str
    divested_assets: list[str] = field(default_factory=list)
    purchaser_requirements: str = ""
    markets_addressed: list[str] = field(default_factory=list)
    passages: list[ExtractedPassage] = field(default_factory=list)
    not_found: bool = False


def _map_article_to_outcome(text: str) -> tuple[str, str]:
    """Map EU merger decision operative-article language to (outcome, procedure_stage).

    Returns values from _VALID_OUTCOMES and _VALID_PROCEDURE_STAGES.
    Returns ("unknown", "unknown") when no operative article is detectable.
    """
    lower = text.lower()
    # Article 8(3) → blocked, phase2  (check before 8(2) to avoid prefix match)
    if "article 8(3)" in lower or "article 8, paragraph 3" in lower:
        return "blocked", "phase2"
    # Article 8(2) → cleared_with_conditions, phase2
    if "article 8(2)" in lower or "article 8, paragraph 2" in lower:
        return "cleared_with_conditions", "phase2"
    # Article 8(1) → cleared, phase2
    if "article 8(1)" in lower or "article 8, paragraph 1" in lower:
        return "cleared", "phase2"
    # Article 6(2) → cleared_with_conditions, phase1
    if "article 6(2)" in lower or "article 6, paragraph 2" in lower:
        return "cleared_with_conditions", "phase1"
    # Article 6(1)(b) with conditions/commitments → cleared_with_conditions, phase1
    if "article 6(1)(b)" in lower and any(
        t in lower for t in ("condition", "commitment", "undertaking")
    ):
        return "cleared_with_conditions", "phase1"
    # Article 6(1)(b) plain → cleared, phase1
    if "article 6(1)(b)" in lower:
        return "cleared", "phase1"
    # Article 6(1)(c) → phase2 opened, not a final decision
    if "article 6(1)(c)" in lower:
        return "pending", "phase2"
    # Clearance language without explicit article reference
    if any(t in lower for t in (
        "does not raise serious doubts",
        "compatible with the internal market",
        "does not significantly impede effective competition",
    )):
        return "cleared", "unknown"
    return "unknown", "unknown"


@dataclass
class ExtractionResult:
    product_markets: list[ExtractedMarket] = field(default_factory=list)
    geographic_markets: list[ExtractedMarket] = field(default_factory=list)
    theories: list[ExtractedTheory] = field(default_factory=list)
    commitments: list[ExtractedCommitment] = field(default_factory=list)
    overall_outcome: str = "unknown"
    procedure_stage: str = "unknown"
    extracted_authority_reference: str = ""
    extracted_decision_date: str = ""
    # Top-level source_passages from Claude that are not nested under any market/theory/commitment.
    # Populated only for outcome_metadata focus (or when Claude returns unlinked passages).
    unlinked_passages: list[ExtractedPassage] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)
    background_concepts: list[str] = field(default_factory=list)
    passages_validated: int = 0
    passages_rejected: int = 0
    orphan_passages: int = 0  # source_passages not linked to any market/theory
    raw_response: str = ""
    section_label: str = ""  # set by section-batch extractor; used to scope caveats
    # Populated only for unit_assessment focus — list of validated unit dicts.
    unit_assessments: list[dict] = field(default_factory=list)


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
    # Set after chunk selection; used by the review report to warn on narrow coverage.
    selection_coverage: Optional[dict] = None  # keys: total_non_toc_pages, selected_pages, ratio


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


# ---------------------------------------------------------------------------
# Neutral market-definition page-text fallback selector (functions)
# ---------------------------------------------------------------------------

def _score_page_market_def(text: str) -> int:
    """Count neutral market-definition signal occurrences in *text*."""
    lower = text.lower()
    return sum(lower.count(sig) for sig in _MARKET_DEF_FALLBACK_SIGNALS)


def _infer_section_label_from_pages(pages: list[dict]) -> str:
    """Derive a synthetic section label from heading-like lines in the first two pages.

    Prefers numbered section headings (e.g. '8.3 Title'); falls back to an
    all-caps heading line; returns a generic label if nothing is found.
    """
    for page in pages[:2]:
        text = page.get("text", "")
        m = _SECTION_TRIM_RE.search(text)
        if m:
            line_end = text.find("\n", m.start())
            return text[m.start(): line_end if line_end > 0 else m.start() + 80].strip()[:80]
        m2 = _FALLBACK_HEADING_RE.search(text)
        if m2:
            return m2.group(1).strip()[:80]
    return "market definition (inferred)"


def _select_market_def_fallback_chunks(
    all_chunks: list[ChunkInfo],
    max_fallback_pages: int = _MAX_FALLBACK_PAGES,
    max_chunks: int = _MAX_FALLBACK_CHUNKS,
) -> list[ChunkInfo]:
    """Select market-definition chunks via neutral page-text scoring.

    Used when section-path selection returns no results for focus='market_definition'.
    Returned chunks carry selection_method='page_text_fallback'.
    Industry-specific terms are never used — only neutral EU market-definition signals.

    *max_chunks* caps the number of returned chunk groups (default: _MAX_FALLBACK_CHUNKS).
    Callers performing supplemental fallback on large documents should pass a higher value
    so that scattered market-definition sections (e.g. "Other Overlaps") are not cut off.
    """
    # Score every page once (first occurrence in document order wins for duplicates).
    page_info: dict[int, tuple[int, str, str]] = {}  # page_num → (score, text, doc_id)
    for chunk in all_chunks:
        for page in chunk.pages:
            pn = page["page_number"]
            if pn not in page_info:
                page_info[pn] = (
                    _score_page_market_def(page["text"]),
                    page["text"],
                    chunk.source_document_id,
                )

    if not page_info:
        return []

    primary = {pn for pn, (score, _, _) in page_info.items() if score >= _MARKET_DEF_FALLBACK_MIN_SCORE}
    if not primary:
        return []

    # Include adjacent pages as continuation when they carry at least the minimum signal.
    selected: set[int] = set(primary)
    for pn in list(primary):
        for adj in (pn - 1, pn + 1):
            if adj in page_info and adj not in selected:
                if page_info[adj][0] >= _MARKET_DEF_FALLBACK_CONTINUATION_MIN:
                    selected.add(adj)

    selected_sorted = sorted(selected)

    # Cap total pages, keeping highest-scoring and primary candidates first.
    if len(selected_sorted) > max_fallback_pages:
        ranked = sorted(
            selected_sorted,
            key=lambda pn: (-page_info[pn][0], pn not in primary, pn),
        )
        selected_sorted = sorted(ranked[:max_fallback_pages])

    # Group consecutive (or near-consecutive with ≤1-page gap) pages into chunks.
    groups: list[list[int]] = []
    current: list[int] = []
    for pn in selected_sorted:
        if not current or pn <= current[-1] + 2:
            current.append(pn)
        else:
            groups.append(current)
            current = [pn]
    if current:
        groups.append(current)

    # Cap number of chunks.
    groups = groups[:max_chunks]

    result: list[ChunkInfo] = []
    for group in groups:
        pages_list: list[dict] = []
        doc_id = ""
        for pn in group:
            _, text, d = page_info[pn]
            pages_list.append({"page_number": pn, "text": text})
            if not doc_id:
                doc_id = d

        section_label = _infer_section_label_from_pages(pages_list)
        page_prefix = (
            f"fallback_p{group[0]}"
            if len(group) == 1
            else f"fallback_p{group[0]}-{group[-1]}"
        )
        result.append(ChunkInfo(
            chunk_id=f"fallback_chunk_{len(result) + 1:03d}",
            section_path=section_label,
            pages=pages_list,
            source_document_id=doc_id,
            selection_method="page_text_fallback",
            effective_prefix=page_prefix,
        ))

    return result


def _select_theories_fallback_chunks(
    chunks: list[ChunkInfo],
    theory_terms: tuple[str, ...],
    max_fallback_pages: int = _MAX_FALLBACK_PAGES,
) -> list[ChunkInfo]:
    """
    Page-text fallback for theories focus when section-path matching finds nothing.

    Scans page text for profile-specific theory terms.  Only used when a profile
    is supplied and the section-path matching produced zero candidates.
    Bounded by max_fallback_pages to avoid sending the whole document.
    """
    scored: list[tuple[int, ChunkInfo]] = []
    for chunk in chunks:
        if not chunk.pages:
            continue
        full = chunk.full_text.lower()
        score = sum(1 for t in theory_terms if t in full)
        if score > 0:
            scored.append((score, chunk))

    scored.sort(key=lambda x: x[0], reverse=True)

    selected: list[ChunkInfo] = []
    total = 0
    for _, chunk in scored:
        n = len(chunk.pages)
        if total + n > max_fallback_pages:
            break
        chunk.selection_method = "page_text_fallback"
        selected.append(chunk)
        total += n

    selected.sort(key=lambda c: min(c.page_numbers) if c.page_numbers else 0)
    return selected


def _select_relevant_chunks(
    chunks: list[ChunkInfo],
    max_total_pages: int = _MAX_INPUT_PAGES,
    focus: Optional[str] = None,
    full_market_def_pass: bool = False,
    profile=None,
) -> list[ChunkInfo]:
    """
    Return relevant chunks up to *max_total_pages* total pages.

    When *focus* is 'market_definition':
    - Section-path matching is tried first (preferred path).
    - If zero chunks match, a neutral page-text fallback is used; returned
      chunks carry selection_method='page_text_fallback'.
    - Supplemental fallback is triggered when EITHER:
        (a) section-path yields fewer than _MARKET_DEF_SP_MIN_PAGES absolute pages, OR
        (b) the document has >= _MARKET_DEF_COVERAGE_MIN_DOC_PAGES non-TOC pages and
            section-path covers < _MARKET_DEF_COVERAGE_MIN_RATIO of them.
      Condition (b) catches long pharma/tech decisions where market-definition content
      is embedded in therapeutic-area or competitive-assessment sub-sections that lack
      "market definition" in their heading.
    - When *full_market_def_pass* is True, page-text fallback is always merged with
      section-path results regardless of thresholds, up to max_total_pages.

    When *focus* is 'theories' and a profile is supplied:
    - Section-path matching is tried first.
    - If zero chunks match, a page-text fallback using profile-specific theory terms
      is used (bounded fallback — never sends the whole document).

    For other focus values, only section-path matching is used (no fallback).
    Without a focus, section-path relevance is used with a broad fallback to
    all non-empty chunks.
    """
    total_non_toc_pages = sum(len(c.pages) for c in chunks)

    if focus:
        candidates = [
            c for c in chunks if _is_focused_section(c.section_path, focus) and c.pages
        ]
        # Neutral page-text fallback for market_definition when section-path finds nothing.
        if not candidates and focus == "market_definition":
            return _select_market_def_fallback_chunks(
                chunks,
                max_fallback_pages=min(max_total_pages, _MAX_FALLBACK_PAGES),
            )

        # Profile-specific page-text fallback for theories focus.
        if not candidates and focus == "theories" and profile is not None:
            theory_terms = profile.keywords_for("theories")
            if theory_terms:
                return _select_theories_fallback_chunks(
                    chunks,
                    theory_terms=theory_terms,
                    max_fallback_pages=min(max_total_pages, _MAX_FALLBACK_PAGES),
                )

        if focus == "market_definition":
            candidate_page_count = sum(len(c.pages) for c in candidates)

            # Determine whether supplemental fallback should run.
            below_absolute = candidate_page_count < _MARKET_DEF_SP_MIN_PAGES
            below_relative = (
                total_non_toc_pages >= _MARKET_DEF_COVERAGE_MIN_DOC_PAGES
                and candidate_page_count / total_non_toc_pages < _MARKET_DEF_COVERAGE_MIN_RATIO
            )
            needs_supplement = below_absolute or below_relative or full_market_def_pass

            if needs_supplement:
                covered = {n for c in candidates for n in c.page_numbers}
                # Allow more fallback chunk groups for large documents so scattered
                # sections (e.g. therapeutic-area "Other Overlaps") are not cut off.
                _fb_max_chunks = (
                    _MAX_FALLBACK_CHUNKS * 2
                    if total_non_toc_pages >= _MARKET_DEF_COVERAGE_MIN_DOC_PAGES
                    else _MAX_FALLBACK_CHUNKS
                )
                for fb_chunk in _select_market_def_fallback_chunks(
                    chunks,
                    max_fallback_pages=min(max_total_pages, _MAX_FALLBACK_PAGES),
                    max_chunks=_fb_max_chunks,
                ):
                    # Add the chunk if it contains at least one page not yet covered.
                    # Using "all covered" (not superset) rather than "any overlap" so that
                    # fallback chunks which partially overlap with section-path pages still
                    # contribute their new pages to the selection.
                    if not covered.issuperset(set(fb_chunk.page_numbers)):
                        candidates.append(fb_chunk)
                        covered.update(fb_chunk.page_numbers)
                candidates.sort(key=lambda c: min(c.page_numbers) if c.page_numbers else 0)
    else:
        candidates = [c for c in chunks if _is_relevant_section(c.section_path) and c.pages]
        if not candidates:
            candidates = [c for c in chunks if c.pages]
        elif (sum(len(c.pages) for c in candidates) < _MARKET_DEF_SP_MIN_PAGES
              and total_non_toc_pages >= _MARKET_DEF_SP_MIN_PAGES):
            # Few section-path matches on a substantive document (e.g. only appendix/
            # questionnaire sections found while main body pages have footnote-numbered
            # bookmarks with no relevant terms). Supplement with page-text fallback.
            covered = {n for c in candidates for n in c.page_numbers}
            for fb_chunk in _select_market_def_fallback_chunks(
                chunks,
                max_fallback_pages=min(max_total_pages, _MAX_FALLBACK_PAGES),
            ):
                if not covered.issuperset(set(fb_chunk.page_numbers)):
                    candidates.append(fb_chunk)
                    covered.update(fb_chunk.page_numbers)
            candidates.sort(key=lambda c: min(c.page_numbers) if c.page_numbers else 0)

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
# _SECTION_PREFIX_RE and _SECTION_TRIM_RE are defined in the constants section above.


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

    market_definition: drop theories_of_harm and commitments; force overall_outcome to "unknown"
                       so the run does not infer case outcome from training data.
    theories:          drop product/geographic markets and commitments; force overall_outcome to "unknown".
    remedies:          may populate commitments; markets and theories are still allowed if present.
    None (full run):   all fields allowed.
    All other focus modes (case_history, etc.): drop commitments.
    """
    if focus == "market_definition":
        result.theories = []
        result.commitments = []
        result.overall_outcome = "unknown"
    elif focus == "theories":
        result.product_markets = []
        result.geographic_markets = []
        result.commitments = []
        result.overall_outcome = "unknown"
    elif focus == "outcome_metadata":
        # Outcome metadata: preserve overall_outcome, procedure_stage, and
        # extracted_authority_reference/decision_date — clear everything else.
        # Rescue validated nested passages before clearing the lists so they
        # appear in the draft as unlinked outcome-evidence passages.
        rescued: list[ExtractedPassage] = []
        for item_list in (
            result.product_markets, result.geographic_markets,
            result.theories, result.commitments,
        ):
            for item in item_list:
                rescued.extend(p for p in item.passages if p.validated)  # type: ignore[attr-defined]
        result.unlinked_passages = result.unlinked_passages + rescued
        result.product_markets = []
        result.geographic_markets = []
        result.theories = []
        result.commitments = []
    elif focus == "unit_assessment":
        # unit_assessment output lives in result.unit_assessments.
        # Clear all standard proposition fields — they are empty from _validate_unit_assessment
        # and should stay empty so _build_draft_record produces clean empty lists.
        result.product_markets = []
        result.geographic_markets = []
        result.theories = []
        result.commitments = []
        result.overall_outcome = "unknown"
    elif focus not in (None, "remedies"):
        # case_history and any future focus modes: no commitments
        result.commitments = []
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
  - "defined": Commission conclusively determined the relevant market scope
  - "left_open": Commission expressly stated it was unnecessary to conclude on the exact
    market definition (e.g. "the exact scope of the market can be left open")
  - "considered": Commission assessed the transaction on this market basis using
    cautious or context-specific wording — e.g. "for the purpose of this decision,
    the Commission will consider…" or "for assessing the Transaction, the relevant
    geographic market could be…". Lower precedential weight than "defined"; more
    concrete than "left_open" because the authority did commit to a working basis.
    Use this when the Commission adopts a market scope for its assessment without
    formally resolving the definition as a general legal matter.
  - "not_conclusive": Analysis performed but no conclusion reached
  - "segmented": Segmentation was considered but not definitively resolved
  - "precedent_only": Referenced from prior cases only, not assessed in this decision
  - "unknown": Status cannot be determined from the supplied text
CRITICAL: Do NOT use "defined" if the text says the definition was "left open",
"not necessary to conclude", or "inconclusive". Use "left_open" or "not_conclusive".
CRITICAL — NO INFERRED CONCLUSIONS: If the supplied text does not contain the
Commission's explicit conclusion on a market, set definition_status to "unknown"

GEOGRAPHIC MARKETS — SCAN ALL PRODUCT MARKET SECTIONS:
Many decisions address geographic scope separately for each product market rather than
in a single dedicated geographic market section. You MUST scan every product market
section for geographic scope language. For each product market where the authority
addressed geographic scope (even briefly), create a corresponding geographic market
entry. Common patterns:
  - "The geographic market for X is national / EEA-wide / worldwide."
  - "The geographic market for the supply of X is at least EEA-wide."
  - "As regards geographic scope, the Commission notes that…"
  - "The relevant geographic market is wider than national."
Do NOT skip geographic markets just because they appear in product-market subsections
rather than a dedicated geographic market section. If geographic scope is left open
alongside the product market, set definition_status: left_open for the geo market too.
and market_importance to "incomplete_source". Do NOT infer "left_open" by analogy
with other markets or by guessing. Do NOT infer any conclusion from training data.
Add a caveat naming the market and explaining that its conclusion is absent from
the supplied chunks.

GEOGRAPHIC MARKET NAMING CONVENTION:
Name each geographic market entry to be self-identifying — include both the product
scope and the geographic scope. Use the pattern:
  '[Product market name] — [national/EEA-wide/worldwide] ([Country] affected)'
Examples:
  - 'Dry premix mortars — national (France affected)'
  - 'Chemical-based concrete admixtures — national (France affected)'
  - 'Multi-sided advertising platforms — EEA-wide'
  - 'Wholesale supply of electricity — national (Germany affected)'
NEVER name a geographic market entry with just a country or region (e.g. 'France',
'EEA') — always prefix with the corresponding product market name so entries are
distinguishable when multiple product markets share the same geographic scope.

MARKET IMPORTANCE CLASSIFICATION:
For every product and geographic market entry, set market_importance:
  - "core_assessed": Commission formally assessed this as a key relevant market.
  - "assessed_no_overlap": Commission assessed it but the parties do not compete here.
  - "ancillary": Related market discussed but not the primary analytical focus.
  - "segmented": Segmentation analysis done but left open.
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

OUTCOME / CLEARANCE PASSAGES — DO NOT LINK TO MARKETS:
Passages that express a merger clearance outcome — containing language such as
"does not raise serious doubts", "compatible with the internal market", "cleared", or
"authorised" — describe the RESULT of the competitive assessment, not market definition.

They MUST NOT appear in:
  - A market or geographic market entry's nested "passages" array
  - The top-level "source_passages" array with a "supports" value pointing at any
    product or geographic market

They MAY be retained as:
  - Top-level source_passages with an empty or absent "supports" list (unlinked)
  - Evidence for the overall_outcome value

IMPORTANT DISTINCTION — market-definition conclusions vs. clearance conclusions:
  - "The Commission concludes the relevant product market is X" → source_role: "conclusion",
    SHOULD link to the market entry (supports_markets / supports_geographic_markets).
    This is a finding about what the market IS.
  - "The concentration is compatible with the internal market" → source_role: "conclusion",
    MUST NOT link to any market entry. This is a finding about the merger OUTCOME.
Only passages containing explicit clearance/authorization language are restricted.
"Commission concludes", "Commission considers", "the relevant market is" are market
definition language and belong linked to the market entry they define.

VERBATIM QUOTES ONLY:
Copy passage text EXACTLY as it appears in the source. Do NOT paraphrase, summarise,
or rephrase. If you cannot find an exact verbatim quote, do not include the passage.

QUOTE CLEANLINESS — PDF NORMALISATION TRAPS (rule mdr_009):
PDF-extracted text commonly contains artifacts that make quote snippets hard to verify.
Avoid including:
  - Footnote number injections mid-sentence: "market definition.14 The Commission"
    where "14" is a footnote marker injected into body text.
  - Line-break hyphen joins: "compe-\ntitive" or "compe- titive" from a word split
    across a line end — copy the joined form "competitive" instead.
  - Inline footnote reference numbers embedded in text: "widget market (23) where
    parties overlap" — omit the parenthesised footnote number if it breaks readability.
Prefer shorter, clean snippets that still fully support the proposition over longer
snippets that include these artifacts. If the only available text is affected, copy it
verbatim but keep the snippet as short as possible. Do not omit a genuinely important
passage solely to avoid artifacts.

MARKET DEDUPLICATION AND HIERARCHY:
Do not create multiple entries for the same market at different hierarchical levels.
  - If segmentation is considered (e.g. search ads vs. display ads within online advertising),
    create one entry with definition_status "segmented" and explain in notes.
  - Distinguish the core market from geographic scope — do not create one entry per geography
    unless the Commission assessed them as genuinely separate relevant markets.
  - For each market, link all supporting passages via the nested "passages" array.

PASSAGE COUNT LIMIT — QUALITY OVER QUANTITY (rule mdr_008):
For each product market, geographic market, or theory of harm, include at most 3 source
passages. Apply this priority order:
  1. The passage that most directly states the authority's conclusion on that market/theory
     (prefer "conclusion" or "commission_assessment" source_role).
  2. The passage that most specifically defines the scope of the market or harm.
  3. One further passage if it adds materially different content (e.g. a market investigation
     finding that corroborates the authority's view).
Do NOT include consecutive paragraphs that repeat the same point. If multiple consecutive
paragraphs from the same section support the same proposition, use the single most
informative excerpt.
Do NOT include background or procedural paragraphs as supporting passages for a market
definition unless they are the only available source.
Thin passages — snippets too short or vague to independently support the linked
proposition on their own (e.g. a three-word fragment, a section title, a pure cross-
reference) — must be omitted or extended to include the surrounding analysis.

DEDUPLICATE IDENTICAL QUOTES (rule mdr_007):
If the same verbatim quote would support both a product market and a theory of harm,
create ONE passage entry and include both in its supports list. Do not create duplicate
entries for the same quote.

CONCLUSION PASSAGES — NOT SOLE SUPPORT (rule mdr_006):
A passage with source_role "conclusion" (the Commission's final verdict) can corroborate
a market entry but must not be its ONLY supporting passage. Every market entry must have
at least one "commission_assessment" or "market_investigation" passage showing the
analytical reasoning, not just the conclusion.

THEORIES OF HARM — INNOVATION AND R&D COMPETITION:
Competition authorities sometimes assess mergers as reducing innovation rivalry rather
than (or in addition to) price competition. These appear as theories of harm even when
no formal "relevant market" is defined. Use `theory_type: "innovation"` when:
  - The text discusses the merger eliminating a "leading innovator", "pipeline competitor",
    or "close innovator" in a technology or R&D space.
  - The authority assesses whether the transaction reduces incentives to invest in R&D
    or results in the loss of an important R&D pipeline.
  - The terms "innovation spaces", "innovation competition", "R&D competition",
    "pipeline products", "pipeline overlap", or "reduction in innovation incentives"
    appear as part of a competitive concern analysis.
  - The authority refers to the parties as "leading innovators" or notes the removal of
    an important innovation constraint.

IMPORTANT DISTINCTIONS — innovation theory context:
  - An "innovation space" used only as an analytical framework (not as a finding of
    competitive harm) is NOT a theory of harm — do not create a theory entry for it.
  - A market definition for an innovation space (e.g., the Commission formally defining
    an R&D market) should go in product_markets, not theories_of_harm.
  - An innovation theory entry REQUIRES that the authority expressly states a competitive
    concern: that the merger eliminates, reduces, or impairs innovation competition.
  - Innovation theories often appear in "Competitive Assessment > Innovation" or
    "Innovation Competition" sections — these are valid theory-of-harm source sections.
  - Capture the authority's view, the notifying parties' counter-arguments, and any
    third-party/customer concerns separately in the `notes` field. Use the source_role
    field on passages to distinguish: commission_assessment, notifying_party_view,
    market_investigation.

COMMITMENTS / REMEDIES (for sections containing operative articles or conditions):
If the supplied text consists of remedies, commitments, conditions of approval, or
divestiture schedules, populate the `commitments` array instead of (or in addition to)
the market/theory fields.

Rules for commitment entries:
  - Create one entry per distinct commitment or condition package (e.g. one entry for the
    "Vegetable Seeds Divestment Business", a separate entry for the "GA Divestment Business").
  - Set `commitment_type`:
      "structural" — divestiture, spin-off, asset transfer, IP transfer
      "behavioral" — ongoing conduct obligation (licensing, supply, access, non-compete)
      "access"     — access remedy (data access, interoperability, customer access)
      "other"      — conditions not fitting the above
  - Copy `divested_assets` as a list of verbatim asset/business names from the text.
  - Copy `purchaser_requirements` verbatim from the text if stated (e.g. "stand-alone viable
    business", "approved by the Commission").
  - Set `markets_addressed` to the market names explicitly linked to this commitment in the
    text. Use [] if the text does not explicitly link the commitment to named markets.
  - Include supporting `passages` as verbatim excerpts from the remedy/commitment text.
  - Do NOT invent market definitions or competitive assessments from remedy schedules alone.
  - If a passage quotes the operative clearance article (e.g. "Article 8(2)"), include it
    as an unlinked source_passage supporting the overall outcome, not as a commitment entry.

OUTCOME METADATA EXTRACTION (outcome_metadata focus only):
When processing the preamble, operative section, or procedural introduction of a decision:
1. Set `overall_outcome` from the operative Article cited:
   - Article 6(1)(b) without conditions → "cleared"
   - Article 6(1)(b) with conditions / Article 6(2) → "cleared_with_conditions"
   - Article 8(1) → "cleared"
   - Article 8(2) → "cleared_with_conditions"
   - Article 8(3) → "blocked"
   - Article 6(1)(c) (Phase II opened but not yet decided) → "pending"
   - Language "does not raise serious doubts" or "compatible with the internal market"
     without an explicit operative article → "cleared"
   - If the operative decision is not in the supplied text → "unknown"
2. Set `procedure_stage`: "phase1" for Article 6 decisions, "phase2" for Article 8.
3. Set `authority_reference` to the case reference number (e.g., "M.8084").
4. Set `decision_date` to the date of the Commission decision (ISO YYYY-MM-DD).
5. Include at least one verbatim passage quoting the operative clearance language
   with `source_role: "conclusion"` and empty `supports` list.
6. Leave product_markets, geographic_markets, theories_of_harm, and commitments as [].

Use the record_extraction tool to return your findings."""

_COMMITMENT_ITEM_SCHEMA = {
    "type": "object",
    "required": ["title", "commitment_type", "description", "not_found", "passages"],
    "properties": {
        "title": {
            "type": "string",
            "description": "Short descriptive title of this commitment or condition.",
        },
        "commitment_type": {
            "type": "string",
            "enum": sorted(_VALID_COMMITMENT_TYPES),
            "description": (
                "structural=divestiture or asset transfer; "
                "behavioral=ongoing conduct obligation (e.g. licensing, supply, access); "
                "access=access remedy (third-party, customer, data); "
                "other=conditions not fitting above categories."
            ),
        },
        "description": {
            "type": "string",
            "description": "Full description of the commitment scope, obligations, and conditions as stated in the text.",
        },
        "divested_assets": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of specific assets, businesses, product lines, or IP to be divested. Use [] for non-structural commitments.",
        },
        "purchaser_requirements": {
            "type": "string",
            "description": "Requirements for the approved purchaser or trustee, if stated. Empty string if none.",
        },
        "markets_addressed": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Market names or IDs this commitment addresses. Use [] if not explicitly linked to specific markets in the text.",
        },
        "not_found": {"type": "boolean"},
        "passages": {
            "type": "array",
            "items": None,  # filled with _PASSAGE_ITEM_SCHEMA after it is defined
            "description": "Verbatim passages from the text supporting this commitment entry.",
        },
    },
}

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
                "defined=Commission conclusively determined scope; "
                "left_open=Commission said unnecessary to conclude on exact definition; "
                "considered=Commission adopted this market basis with cautious/context-specific wording "
                "(e.g. 'for the purpose of this decision' / 'for assessing the Transaction') — "
                "lower precedential weight than defined, more concrete than left_open; "
                "not_conclusive=analysis inconclusive; "
                "segmented=segmentation considered, not resolved; "
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
                "segmented=segmentation discussed but not resolved; "
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
        "theories of harm, and (for remedy sections) commitments from the supplied "
        "merger decision text."
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
                            "enum": sorted(_VALID_THEORY_TYPES),
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
            "procedure_stage": {
                "type": "string",
                "enum": sorted(_VALID_PROCEDURE_STAGES),
                "description": (
                    "Procedure stage of the decision: 'phase1' for Article 6 decisions, "
                    "'phase2' for Article 8 decisions, 'unknown' if not determinable. "
                    "Set only for outcome_metadata focus; use 'unknown' otherwise."
                ),
            },
            "authority_reference": {
                "type": "string",
                "description": (
                    "Case reference number (e.g. 'M.8084'). "
                    "Set only for outcome_metadata focus; empty string otherwise."
                ),
            },
            "decision_date": {
                "type": "string",
                "description": (
                    "Date of the authority decision in ISO format YYYY-MM-DD. "
                    "Set only for outcome_metadata focus; empty string otherwise."
                ),
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
            "commitments": {
                "type": "array",
                "description": (
                    "Commitments, remedies, or conditions of approval found in the supplied text. "
                    "Populate ONLY when the text contains remedy/commitment content (operative "
                    "articles, divestiture schedules, conditions). Return [] if none found."
                ),
                "items": _COMMITMENT_ITEM_SCHEMA,
            },
        },
    },
}

# Wire the passage item schema into _COMMITMENT_ITEM_SCHEMA (defined before _PASSAGE_ITEM_SCHEMA).
_COMMITMENT_ITEM_SCHEMA["properties"]["passages"]["items"] = _PASSAGE_ITEM_SCHEMA


# ---------------------------------------------------------------------------
# Unit-assessment tool schema and extraction prompt
# ---------------------------------------------------------------------------

_VALID_FINDING_TYPES: frozenset[str] = frozenset({
    "horizontal_overlap", "vertical_overlap", "conglomerate",
    "innovation", "no_overlap", "other",
})

_VALID_FINDING_CONCLUSIONS: frozenset[str] = frozenset({
    "siec", "no_siec", "discussed", "remedied", "unknown",
})

_UNIT_FINDING_SCHEMA: dict = {
    "type": "object",
    "required": ["finding_id", "finding_type", "conclusion", "description", "source_passage_refs"],
    "properties": {
        "finding_id": {
            "type": "string",
            "description": "Short stable ID within this unit, e.g. 'f_1', 'f_2'.",
        },
        "finding_type": {
            "type": "string",
            "enum": sorted(_VALID_FINDING_TYPES),
            "description": (
                "horizontal_overlap=parties compete in same segment/geography; "
                "vertical_overlap=parties at different supply-chain levels; "
                "conglomerate=concern from combined portfolio; "
                "innovation=R&D or pipeline concern; "
                "no_overlap=authority found no overlap or no concern; "
                "other=any other finding type."
            ),
        },
        "segment": {
            "type": "string",
            "description": (
                "Product segment or sub-market within the unit "
                "(e.g. 'Open field cucumbers', 'F1 hybrid seeds'). "
                "Use empty string if not sub-segmented."
            ),
        },
        "geography": {
            "type": "string",
            "description": "Geographic scope of this finding (e.g. 'EEA', 'Germany', 'worldwide').",
        },
        "conclusion": {
            "type": "string",
            "enum": sorted(_VALID_FINDING_CONCLUSIONS),
            "description": (
                "siec=authority found significant impediment to effective competition; "
                "no_siec=authority found no concern; "
                "discussed=authority assessed but left open; "
                "remedied=concern resolved by commitment; "
                "unknown=conclusion absent from supplied text."
            ),
        },
        "description": {
            "type": "string",
            "description": "Verbatim or near-verbatim text from the decision describing this finding.",
        },
        "related_markets": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Market names explicitly linked to this finding.",
        },
        "related_theories": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Theory names or IDs explicitly linked to this finding.",
        },
        "source_passage_refs": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "IDs (e.g. 'sp_1') from the source_passages array supporting this finding. "
                "Use the same IDs you assign in source_passages."
            ),
        },
    },
}

_UNIT_ITEM_SCHEMA: dict = {
    "type": "object",
    "required": ["unit_type", "unit_label", "findings"],
    "properties": {
        "unit_type": {
            "type": "string",
            "description": (
                "Category of the repeated unit "
                "(e.g. 'crop', 'route', 'indication', 'country', 'asset')."
            ),
        },
        "unit_label": {
            "type": "string",
            "description": (
                "Specific label for this unit instance "
                "(e.g. 'Cucumber', 'LHR-CDG', 'Lisinopril')."
            ),
        },
        "findings": {
            "type": "array",
            "items": _UNIT_FINDING_SCHEMA,
            "description": (
                "All competitive assessment findings for this unit. "
                "Include one entry per distinct segment × geography combination assessed."
            ),
        },
    },
}

_UNIT_ASSESSMENT_TOOL_SCHEMA: dict = {
    "name": "record_unit_assessment",
    "description": (
        "Record repeated-unit competitive assessment findings extracted from a merger "
        "decision section. Used for cases where the authority analyses many similar "
        "sub-markets (crops, routes, indications, etc.) using a consistent structure."
    ),
    "input_schema": {
        "type": "object",
        "required": ["unit_assessments", "source_passages", "caveats"],
        "properties": {
            "unit_assessments": {
                "type": "array",
                "items": _UNIT_ITEM_SCHEMA,
                "description": "All assessment units found in the supplied text.",
            },
            "source_passages": {
                "type": "array",
                "items": _PASSAGE_ITEM_SCHEMA,
                "description": "All verbatim passages cited across all unit findings.",
            },
            "caveats": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Notes where evidence was ambiguous or absent from the supplied text.",
            },
        },
    },
}

_UNIT_ASSESSMENT_TASK = """\
TASK:
You are extracting a repeated-unit competitive assessment from a merger decision.

A "repeated-unit assessment" appears in long decisions where the authority analyses
many similar sub-markets using a consistent analytical structure:
  1. Market definition for the unit (this crop / this route / this indication)
  2. Competitive overlap analysis (which segments and geographies are affected)
  3. Conclusion for each combination: SIEC / no SIEC / discussed / remedied

CRITICAL RULES:
- Extract findings from TABLES, bullet lists, AND prose equally.
  Table-heavy pages are valid sources — do not skip them.
- Do NOT rely on "Theory of harm" framing. Crop/unit SIEC findings often appear as:
    "The Commission concludes that the Transaction raises serious doubts as to its
    compatibility with the internal market in [segment] – [country/geography]."
  or as a structured table with columns like: Segment | Country | Parties overlap | SIEC?
- For each named assessment unit in the text, create one entry in unit_assessments.
- For each segment × geography combination the authority assessed, create one finding.
- Set conclusion:
    siec        → authority found SIEC or "serious doubts"
    no_siec     → authority found no concern, no overlap, or "no serious doubts"
    remedied    → concern identified but resolved by a commitment/remedy
    discussed   → authority assessed but left the conclusion open
    unknown     → conclusion absent from the supplied text
- Assign short passage IDs (e.g. "sp_1", "sp_2") in source_passages and reference
  the same IDs in source_passage_refs.
- Quote text VERBATIM — do not paraphrase.
- Set source_role on each passage:
    commission_assessment → Commission actively analysing
    conclusion            → Commission's explicit finding
    notifying_party_view  → parties' submission
    background            → factual context only
- Do NOT invent findings absent from the supplied text.
- If the supplied text contains only procedural background or no assessment units,
  return unit_assessments: [] and explain in caveats.

REQUIRED RESPONSE KEYS: unit_assessments, source_passages, caveats.
Never return {}.

Use the record_unit_assessment tool to return your findings."""


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


def _build_extraction_prompt(
    chunks: list[ChunkInfo],
    case_context: dict,
    profile=None,
) -> str:
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
    # Inject profile-specific source-role block when a profile is available.
    # This replaces the static SOURCE ROLE CLASSIFICATION section in _EXTRACTION_TASK
    # with jurisdiction/document-type-specific guidance.
    profile_block = (
        "\n\nDOCUMENT PROFILE: " + profile.display_name + "\n"
        + profile.source_role_prompt_block()
        if profile is not None
        else ""
    )
    return (
        "You are a competition law research assistant extracting structured "
        "information from merger decision text.\n\n"
        "CASE CONTEXT:\n" + context_block + "\n\n"
        "SUPPLIED SOURCE CHUNKS:\n" + chunks_block + "\n\n"
        + _EXTRACTION_TASK
        + profile_block
    )


def _build_unit_assessment_prompt(chunks: list[ChunkInfo], case_context: dict) -> str:
    """Build the prompt for unit_assessment focus mode."""
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
        + _UNIT_ASSESSMENT_TASK
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


def _call_claude_unit_assessment_raw(prompt: str, anthropic_client):
    """Call Claude with the unit_assessment tool; return raw Anthropic message."""
    return anthropic_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        tools=[_UNIT_ASSESSMENT_TOOL_SCHEMA],
        tool_choice={"type": "tool", "name": "record_unit_assessment"},
        messages=[{"role": "user", "content": prompt}],
    )


def _call_claude_unit_assessment(prompt: str, anthropic_client) -> str:
    """Call Claude with the unit_assessment tool; return JSON string."""
    message = _call_claude_unit_assessment_raw(prompt, anthropic_client)
    for block in message.content:
        if getattr(block, "type", None) == "tool_use":
            return json.dumps(block.input)
    for block in message.content:
        if getattr(block, "type", None) == "text":
            return block.text.strip()
    return ""


# ---------------------------------------------------------------------------
# Gemini calling functions
# ---------------------------------------------------------------------------

_GEMINI_MODEL = "gemini-2.5-flash"


def _call_gemini(prompt: str, gemini_client) -> str:
    """Call Gemini with JSON output mode; return JSON string.

    *gemini_client* is a ``google.genai.Client`` instance.
    Retries on 429 (free-tier rate limit) using the retry delay from the error.
    """
    import re as _re
    import time as _time
    from google.genai import types as _gtypes

    for attempt in range(5):
        try:
            response = gemini_client.models.generate_content(
                model=_GEMINI_MODEL,
                contents=prompt,
                config=_gtypes.GenerateContentConfig(
                    response_mime_type="application/json",
                    max_output_tokens=65536,
                ),
            )
            return response.text.strip()
        except Exception as exc:
            msg = str(exc)
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                # Parse retry delay from error message ("retry in X.Xs")
                m = _re.search(r"retry[^\d]*(\d+(?:\.\d+)?)\s*s", msg, _re.IGNORECASE)
                suggested = float(m.group(1)) if m else 0
                # Ensure at least 90s so the per-minute token bucket fully refills
                delay = max(suggested + 2, 90 * (attempt + 1))
                print(f"  Gemini rate limit — waiting {delay:.0f}s (attempt {attempt+1}/5)…")
                _time.sleep(delay)
                continue
            if "503" in msg or "UNAVAILABLE" in msg:
                delay = 30 * (attempt + 1)
                print(f"  Gemini unavailable — waiting {delay:.0f}s (attempt {attempt+1}/5)…")
                _time.sleep(delay)
                continue
            raise
    raise RuntimeError("Gemini call failed after 5 attempts")


def _call_gemini_repair(
    bad_response: str,
    validation_errors: list[str],
    gemini_client,
) -> str:
    """Gemini repair pass; return corrected JSON string."""
    violations = "\n".join(f"  - {e}" for e in validation_errors)
    prompt = (
        "A previous extraction call returned JSON that violates the schema. "
        "Fix ONLY the format errors below — do NOT change any content values.\n\n"
        "VIOLATIONS:\n" + violations + "\n\n"
        "PREVIOUS RESPONSE TO FIX:\n" + bad_response + "\n\n"
        "CRITICAL — every list field MUST be a real JSON array, never a string:\n"
        "  WRONG: \"product_markets\": \"[{\\\"name\\\": \\\"X\\\"}]\"\n"
        "  RIGHT: \"product_markets\": [{\"name\": \"X\", ...}]\n\n"
        "Return the complete corrected JSON object."
    )
    return _call_gemini(prompt, gemini_client)


# ---------------------------------------------------------------------------
# Unified LLM client
# ---------------------------------------------------------------------------

class LLMClient:
    """Thin adapter over Anthropic Claude and Google Gemini for extraction calls.

    Usage::

        # Anthropic
        client = LLMClient("anthropic", anthropic.Anthropic(...))

        # Gemini
        from google import genai
        client = LLMClient("gemini", genai.Client(api_key=...))
    """

    def __init__(self, provider: str, client) -> None:
        if provider not in ("anthropic", "gemini"):
            raise ValueError(f"Unknown provider {provider!r}; must be 'anthropic' or 'gemini'")
        self.provider = provider
        self._client = client

    def call_extraction(self, prompt: str) -> str:
        """Return JSON string matching the extraction schema."""
        if self.provider == "anthropic":
            return _call_claude(prompt, self._client)
        return _call_gemini(prompt, self._client)

    def call_unit_assessment(self, prompt: str) -> str:
        """Return JSON string matching the unit_assessment schema."""
        if self.provider == "anthropic":
            return _call_claude_unit_assessment(prompt, self._client)
        return _call_gemini(prompt, self._client)

    def call_repair(self, bad_response: str, errors: list[str]) -> str:
        """Return corrected JSON string."""
        if self.provider == "anthropic":
            return _call_claude_repair(bad_response, errors, self._client)
        return _call_gemini_repair(bad_response, errors, self._client)


def _validate_unit_assessment(
    raw: dict,
    chunks: list[ChunkInfo],
    chunk_doc_map: dict[str, str],
) -> "ExtractionResult":
    """Parse and validate a unit_assessment Claude response.

    Quote-validates all source_passages; populates ExtractionResult.unit_assessments.
    Passages are stored as unlinked (the link is in finding.source_passage_refs which
    uses Claude's internal passage IDs — the draft builder preserves them as-is).
    """
    validated_count = 0
    rejected_count = 0

    # Build a map from Claude's raw passage IDs to validated sp snippets so the
    # draft builder can emit stable passage refs in the findings.
    raw_id_to_quote: dict[str, str] = {}
    for rp in (raw.get("source_passages") or []):
        if isinstance(rp, dict):
            quote = (rp.get("quote") or "").strip()
            # Claude uses the passage_id field as the ref target
            raw_pid = str(rp.get("passage_id", "") or "").strip()
            if raw_pid and quote:
                raw_id_to_quote[raw_pid] = quote[:80]

    unlinked_passages: list[ExtractedPassage] = []
    for rp in (raw.get("source_passages") or []):
        if not isinstance(rp, dict):
            continue
        quote = (rp.get("quote") or "").strip()
        chunk_id = str(rp.get("chunk_id", "") or "")
        source_role = str(rp.get("source_role", "") or "")
        if source_role and source_role not in _VALID_SOURCE_ROLES:
            source_role = ""
        try:
            page_num = int(rp.get("page_number") or 0)
        except (TypeError, ValueError):
            page_num = 0

        if not chunk_id or not quote or page_num == 0:
            rejected_count += 1
            unlinked_passages.append(ExtractedPassage(
                chunk_id=chunk_id, page_number=page_num, quote=quote,
                validated=False,
                rejection_reason="Missing required field(s): chunk_id, quote, or page_number",
                source_role=source_role,
            ))
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
        unlinked_passages.append(ep)

    # Parse unit_assessments — validate enum values; preserve raw dicts.
    unit_assessments: list[dict] = []
    for raw_unit in (raw.get("unit_assessments") or []):
        if not isinstance(raw_unit, dict):
            continue
        unit_label = str(raw_unit.get("unit_label", "") or "").strip()
        if not unit_label:
            continue
        findings: list[dict] = []
        for raw_f in (raw_unit.get("findings") or []):
            if not isinstance(raw_f, dict):
                continue
            ft = str(raw_f.get("finding_type", "other") or "other").strip()
            if ft not in _VALID_FINDING_TYPES:
                ft = "other"
            conc = str(raw_f.get("conclusion", "unknown") or "unknown").strip()
            if conc not in _VALID_FINDING_CONCLUSIONS:
                conc = "unknown"
            findings.append({
                "finding_id": str(raw_f.get("finding_id", "") or ""),
                "finding_type": ft,
                "segment": str(raw_f.get("segment", "") or ""),
                "geography": str(raw_f.get("geography", "") or ""),
                "conclusion": conc,
                "description": str(raw_f.get("description", "") or ""),
                "related_markets": list(raw_f.get("related_markets") or []),
                "related_theories": list(raw_f.get("related_theories") or []),
                "source_passage_refs": list(raw_f.get("source_passage_refs") or []),
            })
        unit_assessments.append({
            "unit_type": str(raw_unit.get("unit_type", "") or "").strip(),
            "unit_label": unit_label,
            "findings": findings,
        })

    return ExtractionResult(
        product_markets=[],
        geographic_markets=[],
        theories=[],
        commitments=[],
        overall_outcome="unknown",
        unlinked_passages=unlinked_passages,
        caveats=[str(c) for c in (raw.get("caveats") or []) if c],
        passages_validated=validated_count,
        passages_rejected=rejected_count,
        unit_assessments=unit_assessments,
    )


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
        th_type = th.get("theory_type", "other")
        if th_type not in _VALID_THEORY_TYPES:
            th_type = "other"
        theories.append(ExtractedTheory(
            name=th.get("name", ""),
            theory_type=th_type,
            theory_outcome=th.get("theory_outcome", "unclear"),
            notes=th.get("notes", ""),
            passages=_process_passages(th.get("passages") or []),
            not_found=bool(th.get("not_found")),
        ))

    commitments: list[ExtractedCommitment] = []
    for cm in raw.get("commitments") or []:
        cm_type = cm.get("commitment_type", "other")
        if cm_type not in _VALID_COMMITMENT_TYPES:
            cm_type = "other"
        commitments.append(ExtractedCommitment(
            title=cm.get("title", ""),
            commitment_type=cm_type,
            description=cm.get("description", ""),
            divested_assets=list(cm.get("divested_assets") or []),
            purchaser_requirements=cm.get("purchaser_requirements") or "",
            markets_addressed=list(cm.get("markets_addressed") or []),
            passages=_process_passages(cm.get("passages") or []),
            not_found=bool(cm.get("not_found")),
        ))

    # Detect and store orphan top-level source_passages (not nested under any market/theory).
    nested_quotes: set[str] = set()
    for item_list in (product_markets, geographic_markets, theories, commitments):
        for item in item_list:
            for p in item.passages:
                nested_quotes.add(p.quote[:80])
    unlinked_passages = _process_passages([
        sp for sp in (raw.get("source_passages") or [])
        if isinstance(sp, dict) and (sp.get("quote", "") or "")[:80] not in nested_quotes
    ])
    orphan_count = len(unlinked_passages)

    procedure_stage = str(raw.get("procedure_stage", "unknown") or "unknown").strip()
    if procedure_stage not in _VALID_PROCEDURE_STAGES:
        procedure_stage = "unknown"
    extracted_authority_reference = str(raw.get("authority_reference", "") or "").strip()
    extracted_decision_date = str(raw.get("decision_date", "") or "").strip()

    return ExtractionResult(
        product_markets=product_markets,
        geographic_markets=geographic_markets,
        theories=theories,
        commitments=commitments,
        overall_outcome=raw.get("overall_outcome", "unknown"),
        procedure_stage=procedure_stage,
        extracted_authority_reference=extracted_authority_reference,
        extracted_decision_date=extracted_decision_date,
        unlinked_passages=unlinked_passages,
        caveats=[str(c) for c in (raw.get("caveats") or []) if c],
        background_concepts=[str(c) for c in (raw.get("background_concepts") or []) if c],
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
    llm_client: "LLMClient",
    debug_dir: Path,
    case_id: str,
    profile=None,
) -> SectionBatchResult:
    """Run one LLM extraction call for a section batch; never raises.

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

    prompt = _build_extraction_prompt(chunks, case_context, profile=profile)

    # API call — provider-agnostic via LLMClient
    response_text = ""
    message = None  # kept for debug-save compat (None is safe)
    try:
        response_text = llm_client.call_extraction(prompt)
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
                repaired_text = llm_client.call_repair(response_text, all_errors)
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
    cm_list: list[ExtractedCommitment] = []
    caveats: list[str] = []
    background_concepts: list[str] = []
    overall_outcome = "unknown"
    procedure_stage = "unknown"
    extracted_authority_reference = ""
    extracted_decision_date = ""
    unlinked_passages: list[ExtractedPassage] = []
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

    def _dedup_merge_commitments(incoming: list[ExtractedCommitment], existing_list: list) -> None:
        for item in incoming:
            best_sim = 0.0
            best_idx = -1
            for i, ex in enumerate(existing_list):
                sim = _similarity(item.title, ex.title)
                if sim > best_sim:
                    best_sim, best_idx = sim, i
            if best_sim >= _SIMILARITY_MATCH and best_idx >= 0:
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
        _dedup_merge_commitments(r.commitments, cm_list)
        # Prefix each caveat with its section label so the merged list stays navigable.
        _lbl = r.section_label.strip() if r.section_label else ""
        for c in r.caveats:
            caveats.append(f"[{_lbl}] {c}" if _lbl and not c.startswith(f"[{_lbl}]") else c)
        background_concepts.extend(r.background_concepts)
        if r.overall_outcome != "unknown" and overall_outcome == "unknown":
            overall_outcome = r.overall_outcome
        if r.procedure_stage != "unknown" and procedure_stage == "unknown":
            procedure_stage = r.procedure_stage
        if r.extracted_authority_reference and not extracted_authority_reference:
            extracted_authority_reference = r.extracted_authority_reference
        if r.extracted_decision_date and not extracted_decision_date:
            extracted_decision_date = r.extracted_decision_date
        unlinked_passages.extend(r.unlinked_passages)
        passages_validated += r.passages_validated
        passages_rejected += r.passages_rejected

    return ExtractionResult(
        product_markets=pm_list,
        geographic_markets=gm_list,
        theories=th_list,
        commitments=cm_list,
        overall_outcome=overall_outcome,
        procedure_stage=procedure_stage,
        extracted_authority_reference=extracted_authority_reference,
        extracted_decision_date=extracted_decision_date,
        unlinked_passages=unlinked_passages,
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
        "procedure_stage": result.procedure_stage,
        "decision_date": (
            result.extracted_decision_date
            if result.extracted_decision_date
            else existing_record.get("decision_date")
        ),
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

    cm_with_ids: list[tuple[str, ExtractedCommitment]] = []
    for cm in result.commitments:
        if not cm.not_found:
            cm_with_ids.append((f"com_{len(cm_with_ids) + 1}", cm))

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
            "theory_type": th.theory_type,
            "theory_outcome": th.theory_outcome,
            "description": th.notes,
            "verification": {"status": "source_linked"},
        }
        for tid, th in toh_with_ids
    ]

    # Commitments — built before passage collection so passage IDs can be back-linked.
    draft["commitments"] = [
        {
            "commitment_id": cid,
            "commitment_type": cm.commitment_type,
            "title": cm.title,
            "description": cm.description,
            "divested_assets": cm.divested_assets,
            "purchaser_requirements": cm.purchaser_requirements or None,
            "markets_addressed": cm.markets_addressed,
            "related_source_passages": [],  # filled during passage collection below
            "review_status": "unreviewed",
        }
        for cid, cm in cm_with_ids
    ]

    # Collect validated passages only.
    passages: list[dict] = []
    sp_n = 0

    def _add_passages(
        with_ids: list[tuple[str, object]],
        support_pm: bool = False,
        support_gm: bool = False,
        support_toh: bool = False,
        support_cm: bool = False,
    ) -> None:
        nonlocal sp_n
        for prop_id, item in with_ids:
            for ep in item.passages:  # type: ignore[attr-defined]
                if not ep.validated:
                    continue
                sp_n += 1
                sp_id = f"sp_{sp_n}"
                passages.append({
                    "passage_id": sp_id,
                    "source_document_id": ep.source_document_id,
                    "page": str(ep.page_number),
                    "quote_snippet": ep.quote,
                    "source_role": ep.source_role or "not_set",
                    "extraction_method": "pdf_extracted",
                    "review_status": "unreviewed",
                    "confidence_score": 0.70,
                    "last_checked_date": today,
                    "supports_markets": [prop_id] if support_pm else [],
                    "supports_geographic_markets": [prop_id] if support_gm else [],
                    "supports_theories": [prop_id] if support_toh else [],
                    "supports_commitments": [prop_id] if support_cm else [],
                })
                if support_cm:
                    # Back-link: add this passage ID to the commitment's related_source_passages.
                    for com_entry in draft["commitments"]:
                        if com_entry["commitment_id"] == prop_id:
                            com_entry["related_source_passages"].append(sp_id)

    _add_passages(pm_with_ids, support_pm=True)
    _add_passages(gm_with_ids, support_gm=True)
    _add_passages(toh_with_ids, support_toh=True)
    _add_passages(cm_with_ids, support_cm=True)

    # Include unlinked top-level passages (e.g. outcome evidence from outcome_metadata focus).
    for ep in result.unlinked_passages:
        if not ep.validated:
            continue
        sp_id = f"sp_{len(passages) + 1}"
        passages.append({
            "passage_id": sp_id,
            "source_document_id": ep.source_document_id or "",
            "page": str(ep.page_number),
            "quote_snippet": ep.quote,
            "source_role": ep.source_role or "not_set",
            "extraction_method": "pdf_extracted",
            "review_status": "unreviewed",
            "confidence_score": 0.70,
            "last_checked_date": today,
            "supports_markets": [],
            "supports_geographic_markets": [],
            "supports_theories": [],
            "supports_commitments": [],
        })

    draft["source_passages"] = passages

    # Include unit_assessments when the unit_assessment focus was used.
    if result.unit_assessments:
        draft["unit_assessments"] = result.unit_assessments

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
    _skip_markets = focus in ("theories", "remedies", "case_history", "outcome_metadata", "unit_assessment")
    _skip_theories = focus in ("market_definition", "remedies", "case_history", "outcome_metadata", "unit_assessment")

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
    "manual_review_no_overlap",
    "manual_review_geo_pairing",
})

# Source roles that can justify promotion to canonical
_CONCLUSIVE_SOURCE_ROLES: frozenset[str] = frozenset({
    "commission_assessment",
    "conclusion",
})


def _has_conclusive_source_role(
    passages: list[ExtractedPassage],
) -> bool:
    """Return True if at least one passage has a conclusive source role."""
    return any(p.source_role in _CONCLUSIVE_SOURCE_ROLES for p in passages)


def _extract_section_caveats(caveats: list[str]) -> dict[str, bool]:
    """Parse caveats for conclusion-missing flags.

    Returns dict with flags:
    - conclusion_missing: any caveat mentions missing/incomplete/absent conclusion
    - incomplete_definition: definition is incomplete or uncertain
    """
    conclusion_missing = False
    incomplete_definition = False

    for caveat in caveats or []:
        caveat_lower = caveat.lower()
        if any(term in caveat_lower for term in ["conclusion", "absent", "missing", "incomplete", "cut off", "not in supplied"]):
            conclusion_missing = True
        if any(term in caveat_lower for term in ["definition", "inconclusive", "uncertain", "not conclusive"]):
            incomplete_definition = True

    return {
        "conclusion_missing": conclusion_missing,
        "incomplete_definition": incomplete_definition,
    }


def _find_product_market_pairs(
    market_name: str,
    market_type: str,
    all_markets: dict,
) -> list[str]:
    """Find product markets that could pair with a geographic market.

    Returns list of product market IDs that have semantic overlap with the geo market name.
    Geographic markets should reference or pair with product markets where possible.
    """
    if market_type != "geographic":
        return []

    product_list = all_markets.get("product", [])
    geo_tokens = set(market_name.lower().split())

    pairs = []
    for pm in product_list:
        pm_name = pm.get("name", "").lower()
        pm_tokens = set(pm_name.split())
        # Simple overlap check: if there's common meaningful tokens, consider it a pair
        if len(geo_tokens & pm_tokens) > 0:
            pairs.append(pm.get("market_id", ""))

    return pairs


def _promotion_action(
    market_importance: str,
    definition_status: str,
    has_source_refs: bool,
) -> tuple[str, str]:
    """Return (recommended_action, reason) for a single draft market entry.

    Promotion decision rules (conservative source-first logic):

    1. background                                  → exclude_from_canonical
    2. ancillary                                   → keep_as_context_only
    3. precedent_only                              → keep_as_context_only
    4. incomplete_source (explicit)                → hold_pending_source_check
    5. assessed_no_overlap (any status)            → keep_as_context_only (conservative)
    6. unknown status + no source refs             → hold_pending_source_check
    7. core_assessed + (defined|left_open|considered) + refs → promote_to_canonical
    8. core_assessed + segmented + refs → promote_with_uncertainty (needs review)
    9. core_assessed + other status                → manual_review
    10. core_assessed + no source refs             → manual_review
    11. segmented (implicit)           → promote_with_uncertainty (needs review)
    12. has source refs but no recognised importance → manual_review
    13. fallback                                   → manual_review

    NOTE: These rules implement conservative source-first canonicalisation. Assessed
    no-overlap markets are kept as context only, not promoted to canonical, preserving
    source refs for future review. Reconciliation with existing canonical records is
    supplementary only and should not override these promotion decisions.
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

    # Rule 10: assessed_no_overlap — conservative: keep as context only, preserve refs
    # Check this before unknown status rule so assessed_no_overlap is never held
    if imp == "assessed_no_overlap":
        return (
            "keep_as_context_only",
            "Commission assessed this market but parties do not materially overlap. "
            "Keep as context only in draft; preserve source passages and notes for "
            "review. Do not promote to canonical without additional evidence of relevance.",
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
        # Rule 7: core_assessed + segmented/possible_segmentation → needs explicit review
        if status in ("segmented", "possible_segmentation"):
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

    # Rule 11: segmented/possible_segmentation (implicit importance classification)
    if status in ("segmented", "possible_segmentation"):
        return (
            "promote_with_uncertainty",
            "Segmentation was considered but left open by the Commission. "
            "This may be a narrower market or candidate for submarket definition. "
            "Review before adding to canonical market list.",
        )

    # Rule 12: has refs but no recognised importance
    if has_source_refs:
        return (
            "manual_review",
            "Market has source citations but importance/assessment type is unclassified; "
            "review classification and Commission conclusion before deciding on promotion.",
        )

    # Rule 13: unknown status with unrecognised importance — hold for review
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


def _promotion_action_with_guards(
    market_importance: str,
    definition_status: str,
    has_source_refs: bool,
    passages: list[ExtractedPassage],
    caveats: list[str],
    market_type: str,
    market_name: str,
    all_markets: dict,
) -> tuple[str, str]:
    """Apply hardening guards to promotion decisions.

    Wraps _promotion_action with additional checks:
    1. Source role guard: promotion requires commission_assessment or conclusion (when passages available)
    2. Section caveat guard: missing conclusions downgrade to hold_pending_source_check
    3. Geographic pairing: orphan geographic markets go to manual_review_geo_pairing
    4. Left_open tightening: left_open alone does not promote (needs defined status)

    Returns (recommended_action, reason) after applying all guards.
    """
    base_action, base_reason = _promotion_action(market_importance, definition_status, has_source_refs)

    # Guard 1: Source role check — only commission_assessment or conclusion can promote
    # Only apply if we have passages to check (passages may be empty if page refs but no explicit passage mapping)
    if base_action == "promote_to_canonical" and passages:
        if not _has_conclusive_source_role(passages):
            return (
                "hold_pending_source_check",
                "Market would promote but supporting passages lack commission_assessment or "
                "conclusion source role (only found: notifying_party_view, precedent, background). "
                "Re-validate with conclusive source roles before promoting.",
            )

    # Guard 2: Section caveat check — missing conclusions downgrade to hold
    caveat_flags = _extract_section_caveats(caveats)
    if base_action in ("promote_to_canonical", "promote_with_uncertainty"):
        if caveat_flags["conclusion_missing"] and definition_status in ("left_open", "considered", "not_conclusive"):
            return (
                "hold_pending_source_check",
                f"Market's definition status is {definition_status!r} but section caveats indicate "
                "the Commission's conclusion on this market is absent from supplied chunks. "
                "Re-run with broader sections before promoting.",
            )

    # Guard 3: Geographic pairing check — orphan geographic markets require manual review
    if market_type == "geographic" and base_action in ("promote_to_canonical", "promote_with_uncertainty"):
        product_pairs = _find_product_market_pairs(market_name, market_type, all_markets)
        if not product_pairs:
            return (
                "manual_review_geo_pairing",
                "Geographic market has no obvious product market pairing. "
                "Verify this geographic scope is independent or pair with a product market definition.",
            )

    return base_action, base_reason


def _build_promotion_plan(
    draft_record: dict,
    ref_map: dict[str, list[str]],
) -> list[dict]:
    """Build a source-first promotion plan with hardening guards applied.

    Works without an existing canonical YAML — operates purely on draft record.
    Applies guards: source role validation, caveat checks, geographic pairing.

    Returns a list of dicts, one per draft market, ordered product then geographic.
    """
    plan: list[dict] = []

    # Build a passage lookup by market_id to check source roles
    passage_by_market: dict[str, list[ExtractedPassage]] = {}
    for sp in (draft_record.get("source_passages") or []):
        for mid in (sp.get("supports_markets") or []) + (sp.get("supports_geographic_markets") or []):
            if mid not in passage_by_market:
                passage_by_market[mid] = []
            # Reconstruct a passage object from the stored data
            passage_by_market[mid].append(ExtractedPassage(
                chunk_id=sp.get("source_document_id", ""),
                page_number=int(sp.get("page", "0") or "0"),
                quote=sp.get("quote_snippet", ""),
                validated=True,
                source_document_id=sp.get("source_document_id", ""),
                source_role=sp.get("source_role", ""),
            ))

    # Build market maps for pairing checks
    all_markets = {
        "product": draft_record.get("product_markets_considered") or [],
        "geographic": draft_record.get("geographic_markets_considered") or [],
    }

    # Get caveats from draft
    caveats = draft_record.get("caveats") or []

    def _process_market_list(items: list[dict], market_type: str) -> None:
        for m in items:
            mid = str(m.get("market_id") or "")
            importance = str(m.get("market_importance") or "")
            status = str(m.get("definition_status") or "")
            market_name = m.get("name", "")
            source_refs = list(dict.fromkeys(ref_map.get(mid, [])))
            passages = passage_by_market.get(mid, [])

            # Apply hardening guards
            action, reason = _promotion_action_with_guards(
                importance, status, bool(source_refs),
                passages, caveats, market_type, market_name, all_markets,
            )

            entry: dict = {
                "draft_name": market_name,
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


def _group_promotion_plan_by_action(plan: list[dict]) -> dict[str, list[dict]]:
    """Group promotion plan entries by their recommended_action.

    Returns a dict mapping action names to lists of plan entries that recommend that action.
    Includes a count of entries per action for quick triage.
    """
    groups: dict[str, list[dict]] = {}
    for entry in plan:
        action = entry.get("recommended_action", "manual_review")
        if action not in groups:
            groups[action] = []
        groups[action].append(entry)
    return groups


def _build_promotion_plan_summary(plan: list[dict]) -> dict:
    """Build a summary of the promotion plan grouped by recommended_action.

    Returns a dict with total counts and per-action breakdowns, enabling source-first
    merge triage: 'how many core_assessed markets need canonical promotion'
    vs 'how many are assessed_no_overlap or ancillary and should stay as context only'.
    """
    grouped = _group_promotion_plan_by_action(plan)
    by_action: dict[str, int] = {action: len(entries) for action, entries in grouped.items()}

    # Build per-action details for transparency
    action_details: dict[str, dict] = {}
    for action, entries in grouped.items():
        mtype_counts = {}
        importance_counts = {}
        for entry in entries:
            mtype = entry.get("draft_market_type", "unclassified")
            importance = entry.get("market_importance", "unclassified")
            mtype_counts[mtype] = mtype_counts.get(mtype, 0) + 1
            importance_counts[importance] = importance_counts.get(importance, 0) + 1
        action_details[action] = {
            "count": len(entries),
            "by_market_type": mtype_counts,
            "by_market_importance": importance_counts,
        }

    return {
        "total_entries": len(plan),
        "by_action": by_action,
        "action_details": action_details,
    }


def _build_canonical_merge_candidates(plan: list[dict]) -> dict:
    """Build a structured grouping of markets ready for canonical merge.

    Groups promotion plan entries by merge readiness:
    - safe_to_promote: promote_to_canonical (ready now)
    - uncertain_markets: promote_with_uncertainty (needs review)
    - context_only: keep_as_context_only (preserve but don't promote)
    - hold_pending_source_check: re-run with broader sections
    - manual_review: various issues requiring human judgment
    - manual_review_geo_pairing: geographic markets needing product pairing

    Returns dict with these categories and counts.
    """
    result = {
        "safe_to_promote": [],
        "uncertain_markets": [],
        "context_only": [],
        "hold_pending_source_check": [],
        "manual_review": [],
        "manual_review_geo_pairing": [],
    }

    for entry in plan:
        action = entry.get("recommended_action", "manual_review")
        # Strip the entry down to essential info for each category
        summary = {
            "name": entry.get("draft_name", ""),
            "market_type": entry.get("draft_market_type", ""),
            "importance": entry.get("market_importance", ""),
            "definition_status": entry.get("definition_status", ""),
            "reason": entry.get("reason", ""),
        }
        if entry.get("source_refs"):
            summary["source_refs"] = entry["source_refs"]

        if action == "promote_to_canonical":
            result["safe_to_promote"].append(summary)
        elif action == "promote_with_uncertainty":
            result["uncertain_markets"].append(summary)
        elif action == "keep_as_context_only":
            result["context_only"].append(summary)
        elif action == "hold_pending_source_check":
            result["hold_pending_source_check"].append(summary)
        elif action == "manual_review_geo_pairing":
            result["manual_review_geo_pairing"].append(summary)
        else:  # manual_review and any others
            result["manual_review"].append(summary)

    # Add counts
    result["_counts"] = {k: len(v) for k, v in result.items() if k != "_counts"}

    return result


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
    promotion_plan = _serialize_promotion_plan(report.draft_record)
    promotion_plan_summary = _build_promotion_plan_summary(promotion_plan)
    canonical_merge_candidates = _build_canonical_merge_candidates(promotion_plan)
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
        "promotion_plan": promotion_plan,
        "promotion_plan_summary": promotion_plan_summary,
        "promotion_plan_note": (
            "promotion_plan is the authoritative source-first canonicalisation aid. "
            "Each market's recommended_action (promote_to_canonical, keep_as_context_only, etc.) "
            "is derived from the Commission's assessment in source documents. "
            "Reconciliation sections below are supplementary only and should not override these decisions."
        ),
        "canonical_merge_candidates": canonical_merge_candidates,
        "canonical_merge_note": (
            "canonical_merge_candidates groups the promotion_plan by merge readiness: "
            "safe_to_promote contains only promote_to_canonical items ready for immediate merge; "
            "uncertain_markets needs review; context_only should not be promoted; "
            "hold_pending requires broader source re-runs; manual_review needs human judgment."
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

def _filter_chunks_to_range(
    chunks: list[ChunkInfo],
    page_range: tuple[int, int],
) -> list[ChunkInfo]:
    """Return chunks restricted to pages within [page_range[0], page_range[1]] inclusive.

    Chunks that overlap partially with the range have their pages trimmed to those
    within the range.  Chunks with no pages in range are dropped entirely.
    The original pages list on each chunk is replaced with the filtered subset;
    trimmed_pages is left empty (no prefix trimming needed at this stage).
    """
    pr_start, pr_end = page_range
    result: list[ChunkInfo] = []
    for c in chunks:
        in_range = [p for p in c.pages if pr_start <= p["page_number"] <= pr_end]
        if not in_range:
            continue
        result.append(ChunkInfo(
            chunk_id=c.chunk_id,
            section_path=c.section_path,
            pages=in_range,
            source_document_id=c.source_document_id,
        ))
    return result


def extract_case(
    yaml_path: Path,
    *,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    output_path: Optional[Path] = None,
    report_json: Optional[Path] = None,
    use_claude: bool = True,
    llm_client: Optional["LLMClient"] = None,
    anthropic_client=None,  # deprecated: use llm_client
    max_input_pages: int = _MAX_INPUT_PAGES,
    max_chunks: Optional[int] = None,
    debug_dir: Optional[Path] = None,
    focus: Optional[str] = None,
    batch_by_section: bool = False,
    section_prefix: Optional[str] = None,
    max_section_batches: Optional[int] = None,
    max_cost: Optional[float] = None,
    max_input_tokens: Optional[int] = None,
    full_market_def_pass: bool = False,
    page_range: Optional[tuple[int, int]] = None,
    profile=None,
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

    When *page_range* is (start, end), only pages in [start, end] (inclusive)
    are considered.  Coverage stats are relative to the restricted range, making
    section-group iteration on long decisions straightforward.  ``page_range``
    is compatible with ``batch_by_section``.
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

    # Apply page-range restriction before focus selection.
    # Coverage stats are relative to the restricted range so that section-group
    # iteration (e.g. pp64-309) reports meaningful per-run numbers.
    _document_total_non_toc = sum(len(c.pages) for c in all_chunks)
    if page_range is not None:
        pr_start, pr_end = page_range
        if pr_start < 1 or pr_end < pr_start:
            report.error = (
                f"Invalid page_range ({pr_start}, {pr_end}): "
                "start must be >= 1 and end must be >= start"
            )
            return report
        all_chunks = _filter_chunks_to_range(all_chunks, page_range)
        if not all_chunks:
            report.error = (
                f"page_range ({pr_start}, {pr_end}) matched no pages in the document "
                f"(document has {_document_total_non_toc} non-TOC pages)"
            )
            return report

    selected = _select_relevant_chunks(
        all_chunks, max_total_pages=max_input_pages, focus=focus,
        full_market_def_pass=full_market_def_pass, profile=profile,
    )
    if max_chunks is not None:
        selected = selected[:max_chunks]

    # Record coverage stats for the review report.
    _total_non_toc = sum(len(c.pages) for c in all_chunks)
    _selected_pages = sum(len(c.pages) for c in selected)
    report.selection_coverage = {
        "total_non_toc_pages": _total_non_toc,
        "selected_pages": _selected_pages,
        "ratio": round(_selected_pages / _total_non_toc, 3) if _total_non_toc else 1.0,
        "page_range": list(page_range) if page_range is not None else None,
        "document_total_non_toc_pages": _document_total_non_toc,
    }

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

    # Backward compat: wrap a bare anthropic_client in LLMClient.
    if llm_client is None and anthropic_client is not None:
        llm_client = LLMClient("anthropic", anthropic_client)

    if llm_client is None:
        report.error = (
            "No LLM client available — pass llm_client or anthropic_client, "
            "or set ANTHROPIC_API_KEY / GOOGLE_API_KEY"
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
    # unit_assessment uses a separate tool/prompt; _extract_section_batch only
    # knows the standard extraction path, so force single-batch mode here.
    if batch_by_section and focus == "unit_assessment":
        print(
            "  INFO: --batch-by-section not supported for unit_assessment focus "
            "(uses single-batch automatically)"
        )
        batch_by_section = False

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
                llm_client, _effective_debug_dir, case_id,
                profile=profile,
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

        # -------------------------------------------------------------------
        # unit_assessment focus uses a separate tool and validation path.
        # -------------------------------------------------------------------
        if focus == "unit_assessment":
            prompt = _build_unit_assessment_prompt(selected, existing_record)
            try:
                response_text = llm_client.call_unit_assessment(prompt)
            except Exception as exc:
                report.error = f"LLM API error: {exc}"
                return report

            try:
                raw = _parse_extraction_response(
                    response_text, debug_dir=_effective_debug_dir, case_id=case_id
                )
            except ValueError as exc:
                report.error = f"Failed to parse Claude response: {exc}"
                return report

            if not raw:
                _effective_debug_dir.mkdir(parents=True, exist_ok=True)
                debug_path = _effective_debug_dir / f"{case_id}_claude_raw_response.txt"
                debug_path.write_text(response_text, encoding="utf-8")
                report.error = (
                    f"Claude returned empty unit_assessment object — "
                    f"raw response saved to {debug_path}"
                )
                return report

            result = _validate_unit_assessment(raw, selected, chunk_doc_map)
            result.raw_response = response_text
            report.result = result

        # -------------------------------------------------------------------
        # Standard extraction path (all other focus modes)
        # -------------------------------------------------------------------
        else:
            prompt = _build_extraction_prompt(selected, existing_record, profile=profile)
            try:
                response_text = llm_client.call_extraction(prompt)
            except Exception as exc:
                report.error = f"LLM API error: {exc}"
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
                        repaired_text = llm_client.call_repair(response_text, all_errors)
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
        description="Source-first extraction and reconciliation for Meridian cases"
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
    parser.add_argument(
        "--profile",
        default=None,
        help=(
            "Pipeline profile ID (ec_decision | cma_report | us_court_opinion). "
            "Inferred from case_id prefix when omitted."
        ),
    )
    parser.add_argument(
        "--provider",
        default="anthropic",
        choices=["anthropic", "gemini"],
        help=(
            "LLM provider for extraction calls. "
            "'anthropic' uses Claude (requires ANTHROPIC_API_KEY); "
            "'gemini' uses Gemini 2.0 Flash (requires GOOGLE_API_KEY, free tier available)."
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
            print("Extraction (replayed):")
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

    # --inspect-chunks / --estimate-cost imply no LLM call and no file output
    inspect_mode = args.inspect_chunks
    estimate_mode = args.estimate_cost
    use_claude = not args.no_claude and not inspect_mode and not estimate_mode
    llm_client = None

    provider = getattr(args, "provider", "anthropic") or "anthropic"

    if use_claude:
        if provider == "gemini":
            try:
                from google import genai as _genai
                _gc = _genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
                llm_client = LLMClient("gemini", _gc)
            except (ImportError, KeyError) as exc:
                print(
                    f"google-genai package or GOOGLE_API_KEY not available ({exc}) — "
                    "falling back to --no-claude mode"
                )
                use_claude = False
        else:
            try:
                import anthropic as _anthropic
                _ac = _anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
                llm_client = LLMClient("anthropic", _ac)
            except (ImportError, KeyError):
                print(
                    "anthropic package or ANTHROPIC_API_KEY not available — "
                    "falling back to --no-claude mode"
                )
                use_claude = False

    no_output = inspect_mode or estimate_mode
    output_path = Path(args.output) if args.output and not no_output else None
    report_json = Path(args.report_json) if args.report_json and not no_output else None

    try:
        _profile = select_profile(args.case_id, profile_id=args.profile)
    except ValueError as exc:
        print(f"WARNING: could not select pipeline profile: {exc}", file=sys.stderr)
        _profile = None

    print(f"Case:    {args.case_id}")
    print(f"YAML:    {yaml_path}")
    print(f"Cache:   {cache_dir}")
    if _profile is not None:
        print(f"Profile: {_profile.profile_id} ({_profile.display_name})")
    if args.focus:
        print(f"Focus:   {args.focus}")
    if args.section_prefix:
        print(f"Section prefix: {args.section_prefix}")
    if inspect_mode:
        print("Mode:    inspect-chunks (no Claude call)")
    elif estimate_mode:
        print("Mode:    estimate-cost (no Claude call)")
    elif args.batch_by_section or args.section_prefix:
        batch_desc = "batched by section"
        if args.section_prefix:
            batch_desc += f" (prefix: {args.section_prefix})"
        if args.max_section_batches:
            batch_desc += f", max {args.max_section_batches} batches"
        print(f"Mode:    {batch_desc}")
    else:
        if use_claude:
            label = f"enabled ({provider})"
        else:
            label = "disabled (section-analysis only)"
        print(f"LLM:     {label}")
    print()

    rpt = extract_case(
        yaml_path,
        cache_dir=cache_dir,
        output_path=output_path,
        report_json=report_json,
        use_claude=use_claude,
        llm_client=llm_client,
        max_input_pages=args.max_pages,
        max_chunks=args.max_chunks,
        focus=args.focus,
        batch_by_section=args.batch_by_section,
        section_prefix=args.section_prefix,
        max_section_batches=args.max_section_batches,
        max_cost=args.max_cost,
        max_input_tokens=args.max_input_tokens,
        profile=_profile,
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
        used_fallback = any(c.selection_method == "page_text_fallback" for c in rpt.chunks_used)
        selection_label = (
            "neutral page-text fallback (section-path selection returned 0)"
            if used_fallback
            else "normal section-path selection"
        )
        print(f"Selected chunks: {len(rpt.chunks_used)}  [selection: {selection_label}]\n")
        for c in rpt.chunks_used:
            label = c.section_path if c.section_path else "unknown"
            fallback_note = "  [FALLBACK]" if c.selection_method == "page_text_fallback" else ""
            spill_note = (
                f"  [spillover for {c.effective_prefix}]"
                if c.effective_prefix and c.selection_method != "page_text_fallback"
                else ""
            )
            print(f"{c.chunk_id}  {c.page_range}  [{label}]{spill_note}{fallback_note}")
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
        print("\nExtraction:")
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
