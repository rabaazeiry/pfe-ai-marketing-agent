"""Step 4i — V4 vs V5 ablation + V3/V4/V5 final ablation + decision report.

Outputs (under visualizations/v5/):
  compare_rf_v4_vs_v5_pred_vs_actual.png
  compare_xgb_v4_vs_v5_pred_vs_actual.png
  compare_lgb_v4_vs_v5_pred_vs_actual.png
  compare_top_features_v4_vs_v5.png

Plus stdout: V4 vs V5 metrics table + V3/V4/V5 ablation table + SHAP analysis.
And: data/v5_summary_report.txt (decision report).
"""
from __future__ import annotations

import re
import sys
import time
import warnings
from pathlib import Path
from typing import Dict, List, Tuple

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from scipy.stats import spearmanr
from sklearn.metrics import r2_score

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT_DIR = ROOT / "visualizations" / "v5"
OUT_DIR.mkdir(parents=True, exist_ok=True)

MODELS = ("rf", "xgb", "lgb")
VERSIONS = ("v3", "v4", "v5")

PRED_PATHS = {
    (m, v): DATA / f"{m}_{v}_predictions.parquet"
    for m in MODELS for v in VERSIONS
}
RESULTS_PATHS = {
    (m, v): DATA / f"{m}_{v}_results.txt"
    for m in MODELS for v in VERSIONS
}

sns.set_theme(context="paper", style="whitegrid", palette="deep")
plt.rcParams.update({
    "figure.dpi": 150, "savefig.dpi": 150,
    "font.family": "DejaVu Sans",
    "axes.titlesize": 12, "axes.labelsize": 10,
    "xtick.labelsize": 9, "ytick.labelsize": 9,
    "legend.fontsize": 9, "figure.titlesize": 14,
})
INDUSTRY_ORDER = ["beauty", "fashion", "hotels", "patisserie", "restaurants"]
INDUSTRY_PALETTE = dict(zip(INDUSTRY_ORDER, sns.color_palette("deep", 5)))
SHAP_COLOR_V4 = "#3b6e8f"
SHAP_COLOR_V5 = "#c46a3a"


def _load_industry_lookup() -> pd.Series:
    df = pd.read_parquet(DATA / "df_master_masked_with_topics.parquet")
    return pd.Series(
        df["industry_simple"].astype(str).values,
        index=df["post_id"].astype(str).values,
        name="industry_simple",
    )


def _load_preds(model: str, version: str, lookup: pd.Series) -> pd.DataFrame:
    df = pd.read_parquet(PRED_PATHS[(model, version)])
    df["post_id"] = df["post_id"].astype(str)
    df["industry_simple"] = df["post_id"].map(lookup).fillna("unknown")
    return df


# --- SHAP top-15 parser (mirrors phase4_v4_compare.py) --------------------- #

_SHAP_HEADER_RE = re.compile(r"Top 15 features by mean\(\|SHAP\|\)", re.I)
_ROW_RE = re.compile(r"^\s*(\d{1,2})\s+(\S.*?)\s+([0-9.eE+-]+)\s*$")


def _parse_shap_top(path: Path, top_n: int = 15) -> List[Tuple[str, float]]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    in_block = False
    rows: List[Tuple[str, float]] = []
    for line in lines:
        if _SHAP_HEADER_RE.search(line):
            in_block = True
            continue
        if not in_block:
            continue
        if line.strip().startswith("Outputs"):
            break
        if not line.strip() or line.lstrip().startswith(("rank", "----", "===")):
            continue
        m = _ROW_RE.match(line)
        if m:
            try:
                rows.append((m.group(2).strip(), float(m.group(3))))
            except ValueError:
                continue
        if len(rows) >= top_n:
            break
    return rows


def _parse_metric(path: Path, *labels: str) -> float:
    """Parse a single metric line. Tries each label variant in order
    (e.g. RF results use 'R² (log1p scale)' but XGB/LGB use 'R^2 (log1p scale)').
    """
    if not path.exists():
        return float("nan")
    text = path.read_text(encoding="utf-8", errors="replace")
    for label in labels:
        for line in text.splitlines():
            if label in line:
                m = re.search(r"[+-]?\d*\.\d+", line)
                if m:
                    return float(m.group(0))
    return float("nan")


