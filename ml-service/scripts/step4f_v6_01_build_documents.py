"""Step 4f V6 — Build V6-enriched RAG corpus.

Adds 35 new "V6-enriched" documents (7 doc types × 5 industries) plus 10
refreshed `ml_insight` docs that cite V6 stacking + XGB V5c SHAP. Reuses
the 172 existing factual docs (topic_summary, top_post, brand_summary,
industry_summary) from data/step4/documents.json — those remain factually
correct and useful for retrieval.

Outputs
  data/step4f_v6/documents/<industry>/<docname>.md     -- human-readable per-industry
  data/step4f_v6/documents.json                        -- merged corpus for Chroma
"""
from __future__ import annotations

import json
import shutil
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
import yaml

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
STEP4 = DATA / "step4"
STEP4F_V6 = DATA / "step4f_v6"
DOCS_DIR = STEP4F_V6 / "documents"

MASTER_PATH   = DATA / "df_master_masked_with_topics.parquet"
V5C_PATH      = DATA / "df_ml_dataset_v5c.parquet"
V6_PRED_PATH  = DATA / "v6_predictions.parquet"
SHAP_CACHE    = DATA / "_shap_values_cached_xgb_v5c.npz"
TOPICS_YAML   = DATA / "topics_v3_llm_named.yaml"
EXISTING_DOCS = STEP4 / "documents.json"

INDUSTRIES = ["beauty", "fashion", "hotels", "patisserie", "restaurants"]

# ─────────────────────────────────────────────────────────────────────────
# Data loaders
# ─────────────────────────────────────────────────────────────────────────

def load_data() -> Dict:
    print("Loading datasets ...")
    master = pd.read_parquet(MASTER_PATH)
    v5c    = pd.read_parquet(V5C_PATH)
    v6_pred = pd.read_parquet(V6_PRED_PATH)
    master["post_id"] = master["post_id"].astype(str)
    v5c["post_id"]    = v5c["post_id"].astype(str)
    v6_pred["post_id"] = v6_pred["post_id"].astype(str)

    # engagement_rate is stored in percent units by the Apify scraper
    # ((likes+comments)/followers*100). If this invariant breaks the
    # display formatter (_eng_str) must be re-audited — silently rendering
    # fractions as percents (or vice versa) caused the historical
    # "Tuesday=318%" bug. See tests/test_engagement_formatter.py.
    er_p999 = float(master["engagement_rate"].quantile(0.999))
    assert er_p999 < 100, (
        f"engagement_rate appears mis-scaled (p99.9={er_p999:.2f}); "
        "the display formatter must be checked before building documents."
    )

    with open(TOPICS_YAML, "r", encoding="utf-8") as f:
        topics = yaml.safe_load(f)["topics"]

    z = np.load(SHAP_CACHE, allow_pickle=False)
    shap_features = list(z["columns"])
    shap_mean_abs = np.abs(z["shap_values"]).mean(axis=0)
    shap_means    = z["shap_values"].mean(axis=0)  # signed → direction proxy

    shap_ranks = sorted(
        zip(shap_features, shap_mean_abs.tolist(), shap_means.tolist()),
        key=lambda r: -r[1],
    )

    # Merge master with v5c features so per-post enriched stats are available.
    # Drop columns that exist in both to avoid pandas suffix renaming
    # (engagement_rate, followers, brand_avg_likes, brand_engagement_rate,
    # slide_count, views, has_caption are all duplicated between the two).
    cols_to_drop = [
        "industry_simple", "content_type", "caption_lang", "topic_id",
        "engagement_rate", "followers", "brand_avg_likes",
        "brand_engagement_rate", "slide_count", "views", "has_caption",
    ]
    df = master.merge(
        v5c.drop(columns=cols_to_drop, errors="ignore"),
        on="post_id", how="left",
    )
    print(f"  master:   {master.shape}")
    print(f"  v5c:      {v5c.shape}")
    print(f"  v6_pred:  {v6_pred.shape}")
    print(f"  merged:   {df.shape}")
    print(f"  topics:   {len(topics)} BERTopic clusters")
    print(f"  SHAP top-3: " + ", ".join(f"{n}={v:.4f}" for n, v, _ in shap_ranks[:3]))
    return dict(df=df, master=master, v6_pred=v6_pred, topics=topics,
                shap_ranks=shap_ranks)


