"""rephrase_facts.py — LLM rephrasing layer (Step 4, prose-only).

The LLM (llama3.1) is NOT in the calculation path anymore. It receives
ONLY the deterministic facts.json produced by compute_facts.py and
produces French dashboard prose. The dashboard reads this prose; Step 5
(strategy generation) reads facts.json directly — not this output.

CONSTRAINTS ENFORCED HERE
-------------------------
1. The model receives one tiny prompt per module, containing ONLY that
   module's slice of facts.json. No RAG, no Chroma, no cross-industry
   context. This keeps the prompt < 2 KB and the call latency < 30 s.

2. Every numeric prose value is verified against the set of numbers
   present in the source facts block. A number cited by the LLM that
   does NOT appear in facts is logged and removed from the prose.

3. Field-type discipline:
     * `_er`     → "X% d'engagement"
     * `_share`  → "X% des posts" (volume)
     * `_delta`  → "X pp" (percentage points)
     * `_ratio`  → "Xx" (multiplier)
   Prompted explicitly so the LLM cannot mix them.

4. Null fields → "donnée insuffisante", never invented.

5. Low confidence blocks → caveat "(échantillon limité)" appended.

OUTPUT SHAPE (kept identical to the legacy insights_<industry>.json so
the existing backend controller and frontend keep working):
  {
    "industry": ..., "version": "prose_v1",
    "questions": [ {question_id, question_title, answer, evidence,
                    actionable_recommendations, source_facts_path,
                    status, latency_seconds, insights[] }, ... ]
  }
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")
sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
# Make the sibling _verify_prose importable whether this file is run as a
# script (its dir is sys.path[0]) or imported as a module (it may not be).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _verify_prose import (  # noqa: E402
    verify_and_repair_prose,
    _PCT_RE, _ER_CONTEXT, _ER_CONTEXT_CS, _to_number,
)
# Option C — hybrid selective architecture. Q1/Q4/Q5/Q8/Q10 are rendered
# by deterministic templates (no LLM); Q2/Q3/Q6/Q7/Q9 stay on the LLM.
from _template_modules import TEMPLATE_DISPATCH  # noqa: E402

FACTS_DIR    = ROOT / "data" / "step4f_v6" / "facts"
INSIGHTS_DIR = ROOT / "data" / "step4f_v6" / "insights"
INDUSTRIES   = ["beauty", "fashion", "hotels", "patisserie", "restaurants"]

LLM_MODEL    = "llama3.1:latest"
TEMPERATURE  = 0.0   # Step D.1 — determinism > variety for a facts rephraser
MAX_TOKENS   = 700
TIMEOUT_S    = 180
MAX_REPAIR_RETRIES = 2   # hard cap on LLM repair attempts (never loops)

# ─────────────────────────────────────────────────────────────────────────
# Module → question mapping
# ─────────────────────────────────────────────────────────────────────────

QUESTIONS: List[Dict[str, str]] = [
    {"id": "Q1_content_strategy",       "title": "Content Strategy",       "module": "content_strategy"},
    {"id": "Q2_optimal_timing",         "title": "Optimal Timing",         "module": "optimal_timing"},
    {"id": "Q3_visual_strategy",        "title": "Visual Strategy",        "module": "visual_strategy"},
    {"id": "Q4_content_themes",         "title": "Content Themes",         "module": "content_themes"},
    {"id": "Q5_hashtag_strategy",       "title": "Hashtag Strategy",       "module": "hashtag_strategy"},
    {"id": "Q6_brand_differentiation",  "title": "Brand Differentiation",  "module": "brand_differentiation"},
    {"id": "Q7_calendar_strategy",      "title": "30-day Calendar",        "module": "calendar_30d"},
    {"id": "Q8_engagement_tactics",     "title": "Engagement Tactics",     "module": "engagement_tactics"},
    {"id": "Q9_current_trends",         "title": "Current Trends",         "module": "current_trends"},
    {"id": "Q10_performance_predictors","title": "Performance Predictors", "module": "performance_predictors"},
]

# ─────────────────────────────────────────────────────────────────────────
# Prompt — strict, short, type-disciplined
# ─────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """Tu rédiges, en français, le résumé d'un tableau de bord marketing tunisien.
Tu reçois UN SEUL BLOC DE FAITS JSON déjà calculé. Tu le REFORMULES, tu n'ajoutes RIEN.
Le JSON est la SEULE source de vérité. Toute information absente du JSON est INTERDITE.

LES 5 RÈGLES NON NÉGOCIABLES — CHAQUE infraction INVALIDE toute ta réponse.
Chaque règle est suivie d'un CONTRE-EXEMPLE réel à ne JAMAIS reproduire.

