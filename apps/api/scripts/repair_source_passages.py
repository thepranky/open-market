#!/usr/bin/env python3
"""
repair_source_passages.py — ground CompMap source_passages in real PDF text.

For each existing source_passage:
  1. Loads the PDF text cache (builds it from the pdf_url if missing).
  2. Checks whether the quote appears on the listed page.
  3. If not, searches all pages and reports the corrected page.
  4. If not found anywhere, flags as hallucinated and removes support credit.

For every proposition (market / theory), determines whether it has VALID
grounded support.  A passage whose quote is not found in the PDF (not_found)
does NOT count as support:

  Proposition statuses:
    valid_support         — at least one ok/wrong_page passage
    candidates_found      — no valid support; PDF search found candidate pages
    no_candidates         — no valid support; nothing useful found in PDF

Dry-run (default): report only, no YAML changes.
  --report-json <path>  : also write a machine-readable JSON report.
Write mode (--write)    : applies page corrections; requires --use-claude
                          to fill newly unsupported propositions.

Usage:
    cd apps/api

    # Validate and report — no changes:
    .venv/bin/python scripts/repair_source_passages.py \\
        --cases-dir ../../data/cases --case-id eu_google_fitbit_2021 --dry-run

    # Inspect machine-readable report:
    .venv/bin/python scripts/repair_source_passages.py \\
        --all --dry-run --report-json ../../data/source_text/repair_report.json

    # Write repairs (page-number corrections only, no Claude):
    .venv/bin/python scripts/repair_source_passages.py \\
        --case-id eu_google_fitbit_2021 --write

    # Write repairs + fill unsupported propositions (requires ANTHROPIC_API_KEY):
    .venv/bin/python scripts/repair_source_passages.py \\
        --case-id eu_google_fitbit_2021 --use-claude --write
"""

import argparse
import copy
import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
import yaml

# Allow running from the scripts/ directory or from apps/api/
_API_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_API_DIR))

from app.shared.utils.pdf_extractor import (
    DEFAULT_CACHE_DIR,
    fetch_and_extract,
    get_page_text,
    iter_pages,
    load_cache,
)

sys.path.insert(0, str(Path(__file__).parent))
from check_source_integrity import _normalise, quote_found_in_text


_CASES_DIR = Path(__file__).resolve().parents[3] / "data" / "cases"

_CANDIDATE_WINDOW = 600   # chars on each side of a keyword hit
_MAX_CANDIDATES = 5       # candidates per proposition
_MIN_KEYWORD_LEN = 5

# Kept for backward compat with _confidence_label (used in tests)
_STRONG_THRESHOLD = 4
_POSSIBLE_THRESHOLD = 2

# ---------------------------------------------------------------------------
# Type-aware signal and penalty tables (all phrases already in normalised form:
# lowercase, ASCII, no punctuation, single spaces)
# ---------------------------------------------------------------------------

# Positive signals per proposition type.  Tuple: (normalised_phrase, weight).
_TYPE_SIGNALS: dict[str, list[tuple[str, int]]] = {
    "product_market": [
        ("relevant product market", 5),
        ("product market definition", 5),
        ("market is defined", 4),
        ("defines a relevant", 4),
        ("constitutes a relevant", 4),
        ("product market", 3),
        ("market definition", 4),
        ("market for", 2),
        ("the relevant market", 3),
        ("commission concludes that the relevant", 5),
        ("distinct from", 2),
        ("left open", 3),
        ("no need to define", 3),
        ("wider market", 3),
        ("narrower market", 3),
    ],
    "geographic_market": [
        ("relevant geographic market", 5),
        ("geographic market", 4),
        ("geographic scope", 4),
        ("at least eea", 3),
        ("eea wide", 3),           # normalised from "EEA-wide"
        ("competitive conditions across", 3),
        ("across the eea", 3),
        ("national market", 2),
        ("worldwide market", 3),
        ("geographic", 2),
        ("member states", 2),
        ("broader than", 2),
    ],
    "theory_of_harm": [
        ("theory of harm", 5),
        ("ability to foreclose", 5),
        ("incentive to foreclose", 5),
        ("input foreclosure", 5),
        ("technical tying", 5),
        ("data advantage", 4),
        ("competitive harm", 4),
        ("harm to competition", 4),
        ("anticompetitive", 3),
        ("horizontal effects", 4),
        ("vertical effects", 4),
        ("competitive assessment", 4),
        ("non horizontal merger", 4),  # normalised "non-horizontal merger"
        ("effects on competition", 3),
        ("foreclosure", 3),
        ("degrade", 3),
        ("interoperability", 3),
        ("incentive", 2),
        ("ability", 1),
    ],
}

# Penalty phrases per proposition type.
# High penalty → passage is almost certainly from a different section.
_PENALTY_SIGNALS: dict[str, list[tuple[str, int]]] = {
    "product_market": [
        # Theory-of-harm section language
        ("input foreclosure", 4),
        ("technical tying", 4),
        ("ability to foreclose", 3),
        ("incentive to foreclose", 3),
        # Effects-analysis section language
        ("horizontal effects", 3),
        ("vertical effects", 3),
    ],
    "geographic_market": [
        ("input foreclosure", 3),
        ("ability to foreclose", 3),
        ("incentive to foreclose", 3),
        ("horizontal effects", 2),
        ("vertical effects", 2),
        ("technical tying", 3),
    ],
    "theory_of_harm": [],  # ToH sections legitimately reference any other section
}

# Per-subtype bonus signals for theory_of_harm propositions.
# Keyed by subtype: "data_advantage" | "foreclosure_vertical" | "horizontal" | "generic"
_TOH_SUBTYPE_BONUS: dict[str, list[tuple[str, int]]] = {
    "data_advantage": [
        ("health and wellness data", 6),
        ("data advantage", 6),
        ("data aggregation", 5),
        ("fitbit data", 5),
        ("personalisation", 4),
        ("personalise", 4),
        ("search advertising", 4),
        ("display advertising", 4),
        ("health data", 4),
        ("strengthen", 3),
        ("aggregation", 3),
    ],
    "foreclosure_vertical": [
        ("wear os", 6),
        ("companion app", 5),
        ("app gallery", 5),
        ("degrade interoperability", 5),
        ("access to wear", 5),
        ("google apps", 4),
        ("interoperability", 3),
        ("degrade", 3),
    ],
    "horizontal": [
        ("horizontal effects", 5),
        ("horizontal merger", 5),
        ("hhi", 5),
        ("market share", 4),
        ("overlap", 4),
        ("concentration", 4),
        ("increment", 3),
    ],
}

# Per-subtype penalty signals for theory_of_harm propositions.
_TOH_SUBTYPE_PENALTY: dict[str, list[tuple[str, int]]] = {
    "data_advantage": [
        ("wear os", 5),
        ("companion app", 5),
        ("app gallery", 5),
        ("access to wear", 5),
        ("google apps on wearable", 4),
    ],
    "foreclosure_vertical": [
        ("data advantage", 5),
        ("health data", 4),
        ("fitbit data", 4),
        ("personalise", 4),
        ("advertising position", 4),
    ],
    "horizontal": [
        ("input foreclosure", 4),
        ("ability to foreclose", 4),
        ("incentive to foreclose", 4),
        ("technical tying", 4),
        ("conglomerate", 4),
    ],
}

