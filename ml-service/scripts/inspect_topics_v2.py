"""Phase 3.8 — per-topic inspection for bertopic_v2 (brand-masked).

For each non-outlier topic in models/bertopic_v2, prints:
  - top 10 words + c-tf-idf scores
  - top 3 brands (@username) by post count + percentages
  - concentration classification (HIGH / MEDIUM / LOW)
  - top 2 representative posts (recomputed via word-overlap; BERTopic.save()
    does not persist representative_docs_, see project memory)
  - heuristic suggested generic theme name (word-driven; brands are masked
    so brand-name suggestions are intentionally absent)

Writes a tee'd report to data/v2_topics_inspection.txt.
"""
from __future__ import annotations

# Windows DLL workaround: torch BEFORE bertopic. See project memory.
import torch  # noqa: F401

import sys
from pathlib import Path
from typing import List, Tuple

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from bertopic import BERTopic  # noqa: E402

MODEL_DIR = ROOT / "models" / "bertopic_v2"
DATA_PATH = ROOT / "data" / "df_master_masked_with_topics.parquet"
OUT_PATH = ROOT / "data" / "v2_topics_inspection.txt"

# --- Theme heuristics (word-driven; v2 has no brand names in top words) -----

THEME_RULES: List[Tuple[set, str]] = [
    # Order matters — most specific themes first.
    ({"ramadan", "iftar", "ramadanvibes", "ramadanesque"}, "Ramadan & iftar"),
    ({"valentin", "saint valentin", "valentine", "valentinesday", "saintvalentin"},
     "Saint Valentin"),
    ({"anti", "anti âge", "âge", "rides", "imperfections"}, "Anti-âge & soin"),
    ({"cheveux", "shampooing", "haircare", "capillaire", "capillaires"},
     "Cheveux & haircare"),
    ({"skincare", "skincareroutine", "kbeauty", "selfcare", "skincaretips"},
     "Routine soins (hashtags)"),
    ({"البشرة", "روتين", "soyeuse", "crème soyeuse", "serum"},
     "Soins de la peau (multilingue)"),
    ({"cocktail", "cocktails", "bar"}, "Cocktails & bar"),
    ({"spa", "wellness", "massage"}, "Spa & bien-être"),
    ({"parfum", "parfums", "fragrance"}, "Parfums"),
    ({"gâteau", "gâteaux", "pâtisserie", "pâtisseries"}, "Pâtisserie & gâteaux"),
    ({"iftar"}, "Ramadan & iftar"),
    ({"pizza", "papa johns", "slice", "pcs", "bucket", "chicken"},
     "Restauration / fast-food (commande)"),
    ({"black friday", "blackfriday", "blackfridaydeal", "promo", "promotion",
      "soldes", "deal"}, "Promotions & offres"),
    ({"summer", "été", "sunset", "sea", "plage", "beach"}, "Été & saisonnalité"),
    ({"winter", "hiver", "cold days", "outerwear", "jacket"}, "Hiver & saisonnalité"),
    ({"denim", "jeans"}, "Mode – denim"),
    ({"collection", "new collection", "ss26", "trf", "night out"},
     "Mode – nouvelle collection"),
    ({"hotel", "hotels", "resort", "réservation", "reservation"},
     "Hôtellerie & réservation"),
    ({"séjour", "séjours", "vacances", "réservez", "offre", "offres"},
     "Hôtellerie – séjours & offres"),
    ({"protection", "spf50", "spf", "solaire", "photoderm", "haute protection"},
     "Protection solaire"),
    ({"restaurant", "saveurs", "menu"}, "Restauration"),
    ({"giveaway", "concours"}, "Concours / giveaway"),
    ({"eid", "festivewear"}, "Eid & festive"),
]

NOISE_FALLBACK_HINTS = (
    # If most top words look like phone fragments / order codes, label it.
    "order", "now", "724", "71", "000", "961", "628", "52",
)


def _classify(top_pct: float) -> str:
    if top_pct >= 50.0:
        return "HIGH"
    if top_pct >= 25.0:
        return "MEDIUM"
    return "LOW"


def _truncate(text: str, n: int) -> str:
    text = (text or "").replace("\n", " ").replace("\r", " ").strip()
    return (text[: n - 1] + "…") if len(text) > n else text


def _pick_reps(docs: List[str], needles: List[str], k: int = 2) -> List[str]:
    """Score docs by overlap with topic top-words (substring count); top-k by
    score with longer-doc tiebreak. BERTopic.save() drops representative_docs_."""
    if not docs:
        return []
    scored: List[Tuple[int, int, str]] = []
    for doc in docs:
        text = doc.lower() if isinstance(doc, str) else ""
        score = sum(1 for w in needles if w and w in text)
        scored.append((score, len(text), doc))
    scored.sort(key=lambda x: (-x[0], -x[1]))
    return [d for _, _, d in scored[:k] if d]


