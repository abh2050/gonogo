"""Identifier normalization shared by the patent, notice, and T2 modules."""

from __future__ import annotations

import re

_CASE_RE = re.compile(r"\b(?!TOP)([A-Z]{3,4})[-\s]*(\d{4,6})((?:-[0-9A-Z]+)*)")


def patent_number(value: str | None) -> str | None:
    """Return a bare US patent number such as '9297368', or None for placeholders."""
    if value is None:
        return None
    digits = re.sub(r"[^0-9A-Za-z]", "", str(value)).upper()
    digits = digits.removeprefix("US")
    digits = re.sub(r"B\d$", "", digits)
    if not digits or set(digits) == {"0"}:
        return None
    return digits.lstrip("0") or None


def application_serial(value: str | None) -> str | None:
    """Return an eight digit serial such as '13033085' from forms like '13/033,085'."""
    if value is None:
        return None
    digits = re.sub(r"\D", "", str(value))
    if len(digits) < 6 or set(digits) == {"0"}:
        return None
    return digits


def case_number(value: str | None) -> str | None:
    """Return a NASA case number in canonical form, for example 'LAR-18232-1' or 'ARC-14231-2DIV'."""
    if not value:
        return None
    text = str(value).strip().upper().replace("\u2013", "-").replace("\u2011", "-")
    m = _CASE_RE.search(text)
    if not m:
        return None
    prefix, num, rest = m.groups()
    return f"{prefix}-{num}{rest}"


def case_root(value: str | None) -> str | None:
    """Return the case family root, for example 'LAR-18232' for 'LAR-18232-2'."""
    canon = case_number(value)
    if canon is None:
        return None
    parts = canon.split("-")
    return f"{parts[0]}-{parts[1]}"


CENTER_PREFIX = {
    "ARC": "NASA Ames Research Center",
    "AFRC": "NASA Armstrong Flight Research Center",
    "DRC": "NASA Armstrong Flight Research Center",
    "GRC": "NASA Glenn Research Center",
    "LEW": "NASA Glenn Research Center",
    "GSC": "NASA Goddard Space Flight Center",
    "GSFC": "NASA Goddard Space Flight Center",
    "MSC": "NASA Johnson Space Center",
    "KSC": "NASA Kennedy Space Center",
    "LAR": "NASA Langley Research Center",
    "MFS": "NASA Marshall Space Flight Center",
    "SSC": "NASA Stennis Space Center",
    "NPO": "NASA Jet Propulsion Laboratory",
    "HQN": "NASA Headquarters",
}
