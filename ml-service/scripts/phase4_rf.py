"""Phase 4.1 — Random Forest regression on engagement_rate.

Trains a Random Forest on the Phase-3 ML dataset and tunes hyperparameters
via 10-fold randomized search. Saves the best model, predictions, results
report, and a SHAP-based feature-importance plot.

Hyperparameter ranges and methodology follow:
  - Breiman (2001) "Random Forests" — defaults for max_features (sqrt for
    classification / 1/3 for regression) and min_samples_leaf.
  - Probst & Boulesteix (2018) "To tune or not to tune the number of trees
    in random forest" — n_estimators stabilizes after a few hundred trees;
    [100, 300, 500, 1000] covers the empirically-observed plateau.
  - Probst, Wright & Boulesteix (2019) "Hyperparameters and Tuning Strategies
    for Random Forest" — max_depth and min_samples_split ranges.
  - Bergstra & Bengio (2012) "Random Search for Hyper-Parameter Optimization"
    — random search empirically matches/beats grid search at a fraction of
    the budget for high-dim tuning spaces.

Target transform: np.log1p(engagement_rate) for training (heavy right
skew confirmed in Phase 3 — median 0.07, p99 6.80). Predictions inverted
via np.expm1 (clipped at 0) for original-scale metrics.
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
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import (
    KFold,
    RandomizedSearchCV,
    StratifiedShuffleSplit,
    train_test_split,
)

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent

# --- Dataset version switch -----------------------------------------------
# "v2" → original 4127-row dataset (df_ml_dataset.parquet, rf_best.pkl, ...)
# "v3" → outlier-filtered 4087-row dataset; outputs get "_v3" suffix so the
#        V2 model artifacts (rf_best.pkl, rf_results.txt) stay intact.
# Override from CLI: `python phase4_rf.py v2`
DATASET_VERSION = sys.argv[1] if len(sys.argv) > 1 else "v3"
assert DATASET_VERSION in {"v2", "v3"}, \
    f"DATASET_VERSION must be 'v2' or 'v3', got {DATASET_VERSION!r}"

if DATASET_VERSION == "v2":
    IN_PATH      = ROOT / "data"   / "df_ml_dataset.parquet"
    MODEL_PATH   = ROOT / "models" / "rf_best.pkl"
    COLUMNS_PATH = ROOT / "models" / "rf_feature_columns.json"
    RESULTS_PATH = ROOT / "data"   / "rf_results.txt"
    PRED_PATH    = ROOT / "data"   / "rf_predictions.parquet"
    SHAP_HTML    = ROOT / "visualizations" / "v3" / "rf_shap.html"
else:  # v3
    IN_PATH      = ROOT / "data"   / "df_ml_dataset_v3.parquet"
    MODEL_PATH   = ROOT / "models" / "rf_v3.pkl"
    COLUMNS_PATH = ROOT / "models" / "rf_v3_feature_columns.json"
    RESULTS_PATH = ROOT / "data"   / "rf_v3_results.txt"
    PRED_PATH    = ROOT / "data"   / "rf_v3_predictions.parquet"
    SHAP_HTML    = ROOT / "visualizations" / "v3" / "rf_v3_shap.html"

# Reproducibility seed used for split, search, and base estimator.
SEED = 42

# --- Hyperparameter search space -------------------------------------------
# Probst 2018: n_estimators plateau is reached well before 1000 in most
# regression tasks, but include 1000 as a safety upper bound.
# Probst 2019: max_depth=None (unrestricted) is often best for RF; capped
# values guard against overfit on small data.
# Breiman 2001: max_features for regression is conventionally p/3, with
# sqrt(p) as a stronger-randomness alternative. 0.5 is a common middle.
PARAM_DIST: Dict[str, list] = {
    "n_estimators": [100, 300, 500, 1000],         # Probst 2018
    "max_depth": [None, 10, 15, 20, 30],            # Probst 2019
    "min_samples_split": [2, 5, 10, 20],            # Probst 2019
    "min_samples_leaf": [1, 2, 5, 10],              # Breiman 2001
    "max_features": ["sqrt", 0.33, 0.5],            # Breiman 2001 (regression p/3)
    "bootstrap": [True],                            # standard RF
}

NOMINAL_OHE = ["content_type", "industry_simple", "caption_lang"]
# DROP_COLS:
#   has_caption — constant in this dataset (Phase 3 finding).
#   views       — TEMPORAL LEAK. views are a *post-publication* metric; the
#                 deployed agent must predict engagement_rate BEFORE a post is
#                 published, so views are not yet observed at inference time.
#                 Including them inflates offline R² but breaks the production
#                 contract. Removed after the data-leakage audit.
DROP_COLS = ["has_caption", "views"]


def _load_and_prepare() -> Tuple[pd.DataFrame, pd.Series, pd.Series, pd.Series]:
    """Return (X, y_log, y_orig, post_id, stratify_key) ready for the split.

    All boolean cols cast to int8 so they survive sklearn / SHAP unchanged.
    """
    print(f"Loading {IN_PATH} ...")
    df = pd.read_parquet(IN_PATH)
    print(f"  shape: {df.shape}")

    post_id = df["post_id"].copy()
    stratify_key = df["industry_simple"].copy()
    y_orig = df["engagement_rate"].copy()
    y_log = np.log1p(y_orig)

    # Drop traceability + target + constant column from feature matrix.
    feat_cols = [
        c for c in df.columns
        if c not in {"post_id", "engagement_rate", *DROP_COLS}
    ]
    X_raw = df[feat_cols].copy()

    # OHE the three nominal string columns. drop_first=False so every level
    # is visible in feature_importances_ / SHAP output.
    X = pd.get_dummies(X_raw, columns=NOMINAL_OHE, drop_first=False)
    # Cast booleans (incl. the new OHE bool columns) to int8 for downstream
    # tree libs and SHAP. Numeric columns untouched.
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
    """80/20 split. Stratified on industry_simple iff every class has >= 5
    samples (StratifiedShuffleSplit needs that floor); otherwise plain random
    split with the same seed."""
    min_class = int(stratify_key.value_counts().min())
    if min_class >= 5:
        print(f"  stratifying on industry_simple (min class size = {min_class})")
        sss = StratifiedShuffleSplit(n_splits=1, test_size=0.20, random_state=SEED)
        train_idx, test_idx = next(sss.split(X, stratify_key))
    else:
        print(f"  random split (min class size = {min_class} < 5, no stratification)")
        idx = np.arange(len(X))
        train_idx, test_idx = train_test_split(
            idx, test_size=0.20, random_state=SEED,
        )
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
    high-dim tuning spaces. 50 iter × 10-fold = 500 fits."""
    base = RandomForestRegressor(
        random_state=SEED,
        n_jobs=1,    # inner: serial; outer parallelism via search.n_jobs
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
    print(f"Running RandomizedSearchCV: 50 iter × 10-fold = 500 fits ...")
    t0 = time.perf_counter()
    try:
        search.fit(X_train, y_train_log)
    except KeyboardInterrupt:
        elapsed = time.perf_counter() - t0
        print(f"\n  INTERRUPTED after {elapsed:.1f} s — saving best partial model")
        try:
            partial = search.best_estimator_
            partial_path = ROOT / "models" / "rf_best_partial.pkl"
            partial_path.parent.mkdir(parents=True, exist_ok=True)
            joblib.dump(partial, partial_path)
            print(f"  saved partial best to {partial_path}")
        except Exception as save_err:
            print(f"  could not save partial model ({save_err}) — "
                  f"likely no fits completed yet")
        raise
    elapsed = time.perf_counter() - t0
    print(f"  search elapsed: {elapsed:.1f} s ({elapsed/60:.1f} min)")
    return search


def _evaluate(
    model: RandomForestRegressor,
    X_test: pd.DataFrame,
    y_test_log: pd.Series,
    y_test_orig: pd.Series,
) -> Dict[str, float]:
    """Six metrics — log scale and original-scale variants."""
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
        # Stash predictions in the dict for the predictions parquet.
        "_y_pred_log":    y_pred_log,
        "_y_pred_orig":   y_pred_orig,
    }


