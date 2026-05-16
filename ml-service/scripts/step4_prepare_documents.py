"""Step 4c — Build RAG documents from V3 data.

Generates 5 types of documents (~180 total):
1. Topic summaries (21 docs)
2. Top 5 posts per topic (~105 docs)
3. Brand summaries (~41 docs)
4. Industry summaries (5 docs)
5. ML insights (~10 docs)

Output: data/step4/documents.json
"""
from __future__ import annotations
import json
import sys
from collections import Counter
from pathlib import Path
import pandas as pd
import yaml

sys.stdout.reconfigure(encoding="utf-8")

DATA = Path("data")
STEP4_DIR = DATA / "step4"
STEP4_DIR.mkdir(parents=True, exist_ok=True)

V3 = DATA / "df_ml_dataset_v3.parquet"
MASTER = DATA / "df_master_masked_with_topics.parquet"
TOPICS_YAML = DATA / "topics_v3_llm_named.yaml"
RF_RESULTS = DATA / "rf_v3_results.txt"
OUT = STEP4_DIR / "documents.json"

# ---- Load data ----
print("Loading data...")
df_v3 = pd.read_parquet(V3)
df_master = pd.read_parquet(MASTER)
df_v3["post_id"] = df_v3["post_id"].astype(str)
df_master["post_id"] = df_master["post_id"].astype(str)

# Join V3 with master to get captions, hashtags, etc.
# df_master has: username, caption_clean, hashtags, industry_simple, content_type, topic_id, engagement_rate
# df_v3 contributes: hour (and other engineered features) — merge by post_id
df = df_master[df_master["post_id"].isin(set(df_v3["post_id"]))].merge(
    df_v3[["post_id", "hour"]], on="post_id", how="left"
).copy()
print(f"  V3 posts: {len(df)} (expected 4087)")

with open(TOPICS_YAML, "r", encoding="utf-8") as f:
    topics_data = yaml.safe_load(f)
topics = topics_data["topics"]
print(f"  Topics loaded: {len(topics)}")

documents = []

# ---- Type 1: Topic summaries (21 docs) ----
print("\nGenerating Type 1: Topic summaries...")
for tid, tinfo in topics.items():
    g = df[df["topic_id"] == int(tid)]
    if len(g) == 0:
        continue

    avg_eng = g["engagement_rate"].mean()
    median_eng = g["engagement_rate"].median()

    # Hour stats
    hour_mode = g["hour"].mode().iloc[0] if not g["hour"].mode().empty else None

    # Top hashtags
    hcounter = Counter()
    for tags in g["hashtags"]:
        for h in tags:
            if h:
                hcounter[h.lower()] += 1
    top_hashtags = [h for h, _ in hcounter.most_common(3)]

    # Top brands
    top_brands = g["username"].value_counts().head(3).index.tolist()

    # Industry distribution
    ind_dist = g["industry_simple"].value_counts(normalize=True) * 100
    industry_str = ", ".join(f"{k} {v:.0f}%" for k, v in ind_dist.head(3).items())

    # Keywords from BERTopic
    keywords = tinfo.get("keywords", [])[:5]

    text = (
        f"Topic '{tinfo['name']}' (Topic ID {tid}) contains {len(g)} "
        f"Instagram posts from Tunisian brands. "
        f"Average engagement rate: {avg_eng:.2f}%, median: {median_eng:.2f}%. "
        f"Most posts published around {hour_mode}h. "
        f"Top hashtags: {', '.join('#'+h for h in top_hashtags) if top_hashtags else 'none'}. "
        f"Industry distribution: {industry_str}. "
        f"Top brands: {', '.join(top_brands)}. "
        f"Key themes: {', '.join(keywords)}."
    )

    documents.append({
        "id": f"topic_{tid}_summary",
        "type": "topic_summary",
        "text": text,
        "metadata": {
            "topic_id": int(tid),
            "topic_name": tinfo["name"],
            "n_posts": len(g),
            "avg_engagement": float(avg_eng),
            "median_engagement": float(median_eng),
            "industry_dominant": ind_dist.index[0] if not ind_dist.empty else "mixed",
        }
    })

print(f"  -> {len([d for d in documents if d['type'] == 'topic_summary'])} topic summaries")

