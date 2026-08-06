#!/usr/bin/env python3
"""Dependency-free assertions over the pure logic. Run: python tools/selftest.py"""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from intern_engine.classify import classify, classify_domain, detect_role_type
from intern_engine.models import Category, RoleType, Role
from intern_engine.visa import detect
from intern_engine.sponsors import SponsorIndex, normalize_employer
from intern_engine.dedup import dedupe
from intern_engine.locations import is_us
from intern_engine.enrich import extract_skills, extract_pay
from intern_engine.render import (render_csv, render_json, render_readme,
                                  render_rss, render_dashboard)
from intern_engine.config import Settings

PASS = 0
FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {name}")


def test_classify():
    cat, rt = classify("Security Engineer Intern", "SOC, SIEM, threat detection")
    check("cyber intern -> CYBER", cat == Category.CYBER)
    check("cyber intern -> INTERN", rt == RoleType.INTERN)

    cat, rt = classify("Machine Learning Research Co-op", "PyTorch NLP deep learning")
    check("ml coop -> AI", cat == Category.AI)
    check("ml coop -> COOP", rt == RoleType.COOP)

    cat, rt = classify("Cybersecurity Apprenticeship", "red team exploit")
    check("apprentice -> APPRENTICE", rt == RoleType.APPRENTICE)

    cat, _ = classify("Marketing Intern", "email marketing and social media")
    check("marketing intern -> no domain", cat is None)

    cat, rt = classify("Software Engineer, Backend", "Go services full-time")
    check("backend SWE -> no role type", rt is None)

    # false-positive guards
    cat, _ = classify("HR Intern", "handle social security paperwork")
    check("social security not cyber", cat is None)
    check("internal not intern", detect_role_type("Internal Comms Manager") is None)

    # AI Security dual — should classify as one of the two, not None
    cat, _ = classify("AI Security Engineer Intern", "LLM security, prompt injection")
    check("ai-security classified", cat in (Category.CYBER, Category.AI))

    # --- new-grad / entry-level full-time ---
    cat, rt = classify("New Grad Security Engineer", "SIEM, incident response, full-time")
    check("new grad cyber -> NEWGRAD", rt == RoleType.NEWGRAD)
    check("new grad cyber -> CYBER", cat == Category.CYBER)

    cat, rt = classify("Machine Learning Engineer, University Graduate", "PyTorch, LLM")
    check("university grad ML -> NEWGRAD", rt == RoleType.NEWGRAD and cat == Category.AI)

    check("junior title -> NEWGRAD",
          detect_role_type("Junior Threat Analyst", "SOC monitoring") == RoleType.NEWGRAD)
    check("senior title vetoes new-grad",
          detect_role_type("Senior Security Engineer", "mentor new grads, 8+ years") is None)
    check("staff title vetoes",
          detect_role_type("Staff ML Engineer", "entry level friendly") is None)
    # intern precedence over new-grad
    check("intern beats new-grad",
          detect_role_type("New Grad Security Intern", "") == RoleType.INTERN)
    # a plain full-time SWE (no entry-level signal) is still nothing
    check("plain full-time -> None",
          detect_role_type("Security Engineer", "join our team") is None)
    # entry-level signal only in body
    check("body entry-level -> NEWGRAD",
          detect_role_type("Security Analyst", "This is an entry-level role for new graduates.")
          == RoleType.NEWGRAD)


def test_visa():
    ns, cz = detect("We are unable to provide visa sponsorship now or in the future.")
    check("no-sponsor detected", ns is True)
    ns, cz = detect("Must be a US citizen and obtain a security clearance (TS/SCI).")
    check("citizenship detected", cz is True)
    ns, cz = detect("Great internship. We welcome all applicants.")
    check("clean desc -> no flags", (ns, cz) == (False, False))


def test_sponsors():
    check("normalize strips suffix",
          normalize_employer("Amazon.com Services LLC") == "amazon")
    check("normalize the-prefix",
          normalize_employer("The Trade Desk Inc") == "trade desk")
    idx = SponsorIndex.from_paths(
        [os.path.join(os.path.dirname(__file__), "..", "data",
                      "h1b_employers.sample.csv")], min_petitions=1)
    check("index built", len(idx) > 10)
    check("crowdstrike summed across FYs", idx.lookup("CrowdStrike") > 200)
    check("prefix match palantir",
          idx.lookup("Palantir Technologies Inc") >= 300)
    check("unknown employer -> 0", idx.lookup("Totally Unknown Co") == 0)
    check("has_history true", idx.has_history("Anthropic") is True)