_STOP_WORDS: set[str] = {
    "about", "above", "after", "also", "and", "any", "are", "been", "being",
    "both", "but", "by", "can", "case", "commission", "competition", "court",
    "decision", "each", "for", "from", "given", "had", "has", "have", "here",
    "however", "into", "its", "may", "more", "most", "not", "note", "other",
    "over", "own", "part", "party", "per", "point", "regarding", "relevant",
    "shall", "since", "some", "such", "than", "that", "the", "their",
    "therefore", "there", "these", "they", "this", "those", "through", "thus",
    "under", "upon", "was", "were", "which", "while", "will", "with", "would",
    "year", "years",
}

# Words that are too generic to discriminate between sections/topics.
_TOPIC_STOP_WORDS: frozenset[str] = frozenset({
    "and", "for", "the", "in", "of", "to", "a", "an", "is", "are",
    "with", "by", "on", "at", "from", "or", "its", "this", "that",
    "chapter", "section", "overview", "assessment", "analysis",
    "considerations", "introduction", "conclusion", "general",
})

# Regex matching numbered section headings common in EC/CMA/DOJ decisions.
# Matches: "8.6  Online advertising", "9.4.3 Ability and incentives"
# Also matches EC-style trailing-dot format: "8.6. Online advertising"
_HEADING_RE = re.compile(
    r"^\s*(\d+(?:\.\d+)*)\.?\s{1,8}([A-Z][A-Za-z0-9 /,&()\-–—]+)",
    re.MULTILINE,
)

# Lines that look like numbered headings but are actually footnotes or
# bibliographic references.  Reject heading_text when this matches.
_HEADING_REJECT_RE = re.compile(
    r"(?i)"
    r"Replies\s+to\s+questionnaire"
    r"|Commission\s+decision\s+of\s+\d"
    r"|Non.Horizontal\s+Merger\s+Guideline"
    r"|Horizontal\s+Merger\s+Guideline"
    r"|Form\s+CO\b"
    r"|,\s*paragraph\s+\d"
    r"|\bOJ\s+[LC]\s+\d"
    r"|\bibid\b"
    r"|Judgm[ea]nt\s+of"
    r"|Court\s+of\s+Justice"
    r"|General\s+Court\b"
    r"|Case\s+[A-Z]\.\d"
    # Footnote text patterns: start with "In " (e.g. "In the past, Fitbit also...")
    r"|^In\b"
    # Footnote text patterns: start with a month name (e.g. "July 2020", "December 21, 2016")
    r"|^(?:January|February|March|April|May|June|July|August|September|October|November|December)\b"
    # EC case references: COMP/M.XXXX or COMP/AT.XXXX
    r"|\bCOMP/[MA]\b"
    # "See X" cross-references
    r"|^See\b"
)

# Four-or-more consecutive dots — signature of table-of-contents leader lines.
_TOC_LEADER_RE = re.compile(r"\.{4,}")


# ---------------------------------------------------------------------------
# Section-aware helpers
# ---------------------------------------------------------------------------

def _extract_section_map(page_cache: dict) -> dict[int, str]:
    """
    Return {page_number: section_path} for every page in the cache.

    Scans pages in order, maintains a heading stack based on numbering depth.
    section_path is the " > "-joined chain of all active headings, e.g.:
        "8 Product market > 8.6 Online advertising > 8.6.1 Product market definition"

    Best-effort for EC/CMA/DOJ numbered-section PDFs. Falls back to "" when no
    headings are found.
    """
    # Each entry: (depth, "8.6 Online advertising")
    heading_stack: list[tuple[int, str]] = []
    result: dict[int, str] = {}

    for page_num, text in iter_pages(page_cache):
        for m in _HEADING_RE.finditer(text):
            num_str = m.group(1)
            heading_text = m.group(2).strip()
            if len(heading_text) < 4:
                continue
            # Real section headings are short titles (≤65 chars, ≤8 words).
            # Footnote prose or citation text tends to be longer.
            if len(heading_text) > 65:
                continue
            if len(heading_text.split()) > 8:
                continue
            parts = num_str.split(".")
            depth = len(parts)
            # Top-level section number > 25 means it's almost certainly a footnote
            # reference or paragraph number, not a real section heading.  Check the
            # top-level component for all depths (e.g. "2011.309" → top=2011 → reject).
            if int(parts[0]) > 25:
                continue
            # Reject footnote / bibliographic reference text patterns
            if _HEADING_REJECT_RE.search(heading_text):
                continue
            heading = f"{num_str} {heading_text}"
            # Pop stack entries at the same or greater depth
            while heading_stack and heading_stack[-1][0] >= depth:
                heading_stack.pop()
            heading_stack.append((depth, heading))

        result[page_num] = " > ".join(h for _, h in heading_stack)

    return result


def _topic_words(text: str) -> list[str]:
    """
    Extract meaningful topic words from a short text (proposition name or section title).

    Strips section numbers, replaces separators with spaces, lower-cases, and
    filters stop words.  Returns at most 12 unique tokens.
    """
    # Remove leading section number (e.g., "8.6 ")
    text = re.sub(r"^\d+(?:\.\d+)*\s*", "", text)
    # Replace separators with spaces
    text = re.sub(r"[/\-–—|]+", " ", text.lower())
    tokens = re.findall(r"[a-z]{3,}", text)
    seen: set[str] = set()
    result: list[str] = []
    for t in tokens:
        if t not in _TOPIC_STOP_WORDS and t not in seen:
            seen.add(t)
            result.append(t)
    return result[:12]


def _section_coherence_score(
    section_path: str,
    prop_topic_words: list[str],
) -> tuple[int, int, str]:
    """
    Return (topic_bonus, topic_penalty, reason).

    topic_bonus  — section path contains proposition topic words → likely right section
    topic_penalty — section path has content but zero overlap with prop → likely wrong section
    """
    if not section_path or not prop_topic_words:
        return 0, 0, ""

    section_words = set(_topic_words(section_path))
    prop_words = set(prop_topic_words)

    if not section_words:
        return 0, 0, ""

    overlap = prop_words & section_words
    count = len(overlap)

    if count >= 2:
        phrases = ", ".join(repr(w) for w in sorted(overlap)[:3])
        return 6, 0, f"Section topic match: {phrases}"
    if count == 1:
        phrase = repr(next(iter(overlap)))
        return 3, 0, f"Section partial match: {phrase}"

    # No overlap — section is about a different topic.
    # Penalise more for deep (specific) sections, less for shallow ones.
    depth = section_path.count(" > ") + 1
    penalty = 5 if depth >= 2 else 2
    nearest = section_path.split(" > ")[-1]
    return 0, penalty, f"Section topic mismatch: '{nearest}'"


def _is_toc_page(text: str) -> bool:
    """Return True if *text* looks like a table-of-contents page.

    Detected by four or more dotted leader lines (e.g., "8.6 Online advertising.......95").
    """
    return len(_TOC_LEADER_RE.findall(text)) >= 4


# ---------------------------------------------------------------------------
# Type-aware scoring helpers
# ---------------------------------------------------------------------------

def _support_type_to_confidence(support_type: str) -> str:
    return {
        "direct_support": "strong",
        "contextual_support": "possible",
        "weak_keyword_match": "weak",
        "likely_wrong_section": "weak",
    }.get(support_type, "weak")


