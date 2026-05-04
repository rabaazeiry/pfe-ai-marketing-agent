"""Phase 3.7: per-topic inspection + auto-suggested topic names (FR draft).

For each non-outlier topic in models/bertopic_v1, prints:
  - top 10 words + c-tf-idf scores
  - 3 representative posts (truncated)
  - per-topic stats: count, language distribution, industry distribution
  - auto-suggested name / quality / KEEP-or-REMOVE decision

Writes a draft YAML at data/topics_validated_DRAFT.yaml for human review.
The YAML is intended to be edited by hand: refine `suggested_name`, change
`decision` to MERGE_WITH_X where appropriate, adjust `quality`, etc.
"""
from __future__ import annotations

# Windows DLL workaround: torch BEFORE bertopic. See project memory.
import torch  # noqa: F401

import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd
import yaml
from sklearn.feature_extraction.text import CountVectorizer

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from bertopic import BERTopic  # noqa: E402

from corpus.topic_model import VECTORIZER_KWARGS  # noqa: E402

MODEL_DIR = ROOT / "models" / "bertopic_v1"
DATA_PATH = ROOT / "data" / "df_master_with_topics.parquet"
OUT_PATH = ROOT / "data" / "topics_validated_DRAFT.yaml"

# --- Heuristic vocabularies for auto-suggestion -----------------------------
# Tweak these freely — they only drive the FIRST DRAFT.

BRAND_TERMS: Dict[str, str] = {
    "mango": "Mango",
    "mangowoman": "Mango",
    "zara": "Zara",
    "zarawoman": "Zara",
    "kfc": "KFC",
    "nuxe": "Nuxe",
    "nuxetunisie": "Nuxe",
    "bioderma": "Bioderma",
    "floraison": "Floraison",
    "freyatunisie": "Freya",
    "dior": "Dior",
    "chanel": "Chanel",
    "ysl": "YSL",
    "loreal": "L'Oréal",
}

# Ordered: more specific themes first.
THEME_RULES: List[Tuple[set, str]] = [
    ({"ramadan", "iftar", "ramadanvibes", "ramadanesque"}, "Ramadan"),
    ({"cocktail", "cocktails", "bar"}, "Cocktails & bar"),
    ({"spa", "wellness", "massage"}, "Spa & bien-être"),
    ({"skincare", "skincareroutine", "kbeauty", "selfcare", "skincaretips"}, "Routine soins"),
    ({"parfum", "parfums", "fragrance"}, "Parfums"),
    ({"iftar"}, "Ramadan"),
    ({"hotel", "hotels", "resort"}, "Séjour & hôtellerie"),
    ({"restaurant", "saveurs", "menu"}, "Restauration"),
    ({"giveaway", "concours"}, "Concours / Giveaway"),
]

INDUSTRY_PREFIXES_FR: Dict[str, str] = {
    "beauty": "Beauté",
    "hotels": "Hôtellerie",
    "restaurants": "Restauration",
    "fashion": "Mode",
    "patisserie": "Pâtisserie",
}

# Words that strongly suggest a given language when present in top-words list.
FR_MARKERS = {
    "parfum", "éclat", "crème", "soins", "amour", "cocktail", "café",
    "soyeuse", "saveurs", "ambiance", "moment", "vous", "nos", "votre",
    "découvrez", "disponible", "tunisie", "tunis", "sousse",
}
EN_MARKERS = {
    "discover", "collection", "new", "thank", "skincare", "skin", "order",
    "now", "best", "selfcare", "kbeauty", "selection",
}


def detect_language(top_words: List[str]) -> str:
    """Heuristic language flag for a topic from its top words."""
    has_ar = any(0x0600 <= ord(c) <= 0x06FF for w in top_words for c in w)
    has_fr = (
        any(w in FR_MARKERS for w in top_words)
        or any(c in "éèêëàâçôîïùû" for w in top_words for c in w)
    )
    has_en = any(w in EN_MARKERS for w in top_words)

    flags = sum([has_fr, has_en, has_ar])
    if flags >= 2:
        return "mixed"
    if has_ar:
        return "AR"
    if has_en:
        return "EN"
    return "FR"  # default fallback


def _is_noise_token(w: str) -> bool:
    """Tokens that look like phone fragments / pure numerics / 1-2 char junk."""
    bare = w.replace(" ", "")
    if not bare:
        return True
    if bare.isdigit():
        return True
    if len(bare) <= 2 and bare.isalnum():
        return True
    return False


