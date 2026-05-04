"""Phase 4 - Feature engineering V2.

Enriches data/df_ml_dataset.parquet with 4 new pre-publication features
plus a more accurate emoji_count (Unicode-correct via the `emoji` lib,
overwriting the partial-Unicode regex from phase3_features.py).

Final spec applied (Option 1, decided 2026-05-03):
  - is_ramadan         (NEW)  - binary, MENA Marketing 2024 (+31% engagement)
  - caption_sentiment  (NEW)  - float in [-1, +1], zero-shot via
                                cardiffnlp/twitter-xlm-roberta-base-sentiment;
                                Kim & Hwang (Stanford 2025) ArXiv 2508.21650 +
                                Barbieri et al. (2022) XLM-T LREC.
  - has_emoji          (NEW)  - binary, derived from new emoji_count
  - has_cta            (NEW)  - binary, FR/EN/AR call-to-action lexicon
                                (Cloudinary, Brand24 industry guides 2024)
  - emoji_count        (OVERWRITE) - emoji.EMOJI_DATA membership; catches
                                ZWJ sequences, regional-indicator flags, and
                                skin-tone modifiers that the phase3 regex
                                missed. Multimodal Emotion (2019).

SKIPPED (already present in df_ml_dataset.parquet with equivalent
definition - verified by row-by-row inspection on 2026-05-03):
  - is_weekend            (identical: day_of_week >= 5)
  - has_question          (identical: '?' in caption_clean)
  - caption_word_count    (existing word_count is len(caption_clean.split())
                           which strips mentions but keeps emojis - a more
                           informative notion than raw caption.split())

Output: 4127 rows × 32 columns (was 28; +4 new, emoji_count overwritten).
"""
from __future__ import annotations

# IMPORTANT - Windows DLL load-order workaround:
# `import torch` MUST come before transformers / sentence-transformers /
# bertopic, otherwise torch/lib/c10.dll fails to load with WinError 1114.
# See project memory: project_torch_import_order.md.
import torch  # noqa: F401  (side-effect import, do not remove)

import hashlib
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import emoji
import numpy as np
import pandas as pd
from tqdm import tqdm

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
SOURCE_PARQUET = ROOT / "data" / "df_master_masked_with_topics.parquet"
ML_PARQUET     = ROOT / "data" / "df_ml_dataset.parquet"
BACKUP_PATH    = ROOT / "data" / "df_ml_dataset.parquet.bak_v1"
SENTIMENT_CACHE = ROOT / "data" / "_sentiment_cache_v2.parquet"

SENT_MODEL_NAME = "cardiffnlp/twitter-xlm-roberta-base-sentiment"
SENT_BATCH_SIZE = 16
SENT_MAX_LENGTH = 512


# --- Static lookups -------------------------------------------------------- #

# Tunisia Ramadan periods - inclusive ranges.
# Source: official MENA observances; matches the user's spec.
RAMADAN_RANGES_TUNISIA: List[Tuple[pd.Timestamp, pd.Timestamp]] = [
    (pd.Timestamp("2023-03-23", tz="UTC"), pd.Timestamp("2023-04-21", tz="UTC")),
    (pd.Timestamp("2024-03-11", tz="UTC"), pd.Timestamp("2024-04-09", tz="UTC")),
    (pd.Timestamp("2025-03-01", tz="UTC"), pd.Timestamp("2025-03-30", tz="UTC")),
    (pd.Timestamp("2026-02-17", tz="UTC"), pd.Timestamp("2026-03-18", tz="UTC")),
]

