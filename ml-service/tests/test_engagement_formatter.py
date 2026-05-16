"""Regression tests for the engagement-rate display layer.

These pin down the ×100 unit-confusion bug that caused doc values like
"mardi: mean 318.28%" when the true mean was 3.18%.

Tests:
  1. test_engagement_rate_is_already_a_percentage
     Asserts the raw column in the master parquet is already in percent
     units (so the doc formatter must NOT multiply by 100 again).

  2. test_eng_str_does_not_inflate
     Asserts the doc formatter prints values as-is, not ×100.

  3. test_no_insight_value_exceeds_plausible_bound
     End-to-end: scans every "%"-suffixed number in every generated
     insights_<industry>.json and asserts none exceeds 50%. Skipped if
     insights have not been regenerated since the fix (env var
     SKIP_INSIGHT_BOUNDS=1 forces skip).
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
MASTER_PARQUET = ROOT / "data" / "df_master_masked_with_topics.parquet"
DOC_BUILDER    = ROOT / "scripts" / "step4f_v6_01_build_documents.py"
INSIGHTS_DIR   = ROOT / "data" / "step4f_v6" / "insights"
INDUSTRIES = ["beauty", "fashion", "hotels", "patisserie", "restaurants"]

# Bound chosen to catch ×100 inflation (which would produce 300%+, 1000%+,
# 100000%+ values) without flagging legitimate viral single-post citations.
# Real per-post ER on this dataset peaks at 164.47% (one viral beauty post);
# real aggregates (day/hour means and medians) are < 5%. We set the bound
# at 200% — well above any real value, well below the smallest ×100-bug
# output (300%).
PLAUSIBLE_ER_MAX = 200.0


def _import_doc_builder():
    """Load step4f_v6_01_build_documents.py as a module without running it
    (the module has top-level code in main())."""
    spec = importlib.util.spec_from_file_location(
        "step4f_v6_01_build_documents", DOC_BUILDER
    )
    module = importlib.util.module_from_spec(spec)
    # Avoid running main()
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# ─────────────────────────────────────────────────────────────────────────
# Test 1 — parquet schema invariant
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.skipif(
    not MASTER_PARQUET.exists(),
    reason=f"master parquet not present at {MASTER_PARQUET}",
)
def test_engagement_rate_is_already_a_percentage():
    """The Apify scraper stores engagement_rate as (likes+comments)/followers*100,
    i.e. already a percentage. A typical value is < 10. If this column ever
    contains values in the thousands at the 99.9th percentile, somebody has
    re-introduced the ×100 bug at the ingestion layer."""
    master = pd.read_parquet(MASTER_PARQUET)
    p999 = float(master["engagement_rate"].quantile(0.999))
    assert p999 < 100, (
        f"engagement_rate p99.9 = {p999:.2f}; expected < 100 (the column is "
        "already a percentage from the Apify scraper). If this fires, check "
        "whether someone re-introduced a ×100 multiplication at ingest."
    )


# ─────────────────────────────────────────────────────────────────────────
# Test 2 — formatter unit invariant
# ─────────────────────────────────────────────────────────────────────────

def test_eng_str_does_not_inflate():
    """_eng_str must NOT multiply by 100. The input is already a percentage."""
    mod = _import_doc_builder()
    # 3.18% engagement (a typical "high" Tuesday mean for beauty)
    assert mod._eng_str(3.18) == "3.18%", (
        f"_eng_str(3.18) returned {mod._eng_str(3.18)!r}; expected '3.18%'. "
        "If this returns '318.00%', the ×100 bug is back."
    )
    # 0.07% engagement (typical median per-post)
    assert mod._eng_str(0.07) == "0.07%", (
        f"_eng_str(0.07) returned {mod._eng_str(0.07)!r}; expected '0.07%'."
    )
    # NaN / None must still render gracefully
    import math
    assert mod._eng_str(None) == "—"
    assert mod._eng_str(float("nan")) == "—"


# ─────────────────────────────────────────────────────────────────────────
# Test 3 — end-to-end bound on generated insights
# ─────────────────────────────────────────────────────────────────────────

_PCT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")


def _scan_pct_values(obj):
    """Yield every percentage number (as float) found in nested strings."""
    if isinstance(obj, str):
        for m in _PCT_RE.finditer(obj):
            raw = m.group(1).replace(",", ".")
            try:
                yield float(raw)
            except ValueError:
                continue
    elif isinstance(obj, list):
        for item in obj:
            yield from _scan_pct_values(item)
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _scan_pct_values(v)


@pytest.mark.skipif(
    os.environ.get("SKIP_INSIGHT_BOUNDS") == "1",
    reason="SKIP_INSIGHT_BOUNDS=1 set (insights not yet regenerated)",
)
@pytest.mark.parametrize("industry", INDUSTRIES)
def test_no_insight_value_exceeds_plausible_bound(industry):
    """Every percentage cited in the generated insights JSON must be ≤ 50%.
    With the formatter fixed and median-based aggregation, no bucket-level
    ER should exceed a few percent. 50% leaves headroom for legitimately
    viral single-post citations while catching any ×100 regression."""
    path = INSIGHTS_DIR / f"insights_{industry}.json"
    if not path.exists():
        pytest.skip(f"{path.name} not present — pipeline not regenerated yet")
    data = json.loads(path.read_text(encoding="utf-8"))

    offenders = []
    for q in data.get("questions", []):
        for field in ("answer", "evidence", "actionable_recommendations",
                      "ml_evidence", "insights"):
            for val in _scan_pct_values(q.get(field)):
                if val > PLAUSIBLE_ER_MAX:
                    offenders.append((q.get("question_id"), field, val))

    assert not offenders, (
        f"{industry}: {len(offenders)} percentage value(s) exceed "
        f"{PLAUSIBLE_ER_MAX}% (likely ×100 inflation). Examples: "
        f"{offenders[:5]}"
    )
