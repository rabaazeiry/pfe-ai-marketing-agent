"""Step 4k (V6) — Selective stacking ensemble: RF + XGB (vs full RF + XGB + LGB).

V5c finished with three base models that have complementary strengths:
  RF V5c  : best Spearman ρ (0.6626) — wins on RANK ordering
  XGB V5c : best R²(log) (0.4382)   — wins on PREDICTION accuracy
  LGB V5c : middle of the road, no metric champion

Hypothesis: stacking RF + XGB captures the bias diversity, LGB adds noise.
We build V6a (RF + XGB → Ridge) and V6b (RF + XGB + LGB → Ridge), then
pick by a parsimony rule:
  - V6b - V6a < 0.01 R²(log)    -> V6a (parsimony)
  - V6b - V6a >= 0.01 R²(log)   -> V6b (gain worth complexity)

Stacking protocol — Wolpert (1992):
  1. K-fold CV on TRAIN set: each base model trained on K-1 folds, predicts
     the held-out fold -> OOF predictions for the entire train set.
  2. Meta-learner (RidgeCV) trained on (OOF_train, y_train).
  3. Base models retrained on FULL train (already saved as v5c artifacts).
  4. Test prediction = ridge(base.predict(test) for each base).
"""
from __future__ import annotations

import json
import sys
import time
import warnings
from pathlib import Path
from typing import Dict, List, Tuple

import joblib
import lightgbm as lgb
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from scipy.stats import spearmanr
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import RidgeCV
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import KFold, StratifiedShuffleSplit, train_test_split
from xgboost import XGBRegressor

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
MODELS_DIR = ROOT / "models"
VIZ = ROOT / "visualizations" / "v6"
VIZ.mkdir(parents=True, exist_ok=True)
FIG = ROOT / "figures"
FIG.mkdir(parents=True, exist_ok=True)

IN_PATH = DATA / "df_ml_dataset_v5c.parquet"
SEED = 42
NOMINAL_OHE = ["content_type", "industry_simple", "caption_lang"]
DROP_COLS = ["has_caption", "views"]
N_FOLDS = 5
RIDGE_ALPHAS = (0.01, 0.1, 1.0, 10.0, 100.0)

# V4-tuned hyperparameters (mirrored across V5/V5c for consistency).
RF_PARAMS = dict(
    n_estimators=1000, min_samples_split=2, min_samples_leaf=1,
    max_features=0.33, max_depth=None, bootstrap=True,
    random_state=SEED, n_jobs=-1,
)
XGB_PARAMS = dict(
    n_estimators=1000, max_depth=5, learning_rate=0.05,
    subsample=0.7, colsample_bytree=0.7, min_child_weight=5,
    gamma=0, reg_lambda=10,
    objective="reg:squarederror", tree_method="hist",
    random_state=SEED, n_jobs=-1, verbosity=0,
)
LGB_BASE_PARAMS = dict(
    n_estimators=1826, learning_rate=0.0297922,
    num_leaves=61, max_depth=8, min_child_samples=34,
    subsample=0.976562, subsample_freq=0, colsample_bytree=0.597991,
    reg_alpha=2.55297e-08, reg_lambda=8.47175e-06,
    objective="regression", metric="rmse",
    random_state=SEED, n_jobs=-1, verbosity=-1,
)
INDUSTRY_ORDER = ["beauty", "fashion", "hotels", "patisserie", "restaurants"]
INDUSTRY_PALETTE = dict(zip(INDUSTRY_ORDER, sns.color_palette("deep", 5)))
sns.set_theme(context="paper", style="whitegrid", palette="deep")
plt.rcParams.update({
    "figure.dpi": 150, "savefig.dpi": 150,
    "font.family": "DejaVu Sans",
    "axes.titlesize": 12, "axes.labelsize": 10,
    "xtick.labelsize": 9, "ytick.labelsize": 9,
    "legend.fontsize": 9, "figure.titlesize": 14,
})


# --- Pipeline (same split as V5c) ----------------------------------------- #

def _load_and_split() -> Dict[str, object]:
    print(f"Loading {IN_PATH.name} ...")
    df = pd.read_parquet(IN_PATH)
    print(f"  shape: {df.shape}")
    post_id = df["post_id"].copy()
    stratify_key = df["industry_simple"].copy()
    y_orig = df["engagement_rate"].copy()
    y_log = np.log1p(y_orig)

    feat_cols = [c for c in df.columns
                 if c not in {"post_id", "engagement_rate", *DROP_COLS}]
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

    return {
        "X_train": X.iloc[train_idx].reset_index(drop=True),
        "X_test":  X.iloc[test_idx].reset_index(drop=True),
        "y_train_log":  y_log.iloc[train_idx].reset_index(drop=True),
        "y_test_log":   y_log.iloc[test_idx].reset_index(drop=True),
        "y_train_orig": y_orig.iloc[train_idx].reset_index(drop=True),
        "y_test_orig":  y_orig.iloc[test_idx].reset_index(drop=True),
        "post_id_train": post_id.iloc[train_idx].reset_index(drop=True),
        "post_id_test":  post_id.iloc[test_idx].reset_index(drop=True),
        "industry_test": df["industry_simple"].iloc[test_idx].reset_index(drop=True),
    }


