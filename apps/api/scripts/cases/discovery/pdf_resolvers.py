#!/usr/bin/env python3
"""
pdf_resolvers.py — shared contract + authority adapters for resolving the
decision-document ``pdf_url`` of a case-index entry from its ``source_url``.

One small contract, authority-specific adapters:

  * **Extract** candidate PDFs from the authority page or a derived endpoint.
  * **Rank** them with authority-specific document-role rules.
  * **Return** a structured :class:`PdfResolution` with a reason — never patch YAML.

Batch processing, YAML IO, dry-run / overwrite behaviour, rate limiting and
reporting live in ``resolve_case_index_pdf_urls.py``; ``ingest_case.py
--from-index`` calls :func:`resolve_pdf_url` so single-case ingestion and batch
resolution can never diverge again.

Each adapter owns only authority knowledge. HTTP is injected through a
:class:`Fetcher` so the adapters are unit-testable with no network.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal, Optional, Protocol, runtime_checkable

import httpx

# ---------------------------------------------------------------------------
# Result + contract types
# ---------------------------------------------------------------------------

ResolutionStatus = Literal["resolved", "manual_required", "not_found", "error"]


@dataclass(frozen=True)
class PdfCandidate:
    url: str
    label: str
    source: str
    score: int
    reason: str


@dataclass(frozen=True)
class PdfResolution:
    status: ResolutionStatus
    pdf_url: Optional[str]
    candidates: list[PdfCandidate]
    resolver: str
    reason: str

    @classmethod
    def resolved(cls, resolver: str, url: str, reason: str,
                 candidates: Optional[list[PdfCandidate]] = None) -> "PdfResolution":
        return cls("resolved", url, candidates or [], resolver, reason)

    @classmethod
    def manual(cls, resolver: str, reason: str,
               candidates: Optional[list[PdfCandidate]] = None) -> "PdfResolution":
        return cls("manual_required", None, candidates or [], resolver, reason)

    @classmethod
    def missing(cls, resolver: str, reason: str,
                candidates: Optional[list[PdfCandidate]] = None) -> "PdfResolution":
        return cls("not_found", None, candidates or [], resolver, reason)

    @classmethod
    def errored(cls, resolver: str, reason: str) -> "PdfResolution":
        return cls("error", None, [], resolver, reason)


# A light structural view of a case-index entry. CaseIndexEntry satisfies it,
# and so does any object exposing the same attributes — adapters read nothing else.
@runtime_checkable
class IndexEntryLike(Protocol):
    jurisdiction: str
    authority: str
    outcome: object
    source_url: Optional[str]
    decision_date: object


class PdfResolver(Protocol):
    jurisdiction: str
    authority: Optional[str]
    # Outcomes worth resolving by default; None means "all outcomes". The batch
    # CLI skips entries outside this set unless --all-outcomes is given.
    default_outcomes: Optional[set[str]]

    def can_handle(self, entry: IndexEntryLike) -> bool: ...
    def resolve(self, entry: IndexEntryLike, *, timeout: float) -> PdfResolution: ...


# ---------------------------------------------------------------------------
# Injectable HTTP
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class HeadResult:
    status_code: int
    content_type: str
    url: str


class Fetcher(Protocol):
    def head(self, url: str, *, timeout: float) -> HeadResult: ...
    def get_text(self, url: str, *, timeout: float) -> str: ...


_PDF_ACCEPT = {"Accept": "application/pdf, */*;q=0.5"}
_UA = {
    "User-Agent": (
        "Meridian-research-bot/1.0 (academic legal research; bhavyasharma1510@gmail.com)"
    )
}


class HttpxFetcher:
    """Default :class:`Fetcher` backed by httpx. Raises on transport errors."""

    def head(self, url: str, *, timeout: float) -> HeadResult:
        with httpx.Client(follow_redirects=True, timeout=timeout) as client:
            resp = client.head(url, headers={**_UA, **_PDF_ACCEPT})
            return HeadResult(resp.status_code,
                              resp.headers.get("content-type", ""), str(resp.url))

    def get_text(self, url: str, *, timeout: float) -> str:
        with httpx.Client(follow_redirects=True, timeout=timeout) as client:
            resp = client.get(url, headers=_UA)
            if resp.status_code == 404:
                return ""
            resp.raise_for_status()
            return resp.text


def _outcome_str(entry: IndexEntryLike) -> str:
    """Return the entry outcome as a plain string (handles str / Enum)."""
    return getattr(entry.outcome, "value", entry.outcome) or ""


def _year(entry: IndexEntryLike) -> str:
    return str(getattr(entry, "decision_date", "") or "")[:4]


# Anchor links to PDFs, as (url, anchor_text) pairs. The path must end in .pdf,
# optionally followed by a ?query or #fragment (DOJ/FTC asset URLs sometimes
# carry one — without this they would be silently missed).
_ANCHOR_RE = re.compile(
    r'<a\b[^>]*?href=["\']([^"\']+?\.pdf(?:[?#][^"\']*)?)["\'][^>]*?>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")


def _extract_pdf_anchors(html: str) -> list[tuple[str, str]]:
    """Return (url, visible_text) for every <a href="*.pdf"> in the page."""
    out: list[tuple[str, str]] = []
    for url, inner in _ANCHOR_RE.findall(html):
        text = re.sub(r"\s+", " ", _TAG_RE.sub(" ", inner)).strip()
        out.append((url, text))
    return out


# ---------------------------------------------------------------------------
# EU — EUR-Lex / Cellar
# ---------------------------------------------------------------------------

# Phase II / appeal outcomes are not published in EUR-Lex / Cellar; their PDFs
# live on ec.europa.eu case pages and need a manual URL.
_EU_MANUAL_OUTCOMES = {"cleared_with_conditions", "blocked", "annulled",
                       "partially_annulled", "under_appeal"}
_EU_CASE_RE = re.compile(r"M\.(\d+)$")
_CELLAR_TEMPLATE = "http://publications.europa.eu/resource/celex/{celex}.ENG.pdf"


@dataclass
class EuCellarResolver:
    """Resolve EC Phase I (non-opposition) decisions via the EUR-Lex Cellar endpoint.

    The CELEX id follows ``3{YEAR}M{CASE_NUMBER}`` (M.11115 decided 2023 →
    ``32023M11115``); the Cellar URL content-negotiates to a PDF. Phase II /
    appeal outcomes are returned as ``manual_required`` rather than guessed.
    """

    fetcher: Fetcher
    jurisdiction: str = "EU"
    authority: Optional[str] = None
    # None → the batch outcome filter is bypassed for EU: every outcome is
    # attempted and Phase II / appeal cases self-report manual_required from
    # resolve(). So --all-outcomes is effectively a no-op for EU.
    default_outcomes: Optional[set[str]] = None

    name: str = "eu_cellar"

    def can_handle(self, entry: IndexEntryLike) -> bool:
        return entry.jurisdiction == "EU"

    def resolve(self, entry: IndexEntryLike, *, timeout: float) -> PdfResolution:
        if _outcome_str(entry) in _EU_MANUAL_OUTCOMES:
            return PdfResolution.manual(
                self.name, "phase_ii_not_in_cellar")
        source_url = entry.source_url or ""
        m = _EU_CASE_RE.search(source_url)
        if not m:
            return PdfResolution.missing(self.name, "no_case_number_in_source_url")
        year = _year(entry)
        if not year.isdigit():
            return PdfResolution.missing(self.name, "no_decision_year")
        celex = f"3{year}M{m.group(1)}"
        url = _CELLAR_TEMPLATE.format(celex=celex)
        try:
            head = self.fetcher.head(url, timeout=timeout)
        except Exception as exc:  # noqa: BLE001 — transport failure is operational
            return PdfResolution.errored(self.name, f"head_failed: {exc}")
        if head.status_code == 200 and "pdf" in head.content_type:
            return PdfResolution.resolved(
                self.name, head.url, f"cellar_celex_{celex}")
        return PdfResolution.missing(self.name, f"cellar_no_pdf_status_{head.status_code}")


# ---------------------------------------------------------------------------
# UK — GOV.UK case pages
# ---------------------------------------------------------------------------

# PDF asset hosts used by GOV.UK (old and new).
_UK_ASSET_HOSTS = (
    "assets.publishing.service.gov.uk",
    "assets.digital.cabinet-office.gov.uk",
)

# Substantive Phase 2 inquiry reports — the default target. Phase 1 clearances
# are brief decision letters without market analysis.
_UK_PHASE2_OUTCOMES = {"blocked", "cleared_with_conditions", "referred"}

# Filename substrings identifying the main inquiry report, in priority order.
_UK_REPORT_PATTERNS: list[tuple[int, re.Pattern]] = [
    (100, re.compile(r"final.report", re.IGNORECASE)),
    (90, re.compile(r"(inquiry.report|main.report)", re.IGNORECASE)),
    (80, re.compile(r"provisional.findings.report", re.IGNORECASE)),
    (70, re.compile(r"provisional.findings(?!.*(appendix|appendices|notice|summary))", re.IGNORECASE)),
    (60, re.compile(r"full.text.*(phase.1|phase1)", re.IGNORECASE)),
    (50, re.compile(r"report", re.IGNORECASE)),
    (45, re.compile(r"(ftd|full.?text.?decision|fulltext.decision|full.?text)", re.IGNORECASE)),
    (42, re.compile(r"decision", re.IGNORECASE)),
    (42, re.compile(r"fntq", re.IGNORECASE)),
    (38, re.compile(r"non.confidential", re.IGNORECASE)),
    (40, re.compile(r"^\d[\d\-]+\.pdf$", re.IGNORECASE)),
]

# Filename substrings that disqualify a PDF regardless of score.
_UK_DISQUALIFY = re.compile(
    r"(final.order|interim.order|final.undertaking|interim.undertaking"
    r"|notice|summary|appendix|appendices|glossary|annex"
    r"|response|submission|working.paper|issues.statement"
    r"|survey|research|timetable|extension|cancellation"
    r"|explanatory.note|draft.final|draft_final"
    r"|terms.of.reference|ieo|directions|commencement"
    r"|derogation|revocation.order|revocation_order)",
    re.IGNORECASE,
)


def _uk_score(url: str) -> int:
    """Priority score for a GOV.UK PDF URL by filename. 0 = disqualified/no match."""
    filename = url.rsplit("/", 1)[-1]
    if _UK_DISQUALIFY.search(filename):
        return 0
    for score, pattern in _UK_REPORT_PATTERNS:
        if pattern.search(filename):
            return score
    return 0


@dataclass
class UkGovUkResolver:
    """Resolve a CMA/CC inquiry report by scoring the PDFs on the GOV.UK case page.

    Ranks final reports above provisional findings; rejects orders,
    undertakings, appendices, notices and submissions. Falls back to a lone
    surviving PDF only when disqualification leaves exactly one candidate.
    """

    fetcher: Fetcher
    jurisdiction: str = "UK"
    authority: Optional[str] = None
    default_outcomes: Optional[set[str]] = field(
        default_factory=lambda: set(_UK_PHASE2_OUTCOMES))

    name: str = "uk_govuk"

    def can_handle(self, entry: IndexEntryLike) -> bool:
        return entry.jurisdiction == "UK"

    def resolve(self, entry: IndexEntryLike, *, timeout: float) -> PdfResolution:
        source_url = entry.source_url or ""
        if not source_url:
            return PdfResolution.missing(self.name, "no_source_url")
        try:
            html = self.fetcher.get_text(source_url, timeout=timeout)
        except Exception as exc:  # noqa: BLE001
            return PdfResolution.errored(self.name, f"page_fetch_failed: {exc}")
        if not html:
            return PdfResolution.missing(self.name, "page_not_found")

        pdf_links = [
            u for u, _ in _extract_pdf_anchors(html)
            if any(h in u for h in _UK_ASSET_HOSTS)
        ]
        if not pdf_links:
            return PdfResolution.missing(self.name, "no_pdf_links")

        scored = [
            PdfCandidate(u, u.rsplit("/", 1)[-1], "govuk", _uk_score(u),
                         "filename_score")
            for u in pdf_links
        ]
        ranked = sorted([c for c in scored if c.score > 0],
                        key=lambda c: c.score, reverse=True)
        if ranked:
            best = ranked[0]
            return PdfResolution.resolved(
                self.name, best.url, "report_highest_score", ranked)

        # Nothing matched a report pattern. If disqualification left exactly one
        # PDF, that lone document IS the decision (Phase 1 cases named after the
        # parties). Otherwise leave the ambiguous set for manual inspection.
        survivors = [c for c in scored if not _UK_DISQUALIFY.search(c.label)]
        if len(survivors) == 1:
            return PdfResolution.resolved(
                self.name, survivors[0].url, "lone_surviving_pdf", survivors)
        return PdfResolution.manual(
            self.name, "no_report_match", scored)


# ---------------------------------------------------------------------------
# US — DOJ / FTC case pages
# ---------------------------------------------------------------------------

# Anchor-text rules. US publication pages link litigation records (complaints,
# proposed orders, press releases) alongside the merits document, and filenames
# are often opaque — so rank on the visible link text, conservatively.
_US_MERITS_PATTERNS: list[tuple[int, re.Pattern]] = [
    (100, re.compile(r"memorandum opinion", re.IGNORECASE)),
    (95, re.compile(r"\bopinion\b", re.IGNORECASE)),
    (95, re.compile(r"findings of fact", re.IGNORECASE)),
    (90, re.compile(r"decision and order", re.IGNORECASE)),
    (80, re.compile(r"opinion of the commission", re.IGNORECASE)),
]
_US_DISQUALIFY = re.compile(
    r"(complaint|press release|proposed (final )?(judgment|order)|stipulat"
    r"|competitive impact|notice|appendix|exhibit|declaration|motion"
    r"|brief|schedule|undertaking|consent|hold separate|analysis to aid)",
    re.IGNORECASE,
)


def _us_score(text: str) -> int:
    """Conservative merits score for a US PDF by its anchor text. 0 = disqualified."""
    if _US_DISQUALIFY.search(text):
        return 0
    for score, pattern in _US_MERITS_PATTERNS:
        if pattern.search(text):
            return score
    return 0


@dataclass
class UsDojFtcResolver:
    """Resolve a US merger merits document from a DOJ or FTC case page.

    Ranks court opinions / findings of fact / decision-and-order above
    complaints, proposed orders, press releases and procedural filings. Prefers
    a correct ``manual_required`` over an overconfident wrong URL: a single
    clear merits PDF resolves; multiple close high scorers, or only weak
    candidates, return ``manual_required`` with the candidates listed.
    """

    fetcher: Fetcher
    jurisdiction: str = "US"
    authority: Optional[str] = None
    default_outcomes: Optional[set[str]] = None

    name: str = "us_doj_ftc"

    def can_handle(self, entry: IndexEntryLike) -> bool:
        return entry.jurisdiction == "US"

    def resolve(self, entry: IndexEntryLike, *, timeout: float) -> PdfResolution:
        source_url = entry.source_url or ""
        if not source_url:
            return PdfResolution.missing(self.name, "no_source_url")
        try:
            html = self.fetcher.get_text(source_url, timeout=timeout)
        except Exception as exc:  # noqa: BLE001
            return PdfResolution.errored(self.name, f"page_fetch_failed: {exc}")
        if not html:
            return PdfResolution.missing(self.name, "page_not_found")

        anchors = _extract_pdf_anchors(html)
        if not anchors:
            return PdfResolution.missing(self.name, "no_pdf_links")

        scored = [
            PdfCandidate(u, text or u.rsplit("/", 1)[-1], "us_page",
                         _us_score(text), "anchor_text_score")
            for u, text in anchors
        ]
        high = sorted([c for c in scored if c.score > 0],
                      key=lambda c: c.score, reverse=True)
        if not high:
            return PdfResolution.manual(self.name, "no_merits_match", scored)
        if len(high) == 1:
            return PdfResolution.resolved(
                self.name, high[0].url, "single_merits_doc", high)
        # Multiple plausible merits docs. Only resolve if the top one is a clear
        # winner; otherwise leave the close set for manual inspection.
        if high[0].score - high[1].score >= 10:
            return PdfResolution.resolved(
                self.name, high[0].url, "top_merits_doc", high)
        return PdfResolution.manual(self.name, "multiple_close_merits_docs", high)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def build_default_resolvers(fetcher: Optional[Fetcher] = None) -> list[PdfResolver]:
    """The standard adapter set, sharing one fetcher."""
    f = fetcher or HttpxFetcher()
    return [EuCellarResolver(f), UkGovUkResolver(f), UsDojFtcResolver(f)]


def select_resolver(entry: IndexEntryLike,
                    resolvers: list[PdfResolver]) -> Optional[PdfResolver]:
    """First resolver that can handle the entry, or None."""
    for r in resolvers:
        if r.can_handle(entry):
            return r
    return None


def resolve_pdf_url(entry: IndexEntryLike, *, timeout: float = 30.0,
                    resolvers: Optional[list[PdfResolver]] = None) -> PdfResolution:
    """Resolve one entry through the registry. Used by ingest_case --from-index."""
    resolvers = resolvers if resolvers is not None else build_default_resolvers()
    resolver = select_resolver(entry, resolvers)
    if resolver is None:
        return PdfResolution.errored(
            "registry", f"no_resolver_for_jurisdiction_{entry.jurisdiction}")
    return resolver.resolve(entry, timeout=timeout)
