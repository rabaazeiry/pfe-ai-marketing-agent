"""_verify_prose.py — programmatic post-verifier for LLM-rephrased Step-4 prose.

WHY THIS EXISTS
---------------
compute_facts.py makes the numbers deterministic, but rephrase_facts.py
still hands those numbers to llama3.1 to turn into French prose. A live
audit of the dashboard found systematic, repeatable hallucinations:

  * decimal loss ×100         0.08  → "8%"        (4 of 5 industries)
  * SHAP magnitude negated    0.0635 → "-0.0635"  (mean_abs_shap is ≥ 0)
  * invented technical terms  clip_pc01 → "fréquence des clips"
  * reco contradicts data     CTA delta −0.03 → "utilisez des CTA"
  * hallucinated targets      "atteindre 1000 posts"
  * hashtag → fake collab     "collaboration avec @maisonturki"
  * confidence falsely % -ed  "high" → "99%"

This module catches those classes programmatically, *after* the LLM call,
so rephrase_facts.py can re-prompt (max one retry) or log them. It never
calls an LLM and never edits the ML/facts layer — it only reads facts and
inspects a prose string.

PUBLIC API
----------
    verify_and_repair_prose(prose_text, facts_block, industry,
                            *, full_facts=None) -> Tuple[str, List[Dict]]

Returns the prose unchanged (the actual "repair" is the LLM re-prompt
driven by the caller — see rephrase_facts.py STEP C) together with the
list of issues found. Every issue is a dict::

    {"validator": <str>, "severity": "critical"|"warn", "message": <str>}

`severity == "critical"` issues are the ones rephrase_facts.py re-prompts
on; `"warn"` issues are logged and pass through.

`full_facts` is an optional escape hatch: when given (a parsed
facts_<industry>.json dict), it is used instead of reading the file from
disk. rephrase_facts.py already has it loaded, and the unit tests pass a
synthetic dict so they stay hermetic.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
FACTS_DIR = ROOT / "data" / "step4f_v6" / "facts"

# Feature names that must survive into the prose verbatim. They are opaque
# model internals (PCA components, engineered columns); any French
# "translation" of them is a hallucination by definition.
WHITELIST_TERMS: List[str] = (
    [f"clip_pc{i:02d}" for i in range(1, 11)]
    + [f"doc_pc{i:02d}" for i in range(1, 11)]
    + ["topic_id", "brand_engagement_rate", "days_since_first_post"]
)

# Known paraphrases the model substitutes for the whitelist terms. If one of
# these shows up while the real term is absent, it is a fabricated label.
_PARAPHRASE_RES = [
    re.compile(r"fr[ée]quence\s+des\s+(?:clips|vid[ée]os)", re.IGNORECASE),
    re.compile(r"taux\s+de\s+visionnage", re.IGNORECASE),
    re.compile(r"pourcentage\s+de\s+clips", re.IGNORECASE),
    re.compile(r"\bdocument\s+pc\s*\d+", re.IGNORECASE),
    re.compile(r"composante\s+(?:du\s+)?(?:document|clip)", re.IGNORECASE),
]

# A percentage token in the prose: 8%, 0,07 %, 2.12%.
_PCT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")
# A negative numeric token: -0.0635, - 12,3.
_NEG_NUM_RE = re.compile(r"(?<![\w.])-\s*\d+(?:[.,]\d+)?")

# Keywords proving a number is being presented AS an engagement rate.
_ER_CONTEXT = re.compile(r"engagement|taux\s+d'engagement|_er|\bER\b", re.IGNORECASE)
_ER_CONTEXT_CS = re.compile(r"\bER\b")  # case-sensitive ER acronym

# Signal/tactic key -> French surface forms the LLM uses in prose.
_SIGNAL_SURFACE: Dict[str, List[str]] = {
    "has_cta":        ["cta", "appel à l'action", "appel a l'action", "call to action"],
    "cta":            ["cta", "appel à l'action", "appel a l'action", "call to action"],
    "has_question":   ["question"],
    "question":       ["question"],
    "has_promo_word": ["promo", "promotionnel", "mot promotionnel"],
    "promo_word":     ["promo", "promotionnel", "mot promotionnel"],
    "has_emoji":      ["emoji", "émoji", "emojis", "émojis"],
    "has_hashtag":    ["hashtag"],
    "is_weekend":     ["weekend", "week-end", "fin de semaine"],
    "is_evening":     ["soir", "soirée", "en soirée"],
}

# Verbs that turn a mention into an endorsement / recommendation.
_ENDORSE_RE = re.compile(
    r"utilis|emploie|employ|augment|intensif|favoris|appliqu|optimis|"
    r"privil[ée]gi|recommand|miser\s+sur|ajout",
    re.IGNORECASE,
)


# ─────────────────────────────────────────────────────────────────────────
# Small helpers
# ─────────────────────────────────────────────────────────────────────────

def _issue(validator: str, severity: str, message: str) -> Dict[str, str]:
    return {"validator": validator, "severity": severity, "message": message}


def _to_number(raw: str) -> Optional[float]:
    """Parse a human number: '8', '0,07', '2.12', '1 000', '1 000', '1.000'."""
    s = raw.strip().replace(" ", " ").replace(" ", "")
    if not s:
        return None
    # 1.000 / 12.345.678 → thousands-grouped integer
    if re.fullmatch(r"\d{1,3}(\.\d{3})+", s):
        s = s.replace(".", "")
    else:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _load_full_facts(industry: str, full_facts: Optional[Dict[str, Any]]
                     ) -> Optional[Dict[str, Any]]:
    if full_facts is not None:
        return full_facts
    p = FACTS_DIR / f"facts_{industry}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def _lines(text: str) -> List[str]:
    return [ln for ln in text.splitlines() if ln.strip()]


# ─────────────────────────────────────────────────────────────────────────
# B.1 — engagement-rate plausibility (catches the ×100 decimal-loss bug)
# ─────────────────────────────────────────────────────────────────────────

def er_bounds_check(prose: str, facts: Optional[Dict[str, Any]]) -> List[Dict]:
    issues: List[Dict] = []
    if not facts:
        return issues
    p95 = (facts.get("filter_summary") or {}).get("p95_cutoff_value")
    if p95 is None:
        return issues
    ceiling = 2.0 * float(p95)
    for ln in _lines(prose):
        if not (_ER_CONTEXT.search(ln) or _ER_CONTEXT_CS.search(ln)):
            continue
        for m in _PCT_RE.finditer(ln):
            val = _to_number(m.group(1))
            if val is None:
                continue
            if val > ceiling:
                issues.append(_issue(
                    "er_bounds_check", "critical",
                    f"Engagement % {m.group(1)}% exceeds industry plausible "
                    f"max {round(ceiling, 4)}% (2×p95={p95}%) — likely "
                    f"decimal-loss ×100 bug. Copy the JSON value verbatim "
                    f"(e.g. 0.08% not 8%)."
                ))
    return issues


# ─────────────────────────────────────────────────────────────────────────
# B.2 — SHAP magnitude sign (mean_abs_shap is ≥ 0 by construction)
# ─────────────────────────────────────────────────────────────────────────

def shap_sign_check(prose: str, facts: Optional[Dict[str, Any]]) -> List[Dict]:
    issues: List[Dict] = []
    for ln in _lines(prose):
        if not re.search(r"shap|mean_abs_shap|valeur\s+shap", ln, re.IGNORECASE):
            continue
        neg = _NEG_NUM_RE.search(ln)
        if neg:
            issues.append(_issue(
                "shap_sign_check", "critical",
                f"mean_abs_shap rendered as negative ('{neg.group(0).strip()}') "
                f"— a SHAP magnitude is non-negative by definition. The SHAP "
                f"DIRECTION may be negative ('-'), the magnitude cannot."
            ))
    return issues


# ─────────────────────────────────────────────────────────────────────────
# B.3 — technical terms must appear verbatim, never translated
# ─────────────────────────────────────────────────────────────────────────

def technical_term_verbatim_check(prose: str, facts_block: Any,
                                  facts: Optional[Dict[str, Any]]) -> List[Dict]:
    issues: List[Dict] = []
    haystack = json.dumps(facts_block, ensure_ascii=False)
    if facts:
        haystack += json.dumps(facts, ensure_ascii=False)
    prose_l = prose.lower()
    paraphrase_present = [r for r in _PARAPHRASE_RES if r.search(prose)]
    if not paraphrase_present:
        return issues
    for term in WHITELIST_TERMS:
        if term not in haystack:
            continue                       # term not relevant to this block
        if term.lower() in prose_l:
            continue                       # term kept verbatim — fine
        issues.append(_issue(
            "technical_term_verbatim_check", "critical",
            f"Technical term '{term}' is in the facts but absent from the "
            f"prose, replaced by a hallucinated translation "
            f"(\"{paraphrase_present[0].pattern}\"). It must appear verbatim."
        ))
    return issues


# ─────────────────────────────────────────────────────────────────────────
# B.4 — recommendations must not contradict the measured direction
# ─────────────────────────────────────────────────────────────────────────

def reco_direction_check(prose: str, facts: Optional[Dict[str, Any]]) -> List[Dict]:
    issues: List[Dict] = []
    if not facts:
        return issues
    modules = facts.get("modules") or {}

    lifts = list((modules.get("content_strategy") or {}).get("binary_signal_lifts") or [])
    lifts += list((modules.get("engagement_tactics") or {}).get("tactic_lifts") or [])

    prose_lines = _lines(prose)
    for lift in lifts:
        key = lift.get("signal") or lift.get("tactic")
        delta = lift.get("er_delta")
        if key is None or delta is None or delta >= 0:
            continue
        surfaces = _SIGNAL_SURFACE.get(key, [key.replace("has_", "").replace("_", " ")])
        for ln in prose_lines:
            low = ln.lower()
            if _ENDORSE_RE.search(ln) and any(s in low for s in surfaces):
                issues.append(_issue(
                    "reco_direction_check", "critical",
                    f"Recommendation contradicts data: '{key}' has "
                    f"er_delta={delta} (negative) but the prose endorses it "
                    f"(\"{ln.strip()[:90]}\"). Do not recommend a signal that "
                    f"lowers engagement."
                ))
                break

    # performance_predictors: followers / brand_engagement_rate with a
    # negative SHAP direction must NOT be recommended to be increased.
    pp = (modules.get("performance_predictors") or {})
    feats = {f.get("feature"): f.get("direction") for f in pp.get("top_5_features", [])}
    low_prose = prose.lower()
    if feats.get("followers") == "-" and re.search(
        r"augment\w*\s+(?:le\s+nombre\s+de\s+|les\s+|de\s+)?followers|"
        r"plus\s+de\s+followers|gagner\s+des\s+followers", low_prose):
        issues.append(_issue(
            "reco_direction_check", "critical",
            "Recommendation contradicts data: 'followers' has SHAP "
            "direction '-' but the prose recommends increasing followers."
        ))
    if feats.get("brand_engagement_rate") == "-" and re.search(
        r"am[ée]lior\w*\s+le\s+taux\s+d'engagement\s+de\s+la\s+marque|"
        r"augment\w*\s+le\s+brand_engagement_rate", low_prose):
        issues.append(_issue(
            "reco_direction_check", "critical",
            "Recommendation contradicts data: 'brand_engagement_rate' has "
            "SHAP direction '-' but the prose recommends improving it."
        ))
    return issues


# ─────────────────────────────────────────────────────────────────────────
# B.5 — free-form hallucinations
# ─────────────────────────────────────────────────────────────────────────

def hallucination_check(prose: str, facts: Optional[Dict[str, Any]]) -> List[Dict]:
    issues: List[Dict] = []
    facts_blob = json.dumps(facts, ensure_ascii=False).lower() if facts else ""

    # (a) hallucinated post target
    n_kept = (facts or {}).get("n_posts_kept")
    for m in re.finditer(r"atteindre\s+((?:\d[\d  . ]*\d)|\d)", prose, re.IGNORECASE):
        target = _to_number(m.group(1))
        if target is None:
            continue
        if n_kept is not None and target > float(n_kept) * 1.1:
            issues.append(_issue(
                "hallucination_check", "critical",
                f"Hallucinated post target: 'atteindre {m.group(1).strip()}' "
                f"but only {n_kept} posts were analysed. No volume target is "
                f"in facts.json."
            ))
        elif n_kept is None and target >= 1000:
            issues.append(_issue(
                "hallucination_check", "critical",
                f"Hallucinated post target: 'atteindre {m.group(1).strip()}' "
                f"is not grounded in any facts value."
            ))

    # (b) hashtag presented as a commercial collaboration
    if re.search(r"(?:collaboration|partenariat)\s+avec\s+@", prose, re.IGNORECASE):
        issues.append(_issue(
            "hallucination_check", "critical",
            "A hashtag/handle is presented as a commercial collaboration "
            "target ('collaboration/partenariat avec @…'). Hashtags are not "
            "partners — this is fabricated."
        ))

    # (c) a content format that is not in the data
    for fmt in ("Instagram Live", "TikTok Live", "stories", "story",
                "Reels Live", "live shopping"):
        if re.search(re.escape(fmt), prose, re.IGNORECASE) and fmt.lower() not in facts_blob:
            issues.append(_issue(
                "hallucination_check", "critical",
                f"Content format '{fmt}' is cited but does not appear in "
                f"facts.json. Only data-backed formats may be recommended."
            ))

    # (d) the "vidéo photo" oxymoron
    if re.search(r"vid[ée]os?\s+photos?", prose, re.IGNORECASE):
        issues.append(_issue(
            "hallucination_check", "critical",
            "Oxymoron 'vidéo photo' — a post is a video or a photo, not both."
        ))

    # (e) confidence falsely quantified as a percentage
    for m in re.finditer(
        r"(confian\w+|confidence|fiabilit[ée]|certitude)[^.\n]{0,40}?(9[589])\s*%",
        prose, re.IGNORECASE):
        pct = m.group(2)
        if f"{pct}%" not in facts_blob and f"{pct} %" not in facts_blob:
            issues.append(_issue(
                "hallucination_check", "critical",
                f"Confidence falsely quantified as '{pct}%'. confidence is a "
                f"categorical label ('high'/'medium'/'low'), never a percent."
            ))
    return issues


# ─────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────

def verify_and_repair_prose(prose_text: str, facts_block: Any, industry: str,
                            *, full_facts: Optional[Dict[str, Any]] = None
                            ) -> Tuple[str, List[Dict]]:
    """Run the five validators over `prose_text`.

    Returns (prose_text_unchanged, issues). The prose is intentionally
    returned untouched: the only safe "repair" is to re-prompt the LLM with
    the issues (done by rephrase_facts.py), never to silently rewrite
    numbers here. The str slot in the tuple keeps a stable interface for a
    future programmatic-repair step.
    """
    facts = _load_full_facts(industry, full_facts)
    issues: List[Dict] = []
    issues += er_bounds_check(prose_text, facts)
    issues += shap_sign_check(prose_text, facts)
    issues += technical_term_verbatim_check(prose_text, facts_block, facts)
    issues += reco_direction_check(prose_text, facts)
    issues += hallucination_check(prose_text, facts)
    return prose_text, issues
