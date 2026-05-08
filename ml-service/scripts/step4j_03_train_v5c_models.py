"""Step 4j (V5c) — Train RF / XGB / LGB V5c reusing V4 hyperparameters.

Mirror of step4i_train_v5_models.py with paths swapped V5 -> V5c.
Same hyperparameters, same train/test split, same SHAP protocol.
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
from sklearn.model_selection import StratifiedShuffleSplit, train_test_split

import lightgbm as lgb
from xgboost import XGBRegressor

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
MODELS = ROOT / "models"
VIZ = ROOT / "visualizations" / "v5c"
VIZ.mkdir(parents=True, exist_ok=True)

IN_PATH = DATA / "df_ml_dataset_v5c.parquet"
SEED = 42
NOMINAL_OHE = ["content_type", "industry_simple", "caption_lang"]
DROP_COLS = ["has_caption", "views"]

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
LGB_PARAMS = dict(
    n_estimators=1826, learning_rate=0.0297922,
    num_leaves=61, max_depth=8, min_child_samples=34,
    subsample=0.976562, subsample_freq=0, colsample_bytree=0.597991,
    reg_alpha=2.55297e-08, reg_lambda=8.47175e-06,
    objective="regression", metric="rmse",
    random_state=SEED, n_jobs=-1, verbosity=-1,
)


def _load_and_prepare() -> Dict[str, object]:
    print(f"Loading {IN_PATH.name} ...")
    df = pd.read_parquet(IN_PATH)
    print(f"  shape: {df.shape}")

    post_id = df["post_id"].copy()
    stratify_key = df["industry_simple"].copy()
    y_orig = df["engagement_rate"].copy()
    y_log = np.log1p(y_orig)

    feat_cols = [c for c in df.columns
                 if c not in {"post_id", "engagement_rate", *DROP_COLS}]
    X_raw = df[feat_cols].copy()
    X = pd.get_dummies(X_raw, columns=NOMINAL_OHE, drop_first=False)
    bool_cols = X.select_dtypes(include="bool").columns
    X[bool_cols] = X[bool_cols].astype("int8")
    print(f"  feature matrix shape: {X.shape}  (after OHE)")

    min_class = int(stratify_key.value_counts().min())
    if min_class >= 5:
        sss = StratifiedShuffleSplit(n_splits=1, test_size=0.20, random_state=SEED)
        train_idx, test_idx = next(sss.split(X, stratify_key))
    else:
        idx = np.arange(len(X))
        train_idx, test_idx = train_test_split(idx, test_size=0.20, random_state=SEED)

    out = {
        "X_train": X.iloc[train_idx].reset_index(drop=True),
        "X_test":  X.iloc[test_idx].reset_index(drop=True),
        "y_train_log":  y_log.iloc[train_idx].reset_index(drop=True),
        "y_test_log":   y_log.iloc[test_idx].reset_index(drop=True),
        "y_train_orig": y_orig.iloc[train_idx].reset_index(drop=True),
        "y_test_orig":  y_orig.iloc[test_idx].reset_index(drop=True),
        "post_id_test": post_id.iloc[test_idx].reset_index(drop=True),
    }
    print(f"  train: {out['X_train'].shape}   test: {out['X_test'].shape}")
    return out


def _evaluate(model, X_test, y_test_log, y_test_orig) -> Dict[str, object]:
    y_pred_log = model.predict(X_test)
    y_pred_orig = np.clip(np.expm1(y_pred_log), a_min=0.0, a_max=None)
    rho, _ = spearmanr(y_pred_log, y_test_log)
    return {
        "r2_log":       float(r2_score(y_test_log, y_pred_log)),
        "r2_orig":      float(r2_score(y_test_orig, y_pred_orig)),
        "rmse_log":     float(np.sqrt(mean_squared_error(y_test_log, y_pred_log))),
        "rmse_orig":    float(np.sqrt(mean_squared_error(y_test_orig, y_pred_orig))),
        "mae_orig":     float(mean_absolute_error(y_test_orig, y_pred_orig)),
        "spearman_rho": float(rho),
        "n_test":       int(len(y_test_log)),
        "_y_pred_log":  y_pred_log,
        "_y_pred_orig": y_pred_orig,
    }


def _builtin_top(model, names, top_n=15) -> List[Tuple[str, float]]:
    return sorted(zip(names, model.feature_importances_), key=lambda x: -x[1])[:top_n]


def _patch_xgb_base_score_for_shap(model: XGBRegressor) -> None:
    booster = model.get_booster()
    cfg = json.loads(booster.save_config())
    bs = cfg.get("learner", {}).get("learner_model_param", {}).get("base_score")
    if isinstance(bs, str) and bs.startswith("[") and bs.endswith("]"):
        scalar = bs[1:-1].split(",")[0].strip()
        cfg["learner"]["learner_model_param"]["base_score"] = scalar
        booster.load_config(json.dumps(cfg))


def _shap_top(model, X_test, top_n=15, n_sample=200):
    print(f"  SHAP: TreeExplainer on shap.sample(X_test, {n_sample}, "
          f"random_state={SEED}) ...")
    t0 = time.perf_counter()
    if isinstance(model, XGBRegressor):
        _patch_xgb_base_score_for_shap(model)
    explainer = shap.TreeExplainer(model)
    X_sub = shap.sample(X_test, n_sample, random_state=SEED)
    shap_values = explainer.shap_values(X_sub)
    print(f"  SHAP elapsed: {time.perf_counter() - t0:.1f} s  ({shap_values.shape})")
    mean_abs = np.abs(shap_values).mean(axis=0)
    pairs = sorted(zip(list(X_sub.columns), mean_abs.tolist()), key=lambda x: -x[1])
    return pairs[:top_n], shap_values, X_sub


def _save_shap_html(pairs, out_path: Path, model_name: str) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    names  = [p[0] for p in pairs][::-1]
    values = [p[1] for p in pairs][::-1]
    fig = go.Figure(go.Bar(
        x=values, y=names, orientation="h",
        marker={"color": values, "colorscale": "Viridis"},
        hovertemplate="<b>%{y}</b><br>mean|SHAP| = %{x:.4f}<extra></extra>",
    ))
    fig.update_layout(
        title=f"{model_name} V5c — Top {len(pairs)} features by mean(|SHAP|)",
        xaxis_title="Mean absolute SHAP value (impact on log-engagement_rate)",
        yaxis_title="Feature", template="plotly_white",
        height=max(420, 28 * len(pairs)),
        margin={"l": 240, "r": 40, "t": 70, "b": 60},
    )
    fig.write_html(str(out_path))


def _save_predictions(post_id_test, y_test_log, y_test_orig, y_pred_log, y_pred_orig, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({
        "post_id":     post_id_test.values,
        "y_true_log":  y_test_log.values,
        "y_pred_log":  y_pred_log,
        "y_true_orig": y_test_orig.values,
        "y_pred_orig": y_pred_orig,
    }).to_parquet(out_path, index=False)


def _format_results(name, params, metrics, builtin_top, shap_top,
                    n_train, n_test, elapsed_train, model_path, columns_path,
                    pred_path, shap_html, importance_label) -> str:
    L: List[str] = []
    L.append("=" * 96)
    L.append(f"Step 4j V5c — {name} regression on engagement_rate")
    L.append("=" * 96)
    L.append(f"  source:        {IN_PATH}")
    L.append(f"  rows train:    {n_train:,}")
    L.append(f"  rows test:     {n_test:,}")
    L.append(f"  hyperparams:   reused from V4 best (no random search; "
             f"train elapsed {elapsed_train:.1f} s)")
    L.append("")
    L.append("Hyperparameters (mirrored from V4)")
    L.append("-" * 96)
    for k, v in params.items():
        L.append(f"  {k:<22} = {v}")
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
    L.append(f"Top 15 features by built-in ({importance_label}) importance")
    L.append("-" * 96)
    L.append(f"  {'rank':<4} {'feature':<32} {'importance':>14}")
    for i, (n, imp) in enumerate(builtin_top, 1):
        L.append(f"  {i:<4} {n:<32} {imp:>14.6f}")
    L.append("")
    L.append("Top 15 features by mean(|SHAP|) on test set")
    L.append("-" * 96)
    L.append(f"  {'rank':<4} {'feature':<32} {'mean|SHAP|':>14}")
    for i, (n, imp) in enumerate(shap_top, 1):
        L.append(f"  {i:<4} {n:<32} {imp:>14.6f}")
    L.append("")
    L.append("Outputs")
    L.append("-" * 96)
    L.append(f"  model:        {model_path}")
    L.append(f"  columns:      {columns_path}")
    L.append(f"  predictions:  {pred_path}")
    L.append(f"  shap plot:    {shap_html}")
    L.append("=" * 96)
    return "\n".join(L) + "\n"


def _train_one(name, prefix, model_obj, params, importance_label, split):
    print("\n" + "#" * 78)
    print(f"# {name} V5c")
    print("#" * 78)
    t0 = time.perf_counter()
    model_obj.fit(split["X_train"], split["y_train_log"])
    elapsed = time.perf_counter() - t0
    print(f"  fit elapsed: {elapsed:.1f} s")

    metrics = _evaluate(model_obj, split["X_test"], split["y_test_log"], split["y_test_orig"])
    print(f"  R²(log)={metrics['r2_log']:+.4f}  ρ={metrics['spearman_rho']:+.4f}  "
          f"RMSE(log)={metrics['rmse_log']:.4f}")
    feature_names = list(split["X_train"].columns)
    builtin = _builtin_top(model_obj, feature_names)

    model_path   = MODELS / f"{prefix}.pkl"
    columns_path = MODELS / f"{prefix}_feature_columns.json"
    pred_path    = DATA / f"{prefix}_predictions.parquet"
    shap_html    = VIZ / f"{prefix}_shap.html"
    results_path = DATA / f"{prefix}_results.txt"

    joblib.dump(model_obj, model_path)
    columns_path.write_text(json.dumps(feature_names, indent=2), encoding="utf-8")
    _save_predictions(
        split["post_id_test"], split["y_test_log"], split["y_test_orig"],
        metrics["_y_pred_log"], metrics["_y_pred_orig"], pred_path,
    )

    try:
        shap_top, shap_vals, X_sub = _shap_top(model_obj, split["X_test"])
        _save_shap_html(shap_top, shap_html, name)
        np.savez(
            DATA / f"_shap_values_cached_{prefix.split('_')[0]}_v5c.npz",
            seed=np.int32(SEED), n_sample=np.int32(200),
            columns=np.array(feature_names),
            X_sub=X_sub.values, shap_values=shap_vals,
        )
    except Exception as e:  # noqa: BLE001
        print(f"  SHAP step FAILED: {type(e).__name__}: {e}")
        shap_top = [("(SHAP unavailable - see log)", 0.0)]

    text = _format_results(
        name, params, metrics, builtin, shap_top,
        len(split["X_train"]), len(split["X_test"]), elapsed,
        model_path, columns_path, pred_path, shap_html, importance_label,
    )
    results_path.write_text(text, encoding="utf-8")
    print(f"  saved: {model_path.name}, {pred_path.name}, {results_path.name}")
    return metrics


def train_lgb_with_earlystop(split):
    print("\n" + "#" * 78)
    print("# LightGBM V5c")
    print("#" * 78)
    X_tr, X_va, y_tr, y_va = train_test_split(
        split["X_train"], split["y_train_log"],
        test_size=0.10, random_state=SEED,
    )
    early_model = lgb.LGBMRegressor(**LGB_PARAMS)
    early_model.fit(
        X_tr, y_tr, eval_set=[(X_va, y_va)],
        callbacks=[lgb.early_stopping(stopping_rounds=50, verbose=False)],
    )
    best_iter = int(early_model.best_iteration_ or LGB_PARAMS["n_estimators"])
    print(f"  early-stop best_iteration_: {best_iter}")
    final_params = {**LGB_PARAMS, "n_estimators": best_iter}
    return _train_one("LightGBM", "lgb_v5c",
                      lgb.LGBMRegressor(**final_params), final_params,
                      "gain-based", split)


def main() -> int:
    print("=" * 78)
    print("Step 4j — Train RF / XGB / LGB V5c (V4 hyperparameters reused)")
    print("=" * 78)
    split = _load_and_prepare()

    rf_metrics  = _train_one("Random Forest", "rf_v5c",
                             RandomForestRegressor(**RF_PARAMS), RF_PARAMS,
                             "Gini-style", split)
    xgb_metrics = _train_one("XGBoost", "xgb_v5c",
                             XGBRegressor(**XGB_PARAMS), XGB_PARAMS,
                             "gain-based", split)
    lgb_metrics = train_lgb_with_earlystop(split)

    print("\n" + "=" * 78)
    print("V5c final test-set summary")
    print("=" * 78)
    print(f"  RF  V5c: R²(log)={rf_metrics['r2_log']:+.4f}  "
          f"ρ={rf_metrics['spearman_rho']:+.4f}  RMSE(log)={rf_metrics['rmse_log']:.4f}")
    print(f"  XGB V5c: R²(log)={xgb_metrics['r2_log']:+.4f}  "
          f"ρ={xgb_metrics['spearman_rho']:+.4f}  RMSE(log)={xgb_metrics['rmse_log']:.4f}")
    print(f"  LGB V5c: R²(log)={lgb_metrics['r2_log']:+.4f}  "
          f"ρ={lgb_metrics['spearman_rho']:+.4f}  RMSE(log)={lgb_metrics['rmse_log']:.4f}")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