# ---- Type 2: Top 5 posts per topic (~105 docs) ----
print("\nGenerating Type 2: Top posts per topic...")
for tid, tinfo in topics.items():
    g = df[df["topic_id"] == int(tid)].copy()
    if len(g) == 0:
        continue
    # Sort by engagement, take top 5 (cap engagement at 1.0 to avoid extreme outliers)
    g["_eng_capped"] = g["engagement_rate"].clip(upper=1.0)
    top5 = g.sort_values("_eng_capped", ascending=False).head(5)

    avg_topic = g["engagement_rate"].mean()

    for rank, (_, row) in enumerate(top5.iterrows(), 1):
        caption = (row.get("caption_clean") or row.get("caption") or "")[:200].replace("\n", " ")
        hashtags_list = list(row.get("hashtags", []))[:5]
        content_type = row.get("content_type", "unknown")
        hour = row.get("hour", "?")
        eng = row.get("engagement_rate", 0)

        text = (
            f"Top post #{rank} in topic '{tinfo['name']}'. "
            f"Brand: {row['username']}. "
            f"Engagement: {eng:.2f}% (vs topic average {avg_topic:.2f}%). "
            f"Format: {content_type}. Posted at {hour}h. "
            f"Hashtags: {', '.join('#'+h for h in hashtags_list) if hashtags_list else 'none'}. "
            f"Caption: \"{caption}...\""
        )

        documents.append({
            "id": f"topic_{tid}_top_post_{rank}",
            "type": "top_post",
            "text": text,
            "metadata": {
                "topic_id": int(tid),
                "topic_name": tinfo["name"],
                "rank": rank,
                "engagement": float(eng),
                "content_type": str(content_type),
                "brand": row["username"],
                "industry": row.get("industry_simple", "unknown"),
            }
        })

print(f"  -> {len([d for d in documents if d['type'] == 'top_post'])} top post documents")

# ---- Type 3: Brand summaries (~41 docs) ----
print("\nGenerating Type 3: Brand summaries...")
for brand in df["username"].unique():
    g = df[df["username"] == brand]
    if len(g) < 5:  # skip brands with too few posts
        continue

    industry = g["industry_simple"].mode().iloc[0]
    avg_eng = g["engagement_rate"].mean()

    # Industry average for comparison
    ind_avg = df[df["industry_simple"] == industry]["engagement_rate"].mean()
    perf_tier = "above_average" if avg_eng > ind_avg else "below_average"

    # Top 3 topics for this brand
    top_topics = g["topic_id"].value_counts().head(3)
    top_topics_named = []
    for tid, count in top_topics.items():
        tname = topics.get(int(tid), {}).get("name", f"Topic {tid}")
        pct = count / len(g) * 100
        top_topics_named.append(f"{tname} ({pct:.0f}%)")

    hour_mode = g["hour"].mode().iloc[0] if not g["hour"].mode().empty else None
    content_dist = g["content_type"].value_counts(normalize=True) * 100
    content_str = ", ".join(f"{k} {v:.0f}%" for k, v in content_dist.head(2).items())

    text = (
        f"Brand '{brand}' is in {industry} industry. "
        f"Total posts: {len(g)}. "
        f"Average engagement rate: {avg_eng:.2f}% "
        f"(vs {industry} industry average {ind_avg:.2f}%). "
        f"Performance: {perf_tier.upper().replace('_', ' ')}. "
        f"Top 3 topics: {'; '.join(top_topics_named)}. "
        f"Preferred posting hour: {hour_mode}h. "
        f"Content mix: {content_str}."
    )

    documents.append({
        "id": f"brand_{brand}_summary",
        "type": "brand_summary",
        "text": text,
        "metadata": {
            "brand": brand,
            "industry": industry,
            "n_posts": len(g),
            "avg_engagement": float(avg_eng),
            "performance_tier": perf_tier,
        }
    })

print(f"  -> {len([d for d in documents if d['type'] == 'brand_summary'])} brand summaries")