def _score_type_signals(
    normalised_text: str,
    proposition_type: str,
) -> tuple[int, int, list[str], list[str]]:
    """Return (type_bonus, penalty_score, signal_phrases, penalty_phrases)."""
    type_bonus = 0
    signal_phrases: list[str] = []
    for phrase, weight in _TYPE_SIGNALS.get(proposition_type, []):
        if phrase in normalised_text:
            type_bonus += weight
            signal_phrases.append(phrase)

    penalty_score = 0
    penalty_phrases: list[str] = []
    for phrase, weight in _PENALTY_SIGNALS.get(proposition_type, []):
        if phrase in normalised_text:
            penalty_score += weight
            penalty_phrases.append(phrase)

    return type_bonus, penalty_score, signal_phrases, penalty_phrases


def _detect_toh_subtype(prop_name: str, description: str = "") -> str:
    """Detect theory-of-harm subtype from proposition name/description.

    Returns one of: "data_advantage" | "foreclosure_vertical" | "horizontal" | "generic"
    """
    text = (prop_name + " " + description).lower()
    if any(kw in text for kw in ("data advantage", "data in", "advertising data", "health data")):
        return "data_advantage"
    if any(kw in text for kw in ("wear os", "foreclos", "app ecosystem",
                                   "app gallery", "companion app", "input foreclosure")):
        return "foreclosure_vertical"
    if any(kw in text for kw in ("conglomerate", "portfolio", "tying", "bundling")):
        return "conglomerate"
    if any(kw in text for kw in ("horizontal", "consolidat")):
        return "horizontal"
    return "generic"


def _score_toh_subtype_signals(
    normalised_text: str,
    subtype: str,
) -> tuple[int, int, list[str], list[str]]:
    """Return (bonus, penalty, signal_phrases, penalty_phrases) for a ToH subtype."""
    bonus = 0
    signals: list[str] = []
    for phrase, weight in _TOH_SUBTYPE_BONUS.get(subtype, []):
        if phrase in normalised_text:
            bonus += weight
            signals.append(phrase)

    penalty = 0
    penalties: list[str] = []
    for phrase, weight in _TOH_SUBTYPE_PENALTY.get(subtype, []):
        if phrase in normalised_text:
            penalty += weight
            penalties.append(phrase)

    return bonus, penalty, signals, penalties


def _classify_support_type(
    keyword_score: int,
    type_bonus: int,
    penalty_score: int,
    signal_phrases: list[str],
    penalty_phrases: list[str],
    topic_bonus: int = 0,
    topic_penalty: int = 0,
    section_path: str = "",
) -> tuple[str, str]:
    """Return (support_type, reason)."""
    # Section mismatch overrides type-signal analysis.
    # High topic_penalty means the section heading clearly belongs to a
    # different market / theory than the proposition being scored.
    if topic_penalty >= 4:
        nearest = section_path.split(" > ")[-1] if section_path else "unknown section"
        return "likely_wrong_section", f"Section about different topic: '{nearest}'"

    # Penalty signals (e.g., foreclosure language in a product-market query)
    combined = max(type_bonus + keyword_score, 1)
    if penalty_score >= 3 or (penalty_score > 0 and penalty_score * 2 >= combined):
        top_pen = " + ".join(repr(p) for p in penalty_phrases[:2])
        return "likely_wrong_section", f"Off-topic signals dominate: {top_pen}"

    # Direct support requires BOTH strong type signals AND section coherence.
    # When no section info is available (section_path == ""), fall back to
    # type-signal-only classification as before.
    has_section_info = bool(section_path)
    section_ok = (not has_section_info) or (topic_bonus >= 3)

    if type_bonus >= 4 and penalty_score <= 1 and section_ok:
        top_sig = " + ".join(repr(p) for p in signal_phrases[:2])
        if topic_bonus >= 3:
            nearest = section_path.split(" > ")[-1]
            return "direct_support", f"Definition language + section match: {top_sig} ({nearest})"
        return "direct_support", f"Definition language found: {top_sig}"

    if type_bonus >= 2 or topic_bonus >= 3:
        top_sig = repr(signal_phrases[0]) if signal_phrases else "some signals"
        return "contextual_support", f"Some section-relevant language: {top_sig}"

    return "weak_keyword_match", "Keyword overlap — no section-specific language"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class PassageValidationResult:
    passage_id: str
    source_document_id: str
    listed_page: Optional[int]
    status: str          # "ok" | "wrong_page" | "not_found" | "no_cache"
    found_on_page: Optional[int]
    message: str
    original_quote: str = ""   # stored for JSON report inspection
    repaired_page: Optional[int] = None


@dataclass
class Candidate:
    page_number: int
    text_window: str
    source_document_id: str = ""
    match_terms: list[str] = field(default_factory=list)
    keyword_score: int = 0
    type_bonus: int = 0
    penalty_score: int = 0
    topic_bonus: int = 0
    topic_penalty: int = 0
    composite_score: int = 0
    support_type: str = "weak_keyword_match"
    reason: str = ""
    section_path: str = ""
    signal_phrases: list[str] = field(default_factory=list)
    penalty_phrases: list[str] = field(default_factory=list)

    @property
    def score(self) -> int:
        return self.composite_score

    @property
    def confidence(self) -> str:
        return _support_type_to_confidence(self.support_type)

    def display(self, index: int, snippet_len: int = 500) -> str:
        snippet = self.text_window[:snippet_len].replace("\n", " ").strip()
        conf_tag = f"[{self.support_type.upper()}]"
        terms = ", ".join(self.match_terms[:6])
        section_display = self.section_path if self.section_path else "unknown"
        section_line = f"        section: {section_display}\n"
        return (
            f"    [{index}] {self.source_document_id or '?'} p.{self.page_number}"
            f"  composite={self.composite_score}"
            f" (kw={self.keyword_score} +type={self.type_bonus}"
            f" +topic={self.topic_bonus} -pen={self.penalty_score}"
            f" -topicpen={self.topic_penalty})"
            f"  {conf_tag}\n"
            f"{section_line}"
            f"        reason: {self.reason}\n"
            f"        matched: {terms}\n"
            f'        "{snippet}"'
        )


@dataclass
class PropositionSearchResult:
    proposition_id: str
    proposition_type: str   # "product_market" | "geographic_market" | "theory_of_harm"
    proposition_name: str
    # "valid_support" | "candidates_found" | "no_candidates"
    status: str
    # Passage IDs whose quote was not found in PDF but claimed support for this proposition
    invalidated_passage_ids: list[str] = field(default_factory=list)
    candidates: list[Candidate] = field(default_factory=list)
    selected_candidate: Optional[Candidate] = None
    selected_quote: Optional[str] = None
    selected_page: Optional[int] = None
    # Set to "possible_mislabelled_proposition" when top candidates consistently
    # come from sections that don't match the proposition's topic.
    warning: Optional[str] = None


