# DECISIONS.md — defense of choices

Companion to `CLAUDE.md` (the spec) and `analysis/FINDINGS.md` (the results). This
explains *why* the NYC 311 × weather data product is built the way it is, and the
trade-offs behind each call.

**Live dashboard:** https://nyc311-dashboard-526972029302.us-central1.run.app

---

## 1. The question and the pairing

**311 × daily weather.** 311 is a high-volume behavioral signal (what residents complain
about, when, where); weather is a clean, exogenous daily driver that nobody in the city
controls. That makes a sharp, testable question possible — *which complaint types move with
weather, and by how much* — without needing a third dataset. We deliberately kept scope to
two sources so the join, the grain, and the caveats stay legible.

## 2. Grain and the definition of "day"

- **Raw grain = one row per `unique_key`** (one service request), the natural primary key.
- **"Day" = the local NYC calendar date of `created_date`.** Socrata returns `created_date`
  as a floating (offset-less) wall-clock timestamp already in America/New_York, so we take
  its date part directly — **no timezone conversion**. Converting to UTC would push
  late-night complaints into the wrong weather day; weather is reported per local calendar
  day and residents experience it locally. This is the single most important modeling
  decision, because it defines the key we join weather on.
- **Analysis grain = `complaint_date × complaint_type × borough`** with a count and the
  day's weather attached — small enough to serve interactively, rich enough for the
  question.

## 3. Schema: keep a stable core, drop the drift

The SODA feed has 40+ columns with heavy sparsity and drift. We **keep a typed core**
(keys, dates, `complaint_type`, `descriptor`, `agency`, `borough`, zip, lat/long, status,
channel) and **drop** address/routing/request-type-specific fields from the analysis layer.
Those are near-empty across most complaint types, irrelevant to a day×type×borough product,
and the biggest source of schema churn.

**Field-drift strategy — store raw, type late.** The ingester enforces **no column list on
read**: it lands the *full source record as a JSON column*. The clean view then `SAFE`-casts
and selects only the core columns via `JSON_VALUE`. Consequence: a new/renamed/removed
source field can never break ingestion — it only surfaces if we choose to promote it. This
is why every backfill and reload succeeded without a schema migration.

## 4. Pipeline shape

```
Socrata → GCS (raw JSON) → nyc311_raw.requests_raw → nyc311.requests_clean (view) → nyc311.daily_complaints (table)
```

- **Raw table = append-only landing**, full payload + ingest metadata. No dedup here, so we
  never lose provenance.
- **Clean = a VIEW, not a table.** It always reflects the latest raw load, dedups on
  `unique_key` (latest `_ingested_at` wins), and derives `complaint_date` + normalized
  `borough`. A view (vs. materialization) means zero staleness and one less thing to
  schedule; the daily aggregate is where we pay for materialization.
- **`daily_complaints` = materialized table.** It's what the dashboard and analysis hit, so
  it should be fast and stable; it's cheap to `CREATE OR REPLACE`.
- **`LEFT JOIN` to weather**, never inner: a complaint day is never dropped for missing
  weather. Missing weather surfaces as NULL and a `has_weather` flag, and is *reported* by
  verification rather than silently deleting rows.

**Weather columns are pinned, but drift-guarded.** Unlike the volatile 311 feed, the weather
mart is a controlled internal table, so we pin its metrics by name for clarity in Part 2.
`build_marts.py` intersects the desired metric list with the table's *live* schema and drops
(with a warning) anything renamed — so a weather change degrades instead of hard-failing.
The weather **date column is auto-discovered** from the schema at build time, because we hold
only table-level read on `nyu-datasets.weather` and can't assume a column name.

**Calendar fields come from `complaint_date`, not the weather join** (`year/month/day/
day_of_week/is_weekend/season`). If we inherited them from the joined weather row they'd be
NULL on any weather-missing day — and Part 2's season/day-of-week controls must always be
populated. Small decision, real correctness impact.

## 5. Idempotency, pagination, rate limits

- **Window-idempotent loads:** each run overwrites its GCS prefix and does `DELETE … WHERE
  _pull_window` then append — re-running a window can't duplicate rows.
- **Pagination by month + `$limit`/`$offset`** bounds offset depth (a month is ~250k rows,
  so offsets stay shallow), which is stable and avoids deep-offset cost over ~10M rows.
