"""
build_dataset.py
================

Step 4 — AI Reverse Engineering: dataset preparation ONLY.

Produces a clean per-post dataset for DESCRIPTIVE / EXPLAINABLE analysis
of engagement patterns. No model training, no prediction, no feature
importance. Downstream scripts will handle TF-IDF, LDA topic modelling,
and ML explainability.

Two outputs (saved next to this file):
  • clean_posts_dataset.csv   — human-readable; keeps caption + hashtags_text
  • ml_ready_dataset.csv      — encoded numeric; ready for ML / SHAP / etc.

One row = one scraped post. Real Mongo data only — no synthetic rows.

Deps: pandas, numpy, pymongo, python-dotenv
Run:
    cd backend/ml
    pip install pandas numpy pymongo python-dotenv
    python build_dataset.py
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from pymongo import MongoClient


# ──────────────────────────────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────────────────────────────

HERE        = Path(__file__).resolve().parent
BACKEND_DIR = HERE.parent

load_dotenv(BACKEND_DIR / ".env")


def _infer_db_name(uri: str) -> str:
    """Pull the database name out of a Mongo URI (path component)."""
    if not uri:
        return "battouta_db"
    tail = uri.rsplit("/", 1)[-1].split("?", 1)[0]
    return tail or "battouta_db"


MONGODB_URI = os.getenv("MONGODB_URI") or "mongodb://127.0.0.1:27017/battouta_db"
DB_NAME     = os.getenv("MONGO_DB_NAME") or _infer_db_name(MONGODB_URI)

OUT_CLEAN = HERE / "clean_posts_dataset.csv"
OUT_ML    = HERE / "ml_ready_dataset.csv"

HASHTAG_RE = re.compile(r"#\w+", re.UNICODE)


# ──────────────────────────────────────────────────────────────────────
# NORMALIZATION
# ──────────────────────────────────────────────────────────────────────

# Strict mapping of any incoming industry / category string → one of the
# 5 canonical labels. Anything that doesn't resolve lands in OTHER and is
# reported in validation so the operator can patch the source data.
INDUSTRY_MAP = {
    # Hotels
    "hotels": "HOTELS", "hotel": "HOTELS", "hospitality": "HOTELS",
    "hotellerie": "HOTELS", "hôtellerie": "HOTELS", "hotels & resorts": "HOTELS",
    # Patisserie
    "patisserie": "PATISSERIE", "pâtisserie": "PATISSERIE",
    "patisseries": "PATISSERIE", "pastry": "PATISSERIE",
    "food & pastry": "PATISSERIE", "food and pastry": "PATISSERIE",
    # Fashion
    "fashion": "FASHION", "fashion & retail": "FASHION", "retail": "FASHION",
    "mode": "FASHION", "apparel": "FASHION", "clothing": "FASHION",
    # Restaurants
    "restaurants": "RESTAURANTS", "restaurant": "RESTAURANTS",
    "food business": "RESTAURANTS", "food & beverage": "RESTAURANTS",
    "food": "RESTAURANTS", "restauration": "RESTAURANTS",
    # Beauty
    "beauty": "BEAUTY", "cosmetics": "BEAUTY", "beauty & cosmetics": "BEAUTY",
    "skincare": "BEAUTY", "cosmétiques": "BEAUTY", "makeup": "BEAUTY",
}


def normalize_industry(*candidates: str | None) -> str:
    """Try each candidate in order. Exact match first, then fuzzy substring."""
    for c in candidates:
        if not c:
            continue
        key = c.strip().lower()
        if key in INDUSTRY_MAP:
            return INDUSTRY_MAP[key]
    for c in candidates:
        if not c:
            continue
        key = c.strip().lower()
        for k, v in INDUSTRY_MAP.items():
            if k in key:
                return v
    return "OTHER"


# Spec: video → reel, reel → reel, photo → image, image → image, carousel → carousel.
CONTENT_TYPE_MAP = {
    "video"   : "reel",
    "reel"    : "reel",
    "photo"   : "image",
    "image"   : "image",
    "carousel": "carousel",
}


def normalize_content_type(raw: str | None) -> str:
    if not raw:
        return "image"
    key = raw.strip().lower()
    return CONTENT_TYPE_MAP.get(key, key)


def hashtags_text(post: dict) -> str:
    """Joined hashtags as a single string (kept for downstream NLP / TF-IDF)."""
    tags = post.get("hashtags") or []
    if isinstance(tags, list) and tags:
        return " ".join(str(t).lstrip("#") for t in tags if t)
    caption = post.get("caption") or ""
    return " ".join(t.lstrip("#") for t in HASHTAG_RE.findall(caption))


def count_hashtags(post: dict) -> int:
    tags = post.get("hashtags") or []
    if isinstance(tags, list) and tags:
        return len(tags)
    return len(HASHTAG_RE.findall(post.get("caption") or ""))


# ──────────────────────────────────────────────────────────────────────
# 1. EXTRACT  (Mongo aggregation: unwind recentPosts + join brand + industry)
# ──────────────────────────────────────────────────────────────────────

def extract_from_mongo() -> pd.DataFrame:
    client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
    db = client[DB_NAME]

    pipeline = [
        {"$match": {
            "recentPosts.0": {"$exists": True},
            "followers"    : {"$gt": 0},
        }},
        {"$unwind": "$recentPosts"},
        {"$lookup": {
            "from"        : "competitors",
            "localField"  : "competitorId",
            "foreignField": "_id",
            "as"          : "competitor",
        }},
        {"$unwind": {"path": "$competitor", "preserveNullAndEmptyArrays": True}},
        {"$lookup": {
            "from"        : "projects",
            "localField"  : "projectId",
            "foreignField": "_id",
            "as"          : "project",
        }},
        {"$unwind": {"path": "$project", "preserveNullAndEmptyArrays": True}},
        {"$project": {
            "_id"          : 0,
            "platform"     : 1,
            "followers"    : 1,
            "brand"        : "$competitor.companyName",
            # Industry priority: project.industry → competitor.industry → project.category|marketCategory
            "proj_industry": "$project.industry",
            "comp_industry": "$competitor.industry",
            "proj_category": {"$ifNull": ["$project.category", "$project.marketCategory"]},
            "post"         : "$recentPosts",
        }},
    ]

    rows = list(db.socialanalyses.aggregate(pipeline, allowDiskUse=True))
    client.close()

    if not rows:
        sys.exit("✗ No documents returned from socialanalyses.")

    records = []
    for r in rows:
        p = r.get("post") or {}
        records.append({
            "platform"     : r.get("platform"),
            "industry"     : normalize_industry(
                                  r.get("proj_industry"),
                                  r.get("comp_industry"),
                                  r.get("proj_category"),
                              ),
            "brand"        : r.get("brand"),
            "content_type" : normalize_content_type(p.get("contentType")),
            "publishedAt"  : p.get("publishedAt"),
            "post_url"     : p.get("postUrl"),
            "caption"      : p.get("caption") or "",
            "hashtags_text": hashtags_text(p),
            "nbrhashtags"  : count_hashtags(p),
            "captionlength": len(p.get("caption") or ""),
            "followers"    : r.get("followers"),
            "likes"        : p.get("likes"),
            "comments"     : p.get("comments"),
        })

    return pd.DataFrame(records)


# ──────────────────────────────────────────────────────────────────────
# 2. CLEAN  +  TIME FEATURE ENGINEERING
# ──────────────────────────────────────────────────────────────────────

def clean_and_engineer(df: pd.DataFrame) -> pd.DataFrame:
    # Drop rows we can't use at all.
    df = df.dropna(subset=["likes", "followers", "publishedAt", "brand"]).copy()

    # Numeric coercion.
    for col in ("likes", "comments", "followers", "nbrhashtags", "captionlength"):
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["likes", "followers"]).copy()
    df["comments"]      = df["comments"].fillna(0)
    df["nbrhashtags"]   = df["nbrhashtags"].fillna(0)
    df["captionlength"] = df["captionlength"].fillna(0)

    # Followers must be positive (division-by-zero guard for engagementRate).
    df = df[df["followers"] > 0]
    df = df[(df["likes"] >= 0) & (df["comments"] >= 0)].copy()

    int_cols = ["likes", "comments", "followers", "nbrhashtags", "captionlength"]
    df[int_cols] = df[int_cols].astype(int)

    # Time features.
    df["publishedAt"] = pd.to_datetime(df["publishedAt"], errors="coerce", utc=True)
    df = df.dropna(subset=["publishedAt"]).copy()
    df["hour"]       = df["publishedAt"].dt.hour.astype(int)
    df["dayofweek"]  = df["publishedAt"].dt.dayofweek.astype(int)   # Mon=0 … Sun=6
    df["is_weekend"] = (df["dayofweek"] >= 5).astype(int)

    # Always recompute the target — never trust precomputed values.
    df["engagementRate"] = (df["likes"] + df["comments"]) / df["followers"] * 100.0

    # Deduplicate. postUrl is the natural unique key per post.
    has_url = df["post_url"].notna() & (df["post_url"].astype(str).str.len() > 0)
    df_url   = df[has_url].drop_duplicates(subset=["post_url"])
    df_nourl = df[~has_url].drop_duplicates(
        subset=["brand", "publishedAt", "captionlength", "likes"]
    )
    df = pd.concat([df_url, df_nourl], ignore_index=True)

    return df


# ──────────────────────────────────────────────────────────────────────
# 3. OUTLIERS  →  CLIP only (no row drops; keep close to 4119)
# ──────────────────────────────────────────────────────────────────────

def clip_outliers(df: pd.DataFrame,
                  cols=("likes", "comments", "engagementRate")) -> pd.DataFrame:
    df = df.copy()
    for c in cols:
        lo, hi = df[c].quantile([0.01, 0.99])
        clipped_low  = int((df[c] < lo).sum())
        clipped_high = int((df[c] > hi).sum())
        df[c] = df[c].clip(lower=lo, upper=hi)
        print(f"   clip {c:<16}  [{lo:>10.2f}, {hi:>10.2f}]  "
              f"low={clipped_low:>4}  high={clipped_high:>4}")
    return df


# ──────────────────────────────────────────────────────────────────────
# 4. BRAND-LEVEL EXPLANATORY FEATURES
# ──────────────────────────────────────────────────────────────────────

def add_brand_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adds:
      • brand_avg_engagement  — mean engagementRate per brand (baseline)
      • relative_engagement   — this post / brand baseline (1.0 = average)
      • posting_frequency     — posts per brand per week (over observed span)
    """
    df = df.copy()

    brand_avg = df.groupby("brand")["engagementRate"].transform("mean")
    df["brand_avg_engagement"] = brand_avg

    df["relative_engagement"] = np.where(
        brand_avg > 0,
        df["engagementRate"] / brand_avg,
        0.0,
    )

    span_days = df.groupby("brand")["publishedAt"].transform(
        lambda s: max((s.max() - s.min()).days, 1)
    )
    post_count = df.groupby("brand")["brand"].transform("count")
    df["posting_frequency"] = post_count / (span_days / 7.0)

    return df


