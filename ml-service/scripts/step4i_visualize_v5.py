"""Step 4i — Visualizations for V5 RF / XGB / LGB.

Mirror of phase4_*_visualize.py with three models in one run, writing
all 18 PNG files (6 per model) under visualizations/v5/.

Per model:
  *_distributions.png      — true vs predicted histograms (orig + log1p)
  *_pred_vs_actual.png     — colored by industry, R²+ρ in title
  *_residuals.png          — residuals vs predicted, rolling mean
  *_shap_beeswarm.png      — SHAP beeswarm over 200 sampled test rows
  *_gini_importance.png    — RF: built-in (Gini) vs SHAP side-by-side
  *_gain_vs_shap.png       — XGB/LGB: gain-based vs SHAP side-by-side

Reuses the SHAP cache files written by step4i_train_v5_models.py
(_shap_values_cached_<m>_v5.npz) so we don't recompute SHAP.
"""
from __future__ import annotations

import sys
import time
import warnings
from pathlib import Path
from typing import Tuple

import joblib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
import shap
from scipy.stats import spearmanr
from sklearn.metrics import r2_score
from sklearn.model_selection import StratifiedShuffleSplit, train_test_split

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATA_PATH = DATA / "df_ml_dataset_v5.parquet"
OUT_DIR = ROOT / "visualizations" / "v5"
OUT_DIR.mkdir(parents=True, exist_ok=True)

SEED = 42
SHAP_SAMPLE_N = 200
DROP_COLS = ["has_caption", "views"]
NOMINAL_OHE = ["content_type", "industry_simple", "caption_lang"]

MODELS = [
    # (name, prefix, model_path, pred_path, shap_cache, importance_label)
    ("Random Forest", "rf_v5",
     ROOT / "models" / "rf_v5.pkl",
     DATA / "rf_v5_predictions.parquet",
     DATA / "_shap_values_cached_rf_v5.npz",
     "Built-in (Gini-style) importance",
     "gini_importance"),  # filename suffix for the side-by-side plot
    ("XGBoost", "xgb_v5",
     ROOT / "models" / "xgb_v5.pkl",
     DATA / "xgb_v5_predictions.parquet",
     DATA / "_shap_values_cached_xgb_v5.npz",
     "Gain-based importance",
     "gain_vs_shap"),
    ("LightGBM", "lgb_v5",
     ROOT / "models" / "lgb_v5.pkl",
     DATA / "lgb_v5_predictions.parquet",
     DATA / "_shap_values_cached_lgb_v5.npz",
     "Gain-based importance",
     "gain_vs_shap"),
]

sns.set_theme(context="paper", style="whitegrid", palette="deep")
plt.rcParams.update({
    "figure.dpi": 150, "savefig.dpi": 150,
    "font.family": "DejaVu Sans",
    "axes.titlesize": 13, "axes.labelsize": 11,
    "xtick.labelsize": 9, "ytick.labelsize": 9,
    "legend.fontsize": 9, "figure.titlesize": 14,
})
INDUSTRY_ORDER = ["beauty", "fashion", "hotels", "patisserie", "restaurants"]
INDUSTRY_PALETTE = dict(zip(INDUSTRY_ORDER, sns.color_palette("deep", 5)))
MONO_COLOR = "#3b6e8f"
SHAP_COLOR = "#c46a3a"


