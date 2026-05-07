"""Inspect URL columns in df_master_masked_with_topics.parquet.

Read-only inspection — do not modify any file.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "df_master_masked_with_topics.parquet"

URL_CANDIDATES = [
    "display_url",
    "thumbnail_url",
    "video_url",
    "video_thumbnail_url",
    "carousel_media",
    "carousel_media_urls",
    "post_url",
    "image_url",
    "media_url",
    "url",
    "permalink",
    "shortcode",
    "video_view_count",
]


def truncate(value, n: int = 100) -> str:
    if value is None:
        return "<None>"
    s = str(value)
    return s if len(s) <= n else s[:n] + "..."


def main() -> None:
    print(f"Loading: {DATA_PATH}")
    df = pd.read_parquet(DATA_PATH)
    n_rows = len(df)
    print(f"Shape: {df.shape}\n")

    # ---- STEP 1: all columns ----
    print("=" * 72)
    print("STEP 1 — ALL COLUMNS")
    print("=" * 72)
    print(f"{'#':>3}  {'column':<40} {'dtype':<18} {'%non-null':>10}  sample")
    print("-" * 100)
    for i, col in enumerate(df.columns):
        non_null = df[col].notna().sum()
        pct = 100.0 * non_null / n_rows if n_rows else 0.0
        sample_idx = df[col].first_valid_index()
        sample = truncate(df.at[sample_idx, col], 60) if sample_idx is not None else "<all null>"
        print(f"{i:>3}  {col:<40} {str(df[col].dtype):<18} {pct:>9.1f}%  {sample}")

    # ---- STEP 2: URL-related columns ----
    print("\n" + "=" * 72)
    print("STEP 2 — URL-RELATED COLUMNS")
    print("=" * 72)
    found: list[str] = []
    for cand in URL_CANDIDATES:
        if cand in df.columns:
            found.append(cand)
            non_null = df[cand].notna().sum()
            pct = 100.0 * non_null / n_rows if n_rows else 0.0
            print(f"\n[FOUND] {cand}  —  non-null: {non_null}/{n_rows} ({pct:.1f}%)")
            samples = df[cand].dropna().head(3).tolist()
            for j, s in enumerate(samples, 1):
                print(f"   sample {j}: {truncate(s, 100)}")
        else:
            print(f"[----- ] {cand}  (not present)")

    # also flag any other columns that *look* like URLs
    print("\nOther columns whose values look URL-ish (startswith http):")
    for col in df.columns:
        if col in found:
            continue
        if df[col].dtype != object:
            continue
        sample_idx = df[col].first_valid_index()
        if sample_idx is None:
            continue
        v = df.at[sample_idx, col]
        if isinstance(v, str) and v.startswith(("http://", "https://")):
            non_null = df[col].notna().sum()
            pct = 100.0 * non_null / n_rows if n_rows else 0.0
            print(f"   - {col}: {pct:.1f}% non-null, e.g. {truncate(v, 80)}")
            found.append(col)

    # ---- STEP 3: per content_type analysis ----
    print("\n" + "=" * 72)
    print("STEP 3 — URL COVERAGE BY content_type")
    print("=" * 72)

    if "content_type" not in df.columns:
        print("!! 'content_type' column not present — skipping.")
        # try alternate names
        for alt in ("media_type", "type", "post_type"):
            if alt in df.columns:
                print(f"   alternate found: {alt} -> values: {df[alt].value_counts(dropna=False).to_dict()}")
    else:
        url_cols_present = [c for c in found if c in df.columns]
        print(f"\nURL columns considered: {url_cols_present}\n")

        header = f"{'content_type':<14}{'n_posts':>8}  " + "  ".join(f"{c:>20}" for c in url_cols_present)
        print(header)
        print("-" * len(header))
        for ct, sub in df.groupby("content_type", dropna=False):
            n = len(sub)
            cells = []
            for c in url_cols_present:
                pct = 100.0 * sub[c].notna().sum() / n if n else 0.0
                cells.append(f"{pct:>19.1f}%")
            print(f"{str(ct):<14}{n:>8}  " + "  ".join(cells))

        # one example per content_type
        print("\nSample post per content_type:")
        for ct, sub in df.groupby("content_type", dropna=False):
            print(f"\n--- {ct} example ---")
            row = sub.iloc[0]
            id_col = next((k for k in ("post_id", "shortcode", "id") if k in df.columns), None)
            if id_col:
                print(f"  {id_col}: {truncate(row[id_col], 60)}")
            for c in url_cols_present:
                print(f"  {c}: {truncate(row[c], 100)}")

    print("\nDONE — read-only inspection.")


if __name__ == "__main__":
    main()
