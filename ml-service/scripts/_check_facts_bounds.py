"""One-shot sanity check for the facts.json bounds. Reads all 5 facts files,
counts how many `_er` fields each contains, and reports any value outside
[0, ER_MAX]. Used to validate STEP C of the rework."""
from __future__ import annotations
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from compute_facts import _walk_numeric_fields, ER_MAX, EXPECTED_MODULES, INDUSTRIES

ROOT = Path(__file__).resolve().parents[1]
FACTS_DIR = ROOT / "data" / "step4f_v6" / "facts"

issues_total = 0
for ind in INDUSTRIES:
    facts = json.loads((FACTS_DIR / f"facts_{ind}.json").read_text(encoding="utf-8"))
    fields = _walk_numeric_fields(facts)
    n_er = sum(1 for _, s, _ in fields if s == "_er")
    n_share = sum(1 for _, s, _ in fields if s == "_share")
    n_delta = sum(1 for _, s, _ in fields if s == "_delta")
    n_n = sum(1 for _, s, _ in fields if s == "_n")
    bad_er = [(p, v) for p, s, v in fields if s == "_er" and not (0 <= v <= ER_MAX)]
    modules_ok = set(facts["modules"].keys()) == EXPECTED_MODULES
    calendar_ok = len(facts["calendar_30d"]) == 30
    issues_total += len(bad_er)
    print(f"  {ind:<11}  _er={n_er:>3}  _share={n_share:>3}  _delta={n_delta:>3}  _n={n_n:>3}  "
          f"modules_ok={modules_ok}  calendar_30={calendar_ok}  bad_er={len(bad_er)}")
    if bad_er:
        for path, val in bad_er[:5]:
            print(f"     ⚠  {path} = {val}")

print()
print(f"Total _er violations across all 5 industries: {issues_total}")
sys.exit(0 if issues_total == 0 else 1)
