"""One-shot verification: build Arabic stopwords from codepoints, print them.

Mirrors the project convention from src/corpus/cleaner.py (no \\u escapes; use
hex codepoints). If the printed glyphs match the user's intended list and
every codepoint falls in U+0600 - U+06FF, the chr()-constructed values are
safe to paste into topic_model.py.
"""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8")

# Each tuple = (label, [codepoints]). Labels are ASCII-only for safety.
ARABIC_STOPWORD_CODEPOINTS = [
    ("fi",       [0x0641, 0x064A]),                          # في
    ("min",      [0x0645, 0x0646]),                          # من
    ("ala",      [0x0639, 0x0644, 0x0649]),                  # على
    ("an",       [0x0639, 0x0646]),                          # عن
    ("ila",      [0x0627, 0x0644, 0x0649]),                  # الى
    ("maa",      [0x0645, 0x0639]),                          # مع
    ("hatha",    [0x0647, 0x0630, 0x0627]),                  # هذا
    ("hathihi",  [0x0647, 0x0630, 0x0647]),                  # هذه
    ("thalik",   [0x0630, 0x0644, 0x0643]),                  # ذلك
    ("allati",   [0x0627, 0x0644, 0x062A, 0x064A]),          # التي
    ("alladhi",  [0x0627, 0x0644, 0x0630, 0x064A]),          # الذي
    ("kull",     [0x0643, 0x0644]),                          # كل
    ("ma",       [0x0645, 0x0627]),                          # ما
    ("an2",      [0x0627, 0x0646]),                          # ان
    ("al",       [0x0627, 0x0644]),                          # ال
    ("waw",      [0x0648]),                                  # و
    ("ya",       [0x064A, 0x0627]),                          # يا
    ("lam",      [0x0644, 0x0645]),                          # لم
    ("la",       [0x0644, 0x0627]),                          # لا
    ("lakin",    [0x0644, 0x0643, 0x0646]),                  # لكن
    ("aydan",    [0x0627, 0x064A, 0x0636, 0x0627]),          # ايضا
    ("hal",      [0x0647, 0x0644]),                          # هل
    ("am",       [0x0627, 0x0645]),                          # ام
    ("inna",     [0x0625, 0x0646]),                          # إن
    ("wala",     [0x0648, 0x0644, 0x0627]),                  # ولا
]


def _in_arabic_block(cp: int) -> bool:
    return 0x0600 <= cp <= 0x06FF


def main() -> None:
    print("Verifying Arabic stopwords built from codepoints")
    print("=" * 72)
    all_ok = True
    words = []
    for label, cps in ARABIC_STOPWORD_CODEPOINTS:
        word = "".join(chr(cp) for cp in cps)
        words.append(word)
        cp_strs = [f"U+{cp:04X}" for cp in cps]
        ok = all(_in_arabic_block(cp) for cp in cps)
        status = "OK" if ok else "OUT OF RANGE"
        if not ok:
            all_ok = False
        print(f"  {label:<10} {word:<8} {cp_strs}  [{status}]")

    print("-" * 72)
    print(f"All in U+0600-U+06FF: {all_ok}")
    print(f"Distinct words: {len(set(words))} / {len(words)}")
    print()
    print("Final list (paste-ready order):")
    print("  " + ", ".join(words))


if __name__ == "__main__":
    main()
