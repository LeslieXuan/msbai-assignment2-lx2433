-- Analysis-ready daily table: complaint volume by day x complaint_type x borough,
-- LEFT JOINed to NYC daily weather on local calendar date. See CLAUDE.md §2, §3, §4.
--
-- Calendar fields (year/month/day/day_of_week/is_weekend/season) are derived from
-- complaint_date, NOT taken from the weather join, so they are never NULL on a day
-- that happens to be missing weather. Weather *metrics* come from the join and are
-- NULL when no weather row exists (surfaced by has_weather and the coverage check).
--
-- LEFT JOIN so a complaint day is never dropped for missing weather.
--
-- Rendered by pipeline/build_marts.py, which substitutes the project id, the
-- weather table, its auto-discovered date column, and the pinned weather metric
-- list. (Placeholder tokens are intentionally not spelled out here: the metric
-- list is multi-line, and naming the token in a comment would let the blind
-- string-replace expand it inside this comment and break the query.)
CREATE OR REPLACE TABLE `{{PROJECT}}.nyc311.daily_complaints` AS
WITH agg AS (
  SELECT
    complaint_date,
    complaint_type,
    borough,
    COUNT(*) AS complaint_count
  FROM `{{PROJECT}}.nyc311.requests_clean`
  WHERE complaint_date IS NOT NULL
  GROUP BY complaint_date, complaint_type, borough
)
SELECT
  a.complaint_date,
  a.complaint_type,
  a.borough,
  a.complaint_count,
  -- Calendar attributes derived from complaint_date (BQ DAYOFWEEK: 1=Sun..7=Sat).
  EXTRACT(YEAR  FROM a.complaint_date) AS year,
  EXTRACT(MONTH FROM a.complaint_date) AS month,
  EXTRACT(DAY   FROM a.complaint_date) AS day,
  EXTRACT(DAYOFWEEK FROM a.complaint_date) AS day_of_week,
  EXTRACT(DAYOFWEEK FROM a.complaint_date) IN (1, 7) AS is_weekend,
  CASE
    WHEN EXTRACT(MONTH FROM a.complaint_date) IN (12, 1, 2) THEN 'Winter'
    WHEN EXTRACT(MONTH FROM a.complaint_date) IN (3, 4, 5)  THEN 'Spring'
    WHEN EXTRACT(MONTH FROM a.complaint_date) IN (6, 7, 8)  THEN 'Summer'
    ELSE 'Fall'
  END AS season,
  -- Pinned weather metrics (see CLAUDE.md §3 weather-schema table).
  {{WEATHER_COLS}},
  (w.`{{WDATE}}` IS NOT NULL) AS has_weather
FROM agg a
LEFT JOIN `{{WEATHER}}` w
  ON a.complaint_date = CAST(w.`{{WDATE}}` AS DATE);
