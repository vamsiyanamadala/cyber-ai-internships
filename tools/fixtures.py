"""Synthetic postings used for offline testing (no network required)."""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from intern_engine.models import Role  # noqa: E402


def _r(company, title, desc, location, source="greenhouse", country=""):
    return Role(company=company, title=title, description=desc, location=location,
                url=f"https://example.com/{company}/{abs(hash(title)) % 9999}",
                source=source, board_token=company.lower(), country_hint=country)


FIXTURE_ROLES = [
    # --- should be KEPT ---
    _r("CrowdStrike", "Security Engineer Intern",
       "Join our SOC to work on threat detection, SIEM tuning, and incident "
       "response. Python and Splunk experience a plus. $40/hour.",
       "Austin, TX"),
    _r("Anthropic", "Machine Learning Research Co-op",
       "Work with our team on large language model evaluation and NLP research "
       "using PyTorch. Deep learning background preferred.",
       "San Francisco, CA", source="ashby"),
    _r("Palantir Technologies", "Cybersecurity Apprenticeship",
       "A 12-month apprenticeship in offensive security and vulnerability "
       "research. Learn red team tooling and exploit development.",
       "New York, NY", source="lever"),

    # --- should be DROPPED for the reasons noted ---
    _r("NoSponsorCo", "AI Engineer Intern",
       "Applied machine learning role. We are unable to provide visa "
       "sponsorship for this position now or in the future.",
       "Seattle, WA"),  # explicit no-sponsorship
    _r("DefenseWorks", "Security Analyst Intern",
       "Support our SOC. Must be a US citizen and able to obtain a security "
       "clearance (TS/SCI).",
       "Arlington, VA"),  # citizenship/clearance
    _r("GlobalAI", "Deep Learning Intern",
       "Computer vision internship using PyTorch and CUDA.",
       "Toronto, Canada", country="Canada"),  # non-US
    _r("MegaBank", "Marketing Intern",
       "Support the social media and email marketing team. No security or ML "
       "work involved.",
       "Chicago, IL"),  # wrong domain
    _r("BigCo", "Software Engineer, Backend",
       "Build backend services in Go. Full-time role.",
       "Remote - US"),  # not an intern/co-op/apprentice
    _r("StartupNoHistory", "ML Engineer Intern",
       "Train recommendation models with TensorFlow. We love sponsoring great "
       "people.",
       "Boston, MA"),  # in require_history mode: dropped (no USCIS history)
]
