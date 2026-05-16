"""
Prophet Final Training V3 — ml-service/scripts/prophet_train.py

For each industry:
  - Load best params from {industry}_best_params_v3.json (constrained
    selection — see prophet_tune.py / the V1-V2 forensic audit)
  - Load preprocessed CSV (regressors: n_posts_scaled, is_ramadan,
    is_summer_peak)
  - Train Prophet with best params + regressors + Tunisia holidays
    (n_changepoints = 25, identical to the CV in prophet_tune.py)
  - Predict next 12 weeks (FIX-6) with future regressors
  - FIX-8: clip yhat, yhat_lower, yhat_upper at 0 (engagement rate
    can't be negative) before intensity / std / ratio / JSON
  - FIX-7: automated guard — if forecast_std/hist_std < 0.3 the forecast
    collapsed; raise (the run is caught per-industry in main so the
    report is complete, but a collapsed industry is NEVER written)
  - Compute intensity (high/normal/low) + posts_recommended
  - Save {industry}_forecast_v3.json (version "v3") with a new
    "performance" block, + plots ({industry}_forecast_v3.png)

Usage:
    cd ml-service
    .venv/Scripts/python.exe -X utf8 scripts/prophet_train.py
"""

import json
import logging
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd
from prophet import Prophet

# ── Silence noise ─────────────────────────────────────────────────────────────
logging.getLogger("cmdstanpy").setLevel(logging.ERROR)
logging.getLogger("prophet").setLevel(logging.ERROR)
logging.getLogger("pystan").setLevel(logging.ERROR)
warnings.filterwarnings("ignore")

# ── Paths ─────────────────────────────────────────────────────────────────────
DATA_DIR  = Path(__file__).resolve().parents[1] / "data" / "prophet"
PLOTS_DIR = DATA_DIR / "plots"
PLOTS_DIR.mkdir(parents=True, exist_ok=True)

INDUSTRIES     = ["patisserie", "fashion", "beauty", "hotels", "restaurants"]
FORECAST_WEEKS = 12            # FIX-6 (was 30)
N_CHANGEPOINTS = 25            # FIX-3: identical to prophet_tune.py CV
GUARD_RATIO    = 0.30          # FIX-7: below this the forecast collapsed
CONSTRAINT_LOW, CONSTRAINT_HIGH = 0.35, 1.20   # reporting band (= tune)

INDUSTRY_COLORS = {
    "patisserie" : "#e07b54",
    "fashion"    : "#7b5ea7",
    "beauty"     : "#e84393",
    "hotels"     : "#2196f3",
    "restaurants": "#4caf50",
}

RAMADAN_PERIODS = [
    ("2023-03-23", "2023-04-21"),
    ("2024-03-11", "2024-04-09"),
    ("2025-03-01", "2025-03-30"),
    ("2026-02-18", "2026-03-19"),
]


# ── Tunisia holidays (unchanged) ──────────────────────────────────────────────

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
RAMADAN_RANGES  = RAMADAN_PERIODS


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_best_params_v3(industry: str) -> dict | None:
    p = DATA_DIR / f"{industry}_best_params_v3.json"
    if not p.exists():
        print(f"  [{industry}] best_params_v3.json not found — run prophet_tune.py first")
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def load_csv(industry: str) -> pd.DataFrame | None:
    p = DATA_DIR / f"{industry}_preprocessed.csv"
    if not p.exists():
        print(f"  [{industry}] preprocessed CSV not found — skipping")
        return None
    return pd.read_csv(p, parse_dates=["ds"])


def build_model(params: dict) -> Prophet:
    m = Prophet(
        changepoint_prior_scale = params["changepoint_prior_scale"],
        seasonality_prior_scale = params["seasonality_prior_scale"],
        seasonality_mode        = params["seasonality_mode"],
        yearly_seasonality      = True,
        weekly_seasonality      = False,
        daily_seasonality       = False,
        holidays                = CUSTOM_HOLIDAYS,
        n_changepoints          = N_CHANGEPOINTS,   # FIX-3
    )
    try:
        m.add_country_holidays(country_name="TN")
    except Exception:
        pass
    m.add_regressor("n_posts_scaled")
    m.add_regressor("is_ramadan")
    m.add_regressor("is_summer_peak")
    return m


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


