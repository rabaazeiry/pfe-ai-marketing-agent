# Technical Audit — "Step 5: Strategy / Campaign Generation"

*Read-only forensic audit of `ml-service/`, `backend/`, `frontend/`, `infra/n8n/`,
`mcp-server/`. All facts quoted from source with `file:line`. Working tree as of
branch `step4-prose-hardening` / commit `ce7cebb`. Generated 2026-05-19.*

> **One-line summary:** Step 5 is a **hybrid generator** — pure-Python templates
> own every fact/number/date/hashtag/format/theme; an Ollama **llama3.1** model
> writes only French creative prose. It consumes the Step-4 facts JSON **and** a
> Prophet forecast JSON, loops the 5 industries, and writes one
> `campaign_<industry>.json` per industry to disk. **No MongoDB**; the dashboard
> and MCP server read it through a backend HTTP endpoint; n8n orchestrates it by
> calling that endpoint (never runs the script itself).

---

## 1. What Step 5 Produces + Pipeline + Entry Point

### 1.1 Outputs

One JSON campaign object per industry. Schema assembled in
`ml-service/scripts/campaign_generator.py`:

- **Top level** (`:390-407`, `build_skeleton` return): `version` (`"campaign_v1"`),
  `industry`, `generated_at` (UTC), `model` (`"llama3.1:latest"`), `sources`
  (`{prophet: "<ind>_forecast_v3.json", facts: "facts_<ind>.json"}`),
  `anchor_week`, `campaign_summary`, `weeks[]`; plus `generation` metadata
  appended at `:883-888` (`no_llm`, `n_posts`, `elapsed_seconds`,
  `status_counts`).
- **campaign_summary** (`:400-405`, filled `:865-866`): `title`, `objective`,
  `target_audience` (LLM-written), `platforms` = `["instagram"]` (fixed,
  template-owned), `status`.
- **weeks[]** — exactly **4 weeks** (`:381-388`): `week_index`, `week_start`,
  `intensity`, `predicted_engagement` (rounded 4 dp), `posts_recommended`,
  `posts[]`.
- **per post** (`:363-378`): `post_index`, `date` (ISO), `day_of_week` (French),
  `best_time` (e.g. `"19h"`), `format` (photo/reel/carousel), `theme`,
  `hashtags[]` (3), and 5 LLM creative fields — `caption`, `hook`, `ad_angle`,
  `production_guide`, `visual_recommendation` — plus `status`
  (`OK`/`REPAIRED`/`FALLBACK`/`NO_LLM`).

> **Flag — no explicit KPI object.** The only forecast number surfaced is
> per-week `predicted_engagement` (`:385`). This is deliberate — the module
> docstring (`:4-8`) forbids extra numbers. The calendar is **dated**
> (per-post ISO date + French day + `best_time`), not a generic weekly grid.

### 1.2 Pipeline sequence (entry point → output)

Entry point: `campaign_generator.py:944-945` → `if __name__ == "__main__":
sys.exit(main())`. CLI: `--industry {beauty|fashion|hotels|patisserie|
restaurants|all}` (default `all`), `--no-llm` (`:906-908`).

Ordered stages (per industry, inside `build_industry`):

1. `main()` parse args, resolve industry list — `:905-912`
2. Lazy-load Ollama LLM (only if not `--no-llm`) — `:920-925`
3. `load_prophet(industry)` — read Prophet forecast, slice first 4 weeks — `:71-80`
4. `load_facts(industry)` — read Step-4 facts JSON — `:83-88`
5. Compute campaign window from forecast — `:834-835`
6. `build_pools(...)` — deterministic rotation pools (days/hours/formats/
   themes/hashtags) + client-safety filtering — `:245-304`
7. `build_grounding(...)` — qualitative LLM cues, **no digits** — `:435-506`
8. `build_skeleton(...)` — full dated structure, 5 creative fields = `None` —
   `:336-407` (calls `place_week_posts` per week, `:307-333`)
9. campaign_summary: `fallback_summary` if `--no-llm` else
   `generate_summary(llm,...)` — `:861-867`
10. Post loop: per week per post → `fallback_post` if `--no-llm` else
    `generate_post(llm,...)` — `:870-881`
11. Attach `generation` metadata — `:883-888`
12. `validate_schema(camp)` — asserts structure, raises on breach — `:795-818`,
    called `:890`
