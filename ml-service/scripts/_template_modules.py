"""_template_modules.py — deterministic French prose templates (Step 4).

WHY THIS EXISTS
---------------
A manual review of all 5 industries in the dashboard found ~20 prose
defects the LLM rephraser (rephrase_facts.py) keeps producing even after
the post-verifier + repair loop: residual ×100 hallucinations, logical
contradictions ("réduire X car X augmente l'engagement"), unreplaced
"X%" placeholders, invented absolute targets, "Outliers" recommended as
a real theme, inverted recommendations, cross-module contamination,
paraphrased technical names, and impossible recommendations.

OPTION C — HYBRID SELECTIVE ARCHITECTURE. Five modules are taken OUT of
the LLM path entirely and rendered here by deterministic templates that
read facts.json and emit fixed-structure French prose:

    Q1  content_strategy        -> template_content_strategy
    Q4  content_themes          -> template_content_themes
    Q5  hashtag_strategy        -> template_hashtag_strategy
    Q6  brand_differentiation   -> template_brand_differentiation
    Q8  engagement_tactics      -> template_engagement_tactics
    Q10 performance_predictors  -> template_performance_predictors

The remaining four (Q2/Q3/Q7/Q9) stay on the LLM — they read well.
(Q6 was added to the templated set after a live review found the LLM
still hallucinating a CTA contradiction into patisserie/Q6.)

INVARIANTS (every template here)
--------------------------------
1. Reads only facts.json. No LLM, no RAG, no network.
2. Output shape == the LLM path's: {"answer": str,
   "evidence": [str*3], "actionable_recommendations": [str*3]}.
3. Outliers (topic_id == -1, BERTopic catch-all) are filtered out of
   every theme recommendation.
4. Direction follows the SIGN of er_delta / SHAP direction:
       delta > 0  -> "Utiliser X : augmente … de {delta} pp"
       delta < 0  -> "Éviter X : diminue … de {abs(delta)} pp"
       delta ≈ 0  -> no directional reco (not "use", not "avoid")
5. Technical names (clip_pcXX, doc_pcXX, brand_engagement_rate,
   days_since_first_post, topic_id) are emitted verbatim, never
   translated. mean_abs_shap is a magnitude (always ≥ 0); its sign is
   carried by the word "influence positive/négative", never a minus.
6. No invented absolute numbers — only values present in facts.json. No
   "atteindre <n>" volume target.
7. Engagement rates / shares: 2-decimal "%" with the JSON value copied
   verbatim (0.08 -> "0.08%", never "8%"). Deltas: 2-decimal " pp".
8. Thin support is down-ranked: a signal/theme with n < MIN_N is only
   surfaced if no better-supported candidate exists; n is disclosed.

STRUCTURAL RULE found while validating: _verify_prose.er_bounds_check is
LINE-LEVEL — any "%" on a line containing the word "engagement" is
bounds-checked. A large share-% (sentiment positive_share, theme_share)
is NOT an engagement rate, so it must never share a line with the word
"engagement". Templates keep shares on dedicated lines/clauses.

The prose is engineered to pass _verify_prose.py with zero CRITICAL
issues by construction (correct directional verbs; signal-bearing
evidence lines phrased with "On observe/On constate" so _EVIDENCE_RE
exempts them from reco_direction_check; pp-vs-% discipline; verbatim
technical names; no augment-followers / improve-brand_engagement_rate
phrasing where SHAP direction is '-').
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

# Thin-sample floors. MIN_N is the generic floor for binary signals,
# tactics and themes (the user's chosen down-rank threshold). Hashtags
# get a lower floor: per-tag n is structurally tiny in this corpus
# (top tags sit at n=5..24), so a 20-floor would discard almost every
# hashtag. n is always disclosed inline regardless.
MIN_N = 20
MIN_N_HASHTAG = 10
OUTLIER_TOPIC_ID = -1


# ─────────────────────────────────────────────────────────────────────────
# Formatting helpers — the single place numbers become strings
# ─────────────────────────────────────────────────────────────────────────

def _num(v: Any, dp: int = 2) -> str:
    """2-decimal string, dot decimal (matches facts.json verbatim), with
    negative-zero normalised away ('-0.00' -> '0.00')."""
    try:
        f = round(float(v), dp)
    except (TypeError, ValueError):
        return "donnée insuffisante"
    if f == 0:
        f = 0.0
    return f"{f:.{dp}f}"


def _pct(v: Any) -> str:
    """Engagement rate / share: the JSON value IS the percentage. Copy it
    verbatim and append '%'. 0.08 -> '0.08%', 68.44 -> '68.44%'."""
    s = _num(v)
    return f"{s}%" if s != "donnée insuffisante" else s


def _pp(v: Any) -> str:
    """A delta in percentage points. Magnitude only (sign carried by the
    surrounding verb). -0.1 -> '0.10 pp', 0.04 -> '0.04 pp'."""
    try:
        return f"{_num(abs(float(v)))} pp"
    except (TypeError, ValueError):
        return "donnée insuffisante"


def _score(v: Any) -> str:
    """A unitless score (e.g. sentiment polarity). 0.598 -> '0.60'."""
    return _num(v)


def _int(v: Any) -> str:
    try:
        return str(int(v))
    except (TypeError, ValueError):
        return "donnée insuffisante"


def _conf_caveat(block: Dict[str, Any]) -> str:
    """RÈGLE 5: a low-confidence block gets '(échantillon limité)'."""
    return (" (échantillon limité)"
            if str(block.get("confidence")).lower() == "low" else "")


def _module(facts: Dict[str, Any], name: str) -> Dict[str, Any]:
    """Accept either the full facts dict or the module block directly
    (keeps unit tests hermetic)."""
    if isinstance(facts, dict) and "modules" in facts:
        return facts["modules"].get(name, {}) or {}
    return facts or {}


def _round2(v: Any) -> float:
    try:
        r = round(float(v), 2)
        return 0.0 if r == 0 else r
    except (TypeError, ValueError):
        return 0.0


def _pick_directional(items: List[Dict[str, Any]]
                      ) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Given items with 'delta' and 'n', return (best_positive,
    most_negative). Thin-sample down-rank: prefer n >= MIN_N; only fall
    back to a thin candidate if no well-supported one exists."""
    pos = [c for c in items if _round2(c["delta"]) > 0]
    neg = [c for c in items if _round2(c["delta"]) < 0]

    def pick(group: List[Dict[str, Any]], most: str) -> Optional[Dict[str, Any]]:
        if not group:
            return None
        solid = [c for c in group if (c.get("n") or 0) >= MIN_N]
        pool = solid or group
        return (max if most == "pos" else min)(pool, key=lambda c: c["delta"])

    return pick(pos, "pos"), pick(neg, "neg")