@dataclass
class RepairReport:
    case_id: str
    case_yaml_path: Path
    passage_results: list[PassageValidationResult] = field(default_factory=list)
    proposition_results: list[PropositionSearchResult] = field(default_factory=list)

    # --- Passage counters ---
    @property
    def existing_passages_ok(self) -> int:
        return sum(1 for r in self.passage_results if r.status == "ok")

    @property
    def existing_passages_wrong_page(self) -> int:
        return sum(1 for r in self.passage_results if r.status == "wrong_page")

    @property
    def existing_passages_not_found(self) -> int:
        return sum(1 for r in self.passage_results if r.status == "not_found")

    @property
    def existing_passages_no_cache(self) -> int:
        return sum(1 for r in self.passage_results if r.status == "no_cache")

    # --- Proposition counters ---
    @property
    def propositions_total(self) -> int:
        return len(self.proposition_results)

    @property
    def propositions_with_valid_support(self) -> int:
        return sum(1 for r in self.proposition_results if r.status == "valid_support")

    @property
    def propositions_with_candidates(self) -> int:
        return sum(1 for r in self.proposition_results if r.status == "candidates_found")

    @property
    def propositions_without_candidates(self) -> int:
        return sum(1 for r in self.proposition_results if r.status == "no_candidates")

    @property
    def candidate_passages_total(self) -> int:
        return sum(len(r.candidates) for r in self.proposition_results)

    # Legacy aliases used by existing tests
    @property
    def passages_ok(self) -> int:
        return self.existing_passages_ok

    @property
    def passages_wrong_page(self) -> int:
        return self.existing_passages_wrong_page

    @property
    def passages_not_found(self) -> int:
        return self.existing_passages_not_found

    @property
    def passages_no_cache(self) -> int:
        return self.existing_passages_no_cache

    @property
    def propositions_already_supported(self) -> int:
        return self.propositions_with_valid_support

    @property
    def propositions_not_found(self) -> int:
        return self.propositions_without_candidates


# ---------------------------------------------------------------------------
# Keyword extraction
# ---------------------------------------------------------------------------

def _extract_keywords(text: str) -> list[str]:
    """Return meaningful tokens from *text* for PDF search."""
    tokens = re.findall(r"[a-zA-Z]{" + str(_MIN_KEYWORD_LEN) + r",}", text)
    return [t for t in tokens if t.lower() not in _STOP_WORDS]


def _proposition_keywords(prop: dict, record: dict) -> list[str]:
    """
    Build a keyword list for proposition-driven PDF search.

    Sources (in priority order):
      1. Proposition name
      2. Proposition notes / description
      3. Party names
      4. Case sector
      5. Authority name
      6. Case name
    Existing quote_snippet is deliberately excluded — it may be hallucinated.
    """
    parts = [
        prop.get("name", ""),
        prop.get("description", ""),
        prop.get("notes", ""),
    ]
    for p in (record.get("parties") or []):
        parts.append(p.get("name", ""))
    parts.append(record.get("sector", ""))
    parts.append(record.get("authority", ""))
    parts.append(record.get("case_name", ""))

    raw = " ".join(filter(None, parts))
    seen: set[str] = set()
    result: list[str] = []
    for kw in _extract_keywords(raw):
        kl = kw.lower()
        if kl not in seen:
            seen.add(kl)
            result.append(kw)
    return result[:25]


def _confidence_label(score: int) -> str:
    if score >= _STRONG_THRESHOLD:
        return "strong"
    if score >= _POSSIBLE_THRESHOLD:
        return "possible"
    return "weak"


# ---------------------------------------------------------------------------
# Candidate passage search
# ---------------------------------------------------------------------------

def _find_candidates(
    keywords: list[str],
    page_cache: dict,
    proposition_type: str = "",
    prop_topic_words: Optional[list[str]] = None,
    section_map: Optional[dict[int, str]] = None,
    prop_name: str = "",
    window: int = _CANDIDATE_WINDOW,
    max_results: int = _MAX_CANDIDATES,
) -> list[Candidate]:
    """
    Scan all pages for keyword hits; return section-aware, type-aware ranked candidates.

    Composite score = keyword_score
                    + type_bonus * 2   (proposition-type signal phrases)
                    - penalty_score * 2
                    + topic_bonus * 2  (section heading matches proposition topic)
                    - topic_penalty * 3 (section heading clearly about different topic)
    """
    if not keywords:
        return []

    doc_id = page_cache.get("source_document_id", "")
    normalised_kws = [kw.lower() for kw in keywords]

    # Build section map lazily if not provided
    if section_map is None:
        section_map = _extract_section_map(page_cache)

    candidates: list[Candidate] = []

    for page_num, text in iter_pages(page_cache):
        if not text or _is_toc_page(text):
            continue
        nlower = text.lower()
        matched_terms: list[str] = []
        first_pos = len(text)

        for kw, nkw in zip(keywords, normalised_kws):
            pos = nlower.find(nkw)
            if pos >= 0:
                matched_terms.append(kw)
                first_pos = min(first_pos, pos)

        if not matched_terms:
            continue

        start = max(0, first_pos - window)
        end = min(len(text), first_pos + window)
        text_window = text[start:end]
        keyword_score = len(matched_terms)

        type_bonus, penalty_score, signal_phrases, penalty_phrases = _score_type_signals(
            nlower, proposition_type
        )

        # For theory_of_harm, apply subtype-specific bonus/penalty on top of generic signals
        if proposition_type == "theory_of_harm" and prop_name:
            toh_subtype = _detect_toh_subtype(prop_name)
            sub_bonus, sub_pen, sub_sigs, sub_pens = _score_toh_subtype_signals(
                nlower, toh_subtype
            )
            type_bonus += sub_bonus
            penalty_score += sub_pen
            signal_phrases = signal_phrases + sub_sigs
            penalty_phrases = penalty_phrases + sub_pens

        section_path = section_map.get(page_num, "")
        topic_bonus, topic_penalty, _topic_reason = _section_coherence_score(
            section_path, prop_topic_words or []
        )

        if topic_penalty >= 4:
            # Section is clearly about a different market/theory.
            # Type signals from the wrong section are misleading noise;
            # ignore them and score purely on keyword overlap minus mismatch.
            composite = keyword_score - topic_penalty * 2
        else:
            composite = (
                keyword_score
                + type_bonus * 2
                - penalty_score * 2
                + topic_bonus * 2
                - topic_penalty * 3
            )
        support_type, reason = _classify_support_type(
            keyword_score, type_bonus, penalty_score, signal_phrases, penalty_phrases,
            topic_bonus=topic_bonus, topic_penalty=topic_penalty, section_path=section_path,
        )

        candidates.append(Candidate(
            page_number=page_num,
            text_window=text_window,
            source_document_id=doc_id,
            match_terms=matched_terms,
            keyword_score=keyword_score,
            type_bonus=type_bonus,
            penalty_score=penalty_score,
            topic_bonus=topic_bonus,
            topic_penalty=topic_penalty,
            composite_score=composite,
            support_type=support_type,
            reason=reason,
            section_path=section_path,
            signal_phrases=signal_phrases,
            penalty_phrases=penalty_phrases,
        ))

    candidates.sort(key=lambda c: (-c.composite_score, c.page_number))
    return candidates[:max_results]


# ---------------------------------------------------------------------------
# Claude constrained selection
# ---------------------------------------------------------------------------

