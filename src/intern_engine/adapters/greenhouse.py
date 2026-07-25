"""Greenhouse Job Board API adapter.

GET https://boards-api.greenhouse.io/v1/boards/<token>/jobs?content=true
Note: Greenhouse only exposes ``updated_at`` (not a first-published date), so we
treat dates as a weak hint and let the state store anchor "Posted" to first-seen.
"""

from __future__ import annotations

from .base import Adapter, html_to_text
from ..models import Role


class GreenhouseAdapter(Adapter):
    name = "greenhouse"

    async def fetch(self, fetcher, company) -> list[Role]:
        url = f"https://boards-api.greenhouse.io/v1/boards/{company.token}/jobs?content=true"
        res = await fetcher.get(url)
        if res.status != 200 or not isinstance(res.json, dict):
            return []
        roles: list[Role] = []
        for job in res.json.get("jobs", []) or []:
            title = (job.get("title") or "").strip()
            if not title:
                continue
            loc = ((job.get("location") or {}).get("name") or "").strip()
            desc = html_to_text(job.get("content") or "")
            # some boards stash a real location in metadata
            meta = {m.get("name", "").lower(): m.get("value")
                    for m in (job.get("metadata") or []) if isinstance(m, dict)}
            if not loc and meta.get("job posting location"):
                loc = str(meta["job posting location"])
            roles.append(Role(
                company=company.name,
                title=title,
                url=job.get("absolute_url", url),
                source=self.name,
                board_token=company.token,
                location=loc,
                remote="remote" in loc.lower(),
                description=desc,
                # updated_at is an *edit* time, not a publish date -> leave the
                # posting date to the state store (anchored on first_seen).
                posted_at=None,
                posted_source="unknown",
            ))
        return roles
