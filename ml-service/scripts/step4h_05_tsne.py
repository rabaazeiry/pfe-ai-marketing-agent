"""Step 4h.5 — t-SNE visualization of post embeddings.

Following Zhao et al. (2025): project the per-post 512-dim CLIP embeddings to
2D via t-SNE and color points by industry. Compute a silhouette score in the
2D space (cluster validation against industry labels).

Output:
  figures/clip_tsne_industries.png
  data/step4h/tsne_silhouette.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.manifold import TSNE
from sklearn.metrics import silhouette_score

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
STEP4H = DATA / "step4h"
FIG_DIR = ROOT / "figures"
FIG_DIR.mkdir(exist_ok=True)

DF_MASTER = DATA / "df_master_masked_with_topics.parquet"
DF_POST = STEP4H / "df_post_clip.parquet"
OUT_PNG = FIG_DIR / "clip_tsne_industries.png"
OUT_JSON = STEP4H / "tsne_silhouette.json"


def main() -> int:
    print("=" * 70)
    print("STEP 4h.5 — t-SNE + silhouette")
    print("=" * 70)

    posts = pd.read_parquet(DF_POST)
    master = pd.read_parquet(DF_MASTER)[["post_id", "industry"]]
    df = posts.merge(master, on="post_id", how="left")
    print(f"posts: {len(df)}  industries: {sorted(df['industry'].unique())}")

    X = np.stack(df["clip_embedding"].apply(np.asarray).values)
    y = df["industry"].astype(str).values
    print(f"X shape: {X.shape}")

    print("\nFitting t-SNE (perplexity=30, max_iter=1000)...")
    Z = TSNE(
        n_components=2,
        perplexity=30,
        learning_rate="auto",
        init="pca",
        max_iter=1000,
        random_state=42,
        verbose=1,
    ).fit_transform(X)

    print("\nSilhouette in 2D...")
    sil_2d = float(silhouette_score(Z, y, sample_size=min(2000, len(y)), random_state=42))
    print(f"  silhouette (t-SNE 2D, by industry) = {sil_2d:.4f}")

    print("Silhouette in 512D (cosine)...")
    sil_full = float(
        silhouette_score(X, y, metric="cosine",
                         sample_size=min(2000, len(y)), random_state=42)
    )
    print(f"  silhouette (CLIP 512D cosine, by industry) = {sil_full:.4f}")

    # plot
    fig, ax = plt.subplots(figsize=(9, 7), dpi=130)
    palette = {
        "beauty": "#e6194B",
        "fashion": "#3cb44b",
        "hotels": "#4363d8",
        "patisserie": "#f58231",
        "restaurants": "#911eb4",
    }
    for ind, color in palette.items():
        mask = y == ind
        if mask.sum() == 0:
            continue
        ax.scatter(Z[mask, 0], Z[mask, 1], s=8, alpha=0.55, c=color, label=ind,
                   edgecolors="none")
    ax.set_title(f"CLIP t-SNE — posts by industry  (sil. 2D={sil_2d:.3f}, "
                 f"512D cos={sil_full:.3f})")
    ax.set_xlabel("t-SNE-1")
    ax.set_ylabel("t-SNE-2")
    ax.legend(loc="best", fontsize=9, frameon=True)
    ax.set_xticks([])
    ax.set_yticks([])
    fig.tight_layout()
    fig.savefig(OUT_PNG)
    plt.close(fig)
    print(f"\nSaved figure: {OUT_PNG}")

    OUT_JSON.write_text(
        json.dumps(
            {
                "n_posts": int(len(df)),
                "silhouette_tsne_2d_industry": sil_2d,
                "silhouette_clip_512d_cosine_industry": sil_full,
                "industries_present": sorted(set(y)),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Saved metrics: {OUT_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
