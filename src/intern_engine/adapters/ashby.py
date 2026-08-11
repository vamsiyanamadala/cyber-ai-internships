"""Ashby public Job Posting API adapter.

GET https://api.ashbyhq.com/posting-api/job-board/<token>?includeCompensation=true
Returns {"jobs": [...]}. Includes descriptionPlain, compensation, workplaceType,
and address country. Publish dates are inconsistent across boards, so we only
trust an explicit publishedDate/publishedAt when present.
"""

from __future__ import annotations

from .base import Adapter, html_to_text, iso_from_string
from ..enrich import normalize_employment_type
from ..models import Role, RoleType


class AshbyAdapter(Adapter):
    name = "ashby"

    async def fetch(self, fetcher, company) -> list[Role]:
        url = (f"https://api.ashbyhq.com/posting-api/job-board/"
               f"{company.token}?includeCompensation=true")
        res = await fetcher.get(url)
        if res.status != 200 or not isinstance(res.json, dict):
            return []
        roles: list[Role] = []
        for job in res.json.get("jobs", []) or []:
            if job.get("isListed") is False:
                continue
            title = (job.get("title") or "").strip()
            if not title:
                continue
            loc = (job.get("location") or "").strip()
            desc = (job.get("descriptionPlain")
                    or html_to_text(job.get("descriptionHtml") or ""))
            country = ""
            addr = (job.get("address") or {}).get("postalAddress") or {}
            if isinstance(addr, dict):
                country = (addr.get("addressCountry") or "").strip()
            comp = job.get("compensation") or {}
            pay = ""
            if isinstance(comp, dict):
                pay = (comp.get("compensationTierSummary")
                       or comp.get("scrapeableCompensationSalarySummary") or "")
            posted = (iso_from_string(job.get("publishedDate"))
                      or iso_from_string(job.get("publishedAt")))
            # Ashby states the employment type outright (FullTime / Intern / ...),
            # so use it rather than inferring, and treat "Intern" as a declared
            # career stage.
            emp_raw = (job.get("employmentType") or "")
            declared_type = None
            if isinstance(emp_raw, str) and "intern" in emp_raw.lower():
                declared_type = RoleType.INTERN.value
            roles.append(Role(
                company=company.name,
                title=title,
                url=job.get("applyUrl") or job.get("jobUrl") or url,
                source=self.name,
                board_token=company.token,
                location=loc,
                # NOTE: dict.get(key, default) returns the default only when the
                # key is MISSING. Ashby sends explicit nulls, so the default never
                # applied and .lower() raised AttributeError — which silently cost
                # every Ashby board with a null workplaceType.
                remote=bool(job.get("isRemote"))
                       or ((job.get("workplaceType") or "").lower() == "remote"),
                country_hint=country,
                description=desc,
                pay=pay.strip() if isinstance(pay, str) else "",
                role_type=declared_type,
                employment_type=normalize_employment_type(emp_raw),
                posted_at=posted,
                posted_source="source" if posted else "unknown",
            ))
        return roles
