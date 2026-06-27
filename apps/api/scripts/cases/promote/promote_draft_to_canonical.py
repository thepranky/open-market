#!/usr/bin/env python3
"""
promote_draft_to_canonical.py — Convert a reviewed draft to a canonical case record.

Reads data/drafts/{jurisdiction}/{case_id}.{focus}.draft.yaml (or an explicit path
via --draft), merges it with the existing seed/canonical at
data/cases/{jurisdiction}/{case_id}.yaml, strips draft-only fields, adds required
canonical fields, validates against the Pydantic CaseRecord schema, and writes the
result.

Usage:
    # Promote an orchestrator-produced merged draft (explicit path)
    apps/api/.venv/bin/python apps/api/scripts/cases/promote/promote_draft_to_canonical.py \\
        --case-id eu_booking_etraveli_2023 \\
        --draft data/drafts/eu/eu_booking_etraveli_2023.merged.draft.yaml \\
        --overwrite

    # Promote using seed metadata already in data/cases/ (focus-based lookup)
    apps/api/.venv/bin/python apps/api/scripts/cases/promote/promote_draft_to_canonical.py \\
        --case-id eu_facebook_whatsapp_2014 \\
        --focus market_definition

    # Pass procedure_stage explicitly when the seed does not have it
    apps/api/.venv/bin/python apps/api/scripts/cases/promote/promote_draft_to_canonical.py \\
        --case-id eu_facebook_whatsapp_2014 \\
        --focus market_definition \\
        --procedure-stage phase1

    # Dry run — print result, do not write
    apps/api/.venv/bin/python apps/api/scripts/cases/promote/promote_draft_to_canonical.py \\
        --case-id eu_facebook_whatsapp_2014 \\
        --focus market_definition \\
        --dry-run

    # Overwrite an existing canonical record
    apps/api/.venv/bin/python apps/api/scripts/cases/promote/promote_draft_to_canonical.py \\
        --case-id eu_facebook_whatsapp_2014 \\
        --focus market_definition \\
        --overwrite

    # Write to a custom path
    apps/api/.venv/bin/python apps/api/scripts/cases/promote/promote_draft_to_canonical.py \\
        --case-id eu_facebook_whatsapp_2014 \\
        --focus market_definition \\
        --output /tmp/eu_facebook_whatsapp_2014.yaml
"""

import argparse
import datetime
import sys
from pathlib import Path
from typing import Optional

import yaml

_SCRIPTS_DIR = Path(__file__).resolve().parent
_API_DIR = _SCRIPTS_DIR.parent.parent.parent
_REPO_ROOT = _API_DIR.parents[1]

sys.path.insert(0, str(_API_DIR))


# ---------------------------------------------------------------------------
# Fields that belong only in drafts
# ---------------------------------------------------------------------------

# Top-level keys the extraction pipeline adds that have no place in canonical records.
_DRAFT_TOP_STRIP: frozenset[str] = frozenset({"_draft_note"})

# Keys on ProductMarket / GeographicMarket entries that the pipeline adds.
_DRAFT_MARKET_STRIP: frozenset[str] = frozenset({"verification", "market_importance"})

# Keys on SourcePassage entries that the pipeline adds.
_DRAFT_PASSAGE_STRIP: frozenset[str] = frozenset({"source_role"})

# ---------------------------------------------------------------------------
# Fields that should come from the seed/canonical file, not the draft.
# (Case-level metadata set by the human curator, not by AI extraction.)
# ---------------------------------------------------------------------------

_SEED_PRIORITY_FIELDS: frozenset[str] = frozenset({
    "procedure_stage",
    "case_type",
    "authority_reference",
    "metadata",
    "remedies",
    "case_history",
    "ai_summary",
    "similar_cases",
    "decision_date",  # always prefer the human-curated date from the case index
})

# LLM sometimes produces definition_status values outside the enum.
# Map them to the nearest valid value rather than failing promotion.
_DEFINITION_STATUS_REMAP: dict[str, str] = {
    "precedent_only":      "considered",
    "not_conclusive":      "left_open",
    "assessed_no_overlap": "considered",
    "unknown":             "considered",
    "possible_segmentation": "discussed",
    "not_appropriate":     "considered",
    "incomplete_source":   "considered",
    "background":          "considered",
}

# List fields where the seed value is preferred when the seed has a non-empty
# list but the draft has an empty or absent list.  This prevents a new AI
# draft from silently wiping human-reviewed content that was added after the
# original extraction (e.g. theories_of_harm added post-promotion).
# When both draft and seed are non-empty the draft wins (newer extraction).
_SEED_NONEMPTY_FALLBACK_FIELDS: frozenset[str] = frozenset({
    "theories_of_harm",
})