13. Write `campaign_<industry>.json` — `:892-895`

There is **no standalone orchestrator**; the per-industry loop is `main()`
itself (`:930-933`). The de-facto runtime entry point in production is the Node
backend controller (see §6).

---

## 2. Inputs — Step 4 insights? Templates? ML models?

**Two input files per industry; no parquet, no joblib/pkl, no Prophet model
binary.** Path constants `campaign_generator.py:49-52`:

```
ROOT         = Path(__file__).resolve().parents[1]
PROPHET_DIR  = ROOT / "data" / "prophet"
FACTS_DIR    = ROOT / "data" / "step4f_v6" / "facts"
OUT_DIR      = ROOT / "data" / "step5" / "campaigns"
```

- **Step 4 facts — YES.** `load_facts` (`:83-88`) reads
  `ml-service/data/step4f_v6/facts/facts_<industry>.json` (the **deterministic
  facts** output of Step 4 — `compute_facts.py` — *not* the LLM `insights_*.json`).
  Consumed via `facts.get("modules", {})` for `optimal_timing`,
  `visual_strategy`, `content_themes` (`:251-253`) and `content_strategy`,
  `engagement_tactics`, `current_trends`, `brand_differentiation` (`:442-446`).
- **Prophet forecast — YES.** `load_prophet` (`:71-80`) reads
  `ml-service/data/prophet/<industry>_forecast_v3.json`, key `forecast`, first
  4 entries (`FIRST_N_WEEKS = 4`, `:55`). Supplies per-week `week`,
  `posts_recommended`, `intensity`, `predicted_engagement`.
