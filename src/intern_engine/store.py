"""Persistent state so posting dates never shift and closures are tracked.

The store is a single JSON file. For every role we remember the first time the
engine ever saw it; that timestamp anchors the "Posted" date whenever the source
doesn't expose a real one, and it never changes on later runs. Roles that
disappear from all feeds move to a rolling "recently closed" list.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone, timedelta

from .models import Role

_ISO = "%Y-%m-%dT%H:%M:%S%z"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


class StateStore:
    def __init__(self, path: str):
        self.path = path
        self.data = {"roles": {}, "closed": [], "http_cache": {}}
        self._load()

    def _load(self) -> None:
        if os.path.exists(self.path):
            try:
                with open(self.path, encoding="utf-8") as fh:
                    self.data = json.load(fh)
            except (json.JSONDecodeError, OSError):
                pass
        self.data.setdefault("roles", {})
        self.data.setdefault("closed", [])
        self.data.setdefault("http_cache", {})

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.data, fh, indent=2, sort_keys=True)
        os.replace(tmp, self.path)

    # ---- HTTP conditional-request cache --------------------------------
    def cache_get(self, url: str) -> dict:
        return self.data["http_cache"].get(url, {})

    def cache_put(self, url: str, etag: str | None, last_modified: str | None) -> None:
        entry = {}
        if etag:
            entry["etag"] = etag
        if last_modified:
            entry["last_modified"] = last_modified
        if entry:
            self.data["http_cache"][url] = entry

    # ---- role bookkeeping ----------------------------------------------
    def reconcile(self, roles: list[Role], new_window_hours: int = 48
                  ) -> tuple[list[Role], list[Role], list[dict]]:
        """Stamp stable dates, flag new roles, and record closures.

        Returns ``(all_roles, new_roles, recently_closed)``.
        """
        now = _now()
        now_iso = _iso(now)
        seen_now: set[str] = set()
        new_roles: list[Role] = []

        for role in roles:
            if not role.uid:
                role.compute_uid()
            seen_now.add(role.uid)
            record = self.data["roles"].get(role.uid)

            if record is None:
                # brand new to the engine
                role.first_seen = now_iso
                role.last_seen = now_iso
                if not (role.posted_source == "source" and role.posted_at):
                    role.posted_at = now_iso[:10]
                    role.posted_source = "first_seen"
                new_roles.append(role)
            else:
                role.first_seen = record.get("first_seen", now_iso)
                role.last_seen = now_iso
                # keep whatever posting date we locked in the first time
                if record.get("posted_source") == "source" and record.get("posted_at"):
                    role.posted_at = record["posted_at"]
                    role.posted_source = "source"
                elif not (role.posted_source == "source" and role.posted_at):
                    role.posted_at = record.get("posted_at") or role.first_seen[:10]
                    role.posted_source = "first_seen"
                # newness is based on first_seen, not this run
                fs = _parse(role.first_seen)
                if fs and now - fs <= timedelta(hours=new_window_hours):
                    new_roles.append(role)

            self.data["roles"][role.uid] = {
                "company": role.company,
                "title": role.title,
                "url": role.url,
                "first_seen": role.first_seen,
                "last_seen": role.last_seen,
                "posted_at": role.posted_at,
                "posted_source": role.posted_source,
            }

        # anything we tracked but didn't see this run has closed
        recently_closed: list[dict] = []
        for uid, rec in list(self.data["roles"].items()):
            if uid in seen_now:
                continue
            closed_entry = {
                "company": rec.get("company", ""),
                "title": rec.get("title", ""),
                "url": rec.get("url", ""),
                "removed_at": now_iso,
                "posted_at": rec.get("posted_at"),
            }
            self.data["closed"].append(closed_entry)
            del self.data["roles"][uid]

        # keep closed list to the last 30 days
        cutoff = now - timedelta(days=30)
        self.data["closed"] = [
            c for c in self.data["closed"]
            if (_parse(c.get("removed_at", "")) or now) >= cutoff
        ]
        recently_closed = [
            c for c in self.data["closed"]
            if (_parse(c.get("removed_at", "")) or now) >= now - timedelta(days=14)
        ]
        return roles, new_roles, recently_closed


def _parse(value: str):
    if not value:
        return None
    try:
        dt = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S%z")
        return dt.astimezone(timezone.utc)
    except ValueError:
        try:
            return datetime.strptime(value[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
