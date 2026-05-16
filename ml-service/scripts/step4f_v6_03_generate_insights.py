"""Step 4f V6 — RAG + LLM legacy generator (NO LONGER IN STEP 4 CRITICAL PATH).

DEPRECATED FOR STEP 4 — DO NOT WIRE INTO THE DASHBOARD PIPELINE.

Step 4 insight generation is now deterministic and goes through two
scripts that do NOT touch Chroma:

    scripts/compute_facts.py     — pandas → data/step4f_v6/facts/facts_<industry>.json
    scripts/rephrase_facts.py    — LLM rephrases facts.json into French prose

This file is kept on disk for a different future use case ("free-form
RAG QA" on the dashboard, where the user types a question and the LLM
answers using Chroma retrieval). It is NOT called by any backend
controller for the 10 fixed dashboard modules.

Reason for the move: this generator asked an LLM to PRODUCE numbers
from retrieved Markdown docs. That recycled numbers across modules,
confused volume % with engagement %, and recommended outlier giveaway
posts as patterns. The fix was architectural — separate calculation
(Python) from writing (LLM). See PFE_RECAP_COMPLET.md and the audit
in conversation log "Technical Description Request — Insights
Pipeline (Step 4)" for the full history.

Original behaviour (retained below for the QA-feature reuse):
  10 questions × N industries = N×10 LLM calls. For each question we:
    1. Retrieve top-K relevant docs from the V6 Chroma store (k=10),
       filtered by industry metadata so cross-industry docs are excluded.
    2. Build a strict-JSON prompt in French asking for:
         - answer:       single-paragraph synthesised answer (French)
         - evidence[]:   3-5 concrete data citations from the docs
         - actionable_recommendations[]: 3-5 specific marketing actions
         - ml_evidence:  one-line tie-in to V6/SHAP findings
    3. Parse the JSON, validate, fall back to a deterministic structure
       on parse failure.

Usage (legacy / QA feature only):
  python step4f_v6_03_generate_insights.py              # all 5 industries
  python step4f_v6_03_generate_insights.py --industry fashion

Outputs:
  data/step4f_v6/insights/insights_<industry>.json
  (NOTE: rephrase_facts.py writes to the SAME path with a different
   internal schema. Running this legacy script overwrites the
   deterministic prose with the old RAG/LLM output — do not do this
   in production.)
"""
from __future__ import annotations

import argparse
import os
os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

import torch  # noqa: F401  -- Windows DLL ordering

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
CHROMA_DIR = ROOT / "data" / "step4f_v6" / "chroma_db"
OUT_DIR    = ROOT / "data" / "step4f_v6" / "insights"
OUT_DIR.mkdir(parents=True, exist_ok=True)

INDUSTRIES = ["beauty", "fashion", "hotels", "patisserie", "restaurants"]
RETRIEVAL_K = 10
LLM_MODEL = "llama3.1:latest"
TEMPERATURE = 0.3
MAX_TOKENS = 1500
# Q10 (Performance Predictors) was hitting the previous 180s ceiling and
# triggering the deterministic fallback. Bump to 300s; Q10 prompt is also
# shortened below to reduce decoded tokens.
TIMEOUT_S = 300

# ─────────────────────────────────────────────────────────────────────────
# 10 NEW QUESTIONS
# ─────────────────────────────────────────────────────────────────────────

