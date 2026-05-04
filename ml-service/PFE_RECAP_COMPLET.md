# PFE_RECAP_COMPLET

> Comprehensive reference document for thesis writing and defense preparation.
> Generated at end of session 2026-05-03. Consult during PowerPoint preparation,
> rehearsal, and Q&A.

---

## 1. Project Overview

- **Title** — AI Marketing Intelligence Agent for Tunisia
- **Student** — Amira (Master AI & IoT)
- **Objective** — End-to-end 5-step pipeline that turns a business idea into an actionable marketing plan:
  1. **Input** — user describes their business idea / brand
  2. **Market research** — discovery of competitors via SerpAPI/Tavily
  3. **Social scraping** — Instagram/Facebook content from competitors
  4. **AI insights** — BERTopic + ML predictions (Random Forest V3) + RAG with Llama 3.1
  5. **Campaign generation** — 30-day content calendar per brand, scored by RF V3
- **Tech stack**
  - Frontend — Next.js
  - Backend — Express (Node.js), MongoDB Atlas, JWT auth, node-cron
  - Scraping — Playwright + stealth, Puppeteer + adblocker, Crawl4AI (Python FastAPI microservice via uv)
  - ML — Python 3.10, scikit-learn, XGBoost (<3.0), LightGBM, SHAP 0.49
  - NLP — BERTopic (multilingual MiniLM-L12-v2), HuggingFace transformers, XLM-RoBERTa for sentiment
  - LLM / RAG — Ollama 0.22.1 (local), Llama 3.1, Mistral, Chroma DB, LangChain 1.x (split into `langchain-chroma` + `langchain-huggingface` + `langchain-classic`)
- **Scope** — 5 industries × 41 brands in Tunisia
  - Hotels, Restaurants, Beauty, Fashion, Patisserie

---

## 2. Dataset Pipeline

| Stage | File | Rows | Cols | Description |
|---|---|---:|---:|---|
| Raw scrape | `data/df_master.parquet` | 4127 | — | Combined Instagram posts from 41 brands |
| Cleaned | `data/df_master_clean.parquet` | 4127 | — | Deduplicated, normalized timestamps |
| Anonymized | `data/df_master_masked.parquet` | 4127 | — | Brand names masked in captions for downstream NLP |
| + Topics | `data/df_master_masked_with_topics.parquet` | 4127 | 28 | BERTopic v2 `topic_id` joined |
| ML V1 | `data/df_ml_dataset.parquet` (V1 backup) | 4127 | 28 | Baseline features |
| ML V2 | `data/df_ml_dataset.parquet` | 4127 | 32 | + 4 cultural features |
| ML V3 | `data/df_ml_dataset_v3.parquet` | **4087** | 32 | After ±1 % outlier filter per industry |

**V3 industry distribution** (final ML dataset):
| Industry | Posts | Share |
|---|---:|---:|
| Hotels | ~907 | 22.2 % |
| Fashion | ~842 | 20.6 % |
| Restaurants | ~817 | 20.0 % |
| Beauty | ~816 | 20.0 % |
| Patisserie | ~745 | 18.2 % |

Industry balance is approximately even — no class skew bias in training.

---

## 3. Phase 4 — ML Iterations

### V1 — Baseline (post-leakage fix)

- **Data leakage detected and fixed** following Kaufman et al. (2012):
  - Removed from features: `views`, `likes`, `comments`, `shares`, `engagement_rate` (target)
  - Brand-historical features computed using `shift(1).expanding().mean()` per brand (past-only); first post imputed with industry median (Trivedi 2019 / Chen 2022)
- **RF V1 (post-fix)** — R² (log) = **0.316**, ρ = **0.654**
- **XGB V1** — R² (log) = 0.293, ρ = 0.635
- Pre-fix biased numbers (R²=0.513, ρ=0.773) discarded as they used post-publication metrics

### V2 — Cultural Features

Added 4 Tunisia-specific features:
1. `is_ramadan` — boolean for Ramadan periods 2023-2026
2. `caption_sentiment` — XLM-RoBERTa multilingual sentiment score [-1, +1]
3. `has_emoji` — boolean
4. `has_cta` — call-to-action detection in FR / EN / AR

- **RF V2** — R² (log) = **0.323** (+2.2 % vs V1, honest finding)
- Marginal improvement reported as such (no overclaim)
- `caption_sentiment` particularly useful for Spearman ρ improvement
- Marketing data is naturally **76.9 % positive sentiment, mean = +0.56** — not a bug

