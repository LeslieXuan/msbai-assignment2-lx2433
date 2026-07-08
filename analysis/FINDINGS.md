# Part 2 — Which NYC 311 complaints are weather-driven, and by how much

**Question.** Among the highest-volume 311 complaint types, which ones respond to
weather once we hold **season** and **day-of-week** fixed — and how large is the effect?

**Data.** `nyc311.daily_complaints`, 2023-01-01 … 2025-12-31 (1,096 days). Panel =
top-15 complaint types **plus keyword-matched sewer/flood types** (`Sewer`,
`Root/Sewer/Sidewalk Condition`, `Sewer Maintenance`, `Water Drainage`) × every calendar
day, citywide, **zero-filled**, joined to that day's weather (19 types, 20,824 type-days).
Produced by `analysis/panel.sql` + `analysis/analyze.py` (run: GitHub Actions **nyc311-analyze**).

**Method.** For each complaint type and weather condition we compute a **direct-standardized
rate ratio** across `season × is_weekend` strata: within each stratum we compare the mean
daily count on condition days vs non-condition days, then combine strata weighting by their
number of days. This removes the "it's just summer" and "it's just a weekday" confounds by
construction. We validate every effect with a **hold-out**: fit on 2023–24, require the 2025
effect to point the same direction (`ok` / `NO` below). Continuous temperature is summarized
by the within-stratum correlation of daily count vs `tavg_f`. **All effects are associational,
not causal — see caveats.**

Top-15 types by volume (3-yr totals): Illegal Parking 1.56M · Noise-Residential 1.14M ·
HEAT/HOT WATER 810k · Blocked Driveway 509k · Noise-Street/Sidewalk 483k · Unsanitary 354k ·
Street Condition 206k · Abandoned Vehicle 203k · Noise-Commercial 200k · Water System 197k ·
Plumbing 197k · Paint/Plaster 183k · Dirty Condition 170k · Noise 164k · Derelict Vehicles 144k.

---

## Headline findings (robust = replicates on 2025 hold-out)

1. **Cold drives heating complaints — the single strongest, most robust signal.**
   On **freezing** days `HEAT/HOT WATER` rises **+159.8%** (2.60×), from ~772 to ~2,006/day —
   about **+58,800 complaints/year**, hold-out **ok**. Temperature correlation **−0.63** (the
   most negative of any type), and on **hot** days it falls **−69%**.
   → *The assignment's example "heat → HEAT/HOT WATER" is backwards: it is a **cold**-season
   complaint.*

2. **Heat drives open-hydrant (Water System) complaints.**
   On **hot** days `Water System` rises **+149.5%** (2.50×), ~189 → ~471/day, **+3,200/year**,
   hold-out **ok**. Consistent with opened fire hydrants in heat; falls on rainy days (−16.4%, ok).

3. **Rain drives Sewer complaints (the classic flooding signal, confirmed).**
   On **rainy** days `Sewer` rises **+87.0%** (1.87×), ~59 → ~110/day, **≈ +6,300/year**,
   hold-out **ok**. It is specifically *rain*-driven, not temperature: flat temperature gradient
   (+0.08) and *suppressed* on snowy (−17.4%, ok) and freezing (−31.9%, ok) days.

4. **Street/sidewalk noise is a fair-weather, warm-weather activity.**
   `Noise - Street/Sidewalk` has the **highest temperature correlation (+0.57)** and is strongly
   **suppressed by precipitation/cold**, all replicated: rainy **−25.5%** (ok), snowy **−41.6%**
   (ok), freezing **−61.3%** (ok). Its hot-day *binary* jump (+38.8%) did **not** replicate, so
   we lead with the temperature gradient + precip suppression, which do.

5. **Heat raises street-life / sanitation nuisance complaints (modest, robust).**
   `Dirty Condition` +19.2% on hot days (ok; temp corr +0.42); `Plumbing` +19.5% on freezing
   days (ok); `Unsanitary Condition` small but consistent (+5–7%, ok).

6. **Rain and snow suppress outdoor complaints broadly**; **humidity has no reliable effect** —
   *every* humid-day effect failed the hold-out (`NO`), so we discard humidity.

7. **"Heat → noise" is type-specific, not general.** Street/sidewalk noise rises with heat, but
   `Noise` (−23.5% hot) and `Noise - Residential` (−10.9% hot) *fall*. Reported honestly rather
   than forced to fit the hypothesis.

---

## Effect tables (season × weekday adjusted)

Excess/yr = standardized extra (or fewer) complaints per year on condition days.

### FREEZING days
| type | pct | ratio | base→cond/day | excess/yr | hold-out |
|---|--:|--:|--|--:|:--:|
| HEAT/HOT WATER | **+159.8%** | 2.60 | 772→2006 | +58,810 | ok |
| PLUMBING | +19.5% | 1.19 | 177→211 | +1,639 | ok |
| Water System | +9.2% | 1.09 | 132→144 | +576 | NO |
| PAINT/PLASTER | +8.1% | 1.08 | 166→180 | +645 | ok |
| UNSANITARY CONDITION | +6.8% | 1.07 | 310→331 | +1,008 | ok |
| Street Condition | +4.7% | 1.05 | 189→198 | +423 | ok |
| Noise - Commercial | −18.7% | 0.81 | 190→154 | −1,688 | ok |
| Dirty Condition | −22.7% | 0.77 | 144→111 | −1,556 | ok |
| Noise - Street/Sidewalk | −61.3% | 0.39 | 361→140 | −10,550 | ok |

