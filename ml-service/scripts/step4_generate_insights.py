"""Step 4e — Generate RAG insights using Llama 3.1 + Chroma DB.

For each of 5 industries, asks 5 strategic questions to a RAG chain.
Each question retrieves top-5 documents from Chroma DB and Llama 3.1
generates 5 structured insights in JSON.

Output: data/step4/insights/insights_<industry>.json (5 files)
Total: 25 questions x 5 insights = 125 structured insights
"""
from __future__ import annotations
import os
# Required BEFORE chromadb import
os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

import json
import sys
import time
from pathlib import Path

import torch  # noqa: F401

sys.stdout.reconfigure(encoding="utf-8")

CHROMA_DIR = Path("data/step4/chroma_db")
OUT_DIR = Path("data/step4/insights")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ---- Industries + Questions ----
INDUSTRIES = ["hotels", "restaurants", "beauty", "fashion", "patisserie"]

QUESTIONS = [
    {
        "id": "Q1_top_insights",
        "title": "Top 5 actionable marketing insights",
        "template": "What are the top 5 actionable marketing insights for the {industry} industry on Instagram in Tunisia, based on the data? Include specific numbers and percentages where possible."
    },
    {
        "id": "Q2_content_type",
        "title": "Best content type",
        "template": "Which content type (Reel, Carousel, Photo) performs best for {industry} in Tunisia, and why? Provide concrete engagement numbers and explain the gap between formats."
    },
    {
        "id": "Q3_timing",
        "title": "Optimal posting times",
        "template": "What are the optimal posting times and frequency for {industry} brands in Tunisia? Cite specific hours, days of week, and posting cadence based on the engagement data."
    },
    {
        "id": "Q4_seasonal",
        "title": "Seasonal moments and hashtags",
        "template": "Which seasonal moments (Ramadan, Eid, Valentine's Day, summer, winter) and which hashtags drive the highest engagement for {industry} in Tunisia? Provide concrete examples from the data."
    },
    {
        "id": "Q5_mistakes",
        "title": "Common mistakes to avoid",
        "template": "Based on the data, what are the common mistakes brands make in {industry} on Instagram in Tunisia? What patterns do underperforming posts share? How can these mistakes be avoided?"
    },
]

# ---- System Prompt ----
SYSTEM_PROMPT = """You are an expert digital marketing analyst specialized in the Tunisian market. You analyze Instagram engagement data to provide ACTIONABLE insights for businesses.

You have access to data from 41 Tunisian brands across 5 industries (hotels, restaurants, beauty, fashion, patisserie). Your insights are based on:
- 4087 Instagram posts analyzed
- 21 thematic clusters (BERTopic)
- Random Forest V3 ML model (R2=0.3656, Spearman rho=0.6515)
- SHAP feature importance analysis

INSTRUCTIONS:
1. Base ALL insights ONLY on the provided context documents.
2. Be SPECIFIC: cite numbers, percentages, hours, days, brand names when available.
3. Be ACTIONABLE: each insight should lead to a concrete marketing decision.
4. Be CONCISE: each insight title is max 8 words, content is 2-3 sentences.
5. Output format: STRICT JSON as specified in the user prompt.
6. NEVER hallucinate facts not present in the context.
"""

USER_PROMPT_TEMPLATE = """CONTEXT (top 5 retrieved documents):
{context}

QUESTION: {question}

Generate exactly 5 structured insights in JSON format. Use this EXACT structure:

```json
{{
  "insights": [
    {{
      "title": "Short actionable title (max 8 words)",
      "content": "Detailed insight with specific numbers, percentages, or examples. 2-3 sentences max.",
      "evidence": "Reference to specific documents from context (e.g., 'industry_hotels_summary, ml_temporal_insight')"
    }},
    ... (4 more insights)
  ]
}}
```

Output ONLY the JSON, no preamble, no explanation. Start with {{ and end with }}."""


def format_context(docs):
    """Format retrieved documents as numbered list for the prompt."""
    parts = []
    for i, doc in enumerate(docs, 1):
        doc_id = doc.metadata.get("id", "?")
        doc_type = doc.metadata.get("type", "?")
        content = doc.page_content
        parts.append(f"[Doc {i}] (id={doc_id}, type={doc_type})\n{content}")
    return "\n\n".join(parts)


def parse_llm_response(response_text):
    """Extract JSON from LLM response, handling code fences and preamble."""
    text = response_text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
    if text.endswith("```"):
        text = text[:text.rfind("```")]
    text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start:end + 1]
    return json.loads(text)


# ---- Main pipeline ----
print("=" * 80)
print("Step 4e - RAG Insights Generation")
print("=" * 80)
print()

