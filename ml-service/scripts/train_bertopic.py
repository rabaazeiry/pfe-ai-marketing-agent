"""CLI: train BERTopic on the cleaned corpus, evaluate, save artifacts."""
from __future__ import annotations

# Windows DLL workaround: torch BEFORE bertopic. See project memory.
import torch  # noqa: F401

import json
import shutil
import sys
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from corpus.topic_model import (  # noqa: E402
    EMBEDDING_MODEL_NAME,
    TARGETS,
    compute_metrics,
    train_topic_model,
)


class _NumpyJSONEncoder(json.JSONEncoder):
    """Coerce numpy scalars/arrays to Python natives during json.dump."""

    def default(self, o):  # noqa: D401
        if isinstance(o, np.integer):
            return int(o)
        if isinstance(o, np.floating):
            return float(o)
        if isinstance(o, np.ndarray):
            return o.tolist()
        return super().default(o)


@contextmanager
def _numpy_json_compat():
    """Temporarily teach json.dump / json.dumps about numpy types."""
    orig_dump = json.dump
    orig_dumps = json.dumps

    def _patched_dump(*args, **kwargs):
        kwargs.setdefault("cls", _NumpyJSONEncoder)
        return orig_dump(*args, **kwargs)

    def _patched_dumps(*args, **kwargs):
        kwargs.setdefault("cls", _NumpyJSONEncoder)
        return orig_dumps(*args, **kwargs)

    json.dump = _patched_dump
    json.dumps = _patched_dumps
    try:
        yield
    finally:
        json.dump = orig_dump
        json.dumps = orig_dumps


def main() -> None:
    in_path = ROOT / "data" / "df_master_clean.parquet"
    print(f"Loading {in_path} ...")
    df = pd.read_parquet(in_path)
    df_in = df[df["has_caption"]].reset_index(drop=True).copy()
    print(f"  Filtered: {len(df_in):,} captioned posts (from {len(df):,} total).")

    print(f"Training BERTopic with embedder = {EMBEDDING_MODEL_NAME}")
    (
        model,
        topics_before,
        topic_words_before,
        topics_after,
        probs,
        df_out,
        elapsed,
    ) = train_topic_model(df_in)

    # Persist analytical artifacts FIRST — if model.save() ever fails again
    # we still keep the parquet + metrics + ability to inspect the in-memory model.
    out_parquet = ROOT / "data" / "df_master_with_topics.parquet"
    df_out.to_parquet(out_parquet, index=False)
    print(f"  Wrote {out_parquet}")

    print("Computing metrics (before outlier reduction) ...")
    docs = df_in["caption_clean"].tolist()
    # `topic_words_before` is the snapshot taken inside train_topic_model()
    # immediately after fit_transform — i.e. before update_topics ran — so
    # NPMI / diversity here reflect the genuine pre-reduction representation.
    metrics_before = compute_metrics(
        model, docs, topics_before, topic_words_override=topic_words_before
    )
    print("Computing metrics (after outlier reduction) ...")
    metrics_after = compute_metrics(model, docs, topics_after)

    # Now save model. Numpy-JSON shim handles numpy int64 in BERTopic's
    # internal config dumps (numpy 2.x interaction).
    model_dir = ROOT / "models" / "bertopic_v1"
    if model_dir.exists():
        shutil.rmtree(model_dir)  # clear any partial files from earlier runs
    model_dir.mkdir(parents=True, exist_ok=True)
    with _numpy_json_compat():
        model.save(
            str(model_dir),
            serialization="safetensors",
            save_ctfidf=True,
            save_embedding_model=EMBEDDING_MODEL_NAME,
        )
    print(f"  Wrote {model_dir}")

    _print_results(
        model,
        topics_before,
        topics_after,
        metrics_before,
        metrics_after,
        elapsed,
        model_dir,
        out_parquet,
    )


