"""Adapter contract and shared helpers.

Each adapter knows how to talk to one ATS platform's public feed and turn the
response into partially-filled ``Role`` objects (identity + raw description +
any real posting date the source exposes). Classification, visa detection, and
sponsorship lookup all happen later in the pipeline.
"""

from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from typing import Any

from ..models import Role

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def html_to_text(raw: str) -> str:
    if not raw:
        return ""
    text = _TAG.sub(" ", raw)
    text = html.unescape(text)
    return _WS.sub(" ", text).strip()


def iso_from_epoch_ms(ms: Any) -> str | None:
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def iso_from_string(value: Any) -> str | None:
    if not value or not isinstance(value, str):
        return None
    value = value.strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            dt = datetime.strptime(value, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    # trailing 'Z' or fractional seconds
    try:
        cleaned = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned)
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        return None


class Adapter:
    name = "base"

    async def fetch(self, fetcher, company) -> list[Role]:  # pragma: no cover - interface
        raise NotImplementedError
