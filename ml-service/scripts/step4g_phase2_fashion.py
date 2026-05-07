"""
Step 4g Phase 2 — Full multimodal scrape for FASHION industry (842 posts).

Pipeline mirrors Phase 1 Beauty:
  Step 4 — Apify Instagram Scraper (apify/instagram-scraper) on all 842 URLs
  Step 5 — Download photos / carousel slides / reel videos+thumbnails locally
  Step 6 — Validate counts + sample integrity
  Step 7 — Print final report

Idempotent. Output dirs are shared with Phase 1 (photos/, carousel_slides/,
reel_thumbs/, videos/) — file names are post_id-based so there is no collision.
"""
import argparse
import json
import os
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from dotenv import load_dotenv
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT.parent / "backend" / ".env"
load_dotenv(ENV)
APIFY_TOKEN = os.environ.get("APIFY_API_KEY")
if not APIFY_TOKEN:
    print("[FATAL] APIFY_API_KEY missing")
    sys.exit(2)

from apify_client import ApifyClient

ACTOR_ID = "apify/instagram-scraper"

DATA = ROOT / "data" / "step4"
META_DIR = DATA / "metadata"
PHOTOS_DIR = DATA / "images" / "photos"
SLIDES_DIR = DATA / "images" / "carousel_slides"
THUMBS_DIR = DATA / "images" / "reel_thumbs"
VIDEOS_DIR = DATA / "videos"
for d in (META_DIR, PHOTOS_DIR, SLIDES_DIR, THUMBS_DIR, VIDEOS_DIR):
    d.mkdir(parents=True, exist_ok=True)

POSTS_JSON = DATA / "fashion_posts_list.json"
APIFY_DATASET_OUT = META_DIR / "apify_fashion.json"
APIFY_RUN_OUT = META_DIR / "apify_fashion_run.json"
DOWNLOAD_LOG = META_DIR / "fashion_download_log.json"
FINAL_REPORT = META_DIR / "fashion_phase2_report.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}
TIMEOUT_IMG = 45
TIMEOUT_VIDEO = 240


def log(msg):
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


