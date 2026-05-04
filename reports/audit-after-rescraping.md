# Audit After Re-scraping

**Date**: 2026-04-28
**Scope**: Two-phase incremental Instagram re-scrape of the 41 eligible Tunisian PFE brands. Read-write — `recentPosts`, aggregates, and `lastScrapedAt` updated; backup taken before the run (`backup/2026-04-28/`).
**Reference today**: `2026-04-28`

Pairs with `reports/audit-before-rescraping.md`.

---

## 1. Run Summary

| Metric | Value |
|---|---:|
| Phase 3 — single-brand smoke test (`patisseriemasmoudi`) | 1 brand |
| Phase 4 — full batch (`--industry=all --skip-recent-hours=1`) | 40 brands |
| **Total brands processed** | **41** |
| Brands succeeded | 41 |
| Brands failed | 0 |
| Brands skipped (`< 1h since last scrape`) | 1 (`patisseriemasmoudi` in Phase 4) |
| Brands excluded by allowlist (`nike`, `sephora`, `fstunis`) | 1 active in DB (`fstunis`); the other two not in DB or already inactive |
| Posts fetched per brand | 50 |
| **Net new posts added (after dedup)** | **123** (Phase 3: 4 + Phase 4: 119) |
| **Cumulative cost** | **$4.715** of $4.800 cap (under hard stop) |
| Phase 3 cost | $0.115 |
| Phase 4 cost | $4.600 |
| Phase 4 elapsed | 1787.1 s (29 m 47 s) |
| Avg per-brand time | ~45 s |
| Hard-stop triggered | no |

Backup taken before any writes: `backup/2026-04-28/` (9 collections, 6.1 MB, `socialanalyses.json` = 6.0 MB).

---

## 2. Method

Script: `backend/scripts/scrape-incremental.js`.
For each brand:

1. Fetch the 50 newest Instagram posts via `apifyService.scrapeInstagram(url, 50)` (hybrid: profile actor + post actor in parallel).
2. Match each fetched post against `SocialAnalysis.recentPosts` by `postUrl`. Drop duplicates.
3. Append new posts to existing `recentPosts`.
4. Sort by `publishedAt` descending; trim to 200.
5. Update profile snapshot fields (`followers`, `following`, `totalPosts`, `isVerified`, `bio`, `postsPerWeek`).
6. Recompute `avgLikes`, `avgComments`, `avgShares`, `avgViews`, `engagementRate` from the merged `recentPosts`; recompute `performanceScore`.
7. `lastScrapedAt` set to `new Date()`; `scrapingStatus = 'completed'`.
8. Save `SocialAnalysis` → `post('save')` hook recomputes `Competitor.metrics` from the analyses.
9. Mirror snapshot fields onto `Competitor.socialMedia.instagram` and persist.

Every brand wrapped in `try/catch` so a single failure cannot abort the batch. A cost gate runs **before** every Apify call: if `cumulativeCost + 0.115 > 4.80`, the brand is skipped and the run aborts cleanly.

A `--skip-recent-hours=1` flag was added (CLI-opt-in; default behaviour unchanged) to filter out brands whose `lastScrapedAt` is within the last hour. Used in Phase 4 to avoid re-scraping `patisseriemasmoudi`.

---

## 3. Per-brand Results

`Before` is the `recentPosts` count immediately before this 2-phase run (100 for all 41 brands; this is the legacy ceiling from the first scrape pass that the previous "skip if ≥ 100" gate enforced). `After` is the post-merge count. `+New` is `(After - Before)`. `Newest` and `Oldest` are the bounds of `publishedAt` across the final `recentPosts` array.

### PFE Analysis — Patisserie