# Caption-length quartile -> French surface.
_BUCKET_FR = {
    "q1_shortest": "les captions les plus courtes",
    "q2":          "les captions plutôt courtes",
    "q3":          "les captions plutôt longues",
    "q4_longest":  "les captions les plus longues",
}

# Content / tactic signals. is_weekend / is_evening are deliberately
# EXCLUDED from Q1 & Q8 — they are timing signals belonging to Q2
# (contamination class G). (phrase for evidence, noun for recommendations)
_SIGNAL_FR = {
    "has_cta":        ("la présence d'un appel à l'action (CTA)", "les appels à l'action (CTA)"),
    "cta":            ("la présence d'un appel à l'action (CTA)", "les appels à l'action (CTA)"),
    "has_question":   ("la présence d'une question",              "les questions"),
    "question":       ("la présence d'une question",              "les questions"),
    "has_promo_word": ("la présence d'un mot promotionnel",       "les mots promotionnels"),
    "promo_word":     ("la présence d'un mot promotionnel",       "les mots promotionnels"),
    "has_emoji":      ("la présence d'emojis",                    "les emojis"),
}
_CONTENT_SIGNALS = ("has_cta", "has_question", "has_promo_word", "has_emoji")
_TACTIC_SIGNALS = ("cta", "question", "promo_word")

# Hashtag-count bucket -> data-driven French phrasing.
_HCOUNT_FR = {
    "0":    ("ne pas utiliser de hashtag (palier « 0 »)", "le palier « 0 » (aucun hashtag)"),
    "1-3":  ("se limiter à 1–3 hashtags",                  "le palier « 1-3 »"),
    "4-6":  ("viser 4 à 6 hashtags",                       "le palier « 4-6 »"),
    "7-10": ("viser 7 à 10 hashtags",                      "le palier « 7-10 »"),
}


# ─────────────────────────────────────────────────────────────────────────
# Q1 — Content Strategy
# ─────────────────────────────────────────────────────────────────────────

