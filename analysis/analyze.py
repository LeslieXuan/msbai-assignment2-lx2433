"""Part 2: which 311 complaint types are weather-driven, and by how much.

Pulls the zero-filled daily panel (analysis/panel.sql), then for each weather
condition estimates a season x day-of-week ADJUSTED effect on daily complaint
volume via direct standardization, ranks complaint types by effect, and runs a
2023-24 -> 2025 hold-out replication check.

Prints a full report to stdout (read from the CI logs) and writes CSVs to
analysis/results/ for the dashboard.

Method (per complaint_type T, condition C in {hot, rainy, snowy, freezing, humid}):
  - Restrict to strata (season x is_weekend) that contain BOTH C=1 and C=0 days.
  - Within each stratum, mean daily count of T on C=1 days and on C=0 days.
  - Combine strata weighting by total days in the stratum (direct standardization),
    giving adjusted means adj1, adj0.
  - rate_ratio = adj1 / adj0 ; pct_change = rate_ratio - 1.
  - excess_per_day = adj1 - adj0 ; excess_total = excess_per_day * (# C=1 days).
This holds season and weekend/weekday fixed, so the effect is not just "summer".
It is still associational, not causal (see FINDINGS.md caveats).
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd
from google.cloud import bigquery

PROJECT = os.environ.get("GCP_PROJECT", "msbai-dwd-lx2433")
LOCATION = os.environ.get("BQ_LOCATION", "US")
TOPN = int(os.environ.get("TOPN", "15"))
OUTDIR = os.path.join(os.path.dirname(__file__), "results")

BINARY_CONDITIONS = {
    "is_hot_day": "hot",
    "is_rainy": "rainy",
    "is_snowy": "snowy",
    "is_freezing": "freezing",
    "is_humid": "humid",
}


def load_panel(bq: bigquery.Client) -> pd.DataFrame:
    sql = open(os.path.join(os.path.dirname(__file__), "panel.sql")).read()
    sql = sql.replace("{{PROJECT}}", PROJECT).replace("{{TOPN}}", str(TOPN))
    df = bq.query(sql).result().to_dataframe()
    # BigQuery returns nullable dtypes (Int64/boolean); coerce to plain numeric so
    # groupby/astype behave. A flag can be NA even when the row matched weather, so
    # keep NAs here and drop them per-condition in adjusted_effect.
    df = df[df["has_weather"].fillna(False).astype(bool)].copy()
    df["cnt"] = pd.to_numeric(df["cnt"], errors="coerce").fillna(0.0)
    df["year"] = pd.to_numeric(df["year"], errors="coerce").astype(int)
    df["is_weekend"] = pd.to_numeric(df["is_weekend"], errors="coerce").fillna(0).astype(int)
    df["tavg_f"] = pd.to_numeric(df["tavg_f"], errors="coerce")
    for c in BINARY_CONDITIONS:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def adjusted_effect(sub: pd.DataFrame, cond: str):
    """Direct-standardized adj means over season x is_weekend strata."""
    s = sub.dropna(subset=[cond, "cnt"]).copy()
    s[cond] = s[cond].astype(int)
    strata = s.groupby(["season", "is_weekend", cond])["cnt"].mean().unstack(cond)
    if 0 not in strata.columns or 1 not in strata.columns:
        return None
    both = strata.dropna(subset=[0, 1])
    if both.empty:
        return None
    weights = s.groupby(["season", "is_weekend"]).size()
    w = weights.reindex(both.index).astype(float)
    adj0 = float(np.average(both[0], weights=w))
    adj1 = float(np.average(both[1], weights=w))
    n_cond = int((s[cond] == 1).sum())
    rr = adj1 / adj0 if adj0 > 0 else np.nan
    return {
        "adj_baseline": adj0,
        "adj_condition": adj1,
        "rate_ratio": rr,
        "pct_change": rr - 1 if rr == rr else np.nan,
        "excess_per_day": adj1 - adj0,
        "excess_total": (adj1 - adj0) * n_cond,
        "n_condition_days": n_cond,
    }


def build_effects(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for cond, label in BINARY_CONDITIONS.items():
        for ctype, sub in df.groupby("complaint_type"):
            base = adjusted_effect(sub, cond)
            if base is None:
                continue
            row = {"complaint_type": ctype, "condition": label, **base}
            # Hold-out: fit on 2023-24, replicate on 2025.
            tr = adjusted_effect(sub[sub["year"] < 2025], cond)
            te = adjusted_effect(sub[sub["year"] == 2025], cond)
            row["rr_train_2023_24"] = tr["rate_ratio"] if tr else np.nan
            row["rr_test_2025"] = te["rate_ratio"] if te else np.nan
            rows.append(row)
    return pd.DataFrame(rows)


def temp_gradient(df: pd.DataFrame) -> pd.DataFrame:
    """Within-stratum Pearson correlation of daily count vs mean temperature."""
    rows = []
    for ctype, sub in df.groupby("complaint_type"):
        parts = []
        for _, g in sub.groupby(["season", "is_weekend"]):
            if g["tavg_f"].notna().sum() > 5 and g["tavg_f"].std() > 0:
                parts.append(g["cnt"].corr(g["tavg_f"]))
        if parts:
            rows.append({"complaint_type": ctype,
                         "temp_corr_within_stratum": float(np.nanmean(parts))})
    return pd.DataFrame(rows).sort_values("temp_corr_within_stratum", ascending=False)


def holdout_ok(rr_tr, rr_te) -> bool:
    if not (rr_tr == rr_tr and rr_te == rr_te):
        return False
    return (rr_tr - 1) * (rr_te - 1) > 0  # same direction


def main() -> None:
    os.makedirs(OUTDIR, exist_ok=True)
    bq = bigquery.Client(project=PROJECT, location=LOCATION)
    df = load_panel(bq)
    print(f"Panel: {len(df):,} rows, {df['complaint_type'].nunique()} types, "
          f"{df['complaint_date'].nunique()} days\n")

    types_by_vol = (df.groupby("complaint_type")["cnt"].sum()
                    .sort_values(ascending=False))
    print("=== Top complaint types by total volume (2023-2025) ===")
    for t, v in types_by_vol.items():
        print(f"  {int(v):>9,}  {t}")

    effects = build_effects(df)
    effects.to_csv(os.path.join(OUTDIR, "weather_effects.csv"), index=False)
    grad = temp_gradient(df)
    grad.to_csv(os.path.join(OUTDIR, "temp_gradient.csv"), index=False)

    effects["holdout_ok"] = [holdout_ok(a, b) for a, b in
                             zip(effects["rr_train_2023_24"], effects["rr_test_2025"])]

    for cond in [c for c in BINARY_CONDITIONS.values()]:
        sub = effects[effects["condition"] == cond].copy()
        sub = sub[sub["rate_ratio"].notna()].sort_values("pct_change", ascending=False)
        print(f"\n=== Effect of {cond.upper()} days on daily complaint volume "
              f"(season x weekday adjusted) ===")
        print("   pct_chg  ratio  baseline->cond/day  excess/yr  holdout  type")
        for _, r in sub.iterrows():
            print(f"  {r['pct_change']:+7.1%}  {r['rate_ratio']:4.2f}  "
                  f"{r['adj_baseline']:7.1f}->{r['adj_condition']:7.1f}  "
                  f"{r['excess_total']/3:+8.0f}  "
                  f"{'ok' if r['holdout_ok'] else 'NO':>5}  {r['complaint_type']}")

    print("\n=== Temperature gradient (within-stratum corr of count vs tavg_f) ===")
    for _, r in grad.iterrows():
        print(f"  {r['temp_corr_within_stratum']:+.2f}  {r['complaint_type']}")

    print(f"\nWrote {OUTDIR}/weather_effects.csv and temp_gradient.csv")


if __name__ == "__main__":
    main()
