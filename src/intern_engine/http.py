"""Async fetch layer: polite, resilient, cache-aware.

Features: global concurrency cap, per-host minimum delay, exponential backoff
with jitter, ETag / Last-Modified conditional requests (304 -> reuse), and a
per-host circuit breaker that trips after repeated failures.

``httpx`` is imported lazily inside :meth:`Fetcher.__aenter__` so the rest of the
package (classifier, sponsor index, renderers, tests) imports with no third-party
dependency at all.
"""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import urlsplit


@dataclass
class HostState:
    last_request: float = 0.0
    consecutive_failures: int = 0
    open_until: float = 0.0


@dataclass
class FetchResult:
    url: str
    status: int
    text: str = ""
    json: Any = None
    not_modified: bool = False
    etag: Optional[str] = None
    last_modified: Optional[str] = None
    error: Optional[str] = None


class Fetcher:
    def __init__(self, settings, cache: dict | None = None):
        self.s = settings
        self.cache = cache if cache is not None else {}
        self._sem = asyncio.Semaphore(settings.concurrency)
        self._hosts: dict[str, HostState] = {}
        self._host_locks: dict[str, asyncio.Lock] = {}
        self._client = None

    async def __aenter__(self):
        import httpx  # lazy: only needed when actually polling
        self._client = httpx.AsyncClient(
            headers={"User-Agent": self.s.user_agent, "Accept": "application/json"},
            timeout=self.s.timeout_s,
            follow_redirects=True,
        )
        return self

    async def __aexit__(self, *exc):
        if self._client is not None:
            await self._client.aclose()

    def _host(self, url: str) -> str:
        return urlsplit(url).netloc

    def _host_lock(self, host: str) -> asyncio.Lock:
        if host not in self._host_locks:
            self._host_locks[host] = asyncio.Lock()
        return self._host_locks[host]

    async def _respect_rate(self, host: str) -> None:
        state = self._hosts.setdefault(host, HostState())
        async with self._host_lock(host):
            gap = self.s.per_host_delay_ms / 1000.0
            wait = state.last_request + gap - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            state.last_request = time.monotonic()

    def _circuit_open(self, host: str) -> bool:
        state = self._hosts.setdefault(host, HostState())
        return time.monotonic() < state.open_until

    def _record(self, host: str, ok: bool) -> None:
        state = self._hosts.setdefault(host, HostState())
        if ok:
            state.consecutive_failures = 0
        else:
            state.consecutive_failures += 1
            if state.consecutive_failures >= self.s.circuit_fail_threshold:
                state.open_until = time.monotonic() + self.s.circuit_cooldown_s
                state.consecutive_failures = 0

    async def get(self, url: str, method: str = "GET", json_body: Any = None,
                  conditional: bool = False) -> FetchResult:
        host = self._host(url)
        if self._circuit_open(host):
            return FetchResult(url=url, status=0, error="circuit_open")

        headers = {}
        if conditional:
            cached = self.cache.get(url, {})
            if cached.get("etag"):
                headers["If-None-Match"] = cached["etag"]
            if cached.get("last_modified"):
                headers["If-Modified-Since"] = cached["last_modified"]

        backoff = 0.5
        last_err = None
        for attempt in range(self.s.max_retries + 1):
            await self._respect_rate(host)
            async with self._sem:
                try:
                    resp = await self._client.request(
                        method, url, headers=headers or None, json=json_body)
                except Exception as exc:  # network/timeout/dns
                    last_err = f"{type(exc).__name__}: {exc}"
                    self._record(host, ok=False)
                else:
                    if resp.status_code == 304:
                        self._record(host, ok=True)
                        return FetchResult(url=url, status=304, not_modified=True)
                    if resp.status_code == 429 or 500 <= resp.status_code < 600:
                        last_err = f"HTTP {resp.status_code}"
                        self._record(host, ok=False)
                    else:
                        self._record(host, ok=True)
                        etag = resp.headers.get("ETag")
                        lastmod = resp.headers.get("Last-Modified")
                        result = FetchResult(
                            url=url, status=resp.status_code,
                            etag=etag, last_modified=lastmod)
                        if resp.status_code == 200:
                            result.text = resp.text
                            try:
                                result.json = resp.json()
                            except Exception:
                                result.json = None
                            if etag or lastmod:
                                self.cache[url] = {
                                    k: v for k, v in
                                    (("etag", etag), ("last_modified", lastmod)) if v
                                }
                        return result
            # retry with jittered backoff
            await asyncio.sleep(backoff + random.uniform(0, backoff))
            backoff *= 2
        return FetchResult(url=url, status=0, error=last_err or "unknown")