QUESTIONS: List[Dict[str, str]] = [
    {
        "id": "Q1_content_strategy",
        "title": "Content Strategy",
        "template": (
            "What are the TOP 3 content patterns that drive engagement for {industry} "
            "in Tunisia? Provide specific examples of caption styles, visual themes, "
            "and hashtag combinations, with engagement metrics."
        ),
    },
    {
        "id": "Q2_optimal_timing",
        "title": "Optimal Timing",
        "template": (
            "What is the OPTIMAL posting schedule for {industry} in Tunisia? "
            "Provide: best 3 days of the week with engagement evidence, "
            "best 3 hours of the day with engagement evidence, "
            "and a posting frequency recommendation."
        ),
    },
    {
        "id": "Q3_visual_strategy",
        "title": "Visual Strategy",
        "template": (
            "What VISUAL ELEMENTS drive engagement for {industry} in Tunisia? "
            "Address: composition styles (close-up vs lifestyle vs product shot), "
            "photo / reel / carousel / video performance ratio, "
            "and the optimal carousel slide count."
        ),
    },
    {
        "id": "Q4_content_themes",
        "title": "Content Themes",
        "template": (
            "What are the top 5 CONTENT THEMES that resonate with the {industry} "
            "audience in Tunisia? Use the BERTopic clusters from the documents and "
            "provide engagement metrics per theme."
        ),
    },
    {
        "id": "Q5_hashtag_strategy",
        "title": "Hashtag Strategy",
        "template": (
            "What is the OPTIMAL HASHTAG STRATEGY for {industry} in Tunisia? "
            "Cover: optimal number of hashtags (range with evidence), "
            "the mix of broad / niche / branded (% breakdown), "
            "the top 10 specific hashtags with engagement data, "
            "and a trending vs evergreen analysis."
        ),
    },
    {
        "id": "Q6_brand_differentiation",
        "title": "Brand Differentiation",
        "template": (
            "How can a NEW {industry} brand DIFFERENTIATE from current competitors in "
            "Tunisia? Identify gaps in current content strategies, underserved themes "
            "or formats, and emerging opportunities."
        ),
    },
    {
        "id": "Q7_calendar_strategy",
        "title": "30-day Calendar Strategy",
        "template": (
            "For a 30-DAY Instagram CAMPAIGN in {industry} in Tunisia, what is optimal? "
            "Address: posting cadence (per week, per day), "
            "content mix ratio (photo/reel/carousel/story in %), "
            "theme rotation schedule, "
            "and engagement progression strategy week by week."
        ),
    },
    {
        "id": "Q8_engagement_tactics",
        "title": "Engagement Tactics",
        "template": (
            "What SPECIFIC TACTICS drive comments / saves / shares in {industry} in Tunisia? "
            "Cover: caption hooks that work, call-to-action patterns, story arc structures, "
            "and user-generated content strategies."
        ),
    },
    {
        "id": "Q9_current_trends",
        "title": "Current Trends",
        "template": (
            "What are CURRENT TRENDS in {industry} on Instagram Tunisia? "
            "Cover: emerging topics from the BERTopic temporal analysis, "
            "viral content patterns, seasonal opportunities (Ramadan/Eid/summer), "
            "and cultural moments to leverage."
        ),
    },
    {
        "id": "Q10_performance_predictors",
        "title": "Performance Predictors",
        "template": (
            "From the V6 SHAP analysis, what are the TOP 5 features that predict "
            "engagement for {industry}? For each: name the feature, the direction "
            "of impact (+/-), and one concrete example post."
        ),
    },
]

# ─────────────────────────────────────────────────────────────────────────
# Prompts
# ─────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """Tu es un expert en marketing digital tunisien.
Réponds TOUJOURS en français.
Ne mélange JAMAIS l'anglais et le français.
Cite toujours des chiffres précis depuis les documents.

Tu analyses des données d'engagement de 41 marques tunisiennes dans 5 secteurs (beauté, mode, hôtels, pâtisserie, restauration), basées sur 4127 posts Instagram.

Les données incluent :
- 21 clusters thématiques BERTopic (multilingues : français, anglais, arabe).
- Embeddings visuels CLIP (15 composantes PCA).
- Embeddings sémantiques mpnet des légendes (15 composantes PCA).
- Modèle V6 STACKING : Ridge ensemble de RF V5c + XGB V5c, R²(log)=0.4587, ρ de Spearman=0.6686.
- L'analyse SHAP de XGB V5c est la principale lentille d'interprétation pour V6.

INSTRUCTIONS :
1. Base TOUTES les affirmations UNIQUEMENT sur les documents de contexte fournis — n'invente JAMAIS de chiffres, noms de marques ou hashtags.
2. Sois PRÉCIS : cite des chiffres, pourcentages, heures, jours, noms de marques et IDs de documents.
3. Sois ACTIONNABLE : chaque recommandation doit mener à une décision marketing concrète.
4. Sois CONCIS : 2-3 phrases pour la réponse, exactement 3 éléments par liste.
5. JAMAIS de JSON, JAMAIS d'accolades, JAMAIS de guillemets — texte structuré uniquement.

