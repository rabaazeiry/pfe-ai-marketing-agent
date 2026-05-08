"""Step 4i — Build df_ml_dataset_v5.parquet.

V5 = V4 features but with `topic_id` replaced by:
  - 21 one-hot binary cols  (topic_outlier, topic_0, ..., topic_19)
  - 1 continuous `topic_max_prob` recovered via BERTopic.transform()

Rationale (from verification analysis): V4 stores `topic_id` as an int32
ordinal which tree splits treat as numeric (`topic_id <= 7.5`) — meaningless
for a 21-class categorical. Properly encoding the existing topic signal
should unlock SHAP attribution that V4 currently mis-attributes.

Inputs
  data/df_ml_dataset_v4.parquet                 (4010 x 48)
  data/df_master_masked_with_topics.parquet     (4127 x 28)  -- caption_masked
  models/bertopic_v2/                           -- trained BERTopic model

Output
  data/df_ml_dataset_v5.parquet                 (4010 x 69)
"""
from __future__ import annotations

# Windows DLL workaround: torch BEFORE bertopic. See project memory.
import torch  # noqa: F401

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from bertopic import BERTopic

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

V4_PATH       = DATA / "df_ml_dataset_v4.parquet"
MASTER_PATH   = DATA / "df_master_masked_with_topics.parquet"
MODEL_DIR     = ROOT / "models" / "bertopic_v2"
OUT_PATH      = DATA / "df_ml_dataset_v5.parquet"

EXPECTED_TOPIC_RANGE = list(range(-1, 20))  # -1 outlier + topics 0..19


