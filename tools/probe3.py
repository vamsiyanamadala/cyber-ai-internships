"""Round-three probe: find the XHR endpoint a careers page uses to load jobs.

Round two showed Forvis's __NEXT_DATA__ carries no job list, which means the jobs
arrive via a client-side request after the page loads. Two ways to find that
request, and this script does both automatically:

  1. Print the real structure of the /_next/data/<buildId>/jobs.json payload that
     returned 200, in case the job list is nested under an unexpected key.
  2. Download the page's own JavaScript bundles and grep them for API paths and
     hostnames (that's where the front-end's fetch URL is written down).

FASTER MANUAL ALTERNATIVE (30 seconds, and definitive): open the careers page in
Chrome, press F12, click the Network tab, tick "Fetch/XHR", reload the page, and
look for the request that returns the job list. Right-click it -> Copy -> Copy
link address, and paste that URL back. That gives the exact endpoint with no
guessing at all.

Usage:  python tools/probe3.py [host]
Read-only GETs; nothing is written.
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
_HEADERS = {"User-Agent": _UA, "Accept": "text/html,application/json,*/*"}

_NEXT_DATA = re.compile(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S | re.I)
_SCRIPTS = re.compile(r'<script[^>]+src="([^"]+)"', re.I)

# API-ish strings inside bundles
_PATHS = re.compile(r'["\'`](/(?:api|services|widgets|search|ph[A-Za-z]*)/[A-Za-z0-9\-_/\.]{2,60})["\'`]')
_HOSTS = re.compile(r'https://([a-z0-9\-\.]*(?:phenom|phenompeople|jibe|smashfly|avature|icims|eightfold)[a-z0-9\-\.]*)', re.I)
_FULL = re.compile(r'https://[a-z0-9\-\.]+/(?:api|services|widgets)/[A-Za-z0-9\-_/\.]{2,60}', re.I)


def shape(node, depth=0, max_depth=3):
    """Compact structural summary of a JSON payload."""
    pad = "  " * (depth + 1)
    if depth > max_depth:
        return f"{type(node).__name__}"
    if isinstance(node, dict):
        if not node:
            return "{}"
        lines = []
        for key, val in list(node.items())[:14]:
            lines.append(f"{pad}{key}: {shape(val, depth + 1, max_depth)}")
        return "{\n" + "\n".join(lines) + f"\n{'  ' * depth}}}"
    if isinstance(node, list):
        inner = shape(node[0], depth + 1, max_depth) if node else "empty"
        return f"[{len(node)} items] first={inner}"
    text = str(node)
    return f"{type(node).__name__}({text[:40]})" if text else type(node).__name__


def main() -> int:
    host = (sys.argv[1] if len(sys.argv) > 1 else "jobs.forvismazars.us")
    host = host.strip().strip("/").replace("https://", "").replace("http://", "")
    page_url = f"https://{host}/jobs"

    with httpx.Client(headers=_HEADERS, timeout=25.0, follow_redirects=True) as client:
        print("=" * 78)
        print(f"PAGE: {page_url}")
        try:
            page = client.get(page_url)
        except Exception as exc:
            print(f"  failed -> {type(exc).__name__}: {exc}")
            return 1
        print(f"  status {page.status_code}  bytes {len(page.content)}")
        if page.status_code != 200:
            return 1

        build_id = None
        m = _NEXT_DATA.search(page.text)
        if m:
            try:
                build_id = json.loads(m.group(1)).get("buildId")
            except Exception:
                pass
        print(f"  buildId: {build_id!r}")

        # 1. structure of the _next/data payload
        if build_id:
            url = f"https://{host}/_next/data/{build_id}/jobs.json"
            print("-" * 78)
            print(f"STRUCTURE OF {url}")
            try:
                resp = client.get(url)
                print(f"  status {resp.status_code}  bytes {len(resp.content)}")
                if resp.status_code == 200:
                    print(shape(resp.json()))
            except Exception as exc:
                print(f"  failed -> {type(exc).__name__}: {exc}")

        # 2. grep the JS bundles
        print("-" * 78)
        srcs = _SCRIPTS.findall(page.text)
        print(f"SCRIPT TAGS FOUND: {len(srcs)} (scanning up to 14)")
        paths: set[str] = set()
        hosts: set[str] = set()
        fulls: set[str] = set()
        for src in srcs[:14]:
            url = src if src.startswith("http") else f"https://{host}/{src.lstrip('/')}"
            try:
                js = client.get(url)
            except Exception:
                continue
            if js.status_code != 200:
                continue
            body = js.text
            paths.update(p for p in _PATHS.findall(body))
            hosts.update(h.lower() for h in _HOSTS.findall(body))
            fulls.update(f for f in _FULL.findall(body))
        print("-" * 78)
        print("CANDIDATE API PATHS FOUND IN BUNDLES:")
        for p in sorted(paths)[:40]:
            print(f"  {p}")
        if not paths:
            print("  (none)")
        print("CANDIDATE FULL URLS:")
        for f in sorted(fulls)[:20]:
            print(f"  {f}")
        if not fulls:
            print("  (none)")
        print("ATS-RELATED HOSTNAMES:")
        for h in sorted(hosts)[:20]:
            print(f"  {h}")
        if not hosts:
            print("  (none)")

        # 3. try the discovered paths
        if paths:
            print("-" * 78)
            print("TRYING DISCOVERED PATHS")
            for p in sorted(paths)[:12]:
                url = f"https://{host}{p}"
                if "?" not in url:
                    url += "?keyword=intern&limit=10"
                try:
                    resp = client.get(url)
                except Exception:
                    continue
                ctype = resp.headers.get("content-type", "?")[:32]
                flag = ""
                if resp.status_code == 200 and "json" in ctype:
                    try:
                        data = resp.json()
                        blob = json.dumps(data)[:120]
                        flag = f"  <== JSON OK: {blob}"
                    except Exception:
                        pass
                print(f"  [{resp.status_code}] {ctype:32s} {url}{flag}")

    print("=" * 78)
    print("Done. Paste this whole output back.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
