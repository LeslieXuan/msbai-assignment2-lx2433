-- Analysis-ready daily table: complaint volume by day x complaint_type x borough,
-- LEFT JOINed to NYC daily weather on local calendar date. See CLAUDE.md §2, §4.
--
-- LEFT JOIN so a complaint day is never dropped for missing weather; missing
-- weather surfaces as NULL and is reported by the verification step.
--
-- Placeholders substituted by pipeline/build_marts.py:
--   {{PROJECT}}   -> GCP project id
--   {{WDATE}}     -> the weather table's date column (discovered from its schema)
--   {{WEATHER}}   -> fully-qualified weather table
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
  a.*,
  w.* EXCEPT (`{{WDATE}}`)
FROM agg a
LEFT JOIN `{{WEATHER}}` w
  ON a.complaint_date = CAST(w.`{{WDATE}}` AS DATE);
