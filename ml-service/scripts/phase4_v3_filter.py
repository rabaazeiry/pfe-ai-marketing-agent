"""Phase 4 V3 - Step 1/4: backup V2 state, create V3 working copy, filter outliers.

Safety contract:
  - Original df_ml_dataset.parquet is NEVER modified.
  - Existing .bak_v1 / .bak_preleakfix files are NEVER touched.
  - .bak_v2 snapshots are written ONLY if they do not already exist.
  - All filtering happens on the V3 copy: df_ml_dataset_v3.parquet.

Filter pipeline (applied IN ORDER on V3):
  1. Per-industry top 1% engagement_rate (extreme viral posts distort training).
  2. Per-industry bottom 1% engagement_rate (zero-engagement noise floor).
  3. caption_length < 10 chars (too short to be meaningful).

REMOVED on 2026-05-03: days_since_first_post < 30.
  Reason: dropped 632/672 = 94% of all eliminations, removing 27% of
  fashion posts and creating a production blind spot for young brands
  (the agent must serve them at inference time). The remaining two
  filters together drop only ~40 posts and target the actual noise
  sources (extreme tail + meaningless captions).

Does NOT re-train any model. That is Prompt 3b.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import List, Tuple

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
MODELS = ROOT / "models"

ML_PARQUET = DATA / "df_ml_dataset.parquet"
ML_V3      = DATA / "df_ml_dataset_v3.parquet"

BACKUP_PAIRS: List[Tuple[Path, Path]] = [
    (ML_PARQUET,                 DATA  / "df_ml_dataset.parquet.bak_v2"),
    (DATA   / "rf_results.txt",  DATA  / "rf_results.txt.bak_v2"),
    (DATA   / "xgb_results.txt", DATA  / "xgb_results.txt.bak_v2"),
    (MODELS / "rf_best.pkl",     MODELS / "rf_best.pkl.bak_v2"),
    (MODELS / "xgb_best.pkl",    MODELS / "xgb_best.pkl.bak_v2"),
]

TARGET_COL    = "engagement_rate"
INDUSTRY_COL  = "industry_simple"
CAPTION_LEN   = "caption_length"
BRAND_AGE     = "days_since_first_post"

TOP_QUANTILE    = 0.99
BOTTOM_QUANTILE = 0.01
MIN_CAPTION_LEN = 10
MIN_BRAND_AGE   = 30


# --- Step 1: backup V2 state --------------------------------------------------

def backup_v2() -> None:
    print("=" * 88)
    print("STEP 1 - Backup current V2 state to .bak_v2 (only if missing)")
    print("=" * 88)
    for src, dst in BACKUP_PAIRS:
        if not src.exists():
            print(f"  [SKIP] source missing:    {src.relative_to(ROOT)}")
            continue
        if dst.exists():
            print(f"  [KEEP] backup exists:     {dst.relative_to(ROOT)}  "
                  f"({dst.stat().st_size/1024:.1f} KB) - NOT overwriting")
            continue
        shutil.copy2(src, dst)
        print(f"  [NEW]  backed up:         {src.name} -> {dst.name}  "
              f"({dst.stat().st_size/1024:.1f} KB)")


# --- Step 2: V3 working copy --------------------------------------------------

def make_v3_copy() -> None:
    print()
    print("=" * 88)
    print("STEP 2 - Create V3 working copy")
    print("=" * 88)
    if ML_V3.exists():
        print(f"  [REPLACE] V3 copy exists, will be overwritten with fresh "
              f"V2 source ({ML_V3.stat().st_size/1024:.1f} KB)")
    shutil.copy2(ML_PARQUET, ML_V3)
    print(f"  copied {ML_PARQUET.name} -> {ML_V3.name}  "
          f"({ML_V3.stat().st_size/1024:.1f} KB)")


# --- Step 3: filter outliers --------------------------------------------------

def _industry_dist(df: pd.DataFrame, label: str) -> str:
    """Per-industry count + mean engagement, formatted for stdout."""
    g = df.groupby(INDUSTRY_COL, dropna=False)[TARGET_COL].agg(
        ["count", "mean", "median", "std"]
    )
    lines = [f"  {label}"]
    lines.append(f"    {'industry':<14} {'count':>6} {'mean':>9} "
                 f"{'median':>9} {'std':>9}")
    for ind, row in g.iterrows():
        lines.append(f"    {str(ind):<14} {int(row['count']):>6} "
                     f"{row['mean']:>9.4f} {row['median']:>9.4f} "
                     f"{row['std']:>9.4f}")
    lines.append(f"    {'TOTAL':<14} {len(df):>6}")
    return "\n".join(lines)


def _target_summary(s: pd.Series, label: str) -> str:
    qs = s.quantile([0.01, 0.05, 0.25, 0.50, 0.75, 0.95, 0.99])
    return (f"  {label:<28} n={len(s):>5}  mean={s.mean():.4f}  "
            f"std={s.std():.4f}  min={s.min():.4f}  max={s.max():.4f}\n"
            f"    quantiles: p01={qs[0.01]:.4f}  p05={qs[0.05]:.4f}  "
            f"p25={qs[0.25]:.4f}  p50={qs[0.50]:.4f}  "
            f"p75={qs[0.75]:.4f}  p95={qs[0.95]:.4f}  p99={qs[0.99]:.4f}")


def filter_v3() -> pd.DataFrame:
    print()
    print("=" * 88)
    print("STEP 3 - Filter outliers on V3")
    print("=" * 88)

    df = pd.read_parquet(ML_V3)
    n0 = len(df)
    print(f"  loaded V3 working copy: {df.shape}")

    before = df.copy()

    # --- 3a. Stratified per-industry top/bottom 1% on engagement_rate -------
    print()
    print(f"  3a. Per-industry top {(1-TOP_QUANTILE)*100:.0f}% / bottom "
          f"{BOTTOM_QUANTILE*100:.0f}% engagement_rate trim "
          f"(stratified by {INDUSTRY_COL})")

    grp = df.groupby(INDUSTRY_COL, dropna=False)[TARGET_COL]
    upper = grp.transform(lambda s: s.quantile(TOP_QUANTILE))
    lower = grp.transform(lambda s: s.quantile(BOTTOM_QUANTILE))

    # Per-industry threshold print so the user can sanity-check
    thr = (
        df.groupby(INDUSTRY_COL, dropna=False)[TARGET_COL]
        .agg(
            n="count",
            p01=lambda s: s.quantile(BOTTOM_QUANTILE),
            p99=lambda s: s.quantile(TOP_QUANTILE),
        )
    )
    print(f"     per-industry trim thresholds:")
    print(f"     {'industry':<14} {'n':>5} {'p01 (low cut)':>14} "
          f"{'p99 (high cut)':>16}")
    for ind, row in thr.iterrows():
        print(f"     {str(ind):<14} {int(row['n']):>5} "
              f"{row['p01']:>14.4f} {row['p99']:>16.4f}")

    keep_mask_q = (df[TARGET_COL] >= lower) & (df[TARGET_COL] <= upper)
    n_dropped_top    = int(((df[TARGET_COL] > upper)).sum())
    n_dropped_bottom = int(((df[TARGET_COL] < lower)).sum())
    df = df[keep_mask_q].copy()
    n1 = len(df)
    print(f"     dropped TOP    1% per industry: {n_dropped_top:>4} rows")
    print(f"     dropped BOTTOM 1% per industry: {n_dropped_bottom:>4} rows")
    print(f"     after q-trim:  {n0} -> {n1}  "
          f"({n1-n0:+d} / {(n1-n0)/n0*100:+.1f}%)")

    # --- 3b. caption_length < 10 -------------------------------------------
    print()
    print(f"  3b. caption_length < {MIN_CAPTION_LEN} chars")
    keep_mask_cap = df[CAPTION_LEN] >= MIN_CAPTION_LEN
    n_dropped_cap = int((~keep_mask_cap).sum())
    df = df[keep_mask_cap].copy()
    n2 = len(df)
    print(f"     dropped:       {n_dropped_cap:>4} rows")
    print(f"     after caption: {n1} -> {n2}  "
          f"({n2-n1:+d} / {(n2-n1)/max(n1,1)*100:+.1f}%)")

    # --- 3c. days_since_first_post < 30  [REMOVED 2026-05-03] --------------
    # Removed because it dropped 632 rows (94% of all eliminations) and
    # created a young-brand blind spot. See module docstring for details.
    n3 = n2  # kept name for the summary block below

    # --- 3d. Pipeline summary ----------------------------------------------
    print()
    print(f"  PIPELINE SUMMARY")
    print(f"     Original:                     {n0:>5} rows")
    print(f"     After top/bottom 1% (3a):     {n1:>5} rows  "
          f"({n1-n0:+d} / {(n1-n0)/n0*100:+.1f}%)")
    print(f"     After caption_length (3b):    {n2:>5} rows  "
          f"({n2-n1:+d} / {(n2-n1)/max(n1,1)*100:+.1f}%)")
    print(f"     [SKIPPED] days_since_first    (filter removed; would have "
          f"dropped young brands)")
    print(f"     FINAL:                        {n3:>5} rows  "
          f"({n3-n0:+d} / {(n3-n0)/n0*100:+.1f}% vs original)")

    # --- 3e. BEFORE vs AFTER distributions ---------------------------------
    print()
    print("=" * 88)
    print("DISTRIBUTION COMPARISON  (engagement_rate, log-scale-ish)")
    print("=" * 88)
    print(_target_summary(before[TARGET_COL], "BEFORE"))
    print(_target_summary(df[TARGET_COL],     "AFTER "))

    print()
    print("Per-industry comparison")
    print("-" * 88)
    print(_industry_dist(before, "BEFORE"))
    print()
    print(_industry_dist(df,     "AFTER"))

    # --- 3f. Sanity checks --------------------------------------------------
    print()
    print("=" * 88)
    print("SANITY CHECKS")
    print("=" * 88)
    nan_target = int(df[TARGET_COL].isna().sum())
    nan_any    = int(df.isna().any(axis=1).sum())
    n_dupes    = int(df["post_id"].duplicated().sum())
    n_unique   = df["post_id"].nunique()
    print(f"  rows                       {len(df):>5}")
    print(f"  cols                       {df.shape[1]:>5}  (must stay 32)")
    print(f"  NaN in {TARGET_COL!r:<22}{nan_target:>5}")
    print(f"  rows with any NaN          {nan_any:>5}")
    print(f"  duplicate post_id          {n_dupes:>5}")
    print(f"  unique post_id             {n_unique:>5}  "
          f"(should equal rows)")
    print(f"  caption_length min         "
          f"{int(df[CAPTION_LEN].min()):>5}  "
          f"(must be >= {MIN_CAPTION_LEN})")
    print(f"  days_since_first min       "
          f"{df[BRAND_AGE].min():.2f}  "
          f"(filter removed - young brands kept)")
    print(f"  days_since_first p25       "
          f"{df[BRAND_AGE].quantile(0.25):.2f}")

    return df


# --- Step 4: persist V3 + final verification ---------------------------------

def save_and_verify(df_v3: pd.DataFrame) -> None:
    print()
    print("=" * 88)
    print("STEP 4 - Save filtered V3 and verify file integrity")
    print("=" * 88)

    df_v3.to_parquet(ML_V3, index=False)
    print(f"  wrote {ML_V3.name}  ({ML_V3.stat().st_size/1024:.1f} KB)")

    orig = pd.read_parquet(ML_PARQUET)
    bak  = pd.read_parquet(DATA / "df_ml_dataset.parquet.bak_v2")
    v3   = pd.read_parquet(ML_V3)

    print()
    print(f"  Original df_ml_dataset.parquet:        {orig.shape}  "
          f"<- UNCHANGED  (V2 untouched)")
    print(f"  df_ml_dataset.parquet.bak_v2:          {bak.shape}  "
          f"<- BACKUP INTACT")
    print(f"  df_ml_dataset_v3.parquet:              {v3.shape}  "
          f"<- FILTERED V3")

    assert orig.shape == (4127, 32), "ORIGINAL V2 changed!"
    assert bak.shape  == (4127, 32), "V2 backup wrong shape!"
    assert v3.shape[1] == 32,        "V3 column count drifted!"
    assert v3.shape[0] < orig.shape[0], "V3 has same/more rows than V2!"
    print()
    print("  All invariants OK.")


def main() -> None:
    backup_v2()
    make_v3_copy()
    df_v3 = filter_v3()
    save_and_verify(df_v3)
    print()
    print("STOP. No model re-training in this step. Continue with Prompt 3b.")


if __name__ == "__main__":
    main()