def test_dedup():
    a = Role(company="Acme", title="Security Intern", location="NYC",
             url="u1", source="greenhouse")
    b = Role(company="Acme", title="Security Intern", location="New York",
             url="u2", source="lever", posted_at="2026-07-01", posted_source="source")
    out = dedupe([a, b])
    # different first location token ("nyc" vs "new") -> not merged here
    check("dedup keeps distinct location tokens", len(out) == 2)
    c = Role(company="Acme", title="Security Intern", location="New York, NY",
             url="u3", source="greenhouse")
    out2 = dedupe([b, c])
    check("dedup merges same key, prefers real date",
          len(out2) == 1 and out2[0].posted_source == "source")


def test_locations():
    check("Austin TX is US", is_us("Austin, TX") is True)
    check("Toronto Canada not US", is_us("Toronto, Canada", "Canada") is False)
    check("Remote US is US", is_us("Remote - US") is True)
    check("London not US", is_us("London, United Kingdom") is False)


def test_enrich():
    sk = extract_skills("We use Python, PyTorch and Splunk daily.")
    check("skills extracted", "Python" in sk and "PyTorch" in sk and "Splunk" in sk)
    check("pay hourly", extract_pay("Pay is $40/hour for interns.") != "")
    check("pay range", extract_pay("$30 - $45 per hour") != "")


def test_render():
    settings = Settings()
    r = Role(company="CrowdStrike", title="Security Engineer Intern",
             location="Austin, TX", url="https://x/y", source="greenhouse",
             category=Category.CYBER.value, role_type=RoleType.INTERN.value,
             sponsor_history=True, sponsor_petitions=300,
             posted_at="2026-07-20", posted_source="first_seen",
             skills=["Python", "Splunk"], pay="$40/hour")
    r.compute_uid()
    stats = {"open": 1, "new": 1, "new_uids": {r.uid}, "companies": 10,
             "fetched_ok": 8, "sources": {"greenhouse"}, "duration_s": 1.2}
    md = render_readme([r], stats, [], settings)
    check("readme has company+check", "CrowdStrike ✓" in md)
    check("readme has NEW flag", "🆕" in md)
    check("readme has apply link", "[Apply](https://x/y)" in md)
    check("readme estimated-date marker", "2026-07-20 ~" in md)

    csv_text = render_csv([r])
    check("csv header", csv_text.splitlines()[0].startswith("company,title"))
    check("csv skills joined", "Python, Splunk" in csv_text)

    import json
    payload = json.loads(render_json([r], stats))
    check("json roles", len(payload["roles"]) == 1)
    check("json no description", "description" not in payload["roles"][0])

    rss = render_rss([r], "https://site", "Feed", {r.uid})
    check("rss item", "<item>" in rss and "CrowdStrike" in rss)


def test_sponsors_realformat():
    # Mimic the real USCIS file: UTF-16, TAB-delimited, split approval columns,
    # a blank-employer row, and a multi-word legal name.
    header = ("Line by line\tFiscal Year\tEmployer (Petitioner) Name\tTax ID\t"
              "New Employment Approval\tNew Employment Denial\t"
              "Continuation Approval\tChange of Employer Approval")
    rows = [
        "1\t2026\t\t1234\t5\t0\t0\t0",                         # blank name -> skip
        "2\t2026\tACME PLATFORMS INC\t2222\t10\t1\t3\t2",      # 15 approvals
        "3\t2026\tNIMBUS SECURITY LLC\t3333\t4\t0\t0\t1",      # 5 approvals
        "4\t2026\tDENIALS ONLY CORP\t4444\t0\t9\t0\t0",        # 0 approvals -> skip
    ]
    text = "\r\n".join([header] + rows) + "\r\n"
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "Employer_Information.csv")
    with open(path, "w", encoding="utf-16") as fh:   # BOM + UTF-16
        fh.write(text)
    idx = SponsorIndex.from_paths([path], min_petitions=1)
    check("realformat: parsed approving employers", len(idx) == 2)
    check("realformat: sums split approvals (10+3+2)", idx.lookup("Acme Platforms Inc") == 15)
    check("realformat: brand first-token fallback (Acme)", idx.lookup("Acme") == 15)
    check("realformat: denials-only skipped", idx.lookup("Denials Only Corp") == 0)
    check("realformat: suffix strip (Nimbus Security)", idx.lookup("Nimbus Security") == 5)


