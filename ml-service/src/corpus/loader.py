"""Master corpus DataFrame builder — 21-column spec.

Flattens every Instagram post under PFE projects into one row of the
master corpus DataFrame.

Brand-context features (brand_avg_likes, brand_engagement_rate) are
computed as STRICTLY PAST-ONLY expanding means per brand to avoid
target leakage (Hyndman & Athanasopoulos 2018, §3.4). Cold-start
imputation for first-post-per-brand uses INDUSTRY MEDIANS, following
the standard cold-start prior in:
  - Trivedi (2019) — industry-typical priors for missing user-history.
  - Chen et al. (2022) — industry-anchored imputation for sparse
    engagement data.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

INDUSTRY_MAP: Dict[str, str] = {
    "PFE Analysis - Patisserie":  "patisserie",
    "PFE Analysis - Beauty":      "beauty",
    "PFE Analysis - Fashion":     "fashion",
    "PFE Analysis - Hotels":      "hotels",
    "PFE Analysis - Restaurants": "restaurants",
}

EXCLUDED_USERNAMES = {"nike", "sephora", "fstunis"}

SHORTCODE_RE = re.compile(r"/(?:p|reel|tv)/([^/?]+)")

COLUMNS: List[str] = [
    # Identifiers (3)
    "post_id", "post_url", "username",
    # Project info (3)
    "industry", "industry_simple", "country",
    # Content (5)
    "caption", "hashtags", "content_type", "slide_count", "location",
    # Engagement (4)
    "likes", "comments", "views", "engagement_rate",
    # Temporal (1)
    "published_at",
    # Brand context (3)
    "followers", "brand_avg_likes", "brand_engagement_rate",
    # Media URLs (2)
    "image_url", "video_url",
]


def extract_shortcode(post_url: str) -> str:
    if not post_url:
        return ""
    match = SHORTCODE_RE.search(post_url)
    return match.group(1) if match else post_url


def derive_industry_simple(project_name: str) -> Optional[str]:
    return INDUSTRY_MAP.get(project_name)


def _to_utc(dt: Any) -> Optional[datetime]:
    if dt is None:
        return None
    if isinstance(dt, datetime):
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
    return dt


def _compute_brand_features_pastonly(df: pd.DataFrame) -> pd.DataFrame:
    """Compute brand_avg_likes and brand_engagement_rate as expanding
    *past-only* means within each brand (username), ordered by
    published_at.

    For post i of brand B:
        brand_engagement_rate[i] = mean(engagement_rate[0..i-1])  of B
        brand_avg_likes[i]       = mean(likes[0..i-1])            of B

    The first post per brand has no prior history → NaN (handled in
    _impute_first_post_with_industry_median).

    Ref: Hyndman & Athanasopoulos (2018) "Forecasting: Principles and
    Practice" §3.4 — rolling/expanding statistics must be strictly
    past-only to avoid look-ahead bias.
    """
    df = df.sort_values(
        ["username", "published_at", "post_id"],
        kind="mergesort",  # stable
    ).reset_index(drop=True)

    g = df.groupby("username", sort=False, group_keys=False)
    # shift(1) drops the current row from the expanding window → past-only.
    df["brand_engagement_rate"] = g["engagement_rate"].apply(
        lambda s: s.shift(1).expanding().mean()
    ).astype("float64")
    df["brand_avg_likes"] = g["likes"].apply(
        lambda s: s.shift(1).expanding().mean()
    ).astype("float64")
    return df


def _impute_first_post_with_industry_median(
    df: pd.DataFrame,
) -> Tuple[pd.DataFrame, Dict[str, Dict[str, float]]]:
    """Cold-start imputation: fill first-post-per-brand NaN with
    INDUSTRY MEDIANS (5 industries: patisserie, fashion, beauty,
    hotels, restaurants).

    Refs:
      - Trivedi, P. (2019) — cold-start recommendation in social
        media: industry-typical priors for missing user-history.
      - Chen, J., et al. (2022) — industry-anchored imputation for
        sparse engagement data.

    Industry medians are computed from POST-LEVEL engagement_rate and
    likes within each industry (the canonical cohort prior). This
    introduces only a weak global prior, NOT row-level target leakage.

    Returns (df_imputed, medians) where
        medians = {industry: {"engagement_rate": float, "likes": float}}
    """
    medians: Dict[str, Dict[str, float]] = {}
    for industry, sub in df.groupby("industry_simple", sort=True):
        medians[industry] = {
            "engagement_rate": float(sub["engagement_rate"].median()),
            "likes":           float(sub["likes"].median()),
        }

    er_fill    = df["industry_simple"].map(lambda i: medians[i]["engagement_rate"])
    likes_fill = df["industry_simple"].map(lambda i: medians[i]["likes"])
    df["brand_engagement_rate"] = df["brand_engagement_rate"].fillna(er_fill)
    df["brand_avg_likes"]       = df["brand_avg_likes"].fillna(likes_fill)
    return df, medians


def build_master_corpus(
    projects: List[dict],
    competitors: List[dict],
    analyses: List[dict],
) -> Tuple[pd.DataFrame, Dict[str, int], Dict[str, Dict[str, float]]]:
    proj_by_id = {p["_id"]: p for p in projects}
    comp_by_id = {c["_id"]: c for c in competitors}

    rows: List[dict] = []
    drop_log = {
        "skipped_orphan_competitor": 0,
        "skipped_orphan_project": 0,
        "skipped_excluded_username": 0,
        "skipped_unmapped_industry": 0,
        "skipped_no_publish_date": 0,
        "analyses_with_no_recent_posts": 0,
    }

    for analysis in analyses:
        comp = comp_by_id.get(analysis.get("competitorId"))
        if comp is None:
            drop_log["skipped_orphan_competitor"] += 1
            continue
        proj = proj_by_id.get(comp.get("projectId"))
        if proj is None:
            drop_log["skipped_orphan_project"] += 1
            continue

        username = (analysis.get("username") or "").strip().lower()
        if username in EXCLUDED_USERNAMES:
            drop_log["skipped_excluded_username"] += 1
            continue

        industry_simple = derive_industry_simple(proj.get("name") or "")
        if industry_simple is None:
            drop_log["skipped_unmapped_industry"] += 1
            continue

        industry = (proj.get("industry") or "Unknown").strip()
        country = (proj.get("country") or "Tunisie").strip()
        followers = int(analysis.get("followers") or 0)
        # NOTE: analysis.avgLikes / analysis.engagementRate are LEAKY
        # (computed over ALL recent posts, including the row's own
        # engagement_rate). Drop them and recompute past-only below.
        # See _compute_brand_features_pastonly().

        recent_posts = analysis.get("recentPosts") or []
        if not recent_posts:
            drop_log["analyses_with_no_recent_posts"] += 1
            continue

        for post in recent_posts:
            published_at = _to_utc(post.get("publishedAt"))
            if published_at is None:
                drop_log["skipped_no_publish_date"] += 1
                continue

            post_url = post.get("postUrl") or ""
            rows.append({
                "post_id": extract_shortcode(post_url),
                "post_url": post_url,
                "username": username,
                "industry": industry,
                "industry_simple": industry_simple,
                "country": country,
                "caption": post.get("caption") or "",
                "hashtags": list(post.get("hashtags") or []),
                "content_type": (post.get("contentType") or "photo").lower(),
                "slide_count": int(post.get("slideCount") or 0),
                "location": (post.get("location") or "").strip(),
                "likes": int(post.get("likes") or 0),
                "comments": int(post.get("comments") or 0),
                "views": int(post.get("views") or 0),
                "engagement_rate": float(post.get("engagementRate") or 0.0),
                "published_at": published_at,
                "followers": followers,
                "brand_avg_likes": float("nan"),       # set in past-only step
                "brand_engagement_rate": float("nan"), # set in past-only step
                "image_url": post.get("imageUrl") or "",
                "video_url": post.get("videoUrl") or "",
            })

    df = pd.DataFrame(rows, columns=COLUMNS)
    df["published_at"] = pd.to_datetime(df["published_at"], utc=True)

    # --- Past-only brand features + cold-start imputation -------------------
    df = _compute_brand_features_pastonly(df)
    df, medians = _impute_first_post_with_industry_median(df)

    return df, drop_log, medians


def save_master_corpus(df: pd.DataFrame, out_dir: Path) -> Tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)

    parquet_path = out_dir / "df_master.parquet"
    csv_path = out_dir / "df_master.csv"

    df.to_parquet(parquet_path, index=False)

    df_csv = df.copy()
    df_csv["hashtags"] = df_csv["hashtags"].apply(json.dumps)
    df_csv.to_csv(csv_path, index=False)

    return csv_path, parquet_path
