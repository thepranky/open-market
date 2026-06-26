#!/usr/bin/env python3
"""
merge_drafts.py — Merge multiple partial extraction drafts into one reviewable draft.

Reads two or more draft YAMLs for the same case_id, deduplicates records,
rewrites cross-reference IDs, and writes a single merged draft YAML.

Does NOT promote to canonical. Does NOT modify data/cases/.

Usage:
    apps/api/.venv/bin/python apps/api/scripts/cases/extract/merge_drafts.py \\
        data/drafts/eu/eu_bayer_monsanto_2018.outcome_metadata.outcome_pp1_30_v3.draft.yaml \\
        data/drafts/eu/eu_bayer_monsanto_2018.theories.theories_innovation_process_382.draft.yaml \\
        data/drafts/eu/eu_bayer_monsanto_2018.remedies.remedies_vegseeds_basf_adequacy_803.draft.yaml

    # Dry run — print merged YAML, do not write
    ... --dry-run

    # Custom output path
    ... --output /tmp/merged.yaml

    # Validate that all drafts match a specific case ID
    ... --case-id eu_bayer_monsanto_2018
"""

import argparse
import datetime
import re
import sys
from pathlib import Path
from typing import Any, Optional

import yaml

_SCRIPTS_DIR = Path(__file__).resolve().parent
_API_DIR = _SCRIPTS_DIR.parent.parent.parent
_REPO_ROOT = _API_DIR.parents[1]

sys.path.insert(0, str(_API_DIR))
sys.path.insert(0, str(_SCRIPTS_DIR))  # flat import of sibling compare_extractions

# ---------------------------------------------------------------------------
# YAML output helpers (shared with promote_draft_to_canonical)
# ---------------------------------------------------------------------------

class _MergedDumper(yaml.SafeDumper):
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


_MergedDumper.add_representer(str, _str_representer)
_MergedDumper.add_representer(datetime.date, _date_representer)


def _dump_yaml(data: dict) -> str:
    return yaml.dump(
        data,
        Dumper=_MergedDumper,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
        width=90,
    )

# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------

def _norm(text: str) -> str:
    """Lowercase, collapse whitespace, strip leading/trailing space."""
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def _passage_key(p: dict) -> tuple:
    """Dedup key for a source passage."""
    return (
        _norm(p.get("quote_snippet", ""))[:160],
        str(p.get("page", "") or "").strip(),
        str(p.get("source_document_id", "") or "").strip(),
    )


def _theory_key(t: dict) -> tuple:
    """Dedup key for a theory_of_harm."""
    return (
        _norm(t.get("name", ""))[:80],
        str(t.get("theory_type", "") or "").strip().lower(),
    )


def _commitment_key(c: dict) -> tuple:
    """Dedup key for a commitment."""
    return (
        _norm(c.get("title", ""))[:80],
        str(c.get("commitment_type", "") or "").strip().lower(),
    )


def _market_key(m: dict) -> str:
    """Dedup key for a product or geographic market."""
    return _norm(m.get("name", ""))[:80]


def _unit_key(u: dict) -> tuple:
    """Dedup key for a unit_assessment — (unit_type, normalized unit_label)."""
    return (
        str(u.get("unit_type", "") or "").strip().lower(),
        _norm(u.get("unit_label", ""))[:80],
    )


def _finding_key(f: dict) -> tuple:
    """Dedup key for a finding within a unit_assessment."""
    return (
        str(f.get("finding_type", "") or "").strip().lower(),
        _norm(f.get("segment", ""))[:80],
        _norm(f.get("geography", ""))[:40],
        str(f.get("conclusion", "") or "").strip().lower(),
    )

# ---------------------------------------------------------------------------
# ID map
# ---------------------------------------------------------------------------

class _IdMap:
    """Track (draft_idx, old_id) -> new_global_id."""

    def __init__(self) -> None:
        self._map: dict[tuple[int, str], str] = {}

    def register(self, draft_idx: int, old_id: str, new_id: str) -> None:
        self._map[(draft_idx, old_id)] = new_id

    def get(self, draft_idx: int, old_id: str) -> str:
        return self._map.get((draft_idx, old_id), old_id)

    def rewrite_list(self, draft_idx: int, ids: list) -> list:
        seen: set = set()
        out: list = []
        for old in ids or []:
            new = self.get(draft_idx, str(old))
            if new not in seen:
                seen.add(new)
                out.append(new)
        return out

# ---------------------------------------------------------------------------
# Metadata helpers
# ---------------------------------------------------------------------------

_UNKNOWN_SENTINELS = frozenset({"unknown", "", None})

def _is_empty(v: Any) -> bool:
    """True if value should be treated as absent/unknown."""
    if v is None:
        return True
    if isinstance(v, str) and v.strip().lower() in _UNKNOWN_SENTINELS:
        return True
    if isinstance(v, list) and len(v) == 0:
        return True
    return False


def _focus_of(path: Path) -> str:
    """Extract focus segment from a draft filename.

    e.g. eu_bayer_monsanto_2018.outcome_metadata.outcome_pp1_30.draft.yaml
         -> outcome_metadata
    """
    stem = path.name  # e.g. "eu_bayer_monsanto_2018.outcome_metadata.foo.draft.yaml"
    # Remove trailing ".draft.yaml"
    if stem.endswith(".draft.yaml"):
        stem = stem[: -len(".draft.yaml")]
    parts = stem.split(".")
    # parts[0] = case_id, parts[1] = focus, parts[2...] = sub-focus
    if len(parts) >= 2:
        return parts[1]
    return ""


