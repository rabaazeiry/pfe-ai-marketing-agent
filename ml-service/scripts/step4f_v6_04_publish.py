"""Step 4f V6 — Publish V6 insights to live API path + write migration log.

Copies data/step4f_v6/insights/insights_<industry>.json over
data/step4/insights/insights_<industry>.json so the existing backend
controller (backend/src/controllers/insights.controller.js) serves the
new 10-question V6 payloads on GET /api/insights/<industry>.

Old V3 files are backed up first to data/step4/insights/_backup_v3/.
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR    = ROOT / "data" / "step4f_v6" / "insights"
DST_DIR    = ROOT / "data" / "step4"     / "insights"
BACKUP_DIR = DST_DIR / "_backup_v3"
LOG_PATH   = ROOT / "data" / "step4f_v6" / "migration_log.txt"

INDUSTRIES = ["beauty", "fashion", "hotels", "patisserie", "restaurants"]


def main() -> int:
    print("=" * 78)
    print("Step 4f V6 — Publish to live API + write migration log")
    print("=" * 78)

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    DST_DIR.mkdir(parents=True, exist_ok=True)

    log_lines = []
    log_lines.append("=" * 78)
    log_lines.append("V6 INSIGHTS MIGRATION LOG — Step 4f V6")
    log_lines.append("=" * 78)
    log_lines.append(f"Generated:   {time.strftime('%Y-%m-%d %H:%M:%S')}")
    log_lines.append("")

    # 1. Backup existing V3 files
    log_lines.append("STEP 1 — Backup existing V3 files")
    log_lines.append("-" * 78)
    for ind in INDUSTRIES:
        old = DST_DIR / f"insights_{ind}.json"
        if old.exists():
            backup = BACKUP_DIR / f"insights_{ind}.json"
            shutil.copy2(old, backup)
            line = f"  {old.name} -> {backup.relative_to(ROOT)}  ({old.stat().st_size/1024:.1f} KB)"
            print(line); log_lines.append(line)
        else:
            line = f"  {old.name} not present (skipped backup)"
            print(line); log_lines.append(line)

    # 2. Copy V6 files into live path
    log_lines.append("")
    log_lines.append("STEP 2 — Publish V6 files to live API path")
    log_lines.append("-" * 78)
    summary = {}
    for ind in INDUSTRIES:
        src = SRC_DIR / f"insights_{ind}.json"
        dst = DST_DIR / f"insights_{ind}.json"
        if not src.exists():
            line = f"  ❌ {src.name} missing — skip"
            print(line); log_lines.append(line)
            summary[ind] = {"published": False, "reason": "source missing"}
            continue
        shutil.copy2(src, dst)

        # Read the published file to count questions + status
        with open(dst, encoding="utf-8") as f:
            data = json.load(f)
        n_q = len(data.get("questions", []))
        ok_q = sum(1 for q in data["questions"] if q.get("status") == "OK")
        line = (f"  ✅ {src.relative_to(ROOT)} -> {dst.relative_to(ROOT)}  "
                f"({dst.stat().st_size/1024:.1f} KB, {n_q} questions, {ok_q} LLM-OK)")
        print(line); log_lines.append(line)
        summary[ind] = {"published": True, "n_questions": n_q, "n_ok": ok_q}

    # 3. Migration summary
    log_lines.append("")
    log_lines.append("STEP 3 — Migration summary")
    log_lines.append("-" * 78)
    log_lines.append(f"  Files published:    {sum(1 for s in summary.values() if s['published'])} / "
                     f"{len(INDUSTRIES)}")
    total_q = sum(s.get("n_questions", 0) for s in summary.values())
    total_ok = sum(s.get("n_ok", 0) for s in summary.values())
    log_lines.append(f"  Insights count:     {total_q} total ({total_ok} LLM-OK)")
    log_lines.append(f"  Model:              V6 (Ridge over RF V5c + XGB V5c, R²=0.4587, ρ=0.6686)")
    log_lines.append(f"  Question count:     10 per industry (was 5 in V3)")
    log_lines.append("")
    log_lines.append("  Files modified / created:")
    log_lines.append("    + data/step4f_v6/documents/<industry>/*.md  (35 markdown docs)")
    log_lines.append("    + data/step4f_v6/documents.json  (217 docs)")
    log_lines.append("    + data/step4f_v6/chroma_db/  (fresh Chroma store)")
    log_lines.append("    + data/step4f_v6/insights/insights_<industry>.json  (5 files)")
    log_lines.append("    ~ data/step4/insights/insights_<industry>.json  (overwritten with V6 payloads)")
    log_lines.append("    + data/step4/insights/_backup_v3/insights_<industry>.json  (V3 backup)")
    log_lines.append("    + scripts/step4f_v6_01_build_documents.py")
    log_lines.append("    + scripts/step4f_v6_02_index_chroma.py")
    log_lines.append("    + scripts/step4f_v6_03_generate_insights.py")
    log_lines.append("    + scripts/step4f_v6_04_publish.py")
    log_lines.append("")
    log_lines.append("  Backend controller:  unchanged "
                     "(backend/src/controllers/insights.controller.js still reads from "
                     "ml-service/data/step4/insights/insights_<industry>.json — now V6 payloads).")
    log_lines.append("=" * 78)

    LOG_PATH.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    print(f"\nWrote migration log: {LOG_PATH.relative_to(ROOT)}")
    print(f"\nLive API path now serves V6 insights: {DST_DIR.relative_to(ROOT)}/insights_<industry>.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
