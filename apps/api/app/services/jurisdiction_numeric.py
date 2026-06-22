"""Extract and compare numeric threshold values from source text."""

from __future__ import annotations

import re
from typing import Optional

from app.models.jurisdiction import MetricType

_MULTIPLIERS = {
    "thousand": 1_000,
    "million": 1_000_000,
    "billion": 1_000_000_000,
    "bn": 1_000_000_000,
    "m": 1_000_000,
    "k": 1_000,
}


def _parse_number_token(raw: str) -> Optional[float]:
    cleaned = raw.replace(",", "").replace(" ", "").strip()
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_monetary_values(text: str, *, currency: Optional[str] = None) -> list[float]:
    """Return monetary magnitudes found in text, normalised to base units."""
    values: list[float] = []
    cur = (currency or "").upper()
    # A money prefix is a currency symbol or (if supplied) the currency code.
    money_prefix = rf"(?:{re.escape(cur)}|[$€£¥])" if cur else r"[$€£¥]"
    # Require a currency symbol/code or a magnitude word so bare integers
    # (years, section numbers, day counts) are not treated as monetary values.
    patterns = [
        rf"(?:{money_prefix}\s*)?([\d][\d,\.\s]*)\s*(thousand|million|billion|bn|m|k)\b",
        rf"{money_prefix}\s*([\d][\d,\.\s]*)",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.I):
            number = _parse_number_token(match.group(1))
            if number is None:
                continue
            unit = match.group(2).lower() if match.lastindex and match.lastindex >= 2 and match.group(2) else ""
            multiplier = _MULTIPLIERS.get(unit, 1)
            values.append(number * multiplier)
    return values


def parse_share_values(text: str) -> list[float]:
    """Return share values as fractions (0–1)."""
    shares: list[float] = []
    for match in re.finditer(r"(\d+(?:\.\d+)?)\s*(?:%|percent|per cent)", text, flags=re.I):
        shares.append(float(match.group(1)) / 100.0)
    for match in re.finditer(r"\b0\.\d+\b", text):
        val = float(match.group(0))
        if 0 <= val <= 1:
            shares.append(val)
    # UK and similar statutes often express thresholds as fractions in words.
    for pattern, fraction in (
        (r"\bone[- ]quarter\b", 0.25),
        (r"\bthree[- ]quarters\b", 0.75),
        (r"\bone[- ]third\b", 1 / 3),
        (r"\btwo[- ]thirds\b", 2 / 3),
        (r"\bone[- ]half\b", 0.5),
    ):
        if re.search(pattern, text, flags=re.I):
            shares.append(fraction)
    return shares


def value_in_text(
    text: str,
    expected: float,
    *,
    metric: MetricType,
    currency: Optional[str] = None,
    tolerance: float = 0.02,
) -> bool:
    """Return True if expected value appears in text within tolerance."""
    if metric in {MetricType.market_share, MetricType.incremental_share}:
        candidates = parse_share_values(text)
        # Shares are fractions in [0, 1]; rely on the relative tolerance only.
        floor = 0.0
    else:
        candidates = parse_monetary_values(text, currency=currency)
        # Monetary values are large; a one-unit absolute floor avoids float noise.
        floor = 1.0

    if not candidates:
        return False

    if expected == 0:
        return any(abs(c) <= tolerance for c in candidates)

    for candidate in candidates:
        if abs(candidate - expected) <= max(abs(expected) * tolerance, floor):
            return True
    return False