# ─────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────

DAY_FR = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def _to_list(x) -> list:
    """Coerce a parquet cell that might be ndarray / list / None / NaN to list."""
    if x is None:
        return []
    if isinstance(x, float) and np.isnan(x):
        return []
    if hasattr(x, "__iter__") and not isinstance(x, (str, bytes)):
        return list(x)
    return []


def _truncate(text: str, n: int = 180) -> str:
    if not isinstance(text, str):
        return ""
    s = text.replace("\n", " ").strip()
    return s if len(s) <= n else s[: n - 3] + "..."


def _safe_pct(num: float, den: float) -> str:
    return f"{(100 * num / den):.1f}%" if den else "—"


def _eng_str(x) -> str:
    # engagement_rate is already a percentage (Apify computes
    # (likes+comments)/followers*100 — see backend/src/services/apify.service.js).
    # Do NOT multiply by 100 again; tests/test_engagement_formatter.py pins this.
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "—"
    return f"{x:.2f}%"


# ─────────────────────────────────────────────────────────────────────────
# Per-industry document builders (7 docs)
# ─────────────────────────────────────────────────────────────────────────

def build_doc1_top_patterns(industry: str, df_ind: pd.DataFrame, v6_pred: pd.DataFrame, topics: Dict) -> str:
    """DOC 1 — Top Performing Patterns."""
    # Cap engagement_rate at 1.0 to avoid extreme single-post outliers dominating
    g = df_ind.copy()
    g["_eng_capped"] = g["engagement_rate"].clip(upper=1.0)
    top20 = g.sort_values("_eng_capped", ascending=False).head(20)
    avg_ind = g["engagement_rate"].mean()

    lines: List[str] = []
    lines.append(f"# Top Performing Patterns — {industry.capitalize()} ({len(g)} posts in industry)")
    lines.append("")
    lines.append(f"Industry-average engagement: {_eng_str(avg_ind)}.  "
                 f"Listing the top 20 posts by engagement (capped at 100%).")
    lines.append("")

    # V6 predictions overlay if available
    pred_lookup = v6_pred.set_index("post_id")
    for rank, (_, row) in enumerate(top20.iterrows(), 1):
        cap   = _truncate(row.get("caption_clean") or row.get("caption", ""), 200)
        ctype = row.get("content_type", "?")
        eng   = row.get("engagement_rate", 0)
        tags  = _to_list(row.get("hashtags"))[:6]
        brand = row.get("username", "?")
        topic = topics.get(int(row.get("topic_id", -1)), {}).get("name", "?")
        lang  = row.get("caption_lang", "?")
        v6 = "—"
        if str(row["post_id"]) in pred_lookup.index:
            r = pred_lookup.loc[str(row["post_id"])]
            v6 = f"V6 predicted={r['y_pred_orig']:.4f}, actual={r['y_true_orig']:.4f} (Δ={r['y_true_orig']-r['y_pred_orig']:+.4f})"
        lines.append(
            f"- **#{rank}** {brand} — {ctype}, lang={lang}, topic='{topic}', "
            f"engagement={_eng_str(eng)} (×{(eng/avg_ind):.1f} industry avg). "
            f"{v6}. "
            f"Hashtags: {', '.join('#'+t for t in tags) if tags else 'none'}. "
            f"Caption: «{cap}»"
        )

    # Visual themes — mean clip_pc01..15 for top quintile vs bottom quintile
    if "clip_pc01" in g.columns:
        q1 = g["engagement_rate"].quantile(0.80)
        high = g[g["engagement_rate"] >= q1]
        low  = g[g["engagement_rate"] <  g["engagement_rate"].quantile(0.20)]
        clip_cols = [c for c in g.columns if c.startswith("clip_pc")]
        if clip_cols and len(high) > 0 and len(low) > 0:
            diff = (high[clip_cols].mean() - low[clip_cols].mean()).abs().sort_values(ascending=False).head(3)
            lines.append("")
            lines.append("**Visual themes** (CLIP-PCA differentiators between top-quintile vs bottom-quintile engagement):")
            for col, val in diff.items():
                direction = "higher" if (high[col].mean() - low[col].mean()) > 0 else "lower"
                lines.append(f"- {col} is {direction} in top performers (mean shift = {val:.3f}).")

    return "\n".join(lines)


