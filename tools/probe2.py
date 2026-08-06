"""Round-two probe: find embedded job data on a Next.js careers site, and learn
amazon.jobs' query behavior.

Round one told us: Forvis's /api paths 404 but the site is a Next.js app (and two
paths returned a JSON "resource not found" envelope, so a JSON backend exists);
amazon.jobs works but `country=USA` zeroed the results.

So this script:
  1. Fetches the careers page HTML and digs job arrays out of the embedded
     __NEXT_DATA__ blob (Next.js ships initial page data inside the HTML).
  2. Tries the /_next/data/<buildId>/... JSON routes plus more API paths.
  3. Runs an amazon.jobs parameter matrix so we can see which query shapes and
     country filters actually return results.

Usage (from the project root):

    python tools/probe2.py
    python tools/probe2.py jobs.somecompany.com

Read-only GETs; nothing is written and the engine is untouched.
"""

from __future__ import annotations

import json
import re
import sys

try:
    import httpx
except ImportError:  # pragma: no cover
    print("httpx is not installed. Run: pip install -r requirements.txt")
    raise SystemExit(1)

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
_HEADERS = {
    "User-Agent": _UA,
    "Accept": "text/html,application/json,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}

_NEXT_DATA = re.compile(
    r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S | re.I)

# keys that suggest a dict is a job posting
_JOBISH = ("title", "jobtitle", "jobid", "jobseqno", "reqid", "jobdetailurl")


def find_job_arrays(node, path="root", out=None, depth=0):
    """Walk a JSON tree and report arrays whose items look like job postings."""
    if out is None:
        out = []
    if depth > 8:
        return out
    if isinstance(node, list):
        if node and isinstance(node[0], dict):
            keys = {k.lower() for k in node[0].keys()}
            if len(keys & set(_JOBISH)) >= 2 or "title" in keys:
                out.append((path, len(node), list(node[0].keys())[:20], node[0]))
        for i, item in enumerate(node[:3]):
            find_job_arrays(item, f"{path}[{i}]", out, depth + 1)
    elif isinstance(node, dict):
        for key, val in node.items():
            find_job_arrays(val, f"{path}.{key}", out, depth + 1)
    return out


def probe_next_site(host: str, client: httpx.Client) -> None:
    host = host.strip().strip("/").replace("https://", "").replace("http://", "")
    print("=" * 78)
    print(f"NEXT.JS PAGE SCAN: {host}")
    build_id = None
    for page in (f"https://{host}/jobs", f"https://{host}/"):
        print("-" * 78)
        print(f"GET {page}")
        try:
            resp = client.get(page)
        except Exception as exc:
            print(f"  request failed -> {type(exc).__name__}: {exc}")
            continue
        print(f"  status: {resp.status_code}  bytes: {len(resp.content)}")
        if resp.status_code != 200:
            continue
        match = _NEXT_DATA.search(resp.text)
        if not match:
            print("  no __NEXT_DATA__ blob found in this page")
            # maybe another embedded JSON island
            for marker in ("window.__INITIAL_STATE__", "window.phApp",
                           "__APOLLO_STATE__", "application/ld+json"):
                if marker in resp.text:
                    print(f"  NOTE: page contains '{marker}'")
            continue
        try:
            data = json.loads(match.group(1))
        except Exception as exc:
            print(f"  __NEXT_DATA__ found but did not parse: {exc}")
            continue
        build_id = data.get("buildId") or build_id
        print(f"  __NEXT_DATA__ parsed. buildId={build_id!r} "
              f"top keys={list(data.keys())[:10]}")
        hits = find_job_arrays(data)
        if not hits:
            print("  >>> no job-like arrays inside __NEXT_DATA__")
        for path, count, keys, sample in hits[:4]:
            print(f"  >>> JOB ARRAY at {path}  count={count}")
            print(f"      keys: {keys}")
            print("      sample: " + json.dumps(sample, default=str)[:400])
        if hits:
            break

    # Next.js data routes + additional API guesses
    extra = []
    if build_id:
        extra += [
            f"https://{host}/_next/data/{build_id}/jobs.json",
            f"https://{host}/_next/data/{build_id}/en/jobs.json",
        ]
    extra += [
        f"https://{host}/api/jobs/search?keyword=intern&limit=10",
        f"https://{host}/api/search?keyword=intern&limit=10",
        f"https://{host}/api/v1/jobs?keyword=intern&limit=10",
        f"https://{host}/api/careers/jobs?keyword=intern&limit=10",
        f"https://{host}/services/jobs?keyword=intern&limit=10",
        f"https://{host}/jobs.json?keyword=intern",
    ]
    print("-" * 78)
    print("EXTRA PATH GUESSES")
    for url in extra:
        try:
            resp = client.get(url)
        except Exception as exc:
            print(f"  {url}\n    failed -> {type(exc).__name__}")
            continue
        ctype = resp.headers.get("content-type", "?")
        note = ""
        if resp.status_code == 200 and "json" in ctype:
            try:
                hits = find_job_arrays(resp.json())
                if hits:
                    note = f"  >>> JOB ARRAY at {hits[0][0]} count={hits[0][1]}"
                    note += f"\n      keys: {hits[0][2]}"
            except Exception:
                pass
        print(f"  [{resp.status_code}] {ctype[:40]:40s} {url}")
        if note:
            print(note)


AMAZON_MATRIX = [
    ("plain single word", "base_query=intern&result_limit=5"),
    ("two words", "base_query=security+intern&result_limit=5"),
    ("three words", "base_query=cybersecurity+intern+2027&result_limit=5"),
    ("multi-word ML", "base_query=machine+learning+intern&result_limit=5"),
    ("country=USA", "base_query=intern&result_limit=5&country=USA"),
    ("country[]=USA", "base_query=intern&result_limit=5&country%5B%5D=USA"),
    ("loc_query", "base_query=intern&result_limit=5&loc_query=United+States"),
    ("sort=recent", "base_query=intern&result_limit=5&sort=recent"),
    ("new grad phrase", "base_query=new+grad&result_limit=5"),
    ("graduate phrase", "base_query=graduate&result_limit=5"),
]


def probe_amazon(client: httpx.Client) -> None:
    print()
    print("=" * 78)
    print("AMAZON.JOBS PARAMETER MATRIX")
    for label, qs in AMAZON_MATRIX:
        url = f"https://www.amazon.jobs/en/search.json?{qs}"
        try:
            resp = client.get(url)
        except Exception as exc:
            print(f"  {label:20s} failed -> {type(exc).__name__}")
            continue
        if resp.status_code != 200:
            print(f"  {label:20s} HTTP {resp.status_code}")
            continue
        try:
            data = resp.json()
        except Exception:
            print(f"  {label:20s} 200 but not JSON")
            continue
        jobs = data.get("jobs") if isinstance(data, dict) else None
        hits = data.get("hits") if isinstance(data, dict) else None
        count = len(jobs) if isinstance(jobs, list) else "?"
        countries = ""
        if isinstance(jobs, list) and jobs:
            codes = sorted({str(j.get("country_code")) for j in jobs
                            if isinstance(j, dict)})
            titles = [str(j.get("title"))[:34] for j in jobs[:2] if isinstance(j, dict)]
            countries = f"  countries={codes}  e.g. {titles}"
        print(f"  {label:20s} hits={hits}  returned={count}{countries}")


def main() -> int:
    host = sys.argv[1] if len(sys.argv) > 1 else "jobs.forvismazars.us"
    with httpx.Client(headers=_HEADERS, timeout=25.0, follow_redirects=True) as client:
        probe_next_site(host, client)
        probe_amazon(client)
    print("=" * 78)
    print("Done. Paste this whole output back.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