# CTA lexicons - FR / EN / AR. Word-boundary regex to avoid false positives
# (e.g. "essayez" must not match "essayeur"; "book" must not match "booker").
# Note: Arabic does not use \b in the Latin sense; using lookbehind/lookahead
# for non-letter chars is more robust there.
_CTA_FR_EN_PATTERNS = [
    r"\b(découvrez|decouvrez|découvre|decouvre)\b",
    r"\b(venez|viens)\b",
    r"\b(réservez|reservez|réserve|reserve)\b",
    r"\b(visitez|visite)\b",
    r"\b(essayez|essaye)\b",
    r"\b(suivez|suis-nous|suivez-nous)\b",
    r"\b(profitez|profite)\b",
    r"\b(discover)\b",
    r"\b(book)\b",
    r"\b(visit)\b",
    r"\b(try)\b",
    r"\b(explore)\b",
    r"\b(follow)\b",
    r"\b(enjoy)\b",
]
# Arabic CTAs - simple substring match (Arabic word boundaries via [^\w]).
_CTA_AR_PATTERNS = [
    r"احجز",       # book
    r"زوروا",      # visit (plural)
    r"اكتشفوا",    # discover (plural)
    r"جربوا",      # try (plural)
    r"تابعونا",    # follow us
]
_CTA_RE_LATIN = re.compile("|".join(_CTA_FR_EN_PATTERNS), re.IGNORECASE)
_CTA_RE_AR    = re.compile("|".join(_CTA_AR_PATTERNS))


# --- Pure helpers ---------------------------------------------------------- #

def _is_ramadan(ts: Optional[pd.Timestamp]) -> bool:
    if ts is None or pd.isna(ts):
        return False
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return any(start <= ts <= end for start, end in RAMADAN_RANGES_TUNISIA)


def _count_emoji_lib(text: Optional[str]) -> int:
    """Unicode-correct emoji count via emoji.EMOJI_DATA membership.
    Counts ZWJ-joined components separately (e.g., 🙂‍↕️ contributes 2)."""
    if text is None or (isinstance(text, float) and np.isnan(text)):
        return 0
    return sum(1 for c in text if c in emoji.EMOJI_DATA)


# Phase3's original EMOJI_RE - kept here ONLY for the comparison stats.
_PHASE3_EMOJI_RE = re.compile(
    "["
    + chr(0x1F300) + "-" + chr(0x1F9FF)
    + chr(0x2600) + "-" + chr(0x27BF)
    + chr(0x1F000) + "-" + chr(0x1F2FF)
    + "]"
)

def _count_emoji_regex(text: Optional[str]) -> int:
    if text is None or (isinstance(text, float) and np.isnan(text)):
        return 0
    return len(_PHASE3_EMOJI_RE.findall(text))


def _has_cta(text: Optional[str]) -> bool:
    if text is None or (isinstance(text, float) and np.isnan(text)):
        return False
    s = text.lower()
    return bool(_CTA_RE_LATIN.search(s) or _CTA_RE_AR.search(text))


# --- Sentiment subsystem --------------------------------------------------- #

def _hash_caption(text: str) -> str:
    """Stable cache key. Strips outer whitespace; preserves casing and
    inner whitespace so visually-identical captions hit cache."""
    return hashlib.sha1(text.strip().encode("utf-8")).hexdigest()


def _load_cache() -> Dict[str, Dict]:
    """Return {cap_hash: {label, score, signed}} from disk if present."""
    if not SENTIMENT_CACHE.exists():
        return {}
    df = pd.read_parquet(SENTIMENT_CACHE)
    return {
        row["cap_hash"]: {
            "label": row["label"],
            "score": float(row["score"]),
            "signed": float(row["signed"]),
        }
        for _, row in df.iterrows()
    }


def _save_cache(cache: Dict[str, Dict]) -> None:
    if not cache:
        return
    df = pd.DataFrame([
        {"cap_hash": h, "label": v["label"], "score": v["score"], "signed": v["signed"]}
        for h, v in cache.items()
    ])
    SENTIMENT_CACHE.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(SENTIMENT_CACHE, index=False)


def _label_to_signed(label: str, score: float) -> float:
    label = label.lower()
    if label == "positive":
        return float(score)
    if label == "negative":
        return -float(score)
    return 0.0   # neutral / empty / unknown