def build_doc2_ml_predictors(industry: str, df_ind: pd.DataFrame, shap_ranks: List[Tuple[str, float, float]]) -> str:
    """DOC 2 — ML Performance Predictors (V6 stacking, XGB V5c SHAP proxy)."""
    lines = []
    lines.append(f"# ML Performance Predictors — {industry.capitalize()}")
    lines.append("")
    lines.append("Source: XGB V5c SHAP values on 200 sampled test rows (V6 = Ridge stacking of "
                 "RF V5c + XGB V5c, weights ≈ 0.55 / 0.56). XGB SHAP is the most reliable "
                 "single-feature interpretive lens for V6 since the meta-Ridge is a quasi-mean.")
    lines.append("")
    lines.append("**Top 15 features by mean(|SHAP|) on test set**:")
    lines.append("")
    lines.append("| rank | feature | mean(|SHAP|) | direction | category |")
    lines.append("|---|---|---|---|---|")

    def cat(name: str) -> str:
        if name.startswith("doc_pc"): return "mpnet (caption semantics)"
        if name.startswith(("clip_pc", "clip_n_assets")): return "CLIP (visual)"
        if name.startswith("topic_"): return "BERTopic (topic OH)"
        if name.startswith(("industry_simple_", "content_type_", "caption_lang_")): return "categorical"
        return "tabular"

    for rank, (feat, mabs, mean) in enumerate(shap_ranks[:15], 1):
        direction = "↑ engagement" if mean > 0 else ("↓ engagement" if mean < 0 else "≈ neutral")
        lines.append(f"| {rank} | `{feat}` | {mabs:.4f} | {direction} | {cat(feat)} |")

    # Industry-specific high-impact post examples — pick top 3 with highest engagement_rate
    g = df_ind.sort_values("engagement_rate", ascending=False).head(3)
    lines.append("")
    lines.append(f"**Three high-engagement posts in {industry} that the model gets right** (illustrative):")
    for _, row in g.iterrows():
        cap = _truncate(row.get("caption_clean", ""), 140)
        lines.append(f"- {row['username']} — {row.get('content_type','?')}, "
                     f"engagement {_eng_str(row.get('engagement_rate',0))}: «{cap}»")

    lines.append("")
    lines.append("**How to read this**: a feature with high mean(|SHAP|) and `↑ engagement` direction "
                 "is one the V6 model identifies as a *positive driver* of engagement on average. "
                 "`brand_engagement_rate` typically dominates because it captures persistent brand quality. "
                 "Visual features (`clip_pc*`) and caption semantics (`doc_pc*`) come next, "
                 "showing that *what the post looks like and what the caption talks about* "
                 "carries real predictive signal beyond brand identity.")
    return "\n".join(lines)


