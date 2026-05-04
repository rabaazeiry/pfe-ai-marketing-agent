"""Step 4 smoke test — verify all components work end-to-end before writing real code."""
from __future__ import annotations
import os
# Must be set before chromadb (opentelemetry-proto _pb2.py files clash with protobuf 7.x C++ impl)
os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")
import sys
import time
sys.stdout.reconfigure(encoding="utf-8")

print("=" * 80)
print("Step 4 Smoke Test")
print("=" * 80)

# Test 1: langchain-ollama → Llama 3.1
print()
print("[1/4] Testing langchain-ollama -> Llama 3.1...")
from langchain_ollama import OllamaLLM
llm = OllamaLLM(model="llama3.1:latest", temperature=0.3)
t0 = time.perf_counter()
response = llm.invoke("Reply in exactly 5 words: What is marketing?")
print(f"      Response: {response.strip()}")
print(f"      Latency:  {time.perf_counter()-t0:.1f}s")

# Test 2: sentence-transformers (multilingual embeddings)
print()
print("[2/4] Testing sentence-transformers embeddings...")
from sentence_transformers import SentenceTransformer
embedder = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
t0 = time.perf_counter()
test_texts = [
    "Hôtels à Tunis avec piscine",
    "Patisserie tunisienne ramadan",
    "Best instagram engagement strategy",
]
embeddings = embedder.encode(test_texts)
print(f"      Embeddings shape: {embeddings.shape}")
print(f"      Latency:          {time.perf_counter()-t0:.1f}s")

# Test 3: ChromaDB (in-memory, no persistence)
print()
print("[3/4] Testing chromadb (in-memory)...")
import chromadb
t0 = time.perf_counter()
client = chromadb.Client()
collection = client.create_collection("smoke_test")
collection.add(
    documents=test_texts,
    ids=["doc1", "doc2", "doc3"],
    embeddings=embeddings.tolist()
)
results = collection.query(
    query_embeddings=[embeddings[0].tolist()],
    n_results=2
)
print(f"      Top-2 closest to '{test_texts[0]}':")
for doc, dist in zip(results["documents"][0], results["distances"][0]):
    print(f"        - {doc[:50]}... (dist={dist:.3f})")
print(f"      Latency:          {time.perf_counter()-t0:.1f}s")

# Test 4: End-to-end LangChain RAG (Chroma + Llama 3.1)
print()
print("[4/4] Testing LangChain RAG (Chroma + Llama 3.1)...")
from langchain_community.vectorstores import Chroma
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_classic.chains import RetrievalQA
from langchain_core.documents import Document

t0 = time.perf_counter()
hf_embeddings = HuggingFaceEmbeddings(
    model_name="paraphrase-multilingual-MiniLM-L12-v2"
)
docs = [
    Document(page_content="Topic Ramadan: 234 posts, avg engagement 3.2%, peak hour 19h"),
    Document(page_content="Patisserie industry: 8 brands, avg likes 1250 per post"),
    Document(page_content="Best content type: Reels generate 2.4x more engagement than photos"),
]
vectorstore = Chroma.from_documents(documents=docs, embedding=hf_embeddings)
qa = RetrievalQA.from_chain_type(
    llm=llm,
    retriever=vectorstore.as_retriever(search_kwargs={"k": 3}),
)
question = "What is the best content type for Instagram engagement?"
print(f"      Question: {question}")
result = qa.invoke({"query": question})
print(f"      Answer:   {result['result'][:200].strip()}...")
print(f"      Latency:  {time.perf_counter()-t0:.1f}s")

print()
print("=" * 80)
print("SUCCESS - ALL 4 TESTS PASSED -- Step 4 stack is operational")
print("=" * 80)