def _rebuild_split() -> Tuple[pd.DataFrame, pd.Series, pd.Series, pd.Series]:
    df = pd.read_parquet(DATA_PATH)
    post_id = df["post_id"].copy()
    stratify_key = df["industry_simple"].copy()
    y_log = np.log1p(df["engagement_rate"])

    feat_cols = [
        c for c in df.columns
        if c not in {"post_id", "engagement_rate", *DROP_COLS}
    ]
    X = pd.get_dummies(df[feat_cols].copy(), columns=NOMINAL_OHE, drop_first=False)
    bool_cols = X.select_dtypes(include="bool").columns
    X[bool_cols] = X[bool_cols].astype("int8")

    min_class = int(stratify_key.value_counts().min())
    if min_class >= 5:
        sss = StratifiedShuffleSplit(n_splits=1, test_size=0.20, random_state=SEED)
        train_idx, test_idx = next(sss.split(X, stratify_key))
    else:
        idx = np.arange(len(X))
        train_idx, test_idx = train_test_split(idx, test_size=0.20, random_state=SEED)

    return (
        X.iloc[test_idx].reset_index(drop=True),
        df["industry_simple"].iloc[test_idx].reset_index(drop=True),
        post_id.iloc[test_idx].reset_index(drop=True),
        y_log.iloc[test_idx].reset_index(drop=True),
    )


def _caption(fig: plt.Figure, text: str) -> None:
    fig.text(0.5, 0.01, text, ha="center", va="bottom",
             fontsize=8.5, style="italic", color="#444", wrap=True)


def _load_shap(cache_path: Path, X_test: pd.DataFrame, model) -> Tuple[pd.DataFrame, np.ndarray]:
    """Prefer cache (written by step4i_train_v5_models.py). Fall back to recompute."""
    cols = np.array(list(X_test.columns))
    if cache_path.exists():
        try:
            z = np.load(cache_path, allow_pickle=False)
            if (z["seed"].item() == SEED
                and z["n_sample"].item() == SHAP_SAMPLE_N
                and len(z["columns"]) == len(cols)
                and (z["columns"] == cols).all()):
                X_sub = pd.DataFrame(z["X_sub"], columns=cols)
                shap_values = z["shap_values"]
                print(f"  SHAP loaded from cache: {cache_path.name}  "
                      f"({shap_values.shape})")
                return X_sub, shap_values
            print(f"  SHAP cache invariants differ; recomputing")
        except Exception as e:  # noqa: BLE001
            print(f"  SHAP cache unreadable ({e}); recomputing")

    print(f"  SHAP recompute on shap.sample(X_test, {SHAP_SAMPLE_N}, "
          f"random_state={SEED})")
    explainer = shap.TreeExplainer(model)
    X_sub = shap.sample(X_test, SHAP_SAMPLE_N, random_state=SEED)
    shap_values = explainer.shap_values(X_sub)
    return X_sub, shap_values


# --- Plots --------------------------------------------------------------- #

def plot_shap_beeswarm(X_sub, shap_values, prefix, name) -> None:
    plt.figure(figsize=(9, 7))
    shap.summary_plot(
        shap_values, X_sub, plot_type="dot", max_display=20, show=False,
        plot_size=None,
    )
    fig = plt.gcf()
    fig.suptitle(
        f"SHAP summary (beeswarm) — {name} V5\n"
        f"{len(X_sub)} test-set rows (random_state={SEED})",
        fontsize=13, y=0.995,
    )
    plt.tight_layout(rect=[0, 0.05, 1, 0.97])
    _caption(fig,
             "Each dot is one test post. Horizontal position = impact on "
             "log1p(engagement_rate); color = feature value.")
    out = OUT_DIR / f"{prefix}_shap_beeswarm.png"
    fig.savefig(out, bbox_inches="tight"); plt.close(fig)
    print(f"  wrote {out.name}")


