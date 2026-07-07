-- Clean, typed, deduplicated view over the raw landing table.
-- See CLAUDE.md §3 (keep/drop/derive) and §4 (layers).
--   * dedup on unique_key, latest _ingested_at wins
--   * SAFE parsing so one bad value never breaks the view
--   * created_date kept as a local (floating) DATETIME; no timezone conversion
--   * complaint_date = local NYC calendar date of created_date (the weather join key)
--   * borough normalized to a fixed set
-- {{PROJECT}} is substituted by pipeline/build_marts.py.
CREATE OR REPLACE VIEW `{{PROJECT}}.nyc311.requests_clean` AS
WITH ranked AS (
  SELECT
    data,
    ROW_NUMBER() OVER (
      PARTITION BY SAFE_CAST(JSON_VALUE(data, '$.unique_key') AS INT64)
      ORDER BY _ingested_at DESC
    ) AS _rn
  FROM `{{PROJECT}}.nyc311_raw.requests_raw`
  WHERE SAFE_CAST(JSON_VALUE(data, '$.unique_key') AS INT64) IS NOT NULL
),
parsed AS (
  SELECT
    SAFE_CAST(JSON_VALUE(data, '$.unique_key') AS INT64) AS unique_key,
    COALESCE(
      SAFE.PARSE_DATETIME('%Y-%m-%dT%H:%M:%E*S', JSON_VALUE(data, '$.created_date')),
      SAFE.PARSE_DATETIME('%Y-%m-%d %H:%M:%E*S', JSON_VALUE(data, '$.created_date'))
    ) AS created_date,
    COALESCE(
      SAFE.PARSE_DATETIME('%Y-%m-%dT%H:%M:%E*S', JSON_VALUE(data, '$.closed_date')),
      SAFE.PARSE_DATETIME('%Y-%m-%d %H:%M:%E*S', JSON_VALUE(data, '$.closed_date'))
    ) AS closed_date,
    JSON_VALUE(data, '$.complaint_type') AS complaint_type,
    JSON_VALUE(data, '$.descriptor')     AS descriptor,
    JSON_VALUE(data, '$.agency')         AS agency,
    UPPER(TRIM(COALESCE(JSON_VALUE(data, '$.borough'), ''))) AS borough_raw,
    JSON_VALUE(data, '$.incident_zip')   AS incident_zip,
    SAFE_CAST(JSON_VALUE(data, '$.latitude')  AS FLOAT64) AS latitude,
    SAFE_CAST(JSON_VALUE(data, '$.longitude') AS FLOAT64) AS longitude,
    JSON_VALUE(data, '$.status')                  AS status,
    JSON_VALUE(data, '$.open_data_channel_type')  AS open_data_channel_type
  FROM ranked
  WHERE _rn = 1
)
SELECT
  unique_key,
  created_date,
  DATE(created_date) AS complaint_date,
  closed_date,
  complaint_type,
  descriptor,
  agency,
  CASE
    WHEN borough_raw IN ('MANHATTAN', 'BRONX', 'BROOKLYN', 'QUEENS', 'STATEN ISLAND')
      THEN borough_raw
    ELSE 'UNSPECIFIED'
  END AS borough,
  incident_zip,
  latitude,
  longitude,
  status,
  open_data_channel_type
FROM parsed;