def _select_with_claude(
    proposition_name: str,
    proposition_type: str,
    candidates: list[Candidate],
    anthropic_client,
) -> tuple[Optional[Candidate], Optional[str]]:
    """
    Ask Claude to pick the best candidate passage.

    Claude MUST select by index from the supplied candidates or return
    no_support_found.  It CANNOT invent quote text or page numbers.
    The returned quote is validated against the candidate window before
    being accepted.

    Returns (selected_candidate, trimmed_quote) or (None, None).
    """
    if not candidates:
        return None, None

    candidate_block = "\n\n".join(
        f"[{i + 1}] Page {c.page_number} (doc: {c.source_document_id}):\n{c.text_window}"
        for i, c in enumerate(candidates)
    )

    prompt = f"""You are helping validate source passages for a competition law research database.

Proposition ({proposition_type}): {proposition_name}

Below are candidate passages extracted verbatim from the source PDF. Each is labelled with a number and page number.

{candidate_block}

Task:
1. Identify which candidate best supports the proposition above.
2. If a candidate supports it, respond EXACTLY as:
   SELECTED: <number>
   QUOTE: <exact trimmed text from that candidate — copy words verbatim, only trim>

3. If no candidate supports the proposition, respond EXACTLY as:
   no_support_found

Rules:
- Do NOT rewrite or paraphrase the quote. Copy exact words from the candidate text.
- Do NOT invent page numbers. Use the page number shown for the selected candidate.
- Do NOT select a candidate that does not clearly and directly support the proposition.
- If in doubt, return no_support_found rather than a weak or uncertain match.
"""

    message = anthropic_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )
    response_text = message.content[0].text.strip()

    if response_text.strip().lower() == "no_support_found":
        return None, None

    sel_match = re.search(r"SELECTED:\s*(\d+)", response_text, re.IGNORECASE)
    quote_match = re.search(r"QUOTE:\s*(.+)", response_text, re.IGNORECASE | re.DOTALL)

    if not sel_match:
        return None, None

    idx = int(sel_match.group(1)) - 1
    if not (0 <= idx < len(candidates)):
        return None, None

    selected = candidates[idx]
    raw_quote = quote_match.group(1).strip() if quote_match else ""

    # Hard validation: quote must be present in the candidate window
    if not raw_quote or not quote_found_in_text(raw_quote, selected.text_window):
        return None, None

    # Recover the best real substring from the candidate window
    norm_quote = _normalise(raw_quote)
    norm_window = _normalise(selected.text_window)
    pos = norm_window.find(norm_quote)
    if pos < 0:
        # Fragment match path — use Claude's quote directly (it passed validation)
        validated_quote = raw_quote
    else:
        char_ratio = len(selected.text_window) / max(len(norm_window), 1)
        real_start = int(pos * char_ratio)
        real_end = int((pos + len(norm_quote)) * char_ratio)
        validated_quote = selected.text_window[real_start:real_end].strip()
        if len(validated_quote) < 20:
            validated_quote = raw_quote

    return selected, validated_quote


# ---------------------------------------------------------------------------
# Passage validation
# ---------------------------------------------------------------------------

def _validate_passages(
    passages: list[dict],
    doc_map: dict[str, dict],
    page_cache_map: dict[str, Optional[dict]],
) -> list[PassageValidationResult]:
    results: list[PassageValidationResult] = []
    for passage in passages:
        pid = passage.get("passage_id", "?")
        doc_id = passage.get("source_document_id", "")
        quote = (passage.get("quote_snippet") or "").strip()
        page_str = passage.get("page")

        listed_page: Optional[int] = None
        if page_str is not None:
            try:
                listed_page = int(page_str)
            except (TypeError, ValueError):
                pass

        if doc_id not in doc_map:
            results.append(PassageValidationResult(
                passage_id=pid, source_document_id=doc_id,
                listed_page=listed_page, status="no_cache",
                found_on_page=None, original_quote=quote,
                message=f"source_document_id '{doc_id}' not in record — skip",
            ))
            continue

        page_cache = page_cache_map.get(doc_id)
        if page_cache is None:
            results.append(PassageValidationResult(
                passage_id=pid, source_document_id=doc_id,
                listed_page=listed_page, status="no_cache",
                found_on_page=None, original_quote=quote,
                message="No page cache available — run with --build-cache to fetch",
            ))
            continue

        if not quote:
            results.append(PassageValidationResult(
                passage_id=pid, source_document_id=doc_id,
                listed_page=listed_page, status="not_found",
                found_on_page=None, original_quote=quote,
                message="quote_snippet is empty",
            ))
            continue

        # Check on listed page first
        if listed_page is not None:
            page_text = get_page_text(page_cache, listed_page)
            if page_text is not None and quote_found_in_text(quote, page_text):
                results.append(PassageValidationResult(
                    passage_id=pid, source_document_id=doc_id,
                    listed_page=listed_page, status="ok",
                    found_on_page=listed_page, original_quote=quote,
                    message=f"Quote found on listed page {listed_page}",
                ))
                continue

        # Search all pages
        found_page: Optional[int] = None
        for pnum, ptext in iter_pages(page_cache):
            if quote_found_in_text(quote, ptext):
                found_page = pnum
                break

        if found_page is not None and found_page != listed_page:
            results.append(PassageValidationResult(
                passage_id=pid, source_document_id=doc_id,
                listed_page=listed_page, status="wrong_page",
                found_on_page=found_page, original_quote=quote,
                message=(
                    f"Quote found on page {found_page}, not on listed page {listed_page}"
                    if listed_page is not None
                    else f"Quote found on page {found_page} (no page listed)"
                ),
                repaired_page=found_page,
            ))
        elif found_page is not None:
            results.append(PassageValidationResult(
                passage_id=pid, source_document_id=doc_id,
                listed_page=listed_page, status="ok",
                found_on_page=found_page, original_quote=quote,
                message=f"Quote found on page {found_page}",
            ))
        else:
            results.append(PassageValidationResult(
                passage_id=pid, source_document_id=doc_id,
                listed_page=listed_page, status="not_found",
                found_on_page=None, original_quote=quote,
                message="Quote not found on any page — possible hallucination",
            ))

    return results


# ---------------------------------------------------------------------------
# Proposition support scan
# ---------------------------------------------------------------------------

def _find_unsupported(
    record: dict,
    passage_results: Optional[list[PassageValidationResult]] = None,
) -> dict[str, list[dict]]:
    """
    Return propositions that lack *valid* grounded passages.

    A passage with status "ok" or "wrong_page" counts as valid support.
    A passage with status "not_found" does NOT count — its quote is
    unverifiable and is treated as hallucinated.

    Each returned proposition dict has an extra "_invalidated" key listing
    passage IDs that were previously linked but are now invalidated.
    """
    # Determine which passage IDs are validly grounded
    valid_ids: set[str] = set()
    invalid_ids: set[str] = set()
    if passage_results:
        for pvr in passage_results:
            if pvr.status in ("ok", "wrong_page"):
                valid_ids.add(pvr.passage_id)
            elif pvr.status == "not_found":
                invalid_ids.add(pvr.passage_id)

    # Build support maps from valid passages only
    supported_markets: set[str] = set()
    supported_geo: set[str] = set()
    supported_theories: set[str] = set()

    # Also track which propositions had passages that are now invalidated
    invalidated_by_market: dict[str, list[str]] = {}
    invalidated_by_geo: dict[str, list[str]] = {}
    invalidated_by_theory: dict[str, list[str]] = {}

    for p in (record.get("source_passages") or []):
        pid = p.get("passage_id", "")
        if pid in valid_ids:
            supported_markets.update(p.get("supports_markets") or [])
            supported_geo.update(p.get("supports_geographic_markets") or [])
            supported_theories.update(p.get("supports_theories") or [])
        if pid in invalid_ids:
            for m in (p.get("supports_markets") or []):
                invalidated_by_market.setdefault(m, []).append(pid)
            for g in (p.get("supports_geographic_markets") or []):
                invalidated_by_geo.setdefault(g, []).append(pid)
            for t in (p.get("supports_theories") or []):
                invalidated_by_theory.setdefault(t, []).append(pid)

    return {
        "product_market": [
            {**m, "_invalidated": invalidated_by_market.get(m.get("market_id", ""), [])}
            for m in (record.get("product_markets_considered") or [])
            if m.get("market_id") not in supported_markets
        ],
        "geographic_market": [
            {**g, "_invalidated": invalidated_by_geo.get(g.get("market_id", ""), [])}
            for g in (record.get("geographic_markets_considered") or [])
            if g.get("market_id") not in supported_geo
        ],
        "theory_of_harm": [
            {**t, "_invalidated": invalidated_by_theory.get(t.get("theory_id", ""), [])}
            for t in (record.get("theories_of_harm") or [])
            if t.get("theory_id") not in supported_theories
        ],
    }