# --- pred-vs-actual side-by-side ------------------------------------------- #

def _scatter(ax, df: pd.DataFrame, title: str) -> Tuple[float, float]:
    sns.scatterplot(
        data=df, x="y_true_log", y="y_pred_log",
        hue="industry_simple", hue_order=INDUSTRY_ORDER,
        palette=INDUSTRY_PALETTE, s=18, alpha=0.7,
        edgecolor="white", linewidth=0.25, ax=ax, legend=False,
    )
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


def plot_pred_vs_actual_compare(model: str, lookup: pd.Series) -> Path:
    df_v4 = _load_preds(model, "v4", lookup)
    df_v5 = _load_preds(model, "v5", lookup)
    fig, axes = plt.subplots(1, 2, figsize=(14, 7))
    r2_v4, rho_v4 = _scatter(axes[0], df_v4, f"{model.upper()} V4 (CLIP+topic_id ordinal)")
    r2_v5, rho_v5 = _scatter(axes[1], df_v5, f"{model.upper()} V5 (+topic one-hot, max_prob)")
    fig.suptitle(
        f"V4 vs V5 — {model.upper()} predicted vs actual    "
        f"ΔR²={r2_v5 - r2_v4:+.4f}    Δρ={rho_v5 - rho_v4:+.4f}",
        y=1.0,
    )
    handles = [plt.Line2D([0], [0], marker="o", color="w",
                          markerfacecolor=INDUSTRY_PALETTE[i],
                          markersize=8, label=i) for i in INDUSTRY_ORDER]
    handles.append(plt.Line2D([0], [0], linestyle="--", color="red", label="y = x"))
    fig.legend(handles=handles, loc="lower center", ncol=6,
               frameon=True, bbox_to_anchor=(0.5, -0.02))
    plt.tight_layout(rect=[0, 0.05, 1, 0.96])
    out = OUT_DIR / f"compare_{model}_v4_vs_v5_pred_vs_actual.png"
    fig.savefig(out, bbox_inches="tight"); plt.close(fig)
    print(f"  wrote {out.name}")
    return out


def _bar_top(ax, pairs: List[Tuple[str, float]], color: str, title: str) -> None:
    if not pairs:
        ax.text(0.5, 0.5, "(SHAP top-15 not found)", ha="center", va="center",
                transform=ax.transAxes, fontsize=11, color="#888")
        ax.set_xticks([]); ax.set_yticks([]); ax.set_title(title); return
    names  = [p[0] for p in pairs][::-1]
    values = [p[1] for p in pairs][::-1]
    ax.barh(names, values, color=color, edgecolor="white")
    ax.set_xlabel("mean(|SHAP|)")
    ax.set_title(title)
    ax.grid(axis="x", alpha=0.3)


def plot_top_features_compare() -> Path:
    fig, axes = plt.subplots(3, 2, figsize=(15, 14))
    for r, model in enumerate(MODELS):
        v4 = _parse_shap_top(RESULTS_PATHS[(model, "v4")])
        v5 = _parse_shap_top(RESULTS_PATHS[(model, "v5")])
        _bar_top(axes[r, 0], v4, SHAP_COLOR_V4,
                 f"{model.upper()}  V4 — top 15 mean(|SHAP|)")
        _bar_top(axes[r, 1], v5, SHAP_COLOR_V5,
                 f"{model.upper()}  V5 (+topic OH, max_prob) — top 15 mean(|SHAP|)")
    fig.suptitle("V4 vs V5 — top-15 features by mean(|SHAP|), all three models",
                 y=0.995)
    fig.text(0.5, 0.005,
             "topic_*  / topic_max_prob features should appear in V5 panels; "
             "compare with V4 to see which features they displace.",
             ha="center", va="bottom", fontsize=9, style="italic", color="#444")
    plt.tight_layout(rect=[0, 0.02, 1, 0.97])
    out = OUT_DIR / "compare_top_features_v4_vs_v5.png"
    fig.savefig(out, bbox_inches="tight"); plt.close(fig)
    print(f"  wrote {out.name}")
    return out