def _suggest_name(top_words: List[str]) -> str:
    """Heuristic theme name from top words. v2 corpus has no brand tokens, so
    naming is purely thematic. Theme rules run BEFORE the noise fallback so
    a topic with valid theme words + some phone-bigram noise (e.g. cocktails
    + reservation phone fragments) lands on the theme, not on "Bruit"."""
    word_set = {w.lower() for w in top_words}

    for keywords, label in THEME_RULES:
        if word_set & keywords:
            return label

    # No theme matched — check for noise dominance.
    noise = sum(
        1
        for w in top_words
        if w.replace(" ", "").isdigit() or w.lower() in NOISE_FALLBACK_HINTS
    )
    if noise >= 4:
        return "Bruit (numéros / codes commande)"

    # Generic fallback: first content-y word.
    for w in top_words:
        bare = w.split()[0] if " " in w else w
        if bare.isalpha() and len(bare) >= 4:
            return f"Sujet – {bare}"
    return "Sujet (non classifié)"


def _block(model: BERTopic, df: pd.DataFrame, tid: int) -> List[str]:
    pairs = model.get_topic(tid) or []
    top_words_with_scores = [(w, float(s)) for w, s in pairs[:10]]
    top_words = [w for w, _ in top_words_with_scores]

    sub = df[df["topic_id"] == tid]
    count = len(sub)

    bc = sub["username"].fillna("(unknown)").value_counts()
    top3 = bc.head(3)
    if count > 0:
        top_pct = float(top3.iloc[0]) / count * 100.0
    else:
        top_pct = 0.0
    concentration = _classify(top_pct)

    docs = sub["caption_masked"].tolist()
    # Use original (unmasked) caption_clean for the representative posts so
    # the human can read meaningful, brand-bearing text. Fall back to masked
    # if caption_clean isn't present in this parquet.
    rep_source_col = "caption_clean" if "caption_clean" in sub.columns else "caption_masked"
    reps = _pick_reps(sub[rep_source_col].tolist(), top_words, k=2)
    suggested = _suggest_name(top_words)

    lines: List[str] = []
    lines.append("=" * 88)
    lines.append(f"TOPIC {tid} — count: {count} posts")
    lines.append("=" * 88)
    word_str = ", ".join(f"{w} ({s:.4f})" for w, s in top_words_with_scores)
    lines.append(f"  Top words: {word_str}")
    lines.append("")
    lines.append("  Top 3 brands:")
    for rank, (uname, n_posts) in enumerate(top3.items(), 1):
        pct = n_posts / count * 100.0 if count else 0.0
        lines.append(f"    {rank}. @{uname}  → {n_posts} posts ({pct:.1f}%)")
    if len(top3) < 3:
        for r in range(len(top3) + 1, 4):
            lines.append(f"    {r}. (no further brands)")
    lines.append(f"  Concentration: {concentration}")
    lines.append("")
    lines.append("  Representative posts:")
    if reps:
        for i, doc in enumerate(reps, 1):
            lines.append(f'    [{i}] "{_truncate(doc, 200)}"')
    else:
        lines.append("    (none)")
    lines.append("")
    lines.append(f'  Suggested generic name: "{suggested}"')
    lines.append("")
    return lines


def main() -> None:
    print(f"Loading model from {MODEL_DIR} ...")
    model = BERTopic.load(str(MODEL_DIR))

    print(f"Loading data from {DATA_PATH} ...")
    df = pd.read_parquet(DATA_PATH)
    print(f"  rows: {len(df):,}   cols: {len(df.columns)}")

    topic_ids = sorted(t for t in df["topic_id"].unique() if t != -1)
    print(f"  non-outlier topics: {len(topic_ids)}")

    report: List[str] = []
    report.append("=" * 88)
    report.append("Phase 3.8 — bertopic_v2 (brand-masked) per-topic inspection")
    report.append("=" * 88)
    report.append(f"  model:   {MODEL_DIR}")
    report.append(f"  data:    {DATA_PATH}")
    report.append(f"  topics:  {len(topic_ids)}  (non-outlier)")
    report.append(f"  posts:   {len(df):,}")
    report.append("")

    concentration_count = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for tid in topic_ids:
        block = _block(model, df, int(tid))
        report.extend(block)
        # Quick summary tally — re-scan the block for the Concentration line.
        for line in block:
            if line.startswith("  Concentration:"):
                tag = line.split(":", 1)[1].strip()
                if tag in concentration_count:
                    concentration_count[tag] += 1
                break

    report.append("=" * 88)
    report.append("CONCENTRATION SUMMARY")
    report.append("=" * 88)
    for k, v in concentration_count.items():
        report.append(f"  {k:<6} : {v}")
    report.append("=" * 88)

    text = "\n".join(report) + "\n"
    print()
    print(text, end="")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8") as f:
        f.write(text)
    print(f"\nWrote: {OUT_PATH}  ({OUT_PATH.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