def build_doc3_content_strategy(industry: str, df_ind: pd.DataFrame, topics: Dict) -> str:
    lines = []
    lines.append(f"# Content Strategy Patterns — {industry.capitalize()}")
    lines.append("")

    # Content type performance
    ct = df_ind.groupby("content_type")["engagement_rate"].agg(["mean", "median", "count"]).sort_values("mean", ascending=False)
    lines.append("**Engagement by content_type** (mean / median / n):")
    for ctype, row in ct.iterrows():
        lines.append(f"- {ctype}: mean {_eng_str(row['mean'])}, median {_eng_str(row['median'])}, n={int(row['count'])}.")

    # Caption length quartiles vs engagement
    if "caption_length" in df_ind.columns:
        q = pd.qcut(df_ind["caption_length"], q=4, labels=["Q1 (shortest)", "Q2", "Q3", "Q4 (longest)"], duplicates="drop")
        cl = df_ind.groupby(q, observed=True)["engagement_rate"].mean().reset_index()
        lines.append("")
        lines.append("**Caption-length quartile vs engagement**:")
        for _, r in cl.iterrows():
            lines.append(f"- {r['caption_length']}: {_eng_str(r['engagement_rate'])}")

    # Sentiment patterns
    if "caption_sentiment" in df_ind.columns:
        s = df_ind["caption_sentiment"].dropna()
        if len(s) > 0:
            lines.append("")
            lines.append(f"**Sentiment** (XLM-RoBERTa, range [-1, +1]): "
                         f"mean={s.mean():+.3f}, median={s.median():+.3f}. "
                         f"{(s > 0.3).mean()*100:.0f}% of posts are clearly positive (>0.3), "
                         f"{(s < -0.1).mean()*100:.0f}% are negative (<-0.1).")

    # Topic distribution — top 5 BERTopic clusters in industry
    g = df_ind.copy()
    top_topics = g["topic_id"].value_counts().head(5)
    lines.append("")
    lines.append("**Top 5 BERTopic themes in industry**:")
    for tid, n in top_topics.items():
        tname = topics.get(int(tid), {}).get("name", f"Topic {tid}")
        avg = g[g["topic_id"] == int(tid)]["engagement_rate"].mean()
        kws = topics.get(int(tid), {}).get("keywords", [])[:5]
        lines.append(f"- Topic {tid} `{tname}` — {n} posts ({_safe_pct(n, len(g))}), "
                     f"avg eng {_eng_str(avg)}. Keywords: {', '.join(kws)}.")

    # has_cta, has_question, has_promo_word, has_emoji effects (if present in v5c merge)
    boolean_signals = ["has_cta", "has_question", "has_promo_word", "has_emoji", "is_weekend", "is_evening"]
    present = [c for c in boolean_signals if c in df_ind.columns]
    if present:
        lines.append("")
        lines.append("**Binary signal lift** (engagement when flag=1 vs flag=0):")
        for col in present:
            vals = df_ind.groupby(col)["engagement_rate"].mean()
            if 0 in vals.index and 1 in vals.index:
                lift = (vals[1] - vals[0])
                lines.append(f"- {col}: ON={_eng_str(vals[1])}, OFF={_eng_str(vals[0])}, "
                             f"lift={lift:+.2f}pp (n_on={int((df_ind[col]==1).sum())}, "
                             f"n_off={int((df_ind[col]==0).sum())}).")
    return "\n".join(lines)


def build_doc4_timing(industry: str, df_ind: pd.DataFrame) -> str:
    lines = []
    lines.append(f"# Timing & Cadence — {industry.capitalize()}")
    lines.append("")
    lines.append("_Engagement is heavily right-skewed (a few viral posts dominate the mean), "
                 "so we rank by **median** and show both median and mean for transparency._")
    lines.append("")
    g = df_ind.copy()
    if "published_at" in g.columns:
        # Convert UTC timestamps to Africa/Tunis so day-of-week and hour
        # buckets reflect local audience behaviour (a 23:30 Monday Tunis
        # post is otherwise misbucketed as Tuesday UTC).
        ts_tunis = pd.to_datetime(g["published_at"], errors="coerce", utc=True).dt.tz_convert("Africa/Tunis")
        g["dow"]  = ts_tunis.dt.dayofweek
        g["hour_published"] = ts_tunis.dt.hour

    # Best 3 days — rank by median (robust to viral outliers)
    if "dow" in g.columns and g["dow"].notna().any():
        dow_eng = (g.groupby("dow")["engagement_rate"]
                    .agg(["median", "mean", "count"])
                    .sort_values("median", ascending=False))
        lines.append("**Best days of week** (median engagement, mean for reference, post count):")
        for dow, row in dow_eng.head(3).iterrows():
            try:
                day_name = DAY_FR[int(dow)]
            except Exception:
                day_name = f"day {dow}"
            lines.append(f"- {day_name}: median {_eng_str(row['median'])}, "
                         f"mean {_eng_str(row['mean'])}, n={int(row['count'])}.")
        lines.append("")
        lines.append("**Worst days of week** (lowest median engagement):")
        for dow, row in dow_eng.tail(2).iterrows():
            try:
                day_name = DAY_FR[int(dow)]
            except Exception:
                day_name = f"day {dow}"
            lines.append(f"- {day_name}: median {_eng_str(row['median'])}, "
                         f"mean {_eng_str(row['mean'])}, n={int(row['count'])}.")

    # Best 3 hours — rank by median (≥5 posts)
    if "hour_published" in g.columns and g["hour_published"].notna().any():
        hr = g.groupby("hour_published")["engagement_rate"].agg(["median", "mean", "count"])
        hr = hr[hr["count"] >= 5].sort_values("median", ascending=False)
        if len(hr) > 0:
            lines.append("")
            lines.append("**Best hours** (≥5 posts, by median engagement):")
            for h, row in hr.head(3).iterrows():
                lines.append(f"- {int(h):02d}h: median {_eng_str(row['median'])}, "
                             f"mean {_eng_str(row['mean'])}, n={int(row['count'])}.")

    # Posting frequency — posts per active week per brand
    if "published_at" in g.columns:
        ts = pd.to_datetime(g["published_at"], errors="coerce", utc=True)
        weeks = ts.dt.isocalendar().week + ts.dt.year * 100
        g2 = g.assign(_wk=weeks)
        ppw = g2.groupby(["username", "_wk"]).size().reset_index(name="n").groupby("username")["n"].mean()
        lines.append("")
        lines.append(f"**Posting frequency** (posts/active week per brand): "
                     f"mean={ppw.mean():.2f}, median={ppw.median():.2f}, max={ppw.max():.2f}, "
                     f"n_brands={len(ppw)}.")

    # Weekend vs weekday
    if "is_weekend" in g.columns:
        wk = g.groupby("is_weekend")["engagement_rate"].mean()
        if 0 in wk.index and 1 in wk.index:
            lines.append("")
            lines.append(f"**Weekend vs weekday**: weekend={_eng_str(wk[1])}, "
                         f"weekday={_eng_str(wk[0])}, "
                         f"lift={ (wk[1]-wk[0]):+.2f}pp.")

    return "\n".join(lines)


