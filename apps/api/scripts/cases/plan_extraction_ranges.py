#!/usr/bin/env python3
"""
plan_extraction_ranges.py — plan targeted page-range windows for long-decision extraction.

Given a cached source text JSON and a focus mode, this script identifies candidate
page ranges for targeted extraction passes.  It outputs a human-readable plan with
suggested ingest_case.py commands — NO Claude calls, NO draft files written.

Usage:
    # By case-id (resolves source cache automatically):
    .venv/bin/python scripts/cases/plan_extraction_ranges.py \\
        --case-id eu_bayer_monsanto_2018 --focus theories

    # By direct cache path:
    .venv/bin/python scripts/cases/plan_extraction_ranges.py \\
        --source-cache ../../data/source_text/eu_bayer_monsanto_decision.json \\
        --focus remedies

    # Restrict to a subset of pages:
    .venv/bin/python scripts/cases/plan_extraction_ranges.py \\
        --case-id eu_bayer_monsanto_2018 --focus theories --page-range 400:560

    # Adjust window size (default 15 pages):
    .venv/bin/python scripts/cases/plan_extraction_ranges.py \\
        --case-id eu_bayer_monsanto_2018 --focus theories --window-size 12
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

_API_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_API_DIR))
sys.path.insert(0, str(Path(__file__).parent))

from app.shared.utils.pdf_extractor import DEFAULT_CACHE_DIR
from repair_source_passages import _extract_section_map

_CASES_DIR = Path(__file__).resolve().parents[4] / "data" / "cases"

# ---------------------------------------------------------------------------
# Per-focus priority terms — ordered from most to least specific
# ---------------------------------------------------------------------------

# HIGH-priority terms score 2; each increments priority_score by 2.
# LOW-priority terms score 1.

_HIGH_PRIORITY: dict[str, tuple[str, ...]] = {
    "theories": (
        "conclusion",
        "competitive assessment",
        "assessment of competitive effects",
        "innovation competition",
        "leading innovator",
        "pipeline competitor",
    ),
    "remedies": (
        "commitment",
        "divestment",
        "divestiture",
        "condition",
        "supply agreement",
        "remedy",
    ),
    "market_definition": (
        "market definition",
        "product market definition",
        "geographic market definition",
        "relevant market",
    ),
}

_LOW_PRIORITY: dict[str, tuple[str, ...]] = {
    "theories": (
        "horizontal",
        "vertical",
        "conglomerate",
        "foreclosure",
        "effects on competition",
        "competitive effect",
        "innovation",
        "r&d",
        "pipeline",
        "leading innovators",
        "research and development",
        "harm",
        "theory",
    ),
    "remedies": (
        "behavioural",
        "structural",
        "access",
        "obligation",
        "phase",
    ),
    "market_definition": (
        "product market",
        "geographic market",
        "market definition",
        "segmentation",
        "market delineation",
    ),
}

# Generic heading words that indicate framework/structural sections rather than unit labels.
# unit_assessment planner excludes top-level sections whose stripped title matches any of these.
_UNIT_SECTION_EXCLUSIONS = frozenset({
    "introduction", "background", "summary", "overview", "conclusion",
    "conclusions", "annex", "appendix", "recitals", "procedure", "scope",
    "general", "framework", "assessment", "methodology", "legal",
    "market", "markets", "competition", "competitive", "parties",
    "notification", "notifying", "transaction", "concentration",
    "jurisdiction", "applicable", "decision", "outline",
})

# Default window size (pages per suggested range)
_DEFAULT_WINDOW = 15

# How many pages of context to add around hot pages before grouping
_CONTEXT_PAGES = 1

# Merge clusters that are within this many pages of each other
_MERGE_GAP = 4


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class PageScore:
    page_number: int
    section_path: str
    score: int                        # 0 = not hot; >0 = relevant
    matched_terms: list[str] = field(default_factory=list)


@dataclass
class ProbeWindow:
    start_page: int
    end_page: int
    focus: str
    headings: list[tuple[int, str]] = field(default_factory=list)   # (page_num, heading)
    total_score: int = 0
    context_suffix: str = ""   # short label for --output-suffix

    @property
    def page_count(self) -> int:
        return self.end_page - self.start_page + 1

    def command(self, case_id: str, suffix_index: int) -> str:
        suffix = f"{self.focus}_{self.context_suffix or f'range{suffix_index}'}"
        return (
            f"apps/api/.venv/bin/python apps/api/scripts/cases/ingest_case.py"
            f" --case-id {case_id}"
            f" --focus {self.focus}"
            f" --page-range {self.start_page}:{self.end_page}"
            f" --output-suffix {suffix}"
            f" --batch-by-section"
            f" --max-cost 2.00"
        )


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------


def _score_page(section_path: str, focus: str) -> tuple[int, list[str]]:
    """Return (score, matched_terms) for a single page's section_path.

    Score is based on the LEAF heading only (the last component of the path).
    This prevents pages that merely inherit a parent "competitive assessment" heading
    from being scored — only pages whose own heading matches are counted.
    Leaf scoring avoids the vegetable-crop noise problem where hundreds of crop
    sub-sections inherit "competitive assessment" from their parent path.
    """
    if not section_path:
        return 0, []

    leaf = section_path.split(" > ")[-1].lower()
    score = 0
    matched: list[str] = []

    for term in _HIGH_PRIORITY.get(focus, ()):
        if term in leaf:
            score += 2
            matched.append(term)

    for term in _LOW_PRIORITY.get(focus, ()):
        if term in leaf and term not in matched:
            score += 1
            matched.append(term)

    return score, matched


# ---------------------------------------------------------------------------
# Window building
# ---------------------------------------------------------------------------


def _is_unit_label(heading_text: str) -> bool:
    """
    Return True if a top-level heading text looks like a repeated-unit label
    (e.g. a crop name, route, country, indication) rather than a structural heading.

    Heuristics:
    - Strip leading section number to get the label.
    - Label must be 1–4 words.
    - No word in the label may appear in _UNIT_SECTION_EXCLUSIONS.
    """
    # Strip leading section number (e.g. "8 " or "8.1 ")
    label = re.sub(r"^\d+(?:\.\d+)*\s*", "", heading_text).strip()
    if not label:
        return False
    words = label.lower().split()
    if not (1 <= len(words) <= 4):
        return False
    return not any(w in _UNIT_SECTION_EXCLUSIONS for w in words)


def _build_unit_assessment_windows(
    section_map: dict[int, str],
    page_range: Optional[tuple[int, int]] = None,
    window_size: int = _DEFAULT_WINDOW,
) -> list[ProbeWindow]:
    """
    Build ProbeWindows for the unit_assessment focus.

    Instead of keyword scoring, detects pages that belong to a repeated
    unit structure (crops, routes, countries, indications, …) by grouping
    consecutive pages that share the same top-level section heading and
    whose heading label looks like a unit name rather than a generic section.

    Each qualifying group becomes one ProbeWindow.  Large groups are split
    at natural sub-section boundaries (same logic as keyword-based planner).
    """
    all_pages = sorted(section_map.keys())
    if page_range:
        lo, hi = page_range
        all_pages = [p for p in all_pages if lo <= p <= hi]

    if not all_pages:
        return []

    # Group pages by their top-level section heading
    groups: list[tuple[str, list[int]]] = []   # (top_heading, pages)
    current_top = ""
    current_group: list[int] = []

    for pn in all_pages:
        sp = section_map.get(pn, "")
        top = sp.split(" > ")[0] if sp else ""
        if top != current_top:
            if current_group and _is_unit_label(current_top):
                groups.append((current_top, current_group))
            current_top = top
            current_group = [pn]
        else:
            current_group.append(pn)
    if current_group and _is_unit_label(current_top):
        groups.append((current_top, current_group))

    # Build ProbeWindows — split large groups
    windows: list[ProbeWindow] = []
    for top_heading, pages in groups:
        label = re.sub(r"^\d+(?:\.\d+)*\s*", "", top_heading).strip()
        safe_label = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")[:30]

        if len(pages) <= window_size:
            chunks = [pages]
        else:
            split_points = _find_split_points(pages, section_map, window_size)
            chunks = []
            prev = 0
            for sp_idx in split_points:
                chunks.append(pages[prev:sp_idx])
                prev = sp_idx
            chunks.append(pages[prev:])

        for chunk_idx, chunk in enumerate(chunks):
            if not chunk:
                continue
            start, end = min(chunk), max(chunk)
            suffix = f"{safe_label}_{start}" if chunk_idx == 0 else f"{safe_label}_{start}_p{chunk_idx + 1}"
            # Collect unique sub-headings within the chunk
            seen_leaves: set[str] = set()
            headings: list[tuple[int, str]] = []
            for pn in chunk:
                sp = section_map.get(pn, "")
                if sp:
                    leaf = sp.split(" > ")[-1]
                    if leaf not in seen_leaves:
                        seen_leaves.add(leaf)
                        headings.append((pn, leaf))
            windows.append(ProbeWindow(
                start_page=start,
                end_page=end,
                focus="unit_assessment",
                headings=headings[:5],
                total_score=len(chunk),   # score = page count (all pages are relevant)
                context_suffix=suffix,
            ))

    return windows


def _build_windows(
    section_map: dict[int, str],
    focus: str,
    page_range: Optional[tuple[int, int]] = None,
    window_size: int = _DEFAULT_WINDOW,
    context_pages: int = _CONTEXT_PAGES,
    merge_gap: int = _MERGE_GAP,
) -> list[ProbeWindow]:
    """
    Identify and return candidate ProbeWindow objects for the given focus.

    Algorithm:
    1. Score each page via section_path keyword matching.
    2. Collect "hot" pages (score > 0) and expand with ±context_pages.
    3. Group consecutive/nearby expanded pages into contiguous clusters.
    4. Split clusters larger than window_size at section boundaries.
    5. Return ProbeWindow objects with headings and suggested command.
    """
    all_pages = sorted(section_map.keys())

    if page_range:
        lo, hi = page_range
        all_pages = [p for p in all_pages if lo <= p <= hi]

    # Score every page
    page_scores: dict[int, PageScore] = {}
    for pn in all_pages:
        sp = section_map.get(pn, "")
        score, matched = _score_page(sp, focus)
        page_scores[pn] = PageScore(
            page_number=pn,
            section_path=sp,
            score=score,
            matched_terms=matched,
        )

    # Hot pages: score > 0
    hot_set: set[int] = {ps.page_number for ps in page_scores.values() if ps.score > 0}

    if not hot_set:
        return []

    # Expand with context
    expanded: set[int] = set()
    for p in hot_set:
        for offset in range(-context_pages, context_pages + 1):
            neighbour = p + offset
            if neighbour in page_scores:
                expanded.add(neighbour)

    sorted_exp = sorted(expanded)

    # Group into contiguous clusters (merge pages within merge_gap of each other)
    clusters: list[list[int]] = []
    current: list[int] = [sorted_exp[0]]
    for p in sorted_exp[1:]:
        if p - current[-1] <= merge_gap:
            current.append(p)
        else:
            clusters.append(current)
            current = [p]
    clusters.append(current)

    # Fill gaps within each cluster (so the range is solid)
    filled_clusters: list[list[int]] = []
    for cluster in clusters:
        if len(cluster) < 2:
            filled_clusters.append(cluster)
            continue
        full_range = list(range(cluster[0], cluster[-1] + 1))
        filled_clusters.append(full_range)

    # Split large clusters at section-boundary pages; drop pure-context windows
    windows: list[ProbeWindow] = []
    for cluster in filled_clusters:
        if len(cluster) <= window_size:
            w = _make_window(cluster, page_scores, section_map, focus)
            if w.total_score > 0:
                windows.append(w)
        else:
            split_points = _find_split_points(cluster, section_map, window_size)
            start = 0
            for split in split_points:
                chunk = cluster[start:split]
                if chunk:
                    w = _make_window(chunk, page_scores, section_map, focus)
                    if w.total_score > 0:
                        windows.append(w)
                start = split
            remaining = cluster[start:]
            if remaining:
                w = _make_window(remaining, page_scores, section_map, focus)
                if w.total_score > 0:
                    windows.append(w)

    return windows


def _make_window(
    pages: list[int],
    page_scores: dict[int, PageScore],
    section_map: dict[int, str],
    focus: str,
) -> ProbeWindow:
    """Build a ProbeWindow from a list of page numbers."""
    total_score = sum(page_scores[p].score for p in pages if p in page_scores)

    # Collect unique headings from hot pages, ordered by page
    seen_sections: set[str] = set()
    headings: list[tuple[int, str]] = []
    for p in pages:
        ps = page_scores.get(p)
        if ps and ps.score > 0 and ps.section_path:
            leaf = ps.section_path.split(" > ")[-1]
            if leaf not in seen_sections:
                seen_sections.add(leaf)
                headings.append((p, leaf))

    # Context suffix: derive from the most prominent heading
    suffix = ""
    if headings:
        best_heading = max(headings, key=lambda h: page_scores.get(h[0], PageScore(0, "", 0)).score)
        raw = best_heading[1].lower()
        raw = re.sub(r"^\d+[\.\d]*\s*", "", raw)   # strip section number
        raw = re.sub(r"[^a-z0-9]+", "_", raw)       # non-alphanum → _
        suffix = raw[:30].strip("_")

    return ProbeWindow(
        start_page=min(pages),
        end_page=max(pages),
        focus=focus,
        headings=headings,
        total_score=total_score,
        context_suffix=suffix,
    )


def _find_split_points(
    cluster: list[int],
    section_map: dict[int, str],
    window_size: int,
) -> list[int]:
    """
    Return indices (into cluster) at which to split a large cluster.

    Prefers natural section boundaries; within each boundary-delimited segment,
    further splits by window_size if the segment is still too large.
    """
    if not cluster:
        return []

    # Find indices where the top-two-level section prefix changes
    boundary_indices: list[int] = []
    prev_prefix = _top_prefix(section_map.get(cluster[0], ""))
    for i in range(1, len(cluster)):
        cur_prefix = _top_prefix(section_map.get(cluster[i], ""))
        if cur_prefix != prev_prefix:
            boundary_indices.append(i)
        prev_prefix = cur_prefix

    # Segment boundaries: add start and end sentinels
    seg_bounds = [0] + boundary_indices + [len(cluster)]

    split_points: list[int] = []
    for seg_idx in range(len(seg_bounds) - 1):
        seg_start = seg_bounds[seg_idx]
        seg_end = seg_bounds[seg_idx + 1]
        seg_len = seg_end - seg_start
        if seg_len <= window_size:
            # Whole segment fits in one window; split at segment boundary
            # (except the first segment which starts at 0 — no split needed)
            if seg_start > 0:
                split_points.append(seg_start)
        else:
            # Segment too large: split at segment boundary then further by window_size
            if seg_start > 0:
                split_points.append(seg_start)
            pos = seg_start + window_size
            while pos < seg_end:
                split_points.append(pos)
                pos += window_size

    return sorted(set(split_points))


def _top_prefix(section_path: str) -> str:
    """Return the first two components of a section path (e.g. '5 Traits > 1.7 Competitive')."""
    parts = section_path.split(" > ")
    return " > ".join(parts[:2])


# ---------------------------------------------------------------------------
# Source cache resolution
# ---------------------------------------------------------------------------


def _resolve_cache_path(case_id: str) -> Optional[Path]:
    """Find the source cache JSON for a case by reading its YAML."""
    for yaml_path in _CASES_DIR.rglob(f"{case_id}.yaml"):
        if any(".draft" in part for part in yaml_path.parts):
            continue
        try:
            import yaml as _yaml
            with open(yaml_path) as f:
                case_data = _yaml.safe_load(f)
            for doc in case_data.get("source_documents", []):
                doc_id = doc.get("doc_id")
                if doc_id:
                    p = DEFAULT_CACHE_DIR / f"{doc_id}.json"
                    if p.exists():
                        return p
        except Exception:
            continue
    return None


def _load_source_cache(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Plan output
# ---------------------------------------------------------------------------


def format_plan(
    windows: list[ProbeWindow],
    case_id: str,
    focus: str,
    source_doc_id: str,
    total_doc_pages: int,
    page_range: Optional[tuple[int, int]] = None,
) -> str:
    lines: list[str] = []
    scope = (
        f"pp.{page_range[0]}–{page_range[1]}"
        if page_range
        else f"full document ({total_doc_pages} pp)"
    )
    lines.append(f"Extraction plan — case: {case_id}  focus: {focus}  scope: {scope}")
    lines.append(f"Source: {source_doc_id}")
    lines.append(f"Windows: {len(windows)}")
    lines.append("")

    if not windows:
        lines.append("  (no matching sections found for this focus mode)")
        return "\n".join(lines)

    for i, w in enumerate(windows, 1):
        lines.append(f"  Window {i}: pp.{w.start_page}–{w.end_page}  ({w.page_count} pages)  score={w.total_score}")
        if w.headings:
            for pn, heading in w.headings[:5]:   # cap at 5 headings per window
                lines.append(f"    • p.{pn}: {heading}")
            if len(w.headings) > 5:
                lines.append(f"    … +{len(w.headings) - 5} more headings")
        # Warn if this window is immediately adjacent to the next (no gap = possible split mid-section)
        if focus == "unit_assessment" and i < len(windows):
            next_w = windows[i]  # i is 1-based; windows[i] is the next window (0-based i)
            if next_w.start_page <= w.end_page + 1:
                lines.append(
                    f"    ⚠ WARNING: adjacent window boundary at p.{w.end_page}/{next_w.start_page} "
                    "may cross a section boundary — verify headings before extracting."
                )
        lines.append(f"    $ {w.command(case_id, i)}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def plan(
    source_cache: dict,
    focus: str,
    page_range: Optional[tuple[int, int]] = None,
    window_size: int = _DEFAULT_WINDOW,
) -> list[ProbeWindow]:
    """Core planning function — returns ProbeWindow list (no I/O)."""
    section_map = _extract_section_map(source_cache)
    if focus == "unit_assessment":
        return _build_unit_assessment_windows(
            section_map,
            page_range=page_range,
            window_size=window_size,
        )
    return _build_windows(
        section_map,
        focus=focus,
        page_range=page_range,
        window_size=window_size,
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Plan targeted page-range windows for long-decision extraction."
    )
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--case-id", help="Case ID to resolve source cache from canonical YAML")
    src.add_argument("--source-cache", help="Path to source cache JSON file")

    parser.add_argument(
        "--focus",
        required=True,
        choices=["theories", "remedies", "market_definition", "unit_assessment"],
        help="Extraction focus mode",
    )
    parser.add_argument(
        "--page-range",
        metavar="START:END",
        help="Restrict planning to a subset of pages (e.g. 400:560)",
    )
    parser.add_argument(
        "--window-size",
        type=int,
        default=_DEFAULT_WINDOW,
        metavar="N",
        help=f"Target pages per suggested window (default: {_DEFAULT_WINDOW})",
    )
    args = parser.parse_args(argv)

    # Resolve cache
    if args.source_cache:
        cache_path = Path(args.source_cache)
        case_id = cache_path.stem.replace("_decision", "").replace("_source", "")
    else:
        case_id = args.case_id
        cache_path = _resolve_cache_path(case_id)
        if cache_path is None:
            print(f"ERROR: no cached source found for '{case_id}'.", file=sys.stderr)
            print("       Run ingest_case.py first to populate the source cache.", file=sys.stderr)
            sys.exit(1)

    cache = _load_source_cache(cache_path)
    doc_id = cache.get("source_document_id", cache_path.stem)
    total_pages = cache.get("page_count", len(cache.get("pages", [])))

    # Parse page range
    page_range: Optional[tuple[int, int]] = None
    if args.page_range:
        parts = args.page_range.split(":")
        if len(parts) != 2 or not all(p.isdigit() for p in parts):
            print("ERROR: --page-range must be START:END integers.", file=sys.stderr)
            sys.exit(1)
        page_range = (int(parts[0]), int(parts[1]))

    windows = plan(cache, focus=args.focus, page_range=page_range, window_size=args.window_size)
    print(format_plan(windows, case_id, args.focus, doc_id, total_pages, page_range))


if __name__ == "__main__":
    main()
