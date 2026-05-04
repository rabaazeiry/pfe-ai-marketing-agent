"""One-shot rebuild: apply past-only + cold-start fix to existing parquet.

Reads ``data/df_master_masked_with_topics.parquet`` (the post-BERTopic
parquet), recomputes brand_avg_likes / brand_engagement_rate using the
two helpers from ``src.corpus.loader``, and writes back in place.

This avoids re-running BERTopic since brand columns are NOT inputs to
the topic model — they only flow into Phase 3 features.

After this rebuild, run scripts/phase3_features.py to regenerate
``data/df_ml_dataset.parquet`` from the corrected upstream parquet.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from corpus.loader import (  # noqa: E402
    _compute_brand_features_pastonly,
    _impute_first_post_with_industry_median,
)

IN_PATH = ROOT / "data" / "df_master_masked_with_topics.parquet"
OUT_PATH = IN_PATH  # in-place

sys.stdout.reconfigure(encoding="utf-8")


def main() -> None:
    print(f"Loading {IN_PATH} ...")
    df = pd.read_parquet(IN_PATH)
    print(f"  shape: {df.shape}")
    print(f"  brands: {df['username'].nunique()}")
    print(f"  industries: {sorted(df['industry_simple'].dropna().unique())}")

    n_first_post_per_brand = df.groupby("username").size().pipe(lambda s: (s > 0).sum())
    n_brands = df["username"].nunique()
    print(f"  brands with >=1 post: {n_brands}  "
          f"(→ {n_brands} first-posts will receive industry-median imputation)")

    # --- Step A: past-only expanding means -----------------------------------
    print()
    print("Computing past-only expanding means (per username, sorted by published_at) ...")
    df_fixed = _compute_brand_features_pastonly(df)
    nan_er = int(df_fixed["brand_engagement_rate"].isna().sum())
    nan_lk = int(df_fixed["brand_avg_likes"].isna().sum())
    print(f"  NaN after past-only step: brand_engagement_rate={nan_er}  "
          f"brand_avg_likes={nan_lk}")
    print(f"  (expected: NaN == n_brands == {n_brands} for both columns)")
    assert nan_er == n_brands, f"expected {n_brands} NaNs, got {nan_er}"
    assert nan_lk == n_brands, f"expected {n_brands} NaNs, got {nan_lk}"

    # --- Step B: cold-start imputation with industry medians -----------------
    print()
    print("Imputing first-post-per-brand with industry medians "
          "(Trivedi 2019, Chen 2022) ...")
    df_fixed, medians = _impute_first_post_with_industry_median(df_fixed)
    nan_er = int(df_fixed["brand_engagement_rate"].isna().sum())
    nan_lk = int(df_fixed["brand_avg_likes"].isna().sum())
    print(f"  NaN after imputation: brand_engagement_rate={nan_er}  "
          f"brand_avg_likes={nan_lk}  (expected: 0 / 0)")
    assert nan_er == 0 and nan_lk == 0, "imputation left NaNs"

    print()
    print("Industry medians (cold-start prior, applied to first post per brand):")
    print(f"  {'industry':<14} {'engagement_rate':>16} {'likes':>10}")
    for ind, m in medians.items():
        print(f"  {ind:<14} {m['engagement_rate']:>16.4f} {m['likes']:>10.1f}")

    # Persist medians for the audit report.
    medians_path = ROOT / "data" / "_industry_medians.json"
    medians_path.write_text(json.dumps(medians, indent=2), encoding="utf-8")
    print(f"  saved → {medians_path}")

    # --- Step C: write back --------------------------------------------------
    print()
    print(f"Writing fixed parquet → {OUT_PATH}")
    df_fixed.to_parquet(OUT_PATH, index=False)
    sz = OUT_PATH.stat().st_size / 1024
    print(f"  wrote {OUT_PATH.name} ({sz:.1f} KB)")
    print(f"  shape: {df_fixed.shape}")


if __name__ == "__main__":
    main()