def _pick_metadata(drafts: list[dict], paths: list[Path]) -> dict:
    """Return merged scalar metadata, preferring outcome_metadata drafts."""
    outcome_meta_idxs = [
        i for i, p in enumerate(paths)
        if _focus_of(p) == "outcome_metadata"
    ]

    scalar_fields = [
        "case_name", "authority", "jurisdiction", "sector",
        "outcome", "procedure_stage", "decision_date", "authority_reference",
    ]
    # Fields where outcome_metadata draft wins
    outcome_priority_fields = frozenset({
        "outcome", "procedure_stage", "decision_date", "authority_reference",
    })

    result: dict = {}

    for field in scalar_fields:
        # Try outcome_metadata drafts first for priority fields
        if field in outcome_priority_fields and outcome_meta_idxs:
            for i in outcome_meta_idxs:
                v = drafts[i].get(field)
                if not _is_empty(v):
                    result[field] = v
                    break

        # Fall back to first non-empty value across all drafts
        if field not in result or _is_empty(result.get(field)):
            for d in drafts:
                v = d.get(field)
                if not _is_empty(v):
                    result[field] = v
                    break

    # parties: prefer outcome_metadata draft, else first non-empty
    for i in (outcome_meta_idxs or range(len(drafts))):
        parties = drafts[i].get("parties")
        if parties:
            result["parties"] = parties
            break
    if "parties" not in result:
        for d in drafts:
            if d.get("parties"):
                result["parties"] = d["parties"]
                break
    if "parties" not in result:
        result["parties"] = []

    return result

# ---------------------------------------------------------------------------
# Source document merge (dedup by doc_id)
# ---------------------------------------------------------------------------

def _merge_source_documents(drafts: list[dict]) -> list[dict]:
    seen: dict[str, dict] = {}
    for d in drafts:
        for doc in d.get("source_documents") or []:
            doc_id = doc.get("doc_id", "")
            if doc_id not in seen:
                seen[doc_id] = dict(doc)
            else:
                # Fill in any missing fields from duplicate
                for k, v in doc.items():
                    if not _is_empty(v) and _is_empty(seen[doc_id].get(k)):
                        seen[doc_id][k] = v
    return list(seen.values())

# ---------------------------------------------------------------------------
# Record deduplication
# ---------------------------------------------------------------------------

def _merge_records(
    items: list[tuple[int, dict]],
    key_fn,
    prefix: str,
    id_field: str,
    id_map: _IdMap,
    warnings: list[str],
    *,
    union_fields: Optional[list[str]] = None,
    per_draft_ref_fields: Optional[list[str]] = None,
    description_field: Optional[str] = None,
) -> list[dict]:
    """
    Deduplicate records, assign new sequential IDs, register in id_map.

    items: [(draft_idx, record_dict), ...]
    key_fn: record -> hashable key
    prefix: 'pm_', 'gm_', 'toh_', 'com_', 'sp_'
    id_field: field name holding the ID ('market_id', 'theory_id', etc.)
    id_map: IdMap to register (draft_idx, old_id) -> new_id
    union_fields: non-ID list fields to union directly (safe to union before rewrite)
    per_draft_ref_fields: ID-reference list fields that must be tracked per draft index
        and rewritten in the cross-ref rewriting phase.  Stored as
        _per_draft_refs_{field}: [(draft_idx, [old_id, ...]), ...] on the merged record.
    description_field: field whose value should be kept as the richer one
    """
    # canonical_key -> (new_id, merged_record)
    canonical: dict[Any, tuple[str, dict]] = {}
    counter = 1
    collapsed = 0

    for draft_idx, rec in items:
        key = key_fn(rec)
        old_id = rec.get(id_field, "")

        if key not in canonical:
            new_id = f"{prefix}{counter}"
            counter += 1
            merged = dict(rec)
            merged[id_field] = new_id
            # Seed the per-draft ref accumulator for each tracked field
            for f in (per_draft_ref_fields or []):
                merged[f"_per_draft_refs_{f}"] = [(draft_idx, list(rec.get(f) or []))]
            canonical[key] = (new_id, merged)
            id_map.register(draft_idx, old_id, new_id)
        else:
            new_id, merged = canonical[key]
            id_map.register(draft_idx, old_id, new_id)
            collapsed += 1

            # Accumulate per-draft ID-reference lists (rewritten later)
            for f in (per_draft_ref_fields or []):
                acc_key = f"_per_draft_refs_{f}"
                merged.setdefault(acc_key, []).append((draft_idx, list(rec.get(f) or [])))

            # Union non-ID list fields directly
            for f in (union_fields or []):
                existing = merged.get(f) or []
                incoming = rec.get(f) or []
                merged_vals = list(existing)
                for v in incoming:
                    if v not in merged_vals:
                        merged_vals.append(v)
                merged[f] = merged_vals

            # Keep richer description
            if description_field:
                existing_desc = merged.get(description_field) or ""
                incoming_desc = rec.get(description_field) or ""
                if len(incoming_desc) > len(existing_desc):
                    merged[description_field] = incoming_desc
                elif incoming_desc and incoming_desc != existing_desc:
                    warnings.append(
                        f"WARN: merged {prefix.rstrip('_')} '{new_id}': "
                        f"conflicting '{description_field}' values — keeping longer."
                    )

            # Fill non-empty scalar/list fields
            for k, v in rec.items():
                if k in (id_field, description_field or ""):
                    continue
                if k in (per_draft_ref_fields or []):
                    continue  # handled separately
                if not _is_empty(v) and _is_empty(merged.get(k)):
                    merged[k] = v

    if collapsed:
        warnings.append(
            f"INFO: {prefix.rstrip('_')}: {collapsed} duplicate(s) collapsed."
        )

    return [rec for _, rec in canonical.values()]


