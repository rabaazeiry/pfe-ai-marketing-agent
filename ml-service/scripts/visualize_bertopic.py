"""Phase 3.6: generate BERTopic HTML visualizations from the trained model.

Produces six interactive Plotly views in ml-service/visualizations/:
  - topic_words.html              (per-topic top-word bar charts)
  - topic_distance_map.html       (UMAP 2D projection of topics)
  - topics_per_industry.html      (topic distribution per industry_simple)
  - topics_over_time.html         (topic prevalence across published_at)
  - topic_hierarchy.html          (agglomerative hierarchy of topics)
  - topic_similarity_heatmap.html (topic-topic c-tf-idf cosine similarity)

Each visualization is built independently inside a try/except so a single
failure does not abort the others. Final summary table reports per-file
status + size.
"""
from __future__ import annotations

# Windows DLL workaround: torch BEFORE bertopic. See project memory.
import torch  # noqa: F401

import sys
import traceback
from pathlib import Path
from typing import Callable, List, Tuple

import pandas as pd
from sklearn.feature_extraction.text import CountVectorizer

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from bertopic import BERTopic  # noqa: E402

from corpus.topic_model import VECTORIZER_KWARGS  # noqa: E402

MODEL_DIR = ROOT / "models" / "bertopic_v1"
DATA_PATH = ROOT / "data" / "df_master_with_topics.parquet"
OUT_DIR = ROOT / "visualizations" / "v1"


def _load_model_and_data() -> Tuple[BERTopic, pd.DataFrame, List[str]]:
    print(f"Loading model from {MODEL_DIR} ...")
    model = BERTopic.load(str(MODEL_DIR))

    print(f"Loading data from {DATA_PATH} ...")
    df = pd.read_parquet(DATA_PATH)
    df_in = df[df["has_caption"]].reset_index(drop=True).copy()
    print(f"  {len(df_in):,} captioned posts (matches training input).")
    docs = df_in["caption_clean"].tolist()

    # BERTopic.save() does not persist the vectorizer config (see project
    # memory: project_bertopic_update_topics_resets_vectorizer.md). We
    # re-attach a CountVectorizer with our multilingual stop_words + (1,2)
    # n-grams AND fit it on the corpus so it has a vocabulary. Required
    # because topics_per_class() / topics_over_time() call _c_tf_idf with
    # fit=False, which calls vectorizer_model.transform() — that needs a
    # fitted vocabulary or it raises NotFittedError. Fitting on raw docs
    # vs. per-topic concatenations produces the same vocabulary set.
    print("Re-attaching configured vectorizer + fitting on corpus ...")
    vec = CountVectorizer(**VECTORIZER_KWARGS)
    vec.fit(docs)
    model.vectorizer_model = vec
    print(f"  vocab size: {len(vec.get_feature_names_out()):,}")

    return model, df_in, docs


def _run_viz(name: str, path: Path, builder: Callable) -> Tuple[str, Path, str]:
    """Build one figure and write it to HTML; return (name, path, status_or_error)."""
    print(f"  -> {name} ... ", end="", flush=True)
    try:
        fig = builder()
        fig.write_html(str(path))
        print("ok")
        return name, path, "OK"
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL ({exc.__class__.__name__})")
        traceback.print_exc()
        return name, path, f"FAIL: {exc.__class__.__name__}: {exc}"


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    model, df_in, docs = _load_model_and_data()

    # Pre-compute heavy per-group aggregations OUTSIDE the per-viz try blocks
    # so failures attribute correctly. Each is wrapped in its own try below.
    classes = df_in["industry_simple"].fillna("unknown").tolist()
    timestamps = pd.to_datetime(df_in["published_at"]).tolist()

    print()
    print(f"Building visualizations into {OUT_DIR} ...")

    jobs: List[Tuple[str, str, Callable]] = [
        (
            "topic_words",
            "topic_words.html",
            lambda: model.visualize_barchart(top_n_topics=15),
        ),
        (
            "topic_distance_map",
            "topic_distance_map.html",
            lambda: model.visualize_topics(),
        ),
        (
            "topics_per_industry",
            "topics_per_industry.html",
            lambda: model.visualize_topics_per_class(
                model.topics_per_class(docs, classes=classes)
            ),
        ),
        (
            "topics_over_time",
            "topics_over_time.html",
            lambda: model.visualize_topics_over_time(
                model.topics_over_time(docs, timestamps, nr_bins=24)
            ),
        ),
        (
            "topic_hierarchy",
            "topic_hierarchy.html",
            lambda: model.visualize_hierarchy(),
        ),
        (
            "topic_similarity_heatmap",
            "topic_similarity_heatmap.html",
            lambda: model.visualize_heatmap(),
        ),
    ]

    results: List[Tuple[str, Path, str]] = []
    for name, filename, builder in jobs:
        path = OUT_DIR / filename
        results.append(_run_viz(name, path, builder))

    _print_summary(results)


def _print_summary(results: List[Tuple[str, Path, str]]) -> None:
    print()
    print("=" * 88)
    print("Phase 3.6 - BERTopic visualizations summary")
    print("=" * 88)
    print(f"{'name':<28} {'file':<32} {'size':>10}  status")
    print("-" * 88)

    n_ok = 0
    for name, path, status in results:
        if path.exists():
            size_bytes = path.stat().st_size
            if size_bytes < 1024:
                size_str = f"{size_bytes} B"
            elif size_bytes < 1024 * 1024:
                size_str = f"{size_bytes / 1024:.1f} KB"
            else:
                size_str = f"{size_bytes / 1024 / 1024:.2f} MB"
        else:
            size_str = "-"
        if status == "OK":
            n_ok += 1
        print(f"{name:<28} {path.name:<32} {size_str:>10}  {status}")

    print("-" * 88)
    print(f"{n_ok}/{len(results)} visualizations succeeded.")
    print(f"Output dir: {OUT_DIR}")
    print("=" * 88)


if __name__ == "__main__":
    main()