def estimate_quality(top_words: List[str]) -> int:
    """1-5 quality score driven by share of noise tokens in the top-N words."""
    noise = sum(1 for w in top_words if _is_noise_token(w))
    if noise >= 5:
        return 1
    if noise >= 3:
        return 2
    if noise == 0:
        return 5
    if noise == 1:
        return 4
    return 3


def _first_salient_word(top_words: List[str]) -> str:
    """Pick a French-friendly content word for the topic name fallback."""
    for w in top_words:
        bare = w.split()[0] if " " in w else w
        if bare.isalpha() and len(bare) >= 4:
            return bare
    return top_words[0] if top_words else "topic"


def suggest_name(
    top_words: List[str],
    dominant_industry: str,
    language: str,
) -> str:
    """Heuristic name suggestion in French (with multilingue suffix when mixed)."""
    word_set = {w.lower() for w in top_words}

    # 1. Brand match takes precedence.
    for term, label in BRAND_TERMS.items():
        if term in word_set:
            base = f"Marque {label}"
            return f"{base} (multilingue)" if language == "mixed" else base

    # 2. Theme keyword match.
    for keywords, label in THEME_RULES:
        if word_set & keywords:
            if label == "Ramadan":
                # Add language hint for Ramadan (we have one AR + one FR cluster).
                if language == "AR":
                    return "Ramadan (arabe)"
                if language == "FR":
                    return "Ramadan (français)"
                return "Ramadan (multilingue)"
            return f"{label} (multilingue)" if language == "mixed" else label

    # 3. Industry-prefixed fallback.
    prefix = INDUSTRY_PREFIXES_FR.get(dominant_industry, "Sujet")
    salient = _first_salient_word(top_words)
    base = f"{prefix} – {salient}"
    return f"{base} (multilingue)" if language == "mixed" else base


def suggest_decision(quality: int) -> str:
    """Auto KEEP/REMOVE based on quality. MERGE left for human review."""
    return "REMOVE" if quality <= 2 else "KEEP"


def reasoning_for(quality: int, top_words: List[str], language: str) -> str:
    if quality == 5:
        return f"Vocabulaire cohérent et thématique ({language})."
    if quality == 4:
        return f"Sujet clair, un terme marginal ({language})."
    if quality == 3:
        return f"Thème reconnaissable mais bruit modéré ({language})."
    if quality == 2:
        return f"Beaucoup de tokens parasites (chiffres / fragments) — à retirer ({language})."
    return f"Topic parasite (numéros, codes, bruit) — à retirer ({language})."


def _truncate(text: str, n: int) -> str:
    text = text.replace("\n", " ").replace("\r", " ").strip()
    return (text[: n - 1] + "…") if len(text) > n else text


def _pick_representative_docs(
    docs_in_topic: List[str],
    top_words: List[str],
    k: int = 3,
) -> List[str]:
    """Score docs by overlap with the topic's top words; return the best k.

    BERTopic.save() does not persist `representative_docs_` (it reloads as
    an empty dict), so we recompute a sensible substitute here. Score is
    the count of top-10 topic words found as substrings in the lower-cased
    doc, with longer docs as tiebreaker.
    """
    if not docs_in_topic:
        return []
    needles = [w for w in top_words if w]
    scored: List[Tuple[int, int, str]] = []
    for doc in docs_in_topic:
        text = doc.lower() if isinstance(doc, str) else ""
        score = sum(1 for w in needles if w in text)
        scored.append((score, len(text), doc))
    # Sort: highest score first, then longer doc first.
    scored.sort(key=lambda x: (-x[0], -x[1]))
    return [doc for _, _, doc in scored[:k] if doc]


