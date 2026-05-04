"""Phase 1.4 validation — assert master-corpus invariants from the Phase 1 spec."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from pandas.api.types import is_datetime64_any_dtype, is_float_dtype, is_integer_dtype

PARQUET = Path(__file__).resolve().parent.parent / "data" / "df_master.parquet"

EXPECTED_COLUMNS = [
    "post_id", "post_url", "username",
    "industry", "industry_simple", "country",
    "caption", "hashtags", "content_type", "slide_count", "location",
    "likes", "comments", "views", "engagement_rate",
    "published_at",
    "followers", "brand_avg_likes", "brand_engagement_rate",
    "image_url", "video_url",
]

EXPECTED_INDUSTRIES = {"patisserie", "beauty", "fashion", "hotels", "restaurants"}


def main() -> None:
    df = pd.read_parquet(PARQUET)
    n = len(df)
    results: list[tuple[str, bool, str]] = []

    # 1. Total posts > 4,000
    results.append((
        "1. Total posts > 4,000",
        n > 4000,
        f"rows={n:,}",
    ))

    # 2. post_id unique
    dup_count = int(df["post_id"].duplicated().sum())
    results.append((
        "2. post_id unique",
        dup_count == 0,
        f"duplicates={dup_count}",
    ))

    # 3. published_at never null
    null_pub = int(df["published_at"].isna().sum())
    results.append((
        "3. published_at never null",
        null_pub == 0,
        f"nulls={null_pub}",
    ))

    # 4. Exactly the 5 expected industries
    actual_industries = set(df["industry_simple"].dropna().unique())
    results.append((
        "4. industry_simple == 5 expected",
        actual_industries == EXPECTED_INDUSTRIES,
        f"got={sorted(actual_industries)}",
    ))

    # 5. All 21 columns present in correct order
    actual_cols = list(df.columns)
    results.append((
        "5. 21 columns in correct order",
        actual_cols == EXPECTED_COLUMNS,
        f"n_cols={len(actual_cols)} match={actual_cols == EXPECTED_COLUMNS}",
    ))

    # 6. followers > 0 for all rows
    bad_followers = int((df["followers"] <= 0).sum())
    results.append((
        "6. followers > 0 (all rows)",
        bad_followers == 0,
        f"rows_with_followers<=0={bad_followers}",
    ))

    # 7. caption column exists (info: count empties; never fails)
    caption_exists = "caption" in df.columns
    empty_captions = int((df["caption"].fillna("").str.len() == 0).sum()) if caption_exists else -1
    results.append((
        "7. caption column exists",
        caption_exists,
        f"empty_captions={empty_captions} ({empty_captions / n * 100:.1f}%) [info-only]",
    ))

    # 8. Schema types
    pid_ok = df["post_id"].map(lambda x: isinstance(x, str)).all()
    likes_ok = is_integer_dtype(df["likes"])
    er_ok = is_float_dtype(df["engagement_rate"])
    pub = df["published_at"]
    pub_ok = is_datetime64_any_dtype(pub) and getattr(pub.dt, "tz", None) is not None and str(pub.dt.tz) == "UTC"
    schema_ok = bool(pid_ok and likes_ok and er_ok and pub_ok)
    results.append((
        "8. Schema types match",
        schema_ok,
        f"post_id=str:{bool(pid_ok)} likes=int:{likes_ok} engagement_rate=float:{er_ok} published_at=datetime UTC:{pub_ok}",
    ))

    # ---- Render summary table ----
    name_w = max(len(name) for name, _, _ in results)
    detail_w = max(len(detail) for _, _, detail in results)
    sep = "+" + "-" * (name_w + 2) + "+--------+" + "-" * (detail_w + 2) + "+"

    print()
    print("=" * len(sep))
    print(f"PHASE 1.4 VALIDATION — {PARQUET.name}  (rows={n:,})")
    print("=" * len(sep))
    print(sep)
    print(f"| {'Check'.ljust(name_w)} | {'Result':<6} | {'Detail'.ljust(detail_w)} |")
    print(sep)
    for name, passed, detail in results:
        status = "PASS" if passed else "FAIL"
        print(f"| {name.ljust(name_w)} | {status:<6} | {detail.ljust(detail_w)} |")
    print(sep)

    pass_count = sum(1 for _, p, _ in results if p)
    fail_count = len(results) - pass_count
    print(f"\nTotals: {pass_count} PASS  /  {fail_count} FAIL  (out of {len(results)})")

    if fail_count > 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
