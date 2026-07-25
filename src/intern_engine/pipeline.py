"""End-to-end run: poll -> classify -> filter -> dedupe -> persist -> render."""

from __future__ import annotations

import asyncio
import os
import time

from . import classify as cls
from . import enrich, visa, locations
from .adapters import get_adapter
from .config import Settings, CompanyRef
from .dedup import dedupe
from .models import Role
from .sponsors import SponsorIndex
from .store import StateStore
from .render import (render_readme, render_csv, render_json, render_rss,
                     render_dashboard)


def _write(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


def classify_and_enrich(role: Role, sponsors: SponsorIndex) -> Role:
    cat, rtype = cls.classify(role.title, role.description)
    role.category = cat.value if cat else None
    role.role_type = rtype.value if rtype else None
    no_sponsor, citizen = visa.detect(role.description)
    role.no_sponsorship = no_sponsor
    role.citizenship_required = citizen
    role.sponsor_petitions = sponsors.lookup(role.company)
    role.sponsor_history = role.sponsor_petitions >= sponsors.min_petitions
    if not role.skills:
        role.skills = enrich.extract_skills(role.description)
    if not role.pay:
        role.pay = enrich.extract_pay(role.description)
    role.compute_uid()
    return role


def keep(role: Role, settings: Settings) -> bool:
    if role.category not in settings.categories:
        return False
    if role.role_type not in settings.role_types:
        return False
    if settings.us_only and not locations.is_us(role.location, role.country_hint):
        return False
    if settings.exclude_citizenship_required and role.citizenship_required:
        return False
    mode = settings.sponsorship_mode
    if mode == "flag_only":
        return True
    if role.no_sponsorship:
        return False
    if mode == "require_history":
        return role.sponsor_history
    # exclude_negative
    return True


async def _poll_all(companies: list[CompanyRef], settings: Settings,
                    cache: dict) -> tuple[list[Role], dict]:
    from .http import Fetcher  # lazy (needs httpx)
    raw: list[Role] = []
    meta = {"fetched_ok": 0, "sources": set(), "errors": 0}
    async with Fetcher(settings, cache=cache) as fetcher:
        async def one(company: CompanyRef):
            adapter = get_adapter(company.ats)
            if adapter is None:
                return []
            try:
                roles = await adapter.fetch(fetcher, company)
            except Exception:
                meta["errors"] += 1
                return []
            if roles:
                meta["fetched_ok"] += 1
                meta["sources"].add(company.ats)
            return roles

        for chunk in await asyncio.gather(*[one(c) for c in companies]):
            raw.extend(chunk)
    return raw, meta


def run(settings: Settings, companies: list[CompanyRef],
        offline_roles: list[Role] | None = None) -> dict:
    """Run one full cycle. Pass ``offline_roles`` to skip network (for tests)."""
    t0 = time.monotonic()

    sponsors = SponsorIndex.from_dir(
        settings.h1b_dir, min_petitions=settings.min_petitions,
        sample=settings.h1b_sample)

    store = StateStore(settings.state_path)

    if offline_roles is not None:
        raw, meta = offline_roles, {"fetched_ok": 0, "sources": set(), "errors": 0}
    else:
        raw, meta = asyncio.run(_poll_all(companies, settings, store.data["http_cache"]))

    processed = [classify_and_enrich(r, sponsors) for r in raw]
    kept = [r for r in processed if keep(r, settings)]
    kept = dedupe(kept)

    all_roles, new_roles, closed = store.reconcile(
        kept, new_window_hours=settings.new_window_hours)
    store.save()

    new_uids = {r.uid for r in new_roles}
    stats = {
        "open": len(all_roles),
        "new": len(new_roles),
        "new_uids": new_uids,
        "companies": len(companies),
        "fetched_ok": meta["fetched_ok"],
        "errors": meta["errors"],
        "sources": meta["sources"] or {c.ats for c in companies},
        "sponsors_indexed": len(sponsors),
        "duration_s": time.monotonic() - t0,
    }

    _write(settings.out_readme, render_readme(all_roles, stats, closed, settings))
    _write(settings.out_csv, render_csv(all_roles))
    _write(settings.out_json, render_json(all_roles, stats))
    _write(settings.out_rss, render_rss(
        all_roles, settings.site_url,
        "Cybersecurity & AI Internships (US)", new_uids))
    _write(settings.out_html, render_dashboard(all_roles, stats, settings, new_uids))

    return stats