# --- Per-metric analysis (Step 1) ----------------------------------------- #

def _load_test_preds_log(model_short: str) -> pd.DataFrame:
    return pd.read_parquet(DATA / f"{model_short}_v5c_predictions.parquet")


def step1_analysis(split: Dict[str, object]) -> Dict[str, object]:
    print("\n" + "=" * 78)
    print("STEP 1 — Per-metric analysis (V5c base models)")
    print("=" * 78)
    y_test_log = split["y_test_log"].values
    y_test_orig = split["y_test_orig"].values
    industry = split["industry_test"]
    post_id_test = split["post_id_test"].astype(str).values

    metrics_per_model: Dict[str, Dict[str, float]] = {}
    test_preds_log: Dict[str, np.ndarray] = {}
    rmse_per_industry: Dict[str, Dict[str, float]] = {}

    for m in ("rf", "xgb", "lgb"):
        df_pred = _load_test_preds_log(m)
        df_pred["post_id"] = df_pred["post_id"].astype(str)
        df_pred = df_pred.set_index("post_id").loc[post_id_test].reset_index()
        y_pred_log = df_pred["y_pred_log"].values
        y_pred_orig = df_pred["y_pred_orig"].values
        rho, _ = spearmanr(y_pred_log, y_test_log)
        metrics_per_model[m] = {
            "r2_log":   float(r2_score(y_test_log, y_pred_log)),
            "r2_orig":  float(r2_score(y_test_orig, y_pred_orig)),
            "rmse_log": float(np.sqrt(mean_squared_error(y_test_log, y_pred_log))),
            "spearman": float(rho),
        }
        test_preds_log[m] = y_pred_log

        # per-industry RMSE
        rmse_by_ind = {}
        for ind in INDUSTRY_ORDER:
            mask = (industry == ind).values
            if mask.sum() == 0:
                rmse_by_ind[ind] = float("nan")
            else:
                rmse_by_ind[ind] = float(np.sqrt(mean_squared_error(
                    y_test_log[mask], y_pred_log[mask])))
        rmse_per_industry[m] = rmse_by_ind

    print("\n  Test-set metrics (V5c base models)")
    print(f"  {'model':<6} {'R²(log)':>10} {'R²(orig)':>10} "
          f"{'RMSE(log)':>10} {'Spearman':>10}")
    for m, d in metrics_per_model.items():
        print(f"  {m.upper():<6} {d['r2_log']:>+10.4f} {d['r2_orig']:>+10.4f} "
              f"{d['rmse_log']:>10.4f} {d['spearman']:>+10.4f}")

    # Best-per-metric
    best = {
        "R²(log)":   max(metrics_per_model, key=lambda m: metrics_per_model[m]["r2_log"]),
        "R²(orig)":  max(metrics_per_model, key=lambda m: metrics_per_model[m]["r2_orig"]),
        "RMSE(log)": min(metrics_per_model, key=lambda m: metrics_per_model[m]["rmse_log"]),
        "Spearman":  max(metrics_per_model, key=lambda m: metrics_per_model[m]["spearman"]),
    }
    print("\n  Best model per metric:")
    for k, v in best.items():
        print(f"    {k:<10} -> {v.upper()}")

    # Per-industry RMSE table
    print("\n  RMSE(log) per industry")
    print(f"  {'industry':<12} " + "  ".join(f"{m.upper():>8}" for m in metrics_per_model))
    for ind in INDUSTRY_ORDER:
        row = "  " + f"{ind:<12} " + "  ".join(
            f"{rmse_per_industry[m][ind]:>8.4f}" for m in metrics_per_model
        )
        print(row)

    # Prediction correlation matrix (Pearson on log predictions, test set)
    pred_df = pd.DataFrame({m.upper(): test_preds_log[m] for m in metrics_per_model})
    corr = pred_df.corr().round(4)
    print("\n  Prediction correlation matrix (Pearson, test set log-preds)")
    print(corr.to_string())

    return dict(
        metrics_per_model=metrics_per_model,
        test_preds_log=test_preds_log,
        rmse_per_industry=rmse_per_industry,
        pred_corr=corr,
    )