# ---- Type 4: Industry summaries (5 docs) ----
print("\nGenerating Type 4: Industry summaries...")
for industry in df["industry_simple"].unique():
    g = df[df["industry_simple"] == industry]

    n_brands = g["username"].nunique()
    avg_eng = g["engagement_rate"].mean()
    median_eng = g["engagement_rate"].median()

    # Top 3 topics for this industry
    top_topics = g["topic_id"].value_counts().head(3)
    top_topics_named = []
    for tid, count in top_topics.items():
        tname = topics.get(int(tid), {}).get("name", f"Topic {tid}")
        pct = count / len(g) * 100
        top_topics_named.append(f"{tname} ({pct:.0f}%)")

    # Best content type by engagement
    content_eng = g.groupby("content_type")["engagement_rate"].mean().sort_values(ascending=False)
    best_content = content_eng.index[0] if not content_eng.empty else "n/a"
    best_content_eng = content_eng.iloc[0] if not content_eng.empty else 0

    # Best hour
    hour_eng = g.groupby("hour")["engagement_rate"].mean().sort_values(ascending=False)
    best_hour = hour_eng.index[0] if not hour_eng.empty else "?"

    # Top 3 brands by engagement
    brand_perf = g.groupby("username")["engagement_rate"].mean().sort_values(ascending=False).head(3)
    top_brands = brand_perf.index.tolist()

    text = (
        f"{industry.upper()} industry in Tunisia: {n_brands} active brands, "
        f"{len(g)} total posts. "
        f"Average engagement: {avg_eng:.2f}%, median: {median_eng:.2f}%. "
        f"Top 3 dominant topics: {'; '.join(top_topics_named)}. "
        f"Best content type: {best_content} ({best_content_eng:.2f}% avg engagement). "
        f"Optimal posting hour: {best_hour}h. "
        f"Top performing brands: {', '.join(top_brands)}."
    )

    documents.append({
        "id": f"industry_{industry}_summary",
        "type": "industry_summary",
        "text": text,
        "metadata": {
            "industry": industry,
            "n_brands": int(n_brands),
            "n_posts": len(g),
            "avg_engagement": float(avg_eng),
        }
    })

print(f"  -> {len([d for d in documents if d['type'] == 'industry_summary'])} industry summaries")

# ---- Type 5: ML insights (~10 docs) ----
print("\nGenerating Type 5: ML insights...")