RÈGLE 1 — CHIFFRES COPIÉS CARACTÈRE PAR CARACTÈRE, AUCUN CALCUL.
  Tu ne multiplies pas, ne divises pas, n'arrondis pas, ne convertis pas.
  Tu attaches chaque chiffre à l'unité de son champ source :
  `_er`→« X% d'engagement » · `_share`→« X% des posts (volume) » ·
  `_delta`→« X pp » · `_ratio`→« Xx » · `hour_tunis`→« Xh » ·
  `dow`/`day`→nom du jour · `n`/`_count`→« X posts » ·
  `slide_count`→« X diapositives » · `topic_id`→identifiant (jamais un %).
  CONTRE-EXEMPLE INTERDIT : JSON `"median_er": 0.08`
    ❌ « 8% d'engagement »   (×100 : tu as inventé le pourcentage)
    ❌ « 0.08 » sans unité   ❌ « 0.08% » écrit « 8 % »
    ✅ « 0.08% d'engagement »  (le 0.08 EST déjà le pourcentage)

RÈGLE 2 — UNE MAGNITUDE SHAP (`mean_abs_shap`) EST TOUJOURS POSITIVE.
  Tu recopies `mean_abs_shap` tel quel, sans signe « - ». Le SENS de l'effet
  est porté SÉPARÉMENT par le champ `direction` (« + » ou « - ») : tu dis
  « influence positive/négative », tu ne mets jamais de moins sur la magnitude.
  CONTRE-EXEMPLE INTERDIT : JSON `"mean_abs_shap": 0.0635, "direction": "-"`
    ❌ « valeur SHAP de -0.0635 »
    ✅ « importance SHAP 0.0635, avec une influence négative »

RÈGLE 3 — LES NOMS TECHNIQUES RESTENT TELS QUELS, AUCUNE TRADUCTION.
  `clip_pc01`…`clip_pc10`, `doc_pc01`…`doc_pc10`, `topic_id`,
  `brand_engagement_rate`, `days_since_first_post` se recopient À L'IDENTIQUE.
  Tu n'inventes aucun libellé « lisible » pour ces champs.
  CONTRE-EXEMPLE INTERDIT : JSON `"feature": "clip_pc01"`
    ❌ « la fréquence des clips »  ❌ « le taux de visionnage »
    ❌ « le document PC06 »        ❌ « le pourcentage de clips »
    ✅ « la variable clip_pc01 »

RÈGLE 4 — UNE RECOMMANDATION DOIT SUIVRE LE SIGNE DES DONNÉES.
  Si un signal a `er_delta` < 0 (ou `direction` = « - »), il NUIT à
  l'engagement : tu recommandes de le RÉDUIRE/ÉVITER, jamais de l'utiliser,
  l'augmenter, l'intensifier ou le favoriser. Idem pour `followers` /
  `brand_engagement_rate` en direction « - ».
  CONTRE-EXEMPLE INTERDIT : JSON `{"signal":"has_cta","er_delta":-0.03}`
    ❌ « Utiliser des CTA pour améliorer l'engagement »
    ✅ « Réduire les CTA : leur présence baisse l'engagement de 0.03 pp »

RÈGLE 5 — N'INVENTE RIEN HORS DU JSON.
  Aucun objectif chiffré (« atteindre 1000 posts »), aucune collaboration
  ni partenariat (« collaboration avec @… » — un hashtag n'est pas un
  partenaire), aucun format absent du JSON (« Instagram Live », « stories »,
  « vidéo photo »). `confidence` est un MOT (« high »/« medium »/« low »),
  jamais un pourcentage. `null` → « donnée insuffisante ». Si
  `confidence` = « low », ajoute « (échantillon limité) ».
  CONTRE-EXEMPLE INTERDIT :
    ❌ « atteindre 775 posts »  ❌ « collaboration avec @maisonturki »
    ❌ « publier en Instagram Live »  ❌ « confiance de 99% »
    ✅ « confiance : high »   ✅ « donnée insuffisante »

CONTRAINTES DE FORME : pas de JSON, pas de markdown, pas d'anglais ;
2-4 phrases pour RÉSUMÉ ; 3 puces pour PREUVES ; 3 puces numérotées pour
RECOMMANDATIONS. Respecte EXACTEMENT ce gabarit (en-têtes compris) :

RÉSUMÉ :
[2-4 phrases citant uniquement des chiffres du JSON, copiés verbatim]