# --- OOF predictions (Step 2) --------------------------------------------- #

def _oof_rf(X_train: pd.DataFrame, y_train: pd.Series) -> np.ndarray:
    print("  RF OOF (5-fold) ...")
    oof = np.zeros(len(X_train), dtype=np.float32)
    kf = KFold(n_splits=N_FOLDS, shuffle=True, random_state=SEED)
    t0 = time.perf_counter()
    for fold, (tr, va) in enumerate(kf.split(X_train), 1):
        model = RandomForestRegressor(**RF_PARAMS)
        model.fit(X_train.iloc[tr], y_train.iloc[tr])
        oof[va] = model.predict(X_train.iloc[va]).astype(np.float32)
        print(f"    fold {fold}/{N_FOLDS} done")
    print(f"  RF OOF elapsed: {time.perf_counter() - t0:.1f} s")
    return oof


def _oof_xgb(X_train: pd.DataFrame, y_train: pd.Series) -> np.ndarray:
    print("  XGB OOF (5-fold) ...")
    oof = np.zeros(len(X_train), dtype=np.float32)
    kf = KFold(n_splits=N_FOLDS, shuffle=True, random_state=SEED)
    t0 = time.perf_counter()
    for fold, (tr, va) in enumerate(kf.split(X_train), 1):
        model = XGBRegressor(**XGB_PARAMS)
        model.fit(X_train.iloc[tr], y_train.iloc[tr])
        oof[va] = model.predict(X_train.iloc[va]).astype(np.float32)
        print(f"    fold {fold}/{N_FOLDS} done")
    print(f"  XGB OOF elapsed: {time.perf_counter() - t0:.1f} s")
    return oof


def _oof_lgb(X_train: pd.DataFrame, y_train: pd.Series) -> np.ndarray:
    """Mirror V5c LGB protocol: each fold uses internal 90/10 early-stop refit."""
    print("  LGB OOF (5-fold, with internal early-stop) ...")
    oof = np.zeros(len(X_train), dtype=np.float32)
    kf = KFold(n_splits=N_FOLDS, shuffle=True, random_state=SEED)
    t0 = time.perf_counter()
    for fold, (tr, va) in enumerate(kf.split(X_train), 1):
        X_tr, X_va, y_tr, y_va = train_test_split(
            X_train.iloc[tr], y_train.iloc[tr],
            test_size=0.10, random_state=SEED,
        )
        early = lgb.LGBMRegressor(**LGB_BASE_PARAMS)
        early.fit(X_tr, y_tr, eval_set=[(X_va, y_va)],
                  callbacks=[lgb.early_stopping(stopping_rounds=50, verbose=False)])
        best_iter = int(early.best_iteration_ or LGB_BASE_PARAMS["n_estimators"])
        final_params = {**LGB_BASE_PARAMS, "n_estimators": best_iter}
        model = lgb.LGBMRegressor(**final_params)
        model.fit(X_train.iloc[tr], y_train.iloc[tr])
        oof[va] = model.predict(X_train.iloc[va]).astype(np.float32)
        print(f"    fold {fold}/{N_FOLDS} done (best_iter={best_iter})")
    print(f"  LGB OOF elapsed: {time.perf_counter() - t0:.1f} s")
    return oof


def step2_compute_oof(split: Dict[str, object]) -> Dict[str, np.ndarray]:
    print("\n" + "=" * 78)
    print(f"STEP 2 — Compute OOF predictions ({N_FOLDS}-fold CV on train set)")
    print("=" * 78)
    X_train = split["X_train"]; y_train = split["y_train_log"]
    return {
        "rf":  _oof_rf(X_train,  y_train),
        "xgb": _oof_xgb(X_train, y_train),
        "lgb": _oof_lgb(X_train, y_train),
    }


# --- Train V6a / V6b meta-learners --------------------------------------- #

def _evaluate_log(y_test_log, y_test_orig, y_pred_log) -> Dict[str, float]:
    y_pred_orig = np.clip(np.expm1(y_pred_log), a_min=0.0, a_max=None)
    rho, _ = spearmanr(y_pred_log, y_test_log)
    return {
        "r2_log":   float(r2_score(y_test_log, y_pred_log)),
        "r2_orig":  float(r2_score(y_test_orig, y_pred_orig)),
        "rmse_log": float(np.sqrt(mean_squared_error(y_test_log, y_pred_log))),
        "rmse_orig":float(np.sqrt(mean_squared_error(y_test_orig, y_pred_orig))),
        "mae_orig": float(mean_absolute_error(y_test_orig, y_pred_orig)),
        "spearman": float(rho),
    }


