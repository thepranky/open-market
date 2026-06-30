#!/usr/bin/env python3
"""Scrape DOJ Civil Merger case pages into CaseIndex-shaped records."""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlencode, urljoin

import httpx
import yaml

_API_DIR = Path(__file__).resolve().parents[3]
_REPO_ROOT = _API_DIR.parents[1]
_INDEX_DIR = _REPO_ROOT / "data" / "case_index" / "us"
_TEMP_OUTPUT_DIR = Path(tempfile.gettempdir()) / "meridian-us-doj-case-index"

sys.path.insert(0, str(_API_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from case_index_builder import CaseIndexParty  # noqa: E402
from us_discovery_contract import (  # noqa: E402
    UsScrapedCase,
    to_case_index_dict,
)

_BASE_URL = "https://www.justice.gov"
_LISTING_URL = f"{_BASE_URL}/atr/antitrust-case-filings"
_UA = (
    "Mozilla/5.0 (compatible; Meridian-research-bot/1.0; "
    "+https://www.justice.gov/)"
)
_HEADERS = {
    "User-Agent": _UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


@dataclass(frozen=True)
class DojListingCase:
    case_title: str
    case_page_url: str
    listing_open_date: str
    case_type: str
    industry_labels: tuple[str, ...]
    document_labels: tuple[str, ...]


@dataclass(frozen=True)
class DojDocumentFact:
    label: str
    date: str
    url: str | None = None


@dataclass(frozen=True)
class DojDecisionFacts:
    decision_date: str | None
    selected_label: str | None
    outcome_guess: str | None
    documents: tuple[DojDocumentFact, ...]


@dataclass
class _HtmlNode:
    tag: str
    attrs: dict[str, str]
    children: list["_HtmlNode | str"]


class _TreeParser(HTMLParser):
    _VOID_TAGS = {
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _HtmlNode("__root__", {}, [])
        self._stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = _HtmlNode(tag.lower(), {k: v or "" for k, v in attrs}, [])
        self._stack[-1].children.append(node)
        if node.tag not in self._VOID_TAGS:
            self._stack.append(node)

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self._stack[-1].children.append(
            _HtmlNode(tag.lower(), {k: v or "" for k, v in attrs}, [])
        )

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        for index in range(len(self._stack) - 1, 0, -1):
            if self._stack[index].tag == tag:
                del self._stack[index:]
                return

    def handle_data(self, data: str) -> None:
        if data:
            self._stack[-1].children.append(data)


def _parse_html(html: str) -> _HtmlNode:
    parser = _TreeParser()
    parser.feed(html)
    return parser.root


def _iter_nodes(node: _HtmlNode) -> "list[_HtmlNode]":
    found: list[_HtmlNode] = []
    for child in node.children:
        if isinstance(child, _HtmlNode):
            found.append(child)
            found.extend(_iter_nodes(child))
    return found


def _class_tokens(node: _HtmlNode) -> set[str]:
    return set(node.attrs.get("class", "").split())


def _has_class(node: _HtmlNode, class_name: str) -> bool:
    return class_name in _class_tokens(node)


def _text_content(node: _HtmlNode | str) -> str:
    if isinstance(node, str):
        return node
    parts = [_text_content(child) for child in node.children]
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


def _first_descendant(
    node: _HtmlNode,
    predicate: Callable[[_HtmlNode], bool],
) -> _HtmlNode | None:
    for child in _iter_nodes(node):
        if predicate(child):
            return child
    return None


def _descendants(
    node: _HtmlNode,
    predicate: Callable[[_HtmlNode], bool],
) -> list[_HtmlNode]:
    return [child for child in _iter_nodes(node) if predicate(child)]


def _node_text_by_class(node: _HtmlNode, class_name: str) -> str:
    found = _first_descendant(node, lambda child: _has_class(child, class_name))
    return _text_content(found) if found else ""


def _clean_label(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" ,;\n\t")


def _parse_iso_date(value: str) -> str | None:
    value = value.strip()
    if not value:
        return None
    match = re.match(r"(\d{4}-\d{2}-\d{2})", value)
    if match:
        return match.group(1)
    value = re.sub(r"\s+", " ", value.replace("\xa0", " "))
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%b. %d, %Y"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _first_time_date(node: _HtmlNode) -> str | None:
    time_node = _first_descendant(node, lambda child: child.tag == "time")
    if time_node is None:
        return None
    return (
        _parse_iso_date(time_node.attrs.get("datetime", ""))
        or _parse_iso_date(_text_content(time_node))
    )


@dataclass(frozen=True)
class _ListingParseResult:
    listings: list[DojListingCase]
    row_count: int
    skipped_non_merger: int


def _parse_doj_listing_rows(html: str) -> _ListingParseResult:
    root = _parse_html(html)
    rows = _descendants(root, lambda node: _has_class(node, "views-row"))
    listings: list[DojListingCase] = []
    skipped_non_merger = 0

    for row in rows:
        case_type = _clean_label(_node_text_by_class(row, "field_case_type"))
        if not case_type:
            case_type = _clean_label(
                _node_text_by_class(row, "field--name-field-case-document-type")
            )
        if case_type != "Civil Merger":
            skipped_non_merger += 1
            continue

        link = _first_descendant(
            row,
            lambda node: (
                node.tag == "a"
                and node.attrs.get("href", "").startswith("/atr/case/")
                and not node.attrs.get("href", "").startswith("/atr/case-document/")
            ),
        )
        listing_open_date = _first_time_date(row)
        if link is None or listing_open_date is None:
            continue
        title = _clean_label(_text_content(link))
        href = link.attrs.get("href", "")
        if not title or not href:
            continue

        industry_node = _first_descendant(
            row,
            lambda node: _has_class(node, "node-industry"),
        )
        industry_labels = tuple(
            _clean_label(_text_content(item))
            for item in (
                _descendants(industry_node, lambda node: _has_class(node, "field__item"))
                if industry_node
                else []
            )
            if _clean_label(_text_content(item))
        )

        documents_node = _first_descendant(
            row,
            lambda node: _has_class(node, "node-documents"),
        )
        document_labels = tuple(
            _clean_label(_text_content(item))
            for item in (
                _descendants(documents_node, lambda node: node.tag == "a")
                if documents_node
                else []
            )
            if _clean_label(_text_content(item))
        )

        listings.append(
            DojListingCase(
                case_title=title,
                case_page_url=urljoin(_BASE_URL, href),
                listing_open_date=listing_open_date,
                case_type=case_type,
                industry_labels=industry_labels,
                document_labels=document_labels,
            )
        )

    return _ListingParseResult(
        listings=listings,
        row_count=len(rows),
        skipped_non_merger=skipped_non_merger,
    )


def parse_doj_listing_page(html: str) -> list[DojListingCase]:
    """Return eligible DOJ Civil Merger listing rows from one listing page."""
    return _parse_doj_listing_rows(html).listings


class _AnchorDateParser(HTMLParser):
    _DOCUMENT_HREF_RE = re.compile(
        r"(/atr/media/|/atr/case-document/|\.pdf(?:[?#]|$)|/dl(?:[?#]|$))",
        re.IGNORECASE,
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.records: list[DojDocumentFact] = []
        self._current: dict[str, object] | None = None
        self._in_anchor = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        self._finalize_current()
        attr_map = {k: v or "" for k, v in attrs}
        href = attr_map.get("href", "")
        if not self._DOCUMENT_HREF_RE.search(href):
            self._current = None
            self._in_anchor = False
            return
        self._current = {"href": href, "label": [], "tail": []}
        self._in_anchor = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a":
            self._in_anchor = False

    def handle_data(self, data: str) -> None:
        if self._current is None:
            return
        key = "label" if self._in_anchor else "tail"
        parts = self._current[key]
        assert isinstance(parts, list)
        parts.append(data)

    def close(self) -> None:
        self._finalize_current()
        super().close()

    def _finalize_current(self) -> None:
        if self._current is None:
            return
        label = _clean_label(" ".join(self._current["label"]))
        tail = _clean_label(" ".join(self._current["tail"]))
        date = _date_from_text(tail)
        href = str(self._current["href"])
        if label and date:
            self.records.append(
                DojDocumentFact(label=label, date=date, url=urljoin(_BASE_URL, href))
            )
        self._current = None
        self._in_anchor = False


_MONTH_DATE_RE = re.compile(
    r"\b("
    r"January|February|March|April|May|June|July|August|September|October|"
    r"November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
    r")\.?\s+\d{1,2},\s+\d{4}\b"
)


def _date_from_text(text: str) -> str | None:
    match = _MONTH_DATE_RE.search(text)
    return _parse_iso_date(match.group(0)) if match else None


_DECISION_PATTERNS: tuple[tuple[int, re.Pattern[str]], ...] = (
    (120, re.compile(r"findings of fact|conclusions of law", re.IGNORECASE)),
    (110, re.compile(r"memorandum opinion", re.IGNORECASE)),
    (105, re.compile(r"\bopinion\b", re.IGNORECASE)),
    (100, re.compile(r"\bfinal judgment\b", re.IGNORECASE)),
    (95, re.compile(r"\bjudgment\b", re.IGNORECASE)),
    (90, re.compile(r"\bdecision and order\b", re.IGNORECASE)),
    (80, re.compile(r"\border\b", re.IGNORECASE)),
)
_DISQUALIFY_DECISION_LABEL = re.compile(
    r"(\[?proposed\]?|complaint|stipulation|brief|exhibit|notice|schedule|"
    r"motion|competitive impact|certificate|appendix|declaration|press release|"
    r"explanation of procedures|hold separate|asset preservation)",
    re.IGNORECASE,
)
_CONDITIONED_OUTCOME_RE = re.compile(
    r"(final judgment|consent decree|competitive impact statement|"
    r"antitrust procedures and penalties act|proposed final judgment|divest)",
    re.IGNORECASE,
)
_BLOCKED_OUTCOME_RE = re.compile(
    r"(blocked|prohibit|enjoin|injunction|permanent injunction)",
    re.IGNORECASE,
)


def _decision_score(label: str) -> int:
    if _DISQUALIFY_DECISION_LABEL.search(label):
        return 0
    for score, pattern in _DECISION_PATTERNS:
        if pattern.search(label):
            return score
    return 0


def _guess_outcome(selected_label: str, detail_text: str) -> str | None:
    text = f"{selected_label} {detail_text}"
    if _BLOCKED_OUTCOME_RE.search(text) and not _CONDITIONED_OUTCOME_RE.search(text):
        return "blocked"
    if _CONDITIONED_OUTCOME_RE.search(text):
        return "cleared_with_conditions"
    return None


def _dated_document_facts(html: str) -> tuple[DojDocumentFact, ...]:
    parser = _AnchorDateParser()
    parser.feed(html)
    parser.close()
    seen: set[tuple[str, str, str | None]] = set()
    documents: list[DojDocumentFact] = []
    for document in parser.records:
        key = (document.label, document.date, document.url)
        if key in seen:
            continue
        seen.add(key)
        documents.append(document)
    return tuple(documents)


def parse_doj_case_detail(html: str) -> DojDecisionFacts:
    """Extract a true disposition date from one DOJ case detail page."""
    documents = _dated_document_facts(html)
    scored = [
        (score, document.date, document)
        for document in documents
        if (score := _decision_score(document.label)) > 0
    ]
    if not scored:
        return DojDecisionFacts(
            decision_date=None,
            selected_label=None,
            outcome_guess=None,
            documents=documents,
        )

    _score, _date, selected = max(scored, key=lambda item: (item[0], item[1]))
    detail_text = _text_content(_parse_html(html))
    return DojDecisionFacts(
        decision_date=selected.date,
        selected_label=selected.label,
        outcome_guess=_guess_outcome(selected.label, detail_text),
        documents=documents,
    )


_CAPTION_PREFIX_RE = re.compile(
    r"^\s*(?:U\.?S\.?|United States)"
    r"(?:\s+et\s+al\.?|\s+and\s+(?:Plaintiff\s+States|State\s+of\s+[A-Za-z ]+))?"
    r"\s+v\.?\s+",
    re.IGNORECASE,
)
_TRAILING_ET_AL_RE = re.compile(r"(?:,\s*)?et\s+al\.?\s*$", re.IGNORECASE)


def _clean_caption(title: str) -> str:
    cleaned = _CAPTION_PREFIX_RE.sub("", title).strip()
    cleaned = _TRAILING_ET_AL_RE.sub("", cleaned).strip()
    return cleaned.strip(" .;")


def _parse_parties(title: str) -> tuple[CaseIndexParty, ...]:
    cleaned = _clean_caption(title)
    parts = [
        part.strip(" .;,")
        for part in re.split(r"\s+and\s+", cleaned)
        if part.strip(" .;,")
    ]
    if len(parts) >= 2 and all(len(part) >= 3 for part in parts):
        return tuple(
            CaseIndexParty(name=part, role="acquirer" if index == 0 else "target")
            for index, part in enumerate(parts)
        )
    return (CaseIndexParty(name=cleaned or title, role="third_party"),)


def _case_name_from_title(title: str, parties: tuple[CaseIndexParty, ...]) -> str:
    if len(parties) >= 2:
        return " / ".join(party.name for party in parties[:2])
    return _clean_caption(title) or title


_SECTOR_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"electric|energy|gas|fuel|pipeline|power", re.IGNORECASE), "energy"),
    (re.compile(r"cement|concrete|construction|bridge|highway", re.IGNORECASE), "construction"),
    (re.compile(r"manufactur|industrial|crane|hoist|ice", re.IGNORECASE), "manufacturing"),
    (re.compile(r"airline|airways|rail|transport|shipping", re.IGNORECASE), "transport"),
    (re.compile(r"hospital|health|pharma|medical", re.IGNORECASE), "healthcare"),
    (re.compile(r"software|computer|data|digital|technology", re.IGNORECASE), "tech"),
    (re.compile(r"telecom|communications|media|publishing", re.IGNORECASE), "media"),
    (re.compile(r"bank|financial|insurance|credit", re.IGNORECASE), "financial"),
    (re.compile(r"retail|grocery|food|egg|agricultur", re.IGNORECASE), "retail"),
)


def _sector_from_industries(labels: tuple[str, ...]) -> str:
    for label in labels:
        for pattern, sector in _SECTOR_PATTERNS:
            if pattern.search(label):
                return sector
    return "other"


def to_us_scraped_case(
    listing: DojListingCase,
    facts: DojDecisionFacts,
) -> UsScrapedCase:
    """Normalize one eligible DOJ listing/detail pair into the shared US contract."""
    if facts.decision_date is None:
        raise ValueError("missing_decision_date")
    parties = _parse_parties(listing.case_title)
    return UsScrapedCase(
        authority="DOJ",
        case_name=_case_name_from_title(listing.case_title, parties),
        parties=parties,
        source_url=listing.case_page_url,
        decision_date=facts.decision_date,
        outcome_guess=facts.outcome_guess,
        sector=_sector_from_industries(listing.industry_labels),
    )


def _new_counts() -> dict[str, int]:
    return {
        "built": 0,
        "written": 0,
        "dry_run": 0,
        "skipped_existing": 0,
        "skipped_non_merger": 0,
        "missing_decision_date": 0,
        "missing_source_url": 0,
        "invalid_case_index": 0,
        "fetch_error": 0,
    }


def _listing_page_url(page: int) -> str:
    return f"{_LISTING_URL}?{urlencode({'page': page})}"


def _fetch_text(client: httpx.Client, url: str, *, timeout: float) -> str:
    response = client.get(url, timeout=timeout)
    response.raise_for_status()
    return response.text


def _write_yaml(path: Path, record: dict) -> None:
    path.write_text(
        yaml.safe_dump(record, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _print_record(record: dict, *, dry_run: bool) -> None:
    tag = "DRY" if dry_run else "WROTE"
    print(
        f"  {tag}  {record['case_id']}  decision_date={record['decision_date']}  "
        f"outcome={record['outcome']}  source_url={record['source_url']}"
    )
    if dry_run:
        print(yaml.safe_dump(record, sort_keys=False, allow_unicode=True).strip())


def _run_with_fetcher(
    *,
    output_dir: Path,
    dry_run: bool,
    limit: Optional[int],
    force: bool,
    delay: float,
    timeout: float,
    start_page: int,
    fetch_text: Callable[[str, float], str],
    sleep_fn: Callable[[float], None],
) -> dict[str, int]:
    counts = _new_counts()
    if not dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)

    page = start_page
    while limit is None or counts["built"] < limit:
        try:
            listing_html = fetch_text(_listing_page_url(page), timeout)
        except Exception as exc:  # noqa: BLE001
            counts["fetch_error"] += 1
            print(f"  ERR   listing page {page}: {exc}")
            break

        parsed = _parse_doj_listing_rows(listing_html)
        counts["skipped_non_merger"] += parsed.skipped_non_merger
        if parsed.row_count == 0:
            break

        for listing in parsed.listings:
            if limit is not None and counts["built"] >= limit:
                break
            if not listing.case_page_url:
                counts["missing_source_url"] += 1
                continue

            sleep_fn(delay)
            try:
                detail_html = fetch_text(listing.case_page_url, timeout)
            except Exception as exc:  # noqa: BLE001
                counts["fetch_error"] += 1
                print(f"  ERR   {listing.case_title}: {exc}")
                continue

            facts = parse_doj_case_detail(detail_html)
            try:
                scraped = to_us_scraped_case(listing, facts)
            except ValueError:
                counts["missing_decision_date"] += 1
                print(
                    f"  SKIP  {listing.case_title}  "
                    f"missing_decision_date listing_open_date="
                    f"{listing.listing_open_date}"
                )
                continue

            try:
                record = to_case_index_dict(scraped)
            except Exception as exc:  # noqa: BLE001
                counts["invalid_case_index"] += 1
                print(f"  ERR   {listing.case_title}: invalid_case_index {exc}")
                continue

            counts["built"] += 1
            out_path = output_dir / f"{record['case_id']}.yaml"
            if out_path.exists() and not force:
                counts["skipped_existing"] += 1
                print(f"  EXISTS  {record['case_id']}")
                continue
            if dry_run:
                counts["dry_run"] += 1
                _print_record(record, dry_run=True)
                continue

            _write_yaml(out_path, record)
            counts["written"] += 1
            _print_record(record, dry_run=False)

        page += 1

    tag = " (dry run)" if dry_run else ""
    print(
        f"\nDone{tag}: built={counts['built']}  written={counts['written']}  "
        f"dry_run={counts['dry_run']}  skipped_existing="
        f"{counts['skipped_existing']}  skipped_non_merger="
        f"{counts['skipped_non_merger']}  missing_decision_date="
        f"{counts['missing_decision_date']}  missing_source_url="
        f"{counts['missing_source_url']}  invalid_case_index="
        f"{counts['invalid_case_index']}  fetch_error={counts['fetch_error']}"
    )
    return counts


def run(
    *,
    output_dir: Path,
    dry_run: bool,
    limit: Optional[int],
    force: bool,
    delay: float,
    timeout: float,
    start_page: int,
    fetch_text: Callable[[str, float], str] | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, int]:
    """Scrape DOJ listing/detail pages and optionally write CaseIndex YAML."""
    if fetch_text is not None:
        return _run_with_fetcher(
            output_dir=output_dir,
            dry_run=dry_run,
            limit=limit,
            force=force,
            delay=delay,
            timeout=timeout,
            start_page=start_page,
            fetch_text=fetch_text,
            sleep_fn=sleep_fn,
        )

    with httpx.Client(follow_redirects=True, headers=_HEADERS) as client:
        return _run_with_fetcher(
            output_dir=output_dir,
            dry_run=dry_run,
            limit=limit,
            force=force,
            delay=delay,
            timeout=timeout,
            start_page=start_page,
            fetch_text=lambda url, per_request_timeout: _fetch_text(
                client,
                url,
                timeout=per_request_timeout,
            ),
            sleep_fn=sleep_fn,
        )


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scrape DOJ Civil Merger case listings into CaseIndex YAML."
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Stop after N successfully built records",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing files in --output-dir",
    )
    parser.add_argument(
        "--output-dir",
        default=str(_TEMP_OUTPUT_DIR),
        help=(
            "Directory for written YAML; pass ../../data/case_index/us explicitly "
            "to write reviewed index output"
        ),
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="Seconds between detail-page requests",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="Per-request timeout in seconds",
    )
    parser.add_argument(
        "--start-page",
        type=int,
        default=0,
        help="DOJ listing page number to start at",
    )
    args = parser.parse_args(argv)

    run(
        output_dir=Path(args.output_dir),
        dry_run=args.dry_run,
        limit=args.limit,
        force=args.force,
        delay=args.delay,
        timeout=args.timeout,
        start_page=args.start_page,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