RÈGLES DE BON SENS :
- Fréquence maximale = 1 post par jour (7 posts/semaine max)
- Carousel : maximum 7 slides
- Ne mélange JAMAIS les industries — utilise uniquement les données du secteur demandé
- Vérifie que les hashtags recommandés appartiennent au bon secteur
"""

USER_PROMPT_TEMPLATE = """CONTEXTE (top {k} documents récupérés depuis le store RAG V6, filtrés pour le secteur concerné) :
{context}

QUESTION : {question}

Génère ta réponse avec EXACTEMENT cette structure. NE PRODUIS JAMAIS DE JSON, JAMAIS D'ACCOLADES.

RÉPONSE :
Réponds en 2-3 phrases courtes en français.
Cite des chiffres précis et des brands tunisiennes réelles.
JAMAIS de JSON ou de code.
JAMAIS d'anglais.

PREUVES :
Génère exactement 3 preuves chiffrées.
Format STRICT :
- [Fait précis] : [chiffre]% — Source : [nom du document]
- [Fait précis] : [chiffre]% — Source : [nom du document]
- [Fait précis] : [chiffre]% — Source : [nom du document]

Règles :
- JAMAIS de JSON
- Chiffres tirés UNIQUEMENT des documents fournis (ne JAMAIS inventer)

RECOMMANDATIONS :
Génère exactement 3 recommandations concrètes.
Format STRICT — une ligne par recommandation :
1. [Action précise] — [chiffre exact]% d'engagement — Exemple : [nom brand tunisienne]
2. [Action précise] — [chiffre exact]% d'engagement — Exemple : [nom brand tunisienne]
3. [Action précise] — [chiffre exact]% d'engagement — Exemple : [nom brand tunisienne]

Règles :
- Commence chaque ligne par un verbe d'action
- Cite UNIQUEMENT des chiffres présents dans les documents (ne JAMAIS inventer)
- Cite UNIQUEMENT des brands tunisiennes réelles
- Maximum 15 mots par recommandation
- JAMAIS de JSON, JAMAIS d'accolades, JAMAIS de guillemets

