"""Step 4h.8 — Merge CLIP PCA features into df_master.

Joins df_master_masked_with_topics (38 cols typical) with df_post_clip_pca
(15 PC columns) on post_id. Posts without a CLIP embedding receive NaN PC
columns; we surface a `has_clip` boolean for downstream models.

Output: data/df_master_with_clip.parquet
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
STEP4H = DATA / "step4h"

DF_MASTER = DATA / "df_master_masked_with_topics.parquet"
DF_PCA = STEP4H / "df_post_clip_pca.parquet"
OUT = DATA / "df_master_with_clip.parquet"


def main() -> int:
    print("=" * 70)
    print("STEP 4h.8 — merge df_master + CLIP-PCA")
    print("=" * 70)

    master = pd.read_parquet(DF_MASTER)
    pca = pd.read_parquet(DF_PCA).drop(columns=["content_type"], errors="ignore")
    print(f"master         : {master.shape}")
    print(f"clip pca       : {pca.shape}")

    pc_cols = [c for c in pca.columns if c.startswith("clip_pc")]
    merged = master.merge(pca, on="post_id", how="left")
    merged["has_clip"] = merged[pc_cols[0]].notna()
    merged["clip_n_assets"] = merged["n_assets"].fillna(0).astype(int)
    merged = merged.drop(columns=["n_assets"], errors="ignore")

    print(f"merged         : {merged.shape}")
    print(f"posts w/ clip  : {merged['has_clip'].sum()} / {len(merged)}")
    print(f"missing per content_type:")
    print(merged.groupby("content_type")["has_clip"].agg(["count", "sum"]))

    merged.to_parquet(OUT, index=False)
    print(f"\nWrote {OUT}")
    print(f"Total columns  : {merged.shape[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