def _merge_passages(
    items: list[tuple[int, dict]],
    id_map: _IdMap,
    warnings: list[str],
) -> list[dict]:
    """Deduplicate passages and track per-draft ID-reference lists for later rewriting."""
    return _merge_records(
        items,
        _passage_key,
        "sp_",
        "passage_id",
        id_map,
        warnings,
        per_draft_ref_fields=[
            "supports_markets",
            "supports_geographic_markets",
            "supports_theories",
            "supports_commitments",
        ],
        description_field=None,
    )


def _merge_theories(
    items: list[tuple[int, dict]],
    id_map: _IdMap,
    warnings: list[str],
) -> list[dict]:
    return _merge_records(
        items,
        _theory_key,
        "toh_",
        "theory_id",
        id_map,
        warnings,
        description_field="description",
    )


def _merge_commitments(
    items: list[tuple[int, dict]],
    id_map: _IdMap,
    warnings: list[str],
) -> list[dict]:
    return _merge_records(
        items,
        _commitment_key,
        "com_",
        "commitment_id",
        id_map,
        warnings,
        union_fields=["divested_assets", "markets_addressed"],
        per_draft_ref_fields=["related_source_passages"],
        description_field="description",
    )


def _merge_markets(
    items: list[tuple[int, dict]],
    id_map: _IdMap,
    prefix: str,
    id_field: str,
    warnings: list[str],
) -> list[dict]:
    return _merge_records(
        items,
        _market_key,
        prefix,
        id_field,
        id_map,
        warnings,
        union_fields=[],
        description_field="notes",
    )


def _merge_unit_assessments(
    items: list[tuple[int, dict]],
    sp_map: _IdMap,
    warnings: list[str],
) -> list[dict]:
    """
    Deduplicate unit_assessments by (unit_type, normalised unit_label).

    - Assigns stable global IDs: unit_1, unit_2, ...
    - Deduplicates findings within each unit by (finding_type, segment, geography, conclusion).
    - Unions findings when the same unit appears in multiple drafts.
    - Rewrites source_passage_refs in findings using sp_map.
    - related_markets and related_theories are string labels — unioned directly.
    - Finding IDs are reassigned sequentially (f_1, f_2, ...) within each merged unit.

    Note: passages do not carry a supports_unit_assessments forward link in the
    current schema, so back-reference synthesis from passages to unit findings is
    not performed here.  The reverse direction (finding → passage via
    source_passage_refs) is rewritten correctly.
    """
    # canonical_key -> {"unit_type", "unit_label", "_unit_idx", "_pending"}
    canonical: dict[tuple, dict] = {}
    unit_counter = 1
    collapsed_units = 0

    for draft_idx, unit in items:
        key = _unit_key(unit)
        if key not in canonical:
            canonical[key] = {
                "unit_type": unit.get("unit_type", ""),
                "unit_label": unit.get("unit_label", ""),
                "_unit_idx": unit_counter,
                "_pending": [(draft_idx, f) for f in (unit.get("findings") or [])],
            }
            unit_counter += 1
        else:
            canonical[key]["_pending"].extend(
                (draft_idx, f) for f in (unit.get("findings") or [])
            )
            collapsed_units += 1

    if collapsed_units:
        warnings.append(
            f"INFO: unit_assessment: {collapsed_units} duplicate unit(s) collapsed."
        )

    result: list[dict] = []
    for key, acc in canonical.items():
        pending: list[tuple[int, dict]] = acc.pop("_pending")
        acc.pop("_unit_idx")

        # Deduplicate findings within this unit
        finding_canonical: dict[tuple, dict] = {}
        finding_counter = 1
        collapsed_findings = 0

        for draft_idx, finding in pending:
            fkey = _finding_key(finding)
            old_refs = list(finding.get("source_passage_refs") or [])
            new_refs = sp_map.rewrite_list(draft_idx, old_refs)

            if fkey not in finding_canonical:
                merged_finding = dict(finding)
                merged_finding["finding_id"] = f"f_{finding_counter}"
                finding_counter += 1
                merged_finding["source_passage_refs"] = new_refs
                finding_canonical[fkey] = merged_finding
            else:
                existing = finding_canonical[fkey]
                collapsed_findings += 1
                # Union source_passage_refs
                seen_refs: set = set(existing["source_passage_refs"])
                for ref in new_refs:
                    if ref not in seen_refs:
                        seen_refs.add(ref)
                        existing["source_passage_refs"].append(ref)
                # Union string-label list fields
                for lf in ("related_markets", "related_theories"):
                    existing_vals = existing.get(lf) or []
                    incoming_vals = finding.get(lf) or []
                    seen_vals: set = set(existing_vals)
                    for v in incoming_vals:
                        if v not in seen_vals:
                            seen_vals.add(v)
                            existing_vals.append(v)
                    existing[lf] = existing_vals
                # Keep richer description
                incoming_desc = finding.get("description") or ""
                if len(incoming_desc) > len(existing.get("description") or ""):
                    existing["description"] = incoming_desc

        if collapsed_findings:
            warnings.append(
                f"INFO: unit_assessment '{acc['unit_label']}': "
                f"{collapsed_findings} duplicate finding(s) collapsed."
            )

        acc["findings"] = list(finding_canonical.values())
        result.append(acc)

    return result


# ---------------------------------------------------------------------------
# Cross-reference rewriting
# ---------------------------------------------------------------------------