- **Templates — inline only.** No `_template_modules` import (that module is
  Step 4's). Inline constants: `_GENERIC_HASHTAGS` (`:104-125`),
  `_GENERIC_THEMES` (`:130-144`), `SYSTEM_PROMPT` (`:513-536`),
  `_POST_USER_TMPL` (`:538-554`), `_SUMMARY_USER_TMPL` (`:556-569`), plus the
  deterministic `fallback_post`/`fallback_summary` copy.
- **ML / Prophet model artifact — NOT loaded.** The only input read calls in
  the whole file are two `json.loads(p.read_text(...))` (`:76`, `:88`). No
  `joblib.load`, `pickle.load`, `pd.read_parquet`, `np.load`. Step 5 consumes
  the **pre-computed Prophet forecast JSON**, never a serialized Prophet model.

---

## 3. Strategy / Campaign Generation Logic — Deterministic, LLM, or Hybrid

**Hybrid, with an explicit split** (module docstring `:4-8`: *"Python TEMPLATE
owns every fact, number, date, hashtag, @handle, format and theme. The LLM
produces ONLY French creative prose."*).

- **Deterministic (pure Python, zero LLM):** all structure/dates/rotation
  (`build_pools` `:245-304`, `place_week_posts` `:307-333`, `build_skeleton`
  `:336-407`); day/time/format/theme/hashtag rotation by modular counter `k`
  (`:355-362`); client-safety filters (`_theme_is_client_safe` `:236-238`,
  `_BRAND_RE` `:161-163`, `_SEASON_RULES` `:196-207`); schema validation
  (`:795-818`); fixed fields `platforms=["instagram"]`, `predicted_engagement`,
  `best_time`; deterministic fallback prose (`fallback_post` `:686-726`,
  `fallback_summary` `:729-738`).
- **LLM (Ollama llama3.1):** only the 5 creative fields per post and the 3
  summary fields.
- **Hybrid switch** (`:861-877`): `if no_llm:` → fallback; `else:` →
  `generate_summary` / `generate_post`. Within the LLM path, 3-tier
  degradation (`generate_post` `:743-766`): LLM success → `OK`; parse/validate
  fail → 1 repair retry → `REPAIRED`; still failing / Ollama unreachable →
  deterministic `fallback_post` → `FALLBACK`.
- **Numeric-hallucination prevention** (`build_grounding` docstring `:435-440`):
  *"The model never sees a single digit — only directions like 'évite les mots
  promotionnels'. This makes numeric hallucination structurally impossible in
  the creative fields."* Facts/Prophet numbers never enter the prompt.

(Observed in `campaign_beauty.json`:
`status_counts: {'OK': 10, 'REPAIRED': 1, 'FALLBACK': 2}` — confirms the
hybrid degradation actually fires at runtime.)

---

## 4. LLM Usage

**Backend:** Ollama via `langchain_ollama.OllamaLLM`. No Anthropic / Claude /
OpenAI / HTTP LLM anywhere (grep confirmed). Constants
`campaign_generator.py:58-64`:

```
LLM_MODEL   = "llama3.1:latest"
TEMPERATURE = 0.4                       # creative copy needs variety (vs 0.0 rephraser)
NUM_CTX     = 4096
NUM_PREDICT = 700
TIMEOUT_S   = 180
MAX_RETRIES = 1
```

Instantiation `:921-925`:
`llm = OllamaLLM(model=LLM_MODEL, temperature=TEMPERATURE, num_ctx=NUM_CTX,
num_predict=NUM_PREDICT, timeout=TIMEOUT_S)`.

| Param | Value | file:line |
|---|---|---|
| model tag | `"llama3.1:latest"` | `:59` |
| temperature | **`0.4`** (vs Step 4's 0.0 — creative variety) | `:60` |
| num_ctx | `4096` | `:61` |
| num_predict | `700` | `:62` |
| timeout | `180` s | `:63` |
| repair retries | `1` | `:64` |
| top_p / seed | **NOT SET** (Ollama defaults; LLM output non-deterministic across runs) | — |

Invocation is a single concatenated string prompt
(`return f"{SYSTEM_PROMPT}\n\n{user}"`, `:597`/`:770`), via `llm.invoke(...)`
(`:748`, `:759`, `:772`, `:781`).

**Prompt structure (verbatim):**

- `SYSTEM_PROMPT` (`:513-536`) — French copywriter role with **absolute
  prohibitions**: *"AUCUN chiffre, AUCUN pourcentage, AUCUNE date écrite en
  chiffres. AUCUN caractère « # » ni « @ » … AUCUN mot anglais. AUCUN nom de
  marque … AUCUN format ni canal absent du contexte."* Mandates an exact
  template: `CAPTION: / HOOK: / ANGLE: / PRODUCTION: / VISUEL:`.
- `_POST_USER_TMPL` (`:538-554`) — injects `SECTEUR`, the fixed CONTEXTE
  (day, time, format, theme, pre-chosen hashtags) and qualitative creative
  cues (`caption_len`, `tone`, do/don't lists, rotated `angle_theme`) — filled
  at `:583-596`.
- `_SUMMARY_USER_TMPL` (`:556-569`) — 4-week campaign summary; same
  no-digit/no-hashtag/no-brand constraints; template `TITRE: / OBJECTIF: /
  AUDIENCE:`.

**Post-processing of LLM output:** tolerant section split `_split_sections`
(`:616-623`) → `parse_post` (`:626-631`, rejects sections < 8 chars) →
`validate_prose` (`:652-671`, rejects on any digit, `#`, `@`, ≥2 English
markers, competitor brand `_BRAND_RE`, chatbot/meta phrase) → on violation, 1
retry with `_repair_suffix` (`:674-681`) → else deterministic fallback →
`validate_schema` before write.

---

## 5. Per-Industry Generation

**Looped over exactly 5 industries.** `campaign_generator.py:54`:
`INDUSTRIES = ["beauty", "fashion", "hotels", "patisserie", "restaurants"]`.
Loop `:912` (`industries = INDUSTRIES if args.industry == "all" else
[args.industry]`) and `:930-933` (`for ind in industries:
build_industry(ind, ...)`). Each industry independently loads its own
forecast + facts and writes its own campaign file. Same 5-industry set in the
backend (`campaign.controller.js:24`), MCP server (`server.js:12`), and n8n
(`Resolve Context`). **The 5 industries: beauty, fashion, hotels, patisserie,
restaurants.**

---

## 6. Output Structure + Storage + Dashboard Consumption

### 6.1 Storage — file-based, NO MongoDB

`campaign_generator.py:892-895` writes
`ml-service/data/step5/campaigns/campaign_<industry>.json` via
`Path.write_text(json.dumps(camp, ensure_ascii=False, indent=2))`. No
`pymongo`/`requests.post`/HTTP anywhere — the script never publishes
downstream. All 5 files exist on disk (`campaign_{beauty,fashion,hotels,
patisserie,restaurants}.json`, dated 17–18 May).

### 6.2 Backend

- Routes (`backend/src/routes/campaign.routes.js`): JWT-protected
  `GET /api/campaign/:industry` → `getCampaignByIndustry`;
  `POST /api/campaign/:industry/regenerate` → `regenerateCampaign`.
- `getCampaignByIndustry` (`campaign.controller.js:67-83`): pure file read of
  `ml-service/data/step5/campaigns/campaign_<industry>.json`, 404 on `ENOENT`.
- `regenerateCampaign` (`:107-120`): `req.socket.setTimeout(0)` then
  `_runPython(CAMPAIGN_SCRIPT, ['--industry', industry], ...)`, then reads &
  returns the JSON. Spawn (`:26-37`): `spawn(PYTHON_EXE, ['-X','utf8',
  scriptPath, ...args], { env: { ...process.env,
  PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION:'python' } })` →
  `<ml-service>/.venv/Scripts/python.exe -X utf8
  scripts/campaign_generator.py --industry <ind>`.
- **`PYTHON_EXE` is a hard-coded Windows path** (`:22`,
  `.venv/Scripts/python.exe`) — no POSIX fallback (would fail on Linux/Docker).

> **Flag — orphaned Mongoose model.** `backend/src/models/CampaignPlan.model.js`
> is fully defined and registered, but **never created/saved/read/updated** in
> `backend/src` (only a cascade `deleteMany` in `Project.model.js:223`). Its
> schema describes a "30-day content calendar" with `durationDays` ≤ 365 and
> different field names (`callToAction`, `bestTimeToPost`, `visualDescription`)
> — **not interchangeable** with the actual 4-week Prophet-anchored JSON
> contract. Step 5 persistence is **file-based JSON only**; the model is dead
> code relative to the live flow.

### 6.3 Frontend

- Tab wired in `frontend/src/pages/ProjectDetailPage.tsx` (`id: 'campaign'`,
  `<FiCalendar/>`), rendered by
  `frontend/src/features/projects/components/CampaignSection.tsx`
  (sub-components `CampaignSummary`, `WeekCard`, `PostRow`, `DetailField`).
- Hooks `useProjectDetail.ts`: `useIndustryCampaign` (React-Query GET,
  `staleTime 5 min`), `useRegenerateIndustryCampaign` (mutation).
- API `detail.api.ts`: `GET /campaign/${industry}` and
  `POST /campaign/${industry}/regenerate` (10-min client timeout), returns
  `null` on 404/501.
- Displayed fields (`CampaignSection.tsx`): header `model`/`industry`;
  summary `title/objective/target_audience/platforms[]`; per week
  `week_index/week_start/intensity/predicted_engagement(.toFixed(3))/
  posts_recommended`; per post `date/day_of_week/best_time/format/theme/
  status/hashtags[]` and expandable `caption/hook/ad_angle/production_guide/
  visual_recommendation`. Type contract `types.ts:131-175` (`CampaignBundle`),
  header comment: *"Matches campaign_<industry>.json produced by
  scripts/campaign_generator.py."*

---

## 7. Relation to the n8n Workflow

- Workflow file: **`infra/n8n/workflows/full-pipeline.json`** — *"Full Analysis
  Pipeline (Steps 1-5)"*, `"active": false` (manual-trigger only). Header
  (`:7`): *"Calls the EXISTING backend over HTTP only — no business logic is
  reimplemented."* (Two other files exist: `daily-scraping.json`,
  `pipeline-notifications.json` — not the orchestrator.)
- **No Execute-Command / `campaign_generator.py` node.** Node types are limited
  to `manualTrigger`, `code`, `httpRequest`, `wait`, `splitInBatches`, `if`.
  Step 5 is performed purely via HTTP to the backend (which spawns the Python
  script).
- **Step-5 nodes (full mode):** `Campaign Baseline`
  (`GET /campaign/<industry>`) → `Fire Campaign Regenerate`
  (`POST /campaign/<industry>/regenerate`, `full-pipeline.json:492-511`) →
  `Wait Campaign` (default 30 s) → `Poll Campaign` (`GET`) → `Eval Campaign`
  (compares `generated_at` vs baseline) → `Campaign Updated?` (loop or finish).
  In **fast mode**: a single `Fast Get Campaign` (`GET /campaign/<industry>`),
  no regeneration.
- **Step 4 → Step 5 wiring** (`connections`, `:609-611`): the true-branch of
  `Insights Updated?` → `Campaign Baseline` → `Fire Campaign Regenerate`.
  Coupling is **sequencing + shared `industry` string only** — no data payload
  is passed inside n8n. The real Step-4→Step-5 data handoff is
  filesystem-mediated: `facts_<industry>.json` → `campaign_generator.py` →
  `campaign_<industry>.json` (`campaign.controller.js:1-9`).
- Full sequence: Manual Trigger → Pipeline Inputs → Login → Step 1 Create
  Project → Resolve Context → Step 2a-2e (Discover/Enrich/Classify/Market
  Research/SWOT loop) → Step 3 Scrape (poll loop) → Mode Switch → Step 4
  Insights (fast GET or full regen-poll) → Step 5 Campaign (fast GET or full
  regen-poll) → Pipeline Result.
- **Step 5 is industry-scoped, not project-scoped** (consistent across n8n,
  backend, MCP). Steps 1-3 are projectId-scoped; Steps 4-5 switch to the
  `industry` key derived once in `Resolve Context`.

### 7.1 MCP server (bonus)

`mcp-server/src/server.js:85-106` registers tool **`get_campaign`** —
description *"Get the generated content campaign / calendar (pipeline Step 5)
… Industry-scoped artifact."*, input `industry: z.enum(INDUSTRIES)`. The
handler is **read-only**: `apiFetch('/campaign/${industry}')` →
`GET http://localhost:5000/api/campaign/<industry>` (same backend endpoint as
the frontend / n8n fast path; `BACKEND_URL`-overridable). No MCP tool can
*trigger* Step 5 — only `create_project`, `get_insights`, `get_campaign` exist.

---

## Flags — Expected-but-absent / Unexpected-present

- **Expected & present:** Step-4 facts input, Prophet forecast input,
  per-industry loop (5), hybrid template+LLM, Ollama llama3.1, file-based
  output, backend route, frontend tab, n8n orchestration, MCP read tool.
- **Expected-but-absent:**
  1. **No KPI/metrics object** — only per-week `predicted_engagement`.
  2. **No serialized Prophet model** (`joblib`/`pickle`/`model.save`) anywhere
     — only the forecast JSON is persisted; the model is rebuilt from
     `<ind>_best_params_v3.json` + preprocessed CSV each `prophet_train.py` run.
  3. LLM `top_p`/`seed` not set (non-deterministic creative output).
  4. **No MongoDB persistence** for Step 5; no campaign service layer in
     `backend/src/services`.
- **Unexpected-present:**
  1. **`CampaignPlan` Mongoose model is orphaned** — defined/registered but
     never written or read by application code (only cascade-deleted); its
     "30-day" schema does not match the produced 4-week JSON.
  2. **Hard-coded `PYTHON_EXE` Windows path** in the backend controller — no
     cross-platform fallback.
  3. Hard-coded credentials placeholder (`amirapfa@gmail.com` /
     `password: 'CHANGE_ME'`) embedded in `full-pipeline.json:25` (Pipeline
     Inputs code node) — not Step-5-specific but present in the audited file.
  4. **Architectural discontinuity (intentional):** Steps 1-3 are
     project-scoped; Steps 4-5 are industry-scoped. Consistent across all
     layers but worth noting in the report.

### Prophet sub-pipeline (context for §2 input)

`prophet_preprocess.py` reads MongoDB `prophet_posts` → weekly per-industry
mean `engagementRate` (regressors `n_posts_scaled`, `is_ramadan`,
`is_summer_peak`) → `ml-service/data/prophet/<ind>_preprocessed.csv`.
`prophet_tune.py` grid-searches (5×5×2 = 50 combos, Prophet `cross_validation`
initial=365d/period=30d/horizon=84d) → `<ind>_best_params_v3.json`.
`prophet_train.py:124-142` builds `Prophet(changepoint_prior_scale=…,
seasonality_prior_scale=…, seasonality_mode=…, yearly_seasonality=True,
weekly_seasonality=False, daily_seasonality=False, holidays=CUSTOM_HOLIDAYS,
n_changepoints=25)` + Tunisia holidays + 3 regressors; target = weekly mean
engagement rate; horizon `FORECAST_WEEKS = 12`; output
`ml-service/data/prophet/<ind>_forecast_v3.json` (Step 5 uses
`forecast[0:4]`). No Prophet model object is ever serialized.

---

*End of audit. No code, configuration, or scripts were modified during this
investigation; this document is the sole artifact produced.*
