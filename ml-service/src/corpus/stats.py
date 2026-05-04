"""Corpus stats summary printer."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd


def _section(title: str) -> None:
    print()
    print(title)
    print("-" * len(title))


def print_stats(
    df: pd.DataFrame,
    csv_path: Optional[Path] = None,
    parquet_path: Optional[Path] = None,
) -> None:
    print("=" * 72)
    print("MASTER CORPUS — STATS SUMMARY")
    print("=" * 72)
    print(f"Total posts loaded: {len(df):,}")

    if len(df) == 0:
        print("(empty DataFrame — nothing to summarize)")
        return

    _section("Posts per industry")
    grp = (
        df.groupby("industry_simple", as_index=False)
        .agg(posts=("post_id", "count"), brands=("username", "nunique"))
        .sort_values("posts", ascending=False)
    )
    for _, row in grp.iterrows():
        print(f"  {row['industry_simple']:<14} posts={row['posts']:>6,}  brands={row['brands']:>3}")

    _section("Date range")
    print(f"  oldest:  {df['published_at'].min()}")
    print(f"  newest:  {df['published_at'].max()}")

    _section("Brand stats")
    posts_per_brand = df.groupby("username")["post_id"].count()
    print(f"  total brands:     {df['username'].nunique()}")
    print(f"  avg posts/brand:  {posts_per_brand.mean():.1f}")
    print(f"  min posts/brand:  {posts_per_brand.min()}")
    print(f"  max posts/brand:  {posts_per_brand.max()}")

    _section("Content type distribution")
    ct = df["content_type"].value_counts(dropna=False)
    for k, v in ct.items():
        pct = v / len(df) * 100
        print(f"  {k:<10} {v:>6,}  ({pct:5.1f}%)")

    _section("Data quality")
    empty_caption = int((df["caption"].str.len() == 0).sum())
    empty_hashtags = int((df["hashtags"].apply(len) == 0).sum())
    with_location = int((df["location"].str.len() > 0).sum())
    n = len(df)
    print(f"  empty captions:   {empty_caption:>6,} ({empty_caption / n * 100:5.1f}%)")
    print(f"  empty hashtags:   {empty_hashtags:>6,} ({empty_hashtags / n * 100:5.1f}%)")
    print(f"  with location:    {with_location:>6,} ({with_location / n * 100:5.1f}%)")

    if csv_path or parquet_path:
        _section("Output files")
        if csv_path and csv_path.exists():
            size_kb = csv_path.stat().st_size / 1024
            print(f"  {csv_path.name:<22} {size_kb:>8.1f} KB")
        if parquet_path and parquet_path.exists():
            size_kb = parquet_path.stat().st_size / 1024
            print(f"  {parquet_path.name:<22} {size_kb:>8.1f} KB")

    print("=" * 72)
