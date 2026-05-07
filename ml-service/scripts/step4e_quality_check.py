"""Step 4e quality validation — review 125 generated insights before Step 5.

Read-only. Loads the 5 insights JSONs, samples them, runs sanity checks,
and prints a verdict.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

INSIGHTS_DIR = Path("data/step4/insights")
INDUSTRIES = ["hotels", "restaurants", "beauty", "fashion", "patisserie"]


def load_industry(name: str) -> dict:
    return json.loads((INSIGHTS_DIR / f"insights_{name}.json").read_text(encoding="utf-8"))


def word_count(s: str) -> int:
    return len(re.findall(r"\S+", s or ""))


def main() -> None:
    industries = {ind: load_industry(ind) for ind in INDUSTRIES}

    # ============================================================
    # STEP 1 — Summary statistics
    # ============================================================
    print("=" * 72)
    print("STEP 1 — SUMMARY STATISTICS")
    print("=" * 72)
    total_insights = 0
    total_size = 0
    print(f"{'industry':<14}{'questions OK':>14}{'insights':>10}{'size (KB)':>11}")
    print("-" * 72)
    for ind, data in industries.items():
        n_q_ok = sum(1 for q in data["questions"] if q["status"] == "OK")
        n_ins = sum(len(q["insights"]) for q in data["questions"])
        size_kb = (INSIGHTS_DIR / f"insights_{ind}.json").stat().st_size / 1024
        total_insights += n_ins
        total_size += size_kb
        print(f"{ind:<14}{f'{n_q_ok}/5':>14}{n_ins:>10}{size_kb:>11.1f}")
    print("-" * 72)
    print(f"{'TOTAL':<14}{'':>14}{total_insights:>10}{total_size:>11.1f}")
    print()

    print("First 3 insight titles from Q1 of each industry:")
    for ind in INDUSTRIES:
        q1 = industries[ind]["questions"][0]
        print(f"\n  [{ind}] Q1 = {q1['question_title']}")
        for i, ins in enumerate(q1["insights"][:3], 1):
            print(f"    {i}. {ins.get('title', '<no title>')}")

    # ============================================================
    # STEP 2 — One complete sample per industry (Q1, insight #1)
    # ============================================================
    print("\n")
    for ind in INDUSTRIES:
        q1 = industries[ind]["questions"][0]
        ins = q1["insights"][0]
        print("=" * 72)
        print(f"{ind.upper()} — Q1 Sample Insight")
        print("=" * 72)
        print(f"Title    : {ins.get('title', '<missing>')}")
        print(f"Content  : {ins.get('content', '<missing>')}")
        print(f"Evidence : {ins.get('evidence', '<missing>')}")
        print(f"(Retrieved docs: {q1['retrieved_docs']})")
        print(f"(Latency: {q1['latency_seconds']}s)")
        print()

    # ============================================================
    # STEP 3 — Quality checks
    # ============================================================
    print("=" * 72)
    print("STEP 3 — QUALITY CHECKS")
    print("=" * 72)

    empty_content: list[tuple[str, str, int]] = []
    missing_evidence: list[tuple[str, str, int, str]] = []
    long_titles: list[tuple[str, str, int, int, str]] = []
    duplicates: list[tuple[str, str]] = []
    title_lengths: list[int] = []

    for ind in INDUSTRIES:
        seen_titles: dict[str, str] = {}  # title -> "Qx#i"
        for q in industries[ind]["questions"]:
            for i, ins in enumerate(q["insights"], 1):
                title = (ins.get("title") or "").strip()
                content = (ins.get("content") or "").strip()
                evidence = (ins.get("evidence") or "").strip()
                wc = word_count(title)
                title_lengths.append(wc)

                if not content:
                    empty_content.append((ind, q["question_id"], i))
                if not evidence:
                    missing_evidence.append((ind, q["question_id"], i, title[:60]))
                if wc > 12:
                    long_titles.append((ind, q["question_id"], i, wc, title))
                # case-insensitive duplicate check within an industry
                key = title.lower()
                if key and key in seen_titles:
                    duplicates.append((ind, f"{seen_titles[key]} <-> {q['question_id']}#{i}: {title}"))
                else:
                    seen_titles[key] = f"{q['question_id']}#{i}"

    max_title_words = max(title_lengths) if title_lengths else 0
    avg_title_words = (sum(title_lengths) / len(title_lengths)) if title_lengths else 0
    over_8 = sum(1 for w in title_lengths if w > 8)
    over_12 = sum(1 for w in title_lengths if w > 12)

    print(f"\nTitle word-count stats:")
    print(f"  avg {avg_title_words:.1f} words | max {max_title_words} words")
    print(f"  titles > 8  words: {over_8}/125 ({100*over_8/125:.0f}%)")
    print(f"  titles > 12 words: {over_12}/125 ({100*over_12/125:.0f}%)")

    print(f"\nEmpty content       : {len(empty_content)}")
    if empty_content:
        for ind, qid, i in empty_content[:5]:
            print(f"  - {ind} {qid} #{i}")

    print(f"Missing evidence    : {len(missing_evidence)}")
    if missing_evidence:
        for ind, qid, i, ttl in missing_evidence[:5]:
            print(f"  - {ind} {qid} #{i}: {ttl!r}")

    print(f"Titles > 12 words   : {len(long_titles)}")
    if long_titles:
        for ind, qid, i, wc, ttl in long_titles[:5]:
            print(f"  - {ind} {qid} #{i} ({wc} words): {ttl}")

    print(f"Duplicate titles    : {len(duplicates)}")
    if duplicates:
        for ind, info in duplicates[:5]:
            print(f"  - {ind}: {info}")

    # ============================================================
    # STEP 4 — Verdict
    # ============================================================
    print("\n" + "=" * 72)
    print("QUALITY VERDICT")
    print("=" * 72)

    issues: list[str] = []

    def mark(ok: bool, msg_ok: str, msg_bad: str) -> str:
        if ok:
            return f"[OK] {msg_ok}"
        issues.append(msg_bad)
        return f"[!!] {msg_bad}"

    print(mark(not empty_content,
              f"All {total_insights} insights have content",
              f"{len(empty_content)} insights have empty content"))
    print(mark(not missing_evidence,
              f"All {total_insights} insights have evidence sources",
              f"{len(missing_evidence)} insights missing evidence"))
    print(mark(not long_titles,
              f"Titles concise (max {max_title_words} words, avg {avg_title_words:.1f})",
              f"{len(long_titles)} titles > 12 words (max observed: {max_title_words})"))
    print(mark(not duplicates,
              "No duplicate titles within an industry",
              f"{len(duplicates)} duplicate titles within an industry"))
    print("[OK] Sample inspection (5 industries x Q1 #1) printed above for manual review")

    print()
    if issues:
        print("VERDICT: NEEDS REGENERATION (X)")
        print("Issues:")
        for it in issues:
            print(f"  - {it}")
    else:
        print("VERDICT: READY for Step 5 (OK)")


if __name__ == "__main__":
    main()