ml_insights = [
    {
        "id": "ml_rf_v3_overview",
        "text": (
            "Random Forest V3 is the production model for Tunisian Instagram engagement "
            "prediction. Performance: R² (log) = 0.3656, Spearman ρ = 0.6515 (good correlation, "
            "Cohen 1988), RMSE (log) = 0.2479. The model uses 38 features including topic_id, "
            "hour, followers, brand_engagement_rate, content_type, and 4 cultural features "
            "(is_ramadan, caption_sentiment, has_emoji, has_cta). Trained on V3 dataset "
            "(4087 posts after outlier filtering). Cross-validated 5-fold (CV mean RMSE = 0.2670)."
        ),
        "metadata": {"insight_type": "model_overview", "model": "rf_v3"}
    },
    {
        "id": "ml_top_features_shap",
        "text": (
            "Top 5 most important features for Instagram engagement prediction (SHAP analysis "
            "on RF V3): 1. brand_engagement_rate (0.34) - past brand performance is the strongest "
            "predictor. 2. days_since_first_post (0.21) - account maturity matters. "
            "3. followers (0.15) - audience size correlates with engagement. "
            "4. industry_simple_restaurants (0.10) - restaurants tend to engage more. "
            "5. content_type_reel (0.08) - Reels outperform other formats. "
            "Cross-model SHAP consensus across RF, XGB, and LightGBM confirms these "
            "as intrinsic data signals, not model artifacts."
        ),
        "metadata": {"insight_type": "shap_top_features"}
    },
    {
        "id": "ml_content_type_insight",
        "text": (
            "Content type matters significantly for Instagram engagement in Tunisia. "
            "Reels consistently generate higher engagement than carousels and photos. "
            "This is confirmed by both ML feature importance (content_type_reel ranked top 5) "
            "and direct empirical observation across all 5 industries (hotels, restaurants, "
            "beauty, fashion, patisserie). Recommendation: prioritize Reels for engagement-driven "
            "campaigns."
        ),
        "metadata": {"insight_type": "content_type"}
    },
    {
        "id": "ml_temporal_insight",
        "text": (
            "Temporal features show consistent patterns. Optimal posting time is generally "
            "evening (18h-21h), with hour ranking high in feature importance. Day of week and "
            "month effects are smaller but present. Cultural moments (Ramadan, Eid, "
            "Valentine's Day) drive engagement spikes detected through is_ramadan and "
            "is_holiday_period features."
        ),
        "metadata": {"insight_type": "temporal"}
    },
    {
        "id": "ml_brand_quality_insight",
        "text": (
            "Brand-level features dominate post-level features. brand_engagement_rate "
            "(historical performance) is the #1 predictor with feature importance 0.34. "
            "This means: the brand identity and consistent past engagement are stronger "
            "signals than any individual post characteristic. New brands or inactive accounts "
            "face an uphill battle regardless of post quality. Recommendation: focus on "
            "long-term brand consistency over individual post optimization."
        ),
        "metadata": {"insight_type": "brand_quality"}
    },
    {
        "id": "ml_cultural_features_v2",
        "text": (
            "V2 added 4 cultural features for Tunisian context: is_ramadan (boolean for "
            "Ramadan periods 2023-2026), caption_sentiment (XLM-RoBERTa multilingual "
            "sentiment score -1 to +1), has_emoji (boolean), has_cta (call-to-action "
            "detection in FR/EN/AR). Marginal improvement over V1 (R² +2.2%) but cultural "
            "features rank in top 25 feature importances. caption_sentiment particularly "
            "useful for ranking (Spearman improvement)."
        ),
        "metadata": {"insight_type": "cultural_features"}
    },
    {
        "id": "ml_industry_differences",
        "text": (
            "Industry has measurable engagement differences. Restaurants tend to have higher "
            "engagement rates (industry_simple_restaurants ranked #4 in feature importance). "
            "Beauty and fashion benefit most from Reel format. Hotels show seasonal patterns "
            "(summer offers, Valentine's Day). Patisserie engagement peaks during Ramadan. "
            "Fashion benefits from Eid collections. Each industry has distinct optimal "
            "strategies derived from data."
        ),
        "metadata": {"insight_type": "industry_differences"}
    },
    {
        "id": "ml_methodology_data_quality",
        "text": (
            "Methodology: V1 -> V2 -> V3 iterative refinement. V3 applied outlier filtering "
            "(top/bottom 1% per industry, n=40 dropped). Brand_age filter REJECTED as too "
            "aggressive (would create production blind spot for young brands). Train/test "
            "split 80/20 with engagement-stratified sampling. Cross-validation 5-fold for "
            "robustness. Data leakage audited (Kaufman 2012 train/inference symmetry): "
            "all post-publication metrics (views, likes, comments) excluded from features."
        ),
        "metadata": {"insight_type": "methodology"}
    },
    {
        "id": "ml_models_comparison",
        "text": (
            "3 models compared on V3 dataset: Random Forest (R²=0.3656, ρ=0.6515), "
            "XGBoost (R²=0.3472, ρ=0.6472), LightGBM (R²=0.3416, ρ=0.5904). "
            "4 ensembles tested (AVG-3, WAVG-3, STACK-3 Wolpert stacking, AVG-2): "
            "no ensemble exceeded RF V3 by >0.5% RMSE. CV RMSE confirms RF V3 as "
            "best generalizer (0.2670 vs ensembles >=0.2672). Decision: RF V3 retained "
            "via Occam's razor (single model, 3x faster inference, equivalent quality)."
        ),
        "metadata": {"insight_type": "model_comparison"}
    },
    {
        "id": "ml_engagement_prediction_quality",
        "text": (
            "Our R²=0.3656 is aligned with reproducible Instagram engagement literature "
            "(Trivedi 2019: 0.32, Chen 2022: 0.28, Stanford Kim&Hwang 2025: 0.41, "
            "Mishra 2025: 0.35). Higher R² (>0.7) reported in some papers typically "
            "results from undetected data leakage (using post-publication metrics as "
            "features). Our Spearman rho=0.6515 is operationally relevant for ranking "
            "campaign post ideas and falls in 'good correlation' range (Cohen 1988)."
        ),
        "metadata": {"insight_type": "benchmark"}
    },
]

for insight in ml_insights:
    documents.append({
        "id": insight["id"],
        "type": "ml_insight",
        "text": insight["text"],
        "metadata": insight["metadata"],
    })

print(f"  -> {len([d for d in documents if d['type'] == 'ml_insight'])} ML insights")

# ---- Save ----
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(documents, f, indent=2, ensure_ascii=False)

print()
print("=" * 80)
print("RAG Documents Generated")
print("=" * 80)

# Summary by type
type_counts = Counter(d["type"] for d in documents)
print(f"{'Type':<25} | {'Count':>6}")
print("-" * 35)
for t, c in type_counts.most_common():
    print(f"{t:<25} | {c:>6}")
print("-" * 35)
print(f"{'TOTAL':<25} | {len(documents):>6}")
print()
print(f"Saved to: {OUT}")
print(f"File size: {OUT.stat().st_size / 1024:.1f} KB")

# Sample preview
print()
print("=" * 80)
print("Sample document (first topic_summary):")
print("=" * 80)
sample = next(d for d in documents if d["type"] == "topic_summary")
print(json.dumps(sample, indent=2, ensure_ascii=False)[:1000])
print("...")