def test_dashboard():
    import json as _json
    settings = Settings()
    r = Role(company="CrowdStrike", title="Security Engineer Intern",
             location="Austin, TX", url="https://x/y", source="greenhouse",
             category=Category.CYBER.value, role_type=RoleType.INTERN.value,
             sponsor_history=True, sponsor_petitions=126,
             posted_at="2026-07-24", posted_source="first_seen",
             skills=["Python", "SIEM"], pay="$45/hour")
    r.compute_uid()
    stats = {"open": 1, "new": 1, "new_uids": {r.uid}, "companies": 41,
             "sponsors_indexed": 70767}
    html = render_dashboard([r], stats, settings, {r.uid})
    check("dashboard: markers replaced", "__DATA__" not in html and "__META__" not in html)
    check("dashboard: has clearance stamp", 'class="stamp"' in html)
    # embedded JSON parses and carries the role
    import re as _re
    blob = _re.search(r'<script id="data"[^>]*>(.*?)</script>', html, _re.S).group(1)
    recs = _json.loads(blob)
    check("dashboard: role embedded", len(recs) == 1 and recs[0]["petitions"] == 126)
    check("dashboard: no description leaked", "description" not in recs[0])


def test_adzuna():
    import asyncio as _asyncio
    from intern_engine.adapters.adzuna import AdzunaAdapter
    from intern_engine.config import CompanyRef
    ad = AdzunaAdapter()
    # a realistic Adzuna result object
    job = {
        "title": "Cybersecurity <strong>Intern</strong>",
        "company": {"display_name": "CrowdStrike"},
        "location": {"display_name": "Austin, Texas", "area": ["US", "Texas", "Austin"]},
        "description": "Join our SOC to help with detection engineering...",
        "created": "2026-07-24T09:15:00Z",
        "redirect_url": "https://www.adzuna.com/land/ad/123",
        "salary_min": 90000, "salary_max": 95000, "salary_is_predicted": 0,
    }
    r = ad._to_role(job, "https://api.adzuna.com/...")
    check("adzuna: strips tags in title", r.title == "Cybersecurity Intern")
    check("adzuna: real employer name", r.company == "CrowdStrike")
    check("adzuna: location carried", r.location == "Austin, Texas")
    check("adzuna: real posted date", r.posted_at == "2026-07-24" and r.posted_source == "source")
    check("adzuna: US hint set", r.country_hint == "US")
    check("adzuna: apply url", r.url.endswith("/123"))
    check("adzuna: pay from non-predicted salary", r.pay == "$90,000-$95,000/yr")
    # no credentials -> skip cleanly (empty result, no error)
    got = _asyncio.run(ad.fetch(None, CompanyRef(name="q", ats="adzuna", token="cybersecurity intern")))
    check("adzuna: no key -> empty", got == [])
    # company-targeting guard (server filter can be loose)
    check("adzuna: company match (Amazon)", ad._company_matches("Amazon.com Services LLC", "Amazon"))
    check("adzuna: company match multiword abbrev", ad._company_matches("Blue Cross Blue Shield of RI", "Blue Cross Blue Shield of Rhode Island") is True)
    check("adzuna: company mismatch dropped", ad._company_matches("Acme Corp", "Amazon") is False)
    check("adzuna: short target not over-filtered", ad._company_matches("Anything Inc", "EY") is True)


