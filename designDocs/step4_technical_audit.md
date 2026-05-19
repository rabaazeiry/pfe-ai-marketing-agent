# Technical Audit — "Step 4: Insights Generation"

*Read-only forensic audit of `ml-service/` (+ related `backend/`). All facts quoted
from source with `file:line`. Working tree as of branch `step4-prose-hardening` /
commit `ce7cebb`. Generated 2026-05-19.*

> **Critical framing — there are TWO Step-4 implementations in the repo:**
>
> 1. **Legacy RAG pipeline** (`step4_*`, `step4f_v6_03/04`): Chroma vector DB +
>    LLM-generated insights. **Explicitly deprecated.** Header of
>    `ml-service/scripts/step4f_v6_03_generate_insights.py:1-12`: *"Step 4f V6 —
>    RAG + LLM legacy generator (NO LONGER IN STEP 4 CRITICAL PATH). DEPRECATED FOR
>    STEP 4 — DO NOT WIRE INTO THE DASHBOARD PIPELINE."*
> 2. **Active deterministic pipeline** (`compute_facts.py` → `rephrase_facts.py`):
>    all numbers computed in pure Python; the LLM only rephrases pre-computed facts
>    into French prose.
>
> `ml-service/PFE_RECAP_COMPLET.md` documents only the **obsolete** pipeline. The
> report below describes the **active** pipeline and flags the legacy one where
> relevant.

---

## 1. Overall Pipeline

### 1.1 Stage sequence (raw scraped data → final insights)

**Phase A — Offline data preparation** (run once; produces the artifacts Step 4 consumes):

| Stage | Script (`ml-service/scripts/`) | Function |
|---|---|---|
| A1 | `step4g_phase{1..5}_*.py` (+ `step4g_preflight_apify.py`) | Apify Instagram scrape, one phase per industry; downloads photos / carousel slides / reel videos+thumbnails |
| A2 | `step4g_reorganize_by_industry.py` | Reorganizes media into `data/step4/by_industry/<industry>/{photos,carousel_slides,reel_thumbs,videos}` |
| A3 | `step4h_01..09_*.py` | CLIP visual-feature lineage → `df_master_with_clip.parquet` |
| A4 | `train_bertopic.py` / `train_bertopic_v2.py` | BERTopic topic modeling → `df_master_masked_with_topics.parquet` |
| A5 | `phase3_features.py`, `add_features_v2.py`, `rebuild_brand_features.py` | Tabular feature engineering → `df_ml_dataset.parquet` |
| A6 | `step4i_build_v5_dataset.py` → `step4j_01_mpnet_pipeline.py` → `step4j_02_build_v5c_dataset.py` | V5 (topic one-hot) then V5c (+ MPNet caption PCA) dataset |
| A7 | `phase4_{rf,xgb,lgb}.py`, `step4i_train_v5_models.py`, `step4j_03_train_v5c_models.py`, `step4k_v6_stacking.py` | Train models + V6 stacker; emit SHAP cache `_shap_values_cached_xgb_v5c.npz` |
| A8 | `step4_llm_name_topics.py` | LLM-names BERTopic topics → `data/topics_v3_llm_named.yaml` |

**Phase B — Active Step-4 runtime path (exactly two scripts, per industry):**

| Stage | Script | Function |
|---|---|---|
| **B1** | **`ml-service/scripts/compute_facts.py`** | Deterministic facts layer. Docstring: *"This file moves every number into deterministic Python — pandas over the cleaned parquet + the SHAP cache + BERTopic topics. The LLM is no longer in the calculation path."* Writes `data/step4f_v6/facts/facts_<industry>.json` |
| **B2** | **`ml-service/scripts/rephrase_facts.py`** | LLM rephrasing (prose only). Docstring: *"The LLM (llama3.1) is NOT in the calculation path anymore. It receives ONLY the deterministic facts.json … and produces French dashboard prose."* Writes `data/step4f_v6/insights/insights_<industry>.json` |

`compute_facts.py:116-122` defines the exact input lineage:

```
MASTER_PATH = DATA / "df_master_masked_with_topics.parquet"
V5C_PATH    = DATA / "df_ml_dataset_v5c.parquet"
SHAP_CACHE  = DATA / "_shap_values_cached_xgb_v5c.npz"
TOPICS_YAML = DATA / "topics_v3_llm_named.yaml"
OUT_DIR     = DATA / "step4f_v6" / "facts"
```