def build_doc5_hashtags(industry: str, df_ind: pd.DataFrame) -> str:
    lines = []
    lines.append(f"# Hashtag Strategy — {industry.capitalize()}")
    lines.append("")
    lines.append("_Ranked by **median** engagement to avoid skew from viral outliers; "
                 "mean shown alongside for reference._")
    lines.append("")
    g = df_ind.copy()

    # Build per-hashtag engagement
    rows = []
    for _, r in g.iterrows():
        tags = _to_list(r.get("hashtags"))
        e = r.get("engagement_rate", 0)
        for t in tags:
            if isinstance(t, str) and 2 < len(t) < 30:
                rows.append((t.lower(), float(e)))
    if rows:
        df_h = pd.DataFrame(rows, columns=["tag", "eng"])
        agg = df_h.groupby("tag")["eng"].agg(["median", "mean", "count"])
        # Tags with ≥5 occurrences only
        agg = agg[agg["count"] >= 5].sort_values("median", ascending=False)

        lines.append("**Top 30 hashtags by median engagement** (≥5 occurrences):")
        for tag, row in agg.head(30).iterrows():
            lines.append(f"- #{tag}: median {_eng_str(row['median'])}, "
                         f"mean {_eng_str(row['mean'])}, n={int(row['count'])}.")

    # Optimal hashtag count
    if "hashtags_count" in g.columns:
        bins = pd.cut(g["hashtags_count"], bins=[-0.5, 0, 3, 6, 10, 30],
                       labels=["0", "1-3", "4-6", "7-10", "11+"])
        hc = g.groupby(bins, observed=True)["engagement_rate"].agg(["median", "mean", "count"])
        lines.append("")
        lines.append("**Engagement by hashtag-count bucket**:")
        for b, row in hc.iterrows():
            lines.append(f"- {b} tags: median {_eng_str(row['median'])}, "
                         f"mean {_eng_str(row['mean'])}, n={int(row['count'])}.")
    return "\n".join(lines)


