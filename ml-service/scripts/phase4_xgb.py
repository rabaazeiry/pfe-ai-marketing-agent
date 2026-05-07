"""Phase 4.2 - XGBoost regression on engagement_rate (POST data-leakage fix).

Trains an XGBoost regressor on the same Phase-3 ML dataset, split, target
transform, and evaluation protocol as scripts/phase4_rf.py, so the two
models can be compared head-to-head on identical test rows.

Hyperparameter ranges and methodology references
------------------------------------------------
PRIMARY HYPERPARAMETERS - Sigrist (2026) ETH Zurich shows that for
tree-boosting, all hyperparameters have material effect (no clear
"safe to ignore" subset), so we tune across all of them rather than
fix any to a default.

  - n_estimators:     [100, 300, 500, 1000]
        McPanalytics (2025) - standard XGBoost range 100-1000.
  - max_depth:        [3, 5, 7, 10]
        Chen & Guestrin (2016) "XGBoost: A Scalable Tree Boosting
        System" KDD'16, depth bounded to control variance.
        Confirmed by McPanalytics (2025) standard 3-10.
  - learning_rate:    [0.01, 0.05, 0.1, 0.2]
        McPanalytics (2025) standard 0.01-0.3 range.
        Sigrist (2026) confirms learning rate as critical.

SECONDARY HYPERPARAMETERS - Bartz-Beielstein et al. (2023) Springer
"Case Study II: Tuning of Gradient Boosting (xgboost)" identifies
alpha / lambda / gamma as having the largest effect among the
regularization knobs.

  - subsample:        [0.7, 0.8, 0.9, 1.0]   - standard 0.5-1.0
  - colsample_bytree: [0.7, 0.8, 0.9, 1.0]   - standard 0.3-1.0
  - min_child_weight: [1, 3, 5]              - overfit guard on
                                                noisy features
  - gamma:            [0, 0.1, 0.5, 1.0]
        Bartz-Beielstein (2023) - critical regularization.
  - reg_lambda:       [1, 5, 10]
        Bartz-Beielstein (2023) - L2 regularization.

SEARCH PROTOCOL - identical to phase4_rf.py for fair comparison.
  - RandomizedSearchCV, n_iter=50, 10-fold, scoring=neg_root_mean_squared_error
  - random_state = SEED = 42
  - Bergstra & Bengio (2012) "Random Search for Hyper-Parameter
    Optimization" JMLR 13:281-305 - random search is sample-efficient
    on high-dim tuning spaces.
  - Probst, Boulesteix & Bischl (2019) "Tunability: Importance of
    Hyperparameters of ML Algorithms" JMLR 20:1-32 - guidance on
    which knobs deserve tuning budget.

DOMAIN-SPECIFIC REFERENCE
  - Journal of Media Horizons (2025) Vol. 6 Issue 3 - XGBoost applied
    to Facebook engagement prediction (likes / shares / comments);
    same use case, validates ensemble approach (LightGBM + RF +
    XGBoost) for social-media engagement.

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
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import shap
from scipy.stats import spearmanr
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import (
    KFold,
    RandomizedSearchCV,
    StratifiedShuffleSplit,
    train_test_split,
)
from xgboost import XGBRegressor

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent

# --- Dataset version switch -----------------------------------------------
# Mirrors phase4_rf.py.
# "v2" -> original 4127-row dataset (df_ml_dataset.parquet, xgb_best.pkl, ...)
# "v3" -> outlier-filtered 4087-row dataset; outputs get "_v3" suffix so the
#        V2 model artifacts (xgb_best.pkl, xgb_results.txt) stay intact.
# Override from CLI: `python phase4_xgb.py v2`
DATASET_VERSION = sys.argv[1] if len(sys.argv) > 1 else "v3"
assert DATASET_VERSION in {"v2", "v3", "v4"}, \
    f"DATASET_VERSION must be 'v2', 'v3' or 'v4', got {DATASET_VERSION!r}"

if DATASET_VERSION == "v2":
    IN_PATH      = ROOT / "data"   / "df_ml_dataset.parquet"
    MODEL_PATH   = ROOT / "models" / "xgb_best.pkl"
    COLUMNS_PATH = ROOT / "models" / "xgb_feature_columns.json"
    RESULTS_PATH = ROOT / "data"   / "xgb_results.txt"
    PRED_PATH    = ROOT / "data"   / "xgb_predictions.parquet"
    SHAP_HTML    = ROOT / "visualizations" / "v3" / "xgb_shap.html"
elif DATASET_VERSION == "v3":
    IN_PATH      = ROOT / "data"   / "df_ml_dataset_v3.parquet"
    MODEL_PATH   = ROOT / "models" / "xgb_v3.pkl"
    COLUMNS_PATH = ROOT / "models" / "xgb_v3_feature_columns.json"
    RESULTS_PATH = ROOT / "data"   / "xgb_v3_results.txt"
    PRED_PATH    = ROOT / "data"   / "xgb_v3_predictions.parquet"
    SHAP_HTML    = ROOT / "visualizations" / "v3" / "xgb_v3_shap.html"
else:  # v4 — V3 features + 15 CLIP-PCA dims
    IN_PATH      = ROOT / "data"   / "df_ml_dataset_v4.parquet"
    MODEL_PATH   = ROOT / "models" / "xgb_v4.pkl"
    COLUMNS_PATH = ROOT / "models" / "xgb_v4_feature_columns.json"
    RESULTS_PATH = ROOT / "data"   / "xgb_v4_results.txt"
    PRED_PATH    = ROOT / "data"   / "xgb_v4_predictions.parquet"
    SHAP_HTML    = ROOT / "visualizations" / "v4" / "xgb_v4_shap.html"

# Reproducibility seed - identical to phase4_rf.py.
SEED = 42

# --- Hyperparameter search space ------------------------------------------- #
# See module docstring for full reference list.
PARAM_DIST: Dict[str, list] = {
    # PRIMARY
    "n_estimators":     [100, 300, 500, 1000],   # McPanalytics 2025
    "max_depth":        [3, 5, 7, 10],            # Chen & Guestrin 2016 / McPanalytics 2025
    "learning_rate":    [0.01, 0.05, 0.1, 0.2],   # McPanalytics 2025 / Sigrist 2026
    # SECONDARY (regularization - Bartz-Beielstein 2023)
    "subsample":        [0.7, 0.8, 0.9, 1.0],
    "colsample_bytree": [0.7, 0.8, 0.9, 1.0],
    "min_child_weight": [1, 3, 5],
    "gamma":            [0, 0.1, 0.5, 1.0],       # Bartz-Beielstein 2023
    "reg_lambda":       [1, 5, 10],               # Bartz-Beielstein 2023
}

# Identical preprocessing to phase4_rf.py for fair head-to-head comparison.
NOMINAL_OHE = ["content_type", "industry_simple", "caption_lang"]
DROP_COLS = ["has_caption", "views"]   # has_caption const; views = temporal leak


def _load_and_prepare() -> Tuple[pd.DataFrame, pd.Series, pd.Series, pd.Series, pd.Series]:
    """Mirror of phase4_rf.py:_load_and_prepare. Same OHE, same dtype casts,
    same output: (X, y_log, y_orig, post_id, stratify_key)."""
    print(f"Loading {IN_PATH} ...")
    df = pd.read_parquet(IN_PATH)
    print(f"  shape: {df.shape}")

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
    """Identical 80/20 stratified split to phase4_rf.py:_split."""
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


def _run_search(
    X_train: pd.DataFrame,
    y_train_log: pd.Series,
) -> RandomizedSearchCV:
    """Bergstra & Bengio (2012): random search is sample-efficient on
    high-dim tuning spaces. 50 iter x 10-fold = 500 fits - same budget
    as phase4_rf.py for an apples-to-apples comparison."""
    base = XGBRegressor(
        objective="reg:squarederror",
        tree_method="hist",       # modern fast histogram method
        random_state=SEED,
        n_jobs=1,                 # outer parallelism via search.n_jobs
        verbosity=0,              # silence per-fit chatter; search is verbose=2
    )
    search = RandomizedSearchCV(
        estimator=base,
        param_distributions=PARAM_DIST,
        n_iter=50,
        cv=KFold(n_splits=10, shuffle=True, random_state=SEED),
        scoring="neg_root_mean_squared_error",
        n_jobs=-1,
        random_state=SEED,
        refit=True,
        verbose=2,
    )
    print()
    print(f"Running RandomizedSearchCV: 50 iter x 10-fold = 500 fits ...")
    t0 = time.perf_counter()
    try:
        search.fit(X_train, y_train_log)
    except KeyboardInterrupt:
        elapsed = time.perf_counter() - t0
        print(f"\n  INTERRUPTED after {elapsed:.1f} s - saving best partial model")
        try:
            partial = search.best_estimator_
            partial_path = ROOT / "models" / "xgb_best_partial.pkl"
            partial_path.parent.mkdir(parents=True, exist_ok=True)
            joblib.dump(partial, partial_path)
            print(f"  saved partial best to {partial_path}")
        except Exception as save_err:  # noqa: BLE001
            print(f"  could not save partial model ({save_err}) - "
                  f"likely no fits completed yet")
        raise
    elapsed = time.perf_counter() - t0
    print(f"  search elapsed: {elapsed:.1f} s ({elapsed/60:.1f} min)")
    return search


def _evaluate(
    model: XGBRegressor,
    X_test: pd.DataFrame,
    y_test_log: pd.Series,
    y_test_orig: pd.Series,
) -> Dict[str, float]:
    """Same six metrics as phase4_rf.py - log scale and original-scale."""
    y_pred_log = model.predict(X_test)
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
    model: XGBRegressor,
    feature_names: List[str],
    top_n: int = 15,
) -> List[Tuple[str, float]]:
    """XGBoost feature_importances_ defaults to gain-based importance."""
    pairs = sorted(
        zip(feature_names, model.feature_importances_),
        key=lambda x: -x[1],
    )
    return pairs[:top_n]


def _patch_xgb_base_score_for_shap(model: XGBRegressor) -> None:
    """Workaround for shap × xgboost-3.x incompatibility.

    XGBoost 3.x serializes ``learner_model_param.base_score`` as a JSON
    array string (e.g. '[2.0043461E-1]') to support multi-output / multi-
    class targets. shap 0.49.x's ``XGBTreeModelLoader`` calls
    ``float(learner_model_param["base_score"])`` directly and crashes
    with::

        ValueError: could not convert string to float: '[2.0043461E-1]'

    Mutates the booster's saved config to strip the array wrapping so
    SHAP sees a scalar string. Safe no-op on XGBoost <3 / fixed SHAP.
    """
    booster = model.get_booster()
    cfg = json.loads(booster.save_config())
    bs = cfg.get("learner", {}).get("learner_model_param", {}).get("base_score")
    if isinstance(bs, str) and bs.startswith("[") and bs.endswith("]"):
        scalar = bs[1:-1].split(",")[0].strip()
        cfg["learner"]["learner_model_param"]["base_score"] = scalar
        booster.load_config(json.dumps(cfg))
        print(f"  patched booster.base_score: {bs} -> {scalar} "
              f"(shap × xgb-3.x workaround)")


def _shap_importance(
    model: XGBRegressor,
    X_test: pd.DataFrame,
    top_n: int = 15,
    n_sample: int = 200,
) -> Tuple[List[Tuple[str, float]], np.ndarray, List[str]]:
    """TreeExplainer on shap.sample(X_test, 200, random_state=SEED) -
    identical sample to phase4_rf.py so SHAP rankings are comparable."""
    print()
    print(f"Computing SHAP values (TreeExplainer on shap.sample(X_test, "
          f"{n_sample}, random_state={SEED})) ...")
    t0 = time.perf_counter()
    _patch_xgb_base_score_for_shap(model)
    explainer = shap.TreeExplainer(model)
    X_sub = shap.sample(X_test, n_sample, random_state=SEED)
    shap_values = explainer.shap_values(X_sub)
    elapsed = time.perf_counter() - t0
    print(f"  SHAP elapsed: {elapsed:.1f} s  (over {len(X_sub)} samples)")

    feature_names = list(X_sub.columns)
    mean_abs = np.abs(shap_values).mean(axis=0)
    pairs = sorted(
        zip(feature_names, mean_abs.tolist()),
        key=lambda x: -x[1],
    )
    return pairs[:top_n], mean_abs, feature_names


def _save_shap_html(
    pairs: List[Tuple[str, float]],
    out_path: Path,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    names = [p[0] for p in pairs][::-1]
    values = [p[1] for p in pairs][::-1]
    fig = go.Figure(
        go.Bar(
            x=values, y=names, orientation="h",
            marker={"color": values, "colorscale": "Viridis"},
            hovertemplate="<b>%{y}</b><br>mean|SHAP| = %{x:.4f}<extra></extra>",
        )
    )
    fig.update_layout(
        title=f"XGBoost - Top {len(pairs)} features by mean(|SHAP|) "
              f"on test set",
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
    """Same parquet schema as rf_predictions.parquet."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({
        "post_id":     post_id_test.values,
        "y_true_log":  y_test_log.values,
        "y_pred_log":  y_pred_log,
        "y_true_orig": y_test_orig.values,
        "y_pred_orig": y_pred_orig,
    }).to_parquet(out_path, index=False)


