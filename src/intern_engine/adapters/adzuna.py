"""Adzuna job-search API adapter (aggregator source).

Unlike the per-company ATS adapters, Adzuna is a *search* API: each configured
entry under ``adzuna:`` in companies.yml is a search PHRASE, not a company
token. Results come from thousands of employers, so this is what widens coverage
beyond the boards you hand-list. The real employer name comes from each result
and still runs through the same classify + USCIS sponsorship filter as every
other source, so sponsor-filtering is unchanged.

    GET https://api.adzuna.com/v1/api/jobs/us/search/<page>
        ?app_id=..&app_key=..&what=<phrase>&results_per_page=50
        &sort_by=date&max_days_old=<n>&content-type=application/json

Credentials come from the ENVIRONMENT, never the repo:
    ADZUNA_APP_ID, ADZUNA_APP_KEY      (free at https://developer.adzuna.com)
If either is missing the adapter yields nothing and the run continues normally.
"""

from __future__ import annotations

import os
from urllib.parse import quote_plus

from .base import Adapter, html_to_text, iso_from_string
from ..models import Role

_BASE = "https://api.adzuna.com/v1/api/jobs/us/search"
_RESULTS_PER_PAGE = 50
_MAX_DAYS_OLD = 40          # recent only; internships from roughly the last 6 weeks
_PAGES = 1                  # one page per phrase keeps well inside the free tier


class AdzunaAdapter(Adapter):
    name = "adzuna"

    @staticmethod
    def _creds() -> tuple[str | None, str | None]:
        return os.environ.get("ADZUNA_APP_ID"), os.environ.get("ADZUNA_APP_KEY")

    async def fetch(self, fetcher, company) -> list[Role]:
        app_id, app_key = self._creds()
        if not app_id or not app_key:
            return []                                   # no key -> skip quietly
        entry = (company.token or "").strip()
        if not entry:
            return []
        # "company:<Name>" targets a specific employer via Adzuna's company
        # filter; anything else is a keyword search.
        target = None
        if entry.lower().startswith("company:"):
            target = entry.split(":", 1)[1].strip()
            if not target:
                return []
        auth = f"app_id={quote_plus(app_id)}&app_key={quote_plus(app_key)}"
        common = (f"&results_per_page={_RESULTS_PER_PAGE}&sort_by=date"
                  f"&max_days_old={_MAX_DAYS_OLD}&content-type=application/json")
        roles: list[Role] = []
        for page in range(1, _PAGES + 1):
            if target:
                url = f"{_BASE}/{page}?{auth}&company={quote_plus(target)}{common}"
            else:
                url = f"{_BASE}/{page}?{auth}&what={quote_plus(entry)}{common}"
            res = await fetcher.get(url)
            if res.status != 200 or not isinstance(res.json, dict):
                break
            results = res.json.get("results") or []
            for job in results:
                if not isinstance(job, dict):
                    continue
                role = self._to_role(job, url)
                # guard: keep only real matches when targeting a company, in case
                # the server-side filter is loose
                if target and not self._company_matches(role.company, target):
                    continue
                roles.append(role)
            if len(results) < _RESULTS_PER_PAGE:
                break                                   # reached the last page
        return roles

    @staticmethod
    def _company_matches(display: str, target: str) -> bool:
        norm = lambda s: "".join(c if c.isalnum() or c == " " else " " for c in s.lower())
        d, t = norm(display), norm(target)
        toks = [w for w in t.split() if len(w) >= 3]
        if not toks:                                    # target too short to filter safely
            return True
        hits = sum(1 for w in toks if w in d)
        return hits / len(toks) >= 0.6 or t.strip() in d or d.strip() in t

    def _to_role(self, job: dict, url: str) -> Role:
        title = html_to_text(job.get("title") or "")
        emp = ((job.get("company") or {}).get("display_name") or "").strip()
        loc = ((job.get("location") or {}).get("display_name") or "").strip()
        desc = html_to_text(job.get("description") or "")
        posted = iso_from_string(job.get("created"))
        predicted = str(job.get("salary_is_predicted", "0")) == "1"
        pay = ""
        if not predicted and job.get("salary_min"):
            try:
                smin = int(float(job.get("salary_min")))
                smax = int(float(job.get("salary_max") or smin))
                pay = f"${smin:,}-${smax:,}/yr" if smax != smin else f"${smin:,}/yr"
            except (TypeError, ValueError):
                pay = ""
        return Role(
            company=emp or "(unknown employer)",
            title=title,
            url=job.get("redirect_url") or url,
            source=self.name,
            board_token="",
            location=loc,
            remote="remote" in f"{title} {loc}".lower(),
            country_hint="US",                          # /us/ endpoint guarantees US
            description=desc,
            pay=pay,
            posted_at=posted,
            posted_source="source" if posted else "unknown",
        )