### V3 — Outlier Filtering

- **Filter applied**: top/bottom 1 % per industry on `engagement_rate` (-40 posts)
- **`brand_age` filter REJECTED** as too aggressive (would create production blind spot for young brands)
- 4127 → **4087** rows (-1.0 %)
- All three models (RF / XGB / LGB) retrained on V3
- Champion identified via CV mean RMSE — **RF V3** (see §4)

---

## 4. V3 Models — Definitive Results

| Metric | RF V3 🥇 | XGB V3 | LGB V3 |
|---|---:|---:|---:|
| R² (log) | **0.3656** | 0.3472 | 0.3416 |
| R² (orig) | 0.2465 | 0.2293 | 0.2414 |
| Spearman ρ | **0.6515** | 0.6472 | 0.5904 |
| RMSE (log) | **0.2479** | 0.2514 | 0.2525 |
| MAE (orig) | 0.2375 | 0.2363 | 0.2430 |
| CV mean RMSE (5-fold) | **0.2670** | 0.2670 | 0.2672 |

**Final hyperparameters (chosen after tuning):**

- **RF V3** — `n_estimators=1000`, `max_depth=None`, `max_features=0.33`
- **XGB V3** — `n_estimators=500`, `max_depth=10`, `learning_rate=0.01`, `reg_lambda=5`
- **LGB V3** — literature-driven (Sigrist 2025): `num_leaves=34`, `learning_rate=0.0285`

**LGB anomaly noted**: Spearman ρ (0.5904) trails RF/XGB despite competitive RMSE, suggesting LGB ranks borderline cases less consistently. Not a blocker (RF V3 is champion) but worth flagging in defense.

---

## 5. Cross-Model SHAP Consensus (Key Discovery)

Top 5 SHAP features are **identical across RF, XGB, and LGB on V3** — proof that the signal is intrinsic to the data, not a model artifact.

| Rank | Feature | SHAP importance (RF V3) |
|---:|---|---:|
| 1 | `brand_engagement_rate` | 0.34 |
| 2 | `days_since_first_post` | 0.21 |
| 3 | `followers` | 0.15 |
| 4 | `industry_simple_restaurants` | 0.10 |
| 5 | `content_type_reel` | 0.08 |

**Interpretation**: brand-level signals (history, age, audience) dominate post-level signals. Reels and the restaurants industry have measurable engagement uplift across all three model families.

---

## 6. Ensemble Strategies (4 tested — ALL rejected)

| Ensemble | Method | R² (log) | CV mean RMSE | Verdict |
|---|---|---:|---:|---|
| AVG-3 | Equal weights RF+XGB+LGB | ~0.366 | 0.2672 | reject |
| WAVG-3 | Inverse-RMSE weights | 0.3665 | 0.2672 | reject |
| STACK-3 | Wolpert (1992) stacking, ridge meta | ~0.365 | 0.2674 | reject |
| AVG-2 | RF + XGB | ~0.364 | 0.2672 | reject |

- Best ensemble (WAVG-3 R²=0.3665) beats RF V3 by +0.0009 — **within noise**.
- **CV mean RMSE: RF V3 = 0.2670 BEAT all ensembles** (≥0.2672).
- **Decision** — RF V3 retained as production model. Justifications:
  - Occam's razor (single model, simpler to maintain)
  - 3× faster inference vs ensemble
  - Equivalent quality on held-out CV
  - Defensible in thesis as a deliberate negative result

---

## 7. Visualizations (30 + PNGs)

Located in `ml-service/visualizations/v3/`:

- **Pred vs Actual** scatter (RF, XGB, LGB)
- **Residuals** by predicted value, by industry, by content_type
- **SHAP beeswarm** plots
- **Gini importance** bar charts
- **V2 vs V3 comparison** plots
- All six combinations: {RF, XGB, LGB} × {V2, V3}

Cached SHAP arrays: `data/_shap_values_cached_{rf,xgb,lgb}_v3.npz` (avoid re-computing during defense rehearsal).

---

## 8. Data Leakage Audit (Key Differentiator)

**Principle** — Train/Inference Symmetry (Kaufman, Rosset, Perlich 2012). Any feature unavailable at inference time must be excluded from training.

**Audit results** — all post-publication metrics (`views`, `likes`, `comments`, `shares`) excluded. The target `engagement_rate` is held out of features. Brand-history features use `shift(1).expanding().mean()` per brand (past-only).