### 1.2 Entry point

- **No standalone orchestrator script exists** for the active Step 4 (no `main.py`,
  no "run_all"). The README/recap documents only the obsolete RAG flow.
- **The de-facto entry point is the Node backend controller**
  `backend/src/controllers/insights.controller.js`. Route
  `POST /api/insights/:industry/regenerate`
  (`backend/src/routes/insights.routes.js`) calls `child_process.spawn` to run,
  blocking and in order:
  1. `.venv/Scripts/python.exe -X utf8 compute_facts.py --industry <ind>`
  2. `.venv/Scripts/python.exe -X utf8 rephrase_facts.py --industry <ind>`
  - `VALID_INDUSTRIES = ['hotels','restaurants','beauty','fashion','patisserie']`
    (`insights.controller.js:27`); socket timeout disabled because rephrasing is
    ~8–10 min/industry.
- `GET /api/insights/:industry` only **reads** the JSON file — it does not run Python.
- Each Python script also has its own `if __name__ == "__main__"` with
  `argparse --industry` (e.g. `compute_facts.py:1036-1056`).

---

## 2. Feature Extraction

### 2.1 Visual features — CLIP ✅ (used)

- **Model:** `MODEL_NAME = "openai/clip-vit-base-patch32"` — HuggingFace
  `transformers` `CLIPModel`, OpenAI weights. Defined identically in
  `step4h_01_setup_clip.py:23`, `step4h_02_embed_images.py:36`,
  `step4h_03_reel_frames.py:34`.
- **Embedding:** vision tower + `visual_projection`, L2-normalized.
  **Output dimension = 512** (asserted `step4h_02_embed_images.py:191`:
  `assert full.shape == (n, 512)`).
- **PCA: YES → 15 components.** `step4h_06_pca.py:33` `N_COMPONENTS = 15`;
  `:45` `pca = PCA(n_components=N_COMPONENTS, random_state=42)`. Output columns
  `clip_pc01..clip_pc15`; PCA model saved `models/clip_pca_15.joblib`.
- **Aggregation to post level:** reel = 5 frames at fractions
  `(0.10,0.30,0.50,0.70,0.90)` → mean-pooled + re-L2; then per post by
  `content_type`: single image as-is, carousel = mean of slides, reel =
  mean of [thumbnail, mean-reel-frames] (`step4h_04_aggregate_post.py:87-101`).
  *(Minor: the docstring says "0.5·thumb + 0.5·frames" but the code is an
  unweighted `np.mean` — equivalent only when both parts exist.)*

### 2.2 Semantic/text features — MPNet ✅ (used)

- **Model:** `MPNET_NAME = "paraphrase-multilingual-mpnet-base-v2"`
  (`step4j_01_mpnet_pipeline.py:62`), loaded via `SentenceTransformer(MPNET_NAME)`,
  `normalize_embeddings=True`. **Dimension = 768.** Text source = `caption_clean`.
- **PCA: YES → 15 components.** `step4j_01_mpnet_pipeline.py:65`
  `PCA_COMPONENTS = 15`; `:154` `PCA(n_components=PCA_COMPONENTS,
  random_state=SEED)` (`SEED=42`). Output `doc_pc01..doc_pc15`; saved
  `models/mpnet_pca_15.joblib`; joined into the V5c dataset.

### 2.3 Topic modeling — BERTopic ✅ (used)

Instantiation in `ml-service/src/corpus/topic_model.py:118-129` (scripts
`train_bertopic.py` / `_v2.py` delegate to it):

- **Internal embedder:** `EMBEDDING_MODEL_NAME =
  "paraphrase-multilingual-MiniLM-L12-v2"` (MiniLM — *deliberately different
  backbone from the §2.2 MPNet*).
- **UMAP:** `n_neighbors=15, n_components=5, min_dist=0.0, metric="cosine",
  random_state=42`
- **HDBSCAN:** `min_cluster_size=30, min_samples=5, metric="euclidean",
  cluster_selection_method="eom", prediction_data=True`
- **Vectorizer:** `CountVectorizer(ngram_range=(1,2), max_features=10000,
  stop_words=<FR∪EN∪AR multilingual list>)`
- `nr_topics="auto"`, `top_n_words=10`; post-hoc
  `reduce_outliers(strategy="c-tf-idf", threshold=0.3)`.