# --- Tables ----------------------------------------------------------------- #

def collect_metrics() -> Dict[Tuple[str, str], Dict[str, float]]:
    out: Dict[Tuple[str, str], Dict[str, float]] = {}
    for m in MODELS:
        for v in VERSIONS:
            r2  = _parse_metric(RESULTS_PATHS[(m, v)],
                                "R² (log1p scale)", "R^2 (log1p scale)")
            rho = _parse_metric(RESULTS_PATHS[(m, v)],
                                "Spearman ρ (pred,y)", "Spearman rho (pred,y)")
            out[(m, v)] = {"r2_log": r2, "spearman_rho": rho}
    return out


def print_v4_v5_table(metrics: Dict) -> str:
    header = f"| {'Model':<6} | {'V4 R²(log)':>10} | {'V5 R²(log)':>10} | {'Δ R²':>7} " \
             f"| {'V4 ρ':>7} | {'V5 ρ':>7} | {'Δ ρ':>7} |"
    sep = "|" + "-" * (len(header) - 2) + "|"
    L = ["", "V4 vs V5 metrics", header, sep]
    for m in MODELS:
        v4 = metrics[(m, "v4")]; v5 = metrics[(m, "v5")]
        L.append(
            f"| {m.upper():<6} | {v4['r2_log']:>+10.4f} | {v5['r2_log']:>+10.4f} "
            f"| {v5['r2_log']-v4['r2_log']:>+7.4f} "
            f"| {v4['spearman_rho']:>+7.4f} | {v5['spearman_rho']:>+7.4f} "
            f"| {v5['spearman_rho']-v4['spearman_rho']:>+7.4f} |"
        )
    text = "\n".join(L)
    print(text)
    return text


def print_ablation_table(metrics: Dict) -> str:
    """V3/V4/V5 ablation: feature counts + best R² per model + best per row."""
    feature_counts = {"v3": 32, "v4": 48, "v5": 69}
    desc = {
        "v3": "32 (incl topic_id ordinal)",
        "v4": "+ 15 CLIP-PCA",
        "v5": "+ topic one-hot + max_prob",
    }
    header = (
        f"| {'Version':<8} | {'Features':<28} | {'RF R²(log)':>10} "
        f"| {'XGB R²(log)':>11} | {'LGB R²(log)':>11} | {'Best':<7} | {'Δ vs V3':>8} |"
    )
    sep = "|" + "-" * (len(header) - 2) + "|"
    L = ["", "V3 / V4 / V5 ablation table", header, sep]
    rf_v3 = metrics[("rf", "v3")]["r2_log"]
    xgb_v3 = metrics[("xgb", "v3")]["r2_log"]
    lgb_v3 = metrics[("lgb", "v3")]["r2_log"]
    best_v3 = max(rf_v3, xgb_v3, lgb_v3)
    for v in VERSIONS:
        rf  = metrics[("rf",  v)]["r2_log"]
        xgb = metrics[("xgb", v)]["r2_log"]
        lgb = metrics[("lgb", v)]["r2_log"]
        triple = {"RF": rf, "XGB": xgb, "LGB": lgb}
        best = max(triple, key=triple.get)
        best_val = triple[best]
        delta = best_val - best_v3
        delta_str = "baseline" if v == "v3" else f"{delta:+.4f}"
        L.append(
            f"| {v.upper():<8} | {desc[v]:<28} | {rf:>+10.4f} | {xgb:>+11.4f} "
            f"| {lgb:>+11.4f} | {best:<7} | {delta_str:>8} |"
        )
    text = "\n".join(L)
    print(text)
    return text


