# Session summary — 2026-05-07

## 1. Work completed today

**Session focus:** Step 4h CLIP pipeline + RF/XGB/LGB V4 training + full ablation visualizations.

**Pre-existing context (carried into the session):** the 5-industry scraping (beauty, fashion, hotels, patisserie, restaurants — 4127 posts, 10 253 visual assets organized in `ml-service/data/step4/by_industry/`) was already complete before this session opened. Today's work consumed those assets; it did not generate them.

### Step 4h — CLIP visual feature pipeline (9 sub-steps)

1. **Setup CLIP ViT-B/32** via HuggingFace `transformers` on CPU, 151 M params, 512-dim projection. Smoke test passed (L2 norm = 1.000).
2. **Embedded all 8730 images** (`photos`, `carousel_slides`, `reel_thumbs`) — 14 min, avg 10.5 img/s.
3. **Reel frames** — 5 evenly spaced frames per reel (10/30/50/70/90 % positions), 1523 reels × 5 = **7615 frames**, 0 bad videos, 15.4 min.
4. **Per-post aggregation:** photo = 1 emb, carousel = mean of slides, reel = avg(thumb, mean of frames). 4048 / 4127 posts have an embedding (79 had no scraped visual).
5. **t-SNE 2D viz** colored by industry — silhouette 0.225 (2D), 0.077 (raw 512D cosine).
6. **PCA 512 → 15** — 47.5 % cumulative variance.
7. **Statistical validation** — within-industry cosine 0.608 vs across 0.540, permutation-test p < 0.001; per-PC ANOVA: PC1 F=1278, PC3 F=726, PC5 F=574 (p ≈ 0).
8. **Merge with df_master** — `df_master_with_clip.parquet` (4127 × 45).
9. **Final report** with file inventory + 5 nearest-neighbour examples per random query.

**Two regression bugs caught & fixed in flight:**
- `transformers ≥ 5.7` no longer projects via `get_image_features` — wrote a small `clip_image_features()` helper that always goes through `vision_model.pooler_output → visual_projection`.
- Instagram shortcodes can contain `_`. Original regex `[^_]+` skipped 1015 files; rewrote with right-anchored suffix strip (`_slide_<N>` / `_thumb`).

### V4 ablation — RF, XGB, LGB trained and visualized