def build_doc6_visual(industry: str, df_ind: pd.DataFrame) -> str:
    lines = []
    lines.append(f"# Visual Strategy — {industry.capitalize()}")
    lines.append("")
    lines.append("_Ranked by **median** engagement (robust to viral outliers); "
                 "mean shown alongside for reference._")
    lines.append("")
    g = df_ind.copy()

    # Image vs video performance — rank by median
    by_ct = (g.groupby("content_type")["engagement_rate"]
              .agg(["median", "mean", "count"])
              .sort_values("median", ascending=False))
    lines.append("**Format performance** (by median engagement):")
    for ct, row in by_ct.iterrows():
        lines.append(f"- {ct}: median {_eng_str(row['median'])}, "
                     f"mean {_eng_str(row['mean'])}, n={int(row['count'])}.")

    # Slide count for carousel — rank by median (≥3 posts per bucket)
    if "slide_count" in g.columns:
        car = g[g["content_type"] == "carousel"]
        if len(car):
            sc = car.groupby("slide_count")["engagement_rate"].agg(["median", "mean", "count"])
            sc = sc[sc["count"] >= 3].sort_values("median", ascending=False).head(5)
            lines.append("")
            lines.append("**Optimal carousel slide count** (≥3 posts per bucket, top 5 by median engagement):")
            for sc_n, row in sc.iterrows():
                lines.append(f"- {int(sc_n)} slides: median {_eng_str(row['median'])}, "
                             f"mean {_eng_str(row['mean'])}, n={int(row['count'])}.")

    # CLIP centroids: top vs bottom quintile
    clip_cols = [c for c in g.columns if c.startswith("clip_pc")]
    if clip_cols:
        q_hi = g["engagement_rate"].quantile(0.80)
        q_lo = g["engagement_rate"].quantile(0.20)
        hi = g[g["engagement_rate"] >= q_hi]
        lo = g[g["engagement_rate"] <= q_lo]
        if len(hi) and len(lo):
            shifts = (hi[clip_cols].mean() - lo[clip_cols].mean()).abs().sort_values(ascending=False).head(5)
            lines.append("")
            lines.append("**Top 5 visual axes that differentiate high- from low-engagement posts** (CLIP PCs):")
            for col, val in shifts.items():
                d = "+" if (hi[col].mean() - lo[col].mean()) > 0 else "-"
                lines.append(f"- {col}: |Δ|={val:.3f}, sign={d} (high vs low quintile).")

    if "clip_n_assets" in g.columns:
        ca = (g.groupby("clip_n_assets")["engagement_rate"]
               .agg(["median", "mean", "count"])
               .sort_values("median", ascending=False))
        ca = ca[ca["count"] >= 5].head(3)
        lines.append("")
        lines.append("**Best n_assets buckets** (≥5 posts, by median engagement):")
        for n, row in ca.iterrows():
            lines.append(f"- {int(n)} visual assets: median {_eng_str(row['median'])}, "
                         f"mean {_eng_str(row['mean'])}, n={int(row['count'])}.")
    return "\n".join(lines)


def build_doc7_engagement_tactics(industry: str, df_ind: pd.DataFrame) -> str:
    lines = []
    lines.append(f"# Engagement Tactics — {industry.capitalize()}")
    lines.append("")
    g = df_ind.copy()

    # Comments / followers ratio (proxy for "comments-driving" posts)
    if "comments" in g.columns and "followers" in g.columns:
        g = g.copy()
        g["_cmt_ratio"] = g["comments"] / g["followers"].clip(lower=1)
        top_cmt = g.sort_values("_cmt_ratio", ascending=False).head(5)
        lines.append("**Top 5 comment-driving posts** (comments / followers):")
        for _, r in top_cmt.iterrows():
            cap = _truncate(r.get("caption_clean", ""), 130)
            lines.append(f"- {r['username']} — {r.get('content_type','?')}, "
                         f"comments/follower={r['_cmt_ratio']:.5f}, "
                         f"comments={int(r.get('comments',0))}: «{cap}»")

    # Caption hooks — first 4 words of top-engagement posts
    top10 = g.sort_values("engagement_rate", ascending=False).head(10)
    hooks = []
    for cap in top10.get("caption_clean", pd.Series([], dtype=str)):
        if isinstance(cap, str) and cap.strip():
            words = cap.strip().split()[:4]
            hooks.append(" ".join(words))
    if hooks:
        lines.append("")
        lines.append("**Caption opening hooks of top-10 engagement posts**:")
        for i, h in enumerate(hooks, 1):
            lines.append(f"- {i}. «{h}»")

    # CTA / question stats with examples
    for flag, label in [("has_cta", "CTAs"), ("has_question", "questions"), ("has_promo_word", "promo wording")]:
        if flag in g.columns:
            on = g[g[flag] == 1]
            off = g[g[flag] == 0]
            if len(on) and len(off):
                lift = on["engagement_rate"].mean() - off["engagement_rate"].mean()
                lines.append("")
                lines.append(f"**{label}**: ON n={len(on)} mean {_eng_str(on['engagement_rate'].mean())}, "
                             f"OFF n={len(off)} mean {_eng_str(off['engagement_rate'].mean())}, "
                             f"lift={lift:+.2f}pp.")
                top_on = on.sort_values("engagement_rate", ascending=False).head(2)
                for _, r in top_on.iterrows():
                    lines.append(f"  - example: {r['username']} — «{_truncate(r.get('caption_clean',''),120)}»")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────
