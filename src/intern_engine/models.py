"""Core data structures shared across the engine.

A ``Role`` is the normalized representation of a single job posting after it has
been pulled from an ATS, classified, and enriched. Adapters produce partially
filled ``Role`` objects (identity + raw description); the pipeline fills in the
classification, visa, and sponsorship fields.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional


class Category(str, Enum):
    CYBER = "Cybersecurity"
    AI = "AI/ML"
    SOFTWARE = "Software"


class RoleType(str, Enum):
    INTERN = "Internship"
    COOP = "Co-op"
    APPRENTICE = "Apprenticeship"
    NEWGRAD = "New Grad"


_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^a-z0-9 ]+")


def _norm(text: str) -> str:
    text = (text or "").lower()
    text = _PUNCT.sub(" ", text)
    return _WS.sub(" ", text).strip()


@dataclass
class Role:
    # --- identity (filled by adapters) ---
    company: str
    title: str
    url: str
    source: str = ""          # ATS platform name, e.g. "greenhouse"
    board_token: str = ""     # the company's slug on that ATS

    # --- location ---
    location: str = ""
    remote: bool = False
    country_hint: str = ""    # anything the source told us about country

    # --- raw text (used for classification; not serialized to outputs) ---
    description: str = field(default="", repr=False)

    # --- classification (filled by pipeline) ---
    category: Optional[str] = None      # Category.value
    role_type: Optional[str] = None     # RoleType.value — career stage
    # Employment nature (hours/contract), which is a DIFFERENT axis from
    # role_type: an internship is usually full-time hours, and a New Grad role is
    # full-time permanent. Taken from the source when it publishes one, otherwise
    # inferred from explicit wording in the posting; blank when unknown.
    employment_type: str = ""           # "Full-time" | "Part-time" | "Contract" | ""

    # --- visa / sponsorship ---
    no_sponsorship: bool = False        # posting text says it won't sponsor
    citizenship_required: bool = False  # posting requires US citizenship/clearance
    sponsor_history: bool = False       # employer has an H-1B track record
    sponsor_petitions: int = 0          # approved H-1B petitions on record

    # --- enrichment ---
    skills: list[str] = field(default_factory=list)
    pay: str = ""

    # --- dates ---
    posted_at: Optional[str] = None       # ISO date, best available
    posted_source: str = "unknown"        # "source" | "first_seen"
    first_seen: Optional[str] = None       # ISO date engine first saw it
    last_seen: Optional[str] = None

    # --- dedup ---
    uid: str = ""

    def compute_uid(self) -> str:
        """Stable id from company + title + first location token.

        Deliberately coarse so the *same* role surfaced by two different ATS
        sources collapses to one entry.
        """
        loc_token = _norm(self.location).split(" ")[0] if self.location else ""
        key = f"{_norm(self.company)}|{_norm(self.title)}|{loc_token}"
        self.uid = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
        return self.uid

    def to_public_dict(self) -> dict:
        """Serializable view for JSON/CSV — omits the raw description blob."""
        d = asdict(self)
        d.pop("description", None)
        return d