- **df_ml_dataset_v4.parquet** built: V3 (4087 × 32) inner-joined with CLIP-PCA on `post_id` → **4010 × 48** (filter, not impute, per the team's standing rule).
- Modified `phase4_rf.py`, `phase4_xgb.py`, `phase4_lgb.py` and the three `*_visualize.py` scripts to accept `v4` as a third dataset version (artefacts written to `*_v4.*` so V3 outputs stay intact).
- Trained all three models with the **same hyperparameter search budget as V3** (RF/XGB: 50 iter × 10-fold; LGB: Optuna 50 trials × 5-fold).
- Generated complete viz suite for each model, plus 4 cross-version comparison figures.

## 2. Files generated (key paths, all under `ml-service/`)

### Step 4h CLIP outputs

| Path | Shape / size | Purpose |
|---|---|---|
| `data/step4h/df_clip_embeddings.parquet` | 8730 × (post_id, file_path, file_type, industry, slide_idx, embedding) | Raw 512-d image embeddings |
| `data/step4h/df_reel_frames_embeddings.parquet` | 1523 × (post_id, video_path, n_frames, mean_embedding) | Mean-pooled reel video embeddings |
| `data/step4h/df_post_clip.parquet` | 4048 × (post_id, content_type, n_assets, clip_embedding) | Per-post 512-d aggregate |
| `data/step4h/df_post_clip_pca.parquet` | 4048 × (post_id, content_type, n_assets, clip_pc01..15) | PCA features for ML |
| `models/clip_pca_15.joblib` | scikit-learn PCA, 47.5 % var | Fitted basis (don't re-fit on test) |
| `data/df_master_with_clip.parquet` | 4127 × 45 | Master + 15 PCs + has_clip flag |
| `figures/clip_tsne_industries.png` | 9×7 plot | t-SNE 2D viz |
| `data/step4h/{tsne_silhouette,pca_explained_variance,validation_report,final_report}.json` | metrics | |

### V4 model artefacts

| Model | Pickle | Results | Predictions | Feature columns |
|---|---|---|---|---|
| RF | `models/rf_v4.pkl` | `data/rf_v4_results.txt` | `data/rf_v4_predictions.parquet` | `models/rf_v4_feature_columns.json` |
| XGB | `models/xgb_v4.pkl` | `data/xgb_v4_results.txt` | `data/xgb_v4_predictions.parquet` | `models/xgb_v4_feature_columns.json` |
| LGB | `models/lgb_v4.pkl` | `data/lgb_v4_results.txt` | `data/lgb_v4_predictions.parquet` | `models/lgb_v4_feature_columns.json` |
| ML dataset | `data/df_ml_dataset_v4.parquet` (4010 × 48) | | | |
| Summary | `data/v4_summary_report.txt` | | | |

### V4 visualizations — `visualizations/v4/` (22 figures)

- Per model × 6 = 18: `*_distributions.png`, `*_pred_vs_actual.png`, `*_residuals.png`, `*_shap_beeswarm.png`, `*_shap.html`, plus `rf_v4_gini_importance.png` / `xgb_v4_gain_vs_shap.png` / `lgb_v4_gain_vs_shap.png`.
- Cross-version × 4: `compare_{rf,xgb,lgb}_v3_vs_v4_pred_vs_actual.png` + `compare_top_features_v3_vs_v4.png`.

### New scripts

| Script | Role |
|---|---|
| `scripts/step4h_01_setup_clip.py` | smoke test |
| `scripts/step4h_02_embed_images.py` | image embedding |
| `scripts/step4h_03_reel_frames.py` | reel frame extraction + embedding |
| `scripts/step4h_04_aggregate_post.py` | per-post aggregation |
| `scripts/step4h_05_tsne.py` | t-SNE + silhouette |
| `scripts/step4h_06_pca.py` | PCA 512 → 15 |
| `scripts/step4h_07_validate.py` | permutation + ANOVA tests |
| `scripts/step4h_08_merge_master.py` | join into df_master |
| `scripts/step4h_09_final_report.py` | consolidated JSON |
| `scripts/step4h_build_v4_dataset.py` | build df_ml_dataset_v4 |
| `scripts/phase4_v4_compare.py` | cross-version figures |

`scripts/phase4_{rf,xgb,lgb}{,_visualize}.py` were edited to add the `v4` branch.

## 3. Best metrics achieved

| Model | Test R²(log1p) | Test ρ (Spearman) | CV RMSE(log) |
|---|---|---|---|
| **RF V4 (champion)** | **+0.4207** | **+0.6669** | 0.2741 ± 0.0334 |
| LGB V4 | +0.4197 | +0.6556 | 0.2755 |
| XGB V4 | +0.3951 | +0.6299 | 0.2706 ± 0.0306 |
| RF V3 (previous best) | +0.3656 | +0.6515 | 0.2670 ± 0.0366 |

- RF V4 R²(log) is **+15 % relative** over RF V3.
- LGB ρ jumped **+0.065** vs LGB V3 — the largest swing of any model.
- CLIP-derived features land in SHAP top-15 of all three model families (4–6 features each); `clip_pc01` is consistently top-3.
- **Caveat:** R²(orig) and RMSE(orig) drift slightly worse for all three models; the V4 test split (802 rows) contains a few high-engagement posts that dominate original-scale RMSE/MAE. Log-scale R² and ρ are the robust comparison.

## 4. Options for next session

### Option A — V5 BERT (caption embeddings, PROMPTs 1, 2, 3)

Add a textual modality on top of V4 visuals. Skeleton:
- **PROMPT 1:** Encode `caption_clean` with a multilingual sentence-transformer (e.g. `paraphrase-multilingual-mpnet-base-v2`) → 768-d.
- **PROMPT 2:** PCA 768 → 15 (or UMAP), validate via t-SNE + per-industry ANOVA, mirror the step 4h playbook.
- **PROMPT 3:** Build `df_ml_dataset_v5.parquet` (V4 + 15 BERT-PCA → ~63 features), train RF / XGB / LGB V5, visualize and produce a V4 vs V5 ablation report.

Expected win: BERT should help on caption-heavy posts where CLIP and tabular features are weak. Risk: caption coverage and language mix (the corpus has AR/FR/EN); pick a model that handles the three.

### Option B — Step 5 Campaign Generator

Pivot from prediction to generation. Per `designDocs/00_inception/specification.md`, this stage feeds the trained predictor + RAG corpus into an LLM to produce campaign briefs / content plans. Integrates with the Node backend (`backend/src/services/`) and the existing Groq pipeline.

**Recommendation:** I'd lean Option A first — V5 closes the multimodal story (visual + text + tabular) and gives the campaign generator a stronger upstream predictor. Option B can then plug into the V5 model rather than V4. But this is your call.

## 5. Pending tasks / known issues

- **Output buffering on Windows.** Subprocess stdout in this harness needs `PYTHONUNBUFFERED=1` + explicit `flush=True` in long Python loops. All step4h / phase4 scripts already include this; new scripts must too.
- **CV RMSE is marginally worse for V4 (~+0.007 to +0.008 log-RMSE).** Held-out test gains are real but the test set differs by 16 rows (V3: 818, V4: 802), so direct RMSE comparison is not strictly apples-to-apples — interpret CV RMSE alongside ρ.
- **77 posts dropped** from V4 (no scraped visual). They live in `df_master_masked_with_topics.parquet` but not in `df_ml_dataset_v4.parquet`. Re-scraping might recover some.
- **HuggingFace symlink warning** (Windows dev mode off). Cosmetic; cache works fine, uses ~2× disk.
- **xgboost < 3.0 pin** still required for SHAP compatibility (already in `pyproject.toml`).
- No new ml-service test runner / linter was added; manual verification only.

---

**Status at session close:** Step 4h done, V4 trained + visualized, awaiting your decision on V5 vs Step 5 for tomorrow.
