"""Build df_ml_dataset_v4.parquet — V3 features + 15 CLIP PCs.

Strategy (Ju 2024 / Mishra 2025): filter, don't fill. Posts that have no
visual asset (has_clip=False) get dropped from V4 rather than imputed.
The PCA basis is fitted on the full 4048 posts in step4h.6 and is NOT
re-fit here — we just join the precomputed PC scores.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

V3 = DATA / "df_ml_dataset_v3.parquet"
PCA_FEATS = DATA / "step4h" / "df_post_clip_pca.parquet"
OUT = DATA / "df_ml_dataset_v4.parquet"


def main() -> int:
    print("=" * 70)
    print("Build df_ml_dataset_v4.parquet (V3 + CLIP-PCA)")
    print("=" * 70)
    v3 = pd.read_parquet(V3)
    pca = pd.read_parquet(PCA_FEATS)
    print(f"V3              : {v3.shape}")
    print(f"CLIP PCA        : {pca.shape}")

    pc_cols = [c for c in pca.columns if c.startswith("clip_pc")]
    print(f"PC columns added: {len(pc_cols)}")

    # inner join — drop posts with no CLIP embedding (filter, don't fill)
    keep = pca[["post_id", "n_assets", *pc_cols]].rename(
        columns={"n_assets": "clip_n_assets"}
    )
    v4 = v3.merge(keep, on="post_id", how="inner")
    print(f"V4 (inner join) : {v4.shape}")
    print(f"Lost vs V3      : {len(v3) - len(v4)}  "
          "(posts with no scraped visual)")
    print()
    print("by industry_simple:")
    print(v4["industry_simple"].value_counts())
    print()
    print("by content_type:")
    print(v4["content_type"].value_counts())

    v4.to_parquet(OUT, index=False)
    print(f"\nWrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
