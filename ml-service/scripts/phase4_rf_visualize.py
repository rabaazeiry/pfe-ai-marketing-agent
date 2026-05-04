"""Phase 4.1 — Visualizations for the POST-FIX Random Forest model.

Produces 5 thesis-quality plots in visualizations/v3/:
  1. rf_shap_beeswarm.png   — SHAP summary (beeswarm) over 200 sampled
                              test rows (matches phase4_rf.py SHAP run).
  2. rf_pred_vs_actual.png  — log1p predicted vs actual, colored by
                              industry, y=x reference, title with R² + ρ.
  3. rf_residuals.png       — log-scale residuals (y_true - y_pred) vs
                              predicted; y=0 reference + rolling mean.
  4. rf_gini_importance.png — Top-15 built-in (Gini) importances next to
                              top-15 mean(|SHAP|) for direct comparison.
  5. rf_distributions.png   — Overlapping histograms of true vs predicted
                              engagement_rate (original scale + log1p).

Loads the trained model and reconstructs X_test using the SAME pipeline
as scripts/phase4_rf.py (SEED=42, DROP_COLS=['has_caption','views'],
NOMINAL_OHE=['content_type','industry_simple','caption_lang'], stratified
on industry_simple).

SHAP values are computed ONCE on shap.sample(X_test, 200, random_state=42)
and cached to data/_shap_values_cached.npz for re-use between the
beeswarm and the Gini-vs-SHAP comparison plot.
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

ROOT = Path(__file__).resolve().parent.parent

# --- Dataset version switch -----------------------------------------------
# Mirrors phase4_rf.py. v2 reads rf_best.pkl + rf_predictions.parquet and
# writes PNGs without prefix; v3 reads rf_v3.pkl + rf_v3_predictions.parquet
# and writes "rf_v3_*.png" so the V2 PNGs stay intact for side-by-side.
# Override from CLI: `python phase4_rf_visualize.py v2`
DATASET_VERSION = sys.argv[1] if len(sys.argv) > 1 else "v3"
assert DATASET_VERSION in {"v2", "v3"}, \
    f"DATASET_VERSION must be 'v2' or 'v3', got {DATASET_VERSION!r}"

if DATASET_VERSION == "v2":
    MODEL_PATH = ROOT / "models" / "rf_best.pkl"
    DATA_PATH  = ROOT / "data"   / "df_ml_dataset.parquet"
    PRED_PATH  = ROOT / "data"   / "rf_predictions.parquet"
    SHAP_CACHE = ROOT / "data"   / "_shap_values_cached.npz"
    PNG_PREFIX = "rf"
else:  # v3
    MODEL_PATH = ROOT / "models" / "rf_v3.pkl"
    DATA_PATH  = ROOT / "data"   / "df_ml_dataset_v3.parquet"
    PRED_PATH  = ROOT / "data"   / "rf_v3_predictions.parquet"
    # Separate cache so the V2 cache (different X_test rows!) isn't reused.
    SHAP_CACHE = ROOT / "data"   / "_shap_values_cached_rf_v3.npz"
    PNG_PREFIX = "rf_v3"

OUT_DIR = ROOT / "visualizations" / "v3"

SEED = 42
DROP_COLS = ["has_caption", "views"]
NOMINAL_OHE = ["content_type", "industry_simple", "caption_lang"]
SHAP_SAMPLE_N = 200

# --- Style ------------------------------------------------------------------
sns.set_theme(context="paper", style="whitegrid", palette="deep")
plt.rcParams.update({
    "figure.dpi": 150,
    "savefig.dpi": 150,
    "font.family": "DejaVu Sans",
    "axes.titlesize": 13,
    "axes.labelsize": 11,
    "xtick.labelsize": 9,
    "ytick.labelsize": 9,
    "legend.fontsize": 9,
    "figure.titlesize": 14,
})
INDUSTRY_ORDER = ["beauty", "fashion", "hotels", "patisserie", "restaurants"]
INDUSTRY_PALETTE = dict(zip(INDUSTRY_ORDER, sns.color_palette("deep", 5)))
MONO_COLOR = "#3b6e8f"      # muted slate, used for residuals + Gini
SHAP_COLOR = "#c46a3a"      # warm orange for SHAP bars


# --- Pipeline replication --------------------------------------------------- #

def _rebuild_split() -> Tuple[pd.DataFrame, pd.Series, pd.Series, pd.Series]:
    """Replicate phase4_rf.py's _load_and_prepare + _split exactly."""
    df = pd.read_parquet(DATA_PATH)
    post_id = df["post_id"].copy()
    stratify_key = df["industry_simple"].copy()
    y_orig = df["engagement_rate"].copy()
    y_log = np.log1p(y_orig)

    feat_cols = [
        c for c in df.columns
        if c not in {"post_id", "engagement_rate", *DROP_COLS}
    ]
    X_raw = df[feat_cols].copy()
    X = pd.get_dummies(X_raw, columns=NOMINAL_OHE, drop_first=False)
    bool_cols = X.select_dtypes(include="bool").columns
    X[bool_cols] = X[bool_cols].astype("int8")

    min_class = int(stratify_key.value_counts().min())
    if min_class >= 5:
        sss = StratifiedShuffleSplit(n_splits=1, test_size=0.20, random_state=SEED)
        train_idx, test_idx = next(sss.split(X, stratify_key))
    else:
        idx = np.arange(len(X))
        train_idx, test_idx = train_test_split(idx, test_size=0.20, random_state=SEED)

    X_test = X.iloc[test_idx].reset_index(drop=True)
    industry_test = df["industry_simple"].iloc[test_idx].reset_index(drop=True)
    post_id_test = post_id.iloc[test_idx].reset_index(drop=True)
    y_log_test = y_log.iloc[test_idx].reset_index(drop=True)
    return X_test, industry_test, post_id_test, y_log_test