def _check_mislabelled_propositions(results: list[PropositionSearchResult]) -> None:
    """
    Set warning="possible_mislabelled_proposition" on results where the
    top candidates all come from sections that don't match the proposition topic.

    Modifies the list in place.
    """
    for pr in results:
        if pr.status != "candidates_found" or len(pr.candidates) < 2:
            continue
        top = pr.candidates[:3]
        mismatch = sum(1 for c in top if c.support_type == "likely_wrong_section")
        if mismatch == len(top):
            pr.warning = "possible_mislabelled_proposition"


def _search_propositions(
    unsupported: dict[str, list[dict]],
    page_cache_map: dict[str, Optional[dict]],
    record: dict,
) -> list[PropositionSearchResult]:
    """Search PDF pages for candidates for each proposition lacking valid support."""
    all_caches = [c for c in page_cache_map.values() if c is not None]

    # Pre-build section maps once per cache (expensive but done once)
    section_maps: dict[str, dict[int, str]] = {
        cache["source_document_id"]: _extract_section_map(cache)
        for cache in all_caches
        if cache.get("source_document_id")
    }

    results: list[PropositionSearchResult] = []

    for ptype, props in unsupported.items():
        for prop in props:
            pid = prop.get("market_id") or prop.get("theory_id", "?")
            name = prop.get("name", "")
            invalidated = prop.get("_invalidated", [])
            keywords = _proposition_keywords(prop, record)
            prop_topic_words = _topic_words(name)

            candidates: list[Candidate] = []
            for cache in all_caches:
                doc_id = cache.get("source_document_id", "")
                smap = section_maps.get(doc_id)
                candidates.extend(_find_candidates(
                    keywords, cache,
                    proposition_type=ptype,
                    prop_topic_words=prop_topic_words,
                    section_map=smap,
                    prop_name=name,
                ))
            # Sort by composite score descending, then by page ascending for ties
            candidates.sort(key=lambda c: (-c.composite_score, c.page_number))
            candidates = candidates[:_MAX_CANDIDATES]

            status = "candidates_found" if candidates else "no_candidates"
            results.append(PropositionSearchResult(
                proposition_id=pid, proposition_type=ptype,
                proposition_name=name, status=status,
                invalidated_passage_ids=invalidated,
                candidates=candidates,
            ))

    _check_mislabelled_propositions(results)
    return results


# ---------------------------------------------------------------------------
# Per-case repair
# ---------------------------------------------------------------------------

def repair_case(
    yaml_path: Path,
    *,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    build_cache: bool = False,
    use_claude: bool = False,
    dry_run: bool = True,
    timeout: int = 60,
) -> RepairReport:
    with open(yaml_path) as f:
        record: dict = yaml.safe_load(f)

    case_id = record.get("case_id", yaml_path.stem)
    report = RepairReport(case_id=case_id, case_yaml_path=yaml_path)

    source_docs: list[dict] = record.get("source_documents") or []
    passages: list[dict] = record.get("source_passages") or []

    doc_map = {d["doc_id"]: d for d in source_docs if d.get("doc_id")}

    # Build / load page caches
    page_cache_map: dict[str, Optional[dict]] = {}
    with httpx.Client(follow_redirects=True, timeout=timeout) as client:
        for doc in source_docs:
            doc_id = doc.get("doc_id", "")
            pdf_url = doc.get("pdf_url")
            if not doc_id:
                continue
            if pdf_url and build_cache:
                try:
                    cache = fetch_and_extract(
                        doc_id, pdf_url,
                        cache_dir=cache_dir, timeout=timeout, client=client,
                    )
                    page_cache_map[doc_id] = cache
                    print(f"  [cache] Built cache for {doc_id} ({cache['page_count']} pages)")
                except Exception as exc:
                    print(f"  [cache] Failed to build cache for {doc_id}: {exc}")
                    page_cache_map[doc_id] = None
            else:
                page_cache_map[doc_id] = load_cache(doc_id, cache_dir)

    # Step 1: validate existing passages
    report.passage_results = _validate_passages(passages, doc_map, page_cache_map)

    # Step 2: find propositions lacking valid grounded support
    unsupported = _find_unsupported(record, report.passage_results)

    # Step 3: mark propositions that have valid support
    all_unsupported_ids: set[str] = set()
    for props in unsupported.values():
        for p in props:
            all_unsupported_ids.add(p.get("market_id") or p.get("theory_id", ""))

    for ptype, key in (
        ("product_market", "product_markets_considered"),
        ("geographic_market", "geographic_markets_considered"),
        ("theory_of_harm", "theories_of_harm"),
    ):
        pid_field = "market_id" if "market" in ptype else "theory_id"
        for prop in (record.get(key) or []):
            pid = prop.get(pid_field, "?")
            if pid not in all_unsupported_ids:
                report.proposition_results.append(PropositionSearchResult(
                    proposition_id=pid, proposition_type=ptype,
                    proposition_name=prop.get("name", ""),
                    status="valid_support",
                ))

    # Step 4: search for candidates for unsupported propositions
    prop_results = _search_propositions(unsupported, page_cache_map, record)
    report.proposition_results.extend(prop_results)

    # Step 5: Claude candidate selection (optional)
    if use_claude and prop_results:
        try:
            import anthropic
            ac = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        except (ImportError, KeyError):
            print("  [claude] anthropic package or ANTHROPIC_API_KEY not available — skipping")
            ac = None

        if ac:
            for pr in report.proposition_results:
                if pr.status != "candidates_found" or not pr.candidates:
                    continue
                print(f"  [claude] Selecting for {pr.proposition_id} "
                      f"({pr.proposition_name[:50]})")
                cand, quote = _select_with_claude(
                    pr.proposition_name, pr.proposition_type, pr.candidates, ac
                )
                if cand and quote:
                    pr.selected_candidate = cand
                    pr.selected_quote = quote
                    pr.selected_page = cand.page_number
                    print(f"           → page {cand.page_number}: {quote[:80]!r}…")
                else:
                    print(f"           → no support found")

    # Step 6: write-back (only in write mode)
    if not dry_run:
        _write_yaml(yaml_path, record, report, passages, page_cache_map)

    return report


# ---------------------------------------------------------------------------
# YAML write-back
# ---------------------------------------------------------------------------

def _build_new_passage_id(existing_passages: list[dict]) -> str:
    existing_ids = {p.get("passage_id", "") for p in existing_passages}
    n = len(existing_passages) + 1
    while f"sp_{n}" in existing_ids:
        n += 1
    return f"sp_{n}"


