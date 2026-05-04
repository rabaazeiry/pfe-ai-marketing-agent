"""Step 4c POST-CHECK — quality inspection of data/step4/documents.json.

Read-only: loads documents, prints stats, samples one doc per type,
runs sanity checks, surfaces edge cases. NOTHING is modified.
"""
from __future__ import annotations
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
import unicodedata

sys.stdout.reconfigure(encoding="utf-8")

DOC_PATH = Path("data/step4/documents.json")
with open(DOC_PATH, "r", encoding="utf-8") as f:
    docs = json.load(f)

print("=" * 80)
print(" Step 4c POST-CHECK — RAG documents quality inspection")
print("=" * 80)
print(f" File: {DOC_PATH}   Total docs: {len(docs)}")
print()

# ---------------------------------------------------------------------------
# STEP 1 — basic stats per type
# ---------------------------------------------------------------------------
print("[STEP 1] Basic stats per type")
print()
by_type = defaultdict(list)
for d in docs:
    by_type[d["type"]].append(d)

print(f"{'Type':<22} | {'Count':>5} | {'avg_len':>7} | {'min_len':>7} | {'max_len':>7} | {'empty':>5} | {'<50ch':>5}")
print("-" * 80)
empty_total = 0
short_total = 0
for t in sorted(by_type, key=lambda k: -len(by_type[k])):
    lengths = [len(d["text"]) for d in by_type[t]]
    n_empty = sum(1 for L in lengths if L == 0)
    n_short = sum(1 for L in lengths if 0 < L < 50)
    empty_total += n_empty
    short_total += n_short
    print(
        f"{t:<22} | {len(by_type[t]):>5} | {sum(lengths)/len(lengths):>7.0f} | "
        f"{min(lengths):>7} | {max(lengths):>7} | {n_empty:>5} | {n_short:>5}"
    )
print("-" * 80)
print(f"{'TOTAL':<22} | {len(docs):>5} |         |         |         | {empty_total:>5} | {short_total:>5}")
print()

# ---------------------------------------------------------------------------
# STEP 2 — sample one doc per type
# ---------------------------------------------------------------------------
print("=" * 80)
print(" [STEP 2] Sample document per type (full text + metadata)")
print("=" * 80)

def find_doc(predicate):
    return next((d for d in docs if predicate(d)), None)

samples = [
    ("topic_summary",   find_doc(lambda d: d["id"] == "topic_2_summary")),
    ("top_post",        find_doc(lambda d: d["id"] == "topic_1_top_post_1")),
    ("brand_summary",   find_doc(lambda d: d["type"] == "brand_summary"
                                            and d["metadata"].get("performance_tier") == "above_average"
                                            and d["metadata"].get("n_posts", 0) >= 50)),
    ("industry_summary",find_doc(lambda d: d["id"] == "industry_patisserie_summary")),
    ("ml_insight",      find_doc(lambda d: d["id"] == "ml_top_features_shap")),
]

for label, d in samples:
    print(f"\n--- {label} ---")
    if d is None:
        print("  (no doc found matching selection)")
        continue
    print(f"id      : {d['id']}")
    print(f"type    : {d['type']}")
    print(f"text    : {d['text']}")
    print(f"meta    : {json.dumps(d['metadata'], ensure_ascii=False)}")

# ---------------------------------------------------------------------------
# STEP 3 — quality checks
# ---------------------------------------------------------------------------
print()
print("=" * 80)
print(" [STEP 3] Quality checks")
print("=" * 80)

# (a) No null/empty text
empties = [d["id"] for d in docs if not d["text"]]
print(f"\n (a) Empty text: {len(empties)} doc(s)" + (f"  {empties}" if empties else "  ✓"))

# (b) Metadata completeness per type
REQUIRED = {
    "topic_summary":   {"topic_id", "topic_name", "n_posts"},
    "top_post":        {"topic_id", "rank", "engagement", "brand"},
    "brand_summary":   {"brand", "industry", "n_posts"},
    "industry_summary":{"industry", "n_brands"},
    "ml_insight":      {"insight_type"},
}
meta_problems = []
for d in docs:
    needed = REQUIRED.get(d["type"], set())
    missing = needed - set(d["metadata"].keys())
    if missing:
        meta_problems.append((d["id"], missing))