# ----------------------------- STEP 4: SCRAPE --------------------------------
def step4_scrape(posts, rescrape=False):
    if APIFY_DATASET_OUT.exists() and not rescrape:
        log(f"STEP 4 — reusing existing dataset {APIFY_DATASET_OUT.name}")
        items = json.loads(APIFY_DATASET_OUT.read_text(encoding="utf-8"))
        run_meta = (
            json.loads(APIFY_RUN_OUT.read_text(encoding="utf-8"))
            if APIFY_RUN_OUT.exists() else {}
        )
        return items, run_meta

    direct_urls = [p["post_url"] for p in posts]
    run_input = {
        "directUrls": direct_urls,
        "resultsType": "posts",
        "resultsLimit": 1,
        "addParentData": False,
    }
    log(f"STEP 4 — launching Apify on {len(direct_urls)} URLs")
    t0 = time.time()
    client = ApifyClient(APIFY_TOKEN)
    run = client.actor(ACTOR_ID).call(run_input=run_input, wait_secs=7200)
    elapsed = time.time() - t0
    log(f"Apify run finished in {elapsed/60:.1f} min — id={run['id']} "
        f"status={run['status']} cost=${run.get('usageTotalUsd')}")

    run_meta = {
        "id": run.get("id"),
        "status": run.get("status"),
        "startedAt": str(run.get("startedAt")),
        "finishedAt": str(run.get("finishedAt")),
        "elapsed_seconds": elapsed,
        "usage": run.get("usage"),
        "usageTotalUsd": run.get("usageTotalUsd"),
        "stats": run.get("stats"),
        "defaultDatasetId": run.get("defaultDatasetId"),
    }
    APIFY_RUN_OUT.write_text(
        json.dumps(run_meta, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
    APIFY_DATASET_OUT.write_text(
        json.dumps(items, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    log(f"Saved dataset ({len(items)} items) -> {APIFY_DATASET_OUT.name}")
    return items, run_meta


# ----------------------------- STEP 5: DOWNLOADS -----------------------------
def get_field(d, *names):
    for n in names:
        v = d.get(n) if isinstance(d, dict) else None
        if v:
            return v
    return None


def index_items(items):
    """Map post_id (shortCode) -> apify item."""
    by_short = {}
    for it in items:
        sc = get_field(it, "shortCode", "shortcode")
        if sc:
            by_short[sc] = it
            continue
        url = it.get("url", "") or ""
        for token in ("/p/", "/reel/", "/tv/"):
            if token in url:
                sc = url.split(token, 1)[1].rstrip("/").split("/", 1)[0]
                by_short[sc] = it
                break
    return by_short


def download_file(url, dest, timeout):
    if not url:
        return False, "no_url"
    if dest.exists() and dest.stat().st_size > 0:
        return True, "skip_existing"
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout, stream=True)
        r.raise_for_status()
        tmp = dest.with_suffix(dest.suffix + ".part")
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(64 * 1024):
                f.write(chunk)
        tmp.replace(dest)
        return True, dest.stat().st_size
    except Exception as e:
        return False, str(e)[:200]


def resize_jpeg(path, size=(224, 224)):
    try:
        with Image.open(path) as im:
            if im.size == size and im.mode == "RGB":
                return True
            im = im.convert("RGB").resize(size, Image.LANCZOS)
            im.save(path, "JPEG", quality=90)
        return True
    except Exception as e:
        return f"resize_fail: {e}"


def plan_jobs(posts, by_short):
    """Yield download jobs as tuples: (job_kind, url, dest_path, post_id, slide_idx_or_None)."""
    jobs = []
    missing_in_apify = []
    for p in posts:
        pid = p["post_id"]
        ct = p["content_type"]
        item = by_short.get(pid)
        if not item:
            missing_in_apify.append(pid)
            continue
        if ct == "photo":
            url = get_field(item, "displayUrl", "display_url")
            jobs.append(("photo", url, PHOTOS_DIR / f"{pid}.jpg", pid, None))
        elif ct == "carousel":
            children = item.get("childPosts") or []
            if not children:
                # fallback: images list (older Apify schema)
                children = [{"displayUrl": u} for u in (item.get("images") or [])]
            for idx, child in enumerate(children):
                url = get_field(child, "displayUrl", "display_url")
                jobs.append(
                    ("slide", url, SLIDES_DIR / f"{pid}_slide_{idx}.jpg", pid, idx)
                )
        elif ct == "reel":
            t_url = (
                get_field(item, "thumbnailUrl", "thumbnail")
                or get_field(item, "displayUrl", "display_url")
            )
            v_url = get_field(item, "videoUrl", "video_url")
            jobs.append(("reel_thumb", t_url, THUMBS_DIR / f"{pid}_thumb.jpg", pid, None))
            jobs.append(("reel_video", v_url, VIDEOS_DIR / f"{pid}.mp4", pid, None))
    return jobs, missing_in_apify


def step5_download(jobs):
    log(f"STEP 5 — {len(jobs)} download jobs")
    image_jobs = [j for j in jobs if j[0] != "reel_video"]
    video_jobs = [j for j in jobs if j[0] == "reel_video"]

    results = {"photo": {"ok": 0, "fail": 0, "skip": 0, "errors": []},
               "slide": {"ok": 0, "fail": 0, "skip": 0, "errors": []},
               "reel_thumb": {"ok": 0, "fail": 0, "skip": 0, "errors": []},
               "reel_video": {"ok": 0, "fail": 0, "skip": 0, "errors": []}}
    bytes_total = {"photo": 0, "slide": 0, "reel_thumb": 0, "reel_video": 0}

    def run_image(j):
        kind, url, dest, pid, _ = j
        ok, info = download_file(url, dest, TIMEOUT_IMG)
        if ok and info != "skip_existing":
            r = resize_jpeg(dest)
            if r is not True:
                return kind, "fail", f"{pid}: {r}", 0
            return kind, "ok", None, dest.stat().st_size
        if ok and info == "skip_existing":
            return kind, "skip", None, dest.stat().st_size
        return kind, "fail", f"{pid}: {info}", 0

    def run_video(j):
        kind, url, dest, pid, _ = j
        ok, info = download_file(url, dest, TIMEOUT_VIDEO)
        if ok and info == "skip_existing":
            return kind, "skip", None, dest.stat().st_size
        if ok:
            return kind, "ok", None, dest.stat().st_size
        return kind, "fail", f"{pid}: {info}", 0

    log(f"  image jobs: {len(image_jobs)} (8 workers)")
    done = 0
    with ThreadPoolExecutor(max_workers=8) as ex:
        for fut in as_completed([ex.submit(run_image, j) for j in image_jobs]):
            kind, status, err, sz = fut.result()
            results[kind][status] += 1
            bytes_total[kind] += sz
            if err:
                results[kind]["errors"].append(err)
            done += 1
            if done % 200 == 0:
                log(f"    images {done}/{len(image_jobs)}")

    log(f"  video jobs: {len(video_jobs)} (4 workers)")
    done = 0
    with ThreadPoolExecutor(max_workers=4) as ex:
        for fut in as_completed([ex.submit(run_video, j) for j in video_jobs]):
            kind, status, err, sz = fut.result()
            results[kind][status] += 1
            bytes_total[kind] += sz
            if err:
                results[kind]["errors"].append(err)
            done += 1
            if done % 50 == 0:
                log(f"    videos {done}/{len(video_jobs)}")

    summary = {"results": results, "bytes_total": bytes_total}
    DOWNLOAD_LOG.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary


# ----------------------------- STEP 6: VALIDATE ------------------------------
def step6_validate(posts):
    log("STEP 6 — validating sample integrity")
    photo_ids = [p["post_id"] for p in posts if p["content_type"] == "photo"]
    carousel_ids = [p["post_id"] for p in posts if p["content_type"] == "carousel"]
    reel_ids = [p["post_id"] for p in posts if p["content_type"] == "reel"]

    counts = {
        "photos_on_disk": len(list(PHOTOS_DIR.glob("*.jpg"))),
        "carousel_slides_on_disk": len(list(SLIDES_DIR.glob("*.jpg"))),
        "reel_thumbs_on_disk": len(list(THUMBS_DIR.glob("*.jpg"))),
        "reel_videos_on_disk": len(list(VIDEOS_DIR.glob("*.mp4"))),
        "expected_photos": len(photo_ids),
        "expected_carousels": len(carousel_ids),
        "expected_reels": len(reel_ids),
    }

    rng = random.Random(123)
    sample_imgs = []
    for ids, d in (
        (photo_ids, PHOTOS_DIR),
        (reel_ids, THUMBS_DIR),
    ):
        present = [pid for pid in ids if (d / f"{pid}.jpg").exists() or (d / f"{pid}_thumb.jpg").exists()]
        if present:
            for pid in rng.sample(present, min(2, len(present))):
                p = d / (f"{pid}_thumb.jpg" if d == THUMBS_DIR else f"{pid}.jpg")
                sample_imgs.append(p)
    # Add 1 carousel slide
    slides = list(SLIDES_DIR.glob("*.jpg"))
    if slides:
        sample_imgs.append(rng.choice(slides))

    img_check = []
    for p in sample_imgs[:5]:
        try:
            with Image.open(p) as im:
                im.verify()
            img_check.append({"path": str(p), "ok": True, "size_bytes": p.stat().st_size})
        except Exception as e:
            img_check.append({"path": str(p), "ok": False, "error": str(e)})

    videos = list(VIDEOS_DIR.glob("*.mp4"))
    video_check = []
    if videos:
        for v in rng.sample(videos, min(2, len(videos))):
            sz = v.stat().st_size
            ok = sz > 50_000  # crude
            video_check.append({"path": str(v), "size_bytes": sz, "ok_min_size": ok})

    return {"counts": counts, "image_sample": img_check, "video_sample": video_check}


# ----------------------------- STEP 7: REPORT --------------------------------
def step7_report(run_meta, dl_summary, validation, missing_in_apify, total_seconds):
    res = dl_summary["results"]
    bytes_total = dl_summary["bytes_total"]
    cost = run_meta.get("usageTotalUsd") or 0.0

    def total(k):
        return res[k]["ok"] + res[k]["skip"]

    storage_gb = sum(bytes_total.values()) / 1024**3
    free_remaining = max(0.0, 5.0 - cost)

    report = {
        "phase": "Fashion Phase 2",
        "total_posts_input": 842,
        "missing_in_apify": len(missing_in_apify),
        "missing_post_ids_sample": missing_in_apify[:20],
        "downloads": {
            "photos": {"ok": total("photo"), "expected": validation["counts"]["expected_photos"],
                       "fail": res["photo"]["fail"], "bytes": bytes_total["photo"]},
            "carousel_slides": {"ok": total("slide"),
                                "fail": res["slide"]["fail"], "bytes": bytes_total["slide"]},
            "reel_thumbs": {"ok": total("reel_thumb"),
                            "expected": validation["counts"]["expected_reels"],
                            "fail": res["reel_thumb"]["fail"], "bytes": bytes_total["reel_thumb"]},
            "reel_videos": {"ok": total("reel_video"),
                            "expected": validation["counts"]["expected_reels"],
                            "fail": res["reel_video"]["fail"], "bytes": bytes_total["reel_video"]},
        },
        "validation_counts": validation["counts"],
        "validation_image_sample_ok": all(c.get("ok") for c in validation["image_sample"]),
        "validation_video_sample_ok": all(c.get("ok_min_size") for c in validation["video_sample"]) if validation["video_sample"] else None,
        "apify_cost_usd": cost,
        "free_plan_budget_usd": 5.0,
        "free_plan_remaining_usd": free_remaining,
        "total_storage_gb": round(storage_gb, 3),
        "total_seconds": total_seconds,
        "total_hours": round(total_seconds / 3600, 2),
        "errors_first_20": {
            k: v["errors"][:20] for k, v in res.items() if v["errors"]
        },
        "paths": {
            "apify_dataset": str(APIFY_DATASET_OUT),
            "photos_dir": str(PHOTOS_DIR),
            "slides_dir": str(SLIDES_DIR),
            "reel_thumbs_dir": str(THUMBS_DIR),
            "videos_dir": str(VIDEOS_DIR),
        },
    }
    FINAL_REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print()
    print("=" * 64)
    print("STEP 7 — PHASE 2 FASHION FINAL REPORT")
    print("=" * 64)
    print(f"Total posts processed   : 842")
    print(f"Apify items returned    : {842 - len(missing_in_apify)}")
    print(f"Missing in Apify        : {len(missing_in_apify)}")
    print()
    print("Downloads (ok / expected):")
    print(f"  Photos          : {total('photo')} / {validation['counts']['expected_photos']}  fail={res['photo']['fail']}")
    print(f"  Carousel slides : {total('slide')}  fail={res['slide']['fail']}")
    print(f"  Reel thumbs     : {total('reel_thumb')} / {validation['counts']['expected_reels']}  fail={res['reel_thumb']['fail']}")
    print(f"  Reel videos     : {total('reel_video')} / {validation['counts']['expected_reels']}  fail={res['reel_video']['fail']}")
    print()
    print(f"Apify cost              : ${cost:.4f}")
    print(f"Free Plan remaining     : ${free_remaining:.4f}")
    print(f"Total storage           : {storage_gb:.2f} GB")
    print(f"  photos   : {bytes_total['photo']/1024**2:.1f} MB")
    print(f"  slides   : {bytes_total['slide']/1024**2:.1f} MB")
    print(f"  thumbs   : {bytes_total['reel_thumb']/1024**2:.1f} MB")
    print(f"  videos   : {bytes_total['reel_video']/1024**3:.2f} GB")
    print(f"Total elapsed           : {total_seconds/60:.1f} min ({total_seconds/3600:.2f} h)")
    print()
    print(f"Image sample integrity  : {report['validation_image_sample_ok']}")
    print(f"Video sample integrity  : {report['validation_video_sample_ok']}")
    print()
    print(f"Report written to       : {FINAL_REPORT}")
    return report


# ----------------------------- MAIN ------------------------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rescrape", action="store_true",
                        help="Force a fresh Apify run even if dataset exists")
    args = parser.parse_args()

    posts = json.loads(POSTS_JSON.read_text(encoding="utf-8"))
    log(f"Loaded {len(posts)} Fashion posts")

    t_start = time.time()
    items, run_meta = step4_scrape(posts, rescrape=args.rescrape)

    by_short = index_items(items)
    log(f"Indexed {len(by_short)} Apify items by shortCode")

    jobs, missing = plan_jobs(posts, by_short)
    if missing:
        log(f"[WARN] {len(missing)} posts missing from Apify response")
    dl_summary = step5_download(jobs)

    validation = step6_validate(posts)
    total_seconds = time.time() - t_start
    step7_report(run_meta, dl_summary, validation, missing, total_seconds)


if __name__ == "__main__":
    main()
