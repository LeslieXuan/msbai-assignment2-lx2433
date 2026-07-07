"""Ingest NYC 311 service requests from the Socrata SODA API into BigQuery.

Flow (see CLAUDE.md §4):
  Socrata -> newline-delimited JSON in GCS -> BigQuery nyc311_raw.requests_raw

- Bounded to [START_DATE, END_DATE] on created_date.
- Paginated by month window + $limit/$offset (bounds offset depth).
- Full source record kept in a JSON column `data`; ingestion never enforces a
  column list, so source field drift cannot break the load.
- Window-idempotent: re-running a window overwrites its GCS objects and replaces
  its rows in the raw table (DELETE by _pull_window, then append).
"""
from __future__ import annotations

import io
import json

from google.cloud import bigquery, storage

import common


def fetch_window(cfg: common.Config, month_start, month_end_excl) -> list[dict]:
    """Fetch every 311 row created in [month_start, month_end_excl)."""
    where = (
        f"created_date >= '{month_start.isoformat()}T00:00:00' "
        f"AND created_date < '{month_end_excl.isoformat()}T00:00:00'"
    )
    rows: list[dict] = []
    offset = 0
    while True:
        page = common.soda_get(
            cfg,
            {
                "$where": where,
                "$order": "created_date",
                "$limit": cfg.page_size,
                "$offset": offset,
            },
        )
        rows.extend(page)
        print(f"  {month_start} offset={offset} got={len(page)} total={len(rows)}")
        if len(page) < cfg.page_size:
            break
        offset += cfg.page_size
    return rows


def to_ndjson(rows: list[dict], ingested_at: str, pull_window: str, base_offset: int) -> bytes:
    buf = io.StringIO()
    for i, r in enumerate(rows):
        line = {
            "unique_key": r.get("unique_key"),
            "data": r,  # full source record, loaded into a JSON column
            "_ingested_at": ingested_at,
            "_pull_window": pull_window,
            "_source_offset": base_offset + i,
        }
        buf.write(json.dumps(line, ensure_ascii=False))
        buf.write("\n")
    return buf.getvalue().encode("utf-8")


def ensure_bucket(cfg: common.Config, sc: storage.Client) -> storage.Bucket:
    bucket = sc.bucket(cfg.gcs_bucket)
    if not bucket.exists():
        bucket = sc.create_bucket(cfg.gcs_bucket, location=cfg.location)
        print(f"created bucket gs://{cfg.gcs_bucket}")
    return bucket


def ensure_raw_table(cfg: common.Config, bq: bigquery.Client) -> None:
    bq.create_dataset(
        bigquery.Dataset(f"{cfg.project}.{cfg.dataset_raw}"), exists_ok=True
    )
    schema = [
        bigquery.SchemaField("unique_key", "STRING"),
        bigquery.SchemaField("data", "JSON"),
        bigquery.SchemaField("_ingested_at", "TIMESTAMP"),
        bigquery.SchemaField("_pull_window", "STRING"),
        bigquery.SchemaField("_source_offset", "INT64"),
    ]
    table = bigquery.Table(cfg.raw_table, schema=schema)
    table.time_partitioning = bigquery.TimePartitioning(field="_ingested_at")
    bq.create_table(table, exists_ok=True)


def main() -> None:
    cfg = common.load_config()
    ingested_at = common.now_utc_iso()
    print(f"Ingesting window {cfg.pull_window} (page_size={cfg.page_size}, "
          f"app_token={'yes' if cfg.app_token else 'no'})")

    sc = storage.Client(project=cfg.project)
    bq = bigquery.Client(project=cfg.project, location=cfg.location)
    bucket = ensure_bucket(cfg, sc)
    ensure_raw_table(cfg, bq)

    prefix = f"raw/pull_window={cfg.pull_window}"
    gcs_uris: list[str] = []
    total_rows = 0

    for m_start, m_end in common.month_windows(cfg.start_date, cfg.end_exclusive):
        rows = fetch_window(cfg, m_start, m_end)
        if not rows:
            continue
        payload = to_ndjson(rows, ingested_at, cfg.pull_window, total_rows)
        blob_name = f"{prefix}/created_month={m_start.isoformat()}/part-000.json"
        bucket.blob(blob_name).upload_from_string(
            payload, content_type="application/json"
        )
        gcs_uris.append(f"gs://{cfg.gcs_bucket}/{blob_name}")
        total_rows += len(rows)

    print(f"Fetched {total_rows} rows across {len(gcs_uris)} monthly objects")
    if total_rows == 0:
        print("No rows fetched; nothing to load.")
        return

    # Window-idempotent replace: drop any prior rows for this pull window.
    bq.query(
        f"DELETE FROM `{cfg.raw_table}` WHERE _pull_window = @w",
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("w", "STRING", cfg.pull_window)
            ]
        ),
    ).result()

    load_cfg = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        schema=[
            bigquery.SchemaField("unique_key", "STRING"),
            bigquery.SchemaField("data", "JSON"),
            bigquery.SchemaField("_ingested_at", "TIMESTAMP"),
            bigquery.SchemaField("_pull_window", "STRING"),
            bigquery.SchemaField("_source_offset", "INT64"),
        ],
    )
    load = bq.load_table_from_uri(
        f"gs://{cfg.gcs_bucket}/{prefix}/*", cfg.raw_table, job_config=load_cfg
    )
    load.result()
    dest = bq.get_table(cfg.raw_table)
    print(f"Loaded window into {cfg.raw_table}; table now has {dest.num_rows} rows")


if __name__ == "__main__":
    main()
