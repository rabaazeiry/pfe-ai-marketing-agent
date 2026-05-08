"""Step 4j (V5c) — mpnet caption embeddings: encode + PCA + validation + t-SNE.

Loads paraphrase-multilingual-mpnet-base-v2 (Reimers 2020), encodes the
4127 cleaned captions of the master corpus to 768-dim embeddings,
L2-normalizes them, runs PCA to 15 dims, and writes:

  data/step4j/df_caption_mpnet_embeddings.parquet
       post_id (str) + caption_embedding (list[float32], len=768)
  data/step4j/df_caption_mpnet_pca.parquet
       post_id (str) + doc_pc01..doc_pc15 (float32)
  models/mpnet_pca_15.joblib                    -- the fitted PCA
  data/step4j/mpnet_validation_report.json      -- cohesion/separation
  figures/mpnet_tsne_industries.png             -- t-SNE coloured by industry

Why mpnet over MiniLM
  - 110M params vs 22M, 768-dim vs 384-dim.
  - Permuted Language Modelling pretraining (Song 2020) outperforms MLM
    on STS / paraphrase benchmarks (Reimers & Gurevych, 2020).
  - Multilingual coverage matches our FR/EN/AR mix.
  - Independent backbone from the BERTopic MiniLM, so V5c topic features
    and doc-PCA features measure different aspects of the caption.
"""
from __future__ import annotations

# Windows DLL workaround (consistent with other ml-service scripts).
import torch  # noqa: F401

import json
import sys
import time
import warnings
from pathlib import Path
from typing import List

import joblib
import numpy as np
import pandas as pd
from scipy.stats import f_oneway, spearmanr  # noqa: F401
from sentence_transformers import SentenceTransformer
from sklearn.decomposition import PCA
from sklearn.manifold import TSNE
from sklearn.metrics import silhouette_score

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
STEP4J = DATA / "step4j"
STEP4J.mkdir(parents=True, exist_ok=True)
FIG = ROOT / "figures"
FIG.mkdir(parents=True, exist_ok=True)
MODELS = ROOT / "models"
MODELS.mkdir(parents=True, exist_ok=True)

MASTER_PATH       = DATA / "df_master_masked_with_topics.parquet"
EMB_PATH          = STEP4J / "df_caption_mpnet_embeddings.parquet"
PCA_PARQUET_PATH  = STEP4J / "df_caption_mpnet_pca.parquet"
PCA_MODEL_PATH    = MODELS / "mpnet_pca_15.joblib"
VALID_JSON_PATH   = STEP4J / "mpnet_validation_report.json"
TSNE_PNG          = FIG / "mpnet_tsne_industries.png"

MPNET_NAME = "paraphrase-multilingual-mpnet-base-v2"
TEXT_COL = "caption_clean"  # same source as BERTopic v1 (clean text)
EMPTY_SENTINEL = "[empty]"
PCA_COMPONENTS = 15
SEED = 42


def step1_setup() -> SentenceTransformer:
    print("=" * 78)
    print("STEP 1 -- Setup mpnet")
    print("=" * 78)
    t0 = time.perf_counter()
    print(f"  Loading {MPNET_NAME} ...")
    model = SentenceTransformer(MPNET_NAME)
    elapsed = time.perf_counter() - t0
    n_params = sum(p.numel() for p in model.parameters())
    dim = model.get_sentence_embedding_dimension()
    device = next(model.parameters()).device
    print(f"  loaded in {elapsed:.1f} s")
    print(f"  dim={dim}  params={n_params/1e6:.1f}M  device={device}")
    smoke = model.encode(
        ["pasta carbonara recipe", "promotion - 20% off all bags"],
        normalize_embeddings=True,
    )
    print(f"  smoke-encode shape: {smoke.shape}  "
          f"L2 norms: {np.linalg.norm(smoke, axis=1).round(4).tolist()}")
    return model


