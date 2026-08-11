"""Workable adapter.

Workable hosts a very large share of startup and mid-size career pages, none of
which the existing adapters reach. Its public widget endpoint is:

    GET https://apply.workable.com/api/v1/widget/accounts/{token}?details=true

Response shape (fields vary by account, so parsing is defensive):
    {"name": "...", "jobs": [{"title", "shortcode", "url", "application_url",
                              "shortlocation", "location": {...},
                              "created_at", "description", "department"}]}

The token is the company's Workable subdomain, e.g. ``acme`` for
``apply.workable.com/acme``. Use ``tools/discover.py`` to find and VERIFY tokens
rather than guessing: only boards that actually return jobs get written to the
config.
"""

from __future__ import annotations

from .base import Adapter, html_to_text, iso_any
from ..enrich import normalize_employment_type
from ..models import Role

_BASE = "https://apply.workable.com/api/v1/widget/accounts"

_TITLE_KEYS = ("title", "name")
_URL_KEYS = ("url", "application_url", "shortlink")
_DATE_KEYS = ("created_at", "published_on", "created", "publishedAt")
_DESC_KEYS = ("description", "requirements", "benefits")


def _first(job: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        val = job.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _location(job: dict) -> str:
    text = _first(job, ("shortlocation", "location_str", "locationSummary"))
    if text:
        return text
    loc = job.get("location")
    if isinstance(loc, dict):
        parts = [str(loc.get(k)).strip() for k in ("city", "region", "state", "country")
                 if isinstance(loc.get(k), str) and loc.get(k).strip()]
        return ", ".join(dict.fromkeys(parts))
    if isinstance(loc, str):
        return loc.strip()
    return ""


def _country_hint(job: dict) -> str:
    loc = job.get("location")
    if isinstance(loc, dict):
        for key in ("country", "country_code", "countryCode"):
            val = loc.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    val = job.get("country")
    return val.strip() if isinstance(val, str) else ""


class WorkableAdapter(Adapter):
    name = "workable"

    @staticmethod
    def board_url(token: str) -> str:
        return f"{_BASE}/{token}?details=true"

    @staticmethod
    def extract_jobs(payload) -> list:
        if isinstance(payload, dict):
            for key in ("jobs", "results", "data"):
                node = payload.get(key)
                if isinstance(node, list):
                    return node
        if isinstance(payload, list):
            return payload
        return []

    async def fetch(self, fetcher, company) -> list[Role]:
        token = (company.token or "").strip()
        if not token:
            return []
        res = await fetcher.get(self.board_url(token))
        if res.status != 200:
            return []
        roles: list[Role] = []
        for job in self.extract_jobs(res.json):
            if not isinstance(job, dict):
                continue
            title = html_to_text(_first(job, _TITLE_KEYS))
            if not title:
                continue
            loc = html_to_text(_location(job))
            desc = html_to_text(" ".join(
                str(job.get(k)) for k in _DESC_KEYS
                if isinstance(job.get(k), str) and job.get(k).strip()))
            posted = iso_any(_first(job, _DATE_KEYS))
            url = _first(job, _URL_KEYS) or f"https://apply.workable.com/{token}/"
            roles.append(Role(
                company=company.name,
                title=title,
                url=url,
                source=self.name,
                board_token=token,
                location=loc,
                remote=bool(job.get("remote")) or "remote" in f"{title} {loc}".lower(),
                country_hint=_country_hint(job),
                description=desc,
                employment_type=normalize_employment_type(
                    _first(job, ("employment_type", "type", "employmentType"))),
                posted_at=posted,
                posted_source="source" if posted else "unknown",
            ))
        return roles
