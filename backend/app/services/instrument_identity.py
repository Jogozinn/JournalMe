from __future__ import annotations

import re
from datetime import datetime, timezone

MONTH_CODES = {
    "F": 1,
    "G": 2,
    "H": 3,
    "J": 4,
    "K": 5,
    "M": 6,
    "N": 7,
    "Q": 8,
    "U": 9,
    "V": 10,
    "X": 11,
    "Z": 12,
}


def _reference_year(reference: datetime | None) -> int:
    if reference is None:
        return datetime.now(timezone.utc).year
    if reference.tzinfo is None:
        return reference.year
    return reference.astimezone(timezone.utc).year


def _expand_contract_year(value: str, reference: datetime | None) -> int:
    ref_year = _reference_year(reference)
    numeric = int(value)
    if len(value) == 1:
        decade = (ref_year // 10) * 10
        candidates = [decade - 10 + numeric, decade + numeric, decade + 10 + numeric]
        return min(candidates, key=lambda candidate: abs(candidate - ref_year))
    if len(value) == 2:
        century = (ref_year // 100) * 100
        candidate = century + numeric
        if candidate - ref_year > 50:
            candidate -= 100
        elif ref_year - candidate > 50:
            candidate += 100
        return candidate
    return numeric


def root_symbol(symbol: str) -> str:
    compact = re.sub(r"\s+", "", (symbol or "").upper())
    if not compact:
        return ""
    if match := re.match(r"^([A-Z0-9]+?)(\d{2})-(\d{2})$", compact):
        return match.group(1)
    if match := re.match(r"^([A-Z0-9]+?)([FGHJKMNQUVXZ])(\d{1,2})$", compact):
        return match.group(1)
    return compact


def canonical_contract_key(symbol: str, reference: datetime | None = None) -> str:
    """Return a cross-provider contract identity.

    NinjaTrader commonly emits ``MNQ 12-26`` while Tradovate emits ``MNQZ6``.
    Both normalize to ``MNQ:2026-12`` when the execution occurred in 2026.
    Unknown/non-futures symbols fall back to their whitespace-free uppercase form.
    """
    compact = re.sub(r"\s+", "", (symbol or "").upper())
    if not compact:
        return ""

    if match := re.match(r"^([A-Z0-9]+?)(\d{2})-(\d{2})$", compact):
        root, month_text, year_text = match.groups()
        month = int(month_text)
        if 1 <= month <= 12:
            year = _expand_contract_year(year_text, reference)
            return f"{root}:{year:04d}-{month:02d}"

    if match := re.match(r"^([A-Z0-9]+?)([FGHJKMNQUVXZ])(\d{1,2})$", compact):
        root, month_code, year_text = match.groups()
        year = _expand_contract_year(year_text, reference)
        return f"{root}:{year:04d}-{MONTH_CODES[month_code]:02d}"

    return compact
