"""
Prophet Preprocessing — ml-service/scripts/prophet_preprocess.py

Loads prophet_posts from MongoDB, aggregates by industry+week,
removes outliers (IQR-based), fills gaps, adds regressors, and
saves per-industry CSVs ready for Prophet training.

Columns saved:
  ds, y, n_posts, n_posts_scaled, is_ramadan, is_summer_peak

Usage:
    cd ml-service
    .venv/Scripts/python.exe scripts/prophet_preprocess.py
"""

import sys
import os
from pathlib import Path
from datetime import timedelta

import numpy as np
import pandas as pd
from pymongo import MongoClient
from dotenv import load_dotenv

# ── Paths ─────────────────────────────────────────────────────────────────
ROOT        = Path(__file__).resolve().parents[2]          # repo root
ENV_FILE    = ROOT / "backend" / ".env"
OUTPUT_DIR  = Path(__file__).resolve().parents[1] / "data" / "prophet"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

load_dotenv(ENV_FILE)
MONGODB_URI = os.getenv("MONGODB_URI")
if not MONGODB_URI:
    sys.exit("MONGODB_URI not found in backend/.env")

INDUSTRIES = ["patisserie", "fashion", "beauty", "hotels", "restaurants"]

# Ramadan periods for binary regressor (OPT-5)
RAMADAN_PERIODS = [
    ("2023-03-23", "2023-04-21"),
    ("2024-03-11", "2024-04-09"),
    ("2025-03-01", "2025-03-30"),
    ("2026-02-18", "2026-03-19"),
]

# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 — Load from MongoDB
# ─────────────────────────────────────────────────────────────────────────────

def load_posts() -> pd.DataFrame:
    print("Connecting to MongoDB ...")
    client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=10_000)
    db     = client.get_default_database()
    col    = db["prophet_posts"]

    docs = list(col.find(
        {},
        {
            "_id": 0,
            "username"      : 1,
            "industry"      : 1,
            "isLocal"       : 1,
            "publishedAt"   : 1,
            "likes"         : 1,
            "comments"      : 1,
            "engagementRate": 1,
            "followers"     : 1,
        }
    ))
    client.close()

    df = pd.DataFrame(docs)
    print(f"Loaded {len(df):,} documents from prophet_posts\n")
    return df


# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — Filter
# ─────────────────────────────────────────────────────────────────────────────

def filter_posts(df: pd.DataFrame) -> pd.DataFrame:
    before = len(df)

    df = df.dropna(subset=["publishedAt"])

    zero_mask = (
        (df["engagementRate"] == 0) &
        (df["likes"]          == 0) &
        (df["comments"]       == 0)
    )
    df = df[~zero_mask].copy()

    df["publishedAt"] = pd.to_datetime(df["publishedAt"], utc=True)

    after = len(df)
    print(f"STEP 2 -- Filter: {before:,} -> {after:,} posts  (removed {before - after:,})\n")
    return df


# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 — Aggregate by industry + week
# ─────────────────────────────────────────────────────────────────────────────

