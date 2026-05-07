"""
Step 4g — Reorganize multimodal media into industry-based subfolders.

Source files (kept intact, used as backup):
  data/step4/images/photos/<post_id>.jpg
  data/step4/images/carousel_slides/<post_id>_slide_N.jpg
  data/step4/images/reel_thumbs/<post_id>_thumb.jpg
  data/step4/videos/<post_id>.mp4

Destination (copies, not moves):
  data/step4/by_industry/<industry>/{photos,carousel_slides,reel_thumbs,videos}/<filename>

Industry resolved from df_master_masked_with_topics.parquet via post_id lookup.
Idempotent: skips when destination already exists.
"""
import json
import random
import shutil
from pathlib import Path

import pandas as pd
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
PARQUET = ROOT / "data" / "df_master_masked_with_topics.parquet"
SRC = ROOT / "data" / "step4"
DEST = SRC / "by_industry"

INDUSTRIES = ("beauty", "fashion", "hotels", "restaurants", "patisserie")
SUBKINDS = {
    "photos":           {"src": SRC / "images" / "photos",          "ext": ".jpg"},
    "carousel_slides":  {"src": SRC / "images" / "carousel_slides", "ext": ".jpg"},
    "reel_thumbs":      {"src": SRC / "images" / "reel_thumbs",     "ext": ".jpg"},
    "videos":           {"src": SRC / "videos",                     "ext": ".mp4"},
}

# ---------- STEP 1: build mapping --------------------------------------------
print("=" * 64)
print("STEP 1 — Building post_id -> industry mapping")
print("=" * 64)
df = pd.read_parquet(PARQUET)
df = df[df["industry_simple"].isin(INDUSTRIES)][["post_id", "industry_simple"]].copy()
df["post_id"] = df["post_id"].astype(str)
mapping = dict(zip(df["post_id"], df["industry_simple"].astype(str)))
print(f"Mapped {len(mapping)} post_ids")
print(df["industry_simple"].value_counts().to_string())
print()


# ---------- STEP 2: create destination tree ----------------------------------
print("=" * 64)
print("STEP 2 — Creating destination tree")
print("=" * 64)
for ind in INDUSTRIES:
    for kind in SUBKINDS:
        (DEST / ind / kind).mkdir(parents=True, exist_ok=True)
print(f"Created tree under {DEST}")
print()


# ---------- STEP 3: copy files -----------------------------------------------
def post_id_from_name(name: str, kind: str) -> str:
    if kind == "photos":          # <post_id>.jpg
        return name.removesuffix(".jpg")
    if kind == "videos":          # <post_id>.mp4
        return name.removesuffix(".mp4")
    if kind == "reel_thumbs":     # <post_id>_thumb.jpg
        return name.removesuffix(".jpg").removesuffix("_thumb")
    if kind == "carousel_slides": # <post_id>_slide_N.jpg
        stem = name.removesuffix(".jpg")
        # strip trailing "_slide_<digits>"
        if "_slide_" in stem:
            return stem.rsplit("_slide_", 1)[0]
        return stem
    return name


print("=" * 64)
print("STEP 3 — Copying files")
print("=" * 64)

stats = {ind: {k: 0 for k in SUBKINDS} for ind in INDUSTRIES}
skipped_existing = {ind: {k: 0 for k in SUBKINDS} for ind in INDUSTRIES}
orphans = []  # (kind, filename, post_id)

for kind, cfg in SUBKINDS.items():
    src_dir = cfg["src"]
    ext = cfg["ext"]
    if not src_dir.exists():
        print(f"  [{kind}] source dir missing: {src_dir} — skipping")
        continue
    files = list(src_dir.glob(f"*{ext}"))
    print(f"  [{kind}] {len(files)} source files")
    for fp in files:
        pid = post_id_from_name(fp.name, kind)
        ind = mapping.get(pid)
        if ind is None:
            orphans.append((kind, fp.name, pid))
            continue
        dest = DEST / ind / kind / fp.name
        if dest.exists() and dest.stat().st_size > 0:
            skipped_existing[ind][kind] += 1
            continue
        shutil.copy2(fp, dest)
        stats[ind][kind] += 1

