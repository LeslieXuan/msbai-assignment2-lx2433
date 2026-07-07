# CLAUDE.md — NYC 311 × NYC Weather Data Product

Guidance for Claude Code (and humans) working in this repo. This file records the
**Specify decisions** for Assignment 2: an open-ended data product joining **NYC 311
Service Requests** to **NYC daily weather**, built on GCP and presented as a public
dashboard.

> This is a living spec. When a decision changes, change it *here* in the same PR that
> changes the code. Anything asserted but not yet checked in code is labeled
> **UNVERIFIED** until a verification step confirms it.

---

## 0. Cloud environment (reuse — do NOT create new projects)

| Thing | Value |
|---|---|
| GCP project | `msbai-dwd-lx2433` (project number `526972029302`) |
| Service account | `claude-agent@msbai-dwd-lx2433.iam.gserviceaccount.com` (has BigQuery + Storage + Cloud Run; read on `nyu-datasets.weather.m_weather_daily_nyc`) |
| Auth (CI) | Workload Identity Federation, provider `projects/526972029302/locations/global/workloadIdentityPools/github-actions-pool/providers/github-oidc`. Repo `LeslieXuan/msbai-assignment2-lx2433` is authorized to impersonate the SA. |
| GCS bucket (raw landing) | `msbai-dwd-lx2433-nyc311-raw` |
| BigQuery dataset — raw | `nyc311_raw` |
| BigQuery dataset — clean/analysis | `nyc311` |
| BigQuery location | `US` (must match `nyu-datasets` so the join works) |

**Every GitHub Actions workflow** uses `google-github-actions/auth@v2` with that provider +
SA, and declares:

```yaml
permissions:
  id-token: write
  contents: read
```

These objects are **new and dedicated** so nothing collides with the existing Citibike
work in the same project.

---

## 1. Source

- **Dataset:** NYC 311 Service Requests (NYC Open Data), Socrata SODA API.
- **Endpoint:** `https://data.cityofnewyork.us/resource/erm2-nwe9.json`
- **Dataset id:** `erm2-nwe9`
- **Format:** JSON rows over HTTP (SoQL query params).
- **Auth:** anonymous works; an **app token** (`$$app_token` / `X-App-Token` header) is
  optional and only raises the throttling ceiling. If present it is read from the
  `SODA_APP_TOKEN` GitHub secret; ingestion must succeed without it.
- **Weather join source:** `nyu-datasets.weather.m_weather_daily_nyc` (read-only, one row
  per calendar day for NYC).

### Why this source
311 is a high-volume behavioral signal (what residents complain about, when and where);
daily weather is a clean exogenous driver. The pair supports a sharp, testable question
(Part 2) without needing any third dataset.

---

## 2. Grain & the definition of "day"

- **Raw grain:** one row per **`unique_key`** (one 311 service request). `unique_key` is
  the natural primary key and must be unique.
- **"Day" = the local NYC calendar date of `created_date`.** `created_date` is a
  wall-clock timestamp in America/New_York (Socrata returns it without an offset). We take
  its **date part directly** as `complaint_date` — no timezone conversion, because the
  value is already local. This is the key we join to weather on.
  - Rationale: weather is reported per local calendar day; residents experience weather on
    local days; converting to UTC would smear late-night complaints into the wrong weather
    day.
- **Analysis grain:** one row per **`complaint_date` × `complaint_type` × `borough`**, with
  a complaint count and that day's weather attributes attached.

---

## 3. Schema — keep / drop / derive

The SODA response has ~40+ columns with heavy drift and sparsity. We **keep a stable core**
and drop the rest at the clean layer (raw layer keeps everything for provenance).

**Keep (typed at the clean layer):**

| Column | Type | Notes |
|---|---|---|
| `unique_key` | INT64 | PK; dedup on this |
| `created_date` | TIMESTAMP | source of `complaint_date` |
| `closed_date` | TIMESTAMP | nullable |
| `complaint_type` | STRING | primary analysis dimension |
| `descriptor` | STRING | sub-type, kept for drill-down |
| `agency` | STRING | |
| `borough` | STRING | analysis dimension; normalized (see below) |
| `incident_zip` | STRING | kept as STRING (leading zeros, non-numeric) |
| `latitude` | FLOAT64 | nullable |
| `longitude` | FLOAT64 | nullable |
| `status` | STRING | |
| `open_data_channel_type` | STRING | phone/online/mobile |

**Derived (clean layer):**
- `complaint_date` DATE = `DATE(created_date)` (local, see §2).
- `borough` normalized to `{MANHATTAN, BRONX, BROOKLYN, QUEENS, STATEN ISLAND, UNSPECIFIED}`
  (uppercase, trim, map blanks/`Unspecified`/`0` → `UNSPECIFIED`).

**Drop from analysis (kept only in raw JSON):** address/location detail
(`incident_address`, `street_name`, `cross_street_*`, `intersection_*`, BBL, `x/y` state
plane), routing fields (`facility_type`, `location_type`, `community_board`, `bbl`,
`park_*`, `bridge_*`, `taxi_*`, `vehicle_*`), and other request-type-specific sparse
columns. Reason: near-empty across most complaint types, not needed for a day×type×borough
product, and the biggest source of field drift.

**Field drift policy:** the ingester **does not** enforce a column list on read — it stores
the **full raw JSON** per row. The clean view then `SAFE`-casts and selects only the core
columns via `JSON_VALUE`. New/renamed/removed source columns therefore never break
ingestion; they only surface when we choose to promote them into the clean layer.

