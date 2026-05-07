"""Step 4h.3 — Reel video frame extraction & CLIP embedding.

For each .mp4 in `data/step4/by_industry/<industry>/videos/`, sample 5 frames
at evenly spaced positions (10%, 30%, 50%, 70%, 90%) of the video duration,
embed each with CLIP ViT-B/32, then mean-pool to a single 512-dim vector.

Output: `data/step4h/df_reel_frames_embeddings.parquet`
Columns: post_id, video_path, industry, n_frames, mean_embedding (512)

This complements thumbnail-only reel features (HyperFusion 2025).
"""
from __future__ import annotations

import torch  # must come first

import argparse
import os
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
from PIL import Image
from transformers import CLIPModel, CLIPProcessor

ROOT = Path(__file__).resolve().parents[1]
BY_INDUSTRY = ROOT / "data" / "step4" / "by_industry"
OUT_DIR = ROOT / "data" / "step4h"
OUT_DIR.mkdir(exist_ok=True, parents=True)
OUT_PARQUET = OUT_DIR / "df_reel_frames_embeddings.parquet"

MODEL_NAME = "openai/clip-vit-base-patch32"
INDUSTRIES = ["beauty", "fashion", "hotels", "patisserie", "restaurants"]
FRAME_FRACTIONS = (0.10, 0.30, 0.50, 0.70, 0.90)


def clip_image_features(model: CLIPModel, pixel_values: torch.Tensor) -> torch.Tensor:
    vision_out = model.vision_model(pixel_values=pixel_values)
    return model.visual_projection(vision_out.pooler_output)


def collect_videos() -> pd.DataFrame:
    rows = []
    for industry in INDUSTRIES:
        d = BY_INDUSTRY / industry / "videos"
        if not d.exists():
            continue
        for fp in sorted(d.iterdir()):
            if fp.suffix.lower() != ".mp4":
                continue
            pid = fp.stem  # "<post_id>.mp4" -> post_id
            rows.append(
                {
                    "post_id": pid,
                    "video_path": str(fp.relative_to(ROOT)),
                    "industry": industry,
                }
            )
    return pd.DataFrame(rows)


def extract_frames(path: Path, fractions=FRAME_FRACTIONS) -> list[np.ndarray]:
    """Return list of HxWx3 uint8 RGB frames sampled at the given fractions."""
    cap = cv2.VideoCapture(str(path))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    frames: list[np.ndarray] = []
    if total <= 0:
        cap.release()
        return frames
    seen = set()
    for f in fractions:
        idx = int(round(f * (total - 1)))
        idx = max(0, min(idx, total - 1))
        if idx in seen:
            continue
        seen.add(idx)
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, frame = cap.read()
        if not ok or frame is None:
            continue
        # BGR -> RGB
        frames.append(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    cap.release()
    return frames


def embed_pil_batch(model, processor, pils: list[Image.Image], device: str) -> np.ndarray:
    inputs = processor(images=pils, return_tensors="pt").to(device)
    with torch.no_grad():
        feats = clip_image_features(model, inputs.pixel_values)
    feats = feats / feats.norm(p=2, dim=-1, keepdim=True)
    return feats.cpu().numpy().astype(np.float32)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--video-batch", type=int, default=8,
                    help="videos per CLIP batch (each yields up to 5 frames)")
    args = ap.parse_args()

    t0 = time.time()
    print("=" * 70)
    print("STEP 4h.3 — reel frame extraction + CLIP")
    print("=" * 70)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"device: {device}")

    df_vid = collect_videos()
    print(f"videos found: {len(df_vid)}")
    print(df_vid.groupby("industry").size())

    if args.resume and OUT_PARQUET.exists():
        prev = pd.read_parquet(OUT_PARQUET)
        done = set(prev["video_path"])
        df_vid = df_vid[~df_vid["video_path"].isin(done)].reset_index(drop=True)
        print(f"resume: {len(df_vid)} videos remaining")

    if args.limit:
        df_vid = df_vid.head(args.limit)

    if df_vid.empty:
        print("Nothing to do.")
        return 0

    print(f"\nLoading CLIP ...")
    model = CLIPModel.from_pretrained(MODEL_NAME).to(device).eval()
    processor = CLIPProcessor.from_pretrained(MODEL_NAME)

    out_rows = []
    total_frames = 0
    bad_videos = 0
    n = len(df_vid)
    t_start = time.time()
    bs = args.video_batch

    for i in range(0, n, bs):
        chunk = df_vid.iloc[i : i + bs]
        # extract frames per video, remember boundaries
        per_vid_frames: list[list[Image.Image]] = []
        for _, row in chunk.iterrows():
            frames_np = extract_frames(ROOT / row["video_path"])
            pil_list = [Image.fromarray(f) for f in frames_np]
            per_vid_frames.append(pil_list)
            if not pil_list:
                bad_videos += 1
        flat = [im for sub in per_vid_frames for im in sub]
        if flat:
            embs = embed_pil_batch(model, processor, flat, device)
        else:
            embs = np.zeros((0, 512), dtype=np.float32)
        # split back per video
        cursor = 0
        for (_, row), pil_list in zip(chunk.iterrows(), per_vid_frames):
            k = len(pil_list)
            if k == 0:
                mean_emb = np.zeros(512, dtype=np.float32)
            else:
                mean_emb = embs[cursor : cursor + k].mean(axis=0)
                # re-L2 (mean of unit vectors is not unit)
                norm = np.linalg.norm(mean_emb)
                if norm > 0:
                    mean_emb = mean_emb / norm
            cursor += k
            total_frames += k
            for im in pil_list:
                im.close()
            out_rows.append(
                {
                    "post_id": row["post_id"],
                    "video_path": row["video_path"],
                    "industry": row["industry"],
                    "n_frames": k,
                    "mean_embedding": mean_emb.astype(np.float32),
                }
            )
        done_videos = min(i + bs, n)
        if (i // bs) % 5 == 0 or done_videos >= n:
            elapsed = time.time() - t_start
            rate = done_videos / max(elapsed, 1e-6)
            eta = (n - done_videos) / max(rate, 1e-6)
            print(
                f"  [{done_videos:4d}/{n}]  "
                f"{rate:5.2f} vid/s  "
                f"frames={total_frames:5d}  "
                f"bad={bad_videos:3d}  "
                f"elapsed={elapsed:6.1f}s  eta={eta:6.1f}s",
                flush=True,
            )

    df_out = pd.DataFrame(out_rows)
    if args.resume and OUT_PARQUET.exists():
        prev = pd.read_parquet(OUT_PARQUET)
        df_out = pd.concat([prev, df_out], ignore_index=True)
    df_out.to_parquet(OUT_PARQUET, index=False)

    elapsed = time.time() - t0
    print(f"\nWrote {OUT_PARQUET} ({len(df_out)} rows)")
    print(f"Total frames embedded: {total_frames}")
    print(f"Videos with no readable frames: {bad_videos}")
    print(f"Total time: {elapsed:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
