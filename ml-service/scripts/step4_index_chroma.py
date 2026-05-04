"""Step 4d — Index 182 RAG documents into Chroma vector store.

Uses paraphrase-multilingual-MiniLM-L12-v2 (384-dim) for multilingual
support (FR/EN/AR). Persists to data/step4/chroma_db/ for reuse in
Step 4e (RAG insights generation).
"""
from __future__ import annotations
import os
# Required BEFORE chromadb import (protobuf 7.x vs opentelemetry _pb2 mismatch)
os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

import json
import sys
import time
from pathlib import Path

# Order matters: torch before transformers/bertopic on Windows
import torch  # noqa: F401

sys.stdout.reconfigure(encoding="utf-8")

DOC_PATH = Path("data/step4/documents.json")
CHROMA_DIR = Path("data/step4/chroma_db")

print("=" * 80)
print("Step 4d — Chroma DB Indexation")
print("=" * 80)
print()

# ---- Load documents ----
print("[1/4] Loading documents...")
t0 = time.perf_counter()
with open(DOC_PATH, "r", encoding="utf-8") as f:
    raw_docs = json.load(f)
print(f"      Loaded {len(raw_docs)} documents from {DOC_PATH}")
print(f"      Latency: {time.perf_counter()-t0:.1f}s")
print()

# ---- Convert to LangChain Documents ----
from langchain_core.documents import Document

print("[2/4] Converting to LangChain Document format...")
t0 = time.perf_counter()

def sanitize_metadata(md: dict) -> dict:
    """Chroma allows only str/int/float/bool in metadata; coerce everything else."""
    clean = {}
    for k, v in md.items():
        if isinstance(v, (str, int, float, bool)):
            clean[k] = v
        elif v is None:
            clean[k] = "none"
        else:
            clean[k] = str(v)
    return clean

lc_docs = [
    Document(
        page_content=d["text"],
        metadata={
            "id": d["id"],
            "type": d["type"],
            **sanitize_metadata(d["metadata"]),
        }
    )
    for d in raw_docs
]
print(f"      Converted {len(lc_docs)} docs")
print(f"      Latency: {time.perf_counter()-t0:.1f}s")
print()

# ---- Initialize embeddings + Chroma ----
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma

print("[3/4] Initializing embeddings + indexing into Chroma...")
print(f"      Model: paraphrase-multilingual-MiniLM-L12-v2")
print(f"      Persist directory: {CHROMA_DIR}")
t0 = time.perf_counter()

embeddings = HuggingFaceEmbeddings(
    model_name="paraphrase-multilingual-MiniLM-L12-v2",
    model_kwargs={"device": "cpu"},
    encode_kwargs={"normalize_embeddings": True},
)

# Wipe existing chroma_db if present (fresh index each run)
if CHROMA_DIR.exists():
    import shutil
    shutil.rmtree(CHROMA_DIR)

vectorstore = Chroma.from_documents(
    documents=lc_docs,
    embedding=embeddings,
    persist_directory=str(CHROMA_DIR),
    collection_name="rag_documents",
)
print(f"      Indexed {len(lc_docs)} docs")
print(f"      Latency: {time.perf_counter()-t0:.1f}s")
print()

# ---- Test 5 queries ----
print("[4/4] Testing retrieval with 5 sample queries...")
print()

test_queries = [
    "What is the best content type for engagement in Tunisia?",
    "How does Ramadan affect Instagram engagement?",
    "Best practices for hotel marketing in Tunisia",
    "What time should I post for maximum reach?",
    "Top performing brands in patisserie industry",
]

for i, query in enumerate(test_queries, 1):
    print(f"Q{i}: {query}")
    t0 = time.perf_counter()
    results = vectorstore.similarity_search(query, k=3)
    latency = time.perf_counter() - t0
    print(f"    Top-3 retrieved (latency {latency:.2f}s):")
    for j, doc in enumerate(results, 1):
        snippet = doc.page_content[:120].replace("\n", " ")
        print(f"      {j}. [{doc.metadata.get('type'):<20}] {doc.metadata.get('id'):<35}")
        print(f"         {snippet}...")
    print()

# ---- Final summary ----
print("=" * 80)
print("Step 4d — Indexation Complete")
print("=" * 80)
print(f"  Documents indexed : {len(lc_docs)}")
print(f"  Embedding model   : paraphrase-multilingual-MiniLM-L12-v2 (384 dim)")
print(f"  Persisted at      : {CHROMA_DIR}")
disk_size = sum(f.stat().st_size for f in CHROMA_DIR.rglob('*') if f.is_file()) / 1024 / 1024
print(f"  Disk size         : ~{disk_size:.1f} MB")
print(f"  Status            : READY for Step 4e (RAG insights generation)")
