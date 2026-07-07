# msbai-assignment2-lx2433
DDP assignment 2 — **NYC 311 complaints × NYC weather** data product.

See [`CLAUDE.md`](CLAUDE.md) for the full specification (Specify decisions).

## Part 1 — Load pipeline

```
Socrata SODA API (erm2-nwe9)
   └─ pipeline/ingest_311.py ─► GCS gs://msbai-dwd-lx2433-nyc311-raw
                              ─► BQ  nyc311_raw.requests_raw   (full raw JSON)
   └─ pipeline/build_marts.py ─► BQ  nyc311.requests_clean     (typed, deduped view)
                              ─► BQ  nyc311.daily_complaints   (day × type × borough + weather)
   └─ pipeline/verify.py      ─► reconciliation + invariant checks
```

### Run in CI
Trigger the **nyc311-pipeline** workflow (`.github/workflows/pipeline.yml`) via
*Actions → Run workflow*, choosing the date window. It authenticates to GCP with
Workload Identity Federation (no keys) and runs ingest → build → verify.

### Run locally
Requires application-default credentials able to impersonate the pipeline SA.

```bash
pip install -r pipeline/requirements.txt
export START_DATE=2023-01-01 END_DATE=2023-01-31   # small window to smoke-test
python pipeline/ingest_311.py
python pipeline/build_marts.py
python pipeline/verify.py
```

Config is env-driven (defaults in `pipeline/common.py`): `GCP_PROJECT`, `GCS_BUCKET`,
`BQ_DATASET_RAW`, `BQ_DATASET`, `BQ_LOCATION`, `START_DATE`, `END_DATE`, `PAGE_SIZE`,
and optional `SODA_APP_TOKEN`.