- **Resulting topic count:** v1 = **21** non-outlier topics, v2 = **20**
  (`data/v1_vs_v2_comparison.txt:7`). The production naming file
  `data/topics_v3_llm_named.yaml:8` reports `total_topics: 21` (includes the
  `-1` outlier topic, V3 subset). v1 trains on `caption_clean`; **v2 trains on
  brand-masked `caption_masked`** and is the version feeding the active pipeline.

### 2.4 Other engineered features

`phase3_features.py:191-208` defines **26 features in 4 groups**:

- **Group 1 — raw numerical (5):** `followers, brand_avg_likes,
  brand_engagement_rate, slide_count, views`
- **Group 2 — derived numerical (6):** `hashtags_count, caption_length,
  word_count, emoji_count, mention_count, has_caption`
- **Group 3 — temporal (8):** `hour, day_of_week, month, quarter, is_weekend,
  is_evening (18-23h), is_lunch (11-14h), days_since_first_post` (timestamps
  converted UTC→`Africa/Tunis`)
- **Group 4 — categorical & flags (7):** `content_type, industry_simple,
  topic_id, caption_lang, has_question, has_promo_word, is_holiday_period`

`add_features_v2.py:338-339` adds 4 more + overwrites `emoji_count`:
`is_ramadan` (hardcoded Tunisia Ramadan ranges), `caption_sentiment` (zero-shot,
model `cardiffnlp/twitter-xlm-roberta-base-sentiment`, score ∈ [-1,1]),
`has_emoji`, `has_cta` (FR/EN/AR CTA regex). Brand features
(`brand_avg_likes`, `brand_engagement_rate`) are **past-only expanding means**
(no look-ahead; `src/corpus/loader.py:74-103`), cold-start filled with
per-industry medians.

---

## 3. ML Models — Training & Comparison

### 3.1 Models trained

**Four estimator types: `RandomForestRegressor`, `XGBRegressor`,
`LGBMRegressor`, `RidgeCV`.** Note: the meta-model is **`RidgeCV`** (built-in
CV alpha selection) — there is **no plain `Ridge(alpha=...)`** anywhere. No
SVR/linear/NN/CatBoost. Version tokens: `v2, v3, v4, v5, v5c, v6 (v6a/v6b)`.

**Hyperparameter-tuned versions** (RF & XGB via
`RandomizedSearchCV(n_iter=50, cv=KFold(10))`; LGB via Optuna TPE, 50 trials ×
5-fold):

- **RF V3** (`phase4_ensemble.py:92-101`): `n_estimators=1000,
  min_samples_split=2, min_samples_leaf=1, max_features=0.33, max_depth=None,
  bootstrap=True`
- **XGB V3** (`phase4_ensemble.py:102-116`): `subsample=0.9, reg_lambda=5,
  n_estimators=500, min_child_weight=3, max_depth=10, learning_rate=0.01,
  gamma=0, colsample_bytree=0.9, objective="reg:squarederror",
  tree_method="hist"`
- **LGB V3** (`phase4_ensemble.py:117-137`): `n_estimators=313,
  learning_rate=0.028446, num_leaves=34, max_depth=7, min_child_samples=19,
  subsample=0.801594, colsample_bytree=0.68114, reg_alpha=1.18363,
  reg_lambda=0.00743663`

**Fixed-HP versions (V5/V5c/V6 reuse the V4-best params, no re-search)** —
`step4i_train_v5_models.py`:

- `RF_PARAMS` (`:51-60`): `n_estimators=1000, min_samples_split=2,
  min_samples_leaf=1, max_features=0.33, max_depth=None, bootstrap=True`
- `XGB_PARAMS` (`:61-75`): `n_estimators=1000, max_depth=5,
  learning_rate=0.05, subsample=0.7, colsample_bytree=0.7,
  min_child_weight=5, gamma=0, reg_lambda=10`
- `LGB_PARAMS` (`:78-94`): `n_estimators=1826, learning_rate=0.0297922,
  num_leaves=61, max_depth=8, min_child_samples=34, subsample=0.976562,
  colsample_bytree=0.597991, reg_alpha=2.55297e-08, reg_lambda=8.47175e-06`

### 3.2 Target variable

**`y_log = np.log1p(df["engagement_rate"])`** — models train on the log1p of
`engagement_rate`; predictions inverted via
`np.clip(np.expm1(...), 0, None)` for original-scale metrics. Consistent across
`phase4_rf.py:122-123`, `phase4_xgb.py:148-149`, `phase4_lgb.py:132-133`,
`step4i:106-107`, `step4j:69-70`, `step4k:101-102`.

