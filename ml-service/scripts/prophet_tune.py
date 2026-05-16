"""
Prophet Hyperparameter Tuning V3 — ml-service/scripts/prophet_tune.py

WHY V3 (see the V1/V2 forensic audit)
-------------------------------------
V2 widened the grid downward (seasonality_prior_scale floor 0.01) and
selected with pure CV-RMSE. On a noisy weekly-mean engagement series RMSE
structurally rewards a near-flat forecast, so 4/5 V2 forecasts collapsed
(forecast_std / hist_std ratio 0.01–0.20). The grid was not missing
dynamic combos — the objective rejected them.

V3 FIXES
  1. Grid: cps[0.05,0.1,0.2,0.3,0.5] × sps[1,5,10,15,20] (FLOOR=1, never
     below) × {additive,multiplicative} = 5×5×2 = 50 combos / industry.
  2. Constrained selection (the core change): a candidate is accepted
     ONLY if 0.35 <= forecast_std/hist_std <= 1.2 on the 12-week window;
     among accepted candidates pick the lowest mean CV-RMSE. If none
     qualify: loud warning, fall back to the candidate whose ratio is
     closest to 0.5, mark the industry constraint_violated.
  3. n_changepoints = 25 in CV (V2 used 10 in CV but 25 in final →
     ranking was not transferable; prophet_train.py also uses 25).
  4. OPT-4 multiplicative auto-forcing REMOVED — multiplicative competes
     as an ordinary candidate (it produced V2's unstable tails).
  5. CV horizon = 84 days (= the 12-week Step-5 window; was 90).

Output: {industry}_best_params_v3.json (version "v3").

Usage:
    cd ml-service
    .venv/Scripts/python.exe scripts/prophet_tune.py
    .venv/Scripts/python.exe scripts/prophet_tune.py --industry beauty
"""

import json
import logging
import sys
import warnings
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd
from prophet import Prophet
from prophet.diagnostics import cross_validation, performance_metrics

# ── Silence CmdStan / Stan / prophet noise ────────────────────────────────
logging.getLogger("cmdstanpy").setLevel(logging.ERROR)
logging.getLogger("prophet").setLevel(logging.ERROR)
logging.getLogger("pystan").setLevel(logging.ERROR)
warnings.filterwarnings("ignore")

# ── Paths ─────────────────────────────────────────────────────────────────
DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "prophet"

INDUSTRIES = ["patisserie", "fashion", "beauty", "hotels", "restaurants"]

# ── V3 constants ──────────────────────────────────────────────────────────
N_CHANGEPOINTS   = 25          # FIX-3: identical in tune AND prophet_train.py
FORECAST_WEEKS   = 12          # ratio is measured on this window
CV_INITIAL       = "365 days"
CV_PERIOD        = "30 days"
CV_HORIZON       = "84 days"   # FIX-5: 12 weeks, aligned to Step-5
RATIO_LOW        = 0.35        # constraint band (inclusive)
RATIO_HIGH       = 1.20
RATIO_TARGET     = 0.50        # fallback objective when band is empty

# Ramadan windows for the is_ramadan future regressor (mirror of
# prophet_preprocess.py / prophet_train.py — kept local so this script
# has no cross-script import dependency, matching the existing codebase
# convention of duplicating these tables).
RAMADAN_PERIODS = [
    ("2023-03-23", "2023-04-21"),
    ("2024-03-11", "2024-04-09"),
    ("2025-03-01", "2025-03-30"),
    ("2026-02-18", "2026-03-19"),
]

# ─────────────────────────────────────────────────────────────────────────────
# HOLIDAYS  (unchanged from V2 — the Tunisia calendar is correct; the V2
# failure was the prior scale, not the holiday table)
# ─────────────────────────────────────────────────────────────────────────────