_PASSAGE_REF_FIELDS = [
    "supports_markets",
    "supports_geographic_markets",
    "supports_theories",
    "supports_commitments",
]
_COMMITMENT_REF_FIELDS = ["related_source_passages"]


def _rewrite_per_draft_refs(
    record: dict,
    ref_fields: list[str],
    field_maps: dict[str, _IdMap],
) -> None:
    """
    Consume `_per_draft_refs_{field}` accumulators on *record*, rewrite IDs,
    union, and write back to the canonical field name.

    field_maps maps canonical field name -> the _IdMap for that ID type.
    """
    for f in ref_fields:
        acc_key = f"_per_draft_refs_{f}"
        per_draft = record.pop(acc_key, None)
        id_map = field_maps[f]
        if per_draft is None:
            # Field wasn't tracked per-draft (e.g. non-deduplicated record):
            # fall back to the current field value rewritten by _draft_idx.
            di = record.get("_draft_idx", 0)
            old_vals = record.get(f) or []
            record[f] = id_map.rewrite_list(di, old_vals)
        else:
            seen: set = set()
            out: list = []
            for draft_idx, old_ids in per_draft:
                for new_id in id_map.rewrite_list(draft_idx, old_ids):
                    if new_id not in seen:
                        seen.add(new_id)
                        out.append(new_id)
            record[f] = out


def _rewrite_all_refs(
    merged_passages: list[dict],
    merged_commitments: list[dict],
    pm_map: _IdMap,
    gm_map: _IdMap,
    toh_map: _IdMap,
    com_map: _IdMap,
    sp_map: _IdMap,
) -> None:
    """
    Rewrite cross-references in already-merged (globally ID'd) records.

    Each record carries `_per_draft_refs_{field}` accumulators set by
    _merge_records, plus a `_draft_idx` for any non-deduplicated single instance.
    We consume those here and write canonical rewritten ref lists back.
    """
    passage_field_maps = {
        "supports_markets": pm_map,
        "supports_geographic_markets": gm_map,
        "supports_theories": toh_map,
        "supports_commitments": com_map,
    }
    commitment_field_maps = {
        "related_source_passages": sp_map,
    }

    for p in merged_passages:
        _rewrite_per_draft_refs(p, _PASSAGE_REF_FIELDS, passage_field_maps)
        p.pop("_draft_idx", None)

    for c in merged_commitments:
        _rewrite_per_draft_refs(c, _COMMITMENT_REF_FIELDS, commitment_field_maps)
        c.pop("_draft_idx", None)


# ---------------------------------------------------------------------------
# Back-reference synthesis
# ---------------------------------------------------------------------------

def _synthesize_back_refs(
    merged_theories: list[dict],
    merged_commitments: list[dict],
    merged_passages: list[dict],
    warnings: list[str],
) -> None:
    """
    Populate source_passage_refs on theories and related_source_passages on
    commitments from the inverse of passage supports_theories / supports_commitments.

    Extractors write the forward link (passage -> theory/commitment) but omit the
    reverse.  This step synthesises the reverse so consumers can navigate either way.
    Existing explicit refs are preserved; new ones are unioned in.
    """
    # Build passage index: toh_id -> [sp_id, ...]
    toh_to_sps: dict[str, list[str]] = {}
    com_to_sps: dict[str, list[str]] = {}
    for p in merged_passages:
        sp_id = p.get("passage_id", "")
        for toh_id in p.get("supports_theories") or []:
            toh_to_sps.setdefault(toh_id, []).append(sp_id)
        for com_id in p.get("supports_commitments") or []:
            com_to_sps.setdefault(com_id, []).append(sp_id)

    # Populate theory.source_passage_refs
    added_toh = 0
    for t in merged_theories:
        toh_id = t.get("theory_id", "")
        existing = list(t.get("source_passage_refs") or [])
        incoming = toh_to_sps.get(toh_id, [])
        seen: set = set(existing)
        merged_refs = list(existing)
        for sp_id in incoming:
            if sp_id and sp_id not in seen:
                seen.add(sp_id)
                merged_refs.append(sp_id)
                added_toh += 1
        t["source_passage_refs"] = merged_refs

    # Populate commitment.related_source_passages
    added_com = 0
    for c in merged_commitments:
        com_id = c.get("commitment_id", "")
        existing = list(c.get("related_source_passages") or [])
        incoming = com_to_sps.get(com_id, [])
        seen = set(existing)
        merged_refs = list(existing)
        for sp_id in incoming:
            if sp_id and sp_id not in seen:
                seen.add(sp_id)
                merged_refs.append(sp_id)
                added_com += 1
        c["related_source_passages"] = merged_refs

    if added_toh or added_com:
        warnings.append(
            f"INFO: back-refs: synthesised {added_toh} theory ref(s) "
            f"and {added_com} commitment ref(s) from passage supports_ fields."
        )


# ---------------------------------------------------------------------------
# definition_status normalisation
# ---------------------------------------------------------------------------

# Valid values from the DefinitionStatus enum in app/models/case.py
_VALID_DEFINITION_STATUSES = frozenset({
    "defined", "discussed", "segmented", "left_open", "considered",
})

# Conservative normalisations for known invalid draft values.
# Values not in this map and not in _VALID_DEFINITION_STATUSES are warned only.
_DEFINITION_STATUS_NORM: dict[str, str] = {
    "not_conclusive": "left_open",
    "precedent_only": "discussed",
    "possible_segmentation": "discussed",
}