def step2_extract_captions() -> pd.DataFrame:
    print("\n" + "=" * 78)
    print("STEP 2 -- Extract captions from master corpus")
    print("=" * 78)
    df = pd.read_parquet(MASTER_PATH)
    print(f"  master_masked shape: {df.shape}")

    out = df[["post_id", "industry_simple", TEXT_COL]].copy()
    n_total = len(out)
    n_nan = int(out[TEXT_COL].isna().sum())
    out[TEXT_COL] = out[TEXT_COL].fillna(EMPTY_SENTINEL)
    n_blank_after_fillna = int((out[TEXT_COL].astype(str).str.strip() == "").sum())
    out.loc[out[TEXT_COL].astype(str).str.strip() == "", TEXT_COL] = EMPTY_SENTINEL
    n_empty_total = n_nan + n_blank_after_fillna
    n_nonempty = n_total - n_empty_total
    avg_len = float(out[TEXT_COL].astype(str).str.len().mean())

    print(f"  total captions:    {n_total}")
    print(f"  non-empty:         {n_nonempty}")
    print(f"  empty (sentinel):  {n_empty_total}  "
          f"(NaN={n_nan}, blank={n_blank_after_fillna})")
    print(f"  avg length:        {avg_len:.1f} chars")
    return out


def step3_encode(model: SentenceTransformer, captions_df: pd.DataFrame) -> np.ndarray:
    print("\n" + "=" * 78)
    print("STEP 3 -- Encode with mpnet (batched, L2-normalized)")
    print("=" * 78)
    docs: List[str] = captions_df[TEXT_COL].astype(str).tolist()
    n = len(docs)
    print(f"  encoding {n} captions, batch_size=32 ...")
    t0 = time.perf_counter()
    emb = model.encode(
        docs,
        batch_size=32,
        show_progress_bar=True,
        normalize_embeddings=True,
        convert_to_numpy=True,
    ).astype("float32")
    elapsed = time.perf_counter() - t0

    norms = np.linalg.norm(emb, axis=1)
    print(f"\n  encode elapsed: {elapsed:.1f} s ({elapsed/60:.1f} min)")
    print(f"  embedding shape: {emb.shape}  dtype: {emb.dtype}")
    print(f"  mean L2 norm: {norms.mean():.6f}  "
          f"min: {norms.min():.6f}  max: {norms.max():.6f}")

    # Persist as one row per post with a list[float32] column.
    print(f"  writing {EMB_PATH.name} ...")
    df_out = pd.DataFrame({
        "post_id": captions_df["post_id"].values,
        "caption_embedding": list(emb),  # list of 768-d float32 arrays
    })
    df_out.to_parquet(EMB_PATH, index=False)
    print(f"  wrote {EMB_PATH}  ({EMB_PATH.stat().st_size/1024**2:.1f} MB)")
    return emb


def step4_pca(emb: np.ndarray, captions_df: pd.DataFrame) -> pd.DataFrame:
    print("\n" + "=" * 78)
    print("STEP 4 -- PCA 768 -> 15")
    print("=" * 78)
    pca = PCA(n_components=PCA_COMPONENTS, random_state=SEED)
    pcs = pca.fit_transform(emb).astype("float32")
    explained = pca.explained_variance_ratio_
    cum = np.cumsum(explained)
    print(f"  PCA fit: {emb.shape} -> {pcs.shape}")
    print(f"  per-PC explained variance ratio:")
    for i, (e, c) in enumerate(zip(explained, cum), 1):
        print(f"    PC{i:02d}: {e*100:6.2f}%   cum: {c*100:6.2f}%")
    print(f"  total variance retained: {cum[-1]*100:.2f}%")

    cols = [f"doc_pc{i:02d}" for i in range(1, PCA_COMPONENTS + 1)]
    df_pcs = pd.DataFrame(pcs, columns=cols)
    df_pcs.insert(0, "post_id", captions_df["post_id"].values)

    df_pcs.to_parquet(PCA_PARQUET_PATH, index=False)
    joblib.dump(pca, PCA_MODEL_PATH)
    print(f"  wrote {PCA_PARQUET_PATH.name}  "
          f"({PCA_PARQUET_PATH.stat().st_size/1024:.1f} KB)")
    print(f"  wrote {PCA_MODEL_PATH.name}  "
          f"({PCA_MODEL_PATH.stat().st_size/1024:.1f} KB)")
    return df_pcs