def assign_intensity(yhat: pd.Series) -> list[str]:
    mu, sig = yhat.mean(), yhat.std()
    hi, lo = mu + 0.5 * sig, mu - 0.5 * sig
    out = []
    for v in yhat:
        out.append("high" if v >= hi else "low" if v <= lo else "normal")
    return out


def posts_for_intensity(intensity: str) -> int:
    return {"high": 6, "normal": 3, "low": 1}[intensity]


def compute_seasonality_insights(df_train: pd.DataFrame,
                                 forecast_full: pd.DataFrame) -> dict:
    annual_mean = float(df_train["y"].mean())
    fc = forecast_full.copy()
    fc["month"] = fc["ds"].dt.month
    monthly_mean = fc.groupby("month")["yhat"].mean().sort_values()
    best_months  = sorted(int(m) for m in monthly_mean.tail(3).index.tolist())
    worst_months = sorted(int(m) for m in monthly_mean.head(3).index.tolist())

    ramadan_mask = pd.Series(False, index=fc.index)
    for start, end in RAMADAN_RANGES:
        ramadan_mask |= (fc["ds"] >= start) & (fc["ds"] <= end)
    ramadan_mean = fc.loc[ramadan_mask, "yhat"].mean() if ramadan_mask.any() else annual_mean
    ramadan_lift = round(float(ramadan_mean / annual_mean), 4) if annual_mean else 1.0

    summer_mask = fc["month"].isin([6, 7, 8])
    summer_mean = fc.loc[summer_mask, "yhat"].mean() if summer_mask.any() else annual_mean
    summer_drop = round(float(summer_mean / annual_mean), 4) if annual_mean else 1.0

    return {
        "best_months"           : best_months,
        "worst_months"          : worst_months,
        "ramadan_lift"          : ramadan_lift,
        "summer_drop"           : summer_drop,
        "annual_mean_engagement": round(annual_mean, 6),
    }


# ── Plotting ──────────────────────────────────────────────────────────────────

def plot_forecast(industry, df_train, forecast_future, forecast_full):
    fig, ax = plt.subplots(figsize=(14, 5))
    ax.plot(df_train["ds"], df_train["y"], color="steelblue",
            linewidth=1.2, label="Actual (weekly avg)", alpha=0.8)
    ax.plot(forecast_full["ds"], forecast_full["yhat"],
            color=INDUSTRY_COLORS[industry], linewidth=1.8,
            label="Prophet fit / forecast")
    ax.fill_between(forecast_future["ds"], forecast_future["yhat_lower"],
                    forecast_future["yhat_upper"], alpha=0.18,
                    color=INDUSTRY_COLORS[industry], label="90% CI (lower≥0)")
    ax.axvline(df_train["ds"].max(), color="grey", linestyle="--",
               linewidth=0.9, label="Forecast start")
    ax.set_title(f"{industry.capitalize()} — Engagement Rate Forecast V3 "
                 f"({FORECAST_WEEKS} weeks)", fontsize=13)
    ax.set_xlabel("Date"); ax.set_ylabel("Engagement Rate (%)")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    fig.autofmt_xdate(); ax.legend(fontsize=9); ax.grid(axis="y", alpha=0.3)
    plt.tight_layout()
    out = PLOTS_DIR / f"{industry}_forecast_v3.png"     # spec filename
    fig.savefig(out, dpi=150); plt.close(fig)
    print(f"    Saved {out.name}")


def plot_components(industry, model, forecast_full):
    fig = model.plot_components(forecast_full)
    fig.suptitle(f"{industry.capitalize()} — Seasonality Components V3",
                 fontsize=12, y=1.01)
    plt.tight_layout()
    out = PLOTS_DIR / f"{industry}_components_v3.png"
    fig.savefig(out, dpi=150, bbox_inches="tight"); plt.close(fig)
    print(f"    Saved {out.name}")


def plot_comparison(all_forecasts):
    fig, ax = plt.subplots(figsize=(15, 6))
    for industry, fc in all_forecasts.items():
        ax.plot(fc["ds"], fc["yhat"], label=industry.capitalize(),
                color=INDUSTRY_COLORS[industry], linewidth=1.8)
        ax.fill_between(fc["ds"], fc["yhat_lower"], fc["yhat_upper"],
                        alpha=0.08, color=INDUSTRY_COLORS[industry])
    ax.set_title(f"All Industries — {FORECAST_WEEKS}-Week Engagement Forecast V3",
                 fontsize=13)
    ax.set_xlabel("Date"); ax.set_ylabel("Predicted Engagement Rate (%)")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=1))
    fig.autofmt_xdate(); ax.legend(fontsize=10); ax.grid(axis="y", alpha=0.3)
    plt.tight_layout()
    out = PLOTS_DIR / "all_industries_comparison_v3.png"
    fig.savefig(out, dpi=150); plt.close(fig)
    print(f"\n  Saved comparison plot → {out.name}")