def template_content_strategy(facts: Dict[str, Any]) -> Dict[str, Any]:
    b = _module(facts, "content_strategy")
    n = b.get("n")
    caveat = _conf_caveat(b)

    # caption-length quartiles -------------------------------------------
    quarts = [q for q in b.get("caption_length_quartiles", [])
              if q.get("median_er") is not None]
    cap_answer = ""
    cap_evidence = "Longueur de caption : donnée insuffisante."
    cap_reco = ("Faute de données suffisantes sur la longueur des captions, "
                "tester systématiquement des formats courts et longs.")
    if quarts:
        best = max(quarts, key=lambda q: q["median_er"])
        worst = min(quarts, key=lambda q: q["median_er"])
        b_lbl = _BUCKET_FR.get(best.get("bucket"), "ce groupe de longueur")
        w_lbl = _BUCKET_FR.get(worst.get("bucket"), "l'autre groupe")
        cap_answer = (f"{b_lbl.capitalize()} affichent la meilleure médiane "
                      f"d'engagement ({_pct(best['median_er'])}), contre "
                      f"{_pct(worst['median_er'])} pour {w_lbl}.")
        cap_evidence = (f"Longueur de caption : {b_lbl} ont une médiane "
                        f"d'engagement de {_pct(best['median_er'])} (sur "
                        f"{best.get('n')} posts), contre "
                        f"{_pct(worst['median_er'])} pour {w_lbl} (sur "
                        f"{worst.get('n')} posts).")
        cap_reco = (f"Privilégier {b_lbl} : leur médiane d'engagement est de "
                    f"{_pct(best['median_er'])} contre "
                    f"{_pct(worst['median_er'])} pour {w_lbl}.")

    # sentiment (qualitative in answer; precise figures in evidence) ------
    s = b.get("sentiment") or {}
    if s.get("positive_share") is not None:
        pos_sh = float(s["positive_share"])
        neg_sh = float(s.get("negative_share") or 0.0)
        if pos_sh >= 60:
            sent_answer = "Le ton y est très majoritairement positif."
        elif pos_sh >= neg_sh:
            sent_answer = "Le ton y est globalement positif."
        else:
            sent_answer = "Le ton y est plutôt négatif."
        sent_evidence = (f"Sentiment : {_pct(s['positive_share'])} des posts "
                         f"au ton positif et {_pct(s.get('negative_share', 0))} "
                         f"au ton négatif (sur {s.get('n')} posts ; score "
                         f"médian de {_score(s.get('median'))}).")
        sent_fallback_reco = (f"Conserver un ton positif : "
                              f"{_pct(s['positive_share'])} des posts le sont "
                              f"déjà et seulement "
                              f"{_pct(s.get('negative_share', 0))} sont "
                              f"négatifs.")
    else:
        sent_answer = ""
        sent_evidence = "Sentiment : donnée insuffisante."
        sent_fallback_reco = "Maintenir une tonalité positive dans les captions."

    # content signals (exclude is_weekend / is_evening = Q2) -------------
    items = []
    for lift in b.get("binary_signal_lifts", []) or []:
        sig = lift.get("signal")
        if sig not in _CONTENT_SIGNALS or lift.get("er_delta") is None:
            continue
        items.append({"sig": sig, "delta": lift["er_delta"],
                      "n": lift.get("n_on"), "lift": lift})

    if items and max(abs(_round2(i["delta"])) for i in items) > 0:
        top = max(items, key=lambda i: abs(_round2(i["delta"])))
        ph, _ = _SIGNAL_FR[top["sig"]]
        L = top["lift"]
        sig_evidence = (f"On observe que {ph} s'accompagne d'une médiane "
                        f"d'engagement de {_pct(L.get('on_median_er'))} contre "
                        f"{_pct(L.get('off_median_er'))} en son absence "
                        f"(écart de {_pp(_round2(top['delta']))}, sur "
                        f"{L.get('n_on')} posts).")
    else:
        sig_evidence = ("On constate qu'aucun signal de contenu (CTA, "
                        "question, mot promotionnel, emoji) ne déplace la "
                        "médiane d'engagement de façon mesurable.")

    pos, neg = _pick_directional(items)
    if pos:
        _, noun = _SIGNAL_FR[pos["sig"]]
        rec_pos = (f"Utiliser {noun} : leur présence augmente la médiane "
                   f"d'engagement de {_pp(pos['delta'])} (sur "
                   f"{pos['lift'].get('n_on')} posts).")
    else:
        rec_pos = sent_fallback_reco
    if neg:
        _, noun = _SIGNAL_FR[neg["sig"]]
        rec_neg = (f"Éviter {noun} : leur présence réduit la médiane "
                   f"d'engagement de {_pp(neg['delta'])} (sur "
                   f"{neg['lift'].get('n_on')} posts).")
    else:
        rec_neg = ("On constate qu'aucun signal de contenu testé (CTA, "
                   "question, mot promotionnel, emoji) ne dégrade "
                   "l'engagement de façon mesurable.")

    answer_bits = []
    if n is not None:
        answer_bits.append(f"L'analyse porte sur {n} posts (confiance : "
                           f"{b.get('confidence', '?')}{caveat}).")
    if cap_answer:
        answer_bits.append(cap_answer)
    if sent_answer:
        answer_bits.append(sent_answer)
    answer = " ".join(answer_bits) or (
        f"Module Content Strategy : données déterministes issues de "
        f"facts.json{caveat}.")

    return {
        "answer": answer,
        "evidence": [cap_evidence, sent_evidence, sig_evidence],
        "actionable_recommendations": [cap_reco, rec_pos, rec_neg],
    }


# ─────────────────────────────────────────────────────────────────────────
# Q4 — Content Themes  (Outliers / topic_id == -1 filtered out)
# ─────────────────────────────────────────────────────────────────────────

