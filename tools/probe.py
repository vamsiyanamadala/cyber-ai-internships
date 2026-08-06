"""Probe candidate career-site endpoints and report what each returns.

The Phenom and amazon.jobs adapters returned nothing, which means their endpoint
didn't answer as expected (wrong path, or blocked) rather than that parsing
failed. This script tries several known URL patterns for each and prints the
status, content type, and top-level JSON shape, so the working pattern (if any)
can be identified.

Usage (from the project root, with the venv's python):

    python tools/probe.py
    python tools/probe.py jobs.forvismazars.us        # probe a different host

Nothing here writes files or touches the engine; it only makes read-only GETs.
"""

from __future__ import annotations

import json
import sys

try:
    import httpx
except ImportError:  # pragma: no cover
    print("httpx is not installed. Run: pip install -r requirements.txt")
    raise SystemExit(1)

# A browser-like UA: some career sites reject unknown clients outright, and we
# want to distinguish "path is wrong" from "client is blocked".
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

_HEADERS = {
    "User-Agent": _UA,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}


def phenom_candidates(host: str) -> list[tuple[str, str]]:
    host = host.strip().strip("/").replace("https://", "").replace("http://", "")
    return [
        ("phenom A: /api/jobs (current adapter)",
         f"https://{host}/api/jobs?keyword=intern&page=1&limit=10&sortBy=relevance&format=json"),
        ("phenom B: /api/jobs bare",
         f"https://{host}/api/jobs?keyword=intern&limit=10"),
        ("phenom C: /api/apply/v2/jobs",
         f"https://{host}/api/apply/v2/jobs?domain={host}&start=0&num=10"),
        ("phenom D: /widgets json",
         f"https://{host}/widgets?keyword=intern&limit=10&format=json"),
        ("phenom E: /search-jobs/results",
         f"https://{host}/search-jobs/results?keyword=intern"),
        ("phenom F: plain homepage (is host reachable at all?)",
         f"https://{host}/"),
    ]


AMAZON_CANDIDATES = [
    ("amazon A: search.json (current adapter)",
     "https://www.amazon.jobs/en/search.json?base_query=cybersecurity+intern"
     "&country=USA&result_limit=10&offset=0&sort=recent"),
    ("amazon B: search.json minimal",
     "https://www.amazon.jobs/en/search.json?base_query=intern&result_limit=10"),
    ("amazon C: /search.json without /en",
     "https://www.amazon.jobs/search.json?base_query=intern&result_limit=10"),
]


def describe(label: str, url: str, client: httpx.Client) -> None:
    print("=" * 78)
    print(label)
    print(url)
    try:
        resp = client.get(url)
    except Exception as exc:
        print(f"  RESULT: request failed -> {type(exc).__name__}: {exc}")
        return
    ctype = resp.headers.get("content-type", "?")
    print(f"  status: {resp.status_code}   content-type: {ctype}   bytes: {len(resp.content)}")
    if resp.status_code != 200:
        print(f"  RESULT: not usable (HTTP {resp.status_code})")
        snippet = resp.text[:200].replace("\n", " ")
        if snippet.strip():
            print(f"  body starts: {snippet}")
        return
    # Try JSON
    try:
        data = resp.json()
    except Exception:
        body = resp.text[:300].replace("\n", " ")
        looks_html = "<html" in resp.text[:2000].lower()
        print(f"  RESULT: 200 but NOT JSON ({'HTML page' if looks_html else 'unknown body'})")
        print(f"  body starts: {body}")
        return
    print("  RESULT: 200 with JSON")
    if isinstance(data, dict):
        print(f"  top-level keys: {list(data.keys())[:12]}")
        # look for a list of jobs anywhere shallow
        for path in (("refineSearch", "data", "jobs"), ("data", "jobs"),
                     ("jobs",), ("results",), ("hits",),
                     ("refineSearch", "jobs")):
            node = data
            ok = True
            for key in path:
                if isinstance(node, dict) and key in node:
                    node = node[key]
                else:
                    ok = False
                    break
            if ok and isinstance(node, list):
                print(f"  >>> FOUND job list at {'.'.join(path)}  count={len(node)}")
                if node and isinstance(node[0], dict):
                    print(f"      first item keys: {list(node[0].keys())[:18]}")
                    print("      first item sample: "
                          + json.dumps(node[0], default=str)[:400])
                break
        else:
            print("  no recognizable job list; full shape sample: "
                  + json.dumps(data, default=str)[:400])
    elif isinstance(data, list):
        print(f"  top-level is a list, count={len(data)}")
        if data and isinstance(data[0], dict):
            print(f"  first item keys: {list(data[0].keys())[:18]}")


def main() -> int:
    host = sys.argv[1] if len(sys.argv) > 1 else "jobs.forvismazars.us"
    print(f"Probing Phenom host: {host}")
    with httpx.Client(headers=_HEADERS, timeout=20.0, follow_redirects=True) as client:
        for label, url in phenom_candidates(host):
            describe(label, url, client)
        print()
        print("Probing amazon.jobs")
        for label, url in AMAZON_CANDIDATES:
            describe(label, url, client)
    print("=" * 78)
    print("Done. Paste this whole output back.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