def test_phenom():
    from intern_engine.adapters.phenom import PhenomAdapter
    from intern_engine.config import CompanyRef
    ad = PhenomAdapter()
    co = CompanyRef(name="Forvis Mazars", ats="phenom", token="jobs.forvismazars.us")
    # standard Phenom shape: refineSearch.data.jobs, relative detail URL
    payload = {"refineSearch": {"totalHits": 1, "data": {"jobs": [{
        "jobId": "11436",
        "title": "Intern IT Risk and Compliance | Cyber | Fall 2026",
        "cityStateCountry": "Charlotte, North Carolina, United States",
        "descriptionTeaser": "Assist with cybersecurity risk assessments and controls testing.",
        "postedDate": "Aug 01, 2026",
        "jobDetailUrl": "/jobs/11436/intern-it-risk-and-compliance-cyber-fall-2026",
    }]}}}
    jobs = ad._extract_jobs(payload)
    check("phenom: finds jobs in refineSearch.data", len(jobs) == 1)
    r = ad._to_role(jobs[0], "jobs.forvismazars.us", "https://x/api/jobs", co)
    check("phenom: title parsed", r.title.startswith("Intern IT Risk"))
    check("phenom: company from config", r.company == "Forvis Mazars")
    check("phenom: relative url absolutized",
          r.url == "https://jobs.forvismazars.us/jobs/11436/intern-it-risk-and-compliance-cyber-fall-2026")
    check("phenom: loose date parsed", r.posted_at == "2026-08-01" and r.posted_source == "source")
    check("phenom: location parsed", r.location.startswith("Charlotte"))
    # and it must survive the real classifier as a kept cyber internship
    cat, rt = classify(r.title, r.description)
    check("phenom: classifies as cyber internship",
          cat == Category.CYBER and rt == RoleType.INTERN)
    # alternate shape: flat "jobs", split city/state, absolute url
    alt = {"jobs": [{"jobTitle": "Graduate Cyber Analyst", "city": "Dallas",
                     "state": "Texas", "country": "United States",
                     "applyUrl": "https://jobs.example.com/g/1",
                     "postedDate": "2026-07-30T00:00:00.000Z",
                     "summary": "entry-level role for new graduates in security operations"}]}
    jobs2 = ad._extract_jobs(alt)
    r2 = ad._to_role(jobs2[0], "jobs.example.com", "u", co)
    check("phenom: alt shape parsed", r2.title == "Graduate Cyber Analyst")
    check("phenom: split location joined", r2.location == "Dallas, Texas, United States")
    check("phenom: iso date parsed", r2.posted_at == "2026-07-30")
    check("phenom: absolute url kept", r2.url == "https://jobs.example.com/g/1")
    check("phenom: unknown shape -> no jobs", ad._extract_jobs({"nope": 1}) == [])
    check("phenom: missing title dropped",
          ad._to_role({"postedDate": "Aug 01, 2026"}, "h", "u", co) is None)


def test_amazonjobs():
    import asyncio as _asyncio
    from intern_engine.adapters.amazonjobs import AmazonJobsAdapter
    from intern_engine.config import CompanyRef
    ad = AmazonJobsAdapter()
    co = CompanyRef(name="Amazon", ats="amazonjobs", token="cybersecurity")

    class _Res:
        status = 200
        json = {"error": None, "hits": 2, "jobs": [
            {   # US role -> kept
                "title": "Security Engineer Intern",
                "job_path": "/en/jobs/2998877/security-engineer-intern",
                "normalized_location": "Seattle, Washington, USA",
                "country_code": "USA",
                "company_name": "Amazon.com Services LLC",
                "posted_date": "August 1, 2026",
                "description": "Join AWS Security to work on threat detection.",
                "basic_qualifications": "Pursuing a Bachelor's degree.",
                "is_intern": True,
            },
            {   # non-US role -> dropped by country_code
                "title": "Security Intern",
                "job_path": "/en/jobs/3/security-intern",
                "normalized_location": "Munich, Germany",
                "country_code": "DEU",
                "posted_date": "August 1, 2026",
                "description": "CEFR B2 required.",
            },
        ]}

    class _Fetcher:
        async def get(self, url, **kw):
            _Fetcher.seen = url
            return _Res()

    roles = _asyncio.run(ad.fetch(_Fetcher(), co))
    check("amazon: non-US dropped via country_code", len(roles) == 1)
    r = roles[0]
    check("amazon: company from company_name", r.company == "Amazon.com Services LLC")
    check("amazon: title parsed", r.title == "Security Engineer Intern")
    check("amazon: path absolutized",
          r.url == "https://www.amazon.jobs/en/jobs/2998877/security-engineer-intern")
    check("amazon: human date parsed", r.posted_at == "2026-08-01")
    check("amazon: descriptions merged", "threat detection" in r.description
          and "Bachelor" in r.description)
    check("amazon: query encoded in url", "base_query=cybersecurity" in _Fetcher.seen)
    check("amazon: uses verified country=USA", "country=USA" in _Fetcher.seen)
    check("amazon: uses sort=recent", "sort=recent" in _Fetcher.seen)
    check("amazon: US hint set", r.country_hint == "US")
    cat, rt = classify(r.title, r.description)
    check("amazon: classifies as cyber internship",
          cat == Category.CYBER and rt == RoleType.INTERN)
    # missing country_code -> kept (pipeline's US check decides)
    class _Res2:
        status = 200
        json = {"jobs": [{"title": "ML Intern", "job_path": "/x",
                          "description": "pytorch deep learning"}]}
    class _F2:
        async def get(self, url, **kw):
            return _Res2()
    check("amazon: unknown country kept",
          len(_asyncio.run(ad.fetch(_F2(), co))) == 1)
    # empty token -> no request
    check("amazon: empty token -> empty",
          _asyncio.run(ad.fetch(_Fetcher(), CompanyRef(name="a", ats="amazonjobs", token=""))) == [])


