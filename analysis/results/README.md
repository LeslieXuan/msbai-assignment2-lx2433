# analysis/results — committed analysis evidence

Committed outputs of the Part 2 analysis (`analysis/analyze.py`), so the findings
in `analysis/FINDINGS.md` are backed by evidence in the repo, not only in workflow
logs. Regenerate any time by running the **nyc311-analyze** workflow (it also
uploads full-precision copies as run artifacts).

Source run: `nyc311-analyze` over `nyc311.daily_complaints`, top-15 complaint types
plus keyword-discovered sewer/flood types (`SEWER,FLOOD,DRAIN`) — 19 types × 1,096
days. Effects are **season × day-of-week direct-standardized rate ratios**, with a
2023–24 → 2025 **hold-out** replication flag.

## `weather_effects.csv`
One row per (weather condition × complaint type).

| column | meaning |
|---|---|
| `condition` | `hot` / `rainy` / `snowy` / `freezing` / `humid` (the day-level weather flag) |
| `complaint_type` | 311 complaint type |
| `pct_change` | adjusted % change on condition days vs not (e.g. `87.0` = +87%) |
| `rate_ratio` | adjusted condition/baseline ratio (1.87 = 1.87×) |
| `adj_baseline_per_day` | standardized mean complaints/day on non-condition days |
| `adj_condition_per_day` | standardized mean complaints/day on condition days |
| `excess_per_year` | standardized extra (or fewer) complaints per year on condition days |
| `holdout` | `ok` = effect direction replicates on 2025; `NO` = does not (treat as noise) |

**Read the confirmed findings as the `holdout = ok` rows with large `|pct_change|`.**
Values are as displayed by the run (rounded); full precision is in the run artifact.

## `temp_gradient.csv`
Within-stratum Pearson correlation of daily count vs mean temperature (`tavg_f`) per
type. Most positive = most warm-weather (Noise-Street/Sidewalk +0.57); most negative
= most cold-weather (HEAT/HOT WATER −0.63).

## Caveat
Associational, not causal (season & weekday controlled only). See
`analysis/FINDINGS.md` for the full write-up, magnitudes, and limitations.