def _format_results(
    search: RandomizedSearchCV,
    metrics: Dict[str, float],
    builtin_top: List[Tuple[str, float]],
    shap_top: List[Tuple[str, float]],
    n_train: int,
    n_test: int,
    elapsed_search: float,
) -> str:
    """Mirrors rf_results.txt structure for easy diff."""
    L: List[str] = []
    L.append("=" * 96)
    L.append("Phase 4.2 - XGBoost regression on engagement_rate")
    L.append("=" * 96)
    L.append(f"  source:        {IN_PATH}")
    L.append(f"  rows train:    {n_train:,}")
    L.append(f"  rows test:     {n_test:,}")
    L.append(f"  search budget: 50 iter x 10-fold = 500 fits "
             f"({elapsed_search:.1f} s)")
    L.append("")
    L.append("Best hyperparameters")
    L.append("-" * 96)
    for k, v in search.best_params_.items():
        L.append(f"  {k:<22} = {v}")
    L.append("")
    cv_results = search.cv_results_
    best_idx = search.best_index_
    cv_mean_rmse = -cv_results["mean_test_score"][best_idx]
    cv_std_rmse = cv_results["std_test_score"][best_idx]
    L.append(f"  CV mean RMSE (log scale): {cv_mean_rmse:.4f}  "
             f"+/- {cv_std_rmse:.4f}")
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
    L.append("  (XGBoost gain-based - average gain in loss-reduction across "
             "all splits using")
    L.append("   that feature; SHAP below is the more reliable global signal.)")
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


