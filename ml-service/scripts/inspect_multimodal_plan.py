"""
Inspect dataset to plan multimodal scraping for Beauty + Fashion industries.
Reports counts by industry and content_type, plus cost / storage / time estimates.
"""
import pandas as pd
from pathlib import Path

PARQUET = Path(__file__).resolve().parents[1] / "data" / "df_master_masked_with_topics.parquet"

df = pd.read_parquet(PARQUET)

print("=" * 64)
print("STEP 1-2 — DATASET DISTRIBUTION")
print("=" * 64)
print(f"Parquet: {PARQUET}")
print(f"Shape: {df.shape}")
print(f"Columns: {list(df.columns)}")
print()

total = len(df)
print(f"Total posts: {total}")
print()

# Industry column detection
industry_col = None
for c in ["industry_simple", "industry", "industry_label"]:
    if c in df.columns:
        industry_col = c
        break
print(f"Industry column: {industry_col}")
if industry_col:
    counts = df[industry_col].value_counts(dropna=False)
    print(counts.to_string())
    print(f"Sum: {counts.sum()} (matches total: {counts.sum() == total})")
print()

# Content type column detection
ct_col = None
for c in ["content_type", "media_type", "type", "post_type"]:
    if c in df.columns:
        ct_col = c
        break
print(f"Content-type column: {ct_col}")
if ct_col:
    print(df[ct_col].value_counts(dropna=False).to_string())
print()

# Slides column detection
slides_col = None
for c in ["slide_count", "slides_count", "carousel_count", "n_slides", "media_count", "num_slides"]:
    if c in df.columns:
        slides_col = c
        break
print(f"Slides column: {slides_col}")
print()

print("=" * 64)
print("STEP 3 — BEAUTY + FASHION BREAKDOWN")
print("=" * 64)

if industry_col is None or ct_col is None:
    print("Cannot continue — missing industry or content_type column.")
    raise SystemExit(1)

target_industries = []
unique_inds = [str(x).lower() for x in df[industry_col].dropna().unique()]
print(f"Available industries (lowercased): {unique_inds}")

# Pick exact matches case-insensitively
ind_map = {}
for ind in df[industry_col].dropna().unique():
    if str(ind).lower() in ("beauty", "fashion"):
        ind_map[str(ind).lower()] = ind
print(f"Matched: {ind_map}")
print()

breakdown = {}  # industry_lower -> {content_type -> count, plus avg_slides}
for key in ("beauty", "fashion"):
    if key not in ind_map:
        print(f"[WARN] '{key}' not found in dataset.")
        continue
    sub = df[df[industry_col] == ind_map[key]]
    print(f"--- {key.title()} ({ind_map[key]}) — total = {len(sub)} ---")
    by_ct = sub[ct_col].value_counts(dropna=False)
    print(by_ct.to_string())
    avg_slides = None
    if slides_col:
        # average slides only on carousel
        carousel_mask = sub[ct_col].astype(str).str.lower().isin(["carousel", "sidecar", "album"])
        if carousel_mask.any():
            avg_slides = float(sub.loc[carousel_mask, slides_col].dropna().mean())
            print(f"Avg slides per carousel: {avg_slides:.2f}")
    breakdown[key] = {"counts": by_ct.to_dict(), "avg_slides": avg_slides, "total": len(sub)}
    print()


def get_count(industry_key, *type_aliases):
    if industry_key not in breakdown:
        return 0
    counts = breakdown[industry_key]["counts"]
    total = 0
    for k, v in counts.items():
        if str(k).lower() in [a.lower() for a in type_aliases]:
            total += int(v)
    return total


print("=" * 64)
print("STEP 4 — COST ESTIMATION (Apify)")
print("=" * 64)
print("Pricing: Photo $0.002 | Carousel $0.003 + $0.001/extra slide | Reel $0.008")
print()

PHOTO_COST = 0.002
CAROUSEL_BASE = 0.003
CAROUSEL_EXTRA = 0.001
REEL_COST = 0.008

industry_totals = {}
for key in ("beauty", "fashion"):
    if key not in breakdown:
        continue
    photos = get_count(key, "photo", "image")
    carousels = get_count(key, "carousel", "sidecar", "album")
    reels = get_count(key, "reel", "video")

    avg_slides = breakdown[key]["avg_slides"]
    avg_slides_used = avg_slides if avg_slides else 5.0
    carousel_unit = CAROUSEL_BASE + CAROUSEL_EXTRA * max(0, avg_slides_used - 1)

    photo_cost = photos * PHOTO_COST
    carousel_cost = carousels * carousel_unit
    reel_cost = reels * REEL_COST
    sub_total = photo_cost + carousel_cost + reel_cost
    industry_totals[key] = sub_total

    print(f"Industry: {key.title()}")
    print(f"  Photos     : {photos} posts × ${PHOTO_COST:.3f} = ${photo_cost:.2f}")
    print(f"  Carousels  : {carousels} posts × ${carousel_unit:.3f} (avg {avg_slides_used:.1f} slides) = ${carousel_cost:.2f}")
    print(f"  Reels      : {reels} posts × ${REEL_COST:.3f} = ${reel_cost:.2f}")
    print(f"  Total {key.title()} : ${sub_total:.2f}")
    print()