def _enrich_sentiment(captions_per_row: List[str]) -> List[float]:
    """Run XLM-RoBERTa sentiment over unique captions, with on-disk cache.

    Returns one float per input row (in original order).
    Empty / null captions short-circuit to 0.0 with no model call.
    """
    cache = _load_cache()
    initial_cache_size = len(cache)
    print(f"  sentiment cache loaded: {initial_cache_size:,} entries on disk")

    # 1. Bucket per-row work into hash -> rows that need it.
    hash_per_row: List[Optional[str]] = []
    needed_texts: Dict[str, str] = {}   # hash -> raw text
    n_empty = 0
    for cap in captions_per_row:
        if not isinstance(cap, str) or not cap.strip():
            hash_per_row.append(None)
            n_empty += 1
            continue
        h = _hash_caption(cap)
        hash_per_row.append(h)
        if h not in cache and h not in needed_texts:
            needed_texts[h] = cap.strip()

    print(f"  rows total:       {len(captions_per_row):,}")
    print(f"  empty / null:     {n_empty:,}  (-> signed=0.0, no model call)")
    print(f"  unique non-empty: "
          f"{len(set(h for h in hash_per_row if h is not None)):,}")
    print(f"  cache hits:       "
          f"{sum(1 for h in hash_per_row if h is not None and h in cache):,}")
    print(f"  cache misses:     {len(needed_texts):,}  (will run model)")

    # 2. Lazy-load pipeline only if there are misses.
    if needed_texts:
        print(f"  loading transformers pipeline ({SENT_MODEL_NAME}) "
              f"on CPU ...")
        t0 = time.perf_counter()
        from transformers import pipeline   # heavy import; defer to here
        clf = pipeline(
            task="text-classification",
            model=SENT_MODEL_NAME,
            tokenizer=SENT_MODEL_NAME,
            device=-1,
            truncation=True,
            max_length=SENT_MAX_LENGTH,
        )
        print(f"  pipeline ready in {time.perf_counter()-t0:.1f} s")

        miss_hashes = list(needed_texts.keys())
        miss_texts  = [needed_texts[h] for h in miss_hashes]
        print(f"  running inference on {len(miss_texts):,} unique captions "
              f"(batch_size={SENT_BATCH_SIZE}) ...")
        t0 = time.perf_counter()
        # pipeline returns one dict per text when batch_size is set.
        results = []
        for out in tqdm(
            clf(miss_texts, batch_size=SENT_BATCH_SIZE),
            total=len(miss_texts),
            desc="sentiment",
        ):
            results.append(out)
        elapsed = time.perf_counter() - t0
        per_text = elapsed / max(1, len(miss_texts))
        print(f"  inference elapsed: {elapsed:.1f} s "
              f"({per_text*1000:.1f} ms/text)")

        for h, r in zip(miss_hashes, results):
            label = r["label"]
            score = float(r["score"])
            cache[h] = {
                "label": label, "score": score,
                "signed": _label_to_signed(label, score),
            }

        _save_cache(cache)
        print(f"  cache grew {initial_cache_size:,} -> {len(cache):,}  "
              f"(saved to {SENTIMENT_CACHE.name})")
    else:
        print(f"  no model call needed - all captions already cached.")

    # 3. Map back to per-row signed scores.
    signed_per_row: List[float] = []
    for h in hash_per_row:
        if h is None:
            signed_per_row.append(0.0)
        else:
            signed_per_row.append(cache[h]["signed"])
    return signed_per_row


# --- Reporting ------------------------------------------------------------- #

def _print_emoji_comparison(
    ml: pd.DataFrame, caption_clean: pd.Series, post_id: pd.Series,
    raw_caption: pd.Series,
) -> None:
    """Citable thesis stat: regex (phase3) vs emoji-lib counts on caption_clean.

    Computes BOTH counts fresh from caption_clean each run (does NOT trust
    ml['emoji_count'], which on a re-run already holds the V2 emoji-lib
    value and would yield delta=0).
    """
    old = caption_clean.map(_count_emoji_regex).astype(int)
    new = caption_clean.map(_count_emoji_lib).astype(int)
    diff = new - old
    n_diff = int((diff != 0).sum())
    n_total = int(len(diff))

    print()
    print("=" * 88)
    print("EMOJI COUNT - regex (phase3) vs emoji-library (V2)  [thesis stat]")
    print("=" * 88)
    print(f"  rows total:                  {n_total:,}")
    print(f"  mean(old, regex):            {old.mean():.4f}")
    print(f"  mean(new, emoji-lib):        {new.mean():.4f}")
    print(f"  delta in means:              {(new.mean() - old.mean()):+.4f}  "
          f"(emoji-lib catches "
          f"{((new.mean()/max(old.mean(), 1e-9))-1)*100:+.1f}% more)")
    print(f"  rows where they differ:      {n_diff:,}  "
          f"({n_diff/n_total*100:.1f}% of total)")
    if n_diff > 0:
        print(f"  max positive delta:          {int(diff.max())}  "
              f"(emoji-lib > regex)")
        print(f"  max negative delta:          {int(diff.min())}  "
              f"(should never be < 0 in theory)")
        print()
        print("  Top-5 rows by |delta|:")
        top_idx = diff.abs().sort_values(ascending=False).head(5).index
        for i in top_idx:
            cap = (raw_caption.iloc[i] or "")
            cap_short = cap[:90] + ("..." if len(cap) > 90 else "")
            print(f"    post_id={post_id.iloc[i]}  old={old.iloc[i]:>2}  "
                  f"new={new.iloc[i]:>2}  delta={int(diff.iloc[i]):+d}")
            print(f"        caption: {cap_short!r}")
    print("=" * 88)


