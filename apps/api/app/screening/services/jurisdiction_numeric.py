"""Extract and compare numeric threshold values from source text.

Handles three numeral styles found across primary sources:

* Latin digits with assorted group/decimal separators — ``1,234,567.89`` (US),
  ``1.234.567,89`` (EU), ``595 000 000`` (space/NBSP), ``2'000'000'000`` (Swiss).
* Digits followed by a magnitude word in many languages — ``150 εκατομμύρια``
  (Greek), ``7 miliard`` (Czech/Polish), ``20 Mrd`` (German).
* Fully spelled-out integers — ``seven billion`` (English), ``восемьсот
  миллионов`` (Russian), ``διακόσια εκατομμύρια`` (Greek).
"""

from __future__ import annotations

import re
from typing import Optional

from app.screening.models.jurisdiction import MetricType

# Magnitude words → multiplier, across the languages present in our source
# passages. Keys are matched case-insensitively; stems cover inflected forms
# (e.g. Russian "миллиард"/"миллиардов", Czech "miliarda"/"miliard"/"miliardy").
_MULTIPLIERS: dict[str, int] = {
    # English / abbreviations
    "thousand": 1_000,
    "million": 1_000_000,
    "billion": 1_000_000_000,
    "trillion": 1_000_000_000_000,
    "bn": 1_000_000_000,
    "m": 1_000_000,
    "k": 1_000,
    "mn": 1_000_000,
    "mln": 1_000_000,
    "mrd": 1_000_000_000,  # German/Dutch Milliarde abbreviation
    # German
    "tausend": 1_000,
    "millionen": 1_000_000,
    "milliarde": 1_000_000_000,
    "milliarden": 1_000_000_000,
    # French
    "mille": 1_000,
    "millions": 1_000_000,
    "milliard": 1_000_000_000,
    "milliards": 1_000_000_000,
    # Spanish / Portuguese / Italian
    "millon": 1_000_000,
    "millones": 1_000_000,
    "milhao": 1_000_000,
    "milhoes": 1_000_000,
    "milione": 1_000_000,
    "milioni": 1_000_000,
    "mil": 1_000,
    "milliardo": 1_000_000_000,
    "milliardi": 1_000_000_000,
    "mila": 1_000,
    # Slavic (Czech / Polish / Slovak stems)
    "milion": 1_000_000,
    "miliony": 1_000_000,
    "milionu": 1_000_000,
    "milionow": 1_000_000,
    "miliarda": 1_000_000_000,
    "miliardy": 1_000_000_000,
    "miliard": 1_000_000_000,
    "miliardu": 1_000_000_000,
    # Russian (stems; matched against a stripped, lowercased token)
    "миллион": 1_000_000,
    "миллиард": 1_000_000_000,
    "тысяча": 1_000,
    "триллион": 1_000_000_000_000,
    # Greek
    "εκατομμυριο": 1_000_000,
    "εκατομμυρια": 1_000_000,
    "δισεκατομμυριο": 1_000_000_000,
    "δισεκατομμυρια": 1_000_000_000,
    "χιλιαδες": 1_000,
}

# Stems that, when a token *starts with* them, imply the multiplier. Order
# matters: longer stems first so "миллиард" wins over "миллион"-like prefixes.
_MULTIPLIER_STEMS: list[tuple[str, int]] = sorted(
    [
        ("δισεκατομμυρ", 1_000_000_000),
        ("εκατομμυρ", 1_000_000),
        ("миллиард", 1_000_000_000),
        ("миллион", 1_000_000),
        ("триллион", 1_000_000_000_000),
        ("тысяч", 1_000),
        ("miliard", 1_000_000_000),
        ("milion", 1_000_000),
        ("milliard", 1_000_000_000),
        ("million", 1_000_000),
        ("milliarde", 1_000_000_000),
        ("milhao", 1_000_000),
        ("milhoe", 1_000_000),
        ("millon", 1_000_000),
        ("millone", 1_000_000),
        ("milione", 1_000_000),
        ("milioni", 1_000_000),
    ],
    key=lambda kv: len(kv[0]),
    reverse=True,
)

# Characters used as thousands separators that are never decimal separators.
_GROUP_ONLY = "\u0020\u00a0\u202f'\u2019"  # space, NBSP, narrow NBSP, apostrophes