def build_custom_holidays() -> pd.DataFrame:
    rows = []

    def add(name, dates, lower, upper):
        for ds in dates:
            rows.append({"holiday": name, "ds": pd.Timestamp(ds),
                         "lower_window": lower, "upper_window": upper})

    add("Ramadan",         ["2023-03-23","2024-03-11","2025-03-01","2026-02-18"],  0, 29)
    add("Eid_el_Fitr",    ["2023-04-21","2024-04-10","2025-03-30","2026-03-20"], -2,  3)
    add("Eid_el_Adha",    ["2023-06-28","2024-06-17","2025-06-07","2026-05-26"], -1,  3)
    add("Mouloud",        ["2023-09-27","2024-09-16","2025-09-05"],               0,  1)
    add("Nouvel_An_Hijri",["2023-07-19","2024-07-08","2025-06-27","2026-06-17"], 0,  1)
    add("Fete_evacuation", ["2023-10-15","2024-10-15","2025-10-15"],             0,  1)
    add("Fete_revolution", ["2023-12-17","2024-12-17","2025-12-17"],             0,  1)
    add("Journee_martyrs", ["2023-04-09","2024-04-09","2025-04-09","2026-04-09"],0,  1)
    add("Vacances_ete",       ["2023-06-15","2024-06-15","2025-06-15","2026-06-15"], 0, 90)
    add("Vacances_hiver",     ["2023-12-25","2024-12-22","2025-12-22"],              0, 13)
    add("Vacances_octobre",   ["2023-10-23","2024-10-28","2025-10-27"],              0,  7)
    add("Vacances_fevrier",   ["2023-02-06","2024-02-05","2025-02-03","2026-02-02"], 0,  7)
    add("Vacances_printemps", ["2023-03-27","2024-03-25","2025-03-24","2026-03-16"], 0, 13)

    return pd.DataFrame(rows)


CUSTOM_HOLIDAYS = build_custom_holidays()

# ─────────────────────────────────────────────────────────────────────────────
# V3 GRID — 5 × 5 × 2 = 50.  sps FLOOR = 1 (never below: the V2 collapse
# was caused by the sub-1 values 0.01/0.05/0.1/0.5).
# ─────────────────────────────────────────────────────────────────────────────

CHANGEPOINT_PRIOR_SCALES = [0.05, 0.1, 0.2, 0.3, 0.5]
SEASONALITY_PRIOR_SCALES = [1, 5, 10, 15, 20]
SEASONALITY_MODES        = ["additive", "multiplicative"]

GRID = list(product(CHANGEPOINT_PRIOR_SCALES,
                     SEASONALITY_PRIOR_SCALES,
                     SEASONALITY_MODES))   # 50


# ─────────────────────────────────────────────────────────────────────────────
# MODEL BUILDER
# ─────────────────────────────────────────────────────────────────────────────

def build_model(cps: float, sps: float, mode: str) -> Prophet:
    m = Prophet(
        changepoint_prior_scale = cps,
        seasonality_prior_scale = sps,
        seasonality_mode        = mode,
        yearly_seasonality      = True,
        weekly_seasonality      = False,
        daily_seasonality       = False,
        holidays                = CUSTOM_HOLIDAYS,
        n_changepoints          = N_CHANGEPOINTS,   # FIX-3: == prophet_train.py
    )
    try:
        m.add_country_holidays(country_name="TN")
    except Exception:
        pass
    m.add_regressor("n_posts_scaled")
    m.add_regressor("is_ramadan")
    m.add_regressor("is_summer_peak")
    return m


# ─────────────────────────────────────────────────────────────────────────────
# FUTURE REGRESSORS  (identical logic to prophet_train.build_future_regressors
# so the tune-time ratio == the train-time ratio for the same params)
# ─────────────────────────────────────────────────────────────────────────────

def build_future_regressors(df_train: pd.DataFrame,
                             future_df: pd.DataFrame) -> pd.DataFrame:
    future_df = future_df.copy()

    future_n_posts_scaled = float(df_train["n_posts_scaled"].tail(4).mean())
    hist_map = df_train.set_index("ds")["n_posts_scaled"].to_dict()
    future_df["n_posts_scaled"] = future_df["ds"].map(
        lambda d: hist_map.get(d, future_n_posts_scaled))

    future_df["is_ramadan"] = 0
    for start, end in RAMADAN_PERIODS:
        mask = (future_df["ds"] >= pd.Timestamp(start)) & \
               (future_df["ds"] <= pd.Timestamp(end))
        future_df.loc[mask, "is_ramadan"] = 1

    future_df["is_summer_peak"] = future_df["ds"].dt.month.isin([7, 8, 9]).astype(int)
    return future_df


