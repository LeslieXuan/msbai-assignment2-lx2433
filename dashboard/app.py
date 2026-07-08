"""NYC 311 × Weather — public dashboard (Part 3).

Every chart carries one plain-language claim from analysis/FINDINGS.md. Data is
read LIVE from BigQuery (nyc311.daily_complaints) via the Cloud Run service
account, with st.cache_data TTLs so anonymous traffic doesn't re-query BQ per
load. Queries are pre-aggregated (GROUP BY in SQL) so cached payloads stay small.

The headline effect sizes in each claim are the season × weekday adjusted,
hold-out-validated numbers from Part 2; the charts show the live supporting data.
"""
from __future__ import annotations

import os

import pandas as pd
import plotly.express as px
import streamlit as st
from google.cloud import bigquery

PROJECT = os.environ.get("GCP_PROJECT", "msbai-dwd-lx2433")
LOCATION = os.environ.get("BQ_LOCATION", "US")
TABLE = f"`{PROJECT}.nyc311.daily_complaints`"
TTL = int(os.environ.get("CACHE_TTL_SECONDS", "3600"))

st.set_page_config(page_title="NYC 311 × Weather", page_icon="🌦️", layout="wide")


@st.cache_resource
def client() -> bigquery.Client:
    return bigquery.Client(project=PROJECT, location=LOCATION)


@st.cache_data(ttl=TTL, show_spinner=False)
def q(sql: str, params: tuple[tuple[str, str, str], ...] = ()) -> pd.DataFrame:
    cfg = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter(n, t, v) for n, t, v in params
    ]) if params else None
    return client().query(sql, job_config=cfg).result().to_dataframe()


