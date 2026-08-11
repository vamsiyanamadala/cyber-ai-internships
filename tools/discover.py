"""Board discovery: turn company NAMES into VERIFIED job-board tokens.

Coverage is the engine's only real limit — it can only find roles at companies
listed in ``config/companies.yml``. Guessing tokens by hand doesn't scale and
fills the config with dead entries that slow every run. This tool does it
properly:

  1. Read candidate company names (``tools/candidates.txt``, one per line).
  2. Generate the handful of slug spellings a company plausibly uses.
  3. Probe every supported ATS platform for each spelling, concurrently and
     politely.
  4. Keep ONLY boards that returned HTTP 200 *and* at least one real job.
  5. Write the verified result into ``config/companies.yml``, preserving the
     hand-maintained aggregator blocks (adzuna / amazonjobs / phenom).

Nothing unverified ever reaches the config, so growing coverage never degrades
run time or accuracy.

Usage (from the project root):

    python tools/discover.py                     # probe the bundled candidates
    python tools/discover.py --names my.txt      # your own list of names
    python tools/discover.py --limit 200         # try a small batch first
    python tools/discover.py --write             # actually update companies.yml
    python tools/discover.py --concurrency 16    # be gentler / faster

Without ``--write`` it only reports what it found, so you can inspect first.
Results are cached in ``data/discovery_cache.json``, so re-runs skip candidates
already probed and you can stop and resume at will.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys

try:
    import httpx
except ImportError:  # pragma: no cover
    print("httpx is not installed. Run: pip install -r requirements.txt")
    raise SystemExit(1)

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# ---------------------------------------------------------------------------
# Platform probes: (platform key, url builder, job-list extractor)
# Each returns the number of jobs found, or -1 when the board doesn't exist.
# ---------------------------------------------------------------------------


def _jobs_greenhouse(payload):
    return payload.get("jobs") if isinstance(payload, dict) else None


def _jobs_lever(payload):
    return payload if isinstance(payload, list) else None


def _jobs_ashby(payload):
    return payload.get("jobs") if isinstance(payload, dict) else None


def _jobs_smartrecruiters(payload):
    return payload.get("content") if isinstance(payload, dict) else None


def _jobs_workable(payload):
    return payload.get("jobs") if isinstance(payload, dict) else None


def _jobs_recruitee(payload):
    return payload.get("offers") if isinstance(payload, dict) else None


PLATFORMS = [
    ("greenhouse",
     lambda t: f"https://boards-api.greenhouse.io/v1/boards/{t}/jobs",
     _jobs_greenhouse),
    ("lever",
     lambda t: f"https://api.lever.co/v0/postings/{t}?mode=json",
     _jobs_lever),
    ("ashby",
     lambda t: f"https://api.ashbyhq.com/posting-api/job-board/{t}",
     _jobs_ashby),
    ("workable",
     lambda t: f"https://apply.workable.com/api/v1/widget/accounts/{t}",
     _jobs_workable),
    ("smartrecruiters",
     lambda t: f"https://api.smartrecruiters.com/v1/companies/{t}/postings?limit=10",
     _jobs_smartrecruiters),
    ("recruitee",
     lambda t: f"https://{t}.recruitee.com/api/offers/",
     _jobs_recruitee),
]

_PUNCT = re.compile(r"[^a-z0-9]+")
_STOP_SUFFIX = ("inc", "llc", "ltd", "limited", "corp", "corporation", "co",
                "company", "plc", "gmbh", "holdings", "group", "technologies",
                "technology", "labs", "lab", "software", "systems")


def slug_variants(name: str, max_variants: int = 4) -> list[str]:
    """The few spellings a company realistically uses as a board token."""
    base = _PUNCT.sub(" ", name.strip().lower()).strip()
    if not base:
        return []
    words = base.split()
    out: list[str] = []

    def add(candidate: str) -> None:
        candidate = candidate.strip("-")
        if candidate and candidate not in out and 2 <= len(candidate) <= 40:
            out.append(candidate)

    add("".join(words))                       # thetradedesk
    add("-".join(words))                      # the-trade-desk
    if words and words[0] == "the":           # tradedesk
        add("".join(words[1:]))
        add("-".join(words[1:]))
    trimmed = [w for w in words if w not in _STOP_SUFFIX]
    if trimmed and trimmed != words:
        add("".join(trimmed))
        add("-".join(trimmed))
    if len(words) > 1:
        add(words[0])                         # single distinctive first word
    return out[:max_variants]


class Discoverer:
    def __init__(self, concurrency: int, delay_ms: int, timeout: float):
        self.sem = asyncio.Semaphore(concurrency)
        self.delay = delay_ms / 1000.0
        self.timeout = timeout
        self.requests = 0

    async def probe(self, client, platform, url_for, extract, token):
        """Return job count for a token on one platform, or -1 if not a board."""
        url = url_for(token)
        async with self.sem:
            self.requests += 1
            try:
                resp = await client.get(url)
            except Exception:
                return -1
            if self.delay:
                await asyncio.sleep(self.delay)
        if resp.status_code != 200:
            return -1
        try:
            payload = resp.json()
        except Exception:
            return -1
        jobs = extract(payload)
        if not isinstance(jobs, list):
            return -1
        return len(jobs)

    async def find(self, client, name: str):
        """First platform+token pair that returns a live board with jobs."""
        for token in slug_variants(name):
            for platform, url_for, extract in PLATFORMS:
                count = await self.probe(client, platform, url_for, extract, token)
                if count > 0:
                    return {"name": name, "ats": platform, "token": token,
                            "jobs": count}
        return None


def load_names(path: str, limit: int | None) -> list[str]:
    names: list[str] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#"):
                names.append(line)
    seen, out = set(), []
    for n in names:
        key = n.lower()
        if key not in seen:
            seen.add(key)
            out.append(n)
    return out[:limit] if limit else out


def load_cache(path: str) -> dict:
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            return {}
    return {}


def save_cache(path: str, cache: dict) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(cache, fh, indent=1, sort_keys=True)
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Writing companies.yml
# ---------------------------------------------------------------------------
_KEEP_BLOCKS = ("adzuna", "amazonjobs", "phenom", "workday")


def read_existing_blocks(path: str) -> str:
    """Return the hand-maintained aggregator blocks verbatim, so a discovery run
    never clobbers the Adzuna queries, the Amazon terms, or the Phenom hosts."""
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    kept, capture = [], False
    for line in lines:
        stripped = line.strip()
        m = re.match(r"^([a-z_]+):", stripped)
        if m and line.startswith("  "):
            capture = m.group(1) in _KEEP_BLOCKS
        if capture:
            kept.append(line)
        elif kept and stripped and not line.startswith("  "):
            capture = False
    return "\n".join(kept)


def write_companies(path: str, found: list[dict]) -> tuple[int, str]:
    by_ats: dict[str, list[dict]] = {}
    for hit in found:
        by_ats.setdefault(hit["ats"], []).append(hit)
    lines = [
        "# ===========================================================================",
        "# COMPANY LIST — generated by tools/discover.py",
        "# ===========================================================================",
        "# Every entry below was VERIFIED at generation time: the board answered and",
        "# returned at least one live job. Re-run discovery to refresh or extend it:",
        "#     python tools/discover.py --write",
        "# Aggregator blocks (adzuna / amazonjobs / phenom / workday) are preserved",
        "# from the previous file and edited by hand.",
        "# ===========================================================================",
        "",
        "companies:",
    ]
    for ats in sorted(by_ats):
        hits = sorted(by_ats[ats], key=lambda h: h["name"].lower())
        lines.append(f"\n  # {len(hits)} verified {ats} boards")
        lines.append(f"  {ats}:")
        for hit in hits:
            safe = hit["name"].replace('"', "'")
            lines.append(f'    - name: "{safe}"')
            lines.append(f'      token: "{hit["token"]}"')
    preserved = read_existing_blocks(path)
    if preserved:
        lines.append("")
        lines.append("  # ---- hand-maintained aggregator sources (preserved) ----")
        lines.append(preserved)
    text = "\n".join(lines) + "\n"
    return len(found), text


async def main_async(args) -> int:
    names = load_names(args.names, args.limit)
    cache = load_cache(args.cache)
    todo = [n for n in names if n.lower() not in cache]
    print(f"candidates: {len(names)}  already probed: {len(names) - len(todo)}  "
          f"to probe now: {len(todo)}")
    if todo:
        est = len(todo) * len(PLATFORMS) * 2
        print(f"up to ~{est} requests; concurrency {args.concurrency}. "
              f"Ctrl+C is safe — progress is cached.")
    disc = Discoverer(args.concurrency, args.delay_ms, args.timeout)
    limits = httpx.Limits(max_connections=args.concurrency + 8)
    done = 0
    try:
        async with httpx.AsyncClient(
                headers={"User-Agent": _UA, "Accept": "application/json"},
                timeout=args.timeout, limits=limits,
                follow_redirects=True) as client:
            batch = 24
            for i in range(0, len(todo), batch):
                chunk = todo[i:i + batch]
                results = await asyncio.gather(
                    *(disc.find(client, n) for n in chunk),
                    return_exceptions=True)
                for name, res in zip(chunk, results):
                    if isinstance(res, Exception):
                        continue
                    cache[name.lower()] = res or {}
                    if res:
                        print(f"  FOUND  {res['ats']:16s} {res['token']:28s} "
                              f"{res['jobs']:>4d} jobs   {name}")
                done += len(chunk)
                save_cache(args.cache, cache)
                print(f"  ...{done}/{len(todo)} probed "
                      f"({disc.requests} requests so far)")
    except KeyboardInterrupt:
        print("\ninterrupted — progress saved, re-run to continue")
    save_cache(args.cache, cache)

    found = [v for v in cache.values() if v]
    print()
    print(f"VERIFIED BOARDS: {len(found)} of {len(cache)} candidates probed")
    per = {}
    for hit in found:
        per[hit["ats"]] = per.get(hit["ats"], 0) + 1
    for ats in sorted(per):
        print(f"  {ats:16s} {per[ats]}")

    count, text = write_companies(args.out, found)
    if args.write:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"\nwrote {count} verified boards to {args.out}")
        print("Run `python run.py` next — errors should now be near zero.")
    else:
        preview = "\n".join(text.splitlines()[:24])
        print("\n--- preview (not written; pass --write to save) ---")
        print(preview)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Discover and verify ATS job boards")
    here = os.path.dirname(os.path.abspath(__file__))
    ap.add_argument("--names", default=os.path.join(here, "candidates.txt"))
    ap.add_argument("--out", default=os.path.join(os.path.dirname(here),
                                                  "config", "companies.yml"))
    ap.add_argument("--cache", default=os.path.join(os.path.dirname(here),
                                                    "data", "discovery_cache.json"))
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--concurrency", type=int, default=12)
    ap.add_argument("--delay-ms", type=int, default=120)
    ap.add_argument("--timeout", type=float, default=12.0)
    ap.add_argument("--write", action="store_true",
                    help="write the verified list into config/companies.yml")
    args = ap.parse_args()
    if not os.path.exists(args.names):
        print(f"candidate file not found: {args.names}")
        return 1
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