### 3.3 Model comparison

**Metrics computed (6):** `r2_log`, `r2_orig`, `rmse_log`, `rmse_orig`,
`mae_orig`, `spearman_rho` (verbatim block `phase4_rf.py:232-239`, identical in
xgb/lgb/ensemble/step4i/step4j/step4k). **RMSE =
`sqrt(mean_squared_error(...))`. MAPE is NOT computed anywhere.**
`compare_v1_vs_v2.py` additionally adds `mae_log`.

**Comparison artifacts written** (under `ml-service/data/`):
`ensemble_v3_results.txt`, `rf_vs_xgb_comparison.txt` /
`multi_model_comparison.txt`, `feature_engineering_v2_rf_impact.txt`,
`v5_summary_report.txt`, `v5c_summary_report.txt`, `v6_summary_report.txt`;
prediction parquets `{rf,xgb,lgb}_{v3,v4,v5,v5c}_predictions.parquet`; figures
under `ml-service/visualizations/v{4,5,5c,6}/` and `ml-service/figures/`.

### 3.4 Stacking / ensemble

`step4k_v6_stacking.py:310-318` builds **two** stacked configs and the
meta-model **is `RidgeCV`**:

```
for name, models_used in [("v6a", ("rf", "xgb")),
                          ("v6b", ("rf", "xgb", "lgb"))]:
    X_meta_train = np.column_stack([oof[m] for m in models_used])
    X_meta_test  = np.column_stack([test_preds_log[m] for m in models_used])
    ridge = RidgeCV(alphas=RIDGE_ALPHAS, fit_intercept=True)
    ridge.fit(X_meta_train, y_train_log)
```

- **V6a = RF + XGB → RidgeCV meta-model** (the "2 models combined").
- **V6b = RF + XGB + LGB → RidgeCV meta-model.**
- `RIDGE_ALPHAS = (0.01, 0.1, 1.0, 10.0, 100.0)` (`:58`); base predictions are
  **5-fold out-of-fold** (Wolpert 1992 stacking, `N_FOLDS=5`).
- **Selection rule** (`:345-352`): `delta = r2_v6b − r2_v6a`; pick `v6b` if
  `delta ≥ 0.01` else `v6a` (parsimony).
- Both meta-learners saved unconditionally: `step4k_v6_stacking.py:676-677` →
  `models/meta_ridge_v6a.pkl` (634 B), `models/meta_ridge_v6b.pkl` (642 B) —
  both confirmed on disk.
- (`phase4_ensemble.py` has an earlier V3 "shootout": STACK-3 =
  `RidgeCV(alphas=np.logspace(-3,3,13))` over OOF(rf,xgb,lgb); it saves no
  model artifact.)

**On-disk model artifacts** (`ml-service/models/`, git-untracked but present):
full lineage `{rf,xgb,lgb}_{v3,v4,v5,v5c}.pkl` + `rf_best.pkl`/`xgb_best.pkl`
(V2) + `meta_ridge_v6a/b.pkl` + `clip_pca_15.joblib` + `mpnet_pca_15.joblib`.
**`lgb_best.pkl` (V2) is absent** — LightGBM V2 was never saved (lineage starts
at `lgb_v3`).

---

## 4. Explainability — SHAP ✅ (used)

- **SHAP is real.** `shap.TreeExplainer` on a 200-row
  `shap.sample(X_test, 200, random_state=SEED)`, computed **per tree model
  (RF, XGB, LGB) — NOT on the V6 Ridge stacker**.
- The Step-4-relevant cache is **XGBoost V5c**: produced in
  `step4j_03_train_v5c_models.py:138-140`
  (`explainer = shap.TreeExplainer(model)` → `shap_values`), saved
  `step4j_03_train_v5c_models.py:257-262` →
  **`data/_shap_values_cached_xgb_v5c.npz`**.
- **The active Step-4 pipeline does NOT recompute SHAP — it consumes the
  cache.** `compute_facts.py:281-288` loads the `.npz`, takes
  `np.abs(shap_values).mean(axis=0)` (magnitude) and `mean(axis=0)` (sign),
  ranks features, and surfaces top-5 in module `performance_predictors`
  (`compute_facts.py:874-891`) labelled
  `"model": "XGB V5c (interpretive proxy for V6 stacking)"`, with reported
  `model_r2_log = 0.4587`, `model_rho = 0.6686`, `n_test_sample = 200`. XGB
  V5c is explicitly used as the **interpretive proxy** for the V6 RidgeCV
  stacker. Training scripts also emit SHAP beeswarm PNGs / Plotly HTML (not in
  the runtime path).

