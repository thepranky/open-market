#!/usr/bin/env python3
"""
QA utility — validates source_url fields in broad case-index YAML records.

Per-entry checks:
  1. source_url present  (WARN if null — explicit null is documented as "no official public page")
  2. Domain on the official allowlist for the entry's jurisdiction
  3. Authority-specific format validation
       EU  — competition-cases portal path must be /cases/M.<digits>
       US  — FTC matter-URL slug must start with 7-digit or NNN-NNNN matter ID
  4. HTTP liveness — HEAD with GET fallback; 200/3xx pass, 4xx/5xx fail

Does not modify any data. Exit 0 if no FAIL, exit 1 if any FAIL.

Usage:
    python scripts/check_case_index_sources.py [--timeout 15] [--no-http] [--verbose]
    python scripts/check_case_index_sources.py --index-dir ../../data/case_index
"""
import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import httpx

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INDEX_DIR = REPO_ROOT / "data" / "case_index"

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.loader.index_loader import load_all_index_cases
from app.models.case_index import CaseIndexEntry

HEADERS = {
    "User-Agent": "CompMap-IndexChecker/1.0 (open-source research tool; contact: open-market)",
}

# Official domains per jurisdiction.  Subdomains of listed entries are also accepted.
_OFFICIAL_DOMAINS: dict[str, set[str]] = {
    "EU": {
        "competition-cases.ec.europa.eu",
        "ec.europa.eu",
        "eur-lex.europa.eu",
        "curia.europa.eu",
        "infocuria.curia.europa.eu",
        "generalcourt.europa.eu",
    },
    "UK": {
        "gov.uk",
        "assets.publishing.service.gov.uk",
    },
    "US": {
        "ftc.gov",
        "justice.gov",
        "doj.gov",
    },
}

# /cases/M.<digits> — the EC competition-cases deep-link format
_EC_CASE_PATH_RE = re.compile(r"^/cases/M\.\d+$")

# FTC matter-ID slug prefixes: 7-digit modern (e.g. 2210077-) or NNN-NNNN legacy (e.g. 201-0144-)
_FTC_MATTER_RE = re.compile(r"^(\d{7}|\d{3}-\d{4})-")


@dataclass
class CheckItem:
    status: str   # "PASS" | "FAIL" | "WARN"
    message: str


@dataclass
class CaseResult:
    case_id: str
    url: str | None
    items: list[CheckItem] = field(default_factory=list)

    @property
    def status(self) -> str:
        if any(c.status == "FAIL" for c in self.items):
            return "FAIL"
        if any(c.status == "WARN" for c in self.items):
            return "WARN"
        return "PASS"


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def check_url_present(entry: CaseIndexEntry) -> CheckItem:
    if entry.source_url is None:
        return CheckItem(
            "WARN",
            "source_url is null — no official public source recorded for this entry",
        )
    return CheckItem("PASS", "source_url present")


def check_domain_official(url: str, jurisdiction: str) -> CheckItem:
    allowed = _OFFICIAL_DOMAINS.get(jurisdiction, set())
    if not allowed:
        return CheckItem("WARN", f"no domain allowlist configured for jurisdiction {jurisdiction!r}")

    parsed = urlparse(url)
    host = parsed.netloc.lower().split(":")[0]  # strip port

    for domain in allowed:
        if host == domain or host.endswith("." + domain):
            return CheckItem("PASS", f"domain official ({host} — {jurisdiction})")

    # US courts: *.uscourts.gov
    if jurisdiction == "US" and host.endswith(".uscourts.gov"):
        return CheckItem("PASS", f"domain official ({host} — US federal court)")

    return CheckItem(
        "FAIL",
        f"domain not on official allowlist for {jurisdiction}: {host!r}",
    )


def check_ec_case_format(url: str) -> CheckItem | None:
    """Returns None if the URL is not an EC competition-cases portal link."""
    parsed = urlparse(url)
    if parsed.netloc.lower() != "competition-cases.ec.europa.eu":
        return None
    if not _EC_CASE_PATH_RE.match(parsed.path):
        return CheckItem(
            "FAIL",
            f"EC competition portal path does not match /cases/M.<digits>: {parsed.path!r}",
        )
    case_ref = parsed.path.split("/")[-1]
    return CheckItem("PASS", f"EC case number format valid ({case_ref})")