| Brand | Before | After | +New | Followers | Eng % | Perf | Oldest | Newest |
|---|---:|---:|---:|---:|---:|---:|---|---|
| patisseriemasmoudi¹ | 100 | 104 | +4 | 147 020 | 0.29 | 45 | 2025-01-28 | 2026-04-26 |
| patisserie_h_by_omar | 100 | 105 | +5 | 611 642 | 0.10 | 35 | 2024-08-08 | 2026-04-26 |
| mamie.karima | 100 | 100 | 0 | 375 497 | 0.15 | 40 | 2025-02-02 | 2026-04-20 |
| lamaisongourmandise | 100 | 103 | +3 | 126 635 | 0.10 | 45 | 2025-10-08 | 2026-04-27 |
| maisonturki | 100 | 101 | +1 | 81 731 | 0.23 | 35 | 2024-07-14 | 2026-04-23 |
| patisserierekik | 100 | 101 | +1 | 70 698 | 0.17 | 35 | 2025-04-13 | 2026-04-27 |
| patisserie.sakka | 100 | 100 | 0 | 58 196 | 0.43 | 45 | 2024-03-18 | 2026-04-16 |
| labeylicale | 100 | 102 | +2 | 44 298 | 0.11 | 30 | 2025-01-14 | 2026-04-24 |

¹ Phase 3 (smoke test, run 3 minutes before Phase 4). Skipped in Phase 4 by `--skip-recent-hours=1`.

### PFE Analysis — Beauty

| Brand | Before | After | +New | Followers | Eng % | Perf | Oldest | Newest |
|---|---:|---:|---:|---:|---:|---:|---|---|
| floraison.official | 100 | 106 | +6 | 368 743 | 0.26 | 65 | 2026-01-28 | 2026-04-27 |
| my_story_cosmetics | 100 | 103 | +3 | 235 892 | 0.50 | 45 | 2025-08-10 | 2026-04-24 |
| lellacosmetics | 100 | 102 | +2 | 137 719 | 0.83 | 40 | 2025-10-11 | 2026-04-24 |
| therapybylk | 100 | 100 | 0 | 124 278 | 3.13 | 55 | 2025-06-27 | 2026-04-16 |
| yvesrocher_tunisie² | 100 | 103 | +3 | 100 157 | 0.09 | 55 | 2025-11-22 | 2026-04-27 |
| nuxetunisie | 100 | 101 | +1 | 91 673 | 2.13 | 40 | 2025-05-06 | 2026-04-27 |
| freya.tn | 100 | 102 | +2 | 50 385 | 0.95 | 45 | 2025-04-28 | 2026-04-27 |
| biodermatunisie | 100 | 103 | +3 | 23 559 | 1.88 | 35 | 2025-04-30 | 2026-04-24 |

² Apify returned only **12** posts for this run (3 new + 9 dup), not 50. See §6.

### PFE Analysis — Fashion

| Brand | Before | After | +New | Followers | Eng % | Perf | Oldest | Newest |
|---|---:|---:|---:|---:|---:|---:|---|---|
| zara | 100 | 106 | +6 | 62 364 952 | 0.05 | 65 | 2025-12-21 | 2026-04-28 |
| mango | 100 | 111 | +11 | 15 832 255 | 0.02 | 65 | 2026-01-15 | 2026-04-28 |
| bershka | 100 | 106 | +6 | 11 266 402 | 0.09 | 65 | 2026-01-26 | 2026-04-27 |
| pullandbear | 100 | 107 | +7 | 7 778 449 | 0.03 | 55 | 2025-10-28 | 2026-04-28 |
| ha.hamadiabid | 100 | 100 | 0 | 400 583 | 0.09 | 40 | 2025-07-06 | 2026-04-15 |
| zen.tunisie | 100 | 101 | +1 | 351 324 | 0.25 | 40 | 2025-04-12 | 2026-04-25 |
| kastelo.com.tn | 100 | 113 | **+13** | 205 678 | 0.10 | 65 | 2026-02-20 | 2026-04-27 |
| chedly_sisters | 100 | 101 | +1 | 159 987 | 0.45 | 55 | 2026-01-28 | 2026-04-24 |

### PFE Analysis — Hotels

