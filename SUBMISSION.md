# Assignment 2 — Build an End-to-End Data Product

**Name:** lx2433 · **Repo:** https://github.com/LeslieXuan/msbai-assignment2-lx2433
**Live dashboard:** https://nyc311-dashboard-526972029302.us-central1.run.app

## The product
A data product that joins **NYC 311 Service Requests** to **NYC daily weather** and
answers one sharp question: **which 311 complaint types are weather-driven, and by how
much — controlling for season and day-of-week?** Loaded to BigQuery, analyzed with a
hold-out-validated method, and shipped as a public interactive dashboard. Every stage
runs through Claude Code → GitHub PRs → GitHub Actions (Workload Identity Federation,
no keys).

## Why this data (choice defense)
- **Real, and you have to work for it:** NYC Open Data Socrata SODA API (`erm2-nwe9`),
  pulled over a 3-year window with pagination, rate-limit backoff, and heavy schema
  drift/sparsity — not a one-line CSV. ~10.3M rows.
- **A database is warranted:** volume (10M+ rows), a paginated API arriving in pieces,
  ~40 drifting columns, and a **cross-source join** to `nyu-datasets.weather.m_weather_daily_nyc`
  on local calendar date.
- **Allowed:** NYC Open Data is public/open; the weather mart is an authorized read for the
  project service account. Sources cited in `README.md` / `CLAUDE.md`.

---

## What to submit — index

### 1. GitHub repo
https://github.com/LeslieXuan/msbai-assignment2-lx2433

| Piece | Location |
|---|---|
| Spec / decisions | `CLAUDE.md` |
| Pipeline | `pipeline/` (`ingest_311.py`, `build_marts.py`, `verify.py`, `common.py`), `sql/`, `.github/workflows/pipeline.yml` |
| Verification evidence | `pipeline/verify.py` + **`VERIFICATION.md`** |
| Analysis | `analysis/` (`panel.sql`, `analyze.py`), `.github/workflows/analyze.yml` |
| Finding + result tables | **`analysis/FINDINGS.md`**, `analysis/results/*.csv` |
| Artifact | `dashboard/` (`app.py`, `Dockerfile`), `.github/workflows/deploy.yml` |
| Defense of choices | **`DECISIONS.md`** |

Teaching-team access (pi1@stern.nyu.edu, it2190@stern.nyu.edu): GitHub collaborators
added; BigQuery Data Viewer granted on the project.

### 2. Database objects — project `msbai-dwd-lx2433` (BigQuery location `US`)
- **Raw:** `nyc311_raw.requests_raw` — 10,336,524 rows; full source payload as JSON +
  ingest metadata. Landing bucket: `gs://msbai-dwd-lx2433-nyc311-raw`.
- **Clean unified view:** `nyc311.requests_clean` — typed, deduplicated on `unique_key`,
  local-date `complaint_date`, normalized `borough`.
- **Analysis-ready table:** `nyc311.daily_complaints` — 492,512 rows at
  `complaint_date × complaint_type × borough`, LEFT-joined to daily weather.
- **Reproduce the numbers:** `pipeline/verify.py` re-runs every check; `analysis/analyze.py`
  reproduces every finding. Both run in the workflows above.

### 3. The artifact (public dashboard)
https://nyc311-dashboard-526972029302.us-central1.run.app — Streamlit on Cloud Run,
public (`--allow-unauthenticated`), loads in seconds, no login. Reads live from BigQuery
with caching; **each chart carries one plain-language, hold-out-validated claim.**

---

## Verification evidence (Part 1) — see `VERIFICATION.md`
Hard checks (fail the build): `unique_key` uniqueness = **0 duplicates**; **0 missing**
calendar days (1,096/1,096); ranges (dates / NYC bbox / borough / counts) all clean.
Soft checks: row-count reconciliation vs Socrata's own `count(1)` = **−2 rows (0.00%)**;
weather-join coverage = **100%**.

## Finding (Part 2) — see `analysis/FINDINGS.md`
Season × day-of-week **adjusted** rate ratios, **validated on a 2023–24 → 2025 hold-out**:

| Finding | Effect | ≈ / year |
|---|---|--:|
| Cold → **HEAT/HOT WATER** | +160% (2.6×) on freezing days | +58,800 |
| Heat → **Water System** (open hydrants) | +150% (2.5×) on hot days | +3,200 |
| Rain → **Sewer** (flooding) | +87% (1.9×) on rainy days | +6,300 |
| Temperature ↔ **street/sidewalk noise** | corr +0.57; −25/−42/−61% rain/snow/freeze | — |
| Heat → **Dirty Condition** | +19% on hot days | +384 |

**Association, not causation** — season and weekday are controlled; weather still
co-varies with daylight, holidays, time outdoors, and reporting propensity. Humidity
effects failed the hold-out and were discarded; the hinted "heat→HEAT/HOT WATER" is
**backwards** (cold-driven) and "heat→noise" is **type-specific** — all reported honestly.

## Sources
NYC 311 Service Requests, NYC Open Data (Socrata `erm2-nwe9`, public). NYC daily weather:
`nyu-datasets.weather.m_weather_daily_nyc` (authorized read). Cited in `README.md` and
`CLAUDE.md`.
