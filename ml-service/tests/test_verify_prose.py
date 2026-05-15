"""Unit tests for scripts/_verify_prose.py — one test per validator.

Each test feeds synthetic *bad* prose plus a synthetic facts dict (passed
via full_facts so the tests are hermetic and do not depend on regenerated
facts_<industry>.json) and asserts the correct critical issue fires. A
clean-prose negative control is included so the validators are shown not
to be trigger-happy.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from _verify_prose import verify_and_repair_prose  # noqa: E402


def _validators(issues):
    return {i["validator"] for i in issues if i["severity"] == "critical"}


# ── B.1 ──────────────────────────────────────────────────────────────────
def test_er_bounds_check_flags_x100_decimal_loss():
    facts = {"filter_summary": {"p95_cutoff_value": 0.6}}
    bad = "RÉSUMÉ :\nLe taux d'engagement moyen atteint 8% sur la période."
    _, issues = verify_and_repair_prose(bad, {}, "patisserie", full_facts=facts)
    assert "er_bounds_check" in _validators(issues), issues

    good = "RÉSUMÉ :\nLe taux d'engagement médian est de 0.08% d'engagement."
    _, ok = verify_and_repair_prose(good, {}, "patisserie", full_facts=facts)
    assert "er_bounds_check" not in _validators(ok), ok


# ── B.2 ──────────────────────────────────────────────────────────────────
def test_shap_sign_check_flags_negative_magnitude():
    bad = ("PREUVES :\n- La valeur SHAP de brand_engagement_rate est -0.0635, "
           "la plus influente.")
    _, issues = verify_and_repair_prose(bad, {}, "beauty", full_facts={})
    assert "shap_sign_check" in _validators(issues), issues

    good = ("PREUVES :\n- La valeur SHAP (mean_abs_shap) de "
            "brand_engagement_rate vaut 0.0635 avec une direction négative.")
    _, ok = verify_and_repair_prose(good, {}, "beauty", full_facts={})
    assert "shap_sign_check" not in _validators(ok), ok


# ── B.3 ──────────────────────────────────────────────────────────────────
def test_technical_term_verbatim_check_flags_translation():
    facts_block = {"top_5_features": [{"feature": "clip_pc01",
                                       "mean_abs_shap": 0.0323}]}
    bad = ("RÉSUMÉ :\nLa fréquence des clips est le facteur le plus important "
           "pour l'engagement.")
    _, issues = verify_and_repair_prose(bad, facts_block, "fashion", full_facts={})
    assert "technical_term_verbatim_check" in _validators(issues), issues

    good = ("RÉSUMÉ :\nLe facteur clip_pc01 est le plus important "
            "pour l'engagement.")
    _, ok = verify_and_repair_prose(good, facts_block, "fashion", full_facts={})
    assert "technical_term_verbatim_check" not in _validators(ok), ok


# ── B.4 ──────────────────────────────────────────────────────────────────
def test_reco_direction_check_flags_contradiction():
    facts = {
        "modules": {
            "content_strategy": {
                "binary_signal_lifts": [
                    {"signal": "has_emoji", "er_delta": -0.02},
                ]
            },
            "engagement_tactics": {"tactic_lifts": []},
            "performance_predictors": {
                "top_5_features": [{"feature": "followers", "direction": "-"}]
            },
        }
    }
    bad = ("RECOMMANDATIONS :\n1. Il faut utiliser davantage d'emojis pour "
           "booster l'engagement.\n2. Augmenter le nombre de followers.")
    _, issues = verify_and_repair_prose(bad, {}, "patisserie", full_facts=facts)
    crit = _validators(issues)
    assert "reco_direction_check" in crit, issues
    # Both the emoji-lift contradiction and the followers contradiction fire.
    msgs = " ".join(i["message"] for i in issues)
    assert "has_emoji" in msgs and "followers" in msgs, issues

    good = ("RECOMMANDATIONS :\n1. Réduire l'usage des emojis (impact négatif "
            "mesuré).\n2. Se concentrer sur la qualité du contenu.")
    _, ok = verify_and_repair_prose(good, {}, "patisserie", full_facts=facts)
    assert "reco_direction_check" not in _validators(ok), ok


# ── B.5 ──────────────────────────────────────────────────────────────────
def test_hallucination_check_flags_fabrications():
    facts = {"n_posts_kept": 708, "modules": {}}
    bad = (
        "RÉSUMÉ :\nObjectif : atteindre 5000 posts ce trimestre.\n"
        "RECOMMANDATIONS :\n"
        "1. Lancer une collaboration avec @maisonturki.\n"
        "2. Publier des stories quotidiennes et des vidéos photo.\n"
        "3. Le modèle a une confiance de 99%."
    )
    _, issues = verify_and_repair_prose(bad, {}, "patisserie", full_facts=facts)
    assert "hallucination_check" in _validators(issues), issues
    blob = " ".join(i["message"] for i in issues)
    assert "post target" in blob          # atteindre 5000
    assert "collaboration" in blob        # @maisonturki
    assert "vidéo photo" in blob.lower() or "oxymoron" in blob.lower()
    assert "99%" in blob                  # confidence falsely %-ed

    good = ("RÉSUMÉ :\nLes 708 posts analysés montrent une tendance stable. "
            "Confiance : high (échantillon élevé).")
    _, ok = verify_and_repair_prose(good, {}, "patisserie", full_facts=facts)
    assert "hallucination_check" not in _validators(ok), ok