def plot_pred_vs_actual(preds: pd.DataFrame, industry: pd.Series, prefix, name) -> None:
    df = preds.copy()
    df["industry_simple"] = industry.values

    r2 = r2_score(df["y_true_log"], df["y_pred_log"])
    rho, _ = spearmanr(df["y_true_log"], df["y_pred_log"])

    fig, ax = plt.subplots(figsize=(7.5, 7))
    sns.scatterplot(
        data=df, x="y_true_log", y="y_pred_log",
        hue="industry_simple", hue_order=INDUSTRY_ORDER,
        palette=INDUSTRY_PALETTE, s=22, alpha=0.75,
        edgecolor="white", linewidth=0.3, ax=ax,
    )
    lim_lo = float(min(df["y_true_log"].min(), df["y_pred_log"].min())) - 0.05
    lim_hi = float(max(df["y_true_log"].max(), df["y_pred_log"].max())) + 0.05
    ax.plot([lim_lo, lim_hi], [lim_lo, lim_hi], "r--", lw=1.2, label="y = x")
    ax.set_xlim(lim_lo, lim_hi); ax.set_ylim(lim_lo, lim_hi)
    ax.set_xlabel("Actual log1p(engagement_rate)")
    ax.set_ylabel("Predicted log1p(engagement_rate)")
    ax.set_title(f"Predicted vs Actual — {name} V5\n"
                 f"R² = {r2:+.4f}    ρ = {rho:+.4f}    n = {len(df):,}")
    ax.legend(title="Industry", loc="upper left", frameon=True)
    plt.tight_layout(rect=[0, 0.04, 1, 1])
    _caption(fig, "Closer to dashed y=x = better calibration.")
    out = OUT_DIR / f"{prefix}_pred_vs_actual.png"
    fig.savefig(out, bbox_inches="tight"); plt.close(fig)
    print(f"  wrote {out.name}")


def plot_residuals(preds: pd.DataFrame, prefix, name) -> None:
    df = preds.copy()
    df["residual_log"] = df["y_true_log"] - df["y_pred_log"]
    fig, ax = plt.subplots(figsize=(8, 5.5))
    ax.scatter(df["y_pred_log"], df["residual_log"],
               s=14, alpha=0.55, color=MONO_COLOR, edgecolor="white", linewidth=0.2)
    ax.axhline(0, color="red", lw=1.2, ls="--", label="y = 0")
    order = df["y_pred_log"].argsort()
    rolled = df["residual_log"].iloc[order].rolling(50, center=True).mean()
    ax.plot(df["y_pred_log"].iloc[order], rolled,
            color="#222", lw=1.0, alpha=0.8, label="rolling mean (50)")
    ax.set_xlabel("Predicted log1p(engagement_rate)")
    ax.set_ylabel("Residual (actual - predicted)")
    mu = float(df["residual_log"].mean()); sd = float(df["residual_log"].std())
    ax.set_title(f"Residuals vs Predicted — {name} V5\n"
                 f"residual mean = {mu:+.4f}   std = {sd:.4f}")
    ax.legend(loc="upper right", frameon=True)
    plt.tight_layout(rect=[0, 0.05, 1, 1])
    _caption(fig, "Residuals scattered around 0 with no trend = unbiased fit.")
    out = OUT_DIR / f"{prefix}_residuals.png"
    fig.savefig(out, bbox_inches="tight"); plt.close(fig)
    print(f"  wrote {out.name}")


def plot_importance_compare(model, X_sub, shap_values, prefix, name,
                            importance_label, suffix) -> None:
    feature_names = list(X_sub.columns)
    builtin = pd.Series(model.feature_importances_, index=feature_names)
    builtin_top = builtin.sort_values(ascending=True).tail(15)

    shap_imp = pd.Series(np.abs(shap_values).mean(axis=0), index=feature_names)
    shap_top = shap_imp.sort_values(ascending=True).tail(15)

    fig, (axL, axR) = plt.subplots(1, 2, figsize=(13, 7))
    axL.barh(builtin_top.index, builtin_top.values, color=MONO_COLOR, edgecolor="white")
    axL.set_title(f"Top 15 — {importance_label}")
    axL.set_xlabel("feature_importances_")
    axL.grid(axis="x", alpha=0.3)

    axR.barh(shap_top.index, shap_top.values, color=SHAP_COLOR, edgecolor="white")
    axR.set_title(f"Top 15 — mean(|SHAP|) on {len(X_sub)} test samples")
    axR.set_xlabel("mean(|SHAP|) on log1p target")
    axR.grid(axis="x", alpha=0.3)

    fig.suptitle(f"Feature importance — built-in vs SHAP ({name} V5)", y=1.0)
    plt.tight_layout(rect=[0, 0.05, 1, 0.97])
    _caption(fig,
             "Built-in importance is biased toward high-cardinality numerics; "
             "SHAP is the more reliable signal.")
    out = OUT_DIR / f"{prefix}_{suffix}.png"
    fig.savefig(out, bbox_inches="tight"); plt.close(fig)
    print(f"  wrote {out.name}")


