"""Step 4h.2 — Embed every image with CLIP ViT-B/32.

Walks `data/step4/by_industry/<industry>/{photos,carousel_slides,reel_thumbs}/`
and writes a parquet of L2-normalized 512-dim embeddings.

Output columns:
    post_id, file_path, file_type (photo|carousel_slide|reel_thumb),
    industry, slide_idx (int, -1 if N/A), embedding (list[float], len=512)

Following Radford et al. (2021): vision encoder, projection_dim=512,
L2-normalized features (cosine geometry).
"""
from __future__ import annotations

import torch  # must come first on Windows

import argparse
import gc
import os
import re
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image
from transformers import CLIPModel, CLIPProcessor

ROOT = Path(__file__).resolve().parents[1]
BY_INDUSTRY = ROOT / "data" / "step4" / "by_industry"
OUT_DIR = ROOT / "data" / "step4h"
OUT_DIR.mkdir(exist_ok=True, parents=True)
OUT_PARQUET = OUT_DIR / "df_clip_embeddings.parquet"

MODEL_NAME = "openai/clip-vit-base-patch32"
INDUSTRIES = ["beauty", "fashion", "hotels", "patisserie", "restaurants"]
SUBDIRS = {
    "photo": "photos",
    "carousel_slide": "carousel_slides",
    "reel_thumb": "reel_thumbs",
}

def clip_image_features(model: CLIPModel, pixel_values: torch.Tensor) -> torch.Tensor:
    """Vision tower + visual projection -> 512-dim CLIP embedding."""
    vision_out = model.vision_model(pixel_values=pixel_values)
    return model.visual_projection(vision_out.pooler_output)


# Instagram shortcodes can contain underscores, so we strip suffixes from
# the right rather than splitting on the first underscore.
SLIDE_RE = re.compile(r"^(?P<pid>.+)_slide_(?P<idx>\d+)\.(jpg|jpeg|png)$", re.I)
THUMB_RE = re.compile(r"^(?P<pid>.+)_thumb\.(jpg|jpeg|png)$", re.I)
PHOTO_RE = re.compile(r"^(?P<pid>.+)\.(jpg|jpeg|png)$", re.I)


def parse_filename(file_type: str, name: str) -> tuple[str | None, int]:
    """Return (post_id, slide_idx). slide_idx = -1 for non-carousel files."""
    if file_type == "carousel_slide":
        m = SLIDE_RE.match(name)
        return (m.group("pid"), int(m.group("idx"))) if m else (None, -1)
    if file_type == "reel_thumb":
        m = THUMB_RE.match(name)
        return (m.group("pid"), -1) if m else (None, -1)
    m = PHOTO_RE.match(name)
    return (m.group("pid"), -1) if m else (None, -1)


def collect_files() -> pd.DataFrame:
    rows = []
    for industry in INDUSTRIES:
        for ftype, sub in SUBDIRS.items():
            d = BY_INDUSTRY / industry / sub
            if not d.exists():
                continue
            for fp in sorted(d.iterdir()):
                if not fp.is_file():
                    continue
                if fp.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
                    continue
                pid, slide_idx = parse_filename(ftype, fp.name)
                if pid is None:
                    print(f"  [skip] unrecognized name: {fp.name}", file=sys.stderr)
                    continue
                rows.append(
                    {
                        "post_id": pid,
                        "file_path": str(fp.relative_to(ROOT)),
                        "file_type": ftype,
                        "industry": industry,
                        "slide_idx": slide_idx,
                    }
                )
    return pd.DataFrame(rows)


def embed_batch(model, processor, paths: list[Path], device: str) -> np.ndarray:
    imgs = []
    for p in paths:
        try:
            imgs.append(Image.open(p).convert("RGB"))
        except Exception as e:
            print(f"  [bad image] {p}: {e}", file=sys.stderr)
            imgs.append(Image.new("RGB", (224, 224)))  # zero placeholder
    inputs = processor(images=imgs, return_tensors="pt").to(device)
    with torch.no_grad():
        feats = clip_image_features(model, inputs.pixel_values)
    feats = feats / feats.norm(p=2, dim=-1, keepdim=True)
    for im in imgs:
        im.close()
    return feats.cpu().numpy().astype(np.float32)


