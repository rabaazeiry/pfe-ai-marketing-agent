"""Step 4j (V5c) — V5 vs V5c comparison + V3/V4/V5/V5c ablation +
SHAP-category breakdown + evolution figure + decision report.

Outputs (under visualizations/v5c/):
  compare_rf_v5_vs_v5c_pred_vs_actual.png
  compare_xgb_v5_vs_v5c_pred_vs_actual.png
  compare_lgb_v5_vs_v5c_pred_vs_actual.png
  compare_top_features_v5_vs_v5c.png
  shap_v5c_feature_categories.png
  v3_v4_v5_v5c_evolution.png

Plus:
  data/v5c_summary_report.txt   -- decision report (criteria-based verdict)
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
OUT_DIR = ROOT / "visualizations" / "v5c"
OUT_DIR.mkdir(parents=True, exist_ok=True)

MODELS = ("rf", "xgb", "lgb")
VERSIONS = ("v3", "v4", "v5", "v5c")

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
SHAP_COLOR_BASE = "#3b6e8f"
SHAP_COLOR_NEW  = "#c46a3a"

# Feature-category palette for shap_v5c_feature_categories.png + evolution
CATEGORY_COLORS = {
    "tabular":  "#3b6e8f",
    "CLIP":     "#7a9d54",
    "topic":    "#c46a3a",
    "mpnet":    "#8856a7",
    "industry": "#a0a0a0",
}

# Per-version model+features color palette for the evolution figure.
MODEL_COLORS = {
    "rf":  "#3b6e8f",
    "xgb": "#c46a3a",
    "lgb": "#7a9d54",
}


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


# --- SHAP top-15 parser --- #

_SHAP_HEADER_RE = re.compile(r"Top 15 features by mean\(\|SHAP\|\)", re.I)
_ROW_RE = re.compile(r"^\s*(\d{1,2})\s+(\S.*?)\s+([0-9.eE+-]+)\s*$")


def _parse_shap_top(path: Path, top_n: int = 15) -> List[Tuple[str, float]]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    in_block = False; rows: List[Tuple[str, float]] = []
    for line in lines:
        if _SHAP_HEADER_RE.search(line):
            in_block = True; continue
        if not in_block: continue
        if line.strip().startswith("Outputs"): break
        if not line.strip() or line.lstrip().startswith(("rank", "----", "===")):
            continue
        m = _ROW_RE.match(line)
        if m:
            try:
                rows.append((m.group(2).strip(), float(m.group(3))))
            except ValueError:
                continue
        if len(rows) >= top_n: break
    return rows


def _parse_metric(path: Path, *labels: str) -> float:
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


def _full_shap_ranks(model: str, version: str) -> List[Tuple[str, float]]:
    cache = DATA / f"_shap_values_cached_{model}_{version}.npz"
    if not cache.exists():
        return []
    z = np.load(cache, allow_pickle=False)
    cols = list(z["columns"])
    mean_abs = np.abs(z["shap_values"]).mean(axis=0)
    return sorted(zip(cols, mean_abs.tolist()), key=lambda x: -x[1])


# --- Categorize features --- #

def _category(name: str) -> str:
    if name.startswith("doc_pc"):                       return "mpnet"
    if name.startswith(("clip_pc", "clip_n_assets")):   return "CLIP"
    if name.startswith("topic_"):                       return "topic"
    if (name.startswith(("industry_simple_", "content_type_", "caption_lang_"))):
        return "industry"
    return "tabular"


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
    df_v5  = _load_preds(model, "v5",  lookup)
    df_v5c = _load_preds(model, "v5c", lookup)
    fig, axes = plt.subplots(1, 2, figsize=(14, 7))
    r2_v5,  rho_v5  = _scatter(axes[0], df_v5,  f"{model.upper()} V5 (CLIP+topic OH)")
    r2_v5c, rho_v5c = _scatter(axes[1], df_v5c, f"{model.upper()} V5c (+15 mpnet doc-PCA)")
    fig.suptitle(
        f"V5 vs V5c — {model.upper()} predicted vs actual    "
        f"ΔR²={r2_v5c - r2_v5:+.4f}    Δρ={rho_v5c - rho_v5:+.4f}",
        y=1.0,
    )
    handles = [plt.Line2D([0], [0], marker="o", color="w",
                          markerfacecolor=INDUSTRY_PALETTE[i],
                          markersize=8, label=i) for i in INDUSTRY_ORDER]
    handles.append(plt.Line2D([0], [0], linestyle="--", color="red", label="y = x"))
    fig.legend(handles=handles, loc="lower center", ncol=6,
               frameon=True, bbox_to_anchor=(0.5, -0.02))
    plt.tight_layout(rect=[0, 0.05, 1, 0.96])
    out = OUT_DIR / f"compare_{model}_v5_vs_v5c_pred_vs_actual.png"
    fig.savefig(out, bbox_inches="tight"); plt.close(fig)
    print(f"  wrote {out.name}")
    return out


def _bar_top(ax, pairs, color, title):
    if not pairs:
        ax.text(0.5, 0.5, "(SHAP top-15 not found)", ha="center", va="center",
                transform=ax.transAxes, fontsize=11, color="#888")
        ax.set_xticks([]); ax.set_yticks([]); ax.set_title(title); return
    names  = [p[0] for p in pairs][::-1]
    values = [p[1] for p in pairs][::-1]
    ax.barh(names, values, color=color, edgecolor="white")
    ax.set_xlabel("mean(|SHAP|)"); ax.set_title(title); ax.grid(axis="x", alpha=0.3)


def plot_top_features_compare() -> Path:
    fig, axes = plt.subplots(3, 2, figsize=(15, 14))
    for r, model in enumerate(MODELS):
        v5  = _parse_shap_top(RESULTS_PATHS[(model, "v5")])
        v5c = _parse_shap_top(RESULTS_PATHS[(model, "v5c")])
        _bar_top(axes[r, 0], v5,  SHAP_COLOR_BASE,
                 f"{model.upper()}  V5 — top 15 mean(|SHAP|)")
        _bar_top(axes[r, 1], v5c, SHAP_COLOR_NEW,
                 f"{model.upper()}  V5c (+mpnet) — top 15 mean(|SHAP|)")
    fig.suptitle("V5 vs V5c — top-15 features by mean(|SHAP|), all three models",
                 y=0.995)
    fig.text(0.5, 0.005,
             "doc_pcXX (mpnet caption embeddings) should appear in V5c panels; "
             "compare ranks against V5 to see which features they displace.",
             ha="center", va="bottom", fontsize=9, style="italic", color="#444")
    plt.tight_layout(rect=[0, 0.02, 1, 0.97])
    out = OUT_DIR / "compare_top_features_v5_vs_v5c.png"
    fig.savefig(out, bbox_inches="tight"); plt.close(fig)
    print(f"  wrote {out.name}")
    return out


# --- Tables --- #

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


def print_v5_v5c_table(metrics: Dict) -> str:
    header = (f"| {'Model':<6} | {'V5 R²(log)':>10} | {'V5c R²(log)':>11} "
              f"| {'Δ R²':>7} | {'V5 ρ':>7} | {'V5c ρ':>7} | {'Δ ρ':>7} |")
    sep = "|" + "-" * (len(header) - 2) + "|"
    L = ["", "V5 vs V5c metrics", header, sep]
    for m in MODELS:
        v5  = metrics[(m, "v5")]; v5c = metrics[(m, "v5c")]
        L.append(
            f"| {m.upper():<6} | {v5['r2_log']:>+10.4f} | {v5c['r2_log']:>+11.4f} "
            f"| {v5c['r2_log']-v5['r2_log']:>+7.4f} "
            f"| {v5['spearman_rho']:>+7.4f} | {v5c['spearman_rho']:>+7.4f} "
            f"| {v5c['spearman_rho']-v5['spearman_rho']:>+7.4f} |"
        )
    text = "\n".join(L); print(text); return text


def print_ablation_table(metrics: Dict) -> str:
    desc = {
        "v3":  "32 (incl topic_id ordinal)",
        "v4":  "+ 15 CLIP-PCA",
        "v5":  "+ topic OH + max_prob",
        "v5c": "+ 15 mpnet doc-PCA",
    }
    header = (
        f"| {'Version':<8} | {'Features':<28} | {'RF R²(log)':>10} "
        f"| {'XGB R²(log)':>11} | {'LGB R²(log)':>11} | {'Best':<7} | {'Δ vs V3':>9} |"
    )
    sep = "|" + "-" * (len(header) - 2) + "|"
    L = ["", "V3 / V4 / V5 / V5c ablation table", header, sep]
    rf_v3  = metrics[("rf",  "v3")]["r2_log"]
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
            f"| {lgb:>+11.4f} | {best:<7} | {delta_str:>9} |"
        )
    text = "\n".join(L); print(text); return text


def shap_categories_for_best(metrics: Dict) -> Tuple[str, dict, Path]:
    """Step 14 — categorize top SHAP features for the best V5c model."""
    L: List[str] = ["", "SHAP analysis V5c — best model + category breakdown"]
    L.append("-" * 78)
    v5c_scores = {m: metrics[(m, "v5c")]["r2_log"] for m in MODELS}
    best = max(v5c_scores, key=v5c_scores.get)
    L.append(f"  Best V5c model by R²(log): {best.upper()} "
             f"(R²={v5c_scores[best]:+.4f})")

    full = _full_shap_ranks(best, "v5c")
    top20 = full[:20]
    top15 = full[:15]
    by_cat_top20 = {}
    by_cat_top15 = {}
    for name, val in top20:
        c = _category(name)
        by_cat_top20.setdefault(c, []).append((name, val))
    for name, val in top15:
        c = _category(name)
        by_cat_top15.setdefault(c, []).append((name, val))

    L.append("")
    L.append("  Category breakdown — top 15:")
    total15 = max(1, len(top15))
    for c in ["tabular", "industry", "CLIP", "topic", "mpnet"]:
        n = len(by_cat_top15.get(c, []))
        L.append(f"    {c:<10}  {n:>2}  ({100*n/total15:5.1f}%)")
    L.append("")
    L.append("  Category breakdown — top 20:")
    total20 = max(1, len(top20))
    for c in ["tabular", "industry", "CLIP", "topic", "mpnet"]:
        n = len(by_cat_top20.get(c, []))
        L.append(f"    {c:<10}  {n:>2}  ({100*n/total20:5.1f}%)")

    L.append("")
    L.append(f"  V5c top 20 features for {best.upper()}:")
    L.append(f"  {'rank':<4} {'feature':<32} {'mean|SHAP|':>14}  category")
    for i, (n, imp) in enumerate(top20, 1):
        L.append(f"  {i:<4} {n:<32} {imp:>14.6f}  {_category(n)}")

    # Plot pie/bar of category share (top 15 only).
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.5))
    cats = ["tabular", "industry", "CLIP", "topic", "mpnet"]
    counts = [len(by_cat_top15.get(c, [])) for c in cats]
    colors = [CATEGORY_COLORS[c] for c in cats]
    axes[0].bar(cats, counts, color=colors, edgecolor="white")
    axes[0].set_title(f"V5c {best.upper()} — top-15 SHAP feature counts by category")
    axes[0].set_ylabel("number of features in top 15")
    axes[0].grid(axis="y", alpha=0.3)
    for i, n in enumerate(counts):
        axes[0].text(i, n + 0.1, str(n), ha="center", va="bottom", fontsize=10)

    # Sum of mean|SHAP| per category (top 15 only) — measures "weight"
    weight = []
    for c in cats:
        weight.append(sum(v for _, v in by_cat_top15.get(c, [])))
    axes[1].bar(cats, weight, color=colors, edgecolor="white")
    axes[1].set_title(f"V5c {best.upper()} — top-15 Σ mean(|SHAP|) by category")
    axes[1].set_ylabel("Σ mean(|SHAP|) over top-15")
    axes[1].grid(axis="y", alpha=0.3)
    for i, w in enumerate(weight):
        axes[1].text(i, w + max(weight) * 0.01, f"{w:.4f}",
                     ha="center", va="bottom", fontsize=9)

    fig.suptitle(f"SHAP feature-category breakdown — {best.upper()} V5c (top 15)",
                 y=1.0)
    plt.tight_layout(rect=[0, 0.04, 1, 0.95])
    fig.text(0.5, 0.005,
             "Left: count of top-15 features per category. "
             "Right: cumulative SHAP magnitude — captures weight, not just count.",
             ha="center", va="bottom", fontsize=9, style="italic", color="#444")
    out = OUT_DIR / "shap_v5c_feature_categories.png"
    fig.savefig(out, dpi=150, bbox_inches="tight"); plt.close(fig)
    print(f"  wrote {out.name}")

    text = "\n".join(L); print(text)
    return text, dict(
        best_model=best, best_r2=v5c_scores[best],
        top_features=top20, by_category_top15=by_cat_top15,
    ), out


def plot_evolution(metrics: Dict) -> Path:
    """Step 15 — bar chart R²(log) per version × per model."""
    fig, ax = plt.subplots(figsize=(10, 6))
    versions = list(VERSIONS)
    n_v = len(versions); n_m = len(MODELS)
    x = np.arange(n_v); width = 0.26

    for i, m in enumerate(MODELS):
        vals = [metrics[(m, v)]["r2_log"] for v in versions]
        bars = ax.bar(x + (i - 1) * width, vals, width=width,
                      color=MODEL_COLORS[m], edgecolor="white",
                      label=m.upper())
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v + 0.005,
                    f"{v:.3f}", ha="center", va="bottom", fontsize=8)

    # Highlight champion per version
    for i, v in enumerate(versions):
        triple = {m: metrics[(m, v)]["r2_log"] for m in MODELS}
        champ = max(triple, key=triple.get)
        idx = list(MODELS).index(champ)
        ax.scatter([i + (idx - 1) * width], [triple[champ] + 0.025],
                   marker="*", s=220, color="#cc1111", zorder=5,
                   label="version champion" if i == 0 else None)

    ax.set_xticks(x)
    ax.set_xticklabels([v.upper() for v in versions])
    ax.set_ylabel("R² (log1p engagement_rate)")
    ax.set_title("Model evolution — R²(log) per dataset version × model\n"
                 "★ = best model for that version")
    ax.legend(loc="lower right", frameon=True)
    ax.grid(axis="y", alpha=0.3)
    ax.set_ylim(0, max(metrics[k]["r2_log"] for k in metrics) * 1.15)
    plt.tight_layout()
    out = OUT_DIR / "v3_v4_v5_v5c_evolution.png"
    fig.savefig(out, dpi=150, bbox_inches="tight"); plt.close(fig)
    print(f"  wrote {out.name}")
    return out


def write_decision_report(metrics: Dict, v5_v5c_table: str, ablation_table: str,
                          shap_text: str, shap_summary: dict) -> Path:
    out_path = DATA / "v5c_summary_report.txt"
    best_v5c_r2 = max(metrics[(m, "v5c")]["r2_log"] for m in MODELS)
    best_v5_r2  = max(metrics[(m, "v5")]["r2_log"] for m in MODELS)
    best_v3_r2  = max(metrics[(m, "v3")]["r2_log"] for m in MODELS)

    if best_v5c_r2 >= 0.48:
        decision = "EXCELLENT — ML phase done; proceed to Step 5"
        rationale = ("Best V5c R²(log) >= 0.48 — strong performance from "
                     "tabular + visual + topic + caption-semantic features.")
    elif best_v5c_r2 >= 0.45:
        decision = "GOOD — consider stacking ensemble (V6) for marginal lift"
        rationale = ("Best V5c R²(log) in [0.45, 0.48). Stacking RF + XGB + LGB "
                     "could add ~1-2 pp; otherwise ML signal is mostly captured.")
    elif best_v5c_r2 >= 0.43:
        decision = "MARGINAL — consider hyperparameter retune for V5c features"
        rationale = ("V5c added 15 mpnet-PCA features without re-tuning; the "
                     "V4 hyperparameters may not be optimal for the wider "
                     "feature space (75 -> 90 cols after OHE). Retune RF/XGB.")
    else:
        decision = "SATURATED — ML signal exhausted; stop adding features"
        rationale = ("Best V5c R²(log) < 0.43. Adding mpnet features did not "
                     "lift performance. Move to Step 5 with the V5 champion.")

    delta_v3 = best_v5c_r2 - best_v3_r2
    delta_v5 = best_v5c_r2 - best_v5_r2

    L: List[str] = []
    L.append("=" * 78)
    L.append("V5c SUMMARY REPORT — Step 4j")
    L.append("=" * 78)
    L.append("")
    L.append("Goal: lift V5 by adding 15 PCA-reduced mpnet caption embeddings")
    L.append("      (paraphrase-multilingual-mpnet-base-v2, 768-dim source).")
    L.append("")
    L.append("V5c dataset: data/df_ml_dataset_v5c.parquet  (~4010 x 84)")
    L.append("  V5 cols (69) + 15 doc-PC = 84")
    L.append("")
    L.append(v5_v5c_table)
    L.append("")
    L.append(ablation_table)
    L.append("")
    L.append(shap_text)
    L.append("")
    L.append("=" * 78)
    L.append("DECISION")
    L.append("=" * 78)
    L.append(f"  Best V5c R²(log): {best_v5c_r2:+.4f}  "
             f"(model: {shap_summary['best_model'].upper()})")
    L.append(f"  Δ vs V5  best:    {delta_v5:+.4f}  "
             f"({'gain' if delta_v5 > 0 else 'regression'})")
    L.append(f"  Δ vs V3  best:    {delta_v3:+.4f}  (cumulative)")
    L.append("")
    L.append(f"  Verdict: {decision}")
    L.append("")
    L.append(f"  Rationale: {rationale}")
    L.append("")
    L.append("Decision criteria")
    L.append("-" * 78)
    L.append("  best V5c R² >= 0.48  -> EXCELLENT, proceed to Step 5")
    L.append("  best V5c R² in [0.45, 0.48)  -> GOOD, consider V6 stacking")
    L.append("  best V5c R² in [0.43, 0.45)  -> MARGINAL, hyperparameter retune")
    L.append("  best V5c R² < 0.43  -> SATURATED, stop adding features")
    L.append("=" * 78)
    text = "\n".join(L) + "\n"
    out_path.write_text(text, encoding="utf-8")
    print(f"\n  wrote {out_path}")
    return out_path


def print_final_summary(metrics: Dict, files_written: List[Path]) -> None:
    print("\n" + "=" * 78)
    print("STEP 17 — Final summary")
    print("=" * 78)
    for v in VERSIONS:
        triple = {m: metrics[(m, v)]["r2_log"] for m in MODELS}
        champ = max(triple, key=triple.get)
        print(f"  {v.upper():<4}  best model = {champ.upper():<3}  "
              f"R²(log) = {triple[champ]:+.4f}  "
              f"(RF {triple['rf']:+.4f}  XGB {triple['xgb']:+.4f}  "
              f"LGB {triple['lgb']:+.4f})")
    best_v3 = max(metrics[(m, "v3")]["r2_log"] for m in MODELS)
    best_v5c = max(metrics[(m, "v5c")]["r2_log"] for m in MODELS)
    print(f"\n  Cumulative gain V3 -> V5c: {best_v5c - best_v3:+.4f} R² "
          f"(+{100*(best_v5c - best_v3)/best_v3:.1f}% relative)")
    print(f"\n  Files written:")
    for p in files_written:
        if p.exists():
            print(f"    - {p.relative_to(ROOT)}  ({p.stat().st_size/1024:.1f} KB)")


def main() -> int:
    t0 = time.perf_counter()
    print("=" * 78)
    print("Step 4j — V5 vs V5c comparison + V3/V4/V5/V5c ablation + report")
    print("=" * 78)

    written: List[Path] = []

    # 1. Comparison figures
    print("\n[1/5] Comparison figures (V5 vs V5c)")
    lookup = _load_industry_lookup()
    for m in MODELS:
        try:
            written.append(plot_pred_vs_actual_compare(m, lookup))
        except FileNotFoundError as e:
            print(f"  [skip] {m.upper()}: {e}")
    written.append(plot_top_features_compare())

    # 2. Tables
    print("\n[2/5] Metrics tables")
    metrics = collect_metrics()
    v5_v5c_table = print_v5_v5c_table(metrics)
    ablation_table = print_ablation_table(metrics)

    # 3. SHAP categories + figure
    print("\n[3/5] SHAP analysis V5c + category breakdown figure")
    shap_text, shap_summary, shap_fig = shap_categories_for_best(metrics)
    written.append(shap_fig)

    # 4. Evolution figure
    print("\n[4/5] Evolution figure V3 → V4 → V5 → V5c")
    written.append(plot_evolution(metrics))

    # 5. Decision report
    print("\n[5/5] Decision report")
    report_path = write_decision_report(metrics, v5_v5c_table, ablation_table,
                                        shap_text, shap_summary)
    written.append(report_path)

    print_final_summary(metrics, written)
    print(f"\nElapsed: {time.perf_counter() - t0:.1f} s")
    return 0


if __name__ == "__main__":
    warnings.filterwarnings("ignore", category=UserWarning, module="matplotlib")
    sys.exit(main())
