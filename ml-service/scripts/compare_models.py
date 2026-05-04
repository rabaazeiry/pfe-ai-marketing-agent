"""Phase 3.8 — side-by-side comparison of bertopic_v1 (no mask) vs v2 (masked).

Recomputes NPMI / Diversity / Outliers / Brand-concentration for both models
on their respective corpora, then renders a comparison report to stdout and
to ``data/v1_vs_v2_comparison.txt``.

Brand-concentration (the goal of Phase 3.8): for each topic, compute the
share of posts coming from the single most-represented Instagram username.
- HIGH   if top brand >= 50%
- MEDIUM if 25-49%
- LOW    if < 25%
The "mean top-brand share" is post-weighted (sum over topics of
top_brand_count / sum over topics of topic_count).
"""
from __future__ import annotations

# Windows DLL workaround: torch BEFORE bertopic. See project memory.
import torch  # noqa: F401

import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd
from sklearn.feature_extraction.text import CountVectorizer

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from bertopic import BERTopic  # noqa: E402

from corpus.topic_model import VECTORIZER_KWARGS, compute_metrics  # noqa: E402

V1_MODEL_DIR = ROOT / "models" / "bertopic_v1"
V1_PARQUET = ROOT / "data" / "df_master_with_topics.parquet"
V1_TEXT_COL = "caption_clean"

V2_MODEL_DIR = ROOT / "models" / "bertopic_v2"
V2_PARQUET = ROOT / "data" / "df_master_masked_with_topics.parquet"
V2_TEXT_COL = "caption_masked"

OUT_PATH = ROOT / "data" / "v1_vs_v2_comparison.txt"


def _classify(top_pct: float) -> str:
    if top_pct >= 50.0:
        return "HIGH"
    if top_pct >= 25.0:
        return "MEDIUM"
    return "LOW"


def _load(model_dir: Path, parquet: Path, text_col: str) -> Tuple[
    BERTopic, pd.DataFrame, List[str]
]:
    model = BERTopic.load(str(model_dir))
    df = pd.read_parquet(parquet)
    df = df[df["has_caption"]].reset_index(drop=True).copy()
    if text_col == "caption_masked":
        df = df[df["caption_masked"].str.strip() != ""].reset_index(drop=True)
    docs = df[text_col].tolist()
    # Re-attach + fit vectorizer (per BERTopic save/load gotcha — see memory).
    vec = CountVectorizer(**VECTORIZER_KWARGS)
    vec.fit(docs)
    model.vectorizer_model = vec
    return model, df, docs


def _brand_concentration(df: pd.DataFrame) -> Dict:
    """Per-topic top-brand share + aggregate stats."""
    topic_ids = sorted(t for t in df["topic_id"].unique() if t != -1)
    rows = []
    total_top_brand_count = 0
    total_count = 0
    bucket = Counter({"HIGH": 0, "MEDIUM": 0, "LOW": 0})

    for tid in topic_ids:
        sub = df[df["topic_id"] == tid]
        n = len(sub)
        if n == 0:
            continue
        bc = sub["username"].value_counts()
        top_uname = str(bc.index[0])
        top_n = int(bc.iloc[0])
        top_pct = top_n / n * 100.0
        bucket[_classify(top_pct)] += 1
        total_top_brand_count += top_n
        total_count += n
        rows.append(
            {
                "topic_id": int(tid),
                "count": n,
                "top_brand": top_uname,
                "top_brand_count": top_n,
                "top_brand_pct": top_pct,
            }
        )

    mean_top_share = (
        total_top_brand_count / total_count * 100.0 if total_count else 0.0
    )
    return {
        "per_topic": rows,
        "n_topics": len(topic_ids),
        "mean_top_brand_share_pct": mean_top_share,
        "bucket": dict(bucket),
    }


def _summarize(name: str, model_dir: Path, parquet: Path, text_col: str) -> Dict:
    print(f"  Loading {name}: {model_dir.name}")
    model, df, docs = _load(model_dir, parquet, text_col)

    # Topic-id ordering: get the saved topic IDs from the parquet (same as
    # was used at training time). Matches model.topic_representations_.
    topics = df["topic_id"].tolist()
    metrics = compute_metrics(model, docs, topics)
    bc = _brand_concentration(df)

    # Top-5 topics by document count (excluding -1).
    info = model.get_topic_info()
    info = info[info["Topic"] != -1].head(5)
    top5 = []
    bc_lookup = {r["topic_id"]: r for r in bc["per_topic"]}
    for _, row in info.iterrows():
        tid = int(row["Topic"])
        words = [w for w, _ in model.get_topic(tid)][:10]
        bc_row = bc_lookup.get(tid)
        top5.append(
            {
                "topic_id": tid,
                "count": int(row["Count"]),
                "words": words,
                "top_brand": bc_row["top_brand"] if bc_row else "?",
                "top_brand_pct": bc_row["top_brand_pct"] if bc_row else 0.0,
            }
        )

    return {
        "name": name,
        "n_topics": metrics["n_topics"],
        "outliers_ratio": metrics["outliers_ratio"],
        "outliers_count": metrics["outliers_count"],
        "npmi": metrics["npmi_coherence"],
        "diversity": metrics["topic_diversity"],
        "mean_top_brand_share_pct": bc["mean_top_brand_share_pct"],
        "bucket": bc["bucket"],
        "top5": top5,
    }