def _normalize_definition_statuses(
    product_markets: list[dict],
    geographic_markets: list[dict],
    warnings: list[str],
) -> None:
    """
    Normalise or warn on definition_status values that do not match the schema enum.

    Conservative rules:
      - known safe mappings (not_conclusive, precedent_only, possible_segmentation)
        are silently rewritten;
      - 'unknown' and any other unrecognised values are warned but left unchanged
        so a human reviewer makes the legal call.
    """
    invalid_warned: set[str] = set()

    for market_list, kind in (
        (product_markets, "product market"),
        (geographic_markets, "geographic market"),
    ):
        for m in market_list:
            status = m.get("definition_status", "")
            if status in _VALID_DEFINITION_STATUSES:
                continue
            if status in _DEFINITION_STATUS_NORM:
                new_status = _DEFINITION_STATUS_NORM[status]
                m["definition_status"] = new_status
                if status not in invalid_warned:
                    warnings.append(
                        f"INFO: definition_status '{status}' → '{new_status}' "
                        f"(normalised in {kind} records)."
                    )
                    invalid_warned.add(status)
            else:
                if status not in invalid_warned:
                    warnings.append(
                        f"WARN: definition_status '{status}' in {kind} is not a "
                        "valid schema value and has no automatic normalisation — "
                        "manual review required."
                    )
                    invalid_warned.add(status)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate_merged(record: dict) -> tuple[bool, str]:
    """
    Attempt Pydantic validation of the merged draft by stripping draft-only fields first.

    Returns (ok, error_msg).
    """
    import copy
    candidate = copy.deepcopy(record)

    # Strip draft-only fields (same as promote script)
    candidate.pop("_draft_note", None)
    for key in ("product_markets_considered", "geographic_markets_considered"):
        for m in candidate.get(key) or []:
            m.pop("verification", None)
            m.pop("market_importance", None)
    for p in candidate.get("source_passages") or []:
        p.pop("source_role", None)
    # Strip extra draft fields on theories (theory_type, theory_outcome)
    for t in candidate.get("theories_of_harm") or []:
        t.pop("theory_type", None)
        t.pop("theory_outcome", None)
        if isinstance(t.get("verification"), dict):
            # Rename status -> verification_status if needed
            v = t["verification"]
            if "status" in v and "verification_status" not in v:
                v["verification_status"] = v.pop("status")

    # Ensure required canonical fields have defaults so validation can run
    if not candidate.get("procedure_stage"):
        candidate["procedure_stage"] = "unknown"
    if not candidate.get("case_type"):
        candidate["case_type"] = "merger"
    if not candidate.get("metadata"):
        today = datetime.date.today().isoformat()
        candidate["metadata"] = {
            "extraction_method": "ai_extracted",
            "review_status": "unreviewed",
            "overall_confidence": 0.7,
            "created_date": today,
            "last_updated_date": today,
            "tags": [],
        }

    try:
        from app.cases.models import CaseRecord
        CaseRecord.model_validate(candidate)
        return True, ""
    except Exception as exc:
        return False, str(exc)

# ---------------------------------------------------------------------------
# Output path
# ---------------------------------------------------------------------------

def _default_output_path(drafts_dir: Path, case_id: str, draft_paths: list[Path]) -> Path:
    """Derive merged draft output path from the first draft's jurisdiction directory."""
    # Try to infer jurisdiction from the first draft's parent dir name
    first = draft_paths[0]
    jur = first.parent.name  # e.g. "eu"
    return drafts_dir / jur / f"{case_id}.merged.draft.yaml"

# ---------------------------------------------------------------------------
# Core merge function
# ---------------------------------------------------------------------------