---

## 5. Insights Generation (LLM)

### 5.1 LLM backend ✅ confirmed: Ollama + llama3.1

`rephrase_facts.py:68-71` and `:793-800`:

```
LLM_MODEL    = "llama3.1:latest"
TEMPERATURE  = 0.0
MAX_TOKENS   = 700
TIMEOUT_S    = 180
...
llm = OllamaLLM(model=LLM_MODEL, temperature=TEMPERATURE,
                num_ctx=4096, num_predict=MAX_TOKENS, timeout=TIMEOUT_S)
```

- **Exact model tag: `"llama3.1:latest"`** (not `:8b` / `q4_K_M`). Backend =
  `langchain_ollama.OllamaLLM`; **no explicit URL** (langchain default
  `http://localhost:11434`); **no `seed`/`top_p`** set. Temperature **0.0**
  (determinism). *(Legacy `step4f_v6_03` uses temp 0.3, num_ctx 8192, 1500
  tokens — deprecated.)*

### 5.2 How facts + templates become prompts; the Q1–Q10 hybrid

The 10 questions (`rephrase_facts.py:78-89`): Q1 Content Strategy, Q2 Optimal
Timing, Q3 Visual Strategy, Q4 Content Themes, Q5 Hashtag Strategy, Q6 Brand
Differentiation, Q7 30-day Calendar, Q8 Engagement Tactics, Q9 Current Trends,
Q10 Performance Predictors.

**Hybrid dispatch** (`rephrase_facts.py:500-502`):
`if q["module"] in TEMPLATE_DISPATCH: return _template_one(...)` — templated
modules never call the LLM. The authoritative registry
`_template_modules.py:840-847` contains **six** modules:

| Q | Module | Path |
|---|---|---|
| Q1 | content_strategy | **TEMPLATE (no LLM)** |
| Q2 | optimal_timing | **LLM** |
| Q3 | visual_strategy | **LLM** |
| Q4 | content_themes | **TEMPLATE (no LLM)** |
| Q5 | hashtag_strategy | **TEMPLATE (no LLM)** |
| Q6 | brand_differentiation | **TEMPLATE (no LLM)** |
| Q7 | calendar_30d | **LLM** |
| Q8 | engagement_tactics | **TEMPLATE (no LLM)** |
| Q9 | current_trends | **LLM** |
| Q10 | performance_predictors | **TEMPLATE (no LLM)** |

→ **6 deterministic-template / 4 LLM (Q2, Q3, Q7, Q9).**

> ⚠️ **Documentation discrepancy worth citing in the report:** the inline
> comment at `rephrase_facts.py:60-61` says *"Q1/Q4/Q5/Q8/Q10 deterministic;
> Q2/Q3/Q6/Q7/Q9 LLM"* (5 templated), and `_template_modules.py:14` says
> *"Five modules"* — but the actual `TEMPLATE_DISPATCH` dict lists **six**
> (Q6 `brand_differentiation` was added later, per the docstring note at
> `_template_modules.py:24-26`: *"Q6 was added to the templated set after a
> live review found the LLM still hallucinating a CTA contradiction into
> patisserie/Q6"*). The runtime behaviour follows the **dict (6 templated)**;
> the comments are stale.

**Prompt structure (LLM path only):**
`full = f"{SYSTEM_PROMPT}\n\n{user_prompt}"` then `llm.invoke(full)`.

- `SYSTEM_PROMPT` (`rephrase_facts.py:95-168`), in French: *"Tu rédiges, en
  français, le résumé d'un tableau de bord marketing tunisien. Tu reçois UN
  SEUL BLOC DE FAITS JSON déjà calculé. Tu le REFORMULES, tu n'ajoutes
  RIEN…"* — 5 non-negotiable rules (numbers copied character-for-character, no
  computation; SHAP magnitude always positive; technical names untranslated;
  recommendations follow the data sign; invent nothing outside the JSON).
  Mandates output: `RÉSUMÉ:` / `PREUVES:` (3 bullets) / `RECOMMANDATIONS:`
  (3 numbered).
