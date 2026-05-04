"""Step 4 / Phase 3 — feature engineering for the ML comparison phase.

Reads ``data/df_master_masked_with_topics.parquet`` (V2 BERTopic output)
and produces a 28-column ML-ready dataset:

    post_id  +  26 features (4 groups)  +  engagement_rate (target)

Outputs:
  - data/df_ml_dataset.parquet
  - data/phase3_features_summary.txt

Design decisions (also documented inline):
  - No imputation (per project memory feedback_no_imputation.md). Tree-based
    models in Phase 4 (XGBoost/LightGBM/CatBoost, RandomForest in sklearn
    >=1.4) handle NaN natively. Filling would inject false zeros into the
    engagement signal.
  - Drop rows where caption is null AND topic_id == -1: no caption + outlier
    cluster = no signal worth modeling.
  - engagement_rate capped at the 99th percentile (clip upper only) — max
    is 164% which would dominate MAE/RMSE without explanatory power.
  - Temporal fields derived in Africa/Tunis (UTC+1, no DST), not UTC, so
    is_evening / is_lunch reflect local posting time.
  - mention_count is computed on RAW caption (cleaner.py strips @mentions
    from caption_clean, so counting on the clean column would always be 0).
  - Source published_at is datetime64[ns, UTC]; hashtags is numpy.ndarray
    of str (empty array when no hashtags) — len() works directly.
"""
from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
IN_PATH = ROOT / "data" / "df_master_masked_with_topics.parquet"
OUT_PARQUET = ROOT / "data" / "df_ml_dataset.parquet"
OUT_SUMMARY = ROOT / "data" / "phase3_features_summary.txt"

# --- Regexes (project convention: no \u escapes; codepoints via chr()) -------
# Emoji blocks (most populous):
#   U+1F300 - U+1F9FF   pictographs / emoticons / symbols / transport / supplemental
#   U+2600  - U+27BF    misc symbols + dingbats
#   U+1F000 - U+1F2FF   regional indicators / cards / mahjong / domino
EMOJI_RE = re.compile(
    "["
    + chr(0x1F300) + "-" + chr(0x1F9FF)
    + chr(0x2600) + "-" + chr(0x27BF)
    + chr(0x1F000) + "-" + chr(0x1F2FF)
    + "]"
)

MENTION_RE = re.compile(r"@\w+")

# Promo lexicon — case-insensitive substring match on lowercased caption_clean.
# "% off" needs %% in re.escape (well, % is literal — escape just to be safe).
PROMO_RE = re.compile(
    r"(?:promo|soldes|sale|offre|% off|discount|réduction|remise|deal)",
    re.IGNORECASE,
)

HOLIDAY_MONTHS = {2, 3, 4, 12}     # St-Valentin / Ramadan window / Aïd / Christmas
EVENING_HOURS = {18, 19, 20, 21, 22, 23}
LUNCH_HOURS = {11, 12, 13, 14}


def _hashtag_count(v: Any) -> int:
    """Robust hashtag count.

    Source has every row as a numpy.ndarray of str (empty array if no
    hashtags). Defensive against legacy CSV-imported strings like "[]" or
    "tag1,tag2" if upstream changes.
    """
    if v is None:
        return 0
    if isinstance(v, (list, tuple, np.ndarray, pd.Series)):
        return int(len(v))
    if isinstance(v, float) and np.isnan(v):
        return 0
    if isinstance(v, str):
        s = v.strip()
        if not s or s in ("[]", "()", "{}"):
            return 0
        # Try Python literal (handles "['a','b']")
        try:
            import ast

            parsed = ast.literal_eval(s)
            if isinstance(parsed, (list, tuple, set)):
                return len(parsed)
        except (ValueError, SyntaxError):
            pass
        # Fall back to comma split.
        return sum(1 for p in s.split(",") if p.strip())
    return 0


