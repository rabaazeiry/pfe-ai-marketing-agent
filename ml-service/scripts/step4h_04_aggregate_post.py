"""Step 4h.4 — Aggregate per-image embeddings into per-post embeddings.

Strategy (per content_type from df_master):
  * single_image / photo  -> use the photo embedding as-is
  * carousel              -> mean-pool all slide embeddings, re-L2
  * reel / video          -> 0.5 * thumbnail + 0.5 * mean(reel frames)

Output: data/step4h/df_post_clip.parquet
Columns: post_id, content_type, n_assets, clip_embedding (512)
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
STEP4H = DATA / "step4h"

DF_MASTER = DATA / "df_master_masked_with_topics.parquet"
DF_IMG = STEP4H / "df_clip_embeddings.parquet"
DF_REEL = STEP4H / "df_reel_frames_embeddings.parquet"
OUT = STEP4H / "df_post_clip.parquet"


def l2(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v, axis=-1, keepdims=True)
    n = np.where(n == 0, 1.0, n)
    return v / n


def main() -> int:
    print("=" * 70)
    print("STEP 4h.4 — aggregate embeddings per post")
    print("=" * 70)

    master = pd.read_parquet(DF_MASTER)[["post_id", "content_type"]]
    img = pd.read_parquet(DF_IMG)
    reel = pd.read_parquet(DF_REEL) if DF_REEL.exists() else pd.DataFrame()
    print(f"master    : {len(master)} posts")
    print(f"images    : {len(img)} embeddings")
    print(f"reel-pool : {len(reel)} videos")

    # stack image embeddings as a 2D array per post
    img["embedding"] = img["embedding"].apply(np.asarray)

    photo_rows = img[img["file_type"] == "photo"]
    photo_map: dict[str, np.ndarray] = {
        pid: e for pid, e in zip(photo_rows["post_id"], photo_rows["embedding"])
    }

    car_grouped = (
        img[img["file_type"] == "carousel_slide"]
        .groupby("post_id")["embedding"]
        .apply(lambda s: l2(np.stack(s.values).mean(axis=0)))
    )
    car_map: dict[str, np.ndarray] = car_grouped.to_dict()
    car_count = (
        img[img["file_type"] == "carousel_slide"].groupby("post_id").size().to_dict()
    )

    thumb_rows = img[img["file_type"] == "reel_thumb"]
    thumb_map: dict[str, np.ndarray] = {
        pid: e for pid, e in zip(thumb_rows["post_id"], thumb_rows["embedding"])
    }

    if not reel.empty:
        reel["mean_embedding"] = reel["mean_embedding"].apply(np.asarray)
        reel_map: dict[str, np.ndarray] = {
            pid: e for pid, e in zip(reel["post_id"], reel["mean_embedding"])
        }
        reel_frame_count = dict(zip(reel["post_id"], reel["n_frames"]))
    else:
        reel_map = {}
        reel_frame_count = {}

    rows = []
    for _, r in master.iterrows():
        pid = r["post_id"]
        ct = r["content_type"]
        emb: np.ndarray | None = None
        n_assets = 0
        # try in priority order; many posts have multiple modalities
        if pid in photo_map:
            emb = photo_map[pid]
            n_assets = 1
        elif pid in car_map:
            emb = car_map[pid]
            n_assets = car_count.get(pid, 0)
        elif pid in thumb_map or pid in reel_map:
            parts = []
            if pid in thumb_map:
                parts.append(thumb_map[pid])
            if pid in reel_map and reel_frame_count.get(pid, 0) > 0:
                parts.append(reel_map[pid])
            if parts:
                emb = l2(np.mean(np.stack(parts, axis=0), axis=0))
                n_assets = (1 if pid in thumb_map else 0) + reel_frame_count.get(pid, 0)
        if emb is None:
            continue
        rows.append(
            {
                "post_id": pid,
                "content_type": ct,
                "n_assets": int(n_assets),
                "clip_embedding": emb.astype(np.float32),
            }
        )

    df_out = pd.DataFrame(rows)
    df_out.to_parquet(OUT, index=False)
    print(f"\nposts with embedding   : {len(df_out)}")
    print(f"posts in master        : {len(master)}")
    print(f"posts missing visuals  : {len(master) - len(df_out)}")
    print(f"by content_type:")
    print(df_out.groupby("content_type").size())
    print(f"\nWrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