def _print_results(
    model,
    topics_before,
    topics_after,
    metrics_before,
    metrics_after,
    elapsed,
    model_dir,
    out_parquet,
) -> None:
    n_total = len(topics_after)
    print()
    print("=" * 72)
    print(f"BERTopic training - elapsed {elapsed:7.1f} s ({elapsed / 60:.1f} min)")
    print("=" * 72)

    # ---- BEFORE vs AFTER comparison ----------------------------------------
    print()
    print("Phase 3.5: BEFORE vs AFTER outlier reduction")
    print("-" * 72)
    print(f"{'metric':<22} {'BEFORE':<22} {'AFTER':<22} delta")
    print("-" * 72)

    def _fmt_outliers(m):
        return f"{m['outliers_count']:,} ({m['outliers_ratio']*100:.1f}%)"

    delta_outliers = metrics_after["outliers_count"] - metrics_before["outliers_count"]
    delta_npmi = metrics_after["npmi_coherence"] - metrics_before["npmi_coherence"]
    delta_div = metrics_after["topic_diversity"] - metrics_before["topic_diversity"]

    print(f"{'outliers':<22} {_fmt_outliers(metrics_before):<22} "
          f"{_fmt_outliers(metrics_after):<22} {delta_outliers:+,}")
    print(f"{'npmi_coherence':<22} {metrics_before['npmi_coherence']:<22.4f} "
          f"{metrics_after['npmi_coherence']:<22.4f} {delta_npmi:+.4f}")
    print(f"{'topic_diversity':<22} {metrics_before['topic_diversity']:<22.4f} "
          f"{metrics_after['topic_diversity']:<22.4f} {delta_div:+.4f}")
    print(f"{'n_topics':<22} {metrics_before['n_topics']:<22} "
          f"{metrics_after['n_topics']:<22} {metrics_after['n_topics'] - metrics_before['n_topics']:+d}")

    # ---- Acceptance gates (final / AFTER values) ---------------------------
    print()
    print("Acceptance gates (post-reduction)")
    print("-" * 60)
    rows = [
        ("n_topics",
         f"{metrics_after['n_topics']}",
         "(info)"),
        ("outliers",
         f"{metrics_after['outliers_count']:,} / {n_total:,} = {metrics_after['outliers_ratio'] * 100:.1f}%",
         "PASS" if metrics_after["outliers_ratio"] < TARGETS["outliers_max"] else "FAIL"),
        ("npmi_coherence",
         f"{metrics_after['npmi_coherence']:.4f}",
         "PASS" if metrics_after["npmi_coherence"] > TARGETS["npmi"] else "FAIL"),
        ("topic_diversity",
         f"{metrics_after['topic_diversity']:.4f}",
         "PASS" if metrics_after["topic_diversity"] > TARGETS["diversity"] else "FAIL"),
    ]
    print(f"{'metric':<18} {'value':<32} status")
    print("-" * 60)
    for name, val, status in rows:
        print(f"{name:<18} {val:<32} {status}")

    # ---- Top 10 topics with cleaned vocabulary -----------------------------
    info = model.get_topic_info()
    info = info[info["Topic"] != -1].head(10)
    print()
    print("Top 10 topics (post stopword filter + outlier reduction)")
    print("-" * 72)
    for _, row in info.iterrows():
        tid = int(row["Topic"])
        words = [w for w, _ in model.get_topic(tid)][:10]
        print(f"\n  Topic {tid:3d}  count={int(row['Count']):,}")
        print(f"    words: {', '.join(words)}")
        reps = model.get_representative_docs(tid) or []
        for i, doc in enumerate(reps[:3], 1):
            snippet = doc.replace("\n", " ").replace("\r", " ")[:140]
            print(f"    [{i}] {snippet}")

    print()
    print("Saved:")
    print(f"  model -> {model_dir}")
    print(f"  data  -> {out_parquet}")
    print("=" * 72)


if __name__ == "__main__":
    main()
