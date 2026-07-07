"""Build the clean view and the analysis-ready daily table.

  requests_raw  --(sql/01)-->  nyc311.requests_clean (view)
  requests_clean --(sql/02)--> nyc311.daily_complaints (table, weather-joined)

The weather table's schema is discovered at build time (we only have table-level
read access), so the join adapts to whatever the date column is actually called
and the pinned metric list degrades gracefully if a column is renamed upstream.
"""
from __future__ import annotations

import os

from google.cloud import bigquery

import common

SQL_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "sql")

# Preference order for identifying the weather date column when several exist.
DATE_TYPES = ("DATE", "DATETIME", "TIMESTAMP")

# Weather metrics we pin into daily_complaints, in display order (CLAUDE.md §3).
# Calendar helpers (year/month/day/day_of_week/is_weekend/season) are intentionally
# NOT listed here: sql/02 derives them from complaint_date so they are never NULL
# on a weather-missing day. Any name here that is absent from the table is dropped
# with a warning, so an upstream rename degrades instead of hard-failing the build.
WEATHER_METRICS = [
    "tmin_f", "tmax_f", "tavg_f",
    "prcp_inches", "snow_inches", "snow_depth_inches",
    "is_rainy", "is_snowy", "is_hot_day", "is_freezing",
    "rh_avg", "rh_min", "rh_max", "is_humid",
    "dewpoint_f", "wetbulb_f",
    "sea_level_pressure_hpa",
    "wind_avg_mph", "wind_gust_mph", "wind_dir_deg",
    "is_foggy", "is_thunder", "is_hazy",
]


def read_sql(name: str) -> str:
    with open(os.path.join(SQL_DIR, name), "r", encoding="utf-8") as f:
        return f.read()


def run(bq: bigquery.Client, sql: str) -> None:
    bq.query(sql).result()


def discover_weather_date_col(bq: bigquery.Client) -> str:
    table = bq.get_table(common.WEATHER_TABLE)
    fields = [(f.name, f.field_type) for f in table.schema]
    date_like = [(n, t) for n, t in fields if t in DATE_TYPES]
    if not date_like:
        raise SystemExit(
            f"No DATE/DATETIME/TIMESTAMP column found in {common.WEATHER_TABLE}; "
            f"columns: {fields}"
        )
    # Prefer a column named like a date, then by type preference, then first seen.
    date_like.sort(
        key=lambda nt: (
            0 if "date" in nt[0].lower() else 1,
            DATE_TYPES.index(nt[1]),
        )
    )
    chosen = date_like[0][0]
    print(f"weather date column: {chosen} (candidates: {date_like})")
    return chosen


def build_weather_cols(bq: bigquery.Client) -> str:
    """Return the pinned weather metrics that actually exist, as a SELECT fragment."""
    present = {f.name for f in bq.get_table(common.WEATHER_TABLE).schema}
    cols = [c for c in WEATHER_METRICS if c in present]
    missing = [c for c in WEATHER_METRICS if c not in present]
    if missing:
        print(f"WARN: pinned weather metrics not in table, dropped: {missing}")
    if not cols:
        raise SystemExit("No pinned weather metrics found in the weather table.")
    print(f"pinned {len(cols)} weather metrics")
    return ",\n  ".join(f"w.`{c}`" for c in cols)


def main() -> None:
    cfg = common.load_config()
    bq = bigquery.Client(project=cfg.project, location=cfg.location)

    bq.create_dataset(bigquery.Dataset(f"{cfg.project}.{cfg.dataset}"), exists_ok=True)

    print("Building nyc311.requests_clean ...")
    run(bq, read_sql("01_requests_clean.sql").replace("{{PROJECT}}", cfg.project))

    wdate = discover_weather_date_col(bq)
    weather_cols = build_weather_cols(bq)
    print("Building nyc311.daily_complaints ...")
    sql = (
        read_sql("02_daily_complaints.sql")
        .replace("{{PROJECT}}", cfg.project)
        .replace("{{WEATHER}}", common.WEATHER_TABLE)
        .replace("{{WDATE}}", wdate)
        .replace("{{WEATHER_COLS}}", weather_cols)
    )
    run(bq, sql)

    clean = f"{cfg.project}.{cfg.dataset}.requests_clean"
    daily = f"{cfg.project}.{cfg.dataset}.daily_complaints"
    n_clean = list(bq.query(f"SELECT COUNT(*) c FROM `{clean}`").result())[0].c
    n_daily = bq.get_table(daily).num_rows
    print(f"requests_clean rows: {n_clean:,}")
    print(f"daily_complaints rows: {n_daily:,}")


if __name__ == "__main__":
    main()