def aggregate_weekly(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    df["week"] = df["publishedAt"].dt.to_period("W-SUN").apply(lambda p: p.start_time)
    df["week"] = pd.to_datetime(df["week"]).dt.tz_localize(None)

    weekly: dict[str, pd.DataFrame] = {}
    print("STEP 3 — Weekly aggregation:")

    for industry in INDUSTRIES:
        sub = df[df["industry"] == industry]
        if sub.empty:
            print(f"  [{industry}] — no data, skipping")
            continue

        agg = (
            sub.groupby("week")
            .agg(
                y      = ("engagementRate", "mean"),
                n_posts= ("engagementRate", "count"),
            )
            .reset_index()
            .rename(columns={"week": "ds"})
            .sort_values("ds")
        )
        weekly[industry] = agg
        print(f"  [{industry}] {len(agg)} raw weeks  |  {sub.shape[0]:,} posts")

    print()
    return weekly


# ─────────────────────────────────────────────────────────────────────────────
# STEP 4 — Remove outliers per industry (OPT-3: cap at Q3 + 2.0 * IQR)
# ─────────────────────────────────────────────────────────────────────────────

def remove_outliers(weekly: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    print("STEP 4 — Outlier removal (OPT-3: cap at Q3 + 2.0 * IQR):")
    cleaned: dict[str, pd.DataFrame] = {}

    for industry, df in weekly.items():
        q1       = df["y"].quantile(0.25)
        q3       = df["y"].quantile(0.75)
        iqr      = q3 - q1
        cap      = q3 + 2.0 * iqr
        n_capped = (df["y"] > cap).sum()
        df       = df.copy()
        df["y"]  = df["y"].clip(upper=cap)
        cleaned[industry] = df
        print(f"  [{industry}]  Q1={q1:.4f}  Q3={q3:.4f}  IQR={iqr:.4f}  cap={cap:.4f}  capped={n_capped} weeks")

    print()
    return cleaned


# ─────────────────────────────────────────────────────────────────────────────
# STEP 5 — Fill missing weeks + interpolation
# ─────────────────────────────────────────────────────────────────────────────

def fill_missing_weeks(weekly: dict[str, pd.DataFrame], max_interp_gap: int = 4) -> dict[str, pd.DataFrame]:
    print(f"STEP 5 -- Fill missing weeks (interpolate gaps <= {max_interp_gap}w, else 0):")
    filled: dict[str, pd.DataFrame] = {}

    for industry, df in weekly.items():
        df = df.set_index("ds").sort_index()

        min_date = df.index.min()
        max_date = df.index.max()
        full_idx = pd.date_range(start=min_date, end=max_date, freq="W-MON")

        df = df.reindex(full_idx)
        df.index.name = "ds"

        has_data = df["n_posts"].notna()
        df["n_posts"] = df["n_posts"].fillna(0).astype(int)

        y = df["y"].copy()
        in_gap    = False
        gap_start = None

        for i, (idx, val) in enumerate(y.items()):
            if pd.isna(val):
                if not in_gap:
                    in_gap    = True
                    gap_start = i
            else:
                if in_gap:
                    gap_len = i - gap_start
                    if gap_len > max_interp_gap:
                        y.iloc[gap_start:i] = 0.0
                    in_gap = False

        if in_gap:
            y.iloc[gap_start:] = 0.0

        df["y"] = y
        df["y"] = df["y"].interpolate(method="linear", limit_direction="forward")
        df["y"] = df["y"].fillna(0.0)

        df = df.reset_index()
        filled[industry] = df

        n_original = int(has_data.sum())
        n_total    = len(df)
        print(f"  [{industry}]  total={n_total}w  original={n_original}w  filled={n_total - n_original}w")

    print()
    return filled


# ─────────────────────────────────────────────────────────────────────────────
# STEP 6 — Add regressors (OPT-2, OPT-5, OPT-6)
# ─────────────────────────────────────────────────────────────────────────────

def add_regressors(filled: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    print("STEP 6 — Adding regressors (OPT-2: n_posts_scaled | OPT-5: is_ramadan | OPT-6: is_summer_peak):")
    result: dict[str, pd.DataFrame] = {}

    for industry, df in filled.items():
        df = df.copy()

        # OPT-2: normalize n_posts
        mean_posts = df["n_posts"].mean()
        std_posts  = df["n_posts"].std()
        if std_posts > 0:
            df["n_posts_scaled"] = (df["n_posts"] - mean_posts) / std_posts
        else:
            df["n_posts_scaled"] = 0.0

        # OPT-5: Ramadan binary indicator
        df["is_ramadan"] = 0
        for start, end in RAMADAN_PERIODS:
            mask = (df["ds"] >= pd.Timestamp(start)) & (df["ds"] <= pd.Timestamp(end))
            df.loc[mask, "is_ramadan"] = 1
        n_ramadan = int(df["is_ramadan"].sum())

        # OPT-6: Summer peak (July=7, August=8, September=9)
        df["is_summer_peak"] = df["ds"].dt.month.isin([7, 8, 9]).astype(int)
        n_summer = int(df["is_summer_peak"].sum())

        result[industry] = df
        print(f"  [{industry}]  n_posts mean={mean_posts:.1f} std={std_posts:.1f}  "
              f"ramadan_weeks={n_ramadan}  summer_weeks={n_summer}")

    print()
    return result


# ─────────────────────────────────────────────────────────────────────────────
# STEP 7 — Validate + report
# ─────────────────────────────────────────────────────────────────────────────

def validate(filled: dict[str, pd.DataFrame], weekly_raw: dict[str, pd.DataFrame]) -> None:
    print("═" * 68)
    print("  PROPHET PREPROCESSING — VALIDATION REPORT")
    print("═" * 68)

    for industry in INDUSTRIES:
        if industry not in filled:
            print(f"\n  [{industry.upper()}] — NO DATA")
            continue

        df  = filled[industry]
        raw = weekly_raw.get(industry, pd.DataFrame())

        total_weeks  = len(df)
        weeks_data   = int((df["n_posts"] > 0).sum())
        weeks_filled = total_weeks - weeks_data
        oldest       = df["ds"].min().strftime("%Y-%m-%d")
        newest       = df["ds"].max().strftime("%Y-%m-%d")
        mean_er      = df["y"].mean()
        max_er       = df["y"].max()

        if total_weeks >= 104:
            feasibility = "GOOD  (2+ years)"
        elif total_weeks >= 52:
            feasibility = "OK    (1–2 years)"
        else:
            feasibility = "POOR  (< 1 year)"

        print(f"\n  [{industry.upper()}]")
        print(f"    Total weeks      : {total_weeks}")
        print(f"    Date range       : {oldest}  ->  {newest}")
        print(f"    Weeks with data  : {weeks_data}")
        print(f"    Weeks filled     : {weeks_filled}")
        print(f"    Mean engRate     : {mean_er:.4f}%")
        print(f"    Max engRate      : {max_er:.4f}%")
        print(f"    Regressor cols   : n_posts_scaled, is_ramadan, is_summer_peak")
        print(f"    Prophet          : {feasibility}")

    print("\n" + "═" * 68)


# ─────────────────────────────────────────────────────────────────────────────
# STEP 8 — Save CSVs
# ─────────────────────────────────────────────────────────────────────────────

def save_csvs(filled: dict[str, pd.DataFrame]) -> None:
    print("\nSTEP 8 — Saving CSVs (with regressor columns):")
    for industry, df in filled.items():
        out = OUTPUT_DIR / f"{industry}_preprocessed.csv"
        cols = ["ds", "y", "n_posts", "n_posts_scaled", "is_ramadan", "is_summer_peak"]
        df[cols].to_csv(out, index=False)
        print(f"  Saved {len(df)} rows → {out}")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    df         = load_posts()
    df         = filter_posts(df)
    weekly_raw = aggregate_weekly(df)
    weekly     = remove_outliers(weekly_raw)
    filled     = fill_missing_weeks(weekly, max_interp_gap=4)
    filled     = add_regressors(filled)
    validate(filled, weekly_raw)
    save_csvs(filled)
    print("STOP — waiting for validation before Prophet training.\n")


if __name__ == "__main__":
    main()
