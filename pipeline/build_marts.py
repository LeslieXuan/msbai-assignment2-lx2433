"""Build the clean view and the analysis-ready daily table.

  requests_raw  --(sql/01)-->  nyc311.requests_clean (view)
  requests_clean --(sql/02)--> nyc311.daily_complaints (table, weather-joined)

The weather table's schema is discovered at build time (we only have table-level
read access), so the join adapts to whatever the date column is actually called.
"""
from __future__ import annotations

import os

from google.cloud import bigquery

import common

SQL_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "sql")

# Preference order for identifying the weather date column when several exist.
DATE_TYPES = ("DATE", "DATETIME", "TIMESTAMP")


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


def main() -> None:
    cfg = common.load_config()
    bq = bigquery.Client(project=cfg.project, location=cfg.location)

    bq.create_dataset(bigquery.Dataset(f"{cfg.project}.{cfg.dataset}"), exists_ok=True)

    print("Building nyc311.requests_clean ...")
    run(bq, read_sql("01_requests_clean.sql").replace("{{PROJECT}}", cfg.project))

    wdate = discover_weather_date_col(bq)
    print("Building nyc311.daily_complaints ...")
    sql = (
        read_sql("02_daily_complaints.sql")
        .replace("{{PROJECT}}", cfg.project)
        .replace("{{WEATHER}}", common.WEATHER_TABLE)
        .replace("{{WDATE}}", wdate)
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
