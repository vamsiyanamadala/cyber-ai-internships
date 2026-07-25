"""Render the live list as README.md."""

from __future__ import annotations

from datetime import datetime, timezone

from ..models import Role, Category


def _fmt_date(role: Role) -> str:
    if not role.posted_at:
        return "—"
    d = role.posted_at
    return d + (" ~" if role.posted_source != "source" else "")


def _company_cell(role: Role) -> str:
    name = role.company
    if role.sponsor_history:
        name += " ✓"
    return name


def _flags(role: Role) -> str:
    out = []
    if role.citizenship_required:
        out.append("🇺🇸")
    if role.no_sponsorship:
        out.append("🛂")
    if getattr(role, "_is_new", False):
        out.append("🆕")
    return " ".join(out)


def _row(role: Role) -> str:
    title = role.title.replace("|", "\\|")
    flags = _flags(role)
    title_cell = f"{title}{(' ' + flags) if flags else ''}"
    loc = (role.location or "—").replace("|", "\\|")
    pay = f" · {role.pay}" if role.pay else ""
    return (f"| {_company_cell(role)} | {title_cell} | {role.role_type or ''} | "
            f"{loc}{pay} | {_fmt_date(role)} | [Apply]({role.url}) |")


def _table(roles: list[Role]) -> str:
    header = ("| Company | Role | Type | Location | Posted | Apply |\n"
              "|---|---|---|---|---|---|")
    lines = [header] + [_row(r) for r in roles]
    return "\n".join(lines)


def render_readme(roles: list[Role], stats: dict, closed: list[dict],
                  settings) -> str:
    now = datetime.now(timezone.utc).strftime("%b %d, %Y at %H:%M UTC")
    new_ids = stats.get("new_uids", set())
    for r in roles:
        r._is_new = r.uid in new_ids

    by_cat: dict[str, list[Role]] = {c: [] for c in settings.categories}
    for r in roles:
        by_cat.setdefault(r.category, []).append(r)

    def sort_key(r: Role):
        # newest first: real dates before estimated, then date desc, then name
        return (0 if r.posted_source == "source" else 1,
                r.posted_at or "", r.company)

    parts: list[str] = []
    parts.append("# Cybersecurity & AI Internships, Co-ops & Apprenticeships (US)\n")
    parts.append(
        f"A self-updating engine that tracks **{stats['open']} open** early-career "
        f"Cybersecurity and AI/ML roles in the United States and rebuilds this "
        f"page automatically. **{stats['new']} new** in the last "
        f"{settings.new_window_hours}h · **{stats['companies']} companies polled** "
        f"· updated {now}.\n")
    parts.append(
        "Sponsorship policy: **" + settings.sponsorship_mode + "** "
        f"(min petitions = {settings.min_petitions}). "
        "Roles that state they won't sponsor are excluded"
        + (", and citizenship/clearance-only roles are excluded"
           if settings.exclude_citizenship_required else "")
        + ".\n")
    parts.append(
        "> Legend: **✓** = employer has an H-1B track record in USCIS data · "
        "**🆕** = seen in the last 48h · dates marked **~** are estimated from "
        "when the engine first saw the role (the source didn't publish one). "
        "Sponsorship signals are detected from posting text and USCIS history — "
        "strong hints, not guarantees. Always confirm on the source posting.\n")

    order = [Category.CYBER.value, Category.AI.value]
    order += [c for c in settings.categories if c not in order]
    for cat in order:
        group = by_cat.get(cat) or []
        if not group:
            continue
        group.sort(key=sort_key, reverse=True)
        parts.append(f"\n## {cat} ({len(group)} open)\n")
        parts.append(_table(group))

    if closed:
        parts.append(f"\n## Recently closed — {len(closed)} in the last 14 days\n")
        cl = "\n".join(
            f"- {c.get('company','')} — {c.get('title','')}" for c in closed[:40])
        parts.append(cl)

    parts.append("\n## How this stays current\n")
    parts.append(
        "A small async Python engine reads public ATS feeds "
        f"({', '.join(sorted(stats.get('sources', [])))}) directly, keeps only "
        "US cybersecurity/AI internships, co-ops, and apprenticeships, applies "
        "the sponsorship filter, de-duplicates across sources, records each "
        "role's first-seen date once so ordering never shifts, and regenerates "
        "this page. Full source and setup are in the repo.\n")
    parts.append(
        f"Engine (last run): {stats['companies']} companies · "
        f"{stats.get('fetched_ok', 0)} feeds fetched · {stats['open']} open roles "
        f"· {stats.get('duration_s', 0):.1f}s.\n")
    parts.append(
        "\n_Data files: [`data/internships.csv`](data/internships.csv) · "
        "[`data/internships.json`](data/internships.json) · "
        "[RSS](docs/feed.xml). Roles can close anytime — confirm before applying._\n")
    parts.append(
        "_Run it yourself / add companies: see [SETUP.md](SETUP.md). "
        "How it's built: [ARCHITECTURE.md](ARCHITECTURE.md)._\n")
    return "\n".join(parts)