def template_content_themes(facts: Dict[str, Any]) -> Dict[str, Any]:
    b = _module(facts, "content_themes")
    caveat = _conf_caveat(b)
    n_floor = b.get("n_floor_for_er", 5)

    raw = b.get("top_5_by_er", []) or []
    themes = [t for t in raw
              if t.get("topic_id") != OUTLIER_TOPIC_ID
              and t.get("theme_er") is not None]
    # Down-rank thin themes: well-supported (n >= MIN_N) first, then by ER.
    themes.sort(key=lambda t: ((t.get("n") or 0) >= MIN_N,
                               t.get("theme_er") or 0.0,
                               t.get("n") or 0), reverse=True)

    if not themes:
        return {
            "answer": (f"Content Themes : aucun thème propre au secteur ne "
                       f"dépasse le plancher de fiabilité (n ≥ {n_floor}) une "
                       f"fois le bucket résiduel topic_id -1 écarté{caveat}."),
            "evidence": [
                f"Les thèmes transverses ({b.get('cross_industry_topics_excluded', 0)}) "
                f"et le bucket résiduel topic_id -1 sont exclus par "
                f"construction.",
                "Aucun thème sectoriel ne dépasse le plancher de fiabilité.",
                f"Analyse fondée sur {b.get('n', 'N/A')} posts (confiance : "
                f"{b.get('confidence', '?')}).",
            ],
            "actionable_recommendations": [
                "Élargir la collecte pour faire émerger des thèmes "
                "sectoriels fiables.",
                "Tester de nouveaux angles de contenu propres au secteur.",
                "Réévaluer les thèmes une fois le volume de posts accru.",
            ],
        }

    t1 = themes[0]
    t2 = themes[1] if len(themes) > 1 else None
    t3 = themes[2] if len(themes) > 2 else None

    def nm(t):  # quoted topic name (verbatim from facts)
        return f"« {t.get('topic_name')} »"

    answer = (f"Le thème le plus engageant est {nm(t1)} avec une médiane "
              f"d'engagement de {_pct(t1['theme_er'])} (sur {t1.get('n')} "
              f"posts, confiance {t1.get('confidence', '?')}). "
              f"{len(themes)} thème(s) propre(s) au secteur dépassent le "
              f"plancher de fiabilité (n ≥ {n_floor}){caveat}.")

    ev1 = (f"{nm(t1)} : médiane d'engagement de {_pct(t1['theme_er'])} "
           f"(sur {t1.get('n')} posts, confiance {t1.get('confidence', '?')}).")
    if t2:
        ev2 = (f"{nm(t2)} : médiane d'engagement de {_pct(t2['theme_er'])} "
               f"(sur {t2.get('n')} posts, confiance "
               f"{t2.get('confidence', '?')}).")
    else:
        ev2 = ("Un seul thème sectoriel dépasse nettement le plancher de "
               "fiabilité.")
    # Volume line: NO "engagement" word here (theme_share is a share-%).
    share_bits = [f"{nm(t1)} pèse {_pct(t1.get('theme_share'))} des posts"]
    if t2:
        share_bits.append(f"{nm(t2)} {_pct(t2.get('theme_share'))}")
    if t3:
        share_bits.append(f"{nm(t3)} {_pct(t3.get('theme_share'))}")
    ev3 = "Volume actuel : " + ", ".join(share_bits) + "."

    rec1 = (f"Renforcer la production sur {nm(t1)} : c'est le thème à plus "
            f"forte médiane d'engagement ({_pct(t1['theme_er'])}).")
    # NOTE: do NOT assert "sous-exploité en volume" — a high-ER theme can
    # also have a high theme_share (e.g. hotels "Hotel Reviews Tunisia" =
    # 31.94%), which would make that claim false. Stay on the
    # engagement-backed statement, which always holds for top-ER themes.
    if t2 and t3:
        rec2 = (f"Développer {nm(t2)} ({_pct(t2['theme_er'])}) et {nm(t3)} "
                f"({_pct(t3['theme_er'])}) : forte médiane d'engagement, à "
                f"amplifier.")
    elif t2:
        rec2 = (f"Développer {nm(t2)} (médiane d'engagement "
                f"{_pct(t2['theme_er'])}) : performant, à amplifier.")
    else:
        rec2 = (f"Concentrer la production sur {nm(t1)} tant que les autres "
                f"thèmes sectoriels manquent de volume fiable.")
    weakest = themes[-1]
    # Only deprioritise the weakest theme when it is NOT one already being
    # reinforced/developed above (t1/t2/t3) — otherwise reco 2 and reco 3
    # would give opposite advice on the same theme (patisserie: 2 themes).
    if all(weakest is not x for x in (t1, t2, t3)):
        rec3 = (f"Concentrer les efforts sur les thèmes ci-dessus plutôt "
                f"que sur {nm(weakest)}, dont la médiane d'engagement est "
                f"la plus faible du classement ({_pct(weakest['theme_er'])}).")
    else:
        rec3 = ("Maintenir une rotation entre les thèmes sectoriels fiables "
                "identifiés pour éviter une sur-dépendance à un seul sujet.")

    return {
        "answer": answer,
        "evidence": [ev1, ev2, ev3],
        "actionable_recommendations": [rec1, rec2, rec3],
    }


# ─────────────────────────────────────────────────────────────────────────
# Q5 — Hashtag Strategy
# ─────────────────────────────────────────────────────────────────────────