def forecast_ratio(model: Prophet, df_full: pd.DataFrame) -> tuple[float, float, float]:
    """Refit-on-full-data forecast spread vs history, on the 12-week window.
    Population std (ddof=0) on both — matches the approved audit's
    statistics.pstdev so the 0.35/1.2 thresholds stay calibrated."""
    future = model.make_future_dataframe(periods=FORECAST_WEEKS, freq="W")
    future = build_future_regressors(df_full, future)
    fc = model.predict(future)
    cutoff = df_full["ds"].max()
    fut = fc[fc["ds"] > cutoff].head(FORECAST_WEEKS)
    f_std = float(np.std(fut["yhat"].to_numpy(), ddof=0))
    h_std = float(np.std(df_full["y"].to_numpy(), ddof=0))
    ratio = f_std / h_std if h_std else float("nan")
    return f_std, h_std, ratio


# ─────────────────────────────────────────────────────────────────────────────
# CONSTRAINED SELECTION
# ─────────────────────────────────────────────────────────────────────────────

def select_constrained(industry: str, results: list) -> dict:
    """results: list of per-combo dicts with rmse + ratio (finite only).
    Accept iff RATIO_LOW <= ratio <= RATIO_HIGH; among accepted pick min
    rmse. Else: loud warning + candidate whose ratio is closest to
    RATIO_TARGET, flagged constraint_violated."""
    finite = [r for r in results
              if r["rmse"] != float("inf") and np.isfinite(r.get("ratio", float("inf")))]
    if not finite:
        print(f"    !! [{industry}] every candidate failed — no selection possible")
        return {}

    accepted = [r for r in finite if RATIO_LOW <= r["ratio"] <= RATIO_HIGH]
    if accepted:
        best = min(accepted, key=lambda r: r["rmse"])
        return {**best, "constraint_satisfied": True, "constraint_violated": False,
                "n_accepted": len(accepted)}

    # Constraint band empty → loud warning + closest-to-target fallback.
    best = min(finite, key=lambda r: abs(r["ratio"] - RATIO_TARGET))
    print("    " + "!" * 70)
    print(f"    !! [{industry}] CONSTRAINT VIOLATED: NO candidate has "
          f"{RATIO_LOW} <= ratio <= {RATIO_HIGH}")
    print(f"    !! Falling back to ratio-closest-to-{RATIO_TARGET}: "
          f"cps={best['changepoint_prior_scale']} sps={best['seasonality_prior_scale']} "
          f"{best['seasonality_mode']}  ratio={best['ratio']:.3f}  rmse={best['rmse']:.5f}")
    print("    " + "!" * 70)
    return {**best, "constraint_satisfied": False, "constraint_violated": True,
            "n_accepted": 0}


# ─────────────────────────────────────────────────────────────────────────────
# TUNE ONE INDUSTRY
# ─────────────────────────────────────────────────────────────────────────────