# ──────────────────────────────────────────────────────────────────────
# 5. ENCODING (for ml_ready CSV only)
# ──────────────────────────────────────────────────────────────────────

def to_ml_ready(df: pd.DataFrame) -> pd.DataFrame:
    """One-hot encode industry / content_type / dayofweek; drop free text."""
    drop_cols = ["caption", "hashtags_text", "post_url", "publishedAt", "platform"]
    base = df.drop(columns=[c for c in drop_cols if c in df.columns])
    return pd.get_dummies(
        base,
        columns=["industry", "content_type", "dayofweek"],
        prefix=["ind", "ctype", "dow"],
        drop_first=False,
        dtype=int,
    )


# ──────────────────────────────────────────────────────────────────────
# 6. VALIDATION
# ──────────────────────────────────────────────────────────────────────

def validate(df: pd.DataFrame, raw_rows: int) -> None:
    print("\n=== Dataset summary ===")
    print(f"   raw rows               : {raw_rows}")
    print(f"   final rows             : {len(df)}")
    print(f"   unique brands          : {df['brand'].nunique()}")
    print(f"   columns (clean export) : {df.shape[1]}")

    print("\n=== Rows per industry ===")
    print(df["industry"].value_counts().to_string())

    print("\n=== Rows per content_type ===")
    print(df["content_type"].value_counts().to_string())

    print("\n=== Missing values per column ===")
    miss = df.isna().sum()
    miss = miss[miss > 0]
    print(miss.to_string() if not miss.empty else "  (none)")

    print("\n=== engagementRate summary ===")
    print(df["engagementRate"].describe().round(3).to_string())


