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
from .models import Role, RoleType
from .sponsors import SponsorIndex
from .store import StateStore
from .render import (render_readme, render_csv, render_json, render_rss,
                     render_dashboard)


# Long runs with no output look like a hang, which invites Ctrl+C mid-poll.
# Progress is printed for real runs and suppressed for offline tests.
_progress = True


def set_progress(enabled: bool) -> None:
    global _progress
    _progress = enabled


def _log(message: str) -> None:
    if _progress:
        print(message, flush=True)


def _write(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


def _reconcile_role_type(hint: str | None, inferred, title: str = "") -> str | None:
    """Combine a source-declared role type with the inferred one.

    Some sources state the career stage outright (amazon.jobs publishes
    ``is_intern``), which beats inference. When both exist, an explicit
    internship / co-op / apprenticeship signal wins over a generic New Grad
    guess, since the specific formats are what the person is filtering for.
    """
    # A senior/levelled title overrules any source-declared type. amazon.jobs
    # marks some senior postings as interns; without this the hint would put
    # "Sr. Security Engineer" back on the board.
    if title and cls.is_senior_title(title):
        return None
    inferred_val = inferred.value if inferred is not None else None
    if not hint:
        return inferred_val
    if inferred_val is None:
        return hint
    if inferred_val == RoleType.NEWGRAD.value and hint != RoleType.NEWGRAD.value:
        return hint                      # source says intern/co-op -> trust it
    return inferred_val


def screen(role: Role, sponsors: SponsorIndex) -> Role:
    """Decide category, role type and sponsorship — the fields ``keep()`` needs.

    Deliberately does NOT extract skills or pay. With hundreds of boards the
    engine sees tens of thousands of postings and discards most of them, so the
    expensive per-posting text mining is deferred to ``enrich_kept()`` and only
    runs on roles that actually survive the filter.
    """
    cat, rtype = cls.classify(role.title, role.description)
    role.category = cat.value if cat else None
    # adapters may pre-set role_type when the source declares it
    role.role_type = _reconcile_role_type(role.role_type, rtype, role.title)
    role.compute_uid()
    if role.category is None or role.role_type is None:
        return role                     # doomed anyway; skip the remaining work
    if not role.employment_type:
        role.employment_type = enrich.detect_employment_type(
            role.title, role.description)
    no_sponsor, citizen = visa.detect(role.description)
    role.no_sponsorship = no_sponsor
    role.citizenship_required = citizen
    role.sponsor_petitions = sponsors.lookup(role.company)
    role.sponsor_history = role.sponsor_petitions >= sponsors.min_petitions
    return role


def enrich_kept(role: Role) -> Role:
    """Skill tags and pay — run only on roles that passed the filter."""
    if not role.skills:
        role.skills = enrich.extract_skills(role.description)
    if not role.pay:
        role.pay = enrich.extract_pay(role.description)
    return role


def classify_and_enrich(role: Role, sponsors: SponsorIndex) -> Role:
    """Screen and enrich in one call (kept for tests and single-role use)."""
    screen(role, sponsors)
    return enrich_kept(role)


def reject_reason(role: Role, settings: Settings) -> str | None:
    """Why this role is dropped, or None when it is kept.

    Returning the reason (rather than a bare bool) lets a run report where its
    postings went, which is the difference between diagnosing a yield change and
    guessing at it.
    """
    # Role type is checked first because classification short-circuits on it: when
    # a posting isn't early-career the domain is never computed, so blaming the
    # domain would misreport the real cause.
    if role.role_type not in settings.role_types:
        return "not early-career (intern/co-op/apprentice/new-grad)"
    if role.category not in settings.categories:
        return "not cyber/AI/software"
    if settings.us_only and not locations.is_us(role.location, role.country_hint):
        return "not US"
    if settings.exclude_citizenship_required and role.citizenship_required:
        return "citizenship/clearance required"
    mode = settings.sponsorship_mode
    if mode == "flag_only":
        return None
    if role.no_sponsorship:
        return "posting says no sponsorship"
    if mode == "require_history" and not role.sponsor_history:
        return "employer has no H-1B history"
    return None


def keep(role: Role, settings: Settings) -> bool:
    return reject_reason(role, settings) is None


def _keep_legacy(role: Role, settings: Settings) -> bool:
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
    meta = {"fetched_ok": 0, "sources": set(), "errors": 0, "failures": []}
    total = len(companies)
    done = 0
    step = max(1, total // 20)          # ~20 progress lines, whatever the size
    async with Fetcher(settings, cache=cache) as fetcher:
        async def one(company: CompanyRef):
            nonlocal done
            adapter = get_adapter(company.ats)
            if adapter is None:
                return []
            try:
                roles = await adapter.fetch(fetcher, company)
            except Exception as exc:
                meta["errors"] += 1
                meta["failures"].append(
                    (company.ats, company.name, type(exc).__name__, str(exc)[:120]))
                roles = []
            else:
                if roles:
                    meta["fetched_ok"] += 1
                    meta["sources"].add(company.ats)
            done += 1
            if _progress and (done % step == 0 or done == total):
                print(f"  polled {done}/{total} boards "
                      f"({meta['fetched_ok']} with roles, {meta['errors']} errors)",
                      flush=True)
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
        _log(f"  polling {len(companies)} boards "
             f"(concurrency {settings.concurrency})...")
        raw, meta = asyncio.run(_poll_all(companies, settings, store.data["http_cache"]))
        failures = meta.get("failures") or []
        if failures:
            by_ats, by_kind = {}, {}
            for ats, _name, kind, _msg in failures:
                by_ats[ats] = by_ats.get(ats, 0) + 1
                by_kind[kind] = by_kind.get(kind, 0) + 1
            _log(f"  {len(failures)} boards failed — by platform: " + ", ".join(
                f"{k}={v}" for k, v in sorted(by_ats.items(), key=lambda kv: -kv[1])))
            _log("    by error: " + ", ".join(
                f"{k}={v}" for k, v in sorted(by_kind.items(), key=lambda kv: -kv[1])))
            for ats, name, kind, msg in failures[:8]:
                _log(f"    e.g. {ats}/{name}: {kind}: {msg}")

    # screen everything cheaply, then enrich only what survives
    _log(f"  screening {len(raw)} postings...")
    screened = [screen(r, sponsors) for r in raw]
    kept, rejects = [], {}
    for role in screened:
        why = reject_reason(role, settings)
        if why is None:
            kept.append(role)
        else:
            rejects[why] = rejects.get(why, 0) + 1
    if rejects:
        _log("  rejected:")
        for why, count in sorted(rejects.items(), key=lambda kv: -kv[1]):
            _log(f"      {count:6d}  {why}")
    # where the surviving roles came from, so a source going quiet is visible
    by_source = {}
    for role in kept:
        by_source[role.source] = by_source.get(role.source, 0) + 1
    if by_source:
        _log("  kept by source: " + ", ".join(
            f"{k}={v}" for k, v in sorted(by_source.items(), key=lambda kv: -kv[1])))
    _log(f"  {len(kept)} passed the filters; de-duplicating...")
    kept = dedupe(kept)
    _log(f"  enriching {len(kept)} roles (skills, pay)...")
    for role in kept:
        enrich_kept(role)

    all_roles, new_roles, closed = store.reconcile(
        kept, new_window_hours=settings.new_window_hours)
    store.save()
    _log("  writing outputs...")

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
