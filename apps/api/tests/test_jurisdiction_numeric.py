"""Tests for multilingual / non-Latin numeral parsing in jurisdiction_numeric."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.jurisdiction import MetricType
from app.services.jurisdiction_numeric import (
    parse_monetary_values,
    value_in_text,
)

REV = MetricType.revenue


# ── Group/decimal separators ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text, expected, currency",
    [
        ("turnover in Norway of NOK 1 000 000 000", 1_000_000_000, "NOK"),  # space
        ("Schwellenwert von EUR 150.000.000", 150_000_000, "EUR"),  # dot grouping
        ("combined EUR 595 000 000", 595_000_000, "EUR"),  # space grouping
        ("CHF 2'000'000'000 weltweit", 2_000_000_000, "CHF"),  # apostrophe
        ("umsatz 1.234.567,89 EUR", 1_234_567.89, "EUR"),  # EU dot/comma
        ("US$1,234,567.89", 1_234_567.89, "USD"),  # US comma/dot
        ("threshold of 1.5 million euros", 1_500_000, "EUR"),  # single dot decimal
        ("EUR 100.000 only", 100_000, "EUR"),  # single dot = thousands group
    ],
)
def test_separator_styles(text, expected, currency):
    assert value_in_text(text, expected, metric=REV, currency=currency)


# ── Magnitude words across languages (digit + word) ───────────────────────────


@pytest.mark.parametrize(
    "text, expected, currency",
    [
        ("combined turnover of 150 εκατομμύρια ευρώ", 150_000_000, "EUR"),  # Greek
        ("7 miliard EUR", 7_000_000_000, "EUR"),  # Czech/Polish
        ("umsatz von 20 Milliarden EUR", 20_000_000_000, "EUR"),  # German
        ("chiffre de 2 milliards d'euros", 2_000_000_000, "EUR"),  # French
        ("превышает 7 миллиардов рублей", 7_000_000_000, "RUB"),  # Russian digit+word
        ("ventas de 300 millones", 300_000_000, "EUR"),  # Spanish
    ],
)
def test_magnitude_words(text, expected, currency):
    assert value_in_text(text, expected, metric=REV, currency=currency)


# ── Fully spelled-out integers ────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text, expected",
    [
        ("seven billion dollars", 7_000_000_000),  # English
        ("превышает семь миллиардов рублей", 7_000_000_000),  # Russian
        ("восемьсот миллионов рублей", 800_000_000),  # Russian hundreds + scale
        ("десять миллиардов рублей", 10_000_000_000),  # Russian ten + scale
        ("διακόσια εκατομμύρια ευρώ", 200_000_000),  # Greek hundreds + scale
    ],
)
def test_spelled_out(text, expected):
    assert value_in_text(text, expected, metric=REV, currency=None)


# ── Guards: must not over-match ───────────────────────────────────────────────


def test_bare_numbers_not_monetary():
    text = "Section 23 applies to mergers notified after 2002 within 40 days."
    assert not value_in_text(text, 2002, metric=REV)
    assert not value_in_text(text, 40, metric=REV)
    assert not value_in_text(text, 23, metric=REV)


def test_spelled_small_numbers_without_scale_ignored():
    # "two", "three" without a scale word must not be treated as monetary.
    text = "at least two of the parties and three members of the board"
    assert not value_in_text(text, 2, metric=REV)
    assert not value_in_text(text, 3, metric=REV)


def test_adjacent_numbers_not_merged():
    # A year immediately followed by an amount must not fuse into one value.
    text = "in 2023 350 million euros were recorded"
    assert not value_in_text(text, 2_023_350_000_000, metric=REV, currency="EUR")
    # The legitimate amount may still be picked up on its own is acceptable,
    # but the fused over-capture must never confirm.


def test_inconsistent_grouping_rejected():
    # "12 34 567" is not validly grouped (2-digit groups) → no monetary value.
    assert parse_monetary_values("EUR 12 34 567", currency="EUR") == [] or all(
        v != 1_234_567 for v in parse_monetary_values("EUR 12 34 567", currency="EUR")
    )


# ── Russian source-passage style (the ru.yaml Article 28 case) ────────────────


def test_russian_statute_thresholds():
    text = (
        "суммарная стоимость активов превышает семь миллиардов рублей или если их "
        "суммарная выручка превышает десять миллиардов рублей и при этом суммарная "
        "стоимость активов превышает восемьсот миллионов рублей"
    )
    assert value_in_text(text, 7_000_000_000, metric=REV, currency="RUB")
    assert value_in_text(text, 10_000_000_000, metric=REV, currency="RUB")
    assert value_in_text(text, 800_000_000, metric=REV, currency="RUB")
    # A wrong figure (the old erroneous RUB 400m) must NOT confirm.
    assert not value_in_text(text, 400_000_000, metric=REV, currency="RUB")