def step3_train_meta(
    oof: Dict[str, np.ndarray], split: Dict[str, object],
    test_preds_log: Dict[str, np.ndarray],
) -> Dict[str, object]:
    print("\n" + "=" * 78)
    print("STEP 3 — Train V6a / V6b Ridge meta-learners + evaluate")
    print("=" * 78)
    y_train_log = split["y_train_log"].values
    y_test_log = split["y_test_log"].values
    y_test_orig = split["y_test_orig"].values

    out: Dict[str, object] = {}
    for name, models_used in [("v6a", ("rf", "xgb")),
                              ("v6b", ("rf", "xgb", "lgb"))]:
        X_meta_train = np.column_stack([oof[m] for m in models_used])
        X_meta_test  = np.column_stack([test_preds_log[m] for m in models_used])
        ridge = RidgeCV(alphas=RIDGE_ALPHAS, fit_intercept=True)
        ridge.fit(X_meta_train, y_train_log)
        y_pred_log = ridge.predict(X_meta_test)
        metrics = _evaluate_log(y_test_log, y_test_orig, y_pred_log)
        weights = dict(zip([m.upper() for m in models_used], ridge.coef_.tolist()))
        intercept = float(ridge.intercept_)
        out[name] = dict(
            ridge=ridge, models=models_used, alpha=float(ridge.alpha_),
            weights=weights, intercept=intercept,
            y_pred_log=y_pred_log, metrics=metrics,
        )
        print(f"\n  {name.upper()} ({' + '.join(m.upper() for m in models_used)})")
        print(f"    alpha (chosen):  {ridge.alpha_}")
        print(f"    intercept:       {intercept:+.4f}")
        print(f"    weights:         {weights}")
        print(f"    R²(log)={metrics['r2_log']:+.4f}  "
              f"ρ={metrics['spearman']:+.4f}  "
              f"RMSE(log)={metrics['rmse_log']:.4f}  "
              f"RMSE(orig)={metrics['rmse_orig']:.4f}")
    return out


# --- Decision (Step 4) --------------------------------------------------- #

def step4_decide(meta: Dict[str, object], v5c_metrics: Dict[str, Dict[str, float]]) -> Tuple[str, str, float, float]:
    print("\n" + "=" * 78)
    print("STEP 4 — Decision (V6a vs V6b)")
    print("=" * 78)
    r2_v6a = meta["v6a"]["metrics"]["r2_log"]
    r2_v6b = meta["v6b"]["metrics"]["r2_log"]
    delta = r2_v6b - r2_v6a
    if delta >= 0.01:
        chosen = "v6b"
        rationale = (f"V6b > V6a + 0.01 (Δ={delta:+.4f}) — full stacking "
                     "earns its complexity.")
    else:
        chosen = "v6a"
        rationale = (f"V6b - V6a < 0.01 (Δ={delta:+.4f}) — picking V6a for "
                     "parsimony (RF + XGB suffices).")
    print(f"  V6a R²(log) = {r2_v6a:+.4f}  vs  V6b R²(log) = {r2_v6b:+.4f}  "
          f"(Δ = {delta:+.4f})")
    print(f"  -> Selected: {chosen.upper()}")
    print(f"  Rationale:   {rationale}")
    return chosen, rationale, r2_v6a, r2_v6b


# --- Visualizations (Steps 5, 7) ----------------------------------------- #

def plot_meta_weights(meta: Dict[str, object], chosen: str) -> Path:
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    for ax, name in zip(axes, ("v6a", "v6b")):
        w = meta[name]["weights"]
        labels = list(w.keys()); values = list(w.values())
        colors = ["#3b6e8f" if l == "RF" else
                  "#c46a3a" if l == "XGB" else "#7a9d54" for l in labels]
        bars = ax.bar(labels, values, color=colors, edgecolor="white")
        for b, v in zip(bars, values):
            ax.text(b.get_x() + b.get_width() / 2, v + 0.01,
                    f"{v:+.3f}", ha="center", va="bottom", fontsize=10)
        ax.axhline(0, color="#888", lw=0.6)
        is_chosen = " (selected)" if name == chosen else ""
        ax.set_title(f"{name.upper()} ({' + '.join(meta[name]['models']).upper()}){is_chosen}\n"
                     f"intercept = {meta[name]['intercept']:+.4f}   "
                     f"alpha = {meta[name]['alpha']}")
        ax.set_ylabel("Ridge coefficient")
        ax.grid(axis="y", alpha=0.3)
    fig.suptitle("V6 meta-learner Ridge coefficients\n"
                 "weights blend each base model's log1p prediction; "
                 "negative coef = base over-predicts vs blend",
                 y=1.0)
    plt.tight_layout(rect=[0, 0.04, 1, 0.93])
    out = FIG / "v6_meta_learner_weights.png"
    fig.savefig(out, dpi=150, bbox_inches="tight"); plt.close(fig)
    print(f"  wrote {out.relative_to(ROOT)}")
    # mirror under viz/v6/
    out2 = VIZ / "meta_learner_weights.png"
    out2.write_bytes(out.read_bytes())
    print(f"  wrote {out2.relative_to(ROOT)}")
    return out


