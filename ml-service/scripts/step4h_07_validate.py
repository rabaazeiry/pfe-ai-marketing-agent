"""Step 4h.7 — Statistical validation of CLIP embedding structure.

Following Zhao et al. (2025): test that the geometry of CLIP embeddings
encodes meaningful structure rather than noise.

Tests run:
  1. Norm sanity      — all embeddings ~unit (already L2-normalized)
  2. Anisotropy       — mean cosine similarity between random pairs
                        (a perfectly isotropic Gaussian on the sphere has
                         E[cos] ~ 0; CLIP is known to be anisotropic, so
                         we *expect* a positive bias)
  3. Industry separability (hypothesis test):
       H0: post embeddings are exchangeable across industries
       Compare mean cosine similarity within-industry vs across-industry
       using a permutation test (5 industries × 4127 posts).
  4. Concept decomposition: per-PC mean by industry (ANOVA F-test on
     each of the first 15 principal components).

Output: data/step4h/validation_report.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
STEP4H = DATA / "step4h"

DF_MASTER = DATA / "df_master_masked_with_topics.parquet"
DF_POST = STEP4H / "df_post_clip.parquet"
DF_PCA = STEP4H / "df_post_clip_pca.parquet"
OUT = STEP4H / "validation_report.json"

RNG = np.random.default_rng(42)
N_PERM = 1000  # permutations for industry separability test


def cos_pairs(X: np.ndarray, idx_a: np.ndarray, idx_b: np.ndarray) -> np.ndarray:
    """Cosine similarity for paired rows (X is L2-normalized -> dot product)."""
    a = X[idx_a]
    b = X[idx_b]
    return (a * b).sum(axis=1)


def main() -> int:
    print("=" * 70)
    print("STEP 4h.7 — statistical validation")
    print("=" * 70)

    posts = pd.read_parquet(DF_POST)
    master = pd.read_parquet(DF_MASTER)[["post_id", "industry", "content_type"]]
    df = posts.merge(master, on="post_id", how="left",
                     suffixes=("_post", "_master"))
    X = np.stack(df["clip_embedding"].apply(np.asarray).values).astype(np.float32)
    industries = df["industry"].astype(str).values
    n = len(df)

    report: dict = {"n_posts": int(n)}

    # 1. norm sanity
    norms = np.linalg.norm(X, axis=1)
    report["norm_check"] = {
        "mean": float(norms.mean()),
        "std": float(norms.std()),
        "min": float(norms.min()),
        "max": float(norms.max()),
    }
    print(f"\n[1] Norm: mean={norms.mean():.4f}  std={norms.std():.6f}")

    # 2. anisotropy via random pairs
    n_pairs = 5000
    a = RNG.integers(0, n, size=n_pairs)
    b = RNG.integers(0, n, size=n_pairs)
    keep = a != b
    cos_random = cos_pairs(X, a[keep], b[keep])
    report["anisotropy"] = {
        "n_pairs": int(keep.sum()),
        "mean_cosine_random_pairs": float(cos_random.mean()),
        "std": float(cos_random.std()),
    }
    print(f"[2] Anisotropy: E[cos(random pair)] = {cos_random.mean():.4f}")

    # 3. industry separability (permutation test)
    # within-industry mean cosine vs across-industry mean cosine
    inds = np.unique(industries)
    print(f"[3] Industry separability ({len(inds)} industries, "
          f"{N_PERM} permutations)...")

    def split_means(labels: np.ndarray) -> tuple[float, float]:
        # sample n_pairs random index pairs; classify by same/diff label
        a_ = RNG.integers(0, n, size=n_pairs)
        b_ = RNG.integers(0, n, size=n_pairs)
        keep_ = a_ != b_
        a_ = a_[keep_]; b_ = b_[keep_]
        same = labels[a_] == labels[b_]
        cos = cos_pairs(X, a_, b_)
        within = cos[same].mean() if same.any() else float("nan")
        across = cos[~same].mean() if (~same).any() else float("nan")
        return float(within), float(across)

    obs_within, obs_across = split_means(industries)
    obs_diff = obs_within - obs_across
    print(f"    observed within={obs_within:.4f}  across={obs_across:.4f}  "
          f"diff={obs_diff:.4f}")

    # permutation null: shuffle industry labels, recompute diff
    null_diffs = np.empty(N_PERM, dtype=np.float32)
    for k in range(N_PERM):
        perm_labels = RNG.permutation(industries)
        w, a_ = split_means(perm_labels)
        null_diffs[k] = w - a_
    p_perm = float((null_diffs >= obs_diff).mean())
    report["industry_separability"] = {
        "mean_cosine_within_industry": obs_within,
        "mean_cosine_across_industry": obs_across,
        "diff": obs_diff,
        "perm_p_value_one_sided": p_perm,
        "n_permutations": N_PERM,
    }
    print(f"    permutation p-value (1-sided) = {p_perm:.4f}")

    # 4. ANOVA per PC
    if DF_PCA.exists():
        pca_df = pd.read_parquet(DF_PCA).merge(master, on="post_id", how="left")
        pc_cols = [c for c in pca_df.columns if c.startswith("clip_pc")]
        pc_results = []
        for c in pc_cols:
            groups = [pca_df.loc[pca_df["industry"] == ind, c].values
                      for ind in inds if (pca_df["industry"] == ind).any()]
            f, p = stats.f_oneway(*groups)
            pc_results.append({"component": c, "F": float(f), "p_value": float(p)})
        report["anova_industry_per_pc"] = pc_results
        print(f"[4] ANOVA per PC: top 5 by F-stat:")
        for r in sorted(pc_results, key=lambda r: -r["F"])[:5]:
            print(f"    {r['component']}: F={r['F']:8.2f}  p={r['p_value']:.2e}")

    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nWrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