- `USER_PROMPT_TEMPLATE` (`:170-178`): `SECTEUR: {industry}`,
  `MODULE: {module_title}`, then the module's facts block as fenced JSON
  ("source unique de vérité").
- Post-processing: parsed → verified against the facts number-set
  (`_verify_prose`) → up to `MAX_REPAIR_RETRIES=2` LLM repair calls (keeps
  fewest-criticals answer) → no-LLM `_determ_er_repair` fixes residual ×100
  engagement-rate hallucinations.

### 5.3 Per-industry generation

Yes — looped. `rephrase_facts.py:66`
`INDUSTRIES = ["beauty","fashion","hotels","patisserie","restaurants"]`; loop
`rephrase_facts.py:810` `for ind in industries:` then `:834`
`for q_idx, q in enumerate(QUESTIONS, 1):`. Same 5-industry list in
`compute_facts.py:124`, `step4f_v6_01:41`, backend `insights.controller.js:27`.
**The 5 industries: beauty, fashion, hotels, patisserie, restaurants.**

### 5.4 Output artifacts

- `compute_facts.py:1056-1058` →
  `ml-service/data/step4f_v6/facts/facts_<industry>.json` (5 files, ~26–28 KB).
- `rephrase_facts.py:859-861` →
  `ml-service/data/step4f_v6/insights/insights_<industry>.json` (5 files,
  ~23–24 KB) — **this is what the dashboard serves.**
- **No MongoDB persistence for Step 4.**
  `backend/src/controllers/insights.controller.js:70-86` reads the JSON file
  and returns it directly; no `Insight.create/save`. The Mongoose `Insight`
  model (`backend/src/models/Insight.model.js`) is `projectId`-scoped,
  unrelated, and only **read** in `project.controller.js:279` — never written.
  Step-4 persistence is **file-based JSON only**.

---

## 6. Data

**Inputs consumed by the active Step 4 (`compute_facts.py`), all in
`ml-service/data/`:**

- `df_master_masked_with_topics.parquet` — 3.42 MB (BERTopic-v2 output;
  ~4127 rows)
- `df_ml_dataset_v5c.parquet` — 933 KB (~4010 × 84)
- `_shap_values_cached_xgb_v5c.npz` — ~227–299 KB
- `topics_v3_llm_named.yaml` — 23 KB (21 named topics)

**Upstream raw data:** Apify Instagram scrape payloads
`ml-service/data/step4/metadata/apify_{beauty,fashion,hotels,patisserie,restaurants}.json`
(4.5–13.3 MB each); consolidated `df_master.csv` = **5,017,143 bytes /
~19,184 rows**, 21 columns (`post_id, post_url, username, industry, …, likes,
comments, views, engagement_rate, published_at, followers, brand_avg_likes, …,
image_url, video_url`). Per-industry media under
`data/step4/by_industry/<industry>/{photos,carousel_slides,reel_thumbs,videos}`
(binary; feeds the CLIP lineage, not the facts pipeline). The 5 industry
directories: **beauty, fashion, hotels, patisserie, restaurants**.

---

## Expected-but-absent / unexpected-present (explicit)

- **Expected & present:** CLIP (ViT-B/32), MPNet (multilingual), BERTopic, PCA
  (15+15), XGBoost/RF/LightGBM, SHAP, Ollama llama3.1, per-industry loop.
- **Differs from expectation — "Ridge meta-model":** it is **`RidgeCV`**
  (CV-selected alpha), not a plain `Ridge`; and stacking is **two configs**
  (V6a RF+XGB, V6b RF+XGB+LGB) with a parsimony selector.
- **Unexpected/important:**
  1. **Two pipelines** — the documented RAG/Chroma+LLM Step 4 is
     **deprecated**; production is the deterministic
     `compute_facts → rephrase_facts`.
  2. **The LLM does not compute anything** — only rephrases (temp 0.0); 6 of
     10 questions bypass the LLM entirely.
  3. SHAP is on **XGB V5c as an interpretive proxy** for the V6 Ridge stacker,
     **consumed from cache** (not recomputed in Step 4).
  4. **No MongoDB** persistence for Step-4 insights (file-based JSON).
  5. Stale in-code comments say "5 templated"; runtime is **6 templated**.
  6. `lgb_best.pkl` (V2) absent on disk.
  7. BERTopic uses a **MiniLM** backbone, distinct from the §2.2 MPNet.

---

*End of audit. No code, configuration, or scripts were modified during this
investigation; this document is the sole artifact produced.*
