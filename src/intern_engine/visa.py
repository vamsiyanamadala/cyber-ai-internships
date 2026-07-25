"""Detect visa-relevant language in a posting.

Two independent signals:

* ``no_sponsorship`` — the posting explicitly states the employer will not
  provide visa sponsorship. These roles are dropped in ``require_history`` and
  ``exclude_negative`` modes.
* ``citizenship_required`` — the posting requires US citizenship or a security
  clearance. An international candidate can't take these, and they inherently
  can't lead to H-1B sponsorship, so by default they're excluded too.

This is a text heuristic, not ground truth: wording varies and postings change.
Treat the flags as strong hints and always confirm on the source posting.
"""

from __future__ import annotations

import re

NO_SPONSOR_PATTERNS = [
    re.compile(p, re.I)
    for p in [
        r"\b(will|does|can)\s*not\s+(?:be\s+able\s+to\s+)?(?:provide|offer|sponsor)\b.*\bsponsor",
        r"\bunable\s+to\s+(?:provide|offer|sponsor)\b.*sponsor",
        r"\bno\s+(?:visa\s+)?sponsorship\b",
        r"\bsponsorship\s+is\s+not\s+(?:available|offered|provided)\b",
        r"\bnot\s+(?:provide|offer)\s+(?:visa\s+)?sponsorship\b",
        r"\bwithout\s+(?:the\s+need\s+for\s+)?(?:visa\s+|employer\s+)?sponsorship\b",
        r"\bmust\s+not\s+require\s+(?:visa\s+)?sponsorship\b",
        r"\b(?:now\s+or\s+in\s+the\s+future).*\bsponsor",
        r"\bnot\s+eligible\s+for\s+(?:visa\s+)?sponsorship\b",
        r"\bwe\s+are\s+(?:not|unable)\b.*\bsponsor",
        r"\bcannot\s+sponsor\b",
    ]
]

CITIZENSHIP_PATTERNS = [
    re.compile(p, re.I)
    for p in [
        r"\bu\.?\s?s\.?\s+citizen(ship)?\b",
        r"\bunited\s+states\s+citizen",
        r"\bmust\s+be\s+a\s+(?:u\.?s\.?\s+)?citizen\b",
        r"\bcitizenship\s+is\s+required\b",
        r"\bsecurity\s+clearance\b",
        r"\bactive\s+clearance\b",
        r"\b(?:obtain|maintain)\s+a\s+(?:security\s+)?clearance\b",
        r"\bts\/sci\b",
        r"\bpublic\s+trust\b",
        r"\bitar\b",
    ]
]


def detect(description: str) -> tuple[bool, bool]:
    """Return ``(no_sponsorship, citizenship_required)`` for a description."""
    text = description or ""
    no_sponsor = any(p.search(text) for p in NO_SPONSOR_PATTERNS)
    citizenship = any(p.search(text) for p in CITIZENSHIP_PATTERNS)
    return no_sponsor, citizenship
