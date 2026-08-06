"""Pytest suite. Mirrors tools/selftest.py but as standard pytest cases.

Run:  pip install -r requirements-dev.txt  &&  pytest -q
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from intern_engine.classify import classify, detect_role_type
from intern_engine.models import Category, RoleType, Role
from intern_engine.visa import detect
from intern_engine.sponsors import SponsorIndex, normalize_employer
from intern_engine.dedup import dedupe
from intern_engine.locations import is_us
from intern_engine.enrich import extract_skills, extract_pay
from intern_engine.render import (render_csv, render_json, render_readme,
                                  render_rss, render_dashboard)
from intern_engine.config import Settings, CompanyRef

SAMPLE = os.path.join(os.path.dirname(__file__), "..", "data",
                      "h1b_employers.sample.csv")


def test_classify_domains_and_types():
    assert classify("Security Engineer Intern", "SOC SIEM threat") == (
        Category.CYBER, RoleType.INTERN)
    assert classify("Machine Learning Research Co-op", "PyTorch NLP") == (
        Category.AI, RoleType.COOP)
    assert classify("Cybersecurity Apprenticeship", "red team")[1] == RoleType.APPRENTICE
    assert classify("Marketing Intern", "email marketing social")[0] is None
    assert classify("Software Engineer, Backend", "Go full time")[1] is None


def test_classify_false_positive_guards():
    assert classify("HR Intern", "social security paperwork")[0] is None
    assert detect_role_type("Internal Communications Manager") is None
    assert classify("AI Security Engineer Intern", "LLM prompt injection")[0] in (
        Category.CYBER, Category.AI)


def test_visa_detection():
    assert detect("We are unable to provide visa sponsorship now or in the future.")[0]
    assert detect("Must be a US citizen with a TS/SCI clearance.")[1]
    assert detect("We welcome all applicants to this internship.") == (False, False)


def test_sponsor_index():
    assert normalize_employer("Amazon.com Services LLC") == "amazon"
    assert normalize_employer("The Trade Desk Inc") == "trade desk"
    idx = SponsorIndex.from_paths([SAMPLE], min_petitions=1)
    assert len(idx) > 10
    assert idx.lookup("CrowdStrike") > 200          # summed across FY22+FY23
    assert idx.lookup("Palantir Technologies Inc") >= 300
    assert idx.lookup("Totally Unknown Co") == 0
    assert idx.has_history("Anthropic")


def test_dedup_prefers_real_date():
    b = Role(company="Acme", title="Security Intern", location="New York",
             url="u2", source="lever", posted_at="2026-07-01", posted_source="source")
    c = Role(company="Acme", title="Security Intern", location="New York, NY",
             url="u3", source="greenhouse")
    out = dedupe([b, c])
    assert len(out) == 1 and out[0].posted_source == "source"


def test_locations():
    assert is_us("Austin, TX")
    assert not is_us("Toronto, Canada", "Canada")
    assert is_us("Remote - US")
    assert not is_us("London, United Kingdom")


def test_enrich():
    sk = extract_skills("We use Python, PyTorch and Splunk.")
    assert {"Python", "PyTorch", "Splunk"} <= set(sk)
    assert extract_pay("Pay is $40/hour.") != ""
    assert extract_pay("$30 - $45 per hour") != ""


def test_sponsor_real_uscis_format(tmp_path):
    # Real USCIS files are UTF-16, tab-delimited, with split approval columns
    # and blank-employer rows. Verify the loader handles all of that.
    header = ("Line by line\tFiscal Year\tEmployer (Petitioner) Name\tTax ID\t"
              "New Employment Approval\tNew Employment Denial\t"
              "Continuation Approval\tChange of Employer Approval")
    rows = [
        "1\t2026\t\t1\t5\t0\t0\t0",                       # blank -> skipped
        "2\t2026\tACME PLATFORMS INC\t2\t10\t1\t3\t2",    # 15 approvals
        "3\t2026\tNIMBUS SECURITY LLC\t3\t4\t0\t0\t1",    # 5 approvals
        "4\t2026\tDENIALS ONLY CORP\t4\t0\t9\t0\t0",      # 0 -> skipped
    ]
    p = tmp_path / "Employer_Information.csv"
    p.write_text("\r\n".join([header] + rows) + "\r\n", encoding="utf-16")
    idx = SponsorIndex.from_paths([str(p)], min_petitions=1)
    assert len(idx) == 2
    assert idx.lookup("Acme Platforms Inc") == 15          # split cols summed
    assert idx.lookup("Acme") == 15                        # brand fallback
    assert idx.lookup("Nimbus Security") == 5
    assert idx.lookup("Denials Only Corp") == 0            # denials-only skipped


def test_dashboard_render():
    r = Role(company="CrowdStrike", title="Security Engineer Intern",
             location="Austin, TX", url="https://x/y", source="greenhouse",
             category=Category.CYBER.value, role_type=RoleType.INTERN.value,
             sponsor_history=True, sponsor_petitions=126,
             posted_at="2026-07-24", posted_source="first_seen",
             skills=["Python"], pay="$45/hour")
    r.compute_uid()
    stats = {"open": 1, "new": 1, "new_uids": {r.uid}, "companies": 41,
             "sponsors_indexed": 70767}
    html = render_dashboard([r], stats, Settings(), {r.uid})
    assert "__DATA__" not in html and "__META__" not in html
    assert 'class="stamp"' in html
    blob = re.search(r'<script id="data"[^>]*>(.*?)</script>', html, re.S).group(1)
    recs = json.loads(blob)
    assert len(recs) == 1 and recs[0]["petitions"] == 126
    assert "description" not in recs[0]


def test_adzuna_parse_and_skip():
    import asyncio
    from intern_engine.adapters.adzuna import AdzunaAdapter
    ad = AdzunaAdapter()
    job = {
        "title": "Machine Learning <strong>Intern</strong>",
        "company": {"display_name": "Databricks"},
        "location": {"display_name": "San Francisco, California"},
        "description": "Work on ML infrastructure...",
        "created": "2026-07-22T00:00:00Z",
        "redirect_url": "https://www.adzuna.com/land/ad/999",
        "salary_min": 100000, "salary_max": 100000, "salary_is_predicted": 1,
    }
    r = ad._to_role(job, "u")
    assert r.title == "Machine Learning Intern"
    assert r.company == "Databricks"
    assert r.posted_at == "2026-07-22" and r.posted_source == "source"
    assert r.country_hint == "US"
    assert r.pay == ""                       # predicted salary is not shown
    # no credentials in env -> empty, no exception
    assert asyncio.run(ad.fetch(None, CompanyRef(name="q", ats="adzuna", token="ml intern"))) == []


def test_newgrad_detection():
    assert detect_role_type("New Grad Security Engineer", "SIEM full-time") == RoleType.NEWGRAD
    assert detect_role_type("Machine Learning Engineer, University Graduate", "PyTorch") == RoleType.NEWGRAD
    assert detect_role_type("Junior Threat Analyst", "SOC") == RoleType.NEWGRAD
    assert detect_role_type("Senior Security Engineer", "mentor new grads, 8+ years") is None
    assert detect_role_type("Staff ML Engineer", "entry level friendly") is None
    assert detect_role_type("New Grad Security Intern", "") == RoleType.INTERN   # precedence
    assert detect_role_type("Security Engineer", "join our team") is None
    assert detect_role_type("Security Analyst", "an entry-level role for new graduates") == RoleType.NEWGRAD


def test_adzuna_company_targeting():
    from intern_engine.adapters.adzuna import AdzunaAdapter
    ad = AdzunaAdapter()
    assert ad._company_matches("Amazon.com Services LLC", "Amazon")
    assert ad._company_matches("Blue Cross Blue Shield of RI", "Blue Cross Blue Shield of Rhode Island")
    assert ad._company_matches("Acme Corp", "Amazon") is False
    assert ad._company_matches("Anything Inc", "EY") is True     # target too short to filter


def test_phenom_parse():
    from intern_engine.adapters.phenom import PhenomAdapter
    ad = PhenomAdapter()
    co = CompanyRef(name="Forvis Mazars", ats="phenom", token="jobs.forvismazars.us")
    payload = {"refineSearch": {"data": {"jobs": [{
        "title": "Intern IT Risk and Compliance | Cyber | Fall 2026",
        "cityStateCountry": "Charlotte, North Carolina, United States",
        "descriptionTeaser": "Cybersecurity risk assessments and controls testing.",
        "postedDate": "Aug 01, 2026",
        "jobDetailUrl": "/jobs/11436/intern-it-risk",
    }]}}}
    jobs = ad._extract_jobs(payload)
    assert len(jobs) == 1
    r = ad._to_role(jobs[0], "jobs.forvismazars.us", "u", co)
    assert r.company == "Forvis Mazars"
    assert r.url == "https://jobs.forvismazars.us/jobs/11436/intern-it-risk"
    assert r.posted_at == "2026-08-01"
    cat, rt = classify(r.title, r.description)
    assert cat == Category.CYBER and rt == RoleType.INTERN
    assert ad._extract_jobs({"nope": 1}) == []
    assert ad._to_role({"postedDate": "Aug 01, 2026"}, "h", "u", co) is None


def test_amazonjobs_parse():
    import asyncio
    from intern_engine.adapters.amazonjobs import AmazonJobsAdapter
    ad = AmazonJobsAdapter()

    class _Res:
        status = 200
        json = {"jobs": [{
            "title": "Security Engineer Intern",
            "job_path": "/en/jobs/1/security-engineer-intern",
            "normalized_location": "Seattle, Washington, USA",
            "posted_date": "August 1, 2026",
            "description": "AWS Security threat detection internship.",
        }]}

    class _Fetcher:
        async def get(self, url, **kw):
            return _Res()

    roles = asyncio.run(ad.fetch(_Fetcher(), CompanyRef(name="Amazon", ats="amazonjobs",
                                                        token="cybersecurity intern")))
    assert len(roles) == 1
    assert roles[0].company == "Amazon"
    assert roles[0].url == "https://www.amazon.jobs/en/jobs/1/security-engineer-intern"
    assert roles[0].posted_at == "2026-08-01"


def test_employment_type_axis():
    from intern_engine.enrich import detect_employment_type, normalize_employment_type
    from intern_engine.pipeline import _reconcile_role_type, classify_and_enrich
    assert normalize_employment_type("full_time") == "Full-time"
    assert normalize_employment_type("permanent") == "Full-time"
    assert normalize_employment_type("intern") == ""
    assert detect_employment_type("X", "a full-time internship") == "Full-time"
    assert detect_employment_type("X", "nothing stated") == ""
    # source-declared stage beats generic new-grad inference
    assert _reconcile_role_type(RoleType.INTERN.value, RoleType.NEWGRAD) == RoleType.INTERN.value
    assert _reconcile_role_type(None, RoleType.COOP) == RoleType.COOP.value
    r = Role(company="C", title="Security Engineer Intern", url="u", source="s",
             description="full-time summer internship in the SOC")
    classify_and_enrich(r, SponsorIndex(counts={}, min_petitions=1))
    assert r.role_type == RoleType.INTERN.value
    assert r.employment_type == "Full-time"


def test_render_outputs():
    r = Role(company="CrowdStrike", title="Security Engineer Intern",
             location="Austin, TX", url="https://x/y", source="greenhouse",
             category=Category.CYBER.value, role_type=RoleType.INTERN.value,
             sponsor_history=True, sponsor_petitions=300,
             posted_at="2026-07-20", posted_source="first_seen",
             skills=["Python"], pay="$40/hour")
    r.compute_uid()
    stats = {"open": 1, "new": 1, "new_uids": {r.uid}, "companies": 10,
             "fetched_ok": 8, "sources": {"greenhouse"}, "duration_s": 1.0}
    md = render_readme([r], stats, [], Settings())
    assert "CrowdStrike ✓" in md and "🆕" in md and "[Apply](https://x/y)" in md
    payload = json.loads(render_json([r], stats))
    assert len(payload["roles"]) == 1 and "description" not in payload["roles"][0]
    assert "<item>" in render_rss([r], "https://s", "Feed", {r.uid})