def tune_industry(industry: str) -> dict:
    final_path = DATA_DIR / f"{industry}_best_params_v3.json"
    if final_path.exists():
        print(f"\n  [{industry.upper()}]  already done — loading {final_path.name}")
        with open(final_path, encoding="utf-8") as f:
            return json.load(f)

    csv_path = DATA_DIR / f"{industry}_preprocessed.csv"
    if not csv_path.exists():
        print(f"  [{industry}] CSV not found — run prophet_preprocess.py first")
        return {}

    df = pd.read_csv(csv_path, parse_dates=["ds"])
    required = {"n_posts_scaled", "is_ramadan", "is_summer_peak"}
    missing = required - set(df.columns)
    if missing:
        print(f"  [{industry}] Missing regressor columns {missing} — re-run preprocess")
        return {}

    df_model = df[["ds", "y", "n_posts_scaled", "is_ramadan", "is_summer_peak"]].copy()

    # Resume from a v3 partial if a previous run was interrupted (the job is
    # long: 50 CV runs/industry). Partial stores ratio + metrics too.
    partial_path = DATA_DIR / f"{industry}_tune_partial_v3.json"
    done_keys: set = set()
    results: list = []
    if partial_path.exists():
        with open(partial_path, encoding="utf-8") as f:
            partial = json.load(f)
        results = partial.get("results", [])
        for r in results:
            done_keys.add((r["changepoint_prior_scale"],
                           r["seasonality_prior_scale"],
                           r["seasonality_mode"]))
        print(f"\n  [{industry.upper()}]  resuming — {len(results)}/{len(GRID)} done")
    else:
        print(f"\n  [{industry.upper()}]  {len(df)} weeks  "
              f"({df['ds'].min().date()} -> {df['ds'].max().date()})")
    print(f"    Grid {len(GRID)} | CV initial={CV_INITIAL} period={CV_PERIOD} "
          f"horizon={CV_HORIZON} | n_changepoints={N_CHANGEPOINTS}")
    print(f"    Constraint: {RATIO_LOW} <= forecast_std/hist_std <= {RATIO_HIGH}")

    for i, (cps, sps, mode) in enumerate(GRID, 1):
        if (cps, sps, mode) in done_keys:
            print(f"    [{i:2d}/{len(GRID)}] cps={cps} sps={sps} {mode[:3]}  SKIP")
            continue

        label = f"cps={cps} sps={sps} {mode[:3]}"
        try:
            m = build_model(cps, sps, mode)
            m.fit(df_model)                                  # full-data fit

            cv_df = cross_validation(
                m, initial=CV_INITIAL, period=CV_PERIOD, horizon=CV_HORIZON,
                parallel="threads", disable_tqdm=True,
            )
            pm = performance_metrics(cv_df, rolling_window=1)

            # Prophet's performance_metrics DROPS the mape/mdape/smape
            # columns entirely when any CV actual is 0 (division by zero).
            # Fashion has 35 zero-filled weeks → no 'mape' column. Tolerate
            # any missing/non-finite metric: mape/mae/coverage become null,
            # which is the honest value. Only rmse is required to rank.
            def _metric(name):
                if name not in pm.columns:
                    return None
                v = float(pm[name].mean())
                return v if np.isfinite(v) else None

            rmse = _metric("rmse")
            if rmse is None:
                raise ValueError("performance_metrics returned no usable rmse")
            mae  = _metric("mae")
            mape = _metric("mape")
            cov  = _metric("coverage")

            # m is still the full-data fit → measure forecast spread.
            f_std, h_std, ratio = forecast_ratio(m, df)

            results.append({
                "changepoint_prior_scale": cps,
                "seasonality_prior_scale": sps,
                "seasonality_mode"       : mode,
                "rmse"                   : round(rmse, 6),
                "mae"                    : (round(mae, 6) if mae is not None else None),
                "mape"                   : (round(mape, 6) if mape is not None else None),
                "coverage"               : (round(cov, 6) if cov is not None else None),
                "forecast_std"           : round(f_std, 6),
                "hist_std"               : round(h_std, 6),
                "ratio"                  : round(ratio, 6),
                "in_band"                : bool(RATIO_LOW <= ratio <= RATIO_HIGH),
            })
            flag = "OK " if RATIO_LOW <= ratio <= RATIO_HIGH else "rej"
            print(f"    [{i:2d}/{len(GRID)}] {label:<26} "
                  f"RMSE={rmse:.5f}  ratio={ratio:.3f} [{flag}]")

        except Exception as exc:
            print(f"    [{i:2d}/{len(GRID)}] {label:<26} ERROR: {exc}")
            results.append({
                "changepoint_prior_scale": cps,
                "seasonality_prior_scale": sps,
                "seasonality_mode"       : mode,
                "rmse"                   : float("inf"),
                "ratio"                  : float("inf"),
                "error"                  : str(exc),
            })

        with open(partial_path, "w", encoding="utf-8") as f:
            json.dump({"industry": industry, "results": results}, f)

    sel = select_constrained(industry, results)
    if not sel:
        return {}

    finite_sorted = sorted(
        [r for r in results if r["rmse"] != float("inf")],
        key=lambda r: r["rmse"])

    output = {
        "industry"            : industry,
        "version"             : "v3",
        "grid_size"           : len(GRID),
        "grid"                : {
            "changepoint_prior_scale": CHANGEPOINT_PRIOR_SCALES,
            "seasonality_prior_scale": SEASONALITY_PRIOR_SCALES,
            "seasonality_mode"       : SEASONALITY_MODES,
        },
        "cv"                  : {"initial": CV_INITIAL, "period": CV_PERIOD,
                                 "horizon": CV_HORIZON,
                                 "n_changepoints": N_CHANGEPOINTS},
        "regressors"          : ["n_posts_scaled", "is_ramadan", "is_summer_peak"],
        "selection"           : "constrained_ratio_then_min_rmse",
        "constraint"          : {"ratio_low": RATIO_LOW, "ratio_high": RATIO_HIGH,
                                 "ratio_target_fallback": RATIO_TARGET},
        "best_params"         : {
            "changepoint_prior_scale": sel["changepoint_prior_scale"],
            "seasonality_prior_scale": sel["seasonality_prior_scale"],
            "seasonality_mode"       : sel["seasonality_mode"],
        },
        "best_rmse"           : sel["rmse"],
        "selected_metrics"    : {
            "rmse"           : sel["rmse"],
            "mae"            : sel.get("mae"),
            "mape"           : sel.get("mape"),
            "ci_coverage_pct": (round(sel["coverage"] * 100, 4)
                                if sel.get("coverage") is not None else None),
        },
        "selected_forecast_std": sel.get("forecast_std"),
        "selected_hist_std"    : sel.get("hist_std"),
        "ratio"                : sel.get("ratio"),
        "constraint_satisfied" : sel["constraint_satisfied"],
        "constraint_violated"  : sel["constraint_violated"],
        "n_accepted"           : sel.get("n_accepted", 0),
        "worst_rmse"           : (finite_sorted[-1]["rmse"] if finite_sorted else None),
        "all_results"          : finite_sorted
                                 + [r for r in results if r["rmse"] == float("inf")],
    }

    with open(final_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)
    print(f"    Saved -> {final_path.name}  "
          f"(accepted={sel.get('n_accepted',0)}/{len(GRID)})")
    partial_path.unlink(missing_ok=True)
    return output


