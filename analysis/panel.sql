-- Part 2 analysis panel: a zero-filled daily citywide series for the highest-volume
-- 311 complaint types, joined to that day's weather + calendar attributes.
--
-- Zero-fill matters: a (day, type) with no complaints has no row in daily_complaints,
-- and dropping those days would bias means upward. We build a full calendar x type
-- grid and coalesce missing counts to 0.
--
-- {{PROJECT}} and {{TOPN}} are substituted by analysis/analyze.py.
WITH top_types AS (
  SELECT complaint_type
  FROM `{{PROJECT}}.nyc311.daily_complaints`
  GROUP BY complaint_type
  ORDER BY SUM(complaint_count) DESC
  LIMIT {{TOPN}}
),
-- Extra explicitly-requested types (e.g. Sewer / flooding) that fall below TOPN.
extra_types AS (
  SELECT ct AS complaint_type FROM UNNEST(ARRAY<STRING>[{{EXTRA_TYPES}}]) AS ct
),
sel_types AS (
  SELECT complaint_type FROM top_types
  UNION DISTINCT
  SELECT complaint_type FROM extra_types
),
cal AS (
  SELECT d AS complaint_date
  FROM UNNEST(GENERATE_DATE_ARRAY(DATE '2023-01-01', DATE '2025-12-31')) AS d
),
grid AS (
  SELECT c.complaint_date, t.complaint_type
  FROM cal c CROSS JOIN sel_types t
),
-- Aggregate all types once; the grid join below restricts to sel_types. (We do
-- NOT filter here with `IN (SELECT ... FROM sel_types)`: because sel_types is a
-- UNION of a table-derived CTE and an UNNEST, BigQuery cannot de-correlate that
-- IN-subquery and errors out.)
counts AS (
  SELECT complaint_date, complaint_type, SUM(complaint_count) AS cnt
  FROM `{{PROJECT}}.nyc311.daily_complaints`
  GROUP BY complaint_date, complaint_type
),
-- One weather/calendar row per calendar day (identical across type/borough).
wx AS (
  SELECT
    complaint_date,
    ANY_VALUE(year) AS year,
    ANY_VALUE(season) AS season,
    ANY_VALUE(is_weekend) AS is_weekend,
    ANY_VALUE(day_of_week) AS day_of_week,
    ANY_VALUE(tavg_f) AS tavg_f,
    ANY_VALUE(tmax_f) AS tmax_f,
    ANY_VALUE(tmin_f) AS tmin_f,
    ANY_VALUE(is_hot_day) AS is_hot_day,
    ANY_VALUE(is_freezing) AS is_freezing,
    ANY_VALUE(prcp_inches) AS prcp_inches,
    ANY_VALUE(is_rainy) AS is_rainy,
    ANY_VALUE(snow_inches) AS snow_inches,
    ANY_VALUE(is_snowy) AS is_snowy,
    ANY_VALUE(is_humid) AS is_humid,
    ANY_VALUE(has_weather) AS has_weather
  FROM `{{PROJECT}}.nyc311.daily_complaints`
  GROUP BY complaint_date
)
SELECT
  g.complaint_date,
  g.complaint_type,
  IFNULL(co.cnt, 0) AS cnt,
  wx.year, wx.season, wx.is_weekend, wx.day_of_week,
  wx.tavg_f, wx.tmax_f, wx.tmin_f,
  wx.is_hot_day, wx.is_freezing,
  wx.prcp_inches, wx.is_rainy,
  wx.snow_inches, wx.is_snowy,
  wx.is_humid, wx.has_weather
FROM grid g
LEFT JOIN counts co USING (complaint_date, complaint_type)
LEFT JOIN wx USING (complaint_date)
ORDER BY g.complaint_type, g.complaint_date;
