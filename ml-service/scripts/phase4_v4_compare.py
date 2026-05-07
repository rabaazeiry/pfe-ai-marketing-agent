"""Step V4 ablation — V3 (no CLIP) vs V4 (+15 CLIP-PCA) side-by-side.

Generates 4 thesis-quality comparison figures in `visualizations/v4/`:

  1. compare_rf_v3_vs_v4_pred_vs_actual.png   — paired scatter; titles
                                                  show ΔR² and Δρ.
  2. compare_xgb_v3_vs_v4_pred_vs_actual.png  — same, for XGB.
  3. compare_lgb_v3_vs_v4_pred_vs_actual.png  — same, for LGB.
  4. compare_top_features_v3_vs_v4.png        — 3×2 grid of horizontal-bar
                                                  charts (RF/XGB/LGB rows;
                                                  V3 left, V4 right) showing
                                                  top-15 mean(|SHAP|).

Predictions are read from the persisted parquet artefacts written by the
training scripts; SHAP top-15 lists are read back from each model's
*_results.txt (parsed deterministically).
"""
from __future__ import annotations

import re
import sys
import time
import warnings
from pathlib import Path
from typing import List, Tuple

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from scipy.stats import spearmanr
from sklearn.metrics import r2_score

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT_DIR = ROOT / "visualizations" / "v4"
OUT_DIR.mkdir(parents=True, exist_ok=True)

MODELS = ("rf", "xgb", "lgb")
PRED_PATHS = {
    ("rf", "v3"):  DATA / "rf_v3_predictions.parquet",
    ("rf", "v4"):  DATA / "rf_v4_predictions.parquet",
    ("xgb", "v3"): DATA / "xgb_v3_predictions.parquet",
    ("xgb", "v4"): DATA / "xgb_v4_predictions.parquet",
    ("lgb", "v3"): DATA / "lgb_v3_predictions.parquet",
    ("lgb", "v4"): DATA / "lgb_v4_predictions.parquet",
}
RESULTS_PATHS = {
    ("rf", "v3"):  DATA / "rf_v3_results.txt",
    ("rf", "v4"):  DATA / "rf_v4_results.txt",
    ("xgb", "v3"): DATA / "xgb_v3_results.txt",
    ("xgb", "v4"): DATA / "xgb_v4_results.txt",
    ("lgb", "v3"): DATA / "lgb_v3_results.txt",
    ("lgb", "v4"): DATA / "lgb_v4_results.txt",
}

# Style — identical to phase4_*_visualize.py for visual parity.
sns.set_theme(context="paper", style="whitegrid", palette="deep")
plt.rcParams.update({
    "figure.dpi": 150,
    "savefig.dpi": 150,
    "font.family": "DejaVu Sans",
    "axes.titlesize": 12,
    "axes.labelsize": 10,
    "xtick.labelsize": 9,
    "ytick.labelsize": 9,
    "legend.fontsize": 9,
    "figure.titlesize": 14,
})
INDUSTRY_ORDER = ["beauty", "fashion", "hotels", "patisserie", "restaurants"]
INDUSTRY_PALETTE = dict(zip(INDUSTRY_ORDER, sns.color_palette("deep", 5)))
SHAP_COLOR_V3 = "#3b6e8f"
SHAP_COLOR_V4 = "#c46a3a"


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


# --- SHAP top-15 parser ---------------------------------------------------- #

_SHAP_HEADER_RE = re.compile(r"Top 15 features by mean\(\|SHAP\|\)", re.I)
# Each top-15 row looks like:  "  1    brand_engagement_rate          0.061618"
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
        # skip header / divider / blank
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


# --- Figures 1-3: pred-vs-actual side-by-side ------------------------------ #

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
    ax.set_xlim(lim_lo, lim_hi)
    ax.set_ylim(lim_lo, lim_hi)
    ax.set_xlabel("Actual log1p(engagement_rate)")
    ax.set_ylabel("Predicted log1p(engagement_rate)")
    ax.set_title(f"{title}\nR² = {r2:+.4f}    ρ = {rho:+.4f}    n = {len(df):,}")
    return r2, rho


