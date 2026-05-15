"""compute_facts.py — Deterministic facts layer for Step 4.

WHY THIS EXISTS
---------------
Step 4 used to ask an LLM (llama3.1) to compute numbers from a RAG context.
That produced unreliable output: numbers recycled across modules, volume
% confused with engagement %, quintile-deltas confused with engagement,
giveaway posts recommended as patterns, single viral 164% posts treated
as representative.

This file moves every number into deterministic Python — pandas over the
cleaned parquet + the SHAP cache + BERTopic topics. The LLM is no longer
in the calculation path; it is only used downstream to rephrase this
facts.json into French dashboard prose.

CRITICAL CONVENTIONS
--------------------
Every numeric field is typed by its suffix so it can never be confused
downstream:

  _er     engagement rate (a performance metric).  Stored as percent
          (the Apify scraper computes (likes+comments)/followers*100, so
          0.08 means 0.08%). After outlier filtering this should always
          satisfy 0 <= _er <= 20 — if it doesn't, a denominator bug
          re-entered the pipeline.

  _share  share / proportion of volume (e.g. % of posts in a theme).
          Stored as percent.  0 <= _share <= 100.

  _delta  difference between groups (e.g. engagement when CTA present vs
          absent).  In percentage points (pp).  Can be negative.

  _ratio  multiplier (e.g. reel ER / photo ER = 1.8).  Dimensionless.

  _count, _n   raw count / sample size.  Integer.

OUTLIER POLICY
--------------
BEFORE any aggregation, we drop:
  1. posts whose engagement_rate exceeds the industry's 95th percentile
  2. posts whose hashtags match  giveaway|jeuconcours|concours|giveaways
This kills the 164% biodermatunisie viral post and every #giveaway
recommendation at the source — they never reach any computation.

CONFIDENCE
----------
Every block reports a `confidence` field:
  high    n >= 30
  medium  n >= 10
  low     n  < 10
The block is never dropped on low confidence — the dashboard/LLM layer
mentions the "donnée insuffisante" caveat instead.

MODULES (mirroring the 10 dashboard sections)
---------------------------------------------
  content_strategy        — caption-length, sentiment, binary-signal lift
  optimal_timing          — best/worst days, best hours, weekend lift, cadence
  visual_strategy         — format perf, reel_vs_photo_ratio, carousel slides
  content_themes          — per-topic theme_er  AND  theme_share (separated)
  hashtag_strategy        — top hashtags by median ER, count-bucket perf
  brand_differentiation   — top/bottom brands, under-served themes
  engagement_tactics      — CTA / question / promo lift, comment drivers
  current_trends          — recent-vs-prior theme share shifts
  performance_predictors  — XGB V5c SHAP top 5 features + direction
  calendar_30d            — 30 deterministic posts, populated from above

SCHEMA SUMMARY (per industry)
-----------------------------
{
  "industry": "beauty",
  "version": "facts_v1",
  "generated_at": "ISO-8601",
  "n_posts_raw": 816,
  "n_posts_kept": 720,
  "filter_summary": {"dropped_above_p95_er": 41, "dropped_giveaway": 35, ...},
  "modules": {
      "optimal_timing":         { ... },
      "content_strategy":       { ... },
      "visual_strategy":        { ... },
      "content_themes":         { ... },
      "hashtag_strategy":       { ... },
      "brand_differentiation":  { ... },
      "engagement_tactics":     { ... },
      "current_trends":         { ... },
      "performance_predictors": { ... },
  },
  "calendar_30d": [ {day, dow, format, theme, hashtags, est_median_er}, ... ]
}

USAGE
-----
  python scripts/compute_facts.py                 # all 5 industries
  python scripts/compute_facts.py --industry beauty
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import yaml

sys.stdout.reconfigure(encoding="utf-8")

# ─────────────────────────────────────────────────────────────────────────
# Paths & constants
# ─────────────────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
MASTER_PATH = DATA / "df_master_masked_with_topics.parquet"
V5C_PATH    = DATA / "df_ml_dataset_v5c.parquet"
SHAP_CACHE  = DATA / "_shap_values_cached_xgb_v5c.npz"
TOPICS_YAML = DATA / "topics_v3_llm_named.yaml"
OUT_DIR     = DATA / "step4f_v6" / "facts"

INDUSTRIES = ["beauty", "fashion", "hotels", "patisserie", "restaurants"]

DAY_FR = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]

GIVEAWAY_RE = re.compile(r"giveaway|jeuconcours|concours|giveaways|tirage", re.IGNORECASE)

# Bounds enforced by validators (see _validate_facts).
ER_MAX = 20.0      # any post-filter aggregate _er above this means a bug
SHARE_MAX = 100.0

# Confidence thresholds (sample size n)
N_HIGH = 30
N_MEDIUM = 10


def _confidence_for_n(n: int) -> str:
    if n >= N_HIGH:   return "high"
    if n >= N_MEDIUM: return "medium"
    return "low"


# ─────────────────────────────────────────────────────────────────────────
# Validators
# ─────────────────────────────────────────────────────────────────────────

EXPECTED_MODULES = {
    "content_strategy", "optimal_timing", "visual_strategy", "content_themes",
    "hashtag_strategy", "brand_differentiation", "engagement_tactics",
    "current_trends", "performance_predictors",
}


def _classify_field(k: str) -> str:
    """Classify a field name by its typed suffix. Returns '' if untyped."""
    if k in ("n", "count"):
        return "_n"
    for tag in ("_er", "_share", "_delta", "_ratio"):
        if k.endswith(tag):
            return tag
    if k.endswith("_n") or k.endswith("_count"):
        return "_n"
    return ""


def _walk_numeric_fields(obj: Any, path: str = "") -> List[Tuple[str, str, float]]:
    """Yield (field_path, suffix_type, value) for every typed numeric field.
    suffix_type is _er / _share / _delta / _ratio / _n or '' for untyped."""
    out: List[Tuple[str, str, float]] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            sub_path = f"{path}.{k}" if path else k
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                out.append((sub_path, _classify_field(k), float(v)))
            else:
                out.extend(_walk_numeric_fields(v, sub_path))
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            out.extend(_walk_numeric_fields(item, f"{path}[{i}]"))
    return out


def _validate_facts(facts: Dict[str, Any]) -> None:
    """Hard validators — raise AssertionError on contract violation."""
    # 1. Schema shape
    assert isinstance(facts, dict), "facts must be a dict"
    assert facts.get("version") == "facts_v1", "facts version mismatch"
    assert facts.get("industry") in INDUSTRIES, "facts.industry invalid"

    modules = facts.get("modules") or {}
    missing = EXPECTED_MODULES - set(modules.keys())
    assert not missing, f"facts.modules missing keys: {missing}"

    assert isinstance(facts.get("calendar_30d"), list), "calendar_30d must be a list"
    assert len(facts["calendar_30d"]) == 30, "calendar_30d must have exactly 30 entries"

    # 2. Typed-suffix bounds
    for path, suffix, value in _walk_numeric_fields(facts):
        if suffix == "_er":
            assert 0 <= value <= ER_MAX, (
                f"{path}={value} violates 0 <= _er <= {ER_MAX} "
                "(possible denominator / unit bug)"
            )
        elif suffix == "_share":
            assert 0 <= value <= SHARE_MAX, (
                f"{path}={value} violates 0 <= _share <= {SHARE_MAX}"
            )
        elif suffix in ("_n", "_count"):
            assert value >= 0 and float(value).is_integer(), (
                f"{path}={value} must be a non-negative integer"
            )

    # 3. Industry-purity of every theme reference (Step A.6).
    #    Every theme surfaced to the dashboard must be own-industry or the
    #    neutral Outliers cluster (topic_id == -1). This guarantees a
    #    patisserie facts file can never cite "Hotel Reviews Tunisia".
    ct = modules.get("content_themes", {})
    allowed_topic_ids = {-1, None}
    for key in ("top_5_by_share", "top_5_by_er"):
        for t in ct.get(key, []):
            assert t.get("is_own_industry") is True or t.get("topic_id") == -1, (
                f"content_themes.{key} contains cross-industry topic "
                f"{t.get('topic_id')} ({t.get('topic_name')!r}) — "
                "industry filter regressed"
            )
            allowed_topic_ids.add(t.get("topic_id"))

    for t in modules.get("brand_differentiation", {}).get("underserved_themes", []):
        assert t.get("is_own_industry") is True or t.get("topic_id") == -1, (
            f"brand_differentiation.underserved_themes contains cross-industry "
            f"topic {t.get('topic_id')} ({t.get('topic_name')!r})"
        )

    trends = modules.get("current_trends", {})
    for key in ("emerging_themes", "fading_themes"):
        for t in trends.get(key, []):
            assert t.get("is_own_industry") is True or t.get("topic_id") == -1, (
                f"current_trends.{key} contains cross-industry topic "
                f"{t.get('topic_id')} ({t.get('topic_name')!r})"
            )

    for entry in facts.get("calendar_30d", []):
        tid = entry.get("theme_id")
        assert tid in allowed_topic_ids, (
            f"calendar_30d day {entry.get('day_index')} references "
            f"cross-industry / unknown theme_id={tid} "
            f"({entry.get('theme_name')!r})"
        )

    # 4. JSON-serialisable round-trip
    s = json.dumps(facts, ensure_ascii=False)
    assert json.loads(s) == facts, "facts not JSON round-trippable"


# ─────────────────────────────────────────────────────────────────────────
# Data loading & outlier filtering
# ─────────────────────────────────────────────────────────────────────────

def _load_data() -> Dict[str, Any]:
    master = pd.read_parquet(MASTER_PATH)
    v5c    = pd.read_parquet(V5C_PATH)
    master["post_id"] = master["post_id"].astype(str)
    v5c["post_id"]    = v5c["post_id"].astype(str)

    # Same merge strategy as the V6 doc builder
    dup_cols = [
        "industry_simple", "content_type", "caption_lang", "topic_id",
        "engagement_rate", "followers", "brand_avg_likes",
        "brand_engagement_rate", "slide_count", "views", "has_caption",
    ]
    df = master.merge(
        v5c.drop(columns=dup_cols, errors="ignore"),
        on="post_id", how="left",
    )

    with open(TOPICS_YAML, "r", encoding="utf-8") as f:
        topics = yaml.safe_load(f)["topics"]

    z = np.load(SHAP_CACHE, allow_pickle=False)
    shap_features = [str(c) for c in z["columns"]]
    shap_abs = np.abs(z["shap_values"]).mean(axis=0)
    shap_mean = z["shap_values"].mean(axis=0)
    shap_ranks = sorted(
        zip(shap_features, shap_abs.tolist(), shap_mean.tolist()),
        key=lambda r: -r[1],
    )

    topic_industry_map = _build_topic_industry_map(df)

    return {
        "df": df,
        "topics": topics,
        "shap_ranks": shap_ranks,
        "topic_industry_map": topic_industry_map,
    }


def _has_giveaway_hashtag(tags) -> bool:
    if tags is None:
        return False
    if isinstance(tags, float) and np.isnan(tags):
        return False
    try:
        for t in tags:
            if isinstance(t, str) and GIVEAWAY_RE.search(t):
                return True
    except TypeError:
        return False
    return False


def _filter_outliers(df_ind: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, int]]:
    """Drop posts above the industry's p95 engagement_rate and posts with
    giveaway-related hashtags. Reports drop counts."""
    n_raw = len(df_ind)
    p95 = float(df_ind["engagement_rate"].quantile(0.95))

    mask_p95 = df_ind["engagement_rate"] <= p95
    mask_no_giveaway = ~df_ind["hashtags"].apply(_has_giveaway_hashtag)

    kept = df_ind[mask_p95 & mask_no_giveaway].copy()
    summary = {
        "n_raw":                   int(n_raw),
        "p95_cutoff_value":        round(p95, 4),   # in ER units, but kept untyped (metadata, not a primary stat)
        "dropped_above_p95_count": int((~mask_p95).sum()),
        "dropped_giveaway_count":  int((mask_p95 & ~mask_no_giveaway).sum()),
        "n_kept":                  int(len(kept)),
    }
    return kept, summary


# ─────────────────────────────────────────────────────────────────────────
# Small helpers
# ─────────────────────────────────────────────────────────────────────────

def _r(x: Any, ndigits: int = 2) -> Optional[float]:
    """Round float-like to ndigits, return None for NaN/missing."""
    if x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    if np.isnan(f):
        return None
    return round(f, ndigits)


def _ts_tunis(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce", utc=True).dt.tz_convert("Africa/Tunis")


def _topic_name(topics: Dict, tid: int) -> str:
    return topics.get(int(tid), {}).get("name", f"Topic {tid}")


def _industry_majority_for_topic(df: pd.DataFrame, topic_id: int) -> str:
    """Industry holding the most posts of this topic across the whole corpus.

    BERTopic clusters are global (one model over all 5 industries), so a
    topic like "Hotel Reviews Tunisia" or "Ramadan Beauty Routine" can leak
    a handful of posts into patisserie. Theme rankings must not surface a
    topic that belongs to a *different* industry. The majority owner is the
    deterministic, defensible criterion for "whose topic is this".

    Returns "" if the topic has no posts (defensive; never expected)."""
    sub = df.loc[df["topic_id"] == topic_id, "industry_simple"].dropna()
    if sub.empty:
        return ""
    return str(sub.value_counts().idxmax())


def _build_topic_industry_map(df: pd.DataFrame) -> Dict[int, str]:
    """topic_id -> majority industry, computed once at load time and reused
    for every per-industry facts build (see _industry_majority_for_topic)."""
    return {
        int(t): _industry_majority_for_topic(df, int(t))
        for t in sorted(df["topic_id"].dropna().unique())
    }


def _binary_lift(g: pd.DataFrame, col: str) -> Optional[Dict[str, Any]]:
    """Compute median-ER lift for a 0/1 binary feature, robust to bool dtype
    and to NaN rows introduced by left-merging v5c onto master."""
    if col not in g.columns:
        return None
    flag = g[col].astype("Int64").astype("float").fillna(-1).astype(int)
    sub = g.assign(_flag=flag).query("_flag in (0, 1)")
    vals = sub.groupby("_flag")["engagement_rate"].agg(["median", "count"])
    if 0 not in vals.index or 1 not in vals.index:
        return None
    on  = float(vals.loc[1, "median"])
    off = float(vals.loc[0, "median"])
    return {
        "on_median_er":  _r(on),
        "off_median_er": _r(off),
        "er_delta":      _r(on - off),
        "n_on":          int(vals.loc[1, "count"]),
        "n_off":         int(vals.loc[0, "count"]),
    }


# ─────────────────────────────────────────────────────────────────────────
# Module computations
# ─────────────────────────────────────────────────────────────────────────

def _mod_optimal_timing(g: pd.DataFrame) -> Dict[str, Any]:
    ts = _ts_tunis(g["published_at"])
    g = g.assign(_dow=ts.dt.dayofweek, _hour=ts.dt.hour)

    # Best / worst days (median over the whole industry, no n-floor since
    # we expect ≥50 posts per dow on any reasonable bucket)
    dow_eng = (g.groupby("_dow")["engagement_rate"]
                 .agg(["median", "mean", "count"])
                 .reset_index())
    dow_eng = dow_eng.sort_values("median", ascending=False)

    def _row_day(r: pd.Series) -> Dict[str, Any]:
        dow = int(r["_dow"])
        return {
            "day": DAY_FR[dow] if 0 <= dow < 7 else f"day_{dow}",
            "dow": dow,
            "median_er": _r(r["median"]),
            "mean_er": _r(r["mean"]),
            "n": int(r["count"]),
        }

    best_days = [_row_day(r) for _, r in dow_eng.head(3).iterrows()]
    worst_days = [_row_day(r) for _, r in dow_eng.tail(2).iterrows()]

    # Best hours, n >= 5
    hr = g.groupby("_hour")["engagement_rate"].agg(["median", "mean", "count"]).reset_index()
    hr = hr[hr["count"] >= 5].sort_values("median", ascending=False)
    best_hours = [
        {
            "hour_tunis": int(r["_hour"]),
            "median_er": _r(r["median"]),
            "mean_er": _r(r["mean"]),
            "n": int(r["count"]),
        }
        for _, r in hr.head(3).iterrows()
    ]

    # Weekend vs weekday lift (as a _delta in pp). is_weekend is bool in v5c.
    wk_lift = _binary_lift(g, "is_weekend")
    weekend_delta = wk_lift["er_delta"] if wk_lift else None

    # Posting frequency per active week per brand
    iso = ts.dt.isocalendar()
    weeks = iso.week + ts.dt.year * 100
    ppw = (g.assign(_wk=weeks)
            .groupby(["username", "_wk"]).size()
            .reset_index(name="n")
            .groupby("username")["n"].mean())

    return {
        "confidence": _confidence_for_n(int(len(g))),
        "n": int(len(g)),
        "best_days": best_days,
        "worst_days": worst_days,
        "best_hours": best_hours,
        "weekend_vs_weekday_er_delta": weekend_delta,
        "posting_frequency": {
            "median_posts_per_active_week": _r(ppw.median()),
            "mean_posts_per_active_week":   _r(ppw.mean()),
            "max_posts_per_active_week":    _r(ppw.max()),
            "n_brands":                     int(len(ppw)),
        },
    }


def _mod_content_strategy(g: pd.DataFrame, topics: Dict) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "confidence": _confidence_for_n(int(len(g))),
        "n": int(len(g)),
    }

    # Caption length quartiles vs median ER
    if "caption_length" in g.columns:
        try:
            q = pd.qcut(g["caption_length"], q=4,
                        labels=["q1_shortest", "q2", "q3", "q4_longest"],
                        duplicates="drop")
            cl = g.groupby(q, observed=True)["engagement_rate"].agg(["median", "mean", "count"])
            out["caption_length_quartiles"] = [
                {
                    "bucket": str(b),
                    "median_er": _r(row["median"]),
                    "mean_er": _r(row["mean"]),
                    "n": int(row["count"]),
                }
                for b, row in cl.iterrows()
            ]
        except (ValueError, KeyError):
            out["caption_length_quartiles"] = None

    # Sentiment summary
    if "caption_sentiment" in g.columns:
        s = g["caption_sentiment"].dropna()
        if len(s) > 0:
            out["sentiment"] = {
                "median": _r(s.median(), 3),
                "mean":   _r(s.mean(), 3),
                "positive_share": _r((s > 0.3).mean() * 100),
                "negative_share": _r((s < -0.1).mean() * 100),
                "n": int(len(s)),
            }

    # Binary-signal lifts: median ER when flag=1 minus median ER when flag=0
    lifts: List[Dict[str, Any]] = []
    for col in ["has_cta", "has_question", "has_promo_word", "has_emoji",
                "is_weekend", "is_evening"]:
        lift = _binary_lift(g, col)
        if lift is None:
            continue
        lifts.append({"signal": col, **lift})
    out["binary_signal_lifts"] = lifts

    return out


def _mod_visual_strategy(g: pd.DataFrame) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "confidence": _confidence_for_n(int(len(g))),
        "n": int(len(g)),
    }

    # Format performance (median ER) ranked
    by_ct = (g.groupby("content_type")["engagement_rate"]
              .agg(["median", "mean", "count"])
              .sort_values("median", ascending=False)
              .reset_index())
    out["format_performance"] = [
        {
            "content_type": str(r["content_type"]),
            "median_er": _r(r["median"]),
            "mean_er": _r(r["mean"]),
            "n": int(r["count"]),
        }
        for _, r in by_ct.iterrows()
    ]

    # Reel-vs-photo ratio (defined as median ER reel / median ER photo, when both present)
    ct_med = g.groupby("content_type")["engagement_rate"].median()
    reel_vs_photo_ratio = None
    if "reel" in ct_med.index and "photo" in ct_med.index and ct_med.loc["photo"] > 0:
        reel_vs_photo_ratio = _r(ct_med.loc["reel"] / ct_med.loc["photo"])
    out["reel_vs_photo_ratio"] = reel_vs_photo_ratio

    # Optimal carousel slide count (median ER, n>=3)
    car = g[g["content_type"] == "carousel"]
    if "slide_count" in g.columns and len(car) > 0:
        sc = car.groupby("slide_count")["engagement_rate"].agg(["median", "mean", "count"])
        sc = sc[sc["count"] >= 3].sort_values("median", ascending=False)
        out["carousel_slide_count_top"] = [
            {
                "slide_count": int(sc_n),
                "median_er": _r(row["median"]),
                "mean_er": _r(row["mean"]),
                "n": int(row["count"]),
            }
            for sc_n, row in sc.head(5).iterrows()
        ]
    else:
        out["carousel_slide_count_top"] = []

    # CLIP top differentiators between top-quintile and bottom-quintile engagement
    clip_cols = [c for c in g.columns if c.startswith("clip_pc")]
    diff_block: List[Dict[str, Any]] = []
    if clip_cols:
        q_hi = g["engagement_rate"].quantile(0.80)
        q_lo = g["engagement_rate"].quantile(0.20)
        hi = g[g["engagement_rate"] >= q_hi]
        lo = g[g["engagement_rate"] <= q_lo]
        if len(hi) > 0 and len(lo) > 0:
            shifts = (hi[clip_cols].mean() - lo[clip_cols].mean())
            for col, val in shifts.reindex(shifts.abs().sort_values(ascending=False).index).head(5).items():
                diff_block.append({
                    "feature": col,
                    "shift_abs": _r(abs(val), 3),
                    "direction": "+" if val > 0 else "-",
                })
    out["clip_top_differentiators"] = diff_block

    return out


def _industry_clean_theme(t: Dict[str, Any]) -> bool:
    """A theme is allowed in industry-facing rankings iff it belongs to the
    current industry OR it is the neutral Outliers cluster (topic_id == -1).
    -1 is BERTopic's mixed-content bucket — it has no single owner and is
    treated as industry-neutral by design."""
    return bool(t.get("is_own_industry")) or t.get("topic_id") == -1


def _mod_content_themes(g: pd.DataFrame, topics: Dict, industry: str,
                        topic_industry_map: Dict[int, str]) -> Dict[str, Any]:
    """Per-topic theme_er (performance) and theme_share (volume) — KEPT SEPARATE.
    Performance ranking applies n>=5 to avoid surfacing single-post outliers.

    Industry-aware filtering (Step A): BERTopic is a single global model, so a
    topic that majority-belongs to another industry can have a few posts here.
    Such cross-industry topics are flagged (is_own_industry=False) and excluded
    from both rankings so patisserie never recommends "Hotel Reviews Tunisia".
    topic_id == -1 (Outliers) is industry-neutral and always kept."""
    total = int(len(g))
    THEME_N_FLOOR = 5  # minimum posts for a theme to qualify for the by_er ranking
    rows = (g.groupby("topic_id")["engagement_rate"]
              .agg(["median", "mean", "count"])
              .reset_index())

    themes: List[Dict[str, Any]] = []
    for _, r in rows.iterrows():
        tid = int(r["topic_id"])
        n_in_theme = int(r["count"])
        themes.append({
            "topic_id":        tid,
            "topic_name":      _topic_name(topics, tid),
            "theme_er":        _r(r["median"]),       # performance — engagement rate
            "theme_er_mean":   _r(r["mean"]),
            "theme_share":     _r(100 * n_in_theme / total) if total else 0,
            "n":               n_in_theme,
            "confidence":      _confidence_for_n(n_in_theme),
            "is_own_industry": bool(topic_industry_map.get(tid) == industry),
        })

    eligible = [t for t in themes if _industry_clean_theme(t)]
    n_excluded = sum(1 for t in themes if not _industry_clean_theme(t))

    by_share = sorted(eligible, key=lambda t: -(t["theme_share"] or 0))[:5]
    # by_er only includes themes with sample size >= THEME_N_FLOOR
    by_er = sorted([t for t in eligible if t["n"] >= THEME_N_FLOOR],
                   key=lambda t: -(t["theme_er"] or 0))[:5]
    return {
        "confidence":     _confidence_for_n(total),
        "n":              total,
        "n_floor_for_er": THEME_N_FLOOR,
        "cross_industry_topics_excluded": int(n_excluded),
        "top_5_by_share": by_share,
        "top_5_by_er":    by_er,
    }


def _mod_hashtag_strategy(g: pd.DataFrame) -> Dict[str, Any]:
    rows: List[Tuple[str, float]] = []
    for _, r in g.iterrows():
        tags = r.get("hashtags")
        if tags is None or (isinstance(tags, float) and np.isnan(tags)):
            continue
        e = float(r["engagement_rate"])
        try:
            for t in tags:
                if isinstance(t, str) and 2 < len(t) < 30:
                    rows.append((t.lower(), e))
        except TypeError:
            continue

    out: Dict[str, Any] = {
        "confidence": _confidence_for_n(int(len(g))),
        "n_posts": int(len(g)),
    }

    if rows:
        df_h = pd.DataFrame(rows, columns=["tag", "eng"])
        agg = df_h.groupby("tag")["eng"].agg(["median", "mean", "count"])
        agg = agg[agg["count"] >= 5].sort_values("median", ascending=False)
        out["top_10_hashtags"] = [
            {
                "tag":       f"#{tag}",
                "median_er": _r(row["median"]),
                "mean_er":   _r(row["mean"]),
                "n":         int(row["count"]),
            }
            for tag, row in agg.head(10).iterrows()
        ]
    else:
        out["top_10_hashtags"] = []

    # Hashtag-count bucket performance
    if "hashtags_count" in g.columns:
        bins = pd.cut(g["hashtags_count"], bins=[-0.5, 0, 3, 6, 10, 30],
                      labels=["0", "1-3", "4-6", "7-10", "11+"])
        hc = g.groupby(bins, observed=True)["engagement_rate"].agg(["median", "mean", "count"])
        out["count_buckets"] = [
            {
                "bucket":    str(b),
                "median_er": _r(row["median"]),
                "mean_er":   _r(row["mean"]),
                "n":         int(row["count"]),
            }
            for b, row in hc.iterrows()
        ]
    else:
        out["count_buckets"] = []
    return out


def _mod_brand_differentiation(g: pd.DataFrame, themes_block: Dict[str, Any]) -> Dict[str, Any]:
    by_brand = (g.groupby("username")["engagement_rate"]
                 .agg(["median", "mean", "count"])
                 .reset_index())
    by_brand = by_brand[by_brand["count"] >= 5]

    top_brands = by_brand.sort_values("median", ascending=False).head(3)
    bottom_brands = by_brand.sort_values("median", ascending=True).head(3)

    industry_median_er = float(g["engagement_rate"].median())

    # Under-served themes: low share but ER above industry median.
    # themes_block.top_5_* is ALREADY industry-filtered by _mod_content_themes,
    # so no extra cross-industry guard is needed here (Step A.3).
    underserved = []
    for t in themes_block.get("top_5_by_er", []) + themes_block.get("top_5_by_share", []):
        if t in underserved:
            continue
        share = t.get("theme_share") or 0
        er    = t.get("theme_er") or 0
        if share < 10 and er > industry_median_er:
            underserved.append(t)
    # Dedupe by topic_id
    seen = set()
    dedup = []
    for t in underserved:
        if t["topic_id"] in seen:
            continue
        seen.add(t["topic_id"])
        dedup.append({
            "topic_id":        t["topic_id"],
            "topic_name":      t["topic_name"],
            "theme_er":        t["theme_er"],
            "theme_share":     t["theme_share"],
            "n":               t["n"],
            "is_own_industry": bool(t.get("is_own_industry")),
        })

    return {
        "confidence": _confidence_for_n(int(len(g))),
        "n_brands_with_5plus_posts": int(len(by_brand)),
        "industry_median_er": _r(industry_median_er),
        "top_brands_by_median_er": [
            {
                "username": r["username"],
                "median_er": _r(r["median"]),
                "mean_er":   _r(r["mean"]),
                "n":         int(r["count"]),
            }
            for _, r in top_brands.iterrows()
        ],
        "bottom_brands_by_median_er": [
            {
                "username": r["username"],
                "median_er": _r(r["median"]),
                "mean_er":   _r(r["mean"]),
                "n":         int(r["count"]),
            }
            for _, r in bottom_brands.iterrows()
        ],
        "underserved_themes": dedup,
    }


def _mod_engagement_tactics(g: pd.DataFrame) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "confidence": _confidence_for_n(int(len(g))),
        "n": int(len(g)),
    }

    # CTA / question / promo lifts (also referenced in content_strategy).
    lifts: List[Dict[str, Any]] = []
    for col, label in [("has_cta", "cta"), ("has_question", "question"), ("has_promo_word", "promo_word")]:
        lift = _binary_lift(g, col)
        if lift is None:
            continue
        lifts.append({"tactic": label, **lift})
    out["tactic_lifts"] = lifts

    # Top comment-driving posts (comments/followers ratio)
    if "comments" in g.columns and "followers" in g.columns:
        g2 = g.copy()
        g2["_cmt_ratio"] = g2["comments"] / g2["followers"].clip(lower=1)
        top = g2.sort_values("_cmt_ratio", ascending=False).head(5)
        out["top_comment_drivers"] = [
            {
                "username":     r["username"],
                "content_type": str(r.get("content_type", "unknown")),
                "comments":     int(r.get("comments", 0)),
                "followers":    int(r.get("followers", 0)),
                "comments_per_1k_followers_ratio": _r(r["_cmt_ratio"] * 1000, 3),
                "post_id":      str(r.get("post_id", "")),
            }
            for _, r in top.iterrows()
        ]
    else:
        out["top_comment_drivers"] = []
    return out


def _mod_current_trends(g: pd.DataFrame, topics: Dict, industry: str,
                        topic_industry_map: Dict[int, str]) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "confidence": _confidence_for_n(int(len(g))),
        "n": int(len(g)),
    }

    # Temporal theme drift: recent 90 days vs prior 90 days
    if "published_at" in g.columns and len(g) > 0:
        ts = pd.to_datetime(g["published_at"], errors="coerce", utc=True)
        max_t = ts.max()
        if pd.notna(max_t):
            recent_cutoff = max_t - pd.Timedelta(days=90)
            prior_cutoff = max_t - pd.Timedelta(days=180)
            recent = g[(ts > recent_cutoff)]
            prior  = g[(ts > prior_cutoff) & (ts <= recent_cutoff)]

            recent_share = (recent["topic_id"].value_counts(normalize=True) * 100) if len(recent) else pd.Series(dtype=float)
            prior_share  = (prior["topic_id"].value_counts(normalize=True)  * 100) if len(prior)  else pd.Series(dtype=float)

            # _delta on share = percentage-points shift in volume share
            all_tids = sorted(set(recent_share.index) | set(prior_share.index))
            drifts = []
            for tid in all_tids:
                r_s = float(recent_share.get(int(tid), 0))
                p_s = float(prior_share.get(int(tid), 0))
                drifts.append({
                    "topic_id":         int(tid),
                    "topic_name":       _topic_name(topics, int(tid)),
                    "recent_share":     _r(r_s),
                    "prior_share":      _r(p_s),
                    "share_delta_pp":   _r(r_s - p_s),
                    "n_recent":         int((recent["topic_id"] == tid).sum()),
                    "is_own_industry":  bool(topic_industry_map.get(int(tid)) == industry),
                })
            # Same industry-purity rule as content_themes (Step A extension):
            # a patisserie trend report must not flag "Ramadan Beauty Routine"
            # as emerging. Keep own-industry topics or the neutral Outliers (-1).
            clean_drifts = [d for d in drifts if _industry_clean_theme(d)]
            out["cross_industry_topics_excluded"] = int(len(drifts) - len(clean_drifts))
            # Emerging = positive delta. Fading = negative.
            emerging = sorted([d for d in clean_drifts if (d["share_delta_pp"] or 0) > 0],
                              key=lambda d: -(d["share_delta_pp"] or 0))[:5]
            fading   = sorted([d for d in clean_drifts if (d["share_delta_pp"] or 0) < 0],
                              key=lambda d:  (d["share_delta_pp"] or 0))[:5]
            out["emerging_themes"] = emerging
            out["fading_themes"]   = fading
            out["window_recent_n"] = int(len(recent))
            out["window_prior_n"]  = int(len(prior))

    # Seasonal flags representation
    if "is_ramadan" in g.columns:
        ram = g[g["is_ramadan"] == 1]
        if len(ram) > 0:
            out["ramadan"] = {
                "n":         int(len(ram)),
                "share":     _r(100 * len(ram) / len(g)),
                "median_er": _r(ram["engagement_rate"].median()),
            }
    return out


def _shap_category(name: str) -> str:
    if name.startswith("doc_pc"):
        return "mpnet_caption_semantics"
    if name.startswith("clip_pc") or name.startswith("clip_n_assets"):
        return "clip_visual"
    if name.startswith("topic_"):
        return "bertopic_topic"
    if name.startswith(("industry_simple_", "content_type_", "caption_lang_")):
        return "categorical_ohe"
    return "tabular"


def _mod_performance_predictors(shap_ranks: List[Tuple[str, float, float]]) -> Dict[str, Any]:
    """SHAP block (XGB V5c) — global, not industry-specific (cache is 200-row test sample)."""
    top5 = []
    for feat, mabs, mean in shap_ranks[:5]:
        top5.append({
            "feature":       feat,
            "mean_abs_shap": _r(mabs, 4),
            "direction":     "+" if mean > 0 else "-",
            "category":      _shap_category(feat),
        })
    return {
        "confidence": "high",      # 200-row test sample, model R² stable
        "n_test_sample": 200,
        "model":       "XGB V5c (interpretive proxy for V6 stacking)",
        "model_r2_log": 0.4587,
        "model_rho":   0.6686,
        "top_5_features": top5,
    }


# ─────────────────────────────────────────────────────────────────────────
# 30-day calendar (STEP D)
# ─────────────────────────────────────────────────────────────────────────

def _build_calendar_30d(modules: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Fill a 30-day calendar deterministically from facts.json's other
    modules. Rotates the top formats, themes and hashtags. NEVER calls
    an LLM. Returns exactly 30 entries."""

    timing = modules.get("optimal_timing", {})
    visual = modules.get("visual_strategy", {})
    themes_block = modules.get("content_themes", {})
    hashtags_block = modules.get("hashtag_strategy", {})

    # Best day pool — fall back to all 7 if missing
    best_days = timing.get("best_days") or []
    best_day_dows = [d.get("dow") for d in best_days if d.get("dow") is not None]
    if not best_day_dows:
        best_day_dows = list(range(7))

    # Format rotation — sort by median_er, fall back to a generic mix
    fp = visual.get("format_performance") or []
    formats = [f["content_type"] for f in fp] or ["photo", "reel", "carousel"]

    # Theme pool — interleave volume themes and performance themes so the
    # calendar covers both the audience expectation and the upside.
    themes_pool = []
    for src in (themes_block.get("top_5_by_share", []),
                themes_block.get("top_5_by_er",    [])):
        for t in src:
            if t and t.get("topic_name") not in [x.get("topic_name") for x in themes_pool]:
                themes_pool.append({"topic_id": t["topic_id"], "topic_name": t["topic_name"]})
    if not themes_pool:
        themes_pool = [{"topic_id": None, "topic_name": "generic"}]

    hashtags_pool = [h["tag"] for h in (hashtags_block.get("top_10_hashtags") or [])][:10]
    if not hashtags_pool:
        hashtags_pool = []  # the rephraser will warn "donnée insuffisante"

    calendar: List[Dict[str, Any]] = []
    start_date = datetime.now(timezone.utc).date()
    for i in range(30):
        # Pick a best-day-of-week first, otherwise fall through Monday → Sunday
        target_dow = best_day_dows[i % len(best_day_dows)]
        # Step the calendar one day at a time (so the dashboard sees real consecutive dates),
        # but mark each entry's posting recommendation by target_dow.
        day_date = pd.Timestamp(start_date) + pd.Timedelta(days=i)
        fmt = formats[i % len(formats)]
        theme = themes_pool[i % len(themes_pool)]
        # 3 hashtags per day, rotating
        slice_start = (i * 3) % max(len(hashtags_pool), 1)
        if hashtags_pool:
            tags = [hashtags_pool[(slice_start + j) % len(hashtags_pool)] for j in range(min(3, len(hashtags_pool)))]
        else:
            tags = []
        calendar.append({
            "day_index":          i + 1,
            "date":               day_date.strftime("%Y-%m-%d"),
            "recommended_dow":    target_dow,
            "recommended_day":    DAY_FR[target_dow] if 0 <= target_dow < 7 else "?",
            "format":             fmt,
            "theme_id":           theme.get("topic_id"),
            "theme_name":         theme.get("topic_name"),
            "hashtags":           tags,
        })

    # Step A.4 guard: themes_pool is built from the already-filtered
    # top_5_by_share / top_5_by_er, so every calendar theme must be either
    # own-industry, the neutral Outliers cluster (-1), or the generic
    # fallback (topic_id None when no theme survived). Anything else means
    # the upstream filter regressed.
    allowed_ids = {-1, None}
    for src in (themes_block.get("top_5_by_share", []),
                themes_block.get("top_5_by_er", [])):
        for t in src:
            if _industry_clean_theme(t):
                allowed_ids.add(t.get("topic_id"))
    for entry in calendar:
        tid = entry["theme_id"]
        assert tid in allowed_ids, (
            f"calendar_30d day {entry['day_index']} references cross-industry "
            f"theme_id={tid} ({entry['theme_name']!r}); only own-industry "
            f"topics or topic_id == -1 are allowed"
        )
    return calendar