def merge_drafts(
    draft_paths: list[Path],
    *,
    case_id_override: Optional[str] = None,
    drafts_dir: Optional[Path] = None,
) -> tuple[dict, list[str]]:
    """
    Merge draft YAMLs at draft_paths into a single merged draft dict.

    Returns (merged_dict, warnings).
    Raises ValueError on case ID mismatch or other fatal errors.
    """
    if not draft_paths:
        raise ValueError("No draft paths provided.")

    drafts: list[dict] = []
    for p in draft_paths:
        drafts.append(yaml.safe_load(p.read_text(encoding="utf-8")))

    # ------------------------------------------------------------------
    # 1. Case identity validation
    # ------------------------------------------------------------------
    case_ids = [d.get("case_id", "") for d in drafts]
    unique_ids = set(case_ids)
    if len(unique_ids) > 1:
        raise ValueError(
            f"Drafts have mismatched case_ids: {sorted(unique_ids)}. "
            "All drafts must be for the same case."
        )
    resolved_case_id = case_ids[0]
    if not resolved_case_id:
        raise ValueError("No case_id found in the provided drafts.")
    if case_id_override and resolved_case_id != case_id_override:
        raise ValueError(
            f"case_id mismatch: drafts have '{resolved_case_id}' "
            f"but --case-id specified '{case_id_override}'."
        )

    warnings: list[str] = []

    # ------------------------------------------------------------------
    # 2. Metadata precedence
    # ------------------------------------------------------------------
    metadata = _pick_metadata(drafts, draft_paths)

    # ------------------------------------------------------------------
    # 3. Source documents (dedup by doc_id)
    # ------------------------------------------------------------------
    source_documents = _merge_source_documents(drafts)

    # ------------------------------------------------------------------
    # 4. Collect records with their draft index
    #    We tag each record with _draft_idx so rewriting can apply per-draft maps.
    # ------------------------------------------------------------------
    pm_items: list[tuple[int, dict]] = []
    gm_items: list[tuple[int, dict]] = []
    toh_items: list[tuple[int, dict]] = []
    com_items: list[tuple[int, dict]] = []
    sp_items: list[tuple[int, dict]] = []
    ua_items: list[tuple[int, dict]] = []

    for i, d in enumerate(drafts):
        for rec in d.get("product_markets_considered") or []:
            r = dict(rec)
            r["_draft_idx"] = i
            pm_items.append((i, r))
        for rec in d.get("geographic_markets_considered") or []:
            r = dict(rec)
            r["_draft_idx"] = i
            gm_items.append((i, r))
        for rec in d.get("theories_of_harm") or []:
            r = dict(rec)
            r["_draft_idx"] = i
            toh_items.append((i, r))
        for rec in d.get("commitments") or []:
            r = dict(rec)
            r["_draft_idx"] = i
            com_items.append((i, r))
        for rec in d.get("source_passages") or []:
            r = dict(rec)
            r["_draft_idx"] = i
            sp_items.append((i, r))
        for rec in d.get("unit_assessments") or []:
            ua_items.append((i, dict(rec)))

    # ------------------------------------------------------------------
    # 5. Deduplicate and assign global IDs
    # ------------------------------------------------------------------
    pm_map = _IdMap()
    gm_map = _IdMap()
    toh_map = _IdMap()
    com_map = _IdMap()
    sp_map = _IdMap()

    merged_pms = _merge_markets(pm_items, pm_map, "pm_", "market_id", warnings)
    merged_gms = _merge_markets(gm_items, gm_map, "gm_", "market_id", warnings)
    merged_tohs = _merge_theories(toh_items, toh_map, warnings)
    merged_coms = _merge_commitments(com_items, com_map, warnings)
    merged_sps = _merge_passages(sp_items, sp_map, warnings)
    # unit_assessments: passage refs must be rewritten using the final sp_map,
    # so merge after passages are assigned global IDs.
    merged_uas = _merge_unit_assessments(ua_items, sp_map, warnings)

    # ------------------------------------------------------------------
    # 6. Rewrite cross-references
    # ------------------------------------------------------------------
    _rewrite_all_refs(
        merged_sps,
        merged_coms,
        pm_map,
        gm_map,
        toh_map,
        com_map,
        sp_map,
    )

    # Strip _draft_idx from records with no cross-refs to rewrite
    for rec in merged_pms + merged_gms + merged_tohs:
        rec.pop("_draft_idx", None)

    # ------------------------------------------------------------------
    # 6b. Synthesise back-references (passage -> theory / commitment)
    # ------------------------------------------------------------------
    _synthesize_back_refs(merged_tohs, merged_coms, merged_sps, warnings)

    # ------------------------------------------------------------------
    # 6c. Normalise definition_status values
    # ------------------------------------------------------------------
    _normalize_definition_statuses(merged_pms, merged_gms, warnings)

    # ------------------------------------------------------------------
    # 7. Build merged draft
    # ------------------------------------------------------------------
    today = datetime.date.today().isoformat()
    merged: dict = {
        "_draft_note": (
            f"DRAFT (MERGED) — generated by merge_drafts.py on {today}. "
            "Review and validate before promoting to canonical YAML."
        ),
        "case_id": resolved_case_id,
        "case_name": metadata.get("case_name", ""),
        "authority": metadata.get("authority", ""),
        "jurisdiction": metadata.get("jurisdiction", ""),
        "sector": metadata.get("sector", ""),
        "outcome": metadata.get("outcome", "unknown"),
        "decision_date": metadata.get("decision_date", ""),
        "parties": metadata.get("parties", []),
        "source_documents": source_documents,
        "product_markets_considered": merged_pms,
        "geographic_markets_considered": merged_gms,
        "theories_of_harm": merged_tohs,
        "commitments": merged_coms,
        "source_passages": merged_sps,
    }
    if merged_uas:
        merged["unit_assessments"] = merged_uas
    if metadata.get("procedure_stage"):
        merged["procedure_stage"] = metadata["procedure_stage"]
    if metadata.get("authority_reference"):
        merged["authority_reference"] = metadata["authority_reference"]

    return merged, warnings


# ---------------------------------------------------------------------------
# Report helpers
# ---------------------------------------------------------------------------