def check_ftc_matter_format(url: str) -> CheckItem | None:
    """Returns None if the URL is not an FTC cases-proceedings link."""
    parsed = urlparse(url)
    if "ftc.gov" not in parsed.netloc.lower():
        return None
    if "/legal-library/browse/cases-proceedings/" not in parsed.path:
        return None
    slug = parsed.path.rstrip("/").split("/")[-1]
    m = _FTC_MATTER_RE.match(slug)
    if not m:
        return CheckItem(
            "FAIL",
            f"FTC matter-URL slug {slug!r} does not start with a recognised matter ID "
            f"(7-digit modern e.g. '2210077-' or legacy NNN-NNNN e.g. '201-0144-')",
        )
    matter_id = m.group(1)
    return CheckItem("PASS", f"FTC matter ID format valid ({matter_id})")


def check_http(client: httpx.Client, url: str, timeout: int) -> CheckItem:
    try:
        r = client.head(url, follow_redirects=True, timeout=timeout, headers=HEADERS)
        # Some servers reject HEAD — retry with GET
        if r.status_code in (400, 403, 405):
            r = client.get(url, follow_redirects=True, timeout=timeout, headers=HEADERS)
        if r.status_code < 400:
            redirect = f" → {r.url}" if str(r.url) != url else ""
            return CheckItem("PASS", f"HTTP {r.status_code}{redirect}")
        return CheckItem("FAIL", f"HTTP {r.status_code}")
    except httpx.TimeoutException:
        return CheckItem("FAIL", "request timed out")
    except httpx.RequestError as exc:
        return CheckItem("FAIL", f"connection error: {exc}")


# ---------------------------------------------------------------------------
# Per-entry orchestration
# ---------------------------------------------------------------------------

def check_entry(
    entry: CaseIndexEntry,
    client: httpx.Client | None,
    timeout: int,
) -> CaseResult:
    result = CaseResult(case_id=entry.case_id, url=entry.source_url)

    presence = check_url_present(entry)
    result.items.append(presence)
    if presence.status != "PASS":
        return result   # no further checks without a URL

    url = entry.source_url  # confirmed non-None
    assert url is not None  # for type checker

    domain = check_domain_official(url, entry.jurisdiction)
    result.items.append(domain)
    if domain.status == "FAIL":
        return result   # skip format + HTTP checks for unofficial domains

    ec = check_ec_case_format(url)
    if ec is not None:
        result.items.append(ec)

    ftc = check_ftc_matter_format(url)
    if ftc is not None:
        result.items.append(ftc)

    if client is not None:
        result.items.append(check_http(client, url, timeout))

    return result


# ---------------------------------------------------------------------------
# Batch runner
# ---------------------------------------------------------------------------

def run_checks(
    index_dir: str | Path,
    client: httpx.Client | None,
    timeout: int,
) -> list[CaseResult]:
    results: list[CaseResult] = []
    for path, entry_or_exc in load_all_index_cases(str(index_dir)):
        if isinstance(entry_or_exc, Exception):
            r = CaseResult(case_id=path.stem, url=None)
            r.items.append(CheckItem("FAIL", f"YAML load error: {entry_or_exc}"))
            results.append(r)
        else:
            results.append(check_entry(entry_or_exc, client, timeout))
    return results


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def print_report(results: list[CaseResult]) -> None:
    markers = {"PASS": "✓", "FAIL": "✗", "WARN": "⚠"}

    for r in results:
        print(f"\n{r.case_id} ... {r.status}")
        if r.url:
            print(f"  url: {r.url}")
        for item in r.items:
            print(f"  {markers[item.status]} {item.message}")

    totals: dict[str, int] = {"PASS": 0, "FAIL": 0, "WARN": 0}
    for r in results:
        totals[r.status] += 1

    print("\n" + "=" * 52)
    print(f"Summary: {totals['PASS']} PASS  {totals['FAIL']} FAIL  {totals['WARN']} WARN")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate source URLs in broad case-index YAML records"
    )
    parser.add_argument(
        "--index-dir", default=str(DEFAULT_INDEX_DIR),
        help="Root of data/case_index/ (default: auto-detected relative to repo root)",
    )
    parser.add_argument(
        "--timeout", type=int, default=15,
        help="HTTP request timeout in seconds (default: 15)",
    )
    parser.add_argument(
        "--no-http", action="store_true",
        help="Skip HTTP liveness checks — run domain and format checks only",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    index_path = Path(args.index_dir)
    if not index_path.exists():
        print(f"error: index directory not found: {index_path}", file=sys.stderr)
        return 1

    client: httpx.Client | None = None
    if not args.no_http:
        client = httpx.Client(follow_redirects=True)

    try:
        results = run_checks(index_path, client, args.timeout)
    finally:
        if client is not None:
            client.close()

    if not results:
        print("No index entries found.", file=sys.stderr)
        return 1

    print_report(results)
    return 1 if any(r.status == "FAIL" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