# ── Per-industry training pipeline ────────────────────────────────────────────

def train_industry(industry: str) -> dict | None:
    print(f"\n  [{industry.upper()}]")

    meta = load_best_params_v3(industry)
    if meta is None:
        return None
    params = meta["best_params"]

    df = load_csv(industry)
    if df is None:
        return None
    required = {"n_posts_scaled", "is_ramadan", "is_summer_peak"}
    if required - set(df.columns):
        print(f"    Missing columns {required - set(df.columns)} — re-run preprocess")
        return None

    print(f"    Params : cps={params['changepoint_prior_scale']} "
          f"sps={params['seasonality_prior_scale']} "
          f"mode={params['seasonality_mode']}  (n_changepoints={N_CHANGEPOINTS})")
    print(f"    Data   : {len(df)} weeks ({df['ds'].min().date()} → "
          f"{df['ds'].max().date()})")

    df_model = df[["ds", "y", "n_posts_scaled", "is_ramadan", "is_summer_peak"]].copy()

    model = build_model(params)
    model.fit(df_model)

    future_base   = model.make_future_dataframe(periods=FORECAST_WEEKS, freq="W")
    future_full   = build_future_regressors(df, future_base)
    forecast_full = model.predict(future_full)

    # FIX-8: engagement rate can't be negative — clip all three forecast
    # columns at 0 BEFORE intensity / posts_recommended / forecast_std /
    # ratio are computed and before the JSON is written.
    forecast_full["yhat"]       = forecast_full["yhat"].clip(lower=0)
    forecast_full["yhat_lower"] = forecast_full["yhat_lower"].clip(lower=0)
    forecast_full["yhat_upper"] = forecast_full["yhat_upper"].clip(lower=0)

    cutoff       = df["ds"].max()
    future_slice = (forecast_full[forecast_full["ds"] > cutoff]
                    .head(FORECAST_WEEKS).reset_index(drop=True))

    # ── FIX-7: automated collapse guard ────────────────────────────────────
    hist_std     = float(np.std(df["y"].to_numpy(), ddof=0))
    forecast_std = float(np.std(future_slice["yhat"].to_numpy(), ddof=0))
    forecast_rng = float(future_slice["yhat"].max() - future_slice["yhat"].min())
    ratio        = forecast_std / hist_std if hist_std else float("nan")
    constraint_satisfied = bool(CONSTRAINT_LOW <= ratio <= CONSTRAINT_HIGH)
    print(f"    Spread : forecast_std={forecast_std:.5f}  hist_std={hist_std:.5f}  "
          f"ratio={ratio:.3f}  constraint_satisfied={constraint_satisfied}")
    if not np.isfinite(ratio) or ratio < GUARD_RATIO:
        raise ValueError(
            f"{industry}: forecast collapsed (ratio={ratio:.3f} < {GUARD_RATIO}). "
            f"V3 constraint violated — DO NOT SHIP.")

    intensities = assign_intensity(future_slice["yhat"])
    future_slice["intensity"]         = intensities
    future_slice["posts_recommended"] = [posts_for_intensity(i) for i in intensities]

    insights = compute_seasonality_insights(df, forecast_full)
    print(f"    Best months  : {insights['best_months']}  "
          f"Worst : {insights['worst_months']}  "
          f"Ramadan×{insights['ramadan_lift']}  Summer×{insights['summer_drop']}")

    forecast_records = [{
        "week"                : row["ds"].strftime("%Y-%m-%d"),
        "predicted_engagement": round(float(row["yhat"]), 6),
        "lower"               : round(float(max(row["yhat_lower"], 0.0)), 6),
        "upper"               : round(float(row["yhat_upper"]), 6),
        "intensity"           : row["intensity"],
        "posts_recommended"   : int(row["posts_recommended"]),
    } for _, row in future_slice.iterrows()]

    sm = meta.get("selected_metrics", {})
    performance = {
        "rmse"                : sm.get("rmse"),
        "mae"                 : sm.get("mae"),
        "mape"                : sm.get("mape"),
        "ci_coverage_pct"     : sm.get("ci_coverage_pct"),
        "forecast_std"        : round(forecast_std, 6),
        "forecast_range"      : round(forecast_rng, 6),
        "ratio"               : round(ratio, 6),
        "constraint_satisfied": constraint_satisfied,
    }

    output = {
        "industry"            : industry,
        "version"             : "v3",
        "generated_at"        : datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "n_training_weeks"    : int(len(df)),
        "forecast_weeks"      : FORECAST_WEEKS,
        "model_params"        : params,
        "n_changepoints"      : N_CHANGEPOINTS,
        "regressors"          : ["n_posts_scaled", "is_ramadan", "is_summer_peak"],
        "constraint_violated" : bool(meta.get("constraint_violated", False)),
        "performance"         : performance,
        "forecast"            : forecast_records,
        "seasonality_insights": insights,
    }

    out_path = DATA_DIR / f"{industry}_forecast_v3.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"    Saved forecast JSON → {out_path.name}")

    plot_forecast(industry, df, future_slice, forecast_full)
    plot_components(industry, model, forecast_full)
    return {"output": output, "future_slice": future_slice}