def template_hashtag_strategy(facts: Dict[str, Any]) -> Dict[str, Any]:
    b = _module(facts, "hashtag_strategy")
    caveat = _conf_caveat(b)
    n_posts = b.get("n_posts")

    tags = [h for h in b.get("top_10_hashtags", []) or []
            if h.get("tag") and h.get("median_er") is not None]
    tags.sort(key=lambda h: h.get("median_er") or 0.0, reverse=True)
    # Down-rank thin tags (hashtag floor); fall back if none qualify.
    solid = [h for h in tags if (h.get("n") or 0) >= MIN_N_HASHTAG]
    head = (solid or tags)[:3]
    top_for_evidence = tags[:3]

    buckets = [c for c in b.get("count_buckets", []) or []
               if c.get("median_er") is not None]
    best_bk = max(buckets, key=lambda c: c["median_er"]) if buckets else None
    worst_bk = min(buckets, key=lambda c: c["median_er"]) if buckets else None

    if head:
        top1 = head[0]
        answer = (f"Sur {n_posts} posts (confiance : "
                  f"{b.get('confidence', '?')}{caveat}), le hashtag le plus "
                  f"performant est {top1['tag']} avec une médiane "
                  f"d'engagement de {_pct(top1['median_er'])} (sur "
                  f"{top1.get('n')} posts).")
    else:
        answer = (f"Sur {n_posts} posts (confiance : "
                  f"{b.get('confidence', '?')}{caveat}), aucun hashtag ne "
                  f"dispose d'un volume suffisant pour être recommandé.")

    if top_for_evidence:
        ev1 = ("Top hashtags par médiane d'engagement : "
                + ", ".join(f"{h['tag']} ({_pct(h['median_er'])}, n="
                            f"{h.get('n')})" for h in top_for_evidence) + ".")
    else:
        ev1 = "Aucun hashtag exploitable dans les faits."
    if best_bk and worst_bk:
        ev2 = (f"Le nombre de hashtags compte : le palier « "
               f"{best_bk['bucket']} » obtient la meilleure médiane "
               f"d'engagement ({_pct(best_bk['median_er'])}, sur "
               f"{best_bk.get('n')} posts), le palier « {worst_bk['bucket']} "
               f"» la plus faible ({_pct(worst_bk['median_er'])}, sur "
               f"{worst_bk.get('n')} posts).")
    else:
        ev2 = "Répartition par nombre de hashtags : donnée insuffisante."
    ev3 = (f"Analyse fondée sur {n_posts} posts (confiance : "
           f"{b.get('confidence', '?')}) ; {len(buckets)} paliers de volume "
           f"comparés.")

    if head:
        rec1 = ("Privilégier les hashtags à forte traction : "
                + ", ".join(f"{h['tag']} (médiane d'engagement "
                            f"{_pct(h['median_er'])}, sur {h.get('n')} posts)"
                            for h in head) + ".")
    else:
        rec1 = ("Reconstituer un socle de hashtags : aucun ne dispose "
                "encore d'un volume suffisant.")
    if best_bk:
        phrase, _ = _HCOUNT_FR.get(best_bk["bucket"],
                                   (f"viser le palier « {best_bk['bucket']} »",
                                    ""))
        rec2 = (f"Pour le nombre de hashtags, {phrase} : ce palier obtient "
                f"la meilleure médiane d'engagement "
                f"({_pct(best_bk['median_er'])}).")
    else:
        rec2 = "Standardiser le nombre de hashtags après collecte de données."
    if worst_bk and best_bk and worst_bk["bucket"] != best_bk["bucket"]:
        _, label = _HCOUNT_FR.get(worst_bk["bucket"],
                                  ("", f"le palier « {worst_bk['bucket']} »"))
        rec3 = (f"Éviter {label} : il affiche la médiane d'engagement la "
                f"plus faible ({_pct(worst_bk['median_er'])}).")
    else:
        rec3 = ("Tester des combinaisons de hashtags pour confirmer le "
                "palier optimal.")

    return {
        "answer": answer,
        "evidence": [ev1, ev2, ev3],
        "actionable_recommendations": [rec1, rec2, rec3],
    }


# ─────────────────────────────────────────────────────────────────────────
# Q6 — Brand Differentiation
# ─────────────────────────────────────────────────────────────────────────