def _resolve_separators(raw: str) -> Optional[str]:
    """Normalise a numeric token to a plain Python float-literal string.

    Returns ``None`` when the token is not a well-formed grouped number — in
    particular when group sizes are inconsistent, which signals that the regex
    over-captured across two adjacent numbers (e.g. ``"2023 350"`` → reject so a
    year and a following amount are not fused into one bogus value).
    """
    s = raw.strip()
    if not s:
        return None

    has_comma = "," in s
    has_dot = "." in s

    # Only '.' or ',' can be a decimal separator; spaces/NBSP/apostrophes never are.
    decimal_sep: Optional[str] = None
    if has_comma and has_dot:
        # The separator that appears last is the decimal separator.
        decimal_sep = "," if s.rfind(",") > s.rfind(".") else "."
    elif has_comma or has_dot:
        sep = "," if has_comma else "."
        if s.count(sep) == 1:
            tail = s.split(sep)[1]
            # A single separator with exactly three trailing digits reads as a
            # thousands group; otherwise it is a decimal point.
            decimal_sep = sep if (tail.isdigit() and len(tail) != 3) else None
        else:
            decimal_sep = None  # multiple of one separator → all grouping

    int_part, frac_part = s, ""
    if decimal_sep is not None:
        head, _, tail = s.rpartition(decimal_sep)
        int_part, frac_part = head, tail

    # Every non-decimal separator (space, NBSP, narrow NBSP, apostrophes, and the
    # non-decimal of '.'/',') is a grouping separator. Split on all of them and
    # validate group sizes so over-captures across two numbers are rejected.
    group_chars = set(_GROUP_ONLY)
    for ch in (".", ","):
        if ch != decimal_sep:
            group_chars.add(ch)
    pattern = "[" + re.escape("".join(sorted(group_chars))) + "]"
    groups = [g for g in re.split(pattern, int_part) if g != ""]
    digits = "".join(groups)
    if not digits or not digits.isdigit():
        return None

    had_separator = any(ch in int_part for ch in group_chars)
    if had_separator:
        if not (1 <= len(groups[0]) <= 3):
            return None
        if any(len(g) != 3 for g in groups[1:]):
            return None
    if frac_part and not frac_part.isdigit():
        return None
    return f"{digits}.{frac_part}" if frac_part else digits


def _parse_number_token(raw: str) -> Optional[float]:
    normalised = _resolve_separators(raw.strip())
    if normalised is None:
        return None
    try:
        return float(normalised)
    except ValueError:
        return None


def _multiplier_for(unit: str) -> int:
    """Resolve a magnitude word (possibly inflected/accented) to its multiplier."""
    if not unit:
        return 1
    u = _strip_accents(unit.lower())
    if u in _MULTIPLIERS:
        return _MULTIPLIERS[u]
    for stem, mult in _MULTIPLIER_STEMS:
        if u.startswith(stem):
            return mult
    return 1


# A magnitude word: Latin letters (incl. accents), Cyrillic, or Greek.
_MAGNITUDE_WORD = r"[A-Za-zÀ-ÿЀ-ӿͰ-Ͽ]+"


def parse_monetary_values(text: str, *, currency: Optional[str] = None) -> list[float]:
    """Return monetary magnitudes found in text, normalised to base units."""
    values: list[float] = []
    cur = (currency or "").upper()
    money_prefix = rf"(?:{re.escape(cur)}|[$€£¥₽])" if cur else r"[$€£¥₽]"
    # A grouped number: starts and ends with a digit, may contain separators.
    number = r"\d[\d.,'\u00a0\u202f\u2019 ]*\d|\d"
    patterns = [
        # number followed by a magnitude word (currency optional)
        rf"(?:{money_prefix}\s*)?({number})\s*({_MAGNITUDE_WORD})",
        # currency-prefixed bare number
        rf"{money_prefix}\s*({number})",
    ]
    for idx, pattern in enumerate(patterns):
        for match in re.finditer(pattern, text, flags=re.I):
            number_val = _parse_number_token(match.group(1))
            if number_val is None:
                continue
            multiplier = 1
            if idx == 0:
                multiplier = _multiplier_for(match.group(2))
                # A trailing word that is not a magnitude word (e.g. "150 days")
                # leaves multiplier == 1; only keep it if a currency symbol was
                # actually present, otherwise the bare-number guard applies.
                if multiplier == 1 and not re.search(money_prefix, match.group(0)):
                    continue
            values.append(number_val * multiplier)
    values.extend(_parse_spelled_values(text))
    return values


