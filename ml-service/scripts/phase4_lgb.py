"""Phase 4.3 - LightGBM regression on engagement_rate (V2 / V3 switchable).

Mirror of scripts/phase4_xgb.py for cross-model parity (same train/test
split, same target transform, same evaluation metrics, same artifact
layout). Differences:

  - Hyperparameter SEARCH is Optuna (TPE) instead of sklearn RandomizedSearchCV,
    because LightGBM benefits from log-scale priors over learning_rate /
    n_estimators / reg_alpha / reg_lambda that sklearn's discrete lists
    cannot express. Optuna's TPE samples those priors directly.
  - Each Optuna trial does 5-fold CV with early stopping (callback) on a
    held-out fold; budget per trial is therefore much smaller than RF/XGB's
    10-fold-no-early-stop, but Optuna spends it more carefully.
  - Final refit on full training set uses an internal 90/10 split to set
    `n_estimators` via early stopping (the same callback the trials used).

Hyperparameter search space - LITERATURE-DRIVEN
-----------------------------------------------
Forecastegy (2023) "Optuna LightGBM tuning - Kaggle Grandmaster guide"
  - log-scale prior over `learning_rate` in [0.005, 0.05] for small
    datasets; large `n_estimators` budget compensates.
  - log-scale prior over `n_estimators` in [100, 2000].

High Per Parameter (arXiv 2207.06028, 250-dataset benchmark)
  - `num_leaves` is the single most-impactful LightGBM hyperparameter;
    search [15, 63] (LightGBM's default 31 is the centre of mass).
  - L1 / L2 (`reg_alpha` / `reg_lambda`) span 8 orders of magnitude
    [1e-8, 10] on log scale to let TPE prune effectively.

Sigrist (2025) "Tree-Boosting On 2592 Tabular Datasets" ScienceDirect
  - For n < 10000, cap `max_depth` at 8 and require
    `min_child_samples` >= 10 to control variance.

Numerai forum - small-dataset LightGBM best practices
  - `subsample_freq` >= 1 + `subsample` < 1.0 (bagging) is essential
    for n < 5000; without it LightGBM tends to memorise.

Optuna LightGBM Tuner (Ozaki et al., 2020 KDD'20)
  - TPE > RandomSearch on tree-boosting search spaces by 30-40%
    sample efficiency; 50 trials of TPE comparable to 200+ of random.

Domain reference - Journal of Media Horizons (2025) Vol. 6 Issue 3
  - LightGBM applied to Facebook engagement prediction in a similar
    feature regime; validates the use of GBDTs for this target.

Target transform: np.log1p(engagement_rate). Predictions inverted via
np.expm1 (clipped at 0) for original-scale metrics.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple

import joblib
import lightgbm as lgb
import numpy as np
import optuna
import pandas as pd
import plotly.graph_objects as go
import shap
from scipy.stats import spearmanr
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import (
    KFold,
    StratifiedShuffleSplit,
    train_test_split,
)

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent

# --- Dataset version switch -----------------------------------------------
# Mirrors phase4_xgb.py / phase4_rf.py.
# v2 -> df_ml_dataset.parquet, lgb_best.pkl, ...
# v3 -> df_ml_dataset_v3.parquet, lgb_v3.pkl, ...
# Override from CLI: `python phase4_lgb.py v2`
DATASET_VERSION = sys.argv[1] if len(sys.argv) > 1 else "v3"
assert DATASET_VERSION in {"v2", "v3", "v4"}, \
    f"DATASET_VERSION must be 'v2', 'v3' or 'v4', got {DATASET_VERSION!r}"

if DATASET_VERSION == "v2":
    IN_PATH      = ROOT / "data"   / "df_ml_dataset.parquet"
    MODEL_PATH   = ROOT / "models" / "lgb_best.pkl"
    COLUMNS_PATH = ROOT / "models" / "lgb_feature_columns.json"
    RESULTS_PATH = ROOT / "data"   / "lgb_results.txt"
    PRED_PATH    = ROOT / "data"   / "lgb_predictions.parquet"
    SHAP_HTML    = ROOT / "visualizations" / "v3" / "lgb_shap.html"
elif DATASET_VERSION == "v3":
    IN_PATH      = ROOT / "data"   / "df_ml_dataset_v3.parquet"
    MODEL_PATH   = ROOT / "models" / "lgb_v3.pkl"
    COLUMNS_PATH = ROOT / "models" / "lgb_v3_feature_columns.json"
    RESULTS_PATH = ROOT / "data"   / "lgb_v3_results.txt"
    PRED_PATH    = ROOT / "data"   / "lgb_v3_predictions.parquet"
    SHAP_HTML    = ROOT / "visualizations" / "v3" / "lgb_v3_shap.html"
else:  # v4 — V3 features + 15 CLIP-PCA dims
    IN_PATH      = ROOT / "data"   / "df_ml_dataset_v4.parquet"
    MODEL_PATH   = ROOT / "models" / "lgb_v4.pkl"
    COLUMNS_PATH = ROOT / "models" / "lgb_v4_feature_columns.json"
    RESULTS_PATH = ROOT / "data"   / "lgb_v4_results.txt"
    PRED_PATH    = ROOT / "data"   / "lgb_v4_predictions.parquet"
    SHAP_HTML    = ROOT / "visualizations" / "v4" / "lgb_v4_shap.html"

SEED = 42

# Identical preprocessing to phase4_xgb.py / phase4_rf.py (head-to-head).
NOMINAL_OHE = ["content_type", "industry_simple", "caption_lang"]
DROP_COLS   = ["has_caption", "views"]   # has_caption const; views temporal leak

# Optuna search budget. 50 trials × 5-fold CV = 250 inner fits, plus
# early stopping shrinks each fit's effective tree count.
N_TRIALS    = 50
INNER_KFOLD = 5
EARLY_STOP  = 50          # early_stopping_rounds inside each CV fold + final refit
FINAL_REFIT_VAL_FRAC = 0.10   # held-out fraction for early-stop on full-train refit


# --- Pipeline (identical to RF / XGB scripts) ----------------------------- #

def _load_and_prepare() -> Tuple[pd.DataFrame, pd.Series, pd.Series,
                                 pd.Series, pd.Series]:
    """Same as phase4_xgb.py:_load_and_prepare. OHE + bool->int8."""
    print(f"Loading {IN_PATH} ...")
    df = pd.read_parquet(IN_PATH)
    print(f"  shape: {df.shape}")

    post_id      = df["post_id"].copy()
    stratify_key = df["industry_simple"].copy()
    y_orig       = df["engagement_rate"].copy()
    y_log        = np.log1p(y_orig)

    feat_cols = [
        c for c in df.columns
        if c not in {"post_id", "engagement_rate", *DROP_COLS}
    ]
    X_raw = df[feat_cols].copy()
    X = pd.get_dummies(X_raw, columns=NOMINAL_OHE, drop_first=False)
    bool_cols = X.select_dtypes(include="bool").columns
    X[bool_cols] = X[bool_cols].astype("int8")

    print(f"  feature matrix shape: {X.shape}  (after OHE)")
    print(f"  target log1p stats: mean={y_log.mean():.3f}  "
          f"std={y_log.std():.3f}  max={y_log.max():.3f}")
    return X, y_log, y_orig, post_id, stratify_key


def _split(
    X: pd.DataFrame,
    y_log: pd.Series,
    y_orig: pd.Series,
    post_id: pd.Series,
    stratify_key: pd.Series,
) -> Dict[str, pd.DataFrame | pd.Series | np.ndarray]:
    """Identical 80/20 stratified split to phase4_xgb.py / phase4_rf.py."""
    min_class = int(stratify_key.value_counts().min())
    if min_class >= 5:
        print(f"  stratifying on industry_simple (min class size = {min_class})")
        sss = StratifiedShuffleSplit(n_splits=1, test_size=0.20, random_state=SEED)
        train_idx, test_idx = next(sss.split(X, stratify_key))
    else:
        print(f"  random split (min class size = {min_class} < 5, no stratification)")
        idx = np.arange(len(X))
        train_idx, test_idx = train_test_split(idx, test_size=0.20, random_state=SEED)
    return {
        "X_train": X.iloc[train_idx].reset_index(drop=True),
        "X_test":  X.iloc[test_idx].reset_index(drop=True),
        "y_train_log":  y_log.iloc[train_idx].reset_index(drop=True),
        "y_test_log":   y_log.iloc[test_idx].reset_index(drop=True),
        "y_train_orig": y_orig.iloc[train_idx].reset_index(drop=True),
        "y_test_orig":  y_orig.iloc[test_idx].reset_index(drop=True),
        "post_id_test": post_id.iloc[test_idx].reset_index(drop=True),
    }


# --- Optuna objective ----------------------------------------------------- #

def _suggest_params(trial: optuna.Trial) -> Dict[str, object]:
    """Literature-driven search space - see module docstring for refs."""
    return {
        "objective":         "regression",
        "metric":            "rmse",
        "verbosity":         -1,
        "random_state":      SEED,
        "n_jobs":            1,         # outer parallelism is sequential trials
        # Forecastegy 2023 / Sigrist 2025 - log priors on rate + budget.
        "n_estimators":      trial.suggest_int("n_estimators", 100, 2000, log=True),
        "learning_rate":     trial.suggest_float("learning_rate", 0.005, 0.05, log=True),
        # High Per Parameter 2022 - num_leaves dominates variance.
        "num_leaves":        trial.suggest_int("num_leaves", 15, 63),
        # Sigrist 2025 - cap depth, floor leaf size on small data.
        "max_depth":         trial.suggest_int("max_depth", 4, 8),
        "min_child_samples": trial.suggest_int("min_child_samples", 10, 50),
        # Numerai - bagging essential below n=5000.
        "subsample":         trial.suggest_float("subsample", 0.7, 1.0),
        "subsample_freq":    trial.suggest_int("subsample_freq", 0, 7),
        # Feature fraction.
        "colsample_bytree":  trial.suggest_float("colsample_bytree", 0.5, 1.0),
        # Optuna LightGBM Tuner - log priors over 8 orders of magnitude.
        "reg_alpha":         trial.suggest_float("reg_alpha", 1e-8, 10.0, log=True),
        "reg_lambda":        trial.suggest_float("reg_lambda", 1e-8, 10.0, log=True),
    }


def _objective(
    trial: optuna.Trial,
    X_train: pd.DataFrame,
    y_train_log: pd.Series,
) -> float:
    """5-fold CV RMSE on log scale; early stopping inside each fold."""
    params = _suggest_params(trial)
    kf = KFold(n_splits=INNER_KFOLD, shuffle=True, random_state=SEED)
    fold_rmses: List[float] = []
    for fold_idx, (tr, va) in enumerate(kf.split(X_train)):
        model = lgb.LGBMRegressor(**params)
        model.fit(
            X_train.iloc[tr], y_train_log.iloc[tr],
            eval_set=[(X_train.iloc[va], y_train_log.iloc[va])],
            callbacks=[
                lgb.early_stopping(EARLY_STOP, verbose=False),
                lgb.log_evaluation(0),
            ],
        )
        y_pred = model.predict(X_train.iloc[va])
        fold_rmses.append(float(np.sqrt(mean_squared_error(
            y_train_log.iloc[va], y_pred,
        ))))
    return float(np.mean(fold_rmses))


def _run_optuna(
    X_train: pd.DataFrame,
    y_train_log: pd.Series,
) -> Tuple[Dict[str, object], optuna.Study, float]:
    """Run TPE search; return (best_params, study, elapsed_seconds)."""
    sampler = optuna.samplers.TPESampler(seed=SEED)
    study   = optuna.create_study(direction="minimize", sampler=sampler)
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    print()
    print(f"Running Optuna TPE: {N_TRIALS} trials x {INNER_KFOLD}-fold CV "
          f"(early_stopping={EARLY_STOP}) ...")
    t0 = time.perf_counter()
    try:
        study.optimize(
            lambda t: _objective(t, X_train, y_train_log),
            n_trials=N_TRIALS,
            show_progress_bar=True,
        )
    except KeyboardInterrupt:
        elapsed = time.perf_counter() - t0
        print(f"\n  INTERRUPTED after {elapsed:.1f} s "
              f"({len(study.trials)} trials done)")
        raise
    elapsed = time.perf_counter() - t0
    print(f"  Optuna elapsed: {elapsed:.1f} s ({elapsed/60:.1f} min)  "
          f"({N_TRIALS} trials)")
    return study.best_params, study, elapsed


def _refit_with_early_stopping(
    best_params: Dict[str, object],
    X_train: pd.DataFrame,
    y_train_log: pd.Series,
) -> lgb.LGBMRegressor:
    """Final fit on full training set; uses an internal 90/10 split to
    determine `n_estimators` via early stopping (same protocol as trials)."""
    params = {
        "objective":    "regression",
        "metric":       "rmse",
        "verbosity":    -1,
        "random_state": SEED,
        "n_jobs":       -1,
        **best_params,
    }
    Xtr, Xva, ytr, yva = train_test_split(
        X_train, y_train_log,
        test_size=FINAL_REFIT_VAL_FRAC,
        random_state=SEED,
    )
    model = lgb.LGBMRegressor(**params)
    model.fit(
        Xtr, ytr,
        eval_set=[(Xva, yva)],
        callbacks=[
            lgb.early_stopping(EARLY_STOP, verbose=False),
            lgb.log_evaluation(0),
        ],
    )
    print(f"  refit best_iteration_: {model.best_iteration_}  "
          f"(of {best_params.get('n_estimators', '?')} suggested)")
    return model


# --- Eval / importance / artifacts (mirror of phase4_xgb.py) -------------- #

def _evaluate(
    model: lgb.LGBMRegressor,
    X_test: pd.DataFrame,
    y_test_log: pd.Series,
    y_test_orig: pd.Series,
) -> Dict[str, float]:
    y_pred_log  = model.predict(X_test)
    y_pred_orig = np.clip(np.expm1(y_pred_log), a_min=0.0, a_max=None)
    rho, _ = spearmanr(y_pred_log, y_test_log)
    return {
        "r2_log":         float(r2_score(y_test_log, y_pred_log)),
        "r2_orig":        float(r2_score(y_test_orig, y_pred_orig)),
        "rmse_log":       float(np.sqrt(mean_squared_error(y_test_log, y_pred_log))),
        "rmse_orig":      float(np.sqrt(mean_squared_error(y_test_orig, y_pred_orig))),
        "mae_orig":       float(mean_absolute_error(y_test_orig, y_pred_orig)),
        "spearman_rho":   float(rho),
        "n_test":         int(len(y_test_log)),
        "_y_pred_log":    y_pred_log,
        "_y_pred_orig":   y_pred_orig,
    }


def _builtin_importance(
    model: lgb.LGBMRegressor,
    feature_names: List[str],
    top_n: int = 15,
) -> List[Tuple[str, float]]:
    """LightGBM feature_importances_ defaults to split count.  We use
    importance_type='gain' explicitly via booster_ for fair vs XGBoost."""
    booster = model.booster_
    gains = booster.feature_importance(importance_type="gain")
    pairs = sorted(zip(feature_names, gains.tolist()), key=lambda x: -x[1])
    return pairs[:top_n]


def _shap_importance(
    model: lgb.LGBMRegressor,
    X_test: pd.DataFrame,
    top_n: int = 15,
    n_sample: int = 200,
) -> Tuple[List[Tuple[str, float]], np.ndarray, List[str]]:
    """TreeExplainer on shap.sample(X_test, 200, random_state=SEED)."""
    print()
    print(f"Computing SHAP values (TreeExplainer on shap.sample(X_test, "
          f"{n_sample}, random_state={SEED})) ...")
    t0 = time.perf_counter()
    explainer   = shap.TreeExplainer(model)
    X_sub       = shap.sample(X_test, n_sample, random_state=SEED)
    shap_values = explainer.shap_values(X_sub)
    elapsed     = time.perf_counter() - t0
    print(f"  SHAP elapsed: {elapsed:.1f} s  (over {len(X_sub)} samples)")

    feature_names = list(X_sub.columns)
    mean_abs = np.abs(shap_values).mean(axis=0)
    pairs = sorted(zip(feature_names, mean_abs.tolist()), key=lambda x: -x[1])
    return pairs[:top_n], mean_abs, feature_names


def _save_shap_html(pairs: List[Tuple[str, float]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    names  = [p[0] for p in pairs][::-1]
    values = [p[1] for p in pairs][::-1]
    fig = go.Figure(go.Bar(
        x=values, y=names, orientation="h",
        marker={"color": values, "colorscale": "Viridis"},
        hovertemplate="<b>%{y}</b><br>mean|SHAP| = %{x:.4f}<extra></extra>",
    ))
    fig.update_layout(
        title=f"LightGBM - Top {len(pairs)} features by mean(|SHAP|) on test set",
        xaxis_title="Mean absolute SHAP value (impact on log-engagement_rate)",
        yaxis_title="Feature",
        template="plotly_white",
        height=max(420, 28 * len(pairs)),
        margin={"l": 220, "r": 40, "t": 70, "b": 60},
    )
    fig.write_html(str(out_path))


def _save_predictions(
    post_id_test: pd.Series,
    y_test_log: pd.Series,
    y_test_orig: pd.Series,
    y_pred_log: np.ndarray,
    y_pred_orig: np.ndarray,
    out_path: Path,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({
        "post_id":     post_id_test.values,
        "y_true_log":  y_test_log.values,
        "y_pred_log":  y_pred_log,
        "y_true_orig": y_test_orig.values,
        "y_pred_orig": y_pred_orig,
    }).to_parquet(out_path, index=False)


def _format_results(
    study: optuna.Study,
    metrics: Dict[str, float],
    builtin_top: List[Tuple[str, float]],
    shap_top: List[Tuple[str, float]],
    n_train: int,
    n_test: int,
    elapsed_search: float,
    refit_best_iteration: int,
) -> str:
    L: List[str] = []
    L.append("=" * 96)
    L.append("Phase 4.3 - LightGBM regression on engagement_rate")
    L.append("=" * 96)
    L.append(f"  source:        {IN_PATH}")
    L.append(f"  rows train:    {n_train:,}")
    L.append(f"  rows test:     {n_test:,}")
    L.append(f"  search budget: Optuna TPE, {N_TRIALS} trials x "
             f"{INNER_KFOLD}-fold CV, early_stopping={EARLY_STOP} "
             f"({elapsed_search:.1f} s)")
    L.append("")
    L.append("Best hyperparameters (Optuna)")
    L.append("-" * 96)
    for k, v in study.best_params.items():
        if isinstance(v, float):
            L.append(f"  {k:<22} = {v:.6g}")
        else:
            L.append(f"  {k:<22} = {v}")
    L.append(f"  (refit best_iteration_ on 90/10 internal split: "
             f"{refit_best_iteration})")
    L.append("")
    L.append(f"  Optuna best CV RMSE (log scale): {study.best_value:.4f}")
    L.append("")
    L.append("Test-set metrics")
    L.append("-" * 96)
    L.append(f"  R^2 (log1p scale):     {metrics['r2_log']:+.4f}")
    L.append(f"  R^2 (original scale):  {metrics['r2_orig']:+.4f}")
    L.append(f"  RMSE (log1p scale):    {metrics['rmse_log']:.4f}")
    L.append(f"  RMSE (orig scale):     {metrics['rmse_orig']:.4f}")
    L.append(f"  MAE  (orig scale):     {metrics['mae_orig']:.4f}")
    L.append(f"  Spearman rho (pred,y): {metrics['spearman_rho']:+.4f}")
    L.append("")
    L.append("Top 15 features by built-in (gain-based) importance")
    L.append("-" * 96)
    L.append("  (LightGBM gain - sum of loss-reduction across all splits "
             "using that feature; SHAP")
    L.append("   below is the more reliable global signal.)")
    L.append("")
    L.append(f"  {'rank':<4} {'feature':<30} {'importance':>14}")
    for i, (name, imp) in enumerate(builtin_top, 1):
        L.append(f"  {i:<4} {name:<30} {imp:>14.6f}")
    L.append("")
    L.append("Top 15 features by mean(|SHAP|) on test set")
    L.append("-" * 96)
    L.append(f"  {'rank':<4} {'feature':<30} {'mean|SHAP|':>14}")
    for i, (name, imp) in enumerate(shap_top, 1):
        L.append(f"  {i:<4} {name:<30} {imp:>14.6f}")
    L.append("")
    L.append("Outputs")
    L.append("-" * 96)
    L.append(f"  model:        {MODEL_PATH}")
    L.append(f"  columns:      {COLUMNS_PATH}")
    L.append(f"  predictions:  {PRED_PATH}")
    L.append(f"  shap plot:    {SHAP_HTML}")
    L.append("=" * 96)
    return "\n".join(L) + "\n"


# --- Main ----------------------------------------------------------------- #

def main() -> None:
    print("=" * 96)
    print(f"Phase 4.3 LGB - DATASET_VERSION = {DATASET_VERSION!r}")
    print(f"  in:    {IN_PATH.name}")
    print(f"  model: {MODEL_PATH.name}")
    print(f"  txt:   {RESULTS_PATH.name}")
    print("=" * 96)

    X, y_log, y_orig, post_id, stratify_key = _load_and_prepare()
    split = _split(X, y_log, y_orig, post_id, stratify_key)

    print()
    print(f"Train: {split['X_train'].shape}   Test: {split['X_test'].shape}")

    best_params, study, elapsed_search = _run_optuna(
        split["X_train"], split["y_train_log"],
    )

    print()
    print("Best hyperparameters:")
    for k, v in best_params.items():
        print(f"  {k:<22} = {v}")
    print(f"  Optuna best CV RMSE (log): {study.best_value:.4f}")

    print()
    print("Refitting best model on full training set (early stopping on "
          f"{int(FINAL_REFIT_VAL_FRAC*100)}% holdout) ...")
    best_model = _refit_with_early_stopping(
        best_params, split["X_train"], split["y_train_log"],
    )

    print()
    print("Evaluating on held-out test set ...")
    metrics = _evaluate(
        best_model, split["X_test"],
        split["y_test_log"], split["y_test_orig"],
    )
    print(f"  R2(log)={metrics['r2_log']:+.4f}  "
          f"R2(orig)={metrics['r2_orig']:+.4f}  "
          f"RMSE(log)={metrics['rmse_log']:.4f}  "
          f"RMSE(orig)={metrics['rmse_orig']:.4f}  "
          f"MAE(orig)={metrics['mae_orig']:.4f}  "
          f"rho={metrics['spearman_rho']:+.4f}")

    feature_names = list(split["X_train"].columns)
    builtin_top   = _builtin_importance(best_model, feature_names, top_n=15)

    # Persist safe artifacts BEFORE SHAP so a SHAP failure doesn't lose them.
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(best_model, MODEL_PATH)
    COLUMNS_PATH.write_text(json.dumps(feature_names, indent=2),
                            encoding="utf-8")
    _save_predictions(
        split["post_id_test"], split["y_test_log"], split["y_test_orig"],
        metrics["_y_pred_log"], metrics["_y_pred_orig"], PRED_PATH,
    )
    print(f"  saved: {MODEL_PATH.name}, {COLUMNS_PATH.name}, {PRED_PATH.name}")

    shap_top: List[Tuple[str, float]]
    try:
        shap_top, _, _ = _shap_importance(best_model, split["X_test"], top_n=15)
        _save_shap_html(shap_top, SHAP_HTML)
    except Exception as e:  # noqa: BLE001
        print(f"  SHAP step FAILED: {type(e).__name__}: {e}")
        print(f"  Model + predictions are saved; report will list SHAP as 'unavailable'.")
        shap_top = [("(SHAP unavailable - see log)", 0.0)]

    text = _format_results(
        study, metrics, builtin_top, shap_top,
        n_train=len(split["X_train"]),
        n_test=len(split["X_test"]),
        elapsed_search=elapsed_search,
        refit_best_iteration=int(best_model.best_iteration_ or -1),
    )
    RESULTS_PATH.write_text(text, encoding="utf-8")

    print()
    print(text, end="")


if __name__ == "__main__":
    main()