**Why our R² = 0.3656 is honest:**

| Source | R² | Notes |
|---|---:|---|
| Trivedi (2019) | 0.32 | Reproducible, leakage-audited |
| Chen (2022) | 0.28 | Reproducible |
| Mishra (2025) | 0.35 | Reproducible |
| Stanford Kim & Hwang (2025) | 0.41 | Larger dataset |
| **Our RF V3** | **0.3656** | ✅ Aligned with literature |
| Some published papers | >0.7 | ❌ Likely undetected leakage (use post-publication metrics as features) |

**Spearman ρ = 0.6515** falls in the **"good correlation"** range per Cohen (1988) — operationally relevant for ranking campaign post ideas, which is the primary downstream use.

---

## 9. BERTopic + LLM Naming Pipeline

- **Model** — BERTopic v2, multilingual `paraphrase-multilingual-MiniLM-L12-v2` (384-dim)
- **Output** — 21 topics (`topic_id` 0..19) + outliers (`-1`)
- **Stored at** — `ml-service/models/bertopic_v2/`

### Bug detected proactively

The original `topics_validated.yaml` was generated against `df_master_with_topics.parquet` (unmasked), but V3 uses `df_master_masked_with_topics.parquet`. The two BERTopic runs produced different topic ID orderings → topic names were heavily misaligned with V3 IDs (e.g., "Beauté – cheveux" was actually 100 % fashion content; "Pâtisserie – gâteaux" was 95 % restaurants).

### Solution — Llama 3.1 LLM-based renaming

- Script: `scripts/step4_llm_name_topics.py`
- Each topic prompted with: BERTopic c-TF-IDF top 10 keywords + V3 top hashtags + industry distribution + top brands + 3 example captions (highest engagement)
- Llama 3.1 with `temperature=0.0`, `num_predict=20` → deterministic
- **44 sec total**, **2.2 sec/topic** average, 20 LLM calls (outliers got fixed name without LLM)
- 21 names generated; 19/21 validated as-is; 2 manually corrected after review

### Manual corrections (2 of 21)

| Topic | Before (LLM) | After (manual) | Reason |
|---:|---|---|---|
| 0 | Winter Beauty Giveaways | **Multi-Industry Lifestyle** | Multi-industry mega-cluster (beauty 27 %, fashion 25 %, patisserie 20 %, restaurants 18 %, hotels 10 %), not beauty-specific |
| 6 | Zara SS26 Collection | **Pull&Bear Fashion Collection** | Dominant brand is Pull&Bear (61 %), not Zara — LLM was biased by `#zara` hashtags in caption mentions |

- Backup: `data/topics_v3_llm_named.yaml.bak`
- YAML comments document the rename rationale inline above each renamed entry

---

## 10. ML / Labels Independence Audit (3 Proofs)

Before manually editing topic names, formal verification that this could not affect ML metrics:

| Q | Question | Answer | Evidence |
|---:|---|---|---|
| Q1 | Do trained models use `topic_id` as a feature? | **YES** — integer at index 17 | `rf_v3_feature_columns.json` / `xgb_v3_feature_columns.json` / `lgb_v3_feature_columns.json` all 38 features identical, no `topic_name` field |
| Q2 | Will renaming affect R²/ρ/RMSE/SHAP? | **NO** | (1) Models pickled to `.pkl` — frozen; (2) YAML never read during training (didn't exist); (3) Tree splits on integer `topic_id`, not strings |
| Q3 | Are V3 dataset `topic_id`s aligned with YAML keys? | **YES** — 100 % | Set equality on `{-1, 0, 1, ..., 19}`; per-topic counts match exactly for all 21 topics |

→ Renaming proven safe. RF V3 metrics (R²=0.3656, ρ=0.6515, RMSE=0.2479) **frozen**.

---

## 11. Final Topic Names (after manual corrections)

From `data/topics_v3_llm_named.yaml`:

| Tid | Name | n_v3 | Dominant Industry | Decision |
|---:|---|---:|---|---|
| -1 | Outliers (mixed content) | 1029 | fashion 30 % | KEEP_AS_OTHER |
| 0 | **Multi-Industry Lifestyle** ✏️ | 1145 | beauty 27 % | KEEP_BUT_BIG |
| 1 | Hotel Reviews Tunisia | 643 | hotels 45 % | KEEP_BUT_BIG |
| 2 | Ramadan Beauty Routine | 274 | beauty 33 % | KEEP |
| 3 | Ramadan Restaurant Vibes | 154 | hotels 47 % | KEEP |
| 4 | Tunisian Skincare Routine | 93 | beauty 99 % | KEEP |
| 5 | Love on Valentine's Day | 86 | hotels 31 % | KEEP |
| 6 | **Pull&Bear Fashion Collection** ✏️ | 74 | fashion 97 % | KEEP |
| 7 | Anti Aging Skincare | 68 | beauty 100 % | KEEP |
| 8 | Papa John's Promotions | 62 | restaurants 97 % | KEEP |
| 9 | Cocktail Bar Promotions | 61 | restaurants 41 % | KEEP |
| 10 | Chocolat Gourmet Delights | 50 | patisserie 94 % | KEEP |
| 11 | Hotel Summer Offers | 49 | hotels 96 % | KEEP |
| 12 | Summer Fashion Inspiration | 46 | fashion 57 % | KEEP |
| 13 | Haircare and Beauty Tips | 44 | beauty 100 % | KEEP |
| 14 | Eid Festive Wear Collection | 42 | fashion 100 % | KEEP |
| 15 | Fried Chicken Frenzy | 39 | restaurants 95 % | KEEP |
| 16 | Eid Collection Denim | 33 | fashion 100 % | KEEP |
| 17 | Summer Beauty Essentials | 33 | beauty 100 % | KEEP |
| 18 | Turkish Patisserie Delights | 32 | patisserie 84 % | KEEP |
| 19 | Pizza in Ramadan | 30 | restaurants 100 % | KEEP |

✏️ = manually corrected.

---

## 12. Step 4 Status — RAG Pipeline

### Completed

| Sub-step | Status | Artifact / Outcome |
|---|---|---|
| **4a — Diagnostic** | ✅ | Ollama 0.22.1 installed (Windows app), `llama3.1:latest` + `mistral:latest` ready. Diagnosed 5 missing Python packages |
| **4b — Smoke test** | ✅ | 4/4 tests passed (LangChain + Chroma + Llama 3.1). Two stack-level fixes documented: `PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python` env var; `from langchain_classic.chains import RetrievalQA` |
| **4-PRE — Topic inspection** | ✅ | Detected misalignment between `topics_validated.yaml` and V3 `topic_id`s. Generated full quality report |
| **4-LLM — Topic naming** | ✅ | 21 topics renamed via Llama 3.1 (44 sec, 2.2 s/topic). Output: `data/topics_v3_llm_named.yaml` |
| **4-AUDIT — Independence** | ✅ | 3 technical proofs that renaming topics doesn't affect ML metrics |
| **4-RENAME — Manual fixes** | ✅ | Topics 0 and 6 corrected with inline comments. Backup at `data/topics_v3_llm_named.yaml.bak` |
| **4c — Documents** | ✅ | 182 RAG docs generated across 5 types: 21 topic_summary + 105 top_post + 41 brand_summary + 5 industry_summary + 10 ml_insight |
| **4c — Quality audit** | ✅ | 7 dimensions checked. VERDICT: READY |
| **4d — Chroma indexation** | ✅ | 182 vectors @ 384 dim, persisted to `data/step4/chroma_db/` (1.7 MB). 5 test queries — all returning correct top-1. Multilingual cross-language search confirmed (English query → Arabic content retrieved) |

### Pending (next session)

- **4e — RAG insights generation** via Llama 3.1
  - 5 industries × 5 questions = 25 insights
  - Output: `data/step4/insights/insights_<industry>.json`
  - Estimated runtime: ~45 min

---

## 13. Step 5 — Campaign Generator (TO DO)

- **Input** — Step 4e insights + RF V3 model + brand context (industry, follower count, historical performance)
- **Output** — 30-day content calendar per brand
- **Key innovation** — RF V3 used **actively** to score post ideas, creating a feedback loop between ML and campaign generation
- **Estimated effort** — 3-4 hours

---

## 14. Files Reference

### Datasets

```
ml-service/data/
├── df_master_masked_with_topics.parquet    4127 × 28
└── df_ml_dataset_v3.parquet                4087 × 32
```

### Models

```
ml-service/models/
├── rf_v3.pkl                  CHAMPION   246 MB
├── xgb_v3.pkl                              6.6 MB
├── lgb_v3.pkl                              824 KB
├── rf_v3_feature_columns.json
├── xgb_v3_feature_columns.json
├── lgb_v3_feature_columns.json
└── bertopic_v2/               (config.json, ctfidf.safetensors, topic_embeddings.safetensors, topics.json)
```

### Step 4 artifacts

```
ml-service/data/
├── topics_v3_llm_named.yaml       21 topics named, 2 manually corrected
├── topics_v3_llm_named.yaml.bak   backup before manual corrections
└── step4/
    ├── documents.json             182 RAG documents (118 KB)
    └── chroma_db/                 vector store, 1.7 MB
```

### Scripts

```
ml-service/scripts/
├── phase4_rf.py                       RF training (parametrized v2/v3)
├── phase4_xgb.py                      XGBoost training
├── phase4_lgb.py                      LightGBM training
├── phase4_v3_filter.py                ±1 % outlier filter per industry
├── phase4_ensemble.py                 4 ensemble strategies
├── step4_inspect_topics.py            BERTopic V3 quality report
├── step4_llm_name_topics.py           Llama 3.1 LLM-based topic naming
├── step4_prepare_documents.py         RAG documents builder (5 types)
├── step4_check_documents.py           Quality audit (7 dimensions)
├── step4_index_chroma.py              Chroma indexation + 5-query smoke test
└── step4_smoke_test.py                Step 4 stack smoke test (4 components)
```

---

## 15. Bibliographic References

### ML / Methodology

- Kaufman S., Rosset S., Perlich C. (2012) — *Leakage in Data Mining: Formulation, Detection, and Avoidance.* ACM TKDD.
- Sigrist F. (2026) — *Optimal Hyperparameters for LightGBM.* (used for V3 LGB tuning)
- Bartz-Beielstein T. et al. (2023) — *Hyperparameter Tuning for Machine Learning.* Springer.
- Hastie T., Tibshirani R., Friedman J. (2009) — *The Elements of Statistical Learning.* Springer (ESL).
- Sculley D. et al. (2015) — *Hidden Technical Debt in Machine Learning Systems.* NeurIPS.
- Cohen J. (1988) — *Statistical Power Analysis for the Behavioral Sciences.* (Spearman ρ thresholds)

### Topics / NLP

- Grootendorst M. (2022) — *BERTopic: Neural topic modeling with a class-based TF-IDF procedure.*
- Blei D., Ng A., Jordan M. (2003) — *Latent Dirichlet Allocation.* JMLR.

### LLM / RAG

- Lewis P. et al. (2020) — *Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks.* NeurIPS.
- Meta AI (2024) — *Llama 3.1.*
- Chase H. (2022) — *LangChain.*

### Instagram engagement benchmarks

- Trivedi (2019) — R² = 0.32
- Chen (2022) — R² = 0.28
- Kim H. & Hwang J., Stanford (2025) — R² = 0.41
- Mishra (2025) — R² = 0.35

### Ensemble methods

- Wolpert D. (1992) — *Stacked Generalization.* Neural Networks.
- Breiman L. (1996) — *Stacked Regressions.* Machine Learning.

### Imputation / Brand features

- Trivedi P. (2019), Chen et al. (2022) — Industry-median imputation justification for first-post brand features.
- Ju X. (2024), Mishra (2025) — Filter-don't-fill rationale for engagement zeros.

---

## 16. Anticipated Jury Questions + Prepared Answers

**Q: "Why R² = 0.37 and not 0.85 like some papers report?"**

**A:** Our R² is **honest** and aligned with reproducible literature (Trivedi 0.32, Chen 0.28, Mishra 0.35, Stanford 0.41). Higher R² in some papers indicates **undetected data leakage** — they use post-publication metrics (views, likes, comments) as features, which are unavailable at inference time. We applied Train/Inference Symmetry (Kaufman 2012) so the model is **deployable**, not just a retrospective fit. Spearman ρ = 0.6515 confirms operational quality for ranking campaign ideas (Cohen 1988 "good correlation").

**Q: "Why no ensemble?"**

**A:** Four ensembles were tested — AVG-3, WAVG-3, STACK-3 (Wolpert 1992), AVG-2. **None exceeded RF V3 by more than 0.5 % RMSE.** CV mean RMSE: RF V3 = 0.2670 ≤ all ensembles (≥0.2672). RF V3 generalizes better. Occam's razor + 3× faster inference + equivalent quality → single model retained. This is a **deliberate negative result**, not a default choice.

**Q: "Why BERTopic and not LDA?"**

**A:** BERTopic is **multilingual-robust** (paraphrase-multilingual-MiniLM-L12-v2 handles FR/EN/AR in one embedding space), supports **automatic K discovery** via HDBSCAN, and has become a **2022+ academic standard** (Grootendorst 2022). LDA is inadequate for short Instagram captions (most under 200 chars). LLM-based topic modeling (e.g., GPT-4) was rejected as too costly for 4127 captions and not reproducible without API access.

**Q: "How did you handle the topic naming bug?"**

**A:** Misalignment between `topics_validated.yaml` (validated against unmasked data) and V3 `topic_id`s (from masked data) was **detected proactively** during a quality audit. Solution: rename via Llama 3.1 with deterministic settings (T=0). Each topic prompted with BERTopic c-TF-IDF keywords + V3 hashtags + industry distribution + top brands + example captions. 21 names in 44 sec. Two manually corrected after review. **Audit trail preserved** via YAML inline comments + `.bak` file. ML/Labels independence formally verified before editing — RF V3 metrics frozen.

**Q: "Why only 5 industries?"**

**A:** PFE scope constraint, with focus on **quality over breadth**. Architecture is industry-agnostic — adding a 6th industry only requires (1) scraping new brands, (2) re-running BERTopic, (3) RF V3 retraining. The pipeline is extensible.

**Q: "What about the LightGBM Spearman anomaly?"**

**A:** LGB V3 has competitive RMSE (0.2525 vs RF 0.2479) but lower ρ (0.5904 vs 0.6515). Hypothesis: LGB's leaf-wise growth on `num_leaves=34` over-specializes locally on the dominant patterns and ranks borderline cases inconsistently. Not a blocker — RF V3 is champion. Documented as an honest model-family observation.

**Q: "How do you ensure reproducibility?"**

**A:** Three mechanisms — (1) all `random_state=42`; (2) versioned datasets with `.bak_v1/.bak_v2/.bak_preleakfix` snapshots; (3) deterministic LLM naming (`temperature=0`); (4) cached SHAP arrays so plots regenerate identically.

---

## 17. Key Strengths for Defense

1. ⭐ **Explicit data leakage audit** — Kaufman 2012 train/inference symmetry, with both biased PRE-FIX (R²=0.513) and honest POST-FIX (R²=0.316 → 0.366 V3) numbers reported. **Differentiator** vs papers reporting >0.7 without leakage check.
2. ⭐ **V1 → V2 → V3 iterative methodology** — each version justified by a specific design question, with versioned backups (`.bak_v1`, `.bak_v2`, `.bak_preleakfix`).
3. ⭐ **3-model + 4-ensemble comparison** — RF / XGB / LGB benchmarked rigorously; ensembles formally rejected via CV.
4. ⭐ **Cross-model SHAP consensus** — top 5 features identical across all three model families → signal is intrinsic, not artifact.
5. ⭐ **Bug detection + LLM-based resolution** — proactive identification of `topics_validated.yaml` misalignment; deterministic LLM naming; manual corrections with audit trail.
6. ⭐ **Operational metric Spearman ρ = 0.6515** — directly relevant to the campaign-ranking downstream task.
7. ⭐ **Honest R² = 0.3656** vs literature — falls within the reproducible-paper distribution (0.28-0.41).
8. ⭐ **Rigorous versioning** — every iteration produces a backup; `.bak` files visible in `git status`.
9. ⭐ **Explicit RAG / ML separation** — labels and predictions are architecturally independent; topic renames cannot regress ML metrics (formally proven).
10. ⭐ **End-to-end RAG stack working** — Chroma + multilingual embeddings + Llama 3.1, validated on 5 sample queries with semantically-correct top-1 retrieval.

---

## 18. Current State (end of session 2026-05-03)

### ✅ Done today (17 sub-steps)

- Phase 4 V3 complete (RF / XGB / LGB on V3, ensembles tested, cross-model SHAP)
- Step 4 a/b/c/d complete (RAG pipeline ready)
- 182 documents indexed in Chroma DB (1.7 MB)
- All ML model files intact (no retraining; metrics frozen)
- Topic naming bug detected, resolved via LLM, 2 manual corrections applied
- ML/Labels independence formally audited

### 🔄 Pending (next session)

| Task | Estimated time |
|---|---:|
| Step 4e — RAG insights generation via Llama 3.1 | ~45 min |
| Step 5 — Campaign Generator | ~3-4 h |
| PowerPoint slides | ~2-3 h |
| Defense rehearsal | ~2 h |
| **Total remaining** | **~10 h** |

**Defense window** — ~1 week.

---

*End of recap. Good luck with the defense.*
