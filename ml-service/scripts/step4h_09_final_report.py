"""Step 4h.9 — Final validation report for the CLIP pipeline.

Aggregates all step4h artefacts and prints a consolidated summary
(files processed, embeddings count, t-SNE silhouette, PCA variance,
example nearest-neighbour visual matches per post).

Outputs: data/step4h/final_report.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
STEP4H = DATA / "step4h"

DF_IMG = STEP4H / "df_clip_embeddings.parquet"
DF_REEL = STEP4H / "df_reel_frames_embeddings.parquet"
DF_POST = STEP4H / "df_post_clip.parquet"
DF_PCA = STEP4H / "df_post_clip_pca.parquet"
DF_MASTER_CLIP = DATA / "df_master_with_clip.parquet"
TSNE_JSON = STEP4H / "tsne_silhouette.json"
PCA_JSON = STEP4H / "pca_explained_variance.json"
VAL_JSON = STEP4H / "validation_report.json"
OUT = STEP4H / "final_report.json"


def load_json(p: Path):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def main() -> int:
    print("=" * 70)
    print("STEP 4h.9 — FINAL CLIP PIPELINE REPORT")
    print("=" * 70)

    img = pd.read_parquet(DF_IMG)
    reel = pd.read_parquet(DF_REEL) if DF_REEL.exists() else pd.DataFrame()
    post = pd.read_parquet(DF_POST)
    pca = pd.read_parquet(DF_PCA)
    master_clip = pd.read_parquet(DF_MASTER_CLIP)

    n_files = len(img)
    n_frames = int(reel["n_frames"].sum()) if not reel.empty else 0
    n_posts = len(post)

    file_breakdown = img.groupby(["industry", "file_type"]).size().unstack(fill_value=0)

    tsne = load_json(TSNE_JSON) or {}
    pca_meta = load_json(PCA_JSON) or {}
    val = load_json(VAL_JSON) or {}

    # 5 nearest-neighbour examples
    X = np.stack(post["clip_embedding"].apply(np.asarray).values)
    pids = post["post_id"].values
    rng = np.random.default_rng(42)
    samples = rng.choice(len(post), size=5, replace=False)

    nn_examples = []
    for i in samples:
        sims = X @ X[i]
        sims[i] = -np.inf
        top5 = np.argsort(-sims)[:5]
        nn_examples.append(
            {
                "query_post_id": str(pids[i]),
                "neighbours": [
                    {"post_id": str(pids[j]), "cosine_sim": float(sims[j])}
                    for j in top5
                ],
            }
        )

    print()
    print(f"Files processed (images)       : {n_files}")
    print(f"Embeddings generated (images)  : {n_files}")
    if not reel.empty:
        print(f"Reel videos processed          : {len(reel)}")
        print(f"Frames extracted               : {n_frames}")
    else:
        print(f"Reel videos processed          : 0  (df_reel_frames not found)")
    print(f"Posts with CLIP embedding      : {n_posts}")
    print(f"Posts in df_master_with_clip   : {len(master_clip)}  "
          f"(has_clip={int(master_clip['has_clip'].sum())})")

    print(f"\nFile breakdown by industry / file_type:")
    print(file_breakdown.to_string())

    if tsne:
        print(f"\nt-SNE silhouette (2D, industry)        : "
              f"{tsne.get('silhouette_tsne_2d_industry'):.4f}")
        print(f"CLIP 512D cosine silhouette (industry) : "
              f"{tsne.get('silhouette_clip_512d_cosine_industry'):.4f}")

    if pca_meta:
        cum = pca_meta.get("cumulative_explained_variance", 0)
        print(f"\nPCA 512->15 cumulative variance       : {cum*100:.2f}%")

    if val:
        sep = val.get("industry_separability", {})
        print(f"\nIndustry separability (cosine):")
        print(f"  within  = {sep.get('mean_cosine_within_industry'):.4f}")
        print(f"  across  = {sep.get('mean_cosine_across_industry'):.4f}")
        print(f"  diff    = {sep.get('diff'):.4f}")
        print(f"  perm-p  = {sep.get('perm_p_value_one_sided'):.4f}")

    print(f"\n5 nearest-neighbour examples (cosine):")
    for ex in nn_examples:
        print(f"  query {ex['query_post_id']}:")
        for nb in ex["neighbours"]:
            print(f"    {nb['post_id']}  sim={nb['cosine_sim']:.4f}")

    report = {
        "files_processed": int(n_files),
        "embeddings_generated": int(n_files),
        "reel_videos_processed": int(len(reel)) if not reel.empty else 0,
        "frames_extracted": int(n_frames),
        "posts_with_embedding": int(n_posts),
        "posts_in_master_with_clip": int(len(master_clip)),
        "has_clip_count": int(master_clip["has_clip"].sum()),
        "file_breakdown": {
            ind: {ft: int(file_breakdown.loc[ind, ft])
                  for ft in file_breakdown.columns
                  if ind in file_breakdown.index}
            for ind in file_breakdown.index
        },
        "tsne_silhouette": tsne,
        "pca": pca_meta,
        "validation": val,
        "nearest_neighbour_examples": nn_examples,
    }
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nWrote {OUT}")
    print("\nSTEP 4h COMPLETE.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
