# Setup & self-hosting

## 1. Install and run locally

```bash
git clone <your-fork-url> && cd intern-engine
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

This polls the companies in `config/companies.yml`, applies the filters in
`config/settings.yml`, and (re)writes `README.md`, `data/internships.csv`,
`data/internships.json`, and `docs/feed.xml`. State is kept in
`data/state.json` so posting dates and "🆕/recently-closed" stay stable
between runs.

Test without network:

```bash
python tools/selftest.py     # pure-logic checks, zero dependencies
python run.py --self-test    # full pipeline over fixture postings
pytest -q                    # if you installed requirements-dev.txt
```

## 2. Load real H-1B sponsorship data (important)

The repo ships a tiny `data/h1b_employers.sample.csv` so it runs out of the
box. For real coverage, download the official per-fiscal-year CSVs and drop
them in `data/h1b/`:

1. Go to the **USCIS H-1B Employer Data Hub**:
   <https://www.uscis.gov/tools/reports-and-studies/h-1b-employer-data-hub>
2. Download one or more fiscal years as CSV (the "Employer Data Hub Files" page
   links full-year files). Recent years matter most.
3. Save them into `data/h1b/` (any filenames ending in `.csv`).

The loader auto-detects the `Employer` and approval columns and sums approvals
per employer across every file it finds. If `data/h1b/` is empty it falls back
to the sample. More years = better matching, at the cost of a slightly larger
in-memory index.

> The USCIS files can be large; `.gitignore` excludes `data/h1b/*.csv` by
> default so you don't bloat the repo. Remove that line if you'd rather commit
> them (GitHub Actions re-downloads nothing, so committing is the simplest way
> to make the data available to the workflow — see step 4).

## 3. Configure filtering (`config/settings.yml`)

Key knobs:

- `sponsorship_mode`: `require_history` | `exclude_negative` | `flag_only`
  (see the table in the README).
- `min_petitions`: raise to be stricter about what counts as "a sponsor"
  (e.g. `10` mirrors the reference repo's ✓ threshold).
- `exclude_citizenship_required`: drop US-citizen / clearance-only roles.
- `categories` / `role_types`: currently Cybersecurity + AI/ML, and
  Internship + Co-op + Apprenticeship.
- `us_only`: keep US roles only.
- HTTP politeness: `concurrency`, `per_host_delay_ms`, `max_retries`,
  `circuit_fail_threshold`.

## 4. Turn on the self-updating schedule (GitHub Actions)

`.github/workflows/update.yml` runs the engine every 2 hours (and on demand)
and commits the regenerated files back to the repo.

1. Push your fork to GitHub.
2. In **Settings → Actions → General**, set *Workflow permissions* to
   **Read and write**.
3. (If you want real sponsorship data in CI) either commit your `data/h1b/*.csv`
   files, or add a step to the workflow that downloads them before `python run.py`.
4. The schedule starts automatically; trigger a first run from the **Actions**
   tab → *update-internships* → *Run workflow*.
5. To publish the **live dashboard**, enable **GitHub Pages** (Settings → Pages
   → Source: *Deploy from a branch* → branch `main`, folder `/docs`). Your board
   goes live at `https://<you>.github.io/<repo>/` — a searchable, filterable page
   with a sponsorship stamp (and real petition count) on every cleared role. The
   RSS feed sits alongside it at `docs/feed.xml`. The engine regenerates
   `docs/index.html` on every run, so the page stays current automatically.

Adjust the cadence by editing the `cron:` line (UTC). Hourly is `0 * * * *`.

## 5. Grow coverage (the part that matters most)

The engine only sees companies you list. To approach "every company that posts
these roles," keep expanding `config/companies.yml`. Each entry is one line:

```yaml
companies:
  greenhouse:
    - stripe                       # slug == token
    - name: "The Trade Desk"
      token: "thetradedesk"
  lever:
    - palantir
  ashby:
    - openai
  smartrecruiters:
    - name: "Visa"
      token: "Visa"
  workday:
    - name: "Example (Workday)"
      token: "example"
      host: "example.wd1.myworkdayjobs.com"
      site: "External"
```

**Finding the right ATS + token for a company:** open its careers page and look
at the URL/network requests:

- `boards.greenhouse.io/<token>` or `job-boards.greenhouse.io/<token>` →
  **greenhouse**, token = `<token>`.
- `jobs.lever.co/<token>` → **lever**.
- `jobs.ashbyhq.com/<token>` → **ashby**.
- `jobs.smartrecruiters.com/<token>` or `careers.smartrecruiters.com/<token>`
  → **smartrecruiters**.
- `<company>.myworkdayjobs.com/...` → **workday** (grab `host`, `tenant`, `site`
  from the URL; posting dates there are relative, so first-seen is used).

A wrong or stale token is harmless — the engine skips anything that 404s or
switches ATS, so a bad line just yields nothing. This means you can safely
paste in large batches and prune later.

**Scaling to thousands:** community-maintained ATS board-token catalogs exist
(search for "greenhouse/lever/ashby company token list"). You can bulk-append
them under the right platform key. The classifier + sponsorship filter will
keep only the relevant roles, so a big, sector-agnostic list is exactly the
intended way to use this.

## Troubleshooting

- **A known company shows no ✓** — its USCIS name may differ from your display
  name, or you haven't loaded that fiscal year. Check
  `python -c "import sys; sys.path.insert(0,'src'); from intern_engine.sponsors import SponsorIndex; i=SponsorIndex.from_dir('data/h1b', sample='data/h1b_employers.sample.csv'); print(i.lookup('Company Name'))"`.
- **A feed returns nothing** — verify the token by opening the API URL from
  ARCHITECTURE.md in a browser.
- **Too many/few roles** — tune `sponsorship_mode` and `min_petitions`.