# ─────────────────────────────────────────────────────────────────────────────
# REPORT
# ─────────────────────────────────────────────────────────────────────────────

def print_report(all_results: dict) -> None:
    print("\n" + "=" * 78)
    print("  PROPHET HYPERPARAMETER TUNING V3 — FINAL REPORT")
    print("=" * 78)
    print(f"  Grid: {len(GRID)} combos × {len(INDUSTRIES)} industries  "
          f"(cps {CHANGEPOINT_PRIOR_SCALES} × sps {SEASONALITY_PRIOR_SCALES})")
    print(f"  Selection: accept {RATIO_LOW}<=ratio<={RATIO_HIGH}, then min CV-RMSE")
    print(f"  CV horizon={CV_HORIZON}  n_changepoints={N_CHANGEPOINTS}  "
          f"(OPT-4 forcing removed)\n")

    for industry in INDUSTRIES:
        r = all_results.get(industry)
        if not r:
            print(f"  [{industry.upper()}]  -- NO RESULTS --")
            continue
        bp = r["best_params"]
        viol = "  ← CONSTRAINT VIOLATED (fallback)" if r.get("constraint_violated") else ""
        print(f"  [{industry.upper()}]{viol}")
        print(f"    best cps/sps/mode : {bp['changepoint_prior_scale']} / "
              f"{bp['seasonality_prior_scale']} / {bp['seasonality_mode']}")
        print(f"    CV-RMSE           : {r['best_rmse']:.6f}")
        print(f"    ratio             : {r.get('ratio')}  "
              f"(satisfied={r.get('constraint_satisfied')}, "
              f"accepted={r.get('n_accepted')}/{r['grid_size']})\n")

    print("=" * 78)
    print("STOP — validate, then run prophet_train.py (V3, FORECAST_WEEKS=12).\n")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--industry", type=str, default=None,
                        help="Run only this industry (e.g. --industry beauty)")
    args = parser.parse_args()
    targets = [args.industry] if args.industry else INDUSTRIES

    print("Prophet Hyperparameter Tuning V3")
    print(f"Grid: {len(GRID)} combos × {len(targets)} industries "
          f"= {len(GRID)*len(targets)} CV runs")
    print(f"Constrained selection: {RATIO_LOW} <= forecast_std/hist_std "
          f"<= {RATIO_HIGH}")
    print("-" * 78)

    all_results = {}
    for industry in targets:
        result = tune_industry(industry)
        if result:
            all_results[industry] = result

    print_report(all_results)


if __name__ == "__main__":
    main()
