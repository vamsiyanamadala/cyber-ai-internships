"""Lever Postings API adapter.

GET https://api.lever.co/v0/postings/<token>?mode=json
Lever exposes ``createdAt`` (epoch ms) — a genuine publish date — so we trust it.
"""

from __future__ import annotations

from .base import Adapter, html_to_text, iso_from_epoch_ms
from ..models import Role


class LeverAdapter(Adapter):
    name = "lever"

    async def fetch(self, fetcher, company) -> list[Role]:
        url = f"https://api.lever.co/v0/postings/{company.token}?mode=json"
        res = await fetcher.get(url)
        if res.status != 200 or not isinstance(res.json, list):
            return []
        roles: list[Role] = []
        for job in res.json:
            title = (job.get("text") or "").strip()
            if not title:
                continue
            cats = job.get("categories") or {}
            loc = (cats.get("location") or "").strip()
            desc = html_to_text(job.get("description") or "") or (job.get("descriptionPlain") or "")
            posted = iso_from_epoch_ms(job.get("createdAt"))
            country = (job.get("country") or "").strip()
            roles.append(Role(
                company=company.name,
                title=title,
                url=job.get("hostedUrl") or job.get("applyUrl") or url,
                source=self.name,
                board_token=company.token,
                location=loc,
                remote="remote" in (loc + (cats.get("commitment") or "")).lower(),
                country_hint=country,
                description=desc,
                posted_at=posted,
                posted_source="source" if posted else "unknown",
            ))
        return roles
