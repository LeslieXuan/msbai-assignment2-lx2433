"""Verification for the NYC 311 pipeline (CLAUDE.md §6).

Hard checks fail the process (exit 1); soft checks are reported only.

  1. Row-count reconciliation vs Socrata's own count for the window  (soft: delta reported)
  2. unique_key uniqueness in the clean view                          (HARD)
  3. No missing days in daily_complaints across the window            (HARD)
  4. Plausible ranges (dates, lat/long bbox, borough set, counts)     (HARD)
  5. Weather-join coverage                                            (soft: reported)

Anything asserted but not checked here should be labeled UNVERIFIED in docs.
"""
from __future__ import annotations

import sys

from google.cloud import bigquery

import common
from build_marts import discover_weather_date_col

# Reconciliation tolerance: the source can gain rows between the count call and
# the pull, so a small positive drift is expected, not an error.
RECON_TOLERANCE = 0.01  # 1%


def scalar(bq, sql):
    return list(bq.query(sql).result())[0]


def main() -> None:
    cfg = common.load_config()
    bq = bigquery.Client(project=cfg.project, location=cfg.location)
    clean = f"`{cfg.project}.{cfg.dataset}.requests_clean`"
    daily = f"`{cfg.project}.{cfg.dataset}.daily_complaints`"
    start = cfg.start_date.isoformat()
    end_excl = cfg.end_exclusive.isoformat()

    failures: list[str] = []
    print(f"=== Verification for window {cfg.pull_window} ===\n")

    # 1. Reconciliation (soft) ------------------------------------------------
    where = (
        f"created_date >= '{start}T00:00:00' AND created_date < '{end_excl}T00:00:00'"
    )
    src = common.soda_count(cfg, where)
    loaded = scalar(
        bq,
        f"SELECT COUNT(*) c FROM {clean} "
        f"WHERE complaint_date >= '{start}' AND complaint_date < '{end_excl}'",
    ).c
    delta = loaded - src
    rel = abs(delta) / src if src else 0
    print("[1] Row-count reconciliation (soft)")
    print(f"    socrata={src:,} loaded={loaded:,} delta={delta:+,} ({rel:.2%})")
    if rel > RECON_TOLERANCE:
        print(f"    WARN: delta exceeds tolerance {RECON_TOLERANCE:.0%}")

    # 2. unique_key uniqueness (HARD) ----------------------------------------
    dups = scalar(
        bq,
        f"SELECT COUNT(*) c FROM ("
        f"  SELECT unique_key FROM {clean} GROUP BY unique_key HAVING COUNT(*) > 1)",
    ).c
    print("\n[2] unique_key uniqueness (HARD)")
    print(f"    duplicate unique_keys in clean view: {dups}")
    if dups > 0:
        failures.append(f"{dups} duplicate unique_keys in clean view")

    # 3. No missing days (HARD) ----------------------------------------------
    missing = list(
        bq.query(
            f"""
            WITH cal AS (
              SELECT d FROM UNNEST(
                GENERATE_DATE_ARRAY(DATE('{start}'),
                                    DATE_SUB(DATE('{end_excl}'), INTERVAL 1 DAY))
              ) d
            )
            SELECT d FROM cal
            WHERE d NOT IN (SELECT DISTINCT complaint_date FROM {daily})
            ORDER BY d
            """
        ).result()
    )
    print("\n[3] No missing days (HARD)")
    print(f"    missing calendar days in daily_complaints: {len(missing)}")
    if missing:
        sample = ", ".join(str(r.d) for r in missing[:10])
        print(f"    first missing: {sample}")
        failures.append(f"{len(missing)} missing days in daily_complaints")

    # 4. Plausible ranges (HARD) ---------------------------------------------
    lo_lat, hi_lat = common.NYC_LAT
    lo_lon, hi_lon = common.NYC_LON
    valid = ", ".join(f"'{b}'" for b in common.VALID_BOROUGHS)
    r = scalar(
        bq,
        f"""
        SELECT
          COUNTIF(complaint_date < '{start}' OR complaint_date >= '{end_excl}') AS out_of_window,
          COUNTIF(latitude IS NOT NULL AND (latitude < {lo_lat} OR latitude > {hi_lat})) AS bad_lat,
          COUNTIF(longitude IS NOT NULL AND (longitude < {lo_lon} OR longitude > {hi_lon})) AS bad_lon,
          COUNTIF(borough NOT IN ({valid})) AS bad_borough
        FROM {clean}
        """,
    )
    bad_count = scalar(bq, f"SELECT COUNTIF(complaint_count < 1) c FROM {daily}").c
    print("\n[4] Plausible ranges (HARD)")
    print(f"    out_of_window={r.out_of_window} bad_lat={r.bad_lat} "
          f"bad_lon={r.bad_lon} bad_borough={r.bad_borough} nonpositive_counts={bad_count}")
    for name, val in [
        ("out_of_window complaint_date", r.out_of_window),
        ("out_of_bbox latitude", r.bad_lat),
        ("out_of_bbox longitude", r.bad_lon),
        ("invalid borough", r.bad_borough),
        ("nonpositive complaint_count", bad_count),
    ]:
        if val:
            failures.append(f"{val} rows with {name}")

    # 5. Weather-join coverage (soft) ----------------------------------------
    wdate = discover_weather_date_col(bq)
    cov = scalar(
        bq,
        f"""
        WITH days AS (SELECT DISTINCT complaint_date FROM {daily}),
        wx AS (SELECT DISTINCT CAST(`{wdate}` AS DATE) d
               FROM `{common.WEATHER_TABLE}`)
        SELECT
          (SELECT COUNT(*) FROM days) AS total_days,
          (SELECT COUNT(*) FROM days d WHERE d.complaint_date IN (SELECT d FROM wx)) AS matched_days
        """,
    )
    frac = cov.matched_days / cov.total_days if cov.total_days else 0
    print("\n[5] Weather-join coverage (soft)")
    print(f"    days with weather: {cov.matched_days}/{cov.total_days} ({frac:.2%})")

    # Summary ----------------------------------------------------------------
    print("\n=== Summary ===")
    if failures:
        for f in failures:
            print(f"  HARD FAIL: {f}")
        sys.exit(1)
    print("  All hard checks passed.")


if __name__ == "__main__":
    main()