def _write_yaml(
    yaml_path: Path,
    record: dict,
    report: RepairReport,
    original_passages: list[dict],
    page_cache_map: Optional[dict[str, Optional[dict]]] = None,
) -> None:
    """Apply validated repairs and write YAML back to disk."""
    new_passages = copy.deepcopy(original_passages)
    today = date.today().isoformat()

    # Correct page numbers for wrong_page passages
    for pvr in report.passage_results:
        if pvr.status == "wrong_page" and pvr.repaired_page is not None:
            for p in new_passages:
                if p.get("passage_id") == pvr.passage_id:
                    old_page = p.get("page")
                    p["page"] = str(pvr.repaired_page)
                    p["review_status"] = "unreviewed"
                    p["last_checked_date"] = today
                    print(f"  [write] {pvr.passage_id}: page {old_page} → {pvr.repaired_page}")
                    break

    # Add passages for propositions where Claude found a validated candidate
    for pr in report.proposition_results:
        if pr.status != "candidates_found":
            continue
        if pr.selected_candidate is None or not pr.selected_quote:
            continue

        doc_id = _doc_id_for_page(
            pr.selected_candidate.page_number, page_cache_map or {}
        )
        if not doc_id:
            continue

        new_pid = _build_new_passage_id(new_passages)
        prop_id = pr.proposition_id
        supports_key: dict = {}
        if pr.proposition_type == "product_market":
            supports_key = {"supports_markets": [prop_id]}
        elif pr.proposition_type == "geographic_market":
            supports_key = {"supports_geographic_markets": [prop_id]}
        elif pr.proposition_type == "theory_of_harm":
            supports_key = {"supports_theories": [prop_id]}

        entry = {
            "passage_id": new_pid,
            "source_document_id": doc_id,
            "page": str(pr.selected_page),
            "quote_snippet": pr.selected_quote,
            "extraction_method": "pdf_extracted",
            "review_status": "unreviewed",
            "confidence_score": 0.70,
            "last_checked_date": today,
            **supports_key,
        }
        new_passages.append(entry)
        print(f"  [write] Added {new_pid} for {prop_id} (page {pr.selected_page})")

    record["source_passages"] = new_passages

    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.dump(record, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    print(f"  [write] Wrote {yaml_path}")


def _doc_id_for_page(
    page_number: int,
    page_cache_map: dict[str, Optional[dict]],
) -> Optional[str]:
    for doc_id, cache in page_cache_map.items():
        if cache is None:
            continue
        for p in cache.get("pages", []):
            if p.get("page_number") == page_number:
                return doc_id
    return None


# ---------------------------------------------------------------------------
# Report printing
# ---------------------------------------------------------------------------

def print_report(report: RepairReport, verbose: bool = False) -> None:
    print(f"\n{'─' * 60}")
    print(f"Case: {report.case_id}")
    print(f"File: {report.case_yaml_path}")
    print()

    # Existing passage validation
    print(f"Existing passages ({len(report.passage_results)}):")
    for pvr in report.passage_results:
        page_info = f" [listed page {pvr.listed_page}]" if pvr.listed_page else ""
        if pvr.status == "ok":
            marker = "  ✓ OK"
        elif pvr.status == "wrong_page":
            marker = f"  ⚠ WRONG PAGE → {pvr.found_on_page}"
        elif pvr.status == "not_found":
            marker = "  ✗ NOT FOUND (hallucinated?)"
        else:
            marker = "  · no cache"
        print(f"  {marker}  {pvr.passage_id}{page_info}: {pvr.message}")
        if pvr.status == "not_found" and pvr.original_quote:
            quote_preview = pvr.original_quote[:120].replace("\n", " ")
            print(f"             original quote: {quote_preview!r}…")

    print(f"\n  ok={report.existing_passages_ok}  "
          f"wrong_page={report.existing_passages_wrong_page}  "
          f"not_found={report.existing_passages_not_found}  "
          f"no_cache={report.existing_passages_no_cache}")

    # Proposition support results
    total = report.propositions_total
    print(f"\nPropositions ({total} total  |  "
          f"valid_support={report.propositions_with_valid_support}  "
          f"candidates_found={report.propositions_with_candidates}  "
          f"no_candidates={report.propositions_without_candidates}):")

    for pr in report.proposition_results:
        if pr.status == "valid_support":
            if verbose:
                print(f"  ✓ {pr.proposition_id} ({pr.proposition_type}): "
                      f"{pr.proposition_name[:60]} — valid support")
            continue

        invalidated_note = ""
        if pr.invalidated_passage_ids:
            invalidated_note = f" [invalidated: {', '.join(pr.invalidated_passage_ids)}]"

        if pr.status == "no_candidates":
            print(f"\n  ✗ {pr.proposition_id} ({pr.proposition_type}){invalidated_note}")
            print(f"    {pr.proposition_name[:70]}")
            print(f"    → no candidate passages found in PDF")
        elif pr.status == "candidates_found":
            warn_tag = f"  ⚠ WARNING: {pr.warning}" if pr.warning else ""
            print(f"\n  ~ {pr.proposition_id} ({pr.proposition_type}){invalidated_note}{warn_tag}")
            print(f"    {pr.proposition_name[:70]}")
            if pr.selected_quote:
                print(f"    → SELECTED page {pr.selected_page}: {pr.selected_quote[:100]!r}…")
            else:
                print(f"    → {len(pr.candidates)} candidate(s) found (review before write):")
                for i, c in enumerate(pr.candidates[:3]):
                    print(c.display(i + 1))

    print(f"\n  candidate_passages_total={report.candidate_passages_total}")


# ---------------------------------------------------------------------------
# JSON report serialisation
# ---------------------------------------------------------------------------

def _candidate_to_dict(c: Candidate) -> dict:
    return {
        "source_document_id": c.source_document_id,
        "page_number": c.page_number,
        "section_path": c.section_path,
        "composite_score": c.composite_score,
        "keyword_score": c.keyword_score,
        "type_bonus": c.type_bonus,
        "penalty_score": c.penalty_score,
        "topic_bonus": c.topic_bonus,
        "topic_penalty": c.topic_penalty,
        "support_type": c.support_type,
        "confidence": c.confidence,
        "reason": c.reason,
        "signal_phrases": c.signal_phrases,
        "penalty_phrases": c.penalty_phrases,
        "matched_terms": c.match_terms,
        "snippet": c.text_window,   # full window for human review
    }


def serialize_reports(
    reports: list[RepairReport],
    mode: str = "dry-run",
) -> dict:
    """Return a JSON-serialisable dict covering all case reports."""
    cases = []
    for rpt in reports:
        invalid_passages = [
            {
                "passage_id": pvr.passage_id,
                "source_document_id": pvr.source_document_id,
                "listed_page": pvr.listed_page,
                "status": pvr.status,
                "original_quote": pvr.original_quote,
                "message": pvr.message,
            }
            for pvr in rpt.passage_results
            if pvr.status == "not_found"
        ]
        wrong_page_passages = [
            {
                "passage_id": pvr.passage_id,
                "source_document_id": pvr.source_document_id,
                "listed_page": pvr.listed_page,
                "correct_page": pvr.repaired_page,
                "message": pvr.message,
            }
            for pvr in rpt.passage_results
            if pvr.status == "wrong_page"
        ]
        propositions = []
        for pr in rpt.proposition_results:
            entry: dict = {
                "proposition_id": pr.proposition_id,
                "proposition_type": pr.proposition_type,
                "proposition_name": pr.proposition_name,
                "status": pr.status,
                "invalidated_passage_ids": pr.invalidated_passage_ids,
                "warning": pr.warning,
            }
            if pr.status in ("candidates_found", "no_candidates"):
                entry["candidates"] = [
                    {"rank": i + 1, **_candidate_to_dict(c)}
                    for i, c in enumerate(pr.candidates)
                ]
                if pr.selected_quote:
                    entry["selected_page"] = pr.selected_page
                    entry["selected_quote"] = pr.selected_quote
                recommended = (
                    "write_with_claude_selected" if pr.selected_quote
                    else "review_candidates" if pr.candidates
                    else "source_not_found_in_pdf"
                )
                entry["recommended_action"] = recommended
            else:
                entry["recommended_action"] = "none_needed"
            propositions.append(entry)

        cases.append({
            "case_id": rpt.case_id,
            "yaml_path": str(rpt.case_yaml_path),
            "summary": {
                "existing_passages_ok": rpt.existing_passages_ok,
                "existing_passages_wrong_page": rpt.existing_passages_wrong_page,
                "existing_passages_not_found": rpt.existing_passages_not_found,
                "existing_passages_no_cache": rpt.existing_passages_no_cache,
                "propositions_total": rpt.propositions_total,
                "propositions_with_valid_support": rpt.propositions_with_valid_support,
                "propositions_with_candidates": rpt.propositions_with_candidates,
                "propositions_without_candidates": rpt.propositions_without_candidates,
                "candidate_passages_total": rpt.candidate_passages_total,
            },
            "invalid_passages": invalid_passages,
            "wrong_page_passages": wrong_page_passages,
            "propositions": propositions,
        })

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tool": "repair_source_passages",
        "mode": mode,
        "cases": cases,
        "overall_summary": {
            "cases_processed": len(reports),
            "existing_passages_ok": sum(r.existing_passages_ok for r in reports),
            "existing_passages_wrong_page": sum(r.existing_passages_wrong_page for r in reports),
            "existing_passages_not_found": sum(r.existing_passages_not_found for r in reports),
            "existing_passages_no_cache": sum(r.existing_passages_no_cache for r in reports),
            "propositions_total": sum(r.propositions_total for r in reports),
            "propositions_with_valid_support": sum(r.propositions_with_valid_support for r in reports),
            "propositions_with_candidates": sum(r.propositions_with_candidates for r in reports),
            "propositions_without_candidates": sum(r.propositions_without_candidates for r in reports),
            "candidate_passages_total": sum(r.candidate_passages_total for r in reports),
        },
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate and repair CompMap source_passages against PDF text"
    )
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--case-id", help="Repair a single case by case_id")
    source_group.add_argument("--all", action="store_true", help="Repair all cases")

    parser.add_argument(
        "--cases-dir", default=str(_CASES_DIR),
        help=f"Path to data/cases directory (default: {_CASES_DIR})",
    )
    parser.add_argument(
        "--cache-dir", default=str(DEFAULT_CACHE_DIR),
        help=f"Path to source_text cache directory (default: {DEFAULT_CACHE_DIR})",
    )
    parser.add_argument(
        "--report-json",
        metavar="PATH",
        help="Write a machine-readable JSON report to this path (dry-run safe)",
    )

    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--dry-run", dest="dry_run", action="store_true", default=True,
        help="Report only, do not modify YAML (default)",
    )
    mode_group.add_argument(
        "--write", dest="dry_run", action="store_false",
        help="Write validated repairs back to YAML",
    )

    parser.add_argument(
        "--build-cache", action="store_true",
        help="Download and cache PDF text (required on first run per document)",
    )
    parser.add_argument(
        "--use-claude", action="store_true",
        help="Call Claude API to select best candidate (requires ANTHROPIC_API_KEY)",
    )
    parser.add_argument(
        "--timeout", type=int, default=60,
        help="HTTP timeout for PDF downloads in seconds (default: 60)",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    cases_dir = Path(args.cases_dir)
    cache_dir = Path(args.cache_dir)

    if args.all:
        yaml_files = sorted(cases_dir.rglob("*.yaml"))
    else:
        yaml_files = [
            p for p in cases_dir.rglob("*.yaml")
            if p.stem == args.case_id
            or (yaml.safe_load(p.read_text()) or {}).get("case_id") == args.case_id
        ]

    if not yaml_files:
        print(
            f"No matching YAML files found for "
            f"{'all cases' if args.all else args.case_id}",
            file=sys.stderr,
        )
        return 1

    mode_label = "DRY-RUN" if args.dry_run else "WRITE"
    print(f"CompMap Source Passage Repair [{mode_label}]")
    print(f"Cases: {len(yaml_files)}  |  Cache: {cache_dir}  |  "
          f"Build cache: {args.build_cache}  |  Claude: {args.use_claude}\n")

    all_reports: list[RepairReport] = []
    for yaml_path in yaml_files:
        print(f"Processing {yaml_path.name} …")
        try:
            rpt = repair_case(
                yaml_path,
                cache_dir=cache_dir,
                build_cache=args.build_cache,
                use_claude=args.use_claude,
                dry_run=args.dry_run,
                timeout=args.timeout,
            )
            all_reports.append(rpt)
            print_report(rpt, verbose=args.verbose)
        except Exception as exc:
            print(f"  [ERROR] Failed to process {yaml_path.name}: {exc}", file=sys.stderr)

    # Overall summary
    print(f"\n{'═' * 60}")
    print(f"Overall summary ({len(all_reports)} case(s)):")
    total_ok = sum(r.existing_passages_ok for r in all_reports)
    total_wrong = sum(r.existing_passages_wrong_page for r in all_reports)
    total_missing = sum(r.existing_passages_not_found for r in all_reports)
    total_no_cache = sum(r.existing_passages_no_cache for r in all_reports)
    total_valid_props = sum(r.propositions_with_valid_support for r in all_reports)
    total_candidate_props = sum(r.propositions_with_candidates for r in all_reports)
    total_no_support = sum(r.propositions_without_candidates for r in all_reports)
    total_candidates = sum(r.candidate_passages_total for r in all_reports)

    print(f"  Passages:            ok={total_ok}  "
          f"wrong_page={total_wrong}  "
          f"not_found={total_missing}  "
          f"no_cache={total_no_cache}")
    print(f"  Propositions:        valid_support={total_valid_props}  "
          f"with_candidates={total_candidate_props}  "
          f"no_candidates={total_no_support}")
    print(f"  Candidate passages:  total={total_candidates}")

    if args.dry_run and (total_wrong > 0 or total_missing > 0 or total_candidate_props > 0):
        print()
        if total_wrong > 0:
            print("  → Run --write to apply page-number corrections.")
        if total_candidate_props > 0:
            print("  → Review candidate snippets above, then run --use-claude --write "
                  "to fill unsupported propositions.")
        if args.report_json:
            pass  # handled below
        else:
            print("  → Run --report-json <path> for a machine-readable inspection report.")

    # JSON report
    if args.report_json:
        report_path = Path(args.report_json)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        payload = serialize_reports(all_reports, mode=mode_label)
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        print(f"\n  JSON report written to {report_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