- **Backoff with jitter on 429/5xx**; the app token is optional (raises the ceiling) and
  ingestion must — and did — succeed without it. The full 2023–2025 backfill pulled
  **10,336,524** rows this way.

## 6. Verification: hard vs soft, and labeling the unverified

Every load self-checks. **Hard checks fail the workflow** (uniqueness of `unique_key`,
no missing calendar days, plausible ranges for dates/bbox/borough/counts). **Soft checks are
reported** (row-count reconciliation vs Socrata's own `count(1)`; weather-join coverage),
because they depend on upstream timing/ownership we don't control. On the full backfill:
reconciliation matched to **−2 rows (0.00%)**, zero duplicate keys, zero missing days,
100% weather coverage. Anything asserted but not yet checked in code is labeled
**UNVERIFIED** until a check exists — including, right now, the browser-load of the live
dashboard (the deploy is healthy and public, but this build environment's network policy
blocks outbound to `*.run.app`, so final confirmation is a human opening the URL).

## 7. Analysis method (Part 2)

- **Adjusted, not raw.** For each complaint type × weather condition we compute a
  **direct-standardized rate ratio** across `season × is_weekend` strata — comparing
  condition vs non-condition days *within* strata, then combining. This removes the
  "it's just summer / just a weekday" confounds by construction. On synthetic data the
  estimator recovered a planted +40/day effect as +40.5 adjusted while the naive difference
  read +60.7 — evidence the adjustment does real work.
- **Hold-out validation.** Every effect is fit on 2023–24 and required to replicate in
  direction on 2025. Humidity effects and several weak binary effects **failed** and were
  **discarded** — we report what survives, not what we hoped for.
- **Honesty over the hypothesis.** The prompt's "heat → HEAT/HOT WATER" is *backwards*
  (it's a cold complaint, −0.63 temp corr); "heat → noise" is *type-specific* (street noise
  up, residential down). Reported straight. Rain → Sewer was **confirmed** only after adding
  sewer/flood types below the top-15.
- **Low-volume noise flagged, not hidden.** Sub-1k/day flood types show huge % swings off
  tiny baselines and fail the hold-out — excluded with a note.
- **Correlation ≠ causation, stated up front.** We control season and weekday only; weather
  still co-varies with daylight, holidays, time outdoors, and reporting propensity. Nothing
  here is a causal estimate.

## 8. Dashboard (Part 3)

- **Live BigQuery with caching**, chosen over a baked static extract. Rationale: the numbers
  stay fresh as the pipeline reloads, and cost/abuse risk on a public `--allow-unauthenticated`
  app is contained by `st.cache_data` TTLs (BQ is hit at most once per slice per hour) plus
  **pre-aggregated, parameterized** queries (tiny payloads, no injection). Static would be
  cheaper still but goes stale and decouples the app from the product it showcases.
- **One claim per chart.** Each section header is a single plain-language, hold-out-validated
  sentence; the chart shows the live supporting data; a footer states the source and
  "association, not causation."
- **Cloud Run + WIF, no keys.** Deployed via Workload Identity Federation (no service-account
  JSON anywhere). The service *runs as* the pipeline SA so it can read BigQuery; it scales to
  zero. The one deploy snag was that `gcloud run deploy --source` builds as the Compute
  Engine default SA, which lacked Storage read on the build-staging bucket — fixed by
  pointing the build at our SA with `--build-service-account`, no IAM-admin change needed.

## 9. Cloud hygiene

Everything is **new and dedicated** — bucket `…-nyc311-raw`, datasets `nyc311_raw` /
`nyc311`, Cloud Run service `nyc311-dashboard` — reusing the existing project and SA without
touching the existing Citibike objects. BigQuery location is **US** everywhere so the
cross-dataset join to `nyu-datasets` works.

## 10. What we'd do next

- Promote a couple of dropped columns (e.g. `resolution_description`) if a question needs them.
- Test lag effects (does rain drive Sewer complaints *the next day* too?) and per-borough
  heterogeneity as a stronger robustness slice.
- Schedule the pipeline (incremental daily window) instead of manual dispatch.
- Add a bot-rate limit / lightweight cache warmer if the public dashboard sees real traffic.