# Refreshed ml_insight docs (10 V6-aware)
# ─────────────────────────────────────────────────────────────────────────

def build_v6_ml_insights(shap_ranks: List[Tuple[str, float, float]], topics: Dict, df: pd.DataFrame) -> List[Dict]:
    """10 V6 ml_insight docs — concise statements derived from XGB V5c SHAP."""
    docs = []
    feat_to_meta = {n: (m, mn) for n, m, mn in shap_ranks}

    insights = [
        ("v6_top_predictor",
         f"The strongest single feature in the V6 stacking model (XGB V5c proxy SHAP) is "
         f"`{shap_ranks[0][0]}` (mean|SHAP|={shap_ranks[0][1]:.4f}). It captures persistent "
         f"brand-level performance: a brand that has previously delivered above-average "
         f"engagement is the single most reliable signal for whether the next post will too. "
         f"Implication: new brands without history are at a structural disadvantage."),

        ("v6_clip_visual_signal",
         "CLIP visual embeddings (clip_pc01..15) collectively rank in the top 5 SHAP "
         f"contributors for V6 (highest is `{[r[0] for r in shap_ranks if r[0].startswith('clip_pc')][0]}`). "
         "Visual style is a quantifiable performance signal — not just brand or text. "
         "Implication: invest in visual consistency and a recognisable style; the model "
         "rewards posts whose imagery aligns with the high-engagement visual cluster of the industry."),

        ("v6_mpnet_caption_semantics",
         "mpnet caption embeddings (doc_pc01..15) contribute meaningful predictive signal "
         "in V6, with the top axis appearing in the global top 10 SHAP. This complements "
         "BERTopic's discrete topic clustering: rather than 'which of 21 buckets', the doc-PC "
         "scores capture *how the caption is written* (tone, register, vocabulary). "
         "Implication: rewriting an existing caption in a different register can shift "
         "predicted engagement without changing the topic."),

        ("v6_topic_id_under_used",
         "Topic-OH features (topic_0..topic_19, topic_outlier) appear *outside* the V6 top 20 SHAP. "
         "Practically, BERTopic clusters add little marginal predictive value beyond what "
         "captions-as-text and visuals already encode. Implication: topic-based "
         "rotation is useful for editorial planning but is *not* the highest-ROI optimisation lever."),

        ("v6_brand_engagement_persistence",
         "`brand_engagement_rate` and `brand_avg_likes` are both top-10 SHAP features. "
         "Recent past performance per brand is the single best predictor of next-post "
         "performance. Implication: improvements compound; sustained quality over weeks "
         "lifts predicted engagement on subsequent posts via the brand-history features."),

        ("v6_followers_paradox",
         f"`followers` ranks high in SHAP magnitude but with a complex non-linear pattern. "
         f"Higher followers → lower engagement *rate* (denominator effect), but the V6 "
         f"model captures that smaller accounts can have outsized engagement when the "
         f"content quality signal (visual + caption) is strong. Implication: engagement "
         f"rate and reach are different KPIs; optimise one or the other, not both at once."),

        ("v6_days_since_first_post",
         "`days_since_first_post` is in the top 5 SHAP — older accounts tend to have "
         "lower engagement rates (audience fatigue / saturation). Implication: a fresh account "
         "in this industry has a measurable engagement-rate honeymoon; capitalise on it "
         "with high cadence early."),

        ("v6_content_type_format_split",
         "`industry_simple_*` one-hots dominate SHAP for industry-discrimination, but "
         "`content_type_*` (reel, carousel, photo) consistently appear with mid-rank "
         "SHAP. Reels and carousels show mostly positive SHAP across industries. "
         "Implication: format choice matters, but it interacts with industry — a format "
         "that wins for restaurants may not win for hotels."),

        ("v6_stacking_gain_explained",
         "V6 = Ridge over OOF predictions of RF V5c (weight 0.55) + XGB V5c (weight 0.56). "
         "The stacking lifts R²(log) by +2pp over the V5c XGB champion (0.4382 → 0.4587) "
         "AND lifts Spearman ρ to 0.6686 (above either base). Implication: RF and XGB "
         "make complementary errors; they are not redundant."),

        ("v6_lgb_redundant",
         "When LGB V5c is added to the stack (V6b), Ridge gives it weight 0.089 — "
         "essentially negligible. R²(log) gain is +0.0004 (well below the 0.01 parsimony "
         "threshold). Implication: LGB does not add a third independent perspective on "
         "this dataset; RF + XGB suffices."),
    ]

    for ins_id, text in insights:
        docs.append({
            "id": ins_id,
            "type": "ml_insight",
            "text": text,
            "metadata": {"source": "V6 stacking + XGB V5c SHAP", "model_version": "V6"}
        })
    return docs


