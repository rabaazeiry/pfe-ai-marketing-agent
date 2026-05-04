"""V1 (28-col) vs V2 (32-col) Random Forest comparison.

Reads:
  - data/rf_results.txt.bak_v1    (V1 RF report, 28-col features)
  - data/rf_results.txt           (V2 RF report, 32-col features)
  - data/rf_predictions.parquet.bak_v1
  - data/rf_predictions.parquet
Writes:
  - data/feature_engineering_v2_rf_impact.txt

The comparison is apples-to-apples because:
  - same SEED=42, same stratified 80/20 split, same n=826 test rows.
  - same RandomizedSearchCV protocol (50 iter x 10-fold).
  - same SHAP setup (TreeExplainer on shap.sample(X_test, 200, random_state=42)).
  - only the feature matrix differs (28 -> 32 cols, +4 V2 features).

Reusable for future feature-engineering versions: change V1_* / V2_* paths.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from compare_regressors import _parse_results, _read_text  # noqa: E402

V1_RESULTS = ROOT / "data" / "rf_results.txt.bak_v1"
V2_RESULTS = ROOT / "data" / "rf_results.txt"
V1_PREDS   = ROOT / "data" / "rf_predictions.parquet.bak_v1"
V2_PREDS   = ROOT / "data" / "rf_predictions.parquet"
OUT_PATH   = ROOT / "data" / "feature_engineering_v2_rf_impact.txt"

V2_NEW_FEATURES = ["caption_sentiment", "is_ramadan", "has_emoji", "has_cta"]


def _metrics_from_preds(p: Path) -> Dict[str, float]:
    df = pd.read_parquet(p)
    yt_log = df["y_true_log"].to_numpy()
    yp_log = df["y_pred_log"].to_numpy()
    yt_orig = df["y_true_orig"].to_numpy()
    yp_orig = df["y_pred_orig"].to_numpy()
    rho, _ = spearmanr(yp_log, yt_log)
    return {
        "n_test":   int(len(df)),
        "r2_log":   float(r2_score(yt_log, yp_log)),
        "r2_orig":  float(r2_score(yt_orig, yp_orig)),
        "rmse_log": float(np.sqrt(mean_squared_error(yt_log, yp_log))),
        "rmse_orig":float(np.sqrt(mean_squared_error(yt_orig, yp_orig))),
        "mae_log":  float(mean_absolute_error(yt_log, yp_log)),
        "mae_orig": float(mean_absolute_error(yt_orig, yp_orig)),
        "rho":      float(rho),
    }


def _delta_pct(new: float, old: float) -> str:
    if old == 0:
        return "n/a"
    return f"{(new - old) / abs(old) * 100:+.1f}%"


def _shap_rank_lookup(top15: List[Tuple[int, str, float]]) -> Dict[str, Tuple[int, float]]:
    return {name: (rank, val) for rank, name, val in top15}


def _format_report(
    m1: Dict[str, float], m2: Dict[str, float],
    p1: Dict, p2: Dict,
) -> str:
    L: List[str] = []
    L.append("=" * 72)
    L.append("Random Forest -- Feature Engineering V2 Impact")
    L.append("=" * 72)
    L.append("")
    L.append("  V1: 28 features (post data-leakage fix, pre-V2 enrichment)")
    L.append("  V2: 32 features  (V1 + caption_sentiment, is_ramadan,")
    L.append("                    has_emoji, has_cta; emoji_count overwritten)")
    L.append("  same SEED=42, same 80/20 stratified split, same n=826 test")
    L.append("")

    # --- Metrics table --------------------------------------------------
    L.append("Test-set metrics  (recomputed fresh from rf_predictions.parquet)")
    L.append("-" * 72)
    L.append(f"  {'metric':<14} {'BEFORE V2':>12}   {'AFTER V2':>12}   "
             f"{'delta':>10}   {'% change':>10}")
    rows = [
        ("R2 (log)",     "r2_log",    True),
        ("R2 (orig)",    "r2_orig",   True),
        ("Spearman rho", "rho",       True),
        ("RMSE (log)",   "rmse_log",  False),
        ("RMSE (orig)",  "rmse_orig", False),
        ("MAE (log)",    "mae_log",   False),
        ("MAE (orig)",   "mae_orig",  False),
    ]
    for label, key, _ in rows:
        v1, v2 = m1[key], m2[key]
        L.append(f"  {label:<14} {v1:>12.4f}   {v2:>12.4f}   "
                 f"{(v2-v1):>+10.4f}   {_delta_pct(v2, v1):>10}")

    cv1 = p1.get("cv_mean_rmse"); cv2 = p2.get("cv_mean_rmse")
    if cv1 is not None and cv2 is not None:
        L.append("")
        L.append("CV mean RMSE (log scale, 10-fold)")
        L.append("-" * 72)
        L.append(f"  {'mean':<14} {cv1:>12.4f}   {cv2:>12.4f}   "
                 f"{(cv2-cv1):>+10.4f}   {_delta_pct(cv2, cv1):>10}")
        sd1 = p1.get("cv_std_rmse", float("nan"))
        sd2 = p2.get("cv_std_rmse", float("nan"))
        L.append(f"  {'std':<14} {sd1:>12.4f}   {sd2:>12.4f}")

    # --- Best hyperparameters delta ------------------------------------
    L.append("")
    L.append("Best hyperparameters")
    L.append("-" * 72)
    bp1 = p1.get("best_params", {})
    bp2 = p2.get("best_params", {})
    keys = sorted(set(bp1) | set(bp2))
    L.append(f"  {'param':<22} {'V1':<12} {'V2':<12} {'changed':<10}")
    for k in keys:
        v1, v2 = bp1.get(k, "?"), bp2.get(k, "?")
        ch = "yes" if v1 != v2 else ""
        L.append(f"  {k:<22} {v1:<12} {v2:<12} {ch:<10}")

    # --- TOP 5 SHAP in V2 + their old rank ------------------------------
    L.append("")
    L.append("TOP 5 features by SHAP importance (V2 model)")
    L.append("-" * 72)
    shap_v1_lookup = _shap_rank_lookup(p1.get("shap_top15", []))
    shap_v2_lookup = _shap_rank_lookup(p2.get("shap_top15", []))
    top5_v2 = sorted(shap_v2_lookup.items(), key=lambda kv: kv[1][0])[:5]
    L.append(f"  {'rank':<5} {'feature':<28} {'SHAP':>10}   {'V1 rank':>10}   {'shift':>8}")
    for name, (rank2, sval2) in top5_v2:
        v1_info = shap_v1_lookup.get(name)
        if v1_info is None:
            v1_rank_str = "N/A (new)"
            shift_str = "+inf"
        else:
            v1_rank_str = str(v1_info[0])
            shift_str = f"{v1_info[0] - rank2:+d}"
        L.append(f"  {rank2:<5} {name:<28} {sval2:>10.6f}   {v1_rank_str:>10}   {shift_str:>8}")

    # --- V2 NEW FEATURES diagnostic -------------------------------------
    L.append("")
    L.append("NEW V2 features in V2 SHAP ranking")
    L.append("-" * 72)
    L.append(f"  {'feature':<22} {'V2 rank':>10} {'SHAP':>10}   note")
    for f in V2_NEW_FEATURES:
        info = shap_v2_lookup.get(f)
        if info is None:
            L.append(f"  {f:<22} {'>15':>10} {'-':>10}   not in top-15")
        else:
            rank, val = info
            L.append(f"  {f:<22} {rank:>10} {val:>10.6f}   in top-15")

    # --- Top-15 rank-shift table ---------------------------------------
    L.append("")
    L.append("Top-15 SHAP rank shift  (V1 -> V2)")
    L.append("-" * 72)
    union = sorted(set(shap_v1_lookup) | set(shap_v2_lookup))
    rows_rs: List[Tuple[str, str, str, str]] = []
    for name in union:
        v1 = shap_v1_lookup.get(name)
        v2 = shap_v2_lookup.get(name)
        r1 = str(v1[0]) if v1 else "-"
        r2 = str(v2[0]) if v2 else "-"
        if v1 and v2:
            sh = f"{v1[0]-v2[0]:+d}"
        elif v2 and not v1:
            sh = "NEW"
        elif v1 and not v2:
            sh = "OUT"
        else:
            sh = ""
        rows_rs.append((name, r1, r2, sh))
    rows_rs.sort(key=lambda r: int(r[2]) if r[2].isdigit() else 99)
    L.append(f"  {'feature':<32} {'V1':>4} {'V2':>4}  {'shift':>8}")
    for name, r1, r2, sh in rows_rs:
        L.append(f"  {name:<32} {r1:>4} {r2:>4}  {sh:>8}")

    # --- Interpretation -------------------------------------------------
    L.append("")
    L.append("Interpretation")
    L.append("-" * 72)
    delta_r2 = m2["r2_log"] - m1["r2_log"]
    delta_rho = m2["rho"]   - m1["rho"]
    delta_rmse = m2["rmse_log"] - m1["rmse_log"]
    n_v2_in_top15 = sum(1 for f in V2_NEW_FEATURES if f in shap_v2_lookup)

    if abs(delta_r2) < 0.005 and abs(delta_rho) < 0.005:
        verdict = "negligible -- V2 features did not change predictive power"
    elif delta_r2 > 0 and delta_rho > 0 and delta_rmse < 0:
        verdict = "POSITIVE -- V2 features improved all primary metrics"
    elif delta_r2 < 0 and delta_rho < 0:
        verdict = "NEGATIVE -- V2 features degraded predictive power"
    else:
        verdict = "MIXED -- some metrics up, some down (see deltas above)"

    L.append(f"  Verdict:                 {verdict}")
    L.append(f"  R2(log) delta:           {delta_r2:+.4f}  ({_delta_pct(m2['r2_log'], m1['r2_log'])})")
    L.append(f"  Spearman rho delta:      {delta_rho:+.4f}  ({_delta_pct(m2['rho'], m1['rho'])})")
    L.append(f"  RMSE(log) delta:         {delta_rmse:+.4f}  (lower=better; {_delta_pct(m2['rmse_log'], m1['rmse_log'])})")
    L.append(f"  V2 features in top-15:   {n_v2_in_top15} / 4")
    L.append("")
    L.append("  Read with the V2 feature Pearson correlations from")
    L.append("  data/features_v2.log:")
    L.append("    caption_sentiment  r=-0.10   <- strongest pre-publication signal")
    L.append("    has_cta            r=-0.04")
    L.append("    emoji_count (V2)   r=+0.04")
    L.append("    is_ramadan         r=+0.01   (after 2026 window patch)")
    L.append("    has_emoji          r=+0.00")
    L.append("")
    L.append("=" * 72)
    return "\n".join(L) + "\n"


def main() -> None:
    print(f"Reading V1: {V1_RESULTS.name} + {V1_PREDS.name}")
    print(f"Reading V2: {V2_RESULTS.name} + {V2_PREDS.name}")
    for p in (V1_RESULTS, V2_RESULTS, V1_PREDS, V2_PREDS):
        if not p.exists():
            raise FileNotFoundError(p)

    p1 = _parse_results(_read_text(V1_RESULTS))
    p2 = _parse_results(_read_text(V2_RESULTS))
    m1 = _metrics_from_preds(V1_PREDS)
    m2 = _metrics_from_preds(V2_PREDS)

    text = _format_report(m1, m2, p1, p2)
    OUT_PATH.write_text(text, encoding="utf-8")

    print()
    print(text, end="")
    print(f"\nWrote: {OUT_PATH}  ({OUT_PATH.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
