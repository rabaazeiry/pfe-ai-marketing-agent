"""Step 4 PREP — BERTopic V3 topic inspection report.

Joins df_master_masked_with_topics with df_ml_dataset_v3 to compute per-topic
quality metrics: counts (master vs V3), avg engagement, top hashtags, industry
distribution, top brand contributors. Cross-references topics_validated.yaml
for human-validated names and decisions. NO documents/RAG written.
"""
from __future__ import annotations
import sys
from collections import Counter
from pathlib import Path

import pandas as pd
import yaml

sys.stdout.reconfigure(encoding="utf-8")

DATA = Path("data")
MASTER = DATA / "df_master_masked_with_topics.parquet"
V3 = DATA / "df_ml_dataset_v3.parquet"
VALIDATED = DATA / "topics_validated.yaml"

# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------
df_m = pd.read_parquet(MASTER)
df_v3 = pd.read_parquet(V3)
with open(VALIDATED, "r", encoding="utf-8") as f:
    validated = yaml.safe_load(f)

v3_ids = set(df_v3["post_id"].astype(str))
df_m["post_id"] = df_m["post_id"].astype(str)
df_m["in_v3"] = df_m["post_id"].isin(v3_ids)

# Validated topic lookup: topic_id -> dict
val_lookup = {t["topic_id"]: t for t in validated["topics"]}

# ---------------------------------------------------------------------------
# Per-topic stats (computed against df_master, restricted to V3 rows for V3 cols)
# ---------------------------------------------------------------------------
rows = []
total_v3 = 0
for tid, group in df_m.groupby("topic_id"):
    g_v3 = group[group["in_v3"]]
    n_master = len(group)
    n_v3 = len(g_v3)
    total_v3 += n_v3

    avg_eng_v3 = g_v3["engagement_rate"].mean() if n_v3 else float("nan")

    # Top 3 hashtags (V3 subset)
    hcounter = Counter()
    for tags in g_v3["hashtags"]:
        for h in tags:
            if h:
                hcounter[h.lower()] += 1
    top_hashtags = hcounter.most_common(3)

    # Industry distribution (V3 subset, percentages)
    ind_counts = g_v3["industry_simple"].value_counts(normalize=True) * 100 if n_v3 else pd.Series(dtype=float)
    top_industry = (ind_counts.index[0], ind_counts.iloc[0]) if n_v3 else ("n/a", 0.0)

    # Top 3 brand contributors
    brand_counts = g_v3["username"].value_counts().head(3) if n_v3 else pd.Series(dtype=int)
    top_brands = list(zip(brand_counts.index.tolist(), brand_counts.values.tolist()))
    brand_concentration = (brand_counts.iloc[0] / n_v3 * 100) if n_v3 else 0.0

    # Name from validated yaml
    val = val_lookup.get(int(tid))
    if val is None:
        if int(tid) == -1:
            name = "OUTLIERS"
            quality = "N/A"
            decision = "n/a"
        else:
            name = "(unvalidated)"
            quality = "?"
            decision = "?"
    else:
        name = val.get("suggested_name", "?") or "?"
        quality = val.get("quality", "?")
        decision = val.get("decision", "?")

    rows.append(
        {
            "topic_id": int(tid),
            "name": name,
            "n_master": n_master,
            "n_v3": n_v3,
            "avg_eng": avg_eng_v3,
            "top_industry": top_industry[0],
            "top_industry_pct": top_industry[1],
            "industry_dist": ind_counts.to_dict(),
            "top_hashtags": top_hashtags,
            "top_brands": top_brands,
            "brand_concentration": brand_concentration,
            "quality": quality,
            "decision": decision,
        }
    )

rows.sort(key=lambda r: r["topic_id"])

# ---------------------------------------------------------------------------
# Print report
# ---------------------------------------------------------------------------
print("=" * 100)
print(" BERTopic V3 - Topic Quality Report")
print("=" * 100)
print(f" Source: {MASTER.name} ({len(df_m)} posts) joined with {V3.name} ({len(df_v3)} V3 posts)")
print(f" Validated YAML: {VALIDATED.name} ({len(val_lookup)} validated topics)")
print()

# Main table
print(
    f"{'Tid':>4} | {'Name':<36} | {'n_v3':>5} | {'avg_eng':>8} | "
    f"{'Top Industry':<16} | {'Q':>2} | {'Decision':<18}"
)
print("-" * 100)
for r in rows:
    eng = f"{r['avg_eng']*100:>6.2f}%" if pd.notna(r["avg_eng"]) else "    n/a"
    industry_label = f"{r['top_industry']} ({r['top_industry_pct']:.0f}%)"
    print(
        f"{r['topic_id']:>4} | {r['name'][:36]:<36} | {r['n_v3']:>5} | {eng:>8} | "
        f"{industry_label:<16} | {str(r['quality']):>2} | {str(r['decision'])[:18]:<18}"
    )

print("-" * 100)
print(f" TOTAL V3: {total_v3}  (expected 4087)  | TOTAL master: {len(df_m)}")
print()

