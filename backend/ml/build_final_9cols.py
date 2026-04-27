"""
Step 4 - AI Reverse Engineering Insights
Transform the technical ml_ready_dataset.csv into a clean, interpretable dataset
with EXACTLY 9 columns for explanatory ML analysis.

Final columns:
    industry, brand, content_type, hour, dayofweek,
    nbrhashtags, captionlength, followers, engagementRate
"""

from pathlib import Path
import sys
import pandas as pd

HERE = Path(__file__).resolve().parent
SRC = HERE / "ml_ready_dataset.csv"
DST = HERE / "ml_ready_dataset_final_9cols.csv"

FINAL_COLS = [
    "industry",
    "brand",
    "content_type",
    "hour",
    "dayofweek",
    "nbrhashtags",
    "captionlength",
    "followers",
    "engagementRate",
]


def reconstruct_from_one_hot(df: pd.DataFrame, prefix: str, label_map: dict | None = None) -> pd.Series:
    """Collapse one-hot columns starting with `prefix` into a single categorical column."""
    cols = [c for c in df.columns if c.startswith(prefix)]
    if not cols:
        raise ValueError(f"No one-hot columns found with prefix '{prefix}'")
    # idxmax picks the column with value 1 per row
    raw = df[cols].idxmax(axis=1).str.replace(prefix, "", regex=False)
    if label_map:
        raw = raw.map(lambda v: label_map.get(v, v))
    return raw


def main() -> int:
    if not SRC.exists():
        print(f"[ERROR] Source file not found: {SRC}")
        return 1

    print(f"[INFO] Loading {SRC.name} ...")
    df = pd.read_csv(SRC)
    print(f"[INFO] Loaded shape: {df.shape}")
    print(f"[INFO] Source columns: {list(df.columns)}\n")

    # 1. Reconstruct industry from ind_* one-hots (lowercase the label)
    df["industry"] = reconstruct_from_one_hot(df, "ind_").str.lower()

    # 2. Reconstruct content_type from ctype_* (map 'image' -> 'photo' for readability)
    df["content_type"] = reconstruct_from_one_hot(
        df, "ctype_", label_map={"image": "photo"}
    )

    # 3. Reconstruct dayofweek from dow_* (0 = Monday ... 6 = Sunday, per pandas convention)
    if "dayofweek" not in df.columns:
        dow_cols = [c for c in df.columns if c.startswith("dow_")]
        if not dow_cols:
            print(
                "[ERROR] dayofweek cannot be reconstructed: neither a 'dayofweek' "
                "column nor any 'dow_*' one-hot columns nor a timestamp/date column "
                "are present in ml_ready_dataset.csv. Please provide the original "
                "dataset (clean_posts_dataset.csv) or the MongoDB extraction so we "
                "can derive it from the post timestamp."
            )
            return 2
        df["dayofweek"] = (
            df[dow_cols].idxmax(axis=1).str.replace("dow_", "", regex=False).astype(int)
        )

    # 4. Keep only the final 9 columns
    missing = [c for c in FINAL_COLS if c not in df.columns]
    if missing:
        print(f"[ERROR] Missing required columns after reconstruction: {missing}")
        return 3
    final = df[FINAL_COLS].copy()

    # 5. Type coercion + validation
    final["hour"] = pd.to_numeric(final["hour"], errors="coerce").astype("Int64")
    final["dayofweek"] = pd.to_numeric(final["dayofweek"], errors="coerce").astype("Int64")
    final["nbrhashtags"] = pd.to_numeric(final["nbrhashtags"], errors="coerce").astype("Int64")
    final["captionlength"] = pd.to_numeric(final["captionlength"], errors="coerce").astype("Int64")
    final["followers"] = pd.to_numeric(final["followers"], errors="coerce").astype("Int64")
    final["engagementRate"] = pd.to_numeric(final["engagementRate"], errors="coerce")

    # Validation checks (warnings only — we do NOT fabricate data)
    issues = []
    if final.isna().any().any():
        issues.append(f"missing values present:\n{final.isna().sum()}")
    dup_count = final.duplicated().sum()
    if dup_count:
        issues.append(f"{dup_count} duplicated rows")
    if not final["hour"].dropna().between(0, 23).all():
        issues.append("hour out of [0, 23] range")
    if not final["dayofweek"].dropna().between(0, 6).all():
        issues.append("dayofweek out of [0, 6] range")
    for col in ("nbrhashtags", "captionlength", "followers"):
        if (final[col].dropna() < 0).any():
            issues.append(f"{col} has negative values")
    if (final["engagementRate"].dropna() < 0).any():
        issues.append("engagementRate has negative values")

    # 6. Save
    final.to_csv(DST, index=False)
    print(f"[OK] Saved final dataset -> {DST}\n")

    # 7. Reports
    print("=" * 60)
    print("FINAL DATASET REPORT")
    print("=" * 60)
    print(f"Shape: {final.shape}")
    print(f"Columns: {list(final.columns)}\n")

    print("Dtypes:")
    print(final.dtypes.to_string())
    print()

    print("First 10 rows:")
    print(final.head(10).to_string(index=False))
    print()

    print("Missing values per column:")
    print(final.isna().sum().to_string())
    print()

    print("Duplicated rows:", int(final.duplicated().sum()))
    print()

    print("industry value_counts:")
    print(final["industry"].value_counts(dropna=False).to_string())
    print()

    print("content_type value_counts:")
    print(final["content_type"].value_counts(dropna=False).to_string())
    print()

    if issues:
        print("[WARN] Validation issues (no rows altered, reported only):")
        for i in issues:
            print(" -", i)
    else:
        print("[OK] All validation checks passed.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
