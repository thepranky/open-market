"""Load and persist jurisdiction verification sidecars."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

from app.models.jurisdiction_verification import JurisdictionVerification


# Process-level cache mirroring threshold_engine._jurisdiction_cache so that
# screening requests don't re-read and re-validate every sidecar from disk.
# Keyed by (resolved data_dir, jurisdiction_id); caches absence (None) too.
_sidecar_cache: dict[tuple[str, str], Optional[JurisdictionVerification]] = {}


def sidecar_path(data_dir: Path, jurisdiction_id: str) -> Path:
    return data_dir / f"{jurisdiction_id}.verification.yaml"


def clear_sidecar_cache() -> None:
    _sidecar_cache.clear()


def load_sidecar(data_dir: Path, jurisdiction_id: str) -> Optional[JurisdictionVerification]:
    key = (str(data_dir), jurisdiction_id)
    if key in _sidecar_cache:
        return _sidecar_cache[key]
    path = sidecar_path(data_dir, jurisdiction_id)
    if not path.exists():
        _sidecar_cache[key] = None
        return None
    raw = yaml.safe_load(path.read_text()) or {}
    sidecar = JurisdictionVerification.model_validate(raw)
    _sidecar_cache[key] = sidecar
    return sidecar


def write_sidecar(data_dir: Path, sidecar: JurisdictionVerification) -> Path:
    path = sidecar_path(data_dir, sidecar.jurisdiction_id)
    payload = sidecar.model_dump(mode="json", exclude_none=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True))
    # Keep the cache consistent with what was just persisted.
    _sidecar_cache[(str(data_dir), sidecar.jurisdiction_id)] = sidecar
    return path