# ── Final report ──────────────────────────────────────────────────────────────

def print_final_report(results: dict, failures: dict) -> None:
    print("\n" + "=" * 78)
    print("  PROPHET TRAINING V3 — FINAL REPORT")
    print("=" * 78)
    for industry in INDUSTRIES:
        if industry in failures:
            print(f"\n  [{industry.upper()}]  ✗ GUARD TRIPPED — NOT SHIPPED")
            print(f"    {failures[industry]}")
            continue
        r = results.get(industry)
        if r is None:
            print(f"\n  [{industry.upper()}]  — SKIPPED / FAILED")
            continue
        out, fc = r["output"], r["future_slice"]
        p, ins = out["performance"], out["seasonality_insights"]
        nh = int((fc["intensity"] == "high").sum())
        nn = int((fc["intensity"] == "normal").sum())
        nl = int((fc["intensity"] == "low").sum())
        print(f"\n  [{industry.upper()}]")
        print(f"    params            : cps={out['model_params']['changepoint_prior_scale']} "
              f"sps={out['model_params']['seasonality_prior_scale']} "
              f"{out['model_params']['seasonality_mode']}")
        print(f"    CV RMSE/MAE/MAPE  : {p['rmse']} / {p['mae']} / {p['mape']}")
        print(f"    CI coverage %     : {p['ci_coverage_pct']}")
        print(f"    forecast_std      : {p['forecast_std']}  range={p['forecast_range']}")
        print(f"    ratio             : {p['ratio']}  "
              f"constraint_satisfied={p['constraint_satisfied']}  "
              f"constraint_violated(tune)={out['constraint_violated']}")
        print(f"    intensity (12w)   : {nh} high | {nn} normal | {nl} low")
        print(f"    Ramadan×{ins['ramadan_lift']}  Summer×{ins['summer_drop']}  "
              f"best={ins['best_months']} worst={ins['worst_months']}")
    print("\n" + "=" * 78)
    if failures:
        print(f"  {len(failures)} industry(ies) tripped the collapse guard "
              f"(NOT shipped): {list(failures)}")
    print("STOP — visual validation before cleanup + Step-5 integration.\n")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    print("Prophet Final Training V3")
    print(f"Industries : {', '.join(INDUSTRIES)}")
    print(f"Forecast   : {FORECAST_WEEKS} weeks   n_changepoints={N_CHANGEPOINTS}")
    print(f"Guard      : raise if forecast_std/hist_std < {GUARD_RATIO}")
    print("-" * 78)

    results: dict[str, dict] = {}
    failures: dict[str, str] = {}
    future_forecasts: dict[str, pd.DataFrame] = {}

    for industry in INDUSTRIES:
        try:
            r = train_industry(industry)
        except ValueError as exc:                 # FIX-7 guard tripped
            print("    " + "✗" * 60)
            print(f"    GUARD: {exc}")
            print("    " + "✗" * 60)
            failures[industry] = str(exc)
            continue
        if r:
            results[industry] = r
            future_forecasts[industry] = r["future_slice"]

    if future_forecasts:
        plot_comparison(future_forecasts)

    print_final_report(results, failures)
    # Non-zero exit if any industry collapsed — the run is loud, not silent.
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