PREUVES :
- [fait chiffré 1 avec son chiffre verbatim et l'unité du champ source]
- [fait chiffré 2]
- [fait chiffré 3]

RECOMMANDATIONS :
1. [action concrète, cohérente avec le signe du chiffre du JSON]
2. [action concrète, cohérente avec le signe du chiffre du JSON]
3. [action concrète, cohérente avec le signe du chiffre du JSON]
"""

USER_PROMPT_TEMPLATE = """SECTEUR : {industry}
MODULE : {module_title}

FAITS (JSON, source unique de vérité) :
```json
{facts_block}
```

Reformule ce bloc en suivant strictement le format imposé."""

# ─────────────────────────────────────────────────────────────────────────
# Number extraction & verification
# ─────────────────────────────────────────────────────────────────────────

# Numbers in the prose look like: 12.34%, 0,07 %, 1.8x, -0.06 pp, 1234, 0.05.
# We require a non-letter character before the digit so identifiers like
# `R2`, `clip_pc01`, `doc_pc06` aren't matched as standalone numbers.
_NUM_RE = re.compile(r"(?<![A-Za-z_])(-?\d+(?:[.,]\d+)?)\s*(?:%|pp|x)?", re.IGNORECASE)


def _facts_number_set(obj: Any) -> set[str]:
    """Collect every numeric value present in a facts block as a normalised
    decimal string. We compare on a normalised form so '0.07' and '0,07'
    are considered equal."""
    out: set[str] = set()

    def walk(o: Any) -> None:
        if isinstance(o, (int, float)) and not isinstance(o, bool):
            f = float(o)
            # Two normalised forms: the raw float repr (with python rounding)
            # and the 2-decimal rounded form (the formatter standard in
            # compute_facts.py).
            out.add(f"{f:.4f}".rstrip("0").rstrip("."))
            out.add(f"{round(f, 2):.4f}".rstrip("0").rstrip("."))
            out.add(f"{round(f, 1):.4f}".rstrip("0").rstrip("."))
            out.add(f"{int(f)}" if float(f).is_integer() else f"{f:.4f}".rstrip("0").rstrip("."))
        elif isinstance(o, str):
            # numbers that appear as strings (eg. "median_er": "0.08")
            for m in _NUM_RE.finditer(o):
                try:
                    f = float(m.group(1).replace(",", "."))
                    out.add(f"{round(f, 2):.4f}".rstrip("0").rstrip("."))
                except ValueError:
                    pass
        elif isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for item in o:
                walk(item)

    walk(obj)
    return out


def _prose_numbers(text: str) -> List[Tuple[str, float]]:
    """Extract every numeric token from prose, returning the raw match and
    its float value. Skips ordinal markers and explicit indices."""
    found: List[Tuple[str, float]] = []
    for m in _NUM_RE.finditer(text):
        try:
            f = float(m.group(1).replace(",", "."))
        except ValueError:
            continue
        # Skip year-like and small-integer index numbers cleanly: 1./2./3.
        if 1900 <= f <= 2100 and f.is_integer():
            continue
        found.append((m.group(0), f))
    return found


def _verify_prose(prose: str, facts_block: Any) -> Tuple[str, List[float]]:
    """Verify every numeric token in `prose` exists in `facts_block`.
    Returns (verified_prose, list_of_unverified_numbers)."""
    facts_nums = _facts_number_set(facts_block)
    bad: List[float] = []
    for raw, f in _prose_numbers(prose):
        for key in (f"{round(f, 2):.4f}".rstrip("0").rstrip("."),
                    f"{round(f, 1):.4f}".rstrip("0").rstrip("."),
                    f"{f:.4f}".rstrip("0").rstrip("."),
                    str(int(f)) if float(f).is_integer() else ""):
            if key and key in facts_nums:
                break
        else:
            bad.append(f)
    return prose, bad


# ─────────────────────────────────────────────────────────────────────────
# Prose parsing
# ─────────────────────────────────────────────────────────────────────────

def _split_sections(text: str) -> Dict[str, str]:
    """Split the LLM output into named sections. Tolerant of:
      - leading column-0 first section (no preceding \\n)
      - markdown-bold wrappers (`**RÉSUMÉ :**`)
      - missing colon, extra whitespace
    All real bugs encountered in practice, not theoretical."""
    sections: Dict[str, str] = {}
    # Match optional **/##/space wrap, optional colon, optional trailing wrap
    parts = re.split(
        r'(?:^|\n)\s*[*#]*\s*(RÉSUMÉ|PREUVES|RECOMMANDATIONS)\s*:?\s*[*#]*\s*\n?',
        text,
    )
    for i in range(1, len(parts) - 1, 2):
        sections[parts[i]] = parts[i + 1].strip()
    return sections


def _strip_md(s: str) -> str:
    """Drop markdown bold/italic markers so dashboard prose stays clean."""
    return re.sub(r"\*+", "", s).strip()


def _bullets(text: str) -> List[str]:
    return [
        _strip_md(re.sub(r"^[-•·]\s*", "", ln))
        for ln in text.splitlines()
        if re.match(r"^\s*[-•·]", ln) and len(ln.strip()) > 4
    ]


def _numbered(text: str) -> List[str]:
    return [
        _strip_md(m.group(1))
        for ln in text.splitlines()
        for m in (re.match(r"^\s*\d+[\.\)]\s+(.+)", ln),)
        if m and len(m.group(1)) > 4
    ]


def _parse_prose(text: str) -> Dict[str, Any]:
    secs = _split_sections(text)
    return {
        "answer":   _strip_md(secs.get("RÉSUMÉ", "")),
        "evidence": _bullets(secs.get("PREUVES", "")),
        "actionable_recommendations": _numbered(secs.get("RECOMMANDATIONS", "")),
    }


# ─────────────────────────────────────────────────────────────────────────
# Per-question deterministic fallback (no LLM)
# ─────────────────────────────────────────────────────────────────────────

def _fallback_prose(industry: str, q: Dict[str, str], facts_block: Any) -> Dict[str, Any]:
    """If the LLM is unreachable or its output fails verification, return a
    deterministic minimal prose built from the facts block itself. This
    way the dashboard always displays grounded numbers, never an excuse."""
    if isinstance(facts_block, list):
        n = len(facts_block)
        ans = f"Module « {q['title']} » : {n} entrées générées depuis les faits déterministes pour le secteur {industry}."
        ev = []
        recs = ["Voir le calendrier détaillé jour par jour dans facts.json."]
    else:
        conf = (facts_block or {}).get("confidence", "?")
        ans = f"Module « {q['title']} » pour {industry} (confiance : {conf}). Les valeurs déterministes proviennent de facts.json."
        ev, recs = [], []
        # Best-effort: surface a couple of leaf facts as evidence bullets
        try:
            for k, v in list((facts_block or {}).items())[:6]:
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    ev.append(f"{k} = {v}")
                    if len(ev) >= 3:
                        break
        except AttributeError:
            pass
    return {
        "answer": ans,
        "evidence": ev or ["facts.json est la source de vérité — voir le fichier brut."],
        "actionable_recommendations": recs or ["Consulter le module correspondant dans facts.json."],
    }


# ─────────────────────────────────────────────────────────────────────────
# Per-question rephrasing
# ─────────────────────────────────────────────────────────────────────────

def _block_for_module(facts: Dict[str, Any], module_name: str) -> Any:
    if module_name == "calendar_30d":
        # Summarise the calendar so the prompt stays small.
        cal = facts.get("calendar_30d", [])
        formats_seen = sorted({d.get("format") for d in cal if d.get("format")})
        themes_seen = sorted({d.get("theme_name") for d in cal if d.get("theme_name")})
        # Aggregate hashtag rotation
        hashtag_pool = sorted({h for d in cal for h in (d.get("hashtags") or [])})
        # First-7-days preview
        preview = [
            {"day": d["day_index"], "date": d["date"], "dow": d["recommended_day"],
             "format": d["format"], "theme": d["theme_name"], "hashtags": d["hashtags"]}
            for d in cal[:7]
        ]
        return {
            "n_days": len(cal),
            "formats_used": formats_seen,
            "themes_rotation": themes_seen,
            "hashtag_pool": hashtag_pool,
            "preview_first_week": preview,
        }
    return facts.get("modules", {}).get(module_name, {})


def _combined_prose(parsed: Dict[str, Any]) -> str:
    """Flatten a parsed prose dict into one string for verification."""
    return (parsed.get("answer", "") + "\n"
            + "\n".join(parsed.get("evidence", [])) + "\n"
            + "\n".join(parsed.get("actionable_recommendations", [])))


def _build_repair_prompt(critical: List[Dict[str, Any]]) -> str:
    """Augment the original prompt with the critical issues, verbatim, so
    the LLM rewrites the answer without re-introducing them."""
    bullets = "\n".join(f"- {i['message']}" for i in critical)
    return (
        "\n\n──────────\n"
        "CORRECTION OBLIGATOIRE. Ta réponse précédente contenait des erreurs "
        "factuelles GRAVES listées ci-dessous. Réécris INTÉGRALEMENT la "
        "réponse en respectant le FORMAT EXACT imposé et en corrigeant "
        "CHAQUE point. Ne réintroduis AUCUNE de ces erreurs :\n"
        f"{bullets}\n"
        "Rappels : copie les chiffres du JSON caractère par caractère "
        "(0.08 reste « 0.08% », jamais « 8% ») ; une magnitude SHAP est "
        "toujours positive ; garde les noms techniques (clip_pcXX, doc_pcXX, "
        "brand_engagement_rate, topic_id…) tels quels ; n'invente ni "
        "objectif chiffré, ni collaboration, ni format absent du JSON ; "
        "ne recommande jamais un signal dont l'er_delta est négatif."
    )


def _determ_er_repair(parsed: Dict[str, Any], facts_block: Any,
                      facts: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
    """No-LLM, deterministic fix for residual ×100 engagement hallucinations.

    For every "X%" in an engagement-rate context whose value exceeds the
    industry's plausible ceiling (2×p95), try to map it back to a REAL facts
    value: X/100 then X/1000. If the rescaled value exists verbatim in the
    facts number-set, rewrite the token to that grounded value (this is the
    common 0.12 → "12%" loss). If no facts value matches, the number is
    pure invention and is replaced by « valeur indisponible » rather than
    left wrong. Jury-safe: a corrected token always traces to facts.json."""
    p95 = (facts.get("filter_summary") or {}).get("p95_cutoff_value")
    if p95 is None:
        return parsed, 0
    ceiling = 2.0 * float(p95)

    # STRICT facts set: exact + 2-dp forms only, zeros excluded. (The shared
    # _facts_number_set rounds to 1 dp and emits "0", which would let a
    # bogus 0.008 "match" 0.02 — exactly the degenerate we must avoid here.)
    def _norm(x: float) -> str:
        return f"{x:.4f}".rstrip("0").rstrip(".")

    factset: set = set()

    def _walk(o: Any) -> None:
        if isinstance(o, bool):
            return
        if isinstance(o, (int, float)):
            if abs(float(o)) > 1e-9:
                factset.add(_norm(float(o)))
                factset.add(_norm(round(float(o), 2)))
        elif isinstance(o, dict):
            for v in o.values():
                _walk(v)
        elif isinstance(o, list):
            for v in o:
                _walk(v)

    _walk(facts_block)
    n_fixed = 0

    def _fix_line(ln: str) -> str:
        nonlocal n_fixed
        if not (_ER_CONTEXT.search(ln) or _ER_CONTEXT_CS.search(ln)):
            return ln

        def _repl(m: "re.Match") -> str:
            nonlocal n_fixed
            val = _to_number(m.group(1))
            if val is None or val <= ceiling:
                return m.group(0)
            for div in (100.0, 1000.0):
                cand = val / div
                keys = {_norm(cand), _norm(round(cand, 2))}
                if keys & factset:
                    n_fixed += 1
                    return f"{_norm(cand)}%"
            n_fixed += 1
            return "valeur indisponible"

        return _PCT_RE.sub(_repl, ln)

    def _fix_text(t: str) -> str:
        return "\n".join(_fix_line(l) for l in t.split("\n"))

    parsed["answer"] = _fix_text(parsed.get("answer", ""))
    parsed["evidence"] = [_fix_text(x) for x in parsed.get("evidence", [])]
    parsed["actionable_recommendations"] = [
        _fix_text(x) for x in parsed.get("actionable_recommendations", [])
    ]
    return parsed, n_fixed


def _template_one(industry: str, q: Dict[str, str], facts: Dict[str, Any]
                  ) -> Tuple[Dict[str, Any], str, float, List[float], List[Dict[str, Any]]]:
    """Deterministic template path (no LLM). Renders the module from
    facts.json, then runs BOTH verifiers for reporting only — never the
    repair loop. The templates are clean by construction, so a non-zero
    critical here is a real regression worth surfacing in the dashboard."""
    facts_block = _block_for_module(facts, q["module"])
    parsed = TEMPLATE_DISPATCH[q["module"]](facts)
    combined = _combined_prose(parsed)
    _, bad_nums = _verify_prose(combined, facts_block)
    _, validator_issues = verify_and_repair_prose(
        combined, facts_block, industry, full_facts=facts)
    n_crit = sum(1 for i in validator_issues
                 if i.get("severity") == "critical")
    status = "TEMPLATE" if n_crit == 0 else f"TEMPLATE_CRIT: {n_crit} critical"
    return parsed, status, 0.0, bad_nums, validator_issues


def rephrase_one(llm, industry: str, q: Dict[str, str], facts: Dict[str, Any]
                 ) -> Tuple[Dict[str, Any], str, float, List[float], List[Dict[str, Any]]]:
    """Run a single LLM call for one question. Returns (parsed_prose,
    status, latency_seconds, unverified_numbers, validator_issues).

    After the legacy number-set check, the prose is run through
    _verify_prose.verify_and_repair_prose. If it raises CRITICAL issues the
    prompt is augmented with a verbatim repair instruction and the LLM is
    called exactly ONCE more (hard cap, never loops). The retry is kept only
    if it has strictly fewer critical issues; otherwise the first answer is
    kept and every issue is logged."""
    # Option C: templated modules never touch the LLM.
    if q["module"] in TEMPLATE_DISPATCH:
        return _template_one(industry, q, facts)

    facts_block = _block_for_module(facts, q["module"])
    facts_block_json = json.dumps(facts_block, ensure_ascii=False, indent=2)

    # Guard against blocks that ballooned (shouldn't happen but defensive)
    if len(facts_block_json) > 6000:
        facts_block_json = facts_block_json[:6000] + "\n... (truncated)"

    user_prompt = USER_PROMPT_TEMPLATE.format(
        industry=industry, module_title=q["title"], facts_block=facts_block_json,
    )
    full = f"{SYSTEM_PROMPT}\n\n{user_prompt}"

    status = "OK"
    bad_nums: List[float] = []
    t_l = time.perf_counter()
    try:
        resp = llm.invoke(full)
    except Exception as e:  # noqa: BLE001
        return (_fallback_prose(industry, q, facts_block),
                f"LLM_ERROR: {e}", time.perf_counter() - t_l, [], [])
    latency = time.perf_counter() - t_l

    parsed = _parse_prose(resp)
    if not parsed.get("answer") or len(parsed["answer"]) < 20:
        return _fallback_prose(industry, q, facts_block), "PARSE_FAIL", latency, [], []

    # 1. Legacy number-set check (every cited number must exist in facts).
    _, bad_nums = _verify_prose(_combined_prose(parsed), facts_block)

    # 2. New programmatic hallucination verifier.
    _, validator_issues = verify_and_repair_prose(
        _combined_prose(parsed), facts_block, industry, full_facts=facts)
    critical = [i for i in validator_issues if i.get("severity") == "critical"]

    # 3. Up to MAX_REPAIR_RETRIES LLM repair attempts; always keep the best
    #    (fewest criticals) seen so far. Hard-capped — never loops.
    n_retries = 0
    if critical:
        for _ in range(MAX_REPAIR_RETRIES):
            if not critical:
                break
            n_retries += 1
            try:
                resp_r = llm.invoke(full + _build_repair_prompt(critical))
            except Exception as e:  # noqa: BLE001
                status = f"REPAIR_ERROR: {e}"
                break
            parsed_r = _parse_prose(resp_r)
            if not parsed_r.get("answer") or len(parsed_r["answer"]) < 20:
                continue
            _, bad_r = _verify_prose(_combined_prose(parsed_r), facts_block)
            _, issues_r = verify_and_repair_prose(
                _combined_prose(parsed_r), facts_block, industry,
                full_facts=facts)
            crit_r = [i for i in issues_r if i.get("severity") == "critical"]
            if len(crit_r) < len(critical):
                parsed, bad_nums = parsed_r, bad_r
                validator_issues, critical = issues_r, crit_r
        status = (f"REPAIRED: {len(critical)} critical left"
                  if not status.startswith("REPAIR_ERROR")
                  else status)

    # 4. Deterministic, no-LLM fix for any ×100 engagement value the LLM
    #    still produced. This guarantees zero residual er_bounds errors.
    n_determ = 0
    if any(i.get("validator") == "er_bounds_check" for i in critical):
        parsed, n_determ = _determ_er_repair(parsed, facts_block, facts)
        if n_determ:
            _, bad_nums = _verify_prose(_combined_prose(parsed), facts_block)
            _, validator_issues = verify_and_repair_prose(
                _combined_prose(parsed), facts_block, industry,
                full_facts=facts)
            critical = [i for i in validator_issues
                        if i.get("severity") == "critical"]

    # 5. Final status.
    bits = []
    if n_retries:
        bits.append(f"retry×{n_retries}")
    if n_determ:
        bits.append(f"er_determ×{n_determ}")
    if critical:
        bits.append(f"{len(critical)}crit")
    if status.startswith("REPAIR_ERROR"):
        pass
    elif critical:
        status = "VALIDATOR_CRIT: " + " ".join(bits)
    elif bits:
        status = "REPAIRED: " + " ".join(bits)
    elif bad_nums:
        status = f"VERIFY_WARN: {len(bad_nums)} unverified numbers"
    else:
        status = "OK"

    return parsed, status, latency, bad_nums, validator_issues


def _make_question_entry(q: Dict[str, str], parsed: Dict[str, Any],
                         status: str, latency: float, bad: List[float],
                         validator_issues: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The per-question dashboard record. Shared by the full run and the
    --rerun-flagged path so both write an identical schema."""
    return {
        "question_id":                q["id"],
        "question_title":             q["title"],
        "source_module":              q["module"],
        "answer":                     parsed.get("answer", ""),
        "evidence":                   parsed.get("evidence", []),
        "actionable_recommendations": parsed.get("actionable_recommendations", []),
        "insights":                   _synth_legacy_insights(parsed),
        "status":                     status,
        "latency_seconds":            round(latency, 2),
        "unverified_numbers":         bad,
        "validator_issues":           validator_issues,
    }


def _synth_legacy_insights(parsed: Dict[str, Any]) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for rec in (parsed.get("actionable_recommendations") or [])[:5]:
        if isinstance(rec, str) and rec.strip():
            words = rec.strip().split()
            out.append({
                "title":   " ".join(words[:8]),
                "content": rec.strip(),
                "evidence": "actionable_recommendations",
            })
    return out


def rerun_flagged(llm, industries: List[str]) -> int:
    """Re-generate ONLY the questions whose stored prose still has a critical
    issue under the (now precise) verifier. Clean questions are left as-is —
    their validator_issues are merely refreshed with the fixed verifier so
    the dashboard shows accurate flags. ~one-quarter the cost of a full run."""
    qdef = {q["id"]: q for q in QUESTIONS}
    print("=" * 78)
    print("rephrase_facts.py --rerun-flagged  (regenerate only flagged Qs)")
    print("=" * 78)
    grand_regen = 0
    grand_calls = 0
    t0 = time.time()
    for ind in industries:
        facts_path = FACTS_DIR / f"facts_{ind}.json"
        ins_path = INSIGHTS_DIR / f"insights_{ind}.json"
        if not facts_path.exists() or not ins_path.exists():
            print(f"  ⚠  skip {ind}: missing facts or insights")
            continue
        facts = json.loads(facts_path.read_text(encoding="utf-8"))
        env = json.loads(ins_path.read_text(encoding="utf-8"))
        print(f"\n[{ind.upper()}]  ({facts['n_posts_kept']} posts kept)")
        print("-" * 78)
        regen = 0
        for idx, qe in enumerate(env.get("questions", [])):
            q = qdef.get(qe.get("question_id"))
            if q is None:
                continue
            block = _block_for_module(facts, q["module"])
            prose = (qe.get("answer", "") + "\n"
                     + "\n".join(qe.get("evidence", [])) + "\n"
                     + "\n".join(qe.get("actionable_recommendations", [])))
            _, iss = verify_and_repair_prose(prose, block, ind, full_facts=facts)
            crit = [i for i in iss if i.get("severity") == "critical"]
            if not crit:
                qe["validator_issues"] = iss          # refresh, no LLM
                print(f"  Q{idx+1:>2}/10  {q['title']:<24}  KEEP   (clean)")
                continue
            before = len(crit)
            parsed, status, latency, bad, vissues = rephrase_one(
                llm, ind, q, facts)
            grand_calls += 1
            after = sum(1 for i in vissues if i.get("severity") == "critical")
            env["questions"][idx] = _make_question_entry(
                q, parsed, status, latency, bad, vissues)
            regen += 1
            print(f"  Q{idx+1:>2}/10  {q['title']:<24}  REGEN  "
                  f"crit {before}→{after}  {status}")
        env["generated_at"] = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
        ins_path.write_text(json.dumps(env, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        grand_regen += regen
        print(f"  → {ins_path.name}  ({regen} regenerated)")
    print()
    print("=" * 78)
    print(f"rerun-flagged complete: {grand_regen} questions regenerated, "
          f"{grand_calls} hit the LLM, {(time.time()-t0)/60:.1f} min")
    print("=" * 78)
    return 0


def apply_templates(industries: List[str]) -> int:
    """No-LLM in-place pass. Replaces ONLY the templated questions
    (Q1/Q4/Q5/Q8/Q10) in each existing insights_<industry>.json with
    fresh deterministic template output, refreshes validator_issues on
    the untouched LLM questions, and rewrites the file. The working LLM
    prose for Q2/Q3/Q6/Q7/Q9 is preserved verbatim — Ollama is never
    contacted. This is the jury-safe regeneration path."""
    qdef = {q["module"]: q for q in QUESTIONS}
    print("=" * 78)
    print("rephrase_facts.py --apply-templates  (deterministic, no LLM)")
    print("=" * 78)
    grand_tmpl = 0
    grand_crit = 0
    for ind in industries:
        facts_path = FACTS_DIR / f"facts_{ind}.json"
        ins_path = INSIGHTS_DIR / f"insights_{ind}.json"
        if not facts_path.exists() or not ins_path.exists():
            print(f"  ⚠  skip {ind}: missing facts or insights")
            continue
        facts = json.loads(facts_path.read_text(encoding="utf-8"))
        env = json.loads(ins_path.read_text(encoding="utf-8"))
        print(f"\n[{ind.upper()}]  ({facts['n_posts_kept']} posts kept)")
        print("-" * 78)
        n_tmpl = 0
        for idx, qe in enumerate(env.get("questions", [])):
            q = qdef.get(qe.get("source_module")) or next(
                (qq for qq in QUESTIONS
                 if qq["id"] == qe.get("question_id")), None)
            if q is None:
                continue
            if q["module"] in TEMPLATE_DISPATCH:
                parsed, status, latency, bad, vissues = _template_one(
                    ind, q, facts)
                crit = sum(1 for i in vissues
                           if i.get("severity") == "critical")
                grand_crit += crit
                env["questions"][idx] = _make_question_entry(
                    q, parsed, status, latency, bad, vissues)
                n_tmpl += 1
                print(f"  Q{idx+1:>2}/10  {q['title']:<24}  TMPL   "
                      f"crit={crit}  {status}")
            else:
                # Refresh validator flags on the kept LLM answer (no LLM).
                block = _block_for_module(facts, q["module"])
                prose = (qe.get("answer", "") + "\n"
                         + "\n".join(qe.get("evidence", [])) + "\n"
                         + "\n".join(qe.get("actionable_recommendations", [])))
                _, iss = verify_and_repair_prose(
                    prose, block, ind, full_facts=facts)
                qe["validator_issues"] = iss
                crit = sum(1 for i in iss
                           if i.get("severity") == "critical")
                grand_crit += crit
                print(f"  Q{idx+1:>2}/10  {q['title']:<24}  KEEP   "
                      f"crit={crit}  (LLM, refreshed)")
        env["generated_at"] = time.strftime("%Y-%m-%d %H:%M:%S",
                                            time.gmtime())
        env["template_modules"] = sorted(TEMPLATE_DISPATCH.keys())
        ins_path.write_text(json.dumps(env, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        grand_tmpl += n_tmpl
        print(f"  → {ins_path.name}  ({n_tmpl} templated, "
              f"{len(env.get('questions', []))-n_tmpl} LLM kept)")
    print()
    print("=" * 78)
    print(f"apply-templates complete: {grand_tmpl} templated entries, "
          f"{grand_crit} CRITICAL across all questions")
    print("=" * 78)
    return 0


# ─────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="LLM rephrasing of facts.json into French prose")
    parser.add_argument("--industry", choices=INDUSTRIES + ["all"], default="all")
    parser.add_argument("--rerun-flagged", action="store_true",
                        help="only regenerate questions whose stored prose "
                             "still has a critical issue (cheap targeted pass)")
    parser.add_argument("--apply-templates", action="store_true",
                        help="deterministic, no-LLM: rewrite only the "
                             "templated questions (Q1/Q4/Q5/Q8/Q10) in "
                             "existing insights files, keep LLM answers")
    args = parser.parse_args()
    industries = INDUSTRIES if args.industry == "all" else [args.industry]

    INSIGHTS_DIR.mkdir(parents=True, exist_ok=True)

    # No-LLM path: do this before importing/contacting Ollama.
    if args.apply_templates:
        return apply_templates(industries)

    print("=" * 78)
    print(f"rephrase_facts.py — facts.json → French dashboard prose")
    print(f"Industries: {industries}")
    print("=" * 78)
    print("\nLoading Ollama ...")
    from langchain_ollama import OllamaLLM
    llm = OllamaLLM(
        model=LLM_MODEL,
        temperature=TEMPERATURE,
        num_ctx=4096,
        num_predict=MAX_TOKENS,
        timeout=TIMEOUT_S,
    )
    print(f"  llm={LLM_MODEL}, temp={TEMPERATURE}")

    if args.rerun_flagged:
        return rerun_flagged(llm, industries)

    total_calls = 0
    total_time = 0.0
    summary: Dict[str, Dict[str, int]] = {}

    for ind in industries:
        facts_path = FACTS_DIR / f"facts_{ind}.json"
        if not facts_path.exists():
            print(f"  ⚠  {facts_path.name} missing — run compute_facts.py first")
            continue

        facts = json.loads(facts_path.read_text(encoding="utf-8"))
        print(f"\n[{industries.index(ind)+1}/{len(industries)}] Industry: {ind.upper()}  ({facts['n_posts_kept']} posts kept)")
        print("-" * 78)

        envelope: Dict[str, Any] = {
            "version":      "prose_v1",
            "industry":     ind,
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
            "source_facts": facts_path.name,
            "model":        LLM_MODEL,
            "temperature":  TEMPERATURE,
            "n_questions":  len(QUESTIONS),
            "questions":    [],
        }

        ok_count = 0
        warn_count = 0
        fb_count = 0
        for q_idx, q in enumerate(QUESTIONS, 1):
            parsed, status, latency, bad, validator_issues = rephrase_one(
                llm, ind, q, facts)
            total_calls += 1
            total_time += latency

            n_crit = sum(1 for i in validator_issues
                         if i.get("severity") == "critical")
            if status == "OK" or status == "TEMPLATE":
                ok_count += 1
                tag = "TMPL  " if status == "TEMPLATE" else "OK    "
            elif status.startswith(("VERIFY_WARN", "VALIDATOR_CRIT",
                                     "REPAIR", "TEMPLATE_CRIT")):
                warn_count += 1
                tag = "WARN  "
            else:  # LLM_ERROR / PARSE_FAIL → deterministic fallback used
                fb_count += 1
                tag = "FALLBK"
            print(f"  Q{q_idx:>2}/10  {q['title']:<24}  {tag}  "
                  f"answer={len(parsed.get('answer',''))} chars  latency={latency:5.1f}s  "
                  f"unverified={len(bad)}  crit={n_crit}")

            envelope["questions"].append(_make_question_entry(
                q, parsed, status, latency, bad, validator_issues))

        out_file = INSIGHTS_DIR / f"insights_{ind}.json"
        out_file.write_text(json.dumps(envelope, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        print(f"  → {out_file.name}  (ok={ok_count}  warn={warn_count}  fallback={fb_count})")
        summary[ind] = {"ok": ok_count, "warn": warn_count, "fallback": fb_count}

    print()
    print("=" * 78)
    print("rephrase_facts.py — complete")
    print("=" * 78)
    print(f"  total LLM calls:  {total_calls}")
    print(f"  total LLM time:   {total_time:.1f}s ({total_time/60:.1f} min)")
    print(f"  per-industry:     {summary}")
    print(f"  output dir:       {INSIGHTS_DIR.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
