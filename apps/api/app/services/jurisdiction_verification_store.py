"""Load and persist jurisdiction verification sidecars."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

from app.models.jurisdiction_verification import JurisdictionVerification


def sidecar_path(data_dir: Path, jurisdiction_id: str) -> Path:
    return data_dir / f"{jurisdiction_id}.verification.yaml"


def load_sidecar(data_dir: Path, jurisdiction_id: str) -> Optional[JurisdictionVerification]:
    path = sidecar_path(data_dir, jurisdiction_id)
    if not path.exists():
        return None
    raw = yaml.safe_load(path.read_text()) or {}
    return JurisdictionVerification.model_validate(raw)


def write_sidecar(data_dir: Path, sidecar: JurisdictionVerification) -> Path:
    path = sidecar_path(data_dir, sidecar.jurisdiction_id)
    payload = sidecar.model_dump(mode="json", exclude_none=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True))
    return path