def plot_pred_vs_actual_v5c_vs_v6(
    split, meta, chosen,
) -> Path:
    """Side-by-side V5c (best=XGB) vs chosen V6."""
    y_test_log = split["y_test_log"].values
    industry = split["industry_test"]

    # V5c best = XGB (load preds aligned)
    post_id_test = split["post_id_test"].astype(str).values
    df_v5c = pd.read_parquet(DATA / "xgb_v5c_predictions.parquet")
    df_v5c["post_id"] = df_v5c["post_id"].astype(str)
    df_v5c = df_v5c.set_index("post_id").loc[post_id_test].reset_index()

    df_v6 = pd.DataFrame({
        "post_id": post_id_test,
        "y_true_log": y_test_log,
        "y_pred_log": meta[chosen]["y_pred_log"],
    })

    def _scatter(ax, df, title):
        df = df.copy(); df["industry_simple"] = industry.values
        sns.scatterplot(data=df, x="y_true_log", y="y_pred_log",
                        hue="industry_simple", hue_order=INDUSTRY_ORDER,
                        palette=INDUSTRY_PALETTE, s=18, alpha=0.7,
                        edgecolor="white", linewidth=0.25, ax=ax, legend=False)
        r2 = float(r2_score(df["y_true_log"], df["y_pred_log"]))
        rho, _ = spearmanr(df["y_true_log"], df["y_pred_log"])
        rho = float(rho)
        lim_lo = float(min(df["y_true_log"].min(), df["y_pred_log"].min())) - 0.05
        lim_hi = float(max(df["y_true_log"].max(), df["y_pred_log"].max())) + 0.05
        ax.plot([lim_lo, lim_hi], [lim_lo, lim_hi], "r--", lw=1.0, label="y = x")
        ax.set_xlim(lim_lo, lim_hi); ax.set_ylim(lim_lo, lim_hi)
        ax.set_xlabel("Actual log1p(engagement_rate)")
        ax.set_ylabel("Predicted log1p(engagement_rate)")
        ax.set_title(f"{title}\nR² = {r2:+.4f}    ρ = {rho:+.4f}    n = {len(df):,}")
        return r2, rho

    fig, axes = plt.subplots(1, 2, figsize=(14, 7))
    r2a, rhoa = _scatter(axes[0], df_v5c, "XGB V5c (V5c champion)")
    r2b, rhob = _scatter(axes[1], df_v6,  f"{chosen.upper()} stacking ({' + '.join(meta[chosen]['models']).upper()})")
    fig.suptitle(
        f"V5c champion vs V6 stacking — predicted vs actual    "
        f"ΔR²={r2b - r2a:+.4f}    Δρ={rhob - rhoa:+.4f}",
        y=1.0,
    )
    handles = [plt.Line2D([0], [0], marker="o", color="w",
                          markerfacecolor=INDUSTRY_PALETTE[i],
                          markersize=8, label=i) for i in INDUSTRY_ORDER]
    handles.append(plt.Line2D([0], [0], linestyle="--", color="red", label="y = x"))
    fig.legend(handles=handles, loc="lower center", ncol=6, frameon=True,
               bbox_to_anchor=(0.5, -0.02))
    plt.tight_layout(rect=[0, 0.05, 1, 0.96])
    out = VIZ / "compare_v5c_vs_v6_pred_vs_actual.png"
    fig.savefig(out, dpi=150, bbox_inches="tight"); plt.close(fig)
    print(f"  wrote {out.relative_to(ROOT)}")
    return out


def plot_v6_residuals(split, meta, chosen) -> Path:
    y_test_log = split["y_test_log"].values
    y_pred_log = meta[chosen]["y_pred_log"]
    residual = y_test_log - y_pred_log
    fig, ax = plt.subplots(figsize=(8, 5.5))
    ax.scatter(y_pred_log, residual, s=14, alpha=0.55, color="#3b6e8f",
               edgecolor="white", linewidth=0.2)
    ax.axhline(0, color="red", lw=1.2, ls="--", label="y = 0")
    order = np.argsort(y_pred_log)
    rolled = pd.Series(residual[order]).rolling(50, center=True).mean().values
    ax.plot(np.array(y_pred_log)[order], rolled, color="#222",
            lw=1.0, alpha=0.8, label="rolling mean (50)")
    mu = float(residual.mean()); sd = float(residual.std())
    ax.set_xlabel("Predicted log1p(engagement_rate)")
    ax.set_ylabel("Residual (actual - predicted)")
    ax.set_title(f"Residuals — {chosen.upper()} stacking\n"
                 f"residual mean = {mu:+.4f}   std = {sd:.4f}")
    ax.legend(loc="upper right", frameon=True)
    plt.tight_layout(rect=[0, 0.03, 1, 1])
    out = VIZ / "v6_residuals.png"
    fig.savefig(out, dpi=150, bbox_inches="tight"); plt.close(fig)
    print(f"  wrote {out.relative_to(ROOT)}")
    return out