def _summary(ml: pd.DataFrame, target_col: str = "engagement_rate") -> str:
    L: List[str] = []
    L.append("=" * 88)
    L.append("Feature Engineering V2 - summary")
    L.append("=" * 88)
    L.append(f"  rows: {ml.shape[0]:,}   cols: {ml.shape[1]}  "
             f"(was 28 -> now {ml.shape[1]})")
    L.append("")

    new_features = ["is_ramadan", "caption_sentiment", "emoji_count",
                    "has_emoji", "has_cta"]
    L.append("Per-feature distributions")
    L.append("-" * 88)
    for f in new_features:
        s = ml[f]
        n = len(s)
        if pd.api.types.is_bool_dtype(s) or set(s.unique()).issubset({0, 1, True, False}):
            tot = int(s.astype(bool).sum())
            L.append(f"  {f:<22} bool/binary    True={tot:>4} ({tot/n*100:5.1f}%)")
        elif pd.api.types.is_integer_dtype(s):
            mx = int(s.max()); n_pos = int((s > 0).sum())
            L.append(f"  {f:<22} int    "
                     f"mean={s.mean():.3f}  std={s.std():.3f}  "
                     f"max={mx}  >0: {n_pos} ({n_pos/n*100:.1f}%)")
        else:
            qs = s.quantile([0.25, 0.5, 0.75])
            L.append(f"  {f:<22} float  "
                     f"mean={s.mean():+.4f}  std={s.std():.4f}  "
                     f"min={s.min():+.3f}  max={s.max():+.3f}  "
                     f"p25={qs[0.25]:+.3f}  p50={qs[0.5]:+.3f}  "
                     f"p75={qs[0.75]:+.3f}")

    L.append("")
    L.append(f"Pearson r vs {target_col} (sorted by |r|)")
    L.append("-" * 88)
    target = ml[target_col].astype(float).to_numpy()
    rows: List[Tuple[str, float]] = []
    for f in new_features:
        s = ml[f]
        if pd.api.types.is_bool_dtype(s):
            x = s.astype("int8").to_numpy()
        else:
            x = s.astype("float64").to_numpy()
        if np.std(x) == 0:
            r = float("nan")
        else:
            r = float(np.corrcoef(x, target)[0, 1])
        rows.append((f, r))
    rows.sort(key=lambda kv: -abs(kv[1]) if not np.isnan(kv[1]) else 0)
    for f, r in rows:
        L.append(f"  {f:<22} r = {r:+.4f}")

    L.append("")
    L.append("Sanity checks (expected ranges from spec)")
    L.append("-" * 88)
    rama = ml["is_ramadan"].astype(bool).mean() * 100
    sent = ml["caption_sentiment"]
    emoji_max = int(ml["emoji_count"].max())
    cta = ml["has_cta"].astype(bool).mean() * 100

    def _check(label: str, ok: bool, value: str) -> None:
        flag = "OK" if ok else "WARN"
        L.append(f"  [{flag}] {label:<35} {value}")

    _check("is_ramadan share is 5-25%",
           5 <= rama <= 25,
           f"{rama:.1f}% (expected 10-20% per spec)")
    _check("caption_sentiment ~ centred near 0",
           -0.4 <= sent.mean() <= 0.4,
           f"mean = {sent.mean():+.4f}")
    _check("emoji_count max < 100",
           emoji_max < 100,
           f"max = {emoji_max}")
    _check("has_cta share 5-30%",
           5 <= cta <= 30,
           f"{cta:.1f}%")
    L.append("=" * 88)
    return "\n".join(L) + "\n"


