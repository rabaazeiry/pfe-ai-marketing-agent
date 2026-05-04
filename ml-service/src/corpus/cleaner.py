"""Caption preprocessing + data cleaning for the master corpus.

Phase 2.0:
  - drop duplicate post_id (keep first)
  - add booleans: has_caption, has_location, has_views
  - build caption_clean: URLs/@mentions/phones removed, hashtag '#' stripped
    (word kept), lowercased, whitespace normalized
  - build caption_lang via Arabic-codepoint check + FR/EN stopword heuristic

Known limitation: PHONE_RE matches any 8+ digit run, so long numeric IDs
(timestamps, post counts) are also stripped. Acceptable for this pass.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable, Optional, Tuple

import pandas as pd

# --- Caption-cleaning regexes (ASCII / accented Latin only) -------------------
URL_RE     = re.compile(r"https?://\S+|www\.\S+|bit\.ly/\S+", re.IGNORECASE)
MENTION_RE = re.compile(r"@\w+")
PHONE_RE   = re.compile(r"\b\d{8,}\b")
HASHTAG_RE = re.compile(r"#(\w+)")
WS_RE      = re.compile(r"\s+")

# --- Language-detection: Latin-token regex + Arabic codepoint helper ----------
TOKEN_RE = re.compile(r"[a-zàâäçéèêëîïôöùûüÿ]+")

# Arabic ranges, by codepoint (no \u escapes anywhere in source):
#   Arabic           U+0600 - U+06FF
#   Arabic Supplement U+0750 - U+077F
#   Arabic Extended-A U+08A0 - U+08FF
_ARABIC_RANGES = (
    (0x0600, 0x06FF),
    (0x0750, 0x077F),
    (0x08A0, 0x08FF),
)


def _has_arabic(text: str) -> bool:
    for ch in text:
        cp = ord(ch)
        for lo, hi in _ARABIC_RANGES:
            if lo <= cp <= hi:
                return True
    return False


FR_STOPWORDS = frozenset({
    "le", "la", "les", "de", "du", "des", "et", "est", "un", "une", "pour",
    "avec", "dans", "sur", "je", "vous", "nous", "ce", "cette", "ces", "qui",
    "que", "plus", "mais", "ou", "par", "en", "au", "aux", "à",
})
EN_STOPWORDS = frozenset({
    "the", "and", "of", "to", "a", "in", "is", "you", "that", "it", "for",
    "on", "with", "this", "are", "as", "be", "at", "by", "from", "we", "our",
    "your", "my", "have", "has", "will", "can",
})


def clean_caption(text: Optional[str]) -> str:
    if text is None:
        return ""
    if isinstance(text, float) and pd.isna(text):
        return ""
    if not isinstance(text, str) or text == "":
        return ""
    t = URL_RE.sub("", text)
    t = MENTION_RE.sub("", t)
    t = PHONE_RE.sub("", t)
    t = HASHTAG_RE.sub(r"\1", t)
    t = t.lower()
    t = WS_RE.sub(" ", t)
    return t.strip()


def mask_brands(
    text: str,
    brand_tokens: Iterable[str],
    replacement: str = "",
) -> str:
    """Replace word-boundary occurrences of any brand_token with `replacement`.

    Pure function: caller owns the token list. Tokens are sorted by length
    DESC so longer phrases (e.g. ``"el mouradi"``, ``"mango.com.tn"``) match
    before their stems (``"mango"``). Matching is case-insensitive. Multi-word
    tokens (containing spaces) are honored by escaping each token via
    ``re.escape``. After substitution, repeated whitespace is collapsed.
    Empty input returns ``""`` and an empty token list returns ``text`` as-is.
    """
    if not text:
        return ""
    tokens = sorted({t for t in brand_tokens if t}, key=len, reverse=True)
    if not tokens:
        return text
    pattern = r"\b(?:" + "|".join(re.escape(t) for t in tokens) + r")\b"
    masked = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return WS_RE.sub(" ", masked).strip()


def detect_lang(text: str) -> str:
    if not text:
        return "unknown"
    if _has_arabic(text):
        return "ar"
    tokens = set(TOKEN_RE.findall(text))
    fr_hits = len(tokens & FR_STOPWORDS)
    en_hits = len(tokens & EN_STOPWORDS)
    if fr_hits > 0 and en_hits > 0:
        return "mixed"
    if fr_hits > en_hits:
        return "fr"
    if en_hits > fr_hits:
        return "en"
    return "unknown"


def clean_master_corpus(df_in: pd.DataFrame) -> Tuple[pd.DataFrame, dict]:
    rows_before = len(df_in)
    df = (
        df_in.drop_duplicates(subset=["post_id"], keep="first")
        .reset_index(drop=True)
        .copy()
    )
    rows_after = len(df)

    raw_caption  = df["caption"].fillna("")
    raw_location = df["location"].fillna("")

    df["has_caption"]  = raw_caption.str.len() > 0
    df["has_location"] = raw_location.str.len() > 0
    df["has_views"]    = df["views"] > 0

    df["caption_clean"] = df["caption"].map(clean_caption)
    df["caption_lang"]  = df["caption_clean"].map(detect_lang)

    log = {
        "rows_before": rows_before,
        "rows_after": rows_after,
        "duplicates_dropped": rows_before - rows_after,
    }
    return df, log


def save_master_corpus_clean(df: pd.DataFrame, out_dir: Path) -> Tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)

    parquet_path = out_dir / "df_master_clean.parquet"
    csv_path     = out_dir / "df_master_clean.csv"

    df.to_parquet(parquet_path, index=False)

    df_csv = df.copy()
    df_csv["hashtags"] = df_csv["hashtags"].apply(
        lambda v: json.dumps(list(v) if v is not None else [])
    )
    df_csv.to_csv(csv_path, index=False)

    return csv_path, parquet_path


def _section(title: str) -> None:
    print()
    print(title)
    print("-" * len(title))


def print_clean_stats(
    df_before: pd.DataFrame,
    df_after: pd.DataFrame,
    log: dict,
    csv_path: Optional[Path] = None,
    parquet_path: Optional[Path] = None,
) -> None:
    print("=" * 72)
    print("MASTER CORPUS - CLEANED - STATS SUMMARY")
    print("=" * 72)

    _section("Row counts")
    print(f"  rows before dedup:   {log['rows_before']:,}")
    print(f"  rows after dedup:    {log['rows_after']:,}")
    print(f"  duplicates dropped:  {log['duplicates_dropped']}")

    n = len(df_after)

    _section("Caption presence (raw)")
    has_cap = int(df_after["has_caption"].sum())
    no_cap  = n - has_cap
    print(f"  has_caption=True:    {has_cap:>5,} ({has_cap / n * 100:5.1f}%)")
    print(f"  has_caption=False:   {no_cap:>5,} ({no_cap / n * 100:5.1f}%)   <- empty captions handled")

    _section("Boolean breakdown")
    for col in ["has_caption", "has_location", "has_views"]:
        t = int(df_after[col].sum())
        f = n - t
        print(f"  {col:<14} True={t:>5,} ({t / n * 100:5.1f}%)  False={f:>5,} ({f / n * 100:5.1f}%)")

    _section("Caption length")
    raw_lens   = df_before["caption"].fillna("").str.len()
    clean_lens = df_after["caption_clean"].str.len()
    print(f"  avg length BEFORE cleaning: {raw_lens.mean():7.1f} chars")
    print(f"  avg length AFTER  cleaning: {clean_lens.mean():7.1f} chars")
    print(f"  delta:                      {clean_lens.mean() - raw_lens.mean():+7.1f} chars")

    _section("Language distribution (caption_lang)")
    lang_counts = df_after["caption_lang"].value_counts(dropna=False)
    for lang, cnt in lang_counts.items():
        print(f"  {str(lang):<8} {cnt:>5,}  ({cnt / n * 100:5.1f}%)")

    _section("Sample before/after pairs (5)")
    changed = df_after[
        df_after["has_caption"]
        & (df_after["caption"].fillna("") != df_after["caption_clean"])
    ]
    if len(changed) == 0:
        print("  (no captions changed)")
    else:
        sample = changed.sample(n=min(5, len(changed)), random_state=42)
        for i, (_, row) in enumerate(sample.iterrows(), 1):
            before = (row["caption"] or "").replace("\n", " \\n ").replace("\t", " \\t ")
            after  = row["caption_clean"]
            print(f"  [{i}] lang={row['caption_lang']}  username={row['username']}")
            print(f"      BEFORE: {before[:140]}")
            print(f"      AFTER : {after[:140]}")

    if csv_path or parquet_path:
        _section("Output files")
        if parquet_path and parquet_path.exists():
            size_kb = parquet_path.stat().st_size / 1024
            print(f"  {parquet_path.name:<26} {size_kb:>8.1f} KB")
        if csv_path and csv_path.exists():
            size_kb = csv_path.stat().st_size / 1024
            print(f"  {csv_path.name:<26} {size_kb:>8.1f} KB")

    print("=" * 72)