def plot_evolution_v3_to_v6(metrics: Dict, v6_r2: float, v6_chosen: str) -> Path:
    """V3 → V4 → V5 → V5c → V6 evolution with per-model bars + V6 overlay."""
    versions = ["v3", "v4", "v5", "v5c"]
    MODELS = ("rf", "xgb", "lgb")
    MODEL_COLORS = {"rf": "#3b6e8f", "xgb": "#c46a3a", "lgb": "#7a9d54"}
    n_v = len(versions); width = 0.26

    fig, ax = plt.subplots(figsize=(11, 6.5))
    x = np.arange(n_v + 1)  # one extra slot for V6
    for i, m in enumerate(MODELS):
        vals = [metrics[(m, v)]["r2_log"] for v in versions]
        bars = ax.bar(x[:n_v] + (i - 1) * width, vals, width=width,
                      color=MODEL_COLORS[m], edgecolor="white", label=m.upper())
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v + 0.005,
                    f"{v:.3f}", ha="center", va="bottom", fontsize=8)

    # V6 single bar (stacking)
    v6_color = "#8856a7"
    bar6 = ax.bar([x[n_v]], [v6_r2], width=width * 1.2,
                  color=v6_color, edgecolor="white",
                  label=f"{v6_chosen.upper()} stacking")
    for b, v in zip(bar6, [v6_r2]):
        ax.text(b.get_x() + b.get_width() / 2, v + 0.005,
                f"{v:.3f}", ha="center", va="bottom", fontsize=9, fontweight="bold")

    # Champion stars
    for i, v in enumerate(versions):
        triple = {m: metrics[(m, v)]["r2_log"] for m in MODELS}
        champ = max(triple, key=triple.get)
        idx = list(MODELS).index(champ)
        ax.scatter([i + (idx - 1) * width], [triple[champ] + 0.025],
                   marker="*", s=220, color="#cc1111", zorder=5,
                   label="version champion" if i == 0 else None)
    # V6 final-champion star
    ax.scatter([x[n_v]], [v6_r2 + 0.025],
               marker="*", s=260, color="#cc1111", zorder=5)

    labels = [v.upper() for v in versions] + [f"V6\n({v6_chosen.upper()})"]
    ax.set_xticks(x); ax.set_xticklabels(labels)
    ax.set_ylabel("R² (log1p engagement_rate)")
    ax.set_title("Model evolution V3 → V4 → V5 → V5c → V6 (stacking)\n"
                 "★ = best per-version model")
    ax.legend(loc="lower right", frameon=True)
    ax.grid(axis="y", alpha=0.3)
    ax.set_ylim(0, max(*[metrics[k]["r2_log"] for k in metrics], v6_r2) * 1.18)
    plt.tight_layout()
    out = VIZ / "v3_v4_v5_v5c_v6_evolution.png"
    fig.savefig(out, dpi=150, bbox_inches="tight"); plt.close(fig)
    print(f"  wrote {out.relative_to(ROOT)}")
    return out


# --- Helper: collect prior-version R² from results.txt ------------------- #

import re
_R2_RE = re.compile(r"R[²2\^]+\s*\(log1p scale\)[^+\-0-9]*([+-]?\d*\.\d+)")
_RHO_RE = re.compile(r"Spearman\s+(?:ρ|rho)\s*\(pred,y\)[^+\-0-9]*([+-]?\d*\.\d+)")


def _read_metric(path: Path, regex: re.Pattern) -> float:
    if not path.exists(): return float("nan")
    txt = path.read_text(encoding="utf-8", errors="replace")
    m = regex.search(txt)
    return float(m.group(1)) if m else float("nan")


def collect_history() -> Dict[Tuple[str, str], Dict[str, float]]:
    out = {}
    for m in ("rf", "xgb", "lgb"):
        for v in ("v3", "v4", "v5", "v5c"):
            p = DATA / f"{m}_{v}_results.txt"
            out[(m, v)] = {
                "r2_log":  _read_metric(p, _R2_RE),
                "spearman":_read_metric(p, _RHO_RE),
            }
    return out


# --- Decision report (Step 8) -------------------------------------------- #

