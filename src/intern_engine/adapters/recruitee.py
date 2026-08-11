"""Recruitee adapter.

Recruitee is another widely used hosted career-site platform. Its public offers
endpoint is:

    GET https://{token}.recruitee.com/api/offers/

Response shape:
    {"offers": [{"title", "city", "state_code", "country_code", "careers_url",
                 "created_at", "description", "requirements", "department",
                 "employment_type_code"}]}

The token is the company's Recruitee subdomain. Use ``tools/discover.py`` to
verify a token before adding it — nothing enters the config unless the board
actually returned jobs.
"""

from __future__ import annotations

from .base import Adapter, html_to_text, iso_any
from ..enrich import normalize_employment_type
from ..models import Role

_TITLE_KEYS = ("title", "position", "name")
_URL_KEYS = ("careers_url", "careers_apply_url", "url", "apply_url")
_DATE_KEYS = ("published_at", "created_at", "publish_date")
_DESC_KEYS = ("description", "requirements", "highlight_html")


def _first(job: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        val = job.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _location(job: dict) -> str:
    parts = [str(job.get(k)).strip() for k in ("city", "state_name", "state_code",
                                               "country_code")
             if isinstance(job.get(k), str) and job.get(k).strip()]
    if parts:
        return ", ".join(dict.fromkeys(parts))
    return _first(job, ("location", "locations_string"))


class RecruiteeAdapter(Adapter):
    name = "recruitee"

    @staticmethod
    def board_url(token: str) -> str:
        return f"https://{token}.recruitee.com/api/offers/"

    @staticmethod
    def extract_jobs(payload) -> list:
        if isinstance(payload, dict):
            for key in ("offers", "jobs", "data"):
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
            url = _first(job, _URL_KEYS) or self.board_url(token)
            country = _first(job, ("country_code", "country"))
            roles.append(Role(
                company=company.name,
                title=title,
                url=url,
                source=self.name,
                board_token=token,
                location=loc,
                remote=bool(job.get("remote")) or "remote" in f"{title} {loc}".lower(),
                country_hint=country,
                description=desc,
                employment_type=normalize_employment_type(
                    _first(job, ("employment_type_code", "employment_type", "type"))),
                posted_at=posted,
                posted_source="source" if posted else "unknown",
            ))
        return roles
