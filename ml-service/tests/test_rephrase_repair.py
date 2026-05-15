"""STEP C validation — the one-shot repair retry in rephrase_facts.py.

Uses a fake LLM (no Ollama) and a hand-crafted facts dict so it is
hermetic. Proves:
  1. a critical hallucination triggers exactly ONE retry, and a clean
     retry is adopted (status REPAIRED, validator_issues recorded);
  2. if the retry does not improve, the first answer is kept
     (status REPAIR_FAILED) and the LLM is still called at most twice;
  3. clean prose triggers NO retry (single LLM call).
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import rephrase_facts  # noqa: E402


class FakeLLM:
    """Returns the queued responses in order; records every prompt."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def invoke(self, prompt):
        self.calls.append(prompt)
        idx = min(len(self.calls) - 1, len(self._responses) - 1)
        return self._responses[idx]


FACTS = {
    "n_posts_kept": 700,
    "filter_summary": {"p95_cutoff_value": 0.6},
    "modules": {
        "content_strategy": {
            "confidence": "high",
            "n": 700,
            "binary_signal_lifts": [{"signal": "has_cta", "er_delta": 0.02}],
        },
        "engagement_tactics": {"tactic_lifts": []},
        "performance_predictors": {"top_5_features": []},
    },
}
Q = {"id": "Q1_content_strategy", "title": "Content Strategy",
     "module": "content_strategy"}

# "8% d'engagement" with p95=0.6 → er_bounds_check critical (×100 bug).
BAD = ("RÉSUMÉ :\nLe taux d'engagement moyen atteint 8% sur la période, "
       "un score élevé.\n\nPREUVES :\n- 8% d'engagement constaté.\n\n"
       "RECOMMANDATIONS :\n1. Maintenir la stratégie actuelle.")
GOOD = ("RÉSUMÉ :\nLe taux d'engagement médian est de 0.07% d'engagement, "
        "stable sur la période.\n\nPREUVES :\n- 0.07% d'engagement médian.\n\n"
        "RECOMMANDATIONS :\n1. Conserver la cadence de publication.")


def test_critical_triggers_one_retry_and_adopts_clean():
    llm = FakeLLM([BAD, GOOD])
    parsed, status, _lat, _bad, issues = rephrase_facts.rephrase_one(
        llm, "patisserie", Q, FACTS)
    assert len(llm.calls) == 2, "exactly one repair retry expected"
    assert status.startswith("REPAIRED"), status
    assert "0.07" in parsed["answer"], parsed
    assert all(i.get("severity") != "critical" for i in issues), issues
    # The repair prompt must carry the issue verbatim.
    assert "CORRECTION OBLIGATOIRE" in llm.calls[1]
    assert "decimal-loss" in llm.calls[1]


def test_retry_not_improving_keeps_first_and_caps_at_two_calls():
    llm = FakeLLM([BAD, BAD])
    parsed, status, _lat, _bad, issues = rephrase_facts.rephrase_one(
        llm, "patisserie", Q, FACTS)
    assert len(llm.calls) == 2, "must never loop beyond one retry"
    assert status.startswith("REPAIR_FAILED"), status
    assert "8%" in parsed["answer"], "first answer kept when retry no better"
    assert any(i.get("severity") == "critical" for i in issues), issues


def test_clean_prose_no_retry():
    llm = FakeLLM([GOOD])
    parsed, status, _lat, _bad, issues = rephrase_facts.rephrase_one(
        llm, "patisserie", Q, FACTS)
    assert len(llm.calls) == 1, "no retry when no critical issues"
    assert not status.startswith("REPAIR")
    assert all(i.get("severity") != "critical" for i in issues), issues