ML :
[Une phrase courte sur les features SHAP V6 les plus importantes pour ce secteur : clip_pcXX, doc_pcXX, brand_engagement_rate...]"""


# ─────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────

# Counter incremented each time we redact a >300% value. After the
# ×100 display-formatter bug was fixed (see step4f_v6_01_build_documents.py
# _eng_str), no doc should ever contain a value above 300%, so this should
# stay at 0. We keep the filter wired in as a belt-and-braces safety net
# but log the count at the end of generation — if it ever rises, somebody
# has re-introduced an upstream inflation bug.
HIGH_ENGAGEMENT_REDACTION_COUNT = 0


def _filter_high_engagement(text: str) -> str:
    """Replace any engagement percentage > 300 with a neutral placeholder.
    Now defensive-only: with the display formatter fixed this should
    never trigger."""
    def _replace(m: re.Match) -> str:
        global HIGH_ENGAGEMENT_REDACTION_COUNT
        raw = m.group(1).replace(',', '.')
        try:
            val = float(raw)
        except ValueError:
            return m.group(0)
        if val > 300:
            HIGH_ENGAGEMENT_REDACTION_COUNT += 1
            return "[valeur exceptionnelle exclue]"
        return m.group(0)
    return re.sub(r'(\d+(?:[.,]\d+)?)\s*%', _replace, text)


def format_context(docs) -> str:
    parts = []
    for i, doc in enumerate(docs, 1):
        doc_id = doc.metadata.get("id", "?")
        doc_type = doc.metadata.get("type", "?")
        content = doc.page_content
        # Remove outlier engagement values before they reach the LLM
        content = _filter_high_engagement(content)
        # Truncate per-doc to keep prompt size reasonable
        if len(content) > 1500:
            content = content[:1500] + " …(truncated)"
        parts.append(f"[Doc {i}] (id={doc_id}, type={doc_type})\n{content}")
    return "\n\n".join(parts)


def _parse_plain(s: str) -> Dict[str, Any] | None:
    """Parse RÉPONSE/PREUVES/RECOMMANDATIONS/ML sections.
    Falls back to heuristic extraction when headers are absent."""

    def extract_section(header: str) -> str:
        m = re.search(
            rf'{re.escape(header)}\s*\n(.*?)(?=\n[A-ZÉÈÊËÀÂÙÛÇ][A-ZÉÈÊËÀÂÙÛÇ\w\s]+\s*:\s*\n|\Z)',
            s, re.DOTALL | re.IGNORECASE,
        )
        return m.group(1).strip() if m else ""

    def extract_numbered(text: str) -> List[str]:
        return [
            m.group(1).strip()
            for ln in text.splitlines()
            for m in (re.match(r'^\d+[\.\)]\s+(.+)', ln.strip()),)
            if m and len(m.group(1)) > 8
        ]

    def extract_bullets(text: str) -> List[str]:
        # Skip lines that are clearly instruction/rule text
        _skip = re.compile(r'^(JAMAIS|Commence|Cite|Maximum|Format|Règles?|Instructions?)',
                           re.IGNORECASE)
        return [
            ln.lstrip("•·- ").strip()
            for ln in text.splitlines()
            if re.match(r'^\s*[-•·]', ln) and len(ln.strip()) > 8
            and not _skip.match(ln.lstrip("•·- ").strip())
        ]

    # ── Strict parse: section headers present ─────────────────────────────
    answer       = extract_section("RÉPONSE :")
    evidence_blk = extract_section("PREUVES :")
    recs_blk     = extract_section("RECOMMANDATIONS :")
    ml_blk       = extract_section("ML :")

    evidence = extract_bullets(evidence_blk)
    recs     = extract_numbered(recs_blk)
    ml       = ml_blk.splitlines()[0].strip() if ml_blk else ""

    # ── Lenient parse: no headers found — mine the raw text ───────────────
    if not answer:
        paragraphs = [p.strip() for p in re.split(r'\n\s*\n', s) if p.strip()]
        answer = paragraphs[0] if paragraphs else ""

    if not recs:
        recs = extract_numbered(s)

    if not evidence:
        evidence = extract_bullets(s)

    if not answer or not recs:
        return None

    return {
        "answer": answer,
        "evidence": evidence or ([evidence_blk] if evidence_blk else []),
        "actionable_recommendations": recs,
        "ml_evidence": ml,
    }


def parse_llm_response(text: str) -> Dict[str, Any] | None:
    if not isinstance(text, str) or len(text.strip()) < 20:
        return None
    s = text.strip()

    # Strip markdown fences
    if s.startswith("```"):
        s = re.sub(r'^```\w*\n?', '', s)
        s = re.sub(r'\n?```\s*$', '', s)
        s = s.strip()

    # Plain-text format (preferred)
    if re.search(r'RÉPONSE\s*:|PREUVES\s*:|RECOMMANDATIONS\s*:', s, re.IGNORECASE):
        result = _parse_plain(s)
        if result:
            return result

    # Fallback: LLM ignored the instruction and returned JSON anyway
    a = s.find("{"); b = s.rfind("}")
    if a >= 0 and b > a:
        try:
            return json.loads(s[a:b + 1])
        except json.JSONDecodeError:
            pass

    # Last resort: try plain parse on whatever text came back
    return _parse_plain(s)


def synth_legacy_insights(parsed: Dict[str, Any]) -> List[Dict[str, str]]:
    """Build a backwards-compat `insights[]` array from the new structure
    so the existing frontend (which renders `insights`) still works."""
    out: List[Dict[str, str]] = []
    for rec in (parsed.get("actionable_recommendations") or [])[:5]:
        if isinstance(rec, str) and rec.strip():
            words = rec.strip().split()
            title = " ".join(words[:8])
            out.append({
                "title": title,
                "content": rec.strip(),
                "evidence": "actionable_recommendations",
            })
    if not out:
        # fallback: convert evidence items into pseudo-insights
        for ev in (parsed.get("evidence") or [])[:5]:
            if isinstance(ev, str) and ev.strip():
                words = ev.strip().split()
                out.append({
                    "title": " ".join(words[:8]),
                    "content": ev.strip(),
                    "evidence": "evidence",
                })
    if not out and parsed.get("answer"):
        out.append({
            "title": "Synthesised answer",
            "content": parsed["answer"],
            "evidence": "answer",
        })
    return out


def deterministic_fallback(industry: str, q: Dict[str, str], retrieved_ids: List[str]) -> Dict[str, Any]:
    """If the LLM fails, return a minimal but valid V6 answer wrapper."""
    return {
        "answer": (
            f"Insight non disponible pour {industry} (LLM échec). Voir documents source : "
            f"{', '.join(retrieved_ids[:3])}. Re-générer manuellement avec scripts/step4f_v6_03_generate_insights.py."
        ),
        "evidence": retrieved_ids[:3],
        "actionable_recommendations": [
            f"Consulter {retrieved_ids[0]} pour le contexte direct." if retrieved_ids else "—",
            "Relancer le pipeline V6 quand Ollama est disponible.",
        ],
        "ml_evidence": "V6 stacking (Ridge over RF V5c + XGB V5c, R²=0.4587). Voir XGB V5c SHAP cache.",
    }


def validate_parsed(parsed: Dict[str, Any]) -> Tuple[bool, str]:
    if not isinstance(parsed, dict):
        return False, "not a dict"
    ans = parsed.get("answer")
    if not isinstance(ans, str) or len(ans.strip()) < 30:
        return False, f"answer too short ({len(ans) if isinstance(ans,str) else 0})"
    ev = parsed.get("evidence") or []
    if not (isinstance(ev, list) and len(ev) >= 1):
        return False, "evidence missing or empty"
    rec = parsed.get("actionable_recommendations") or []
    if not (isinstance(rec, list) and len(rec) >= 1):
        return False, "actionable_recommendations missing or empty"
    return True, ""


# ─────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="Generate V6 RAG insights")
    parser.add_argument(
        "--industry",
        choices=INDUSTRIES + ["all"],
        default="all",
        help="Industry to regenerate (default: all)",
    )
    args = parser.parse_args()
    industries_to_run = INDUSTRIES if args.industry == "all" else [args.industry]

    n_calls = len(QUESTIONS) * len(industries_to_run)
    print("=" * 78)
    print(f"Step 4f V6 — Generate {n_calls} insights via Llama 3.1 + Chroma")
    print(f"Industries : {industries_to_run}")
    print("=" * 78)

    print(f"\nLoading Chroma + Llama ...")
    t0 = time.perf_counter()
    from langchain_chroma import Chroma
    from langchain_huggingface import HuggingFaceEmbeddings
    from langchain_ollama import OllamaLLM

    embeddings = HuggingFaceEmbeddings(
        model_name="paraphrase-multilingual-MiniLM-L12-v2",
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )
    vs = Chroma(
        persist_directory=str(CHROMA_DIR),
        embedding_function=embeddings,
        collection_name="rag_documents_v6",
    )
    llm = OllamaLLM(
        model=LLM_MODEL,
        temperature=TEMPERATURE,
        num_ctx=8192,
        num_predict=MAX_TOKENS,
        timeout=TIMEOUT_S,
    )
    print(f"  Chroma + Llama ready in {time.perf_counter() - t0:.1f}s "
          f"(Chroma docs = {vs._collection.count()})")

    total_calls = 0
    total_llm_time = 0.0
    summary: Dict[str, Dict[str, int]] = {}

    for ind_idx, industry in enumerate(industries_to_run, 1):
        print(f"\n[{ind_idx}/{len(industries_to_run)}] Industry: {industry.upper()}")
        print("-" * 78)

        envelope = {
            "industry":      industry,
            "generated_at":  time.strftime("%Y-%m-%d %H:%M:%S"),
            "model":         LLM_MODEL,
            "model_version": "V6",
            "ml_model":      "V6 Ridge(RF V5c + XGB V5c), R²=0.4587, ρ=0.6686",
            "temperature":   TEMPERATURE,
            "n_questions":   len(QUESTIONS),
            "questions":     [],
        }
        ok_count = 0
        fb_count = 0

        for q_idx, q in enumerate(QUESTIONS, 1):
            qtext = q["template"].format(industry=industry)
            print(f"  Q{q_idx:>2}/10  {q['title']}")

            # FIX 2 — filter by industry so cross-industry docs never appear
            industry_filter = {
                "$or": [
                    {"industry": {"$eq": industry}},
                    {"industry_dominant": {"$eq": industry}},
                    {"type": {"$eq": "ml_insight"}},
                ]
            }
            t_r = time.perf_counter()
            retrieved = vs.similarity_search(qtext, k=RETRIEVAL_K, filter=industry_filter)
            r_time = time.perf_counter() - t_r
            r_ids = [d.metadata.get("id", "?") for d in retrieved]
            print(f"        retrieved {len(retrieved)} docs ({r_time*1000:.0f} ms)")

            ctx = format_context(retrieved)
            user_prompt = USER_PROMPT_TEMPLATE.format(
                k=RETRIEVAL_K, context=ctx, question=qtext,
            )
            full = f"{SYSTEM_PROMPT}\n\n{user_prompt}"

            parsed: Dict[str, Any] | None = None
            llm_status = "OK"
            llm_time = 0.0
            try:
                t_l = time.perf_counter()
                resp = llm.invoke(full)
                llm_time = time.perf_counter() - t_l
                total_calls += 1; total_llm_time += llm_time
                parsed = parse_llm_response(resp)
                if parsed is None:
                    llm_status = "JSON_PARSE_ERROR"
                else:
                    ok, why = validate_parsed(parsed)
                    if not ok:
                        llm_status = f"VALIDATION_FAIL: {why}"
                        parsed = None
            except Exception as e:  # noqa: BLE001
                llm_status = f"LLM_ERROR: {e}"

            if parsed is None:
                parsed = deterministic_fallback(industry, q, r_ids)
                print(f"        ↩️  fallback ({llm_status}) — using deterministic answer")
                fb_count += 1
            else:
                print(f"        ✅ parsed in {llm_time:.1f}s — answer={len(parsed['answer'])} chars, "
                      f"evidence={len(parsed['evidence'])}, recs={len(parsed['actionable_recommendations'])}")
                ok_count += 1

            envelope["questions"].append({
                "question_id":              q["id"],
                "question_title":           q["title"],
                "question_text":            qtext,
                "retrieved_docs":           r_ids,
                # NEW V6 fields:
                "answer":                   parsed.get("answer", ""),
                "evidence":                 parsed.get("evidence", []),
                "actionable_recommendations": parsed.get("actionable_recommendations", []),
                "ml_evidence":              parsed.get("ml_evidence", ""),
                # Backwards-compat insights[] for the existing frontend:
                "insights":                 synth_legacy_insights(parsed),
                "status":                   llm_status,
                "latency_seconds":          round(llm_time, 2),
            })

        out_file = OUT_DIR / f"insights_{industry}.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(envelope, f, indent=2, ensure_ascii=False)
        size_kb = out_file.stat().st_size / 1024
        print(f"  ✅ saved {out_file.name}  ({size_kb:.1f} KB, {ok_count}/{len(QUESTIONS)} LLM-OK, "
              f"{fb_count} fallback)")
        summary[industry] = {"ok": ok_count, "fallback": fb_count}

    print()
    print("=" * 78)
    print("V6 insights generation complete")
    print("=" * 78)
    print(f"  total LLM calls:  {total_calls}")
    print(f"  total LLM time:   {total_llm_time:.1f}s ({total_llm_time/60:.1f} min)")
    print(f"  avg per call:     {total_llm_time/max(total_calls,1):.1f}s")
    print()
    print(f"  per-industry: {summary}")
    print(f"  output dir:   {OUT_DIR.relative_to(ROOT)}")
    # Defensive >300% redactions should now be 0; non-zero means an
    # upstream inflation bug has re-entered the pipeline.
    print(f"  >300% redactions in context (should be 0): {HIGH_ENGAGEMENT_REDACTION_COUNT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
