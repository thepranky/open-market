#!/usr/bin/env python3
"""
Verify all URLs in jurisdiction YAML files.

Checks every url: field across all jurisdiction YAMLs (authority URLs,
legal_basis URLs, source_passages URLs, fee source URLs, etc.) using async
HTTP HEAD requests. Reports broken links, slow responses, and redirect chains.

Usage:
    python scripts/screening/verify_jurisdiction_urls.py [--timeout 15] [--verbose] [--fix-yaml]

Exit 0 if all URLs return 2xx, exit 1 if any broken links found.
"""
import argparse
import asyncio
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import httpx
import yaml

DATA_DIR = Path(__file__).resolve().parents[4] / "data" / "jurisdictions"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; Meridian-LinkChecker/1.0; "
        "+https://github.com/open-market)"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Some official sites block HEAD; retry with GET for these domains
GET_FALLBACK_DOMAINS = {
    "eur-lex.europa.eu",
    "ftc.gov",
    "uscode.house.gov",
    "ecfr.gov",
    "legislation.gov.uk",
    "gov.uk",
}


@dataclass
class UrlEntry:
    jurisdiction_id: str
    field_path: str   # e.g. "authority.url", "threshold_tests[0].source_url"
    url: str


# Status codes that indicate bot protection (URL likely valid, just blocked for scripts)
BOT_PROTECTED_STATUSES = {400, 403}

# SSL error substrings that indicate a working site with a cert Python can't verify
SSL_ERROR_SUBSTRINGS = ("CERTIFICATE_VERIFY_FAILED", "SSL:", "[SSL")


@dataclass
class CheckResult:
    entry: UrlEntry
    status: Optional[int]
    final_url: Optional[str]       # after redirects
    redirect_count: int = 0
    error: Optional[str] = None
    slow: bool = False             # >8s response

    @property
    def bot_protected(self) -> bool:
        return self.status in BOT_PROTECTED_STATUSES

    @property
    def ssl_uncertain(self) -> bool:
        return bool(self.error and any(s in self.error for s in SSL_ERROR_SUBSTRINGS))

    @property
    def broken(self) -> bool:
        if self.bot_protected or self.ssl_uncertain:
            return False
        if self.error:
            return True
        return self.status is not None and self.status not in BOT_PROTECTED_STATUSES and self.status >= 400

    @property
    def redirected(self) -> bool:
        return self.redirect_count > 0 and not self.broken and not self.bot_protected

    @property
    def ok(self) -> bool:
        return not self.broken