@st.cache_data(ttl=TTL, show_spinner=False)
def daily_for(complaint_type: str) -> pd.DataFrame:
    sql = f"""
      SELECT complaint_date,
             SUM(complaint_count) AS cnt,
             ANY_VALUE(tavg_f) AS tavg_f,
             ANY_VALUE(is_freezing) AS is_freezing,
             ANY_VALUE(is_hot_day) AS is_hot_day,
             ANY_VALUE(is_rainy) AS is_rainy,
             ANY_VALUE(is_snowy) AS is_snowy
      FROM {TABLE}
      WHERE complaint_type = @t
      GROUP BY complaint_date
      ORDER BY complaint_date
    """
    df = q(sql, (("t", "STRING", complaint_type),))
    for c in ["is_freezing", "is_hot_day", "is_rainy", "is_snowy"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["tavg_f"] = pd.to_numeric(df["tavg_f"], errors="coerce")
    df["cnt"] = pd.to_numeric(df["cnt"], errors="coerce").fillna(0)
    return df


def cond_means(complaint_type: str, flag: str, labels: tuple[str, str]) -> pd.DataFrame:
    d = daily_for(complaint_type)
    d = d.dropna(subset=[flag])
    g = d.groupby(d[flag].astype(int))["cnt"].mean()
    return pd.DataFrame({
        "condition": [labels[0], labels[1]],
        "avg_daily": [g.get(0, float("nan")), g.get(1, float("nan"))],
    })


# ---- Header -----------------------------------------------------------------
st.title("🌦️ NYC 311 complaints × NYC weather")
st.caption(
    "Which 311 complaint types are weather-driven, and by how much — 2023–2025, "
    "citywide. Effect sizes below are adjusted for season and day-of-week and "
    "validated on a 2025 hold-out (see `analysis/FINDINGS.md`). "
    "Association, not causation."
)

try:
    overview = q(f"""
        SELECT COUNT(*) AS n_rows,
               SUM(complaint_count) AS complaints,
               MIN(complaint_date) AS d0, MAX(complaint_date) AS d1,
               COUNT(DISTINCT complaint_type) AS types
        FROM {TABLE}
    """).iloc[0]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Complaints", f"{int(overview.complaints):,}")
    c2.metric("Daily rows", f"{int(overview.n_rows):,}")
    c3.metric("Complaint types", f"{int(overview.types):,}")
    c4.metric("Window", f"{overview.d0} → {overview.d1}")
except Exception as e:  # pragma: no cover - surfaced in the UI
    st.error(f"Could not reach BigQuery: {e}")
    st.stop()

st.divider()

# ---- Claim 1: Cold → HEAT/HOT WATER ----------------------------------------
st.subheader("1 · On freezing days, HEAT/HOT WATER complaints rise ~160% (2.6×) — roughly +59,000/year")
d = daily_for("HEAT/HOT WATER")
fig = px.scatter(
    d, x="tavg_f", y="cnt",
    color=d["is_freezing"].map({1: "Freezing", 0: "Above freezing"}),
    labels={"tavg_f": "Daily mean temperature (°F)", "cnt": "HEAT/HOT WATER complaints/day",
            "color": ""},
    opacity=0.6,
)
st.plotly_chart(fig, use_container_width=True)
st.caption("Each point is one day. Heating complaints climb sharply as temperature falls "
           "(within-stratum corr −0.63) — it is a **cold**-season complaint, not a hot one.")

# ---- Claim 2: Heat → Water System ------------------------------------------
st.subheader("2 · Open-hydrant (Water System) complaints jump ~150% on hot days")
m = cond_means("Water System", "is_hot_day", ("Not hot", "Hot day"))
fig = px.bar(m, x="condition", y="avg_daily", text_auto=".0f",
             labels={"condition": "", "avg_daily": "Water System complaints/day"})
st.plotly_chart(fig, use_container_width=True)
st.caption("Average daily citywide count. Adjusted for season & weekday the hot-day effect is "
           "+149.5% (hold-out ok) — consistent with opened fire hydrants in heat.")

# ---- Claim 3: Rain → Sewer -------------------------------------------------
st.subheader("3 · On rainy days, Sewer complaints rise ~87% (1.9×) — about +6,300/year")
m = cond_means("Sewer", "is_rainy", ("Dry", "Rainy day"))
fig = px.bar(m, x="condition", y="avg_daily", text_auto=".0f",
             labels={"condition": "", "avg_daily": "Sewer complaints/day"})
st.plotly_chart(fig, use_container_width=True)
st.caption("The classic flooding signal: Sewer complaints spike with rain (adjusted +87.0%, "
           "hold-out ok) and are flat with temperature.")

# ---- Claim 4: Street/sidewalk noise tracks temperature ---------------------
st.subheader("4 · Street/sidewalk noise tracks temperature (corr +0.57) and drops 25–61% on rainy, snowy, or freezing days")
d = daily_for("Noise - Street/Sidewalk")
fig = px.scatter(
    d, x="tavg_f", y="cnt",
    color=d["is_rainy"].map({1: "Rainy", 0: "Dry"}),
    labels={"tavg_f": "Daily mean temperature (°F)", "cnt": "Street/sidewalk noise/day",
            "color": ""},
    opacity=0.6,
)
st.plotly_chart(fig, use_container_width=True)
st.caption("A warm, fair-weather activity: more complaints when it's hot, fewer when it rains.")

# ---- Claim 5: Rain/snow suppress outdoor complaints ------------------------
st.subheader("5 · Rain and snow suppress outdoor complaints across the board")
outdoor = ["Noise - Street/Sidewalk", "Noise - Commercial", "Illegal Parking",
           "Abandoned Vehicle", "Dirty Condition"]
rows = []
for t in outdoor:
    mm = cond_means(t, "is_rainy", ("Dry", "Rainy"))
    dry, rainy = mm["avg_daily"].tolist()
    if dry and dry == dry:
        rows.append({"type": t, "pct_change": rainy / dry - 1})
chg = pd.DataFrame(rows).sort_values("pct_change")
fig = px.bar(chg, x="pct_change", y="type", orientation="h",
             labels={"pct_change": "Change in complaints/day, rainy vs dry", "type": ""})
fig.update_layout(xaxis_tickformat=".0%")
st.plotly_chart(fig, use_container_width=True)
st.caption("Raw rainy-vs-dry change for high-volume outdoor types (all negative). "
           "Humidity, by contrast, showed no hold-out-replicable effect and is excluded.")

st.divider()
st.caption(
    "Source: NYC 311 Service Requests (Socrata `erm2-nwe9`) × `nyu-datasets.weather."
    "m_weather_daily_nyc`, joined on local NYC calendar date. Live from BigQuery "
    f"`{PROJECT}.nyc311.daily_complaints` (cached {TTL // 60} min). "
    "Method & caveats: `analysis/FINDINGS.md`."
)
