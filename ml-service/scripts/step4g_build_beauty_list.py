"""
Step 4g — Build Beauty post list for multimodal scraping (Phase 1).

Filters df_master_masked_with_topics.parquet to industry_simple == 'beauty'
and writes ml-service/data/step4/beauty_posts_list.json.
"""
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PARQUET = ROOT / "data" / "df_master_masked_with_topics.parquet"
OUT = ROOT / "data" / "step4" / "beauty_posts_list.json"

df = pd.read_parquet(PARQUET)
beauty = df[df["industry_simple"] == "beauty"].copy()

records = []
for _, r in beauty.iterrows():
    records.append({
        "post_id": str(r["post_id"]),
        "post_url": str(r["post_url"]),
        "username": str(r["username"]),
        "content_type": str(r["content_type"]),
        "slide_count": (int(r["slide_count"]) if pd.notna(r["slide_count"]) else None),
    })

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")

print(f"Wrote {len(records)} beauty posts -> {OUT}")
print()
print("Content-type breakdown:")
print(beauty["content_type"].value_counts().to_string())

carousels = beauty[beauty["content_type"] == "carousel"]
if len(carousels):
    avg_sl = carousels["slide_count"].dropna().mean()
    total_slides = carousels["slide_count"].dropna().sum()
    print()
    print(f"Carousels: {len(carousels)} posts, "
          f"avg {avg_sl:.2f} slides, total ~{int(total_slides)} slides")

print()
print("Top 10 brands by post count:")
print(beauty["username"].value_counts().head(10).to_string())

# URL sanity check
n_url_ok = beauty["post_url"].astype(str).str.startswith("https://").sum()
print()
print(f"post_url valid (https://): {n_url_ok}/{len(beauty)} "
      f"({n_url_ok/len(beauty)*100:.1f}%)")