def test_employment_type():
    from intern_engine.enrich import detect_employment_type, normalize_employment_type
    from intern_engine.pipeline import _reconcile_role_type
    from intern_engine.sponsors import SponsorIndex
    from intern_engine.pipeline import classify_and_enrich
    # source vocabularies -> our labels
    check("emp: full_time mapped", normalize_employment_type("full_time") == "Full-time")
    check("emp: Part-Time mapped", normalize_employment_type("Part-Time") == "Part-time")
    check("emp: permanent -> Full-time", normalize_employment_type("permanent") == "Full-time")
    check("emp: contract mapped", normalize_employment_type("contract") == "Contract")
    check("emp: 'intern' is not an hours value", normalize_employment_type("intern") == "")
    check("emp: unknown -> blank", normalize_employment_type("banana") == "")
    # explicit wording only
    check("emp: full-time from text",
          detect_employment_type("Security Intern", "a full-time summer internship") == "Full-time")
    check("emp: part-time from text",
          detect_employment_type("Analyst", "20 hours per week, part time") == "Part-time")
    check("emp: silence -> blank",
          detect_employment_type("Security Engineer", "join our team") == "")

    # career stage vs employment basis are independent axes
    r = Role(company="CrowdStrike", title="Security Engineer Intern",
             url="u", source="greenhouse",
             description="This is a full-time summer internship in our SOC.")
    classify_and_enrich(r, SponsorIndex(counts={}, min_petitions=1))
    check("emp: intern keeps stage", r.role_type == RoleType.INTERN.value)
    check("emp: intern also full-time hours", r.employment_type == "Full-time")

    # source-declared stage beats a generic New Grad inference
    check("reconcile: hint wins over newgrad",
          _reconcile_role_type(RoleType.INTERN.value, RoleType.NEWGRAD) == RoleType.INTERN.value)
    check("reconcile: hint used when nothing inferred",
          _reconcile_role_type(RoleType.COOP.value, None) == RoleType.COOP.value)
    check("reconcile: inference used when no hint",
          _reconcile_role_type(None, RoleType.INTERN) == RoleType.INTERN.value)
    check("reconcile: specific inference kept over hint",
          _reconcile_role_type(RoleType.NEWGRAD.value, RoleType.COOP) == RoleType.COOP.value)
    # adapter-declared type survives the pipeline (amazon's is_intern case)
    r2 = Role(company="Amazon", title="2027 Applied Science Intern", url="u",
              source="amazonjobs", role_type=RoleType.INTERN.value,
              employment_type="Full-time",
              description="machine learning research, deep learning, PyTorch")
    classify_and_enrich(r2, SponsorIndex(counts={}, min_petitions=1))
    check("emp: declared intern preserved", r2.role_type == RoleType.INTERN.value)
    check("emp: source employment preserved", r2.employment_type == "Full-time")

    # surfaced in CSV and dashboard
    r2.compute_uid()
    csv_out = render_csv([r2])
    check("emp: employment_type column in CSV", "employment_type" in csv_out.splitlines()[0])
    check("emp: value in CSV row", "Full-time" in csv_out)
    html = render_dashboard([r2], {"open": 1, "new": 0, "companies": 1,
                                   "sponsors_indexed": 0}, Settings(), set())
    check("emp: type colour class rendered", "t-intern" in html)
    check("emp: New Grad label spells out full-time", "New Grad · Full-time" in html)


def main():
    for fn in (test_classify, test_visa, test_sponsors, test_sponsors_realformat,
               test_dedup, test_locations, test_enrich, test_employment_type,
               test_render, test_dashboard, test_adzuna, test_phenom,
               test_amazonjobs):
        fn()
    total = PASS + FAIL
    print(f"\n{PASS}/{total} checks passed.")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