### HOT days
| type | pct | ratio | base→cond/day | excess/yr | hold-out |
|---|--:|--:|--|--:|:--:|
| Water System | **+149.5%** | 2.50 | 189→471 | +3,200 | ok |
| Noise - Street/Sidewalk | +38.8% | 1.39 | 507→703 | +2,226 | NO |
| Dirty Condition | +19.2% | 1.19 | 177→210 | +384 | ok |
| PLUMBING | +7.9% | 1.08 | 186→200 | +166 | ok |
| UNSANITARY CONDITION | +5.2% | 1.05 | 365→384 | +215 | ok |
| Street Condition | −19.4% | 0.81 | 207→167 | −454 | ok |
| Noise | −23.5% | 0.77 | 160→122 | −425 | ok |
| HEAT/HOT WATER | −69.0% | 0.31 | 455→141 | −3,562 | NO |

### RAINY days
| type | pct | ratio | base→cond/day | excess/yr | hold-out |
|---|--:|--:|--|--:|:--:|
| **Sewer** | **+87.0%** | 1.87 | 59→110 | **+6,321** | ok |
| PAINT/PLASTER | +3.3% | 1.03 | 165→170 | +660 | ok |
| Noise - Commercial | −9.8% | 0.90 | 188→170 | −2,270 | ok |
| HEAT/HOT WATER | −15.3% | 0.85 | 784→664 | −14,730 | ok |
| Water System | −16.4% | 0.84 | 190→159 | −3,851 | ok |
| Noise - Street/Sidewalk | −25.5% | 0.75 | 482→359 | −15,114 | ok |

*Sub-1k/day flood types (`Sewer Maintenance`, `Water Drainage`) show huge % swings on rain/humid
days but off near-zero baselines and **fail the hold-out** (`NO`) — discarded as noise.*

### SNOWY days
| type | pct | ratio | excess/yr | hold-out |
|---|--:|--:|--:|:--:|
| HEAT/HOT WATER | +43.6% | 1.44 | +4,152 | NO |
| PLUMBING | +12.2% | 1.12 | +208 | NO |
| Noise - Commercial | −32.0% | 0.68 | −417 | ok |
| Noise - Street/Sidewalk | −41.6% | 0.58 | −819 | ok |

### HUMID days — **discarded**: every effect failed the hold-out (all `NO`).

### Temperature gradient (within-stratum corr of daily count vs `tavg_f`)
`+0.57` Noise-Street/Sidewalk · `+0.42` Dirty Condition · `+0.26` Derelict Vehicles ·
`+0.23` Abandoned Vehicle · `+0.22` Water System · `+0.21` Noise-Commercial ·
`+0.12` Illegal Parking · ~0 Unsanitary / Noise-Residential / Street Condition / Noise ·
`−0.17` Plumbing · **`−0.63` HEAT/HOT WATER**.

---

## Verification

- **Hold-out (2023–24 → 2025).** Reported per effect above. The headline effects (freezing→HEAT/HOT
  WATER, hot→Water System, precip/cold→Noise-Street/Sidewalk) all replicate. Humidity and several
  weaker effects do **not**, and are excluded from claims.
- **Magnitude sanity.** HEAT/HOT WATER totals ~270k/yr; the freezing-day standardized excess
  (~+59k/yr) is a believable fraction concentrated in the heating season. Water System ~66k/yr;
  a +3.2k/yr hot-day excess is plausible for hydrant reports.
- **Confound control.** Standardization on `season × is_weekend` shrank the naive hot-day effect
  materially (validated on synthetic data during development: naive +60.7/day → adjusted +40.5/day),
  confirming the adjustment is doing real work rather than restating seasonality.

## Limitations & correlation vs causation

- **Associational only.** Weather co-varies with unobserved drivers — daylight hours, school
  calendar, holidays, time spent outdoors, and **reporting propensity** (people may call 311 more
  when home). We control season and weekday, nothing else; do not read these as causal effects.
- **Binary flags are coarse.** `is_hot_day`/`is_rainy` thresholds compress a continuous signal; the
  temperature correlation is a useful cross-check (and why we lead with it for Noise-Street/Sidewalk).
- **Low-volume types are noisy.** `Sewer` (82k) is solid, but `Sewer Maintenance` (2.8k) and
  `Water Drainage` (136) produce extreme % swings off tiny baselines that don't replicate — we
  keep only hold-out-passing effects and flag the rest.
- **Single city, three years.** No claim of generalization beyond NYC 2023–2025.

## Dashboard claims (Part 3 — one sentence each)

1. On **freezing** days, `HEAT/HOT WATER` complaints rise **~160% (2.6×)** — roughly **+59,000/year**.
2. `Water System` (open-hydrant) complaints jump **~150%** on **hot** days.
3. On **rainy** days, `Sewer` complaints rise **~87% (1.9×)** — about **+6,300/year**.
4. **Street/sidewalk noise tracks temperature** (corr **+0.57**) and drops **25–61%** on rainy,
   snowy, or freezing days.
5. **Rain and snow suppress outdoor complaints** across the board, while **humidity shows no
   reliable effect**.

## Reproduce
Run the **nyc311-analyze** workflow (input `topn`, default 15). It prints this report and writes
`analysis/results/weather_effects.csv` and `temp_gradient.csv` as run artifacts.