| Brand | Before | After | +New | Followers | Eng % | Perf | Oldest | Newest |
|---|---:|---:|---:|---:|---:|---:|---|---|
| soussepearlmarriott | 100 | 101 | +1 | 60 899 | 0.10 | 35 | 2025-07-09 | 2026-04-22 |
| hiltonskanesmonastir | 100 | 104 | +4 | 49 672 | 0.20 | 25 | 2024-08-23 | 2026-04-27 |
| radissonblutunis | 100 | 101 | +1 | 38 029 | 0.88 | 40 | 2025-11-14 | 2026-04-21 |
| tunismarriott | 100 | 104 | +4 | 37 996 | 0.55 | 30 | 2025-03-04 | 2026-04-26 |
| la_badira | 100 | 102 | +2 | 86 394 | 0.87 | 35 | 2024-08-27 | 2026-04-26 |
| movenpick_hotel_gammarth | 100 | 103 | +3 | 47 418 | 0.16 | 35 | 2025-10-17 | 2026-04-27 |
| el_mouradi_hotels | 100 | 102 | +2 | 38 671 | 0.32 | 35 | 2025-08-16 | 2026-04-27 |
| movenpicklactunis | 100 | 104 | +4 | 36 628 | 0.94 | 35 | 2025-11-10 | 2026-04-27 |
| theresidencetunis | 100 | 103 | +3 | 26 275 | 0.32 | 45 | 2025-09-04 | 2026-04-27 |

### PFE Analysis — Restaurants

| Brand | Before | After | +New | Followers | Eng % | Perf | Oldest | Newest |
|---|---:|---:|---:|---:|---:|---:|---|---|
| the716lac2 | 100 | 100 | 0 | 71 922 | 0.24 | 30 | 2024-01-23 | 2026-04-20 |
| legolfe.restaurant | 100 | 101 | +1 | 69 839 | 0.58 | 35 | 2024-06-12 | 2026-04-23 |
| elfirma.tunis | 100 | 106 | +6 | 53 033 | 0.19 | 35 | 2025-06-19 | 2026-04-26 |
| baguettebaguette | 100 | 104 | +4 | 48 289 | 2.24 | 40 | 2025-10-16 | 2026-04-28 |
| kfctunisie | 100 | 100 | 0 | 44 894 | 1.16 | 45 | 2023-04-07 | 2026-04-21 |
| vie.tunis | 100 | 102 | +2 | 28 705 | 0.17 | 30 | 2024-12-24 | 2026-04-27 |
| papajohnstn | 100 | 102 | +2 | 21 910 | 1.95 | 40 | 2025-10-08 | 2026-04-25 |
| la_salle_a_manger | 100 | 103 | +3 | 21 789 | 0.06 | 35 | 2025-10-25 | 2026-04-26 |

---

## 4. Industry roll-up

| Industry | Brands | Before | After | +New | Avg new / brand |
|---|---:|---:|---:|---:|---:|
| Patisserie | 8 | 800 | 816 | +16 | 2.0 |
| Beauty | 8 | 800 | 820 | +20 | 2.5 |
| Fashion | 8 | 800 | 845 | **+45** | 5.6 |
| Hotels | 9 | 900 | 924 | +24 | 2.7 |
| Restaurants | 8 | 800 | 818 | +18 | 2.3 |
| **Total (PFE eligible)** | **41** | **4 100** | **4 223** | **+123** | **3.0** |

`fstunis` (excluded by allowlist) remains at its previous state: 19 posts, last scraped 2026-04-21 — **not updated** by this run.

---

## 5. Notable observations

- **Fashion is the most active industry.** International giants (`mango +11`, `pullandbear +7`, `zara/bershka +6`) plus Tunisian outlier `kastelo.com.tn +13` (the single biggest gain in the run) drove the +45.
- **Six brands added 0 new posts**: `mamie.karima`, `patisserie.sakka`, `therapybylk`, `ha.hamadiabid`, `the716lac2`, `kfctunisie`. The previous scrape (during the original 100-post pass) already captured the most recent 50 posts for these accounts — no posts have been published since then. This is expected for low-frequency posters, not a script bug.
- **Heaviest engagement (per `engagementRate`)** in the post-merge view: `therapybylk 3.13%`, `baguettebaguette 2.24%`, `nuxetunisie 2.13%`, `papajohnstn 1.95%`, `biodermatunisie 1.88%`. Despite their giant follower bases, the Spanish high-street brands (`zara`, `mango`, `pullandbear`, `bershka`) sit at 0.02 – 0.09 %.
- **`recentPosts` cap not yet binding.** No brand was trimmed (max post count in the dataset is 113 / 200). The trim path is exercised on the next pass.

---

## 6. Failures and anomalies

