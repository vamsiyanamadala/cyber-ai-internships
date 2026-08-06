"""CSV and JSON renderers for the role list."""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone

from ..models import Role

_CSV_FIELDS = [
    "company", "title", "category", "role_type", "employment_type",
    "location", "remote",
    "posted_at", "posted_source", "sponsor_history", "sponsor_petitions",
    "no_sponsorship", "citizenship_required", "skills", "pay", "url",
    "first_seen", "uid", "source",
]


def render_csv(roles: list[Role]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_CSV_FIELDS, extrasaction="ignore")
    writer.writeheader()
    for r in roles:
        row = r.to_public_dict()
        row["skills"] = ", ".join(r.skills)
        writer.writerow(row)
    return buf.getvalue()


def render_json(roles: list[Role], stats: dict) -> str:
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stats": {k: (sorted(v) if isinstance(v, set) else v)
                  for k, v in stats.items()},
        "roles": [r.to_public_dict() for r in roles],
    }
    return json.dumps(payload, indent=2, sort_keys=True)
