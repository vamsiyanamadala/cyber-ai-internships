"""Load engine settings and the company list from YAML."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import yaml

from .models import Category, RoleType


@dataclass
class CompanyRef:
    name: str
    ats: str
    token: str
    extra: dict = field(default_factory=dict)  # e.g. Workday host/tenant/site


@dataclass
class Settings:
    # filtering
    categories: list[str] = field(default_factory=lambda: [Category.CYBER.value, Category.AI.value])
    role_types: list[str] = field(default_factory=lambda: [
        RoleType.INTERN.value, RoleType.COOP.value, RoleType.APPRENTICE.value])
    us_only: bool = True
    # sponsorship: "require_history" | "exclude_negative" | "flag_only"
    sponsorship_mode: str = "require_history"
    min_petitions: int = 1
    exclude_citizenship_required: bool = True
    # freshness
    new_window_hours: int = 48
    # http
    concurrency: int = 24
    per_host_delay_ms: int = 400
    timeout_s: float = 20.0
    max_retries: int = 3
    circuit_fail_threshold: int = 5
    circuit_cooldown_s: int = 900
    user_agent: str = "intern-engine/1.0 (+https://github.com/your/repo)"
    # paths (relative to repo root)
    h1b_dir: str = "data/h1b"
    h1b_sample: str = "data/h1b_employers.sample.csv"
    state_path: str = "data/state.json"
    out_readme: str = "README.md"
    out_csv: str = "data/internships.csv"
    out_json: str = "data/internships.json"
    out_rss: str = "docs/feed.xml"
    out_html: str = "docs/index.html"
    site_url: str = "https://github.com/your/repo"


def load_settings(path: str) -> Settings:
    raw = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
    known = {f for f in Settings.__dataclass_fields__}
    kwargs = {k: v for k, v in raw.items() if k in known}
    return Settings(**kwargs)


def load_companies(path: str) -> list[CompanyRef]:
    with open(path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    companies: list[CompanyRef] = []
    for ats, entries in (raw.get("companies") or {}).items():
        for entry in entries or []:
            if isinstance(entry, str):
                companies.append(CompanyRef(name=entry, ats=ats, token=entry))
            elif isinstance(entry, dict):
                token = entry.get("token") or entry.get("slug") or entry.get("name")
                extra = {k: v for k, v in entry.items() if k not in ("name", "token", "slug")}
                companies.append(CompanyRef(
                    name=entry.get("name", token), ats=ats, token=token, extra=extra))
    return companies