def maybe_peak_mem_gb() -> float:
    try:
        import psutil  # type: ignore
        return psutil.Process(os.getpid()).memory_info().rss / 1e9
    except Exception:
        return float("nan")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch-size", type=int, default=32)
    ap.add_argument("--limit", type=int, default=0, help="0=all")
    ap.add_argument("--resume", action="store_true",
                    help="Skip files already in the output parquet")
    args = ap.parse_args()

    t0 = time.time()
    print("=" * 70)
    print("STEP 4h.2 — embed all images")
    print("=" * 70)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"device: {device}")
    print(f"model:  {MODEL_NAME}")
    print(f"batch:  {args.batch_size}")
    print()

    print("Scanning files ...")
    df_files = collect_files()
    print(f"  total files: {len(df_files)}")
    print(df_files.groupby(["industry", "file_type"]).size().unstack(fill_value=0))

    if args.resume and OUT_PARQUET.exists():
        prev = pd.read_parquet(OUT_PARQUET)
        done = set(prev["file_path"])
        print(f"  resume: skipping {len(done)} already-embedded files")
        df_files = df_files[~df_files["file_path"].isin(done)].reset_index(drop=True)

    if args.limit:
        df_files = df_files.head(args.limit)
        print(f"  --limit {args.limit} -> {len(df_files)} files")

    if len(df_files) == 0:
        print("Nothing to do.")
        return 0

    print(f"\nLoading CLIP ...")
    model = CLIPModel.from_pretrained(MODEL_NAME).to(device).eval()
    processor = CLIPProcessor.from_pretrained(MODEL_NAME)

    bs = args.batch_size
    embeddings: list[np.ndarray] = []
    n = len(df_files)
    peak_mem = 0.0
    t_emb_start = time.time()
    for i in range(0, n, bs):
        chunk = df_files.iloc[i : i + bs]
        paths = [ROOT / fp for fp in chunk["file_path"]]
        emb = embed_batch(model, processor, paths, device)
        embeddings.append(emb)
        # log every 5 batches so we see progress on slow CPUs
        if (i // bs) % 5 == 0 or i + bs >= n:
            mem = maybe_peak_mem_gb()
            peak_mem = max(peak_mem, mem if mem == mem else 0.0)
            done_files = min(i + bs, n)
            elapsed = time.time() - t_emb_start
            rate = done_files / max(elapsed, 1e-6)
            eta = (n - done_files) / max(rate, 1e-6)
            print(
                f"  [{done_files:5d}/{n}]  "
                f"{rate:5.1f} img/s  "
                f"mem={mem:.2f}GB  "
                f"elapsed={elapsed:6.1f}s  eta={eta:6.1f}s",
                flush=True,
            )

    full = np.vstack(embeddings)
    assert full.shape == (n, 512), f"unexpected shape {full.shape}"
    print(f"\nFinal embedding matrix: {full.shape}")

    if args.resume and OUT_PARQUET.exists():
        prev = pd.read_parquet(OUT_PARQUET)
    else:
        prev = None

    df_out = df_files.copy()
    df_out["embedding"] = list(full)
    if prev is not None:
        df_out = pd.concat([prev, df_out], ignore_index=True)

    df_out.to_parquet(OUT_PARQUET, index=False)
    print(f"\nWrote {OUT_PARQUET} ({len(df_out)} rows)")

    elapsed = time.time() - t0
    print(
        f"\nDone in {elapsed:.1f}s "
        f"({n} new / {len(df_out)} total embeddings, "
        f"peak RSS ~ {peak_mem:.2f} GB)"
    )
    del model, processor
    gc.collect()
    return 0


if __name__ == "__main__":
    sys.exit(main())
