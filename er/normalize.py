"""Normalize organization names and addresses so that spelling differences do not hide a match."""

from __future__ import annotations

import re
import unicodedata

# Legal-form words carry no identity. The resolver strips them from the end of a name.
LEGAL_SUFFIXES = {
    "inc",
    "incorporated",
    "llc",
    "llp",
    "lp",
    "ltd",
    "limited",
    "corp",
    "corporation",
    "co",
    "company",
    "gmbh",
    "plc",
    "ag",
    "ab",
    "sa",
    "nv",
    "bv",
    "pty",
    "kk",
    "oy",
    "srl",
    "spa",
    "pbc",
    "pllc",
    "lc",
}
# "X, a Y Company" and "X and its subsidiary Z" name a second party after the first. The first is the licensee.
PARENT_CLAUSE = re.compile(
    r"(?:,\s*an?\s+|\s+an?\s+(?:division|subsidiary|affiliate)\s+of\s+|\s+and\s+its\s+subsidiary\s+)", re.I
)
STATES = {
    "alabama": "al",
    "alaska": "ak",
    "arizona": "az",
    "arkansas": "ar",
    "california": "ca",
    "colorado": "co",
    "connecticut": "ct",
    "delaware": "de",
    "florida": "fl",
    "georgia": "ga",
    "hawaii": "hi",
    "idaho": "id",
    "illinois": "il",
    "indiana": "in",
    "iowa": "ia",
    "kansas": "ks",
    "kentucky": "ky",
    "louisiana": "la",
    "maine": "me",
    "maryland": "md",
    "massachusetts": "ma",
    "michigan": "mi",
    "minnesota": "mn",
    "mississippi": "ms",
    "missouri": "mo",
    "montana": "mt",
    "nebraska": "ne",
    "nevada": "nv",
    "new hampshire": "nh",
    "new jersey": "nj",
    "new mexico": "nm",
    "new york": "ny",
    "north carolina": "nc",
    "north dakota": "nd",
    "ohio": "oh",
    "oklahoma": "ok",
    "oregon": "or",
    "pennsylvania": "pa",
    "rhode island": "ri",
    "south carolina": "sc",
    "south dakota": "sd",
    "tennessee": "tn",
    "texas": "tx",
    "utah": "ut",
    "vermont": "vt",
    "virginia": "va",
    "washington": "wa",
    "west virginia": "wv",
    "wisconsin": "wi",
    "wyoming": "wy",
}
ADDRESS_STOP = {
    "the",
    "of",
    "and",
    "usa",
    "us",
    "united",
    "states",
    "street",
    "st",
    "road",
    "rd",
    "avenue",
    "ave",
    "suite",
}


def _ascii(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def primary_name(name: str) -> str:
    """The licensee itself, without a parent or subsidiary clause."""
    return PARENT_CLAUSE.split(name, maxsplit=1)[0]


def tokens(name: str) -> list[str]:
    """Lower-case words of a name, with punctuation and legal-form words removed."""
    text = _ascii(primary_name(name)).lower()
    text = text.replace("&", " and ")
    text = re.sub(r"public limited company", "plc", text)
    text = re.sub(r"[.'`\"]", "", text)  # dots join initials: "L.L.C." becomes "llc"
    text = re.sub(r"[^a-z0-9]+", " ", text).strip()
    words = text.split()
    if words and words[0] == "the":
        words = words[1:]
    while words and words[-1] in LEGAL_SUFFIXES:
        words.pop()
    return words


def normalize(name: str) -> str:
    return " ".join(tokens(name))


def compact(name: str) -> str:
    """The name with every space removed, so "Bio-Process" and "Bioprocess" compare equal."""
    return "".join(tokens(name))


def address_tokens(address: str | None) -> set[str]:
    if not address:
        return set()
    text = _ascii(address).lower()
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    text = " ".join(text.split())
    for state, abbreviation in sorted(STATES.items(), key=lambda kv: -len(kv[0])):
        text = re.sub(rf"\b{state}\b", abbreviation, text)
    return {t for t in text.split() if t not in ADDRESS_STOP and not t.isdigit()}
