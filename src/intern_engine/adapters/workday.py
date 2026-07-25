"""Workday adapter (experimental).

POST https://<host>/wday/cxs/<tenant>/<site>/jobs   body: {limit, offset, ...}
Workday tenants vary a lot and only expose *relative* posting dates
("Posted 5 Days Ago"), so we don't trust them — first-seen anchors the date.
Requires ``host`` and ``site`` in the company's config; ``tenant`` is inferred
from the host subdomain when not given.
"""

from __future__ import annotations

from .base import Adapter, html_to_text
from ..models import Role

_PAGE = 20
_MAX_PAGES = 25


class WorkdayAdapter(Adapter):
    name = "workday"

    async def fetch(self, fetcher, company) -> list[Role]:
        host = company.extra.get("host")
        site = company.extra.get("site", "External")
        tenant = company.extra.get("tenant") or company.token
        if not host:
            return []
        base = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
        roles: list[Role] = []
        offset = 0
        for _ in range(_MAX_PAGES):
            body = {"appliedFacets": {}, "limit": _PAGE, "offset": offset, "searchText": ""}
            res = await fetcher.get(base, method="POST", json_body=body)
            if res.status != 200 or not isinstance(res.json, dict):
                break
            postings = res.json.get("jobPostings") or []
            if not postings:
                break
            for job in postings:
                title = (job.get("title") or "").strip()
                if not title:
                    continue
                ext = job.get("externalPath") or ""
                apply_url = f"https://{host}{ext}" if ext else base
                roles.append(Role(
                    company=company.name,
                    title=title,
                    url=apply_url,
                    source=self.name,
                    board_token=company.token,
                    location=(job.get("locationsText") or "").strip(),
                    description=html_to_text(job.get("jobDescription") or ""),
                    posted_at=None,          # only relative dates available
                    posted_source="unknown",
                ))
            offset += _PAGE
            total = int(res.json.get("total", offset))
            if offset >= total:
                break
        return roles