print("[Setup] Loading Chroma DB + Llama 3.1...")
t0 = time.perf_counter()

from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_ollama import OllamaLLM

embeddings = HuggingFaceEmbeddings(
    model_name="paraphrase-multilingual-MiniLM-L12-v2",
    model_kwargs={"device": "cpu"},
    encode_kwargs={"normalize_embeddings": True},
)

vectorstore = Chroma(
    persist_directory=str(CHROMA_DIR),
    embedding_function=embeddings,
    collection_name="rag_documents",
)

llm = OllamaLLM(
    model="llama3.1:latest",
    temperature=0.3,
    num_ctx=8192,
    num_predict=1500,
)

setup_time = time.perf_counter() - t0
print(f"      Chroma + Llama loaded in {setup_time:.1f}s")
print(f"      Documents in Chroma: {vectorstore._collection.count()}")
print()

total_calls = 0
total_llm_time = 0.0
all_results = {}

for ind_idx, industry in enumerate(INDUSTRIES, 1):
    print(f"[{ind_idx}/{len(INDUSTRIES)}] Industry: {industry.upper()}")
    print("-" * 80)

    industry_results = {
        "industry": industry,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "model": "llama3.1:latest",
        "temperature": 0.3,
        "questions": []
    }

    for q_idx, q in enumerate(QUESTIONS, 1):
        question_text = q["template"].format(industry=industry)
        print(f"  Q{q_idx}/5: {q['title']}")

        t_retrieve = time.perf_counter()
        retrieved_docs = vectorstore.similarity_search(question_text, k=5)
        retrieve_time = time.perf_counter() - t_retrieve
        retrieved_ids = [d.metadata.get("id", "?") for d in retrieved_docs]
        print(f"        Retrieved 5 docs in {retrieve_time*1000:.0f}ms: {retrieved_ids}")

        context = format_context(retrieved_docs)
        user_prompt = USER_PROMPT_TEMPLATE.format(context=context, question=question_text)
        full_prompt = f"{SYSTEM_PROMPT}\n\n{user_prompt}"

        t_llm = time.perf_counter()
        try:
            response = llm.invoke(full_prompt)
            llm_time = time.perf_counter() - t_llm
            total_calls += 1
            total_llm_time += llm_time

            try:
                parsed = parse_llm_response(response)
                insights = parsed.get("insights", [])
                status = "OK"
            except json.JSONDecodeError as e:
                insights = []
                status = f"JSON_PARSE_ERROR: {e}"
                print(f"        WARNING: JSON parse failed, raw response saved")

            print(f"        LLM generated {len(insights)} insights in {llm_time:.1f}s [{status}]")

            industry_results["questions"].append({
                "question_id": q["id"],
                "question_title": q["title"],
                "question_text": question_text,
                "retrieved_docs": retrieved_ids,
                "insights": insights,
                "raw_response": response if status != "OK" else None,
                "status": status,
                "latency_seconds": round(llm_time, 2),
            })
        except Exception as e:
            print(f"        ERROR: {e}")
            industry_results["questions"].append({
                "question_id": q["id"],
                "question_title": q["title"],
                "question_text": question_text,
                "retrieved_docs": retrieved_ids,
                "insights": [],
                "status": f"LLM_ERROR: {e}",
                "latency_seconds": 0,
            })

    out_file = OUT_DIR / f"insights_{industry}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(industry_results, f, indent=2, ensure_ascii=False)
    print(f"  Saved: {out_file}")
    print()

    all_results[industry] = industry_results

print("=" * 80)
print("Step 4e - Generation Complete")
print("=" * 80)
print(f"Total industries processed : {len(INDUSTRIES)}")
print(f"Total LLM calls            : {total_calls}")
print(f"Total LLM time             : {total_llm_time:.1f}s ({total_llm_time/60:.1f}min)")
print(f"Average per call           : {total_llm_time/max(total_calls,1):.1f}s")
print()
print("Per-industry summary:")
for ind in INDUSTRIES:
    res = all_results[ind]
    n_questions = len(res["questions"])
    n_ok = sum(1 for q in res["questions"] if q["status"] == "OK")
    total_insights = sum(len(q["insights"]) for q in res["questions"])
    print(f"  {ind:<14} : {n_ok}/{n_questions} questions OK, {total_insights} insights generated")

print()
print(f"Output files in: {OUT_DIR}")
for ind in INDUSTRIES:
    f = OUT_DIR / f"insights_{ind}.json"
    if f.exists():
        print(f"  {f.name}  ({f.stat().st_size / 1024:.1f} KB)")