def plot_distributions(preds: pd.DataFrame, prefix, name) -> None:
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5.5))
    p99 = float(preds["y_true_orig"].quantile(0.99))
    bins = np.linspace(0, p99, 50)
    ax1.hist(preds["y_true_orig"].clip(upper=p99), bins=bins, alpha=0.55,
             color=INDUSTRY_PALETTE["fashion"], label="Actual", edgecolor="white")
    ax1.hist(preds["y_pred_orig"].clip(upper=p99), bins=bins, alpha=0.55,
             color=MONO_COLOR, label="Predicted", edgecolor="white")
    ax1.set_xlabel("engagement_rate (orig scale, p99 cap)")
    ax1.set_ylabel("count")
    ax1.set_title(f"Distribution — original scale (p99 cap = {p99:.2f})")
    ax1.legend()

    bins_log = np.linspace(
        min(preds["y_true_log"].min(), preds["y_pred_log"].min()),
        max(preds["y_true_log"].max(), preds["y_pred_log"].max()), 50,
    )
    ax2.hist(preds["y_true_log"], bins=bins_log, alpha=0.55,
             color=INDUSTRY_PALETTE["fashion"], label="Actual", edgecolor="white")
    ax2.hist(preds["y_pred_log"], bins=bins_log, alpha=0.55,
             color=MONO_COLOR, label="Predicted", edgecolor="white")
    ax2.set_xlabel("log1p(engagement_rate)")
    ax2.set_ylabel("count")
    ax2.set_title("Distribution — log1p scale")
    ax2.legend()

    fig.suptitle(f"True vs Predicted distribution — {name} V5", y=1.0)
    plt.tight_layout(rect=[0, 0.05, 1, 0.96])
    _caption(fig, "Predicted narrower than actual = regression toward mean.")
    out = OUT_DIR / f"{prefix}_distributions.png"
    fig.savefig(out, bbox_inches="tight"); plt.close(fig)
    print(f"  wrote {out.name}")


def visualize_one(name, prefix, model_path, pred_path, shap_cache,
                  importance_label, suffix) -> None:
    print(f"\n--- {name} ({prefix}) ---")
    model = joblib.load(model_path)
    preds = pd.read_parquet(pred_path)

    X_test, industry_test, post_id_test, _ = _rebuild_split()
    preds = preds.set_index("post_id").loc[post_id_test.values].reset_index()
    assert len(preds) == len(X_test), "post_id alignment broke"

    X_sub, shap_values = _load_shap(shap_cache, X_test, model)

    plot_shap_beeswarm(X_sub, shap_values, prefix, name)
    plot_pred_vs_actual(preds, industry_test, prefix, name)
    plot_residuals(preds, prefix, name)
    plot_importance_compare(model, X_sub, shap_values, prefix, name,
                            importance_label, suffix)
    plot_distributions(preds, prefix, name)


def main() -> int:
    t0 = time.perf_counter()
    print("=" * 78)
    print("Step 4i — Visualize V5 (RF / XGB / LGB)")
    print("=" * 78)
    for cfg in MODELS:
        visualize_one(*cfg)
    print(f"\nAll figures saved under {OUT_DIR}")
    print(f"Elapsed: {time.perf_counter() - t0:.1f} s")
    return 0


if __name__ == "__main__":
    warnings.filterwarnings("ignore", category=UserWarning, module="matplotlib")
    sys.exit(main())
