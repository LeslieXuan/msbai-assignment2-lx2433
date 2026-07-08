# VERIFICATION.md — evidence the data is trustworthy

Committed evidence for the Part 1 load. The checks live in `pipeline/verify.py`
and run as the last step of the **nyc311-pipeline** GitHub Actions workflow; the
output below is copied verbatim from the workflow log. Hard checks fail the build;
soft checks are reported (they depend on upstream timing/ownership we don't own).

## Latest full-window verification (2023-01-01 … 2025-12-31)

Source of this output: `nyc311-pipeline` run over the full window on the pinned
schema (ingest of 10,336,524 rows → clean view → `daily_complaints`).

```
=== Verification for window 2023-01-01_2025-12-31 ===

[1] Row-count reconciliation (soft)
    socrata=10,336,526 loaded=10,336,524 delta=-2 (0.00%)

[2] unique_key uniqueness (HARD)
    duplicate unique_keys in clean view: 0

[3] No missing days (HARD)
    missing calendar days in daily_complaints: 0

[4] Plausible ranges (HARD)
    out_of_window=0 bad_lat=0 bad_lon=0 bad_borough=0 nonpositive_counts=0

[5] Weather-join coverage (soft)
    days with weather: 1096/1096 (100.00%)
    rows with weather: 492512/492512 (100.00%)

=== Summary ===
  All hard checks passed.
```

## What each check proves (see CLAUDE.md §6)

| # | Check | Type | Result | What it rules out |
|---|---|---|---|---|
| 1 | Reconcile loaded rows vs Socrata's own `count(1)` for the same `created_date` window | soft | −2 rows (0.00%) | Missed pages / duplicated pulls. Two rows are within tolerance (see note). |
| 2 | `unique_key` has zero duplicates in the clean view | HARD | 0 | Fan-out from a bad join or dedup; double-loading |
| 3 | Every calendar day in the window appears in `daily_complaints` | HARD | 0 missing (1,096/1,096) | A silently dropped ingestion window (a zero-complaint NYC day is implausible) |
| 4 | `complaint_date` in window; lat/long in NYC bbox or NULL; borough in the allowed set; counts ≥ 1 | HARD | all 0 | Type/parse corruption, out-of-range coordinates, bad borough normalization |
| 5 | Fraction of `daily_complaints` days/rows with a matched weather row | soft | 100% / 100% | Broken join key (local-date mismatch) |

**The −2 reconciliation delta:** loaded is two rows below Socrata's live count for
the window. Expected causes: the source can gain/rename rows between the count call
and the pull, and the clean view drops any record whose `unique_key` fails
`SAFE_CAST` to INT64. Two rows out of 10.3M (0.00%) is well inside tolerance and is
reported, not hidden.

## Reproduce

Run the **nyc311-pipeline** workflow (Actions → Run workflow), or, on already-loaded
raw data, run it with `skip_ingest: true` to rebuild the marts and re-run every
check. The verifier re-queries BigQuery live, so the numbers above are reproducible
against `msbai-dwd-lx2433.nyc311.*`.
