"""
pipeline_profile.py — load and select jurisdiction/document-type profiles.

Profiles live in data/pipeline_profiles/*.yaml.  Each profile defines the
coverage keywords, source-role mapping, and readiness expectations for one
family of source documents (EC merger decision, CMA report, US court opinion).

Usage:
    from pipeline_profile import select_profile, load_profile

    profile = select_profile(case_id="us_tapestry_capri_2024")
    profile = select_profile(case_id="eu_viasat_inmarsat_2023", profile_id="ec_decision")
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PROFILES_DIR = _REPO_ROOT / "data" / "pipeline_profiles"

# ---------------------------------------------------------------------------
# Profile dataclass
# ---------------------------------------------------------------------------


@dataclass
class PipelineProfile:
    profile_id: str
    display_name: str
    jurisdictions: list[str] = field(default_factory=list)
    procedure_stages: list[str] = field(default_factory=list)
    doc_types: list[str] = field(default_factory=list)
    authority_patterns: list[str] = field(default_factory=list)
    focus_defaults: list[str] = field(default_factory=list)
    coverage_keywords: dict[str, list[str]] = field(default_factory=dict)
    source_role_mapping: dict[str, str] = field(default_factory=dict)
    orphan_policy: dict = field(default_factory=dict)
    readiness: dict = field(default_factory=dict)

    # Convenience accessors
    def keywords_for(self, category: str) -> tuple[str, ...]:
        """Return coverage keywords for a category as a lowercase tuple."""
        return tuple(kw.lower() for kw in self.coverage_keywords.get(category, []))

    def allowed_orphan_roles(self) -> frozenset[str]:
        return frozenset(self.orphan_policy.get("allow_roles", []))

    def source_role_prompt_block(self) -> str:
        """
        Return a formatted SOURCE ROLE CLASSIFICATION block for injection into
        extraction prompts.  The block makes source_role mandatory and tailors
        the descriptions to this profile's document type.
        """
        lines = [
            "SOURCE ROLE CLASSIFICATION (MANDATORY — every passage must have source_role):",
            "You MUST set source_role on every passage. Omitting source_role is an error.",
            "Choose the most accurate role from the following options:",
        ]
        for role, description in self.source_role_mapping.items():
            # Collapse multi-line YAML block scalars to a single line
            desc_single = " ".join(str(description).split())
            lines.append(f'  - "{role}": {desc_single}')
        lines.append(
            "NEVER return source_role: null, source_role: not_set, or omit source_role."
        )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _load_profile_yaml(path: Path) -> PipelineProfile:
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    return PipelineProfile(
        profile_id=data.get("profile_id", path.stem),
        display_name=data.get("display_name", path.stem),
        jurisdictions=[j.lower() for j in (data.get("jurisdictions") or [])],
        procedure_stages=[s.lower() for s in (data.get("procedure_stages") or [])],
        doc_types=[d.lower() for d in (data.get("doc_types") or [])],
        authority_patterns=[p.lower() for p in (data.get("authority_patterns") or [])],
        focus_defaults=data.get("focus_defaults") or [],
        coverage_keywords=data.get("coverage_keywords") or {},
        source_role_mapping=data.get("source_role_mapping") or {},
        orphan_policy=data.get("orphan_policy") or {"default": "warn", "allow_roles": []},
        readiness=data.get("readiness") or {},
    )


def load_profile(profile_id: str) -> PipelineProfile:
    """Load a profile by its profile_id.  Raises ValueError if not found."""
    path = _PROFILES_DIR / f"{profile_id}.yaml"
    if not path.exists():
        available = [p.stem for p in _PROFILES_DIR.glob("*.yaml")]
        raise ValueError(
            f"Profile {profile_id!r} not found in {_PROFILES_DIR}. "
            f"Available: {available}"
        )
    return _load_profile_yaml(path)


def list_profiles() -> list[PipelineProfile]:
    """Return all profiles found in the profiles directory."""
    profiles = []
    for path in sorted(_PROFILES_DIR.glob("*.yaml")):
        try:
            profiles.append(_load_profile_yaml(path))
        except Exception:
            pass
    return profiles


# ---------------------------------------------------------------------------
# Profile inference
# ---------------------------------------------------------------------------


def _infer_jurisdiction(case_id: str) -> str:
    for prefix, jur in (("eu_", "eu"), ("uk_", "uk"), ("us_", "us")):
        if case_id.startswith(prefix):
            return jur
    return ""


def _infer_profile_from_case_meta(case_meta: dict) -> Optional[str]:
    """
    Infer a profile_id from canonical YAML metadata fields.
    Returns None if no confident match.
    """
    jurisdiction = str(case_meta.get("jurisdiction") or "").lower()
    procedure_stage = str(case_meta.get("procedure_stage") or "").lower()
    authority = str(case_meta.get("authority") or "").lower()

    # US jurisdiction: court opinions (district court, appellate, etc.)
    if jurisdiction == "us":
        return "us_court_opinion"

    # UK jurisdiction → CMA report
    if jurisdiction == "uk":
        return "cma_report"

    # EU jurisdiction → EC decision
    if jurisdiction in ("eu", "european union"):
        return "ec_decision"

    # Authority-pattern fallback
    for profile in list_profiles():
        for pat in profile.authority_patterns:
            if pat in authority:
                return profile.profile_id

    return None


def select_profile(
    case_id: str,
    profile_id: Optional[str] = None,
    case_meta: Optional[dict] = None,
) -> PipelineProfile:
    """
    Select and return a PipelineProfile.

    Resolution order:
      1. Explicit profile_id override (from --profile CLI flag).
      2. Inference from case_meta (jurisdiction, procedure_stage, authority).
      3. Inference from case_id prefix (eu_ → ec_decision, uk_ → cma_report, us_ → us_court_opinion).
      4. ValueError if no profile can be determined.
    """
    # 1. Explicit override
    if profile_id:
        return load_profile(profile_id)

    # 2. Inference from case metadata
    if case_meta:
        inferred = _infer_profile_from_case_meta(case_meta)
        if inferred:
            return load_profile(inferred)

    # 3. Inference from case_id prefix
    jur = _infer_jurisdiction(case_id)
    prefix_map = {"eu": "ec_decision", "uk": "cma_report", "us": "us_court_opinion"}
    if jur in prefix_map:
        return load_profile(prefix_map[jur])

    raise ValueError(
        f"Cannot infer pipeline profile for case_id={case_id!r}. "
        "Pass --profile explicitly (ec_decision | cma_report | us_court_opinion)."
    )
