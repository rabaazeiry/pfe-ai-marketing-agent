"""
Step 4g — Phase 5 pre-flight: run Apify Instagram Scraper on 10 Patisserie
posts (3 photo + 3 carousel + 4 reel — reel-heavy for Patisserie content mix).
"""
import json
import os
import random
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv
from PIL import Image
from io import BytesIO

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT.parent / "backend" / ".env"
load_dotenv(ENV)
APIFY_TOKEN = os.environ.get("APIFY_API_KEY")
if not APIFY_TOKEN:
    print("[FATAL] APIFY_API_KEY missing")
    sys.exit(2)

from apify_client import ApifyClient

ACTOR_ID = "apify/instagram-scraper"

POSTS_JSON = ROOT / "data" / "step4" / "patisserie_posts_list.json"
META_DIR = ROOT / "data" / "step4" / "metadata"
PHOTOS_DIR = ROOT / "data" / "step4" / "images" / "photos"
SLIDES_DIR = ROOT / "data" / "step4" / "images" / "carousel_slides"
THUMBS_DIR = ROOT / "data" / "step4" / "images" / "reel_thumbs"
VIDEOS_DIR = ROOT / "data" / "step4" / "videos"
for d in (META_DIR, PHOTOS_DIR, SLIDES_DIR, THUMBS_DIR, VIDEOS_DIR):
    d.mkdir(parents=True, exist_ok=True)

RAW_OUT = META_DIR / "apify_patisserie_preflight.json"
RUN_OUT = META_DIR / "apify_patisserie_preflight_run.json"

random.seed(42)
posts = json.loads(POSTS_JSON.read_text(encoding="utf-8"))

by_type = {"photo": [], "carousel": [], "reel": []}
for p in posts:
    if p["content_type"] in by_type:
        by_type[p["content_type"]].append(p)

sample = (
    random.sample(by_type["photo"], 3)
    + random.sample(by_type["carousel"], 3)
    + random.sample(by_type["reel"], 4)
)
print(f"Pre-flight sample: {len(sample)} posts (3p+3c+4r — reel-heavy for Patisserie)")
url_to_post = {p["post_url"]: p for p in sample}
direct_urls = [p["post_url"] for p in sample]
print("URLs:")
for p in sample:
    print(f"  [{p['content_type']:8}] {p['post_id']}  {p['post_url']}")

run_input = {
    "directUrls": direct_urls,
    "resultsType": "posts",
    "resultsLimit": 1,
    "addParentData": False,
}

print("\nLaunching Apify actor:", ACTOR_ID)
t0 = time.time()
client = ApifyClient(APIFY_TOKEN)
run = client.actor(ACTOR_ID).call(run_input=run_input, wait_secs=600)
elapsed = time.time() - t0
print(f"Run finished in {elapsed:.1f}s — id={run['id']} status={run['status']}")

