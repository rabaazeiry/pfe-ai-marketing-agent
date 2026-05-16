"""STEP G — verify facts_<industry>.json is grounded in the parquet.

For each industry, take 5 numbers from the facts.json and recompute each
ONE independently (naive pandas, NOT reusing compute_facts helpers). Assert
they match. This proves facts.json is not approximating — every number is
recomputable from the raw data.

The 5 numbers chosen are deliberately spread across modules and types:
  1. n_kept                                — filter accounting
  2. optimal_timing.best_days[0].median_er — temporal aggregate, _er
  3. visual_strategy.reel_vs_photo_ratio   — derived ratio
  4. hashtag_strategy.top_10_hashtags[0].n — categorical count
  5. content_themes.top_5_by_share[0].n    — topic-grouped count
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List, Tuple

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
MASTER  = ROOT / "data" / "df_master_masked_with_topics.parquet"
FACTS_D = ROOT / "data" / "step4f_v6" / "facts"

INDUSTRIES = ["beauty", "fashion", "hotels", "patisserie", "restaurants"]
GIVEAWAY_RE = re.compile(r"giveaway|jeuconcours|concours|giveaways|tirage", re.IGNORECASE)


def _has_giveaway(tags) -> bool:
    if tags is None:
        return False
    try:
        return any(isinstance(t, str) and GIVEAWAY_RE.search(t) for t in tags)
    except TypeError:
        return False


def _filtered(df_ind: pd.DataFrame) -> pd.DataFrame:
    """Same filter compute_facts applies — but written from scratch here
    so the test really is independent."""
    p95 = df_ind["engagement_rate"].quantile(0.95)
    kept = df_ind[
        (df_ind["engagement_rate"] <= p95) &
        (~df_ind["hashtags"].apply(_has_giveaway))
    ]
    return kept


@pytest.fixture(scope="module")
def master_df() -> pd.DataFrame:
    if not MASTER.exists():
        pytest.skip(f"master parquet not present at {MASTER}")
    return pd.read_parquet(MASTER)


@pytest.mark.parametrize("industry", INDUSTRIES)
def test_facts_match_independent_recompute(industry: str, master_df: pd.DataFrame):
    facts_path = FACTS_D / f"facts_{industry}.json"
    if not facts_path.exists():
        pytest.skip(f"{facts_path.name} missing — run compute_facts.py first")
    facts = json.loads(facts_path.read_text(encoding="utf-8"))

    df_ind = master_df[master_df["industry_simple"] == industry].copy()
    g = _filtered(df_ind)

    failures: List[Tuple[str, float, float]] = []

    # ── (1) n_kept ──────────────────────────────────────────────────────
    expected_n_kept = int(len(g))
    got_n_kept = int(facts["n_posts_kept"])
    if expected_n_kept != got_n_kept:
        failures.append(("n_posts_kept", got_n_kept, expected_n_kept))

    # ── (2) optimal_timing.best_days[0].median_er ───────────────────────
    ts_tunis = pd.to_datetime(g["published_at"], errors="coerce", utc=True).dt.tz_convert("Africa/Tunis")
    dow_med = g.assign(_dow=ts_tunis.dt.dayofweek).groupby("_dow")["engagement_rate"].median()
    expected_best_med = round(float(dow_med.sort_values(ascending=False).iloc[0]), 2)
    got_best_med = float(facts["modules"]["optimal_timing"]["best_days"][0]["median_er"])
    if abs(expected_best_med - got_best_med) > 0.005:
        failures.append(("optimal_timing.best_days[0].median_er", got_best_med, expected_best_med))

    # ── (3) visual_strategy.reel_vs_photo_ratio ─────────────────────────
    ct_med = g.groupby("content_type")["engagement_rate"].median()
    got_ratio = facts["modules"]["visual_strategy"]["reel_vs_photo_ratio"]
    if "reel" in ct_med.index and "photo" in ct_med.index and ct_med.loc["photo"] > 0:
        expected_ratio = round(float(ct_med.loc["reel"] / ct_med.loc["photo"]), 2)
        if got_ratio is None or abs(expected_ratio - float(got_ratio)) > 0.05:
            failures.append(("visual_strategy.reel_vs_photo_ratio", got_ratio, expected_ratio))
    else:
        # If reel or photo missing entirely, facts.json should report None
        if got_ratio is not None:
            failures.append(("visual_strategy.reel_vs_photo_ratio (expected None)", got_ratio, None))

    # ── (4) hashtag_strategy.top_10_hashtags[0].n ───────────────────────
    top_hashtags = facts["modules"]["hashtag_strategy"].get("top_10_hashtags") or []
    if top_hashtags:
        tag = top_hashtags[0]["tag"].lstrip("#").lower()
        got_n = int(top_hashtags[0]["n"])
        # Independent count: number of posts in filtered set that contain this tag
        def _has_tag(tags) -> bool:
            if tags is None:
                return False
            try:
                return any(isinstance(t, str) and t.lower() == tag for t in tags)
            except TypeError:
                return False
        expected_n = int(g["hashtags"].apply(_has_tag).sum())
        if expected_n != got_n:
            failures.append((f"hashtag_strategy.top_10_hashtags[0].n (#{tag})", got_n, expected_n))

    # ── (5) content_themes.top_5_by_share[0].n ──────────────────────────
    top_themes = facts["modules"]["content_themes"].get("top_5_by_share") or []
    if top_themes:
        tid = int(top_themes[0]["topic_id"])
        got_n = int(top_themes[0]["n"])
        expected_n = int((g["topic_id"] == tid).sum())
        if expected_n != got_n:
            failures.append((f"content_themes.top_5_by_share[0].n (topic={tid})", got_n, expected_n))

    assert not failures, (
        f"{industry}: {len(failures)} facts.json value(s) do not match an "
        f"independent recompute from the parquet:\n  " +
        "\n  ".join(f"{p}: facts={g!r} but parquet={e!r}" for p, g, e in failures)
    )
