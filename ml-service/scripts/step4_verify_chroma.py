"""Step 4d verification — confirm Chroma DB persistence is intact for Step 4e."""
from __future__ import annotations
import os
os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

import json
import sys
from pathlib import Path

import torch  # noqa: F401  (Windows: torch before transformers/bertopic)

sys.stdout.reconfigure(encoding="utf-8")

CHROMA_DIR = Path("data/step4/chroma_db")
DOC_PATH = Path("data/step4/documents.json")

print("=" * 64)
print("CHROMA DB VERIFICATION")
print("=" * 64)

checks = {
    "chroma_dir_exists": False,
    "docs_json_exists": False,
    "chroma_reload": False,
    "doc_count_match": False,
    "query_returns_results": False,
    "metadata_integrity": False,
}

# ---- STEP 1: filesystem ----
print("\n[STEP 1] Filesystem check")
print("-" * 64)

checks["chroma_dir_exists"] = CHROMA_DIR.is_dir()
checks["docs_json_exists"] = DOC_PATH.is_file()

if checks["chroma_dir_exists"]:
    print(f"  data/step4/chroma_db/ exists")
    total_size = 0
    for p in sorted(CHROMA_DIR.rglob("*")):
        if p.is_file():
            sz = p.stat().st_size
            total_size += sz
            rel = p.relative_to(CHROMA_DIR)
            print(f"    {rel}  ({sz:,} bytes)")
    print(f"  Total chroma_db size: {total_size:,} bytes ({total_size/1024/1024:.2f} MB)")
else:
    print(f"  MISSING: {CHROMA_DIR}")

if checks["docs_json_exists"]:
    sz = DOC_PATH.stat().st_size
    print(f"  documents.json size: {sz:,} bytes ({sz/1024:.1f} KB)")
    with open(DOC_PATH, "r", encoding="utf-8") as f:
        raw_docs = json.load(f)
    print(f"  Number of documents in JSON: {len(raw_docs)}")
else:
    print(f"  MISSING: {DOC_PATH}")
    raw_docs = []

# ---- STEP 2: reload Chroma ----
print("\n[STEP 2] Reload Chroma DB")
print("-" * 64)

try:
    from langchain_chroma import Chroma
    from langchain_huggingface import HuggingFaceEmbeddings

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

    count = vectorstore._collection.count()
    print(f"  Chroma reloaded successfully")
    print(f"  Total documents in Chroma: {count}")
    print(f"  Expected: 182")
    checks["chroma_reload"] = True
    checks["doc_count_match"] = (count == 182)

    test_query = "What is the best content type for engagement?"
    print(f"\n  Quick test query: {test_query}")
    results = vectorstore.similarity_search(test_query, k=3)
    print(f"  Top-3 results:")
    for i, doc in enumerate(results, 1):
        t = doc.metadata.get("type", "?")
        did = doc.metadata.get("id", "?")
        print(f"    {i}. [{t:<20}] {did}")
        snippet = doc.page_content[:100].replace("\n", " ")
        print(f"       {snippet}...")
    checks["query_returns_results"] = len(results) > 0

    # ---- STEP 3: metadata integrity (topic_2_summary) ----
    print("\n[STEP 3] Metadata integrity for topic_2_summary")
    print("-" * 64)
    got = vectorstore.get(where={"id": "topic_2_summary"})
    ids = got.get("ids", [])
    metas = got.get("metadatas", [])
    docs = got.get("documents", [])

    if ids:
        md = metas[0]
        text_in_chroma = docs[0]
        json_doc = next((d for d in raw_docs if d["id"] == "topic_2_summary"), None)
        json_text = json_doc["text"] if json_doc else None

        print(f"  Found in Chroma: id={ids[0]}")
        print(f"  metadata.topic_id   = {md.get('topic_id')}   (expected 2)")
        print(f"  metadata.topic_name = {md.get('topic_name')!r}   (expected 'Ramadan Beauty Routine')")
        print(f"  text matches documents.json: {text_in_chroma == json_text}")

        ok = (
            md.get("topic_id") == 2
            and md.get("topic_name") == "Ramadan Beauty Routine"
            and text_in_chroma == json_text
        )
        checks["metadata_integrity"] = ok
    else:
        print("  topic_2_summary NOT found in Chroma")
except Exception as e:
    print(f"  ERROR while reloading Chroma: {type(e).__name__}: {e}")

# ---- STEP 4: verdict ----
print("\n" + "=" * 64)
print("VERDICT")
print("=" * 64)

def mark(ok: bool) -> str:
    return "[OK]" if ok else "[FAIL]"

print(f"  {mark(checks['chroma_dir_exists'])} data/step4/chroma_db/ exists")
print(f"  {mark(checks['docs_json_exists'])} data/step4/documents.json exists")
print(f"  {mark(checks['chroma_reload'])} Chroma reloaded successfully")
print(f"  {mark(checks['doc_count_match'])} Document count: 182 (matches expected)")
print(f"  {mark(checks['query_returns_results'])} Test query returns relevant results")
print(f"  {mark(checks['metadata_integrity'])} Metadata integrity preserved")

all_ok = all(checks.values())
print()
if all_ok:
    print("  VERDICT: READY for Step 4e")
else:
    print("  VERDICT: NEEDS RE-INDEXATION")
print("=" * 64)