# ──────────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────────

def main() -> None:
    host_hint = MONGODB_URI.split("@")[-1].split("/")[0]
    print(f"→ Connecting to db='{DB_NAME}' at {host_hint}")

    print("→ Extracting (unwind recentPosts + lookup competitor + project)…")
    df = extract_from_mongo()
    raw_rows = len(df)
    print(f"   extracted: {raw_rows}")

    print("→ Cleaning + time-feature engineering…")
    df = clean_and_engineer(df)
    print(f"   after clean & dedup: {len(df)}")

    print("→ Clipping outliers (1%–99% on likes / comments / engagementRate)…")
    df = clip_outliers(df)

    print("→ Adding brand-level features…")
    df = add_brand_features(df)

    # Ordered columns for the human-readable export.
    ordered = [
        "industry", "brand", "content_type",
        "publishedAt", "hour", "dayofweek", "is_weekend",
        "followers", "likes", "comments",
        "engagementRate", "brand_avg_engagement", "relative_engagement",
        "posting_frequency",
        "nbrhashtags", "captionlength",
        "caption", "hashtags_text",
        "platform", "post_url",
    ]
    ordered = [c for c in ordered if c in df.columns]
    df_clean = df[ordered]

    df_clean.to_csv(OUT_CLEAN, index=False)
    print(f"\n✓ clean_posts_dataset.csv  →  {len(df_clean)} rows × {df_clean.shape[1]} cols")
    print(f"  {OUT_CLEAN.relative_to(BACKEND_DIR)}")

    print("→ Building ML-ready encoded dataset…")
    df_ml = to_ml_ready(df_clean)
    df_ml.to_csv(OUT_ML, index=False)
    print(f"✓ ml_ready_dataset.csv     →  {len(df_ml)} rows × {df_ml.shape[1]} cols")
    print(f"  {OUT_ML.relative_to(BACKEND_DIR)}")

    validate(df_clean, raw_rows)


if __name__ == "__main__":
    main()