def write_decision_report(
    step1: Dict, meta: Dict, chosen: str, rationale: str,
    history: Dict, v6_r2: float, v6_metrics: Dict[str, float],
) -> Path:
    out_path = DATA / "v6_summary_report.txt"
    L: List[str] = []
    L.append("=" * 78)
    L.append("V6 SUMMARY REPORT — Step 4k (selective stacking ensemble)")
    L.append("=" * 78)
    L.append("")
    L.append("Goal: blend complementary V5c base models with a Ridge meta-learner")
    L.append("      trained on out-of-fold predictions.")
    L.append("")
    L.append("Base models (V5c) — per-metric strengths")
    L.append("-" * 78)
    L.append(f"  {'model':<6} {'R²(log)':>10} {'R²(orig)':>10} "
             f"{'RMSE(log)':>10} {'Spearman':>10}")
    for m in ("rf", "xgb", "lgb"):
        d = step1["metrics_per_model"][m]
        L.append(f"  {m.upper():<6} {d['r2_log']:>+10.4f} {d['r2_orig']:>+10.4f} "
                 f"{d['rmse_log']:>10.4f} {d['spearman']:>+10.4f}")
    L.append("")
    L.append("Prediction correlation (test set log-preds, Pearson)")
    L.append("-" * 78)
    L.append(step1["pred_corr"].to_string())
    L.append("")
    L.append("Stacking results")
    L.append("-" * 78)
    base_r2 = max(step1["metrics_per_model"][m]["r2_log"] for m in ("rf", "xgb", "lgb"))
    base_rho = max(step1["metrics_per_model"][m]["spearman"] for m in ("rf", "xgb", "lgb"))
    L.append(f"  {'config':<28} {'R²(log)':>10} {'Spearman':>10} {'RMSE(log)':>10}")
    L.append(f"  {'V5c champion (XGB)':<28} {base_r2:>+10.4f} "
             f"{base_rho:>+10.4f} {step1['metrics_per_model']['xgb']['rmse_log']:>10.4f}  baseline")
    for name in ("v6a", "v6b"):
        info = meta[name]; mt = info["metrics"]
        tag = "(selected)" if name == chosen else ""
        L.append(f"  {name.upper() + ' (' + ' + '.join(m.upper() for m in info['models']) + ')':<28} "
                 f"{mt['r2_log']:>+10.4f} {mt['spearman']:>+10.4f} {mt['rmse_log']:>10.4f}  {tag}")
    L.append("")
    L.append("Meta-learner (Ridge) details — chosen configuration")
    L.append("-" * 78)
    info = meta[chosen]
    L.append(f"  alpha (RidgeCV chose):  {info['alpha']}")
    L.append(f"  intercept:               {info['intercept']:+.6f}")
    for k, v in info["weights"].items():
        L.append(f"  weight {k:<3}              =  {v:+.6f}")
    L.append(f"  weight sum               = {sum(info['weights'].values()):+.6f}")
    L.append("")
    L.append("V3 / V4 / V5 / V5c / V6 ablation table (best-per-version)")
    L.append("-" * 78)
    rows = []
    for v in ("v3", "v4", "v5", "v5c"):
        triple = {m: history[(m, v)]["r2_log"] for m in ("rf", "xgb", "lgb")}
        champ = max(triple, key=triple.get)
        rows.append((v.upper(), champ.upper(), triple[champ]))
    rows.append(("V6", f"stack {chosen.upper()}", v6_r2))
    base_v3 = rows[0][2]
    L.append(f"  {'version':<8} {'best model':<14} {'R²(log)':>10} "
             f"{'Δ vs V3':>10} {'Δ relative':>12}")
    for v, champ, r2 in rows:
        delta = r2 - base_v3
        rel = (delta / base_v3) * 100.0
        L.append(f"  {v:<8} {champ:<14} {r2:>+10.4f} {delta:>+10.4f} "
                 f"{rel:>+11.2f}%")
    L.append("")
    L.append("=" * 78)
    L.append("DECISION")
    L.append("=" * 78)
    L.append(f"  Selected configuration: {chosen.upper()}  "
             f"({' + '.join(m.upper() for m in info['models'])})")
    L.append(f"  Final R²(log):          {v6_r2:+.4f}")
    L.append(f"  Final Spearman ρ:       {v6_metrics['spearman']:+.4f}")
    L.append(f"  Final RMSE(log):        {v6_metrics['rmse_log']:.4f}")
    L.append(f"  Cumulative gain V3→V6:  {v6_r2 - base_v3:+.4f} R² "
             f"({(v6_r2 - base_v3)/base_v3*100:+.2f}% relative)")
    L.append("")
    L.append(f"  Rationale: {rationale}")
    L.append("")
    L.append("Decision criteria")
    L.append("-" * 78)
    L.append("  V6b - V6a < 0.01 R²(log)   -> V6a (parsimony)")
    L.append("  V6b - V6a >= 0.01 R²(log)  -> V6b (complexity earns gain)")
    L.append("=" * 78)
    text = "\n".join(L) + "\n"
    out_path.write_text(text, encoding="utf-8")
    print(f"\n  wrote {out_path.relative_to(ROOT)}")
    return out_path


