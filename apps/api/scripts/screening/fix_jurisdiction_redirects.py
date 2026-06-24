#!/usr/bin/env python3
"""
Fix redirected URLs in jurisdiction YAML files.

For every url: field that returns a 3xx redirect, rewrites the YAML to use
the final destination URL. Only modifies files with at least one redirect.
Broken (4xx/5xx) URLs are reported but NOT modified — those need manual research.

Usage:
    python scripts/screening/fix_jurisdiction_redirects.py [--dry-run] [--timeout 15]

--dry-run  Print changes without writing them.
"""
import argparse
import asyncio
import re
import sys
from pathlib import Path

import httpx
import yaml

DATA_DIR = Path(__file__).resolve().parents[4] / "data" / "jurisdictions"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; CompMap-LinkChecker/1.0; "
        "+https://github.com/open-market)"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

GET_FALLBACK_DOMAINS = {
    "eur-lex.europa.eu", "ftc.gov", "uscode.house.gov",
    "ecfr.gov", "legislation.gov.uk", "gov.uk",
}


def needs_get(url: str) -> bool:
    return any(d in url for d in GET_FALLBACK_DOMAINS)


async def resolve_url(
    client: httpx.AsyncClient, url: str, timeout: float
) -> tuple[str, int, int]:
    """Return (final_url, status, redirect_count)."""
    method = "GET" if needs_get(url) else "HEAD"
    try:
        resp = await client.request(
            method, url, headers=HEADERS, follow_redirects=True, timeout=timeout
        )
        if resp.status_code == 405 and method == "HEAD":
            resp = await client.get(
                url, headers=HEADERS, follow_redirects=True, timeout=timeout
            )
        return str(resp.url), resp.status_code, len(resp.history)
    except Exception:
        return url, 0, 0


async def resolve_all(
    url_map: dict[str, None], timeout: float, concurrency: int = 20
) -> dict[str, tuple[str, int, int]]:
    """Resolve all unique URLs; return {original_url: (final_url, status, redirects)}."""
    sem = asyncio.Semaphore(concurrency)
    results: dict[str, tuple[str, int, int]] = {}

    async def bounded(url: str) -> None:
        async with sem:
            results[url] = await resolve_url(client, url, timeout)

    limits = httpx.Limits(max_connections=concurrency, max_keepalive_connections=10)
    async with httpx.AsyncClient(limits=limits) as client:
        tasks = [bounded(url) for url in url_map]
        total = len(tasks)
        done = 0
        for coro in asyncio.as_completed(tasks):
            await coro
            done += 1
            print(f"\r  Resolving... {done}/{total}", end="", flush=True)
    print()
    return results


def extract_urls_from_yaml(text: str) -> list[str]:
    """Find all url: values in YAML text (preserves order, may have duplicates)."""
    return re.findall(r'(?:^|\s)(?:url|source_url|filing_url|document_url|legislation_url|concentration_definition_url|substantive_test_url|legal_basis_url):\s+"?(https?://[^\s"\']+)"?', text)


def apply_replacements(text: str, replacements: dict[str, str]) -> str:
    """Replace old URLs with new URLs in raw YAML text."""
    for old, new in replacements.items():
        if old == new:
            continue
        text = text.replace(f'"{old}"', f'"{new}"')
        text = text.replace(f"'{old}'", f"'{new}'")
        # unquoted
        text = text.replace(old, new)
    return text


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--jurisdiction", "-j")
    args = parser.parse_args()

    yaml_files = sorted(DATA_DIR.glob("*.yaml"))
    if args.jurisdiction:
        yaml_files = [f for f in yaml_files if f.stem == args.jurisdiction]

    # Collect all unique URLs
    all_urls: set[str] = set()
    file_texts: dict[Path, str] = {}
    for path in yaml_files:
        if path.name.startswith("_"):
            continue
        text = path.read_text()
        file_texts[path] = text
        for url in re.findall(r'https?://[^\s"\'\n>]+', text):
            all_urls.add(url.rstrip(",;)"))

    print(f"Resolving {len(all_urls)} unique URLs...")
    resolved = asyncio.run(resolve_all({u: None for u in all_urls}, args.timeout))

    # Separate into redirected vs broken vs ok
    redirected = {orig: final for orig, (final, status, hops) in resolved.items()
                  if hops > 0 and 200 <= status < 400 and final != orig}
    broken = {orig: status for orig, (_, status, _) in resolved.items()
              if status == 0 or status >= 400}

    print(f"\nRedirected (will fix): {len(redirected)}")
    print(f"Broken (skipped):      {len(broken)}")
    print()

    fixed_files = 0
    total_replacements = 0

    for path, text in file_texts.items():
        # Find URLs in this file that are redirected
        file_urls = set(re.findall(r'https?://[^\s"\'\n>]+', text))
        file_redirects = {u.rstrip(",;)"): redirected[u.rstrip(",;)")]
                          for u in file_urls if u.rstrip(",;)") in redirected}

        if not file_redirects:
            continue

        new_text = apply_replacements(text, file_redirects)
        if new_text == text:
            continue

        fixed_files += 1
        total_replacements += len(file_redirects)
        jid = path.stem

        print(f"[{jid}] {len(file_redirects)} redirect(s) to fix:")
        for old, new in file_redirects.items():
            print(f"  - {old}")
            print(f"  + {new}")

        if not args.dry_run:
            path.write_text(new_text)
            print(f"  => written")
        else:
            print(f"  => (dry run, not written)")
        print()

    print(f"{'DRY RUN — ' if args.dry_run else ''}Fixed {total_replacements} redirected URLs in {fixed_files} files")

    if broken:
        print(f"\nBroken URLs still need manual fixes ({len(broken)} total).")
        print("Run verify_jurisdiction_urls.py for the full breakdown.")


if __name__ == "__main__":
    main()