def main() -> int:
    print("=" * 78)
    print("Step 4i -- Build V5 dataset (one-hot topic + topic_max_prob)")
    print("=" * 78)

    # 1. Load V4 + master_masked --------------------------------------------- #
    print(f"\n[1/5] Loading inputs ...")
    v4 = pd.read_parquet(V4_PATH)
    print(f"  V4              : {v4.shape}")
    master = pd.read_parquet(MASTER_PATH)
    print(f"  master_masked   : {master.shape}")

    # Verify V4 post_ids are a subset of master post_ids.
    v4_ids = set(v4["post_id"])
    m_ids  = set(master["post_id"])
    missing = v4_ids - m_ids
    assert not missing, f"{len(missing)} V4 post_ids missing from master_masked"
    print(f"  V4 post_ids subset of master: OK")

    # Verify topic_id range matches what BERTopic_v2 produced.
    observed = sorted(v4["topic_id"].unique().tolist())
    print(f"  V4 topic_id range observed: {observed}")
    assert observed == EXPECTED_TOPIC_RANGE, \
        f"unexpected topic_id range; got {observed} expected {EXPECTED_TOPIC_RANGE}"

    # 2. Recover topic_max_prob via BERTopic.transform ----------------------- #
    print(f"\n[2/5] Loading BERTopic model from {MODEL_DIR} ...")
    t0 = time.perf_counter()
    model = BERTopic.load(str(MODEL_DIR))
    print(f"  loaded in {time.perf_counter() - t0:.1f} s")

    # Build the doc list aligned to V4 row order.
    cap_lookup = pd.Series(
        master["caption_masked"].values, index=master["post_id"].values,
    )
    docs = cap_lookup.loc[v4["post_id"].values].fillna("").astype(str).tolist()
    n_empty = sum(1 for d in docs if not d.strip())
    print(f"  documents prepared: {len(docs)}  (blank captions: {n_empty})")

    print(f"\n[3/5] Running model.transform on {len(docs)} captions ...")
    t0 = time.perf_counter()
    topics_pred, probs = model.transform(docs)
    print(f"  transform elapsed: {time.perf_counter() - t0:.1f} s")
    probs = np.asarray(probs)
    print(f"  probs shape: {probs.shape}  dtype: {probs.dtype}")

    # probs is (n_docs,) for HDBSCAN-based BERTopic when calculate_probabilities=False.
    # In that case BERTopic returns the assignment confidence as a 1-D array; if it
    # is 2-D (n_docs, n_topics), take row max.
    if probs.ndim == 2:
        topic_max_prob = probs.max(axis=1).astype("float32")
        print(f"  probs is 2-D -> topic_max_prob = max over topics axis")
    else:
        topic_max_prob = probs.astype("float32")
        print(f"  probs is 1-D -> topic_max_prob = probs directly (HDBSCAN confidence)")

    # Sanity-check predicted topics vs stored topic_id.
    # Note: BERTopic.transform() uses HDBSCAN approximate_predict, which may
    # disagree with the trained labels for some posts (esp. those that were
    # outlier-reduced post-fit). We log the mismatch but DON'T fail.
    pred_arr = np.asarray(topics_pred)
    stored = v4["topic_id"].values
    n_match = int((pred_arr == stored).sum())
    print(f"  transform topic agreement with stored topic_id: "
          f"{n_match}/{len(stored)} ({100*n_match/len(stored):.1f}%)")
    print(f"  topic_max_prob stats: "
          f"mean={topic_max_prob.mean():.3f}  "
          f"std={topic_max_prob.std():.3f}  "
          f"min={topic_max_prob.min():.3f}  "
          f"max={topic_max_prob.max():.3f}")

    # 3. One-hot encode topic_id -------------------------------------------- #
    print(f"\n[4/5] One-hot encoding topic_id ...")
    v5 = v4.copy()

    onehot = pd.DataFrame(index=v5.index)
    onehot["topic_outlier"] = (v5["topic_id"] == -1).astype("int8")
    for tid in range(20):
        onehot[f"topic_{tid}"] = (v5["topic_id"] == tid).astype("int8")

    # Sanity: each row has exactly one 1 across the 21 cols.
    row_sum = onehot.sum(axis=1)
    bad = int((row_sum != 1).sum())
    assert bad == 0, f"{bad} rows have row-sum != 1 in one-hot block"
    print(f"  one-hot block: {onehot.shape}  (per-col counts head):")
    print(onehot.sum().head(10).to_string().replace("\n", "\n    "))

    # 4. Assemble V5 -------------------------------------------------------- #
    v5 = v5.drop(columns=["topic_id"])
    v5 = pd.concat([v5, onehot], axis=1)
    v5["topic_max_prob"] = topic_max_prob

    print(f"\n[5/5] Verifying V5 ...")
    print(f"  V4 shape: {v4.shape}")
    print(f"  V5 shape: {v5.shape}  (expected 48 - 1 + 21 + 1 = 69)")
    assert v5.shape == (len(v4), 69), \
        f"unexpected V5 shape {v5.shape}; expected ({len(v4)}, 69)"

    # Required-feature sanity checks.
    assert "caption_sentiment" in v5.columns, "caption_sentiment missing!"
    print(f"  caption_sentiment present: OK")
    clip_pcs = [c for c in v5.columns if c.startswith("clip_pc")]
    assert len(clip_pcs) == 15, f"expected 15 clip_pc cols, got {len(clip_pcs)}"
    print(f"  clip_pc01..15 present: OK")
    topic_cols = [c for c in v5.columns if c.startswith("topic_")]
    assert len(topic_cols) == 22, \
        f"expected 21 one-hot + 1 max_prob = 22 topic_* cols, got {len(topic_cols)}"
    print(f"  topic_* cols ({len(topic_cols)}): "
          f"{topic_cols[:5]}...{topic_cols[-3:]}")
    assert "topic_id" not in v5.columns, "topic_id should have been dropped"
    print(f"  topic_id dropped: OK")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    v5.to_parquet(OUT_PATH, index=False)
    print(f"\n  wrote {OUT_PATH}  ({OUT_PATH.stat().st_size/1024:.1f} KB)")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