def _caption(fig: plt.Figure, text: str) -> None:
    fig.text(
        0.5, 0.01, text,
        ha="center", va="bottom",
        fontsize=8.5, style="italic", color="#444",
        wrap=True,
    )


# --- SHAP (cached) --------------------------------------------------------- #

def _compute_or_load_shap(
    model, X_test: pd.DataFrame,
) -> Tuple[pd.DataFrame, np.ndarray]:
    """Return (X_sub, shap_values).

    Cache key invariants: identical SEED, sample size, and column order.
    The cache stores X_sub.values + columns + shap_values; the column list
    is verified before reuse.
    """
    cols = np.array(list(X_test.columns))
    if SHAP_CACHE.exists():
        try:
            z = np.load(SHAP_CACHE, allow_pickle=False)
            if (
                z["seed"].item() == SEED
                and z["n_sample"].item() == SHAP_SAMPLE_N
                and len(z["columns"]) == len(cols)
                and (z["columns"] == cols).all()
            ):
                X_sub = pd.DataFrame(z["X_sub"], columns=cols)
                shap_values = z["shap_values"]
                print(f"  SHAP: loaded cache <- {SHAP_CACHE.name}  "
                      f"({shap_values.shape})")
                return X_sub, shap_values
            print("  SHAP: cache present but invariants differ; recomputing")
        except Exception as e:  # noqa: BLE001
            print(f"  SHAP: cache unreadable ({e}); recomputing")

    print(f"  SHAP: computing TreeExplainer on shap.sample(X_test, "
          f"{SHAP_SAMPLE_N}, random_state={SEED}) ...")
    t0 = time.perf_counter()
    explainer = shap.TreeExplainer(model)
    X_sub = shap.sample(X_test, SHAP_SAMPLE_N, random_state=SEED)
    shap_values = explainer.shap_values(X_sub)
    dt = time.perf_counter() - t0
    print(f"  SHAP: computed in {dt:.1f} s  ({shap_values.shape})")

    np.savez(
        SHAP_CACHE,
        seed=np.int32(SEED),
        n_sample=np.int32(SHAP_SAMPLE_N),
        columns=cols,
        X_sub=X_sub.values,
        shap_values=shap_values,
    )
    print(f"  SHAP: cached -> {SHAP_CACHE.name}")
    return X_sub, shap_values


# --- Plot 1: SHAP beeswarm -------------------------------------------------- #

def plot_shap_beeswarm(X_sub: pd.DataFrame, shap_values: np.ndarray) -> None:
    print("[1/5] SHAP beeswarm ...")
    t0 = time.perf_counter()
    plt.figure(figsize=(9, 7))
    shap.summary_plot(
        shap_values, X_sub,
        plot_type="dot",       # beeswarm
        max_display=20,
        show=False,
        plot_size=None,
    )
    fig = plt.gcf()
    fig.suptitle(
        f"SHAP summary (beeswarm) -- Random Forest [{DATASET_VERSION.upper()}]\n"
        f"{len(X_sub)} test-set rows (random_state={SEED})",
        fontsize=13, y=0.995,
    )
    plt.tight_layout(rect=[0, 0.05, 1, 0.97])
    _caption(
        fig,
        "Each dot is one test post. Horizontal position = impact on "
        "log1p(engagement_rate); color = feature value (red high, blue low).",
    )
    out = OUT_DIR / f"{PNG_PREFIX}_shap_beeswarm.png"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    print(f"      wrote {out.name}  ({out.stat().st_size/1024:.1f} KB)  "
          f"[{time.perf_counter()-t0:.1f}s]")


# --- Plot 2: Predicted vs Actual ------------------------------------------- #