def _print_report(
    draft_paths: list[Path],
    merged: dict,
    warnings: list[str],
    output_path: Optional[Path],
    dry_run: bool,
) -> None:
    print("\nMerge report")
    print(f"  Input drafts : {len(draft_paths)}")
    for p in draft_paths:
        print(f"    {p}")
    print(f"  Product markets   : {len(merged.get('product_markets_considered') or [])}")
    print(f"  Geographic markets: {len(merged.get('geographic_markets_considered') or [])}")
    print(f"  Theories of harm  : {len(merged.get('theories_of_harm') or [])}")
    print(f"  Commitments       : {len(merged.get('commitments') or [])}")
    print(f"  Source passages   : {len(merged.get('source_passages') or [])}")
    uas = merged.get("unit_assessments") or []
    if uas:
        total_findings = sum(len(u.get("findings") or []) for u in uas)
        print(f"  Unit assessments  : {len(uas)} unit(s), {total_findings} finding(s)")
    print(f"  Warnings          : {len(warnings)}")
    for w in warnings:
        print(f"    {w}")
    if dry_run:
        print("  Output            : (dry-run — not written)")
    else:
        print(f"  Output            : {output_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Conflict-report merge (dual extraction, ROADMAP 5.9)
# ---------------------------------------------------------------------------

# Map the ConflictReport path label → the draft list key it addresses.
_LABEL_TO_LIST_KEY = {
    "product_markets": "product_markets_considered",
    "geographic_markets": "geographic_markets_considered",
    "theories": "theories_of_harm",
}
# Per list: (id field on the market, the passage field that references that id).
_LIST_ID_AND_SUPPORT = {
    "product_markets_considered": ("market_id", "supports_markets"),
    "geographic_markets_considered": ("market_id", "supports_geographic_markets"),
    "theories_of_harm": ("theory_id", "supports_theories"),
}
_DROP_WORDS = {"drop", "remove", "reject", "discard", "exclude", "no"}
_KEEP_WORDS = {"keep", "add", "accept", "include", "yes"}


def _decision(resolution: Any) -> str:
    """Normalize an a_only/b_only resolution to 'keep' | 'drop' | '' (unknown)."""
    val = str(resolution or "").strip().lower()
    if val in _DROP_WORDS:
        return "drop"
    if val in _KEEP_WORDS:
        return "keep"
    return ""


def _remove_market(record: dict, list_key: str, name: str, norm) -> None:
    target = norm(name)
    record[list_key] = [
        m for m in (record.get(list_key) or []) if norm(m.get("name", "")) != target
    ]


def _fresh_id(id_field: str, existing: set) -> str:
    prefix = "toh" if id_field == "theory_id" else "pm"
    n = 1
    while f"{prefix}_merged_{n}" in existing:
        n += 1
    return f"{prefix}_merged_{n}"


def _add_market_from_b(merged: dict, draft_b: dict, list_key: str, name: str, norm) -> None:
    """Copy a B-only market (and its supporting passages) into the merged record.

    Rewrites the market's id if it would collide with an existing merged id, keeping
    the copied passages' support references consistent. Passages already present
    (by passage_id) are not duplicated.
    """
    import copy as _copy

    src = next(
        (m for m in (draft_b.get(list_key) or []) if norm(m.get("name", "")) == norm(name)),
        None,
    )
    if src is None:
        return
    id_field, support_key = _LIST_ID_AND_SUPPORT[list_key]
    market = _copy.deepcopy(src)
    old_id = market.get(id_field, "")
    existing_ids = {m.get(id_field) for m in (merged.get(list_key) or [])}
    new_id = old_id
    if not new_id or new_id in existing_ids:
        new_id = _fresh_id(id_field, existing_ids)
        market[id_field] = new_id
    merged.setdefault(list_key, []).append(market)

    existing_pids = {sp.get("passage_id") for sp in (merged.get("source_passages") or [])}
    for sp in (draft_b.get("source_passages") or []):
        if old_id not in (sp.get(support_key) or []):
            continue
        if sp.get("passage_id") in existing_pids:
            continue
        sp_copy = _copy.deepcopy(sp)
        sp_copy[support_key] = [new_id if r == old_id else r for r in (sp.get(support_key) or [])]
        merged.setdefault("source_passages", []).append(sp_copy)


def merge_from_conflict_report(
    draft_a: dict,
    draft_b: dict,
    report: dict,
    focus: Optional[str] = None,
) -> dict:
    """Apply a resolved ConflictReport to Draft A, producing one merged draft.

    Aligned fields both drafts agreed on are already correct in A. Resolved
    value_mismatch / rename conflicts overwrite A's field with the human's value;
    auto-resolved names are applied; a_only markets are kept (default) or dropped;
    b_only markets are added from B (with their supporting passages) when kept.

    Raises ValueError if any conflict still has an empty `resolution` — unresolved
    conflicts must block, never silently drop a field.
    """
    import copy as _copy

    from compare_extractions import (
        _index_markets_by_name,
        _normalize_for_similarity,
        align_drafts,
    )
    norm = _normalize_for_similarity

    cr = report.get("conflict_report", report)
    conflicts = cr.get("conflicts") or []
    auto_resolved = cr.get("auto_resolved") or []

    unresolved = [c for c in conflicts if not str(c.get("resolution") or "").strip()]
    if unresolved:
        fields = ", ".join(str(c.get("field")) for c in unresolved)
        raise ValueError(
            f"{len(unresolved)} unresolved conflict(s) — fill 'resolution' for: {fields}"
        )

    merged = _copy.deepcopy(draft_a)
    align = align_drafts(draft_a, draft_b, focus=focus)
    idx_merged = _index_markets_by_name(merged)

    # Locate the merged (A-origin) market for an aligned-pair prefix. The prefix in
    # the report uses B's name; the pair carries A's name so the lookup is correct
    # even when the pair was renamed.
    pair_by_prefix = {
        f"{p['label']}/{p['name_b'] or p['name_a']}": p for p in align["pairs"]
    }

    def _market_for_prefix(prefix: str) -> Optional[dict]:
        p = pair_by_prefix.get(prefix)
        if p is None:
            return None
        return idx_merged[p["list_key"]].get(norm(p["name_a"]))

    # 1. Aligned-pair field resolutions (value_mismatch, rename_candidate) and
    #    top-level record scalars (field path without a "/").
    for c in conflicts:
        if c.get("kind") not in ("value_mismatch", "rename_candidate"):
            continue
        field = c.get("field", "")
        if "/" not in field:
            merged[field] = c["resolution"]
            continue
        prefix, _, leaf = field.rpartition("/")
        m = _market_for_prefix(prefix)
        if m is not None:
            m[leaf] = c["resolution"]

    # 2. Auto-resolved names → apply the expanded canonical name.
    for a in auto_resolved:
        prefix, _, leaf = a.get("field", "").rpartition("/")
        m = _market_for_prefix(prefix)
        if m is not None and leaf == "name" and a.get("resolved_to"):
            m["name"] = a["resolved_to"]

    # 3. a_only — keep (default) or drop.
    for c in conflicts:
        if c.get("kind") == "a_only" and _decision(c.get("resolution")) == "drop":
            list_key = _LABEL_TO_LIST_KEY.get(c.get("field", ""))
            if list_key:
                _remove_market(merged, list_key, c.get("draft_a", ""), norm)

    # 4. b_only — keep (add from B with passages) or drop (default).
    for c in conflicts:
        if c.get("kind") == "b_only" and _decision(c.get("resolution")) == "keep":
            list_key = _LABEL_TO_LIST_KEY.get(c.get("field", ""))
            if list_key:
                _add_market_from_b(merged, draft_b, list_key, c.get("draft_b", ""), norm)

    return merged


def _main_conflict_report_merge(args) -> int:
    """CLI handler for `--from-conflict-report` (dual-extraction merge)."""
    if not args.draft_a or not args.draft_b:
        print("ERROR: --from-conflict-report requires --draft-a and --draft-b", file=sys.stderr)
        return 1
    report_path = Path(args.from_conflict_report)
    draft_a_path = Path(args.draft_a)
    draft_b_path = Path(args.draft_b)
    for p in (report_path, draft_a_path, draft_b_path):
        if not p.exists():
            print(f"ERROR: not found: {p}", file=sys.stderr)
            return 1

    report = yaml.safe_load(report_path.read_text(encoding="utf-8"))
    draft_a = yaml.safe_load(draft_a_path.read_text(encoding="utf-8"))
    draft_b = yaml.safe_load(draft_b_path.read_text(encoding="utf-8"))
    focus = (report.get("conflict_report", report) or {}).get("focus") or None

    try:
        merged = merge_from_conflict_report(draft_a, draft_b, report, focus=focus)
    except ValueError as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 1

    ok, err_msg = _validate_merged(merged)
    print("Validation: PASS" if ok else f"Validation: WARN — {err_msg}")

    out_path = (
        Path(args.output) if args.output
        else draft_a_path.parent / draft_a_path.name.replace(".draft_a.yaml", ".merged.draft.yaml")
    )
    yaml_text = _dump_yaml(merged)
    if args.dry_run:
        print("\n--- DRY RUN — merged YAML (not written) ---\n")
        print(yaml_text)
        return 0
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(yaml_text, encoding="utf-8")
    print(f"Written: {out_path}")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Merge partial extraction drafts into one reviewable draft YAML."
    )
    parser.add_argument(
        "drafts",
        nargs="*",
        metavar="DRAFT_PATH",
        help="Paths to draft YAML files to merge (multi-focus merge mode).",
    )
    parser.add_argument(
        "--from-conflict-report",
        metavar="PATH",
        help=(
            "Dual-extraction merge (ROADMAP 5.9): apply a resolved ConflictReport "
            "to Draft A, producing one merged draft. Requires --draft-a and "
            "--draft-b. Blocks if any conflict is unresolved."
        ),
    )
    parser.add_argument("--draft-a", help="Draft A path (with --from-conflict-report).")
    parser.add_argument("--draft-b", help="Draft B path (with --from-conflict-report).")
    parser.add_argument(
        "--case-id",
        help="Expected case ID. Fails if any draft does not match.",
    )
    parser.add_argument(
        "--output",
        help="Custom output path. Default: data/drafts/<jur>/<case_id>.merged.draft.yaml",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print merged YAML without writing to disk.",
    )
    parser.add_argument(
        "--drafts-dir",
        default=str(_REPO_ROOT / "data" / "drafts"),
        help="Root directory for draft files (used for default output path).",
    )
    args = parser.parse_args(argv)

    # Dual-extraction conflict-report merge takes a distinct path.
    if args.from_conflict_report:
        return _main_conflict_report_merge(args)

    if not args.drafts:
        print("ERROR: no draft paths given (or use --from-conflict-report)", file=sys.stderr)
        return 1

    draft_paths = [Path(p) for p in args.drafts]
    drafts_dir = Path(args.drafts_dir)

    # Check all input files exist
    missing = [p for p in draft_paths if not p.exists()]
    if missing:
        for p in missing:
            print(f"ERROR: Draft not found: {p}", file=sys.stderr)
        return 1

    # ------------------------------------------------------------------
    # Merge
    # ------------------------------------------------------------------
    try:
        merged, warnings = merge_drafts(
            draft_paths,
            case_id_override=args.case_id,
            drafts_dir=drafts_dir,
        )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    # ------------------------------------------------------------------
    # Validate
    # ------------------------------------------------------------------
    ok, err_msg = _validate_merged(merged)
    if ok:
        print("Validation: PASS")
    else:
        print(f"Validation: WARN — schema issues (merged draft may still be useful):\n{err_msg}")

    # ------------------------------------------------------------------
    # Determine output path
    # ------------------------------------------------------------------
    if args.output:
        out_path = Path(args.output)
    else:
        out_path = _default_output_path(drafts_dir, merged["case_id"], draft_paths)

    # ------------------------------------------------------------------
    # Report + output
    # ------------------------------------------------------------------
    _print_report(draft_paths, merged, warnings, out_path, args.dry_run)

    yaml_text = _dump_yaml(merged)

    if args.dry_run:
        print("\n--- DRY RUN — merged YAML (not written) ---\n")
        print(yaml_text)
        return 0

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(yaml_text, encoding="utf-8")
    print(f"\nWritten: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