def template_brand_differentiation(facts: Dict[str, Any]) -> Dict[str, Any]:
    """Deterministic prose for Q6: benchmark vs the industry median, top
    and bottom brands, and underserved themes as differentiation
    opportunities. No CTA/tactic surfaces (the LLM kept hallucinating a
    CTA contradiction here). Outliers (topic_id == -1) filtered from
    underserved themes; theme_share kept OFF "engagement" lines (it can
    exceed 2×p95); usernames cited verbatim without an '@' (so the
    hallucinated-collaboration check can never fire)."""
    b = _module(facts, "brand_differentiation")
    caveat = _conf_caveat(b)
    conf = b.get("confidence", "?")
    n_brands = b.get("n_brands_with_5plus_posts")
    med = b.get("industry_median_er")

    tops = [x for x in b.get("top_brands_by_median_er", []) or []
            if x.get("username") and x.get("median_er") is not None]
    bots = [x for x in b.get("bottom_brands_by_median_er", []) or []
            if x.get("username") and x.get("median_er") is not None]
    # Down-rank thin brands for the headline; disclose n regardless.
    solid_tops = [x for x in tops if (x.get("n") or 0) >= MIN_N]
    lead = (solid_tops or tops)[0] if (solid_tops or tops) else None

    themes = [t for t in b.get("underserved_themes", []) or []
              if t.get("topic_id") != OUTLIER_TOPIC_ID
              and t.get("theme_er") is not None]
    themes.sort(key=lambda t: ((t.get("n") or 0) >= MIN_N,
                               t.get("theme_er") or 0.0), reverse=True)

    # answer
    bits = []
    if n_brands is not None and med is not None:
        bits.append(f"Sur {n_brands} marques analysées (≥5 posts, "
                    f"confiance : {conf}{caveat}), la médiane d'engagement "
                    f"du secteur est de {_pct(med)}.")
    elif med is not None:
        bits.append(f"La médiane d'engagement du secteur est de "
                    f"{_pct(med)} (confiance : {conf}{caveat}).")
    if lead:
        bits.append(f"La marque la plus performante est "
                    f"{lead['username']} (médiane d'engagement "
                    f"{_pct(lead['median_er'])}, sur {lead.get('n')} "
                    f"posts), nettement au-dessus du secteur.")
    answer = " ".join(bits) or (
        f"Module Brand Differentiation : données déterministes issues de "
        f"facts.json{caveat}.")

    # evidence
    if tops:
        ev1 = ("Marques de référence par médiane d'engagement : "
                + ", ".join(f"{x['username']} ({_pct(x['median_er'])}, sur "
                            f"{x.get('n')} posts)" for x in tops[:3]) + ".")
    else:
        ev1 = "Marques de référence : donnée insuffisante."
    if bots and med is not None:
        ev2 = ("Sous la médiane sectorielle (" + _pct(med) + ") : "
                + ", ".join(f"{x['username']} ({_pct(x['median_er'])}, sur "
                            f"{x.get('n')} posts)" for x in bots[:3]) + ".")
    elif bots:
        ev2 = ("Marques en retrait : "
                + ", ".join(f"{x['username']} ({_pct(x['median_er'])})"
                            for x in bots[:3]) + ".")
    else:
        ev2 = "Marques en retrait : donnée insuffisante."
    if themes:
        # theme_er only here — NO theme_share on an "engagement" line.
        ev3 = ("Thèmes différenciants sous-exploités : "
                + ", ".join(f"« {t['topic_name']} » (médiane d'engagement "
                            f"{_pct(t['theme_er'])}, sur {t.get('n')} posts)"
                            for t in themes[:3]) + ".")
    else:
        ev3 = ("Aucun thème différenciant sous-exploité ne se dégage une "
               "fois le bucket résiduel topic_id -1 écarté.")

    # recommendations
    if med is not None:
        rec1 = (f"Se hisser au-dessus de la médiane d'engagement du "
                f"secteur ({_pct(med)}), aujourd'hui dépassée par les "
                f"marques de tête.")
    else:
        rec1 = ("Établir un benchmark d'engagement sectoriel une fois "
                "davantage de marques disponibles.")
    if lead:
        rec2 = (f"S'inspirer de la marque de tête {lead['username']} "
                f"(médiane d'engagement {_pct(lead['median_er'])}) : c'est "
                f"la référence à étudier.")
    else:
        rec2 = ("Identifier la marque de référence du secteur pour en "
                "analyser les bonnes pratiques.")
    if themes:
        t1 = themes[0]
        rec3 = (f"Investir le thème différenciant « {t1['topic_name']} » "
                f"(médiane d'engagement {_pct(t1['theme_er'])}), encore "
                f"peu couvert par les concurrents.")
    else:
        rec3 = ("Creuser de nouveaux thèmes différenciants : aucun thème "
                "sous-exploité fiable n'émerge encore.")

    return {
        "answer": answer,
        "evidence": [ev1, ev2, ev3],
        "actionable_recommendations": [rec1, rec2, rec3],
    }


# ─────────────────────────────────────────────────────────────────────────
# Q8 — Engagement Tactics
# ─────────────────────────────────────────────────────────────────────────

