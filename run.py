#!/usr/bin/env python3
"""Command-line entry point for the internship engine.

Usage:
    python run.py                 # one full cycle (poll + render)
    python run.py --config-dir config
    python run.py --self-test     # run offline logic on bundled fixtures
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from intern_engine.config import load_settings, load_companies  # noqa: E402
from intern_engine.pipeline import run  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Cybersecurity + AI internship engine")
    ap.add_argument("--config-dir", default="config")
    ap.add_argument("--self-test", action="store_true",
                    help="run the offline fixture pipeline and exit")
    args = ap.parse_args()

    settings = load_settings(os.path.join(args.config_dir, "settings.yml"))

    if args.self_test:
        from tools.fixtures import FIXTURE_ROLES
        stats = run(settings, [], offline_roles=list(FIXTURE_ROLES))
        print("self-test stats:", {k: v for k, v in stats.items() if k != "new_uids"})
        return 0

    companies = load_companies(os.path.join(args.config_dir, "companies.yml"))
    stats = run(settings, companies)
    print("run complete:",
          {k: (len(v) if isinstance(v, (set, list)) else v)
           for k, v in stats.items() if k != "new_uids"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