- **0 hard failures.** All 41 brands wrote successfully. No `try/catch` brand-level error fired; no Apify run was rejected.
- **`yvesrocher_tunisie` returned 12 posts instead of 50.** Apify Run succeeded but returned a smaller dataset (3 new + 9 dup = 12). Two plausible causes:
  1. The account's `latestPosts` actor view doesn't expose a contiguous 50-post tail (private or rate-limited fragment).
  2. Account genuinely has < 50 unique posts visible to the scraper at this moment.
  Followers (100 157) and engagement metrics persisted correctly. Worth a manual re-check on the next pass.
- **Mongoose duplicate-index warnings** continue to print at boot (`projectId`, `generatedBy` declared with both `index: true` and `schema.index()`). Pre-existing; unrelated to scraping; harmless. Worth cleaning up later in the schema files.
- **`fstunis`** still shows in the DB with 19 stale posts and `lastScrapedAt = 2026-04-21`. Excluded by allowlist as instructed; flag if you want it included or hard-deleted before Step 4.

---

## 7. Database state after the run

| Collection | Docs (before) | Docs (after) | Δ |
|---|---:|---:|---:|
| `socialanalyses` | 44 | 44 | 0 (in-place updates) |
| `competitors` | 45 | 45 | 0 |
| `projects` | 7 | 7 | 0 |

No new documents were inserted; only existing `socialanalyses` documents were mutated (`recentPosts` extended, aggregates recomputed, `lastScrapedAt` bumped). Competitor metrics were recalculated automatically by the `post('save')` hook on `SocialAnalysis`.

`PFE Analysis - *` Instagram dataset:
- **41 brands × ~103 posts ≈ 4 223 posts** total (vs. 4 100 before).
- `lastScrapedAt` now within the last hour for all 41 brands (range: `2026-04-28T11:53:31Z` for `patisseriemasmoudi` from Phase 3; the Phase 4 brands all between `12:18Z` and `12:47Z`).

---

## 8. Recommendations for Step 4

1. **Use the dataset as-is for Step 4 modeling/insights**. 4 223 posts spanning, in most cases, > 6 months per brand (some > 2 years for low-frequency posters) is sufficient for rolling-window analysis.
2. **Expect dedup behaviour to be the new normal.** With the 200-cap incremental design, future weekly scrapes at `--limit=50` will average ~3 net-new posts per brand (this run's average). Cost per refresh: ~$4.70 for the full PFE roster. The `recentPosts` cap will start binding in roughly 30 weeks for the most active brands (`mango`, `kastelo.com.tn`).
3. **Re-investigate `yvesrocher_tunisie`** before running Step 4 metrics on it — the truncated fetch suggests its dataset is less complete than its 100-post history implies.
4. **Decide on `fstunis`.** Either (a) drop the allowlist exclusion and let it back into the rotation, (b) hard-delete the stale `socialanalyses` doc and the `competitor` entry, or (c) leave as-is and exclude from Step 4 aggregations. The current 19-post / 7-day-stale state will pollute industry averages if used naïvely.
5. **Schedule the recurring scrape**. The script is now stable enough to run weekly. A cron entry `--industry=all --skip-recent-hours=24` would refresh every brand once per day, reuse the dedup window, and stay under $5/run. (Mention `/schedule` if you want me to set this up.)
6. **Tighten the budget guard before scaling**. The current cost estimate (`$0.115/brand`) is hard-coded; if Apify pricing changes, the cap drift will bite silently. Read actual `usageTotalUsd` from the Apify run summary instead.
7. **Add a `lastFetchedCount` field** on `SocialAnalysis` so anomalies like `yvesrocher_tunisie` (12 of 50 fetched) become queryable without re-reading the script log.

---

## 9. Artefacts

| Path | Purpose |
|---|---|
| `backup/2026-04-28/` | Full pre-scrape JSON dump of all 9 collections |
| `backend/scripts/scrape-incremental.js` | Re-runnable scrape orchestrator (CLI: `--dry-run`, `--industry=`, `--brand=`, `--limit=`, `--skip-recent-hours=`) |
| `backend/scripts/_after-scrape-stats.js` | One-off helper that produced `_after-stats.json` for this report |
| `reports/scrape-batch.log` | Full Phase 4 stdout (695 lines, all 40 brands) |
| `reports/_after-stats.json` | Machine-readable per-brand snapshot used to build §3 |
| `reports/audit-before-rescraping.md` | Companion pre-scrape audit |
| `reports/audit-after-rescraping.md` | This file |
