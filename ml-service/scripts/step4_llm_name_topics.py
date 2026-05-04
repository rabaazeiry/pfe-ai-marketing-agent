"""Step 4 PREP — Generate LLM-validated topic names for the V3 dataset.

For each topic in the BERTopic v2 model, gathers:
  - top 10 c-TF-IDF keywords (from BERTopic)
  - top 5 hashtags + top 3 brands (from V3 subset)
  - industry distribution
  - 3 example captions (top by engagement_rate)
Sends to Llama 3.1 (temperature=0, deterministic) which returns a short name.
Outliers (-1) get the fixed name "Outliers (mixed content)" without an LLM call.

Output: data/topics_v3_llm_named.yaml
"""
from __future__ import annotations
import os
import sys
import time
from collections import Counter
from datetime import date
from pathlib import Path

# ORDER MATTERS: torch must be imported before bertopic on Windows (c10.dll bug)
import torch  # noqa: F401
import pandas as pd
import yaml
from bertopic import BERTopic
from langchain_ollama import OllamaLLM

sys.stdout.reconfigure(encoding="utf-8")

DATA = Path("data")
MASTER = DATA / "df_master_masked_with_topics.parquet"
V3 = DATA / "df_ml_dataset_v3.parquet"
MODEL_DIR = Path("models/bertopic_v2")
OUT = DATA / "topics_v3_llm_named.yaml"

# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------
print("Loading data + BERTopic v2 model...")
df_m = pd.read_parquet(MASTER)
df_v3 = pd.read_parquet(V3)
df_m["post_id"] = df_m["post_id"].astype(str)
df_v3["post_id"] = df_v3["post_id"].astype(str)
v3_ids = set(df_v3["post_id"])
df_m = df_m[df_m["post_id"].isin(v3_ids)].copy()  # restrict to V3 from now on

model = BERTopic.load(str(MODEL_DIR))
all_tids = sorted(model.get_topics().keys())
print(f"  V3 posts loaded: {len(df_m)}   topic ids in model: {all_tids}")

# ---------------------------------------------------------------------------
# Per-topic metadata gathering
# ---------------------------------------------------------------------------
def topic_metadata(tid: int) -> dict:
    g = df_m[df_m["topic_id"] == tid]
    n = len(g)

    keywords = [w for w, _ in model.get_topic(tid)[:10]] if model.get_topic(tid) else []

    hcounter: Counter = Counter()
    for tags in g["hashtags"]:
        for h in tags:
            if h:
                hcounter[h.lower()] += 1
    top_hashtags = [h for h, _ in hcounter.most_common(5)]

    industry_counts = g["industry_simple"].value_counts(normalize=True) * 100
    industry_dist = {k: round(float(v), 1) for k, v in industry_counts.items()}
    if industry_counts.empty:
        industry_dominant = "n/a"
    else:
        industry_dominant = f"{industry_counts.index[0]} ({industry_counts.iloc[0]:.0f}%)"

    brand_counts = g["username"].value_counts().head(3)
    top_brands = brand_counts.index.tolist()

    # Top 3 captions by engagement (cap engagement to 1.0 to avoid pathological outliers)
    g_sorted = g.assign(_eng=g["engagement_rate"].clip(upper=1.0)).sort_values("_eng", ascending=False)
    examples = []
    for cap in g_sorted["caption_clean"].head(3).tolist():
        examples.append((cap or "")[:200].replace("\n", " ").strip())

    return {
        "n_v3": n,
        "keywords": keywords,
        "top_hashtags": top_hashtags,
        "top_brands": top_brands,
        "industry_dominant": industry_dominant,
        "industry_dist": industry_dist,
        "example_captions": examples,
    }

metas = {tid: topic_metadata(tid) for tid in all_tids}

# ---------------------------------------------------------------------------
# LLM naming
# ---------------------------------------------------------------------------
PROMPT_TEMPLATE = """Analyze this Instagram post cluster and give it a SHORT descriptive name (max 4 words, in English).

Top keywords (BERTopic c-TF-IDF): {keywords}
Top 5 hashtags: {hashtags}
Dominant industry: {industry}
Top brands: {brands}
Number of posts: {n}

Example captions:
- "{cap1}"
- "{cap2}"
- "{cap3}"

Reply with ONLY the topic name (max 4 words), no explanation, no quotes.
Example good answers: "Ramadan & Iftar", "Behind the Scenes", "Summer Fashion"
"""

def clean_name(raw: str) -> str:
    """Strip quotes, trailing punctuation, leading bullets; trim to 6 words max."""
    s = raw.strip()
    for q in ('"', "'", "`"):
        s = s.strip(q)
    s = s.strip(" -•:.\n")
    # Collapse to first line if multi-line
    s = s.split("\n")[0].strip()
    # Hard cap on word count (LLM occasionally exceeds the 4-word ask)
    words = s.split()
    if len(words) > 6:
        s = " ".join(words[:6])
    return s

print("Initializing Llama 3.1 (temperature=0)...")
llm = OllamaLLM(model="llama3.1:latest", temperature=0.0, num_predict=20)

results: dict[int, dict] = {}
total_calls = 0
total_latency = 0.0

print()
print("Generating names...")
print(f"{'Tid':>4} | {'Name (LLM)':<38} | {'n_v3':>5} | {'Industry':<22} | {'Latency':>8}")
print("-" * 95)

