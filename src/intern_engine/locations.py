"""Decide whether a role is US-based, for the ``us_only`` filter."""

from __future__ import annotations

import re

_STATES = {
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho",
    "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana", "maine",
    "maryland", "massachusetts", "michigan", "minnesota", "mississippi",
    "missouri", "montana", "nebraska", "nevada", "new hampshire", "new jersey",
    "new mexico", "new york", "north carolina", "north dakota", "ohio",
    "oklahoma", "oregon", "pennsylvania", "rhode island", "south carolina",
    "south dakota", "tennessee", "texas", "utah", "vermont", "virginia",
    "washington", "west virginia", "wisconsin", "wyoming",
}
_ABBR = {
    "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga", "hi", "id",
    "il", "in", "ia", "ks", "ky", "la", "me", "md", "ma", "mi", "mn", "ms",
    "mo", "mt", "ne", "nv", "nh", "nj", "nm", "ny", "nc", "nd", "oh", "ok",
    "or", "pa", "ri", "sc", "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv",
    "wi", "wy", "dc",
}
_US_HINTS = re.compile(
    r"\b(usa|u\.s\.a?\.?|united states|remote\s*[-,]?\s*us|us\s+remote)\b", re.I)

_NON_US = re.compile(
    r"\b(canada|india|united kingdom|uk|england|ireland|germany|france|spain|"
    r"portugal|poland|netherlands|switzerland|sweden|norway|finland|denmark|"
    r"australia|singapore|japan|china|korea|mexico|brazil|argentina|israel|"
    r"uae|dubai|remote\s*[-,]?\s*(emea|apac|eu|europe|canada|india))\b", re.I)

_WORD = re.compile(r"[a-z]+", re.I)


def is_us(location: str, country_hint: str = "") -> bool:
    text = f"{location} {country_hint}".strip()
    if not text:
        return True  # unknown -> don't discard (tune with us_only if noisy)
    low = text.lower()
    if _NON_US.search(low) and not _US_HINTS.search(low):
        return False
    if _US_HINTS.search(low):
        return True

    # A location written as "City, Region, cc" ends in a COUNTRY code, not a US
    # state abbreviation. Without this, "Gerlingen, BW, de" matched "de" from the
    # state list and Germany was accepted as Delaware.
    parts = [p.strip() for p in str(location).split(",") if p.strip()]
    if len(parts) >= 3 and len(parts[-1]) == 2 and parts[-1].isalpha():
        return parts[-1].lower() == "us"

    words = set(_WORD.findall(low))
    if words & _STATES:
        return True
    # 2-letter state codes only count as tokens (avoid matching inside words)
    tokens = set(re.findall(r"\b[a-z]{2}\b", low))
    if tokens & _ABBR:
        return True
    # remote with no country cue -> treat as possibly US
    if "remote" in low and not _NON_US.search(low):
        return True
    return False
