"""Step 4h.1 — CLIP environment setup & smoke test.

Loads CLIP ViT-B/32 (OpenAI weights) via HuggingFace transformers,
verifies CUDA availability, and embeds a single sample image to confirm
the full pipeline (PIL load -> processor -> model -> 512-dim vector).
"""
from __future__ import annotations

# Project memory rule: import torch BEFORE bertopic/transformers on Windows
import torch  # noqa: F401  (must come first)

import os
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image
from transformers import CLIPModel, CLIPProcessor

ROOT = Path(__file__).resolve().parents[1]
BY_INDUSTRY = ROOT / "data" / "step4" / "by_industry"
MODEL_NAME = "openai/clip-vit-base-patch32"


def clip_image_features(model: CLIPModel, pixel_values: torch.Tensor) -> torch.Tensor:
    """Run vision tower + visual projection -> 512-dim embedding.

    Robust across transformers versions: 4.x's `get_image_features` returned
    the projected tensor directly; some 5.x snapshots return the un-projected
    BaseModelOutputWithPooling. We always go through `vision_model` +
    `visual_projection` ourselves to get the canonical CLIP image embedding.
    """
    vision_out = model.vision_model(pixel_values=pixel_values)
    pooled = vision_out.pooler_output  # (B, hidden)
    return model.visual_projection(pooled)  # (B, 512)


def main() -> int:
    t0 = time.time()
    print("=" * 70)
    print("STEP 4h.1 — CLIP ViT-B/32 setup & smoke test")
    print("=" * 70)
    print(f"torch              : {torch.__version__}")
    print(f"cuda available     : {torch.cuda.is_available()}")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"selected device    : {device}")

    print(f"\nLoading model: {MODEL_NAME} ...")
    model = CLIPModel.from_pretrained(MODEL_NAME).to(device).eval()
    processor = CLIPProcessor.from_pretrained(MODEL_NAME)
    n_params = sum(p.numel() for p in model.parameters())
    print(f"  params         : {n_params/1e6:.1f}M")
    print(f"  vision dim     : {model.config.projection_dim}")  # should be 512

    # smoke test: pick first photo from beauty
    sample = sorted((BY_INDUSTRY / "beauty" / "photos").iterdir())[0]
    print(f"\nSmoke-test image : {sample.name}")
    img = Image.open(sample).convert("RGB")
    print(f"  size           : {img.size}")

    inputs = processor(images=img, return_tensors="pt").to(device)
    with torch.no_grad():
        feats = clip_image_features(model, inputs.pixel_values)
    feats = feats / feats.norm(p=2, dim=-1, keepdim=True)  # L2 normalize
    emb = feats.cpu().numpy().astype(np.float32).squeeze(0)
    print(f"  embedding shape: {emb.shape}")
    print(f"  L2 norm        : {np.linalg.norm(emb):.6f} (expect ~1.0)")
    print(f"  sample values  : {emb[:6].round(4).tolist()}")
    print(f"  finite         : {bool(np.isfinite(emb).all())}")

    print(f"\nSetup OK in {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