def plot_pred_vs_actual_compare(model: str, lookup: pd.Series) -> Path:
    print(f"  pred-vs-actual: {model.upper()} V3 vs V4 ...")
    df_v3 = _load_preds(model, "v3", lookup)
    df_v4 = _load_preds(model, "v4", lookup)
    fig, axes = plt.subplots(1, 2, figsize=(14, 7))
    r2_v3, rho_v3 = _scatter(axes[0], df_v3, f"{model.upper()} V3 (no CLIP)")
    r2_v4, rho_v4 = _scatter(axes[1], df_v4, f"{model.upper()} V4 (+15 CLIP-PCA)")
    fig.suptitle(
        f"V3 vs V4 — {model.upper()} predicted vs actual    "
        f"ΔR²={r2_v4 - r2_v3:+.4f}    Δρ={rho_v4 - rho_v3:+.4f}",
        y=1.0,
    )
    # Single legend at the bottom for the whole figure.
    handles = [plt.Line2D([0], [0], marker="o", color="w",
                          markerfacecolor=INDUSTRY_PALETTE[i],
                          markersize=8, label=i) for i in INDUSTRY_ORDER]
    handles.append(plt.Line2D([0], [0], linestyle="--", color="red",
                              label="y = x"))
    fig.legend(handles=handles, loc="lower center", ncol=6,
               frameon=True, bbox_to_anchor=(0.5, -0.02))
    plt.tight_layout(rect=[0, 0.05, 1, 0.96])
    out = OUT_DIR / f"compare_{model}_v3_vs_v4_pred_vs_actual.png"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    print(f"    wrote {out.name}")
    return out


# --- Figure 4: top-features SHAP comparison -------------------------------- #

def _bar_top(ax, pairs: List[Tuple[str, float]], color: str, title: str) -> None:
    if not pairs:
        ax.text(0.5, 0.5, "(SHAP top-15 not found)",
                ha="center", va="center", transform=ax.transAxes,
                fontsize=11, color="#888")
        ax.set_xticks([]); ax.set_yticks([])
        ax.set_title(title)
        return
    names = [p[0] for p in pairs][::-1]
    values = [p[1] for p in pairs][::-1]
    ax.barh(names, values, color=color, edgecolor="white")
    ax.set_xlabel("mean(|SHAP|)")
    ax.set_title(title)
    ax.grid(axis="x", alpha=0.3)


def plot_top_features_compare() -> Path:
    print("  top-features: RF / XGB / LGB  V3 vs V4 ...")
    fig, axes = plt.subplots(3, 2, figsize=(15, 14))
    for r, model in enumerate(MODELS):
        v3 = _parse_shap_top(RESULTS_PATHS[(model, "v3")])
        v4 = _parse_shap_top(RESULTS_PATHS[(model, "v4")])
        _bar_top(axes[r, 0], v3, SHAP_COLOR_V3,
                 f"{model.upper()}  V3 (no CLIP) — top 15 mean(|SHAP|)")
        _bar_top(axes[r, 1], v4, SHAP_COLOR_V4,
                 f"{model.upper()}  V4 (+15 CLIP-PCA) — top 15 mean(|SHAP|)")
    fig.suptitle(
        "V3 vs V4 — top-15 features by mean(|SHAP|), all three models",
        y=0.995,
    )
    fig.text(
        0.5, 0.005,
        "CLIP-PCA features (clip_pcXX, clip_n_assets) appear in V4 panels; "
        "compare ranks against V3 to see which tabular features they displace.",
        ha="center", va="bottom", fontsize=9, style="italic", color="#444",
    )
    plt.tight_layout(rect=[0, 0.02, 1, 0.97])
    out = OUT_DIR / "compare_top_features_v3_vs_v4.png"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    print(f"    wrote {out.name}")
    return out


def main() -> int:
    t0 = time.perf_counter()
    print("=" * 88)
    print("V3 vs V4 ablation — comparison figures under visualizations/v4/")
    print("=" * 88)
    lookup = _load_industry_lookup()
    written: List[Path] = []
    for m in MODELS:
        try:
            written.append(plot_pred_vs_actual_compare(m, lookup))
        except FileNotFoundError as e:
            print(f"  [skip] {m.upper()}: missing parquet -> {e}")
    written.append(plot_top_features_compare())
    print()
    print(f"Wrote {len(written)} comparison figures:")
    for p in written:
        print(f"  - {p.name}")
    print(f"Elapsed: {time.perf_counter() - t0:.1f} s")
    return 0


if __name__ == "__main__":
    warnings.filterwarnings("ignore", category=UserWarning, module="matplotlib")
    sys.exit(main())