# ---------------------------------------------------------------------------
# Detail block: top hashtags + brands per topic
# ---------------------------------------------------------------------------
print("=" * 100)
print(" Detail per topic: top 3 hashtags + top 3 brand contributors (V3 subset)")
print("=" * 100)
for r in rows:
    print(f"\n  Topic {r['topic_id']:>3}  {r['name']}")
    if r["top_hashtags"]:
        hts = ", ".join(f"#{h} ({c})" for h, c in r["top_hashtags"])
    else:
        hts = "(no hashtags)"
    print(f"    hashtags : {hts}")
    if r["top_brands"]:
        brands = ", ".join(f"{u} ({c})" for u, c in r["top_brands"])
    else:
        brands = "(empty)"
    print(f"    brands   : {brands}    [top brand = {r['brand_concentration']:.0f}% of topic]")
    if r["industry_dist"]:
        ind_str = ", ".join(f"{k}={v:.0f}%" for k, v in sorted(r["industry_dist"].items(), key=lambda x: -x[1]))
        print(f"    industry : {ind_str}")

# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------
print()
print("=" * 100)
print(" ANALYSIS")
print("=" * 100)

n_total_v3 = total_v3
outlier_row = next((r for r in rows if r["topic_id"] == -1), None)
if outlier_row:
    out_pct = outlier_row["n_v3"] / n_total_v3 * 100
    flag = "RED FLAG (>30%)" if out_pct > 30 else "OK"
    print(f"\n  Outliers (-1) : {outlier_row['n_v3']} posts = {out_pct:.1f}% of V3   [{flag}]")

small = [r for r in rows if r["topic_id"] != -1 and r["n_v3"] < 30]
print(f"\n  Topics with n_v3 < 30 (potentially weak):")
if small:
    for r in small:
        print(f"    Topic {r['topic_id']:>3}  n_v3={r['n_v3']:<4}  {r['name']}")
else:
    print("    (none)")

big = [r for r in rows if r["topic_id"] != -1 and r["n_v3"] > 500]
print(f"\n  Topics with n_v3 > 500 (very large, low specificity):")
if big:
    for r in big:
        print(f"    Topic {r['topic_id']:>3}  n_v3={r['n_v3']:<5}  {r['name']}")
else:
    print("    (none)")

dominated = [r for r in rows if r["topic_id"] != -1 and r["brand_concentration"] >= 50 and r["n_v3"] >= 10]
print(f"\n  Topics dominated by 1 brand (>=50% of posts, brand bias risk):")
if dominated:
    for r in dominated:
        top_brand = r["top_brands"][0][0] if r["top_brands"] else "?"
        print(
            f"    Topic {r['topic_id']:>3}  {r['name']:<36}  "
            f"top brand = {top_brand} ({r['brand_concentration']:.0f}%)"
        )
else:
    print("    (none)")

# Industry distribution
print(f"\n  Industry distribution (V3, all topics):")
ind_global = df_m[df_m["in_v3"]]["industry_simple"].value_counts(normalize=True) * 100
for ind, pct in ind_global.items():
    print(f"    {ind:<14} {pct:>5.1f}%")

# Decision breakdown
print(f"\n  Decisions in topics_validated.yaml:")
dec_counter = Counter(r["decision"] for r in rows if r["topic_id"] != -1)
for d, c in dec_counter.most_common():
    print(f"    {d:<18} {c}")

print("\n" + "=" * 100)
print(" RECOMMENDATIONS (auto-generated, for user review)")
print("=" * 100)
remove = [r for r in rows if r["decision"] == "REMOVE"]
merge = [r for r in rows if isinstance(r["decision"], str) and r["decision"].startswith("MERGE")]
keep = [r for r in rows if r["decision"] == "KEEP"]
print(f"\n  YAML says: KEEP={len(keep)}  REMOVE={len(remove)}  MERGE={len(merge)}")
if remove:
    print(f"\n  Topics flagged REMOVE in YAML:")
    for r in remove:
        print(f"    Topic {r['topic_id']:>3}  n_v3={r['n_v3']:<4}  {r['name']}  -- {val_lookup[r['topic_id']].get('reasoning', '')}")
if merge:
    print(f"\n  Topics flagged MERGE in YAML:")
    for r in merge:
        print(f"    Topic {r['topic_id']:>3}  -> {r['decision']}  n_v3={r['n_v3']}  {r['name']}")

print()
print("  Suggested next step:")
if outlier_row and (outlier_row["n_v3"] / n_total_v3) > 0.20:
    print("    - Outliers are a large fraction (>20%); consider treating them as a separate")
    print("      'Other / unstructured' category in the RAG corpus rather than dropping them.")
if small:
    print(f"    - {len(small)} topic(s) below the n=30 floor: candidates for merge/drop in RAG documents.")
if dominated:
    print(f"    - {len(dominated)} topic(s) brand-dominated: consider noting the brand in topic name")
    print("      so RAG queries surface them only when relevant (avoids generic-sounding answers).")
if remove or merge:
    print(f"    - Apply YAML decisions before building documents: drop REMOVE topics, merge MERGE topics.")
print()