# ── Spelled-out integers ──────────────────────────────────────────────────────
# Curated vocabulary for the languages in our source passages. Each entry maps a
# word (lowercased) to (value, kind): kind "unit" (1–99 building blocks and the
# hundreds), or "scale" (×1000 and above). The parser walks left to right,
# accumulating hundreds/tens/units into a current group and applying scale words.
_WORD_UNITS: dict[str, int] = {
    # English
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
    "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
    "eighty": 80, "ninety": 90, "hundred": 100,
    # Russian (cardinals; common gender forms)
    "один": 1, "одна": 1, "одно": 1, "два": 2, "две": 2, "три": 3,
    "четыре": 4, "пять": 5, "шесть": 6, "семь": 7, "восемь": 8, "девять": 9,
    "десять": 10, "одиннадцать": 11, "двенадцать": 12, "тринадцать": 13,
    "четырнадцать": 14, "пятнадцать": 15, "шестнадцать": 16,
    "семнадцать": 17, "восемнадцать": 18, "девятнадцать": 19,
    "двадцать": 20, "тридцать": 30, "сорок": 40, "пятьдесят": 50,
    "шестьдесят": 60, "семьдесят": 70, "восемьдесят": 80, "девяносто": 90,
    "сто": 100, "двести": 200, "триста": 300, "четыреста": 400,
    "пятьсот": 500, "шестьсот": 600, "семьсот": 700, "восемьсот": 800,
    "девятьсот": 900,
    # Greek (cardinals; neuter/common forms used with magnitudes)
    "ενα": 1, "δυο": 2, "τρια": 3, "τεσσερα": 4, "πεντε": 5, "εξι": 6,
    "επτα": 7, "εφτα": 7, "οκτω": 8, "οχτω": 8, "εννεα": 9, "δεκα": 10,
    "εικοσι": 20, "τριαντα": 30, "σαραντα": 40, "πενηντα": 50,
    "εξηντα": 60, "εβδομηντα": 70, "ογδοντα": 80, "ενενηντα": 90,
    "εκατο": 100, "διακοσια": 200, "τριακοσια": 300, "τετρακοσια": 400,
    "πεντακοσια": 500, "εξακοσια": 600, "επτακοσια": 700, "οκτακοσια": 800,
    "εννιακοσια": 900,
}

_WORD_SCALES: dict[str, int] = {
    "thousand": 1_000, "million": 1_000_000, "billion": 1_000_000_000,
    "trillion": 1_000_000_000_000,
    # Russian scale stems handled via _multiplier_for; explicit common forms:
    "тысяч": 1_000, "тысяча": 1_000, "тысячи": 1_000,
    "миллион": 1_000_000, "миллиона": 1_000_000, "миллионов": 1_000_000,
    "миллиард": 1_000_000_000, "миллиарда": 1_000_000_000,
    "миллиардов": 1_000_000_000,
    # Greek
    "χιλιαδες": 1_000, "εκατομμυριο": 1_000_000, "εκατομμυρια": 1_000_000,
    "δισεκατομμυριο": 1_000_000_000, "δισεκατομμυρια": 1_000_000_000,
}


def _scale_for_word(word: str) -> Optional[int]:
    if word in _WORD_SCALES:
        return _WORD_SCALES[word]
    mult = _multiplier_for(word)
    return mult if mult > 1 else None


def _strip_accents(text: str) -> str:
    import unicodedata

    return "".join(
        c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn"
    )


def _parse_spelled_values(text: str) -> list[float]:
    """Parse fully spelled-out integers (e.g. 'seven billion', 'восемьсот
    миллионов'). Only emits values that include a scale word ≥ 1000, so ordinary
    prose numbers ('two parties', 'three years') are ignored."""
    lowered = _strip_accents(text.lower())
    tokens = re.findall(r"[a-zЀ-ӿͰ-Ͽ]+", lowered)

    values: list[float] = []
    current = 0  # accumulated value below the next scale boundary
    group = 0  # current hundreds/tens/units group
    saw_scale = False

    def flush() -> None:
        nonlocal current, group, saw_scale
        total = current + group
        if saw_scale and total > 0:
            values.append(float(total))
        current = 0
        group = 0
        saw_scale = False

    i = 0
    consumed_any = False
    while i < len(tokens):
        tok = tokens[i]
        unit = _WORD_UNITS.get(tok)
        scale = _scale_for_word(tok)
        if unit is not None:
            if unit == 100:
                group = (group or 1) * 100
            else:
                group += unit
            consumed_any = True
            i += 1
            continue
        if scale is not None:
            multiplicand = current + group
            if multiplicand > 0:
                current = multiplicand * scale
                group = 0
                saw_scale = True
                consumed_any = True
            i += 1
            continue
        # A non-number token ends the current spelled number.
        if consumed_any:
            flush()
            consumed_any = False
        i += 1
    if consumed_any:
        flush()
    return values


def parse_share_values(text: str) -> list[float]:
    """Return share values as fractions (0–1)."""
    shares: list[float] = []
    for match in re.finditer(r"(\d+(?:[.,]\d+)?)\s*(?:%|percent|per cent|τοις εκατο)", text, flags=re.I):
        shares.append(float(match.group(1).replace(",", ".")) / 100.0)
    for match in re.finditer(r"\b0[.,]\d+\b", text):
        val = float(match.group(0).replace(",", "."))
        if 0 <= val <= 1:
            shares.append(val)
    # Statutes often express thresholds as fractions in words.
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