print(f"\n (b) Metadata completeness: {'✓' if not meta_problems else 'PROBLEMS'}")
for did, miss in meta_problems[:10]:
    print(f"      {did} missing: {miss}")
if len(meta_problems) > 10:
    print(f"      ... ({len(meta_problems)-10} more)")

# (c) Duplicate IDs
ids = [d["id"] for d in docs]
dup = [i for i, c in Counter(ids).items() if c > 1]
print(f"\n (c) Duplicate IDs: {'✓ none' if not dup else dup}")

# (d) NaN-like strings in text
# Look for patterns that suggest a None/NaN slipped into formatted text:
#   "around None h"  "around nan h"  "Posted at nan h"  "Brand: nan."  "around <NA>"
nan_patterns = [
    re.compile(r"\bnone\b", re.IGNORECASE),
    re.compile(r"\bnan\b", re.IGNORECASE),
    re.compile(r"<NA>"),
    # Suspicious: hour or rank shown as ? in text
    re.compile(r"Posted at \?h"),
    re.compile(r"around \?h"),
]
nan_hits = []
for d in docs:
    for pat in nan_patterns:
        m = pat.search(d["text"])
        if m:
            nan_hits.append((d["id"], pat.pattern, m.group()))
            break
print(f"\n (d) NaN/None tokens in text: {'✓ none' if not nan_hits else f'{len(nan_hits)} hit(s)'}")
for did, pat, match in nan_hits[:5]:
    print(f"      {did}  pattern={pat!r}  match={match!r}")

# (e) Engagement > 200% in top_post docs
extreme = [(d["id"], d["metadata"]["engagement"], d["metadata"].get("brand"))
           for d in by_type.get("top_post", []) if d["metadata"].get("engagement", 0) > 2.0]
extreme.sort(key=lambda x: -x[1])
print(f"\n (e) top_post engagement > 200%: {len(extreme)} doc(s)")
for did, eng, brand in extreme[:10]:
    print(f"      {did}  eng={eng*100:.1f}%  brand={brand}")

# (f) Caption truncation in top_post (caption snippet capped at 200 chars in source)
trunc_problems = []
for d in by_type.get("top_post", []):
    # Extract caption portion: text contains  Caption: "...."
    m = re.search(r'Caption:\s*"(.*)"\s*$', d["text"], flags=re.DOTALL)
    if m:
        cap = m.group(1).rstrip(".")  # strip the trailing "..." marker
        if len(cap) > 220:  # 200 + small slack
            trunc_problems.append((d["id"], len(cap)))
print(f"\n (f) Caption truncation (~200 char cap): {'✓ all within 220ch' if not trunc_problems else f'{len(trunc_problems)} oversize'}")
for did, L in trunc_problems[:5]:
    print(f"      {did}  caption_len={L}")

# (g) Multilingual content preserved (Arabic / French accents / emoji)
def has_arabic(s): return any("؀" <= ch <= "ۿ" for ch in s)
def has_emoji(s):  return any(unicodedata.category(ch).startswith("So") for ch in s)
def has_french_accent(s): return any(ch in s for ch in "éèàçâêîôûïëüœ")

ar_docs    = [d for d in docs if has_arabic(d["text"])]
fr_docs    = [d for d in docs if has_french_accent(d["text"])]
emoji_docs = [d for d in docs if has_emoji(d["text"])]
print(f"\n (g) Multilingual unicode preserved:")
print(f"      Arabic chars   : {len(ar_docs)} doc(s)")
print(f"      French accents : {len(fr_docs)} doc(s)")
print(f"      Emoji          : {len(emoji_docs)} doc(s)")

# ---------------------------------------------------------------------------
# STEP 4 — edge case inspection
# ---------------------------------------------------------------------------
print()
print("=" * 80)
print(" [STEP 4] Edge cases")
print("=" * 80)