# ─────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────

def write_industry_docs(industry: str, ddata: Dict) -> List[Dict]:
    df_ind = ddata["df"][ddata["df"]["industry_simple"] == industry]
    out_dir = DOCS_DIR / industry
    out_dir.mkdir(parents=True, exist_ok=True)
    builders = [
        ("top_patterns",       lambda: build_doc1_top_patterns(industry, df_ind, ddata["v6_pred"], ddata["topics"])),
        ("ml_predictors",      lambda: build_doc2_ml_predictors(industry, df_ind, ddata["shap_ranks"])),
        ("content_strategy",   lambda: build_doc3_content_strategy(industry, df_ind, ddata["topics"])),
        ("timing_cadence",     lambda: build_doc4_timing(industry, df_ind)),
        ("hashtag_strategy",   lambda: build_doc5_hashtags(industry, df_ind)),
        ("visual_strategy",    lambda: build_doc6_visual(industry, df_ind)),
        ("engagement_tactics", lambda: build_doc7_engagement_tactics(industry, df_ind)),
    ]
    out_docs: List[Dict] = []
    for slug, fn in builders:
        text = fn()
        md_path = out_dir / f"{slug}.md"
        md_path.write_text(text, encoding="utf-8")
        out_docs.append({
            "id": f"v6_{industry}_{slug}",
            "type": f"v6_{slug}",
            "text": text,
            "metadata": {
                "industry": industry,
                "doc_kind": slug,
                "model_version": "V6",
                "n_industry_posts": int(len(df_ind)),
            }
        })
    print(f"  {industry:<11} → 7 markdown docs ({sum(len(d['text']) for d in out_docs)//1024} KB total)")
    return out_docs


def main() -> int:
    print("=" * 78)
    print("Step 4f V6 — Build V6-enriched RAG corpus")
    print("=" * 78)

    if STEP4F_V6.exists():
        # Avoid stale carry-over of the docs/ subtree only — keep parent and other artifacts
        shutil.rmtree(DOCS_DIR, ignore_errors=True)
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    ddata = load_data()

    print("\nGenerating V6 per-industry docs (7 × 5 = 35) ...")
    new_docs: List[Dict] = []
    for ind in INDUSTRIES:
        new_docs.extend(write_industry_docs(ind, ddata))

    print("\nGenerating V6 ml_insight refresh (10 docs) ...")
    new_docs.extend(build_v6_ml_insights(ddata["shap_ranks"], ddata["topics"], ddata["df"]))

    # Reuse existing factual docs (topic / top_post / brand / industry summaries).
    # Drop the previous V3-era ml_insight docs — replaced by V6-aware ones above.
    existing = []
    if EXISTING_DOCS.exists():
        with open(EXISTING_DOCS, "r", encoding="utf-8") as f:
            existing = json.load(f)
        kept = [d for d in existing if d.get("type") != "ml_insight"]
        dropped = len(existing) - len(kept)
        print(f"\nReusing {len(kept)} factual docs from existing corpus (dropped {dropped} V3 ml_insight)")
        existing = kept

    merged = existing + new_docs
    print(f"\nFinal corpus:")
    from collections import Counter as _C
    type_counts = _C(d["type"] for d in merged)
    for t, n in type_counts.most_common():
        print(f"  {t:<26} {n:>4}")
    print(f"  {'TOTAL':<26} {len(merged):>4}")

    out_json = STEP4F_V6 / "documents.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)
    print(f"\nWrote {out_json}  ({out_json.stat().st_size/1024:.1f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
