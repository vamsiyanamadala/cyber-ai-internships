"""amazon.jobs adapter.

Amazon doesn't use a third-party job board, so none of the ATS adapters reach it.
Its own careers site is backed by a public JSON search endpoint:

    GET https://www.amazon.jobs/en/search.json?base_query=<q>&country=USA
        &sort=recent&result_limit=100&offset=0

IMPORTANT (verified against the live endpoint): ``base_query`` must be a SINGLE
WORD -- multi-word queries return zero hits ("security intern" -> 0 results).
Broad single-word queries are therefore used and the engine's classifier does the
filtering. Response shape:
``{"error":..., "hits":N, "jobs":[{title, job_path, country_code, posted_date,
description, basic_qualifications, ...}]}``.

Configure with one entry per search phrase (the token IS the query):

    amazonjobs:
      - "intern"
      - "graduate"

Parsing is defensive: field names are tried in order and a host that stops
answering simply yields nothing, like any other failing source.
"""

from __future__ import annotations

from urllib.parse import quote_plus, urljoin

from .base import Adapter, html_to_text, iso_any
from ..models import Role

_BASE = "https://www.amazon.jobs/en/search.json"
_SITE = "https://www.amazon.jobs"
_LIMIT = 100
_PAGES = 3            # up to 300 per query via offset paging

# Verified against the live endpoint:
#   * `country=USA` works and returns US-only results (45 hits for "intern").
#   * `sort=recent` is honored.
#   * `country[]=USA` and `loc_query=...` are IGNORED (results stay global).
#   * MULTI-WORD `base_query` returns ZERO hits ("security intern" -> 0,
#     "new grad" -> 0), so queries must be SINGLE WORDS. Precision comes from
#     the engine's own classifier, not from the search phrase.
_US_CODES = {"USA", "US", "U.S.", "UNITED STATES"}

_TITLE_KEYS = ("title", "job_title")
_DATE_KEYS = ("posted_date", "postedDate", "updated_time", "created_date")
_LOC_KEYS = ("normalized_location", "location", "city_state_country", "city")
_DESC_KEYS = ("description", "description_short", "basic_qualifications",
              "preferred_qualifications")
_PATH_KEYS = ("job_path", "url", "jobPath")


def _first(job: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        val = job.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _is_us(job: dict) -> bool:
    """Belt-and-braces US check; unknown country -> keep (pipeline decides)."""
    code = job.get("country_code")
    if isinstance(code, str) and code.strip():
        return code.strip().upper() in _US_CODES
    return True


class AmazonJobsAdapter(Adapter):
    name = "amazonjobs"

    async def fetch(self, fetcher, company) -> list[Role]:
        query = (company.token or "").strip()
        if not query:
            return []
        roles: list[Role] = []
        for page in range(_PAGES):
            offset = page * _LIMIT
            url = (f"{_BASE}?base_query={quote_plus(query)}&country=USA"
                   f"&sort=recent&result_limit={_LIMIT}&offset={offset}")
            res = await fetcher.get(url)
            if res.status != 200 or not isinstance(res.json, dict):
                break
            jobs = res.json.get("jobs")
            if not isinstance(jobs, list) or not jobs:
                break
            for job in jobs:
                if not isinstance(job, dict) or not _is_us(job):
                    continue
                role = self._to_role(job, url)
                if role is not None:
                    roles.append(role)
            if len(jobs) < _LIMIT:
                break
        return roles

    def _to_role(self, job: dict, url: str) -> Role | None:
        title = html_to_text(_first(job, _TITLE_KEYS))
        if not title:
            return None
        path = _first(job, _PATH_KEYS)
        link = urljoin(_SITE, path) if path else url
        loc = html_to_text(_first(job, _LOC_KEYS))
        if not loc:
            parts = [str(job.get(k)).strip() for k in ("city", "state", "country_code")
                     if isinstance(job.get(k), str) and job.get(k).strip()]
            loc = ", ".join(parts)
        desc = html_to_text(" ".join(
            str(job.get(k)) for k in _DESC_KEYS
            if isinstance(job.get(k), str) and job.get(k).strip()
        ))
        posted = iso_any(_first(job, _DATE_KEYS))
        return Role(
            company=str(job.get("company_name") or "Amazon").strip() or "Amazon",
            title=title,
            url=link,
            source=self.name,
            board_token="amazon.jobs",
            location=loc,
            remote="remote" in f"{title} {loc}".lower(),
            country_hint="US",
            description=desc,
            posted_at=posted,
            posted_source="source" if posted else "unknown",
        )