def _builtin_importance(
    model: RandomForestRegressor,
    feature_names: List[str],
    top_n: int = 15,
) -> List[Tuple[str, float]]:
    pairs = sorted(
        zip(feature_names, model.feature_importances_),
        key=lambda x: -x[1],
    )
    return pairs[:top_n]


def _shap_importance(
    model: RandomForestRegressor,
    X_test: pd.DataFrame,
    top_n: int = 15,
    n_sample: int = 200,
) -> Tuple[List[Tuple[str, float]], np.ndarray, List[str]]:
    """TreeExplainer on a SAMPLE of the test set. Returns top-N by
    mean(|SHAP|), the full mean-abs vector, and the feature-name list
    (column order).

    Sampling rationale: full-test SHAP can take 30+ min on this dataset.
    Lundberg & Lee (2017) "A Unified Approach to Interpreting Model
    Predictions" §5 — mean(|SHAP|) is a stable global summary even on
    a few hundred samples; 200 keeps the run under 5 minutes while
    preserving the top-feature ranking.
    """
    print()
    print(f"Computing SHAP values (TreeExplainer on shap.sample(X_test, "
          f"{n_sample}, random_state={SEED})) ...")
    t0 = time.perf_counter()
    explainer = shap.TreeExplainer(model)
    X_sub = shap.sample(X_test, n_sample, random_state=SEED)
    # shap_values: (n_samples, n_features) for regressors.
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
    """Plotly horizontal bar chart of top-N mean(|SHAP|) features."""
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
        title=f"Random Forest — Top {len(pairs)} features by mean(|SHAP|) "
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
    L: List[str] = []
    L.append("=" * 96)
    L.append("Phase 4.1 — Random Forest regression on engagement_rate")
    L.append("=" * 96)
    L.append(f"  source:        {IN_PATH}")
    L.append(f"  rows train:    {n_train:,}")
    L.append(f"  rows test:     {n_test:,}")
    L.append(f"  search budget: 50 iter × 10-fold = 500 fits "
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
             f"± {cv_std_rmse:.4f}")
    L.append("")
    L.append("Test-set metrics")
    L.append("-" * 96)
    L.append(f"  R² (log1p scale):     {metrics['r2_log']:+.4f}")
    L.append(f"  R² (original scale):  {metrics['r2_orig']:+.4f}")
    L.append(f"  RMSE (log1p scale):   {metrics['rmse_log']:.4f}")
    L.append(f"  RMSE (orig scale):    {metrics['rmse_orig']:.4f}")
    L.append(f"  MAE  (orig scale):    {metrics['mae_orig']:.4f}")
    L.append(f"  Spearman ρ (pred,y):  {metrics['spearman_rho']:+.4f}")
    L.append("")
    L.append("Top 15 features by built-in (Gini-style) importance")
    L.append("-" * 96)
    L.append("  (sklearn impurity-based — biased toward high-cardinality "
             "numerics; SHAP below is the more reliable signal.)")
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
    print(f"Phase 4.1 RF — DATASET_VERSION = {DATASET_VERSION!r}")
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
    print(f"  CV mean RMSE (log): {cv_mean_rmse:.4f} ± {cv_std_rmse:.4f}")

    print()
    print("Evaluating on held-out test set ...")
    metrics = _evaluate(
        best_model, split["X_test"],
        split["y_test_log"], split["y_test_orig"],
    )
    print(f"  R²(log)={metrics['r2_log']:+.4f}  "
          f"R²(orig)={metrics['r2_orig']:+.4f}  "
          f"RMSE(log)={metrics['rmse_log']:.4f}  "
          f"RMSE(orig)={metrics['rmse_orig']:.4f}  "
          f"MAE(orig)={metrics['mae_orig']:.4f}  "
          f"ρ={metrics['spearman_rho']:+.4f}")

    feature_names = list(split["X_train"].columns)
    builtin_top = _builtin_importance(best_model, feature_names, top_n=15)
    shap_top, _, _ = _shap_importance(best_model, split["X_test"], top_n=15)

    # Persist artifacts.
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(best_model, MODEL_PATH)
    COLUMNS_PATH.write_text(json.dumps(feature_names, indent=2),
                            encoding="utf-8")

    _save_predictions(
        split["post_id_test"], split["y_test_log"], split["y_test_orig"],
        metrics["_y_pred_log"], metrics["_y_pred_orig"], PRED_PATH,
    )
    _save_shap_html(shap_top, SHAP_HTML)

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
