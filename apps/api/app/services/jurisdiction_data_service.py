"""Load jurisdiction rules with optional verification sidecars."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.models.jurisdiction import JurisdictionRule
from app.models.jurisdiction_verification import (
    FreshnessStatus,
    JurisdictionVerification,
    RegressionStatus,
    SourceVerificationTier,
)
from app.services.jurisdiction_verification_store import load_sidecar
from app.services.threshold_engine import load_all_jurisdictions, load_jurisdiction


@dataclass
class JurisdictionBundle:
    rule: JurisdictionRule
    verification: Optional[JurisdictionVerification] = None

    @property
    def source_verification_tier(self) -> int:
        if self.verification:
            return int(self.verification.source_verification_tier.value)
        return int(SourceVerificationTier.schema_valid.value)

    @property
    def regression_status(self) -> str:
        if self.verification:
            return self.verification.regression_status.value
        return RegressionStatus.not_run.value

    @property
    def freshness_status(self) -> str:
        if self.verification:
            return self.verification.freshness_status.value
        return FreshnessStatus.unknown.value


def load_bundle(data_dir: Path | str, jurisdiction_id: str) -> JurisdictionBundle:
    data_path = Path(data_dir)
    rule = load_jurisdiction(jurisdiction_id, str(data_path))
    verification = load_sidecar(data_path, jurisdiction_id)
    return JurisdictionBundle(rule=rule, verification=verification)


def list_bundles(data_dir: Path | str) -> list[JurisdictionBundle]:
    data_path = Path(data_dir)
    return [
        JurisdictionBundle(rule=rule, verification=load_sidecar(data_path, rule.jurisdiction_id))
        for rule in load_all_jurisdictions(str(data_path))
    ]


def verification_metadata(bundle: JurisdictionBundle) -> dict:
    return {
        "source_verification_tier": bundle.source_verification_tier,
        "regression_status": bundle.regression_status,
        "freshness_status": bundle.freshness_status,
        "verified_at": bundle.verification.verified_at.isoformat() if bundle.verification and bundle.verification.verified_at else None,
    }
