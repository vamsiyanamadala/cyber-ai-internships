"""Hand-rolled RSS 2.0 feed (no dependencies) for newly-seen roles."""

from __future__ import annotations

from datetime import datetime, timezone
from xml.sax.saxutils import escape

from ..models import Role


def _rfc822(iso: str | None) -> str:
    dt = None
    if iso:
        try:
            dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        except ValueError:
            try:
                dt = datetime.strptime(iso[:10], "%Y-%m-%d")
            except ValueError:
                dt = None
    dt = (dt or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return dt.strftime("%a, %d %b %Y %H:%M:%S +0000")


def render_rss(roles: list[Role], site_url: str, title: str, new_uids: set) -> str:
    items = []
    feed_roles = [r for r in roles if r.uid in new_uids] or roles[:50]
    for r in feed_roles[:100]:
        desc = f"{r.company} · {r.category} · {r.role_type} · {r.location}"
        if r.pay:
            desc += f" · {r.pay}"
        items.append(
            "<item>"
            f"<title>{escape(r.company)}: {escape(r.title)}</title>"
            f"<link>{escape(r.url)}</link>"
            f"<guid isPermaLink=\"false\">{escape(r.uid)}</guid>"
            f"<pubDate>{_rfc822(r.first_seen or r.posted_at)}</pubDate>"
            f"<description>{escape(desc)}</description>"
            "</item>")
    now = _rfc822(datetime.now(timezone.utc).isoformat())
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0"><channel>'
        f"<title>{escape(title)}</title>"
        f"<link>{escape(site_url)}</link>"
        f"<description>{escape(title)}</description>"
        f"<lastBuildDate>{now}</lastBuildDate>"
        + "".join(items) +
        "</channel></rss>\n")