def _full_shap_ranks(model: str, version: str) -> List[Tuple[str, float]]:
    """Recover the full SHAP-ranked feature list (not just top 15) by reading
    the cached SHAP values written by step4i_train_v5_models.py."""
    cache = DATA / f"_shap_values_cached_{model}_{version}.npz"
    if not cache.exists():
        return []
    z = np.load(cache, allow_pickle=False)
    cols = list(z["columns"])
    mean_abs = np.abs(z["shap_values"]).mean(axis=0)
    return sorted(zip(cols, mean_abs.tolist()), key=lambda x: -x[1])


def shap_topic_analysis(metrics: Dict) -> Tuple[str, dict]:
    """For best V5 model: top 20 features, count topic_*, position of topic_max_prob."""
    L: List[str] = ["", "SHAP analysis V5 — best model"]
    L.append("-" * 78)
    v5_scores = {m: metrics[(m, "v5")]["r2_log"] for m in MODELS}
    best = max(v5_scores, key=v5_scores.get)
    L.append(f"  Best V5 model by R²(log): {best.upper()} "
             f"(R²={v5_scores[best]:+.4f})")

    shap_v4_top = _parse_shap_top(RESULTS_PATHS[(best, "v4")])
    shap_v5_full = _full_shap_ranks(best, "v5")  # all 75 OHE features, ranked
    shap_v5_top20 = shap_v5_full[:20]

    L.append("")
    topic_id_rank_v4 = next(
        (i for i, p in enumerate(shap_v4_top, 1) if p[0] == "topic_id"), None,
    )
    L.append(f"  V4 top-15 SHAP for {best.upper()}: topic_id rank = "
             f"{topic_id_rank_v4 or 'NOT IN TOP 15'}")
    n_topic_v5_top15 = sum(1 for p in shap_v5_top20[:15] if p[0].startswith("topic_"))
    n_topic_v5_top20 = sum(1 for p in shap_v5_top20 if p[0].startswith("topic_"))
    L.append(f"  V5 top-15 SHAP for {best.upper()}: "
             f"{n_topic_v5_top15} topic_* features in top 15 "
             f"({n_topic_v5_top20} in top 20)")

    max_prob_rank = next(
        (i for i, p in enumerate(shap_v5_full, 1) if p[0] == "topic_max_prob"),
        None,
    )
    if max_prob_rank is not None:
        mean_abs = shap_v5_full[max_prob_rank - 1][1]
        L.append(f"  topic_max_prob full rank: #{max_prob_rank} / {len(shap_v5_full)}  "
                 f"(mean|SHAP|={mean_abs:.6f})")
    else:
        L.append("  topic_max_prob: feature missing (cache empty?)")

    # Full picture for topic_* features when they're not in top 20.
    topic_ranks = [
        (i, name, val) for i, (name, val) in enumerate(shap_v5_full, 1)
        if name.startswith("topic_")
    ]
    if topic_ranks:
        L.append("")
        L.append(f"  All topic_* features by full SHAP rank (V5, {best.upper()}):")
        L.append(f"  {'rank':<6} {'feature':<24} {'mean|SHAP|':>14}")
        for r, name, val in topic_ranks:
            L.append(f"  #{r:<5} {name:<24} {val:>14.6f}")
        topic_total = sum(v for _, _, v in topic_ranks)
        L.append(f"  Σ mean|SHAP| over all topic_* features: {topic_total:.6f}")

    L.append("")
    L.append(f"  V5 top 20 features for {best.upper()}:")
    L.append(f"  {'rank':<4} {'feature':<32} {'mean|SHAP|':>14}")
    for i, (n, imp) in enumerate(shap_v5_top20, 1):
        marker = "  <-- topic" if n.startswith("topic_") else ""
        L.append(f"  {i:<4} {n:<32} {imp:>14.6f}{marker}")
    text = "\n".join(L)
    print(text)
    return text, dict(
        best_model=best, best_r2=v5_scores[best],
        n_topic_v5_top15=n_topic_v5_top15, n_topic_v5_top20=n_topic_v5_top20,
        max_prob_rank=max_prob_rank, shap_v5=shap_v5_top20,
    )


