"""Step 4f V6 — Generate 50 V6 insights via Llama 3.1 + Chroma.

10 questions × 5 industries = 50 LLM calls. For each question we:
  1. Retrieve top-K relevant docs from the V6 Chroma store (k=10).
  2. Build a strict-JSON prompt asking for:
       - answer:       single-paragraph synthesised answer
       - evidence[]:   3-5 concrete data citations from the docs
       - actionable_recommendations[]: 3-5 specific marketing actions
       - ml_evidence:  one-line tie-in to V6/SHAP findings
  3. Parse the JSON, validate, fall back to a deterministic structure on
     parse failure.

The output keeps the existing envelope shape (so the live backend
controller still works) and *extends* each question item with the new
fields. For backwards compatibility with the existing frontend, we
also synthesise an `insights[]` array (one item per recommendation +
one per evidence point capped at 5).

Outputs:
  data/step4f_v6/insights/insights_<industry>.json   (5 files, V6 envelope)
"""
from __future__ import annotations

import os
os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

import json
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
TIMEOUT_S = 180

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
            "What POST CHARACTERISTICS most strongly predict high engagement in {industry}? "
            "Use the V6 stacking model (Ridge over RF V5c + XGB V5c, R²=0.4587, ρ=0.6686) "
            "and the XGB V5c SHAP analysis. List the top 10 predictive features, the "
            "direction of impact (positive / negative), and concrete examples of high-engagement "
            "posts that confirm the pattern."
        ),
    },
]

# ─────────────────────────────────────────────────────────────────────────
# Prompts
# ─────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are an expert digital marketing analyst specialising in the Tunisian Instagram market.
You analyse engagement data from 41 Tunisian brands across 5 industries (beauty, fashion, hotels, patisserie, restaurants), based on 4127 Instagram posts.

The data is enriched with:
- 21 BERTopic thematic clusters (multilingual: French, English, Arabic).
- CLIP visual embeddings (15 PCA components).
- mpnet caption-semantic embeddings (15 PCA components).
- V6 STACKING model: Ridge ensemble of RF V5c + XGB V5c, R²(log)=0.4587, Spearman ρ=0.6686.
- XGB V5c SHAP analysis is the primary interpretive lens for V6.

INSTRUCTIONS:
1. Base ALL claims ONLY on the provided context documents — never invent numbers, brand names, or hashtags.
2. Be SPECIFIC: cite numbers, percentages, hours, days, brand names, and document IDs.
3. Be ACTIONABLE: each recommendation must lead to a concrete marketing decision.
4. Be CONCISE but RICH: ~3-5 sentences for the answer, 3-5 items per list.
5. Output STRICTLY valid JSON in the schema provided in the user prompt — no preamble, no markdown fence.
"""

USER_PROMPT_TEMPLATE = """CONTEXT (top {k} retrieved documents from the V6 RAG store):
{context}

QUESTION: {question}

Produce a JSON object with EXACTLY this schema:
{{
  "answer": "3-5 sentence synthesised answer that directly answers the question, citing specific numbers and patterns from the context",
  "evidence": [
    "concrete data point #1 with numbers and document reference",
    "concrete data point #2",
    "concrete data point #3"
  ],
  "actionable_recommendations": [
    "specific marketing action #1 (concrete: format X at hour Y, hashtag #Z, etc.)",
    "specific marketing action #2",
    "specific marketing action #3"
  ],
  "ml_evidence": "one short sentence tying the answer to V6 SHAP / stacking findings (cite specific feature names like clip_pcXX, doc_pcXX, brand_engagement_rate, etc.)"
}}

Output ONLY the JSON, starting with {{ and ending with }}. No preamble, no code fence, no comments."""


# ─────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────

def format_context(docs) -> str:
    parts = []
    for i, doc in enumerate(docs, 1):
        doc_id = doc.metadata.get("id", "?")
        doc_type = doc.metadata.get("type", "?")
        content = doc.page_content
        # Truncate per-doc to keep prompt size reasonable
        if len(content) > 1500:
            content = content[:1500] + " …(truncated)"
        parts.append(f"[Doc {i}] (id={doc_id}, type={doc_type})\n{content}")
    return "\n\n".join(parts)


def parse_llm_response(text: str) -> Dict[str, Any] | None:
    if not isinstance(text, str):
        return None
    s = text.strip()
    if s.startswith("```"):
        # strip ``` or ```json fences
        s = s.split("```", 2)[1]
        if s.startswith("json"):
            s = s[4:]
    if s.endswith("```"):
        s = s[: s.rfind("```")]
    s = s.strip()
    a = s.find("{"); b = s.rfind("}")
    if a < 0 or b <= a:
        return None
    try:
        return json.loads(s[a:b + 1])
    except json.JSONDecodeError:
        return None


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
    print("=" * 78)
    print("Step 4f V6 — Generate 50 insights via Llama 3.1 + Chroma")
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

    for ind_idx, industry in enumerate(INDUSTRIES, 1):
        print(f"\n[{ind_idx}/{len(INDUSTRIES)}] Industry: {industry.upper()}")
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

            t_r = time.perf_counter()
            retrieved = vs.similarity_search(qtext, k=RETRIEVAL_K)
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