# ─────────────────────────────────────────────────────────────────────────
# Top-level builder
# ─────────────────────────────────────────────────────────────────────────

def compute_industry_facts(industry: str, loaded: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Build facts.json for one industry. Pure function — no LLM, no RAG,
    no Chroma. Raises AssertionError if the validators detect a bad value."""
    if loaded is None:
        loaded = _load_data()

    df    = loaded["df"]
    topics = loaded["topics"]
    shap_ranks = loaded["shap_ranks"]
    topic_industry_map = loaded["topic_industry_map"]

    df_ind_raw = df[df["industry_simple"] == industry].copy()
    g, filter_summary = _filter_outliers(df_ind_raw)

    # Modules (calendar depends on the others, so it goes last)
    themes_block = _mod_content_themes(g, topics, industry, topic_industry_map)
    modules: Dict[str, Any] = {
        "optimal_timing":         _mod_optimal_timing(g),
        "content_strategy":       _mod_content_strategy(g, topics),
        "visual_strategy":        _mod_visual_strategy(g),
        "content_themes":         themes_block,
        "hashtag_strategy":       _mod_hashtag_strategy(g),
        "brand_differentiation":  _mod_brand_differentiation(g, themes_block),
        "engagement_tactics":     _mod_engagement_tactics(g),
        "current_trends":         _mod_current_trends(g, topics, industry, topic_industry_map),
        "performance_predictors": _mod_performance_predictors(shap_ranks),
    }
    calendar = _build_calendar_30d(modules)

    facts = {
        "version":          "facts_v1",
        "industry":         industry,
        "generated_at":     time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
        "data_sources": {
            "master_parquet":   MASTER_PATH.name,
            "v5c_parquet":      V5C_PATH.name,
            "shap_cache":       SHAP_CACHE.name,
            "topics_yaml":      TOPICS_YAML.name,
        },
        "n_posts_raw":      filter_summary["n_raw"],
        "n_posts_kept":     filter_summary["n_kept"],
        "filter_summary":   filter_summary,
        "modules":          modules,
        "calendar_30d":     calendar,
    }

    _validate_facts(facts)
    return facts


def main() -> int:
    parser = argparse.ArgumentParser(description="Compute deterministic facts.json")
    parser.add_argument("--industry", choices=INDUSTRIES + ["all"], default="all")
    args = parser.parse_args()
    industries = INDUSTRIES if args.industry == "all" else [args.industry]

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 78)
    print("compute_facts.py — deterministic facts layer for Step 4")
    print("=" * 78)
    print("Loading data ...")
    loaded = _load_data()
    print(f"  master rows: {len(loaded['df'])}")
    print(f"  topics:      {len(loaded['topics'])}")
    print(f"  SHAP features: {len(loaded['shap_ranks'])}")
    print()

    for ind in industries:
        t0 = time.perf_counter()
        facts = compute_industry_facts(ind, loaded)
        out_file = OUT_DIR / f"facts_{ind}.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(facts, f, ensure_ascii=False, indent=2)
        dt = time.perf_counter() - t0
        n_raw  = facts["n_posts_raw"]
        n_kept = facts["n_posts_kept"]
        n_xind = facts["modules"]["content_themes"]["cross_industry_topics_excluded"]
        print(f"  {ind:<11} ok  {n_kept}/{n_raw} posts kept "
              f"(p95 cutoff {facts['filter_summary']['p95_cutoff_value']:.2f}%, "
              f"-{facts['filter_summary']['dropped_giveaway_count']} giveaways, "
              f"-{n_xind} cross-industry topics)  "
              f"({dt*1000:.0f} ms)  → {out_file.name}")

    print()
    print(f"output dir: {OUT_DIR.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