def step5_validation(emb: np.ndarray, industry: pd.Series, df_pcs: pd.DataFrame) -> dict:
    print("\n" + "=" * 78)
    print("STEP 5 -- Statistical validation")
    print("=" * 78)
    rng = np.random.default_rng(SEED)

    # Within-vs-across industry cosine similarity (sampled pairs)
    industry = industry.reset_index(drop=True)
    n = len(emb)
    n_pairs = 5000
    print(f"  Cosine: sampling {n_pairs} within + {n_pairs} cross pairs ...")
    by_ind: dict = {}
    for ind, idx in industry.groupby(industry).groups.items():
        by_ind[ind] = np.array(idx, dtype=np.int64)

    def sample_within() -> np.ndarray:
        out = []
        choices = list(by_ind.keys())
        sizes = np.array([len(by_ind[c]) for c in choices], dtype=float)
        probs = sizes / sizes.sum()
        for _ in range(n_pairs):
            ind = rng.choice(choices, p=probs)
            i, j = rng.choice(by_ind[ind], 2, replace=False)
            out.append(float(np.dot(emb[i], emb[j])))
        return np.array(out)

    def sample_cross() -> np.ndarray:
        out = []
        for _ in range(n_pairs):
            i, j = rng.choice(n, 2, replace=False)
            while industry.iloc[i] == industry.iloc[j]:
                i, j = rng.choice(n, 2, replace=False)
            out.append(float(np.dot(emb[i], emb[j])))
        return np.array(out)

    within = sample_within()
    across = sample_cross()
    delta_obs = float(within.mean() - across.mean())
    print(f"  within-industry mean cosine:  {within.mean():.4f}  std={within.std():.4f}")
    print(f"  across-industry mean cosine:  {across.mean():.4f}  std={across.std():.4f}")
    print(f"  delta = within - across:      {delta_obs:+.4f}")

    # Permutation test on the delta (1000 perms shuffling industry labels).
    print(f"  Permutation test (1000 perms) ...")
    n_perm = 1000
    bigger = 0
    for _ in range(n_perm):
        shuffled = industry.sample(frac=1.0, random_state=int(rng.integers(2**31))).reset_index(drop=True)
        # rebuild groups
        by_perm: dict = {}
        for ind, idx in shuffled.groupby(shuffled).groups.items():
            by_perm[ind] = np.array(idx, dtype=np.int64)
        choices = list(by_perm.keys())
        sizes = np.array([len(by_perm[c]) for c in choices], dtype=float)
        probs = sizes / sizes.sum()
        # smaller sample (1000) to keep permutation tractable
        within_p = []
        for _ in range(1000):
            ind = rng.choice(choices, p=probs)
            i, j = rng.choice(by_perm[ind], 2, replace=False)
            within_p.append(float(np.dot(emb[i], emb[j])))
        across_p = []
        for _ in range(1000):
            i, j = rng.choice(n, 2, replace=False)
            while shuffled.iloc[i] == shuffled.iloc[j]:
                i, j = rng.choice(n, 2, replace=False)
            across_p.append(float(np.dot(emb[i], emb[j])))
        delta_p = float(np.mean(within_p) - np.mean(across_p))
        if delta_p >= delta_obs:
            bigger += 1
    p_value = (bigger + 1) / (n_perm + 1)
    print(f"  permutation p-value (one-sided, H1: within > across): {p_value:.4f}")

    # Per-PC ANOVA (PC1, PC3, PC5)
    print(f"  Per-PC ANOVA on PC1, PC3, PC5 across industries ...")
    anova_out = {}
    df_pcs_with_ind = df_pcs.copy()
    df_pcs_with_ind["industry_simple"] = industry.values
    for pc in ["doc_pc01", "doc_pc03", "doc_pc05"]:
        groups = [g[pc].values for _, g in df_pcs_with_ind.groupby("industry_simple")]
        F, p = f_oneway(*groups)
        anova_out[pc] = {"F": float(F), "p": float(p)}
        print(f"    {pc}: F={F:8.3f}  p={p:.6e}")

    report = {
        "n_samples": int(n),
        "n_pairs_sampled": n_pairs,
        "cosine_within_mean": float(within.mean()),
        "cosine_within_std":  float(within.std()),
        "cosine_across_mean": float(across.mean()),
        "cosine_across_std":  float(across.std()),
        "delta_within_minus_across": float(delta_obs),
        "permutation_n": n_perm,
        "permutation_p_value": float(p_value),
        "anova": anova_out,
        "comparison_notes": {
            "clip_silhouette_2d_known": 0.225,
            "see_data_step4j": "mpnet_validation_report.json"
        },
    }
    VALID_JSON_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"  wrote {VALID_JSON_PATH.name}")
    return report


