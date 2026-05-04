"""Phase 3.8 — apply brand masking to df_master_clean and save the result.

Reads ``data/df_master_clean.parquet`` (4222 × 26), applies ``mask_brands``
from ``src/corpus/cleaner.py`` to ``caption_clean`` using a curated token
list, and writes ``data/df_master_masked.parquet`` with a new
``caption_masked`` column (4222 × 27).

The token list is intentionally defined HERE (not in cleaner.py) so the
cleaner stays pure / generic and the project-specific brand list lives
next to its consumers.
"""
from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from corpus.cleaner import mask_brands  # noqa: E402

IN_PATH = ROOT / "data" / "df_master_clean.parquet"
OUT_PATH = ROOT / "data" / "df_master_masked.parquet"

# --- Brand token catalogue --------------------------------------------------
# Tier A: exact Instagram handles from df.username.unique() (41).
# Tier B: hashtag / social variants observed in caption_clean (>=5 occurrences).
# Tier C: unambiguous brand stems (>=5 chars, no overlap with FR/EN content).
# Multi-word brand phrases are mixed in alongside (regex handles the spaces).

TIER_A_HANDLES = {
    "baguettebaguette", "bershka", "biodermatunisie", "chedly_sisters",
    "elfirma.tunis", "el_mouradi_hotels", "floraison.official", "freya.tn",
    "ha.hamadiabid", "hiltonskanesmonastir", "kastelo.com.tn", "kfctunisie",
    "la_badira", "la_salle_a_manger", "labeylicale", "lamaisongourmandise",
    "legolfe.restaurant", "lellacosmetics", "maisonturki", "mamie.karima",
    "mango", "movenpick_hotel_gammarth", "movenpicklactunis",
    "my_story_cosmetics", "nuxetunisie", "papajohnstn", "patisserie.sakka",
    "patisserie_h_by_omar", "patisseriemasmoudi", "patisserierekik",
    "pullandbear", "radissonblutunis", "soussepearlmarriott", "the716lac2",
    "therapybylk", "theresidencetunis", "tunismarriott", "vie.tunis",
    "yvesrocher_tunisie", "zara", "zen.tunisie",
}

TIER_B_VARIANTS = {
    "bershkastyle", "bershkamusic",
    "bioderma", "biodermatn",
    "mangowoman", "mangoman", "mangokids", "mangogirl",
    "mango.com", "mango.com.tn",
    "zarawoman", "zaranewin", "zarastudio", "zarasrpls",
    "kastelo",
    "floraison",
    "freya", "freyatunisie",
    "legolfe", "legolferestaurant",
    "movenpick", "movenpickgammarth", "movenpickhoteldulac",
    "movenpickhoteldulactunis",
    "nuxe",
    "papajohns",
    "radissonblu", "radissonhotels",
    "yvesrocher",
    "kfc", "kfctunisia",
}

TIER_C_STEMS = {
    "mouradi", "marriott", "radisson", "hilton", "elmouradi",
}

MULTI_WORD_PHRASES = {
    "el mouradi", "papa johns", "radisson blu",
}

BRAND_TOKENS = frozenset(
    TIER_A_HANDLES | TIER_B_VARIANTS | TIER_C_STEMS | MULTI_WORD_PHRASES
)


def _count_masks(before: str, after: str, tokens) -> int:
    """How many brand-token occurrences disappeared between before and after."""
    if not before:
        return 0
    pat = r"\b(?:" + "|".join(re.escape(t) for t in tokens) + r")\b"
    return len(re.findall(pat, before, flags=re.IGNORECASE))


def main() -> None:
    print(f"Loading {IN_PATH} ...")
    df = pd.read_parquet(IN_PATH)
    print(f"  rows: {len(df):,}   cols: {len(df.columns)}")
    print(f"  BRAND_TOKENS: {len(BRAND_TOKENS)} unique tokens")

    captions = df["caption_clean"].fillna("").tolist()

    masked_captions = []
    masks_per_post = []
    masked_token_freq: Counter = Counter()
    pat = re.compile(
        r"\b(?:" + "|".join(re.escape(t) for t in BRAND_TOKENS) + r")\b",
        flags=re.IGNORECASE,
    )

    for cap in captions:
        # Count what's about to be masked (so we can report top-masked tokens).
        for m in pat.findall(cap):
            masked_token_freq[m.lower()] += 1
        masked = mask_brands(cap, BRAND_TOKENS, replacement="")
        masked_captions.append(masked)
        masks_per_post.append(
            _count_masks(cap, masked, BRAND_TOKENS)
        )

    df_out = df.copy()
    df_out["caption_masked"] = masked_captions
    df_out.to_parquet(OUT_PATH, index=False)

    masks_arr = pd.Series(masks_per_post)
    rows_touched = int((masks_arr > 0).sum())
    rows_total = len(masks_arr)

    # Char-length comparison.
    raw_lens = pd.Series([len(c) for c in captions])
    msk_lens = pd.Series([len(c) for c in masked_captions])

    print()
    print("=" * 72)
    print("Brand-masking stats")
    print("=" * 72)
    print(f"  output:                  {OUT_PATH}")
    print(f"  rows × cols:             {df_out.shape[0]:,} × {df_out.shape[1]}")
    print(f"  rows with >=1 mask:      {rows_touched:,} / {rows_total:,} "
          f"({rows_touched / rows_total * 100:.1f}%)")
    print(f"  total masks applied:     {int(masks_arr.sum()):,}")
    print(f"  masks per post (mean):   {masks_arr.mean():.2f}")
    print(f"  masks per post (median): {int(masks_arr.median())}")
    print(f"  masks per post (max):    {int(masks_arr.max())}")
    print(f"  caption length avg:      {raw_lens.mean():.1f} → {msk_lens.mean():.1f} chars "
          f"(Δ {msk_lens.mean() - raw_lens.mean():+.1f})")

    print()
    print("Top 20 most-masked tokens (across the whole corpus):")
    print(f"  {'token':<30}  count")
    print("  " + "-" * 38)
    for token, n in masked_token_freq.most_common(20):
        print(f"  {token:<30}  {n:>5,}")
    print("=" * 72)


if __name__ == "__main__":
    main()
