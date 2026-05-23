#!/usr/bin/env python3
"""
QA utility — checks all source URLs in YAML case records for HTTP status,
content-type, and redirects. Does not modify any data. Exit 0 if all OK,
exit 1 if any broken links found.

Usage:
    python scripts/check_source_links.py [--timeout 10] [--verbose]
"""
import argparse
import sys
from pathlib import Path

import httpx
import yaml


DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "cases"

HEADERS = {
    "User-Agent": "CompMap-LinkChecker/1.0 (open-source research tool; contact: open-market)",
}


def collect_urls(record: dict) -> list[tuple[str, str]]:
    """Return (url, label) pairs from a case record dict."""
    pairs: list[tuple[str, str]] = []
    case_id = record.get("case_id", "?")

    for doc in record.get("source_documents", []):
        doc_id = doc.get("doc_id", "?")
        for field in ("pdf_url", "case_page_url", "url"):
            val = doc.get(field)
            if val:
                pairs.append((val, f"{case_id} / {doc_id} / {field}"))

    for event in record.get("case_history", {}).get("events", []) if record.get("case_history") else []:
        val = event.get("source_url")
        if val:
            pairs.append((val, f"{case_id} / case_history event / {event.get('event_type', '?')}"))

    return pairs


def check_url(client: httpx.Client, url: str, timeout: int) -> dict:
    try:
        r = client.head(url, follow_redirects=True, timeout=timeout, headers=HEADERS)
        # Some servers reject HEAD; retry with GET if 405 or 4xx
        if r.status_code in (405, 403, 400):
            r = client.get(url, follow_redirects=True, timeout=timeout, headers=HEADERS)
        return {
            "status": r.status_code,
            "ok": r.status_code < 400,
            "content_type": r.headers.get("content-type", ""),
            "final_url": str(r.url),
            "redirected": str(r.url) != url,
            "error": None,
        }
    except httpx.TimeoutException:
        return {"status": None, "ok": False, "content_type": "", "final_url": url, "redirected": False, "error": "timeout"}
    except httpx.RequestError as e:
        return {"status": None, "ok": False, "content_type": "", "final_url": url, "redirected": False, "error": str(e)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Check source URLs in CompMap YAML case files")
    parser.add_argument("--timeout", type=int, default=15, help="Request timeout in seconds (default: 15)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Print results for all URLs, not just failures")
    args = parser.parse_args()

    yaml_files = sorted(DATA_DIR.rglob("*.yaml"))
    if not yaml_files:
        print(f"No YAML files found under {DATA_DIR}", file=sys.stderr)
        return 1

    all_pairs: list[tuple[str, str]] = []
    for path in yaml_files:
        with open(path) as f:
            record = yaml.safe_load(f)
        all_pairs.extend(collect_urls(record))

    if not all_pairs:
        print("No URLs found in any case record.")
        return 0

    print(f"Checking {len(all_pairs)} URL(s) across {len(yaml_files)} case file(s) …\n")

    broken: list[tuple[str, str, dict]] = []

    with httpx.Client(follow_redirects=True) as client:
        for url, label in all_pairs:
            result = check_url(client, url, args.timeout)
            ok_marker = "✓" if result["ok"] else "✗"

            if args.verbose or not result["ok"]:
                status_str = str(result["status"]) if result["status"] else result["error"]
                redirect_note = f" → {result['final_url']}" if result["redirected"] else ""
                ct = f"  [{result['content_type'].split(';')[0].strip()}]" if result["content_type"] else ""
                print(f"  {ok_marker} [{status_str}]{ct}{redirect_note}")
                print(f"    {label}")
                print(f"    {url}")
                print()

            if not result["ok"]:
                broken.append((url, label, result))

    if broken:
        print(f"BROKEN LINKS ({len(broken)}):")
        for url, label, res in broken:
            err = res["error"] or res["status"]
            print(f"  ✗ {err}  {label}")
            print(f"    {url}")
        return 1

    print(f"All {len(all_pairs)} link(s) OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
