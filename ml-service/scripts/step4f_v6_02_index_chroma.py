"""Step 4f V6 — Index V6 RAG corpus into a fresh Chroma DB.

Mirrors scripts/step4_index_chroma.py but reads from data/step4f_v6/documents.json
and persists to data/step4f_v6/chroma_db/.
"""
from __future__ import annotations

import os
os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

import json
import shutil
import sys
import time
from pathlib import Path

import torch  # noqa: F401  -- Windows DLL order

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
DOC_PATH   = ROOT / "data" / "step4f_v6" / "documents.json"
CHROMA_DIR = ROOT / "data" / "step4f_v6" / "chroma_db"


def main() -> int:
    print("=" * 78)
    print("Step 4f V6 — Chroma indexing")
    print("=" * 78)

    print(f"\nLoading {DOC_PATH.name} ...")
    with open(DOC_PATH, "r", encoding="utf-8") as f:
        raw_docs = json.load(f)
    print(f"  {len(raw_docs)} documents")

    from langchain_core.documents import Document
    from langchain_huggingface import HuggingFaceEmbeddings
    from langchain_chroma import Chroma

    def _coerce_md(md: dict) -> dict:
        clean = {}
        for k, v in (md or {}).items():
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
                "id":   d["id"],
                "type": d["type"],
                **_coerce_md(d.get("metadata", {})),
            },
        )
        for d in raw_docs
    ]
    print(f"  converted to LangChain docs: {len(lc_docs)}")

    print(f"\nInitialising embeddings (paraphrase-multilingual-MiniLM-L12-v2) ...")
    t0 = time.perf_counter()
    embeddings = HuggingFaceEmbeddings(
        model_name="paraphrase-multilingual-MiniLM-L12-v2",
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )
    print(f"  embeddings ready in {time.perf_counter() - t0:.1f}s")

    if CHROMA_DIR.exists():
        shutil.rmtree(CHROMA_DIR)

    print(f"\nIndexing {len(lc_docs)} docs into Chroma at {CHROMA_DIR.relative_to(ROOT)} ...")
    t0 = time.perf_counter()
    vs = Chroma.from_documents(
        documents=lc_docs,
        embedding=embeddings,
        persist_directory=str(CHROMA_DIR),
        collection_name="rag_documents_v6",
    )
    print(f"  indexed in {time.perf_counter() - t0:.1f}s  "
          f"(collection count = {vs._collection.count()})")

    # Quick smoke retrieval test
    print(f"\nSmoke test — 3 sample queries:")
    queries = [
        "What visual elements drive engagement for hotels in Tunisia?",
        "Optimal hashtag count for patisserie",
        "V6 SHAP top features for content strategy",
    ]
    for q in queries:
        t0 = time.perf_counter()
        res = vs.similarity_search(q, k=3)
        print(f"  Q: {q}  ({(time.perf_counter() - t0)*1000:.0f} ms)")
        for r in res:
            print(f"     - [{r.metadata.get('type')}] {r.metadata.get('id')}")

    disk_mb = sum(f.stat().st_size for f in CHROMA_DIR.rglob("*") if f.is_file()) / 1024 / 1024
    print(f"\nChroma store size: {disk_mb:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