def plot_pred_vs_actual(preds: pd.DataFrame, industry: pd.Series) -> None:
    print("[2/5] Predicted vs Actual ...")
    t0 = time.perf_counter()
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
    ax.set_xlim(lim_lo, lim_hi)
    ax.set_ylim(lim_lo, lim_hi)
    ax.set_xlabel("Actual log1p(engagement_rate)")
    ax.set_ylabel("Predicted log1p(engagement_rate)")
    ax.set_title(
        f"Predicted vs Actual -- RF [{DATASET_VERSION.upper()}]\n"
        f"R^2 = {r2:+.4f}    Spearman rho = {rho:+.4f}    n = {len(df):,}"
    )
    ax.legend(title="Industry", loc="upper left", frameon=True)
    plt.tight_layout(rect=[0, 0.04, 1, 1])
    _caption(
        fig,
        "Closer to the dashed y=x line means better calibration. "
        "Systematic vertical offset for an industry indicates per-cohort bias.",
    )
    out = OUT_DIR / f"{PNG_PREFIX}_pred_vs_actual.png"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    print(f"      wrote {out.name}  ({out.stat().st_size/1024:.1f} KB)  "
          f"[{time.perf_counter()-t0:.1f}s]")


# --- Plot 3: Residuals ------------------------------------------------------ #

def plot_residuals(preds: pd.DataFrame) -> None:
    print("[3/5] Residuals ...")
    t0 = time.perf_counter()
    df = preds.copy()
    df["residual_log"] = df["y_true_log"] - df["y_pred_log"]

    fig, ax = plt.subplots(figsize=(8, 5.5))
    ax.scatter(
        df["y_pred_log"], df["residual_log"],
        s=14, alpha=0.55, color=MONO_COLOR, edgecolor="white", linewidth=0.2,
    )
    ax.axhline(0, color="red", lw=1.2, ls="--", label="y = 0")
    order = df["y_pred_log"].argsort()
    rolled = df["residual_log"].iloc[order].rolling(50, center=True).mean()
    ax.plot(
        df["y_pred_log"].iloc[order], rolled,
        color="#222", lw=1.0, alpha=0.8, label="rolling mean (window=50)",
    )
    ax.set_xlabel("Predicted log1p(engagement_rate)")
    ax.set_ylabel("Residual  (actual - predicted)")
    mu = float(df["residual_log"].mean())
    sd = float(df["residual_log"].std())
    ax.set_title(
        f"Residuals vs Predicted -- RF [{DATASET_VERSION.upper()}]\n"
        f"residual mean = {mu:+.4f}   std = {sd:.4f}"
    )
    ax.legend(loc="upper right", frameon=True)
    plt.tight_layout(rect=[0, 0.05, 1, 1])
    _caption(
        fig,
        "Residuals scattered around 0 with no trend = unbiased fit. "
        "A drifting rolling-mean line indicates systematic over/under-prediction.",
    )
    out = OUT_DIR / f"{PNG_PREFIX}_residuals.png"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    print(f"      wrote {out.name}  ({out.stat().st_size/1024:.1f} KB)  "
          f"[{time.perf_counter()-t0:.1f}s]")


# --- Plot 4: Gini importance vs SHAP --------------------------------------- #

def plot_gini_vs_shap(
    model, X_sub: pd.DataFrame, shap_values: np.ndarray,
) -> None:
    print("[4/5] Gini importance + SHAP side-by-side ...")
    t0 = time.perf_counter()
    feature_names = list(X_sub.columns)
    gini = pd.Series(model.feature_importances_, index=feature_names)
    gini_top = gini.sort_values(ascending=True).tail(15)

    shap_imp = pd.Series(np.abs(shap_values).mean(axis=0), index=feature_names)
    shap_top = shap_imp.sort_values(ascending=True).tail(15)

    fig, (axL, axR) = plt.subplots(1, 2, figsize=(13, 7))
    axL.barh(gini_top.index, gini_top.values, color=MONO_COLOR, edgecolor="white")
    axL.set_title("Top 15 -- Built-in (Gini-style) importance")
    axL.set_xlabel("feature_importances_")
    axL.grid(axis="x", alpha=0.3)

    axR.barh(shap_top.index, shap_top.values, color=SHAP_COLOR, edgecolor="white")
    axR.set_title(f"Top 15 -- mean(|SHAP|) on {len(X_sub)} test samples")
    axR.set_xlabel("mean(|SHAP|) on log1p target")
    axR.grid(axis="x", alpha=0.3)

    fig.suptitle(
        f"Feature importance -- Gini vs SHAP (RF [{DATASET_VERSION.upper()}])",
        y=1.0,
    )
    plt.tight_layout(rect=[0, 0.05, 1, 0.97])
    _caption(
        fig,
        "Gini is biased toward high-cardinality numerics; SHAP marginalizes "
        "those biases and is the more reliable signal for thesis discussion.",
    )
    out = OUT_DIR / f"{PNG_PREFIX}_gini_importance.png"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    print(f"      wrote {out.name}  ({out.stat().st_size/1024:.1f} KB)  "
          f"[{time.perf_counter()-t0:.1f}s]")


