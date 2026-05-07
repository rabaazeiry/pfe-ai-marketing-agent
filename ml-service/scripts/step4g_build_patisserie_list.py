"""
Step 4g Phase 5 — Build Patisserie post list for multimodal scraping.
Verifies the exact industry-name spelling in the parquet first.
"""
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PARQUET = ROOT / "data" / "df_master_masked_with_topics.parquet"
OUT = ROOT / "data" / "step4" / "patisserie_posts_list.json"

df = pd.read_parquet(PARQUET)

print("All industry_simple values:")
print(df["industry_simple"].value_counts(dropna=False).to_string())
print()

# Pick whatever spelling is present (patisserie / patisseries / pâtisserie / pastry / ...)
candidates = {str(x).lower() for x in df["industry_simple"].dropna().unique()}
target = None
for needle in ("patisserie", "patisseries", "pâtisserie", "pâtisseries", "pastry"):
    for raw in df["industry_simple"].dropna().unique():
        if str(raw).lower() == needle:
            target = raw
            break
    if target:
        break
if target is None:
    raise SystemExit(f"[FATAL] no patisserie-like industry found among: {sorted(candidates)}")
print(f"Resolved industry label: {target!r}")

sub = df[df["industry_simple"] == target].copy()

records = []
for _, r in sub.iterrows():
    records.append({
        "post_id": str(r["post_id"]),
        "post_url": str(r["post_url"]),
        "username": str(r["username"]),
        "content_type": str(r["content_type"]),
        "slide_count": (int(r["slide_count"]) if pd.notna(r["slide_count"]) else None),
    })

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")

print(f"\nWrote {len(records)} {target} posts -> {OUT}")
print()
print("Content-type breakdown:")
print(sub["content_type"].value_counts().to_string())

car = sub[sub["content_type"] == "carousel"]
if len(car):
    avg_sl = car["slide_count"].dropna().mean()
    total_slides = car["slide_count"].dropna().sum()
    print()
    print(f"Carousels: {len(car)} posts, avg {avg_sl:.2f} slides, total ~{int(total_slides)} slides")

print()
print("Top 10 brands by post count:")
print(sub["username"].value_counts().head(10).to_string())

n_url_ok = sub["post_url"].astype(str).str.startswith("https://").sum()
print()
print(f"post_url valid (https://): {n_url_ok}/{len(sub)} ({n_url_ok/len(sub)*100:.1f}%)")