def template_engagement_tactics(facts: Dict[str, Any]) -> Dict[str, Any]:
    b = _module(facts, "engagement_tactics")
    caveat = _conf_caveat(b)
    n = b.get("n")

    items = []
    for lift in b.get("tactic_lifts", []) or []:
        tac = lift.get("tactic")
        if tac not in _TACTIC_SIGNALS or lift.get("er_delta") is None:
            continue
        items.append({"sig": tac, "delta": lift["er_delta"],
                      "n": lift.get("n_on"), "lift": lift})

    drivers = b.get("top_comment_drivers", []) or []
    d0 = drivers[0] if drivers else None

    # answer
    if items and max(abs(_round2(i["delta"])) for i in items) > 0:
        topt = max(items, key=lambda i: abs(_round2(i["delta"])))
        _, noun = _SIGNAL_FR[topt["sig"]]
        tac_clause = (f"{noun} se distinguent (écart de "
                      f"{_pp(_round2(topt['delta']))})")
    else:
        tac_clause = "aucune tactique de caption ne déplace nettement l'engagement"
    drv_clause = ""
    if d0:
        drv_clause = (f" Le format générant le plus de commentaires est "
                      f"{d0.get('content_type')} (jusqu'à "
                      f"{_int(d0.get('comments'))} commentaires sur un post "
                      f"du compte {d0.get('username')}).")
    answer = (f"Sur {n} posts (confiance : {b.get('confidence', '?')}"
              f"{caveat}), parmi les tactiques testées, {tac_clause}."
              f"{drv_clause}")

    # evidence
    if items and max(abs(_round2(i["delta"])) for i in items) > 0:
        topt = max(items, key=lambda i: abs(_round2(i["delta"])))
        L = topt["lift"]
        ph, _ = _SIGNAL_FR[topt["sig"]]
        ev1 = (f"On observe que {ph} s'accompagne d'une médiane "
               f"d'engagement de {_pct(L.get('on_median_er'))} contre "
               f"{_pct(L.get('off_median_er'))} sans (écart de "
               f"{_pp(_round2(topt['delta']))}, sur {L.get('n_on')} posts).")
    else:
        ev1 = ("On constate qu'aucune tactique testée (CTA, question, mot "
               "promotionnel) ne déplace la médiane d'engagement de façon "
               "mesurable.")
    if d0:
        ev2 = (f"Top générateur de commentaires : le compte "
               f"{d0.get('username')} avec un post {d0.get('content_type')} "
               f"({_int(d0.get('comments'))} commentaires pour "
               f"{_int(d0.get('followers'))} abonnés, soit un ratio de "
               f"{_score(d0.get('comments_per_1k_followers_ratio'))} pour "
               f"1000 abonnés).")
    else:
        ev2 = "Aucun générateur de commentaires identifié dans les faits."
    ev3 = (f"Analyse sur {n} posts (confiance : {b.get('confidence', '?')}) "
           f"; {len(items)} tactiques et {len(drivers)} posts les plus "
           f"commentés examinés.")

    # recommendations — direction from sign, thin-sample down-ranked
    pos, neg = _pick_directional(items)
    if pos:
        _, noun = _SIGNAL_FR[pos["sig"]]
        rec1 = (f"Utiliser {noun} : leur présence augmente la médiane "
                f"d'engagement de {_pp(pos['delta'])} (sur "
                f"{pos['lift'].get('n_on')} posts).")
    else:
        rec1 = ("Aucune tactique testée n'augmente l'engagement de façon "
                "mesurable : se concentrer sur le format générateur de "
                "commentaires.")
    if neg:
        _, noun = _SIGNAL_FR[neg["sig"]]
        rec2 = (f"Limiter {noun} : leur présence réduit la médiane "
                f"d'engagement de {_pp(neg['delta'])} (sur "
                f"{neg['lift'].get('n_on')} posts).")
    else:
        rec2 = ("On constate qu'aucune tactique testée (CTA, question, mot "
                "promotionnel) ne dégrade l'engagement de façon mesurable.")
    if d0:
        rec3 = (f"Capitaliser sur le format {d0.get('content_type')}, qui "
                f"génère le plus de commentaires (jusqu'à "
                f"{_int(d0.get('comments'))} sur un post du compte "
                f"{d0.get('username')}).")
    else:
        rec3 = ("Suivre les posts les plus commentés pour identifier les "
                "formats générateurs de conversation.")

    return {
        "answer": answer,
        "evidence": [ev1, ev2, ev3],
        "actionable_recommendations": [rec1, rec2, rec3],
    }


# ─────────────────────────────────────────────────────────────────────────
# Q10 — Performance Predictors
# ─────────────────────────────────────────────────────────────────────────

# Non-actionable predictors get observational phrasing (never "increase
# followers" / "improve brand_engagement_rate" when SHAP direction is '-';
# never "reduce days_since_first_post" — past time cannot shrink).
def _feature_reco(feat: str, shap: Any, direction: str) -> str:
    pos = direction == "+"
    sign_word = "positive" if pos else "négative"
    if feat == "clip_pc01":
        return (f"Soigner les caractéristiques visuelles que capture la "
                f"variable clip_pc01 (SHAP {_num(shap, 4)}, influence "
                f"{sign_word}).")
    if feat == "days_since_first_post":
        return (f"Capitaliser sur la régularité dans la durée : la variable "
                f"days_since_first_post (SHAP {_num(shap, 4)}, influence "
                f"{sign_word}) montre que l'ancienneté du compte renforce "
                f"la performance.")
    if feat == "doc_pc06":
        return (f"Réviser le style sémantique des captions que capture la "
                f"variable doc_pc06 (SHAP {_num(shap, 4)}, influence "
                f"{sign_word}).")
    if feat == "followers":
        return (f"Ne pas faire de la course aux abonnés une priorité : la "
                f"variable followers pèse fortement (SHAP {_num(shap, 4)}) "
                f"mais avec une influence {sign_word}.")
    if feat == "brand_engagement_rate":
        return (f"Tenir compte de brand_engagement_rate dans le ciblage "
                f"(SHAP {_num(shap, 4)}, influence {sign_word}) : c'est le "
                f"1er prédicteur, mais on ne le pilote pas directement.")
    return (f"Surveiller la variable {feat} (SHAP {_num(shap, 4)}, influence "
            f"{sign_word}).")


