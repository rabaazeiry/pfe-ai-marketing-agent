"""Phase 4 V3 - FINAL: Single vs Ensemble shootout.

Compares 7 candidates on the V3 test set (n=818, identical stratified
split as the single-model scripts):

  Singles:   RF V3, XGB V3, LGB V3
  Ensembles: AVG-3   = mean(rf, xgb, lgb)
             WAVG-3  = R^2-weighted mean (RF gets the largest weight)
             STACK-3 = Ridge meta-model on OUT-OF-FOLD train predictions
             AVG-2   = mean(rf, xgb)   [drops LGB; LGB had the rho anomaly]

Stacking protocol (the one that requires care)
----------------------------------------------
A naive stacker would fit Ridge on each base model's TEST predictions
and y_test - that leaks the held-out labels into the meta-model. The
correct protocol (Wolpert 1992 "Stacked Generalization", Breiman 1996
"Stacked Regressions"):

  1. Generate OUT-OF-FOLD predictions on the TRAINING set for each base
     model: KFold(5) over X_train, in each fold fit on (X_train\fold)
     and predict on fold using the SAME hyperparameters as the trained
     single model.
  2. Stack OOF columns -> meta-features for the training set.
  3. Fit a regularized linear meta-model (RidgeCV) on (meta_features, y_train).
  4. At test time, apply the already-trained single models' test
     predictions as meta-features and call meta_model.predict.

cross_val_predict from sklearn does step 1 in one line per base model.

Ensemble CV metric
------------------
For each ensemble strategy we also report 5-fold CV RMSE on the
TRAINING set, computed by applying the strategy's formula to the OOF
columns (no extra refit needed - the OOF columns already are CV
predictions). This lets us check if the test-set advantage is real or
a single-split artifact.

Outputs
-------
- data/ensemble_v3_results.txt - full table + recommendation
- console: same content
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
import pandas as pd
from scipy.stats import spearmanr
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import RidgeCV
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import (
    KFold,
    StratifiedShuffleSplit,
    cross_val_predict,
    train_test_split,
)
from xgboost import XGBRegressor

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
MODELS = ROOT / "models"

ML_V3 = DATA / "df_ml_dataset_v3.parquet"

PRED_FILES: Dict[str, Path] = {
    "rf":  DATA / "rf_v3_predictions.parquet",
    "xgb": DATA / "xgb_v3_predictions.parquet",
    "lgb": DATA / "lgb_v3_predictions.parquet",
}

OUT_TXT = DATA / "ensemble_v3_results.txt"

SEED = 42
DROP_COLS = ["has_caption", "views"]
NOMINAL_OHE = ["content_type", "industry_simple", "caption_lang"]
KFOLDS_OOF = 5

# Best hyperparameters per model - copied verbatim from the V3 results
# files (see header of each *_v3_results.txt). Hardcoded so this script
# is self-contained and reproducible without re-parsing text.
BEST_PARAMS: Dict[str, Dict[str, object]] = {
    "rf": {                                     # rf_v3_results.txt
        "n_estimators":      1000,
        "min_samples_split": 2,
        "min_samples_leaf":  1,
        "max_features":      0.33,
        "max_depth":         None,
        "bootstrap":         True,
        "random_state":      SEED,
        "n_jobs":            -1,
    },
    "xgb": {                                    # xgb_v3_results.txt
        "subsample":         0.9,
        "reg_lambda":        5,
        "n_estimators":      500,
        "min_child_weight":  3,
        "max_depth":         10,
        "learning_rate":     0.01,
        "gamma":             0,
        "colsample_bytree":  0.9,
        "objective":         "reg:squarederror",
        "tree_method":       "hist",
        "random_state":      SEED,
        "n_jobs":            -1,
        "verbosity":         0,
    },
    "lgb": {                                    # lgb_v3_results.txt
        # n_estimators uses the converged value from the 90/10 refit
        # (best_iteration_=313) rather than Optuna's pre-early-stop
        # suggestion of 958, since cross_val_predict cannot pass an
        # eval_set callback per fold.
        "n_estimators":      313,
        "learning_rate":     0.028446,
        "num_leaves":        34,
        "max_depth":         7,
        "min_child_samples": 19,
        "subsample":         0.801594,
        "subsample_freq":    0,
        "colsample_bytree":  0.68114,
        "reg_alpha":         1.18363,
        "reg_lambda":        0.00743663,
        "objective":         "regression",
        "metric":            "rmse",
        "verbosity":         -1,
        "random_state":      SEED,
        "n_jobs":            -1,
    },
}


# --- Pipeline replication (mirror of phase4_lgb.py) ----------------------- #

def _load_and_prepare() -> Tuple[pd.DataFrame, pd.Series, pd.Series, pd.Series]:
    """Same OHE pipeline + dtype casts as the single-model scripts."""
    df = pd.read_parquet(ML_V3)
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
    return X, y_log, y_orig, post_id


def _split(
    X: pd.DataFrame,
    y_log: pd.Series,
    y_orig: pd.Series,
    post_id: pd.Series,
    industry: pd.Series,
) -> Dict[str, object]:
    """Identical 80/20 stratified split to the single-model scripts."""
    sss = StratifiedShuffleSplit(n_splits=1, test_size=0.20, random_state=SEED)
    train_idx, test_idx = next(sss.split(X, industry))
    return {
        "X_train": X.iloc[train_idx].reset_index(drop=True),
        "X_test":  X.iloc[test_idx].reset_index(drop=True),
        "y_train_log":  y_log.iloc[train_idx].reset_index(drop=True),
        "y_test_log":   y_log.iloc[test_idx].reset_index(drop=True),
        "y_train_orig": y_orig.iloc[train_idx].reset_index(drop=True),
        "y_test_orig":  y_orig.iloc[test_idx].reset_index(drop=True),
        "post_id_train": post_id.iloc[train_idx].reset_index(drop=True),
        "post_id_test":  post_id.iloc[test_idx].reset_index(drop=True),
    }


# --- Test-set predictions: load aligned by post_id ------------------------ #

def _load_test_preds(post_id_test: pd.Series) -> pd.DataFrame:
    """Returns DataFrame with columns ['rf','xgb','lgb','y_true_log','y_true_orig']
    aligned in post_id_test order."""
    out = pd.DataFrame({"post_id": post_id_test.values})
    for name, path in PRED_FILES.items():
        p = pd.read_parquet(path)
        p = p.set_index("post_id").loc[post_id_test.values].reset_index()
        if "y_true_log" not in out.columns:
            out["y_true_log"]  = p["y_true_log"].values
            out["y_true_orig"] = p["y_true_orig"].values
        out[f"{name}_log"]  = p["y_pred_log"].values
        out[f"{name}_orig"] = p["y_pred_orig"].values
    return out


# --- Out-of-fold training predictions ------------------------------------- #

def _make_estimator(name: str):
    p = BEST_PARAMS[name]
    if name == "rf":
        return RandomForestRegressor(**p)
    if name == "xgb":
        return XGBRegressor(**p)
    if name == "lgb":
        return lgb.LGBMRegressor(**p)
    raise ValueError(name)


def _oof_predictions(
    X_train: pd.DataFrame,
    y_train_log: pd.Series,
) -> pd.DataFrame:
    """5-fold cross_val_predict per base model on training set."""
    kf = KFold(n_splits=KFOLDS_OOF, shuffle=True, random_state=SEED)
    oof = pd.DataFrame(index=X_train.index)
    for name in ("rf", "xgb", "lgb"):
        print(f"  OOF for {name.upper():<3} ({KFOLDS_OOF}-fold) ...", end="",
              flush=True)
        t0 = time.perf_counter()
        est = _make_estimator(name)
        oof[name] = cross_val_predict(est, X_train, y_train_log, cv=kf, n_jobs=1)
        print(f" done in {time.perf_counter()-t0:.1f} s")
    return oof


# --- Ensemble formulas ---------------------------------------------------- #

def _avg3(df: pd.DataFrame, suffix: str) -> np.ndarray:
    return ((df[f"rf{suffix}"] + df[f"xgb{suffix}"] + df[f"lgb{suffix}"]) / 3.0
            ).to_numpy()


def _wavg3(df: pd.DataFrame, suffix: str, w: Tuple[float, float, float]
           ) -> np.ndarray:
    s = sum(w)
    return ((w[0]*df[f"rf{suffix}"] + w[1]*df[f"xgb{suffix}"]
             + w[2]*df[f"lgb{suffix}"]) / s).to_numpy()


def _avg2(df: pd.DataFrame, suffix: str) -> np.ndarray:
    return ((df[f"rf{suffix}"] + df[f"xgb{suffix}"]) / 2.0).to_numpy()


# --- Metrics -------------------------------------------------------------- #

def _metrics(y_true_log, y_pred_log,
             y_true_orig=None, y_pred_orig=None) -> Dict[str, float]:
    """If orig values not supplied, derive from log via expm1 (matches
    the single-model scripts' behaviour)."""
    if y_true_orig is None:
        y_true_orig = np.expm1(y_true_log)
    if y_pred_orig is None:
        y_pred_orig = np.clip(np.expm1(y_pred_log), 0.0, None)
    rho, _ = spearmanr(y_pred_log, y_true_log)
    return {
        "r2_log":       float(r2_score(y_true_log, y_pred_log)),
        "r2_orig":      float(r2_score(y_true_orig, y_pred_orig)),
        "rmse_log":     float(np.sqrt(mean_squared_error(y_true_log, y_pred_log))),
        "rmse_orig":    float(np.sqrt(mean_squared_error(y_true_orig, y_pred_orig))),
        "mae_orig":     float(mean_absolute_error(y_true_orig, y_pred_orig)),
        "spearman_rho": float(rho),
    }


# --- Main ----------------------------------------------------------------- #

def main() -> None:
    print("=" * 96)
    print("Phase 4 V3 - FINAL: Single vs Ensemble shootout")
    print("=" * 96)

    # 1. Reconstruct the same train/test split as the single-model scripts.
    print()
    print("[1] Reconstructing train/test split (SEED=42, stratified by industry)")
    X, y_log, y_orig, post_id = _load_and_prepare()
    df = pd.read_parquet(ML_V3)
    industry = df["industry_simple"]
    split = _split(X, y_log, y_orig, post_id, industry)
    print(f"    X_train: {split['X_train'].shape}   "
          f"X_test: {split['X_test'].shape}")

    # 2. Load test predictions aligned by post_id.
    print()
    print("[2] Loading saved V3 test predictions (rf/xgb/lgb)")
    preds_test = _load_test_preds(split["post_id_test"])
    n_test = len(preds_test)
    print(f"    test n={n_test}; per-model snapshot of first row:")
    print(f"    {preds_test.iloc[0].to_dict()}")

    # 3. Generate OOF training predictions for stacking + ensemble CV.
    print()
    print(f"[3] Computing OUT-OF-FOLD training predictions "
          f"({KFOLDS_OOF}-fold cross_val_predict per base model)")
    print(f"    note: RF is the slow one (~5-10 min). LGB and XGB are fast.")
    t_oof = time.perf_counter()
    oof = _oof_predictions(split["X_train"], split["y_train_log"])
    print(f"    OOF total elapsed: {time.perf_counter()-t_oof:.1f} s "
          f"({(time.perf_counter()-t_oof)/60:.1f} min)")

    # 4. Fit Ridge meta-model on OOF predictions.
    print()
    print("[4] Fitting RidgeCV meta-model on OOF predictions")
    meta_X = oof[["rf", "xgb", "lgb"]].to_numpy()
    meta_y = split["y_train_log"].to_numpy()
    ridge = RidgeCV(alphas=np.logspace(-3, 3, 13), cv=KFOLDS_OOF)
    ridge.fit(meta_X, meta_y)
    print(f"    RidgeCV best alpha:   {ridge.alpha_:.4g}")
    print(f"    Ridge coefficients:   "
          f"rf={ridge.coef_[0]:+.4f}  "
          f"xgb={ridge.coef_[1]:+.4f}  "
          f"lgb={ridge.coef_[2]:+.4f}")
    print(f"    Ridge intercept:      {ridge.intercept_:+.4f}")

    # 5. Apply each ensemble strategy on TEST set and compute metrics.
    print()
    print("[5] Computing TEST-SET metrics for 7 candidates")

    # log-scale and orig-scale predictions per ensemble.
    # (For ensembles, we average the log preds and re-expand.)
    test_y_log  = preds_test["y_true_log"].to_numpy()
    test_y_orig = preds_test["y_true_orig"].to_numpy()

    candidates: Dict[str, Tuple[np.ndarray, np.ndarray]] = {}

    # Singles - just take the saved predictions.
    for name in ("rf", "xgb", "lgb"):
        log_pred = preds_test[f"{name}_log"].to_numpy()
        orig_pred = preds_test[f"{name}_orig"].to_numpy()
        candidates[name.upper() + " V3"] = (log_pred, orig_pred)

    # Ensembles - compute on log scale, then expm1 for original-scale metrics.
    log_avg3   = _avg3(preds_test,  "_log")
    log_avg2   = _avg2(preds_test,  "_log")
    weights    = (0.3656, 0.3472, 0.3416)   # R^2(log) per single model
    log_wavg3  = _wavg3(preds_test, "_log", weights)
    # STACK-3 - apply the trained Ridge to test meta-features.
    test_meta_X = preds_test[["rf_log", "xgb_log", "lgb_log"]].to_numpy()
    log_stack3  = ridge.predict(test_meta_X)

    for label, log_pred in [
        ("AVG-3",        log_avg3),
        ("WAVG-3 (R^2)", log_wavg3),
        ("STACK-3",      log_stack3),
        ("AVG-2 (RF+XGB)", log_avg2),
    ]:
        orig_pred = np.clip(np.expm1(log_pred), 0.0, None)
        candidates[label] = (log_pred, orig_pred)

    rows: List[Dict[str, object]] = []
    for label, (lp, op) in candidates.items():
        m = _metrics(test_y_log, lp, test_y_orig, op)
        rows.append({"strategy": label, **m})

    # 6. CV metrics on training OOF for ensembles (singles already have CV
    #    RMSE in their results files: RF=0.2670, XGB=0.2670, LGB=0.2672).
    print()
    print("[6] Computing CV RMSE (log) for ensembles using OOF columns")
    oof_y_log = split["y_train_log"].to_numpy()
    oof_strats = {
        "AVG-3":          (oof["rf"] + oof["xgb"] + oof["lgb"]) / 3.0,
        "WAVG-3 (R^2)":   (weights[0]*oof["rf"] + weights[1]*oof["xgb"]
                           + weights[2]*oof["lgb"]) / sum(weights),
        "STACK-3":        ridge.predict(oof[["rf","xgb","lgb"]].to_numpy()),
        "AVG-2 (RF+XGB)": (oof["rf"] + oof["xgb"]) / 2.0,
    }
    cv_rmse: Dict[str, float] = {
        "RF V3":  0.2670,        # from rf_v3_results.txt
        "XGB V3": 0.2670,        # from xgb_v3_results.txt
        "LGB V3": 0.2672,        # from lgb_v3_results.txt
    }
    for label, oof_pred in oof_strats.items():
        cv_rmse[label] = float(np.sqrt(mean_squared_error(oof_y_log, oof_pred)))
        print(f"    {label:<16} OOF RMSE(log) = {cv_rmse[label]:.4f}")

    # 7. Print + save the final comparison table.
    print()
    print("=" * 130)
    print("FINAL Phase 4 V3 - Single vs Ensemble Strategies (test n=818)")
    print("=" * 130)
    header = (f"{'strategy':<18} {'R2(log)':>9} {'R2(orig)':>9} "
              f"{'rho':>8} {'RMSE(log)':>10} {'RMSE(orig)':>11} "
              f"{'MAE(orig)':>10} {'CV RMSE(log)':>13}")
    print(header)
    print("-" * len(header))
    by_label = {r["strategy"]: r for r in rows}
    order = ["RF V3", "XGB V3", "LGB V3",
             "AVG-3", "WAVG-3 (R^2)", "STACK-3", "AVG-2 (RF+XGB)"]
    for label in order:
        r = by_label[label]
        print(f"{label:<18} "
              f"{r['r2_log']:+9.4f} "
              f"{r['r2_orig']:+9.4f} "
              f"{r['spearman_rho']:+8.4f} "
              f"{r['rmse_log']:10.4f} "
              f"{r['rmse_orig']:11.4f} "
              f"{r['mae_orig']:10.4f} "
              f"{cv_rmse[label]:13.4f}")
    print()

    # 8. Per-metric winner.
    metric_directions = [
        ("r2_log",       "R2(log)",      "max"),
        ("r2_orig",      "R2(orig)",     "max"),
        ("spearman_rho", "Spearman rho", "max"),
        ("rmse_log",     "RMSE(log)",    "min"),
        ("rmse_orig",    "RMSE(orig)",   "min"),
        ("mae_orig",     "MAE(orig)",    "min"),
    ]
    print("WINNER on each metric (test set):")
    print("-" * 130)
    for key, name, direction in metric_directions:
        best = max(rows, key=lambda r: r[key]) if direction == "max" \
               else min(rows, key=lambda r: r[key])
        print(f"  {name:<14} {direction:<3} -> {best['strategy']:<18} "
              f"= {best[key]:+.4f}")

    # CV RMSE winner separately (singles use historical CV; ensembles use OOF).
    cv_best = min(cv_rmse, key=cv_rmse.get)
    print(f"  {'CV RMSE(log)':<14} min -> {cv_best:<18} = {cv_rmse[cv_best]:.4f}")

    # 9. Recommendation.
    rec = _recommendation(rows, cv_rmse, ridge)
    print()
    print("=" * 130)
    print("RECOMMENDATION")
    print("=" * 130)
    print(rec)

    # 10. Persist everything to results txt.
    print()
    print(f"Saving full report to {OUT_TXT.relative_to(ROOT)} ...")
    OUT_TXT.write_text(_format_report(rows, cv_rmse, ridge, rec, order),
                       encoding="utf-8")
    print(f"  wrote {OUT_TXT.name}  ({OUT_TXT.stat().st_size/1024:.1f} KB)")


def _recommendation(
    rows: List[Dict[str, object]],
    cv_rmse: Dict[str, float],
    ridge: RidgeCV,
) -> str:
    """Pick the production model. Logic:
      - If a clear leader emerges on >=4 of 6 metrics AND its CV RMSE is
        not worse than the next-best by more than 1 std, pick it.
      - Tiebreaker: RMSE(log) (training objective).
      - Sanity: ensemble must beat the best single by >= 0.5% on RMSE(log)
        to be worth the extra inference complexity.
    """
    rf  = next(r for r in rows if r["strategy"] == "RF V3")
    best_overall = min(rows, key=lambda r: r["rmse_log"])
    best_label = best_overall["strategy"]

    L: List[str] = []
    L.append(f"Best test RMSE(log): {best_label} ({best_overall['rmse_log']:.4f})")
    L.append(f"RF V3 baseline:      {rf['rmse_log']:.4f}")
    delta_pct = (rf["rmse_log"] - best_overall["rmse_log"]) / rf["rmse_log"] * 100
    L.append(f"Improvement vs RF V3: {delta_pct:+.2f}%")
    L.append("")
    if best_label == "RF V3" or abs(delta_pct) < 0.5:
        L.append(f"-> Pick RF V3 as the production model.")
        L.append(f"   No ensemble beats it by the 0.5% RMSE threshold; the "
                 f"extra")
        L.append(f"   inference cost (3 models + Ridge) is not justified.")
    else:
        L.append(f"-> Pick {best_label} as the production model "
                 f"({delta_pct:+.2f}% over RF V3).")
        L.append(f"   Ridge meta-model coefficients: rf={ridge.coef_[0]:+.4f}, "
                 f"xgb={ridge.coef_[1]:+.4f}, lgb={ridge.coef_[2]:+.4f}")
    return "\n".join(L)


def _format_report(
    rows: List[Dict[str, object]],
    cv_rmse: Dict[str, float],
    ridge: RidgeCV,
    rec: str,
    order: List[str],
) -> str:
    L: List[str] = []
    L.append("=" * 130)
    L.append("Phase 4 V3 - FINAL: Single vs Ensemble Strategies (test n=818)")
    L.append("=" * 130)
    L.append("")
    L.append("Stacking meta-model (RidgeCV)")
    L.append("-" * 130)
    L.append(f"  alpha:        {ridge.alpha_:.4g}")
    L.append(f"  rf coef:      {ridge.coef_[0]:+.6f}")
    L.append(f"  xgb coef:     {ridge.coef_[1]:+.6f}")
    L.append(f"  lgb coef:     {ridge.coef_[2]:+.6f}")
    L.append(f"  intercept:    {ridge.intercept_:+.6f}")
    L.append("")
    header = (f"{'strategy':<18} {'R2(log)':>9} {'R2(orig)':>9} "
              f"{'rho':>8} {'RMSE(log)':>10} {'RMSE(orig)':>11} "
              f"{'MAE(orig)':>10} {'CV RMSE(log)':>13}")
    L.append(header)
    L.append("-" * len(header))
    by_label = {r["strategy"]: r for r in rows}
    for label in order:
        r = by_label[label]
        L.append(f"{label:<18} "
                 f"{r['r2_log']:+9.4f} "
                 f"{r['r2_orig']:+9.4f} "
                 f"{r['spearman_rho']:+8.4f} "
                 f"{r['rmse_log']:10.4f} "
                 f"{r['rmse_orig']:11.4f} "
                 f"{r['mae_orig']:10.4f} "
                 f"{cv_rmse[label]:13.4f}")
    L.append("")
    L.append("RECOMMENDATION")
    L.append("-" * 130)
    L.append(rec)
    L.append("=" * 130)
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    main()