top_posts = sorted(by_type.get("top_post", []), key=lambda d: -d["metadata"].get("engagement", 0))
print(f"\n  Top 3 posts by HIGHEST engagement:")
for d in top_posts[:3]:
    m = d["metadata"]
    print(f"    {d['id']:<35}  eng={m['engagement']*100:>7.1f}%  brand={m.get('brand')}  topic={m.get('topic_name')}")

print(f"\n  Top 3 posts by LOWEST engagement:")
for d in top_posts[-3:]:
    m = d["metadata"]
    print(f"    {d['id']:<35}  eng={m['engagement']*100:>7.1f}%  brand={m.get('brand')}  topic={m.get('topic_name')}")

# Topics with avg_engagement > 100% (mean of raw engagement_rate)
big_topics = [d for d in by_type.get("topic_summary", [])
              if d["metadata"].get("avg_engagement", 0) > 1.0]
print(f"\n  topic_summary with avg_engagement > 100%: {len(big_topics)}")
for d in big_topics:
    m = d["metadata"]
    print(
        f"    {d['id']:<25}  avg={m['avg_engagement']*100:>7.1f}%  "
        f"median={m['median_engagement']*100:>6.1f}%  n_posts={m['n_posts']:>4}  "
        f"name={m['topic_name']}"
    )

# Brands with < 10 posts that still made it through (script floor was 5)
small_brands = [d for d in by_type.get("brand_summary", []) if d["metadata"].get("n_posts", 0) < 10]
print(f"\n  Brand summaries with n_posts < 10: {len(small_brands)}")
for d in sorted(small_brands, key=lambda x: x["metadata"]["n_posts"]):
    m = d["metadata"]
    print(f"    {d['id']:<45}  n_posts={m['n_posts']:>2}  industry={m['industry']:<12}  perf={m['performance_tier']}")

# ---------------------------------------------------------------------------
# STEP 5 — verdict
# ---------------------------------------------------------------------------
print()
print("=" * 80)
print(" [STEP 5] DOCUMENTS QUALITY REPORT")
print("=" * 80)

structure_ok = all({"id", "type", "text", "metadata"}.issubset(d.keys()) for d in docs)
text_ok = empty_total == 0
ids_ok = not dup
nan_ok = not nan_hits
multi_ok = (len(ar_docs) > 0 or len(fr_docs) > 0 or len(emoji_docs) > 0)
meta_ok = not meta_problems

def chk(ok): return "✓" if ok else "✗"

print(f"\n  Total docs                : {len(docs)}")
print(f"  Structure valid            : {chk(structure_ok)}")
print(f"  All texts non-empty        : {chk(text_ok)}")
print(f"  All IDs unique             : {chk(ids_ok)}")
print(f"  No NaN/None tokens         : {chk(nan_ok)}")
print(f"  Multilingual preserved     : {chk(multi_ok)}  (ar={len(ar_docs)} fr={len(fr_docs)} emoji={len(emoji_docs)})")
print(f"  Metadata complete          : {chk(meta_ok)}")

# Build outliers/quirks list
quirks = []
if extreme:
    quirks.append(f"{len(extreme)} top_post(s) have engagement > 200% (raw, no upper cap)")
if big_topics:
    quirks.append(f"{len(big_topics)} topic_summary(ies) have avg_engagement > 100% (mean pulled by extremes)")
if small_brands:
    quirks.append(f"{len(small_brands)} brand_summary(ies) below 10 posts (cutoff was n>=5)")

print()
if quirks:
    print(f"  Quirks worth noting:")
    for q in quirks:
        print(f"    - {q}")
else:
    print(f"  Quirks: none")

print()
all_critical_ok = structure_ok and text_ok and ids_ok and nan_ok and meta_ok and multi_ok
verdict = "READY for Step 4d (Chroma indexation)" if all_critical_ok else "NEEDS FIXES before indexation"
mark = "✓" if all_critical_ok else "✗"
print(f"  VERDICT: {verdict}  {mark}")
print()
