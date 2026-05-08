"""Step 4j (V5c) — Build df_ml_dataset_v5c.parquet = V5 + 15 mpnet doc-PCA cols.

Inputs
  data/df_ml_dataset_v5.parquet                  (4010 x 69)
  data/step4j/df_caption_mpnet_pca.parquet       (4127 x 16: post_id + 15 PCs)

Output
  data/df_ml_dataset_v5c.parquet                 (~4010 x 84)

Strategy: inner join on post_id (filter, don't fill — same convention as V4).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

V5_PATH      = DATA / "df_ml_dataset_v5.parquet"
PCA_PATH     = DATA / "step4j" / "df_caption_mpnet_pca.parquet"
OUT_PATH     = DATA / "df_ml_dataset_v5c.parquet"


def main() -> int:
    print("=" * 78)
    print("Step 4j -- Build V5c dataset (V5 + 15 mpnet doc-PCA)")
    print("=" * 78)
    v5 = pd.read_parquet(V5_PATH)
    pca = pd.read_parquet(PCA_PATH)
    print(f"  V5            : {v5.shape}")
    print(f"  mpnet-PCA     : {pca.shape}")

    pc_cols = [c for c in pca.columns if c.startswith("doc_pc")]
    assert len(pc_cols) == 15, f"expected 15 doc_pc cols, got {len(pc_cols)}"

    v5c = v5.merge(pca[["post_id", *pc_cols]], on="post_id", how="inner")
    print(f"  V5c (inner join): {v5c.shape}")
    print(f"  rows lost vs V5 : {len(v5) - len(v5c)}  "
          "(posts with no mpnet embedding)")
    assert v5c.shape == (len(v5c), v5.shape[1] + 15), \
        f"unexpected V5c shape {v5c.shape}"
    print(f"  new features    : {pc_cols[:3]} ... {pc_cols[-2:]}  "
          f"(15 doc-PCs)")
    print(f"  total V5c features: {v5c.shape[1]}")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    v5c.to_parquet(OUT_PATH, index=False)
    print(f"\n  wrote {OUT_PATH}  ({OUT_PATH.stat().st_size/1024:.1f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