# --- Main ---------------------------------------------------------------- #

def main() -> int:
    t_total = time.perf_counter()
    print("=" * 78)
    print("Step 4k — V6 selective stacking ensemble (RF + XGB) [+ optional LGB]")
    print("=" * 78)

    split = _load_and_split()
    print(f"  train: {split['X_train'].shape}   test: {split['X_test'].shape}")

    step1 = step1_analysis(split)

    oof = step2_compute_oof(split)
    # Persist OOF arrays for reproducibility / future experiments.
    np.savez(
        DATA / "v6_oof_predictions.npz",
        rf=oof["rf"], xgb=oof["xgb"], lgb=oof["lgb"],
        post_id_train=split["post_id_train"].astype(str).values,
        y_train_log=split["y_train_log"].values,
    )
    print(f"  saved {(DATA / 'v6_oof_predictions.npz').relative_to(ROOT)}")

    meta = step3_train_meta(oof, split, step1["test_preds_log"])
    chosen, rationale, r2_v6a, r2_v6b = step4_decide(meta,
                                                     step1["metrics_per_model"])

    # Persist BOTH meta-learners regardless of which was chosen
    joblib.dump(meta["v6a"]["ridge"], MODELS_DIR / "meta_ridge_v6a.pkl")
    joblib.dump(meta["v6b"]["ridge"], MODELS_DIR / "meta_ridge_v6b.pkl")
    print(f"  saved meta_ridge_v6a.pkl, meta_ridge_v6b.pkl")

    # Save chosen V6 test predictions parquet for downstream tooling
    chosen_meta = meta[chosen]
    pd.DataFrame({
        "post_id":     split["post_id_test"].astype(str).values,
        "y_true_log":  split["y_test_log"].values,
        "y_pred_log":  chosen_meta["y_pred_log"],
        "y_true_orig": split["y_test_orig"].values,
        "y_pred_orig": np.clip(np.expm1(chosen_meta["y_pred_log"]),
                                a_min=0.0, a_max=None),
    }).to_parquet(DATA / "v6_predictions.parquet", index=False)

    print("\n" + "=" * 78)
    print("STEP 5 — Meta-learner weights figure")
    print("=" * 78)
    plot_meta_weights(meta, chosen)

    print("\n" + "=" * 78)
    print("STEP 6 — V3 / V4 / V5 / V5c / V6 ablation")
    print("=" * 78)
    history = collect_history()
    final_r2 = chosen_meta["metrics"]["r2_log"]
    rows = []
    base_v3 = max(history[(m, "v3")]["r2_log"] for m in ("rf", "xgb", "lgb"))
    for v in ("v3", "v4", "v5", "v5c"):
        triple = {m: history[(m, v)]["r2_log"] for m in ("rf", "xgb", "lgb")}
        champ = max(triple, key=triple.get)
        rows.append((v.upper(), champ.upper(), triple[champ]))
    rows.append(("V6", f"stack {chosen.upper()}", final_r2))
    print(f"  {'version':<8} {'best model':<14} {'R²(log)':>10} "
          f"{'Δ vs V3':>10} {'Δ relative':>12}")
    for v, champ, r2 in rows:
        delta = r2 - base_v3
        rel = (delta / base_v3) * 100.0
        print(f"  {v:<8} {champ:<14} {r2:>+10.4f} {delta:>+10.4f} "
              f"{rel:>+11.2f}%")

    print("\n" + "=" * 78)
    print("STEP 7 — Comparison + residuals + evolution figures")
    print("=" * 78)
    plot_pred_vs_actual_v5c_vs_v6(split, meta, chosen)
    plot_v6_residuals(split, meta, chosen)
    plot_evolution_v3_to_v6(history, final_r2, chosen)

    print("\n" + "=" * 78)
    print("STEP 8 — Decision report")
    print("=" * 78)
    write_decision_report(step1, meta, chosen, rationale, history,
                          final_r2, chosen_meta["metrics"])

    print(f"\nTotal elapsed: {(time.perf_counter() - t_total)/60:.2f} min")
    return 0


if __name__ == "__main__":
    warnings.filterwarnings("ignore", category=UserWarning, module="matplotlib")
    sys.exit(main())
