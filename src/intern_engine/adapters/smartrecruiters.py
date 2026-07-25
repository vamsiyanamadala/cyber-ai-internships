"""SmartRecruiters public postings API adapter.

GET https://api.smartrecruiters.com/v1/companies/<token>/postings?limit=100&offset=N
Paginated. Each posting exposes ``releasedDate`` (a real publish date) and a
``location`` object; the list endpoint doesn't include the full description, so
classification runs on title + department/function only.
"""

from __future__ import annotations

from .base import Adapter, iso_from_string
from ..models import Role

_PAGE = 100
_MAX_PAGES = 20


class SmartRecruitersAdapter(Adapter):
    name = "smartrecruiters"

    async def fetch(self, fetcher, company) -> list[Role]:
        roles: list[Role] = []
        offset = 0
        for _ in range(_MAX_PAGES):
            url = (f"https://api.smartrecruiters.com/v1/companies/"
                   f"{company.token}/postings?limit={_PAGE}&offset={offset}")
            res = await fetcher.get(url)
            if res.status != 200 or not isinstance(res.json, dict):
                break
            content = res.json.get("content") or []
            if not content:
                break
            for job in content:
                title = (job.get("name") or "").strip()
                if not title:
                    continue
                loc = job.get("location") or {}
                parts = [loc.get("city"), loc.get("region"), loc.get("country")]
                loc_str = ", ".join(p for p in parts if p)
                func = ((job.get("function") or {}).get("label") or "")
                dept = ((job.get("department") or {}).get("label") or "")
                posted = iso_from_string(job.get("releasedDate"))
                apply_url = (job.get("ref")
                             or f"https://jobs.smartrecruiters.com/{company.token}/{job.get('id','')}")
                roles.append(Role(
                    company=company.name,
                    title=title,
                    url=apply_url,
                    source=self.name,
                    board_token=company.token,
                    location=loc_str,
                    remote=(loc.get("remote") is True),
                    country_hint=loc.get("country") or "",
                    description=f"{func} {dept}".strip(),
                    posted_at=posted,
                    posted_source="source" if posted else "unknown",
                ))
            offset += _PAGE
            if offset >= int(res.json.get("totalFound", offset)):
                break
        return roles
