"""Shared config and helpers for the NYC 311 pipeline.

All settings come from environment variables with defaults that match the
decisions recorded in CLAUDE.md. Nothing here is secret; the optional Socrata
app token is read from SODA_APP_TOKEN only if present.
"""
from __future__ import annotations

import os
import sys
import time
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import requests

SODA_URL = "https://data.cityofnewyork.us/resource/erm2-nwe9.json"
WEATHER_TABLE = "nyu-datasets.weather.m_weather_daily_nyc"

# NYC bounding box, used for plausibility checks on lat/long.
NYC_LAT = (40.40, 40.95)
NYC_LON = (-74.30, -73.65)

VALID_BOROUGHS = {
    "MANHATTAN",
    "BRONX",
    "BROOKLYN",
    "QUEENS",
    "STATEN ISLAND",
    "UNSPECIFIED",
}


@dataclass(frozen=True)
class Config:
    project: str
    gcs_bucket: str
    dataset_raw: str
    dataset: str
    location: str
    start_date: date
    end_date: date  # inclusive
    page_size: int
    app_token: str | None

    @property
    def pull_window(self) -> str:
        return f"{self.start_date.isoformat()}_{self.end_date.isoformat()}"

    @property
    def end_exclusive(self) -> date:
        return self.end_date + timedelta(days=1)

    @property
    def raw_table(self) -> str:
        return f"{self.project}.{self.dataset_raw}.requests_raw"


def _env(name: str, default: str | None = None, required: bool = False) -> str | None:
    val = os.environ.get(name, default)
    if required and not val:
        sys.exit(f"ERROR: required environment variable {name} is not set")
    return val


def load_config() -> Config:
    return Config(
        project=_env("GCP_PROJECT", "msbai-dwd-lx2433"),
        gcs_bucket=_env("GCS_BUCKET", "msbai-dwd-lx2433-nyc311-raw"),
        dataset_raw=_env("BQ_DATASET_RAW", "nyc311_raw"),
        dataset=_env("BQ_DATASET", "nyc311"),
        location=_env("BQ_LOCATION", "US"),
        start_date=date.fromisoformat(_env("START_DATE", "2023-01-01")),
        end_date=date.fromisoformat(_env("END_DATE", "2025-12-31")),
        page_size=int(_env("PAGE_SIZE", "50000")),
        app_token=os.environ.get("SODA_APP_TOKEN") or None,
    )


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def month_windows(start: date, end_exclusive: date):
    """Yield (month_start, next_month_start) covering [start, end_exclusive)."""
    cur = date(start.year, start.month, 1)
    if cur < start:
        cur = start
    while cur < end_exclusive:
        if cur.month == 12:
            nxt = date(cur.year + 1, 1, 1)
        else:
            nxt = date(cur.year, cur.month + 1, 1)
        yield cur, min(nxt, end_exclusive)
        cur = nxt


def soda_headers(cfg: Config) -> dict:
    return {"X-App-Token": cfg.app_token} if cfg.app_token else {}


def soda_get(cfg: Config, params: dict, max_retries: int = 6) -> list[dict]:
    """GET the SODA endpoint with exponential backoff + jitter on 429/5xx."""
    delay = 2.0
    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.get(
                SODA_URL, params=params, headers=soda_headers(cfg), timeout=120
            )
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 429 or resp.status_code >= 500:
                last_err = f"HTTP {resp.status_code}"
            else:
                resp.raise_for_status()
                return resp.json()
        except requests.RequestException as e:  # connection/timeout
            last_err = str(e)
        sleep = min(delay, 60.0) + random.uniform(0, 1.0)
        print(f"  retry {attempt}/{max_retries} after {last_err}; sleeping {sleep:.1f}s")
        time.sleep(sleep)
        delay *= 2
    sys.exit(f"ERROR: SODA request failed after {max_retries} retries: {last_err}")


def soda_count(cfg: Config, where: str) -> int:
    rows = soda_get(cfg, {"$select": "count(1)", "$where": where})
    if not rows:
        return 0
    # Column name is typically "count_1"; take the sole value defensively.
    return int(next(iter(rows[0].values())))
