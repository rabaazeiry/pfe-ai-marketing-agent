"""STEP-0 sanity probe for Phase 4.1. Read-only — no training."""
from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
IN = ROOT / "data" / "df_ml_dataset.parquet"

df = pd.read_parquet(IN)
print(f"path: {IN}")
print(f"shape: {df.shape}")
print()
print("--- df.head(3) ---")
with pd.option_context("display.width", 200, "display.max_columns", None):
    print(df.head(3))
print()
print("--- df.dtypes ---")
print(df.dtypes.to_string())
print()
print("--- df['engagement_rate'].describe() ---")
print(df["engagement_rate"].describe().to_string())
print()
print("--- df['industry_simple'].value_counts() ---")
print(df["industry_simple"].value_counts().to_string())
print()
print(f"min industry_simple class size: {df['industry_simple'].value_counts().min()}")
print(f"# unique post_id: {df['post_id'].nunique()}  (rows: {len(df)})")
print(f"# nulls per col (>0 only):")
nn = df.isna().sum()
print(nn[nn > 0].to_string() if (nn > 0).any() else "  (none)")