def step6_tsne(emb: np.ndarray, industry: pd.Series) -> float:
    print("\n" + "=" * 78)
    print("STEP 6 -- t-SNE 2-D projection + silhouette")
    print("=" * 78)
    import matplotlib.pyplot as plt
    import seaborn as sns

    print(f"  fitting t-SNE (perplexity=30, max_iter=1000, seed={SEED}) ...")
    t0 = time.perf_counter()
    # sklearn >=1.5 renamed n_iter -> max_iter; try new first, fall back if needed.
    try:
        tsne = TSNE(
            n_components=2, perplexity=30, learning_rate="auto",
            init="pca", random_state=SEED, max_iter=1000,
        )
    except TypeError:
        tsne = TSNE(
            n_components=2, perplexity=30, learning_rate="auto",
            init="pca", random_state=SEED, n_iter=1000,
        )
    coords = tsne.fit_transform(emb)
    print(f"  t-SNE elapsed: {time.perf_counter() - t0:.1f} s")

    industry = industry.reset_index(drop=True)
    sil_emb = float(silhouette_score(emb, industry, metric="cosine"))
    sil_2d  = float(silhouette_score(coords, industry, metric="euclidean"))
    print(f"  silhouette (full 768-d, cosine): {sil_emb:.4f}")
    print(f"  silhouette (2-D t-SNE, euclid):  {sil_2d:.4f}")
    print(f"  reference: CLIP 2-D silhouette = 0.225 (known)")

    sns.set_theme(context="paper", style="whitegrid", palette="deep")
    INDUSTRY_ORDER = ["beauty", "fashion", "hotels", "patisserie", "restaurants"]
    palette = dict(zip(INDUSTRY_ORDER, sns.color_palette("deep", 5)))
    fig, ax = plt.subplots(figsize=(8.5, 7))
    df_plot = pd.DataFrame({"x": coords[:, 0], "y": coords[:, 1],
                            "industry_simple": industry.values})
    sns.scatterplot(
        data=df_plot, x="x", y="y", hue="industry_simple",
        hue_order=INDUSTRY_ORDER, palette=palette,
        s=18, alpha=0.7, edgecolor="white", linewidth=0.2, ax=ax,
    )
    ax.set_title(
        "mpnet caption embeddings -- t-SNE projection, coloured by industry\n"
        f"silhouette(2-D, euclid) = {sil_2d:.4f}    "
        f"silhouette(768-d, cosine) = {sil_emb:.4f}    "
        f"n = {len(coords):,}"
    )
    ax.set_xlabel("t-SNE-1"); ax.set_ylabel("t-SNE-2")
    ax.legend(title="Industry", loc="best", frameon=True)
    plt.tight_layout()
    fig.savefig(TSNE_PNG, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote {TSNE_PNG.name}")

    # Append silhouette to validation report so downstream report has it.
    report = json.loads(VALID_JSON_PATH.read_text(encoding="utf-8"))
    report["silhouette_full_768d_cosine"] = sil_emb
    report["silhouette_tsne_2d_euclid"]   = sil_2d
    VALID_JSON_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return sil_2d


def main() -> int:
    warnings.filterwarnings("ignore", category=UserWarning)
    t_total = time.perf_counter()
    model = step1_setup()
    captions_df = step2_extract_captions()
    emb = step3_encode(model, captions_df)
    df_pcs = step4_pca(emb, captions_df)
    step5_validation(emb, captions_df["industry_simple"], df_pcs)
    step6_tsne(emb, captions_df["industry_simple"])
    print("\n" + "=" * 78)
    print(f"Step 4j mpnet pipeline complete in "
          f"{(time.perf_counter() - t_total)/60:.1f} min")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