def _safe_str(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and np.isnan(v):
        return ""
    return str(v)


# ---- Feature build -------------------------------------------------------- #

def _build_group1(df: pd.DataFrame) -> pd.DataFrame:
    """5 raw numerical features (NaN preserved — no imputation policy)."""
    return df[
        ["followers", "brand_avg_likes", "brand_engagement_rate",
         "slide_count", "views"]
    ].copy()


def _build_group2(df: pd.DataFrame) -> pd.DataFrame:
    """6 derived numerical features."""
    out = pd.DataFrame(index=df.index)
    out["hashtags_count"] = df["hashtags"].apply(_hashtag_count).astype("int32")
    out["caption_length"] = df["caption_clean"].fillna("").str.len().astype("int32")
    out["word_count"] = df["caption_clean"].fillna("").str.split().str.len().fillna(0).astype("int32")
    out["emoji_count"] = (
        df["caption_clean"].fillna("").apply(lambda s: len(EMOJI_RE.findall(s))).astype("int32")
    )
    # Use RAW caption — cleaner.py strips @mentions from caption_clean, so
    # a count on caption_clean would always be zero.
    out["mention_count"] = (
        df["caption"].fillna("").apply(lambda s: len(MENTION_RE.findall(s))).astype("int32")
    )
    out["has_caption"] = df["has_caption"].astype(bool)
    return out


def _build_group3(df: pd.DataFrame) -> pd.DataFrame:
    """8 temporal features. published_at is UTC; convert to Africa/Tunis
    (UTC+1, no DST) before extracting hour/dow/etc. so is_evening/is_lunch
    reflect *local* posting time (the only interpretation that's meaningful).
    """
    out = pd.DataFrame(index=df.index)
    pub_utc = pd.to_datetime(df["published_at"], utc=True)
    pub_local = pub_utc.dt.tz_convert("Africa/Tunis")

    hour = pub_local.dt.hour.astype("int16")
    dow = pub_local.dt.dayofweek.astype("int16")  # 0=Mon ... 6=Sun
    month = pub_local.dt.month.astype("int16")
    quarter = pub_local.dt.quarter.astype("int16")

    out["hour"] = hour
    out["day_of_week"] = dow
    out["month"] = month
    out["quarter"] = quarter
    out["is_weekend"] = (dow >= 5)
    out["is_evening"] = hour.isin(EVENING_HOURS)
    out["is_lunch"] = hour.isin(LUNCH_HOURS)

    # days_since_first_post per username — operate on the UTC value so the
    # difference is unambiguous (timezone shift doesn't change deltas).
    first = pub_utc.groupby(df["username"]).transform("min")
    delta_days = (pub_utc - first).dt.total_seconds() / 86400.0
    out["days_since_first_post"] = delta_days.astype("float32")
    return out


def _build_group4(df: pd.DataFrame) -> pd.DataFrame:
    """7 categorical & flag features."""
    out = pd.DataFrame(index=df.index)
    out["content_type"] = df["content_type"].astype("string")
    out["industry_simple"] = df["industry_simple"].astype("string")
    out["topic_id"] = df["topic_id"].astype("int32")
    out["caption_lang"] = df["caption_lang"].astype("string")

    cap_lower = df["caption_clean"].fillna("").str.lower()
    out["has_question"] = df["caption_clean"].fillna("").str.contains(r"\?", regex=True)
    out["has_promo_word"] = cap_lower.str.contains(PROMO_RE, regex=True)
    month = pd.to_datetime(df["published_at"], utc=True).dt.tz_convert(
        "Africa/Tunis"
    ).dt.month
    out["is_holiday_period"] = month.isin(HOLIDAY_MONTHS)
    return out


# ---- Reporting ------------------------------------------------------------ #

FEATURE_GROUPS: Dict[str, List[str]] = {
    "Group 1 — raw numerical": [
        "followers", "brand_avg_likes", "brand_engagement_rate",
        "slide_count", "views",
    ],
    "Group 2 — derived numerical": [
        "hashtags_count", "caption_length", "word_count",
        "emoji_count", "mention_count", "has_caption",
    ],
    "Group 3 — temporal": [
        "hour", "day_of_week", "month", "quarter",
        "is_weekend", "is_evening", "is_lunch", "days_since_first_post",
    ],
    "Group 4 — categorical & flags": [
        "content_type", "industry_simple", "topic_id", "caption_lang",
        "has_question", "has_promo_word", "is_holiday_period",
    ],
}


def _feature_stats_row(name: str, s: pd.Series) -> Dict[str, Any]:
    n_null = int(s.isna().sum())
    if pd.api.types.is_bool_dtype(s):
        s_int = s.astype("int8")
        return {
            "name": name, "dtype": "bool",
            "n_null": n_null,
            "min": int(s_int.min()), "max": int(s_int.max()),
            "mean": float(s_int.mean()), "median": float(s_int.median()),
            "summary": "",
        }
    if pd.api.types.is_numeric_dtype(s):
        return {
            "name": name, "dtype": str(s.dtype),
            "n_null": n_null,
            "min": float(s.min()) if n_null < len(s) else float("nan"),
            "max": float(s.max()) if n_null < len(s) else float("nan"),
            "mean": float(s.mean()) if n_null < len(s) else float("nan"),
            "median": float(s.median()) if n_null < len(s) else float("nan"),
            "summary": "",
        }
    # Categorical / string
    vc = s.value_counts(dropna=True)
    n_unique = int(vc.shape[0])
    top = (
        f"top='{str(vc.index[0])}' ({int(vc.iloc[0])})" if n_unique else "n/a"
    )
    return {
        "name": name, "dtype": str(s.dtype),
        "n_null": n_null,
        "min": None, "max": None, "mean": None, "median": None,
        "summary": f"n_unique={n_unique}, {top}",
    }


def _spearman_with_target(
    df_features: pd.DataFrame,
    target: pd.Series,
) -> List[Tuple[str, float, float, int]]:
    """Spearman correlation between every feature and the target.

    Categorical strings are factorized first (arbitrary code mapping). The
    correlation is still meaningful as a *screening* signal because Spearman
    is rank-based — but it should not be over-interpreted for nominal
    categoricals (encoding ordering is arbitrary).
    """
    rows: List[Tuple[str, float, float, int]] = []
    for col in df_features.columns:
        s = df_features[col]
        if pd.api.types.is_bool_dtype(s):
            x = s.astype("int8").to_numpy()
        elif pd.api.types.is_numeric_dtype(s):
            x = s.astype("float64").to_numpy()
        else:
            codes, _ = pd.factorize(s, sort=True, use_na_sentinel=True)
            x = codes.astype("float64")
            # Sentinel -1 → NaN so spearmanr drops it.
            x[x == -1] = np.nan
        y = target.astype("float64").to_numpy()
        mask = ~np.isnan(x) & ~np.isnan(y)
        n_used = int(mask.sum())
        if n_used < 3:
            rows.append((col, float("nan"), float("nan"), n_used))
            continue
        # Skip constant features: spearman is undefined and scipy emits a
        # ConstantInputWarning. has_caption is constant in this dataset
        # (source already filtered has_caption=True).
        if np.unique(x[mask]).size < 2:
            rows.append((col, float("nan"), float("nan"), n_used))
            continue
        try:
            r, p = spearmanr(x[mask], y[mask])
            rows.append((col, float(r), float(p), n_used))
        except Exception:  # noqa: BLE001
            rows.append((col, float("nan"), float("nan"), n_used))
    return rows


def _format_summary(
    df_ml: pd.DataFrame,
    target_name: str,
    cap_value: float,
    n_in: int,
    n_dropped: int,
    spearman_rows: List[Tuple[str, float, float, int]],
) -> str:
    L: List[str] = []
    L.append("=" * 96)
    L.append("Phase 3 — feature engineering summary")
    L.append("=" * 96)
    L.append(f"  source:           {IN_PATH}")
    L.append(f"  output:           {OUT_PARQUET}")
    L.append(f"  rows in:          {n_in:,}")
    L.append(f"  rows dropped:     {n_dropped:,}  "
             f"(no caption AND topic_id == -1)")
    L.append(f"  rows out:         {len(df_ml):,}")
    L.append(f"  cols:             {df_ml.shape[1]}  "
             f"(post_id + 26 features + engagement_rate)")
    L.append("")
    L.append("  NOTE: post_id is a TRACEABILITY column, not a feature.")
    L.append("        Use it to keep deterministic row IDs across folds and")
    L.append("        to join back to the source parquet. Do NOT pass it as")
    L.append("        a feature to the Phase 4 models.")
    L.append("")
    L.append(f"  engagement_rate cap (99th pct): {cap_value:.4f}  "
             f"(clip upper only)")
    L.append("")

    L.append("Feature inventory by group")
    L.append("-" * 96)
    header = f"{'name':<24} {'group':<32} {'dtype':<12} {'n_null':>6}  {'min':>10} {'max':>10} {'mean':>10} {'median':>10}  notes"
    L.append(header)
    L.append("-" * len(header))
    for group_label, feat_names in FEATURE_GROUPS.items():
        for name in feat_names:
            s = df_ml[name]
            row = _feature_stats_row(name, s)
            mn = "" if row["min"] is None else f"{row['min']:>10.3f}"
            mx = "" if row["max"] is None else f"{row['max']:>10.3f}"
            mu = "" if row["mean"] is None else f"{row['mean']:>10.3f}"
            md = "" if row["median"] is None else f"{row['median']:>10.3f}"
            L.append(
                f"{name:<24} {group_label:<32} {row['dtype']:<12} "
                f"{row['n_null']:>6}  "
                f"{mn:<10} {mx:<10} {mu:<10} {md:<10}  {row['summary']}"
            )

    L.append("")
    L.append(f"Target distribution (post-cap): {target_name}")
    L.append("-" * 96)
    t = df_ml[target_name]
    pcts = t.quantile([0.25, 0.5, 0.75, 0.95, 0.99])
    L.append(f"  count:  {int(t.shape[0]):,}")
    L.append(f"  mean:   {t.mean():.4f}")
    L.append(f"  std:    {t.std():.4f}")
    L.append(f"  min:    {t.min():.4f}")
    L.append(f"  p25:    {pcts.loc[0.25]:.4f}")
    L.append(f"  median: {pcts.loc[0.50]:.4f}")
    L.append(f"  p75:    {pcts.loc[0.75]:.4f}")
    L.append(f"  p95:    {pcts.loc[0.95]:.4f}")
    L.append(f"  p99:    {pcts.loc[0.99]:.4f}")
    L.append(f"  max:    {t.max():.4f}")

    L.append("")
    L.append(f"Top 10 Spearman correlations with {target_name}")
    L.append("-" * 96)
    L.append(
        "  (Categorical strings factorized first; correlation is a screening "
        "signal —"
    )
    L.append("   ranking-based but encoding ordering is arbitrary for nominal cols.)")
    L.append("")
    sorted_rows = sorted(
        (r for r in spearman_rows if not np.isnan(r[1])),
        key=lambda r: -abs(r[1]),
    )[:10]
    L.append(f"  {'feature':<24} {'spearman_r':>12} {'p-value':>12} {'n_used':>10}")
    L.append("  " + "-" * 60)
    for name, r, p, n in sorted_rows:
        L.append(f"  {name:<24} {r:>+12.4f} {p:>12.2e} {n:>10}")

    L.append("")
    L.append("=" * 96)
    return "\n".join(L) + "\n"


# ---- Main ----------------------------------------------------------------- #

def main() -> None:
    print(f"Loading {IN_PATH} ...")
    df = pd.read_parquet(IN_PATH)
    n_in = len(df)
    print(f"  shape: {df.shape}")

    # --- Cleaning -----------------------------------------------------------
    # Drop rows with no caption AND outlier topic_id (no signal).
    is_no_caption = df["caption"].isna() | (df["caption"].astype(str).str.strip() == "")
    is_outlier = df["topic_id"] == -1
    drop_mask = is_no_caption & is_outlier
    n_drop = int(drop_mask.sum())
    df = df.loc[~drop_mask].reset_index(drop=True).copy()
    print(f"  Dropped {n_drop:,} rows (no caption AND topic_id == -1).")
    print(f"  shape after drop: {df.shape}")

    # Cap engagement_rate at 99th percentile (computed on the post-drop rows).
    cap_value = float(df["engagement_rate"].quantile(0.99))
    n_above = int((df["engagement_rate"] > cap_value).sum())
    df["engagement_rate"] = df["engagement_rate"].clip(upper=cap_value)
    print(f"  Capped engagement_rate at p99 = {cap_value:.4f} "
          f"({n_above:,} rows clipped).")

    # --- Build features -----------------------------------------------------
    print("Building features ...")
    g1 = _build_group1(df)
    g2 = _build_group2(df)
    g3 = _build_group3(df)
    g4 = _build_group4(df)

    df_ml = pd.concat(
        [df[["post_id"]].reset_index(drop=True),
         g1.reset_index(drop=True),
         g2.reset_index(drop=True),
         g3.reset_index(drop=True),
         g4.reset_index(drop=True),
         df[["engagement_rate"]].reset_index(drop=True)],
        axis=1,
    )
    print(f"  df_ml shape: {df_ml.shape}  "
          f"(post_id + 26 features + engagement_rate)")

    # --- Validation ---------------------------------------------------------
    print()
    print("Feature group counts:")
    for label, names in FEATURE_GROUPS.items():
        present = [n for n in names if n in df_ml.columns]
        missing = [n for n in names if n not in df_ml.columns]
        print(f"  {label:<32}  {len(present)}  "
              + (f"MISSING: {missing}" if missing else ""))
    print()

    print("NaN counts (features only — target excluded):")
    feature_names = [n for grp in FEATURE_GROUPS.values() for n in grp]
    nan_report = []
    for name in feature_names:
        n_null = int(df_ml[name].isna().sum())
        if n_null > 0:
            nan_report.append((name, n_null))
    if nan_report:
        for name, n_null in nan_report:
            print(f"  {name:<24} {n_null:>5}  "
                  f"({n_null / len(df_ml) * 100:.1f}%)")
        print("  (NaN allowed per project policy — "
              "no imputation; tree models handle it.)")
    else:
        print("  (no NaN in any feature)")
    print()

    # --- Spearman correlations ---------------------------------------------
    print("Computing Spearman correlations vs engagement_rate ...")
    feat_df = df_ml[feature_names]
    spearman_rows = _spearman_with_target(feat_df, df_ml["engagement_rate"])

    # --- Persist ------------------------------------------------------------
    OUT_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    df_ml.to_parquet(OUT_PARQUET, index=False)
    print(f"  wrote {OUT_PARQUET}  "
          f"({OUT_PARQUET.stat().st_size / 1024:.1f} KB)")

    summary_text = _format_summary(
        df_ml=df_ml,
        target_name="engagement_rate",
        cap_value=cap_value,
        n_in=n_in,
        n_dropped=n_drop,
        spearman_rows=spearman_rows,
    )
    OUT_SUMMARY.write_text(summary_text, encoding="utf-8")
    print(f"  wrote {OUT_SUMMARY}  "
          f"({OUT_SUMMARY.stat().st_size / 1024:.1f} KB)")

    print()
    print(summary_text, end="")


if __name__ == "__main__":
    main()
