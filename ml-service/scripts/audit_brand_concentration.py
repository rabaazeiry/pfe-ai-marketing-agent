"""Phase 3.7 (read-only): per-topic brand-concentration audit.

For every topic in `data/topics_validated.yaml`, measures how concentrated
the topic is around a single Instagram account (username). Topics where one
brand owns >=25% of the posts are flagged as candidates for renaming
("Marque <Brand>" rather than the current thematic label).

This script DOES NOT modify `topics_validated.yaml` or any other input. It
writes a single new artifact: `data/topics_brand_audit.txt`.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Tuple

import pandas as pd
import yaml

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "data" / "df_master_with_topics.parquet"
YAML_PATH = ROOT / "data" / "topics_validated.yaml"
OUT_PATH = ROOT / "data" / "topics_brand_audit.txt"


def _classify(top_pct: float) -> str:
    if top_pct >= 50.0:
        return "HIGH"
    if top_pct >= 25.0:
        return "MEDIUM"
    return "LOW"


def _recommendation(concentration: str) -> str:
    if concentration in ("HIGH", "MEDIUM"):
        return "RENAME suggested (brand-dominated)"
    return "KEEP (genuinely thematic)"


def _truncate(text: str, n: int) -> str:
    text = (text or "").replace("\n", " ").replace("\r", " ").strip()
    return (text[: n - 1] + "…") if len(text) > n else text


def _pick_reps(docs: List[str], needles: List[str], k: int = 2) -> List[str]:
    """Score docs by occurrences of needle-words; return top-k. Longer wins ties."""
    scored: List[Tuple[int, int, str]] = []
    for doc in docs:
        text = doc.lower() if isinstance(doc, str) else ""
        score = sum(1 for w in needles if w and w in text)
        scored.append((score, len(text), doc))
    scored.sort(key=lambda x: (-x[0], -x[1]))
    return [d for _, _, d in scored[:k] if d]


def _audit_topic(
    df: pd.DataFrame,
    topic_yaml: dict,
) -> Tuple[List[str], str]:
    """Build the report block for one topic. Returns (lines, concentration)."""
    tid = int(topic_yaml["topic_id"])
    name = topic_yaml.get("suggested_name", "?")
    rep_words = list(topic_yaml.get("representative_words") or [])

    sub = df[df["topic_id"] == tid]
    count = len(sub)
    if count == 0:
        return ([f"TOPIC {tid} — empty (no rows in parquet)"], "LOW")

    industry_dist = sub["industry_simple"].fillna("unknown").value_counts()
    dominant_industry = str(industry_dist.index[0])

    brand_counts = sub["username"].fillna("(unknown)").value_counts()
    top5 = brand_counts.head(5)

    top_pct = float(top5.iloc[0]) / count * 100.0
    concentration = _classify(top_pct)

    reps = _pick_reps(sub["caption_clean"].tolist(), rep_words, k=2)
    rep_lines = [_truncate(r, 200) for r in reps]

    lines: List[str] = []
    lines.append("=" * 88)
    lines.append(f'TOPIC {tid} — current_name: "{name}"')
    lines.append("=" * 88)
    lines.append(f"  count: {count} posts")
    lines.append(f"  dominant_industry: {dominant_industry}")
    lines.append("")
    lines.append("  Top 5 brands by post count:")
    for rank, (uname, n_posts) in enumerate(top5.items(), 1):
        pct = n_posts / count * 100.0
        lines.append(f"    {rank}. @{uname}  → {n_posts} posts ({pct:.1f}% of topic)")
    if len(top5) < 5:
        for missing_rank in range(len(top5) + 1, 6):
            lines.append(f"    {missing_rank}. (no further brands)")
    lines.append("")
    lines.append(f"  Brand concentration: {concentration}")
    lines.append(
        "    - HIGH   = top brand >= 50%   "
        "MEDIUM = 25-49%   "
        "LOW = < 25%"
    )
    lines.append("")
    lines.append(
        "  Top 10 representative words: "
        + (", ".join(rep_words[:10]) if rep_words else "(none in YAML)")
    )
    lines.append("")
    lines.append("  Top 2 representative posts (truncated 200 chars):")
    if rep_lines:
        for i, snip in enumerate(rep_lines, 1):
            lines.append(f'    [{i}] "{snip}"')
    else:
        lines.append("    (none)")
    lines.append("")
    lines.append("  RECOMMENDATION:")
    lines.append(f"    {_recommendation(concentration)}")
    lines.append("")

    return lines, concentration


def main() -> None:
    if not DATA_PATH.exists():
        raise SystemExit(f"missing parquet: {DATA_PATH}")
    if not YAML_PATH.exists():
        raise SystemExit(f"missing yaml: {YAML_PATH}")

    df = pd.read_parquet(DATA_PATH)
    with YAML_PATH.open(encoding="utf-8") as f:
        validated = yaml.safe_load(f)
    topics = sorted(validated.get("topics") or [], key=lambda t: int(t["topic_id"]))

    report: List[str] = []
    report.append("=" * 88)
    report.append("Phase 3.7 — Brand-concentration audit (READ-ONLY)")
    report.append("=" * 88)
    report.append(f"  parquet: {DATA_PATH}")
    report.append(f"  yaml:    {YAML_PATH}")
    report.append(f"  topics:  {len(topics)}")
    report.append(f"  posts:   {len(df):,}")
    report.append("")

    bucket_to_ids = {"HIGH": [], "MEDIUM": [], "LOW": []}
    for topic_yaml in topics:
        block, concentration = _audit_topic(df, topic_yaml)
        report.extend(block)
        bucket_to_ids[concentration].append(int(topic_yaml["topic_id"]))

    # Final summary
    report.append("=" * 88)
    report.append("FINAL SUMMARY")
    report.append("=" * 88)
    report.append(f"  Total topics: {len(topics)}")
    for bucket in ("HIGH", "MEDIUM", "LOW"):
        ids = bucket_to_ids[bucket]
        ids_str = ", ".join(str(i) for i in ids) if ids else "(none)"
        report.append(f"  {bucket:<6} concentration: {len(ids):>2} topics  [{ids_str}]")
    report.append("=" * 88)

    text = "\n".join(report) + "\n"
    print(text, end="")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8") as f:
        f.write(text)
    print(f"\nWrote: {OUT_PATH}  ({OUT_PATH.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