# --- Plot 5: Distribution overlap ------------------------------------------ #

def plot_distributions(preds: pd.DataFrame) -> None:
    print("[5/5] True vs Predicted distribution ...")
    t0 = time.perf_counter()
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5.5))

    p99 = float(preds["y_true_orig"].quantile(0.99))
    bins = np.linspace(0, p99, 50)
    ax1.hist(
        preds["y_true_orig"].clip(upper=p99), bins=bins,
        alpha=0.55, color=INDUSTRY_PALETTE["fashion"], label="Actual", edgecolor="white",
    )
    ax1.hist(
        preds["y_pred_orig"].clip(upper=p99), bins=bins,
        alpha=0.55, color=MONO_COLOR, label="Predicted", edgecolor="white",
    )
    ax1.set_xlabel("engagement_rate (original scale, capped at p99)")
    ax1.set_ylabel("count")
    ax1.set_title(f"Distribution -- original scale (p99 cap = {p99:.2f})")
    ax1.legend()

    bins_log = np.linspace(
        min(preds["y_true_log"].min(), preds["y_pred_log"].min()),
        max(preds["y_true_log"].max(), preds["y_pred_log"].max()),
        50,
    )
    ax2.hist(
        preds["y_true_log"], bins=bins_log,
        alpha=0.55, color=INDUSTRY_PALETTE["fashion"], label="Actual", edgecolor="white",
    )
    ax2.hist(
        preds["y_pred_log"], bins=bins_log,
        alpha=0.55, color=MONO_COLOR, label="Predicted", edgecolor="white",
    )
    ax2.set_xlabel("log1p(engagement_rate)")
    ax2.set_ylabel("count")
    ax2.set_title("Distribution -- log1p scale (full range)")
    ax2.legend()

    fig.suptitle(
        f"True vs Predicted distribution -- RF [{DATASET_VERSION.upper()}]",
        y=1.0,
    )
    plt.tight_layout(rect=[0, 0.05, 1, 0.96])
    _caption(
        fig,
        "Predicted distribution narrower than actual = model regresses toward "
        "the mean (common with tree ensembles on heavy-tailed targets).",
    )
    out = OUT_DIR / f"{PNG_PREFIX}_distributions.png"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    print(f"      wrote {out.name}  ({out.stat().st_size/1024:.1f} KB)  "
          f"[{time.perf_counter()-t0:.1f}s]")


# --- Main ------------------------------------------------------------------- #

def main() -> None:
    t_total = time.perf_counter()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("=" * 88)
    print(f"phase4_rf_visualize -- DATASET_VERSION = {DATASET_VERSION!r}")
    print(f"  model:  {MODEL_PATH.name}")
    print(f"  data:   {DATA_PATH.name}")
    print(f"  preds:  {PRED_PATH.name}")
    print(f"  PNGs:   {PNG_PREFIX}_*.png  (under {OUT_DIR.relative_to(ROOT)})")
    print("=" * 88)
    print(f"Loading model       <- {MODEL_PATH.name}")
    model = joblib.load(MODEL_PATH)
    print(f"Loading predictions <- {PRED_PATH.name}")
    preds = pd.read_parquet(PRED_PATH)
    print(f"  {len(preds):,} test rows")

    print("Reconstructing X_test (SEED=42, identical pipeline) ...")
    X_test, industry_test, post_id_test, y_log_test = _rebuild_split()
    preds = preds.set_index("post_id").loc[post_id_test.values].reset_index()
    assert len(preds) == len(X_test), "post_id alignment broke between preds and X_test"
    print(f"  X_test: {X_test.shape}   industry counts: "
          f"{industry_test.value_counts().to_dict()}")

    print()
    X_sub, shap_values = _compute_or_load_shap(model, X_test)
    print()

    plot_shap_beeswarm(X_sub, shap_values)
    plot_pred_vs_actual(preds, industry_test)
    plot_residuals(preds)
    plot_gini_vs_shap(model, X_sub, shap_values)
    plot_distributions(preds)

    print()
    print(f"All 5 figures saved under {OUT_DIR}")
    print(f"Total elapsed: {time.perf_counter()-t_total:.1f} s "
          f"({(time.perf_counter()-t_total)/60:.1f} min)")


if __name__ == "__main__":
    # Mute the standard tight_layout / shap noise for a clean log; let
    # genuine warnings (Convergence*, Deprecation*, RuntimeWarning) through.
    warnings.filterwarnings("ignore", category=UserWarning, module="matplotlib")
    main()
