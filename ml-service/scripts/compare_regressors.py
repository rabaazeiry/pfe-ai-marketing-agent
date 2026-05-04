"""Phase 4 - side-by-side comparison of regression models on
engagement_rate. Currently parameterized for RF vs XGBoost; a third
entry can be added when LightGBM (Phase 4.3) lands.

Reads each model's:
  - predictions parquet (post_id, y_true_log, y_pred_log, y_true_orig,
    y_pred_orig) - used for fresh metric recomputation.
  - results.txt        - parsed for best hyperparameters, search elapsed,
    CV mean RMSE +/- std, top-15 SHAP / Gini features.

Writes:
  - data/rf_vs_xgb_comparison.txt     (when only RF + XGB are configured)
  - data/multi_model_comparison.txt   (when 3+ models are configured)
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class ModelEntry:
    label: str                       # short header label, e.g. "RF"
    long_name: str                   # for the title line
    predictions_parquet: Path
    results_txt: Path


# Edit this list when adding LightGBM (Phase 4.3) etc.
MODELS: List[ModelEntry] = [
    ModelEntry(
        label="RF",
        long_name="Random Forest (phase4_rf.py)",
        predictions_parquet=ROOT / "data" / "rf_predictions.parquet",
        results_txt=ROOT / "data" / "rf_results.txt",
    ),
    ModelEntry(
        label="XGB",
        long_name="XGBoost (phase4_xgb.py)",
        predictions_parquet=ROOT / "data" / "xgb_predictions.parquet",
        results_txt=ROOT / "data" / "xgb_results.txt",
    ),
]

OUT_PATH_DEFAULT = ROOT / "data" / "rf_vs_xgb_comparison.txt"
OUT_PATH_MULTI   = ROOT / "data" / "multi_model_comparison.txt"


# --- Parsing helpers ------------------------------------------------------- #

_NUM = r"([+-]?\d+(?:\.\d+)?)"

def _read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _grep_first(pattern: str, text: str, group: int = 1) -> Optional[str]:
    m = re.search(pattern, text)
    return m.group(group) if m else None


def _parse_results(text: str) -> Dict:
    """Pull the structured fields out of a phase4_*_results.txt file."""
    out: Dict = {}

    # Best hyperparameters block (between 'Best hyperparameters' and blank line).
    hp_block = re.search(
        r"Best hyperparameters\s*\n-+\n(.*?)\n\n",
        text, re.DOTALL,
    )
    out["best_params"] = {}
    if hp_block:
        for line in hp_block.group(1).splitlines():
            m = re.match(r"\s*(\S+)\s*=\s*(.+)$", line)
            if m:
                out["best_params"][m.group(1)] = m.group(2).strip()

    # CV mean RMSE +/- std (handle both U+00B1 and ASCII +/-).
    cv = re.search(
        r"CV mean RMSE \(log scale\):\s*" + _NUM + r"\s*(?:±|\+/-)\s*" + _NUM,
        text,
    )
    if cv:
        out["cv_mean_rmse"] = float(cv.group(1))
        out["cv_std_rmse"] = float(cv.group(2))

    # Search elapsed seconds (... fits (NNN.N s)).
    se = re.search(r"=\s*500 fits\s*\(" + _NUM + r"\s*s\)", text)
    if se:
        out["search_elapsed_s"] = float(se.group(1))

    # Top-15 SHAP block.
    shap_block = re.search(
        r"Top 15 features by mean\(\|SHAP\|\)[^\n]*\n-+\n[^\n]*\n((?:\s+\d+\s+\S.*\n)+)",
        text,
    )
    out["shap_top15"] = []
    if shap_block:
        for line in shap_block.group(1).splitlines():
            m = re.match(r"\s*(\d+)\s+(\S+)\s+([\d.]+)\s*$", line)
            if m:
                out["shap_top15"].append(
                    (int(m.group(1)), m.group(2), float(m.group(3)))
                )
    out["shap_top15"] = out["shap_top15"][:15]

    # Top-15 built-in importance (Gini for RF, gain for XGB).
    bi_block = re.search(
        r"Top 15 features by built-in[^\n]*\n-+\n.*?\n\n[^\n]*\n((?:\s+\d+\s+\S.*\n)+)",
        text, re.DOTALL,
    )
    out["builtin_top15"] = []
    if bi_block:
        for line in bi_block.group(1).splitlines():
            m = re.match(r"\s*(\d+)\s+(\S+)\s+([\d.]+)\s*$", line)
            if m:
                out["builtin_top15"].append(
                    (int(m.group(1)), m.group(2), float(m.group(3)))
                )
    # Defensive cap: regex may bleed into the SHAP block if the file
    # structure varies; we always want exactly the first 15 rows here.
    out["builtin_top15"] = out["builtin_top15"][:15]

    return out


# --- Metric recomputation from predictions parquet ------------------------- #

def _metrics_from_preds(p: Path) -> Dict[str, float]:
    df = pd.read_parquet(p)
    y_true_log = df["y_true_log"].to_numpy()
    y_pred_log = df["y_pred_log"].to_numpy()
    y_true_orig = df["y_true_orig"].to_numpy()
    y_pred_orig = df["y_pred_orig"].to_numpy()
    rho, _ = spearmanr(y_pred_log, y_true_log)
    return {
        "n_test":       int(len(df)),
        "r2_log":       float(r2_score(y_true_log, y_pred_log)),
        "r2_orig":      float(r2_score(y_true_orig, y_pred_orig)),
        "rmse_log":     float(np.sqrt(mean_squared_error(y_true_log, y_pred_log))),
        "rmse_orig":    float(np.sqrt(mean_squared_error(y_true_orig, y_pred_orig))),
        "mae_orig":     float(mean_absolute_error(y_true_orig, y_pred_orig)),
        "spearman_rho": float(rho),
    }


# --- SHAP overlap analysis ------------------------------------------------- #

def _shap_overlap(
    entries: List[Tuple[str, List[Tuple[int, str, float]]]],
) -> Dict:
    """For each pair of models, compute:
      - shared top-15 features (set intersection)
      - features unique to each (symmetric difference, split per-side)
      - Spearman correlation of ranks on the shared subset
    """
    out: Dict = {"per_model_top15": {}, "pairs": []}
    for label, top15 in entries:
        names = [n for _, n, _ in top15]
        out["per_model_top15"][label] = names

    for i in range(len(entries)):
        for j in range(i + 1, len(entries)):
            la, ta = entries[i]
            lb, tb = entries[j]
            sa = {n for _, n, _ in ta}
            sb = {n for _, n, _ in tb}
            shared = sorted(sa & sb)
            only_a = sorted(sa - sb)
            only_b = sorted(sb - sa)
            ra = {n: r for r, n, _ in ta}
            rb = {n: r for r, n, _ in tb}
            if shared:
                ranks_a = np.array([ra[n] for n in shared], dtype=float)
                ranks_b = np.array([rb[n] for n in shared], dtype=float)
                if len(shared) >= 3:
                    rho, p = spearmanr(ranks_a, ranks_b)
                else:
                    rho, p = float("nan"), float("nan")
            else:
                rho, p = float("nan"), float("nan")
            out["pairs"].append({
                "a": la, "b": lb,
                "shared": shared,
                "only_a": only_a,
                "only_b": only_b,
                "rank_spearman": float(rho),
                "rank_pvalue":   float(p),
            })
    return out


# --- Rendering ------------------------------------------------------------- #

def _render(
    entries: List[ModelEntry],
    metrics: Dict[str, Dict[str, float]],
    parsed: Dict[str, Dict],
    overlap: Dict,
) -> str:
    L: List[str] = []
    L.append("=" * 96)
    if len(entries) == 2:
        L.append(f"Phase 4 - Head-to-head: {entries[0].long_name}  vs  "
                 f"{entries[1].long_name}")
    else:
        L.append("Phase 4 - Multi-model comparison: " +
                 ", ".join(e.label for e in entries))
    L.append("=" * 96)
    L.append("  same dataset:    data/df_ml_dataset.parquet (4127 rows, "
             "POST data-leakage fix)")
    L.append("  same split:      stratified 80/20 on industry_simple, SEED=42")
    L.append("  same target:     log1p(engagement_rate)")
    L.append("  same protocol:   RandomizedSearchCV n_iter=50, KFold(10)")
    L.append("  same SHAP setup: TreeExplainer on shap.sample(X_test, 200, "
             "random_state=42)")
    L.append("")

    # --- Test-set metrics --------------------------------------------------
    L.append("Test-set metrics (n=826)")
    L.append("-" * 96)
    metric_names = [
        ("r2_log",       "R^2 (log1p)",        "{:+.4f}", True),
        ("r2_orig",      "R^2 (orig)",         "{:+.4f}", True),
        ("rmse_log",     "RMSE (log)",         "{:.4f}",  False),
        ("rmse_orig",    "RMSE (orig)",        "{:.4f}",  False),
        ("mae_orig",     "MAE  (orig)",        "{:.4f}",  False),
        ("spearman_rho", "Spearman rho",       "{:+.4f}", True),
    ]
    head = f"  {'metric':<14}"
    for e in entries:
        head += f"  {e.label:>14}"
    if len(entries) == 2:
        head += f"  {'delta':>10}   {'winner':>8}"
    L.append(head)
    L.append("  " + "-" * 94)
    for key, lbl, fmt, higher_better in metric_names:
        row = f"  {lbl:<14}"
        vals = [metrics[e.label][key] for e in entries]
        for v in vals:
            row += f"  {fmt.format(v):>14}"
        if len(entries) == 2:
            delta = vals[1] - vals[0]
            row += f"  {('{:+.4f}'.format(delta)):>10}"
            if higher_better:
                winner = entries[1].label if delta > 0 else entries[0].label if delta < 0 else "tie"
            else:
                winner = entries[0].label if delta > 0 else entries[1].label if delta < 0 else "tie"
            row += f"   {winner:>8}"
        L.append(row)

    L.append("")
    L.append("CV mean RMSE (log scale, 10-fold)")
    L.append("-" * 96)
    head = f"  {'':<14}"
    for e in entries:
        head += f"  {e.label:>14}"
    L.append(head)
    cv_row = f"  {'mean':<14}"
    sd_row = f"  {'std':<14}"
    for e in entries:
        p = parsed[e.label]
        cv_row += f"  {p.get('cv_mean_rmse', float('nan')):>14.4f}"
        sd_row += f"  {p.get('cv_std_rmse', float('nan')):>14.4f}"
    L.append(cv_row)
    L.append(sd_row)
    se_row = f"  {'search elapsed':<14}"
    for e in entries:
        p = parsed[e.label]
        se = p.get("search_elapsed_s", None)
        se_str = f"{se:.1f}s ({se/60:.1f}m)" if se is not None else "?"
        se_row += f"  {se_str:>14}"
    L.append(se_row)

    # --- Best hyperparameters per model -----------------------------------
    L.append("")
    L.append("Best hyperparameters")
    L.append("-" * 96)
    for e in entries:
        L.append(f"  {e.label}  ({e.long_name})")
        for k, v in parsed[e.label].get("best_params", {}).items():
            L.append(f"      {k:<22} = {v}")
        L.append("")

    # --- Top-15 SHAP side-by-side -----------------------------------------
    L.append("Top 15 features by mean(|SHAP|) - side-by-side")
    L.append("-" * 96)
    head = f"  {'rank':<4}"
    for e in entries:
        head += f"  {e.label + ' feature':<30} {e.label + ' SHAP':>12}"
    L.append(head)
    max_rows = max(len(parsed[e.label].get("shap_top15", [])) for e in entries)
    for i in range(max_rows):
        row = f"  {i+1:<4}"
        for e in entries:
            top = parsed[e.label].get("shap_top15", [])
            if i < len(top):
                _, n, v = top[i]
                row += f"  {n:<30} {v:>12.6f}"
            else:
                row += f"  {'':<30} {'':>12}"
        L.append(row)

    # --- Overlap analysis -------------------------------------------------
    L.append("")
    L.append("SHAP top-15 overlap analysis")
    L.append("-" * 96)
    for pair in overlap["pairs"]:
        a, b = pair["a"], pair["b"]
        shared = pair["shared"]
        only_a = pair["only_a"]
        only_b = pair["only_b"]
        L.append(f"  {a} vs {b}")
        L.append(f"    shared features in top-15:   {len(shared):>2} / 15  "
                 f"({len(shared)/15*100:.0f}%)")
        L.append(f"    only in {a:<3} top-15:           {only_a}")
        L.append(f"    only in {b:<3} top-15:           {only_b}")
        if not np.isnan(pair["rank_spearman"]):
            L.append(f"    rank Spearman (shared subset): rho={pair['rank_spearman']:+.4f}  "
                     f"p={pair['rank_pvalue']:.2e}  n={len(shared)}")
        else:
            L.append(f"    rank Spearman: undefined (n_shared < 3)")
        L.append("")

    # --- Verdict ----------------------------------------------------------
    if len(entries) == 2:
        L.append("Verdict")
        L.append("-" * 96)
        a, b = entries[0].label, entries[1].label
        wins_a = wins_b = ties = 0
        for key, _, _, higher_better in metric_names:
            va, vb = metrics[a][key], metrics[b][key]
            if va == vb:
                ties += 1
                continue
            if higher_better:
                if vb > va: wins_b += 1
                else:       wins_a += 1
            else:
                if vb < va: wins_b += 1
                else:       wins_a += 1
        if wins_a > wins_b:
            verdict = f"{a} wins ({wins_a}-{wins_b}-{ties})"
        elif wins_b > wins_a:
            verdict = f"{b} wins ({wins_b}-{wins_a}-{ties})"
        else:
            verdict = f"tie ({wins_a}-{wins_b}-{ties})"
        L.append(f"  {verdict}  on the 6 test-set metrics")
        L.append("")

    L.append("=" * 96)
    return "\n".join(L) + "\n"


# --- Main ------------------------------------------------------------------ #

def main() -> None:
    print(f"Comparing {len(MODELS)} model(s):")
    for e in MODELS:
        print(f"  - {e.label:<5} {e.long_name}")
        for p in (e.predictions_parquet, e.results_txt):
            if not p.exists():
                raise FileNotFoundError(f"missing: {p}")

    metrics: Dict[str, Dict[str, float]] = {}
    parsed: Dict[str, Dict] = {}
    for e in MODELS:
        metrics[e.label] = _metrics_from_preds(e.predictions_parquet)
        parsed[e.label] = _parse_results(_read_text(e.results_txt))

    overlap = _shap_overlap(
        [(e.label, parsed[e.label].get("shap_top15", [])) for e in MODELS]
    )

    text = _render(MODELS, metrics, parsed, overlap)

    out_path = OUT_PATH_DEFAULT if len(MODELS) == 2 else OUT_PATH_MULTI
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")

    print()
    print(text, end="")
    print(f"\nWrote: {out_path}  ({out_path.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
