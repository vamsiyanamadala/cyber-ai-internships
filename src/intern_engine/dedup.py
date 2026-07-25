"""Collapse duplicate roles that appear across multiple sources.

Two postings are considered the same role when their ``uid`` (company + title +
first location token) matches. When duplicates are found we keep the "best"
copy: prefer one with a real source-provided posting date and a longer
description, so downstream date handling stays accurate.
"""

from __future__ import annotations

from .models import Role


def _quality(role: Role) -> tuple[int, int]:
    has_real_date = 1 if role.posted_source == "source" and role.posted_at else 0
    return (has_real_date, len(role.description or ""))


def dedupe(roles: list[Role]) -> list[Role]:
    best: dict[str, Role] = {}
    for role in roles:
        if not role.uid:
            role.compute_uid()
        existing = best.get(role.uid)
        if existing is None or _quality(role) > _quality(existing):
            # carry forward richer metadata from the copy we're discarding
            if existing is not None:
                role.skills = sorted(set(role.skills) | set(existing.skills))
            best[role.uid] = role
    return list(best.values())
