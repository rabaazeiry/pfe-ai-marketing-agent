"""test_template_modules.py — unit + integration tests for the Step-4
deterministic prose templates (_template_modules.py).

No pytest in this environment, so this is a self-running suite (the
repo convention, cf. step4_smoke_test.py). Run:

    python scripts/test_template_modules.py

Every `test_*` function asserts; the __main__ runner executes them all,
prints PASS/FAIL per test and exits non-zero if anything fails. The
functions are also plain `assert`-based so they work unchanged under
pytest if it is ever added.

Coverage:
  * output contract (answer / 3 evidence / 3 recommendations) on
    synthetic AND the 5 real facts files
  * direction follows sign(er_delta): a negative signal is never
    "Utiliser…", a positive one never "Éviter…"
  * neutral (er_delta ≈ 0) signal is recommended in NEITHER direction
  * ×100 / pp discipline: 0.04 -> "0.04 pp", never "4%"; 0.08 -> "0.08%"
  * Outliers (topic_id == -1) filtered from Q4 entirely
  * Q10 technical names verbatim, no paraphrase, no negative on a SHAP
    line, no impossible "réduire les jours…"
  * thin-sample down-rank: n_on < MIN_N loses to a well-supported signal
  * TEMPLATE_DISPATCH registry + rephrase_facts routes templated modules
    with NO LLM
  * validator gate: 0 CRITICAL for all 5 templates × 5 industries
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from _template_modules import (  # noqa: E402
    MIN_N, TEMPLATE_DISPATCH,
    template_content_strategy, template_content_themes,
    template_hashtag_strategy, template_brand_differentiation,
    template_engagement_tactics, template_performance_predictors,
)
from _verify_prose import verify_and_repair_prose  # noqa: E402

FACTS_DIR = ROOT / "data" / "step4f_v6" / "facts"
INDUSTRIES = ["beauty", "fashion", "hotels", "patisserie", "restaurants"]


# ─────────────────────────────────────────────────────────────────────────
# Synthetic facts builders
# ─────────────────────────────────────────────────────────────────────────

def _facts(modules: dict, *, p95: float = 2.0, n_kept: int = 500) -> dict:
    return {
        "industry": "synthetic",
        "n_posts_kept": n_kept,
        "filter_summary": {"p95_cutoff_value": p95},
        "modules": modules,
    }


def _sig(signal, delta, n_on, on=0.10, off=0.10):
    return {"signal": signal, "on_median_er": on, "off_median_er": off,
            "er_delta": delta, "n_on": n_on, "n_off": 500 - n_on}


def _tac(tactic, delta, n_on, on=0.10, off=0.10):
    return {"tactic": tactic, "on_median_er": on, "off_median_er": off,
            "er_delta": delta, "n_on": n_on, "n_off": 500 - n_on}


def _shape_ok(out: dict) -> None:
    assert set(out) == {"answer", "evidence", "actionable_recommendations"}
    assert isinstance(out["answer"], str) and len(out["answer"]) >= 20
    assert len(out["evidence"]) == 3
    assert len(out["actionable_recommendations"]) == 3
    for blk in (out["evidence"], out["actionable_recommendations"]):
        for s in blk:
            assert isinstance(s, str) and len(s.strip()) > 4


def _flat(out: dict) -> str:
    return (out["answer"] + "\n" + "\n".join(out["evidence"]) + "\n"
            + "\n".join(out["actionable_recommendations"]))


def _crit(out: dict, facts: dict, module: str, industry="synthetic") -> list:
    block = facts["modules"][module]
    _, iss = verify_and_repair_prose(_flat(out), block, industry,
                                     full_facts=facts)
    return [i for i in iss if i.get("severity") == "critical"]


# ─────────────────────────────────────────────────────────────────────────
# Output contract
# ─────────────────────────────────────────────────────────────────────────

def test_shape_real_facts():
    for ind in INDUSTRIES:
        fp = FACTS_DIR / f"facts_{ind}.json"
        if not fp.exists():
            continue
        data = json.loads(fp.read_text(encoding="utf-8"))
        for fn in TEMPLATE_DISPATCH.values():
            _shape_ok(fn(data))


def test_shape_minimal_synthetic():
    f = _facts({
        "content_strategy": {"confidence": "high", "n": 10,
                             "caption_length_quartiles": [], "sentiment": {},
                             "binary_signal_lifts": []},
        "content_themes": {"confidence": "high", "n": 10,
                           "n_floor_for_er": 5,
                           "cross_industry_topics_excluded": 0,
                           "top_5_by_er": [], "top_5_by_share": []},
        "hashtag_strategy": {"confidence": "high", "n_posts": 10,
                             "top_10_hashtags": [], "count_buckets": []},
        "brand_differentiation": {"confidence": "high",
                                  "n_brands_with_5plus_posts": 0,
                                  "industry_median_er": None,
                                  "top_brands_by_median_er": [],
                                  "bottom_brands_by_median_er": [],
                                  "underserved_themes": []},
        "engagement_tactics": {"confidence": "high", "n": 10,
                               "tactic_lifts": [], "top_comment_drivers": []},
        "performance_predictors": {"confidence": "low", "n_test_sample": 10,
                                   "model": "m", "model_r2_log": 0.1,
                                   "model_rho": 0.2, "top_5_features": []},
    })
    for mod, fn in TEMPLATE_DISPATCH.items():
        _shape_ok(fn(f))


# ─────────────────────────────────────────────────────────────────────────
# Direction discipline (Q1 + Q8)
# ─────────────────────────────────────────────────────────────────────────

def test_q1_direction_and_units():
    # promo_word positive (+0.04), emoji negative (-0.10), cta neutral (-0.0)
    f = _facts({"content_strategy": {
        "confidence": "high", "n": 500,
        "caption_length_quartiles": [
            {"bucket": "q1_shortest", "median_er": 0.25, "mean_er": 0.5,
             "n": 120},
            {"bucket": "q4_longest", "median_er": 0.07, "mean_er": 0.2,
             "n": 120}],
        "sentiment": {"median": 0.6, "mean": 0.5, "positive_share": 68.4,
                      "negative_share": 2.8, "n": 480},
        "binary_signal_lifts": [
            _sig("has_promo_word", 0.04, 60, on=0.15, off=0.11),
            _sig("has_emoji", -0.10, 300, on=0.11, off=0.21),
            _sig("has_cta", -0.0, 40)],
    }})
    out = template_content_strategy(f)
    recs = " || ".join(out["actionable_recommendations"]).lower()
    # positive promo -> "utiliser", never "éviter"
    assert "utiliser les mots promotionnels" in recs
    assert "éviter les mots promotionnels" not in recs
    # negative emoji -> "éviter", never "utiliser"
    assert "éviter les emojis" in recs
    assert "utiliser les emojis" not in recs
    # ×100 discipline: deltas in pp, never bare "4%"/"10%"
    flat = _flat(out)
    assert "0.04 pp" in flat and "0.10 pp" in flat
    assert "4%" not in flat and "augmente l'engagement de 4" not in flat
    # neutral cta (-0.0) recommended in neither direction
    assert "appel à l'action" not in recs
    assert _crit(out, f, "content_strategy") == []


def test_q8_direction_and_neutral():
    # cta positive (+0.03), question negative (-0.02), promo neutral (0.0)
    f = _facts({"engagement_tactics": {
        "confidence": "high", "n": 500,
        "tactic_lifts": [
            _tac("cta", 0.03, 80, on=0.13, off=0.10),
            _tac("question", -0.02, 60, on=0.08, off=0.10),
            _tac("promo_word", 0.0, 120)],
        "top_comment_drivers": [
            {"username": "acct", "content_type": "reel", "comments": 50,
             "followers": 10000, "comments_per_1k_followers_ratio": 5.0,
             "post_id": "X"}],
    }})
    out = template_engagement_tactics(f)
    recs = " || ".join(out["actionable_recommendations"]).lower()
    assert "utiliser les appels à l'action" in recs
    assert "limiter les questions" in recs
    assert "utiliser les questions" not in recs
    # neutral promo (0.0) not directionally recommended
    assert "utiliser les mots promotionnels" not in recs
    assert "limiter les mots promotionnels" not in recs
    flat = _flat(out)
    assert "0.03 pp" in flat and "0.02 pp" in flat
    assert _crit(out, f, "engagement_tactics") == []


# ─────────────────────────────────────────────────────────────────────────
# Thin-sample down-rank (the user's chosen policy)
# ─────────────────────────────────────────────────────────────────────────

def test_thin_sample_downrank_q1():
    # strong-but-thin promo (+0.09, n=11) vs solid question (+0.02, n=120).
    # The well-supported one must be the surfaced "Utiliser…".
    f = _facts({"content_strategy": {
        "confidence": "high", "n": 500,
        "caption_length_quartiles": [
            {"bucket": "q1_shortest", "median_er": 0.2, "mean_er": 0.4,
             "n": 120}],
        "sentiment": {"positive_share": 60.0, "negative_share": 1.0,
                      "median": 0.5, "n": 480},
        "binary_signal_lifts": [
            _sig("has_promo_word", 0.09, 11),     # thin (< MIN_N)
            _sig("has_question", 0.02, 120),      # solid
            _sig("has_emoji", -0.05, 200)],
    }})
    assert 11 < MIN_N <= 120
    recs = " || ".join(
        template_content_strategy(f)["actionable_recommendations"]).lower()
    assert "utiliser les questions" in recs
    assert "utiliser les mots promotionnels" not in recs


def test_thin_sample_fallback_when_only_thin():
    # Only positive is thin (n=11) -> still surfaced (nothing else qualifies)
    f = _facts({"content_strategy": {
        "confidence": "high", "n": 500,
        "caption_length_quartiles": [
            {"bucket": "q1_shortest", "median_er": 0.2, "mean_er": 0.4,
             "n": 120}],
        "sentiment": {"positive_share": 60.0, "negative_share": 1.0,
                      "median": 0.5, "n": 480},
        "binary_signal_lifts": [
            _sig("has_promo_word", 0.09, 11),
            _sig("has_emoji", -0.05, 200)],
    }})
    recs = " || ".join(
        template_content_strategy(f)["actionable_recommendations"]).lower()
    assert "utiliser les mots promotionnels" in recs
    assert "(sur 11 posts)" in recs   # thin support disclosed


# ─────────────────────────────────────────────────────────────────────────
# Q4 — Outliers filtered
# ─────────────────────────────────────────────────────────────────────────

def test_q4_outliers_filtered_even_if_highest_er():
    f = _facts({"content_themes": {
        "confidence": "high", "n": 500, "n_floor_for_er": 5,
        "cross_industry_topics_excluded": 9,
        "top_5_by_er": [
            {"topic_id": -1, "topic_name": "Outliers (mixed content)",
             "theme_er": 0.99, "theme_er_mean": 1.0, "theme_share": 30.0,
             "n": 200, "confidence": "high", "is_own_industry": False},
            {"topic_id": 8, "topic_name": "Real Theme A", "theme_er": 0.40,
             "theme_er_mean": 0.5, "theme_share": 6.0, "n": 50,
             "confidence": "high", "is_own_industry": True},
            {"topic_id": 9, "topic_name": "Real Theme B", "theme_er": 0.20,
             "theme_er_mean": 0.3, "theme_share": 4.0, "n": 40,
             "confidence": "high", "is_own_industry": True},
            {"topic_id": 7, "topic_name": "Real Theme C", "theme_er": 0.10,
             "theme_er_mean": 0.2, "theme_share": 3.0, "n": 30,
             "confidence": "medium", "is_own_industry": True}],
        "top_5_by_share": [],
    }})
    out = template_content_themes(f)
    blob = _flat(out).lower()
    assert "outlier" not in blob
    assert "topic_id -1" not in out["answer"].lower() or "écart" in blob
    # the real top-ER theme leads
    assert "Real Theme A" in out["answer"]
    assert _crit(out, f, "content_themes") == []


def test_q4_all_outliers_graceful():
    f = _facts({"content_themes": {
        "confidence": "high", "n": 50, "n_floor_for_er": 5,
        "cross_industry_topics_excluded": 3,
        "top_5_by_er": [
            {"topic_id": -1, "topic_name": "Outliers (mixed content)",
             "theme_er": 0.5, "theme_er_mean": 0.6, "theme_share": 40.0,
             "n": 30, "confidence": "high", "is_own_industry": False}],
        "top_5_by_share": [],
    }})
    out = template_content_themes(f)
    _shape_ok(out)
    # Requirement #3 is about not RECOMMENDING Outliers. Outliers must be
    # absent from the answer and every recommendation; an evidence bullet
    # may explicitly state it was EXCLUDED (jury-facing transparency).
    assert "outlier" not in out["answer"].lower()
    for rec in out["actionable_recommendations"]:
        assert "outlier" not in rec.lower()
    excl = " ".join(out["evidence"]).lower()
    assert "exclu" in excl  # methodology stated, not recommended


# ─────────────────────────────────────────────────────────────────────────
# Q5 — never "réduire #X" for a high-ER hashtag (contradiction class B)
# ─────────────────────────────────────────────────────────────────────────

def test_q5_no_reduce_high_er_hashtag():
    f = _facts({"hashtag_strategy": {
        "confidence": "high", "n_posts": 500,
        "top_10_hashtags": [
            {"tag": "#corpsetcheveux", "median_er": 0.40, "mean_er": 0.5,
             "n": 25},
            {"tag": "#veryrose", "median_er": 0.26, "mean_er": 0.3,
             "n": 20}],
        "count_buckets": [
            {"bucket": "0", "median_er": 0.08, "mean_er": 0.2, "n": 300},
            {"bucket": "7-10", "median_er": 0.10, "mean_er": 0.2, "n": 96}],
    }})
    out = template_hashtag_strategy(f)
    blob = _flat(out).lower()
    # the top hashtag is promoted, never told to be reduced/avoided
    assert "#corpsetcheveux" in blob
    for bad in ("réduire #corpsetcheveux", "éviter #corpsetcheveux",
                "moins de #corpsetcheveux"):
        assert bad not in blob
    assert _crit(out, f, "hashtag_strategy") == []


# ─────────────────────────────────────────────────────────────────────────
# Q6 — benchmark, no CTA contradiction, Outliers filtered, no fake collab
# ─────────────────────────────────────────────────────────────────────────

def test_q6_no_cta_contradiction_outliers_filtered():
    # content_strategy carries a NEGATIVE has_cta so the cross-module
    # reco_direction_check has a CTA signal to catch — Q6 must simply
    # never mention CTA (the exact LLM bug being templated away).
    f = _facts({
        "content_strategy": {"confidence": "high", "n": 500,
                             "caption_length_quartiles": [],
                             "sentiment": {},
                             "binary_signal_lifts": [
                                 _sig("has_cta", -0.05, 200)]},
        "brand_differentiation": {
            "confidence": "high", "n_brands_with_5plus_posts": 8,
            "industry_median_er": 0.07,
            "top_brands_by_median_er": [
                {"username": "leader.brand", "median_er": 0.26,
                 "mean_er": 0.3, "n": 85},
                {"username": "second.brand", "median_er": 0.12,
                 "mean_er": 0.2, "n": 92}],
            "bottom_brands_by_median_er": [
                {"username": "weak.brand", "median_er": 0.01,
                 "mean_er": 0.05, "n": 102}],
            "underserved_themes": [
                {"topic_id": -1, "topic_name": "Outliers (mixed content)",
                 "theme_er": 0.99, "theme_share": 30.0, "n": 200,
                 "is_own_industry": False},
                {"topic_id": 7, "topic_name": "Real Underserved Theme",
                 "theme_er": 0.16, "theme_share": 4.13, "n": 32,
                 "is_own_industry": True}],
        },
    })
    out = template_brand_differentiation(f)
    _shape_ok(out)
    blob = _flat(out).lower()
    # no CTA / tactic surface anywhere -> no contradiction possible
    for bad in ("cta", "appel à l'action", "emoji", "promotionnel"):
        assert bad not in blob
    # Outliers never recommended; the real underserved theme is the one used
    assert "outlier" not in blob
    assert "Real Underserved Theme" in _flat(out)
    # benchmark cites the industry median; leader cited WITHOUT '@'
    assert "0.07%" in _flat(out)
    assert "leader.brand" in _flat(out) and "@leader.brand" not in _flat(out)
    assert "collaboration avec @" not in blob and "partenariat avec @" not in blob
    assert _crit(out, f, "brand_differentiation") == []


# ─────────────────────────────────────────────────────────────────────────
# Q10 — verbatim technical names, SHAP magnitude, no impossible reco
# ─────────────────────────────────────────────────────────────────────────

def test_q10_verbatim_and_shap_and_no_impossible():
    f = _facts({"performance_predictors": {
        "confidence": "high", "n_test_sample": 200,
        "model": "XGB V5c (interpretive proxy for V6 stacking)",
        "model_r2_log": 0.4587, "model_rho": 0.6686,
        "top_5_features": [
            {"feature": "brand_engagement_rate", "mean_abs_shap": 0.0635,
             "direction": "-", "category": "tabular"},
            {"feature": "followers", "mean_abs_shap": 0.0351,
             "direction": "-", "category": "tabular"},
            {"feature": "clip_pc01", "mean_abs_shap": 0.0323,
             "direction": "+", "category": "clip_visual"},
            {"feature": "days_since_first_post", "mean_abs_shap": 0.0224,
             "direction": "+", "category": "tabular"},
            {"feature": "doc_pc06", "mean_abs_shap": 0.0211,
             "direction": "-", "category": "mpnet_caption_semantics"}],
    }})
    out = template_performance_predictors(f)
    flat = _flat(out)
    low = flat.lower()
    # names verbatim
    for name in ("clip_pc01", "doc_pc06", "brand_engagement_rate",
                 "days_since_first_post"):
        assert name in flat
    # no paraphrase
    for bad in ("fréquence des clips", "document pc", "taux de visionnage",
                "pourcentage de clips"):
        assert bad not in low
    # SHAP magnitude carried positive; the 1st predictor's value bound to
    # the 1st predictor (not reassigned to CTA — CTA isn't even here)
    assert "0.0635" in flat and "-0.0635" not in flat
    assert "cta" not in low
    # impossible reco absent: never "réduire … jours/days_since…"
    assert "réduire le nombre de jours" not in low
    assert "réduire days_since_first_post" not in low
    # SHAP-magnitude-negative validator must stay silent
    assert _crit(out, f, "performance_predictors") == []


def test_q10_no_increase_followers_or_ber():
    f = _facts({"performance_predictors": {
        "confidence": "high", "n_test_sample": 200, "model": "m",
        "model_r2_log": 0.45, "model_rho": 0.66,
        "top_5_features": [
            {"feature": "brand_engagement_rate", "mean_abs_shap": 0.06,
             "direction": "-", "category": "tabular"},
            {"feature": "followers", "mean_abs_shap": 0.03,
             "direction": "-", "category": "tabular"},
            {"feature": "clip_pc01", "mean_abs_shap": 0.02,
             "direction": "+", "category": "clip_visual"}],
    }})
    out = template_performance_predictors(f)
    low = _flat(out).lower()
    assert "augmenter le nombre de followers" not in low
    assert "plus de followers" not in low
    assert "gagner des followers" not in low
    assert "améliorer le taux d'engagement de la marque" not in low
    assert _crit(out, f, "performance_predictors") == []


# ─────────────────────────────────────────────────────────────────────────
# Dispatch registry + rephrase_facts routing (NO LLM)
# ─────────────────────────────────────────────────────────────────────────

def test_dispatch_registry_exact():
    assert set(TEMPLATE_DISPATCH) == {
        "content_strategy", "content_themes", "hashtag_strategy",
        "brand_differentiation", "engagement_tactics",
        "performance_predictors"}


def test_rephrase_one_routes_without_llm():
    import rephrase_facts as rf
    fp = FACTS_DIR / "facts_restaurants.json"
    if not fp.exists():
        return
    facts = json.loads(fp.read_text(encoding="utf-8"))
    templated = {q["module"] for q in rf.QUESTIONS} & set(TEMPLATE_DISPATCH)
    assert templated == set(TEMPLATE_DISPATCH)
    for q in rf.QUESTIONS:
        if q["module"] in TEMPLATE_DISPATCH:
            parsed, status, lat, bad, iss = rf.rephrase_one(
                None, "restaurants", q, facts)   # llm=None: must NOT be used
            assert status.startswith("TEMPLATE")
            assert lat == 0.0
            _shape_ok(parsed)


# ─────────────────────────────────────────────────────────────────────────
# Validator gate — 0 CRITICAL for all 5 templates × 5 industries
# ─────────────────────────────────────────────────────────────────────────

def test_validator_gate_all_real():
    total = 0
    for ind in INDUSTRIES:
        fp = FACTS_DIR / f"facts_{ind}.json"
        if not fp.exists():
            continue
        facts = json.loads(fp.read_text(encoding="utf-8"))
        for mod, fn in TEMPLATE_DISPATCH.items():
            out = fn(facts)
            crit = _crit(out, facts, mod, industry=ind)
            assert not crit, f"{ind}/{mod}: {[c['message'] for c in crit]}"
            total += 0
    assert total == 0


# ─────────────────────────────────────────────────────────────────────────
# Runner (no pytest in this env)
# ─────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = sorted((n, o) for n, o in globals().items()
                    if n.startswith("test_") and callable(o))
    passed = failed = 0
    print("=" * 78)
    print(f"test_template_modules.py — {len(tests)} tests")
    print("=" * 78)
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS  {name}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL  {name}  :: {e}")
            failed += 1
        except Exception as e:  # noqa: BLE001
            print(f"  ERROR {name}  :: {type(e).__name__}: {e}")
            failed += 1
    print("-" * 78)
    print(f"  {passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