# Persist run metadata (esp. usage/cost)
run_meta = {
    "id": run.get("id"),
    "status": run.get("status"),
    "startedAt": str(run.get("startedAt")),
    "finishedAt": str(run.get("finishedAt")),
    "usage": run.get("usage"),
    "usageTotalUsd": run.get("usageTotalUsd"),
    "stats": run.get("stats"),
    "defaultDatasetId": run.get("defaultDatasetId"),
}
RUN_OUT.write_text(json.dumps(run_meta, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
print(f"Run meta -> {RUN_OUT}")
print(f"  usageTotalUsd = {run.get('usageTotalUsd')}")

# Pull dataset items
items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
RAW_OUT.write_text(json.dumps(items, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
print(f"Dataset -> {RAW_OUT}  ({len(items)} items)")

# Validate per type
def get_field(item, *names):
    for n in names:
        if n in item and item[n]:
            return item[n]
    return None

results = {"photo": [], "carousel": [], "reel": []}
for item in items:
    url = item.get("url") or item.get("inputUrl") or ""
    matched = url_to_post.get(url)
    if not matched:
        # Apify sometimes returns a normalized URL — match by shortcode
        sc = item.get("shortCode") or item.get("shortcode")
        if sc:
            for p in sample:
                if f"/p/{sc}/" in p["post_url"] or f"/reel/{sc}/" in p["post_url"]:
                    matched = p
                    break
    ct = matched["content_type"] if matched else "?"
    record = {
        "expected_type": ct,
        "post_id": matched["post_id"] if matched else None,
        "url": url,
        "type_field": item.get("type"),
        "displayUrl": get_field(item, "displayUrl", "display_url"),
        "videoUrl": get_field(item, "videoUrl", "video_url"),
        "images": item.get("images"),
        "childPosts": [
            {
                "displayUrl": get_field(c, "displayUrl", "display_url"),
                "videoUrl": get_field(c, "videoUrl", "video_url"),
            }
            for c in (item.get("childPosts") or [])
        ],
        "thumb_candidates": [
            item.get("thumbnailUrl"),
            item.get("thumbnail"),
            get_field(item, "displayUrl", "display_url"),
        ],
    }
    if ct in results:
        results[ct].append(record)
    else:
        results.setdefault("?", []).append(record)

print("\n=== Validation ===")
for ct in ("photo", "carousel", "reel"):
    print(f"\n{ct.upper()}: {len(results[ct])} returned")
    for r in results[ct]:
        if ct == "photo":
            ok = bool(r["displayUrl"])
            print(f"  {r['post_id']}: displayUrl={'OK' if ok else 'MISSING'}")
        elif ct == "carousel":
            n = len(r["childPosts"]) or len(r.get("images") or [])
            print(f"  {r['post_id']}: {n} slides")
        elif ct == "reel":
            ok_v = bool(r["videoUrl"])
            ok_t = any(r["thumb_candidates"])
            print(f"  {r['post_id']}: video={'OK' if ok_v else 'MISSING'} thumb={'OK' if ok_t else 'MISSING'}")

# --- Download 1 sample of each format -----------------------------------
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}
def download(url, dest):
    if not url:
        return False, "no url"
    try:
        r = requests.get(url, headers=HEADERS, timeout=60, stream=True)
        r.raise_for_status()
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "wb") as f:
            for chunk in r.iter_content(64 * 1024):
                f.write(chunk)
        return True, dest.stat().st_size
    except Exception as e:
        return False, str(e)

def resize_inplace(p, size=(224, 224)):
    try:
        with Image.open(p) as im:
            im = im.convert("RGB")
            im = im.resize(size, Image.LANCZOS)
            im.save(p, "JPEG", quality=90)
        return True
    except Exception as e:
        return f"resize failed: {e}"

print("\n=== Sample downloads ===")
# Photo
if results["photo"]:
    r = results["photo"][0]
    ok, info = download(r["displayUrl"], PHOTOS_DIR / f"{r['post_id']}.jpg")
    print(f"photo {r['post_id']}: dl={ok} {info}")
    if ok:
        print("  resize:", resize_inplace(PHOTOS_DIR / f"{r['post_id']}.jpg"))
# Carousel — first slide of first carousel
if results["carousel"]:
    r = results["carousel"][0]
    if r["childPosts"]:
        slide_url = r["childPosts"][0]["displayUrl"]
    else:
        slide_url = (r.get("images") or [None])[0]
    ok, info = download(slide_url, SLIDES_DIR / f"{r['post_id']}_slide_0.jpg")
    print(f"carousel slide {r['post_id']}: dl={ok} {info}")
    if ok:
        print("  resize:", resize_inplace(SLIDES_DIR / f"{r['post_id']}_slide_0.jpg"))
# Reel
if results["reel"]:
    r = results["reel"][0]
    thumb_url = next((u for u in r["thumb_candidates"] if u), None)
    ok_t, info_t = download(thumb_url, THUMBS_DIR / f"{r['post_id']}_thumb.jpg")
    print(f"reel thumb {r['post_id']}: dl={ok_t} {info_t}")
    if ok_t:
        print("  resize:", resize_inplace(THUMBS_DIR / f"{r['post_id']}_thumb.jpg"))
    ok_v, info_v = download(r["videoUrl"], VIDEOS_DIR / f"{r['post_id']}.mp4")
    print(f"reel video {r['post_id']}: dl={ok_v} {info_v}")

# --- Cost projections ---------------------------------------------------
total_cost = run.get("usageTotalUsd") or 0
per_post = total_cost / max(1, len(items))
print("\n=== Cost projections ===")
print(f"Pre-flight cost (10 posts) : ${total_cost:.4f}")
print(f"Avg cost / post            : ${per_post:.4f}")
print(f"Projected for 745 Patiss.  : ${per_post * 745:.2f}")
print(f"Projected runtime (Apify)  : ~{elapsed/len(items)*745/3600:.2f} h "
      f"(based on {elapsed/len(items):.1f} s/post)")

print("\n=== Done — STOP for user approval before launching full Patisserie run. ===")