print()
print(f"Orphans (post_id not in beauty/fashion parquet rows): {len(orphans)}")
if orphans:
    for o in orphans[:10]:
        print(f"  {o[0]}: {o[1]} -> id={o[2]}")
print()


# ---------- STEP 4: validation -----------------------------------------------
print("=" * 64)
print("STEP 4 — Validation")
print("=" * 64)
counts_on_disk = {
    ind: {k: len(list((DEST / ind / k).glob("*"))) for k in SUBKINDS}
    for ind in INDUSTRIES
}
for ind in INDUSTRIES:
    print(f"  {ind}:")
    for k, n in counts_on_disk[ind].items():
        print(f"    {k:18s}: {n} files (newly copied: {stats[ind][k]}, skipped existing: {skipped_existing[ind][k]})")

# Random sample integrity + industry-tag verification
rng = random.Random(7)
all_files = []
for ind in INDUSTRIES:
    for k in SUBKINDS:
        for fp in (DEST / ind / k).glob("*"):
            all_files.append((ind, k, fp))
sample = rng.sample(all_files, min(5, len(all_files)))
print()
print("Random sample check (5 files):")
for ind, k, fp in sample:
    pid = post_id_from_name(fp.name, k)
    expected = mapping.get(pid, "?")
    ok_ind = (expected == ind)
    if k == "videos":
        ok_open = fp.stat().st_size > 50_000
        info = f"size={fp.stat().st_size}"
    else:
        try:
            with Image.open(fp) as im:
                im.verify()
            ok_open = True
            info = "JPEG verify OK"
        except Exception as e:
            ok_open = False
            info = f"JPEG err: {e}"
    print(f"  [{ind}/{k}] {fp.name}  industry_match={ok_ind}  {info}")


# ---------- STEP 5: summary report -------------------------------------------
print()
print("=" * 64)
print("FILES BY INDUSTRY (after reorganization)")
print("=" * 64)
grand = 0
for ind in INDUSTRIES:
    sub_total = sum(counts_on_disk[ind].values())
    grand += sub_total
    print(f"\nIndustry: {ind.upper()}")
    print(f"  Photos          : {counts_on_disk[ind]['photos']} files")
    print(f"  Carousel slides : {counts_on_disk[ind]['carousel_slides']} files")
    print(f"  Reel thumbs     : {counts_on_disk[ind]['reel_thumbs']} files")
    print(f"  Reel videos     : {counts_on_disk[ind]['videos']} files")
    print(f"  Total {ind:7s}   : {sub_total} files")
print()
print(f"GRAND TOTAL : {grand} files")
print()

# Storage impact
def dir_size_bytes(p: Path) -> int:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())

orig_bytes = sum(dir_size_bytes(cfg["src"]) for cfg in SUBKINDS.values())
new_bytes = dir_size_bytes(DEST)
print("Storage impact:")
print(f"  Original (flat dirs)         : {orig_bytes/1024**3:.2f} GB")
print(f"  Duplicate (by_industry tree) : {new_bytes/1024**3:.2f} GB")
print(f"  Total used                   : {(orig_bytes + new_bytes)/1024**3:.2f} GB")
print()
print(f"Original files preserved at : {SRC}/{{photos,carousel_slides,reel_thumbs,videos}}/")
print(f"New organized files at      : {DEST}")

# Save manifest
manifest = {
    "by_industry_counts": counts_on_disk,
    "newly_copied_this_run": stats,
    "skipped_existing_this_run": skipped_existing,
    "orphans_count": len(orphans),
    "orphans_sample": [{"kind": k, "filename": f, "post_id": p} for (k, f, p) in orphans[:50]],
    "storage": {
        "originals_gb": round(orig_bytes / 1024**3, 3),
        "duplicate_gb": round(new_bytes / 1024**3, 3),
    },
}
manifest_path = SRC / "metadata" / "by_industry_manifest.json"
manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"Manifest written to         : {manifest_path}")