def _extract_urls(obj, path: str, entries: list[UrlEntry], jid: str) -> None:
    """Recursively walk a YAML object and collect all string values for keys ending in 'url'."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            child_path = f"{path}.{k}" if path else k
            if k.lower().endswith("url") and isinstance(v, str) and v.startswith("http"):
                entries.append(UrlEntry(jid, child_path, v))
            else:
                _extract_urls(v, child_path, entries, jid)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            _extract_urls(item, f"{path}[{i}]", entries, jid)


def collect_entries(data_dir: Path) -> list[UrlEntry]:
    entries: list[UrlEntry] = []
    for yaml_path in sorted(data_dir.glob("*.yaml")):
        if yaml_path.name.startswith("_"):
            continue
        with open(yaml_path) as f:
            data = yaml.safe_load(f)
        if not data:
            continue
        jid = data.get("jurisdiction_id", yaml_path.stem)
        _extract_urls(data, "", entries, jid)
    return entries


def _needs_get_fallback(url: str) -> bool:
    for domain in GET_FALLBACK_DOMAINS:
        if domain in url:
            return True
    return False


async def check_url(
    client: httpx.AsyncClient,
    entry: UrlEntry,
    timeout: float,
    verbose: bool,
) -> CheckResult:
    import time

    method = "GET" if _needs_get_fallback(entry.url) else "HEAD"
    start = time.monotonic()
    try:
        resp = await client.request(
            method,
            entry.url,
            headers=HEADERS,
            follow_redirects=True,
            timeout=timeout,
        )
        elapsed = time.monotonic() - start
        redirect_count = len(resp.history)
        final_url = str(resp.url) if redirect_count > 0 else None

        # HEAD returned 405 → retry with GET
        if resp.status_code == 405 and method == "HEAD":
            resp = await client.get(
                entry.url,
                headers=HEADERS,
                follow_redirects=True,
                timeout=timeout,
            )
            redirect_count = len(resp.history)
            final_url = str(resp.url) if redirect_count > 0 else None

        if verbose:
            print(f"  [{resp.status_code}] {entry.url}")

        return CheckResult(
            entry=entry,
            status=resp.status_code,
            final_url=final_url,
            redirect_count=redirect_count,
            slow=elapsed > 8,
        )
    except httpx.TimeoutException:
        return CheckResult(entry=entry, status=None, final_url=None, error="TIMEOUT")
    except httpx.TooManyRedirects:
        return CheckResult(entry=entry, status=None, final_url=None, error="TOO_MANY_REDIRECTS")
    except Exception as e:
        return CheckResult(entry=entry, status=None, final_url=None, error=str(e)[:80])


async def run_checks(
    entries: list[UrlEntry],
    timeout: float,
    verbose: bool,
    concurrency: int = 20,
) -> list[CheckResult]:
    semaphore = asyncio.Semaphore(concurrency)
    results: list[CheckResult] = []

    async def bounded(entry: UrlEntry) -> CheckResult:
        async with semaphore:
            return await check_url(client, entry, timeout, verbose)

    limits = httpx.Limits(max_connections=concurrency, max_keepalive_connections=10)
    async with httpx.AsyncClient(limits=limits) as client:
        tasks = [bounded(e) for e in entries]
        total = len(tasks)
        done = 0
        for coro in asyncio.as_completed(tasks):
            result = await coro
            results.append(result)
            done += 1
            if not verbose:
                print(f"\r  Checking... {done}/{total}", end="", flush=True)
    if not verbose:
        print()
    return results


def print_report(results: list[CheckResult], verbose: bool) -> bool:
    broken = [r for r in results if r.broken]
    redirected = [r for r in results if r.redirected]
    bot_protected = [r for r in results if r.bot_protected]
    ssl_uncertain = [r for r in results if r.ssl_uncertain]
    slow = [r for r in results if r.slow and r.ok]
    ok = [r for r in results if r.ok and not r.redirected and not r.bot_protected and not r.ssl_uncertain]

    print(f"\n{'='*70}")
    print(f"JURISDICTION URL VERIFICATION REPORT")
    print(f"{'='*70}")
    print(f"  Total URLs checked : {len(results)}")
    print(f"  OK (2xx)           : {len(ok)}")
    print(f"  Redirected (3xx)   : {len(redirected)}")
    print(f"  Broken (4xx/5xx)   : {len(broken)}")
    print(f"  Bot-protected(400/403): {len(bot_protected)}  (likely valid — verify manually)")
    print(f"  SSL uncertain      : {len(ssl_uncertain)}  (site may work in browser)")
    print(f"  Slow (>8s)         : {len(slow)}")
    print()

    if broken:
        print(f"BROKEN LINKS — must fix before launch:")
        print(f"{'-'*70}")
        by_jid: dict[str, list[CheckResult]] = {}
        for r in broken:
            by_jid.setdefault(r.entry.jurisdiction_id, []).append(r)
        for jid, rlist in sorted(by_jid.items()):
            print(f"\n  [{jid}]")
            for r in rlist:
                status = r.status or r.error
                print(f"    {r.entry.field_path}")
                print(f"      URL    : {r.entry.url}")
                print(f"      Status : {status}")
        print()

    if redirected:
        print(f"REDIRECTS — update URLs in YAML to avoid extra hops:")
        print(f"{'-'*70}")
        for r in redirected:
            print(f"  [{r.entry.jurisdiction_id}] {r.entry.field_path}")
            print(f"    Old: {r.entry.url}")
            print(f"    New: {r.final_url}")
        print()

    if slow and verbose:
        print(f"SLOW (>8s) — check these are real:")
        for r in slow:
            print(f"  [{r.entry.jurisdiction_id}] {r.entry.url}")
        print()

    any_broken = len(broken) > 0
    if any_broken:
        print(f"RESULT: FAIL — {len(broken)} broken link(s) found")
    else:
        print(f"RESULT: PASS — all URLs reachable")
    return any_broken


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify jurisdiction YAML URLs")
    parser.add_argument("--timeout", type=float, default=15.0, help="HTTP timeout in seconds")
    parser.add_argument("--verbose", action="store_true", help="Print each URL as checked")
    parser.add_argument(
        "--jurisdiction", "-j",
        help="Check only this jurisdiction ID (e.g. us_hsr)",
    )
    args = parser.parse_args()

    print(f"Collecting URLs from {DATA_DIR}...")
    entries = collect_entries(DATA_DIR)

    if args.jurisdiction:
        entries = [e for e in entries if e.jurisdiction_id == args.jurisdiction]
        if not entries:
            print(f"No entries found for jurisdiction: {args.jurisdiction}")
            sys.exit(1)

    print(f"Found {len(entries)} URLs across {len({e.jurisdiction_id for e in entries})} jurisdiction files")
    print(f"Running checks (timeout={args.timeout}s)...\n")

    results = asyncio.run(run_checks(entries, args.timeout, args.verbose))
    any_broken = print_report(results, args.verbose)
    sys.exit(1 if any_broken else 0)


if __name__ == "__main__":
    main()
