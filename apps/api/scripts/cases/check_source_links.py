#!/usr/bin/env python3
"""
QA utility — checks all source URLs in YAML case records for HTTP status,
content-type, and redirects. Does not modify any data. Exit 0 if all OK,
exit 1 if any broken links found.

Court-opinion policy: for doc_type=court_opinion, a failing case_page_url is
downgraded to a warning (not an error) when the same document's pdf_url passes.
The PDF is the authoritative source; case_page_url is navigation metadata only.

Usage:
    python scripts/cases/check_source_links.py [--timeout 10] [--verbose]
"""
import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import httpx
import yaml


DATA_DIR = Path(__file__).resolve().parents[4] / "data" / "cases"

HEADERS = {
    "User-Agent": "Meridian-LinkChecker/1.0 (open-source research tool; contact: open-market)",
}


@dataclass
class UrlSpec:
    url: str
    label: str
    doc_type: str   # e.g. "court_opinion", "merger_decision", ""
    field: str      # "pdf_url", "case_page_url", "url", etc.
    doc_key: str    # "{case_id}/{doc_id}" for per-doc grouping


def collect_url_specs(record: dict) -> list[UrlSpec]:
    """Return UrlSpec entries for every URL in a case record."""
    specs: list[UrlSpec] = []
    case_id = record.get("case_id", "?")

    for doc in record.get("source_documents", []):
        doc_id = doc.get("doc_id", "?")
        doc_type = doc.get("doc_type", "")
        doc_key = f"{case_id}/{doc_id}"
        for fld in ("pdf_url", "case_page_url", "url"):
            val = doc.get(fld)
            if val:
                specs.append(UrlSpec(
                    url=val,
                    label=f"{case_id} / {doc_id} / {fld}",
                    doc_type=doc_type,
                    field=fld,
                    doc_key=doc_key,
                ))

    for event in (record.get("case_history") or {}).get("events") or []:
        val = event.get("source_url")
        if val:
            specs.append(UrlSpec(
                url=val,
                label=f"{case_id} / case_history event / {event.get('event_type', '?')}",
                doc_type="",
                field="source_url",
                doc_key=f"{case_id}/_history",
            ))

    return specs


def collect_urls(record: dict) -> list[tuple[str, str]]:
    """Compatibility shim: return (url, label) pairs. Used by tests."""
    return [(s.url, s.label) for s in collect_url_specs(record)]


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


def _is_court_opinion_case_page(spec: UrlSpec) -> bool:
    return spec.doc_type == "court_opinion" and spec.field == "case_page_url"


def classify_results(
    results: list[tuple[UrlSpec, dict]],
) -> tuple[list[tuple[UrlSpec, dict]], list[tuple[UrlSpec, dict]]]:
    """
    Split results into (errors, warnings).

    Court-opinion policy: if a court_opinion case_page_url fails but the same
    doc's pdf_url passed, downgrade to a warning rather than an error.
    """
    # Build a set of doc_keys whose pdf_url passed
    pdf_passed: set[str] = {
        spec.doc_key
        for spec, res in results
        if spec.field == "pdf_url" and res["ok"]
    }

    errors: list[tuple[UrlSpec, dict]] = []
    warnings: list[tuple[UrlSpec, dict]] = []

    for spec, res in results:
        if res["ok"]:
            continue
        if _is_court_opinion_case_page(spec) and spec.doc_key in pdf_passed:
            warnings.append((spec, res))
        else:
            errors.append((spec, res))

    return errors, warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check source URLs in Meridian YAML case files")
    parser.add_argument("--timeout", type=int, default=15, help="Request timeout in seconds (default: 15)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Print results for all URLs, not just failures")
    args = parser.parse_args(argv)

    yaml_files = sorted(DATA_DIR.rglob("*.yaml"))
    if not yaml_files:
        print(f"No YAML files found under {DATA_DIR}", file=sys.stderr)
        return 1

    all_specs: list[UrlSpec] = []
    for path in yaml_files:
        with open(path) as f:
            record = yaml.safe_load(f)
        all_specs.extend(collect_url_specs(record))

    if not all_specs:
        print("No URLs found in any case record.")
        return 0

    print(f"Checking {len(all_specs)} URL(s) across {len(yaml_files)} case file(s) …\n")

    all_results: list[tuple[UrlSpec, dict]] = []

    with httpx.Client(follow_redirects=True) as client:
        for spec in all_specs:
            result = check_url(client, spec.url, args.timeout)
            all_results.append((spec, result))

            ok_marker = "✓" if result["ok"] else "✗"
            if args.verbose or not result["ok"]:
                status_str = str(result["status"]) if result["status"] else result["error"]
                redirect_note = f" → {result['final_url']}" if result["redirected"] else ""
                ct = f"  [{result['content_type'].split(';')[0].strip()}]" if result["content_type"] else ""
                print(f"  {ok_marker} [{status_str}]{ct}{redirect_note}")
                print(f"    {spec.label}")
                print(f"    {spec.url}")
                print()

    errors, warnings = classify_results(all_results)

    if warnings:
        print(f"WARNINGS ({len(warnings)}) — court_opinion case_page_url(s) failed but pdf_url passed; not blocking:")
        for spec, res in warnings:
            err = res["error"] or res["status"]
            print(f"  ⚠ {err}  {spec.label}")
            print(f"    {spec.url}")
            print("    court_opinion case_page_url failed, but pdf_url passed; not blocking")
        print()

    if errors:
        print(f"BROKEN LINKS ({len(errors)}):")
        for spec, res in errors:
            err = res["error"] or res["status"]
            print(f"  ✗ {err}  {spec.label}")
            print(f"    {spec.url}")
        return 1

    total = len(all_specs)
    warn_note = f" ({len(warnings)} warning(s))" if warnings else ""
    print(f"All {total} link(s) OK{warn_note}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