grand = sum(industry_totals.values())
print(f"GRAND TOTAL Beauty + Fashion : ${grand:.2f}")
free_plan = 5.0
covered_pct = min(100.0, free_plan / grand * 100) if grand > 0 else 100.0
print(f"Free Plan ($5) covers : {covered_pct:.1f}%")
print(f"You need to pay : ${max(0.0, grand - free_plan):.2f}")
print()

print("=" * 64)
print("STEP 5 — STORAGE ESTIMATION")
print("=" * 64)
PHOTO_KB = 200
SLIDE_KB = 200
REEL_VIDEO_MB = 30
REEL_THUMB_KB = 100

storage_totals = {}
for key in ("beauty", "fashion"):
    if key not in breakdown:
        continue
    photos = get_count(key, "photo", "image")
    carousels = get_count(key, "carousel", "sidecar", "album")
    reels = get_count(key, "reel", "video")
    avg_slides = breakdown[key]["avg_slides"] or 5.0

    photo_mb = photos * PHOTO_KB / 1024
    slide_mb = carousels * avg_slides * SLIDE_KB / 1024
    reel_video_gb = reels * REEL_VIDEO_MB / 1024
    reel_thumb_mb = reels * REEL_THUMB_KB / 1024
    subtotal_gb = (photo_mb + slide_mb + reel_thumb_mb) / 1024 + reel_video_gb
    storage_totals[key] = subtotal_gb

    print(f"{key.title()}:")
    print(f"  Photos          : {photo_mb:.1f} MB")
    print(f"  Carousel slides : {slide_mb:.1f} MB ({carousels} × {avg_slides:.1f} slides)")
    print(f"  Reel videos     : {reel_video_gb:.2f} GB")
    print(f"  Reel thumbs     : {reel_thumb_mb:.1f} MB")
    print(f"  Subtotal        : {subtotal_gb:.2f} GB")
    print()

print(f"GRAND TOTAL: {sum(storage_totals.values()):.2f} GB")
print()

print("=" * 64)
print("STEP 6 — TIME ESTIMATION")
print("=" * 64)
APIFY_SEC = 45         # avg per post
PHOTO_DL = 1.5
SLIDE_DL = 6
REEL_DL = 45
CLIP_EMB = 0.75
FRAME_EXTRACT = 7

total_posts = 0
total_seconds = 0
for key in ("beauty", "fashion"):
    if key not in breakdown:
        continue
    photos = get_count(key, "photo", "image")
    carousels = get_count(key, "carousel", "sidecar", "album")
    reels = get_count(key, "reel", "video")
    avg_slides = breakdown[key]["avg_slides"] or 5.0

    posts = photos + carousels + reels
    apify = posts * APIFY_SEC
    dl = photos * PHOTO_DL + carousels * SLIDE_DL + reels * REEL_DL
    embed = (photos + carousels * avg_slides) * CLIP_EMB + reels * FRAME_EXTRACT
    sec = apify + dl + embed
    total_posts += posts
    total_seconds += sec
    print(f"{key.title()}: {posts} posts -> {sec/3600:.1f} h "
          f"(apify {apify/3600:.1f}h + dl {dl/3600:.1f}h + embed {embed/3600:.1f}h)")

print()
print(f"GRAND TOTAL: {total_posts} posts -> {total_seconds/3600:.1f} h "
      f"({total_seconds/3600/24:.2f} days)")
print()

print("=" * 64)
print("STEP 7 — RECOMMENDATION")
print("=" * 64)
print(f"Full Beauty + Fashion cost : ${grand:.2f}")
print(f"Free Plan budget           : $5.00")
if grand <= free_plan:
    print("VERDICT: GO — full extraction fits within free $5 budget.")
else:
    over = grand - free_plan
    sample_per_industry = 200
    # estimate per-post avg cost
    total_p = sum(get_count(k, "photo", "image") + get_count(k, "carousel", "sidecar", "album") + get_count(k, "reel", "video") for k in ("beauty", "fashion") if k in breakdown)
    per_post = grand / total_p if total_p else 0
    sample_cost = sample_per_industry * 2 * per_post
    print(f"VERDICT: NO-GO on full extraction (over by ${over:.2f}).")
    print(f"Suggested sample: {sample_per_industry} posts/industry -> ~${sample_cost:.2f} total "
          f"(avg ${per_post:.4f}/post).")
    # also compute biggest sample that fits in $5
    fit_total = int(free_plan / per_post) if per_post else 0
    print(f"Largest sample that fits in $5: {fit_total} posts total "
          f"(~{fit_total // 2} per industry).")
print()
print("STOP — no scraping started. Awaiting user decision.")