---

## 4. Pipeline layers

```
Socrata SODA API
   │  ingester (Python, paginated, retried)
   ▼
GCS  gs://msbai-dwd-lx2433-nyc311-raw/…      (raw JSON, partitioned by pull window)
   │  load
   ▼
BQ   nyc311_raw.requests_raw                  (full raw rows + _ingested_at, _source_page)
   │  clean typed view
   ▼
BQ   nyc311.requests_clean   (view)           (typed core columns, normalized borough, complaint_date)
   │  aggregate + join weather
   ▼
BQ   nyc311.daily_complaints  (table)         (complaint_date × complaint_type × borough × count × weather)
```

- **Raw table `nyc311_raw.requests_raw`**: append-only landing. Full source payload
  retained (as JSON or wide STRING columns) plus ingestion metadata (`_ingested_at`,
  `_pull_window`, `_source_offset`). No dedup here.
- **Clean view `nyc311.requests_clean`**: typed, deduplicated on `unique_key` (latest
  `_ingested_at` wins), core columns only, `complaint_date` and normalized `borough`
  derived. A **view** (not a table) so it always reflects the latest raw load.
- **Analysis table `nyc311.daily_complaints`**: materialized aggregate,
  `GROUP BY complaint_date, complaint_type, borough`, `LEFT JOIN` weather on
  `complaint_date = weather.date`. `LEFT JOIN` so a complaint day is never dropped for
  missing weather (missing weather is surfaced as NULL and counted in verification).

---

## 5. Pagination, rate limits, retries

- **Window bound:** pull is bounded to **created_date in 2023-01-01 … 2025-12-31** to start
  (configurable via workflow inputs). We never pull the full ~40M-row history.
- **Pagination:** page by `created_date` ranges combined with `$limit`/`$offset`.
  Preferred: iterate **day-by-day (or month-by-month) using `$where` on `created_date`**
  with `$order=created_date` + `$limit` (page size 50000), advancing a cursor — this avoids
  deep-`$offset` cost and is stable under concurrent writes to the source.
- **Rate limits:** exponential backoff with jitter on HTTP 429/5xx (base 2s, cap ~60s,
  max ~6 retries). Send the app token when available to raise the ceiling.
- **Idempotency:** each run writes to a window-scoped GCS prefix and reloads that window;
  re-running a window replaces its raw objects rather than duplicating.

---

## 6. Verification strategy (commit this; label the unverified)

Every load reports these checks; a failed hard check fails the workflow.

1. **Row-count reconciliation** — compare loaded row count for the window to the Socrata
   dataset's own count for the same `$where` window (`SELECT COUNT(*)` via
   `$select=count(1)` on the API). Expect a match within a small tolerance (source may gain
   rows between the count call and the pull); log the delta.
2. **Uniqueness invariant** — `unique_key` has **zero duplicates** in the clean view
   (hard check).
3. **No missing days** — every calendar date in the window appears in `daily_complaints`
   (a day with zero complaints is implausible for 311 and flags a gap). Hard check.
4. **Plausible ranges** — `complaint_date` within the window; `latitude`/`longitude` within
   NYC bounding box or NULL; counts ≥ 1; borough in the allowed set.
5. **Weather join coverage** — fraction of `daily_complaints` rows with non-NULL weather;
   list any dates missing weather. Reported, not hard-failed (weather source owned upstream).
6. **Labeling** — any metric we assert but haven't yet checked in code is marked
   **UNVERIFIED** in docs/PR until a check exists.

Correlation ≠ causation, hold-out checks, and magnitude sanity checks are **Part 2**
concerns and specified there.

---

## 7. Repo layout (target)

```
CLAUDE.md              ← this file (Specify decisions)
DECISIONS.md           ← Part 3: defense of choices
README.md
ingest/                ← Socrata ingester (Python)
sql/                   ← clean view + daily_complaints DDL/queries
  01_requests_clean.sql
  02_daily_complaints.sql
verify/                ← verification queries + runner
analysis/              ← Part 2 notebooks / queries
dashboard/             ← Part 3 Streamlit app + Dockerfile
.github/workflows/     ← WIF-authed ingest, build-daily, deploy
```

---

## 8. Conventions

- **BigQuery location `US`** everywhere (cross-dataset join requires it).
- Prefer **`SAFE_CAST`** in the clean layer so one bad value never fails a load.
- SQL is **idempotent** (`CREATE OR REPLACE`); loads are **window-idempotent**.
- Never hardcode secrets; app token via `SODA_APP_TOKEN` secret only.
- Every chart in the Part 3 dashboard carries **one plain-language claim**.
- Do not touch existing Citibike objects in the project.

---

## 9. Build plan (checkpoints)

- **Part 1 — Load:** this spec + ingester → `nyc311_raw` → clean view → `daily_complaints`
  joined to weather + verification. *(current)*
- **Part 2 — Analyze:** which 311 complaint types are weather-driven and by how much
  (e.g. heat → noise / `HEAT/HOT WATER`; rain → `Sewer` / flooding), controlling for season
  and day-of-week; with a hold-out / alternative-slice check and stated causal caveats.
- **Part 3 — Present:** public Streamlit dashboard on Cloud Run (WIF deploy,
  `--allow-unauthenticated`) + `DECISIONS.md`.