for tid in all_tids:
    meta = metas[tid]
    if tid == -1:
        name = "Outliers (mixed content)"
        latency = 0.0
        decision = "KEEP_AS_OTHER"
    else:
        prompt = PROMPT_TEMPLATE.format(
            keywords=", ".join(meta["keywords"]),
            hashtags=", ".join(f"#{h}" for h in meta["top_hashtags"]) or "(none)",
            industry=meta["industry_dominant"],
            brands=", ".join(meta["top_brands"]) or "(none)",
            n=meta["n_v3"],
            cap1=meta["example_captions"][0] if len(meta["example_captions"]) > 0 else "",
            cap2=meta["example_captions"][1] if len(meta["example_captions"]) > 1 else "",
            cap3=meta["example_captions"][2] if len(meta["example_captions"]) > 2 else "",
        )
        t0 = time.perf_counter()
        raw = llm.invoke(prompt)
        latency = time.perf_counter() - t0
        total_calls += 1
        total_latency += latency
        name = clean_name(raw)
        # Decision heuristics
        if meta["n_v3"] > 500:
            decision = "KEEP_BUT_BIG"
        elif meta["n_v3"] < 30:
            decision = "REVIEW_SMALL"
        else:
            decision = "KEEP"

    print(
        f"{tid:>4} | {name[:38]:<38} | {meta['n_v3']:>5} | "
        f"{meta['industry_dominant'][:22]:<22} | {latency:>6.2f}s"
    )

    results[tid] = {
        "name": name,
        "n_v3": meta["n_v3"],
        "keywords": meta["keywords"],
        "top_hashtags": meta["top_hashtags"],
        "top_brands": meta["top_brands"],
        "industry_dominant": meta["industry_dominant"],
        "industry_distribution": meta["industry_dist"],
        "example_captions": meta["example_captions"],
        "decision": decision,
    }

print("-" * 95)
print(f"Total Llama 3.1 calls: {total_calls}   Total LLM time: {total_latency:.1f}s   Avg: {total_latency/max(total_calls,1):.2f}s/call")

# ---------------------------------------------------------------------------
# Save YAML
# ---------------------------------------------------------------------------
output = {
    "_meta": {
        "generated_at": date.today().isoformat(),
        "source_master": str(MASTER),
        "source_v3": str(V3),
        "model_dir": str(MODEL_DIR),
        "llm": "llama3.1:latest",
        "llm_temperature": 0.0,
        "total_topics": len(all_tids),
        "total_outliers": metas[-1]["n_v3"],
        "total_v3_posts": int(len(df_m)),
        "generation_method": (
            "LLM-based naming using BERTopic c-TF-IDF keywords + V3 hashtags + "
            "industry distribution + top brands + 3 highest-engagement example captions"
        ),
    },
    "topics": {int(tid): results[tid] for tid in all_tids},
}

with open(OUT, "w", encoding="utf-8") as f:
    yaml.safe_dump(output, f, sort_keys=False, allow_unicode=True, width=120)

print(f"\nSaved: {OUT}")

# ---------------------------------------------------------------------------
# Brief analysis
# ---------------------------------------------------------------------------
print()
print("=" * 95)
print("ANALYSIS")
print("=" * 95)

# Detect potentially weak names
weak_names = []
for tid, r in results.items():
    if tid == -1:
        continue
    n = r["name"].lower()
    # Heuristic: very short, all-stopwords, or just industry name
    if len(n) < 4 or n in {"mixed", "other", "general", "various"}:
        weak_names.append((tid, r["name"]))

# Detect mismatches between LLM name and dominant industry
mismatches = []
INDUSTRY_HINTS = {
    "patisserie": ["pastry", "bakery", "cake", "patisserie", "dessert", "sweet"],
    "hotels": ["hotel", "resort", "stay", "tourism", "vacation"],
    "restaurants": ["restaurant", "food", "dining", "cuisine", "meal", "eat"],
    "fashion": ["fashion", "clothing", "apparel", "outfit", "wear", "style", "denim", "collection"],
    "beauty": ["beauty", "skin", "skincare", "cosmetic", "makeup", "hair", "perfume", "fragrance"],
}
for tid, r in results.items():
    if tid == -1:
        continue
    dom = r["industry_dominant"].split(" (")[0]
    name_lower = r["name"].lower()
    expected = INDUSTRY_HINTS.get(dom, [])
    # If a strong industry concentration exists (>=80%) and the LLM name doesn't reflect it
    pct = r["industry_distribution"].get(dom, 0)
    if pct >= 80 and expected and not any(k in name_lower for k in expected):
        # Also check if the LLM name mentions a *different* industry's keywords
        wrong = []
        for other_ind, kws in INDUSTRY_HINTS.items():
            if other_ind == dom:
                continue
            if any(k in name_lower for k in kws):
                wrong.append(other_ind)
        mismatches.append((tid, r["name"], f"{dom} ({pct:.0f}%)", wrong))

print(f"\nNames that look weak/generic (need review): {len(weak_names)}")
for tid, n in weak_names:
    print(f"  Topic {tid:>2}: '{n}'")

print(f"\nNames where LLM may have ignored dominant industry (>=80% concentration): {len(mismatches)}")
for tid, name, dom, wrong in mismatches:
    wrong_str = f" -> reads as: {wrong}" if wrong else ""
    print(f"  Topic {tid:>2}: '{name}'   (dominant: {dom}){wrong_str}")

# Topics LLM might find hard to name (mixed industry, no brand dominance)
hard = []
for tid, r in results.items():
    if tid == -1:
        continue
    dist = r["industry_distribution"]
    top_pct = max(dist.values()) if dist else 0
    if top_pct < 35:  # no industry holds >=35%
        hard.append((tid, r["name"], top_pct))
print(f"\nTopics with no clear industry dominance (top <35%, hard to name): {len(hard)}")
for tid, name, pct in hard:
    print(f"  Topic {tid:>2}: '{name}'   (top industry only {pct:.0f}%)")

print()