def main() -> None:
    print("=" * 96)
    print(f"Phase 4.2 XGB - DATASET_VERSION = {DATASET_VERSION!r}")
    print(f"  in:    {IN_PATH.name}")
    print(f"  model: {MODEL_PATH.name}")
    print(f"  txt:   {RESULTS_PATH.name}")
    print("=" * 96)

    X, y_log, y_orig, post_id, stratify_key = _load_and_prepare()
    split = _split(X, y_log, y_orig, post_id, stratify_key)

    print()
    print(f"Train: {split['X_train'].shape}   Test: {split['X_test'].shape}")

    t0 = time.perf_counter()
    search = _run_search(split["X_train"], split["y_train_log"])
    elapsed_search = time.perf_counter() - t0

    best_model = search.best_estimator_
    print()
    print("Best hyperparameters:")
    for k, v in search.best_params_.items():
        print(f"  {k:<22} = {v}")
    cv_mean_rmse = -search.cv_results_["mean_test_score"][search.best_index_]
    cv_std_rmse = search.cv_results_["std_test_score"][search.best_index_]
    print(f"  CV mean RMSE (log): {cv_mean_rmse:.4f} +/- {cv_std_rmse:.4f}")

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
    builtin_top = _builtin_importance(best_model, feature_names, top_n=15)

    # Persist the safe artifacts BEFORE SHAP so a SHAP failure (e.g. the
    # known shap x xgboost-3.x base_score issue) doesn't lose model +
    # predictions + best params. Report is rewritten after SHAP completes.
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
        search, metrics, builtin_top, shap_top,
        n_train=len(split["X_train"]),
        n_test=len(split["X_test"]),
        elapsed_search=elapsed_search,
    )
    RESULTS_PATH.write_text(text, encoding="utf-8")

    print()
    print(text, end="")


if __name__ == "__main__":
    main()
