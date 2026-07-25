# Architecture

## Data flow

```
config/companies.yml ─┐
                      ▼
              adapters (per ATS)         ← async HTTP (http.py): concurrency cap,
              greenhouse / lever /         per-host rate limit, retry/backoff,
              ashby / smartrecruiters /    circuit breaker, conditional caching
              workday
                      │  raw Role objects (identity + description + any real date)
                      ▼
   classify.py  ──►  domain (Cybersecurity / AI/ML) + role type (intern/coop/apprentice)
   visa.py      ──►  no_sponsorship / citizenship_required  (from posting text)
   sponsors.py  ──►  H-1B petition count + has_history       (USCIS data)
   enrich.py    ──►  skill tags + pay
                      │
                      ▼
   pipeline.keep()  ── filter: category ∈ target, role_type ∈ target, US-only,
                       sponsorship_mode, citizenship rule
                      │
                      ▼
   dedup.py     ──►  collapse duplicates across sources (prefer real date)
                      │
                      ▼
   store.py     ──►  stamp stable first_seen / posted_at, flag 🆕, record closures
                      │
                      ▼
   render/      ──►  README.md · internships.csv · internships.json · feed.xml
```

## Module map (`src/intern_engine/`)

| File | Responsibility |
|---|---|
| `models.py` | `Role` dataclass, `Category`/`RoleType` enums, stable `uid` |
| `config.py` | Load `settings.yml` and `companies.yml` |
| `http.py` | Async `Fetcher`: concurrency, rate limiting, retries, circuit breaker, ETag/Last-Modified (httpx imported lazily) |
| `adapters/` | One module per ATS + a registry; each returns partially-filled `Role`s |
| `classify.py` | Domain + role-type scoring with false-positive guards |
| `visa.py` | No-sponsorship & citizenship/clearance detection |
| `sponsors.py` | USCIS employer-name normalization, index build, fuzzy lookup |
| `enrich.py` | Skill/stack tags and pay extraction |
| `locations.py` | US-location detection for `us_only` |
| `dedup.py` | Cross-source de-duplication |
| `store.py` | JSON state: stable dates, 🆕 window, recently-closed, HTTP cache |
| `pipeline.py` | Orchestration + filtering policy |
| `render/` | README (Markdown), CSV, JSON, RSS |

## ATS endpoints used

| Adapter | Endpoint | Real publish date? |
|---|---|---|
| greenhouse | `GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true` | No (only `updated_at`) → first-seen |
| lever | `GET https://api.lever.co/v0/postings/{token}?mode=json` | Yes (`createdAt`, epoch ms) |
| ashby | `GET https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=true` | Sometimes (`publishedDate`) |
| smartrecruiters | `GET https://api.smartrecruiters.com/v1/companies/{token}/postings` (paginated) | Yes (`releasedDate`) |
| workday | `POST https://{host}/wday/cxs/{tenant}/{site}/jobs` | No (relative only) → first-seen |

All are public, read-only, unauthenticated JSON feeds.

## Adding a new ATS adapter

1. Create `src/intern_engine/adapters/<name>.py` with a class subclassing
   `Adapter`, setting `name = "<name>"`, and implementing:

   ```python
   async def fetch(self, fetcher, company) -> list[Role]:
       res = await fetcher.get(some_url)          # fetcher handles retries etc.
       if res.status != 200: return []
       roles = []
       for job in res.json[...]:
           roles.append(Role(company=company.name, title=..., url=...,
                             source=self.name, board_token=company.token,
                             location=..., description=...,
                             posted_at=<iso or None>,
                             posted_source="source" if real_date else "unknown"))
       return roles
   ```

   Use helpers in `adapters/base.py` (`html_to_text`, `iso_from_epoch_ms`,
   `iso_from_string`). Only set `posted_source="source"` when the date is a
   genuine *publish* date, not an edit timestamp.

2. Register it in `adapters/__init__.py`.
3. Add companies under that key in `config/companies.yml`.

## Testing

- `tools/selftest.py` — dependency-free assertions (runs anywhere).
- `tests/test_engine.py` — the same coverage as pytest.
- `python run.py --self-test` — full pipeline over `tools/fixtures.py`, no
  network.

Because every pure-logic module avoids third-party imports, the classifier,
sponsor index, dedup, and renderers are all unit-testable without installing
`httpx` or hitting the network.