def write_decision_report(
    metrics: Dict, v4_v5_table: str, ablation_table: str, shap_text: str,
    shap_summary: dict,
) -> Path:
    out_path = DATA / "v5_summary_report.txt"
    best_v5_r2 = max(metrics[(m, "v5")]["r2_log"] for m in MODELS)

    if best_v5_r2 >= 0.46:
        decision = "SUCCESS — proceed to Step 5 (Campaign Generator)"
        rationale = ("Best V5 R²(log) >= 0.46 threshold; topic encoding "
                     "delivered enough signal to move on.")
    elif best_v5_r2 >= 0.43:
        decision = "PARTIAL — consider V5b: add MiniLM doc-embedding PCA"
        rationale = ("Best V5 R²(log) is in [0.43, 0.46) — meaningful gain "
                     "but below SUCCESS bar. Adding 384-d caption embeddings "
                     "(PCA->15) is the next-cheapest signal to try.")
    else:
        decision = "INVESTIGATE — topic encoding did not lift performance"
        rationale = ("Best V5 R²(log) < 0.43 (V4 baseline ~0.421). The topic "
                     "signal already captured by topic_id-as-ordinal in V4 "
                     "may have been most of what BERTopic offered for this "
                     "target. Investigate before adding more features.")

    L: List[str] = []
    L.append("=" * 78)
    L.append("V5 SUMMARY REPORT — Step 4i")
    L.append("=" * 78)
    L.append("")
    L.append("Goal: lift V4 by replacing topic_id (int32 ordinal) with 21 "
             "one-hot bins")
    L.append("      + topic_max_prob (HDBSCAN cluster confidence from "
             "BERTopic.transform).")
    L.append("")
    L.append(f"V5 dataset: data/df_ml_dataset_v5.parquet  (4010 x 69)")
    L.append(f"  V4 cols (48) - topic_id + 21 one-hot + topic_max_prob = 69")
    L.append("")
    L.append(v4_v5_table)
    L.append("")
    L.append(ablation_table)
    L.append("")
    L.append(shap_text)
    L.append("")
    L.append("=" * 78)
    L.append("DECISION")
    L.append("=" * 78)
    L.append(f"  Best V5 R²(log): {best_v5_r2:+.4f}  "
             f"(model: {shap_summary['best_model'].upper()})")
    L.append(f"  Verdict: {decision}")
    L.append("")
    L.append(f"  Rationale: {rationale}")
    L.append("")
    L.append("Decision criteria")
    L.append("-" * 78)
    L.append("  best V5 R² >= 0.46  -> SUCCESS, proceed to Step 5")
    L.append("  best V5 R² in [0.43, 0.46)  -> consider V5b doc-embeddings")
    L.append("  best V5 R² < 0.43  -> investigate before adding features")
    L.append("=" * 78)

    text = "\n".join(L) + "\n"
    out_path.write_text(text, encoding="utf-8")
    print(f"\n  wrote {out_path}")
    return out_path


def main() -> int:
    t0 = time.perf_counter()
    print("=" * 78)
    print("Step 4i — V4 vs V5 comparison + V3/V4/V5 ablation + decision report")
    print("=" * 78)

    # 1. Comparison figures
    print("\n[1/3] Comparison figures (V4 vs V5)")
    lookup = _load_industry_lookup()
    for m in MODELS:
        try:
            plot_pred_vs_actual_compare(m, lookup)
        except FileNotFoundError as e:
            print(f"  [skip] {m.upper()}: {e}")
    plot_top_features_compare()

    # 2. Tables
    print("\n[2/3] Metrics tables")
    metrics = collect_metrics()
    v4_v5_table = print_v4_v5_table(metrics)
    ablation_table = print_ablation_table(metrics)

    # 3. SHAP analysis + decision report
    print("\n[3/3] SHAP analysis V5 + decision report")
    shap_text, shap_summary = shap_topic_analysis(metrics)
    write_decision_report(metrics, v4_v5_table, ablation_table, shap_text, shap_summary)

    print(f"\nElapsed: {time.perf_counter() - t0:.1f} s")
    return 0


if __name__ == "__main__":
    warnings.filterwarnings("ignore", category=UserWarning, module="matplotlib")
    sys.exit(main())