# --- Main ------------------------------------------------------------------ #

def main() -> None:
    t_total = time.perf_counter()

    # --- Step 1: backup (V1 snapshot — never overwrite) -------------------
    print(f"Step 1: backing up {ML_PARQUET.name} -> {BACKUP_PATH.name}")
    if not ML_PARQUET.exists():
        raise FileNotFoundError(ML_PARQUET)
    if not BACKUP_PATH.exists():
        BACKUP_PATH.write_bytes(ML_PARQUET.read_bytes())
        print(f"  backup created: {BACKUP_PATH.stat().st_size/1024:.1f} KB")
    else:
        print(f"  backup already exists - keeping pristine V1 snapshot "
              f"({BACKUP_PATH.stat().st_size/1024:.1f} KB)")

    # --- Step 2: load both parquets ---------------------------------------
    print()
    print(f"Step 2: loading parquets")
    src = pd.read_parquet(SOURCE_PARQUET)
    ml  = pd.read_parquet(ML_PARQUET)
    print(f"  source: {src.shape}  cols={list(src.columns)[:5]}...")
    print(f"  ml:     {ml.shape}")

    # --- Step 3: align rows via post_id -----------------------------------
    print()
    print(f"Step 3: aligning rows via post_id")
    src_indexed = src.set_index("post_id")
    aligned = src_indexed.loc[ml["post_id"].values]
    aligned = aligned.reset_index()
    assert (aligned["post_id"].values == ml["post_id"].values).all(), \
        "post_id alignment broke"
    raw_caption    = aligned["caption"].copy()           # for thesis emoji top-5 print
    caption_clean  = aligned["caption_clean"].copy()     # for emoji-lib (matches phase3 input)
    caption_masked = aligned["caption_masked"].copy()    # for sentiment (brand handles masked)
    published_at   = pd.to_datetime(aligned["published_at"], utc=True)
    print(f"  aligned: {len(aligned):,} rows  (matches ml)")

    # --- Step 4: pure / fast feature columns ------------------------------
    print()
    print("Step 4: computing pure/fast features (is_ramadan, has_cta, "
          "emoji_count_lib)")
    is_ramadan_col = published_at.map(_is_ramadan).astype(bool)
    has_cta_col    = aligned["caption"].map(_has_cta).astype(bool)
    new_emoji_col  = caption_clean.map(_count_emoji_lib).astype("int32")

    # --- Step 5: emoji-count comparison block (thesis stat) ---------------
    _print_emoji_comparison(ml, caption_clean, ml["post_id"], raw_caption)

    # --- Step 6: overwrite + add ------------------------------------------
    print()
    print("Step 6: writing new columns into ml frame")
    ml["emoji_count"]      = new_emoji_col                   # OVERWRITE
    ml["has_emoji"]        = (new_emoji_col > 0).astype(bool)  # NEW
    ml["is_ramadan"]       = is_ramadan_col                  # NEW
    ml["has_cta"]          = has_cta_col                     # NEW
    print(f"  emoji_count overwritten; has_emoji/is_ramadan/has_cta added")

    # --- Step 7: sentiment (slow, cached) ---------------------------------
    print()
    print("Step 7: computing caption_sentiment (zero-shot XLM-RoBERTa)")
    sentiment = _enrich_sentiment(caption_masked.tolist())
    ml["caption_sentiment"] = pd.Series(sentiment, index=ml.index, dtype="float32")

    # --- Step 8: persist --------------------------------------------------
    print()
    print(f"Step 8: writing {ML_PARQUET.name}")
    ml.to_parquet(ML_PARQUET, index=False)
    print(f"  wrote {ML_PARQUET.name}  ({ML_PARQUET.stat().st_size/1024:.1f} KB)")

    # --- Step 9: summary --------------------------------------------------
    text = _summary(ml)
    print()
    print(text, end="")

    print()
    print(f"Total elapsed: {time.perf_counter()-t_total:.1f} s "
          f"({(time.perf_counter()-t_total)/60:.1f} min)")


if __name__ == "__main__":
    main()
