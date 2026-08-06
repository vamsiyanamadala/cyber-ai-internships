"""Phenom career-site adapter.

Many mid/large employers run their careers site on Phenom (e.g. Forvis Mazars at
``jobs.forvismazars.us``). These sites are NOT one of the classic job-board APIs,
but most expose the JSON search endpoint their own front-end calls:

    GET https://<host>/api/jobs?keyword=<q>&page=1&limit=50&sortBy=relevance
        &format=json

One adapter therefore covers every employer on the platform, not just one
company. Configure by HOST (the careers domain), not a board slug:

    phenom:
      - name: "Forvis Mazars"
        token: "jobs.forvismazars.us"

Because Phenom deployments differ (and some are locked down behind bot
protection), everything here is defensive: several response shapes and field
names are tried, and any host that doesn't answer usefully yields nothing and is
skipped like any other failing source.

Each host is queried with a small set of early-career keywords rather than being
crawled wholesale, which keeps request volume bounded on employers with
thousands of open roles.
"""

from __future__ import annotations

from urllib.parse import quote_plus, urljoin

from .base import Adapter, html_to_text, iso_any
from ..models import Role

# Bounded keyword sweep per host. Broad enough to catch early-career postings in
# either domain; the pipeline's classifier still makes the final call.
_DEFAULT_QUERIES = (
    "intern",
    "graduate",
    "cyber",
    "security",
    "machine learning",
)

_LIMIT = 50
_PAGES = 1          # one page per keyword; raise only if a host truncates results

# Response shapes seen across Phenom deployments, in order of likelihood.
_JOB_LIST_PATHS = (
    ("refineSearch", "data", "jobs"),
    ("data", "jobs"),
    ("refineSearch", "jobs"),
    ("jobs",),
    ("results",),
    ("hits",),
)

_TITLE_KEYS = ("title", "jobTitle", "name")
_URL_KEYS = ("jobDetailUrl", "applyUrl", "jobUrl", "url", "applyURL", "detailUrl")
_DATE_KEYS = ("postedDate", "createDate", "posted_date", "datePosted",
              "postedOn", "jobPostingDate")
_DESC_KEYS = ("descriptionTeaser", "description", "jobDescription",
              "shortDescription", "summary")
_LOC_KEYS = ("cityStateCountry", "location", "cityState", "jobLocation",
             "locationName", "primaryLocation")


def _dig(payload, path: tuple[str, ...]):
    node = payload
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def _first(job: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        val = job.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
        if isinstance(val, (int, float)):
            return str(val)
    return ""


def _location(job: dict) -> str:
    text = _first(job, _LOC_KEYS)
    if text:
        return text
    # some deployments split the location into parts
    parts = [str(job.get(k)).strip() for k in ("city", "state", "country")
             if isinstance(job.get(k), str) and job.get(k).strip()]
    return ", ".join(parts)


class PhenomAdapter(Adapter):
    name = "phenom"

    async def fetch(self, fetcher, company) -> list[Role]:
        host = (company.token or "").strip().strip("/")
        if not host:
            return []
        host = host.replace("https://", "").replace("http://", "")
        queries = company.extra.get("queries") or _DEFAULT_QUERIES
        if isinstance(queries, str):
            queries = [queries]

        seen: set[str] = set()
        roles: list[Role] = []
        for query in queries:
            for page in range(1, _PAGES + 1):
                url = (f"https://{host}/api/jobs?keyword={quote_plus(str(query))}"
                       f"&page={page}&limit={_LIMIT}&sortBy=relevance&format=json")
                res = await fetcher.get(url)
                if res.status != 200 or not isinstance(res.json, dict):
                    break                       # host unavailable / different shape
                jobs = self._extract_jobs(res.json)
                if not jobs:
                    break
                for job in jobs:
                    if not isinstance(job, dict):
                        continue
                    role = self._to_role(job, host, url, company)
                    if role is None:
                        continue
                    key = role.url or f"{role.company}|{role.title}|{role.location}"
                    if key in seen:
                        continue               # same posting across keywords
                    seen.add(key)
                    roles.append(role)
                if len(jobs) < _LIMIT:
                    break
        return roles

    @staticmethod
    def _extract_jobs(payload: dict) -> list:
        for path in _JOB_LIST_PATHS:
            node = _dig(payload, path)
            if isinstance(node, list) and node:
                return node
        return []

    def _to_role(self, job: dict, host: str, url: str, company) -> Role | None:
        title = html_to_text(_first(job, _TITLE_KEYS))
        if not title:
            return None
        link = _first(job, _URL_KEYS)
        if link and not link.startswith("http"):
            link = urljoin(f"https://{host}/", link.lstrip("/"))
        loc = html_to_text(_location(job))
        desc = html_to_text(_first(job, _DESC_KEYS))
        posted = iso_any(_first(job, _DATE_KEYS))
        return Role(
            company=company.name,
            title=title,
            url=link or url,
            source=self.name,
            board_token=host,
            location=loc,
            remote="remote" in f"{title} {loc}".lower(),
            description=desc,
            posted_at=posted,
            posted_source="source" if posted else "unknown",
        )
