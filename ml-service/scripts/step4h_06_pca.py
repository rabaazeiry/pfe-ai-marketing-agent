"""Step 4h.6 — PCA reduction of CLIP embeddings 512 -> 15.

Train PCA on the per-post embeddings, save the model, write a parquet
with 15-dim features per post.

Outputs:
  models/clip_pca_15.joblib
  data/step4h/df_post_clip_pca.parquet
  data/step4h/pca_explained_variance.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.decomposition import PCA

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
STEP4H = DATA / "step4h"
MODELS_DIR = ROOT / "models"
MODELS_DIR.mkdir(exist_ok=True)

DF_POST = STEP4H / "df_post_clip.parquet"
OUT_PARQUET = STEP4H / "df_post_clip_pca.parquet"
OUT_MODEL = MODELS_DIR / "clip_pca_15.joblib"
OUT_JSON = STEP4H / "pca_explained_variance.json"

N_COMPONENTS = 15


def main() -> int:
    print("=" * 70)
    print("STEP 4h.6 — PCA 512 -> 15")
    print("=" * 70)

    df = pd.read_parquet(DF_POST)
    X = np.stack(df["clip_embedding"].apply(np.asarray).values).astype(np.float32)
    print(f"X: {X.shape}")

    pca = PCA(n_components=N_COMPONENTS, random_state=42)
    Z = pca.fit_transform(X).astype(np.float32)

    evr = pca.explained_variance_ratio_
    print(f"\nExplained variance ratio per component:")
    for i, v in enumerate(evr):
        print(f"  PC{i+1:2d}: {v*100:5.2f}%   (cum={evr[:i+1].sum()*100:5.2f}%)")
    print(f"Total ({N_COMPONENTS} comps): {evr.sum()*100:.2f}%")

    joblib.dump(pca, OUT_MODEL)
    print(f"\nSaved PCA model: {OUT_MODEL}")

    out = pd.DataFrame(
        {
            "post_id": df["post_id"].values,
            "content_type": df["content_type"].values,
            "n_assets": df["n_assets"].values,
        }
    )
    for i in range(N_COMPONENTS):
        out[f"clip_pc{i+1:02d}"] = Z[:, i]
    out.to_parquet(OUT_PARQUET, index=False)
    print(f"Wrote {OUT_PARQUET} ({len(out)} rows, {N_COMPONENTS} PC cols)")

    OUT_JSON.write_text(
        json.dumps(
            {
                "n_components": N_COMPONENTS,
                "explained_variance_ratio": evr.tolist(),
                "cumulative_explained_variance": float(evr.sum()),
                "n_samples": int(len(df)),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Saved metrics: {OUT_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