def template_performance_predictors(facts: Dict[str, Any]) -> Dict[str, Any]:
    b = _module(facts, "performance_predictors")
    caveat = _conf_caveat(b)
    feats = [f for f in b.get("top_5_features", []) or []
             if f.get("feature") and f.get("mean_abs_shap") is not None]
    feats.sort(key=lambda f: f.get("mean_abs_shap") or 0.0, reverse=True)

    model = b.get("model", "le modèle")
    r2 = b.get("model_r2_log")
    rho = b.get("model_rho")
    n_test = b.get("n_test_sample")

    if not feats:
        return {
            "answer": (f"Performance Predictors : le modèle {model} ne "
                       f"fournit pas de prédicteurs exploitables{caveat}."),
            "evidence": [
                f"Modèle : {model}.",
                (f"R²(log) de {_num(r2, 4)} et ρ de {_num(rho, 4)} sur "
                 f"{n_test} posts de test." if r2 is not None
                 else "Métriques de modèle indisponibles."),
                f"Confiance : {b.get('confidence', '?')}.",
            ],
            "actionable_recommendations": [
                "Réentraîner le modèle une fois davantage de données "
                "disponibles.",
                "Auditer les variables d'entrée du modèle.",
                "Réévaluer les prédicteurs au prochain cycle.",
            ],
        }

    f1 = feats[0]
    sign1 = "positive" if f1.get("direction") == "+" else "négative"
    answer = (f"{model} affiche un R²(log) de {_num(r2, 4)} et un ρ de "
              f"{_num(rho, 4)} sur {n_test} posts de test (confiance : "
              f"{b.get('confidence', '?')}{caveat}). Le prédicteur le plus "
              f"influent est {f1['feature']} (SHAP "
              f"{_num(f1['mean_abs_shap'], 4)}, influence {sign1}).")

    def ev_for(f):
        sw = "positive" if f.get("direction") == "+" else "négative"
        return (f"{f['feature']} — SHAP {_num(f['mean_abs_shap'], 4)}, "
                f"influence {sw} (catégorie {f.get('category', '?')})")

    ev1 = "1er prédicteur : " + ev_for(feats[0]) + "."
    ev2 = (" ; ".join(f"{i+2}e : " + ev_for(feats[i + 1])
                      for i in range(min(2, len(feats) - 1))) + "."
           if len(feats) > 1 else "Un seul prédicteur disponible.")
    ev3 = (" ; ".join(f"{i+4}e : " + ev_for(feats[i + 3])
                       for i in range(min(2, max(0, len(feats) - 3)))) + "."
           if len(feats) > 3 else
           f"Modèle : {model} ; échantillon de test {n_test} posts.")

    # Recommendations: actionable positive levers first, then a combined
    # observational note for the non-actionable negative predictors.
    by_feat = {f["feature"]: f for f in feats}
    recos: List[str] = []
    for name in ("clip_pc01", "days_since_first_post", "doc_pc06"):
        if name in by_feat and len(recos) < 2:
            f = by_feat[name]
            recos.append(_feature_reco(f["feature"], f["mean_abs_shap"],
                                       f.get("direction", "+")))
    neg_non_actionable = [by_feat[n] for n in ("brand_engagement_rate",
                                               "followers") if n in by_feat]
    if neg_non_actionable:
        parts = ", ".join(
            f"{f['feature']} (SHAP {_num(f['mean_abs_shap'], 4)})"
            for f in neg_non_actionable)
        recos.append("Ne pas surinvestir dans des leviers non pilotables : "
                     f"{parts} pèsent le plus mais avec une influence "
                     f"négative.")
    while len(recos) < 3 and feats:
        extra = next((f for f in feats
                      if _feature_reco(f["feature"], f["mean_abs_shap"],
                                       f.get("direction", "+")) not in recos),
                     None)
        if extra is None:
            break
        recos.append(_feature_reco(extra["feature"], extra["mean_abs_shap"],
                                   extra.get("direction", "+")))
    recos = (recos + [
        "Suivre l'évolution des prédicteurs au prochain réentraînement.",
        "Documenter les variables du modèle pour la prochaine itération.",
        "Réévaluer les leviers actionnables après collecte de données.",
    ])[:3]

    return {
        "answer": answer,
        "evidence": [ev1, ev2, ev3],
        "actionable_recommendations": recos,
    }


# ─────────────────────────────────────────────────────────────────────────
# Dispatch registry — module name -> template fn (used by rephrase_facts.py)
# ─────────────────────────────────────────────────────────────────────────

TEMPLATE_DISPATCH = {
    "content_strategy":       template_content_strategy,
    "content_themes":         template_content_themes,
    "hashtag_strategy":       template_hashtag_strategy,
    "brand_differentiation":  template_brand_differentiation,
    "engagement_tactics":     template_engagement_tactics,
    "performance_predictors": template_performance_predictors,
}


# ─────────────────────────────────────────────────────────────────────────
# Dry-run preview: `python scripts/_template_modules.py [module]`
# ─────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json
    import sys
    from pathlib import Path

    sys.stdout.reconfigure(encoding="utf-8")
    facts_dir = Path(__file__).resolve().parents[1] / "data" / "step4f_v6" / "facts"
    industries = ["beauty", "fashion", "hotels", "patisserie", "restaurants"]
    only = sys.argv[1] if len(sys.argv) > 1 else None

    for mod, fn in TEMPLATE_DISPATCH.items():
        if only and only != mod:
            continue
        for ind in industries:
            fp = facts_dir / f"facts_{ind}.json"
            if not fp.exists():
                continue
            data = json.loads(fp.read_text(encoding="utf-8"))
            out = fn(data)
            print("=" * 78)
            print(f"{ind.upper()}  —  {mod}")
            print("=" * 78)
            print("RÉSUMÉ :\n ", out["answer"])
            print("\nPREUVES :")
            for e in out["evidence"]:
                print("  -", e)
            print("\nRECOMMANDATIONS :")
            for i, r in enumerate(out["actionable_recommendations"], 1):
                print(f"  {i}. {r}")
            print()