# ---------------------------------------------------------------------------
# YAML output helpers
# ---------------------------------------------------------------------------

class _CanonicalDumper(yaml.SafeDumper):
    """SafeDumper with block-scalar strings and ISO-formatted dates."""


def _str_representer(dumper: yaml.SafeDumper, data: str) -> yaml.ScalarNode:
    if "\n" in data:
        # Block scalar only for strings that contain real newlines.
        # Single-line strings — including long URLs — are left to yaml.dump's
        # natural word-wrapping so no spurious trailing newline is introduced
        # on YAML round-trip (the old len>80 path caused httpx.InvalidURL).
        cleaned = "\n".join(line.rstrip() for line in data.splitlines()).rstrip() + "\n"
        return dumper.represent_scalar("tag:yaml.org,2002:str", cleaned, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


def _date_representer(dumper: yaml.SafeDumper, data: datetime.date) -> yaml.ScalarNode:
    return dumper.represent_scalar("tag:yaml.org,2002:str", data.isoformat())


_CanonicalDumper.add_representer(str, _str_representer)
_CanonicalDumper.add_representer(datetime.date, _date_representer)


def _dump_canonical_yaml(data: dict) -> str:
    return yaml.dump(
        data,
        Dumper=_CanonicalDumper,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
        width=90,
    )

# ---------------------------------------------------------------------------
# Path resolution helpers
# ---------------------------------------------------------------------------

def find_draft(case_id: str, focus: str, drafts_dir: Path) -> Optional[Path]:
    """Return the draft path by searching all jurisdiction sub-directories."""
    filename = f"{case_id}.{focus}.draft.yaml"
    for p in drafts_dir.rglob(filename):
        if not any(".draft" in part for part in p.parent.parts):
            return p
    return None


def find_canonical(case_id: str, cases_dir: Path) -> Optional[Path]:
    """Return the canonical YAML path for case_id, or None if not found."""
    for p in cases_dir.rglob(f"{case_id}.yaml"):
        if p.stem != case_id:
            continue
        if any(".draft" in part for part in p.parts):
            continue
        return p
    return None


def _canonical_output_path(draft_path: Path, cases_dir: Path, case_id: str) -> Path:
    """Derive the default canonical output path from the draft's jurisdiction directory."""
    # draft_path: .../data/drafts/eu/eu_xxx.yyy.draft.yaml
    # output:     .../data/cases/eu/eu_xxx.yaml
    jurisdiction = draft_path.parent.name
    return cases_dir / jurisdiction / f"{case_id}.yaml"

# ---------------------------------------------------------------------------
# Transformation
# ---------------------------------------------------------------------------

def _strip_draft_fields_inplace(record: dict) -> None:
    """Mutate *record* in-place: remove all draft-only keys."""
    for key in _DRAFT_TOP_STRIP:
        record.pop(key, None)

    for markets_key in ("product_markets_considered", "geographic_markets_considered"):
        for market in record.get(markets_key) or []:
            for field in _DRAFT_MARKET_STRIP:
                market.pop(field, None)

    for passage in record.get("source_passages") or []:
        for field in _DRAFT_PASSAGE_STRIP:
            passage.pop(field, None)


def _apply_seed_fields(record: dict, seed: dict) -> None:
    """Mutate *record* in-place: overlay seed values for metadata-priority fields."""
    for field in _SEED_PRIORITY_FIELDS:
        if field in seed:
            record[field] = seed[field]


def _apply_seed_nonempty_fallbacks(record: dict, seed: dict) -> None:
    """Mutate *record* in-place: use seed list when draft list is empty/absent.

    For fields in _SEED_NONEMPTY_FALLBACK_FIELDS: if the seed has a non-empty
    list but the draft produced an empty (or missing) list, keep the seed value
    so human-reviewed content is not silently wiped.
    """
    for field in _SEED_NONEMPTY_FALLBACK_FIELDS:
        seed_val = seed.get(field)
        if seed_val:  # non-empty list in seed
            draft_val = record.get(field)
            if not draft_val:  # draft is empty or absent
                record[field] = seed_val


def _normalize_draft_inplace(record: dict) -> None:
    """Remap LLM hallucinations to valid enum values so validation passes."""
    _valid_ds = {"defined", "discussed", "segmented", "left_open", "considered"}
    for key in ("product_markets_considered", "geographic_markets_considered"):
        for market in record.get(key) or []:
            ds = market.get("definition_status")
            if ds and ds not in _valid_ds:
                market["definition_status"] = _DEFINITION_STATUS_REMAP.get(ds, "considered")


def check_draft_warnings(draft: dict) -> list[str]:
    """Return a list of human-readable warnings about quality issues in *draft*.

    These are emitted before promotion so the operator can decide whether to
    proceed or fix the draft first.  They do not block promotion.
    """
    warnings: list[str] = []

    not_set_passages = [
        p.get("passage_id", "<unknown>")
        for p in (draft.get("source_passages") or [])
        if p.get("source_role") == "not_set"
    ]
    if not_set_passages:
        ids = ", ".join(not_set_passages)
        warnings.append(
            f"WARNING: {len(not_set_passages)} passage(s) have source_role=not_set "
            f"({ids}). Assign roles before promotion or accept unclassified evidence."
        )

    untranslated_non_english = [
        p.get("passage_id", "<unknown>")
        for p in (draft.get("source_passages") or [])
        if p.get("source_language") and p.get("source_language") != "eng"
        and not p.get("quote_translation")
    ]
    if untranslated_non_english:
        ids = ", ".join(untranslated_non_english)
        warnings.append(
            f"WARNING: {len(untranslated_non_english)} non-English passage(s) are missing "
            f"quote_translation ({ids}). Verbatim quote_snippet remains authoritative."
        )

    return warnings


def _ensure_metadata(record: dict, today: str) -> None:
    """Add a default metadata block if none is present (cannot be inferred from draft)."""
    if "metadata" not in record:
        record["metadata"] = {
            "extraction_method": "ai_extracted",
            "review_status": "unreviewed",
            "overall_confidence": 0.7,
            "created_date": today,
            "last_updated_date": today,
            "tags": [],
        }


def build_canonical(
    draft: dict,
    seed: Optional[dict],
    *,
    procedure_stage_override: Optional[str],
    today: str,
) -> dict:
    """
    Return a new canonical-ready dict derived from *draft* and *seed*.

    Raises ValueError listing all missing required fields if the result cannot
    be validated.
    """
    result: dict = {}
    result.update(draft)

    # Overlay seed values for human-curated metadata fields.
    if seed:
        _apply_seed_fields(result, seed)
        # Preserve non-empty seed lists when the draft produced an empty result.
        _apply_seed_nonempty_fallbacks(result, seed)

    # CLI override always wins for procedure_stage.
    if procedure_stage_override:
        result["procedure_stage"] = procedure_stage_override

    # Normalize LLM hallucinations to valid enum values.
    _normalize_draft_inplace(result)

    # Strip draft-only fields.
    _strip_draft_fields_inplace(result)

    # Fill in metadata default if not present (from seed or otherwise).
    _ensure_metadata(result, today)

    # Check required fields that cannot have safe defaults.
    missing = [f for f in ("procedure_stage",) if not result.get(f)]
    if missing:
        raise ValueError(
            f"Required canonical fields are missing and could not be inferred: "
            f"{missing}.\n"
            "Provide them in the seed YAML at data/cases/, or pass "
            "--procedure-stage on the command line."
        )

    return result


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_canonical_dict(record: dict) -> tuple[bool, str]:
    """
    Validate *record* against the Pydantic CaseRecord model.

    Returns (ok, error_message).  error_message is empty when ok is True.
    """
    try:
        from app.cases.models import CaseRecord
        CaseRecord.model_validate(record)
        return True, ""
    except Exception as exc:
        return False, str(exc)

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Promote a reviewed draft to a canonical case record.",
    )
    parser.add_argument("--case-id", required=True,
                        help="Case ID (e.g. eu_facebook_whatsapp_2014)")
    parser.add_argument("--draft",
                        help="Explicit path to the draft YAML to promote. "
                             "When supplied, --focus is ignored for draft lookup.")
    parser.add_argument("--focus", default="market_definition",
                        help="Extraction focus (default: market_definition). "
                             "Ignored when --draft is supplied.")
    parser.add_argument("--procedure-stage",
                        help="Override procedure_stage (phase1 | phase2). "
                             "Required when the seed does not have it.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the canonical YAML without writing to disk.")
    parser.add_argument("--output",
                        help="Custom output path (default: data/cases/{jur}/{case_id}.yaml)")
    parser.add_argument("--overwrite", action="store_true",
                        help="Overwrite the canonical file if it already exists.")
    parser.add_argument("--drafts-dir", default=str(_REPO_ROOT / "data" / "drafts"),
                        help="Root directory for draft files.")
    parser.add_argument("--cases-dir", default=str(_REPO_ROOT / "data" / "cases"),
                        help="Root directory for canonical case files.")
    args = parser.parse_args(argv)

    drafts_dir = Path(args.drafts_dir)
    cases_dir = Path(args.cases_dir)
    today = datetime.date.today().isoformat()

    # ------------------------------------------------------------------
    # 1. Locate draft
    # ------------------------------------------------------------------
    if args.draft:
        draft_path = Path(args.draft)
        if not draft_path.is_absolute():
            draft_path = _REPO_ROOT / draft_path
        if not draft_path.exists():
            print(
                f"ERROR: Explicit draft path does not exist: {args.draft}",
                file=sys.stderr,
            )
            return 1
    else:
        draft_path = find_draft(args.case_id, args.focus, drafts_dir)
        if draft_path is None:
            print(
                f"ERROR: No draft found for '{args.case_id}' (focus={args.focus}) "
                f"under {drafts_dir}",
                file=sys.stderr,
            )
            return 1

    draft = yaml.safe_load(draft_path.read_text(encoding="utf-8"))
    print(f"Draft:     {draft_path}")

    # ------------------------------------------------------------------
    # 1b. Draft quality warnings (non-blocking)
    # ------------------------------------------------------------------
    for w in check_draft_warnings(draft):
        print(f"\n{w}", file=sys.stderr)

    # ------------------------------------------------------------------
    # 2. Locate seed / existing canonical (optional)
    # ------------------------------------------------------------------
    canonical_path = find_canonical(args.case_id, cases_dir)
    seed: Optional[dict] = None
    if canonical_path:
        seed = yaml.safe_load(canonical_path.read_text(encoding="utf-8"))
        print(f"Seed:      {canonical_path}")
    else:
        # Fall back to the case_index entry so metadata fields like decision_date
        # and parties are always populated even on first promotion.
        index_root = _REPO_ROOT / "data" / "case_index"
        jur = args.case_id.split("_")[0]
        index_path = index_root / jur / f"{args.case_id}.yaml"
        if index_path.exists():
            seed = yaml.safe_load(index_path.read_text(encoding="utf-8"))
            print(f"Seed:      {index_path}  (case_index fallback)")
        else:
            print("Seed:      (none)")

    # ------------------------------------------------------------------
    # 3. Determine output path
    # ------------------------------------------------------------------
    if args.output:
        out_path = Path(args.output)
    elif canonical_path:
        out_path = canonical_path
    else:
        out_path = _canonical_output_path(draft_path, cases_dir, args.case_id)

    print(f"Output:    {out_path}")
    print()

    # ------------------------------------------------------------------
    # 4. Safety gate: refuse to overwrite without --overwrite
    # ------------------------------------------------------------------
    if not args.dry_run and out_path.exists() and not args.overwrite:
        print(
            f"ERROR: {out_path} already exists. "
            "Pass --overwrite to replace it.",
            file=sys.stderr,
        )
        return 1

    # ------------------------------------------------------------------
    # 5. Build canonical record
    # ------------------------------------------------------------------
    try:
        canonical = build_canonical(
            draft,
            seed,
            procedure_stage_override=args.procedure_stage,
            today=today,
        )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    # ------------------------------------------------------------------
    # 6. Validate against Pydantic model
    # ------------------------------------------------------------------
    ok, error_msg = validate_canonical_dict(canonical)
    if not ok:
        print(f"ERROR: Pydantic validation failed:\n{error_msg}", file=sys.stderr)
        return 1

    print("Validation: PASS")

    # ------------------------------------------------------------------
    # 7. Write (or print for dry-run)
    # ------------------------------------------------------------------
    yaml_text = _dump_canonical_yaml(canonical)

    if args.dry_run:
        print("\n--- DRY RUN — canonical YAML (not written) ---\n")
        print(yaml_text)
        return 0

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(yaml_text, encoding="utf-8")
    print(f"Written:   {out_path}")

    # ------------------------------------------------------------------
    # 8. Quick summary
    # ------------------------------------------------------------------
    pms = len(canonical.get("product_markets_considered") or [])
    gms = len(canonical.get("geographic_markets_considered") or [])
    ths = len(canonical.get("theories_of_harm") or [])
    sps = len(canonical.get("source_passages") or [])
    print(
        f"\nSummary:   {pms} product market(s), {gms} geographic market(s), "
        f"{ths} theory/ies, {sps} passage(s)"
    )
    print("\nPromotion complete. Run the post-promotion checks:")
    print("  apps/api/.venv/bin/python apps/api/scripts/cases/integrity/validate_cases.py")
    print("  apps/api/.venv/bin/python apps/api/scripts/cases/integrity/check_source_integrity.py --no-cache")

    return 0


if __name__ == "__main__":
    sys.exit(main())