def _render(v1: Dict, v2: Dict) -> str:
    lines: List[str] = []
    lines.append("=" * 96)
    lines.append("Phase 3.8 — bertopic_v1 (no mask) vs bertopic_v2 (brand-masked)")
    lines.append("=" * 96)
    lines.append("")
    lines.append(f"{'metric':<32} {'v1 (no mask)':<22} {'v2 (masked)':<22} delta")
    lines.append("-" * 96)

    def row(label, v1v, v2v, fmt="{:>20}", delta_fmt=None):
        if delta_fmt is None:
            delta = ""
        else:
            try:
                delta = delta_fmt.format(v2v - v1v)
            except Exception:
                delta = ""
        lines.append(
            f"{label:<32} {fmt.format(v1v):<22} {fmt.format(v2v):<22} {delta}"
        )

    lines.append(f"{'n_topics':<32} {v1['n_topics']:<22} {v2['n_topics']:<22} "
                 f"{v2['n_topics'] - v1['n_topics']:+d}")
    lines.append(f"{'NPMI (post-reduction)':<32} {v1['npmi']:<22.4f} "
                 f"{v2['npmi']:<22.4f} {v2['npmi'] - v1['npmi']:+.4f}")
    lines.append(f"{'Diversity (post-reduction)':<32} {v1['diversity']:<22.4f} "
                 f"{v2['diversity']:<22.4f} {v2['diversity'] - v1['diversity']:+.4f}")
    v1_out = f"{v1['outliers_count']:,} ({v1['outliers_ratio']*100:.1f}%)"
    v2_out = f"{v2['outliers_count']:,} ({v2['outliers_ratio']*100:.1f}%)"
    out_delta = (v2['outliers_ratio'] - v1['outliers_ratio']) * 100
    lines.append(f"{'Outliers':<32} {v1_out:<22} {v2_out:<22} {out_delta:+.1f}pp")
    lines.append(
        f"{'Mean top-brand share':<32} "
        f"{v1['mean_top_brand_share_pct']:<22.1f} "
        f"{v2['mean_top_brand_share_pct']:<22.1f} "
        f"{v2['mean_top_brand_share_pct']-v1['mean_top_brand_share_pct']:+.1f}pp"
    )

    lines.append("")
    lines.append("Brand-concentration buckets")
    lines.append("-" * 96)
    for b in ("HIGH", "MEDIUM", "LOW"):
        v1n = v1["bucket"].get(b, 0)
        v2n = v2["bucket"].get(b, 0)
        lines.append(f"  {b:<8} (>={'50%' if b == 'HIGH' else '25%' if b == 'MEDIUM' else '<25%'})   "
                     f"v1: {v1n:>2}   v2: {v2n:>2}   delta: {v2n - v1n:+d}")

    lines.append("")
    lines.append("Top 5 topics — v1 vs v2 (count, words, top brand)")
    lines.append("-" * 96)

    for i in range(max(len(v1["top5"]), len(v2["top5"]))):
        v1t = v1["top5"][i] if i < len(v1["top5"]) else None
        v2t = v2["top5"][i] if i < len(v2["top5"]) else None
        lines.append("")
        lines.append(f"  rank {i+1}")
        if v1t:
            lines.append(
                f"    v1  T{v1t['topic_id']:<3} count={v1t['count']:<5} "
                f"top=@{v1t['top_brand']} ({v1t['top_brand_pct']:.0f}%)"
            )
            lines.append(f"        words: {', '.join(v1t['words'])}")
        else:
            lines.append("    v1  (no topic)")
        if v2t:
            lines.append(
                f"    v2  T{v2t['topic_id']:<3} count={v2t['count']:<5} "
                f"top=@{v2t['top_brand']} ({v2t['top_brand_pct']:.0f}%)"
            )
            lines.append(f"        words: {', '.join(v2t['words'])}")
        else:
            lines.append("    v2  (no topic)")

    lines.append("")
    lines.append("=" * 96)
    return "\n".join(lines) + "\n"


def main() -> None:
    print("Loading models + parquets ...")
    v1 = _summarize("v1", V1_MODEL_DIR, V1_PARQUET, V1_TEXT_COL)
    v2 = _summarize("v2", V2_MODEL_DIR, V2_PARQUET, V2_TEXT_COL)

    text = _render(v1, v2)
    print()
    print(text, end="")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8") as f:
        f.write(text)
    print(f"\nWrote: {OUT_PATH}  ({OUT_PATH.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