def analyze_topic(
    model: BERTopic,
    df: pd.DataFrame,
    tid: int,
) -> Dict[str, Any]:
    pairs = model.get_topic(tid) or []
    top_words_with_scores = [(w, float(s)) for w, s in pairs[:10]]
    top_words = [w for w, _ in top_words_with_scores]

    sub = df[df["topic_id"] == tid]
    sub_docs = sub["caption_clean"].tolist()
    reps = _pick_representative_docs(sub_docs, top_words, k=3)
    reps_truncated = [_truncate(r, 200) for r in reps]
    representative_post = _truncate(reps[0], 300) if reps else ""

    count = int(len(sub))
    lang_dist = Counter(sub["caption_lang"].fillna("unknown"))
    industry_dist = Counter(sub["industry_simple"].fillna("unknown"))
    dominant_industry = (
        industry_dist.most_common(1)[0][0] if industry_dist else "unknown"
    )

    language = detect_language(top_words)
    quality = estimate_quality(top_words)
    name = suggest_name(top_words, dominant_industry, language)
    decision = suggest_decision(quality)
    reasoning = reasoning_for(quality, top_words, language)

    return {
        "topic_id": int(tid),
        "count": count,
        "dominant_industry": dominant_industry,
        "language": language,
        "quality": quality,
        "decision": decision,
        "suggested_name": name,
        "reasoning": reasoning,
        "representative_words": top_words,
        "representative_post": representative_post,
        "industry_distribution": dict(industry_dist.most_common()),
        "language_distribution": dict(lang_dist.most_common()),
        "top_words_scores": [
            {"word": w, "score": round(s, 6)} for w, s in top_words_with_scores
        ],
        "_representative_posts_preview": reps_truncated,
    }


def print_topic_block(entry: Dict[str, Any]) -> None:
    print()
    print("=" * 88)
    print(f"TOPIC {entry['topic_id']:3d}   count={entry['count']:,}")
    print("=" * 88)

    print("  Top words (c-TF-IDF):")
    for item in entry["top_words_scores"]:
        print(f"    {item['word']:<28}  {item['score']:.4f}")

    print()
    print("  Representative posts:")
    for i, snip in enumerate(entry["_representative_posts_preview"], 1):
        print(f"    [{i}] {snip}")

    print()
    print("  Stats:")
    total = entry["count"] or 1
    lang_str = ", ".join(
        f"{k}={v} ({v / total * 100:.0f}%)"
        for k, v in entry["language_distribution"].items()
    )
    ind_str = ", ".join(
        f"{k}={v} ({v / total * 100:.0f}%)"
        for k, v in entry["industry_distribution"].items()
    )
    print(f"    Languages:  {lang_str}")
    print(f"    Industries: {ind_str}")

    print()
    print("  AUTO-SUGGESTION:")
    print(f"    Name:      {entry['suggested_name']}")
    print(f"    Language:  {entry['language']}")
    print(f"    Quality:   {entry['quality']}/5")
    print(f"    Decision:  {entry['decision']}")
    print(f"    Reasoning: {entry['reasoning']}")


def _load_setup() -> Tuple[BERTopic, pd.DataFrame, List[str]]:
    print(f"Loading model from {MODEL_DIR} ...")
    model = BERTopic.load(str(MODEL_DIR))

    print(f"Loading data from {DATA_PATH} ...")
    df = pd.read_parquet(DATA_PATH)
    df = df[df["has_caption"]].reset_index(drop=True).copy()
    print(f"  {len(df):,} captioned posts.")

    docs = df["caption_clean"].tolist()
    print("Re-attaching configured vectorizer + fitting on corpus ...")
    vec = CountVectorizer(**VECTORIZER_KWARGS)
    vec.fit(docs)
    model.vectorizer_model = vec
    print(f"  vocab size: {len(vec.get_feature_names_out()):,}")

    return model, df, docs


def main() -> None:
    model, df, _docs = _load_setup()

    topic_ids = sorted(t for t in df["topic_id"].unique() if t != -1)
    print()
    print(f"Inspecting {len(topic_ids)} non-outlier topics ...")

    entries: List[Dict[str, Any]] = []
    for tid in topic_ids:
        entry = analyze_topic(model, df, int(tid))
        print_topic_block(entry)
        # Drop the console-only preview before YAML serialization.
        yaml_entry = {k: v for k, v in entry.items() if not k.startswith("_")}
        entries.append(yaml_entry)

    payload = {
        "_meta": {
            "model_dir": str(MODEL_DIR),
            "data_source": str(DATA_PATH),
            "n_topics": len(topic_ids),
            "n_docs": int(len(df)),
            "instructions": (
                "DRAFT auto-generated by scripts/inspect_topics.py. "
                "Edit suggested_name, change decision to KEEP / REMOVE / "
                "MERGE_WITH_<topic_id>, refine quality (1-5) and reasoning. "
                "Save as topics_validated.yaml when finalized."
            ),
        },
        "topics": entries,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8") as f:
        yaml.dump(
            payload,
            f,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
            width=100,
        )

    print()
    print("=" * 88)
    print(f"Wrote DRAFT YAML: {OUT_PATH}")
    print("Edit it manually, then save as topics_validated.yaml when finalized.")
    print("=" * 88)


if __name__ == "__main__":
    main()
