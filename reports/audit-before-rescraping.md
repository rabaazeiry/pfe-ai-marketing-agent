# Audit Before Re-scraping

**Date**: 2026-04-28
**Scope**: Read-only audit of MongoDB + project files. No data modified, no scraping launched.
**Reference today** (used for "days since" calculations): `2026-04-28`

---

## 1. MongoDB Architecture

| Item | Value |
|---|---|
| Connection driver | `mongoose ^8.0.0` (Node) |
| Effective URI host | `127.0.0.1:27017` (local MongoDB) |
| Database name | `battouta_db` |
| `MONGODB_URI` env var | present ✅ |
| `database.js` fallback URI | `mongodb://127.0.0.1:27017/battouta_db` |

> Note: `CLAUDE.md` mentions a Google-DNS workaround for MongoDB Atlas SRV lookups. The current `backend/src/config/database.js` no longer applies that workaround — it connects to a local Mongo. The Atlas note in `CLAUDE.md` is stale.

### Collections

| Collection | Document count |
|---|---:|
| `users` | 2 |
| `projects` | 7 |
| `competitors` | 45 |
| `socialanalyses` | 44 |
| `swotanalyses` | 4 |
| `marketresearches` | 6 |
| `campaignplans` | 0 |
| `insights` | 0 |
| `reports` | 0 |

**Brands/competitors collection**: `competitors` (45 docs). The actual scraped Instagram data lives in `socialanalyses` (44 docs filtered to `platform: 'instagram'`), with one doc per `(competitorId, 'instagram')` pair. `recentPosts` is an **embedded array** inside each `socialanalyses` document — there is **no separate `posts` collection**.

### Project breakdown

| Project name | Industry | _id |
|---|---|---|
| Hôtels Luxe Tunisie | Tourism & Hotels | `69e0418fb53a9b918dea9b3e` |
| Nike Test Project | Sportswear & Apparel | `69e4a863d9a2266f266edf8d` |
| PFE Analysis - Patisserie | patisserie | `69e54de3c8a0e851a8b19ddf` |
| PFE Analysis - Beauty | beauty | `69e54de3c8a0e851a8b19de0` |
| PFE Analysis - Fashion | fashion | `69e63f09c8a0e851a8b19de2` |
| PFE Analysis - Hotels | hotels | `69e63f09c8a0e851a8b19de3` |
| PFE Analysis - Restaurants | restaurants | `69e63f09c8a0e851a8b19de4` |

The 5 `PFE Analysis - *` projects are the ones holding the 42 Tunisian brands of the dataset. The other two (Hôtels Luxe Tunisie, Nike Test Project) are legacy / test artifacts.

---

## 2. Competitors collection schema

Source: `backend/src/models/Competitor.model.js` (VERSION 5).

### Top-level fields

| Field | Type | Required | Default / Constraints |
|---|---|---|---|
| `projectId` | `ObjectId` (ref `Project`) | yes | indexed |
| `companyName` | `String` | yes | 2–100 chars, trimmed |
| `website` | `String` | no | `''` |
| `description` | `String` | no | ≤ 1000 chars |
| `logo.url` | `String` | no | `''` |
| `logo.source` | `String` | no | `''` |
| `classificationMaturity` | `String` (enum: `startup`, `leader`) | no | `startup` |
| `classification` | `String` | no | `startup` (kept in sync with `classificationMaturity`) |
| `classificationScore` | `Number` 0–100 | no | `0` |
| `classificationJustification` | `String` ≤ 500 | no | `''` |
| `rank` | `Number ≥ 0` | no | `0` |
| `isManuallyAdded` | `Boolean` | no | `false` |
| `foundedYear` | `Number` (1800 – current year) | no | — |
| `country` | `String` (ISO-2, uppercased) | no | — |
| `socialMedia.instagram.{username,url,verified,followers,postsCount}` | mixed | no | empty defaults |
| `socialMedia.facebook.{...}` | same shape | no | — |
| `socialMedia.linkedin.{...}` | same shape | no | — |
| `socialMedia.tiktok.{...}` | same shape | no | — |
| `swotAnalysis.{strengths,weaknesses,opportunities,threats}` | `[String]` (≤ 10 each) | no | `[]` |
| `swotAnalysis.analyzedAt` | `Date` | no | — |
| `scrapingStatus` | enum `pending` \| `in_progress` \| `completed` \| `failed` | no | `pending` |
| `lastScrapedAt` | `Date` | no | — |
| `scrapingError` | `String` | no | `''` |
| `metrics.{totalFollowers,avgEngagementRate,platformsCount,overallScore}` | `Number` | no | computed by `SocialAnalysis.post('save')` hook |
| `discoveredAt` | `Date` | no | `Date.now` |
| `isActive` | `Boolean` | no | `true` |
| `notes` | `String` ≤ 1000 | no | `''` |
| `createdAt`, `updatedAt` | `Date` | yes (timestamps) | auto |

### Indexes

```
{ projectId: 1, classificationMaturity: 1 }
{ projectId: 1, companyName: 1 }
{ scrapingStatus: 1 }
{ createdAt: -1 }
```

### Concrete example (anonymised, drawn from `floraison.official`)

```jsonc
{
  "_id": "ObjectId(...)",
  "projectId": "ObjectId(69e54de3c8a0e851a8b19de0)",  // PFE Analysis - Beauty
  "companyName": "floraison.official",
  "classification": "leader",
  "classificationMaturity": "leader",
  "isManuallyAdded": true,
  "isActive": true,
  "socialMedia": {
    "instagram": {
      "username": "floraison.official",
      "url": "https://www.instagram.com/floraison.official/",
      "verified": false,
      "followers": 368737,
      "postsCount": 7324
    },
    "facebook":  { "username": "", "url": "", "verified": false, "followers": 0, "postsCount": 0 },
    "linkedin":  { /* empty defaults */ },
    "tiktok":    { /* empty defaults */ }
  },
  "scrapingStatus": "completed",
  "lastScrapedAt": "2026-04-21T11:21:55.966Z",
  "scrapingError": "",
  "metrics": {
    "totalFollowers": 368737,
    "avgEngagementRate": 0.27,
    "platformsCount": 1,
    "overallScore": 25
  },
  "swotAnalysis": { "strengths": [], "weaknesses": [], "opportunities": [], "threats": [] },
  "createdAt": "...", "updatedAt": "..."
}
```

---

## 3. Posts schema

Posts are embedded in `socialanalyses.recentPosts`. They follow the `topPostSchema` defined in `backend/src/models/SocialAnalysis.model.js`.

### Per-post fields

| Field | Type | Default | Notes |
|---|---|---|---|
| `postUrl` | `String` (required) | — | trimmed |
| `imageUrl` | `String` | `''` | |
| `thumbnailUrl` | `String` | `''` | |
| `videoUrl` | `String` | `''` | empty for non-video |
| `likes` | `Number ≥ 0` | `0` | |
| `comments` | `Number ≥ 0` | `0` | |
| `shares` | `Number ≥ 0` | `0` | always `0` for Instagram (Apify doesn't expose) |
| `views` | `Number ≥ 0` | `0` | non-zero only for video / reel |
| `contentType` | enum (see below) | `'photo'` | |
| `slideCount` | `Number` 1–20 | `1` | only > 1 for carousels |
| `caption` | `String ≤ 2200` | `''` | |
| `hashtags` | `[String]` (≤ 30) | `[]` | **stored without the `#` prefix**, lowercased |
| `location` | `String ≤ 200` | `''` | |
| `publishedAt` | `Date` | — | **JavaScript `Date` object** (BSON Date), not a timestamp string |
| `engagementRate` | `Number` 0–1000 | `0` | per-post `(likes+comments)/followers * 100` |
| _id | (suppressed) | — | sub-doc has `{ _id: false }` |

### `contentType` enum values

`'photo'`, `'video'`, `'reel'`, `'carousel'`, `'story'`, `'article'`, `'document'`. Apify Instagram is mapped via `apify.service.js#_igContentType`:
- type/productType contains `video` or `reel` → `reel`
- type/productType contains `sidecar` or `carousel` → `carousel`
- otherwise → `photo`

### Concrete example (drawn from sample, anonymised)

```jsonc
{
  "postUrl": "https://www.instagram.com/p/DP3TvEcEafE/",
  "imageUrl": "https://...",
  "thumbnailUrl": "",
  "videoUrl": "",
  "likes": 345,
  "comments": 0,
  "shares": 0,
  "views": 0,
  "contentType": "photo",
  "slideCount": 1,
  "caption": "The 12PM Baguette Routine",
  "hashtags": [],
  "location": "",
  "publishedAt": "2025-10-16T08:56:17.000Z",
  "engagementRate": 0.71
}
```

### Date format check

Returned by Mongoose as ISO-8601 strings via `toJSON`; stored in BSON as `Date`. The script `apify.service.js#_transformInstagram` constructs them with `new Date(p.timestamp)` where `p.timestamp` is the Unix timestamp from Apify. **No raw timestamps observed in DB.**

---

## 4. Inventory of brands

Sorted by industry (project name) then username. Total Instagram `SocialAnalysis` docs in DB: **44** (1 Nike test + 9 in Beauty including Sephora + 8 Fashion + 10 Hotels + 8 Patisserie + 8 Restaurants). Excluding the Nike test and the international Sephora outlier, the Tunisian-PFE dataset is **43 brands** — close to the "42 Tunisian brands" target (Sephora was added by the legacy `scrape-batch-1.js` and a `deactivate-beauty-sephora.js` script exists in `backend/scripts/`).

> "Days stale" = `2026-04-28 − newest publishedAt`.
> **lt100** flag highlights brands where `recentPostsCount < 100` (priority for re-scraping).

| Industry | Username | Posts (in DB) | Total IG posts | Oldest | Newest | Span (d) | Days stale | Followers | avgLikes | avgComments | ER (%) | Flag |
|---|---|---:|---:|---|---|---:|---:|---:|---:|---:|---:|---|
| Beauty | biodermatunisie | 100 | 248 | 2025-04-30 | 2026-04-20 | 355 | 8 | 23,034 | 445 | 9 | 1.97 | OK |
| Beauty | floraison.official | 100 | 7,324 | 2026-01-28 | 2026-04-20 | 82 | 8 | 368,737 | 219 | 793 | 0.27 | OK |
| Beauty | freya.tn | 100 | 217 | 2025-04-28 | 2026-04-19 | 356 | 9 | 50,467 | 455 | 32 | 0.96 | OK |
| Beauty | lellacosmetics | 100 | 1,871 | 2025-10-11 | 2026-04-13 | 184 | 15 | 137,781 | 106 | 1,054 | 0.84 | OK |
| Beauty | my_story_cosmetics | 100 | 265 | 2025-08-10 | 2026-04-08 | 241 | 20 | 235,954 | 1,174 | 38 | 0.51 | OK |
| Beauty | nuxetunisie | 100 | 1,447 | 2025-05-06 | 2026-04-16 | 345 | 12 | 91,545 | 502 | 1,473 | 2.16 | OK |
| Beauty | **sephora** ⚠️ | **12** | **15,669** | 2025-09-24 | 2026-04-19 | 208 | 9 | 23,015,123 | 7,378 | 1,262 | 0.04 | **lt100 — international, possibly deactivated** |
| Beauty | therapybylk | 100 | 170 | 2025-06-27 | 2026-04-16 | 293 | 12 | 123,493 | 1,527 | 2,367 | 3.15 | OK |
| Beauty | yvesrocher_tunisie | 100 | 1,387 | 2025-11-22 | 2026-04-21 | 150 | 7 | 100,171 | 22 | 75 | 0.10 | OK |
| Fashion | bershka | 100 | 5,655 | 2026-01-26 | 2026-04-21 | 85 | 7 | 11,252,086 | 10,769 | 146 | 0.10 | OK |
| Fashion | chedly_sisters | 100 | 689 | 2026-01-28 | 2026-04-20 | 82 | 8 | 159,549 | 695 | 16 | 0.45 | OK |
| Fashion | ha.hamadiabid | 100 | 1,633 | 2025-07-06 | 2026-04-15 | 283 | 13 | 400,021 | 354 | 2 | 0.09 | OK |
| Fashion | kastelo.com.tn | 100 | 1,816 | 2026-02-20 | 2026-04-20 | 59 | 8 | 205,262 | 210 | 5 | 0.10 | OK |
| Fashion | mango | 100 | 6,660 | 2026-01-15 | 2026-04-20 | 95 | 8 | 15,827,479 | 2,451 | 70 | 0.02 | OK |
| Fashion | pullandbear | 100 | 6,475 | 2025-10-28 | 2026-04-20 | 174 | 8 | 7,778,384 | 2,586 | 45 | 0.03 | OK |
| Fashion | zara | 100 | 5,249 | 2025-12-21 | 2026-04-21 | 121 | 7 | 62,356,583 | 28,309 | 279 | 0.05 | OK |
| Fashion | zen.tunisie | 100 | 2,091 | 2025-04-12 | 2026-04-08 | 361 | 20 | 350,925 | 865 | 10 | 0.25 | OK (data >12mo) |
| Hotels | el_mouradi_hotels | 100 | 1,224 | 2025-08-16 | 2026-04-20 | 247 | 8 | 38,620 | 124 | 2 | 0.33 | OK |
| Hotels | **fstunis** ⚠️ | **19** | **20** | 2026-02-23 | 2026-04-17 | 53 | 11 | 121,049 | 137 | 1 | 0.11 | **lt100 — but profile only has 20 posts total (account is near-empty)** |
| Hotels | hiltonskanesmonastir | 100 | 171 | 2024-08-23 | 2026-04-20 | 605 | 8 | 49,592 | 95 | 2 | 0.20 | OK (data >12mo) |
| Hotels | la_badira | 100 | 877 | 2024-08-27 | 2026-04-19 | 600 | 9 | 86,221 | 765 | 5 | 0.89 | OK (data >12mo) |
| Hotels | movenpick_hotel_gammarth | 100 | 1,598 | 2025-10-17 | 2026-04-21 | 186 | 7 | 47,374 | 78 | 1 | 0.17 | OK |
| Hotels | movenpicklactunis | 100 | 1,184 | 2025-11-10 | 2026-04-20 | 161 | 8 | 36,594 | 349 | 1 | 0.96 | OK |
| Hotels | radissonblutunis | 100 | 529 | 2025-11-14 | 2026-04-21 | 158 | 7 | 37,979 | 335 | 4 | 0.89 | OK |
| Hotels | soussepearlmarriott | 100 | 1,012 | 2025-07-09 | 2026-04-21 | 286 | 7 | 60,912 | 56 | 4 | 0.10 | OK |
| Hotels | theresidencetunis | 100 | 1,598 | 2025-09-04 | 2026-04-21 | 229 | 7 | 26,240 | 84 | 3 | 0.33 | OK |
| Hotels | tunismarriott | 100 | 452 | 2025-03-04 | 2026-04-19 | 411 | 9 | 37,901 | 215 | 1 | 0.57 | OK (data >12mo) |
| Patisserie | labeylicale | 100 | 339 | 2025-01-14 | 2026-04-03 | 444 | 25 | 44,254 | 46 | 1 | 0.11 | OK (data >12mo, posting paused) |
| Patisserie | lamaisongourmandise | 100 | 2,134 | 2025-10-08 | 2026-04-20 | 194 | 8 | 126,482 | 126 | 3 | 0.10 | OK |
| Patisserie | maisonturki | 100 | 772 | 2024-07-14 | 2026-04-17 | 642 | 11 | 81,688 | 180 | 5 | 0.23 | OK (data >12mo) |
| Patisserie | mamie.karima | 100 | 514 | 2025-02-02 | 2026-04-20 | 442 | 8 | 375,335 | 572 | 10 | 0.16 | OK (data >12mo) |
| Patisserie | patisserie_h_by_omar | 100 | 1,217 | 2024-08-08 | 2026-04-20 | 620 | 8 | 613,877 | 562 | 47 | 0.10 | OK (data >12mo) |
| Patisserie | patisserie.sakka | 100 | 1,061 | 2024-03-18 | 2026-04-16 | 759 | 12 | 58,124 | 243 | 8 | 0.43 | OK (data >12mo) |
| Patisserie | patisseriemasmoudi | 100 | 1,996 | 2025-01-28 | 2026-04-19 | 446 | 9 | 146,846 | 426 | 8 | 0.30 | OK (data >12mo) |
| Patisserie | patisserierekik | 100 | 1,627 | 2025-04-13 | 2026-04-11 | 363 | 17 | 70,602 | 116 | 3 | 0.17 | OK |
| Restaurants | baguettebaguette | 100 | 1,906 | 2025-10-16 | 2026-04-21 | 187 | 7 | 48,234 | 1,121 | 5 | 2.33 | OK |
| Restaurants | elfirma.tunis | 100 | 238 | 2025-06-19 | 2026-04-20 | 305 | 8 | 52,843 | 88 | 4 | 0.17 | OK |
| Restaurants | kfctunisie | 100 | 489 | 2023-04-07 | 2026-04-21 | 1,110 | 7 | 44,915 | 521 | 2 | 1.16 | OK (data >12mo) |
| Restaurants | la_salle_a_manger | 100 | 1,532 | 2025-10-25 | 2026-04-21 | 178 | 7 | 21,784 | 14 | 0 | 0.06 | OK |
| Restaurants | legolfe.restaurant | 100 | 175 | 2024-06-12 | 2026-04-16 | 673 | 12 | 69,616 | 398 | 6 | 0.58 | OK (data >12mo) |
| Restaurants | papajohnstn | 100 | 1,303 | 2025-10-08 | 2026-04-21 | 195 | 7 | 21,943 | 437 | 0 | 1.99 | OK |
| Restaurants | the716lac2 | 100 | 659 | 2024-01-23 | 2026-04-20 | 818 | 8 | 71,925 | 169 | 2 | 0.24 | OK (data >12mo) |
| Restaurants | vie.tunis | 100 | 122 | 2024-12-24 | 2026-04-21 | 483 | 7 | 28,624 | 49 | 1 | 0.17 | OK (data >12mo) |
| _Test_ | **nike** ⚠️ | **0** | **1,627** | — | — | 0 | n/a | 297,504,435 | 71,229 | 2,190 | 0.02 | **lt100 — empty `recentPosts` (legacy test row)** |

---

## 5. Detected anomalies

### 5a. Under-sampled (`recentPostsCount < 100`) — **priority for re-scraping**

| Username | Posts in DB | Total IG posts | Note |
|---|---:|---:|---|
| **nike** | 0 | 1,627 | Legacy test record. `SocialAnalysis` exists but `recentPosts` is empty. Likely created by an early run before `scrape-batch-1.js` was finalised. Recommend exclusion or re-scrape. |
| **sephora** | 12 | 15,669 | International. Added by `scrape-batch-1.js`. A `deactivate-beauty-sephora.js` script exists — the brand may already be marked for removal. Not part of the 42 Tunisian targets. |
| **fstunis** | 19 | 20 | The Four Seasons Tunis profile genuinely only has 20 posts. **Not a scraping bug** — the cap was hit by the source. The batch JSON (`hotels-batch-results.json`) confirmed it as `partial`. |

### 5b. Over-sampled (`recentPostsCount > 100`)

None. The hard cap of 100 was respected by all completed runs.

### 5c. Brands with oldest post older than 12 months (before 2025-04-28)

15 brands, sorted by `oldest`:

| Username | Oldest post | Industry |
|---|---|---|
| kfctunisie | 2023-04-07 | Restaurants |
| the716lac2 | 2024-01-23 | Restaurants |
| patisserie.sakka | 2024-03-18 | Patisserie |
| legolfe.restaurant | 2024-06-12 | Restaurants |
| maisonturki | 2024-07-14 | Patisserie |
| patisserie_h_by_omar | 2024-08-08 | Patisserie |
| hiltonskanesmonastir | 2024-08-23 | Hotels |
| la_badira | 2024-08-27 | Hotels |
| vie.tunis | 2024-12-24 | Restaurants |
| labeylicale | 2025-01-14 | Patisserie |
| patisseriemasmoudi | 2025-01-28 | Patisserie |
| mamie.karima | 2025-02-02 | Patisserie |
| tunismarriott | 2025-03-04 | Hotels |
| zen.tunisie | 2025-04-12 | Fashion |
| patisserierekik | 2025-04-13 | Patisserie |

This is **not** a problem — it's an expected effect of low posting cadence on those accounts. With 100 posts and ~1 post/week, the dataset spans 100 weeks (~24 months). For the re-scraping run, this means an incremental fetch (newest-only) is appropriate; full backfill is not needed.

### 5d. Posts with future dates

**0** — clean.

### 5e. Posts with empty captions

**94 posts (2.27%)** across 14 brands. Most concentrated in Patisserie:

| Brand | Empty captions | Brand | Empty captions |
|---|---:|---|---:|
| patisserie.sakka | 41 | mamie.karima | 9 |
| maisonturki | 20 | el_mouradi_hotels | 3 |
| movenpick_hotel_gammarth | 8 | lellacosmetics | 2 |
| freya.tn | 2 | zen.tunisie | 2 |
| radissonblutunis | 2 | labeylicale | 1 |
| tunismarriott | 1 | movenpicklactunis | 1 |
| theresidencetunis | 1 | elfirma.tunis | 1 |

This is normal Instagram behaviour — pure-image posts often have no caption.

### 5f. Posts with empty `hashtags` array

**2,211 posts (53.5%)** — every brand has at least some captionless or hashtag-less posts. **This is not a data-quality issue** but reflects how Tunisian brands actually post (many use no hashtags). Some brands post-by-post:

| Worst offenders (≥80 posts without hashtags) | Empty | Best (≤5 posts without hashtags) |
|---|---:|---|
| therapybylk, chedly_sisters, patisserierekik | 100 | la_salle_a_manger |
| baguettebaguette, floraison.official | 98 | nuxetunisie |
| papajohnstn, zen.tunisie, patisserie_h_by_omar | 97 | mango, zara |

→ For the AI/insights step (Step 4–5), don't rely on `hashtags`. Use **caption text** + the `topHashtags` aggregate (which extracts inline `#tags` from captions in `apify.service.js#_extractHashtags`).

### 5g. Posts with `likes === 0`

**48 posts (1.16%)**. Acceptable for very recent posts on small accounts.

### 5h. Posts with malformed dates

**0** — every `publishedAt` parses as a valid `Date`. No NaN, no future dates.

---

## 6. Previous scraping metadata

| Stat | Value |
|---|---|
| `competitor.scrapingStatus` distribution | `{ completed: 45 }` (100%) |
| `socialanalysis.scrapingStatus` distribution | `{ completed: 44 }` (100%) |
| Most recent `lastScrapedAt` | `2026-04-21T21:11:57.629Z` (restaurants batch end) |
| Oldest `lastScrapedAt` | `2026-04-19T10:03:33.637Z` (Nike test row) |
| `scrapingError` values | none — all empty |

The five PFE batches were run between **2026-04-20 and 2026-04-21** (chronological order based on `*-batch-results.json` files):

| Batch file | Started | Ended | Brands run | Skipped (≥100 in DB) | Success | Partial | Failed | New posts |
|---|---|---|---:|---:|---:|---:|---:|---:|
| `beauty-batch-results.json` | 2026-04-21 13:31 | 2026-04-21 13:33 | 8 | 5 | 3 | 0 | 0 | 300 |
| `fashion-batch-results.json` | 2026-04-21 19:30 | 2026-04-21 19:30 | 8 | 8 | 0 | 0 | 0 | 0 (all already in DB) |
| `hotels-batch-results.json` | 2026-04-21 20:15 | 2026-04-21 20:24 | 10 | 0 | 9 | 1 (`fstunis`) | 0 | 919 |
| `patisserie-batch-results.json` | 2026-04-20 21:17 | 2026-04-20 21:23 | 8 | 1 (`patisserie_h_by_omar`) | 7 | 0 | 0 | 700 |
| `restaurants-batch-results.json` | 2026-04-21 21:04 | 2026-04-21 21:11 | 8 | 0 | 8 | 0 | 0 | 800 |

Total new posts captured in the April-2026 wave: **2,719**. Combined with what was already in the DB, the inventory shows **4,131 posts in `recentPosts` arrays** (excluding the empty Nike row).

---

## 7. Apify configuration (traceable)

### Service file

`backend/src/services/apify.service.js` (single class, exported as a singleton). Key constants:

```js
const APIFY_BASE    = 'https://api.apify.com/v2';
const POLL_INTERVAL = 4000;     // 4s between Apify run polls
const MAX_WAIT      = 300000;   // 5min max per actor run
const ACTORS = {
  INSTAGRAM_PROFILE : 'apify/instagram-profile-scraper',
  INSTAGRAM_POST    : 'apify/instagram-post-scraper',
  FACEBOOK_PAGE     : 'apify/facebook-pages-scraper',
};
```

### Hybrid Instagram strategy

`apifyService.scrapeInstagram(url, postsLimit=100)` runs **two actors in parallel** via `Promise.allSettled`:

| Actor | Input | Output |
|---|---|---|
| `apify/instagram-profile-scraper` | `{ usernames: [u], resultsLimit: 1, resultsType: 'details' }` | profile metadata (followers, bio, verified, totalPosts) |
| `apify/instagram-post-scraper` | `{ username: [u], resultsLimit: 100 }` | the most recent N posts |

Results are merged: `merged = { ...profile, latestPosts: posts }`. If the profile actor fails but the post actor succeeds (or vice-versa), the run still produces partial data — only a total failure throws.

### Per-batch script config

The five `backend/scripts/scrape-industry-*.js` files share the same shape (example: `scrape-industry-patisserie.js`):

```js
const POSTS_PER_BRAND = 100;
const DELAY_MS        = 3000;   // pause between brands
const SKIP_THRESHOLD  = 100;    // skip if ≥ this many posts already in DB
const COST_PER_BRAND  = 0.10;   // est. $/brand (Apify)
```

The "smart skip" logic is what made the **fashion** batch a no-op on 2026-04-21 (every brand already had ≥100 posts).

### apify-client install state

`apify-client` is **NOT installed** in `backend/node_modules`. The service uses raw `axios` against the Apify v2 REST API (`POST /acts/{actor}/runs` then poll `/actor-runs/{id}` then `GET /datasets/{id}/items`). This is a deliberate choice — the service implements its own poll loop.

---

## 8. Data quality (sample of 5 posts)

Sample is **deterministic**: posts sorted by `(owner ASC, publishedAt ASC)`, first 5 taken. All 5 happen to come from `baguettebaguette` (alphabetically first owner with posts).

| # | postUrl | Type | Caption length | Caption preview | Hashtags | Likes | Comments | Views | publishedAt | Image | Video |
|---:|---|---|---:|---|---:|---:|---:|---:|---|:---:|:---:|
| 1 | DP3TvEcEafE | photo | 25 | "The 12PM Baguette Routine" | 0 | 345 | 0 | 0 | 2025-10-16 | ✅ | — |
| 2 | DP8d4quDM-g | reel | 21 | "YALLAH! \nفاش تستناو ؟" | 0 | 234 | 0 | 47,778 | 2025-10-18 | ✅ | ✅ |
| 3 | DP_CopfEaM2 | photo | 39 | "Box rigolo pour les petits gourmands 😋" | 0 | 529 | 0 | 0 | 2025-10-19 | ✅ | — |
| 4 | DQELavSjGTg | photo | 14 | "الكيف عالKifff" | 0 | 679 | 0 | 0 | 2025-10-21 | ✅ | — |
| 5 | DQJY2dPjC2A | photo | 19 | "Baguette vibes only" | 0 | 792 | 0 | 0 | 2025-10-23 | ✅ | — |

### Observations

- ✅ **Captions** present on all 5 (Arabic, French, English mix — multilingual content as expected for Tunisia).
- ⚠️ **Hashtags** empty on all 5 — confirms the wider pattern: this brand simply does not use hashtags. Not a scraper bug.
- ✅ **publishedAt** valid ISO dates, no malformed values.
- ✅ **contentType** consistent with media (photos have `videoUrl: ''`; the reel has both `imageUrl` (thumbnail) and `videoUrl`, plus `views > 0`).
- ✅ **likes/comments** are real values, not placeholder zeros (the comment counts of 0 are legitimate — Tunisian small-restaurant accounts genuinely get few public comments).
- ✅ **image URLs** present everywhere; the reel also has a video URL.
- ✅ **slideCount** = 1 for all (no carousels in this slice).

---

## 9. Environment variables

`backend/.env` keys observed (values **NOT shown**):

| Variable | Status | Used by |
|---|---|---|
| `MONGODB_URI` | present ✅ | `database.js` (currently overrides local fallback) |
| `JWT_SECRET` | present ✅ | `utils/jwt.util.js` |
| `JWT_EXPIRES_IN` | present ✅ | `utils/jwt.util.js` |
| `APIFY_API_KEY` | present ✅ | `apify.service.js` (this is the Apify token requested) |
| `GROQ_API_KEY` | present ✅ | LLM calls (groq-sdk) |
| `VALUESERP_API_KEY` | present ✅ | `valueserp.service.js` |
| `SERPER_API_KEY` | present ✅ | `search.service.js` |
| `TAVILY_API_KEY` | present ✅ | research |
| `CHROMA_API_KEY`, `CHROMA_TENANT`, `CHROMA_DATABASE` | present ✅ | `chroma.service.js` (RAG) |
| `FB_APP_ID`, `FB_APP_SECRET` | present ✅ | Facebook Graph API |
| `FB_COOKIE_C_USER`, `FB_COOKIE_XS` | present ✅ | `scraping.facebook.js` (cookie-based scraping) |
| `NODE_ENV` | present ✅ | global |
| `PORT` | present ✅ | `server.js` |

> Note: the variable name in code is `APIFY_API_KEY`, **not** `APIFY_TOKEN`. The user's question asked specifically about `APIFY_TOKEN` — that variable is **absent ❌** under that exact name; the equivalent **is** present as `APIFY_API_KEY`.

`backend/src/config/env.js` re-exports a subset (NODE_ENV, PORT, FRONTEND_URL, MONGODB_URI, JWT_*, SCRAPER_URL, N8N_*, OPENAI_*, GROQ_*, VALUESERP_*, SERPER_*, TAVILY_*, CHROMA_*, APIFY_*, OLLAMA_*). Other vars (Facebook cookies, FB_APP_*) are read directly via `process.env` from the consumer modules.

---

## 10. Tech stack

| Component | Version |
|---|---|
| Node.js (runtime) | `v24.13.0` |
| Express | `^4.18.2` |
| Mongoose | `^8.0.0` |
| `apify-client` | **not installed** — service uses `axios` directly against Apify REST API |
| `axios` | `^1.15.0` |
| `groq-sdk` | `^0.37.0` (LLM) |
| `chromadb` | `^3.4.0` (vector RAG) |
| `playwright` / `playwright-extra` / stealth | `^1.59.1` / `^4.3.6` / `^0.0.1` |
| `puppeteer` / `puppeteer-extra` / stealth / adblocker | `^24.40.0` / `^3.3.6` / `^2.11.2` / `^2.13.6` |
| `cheerio` | `^1.2.0` (HTML parsing) |
| `socket.io` | `^4.8.3` (live progress events) |
| `node-cron` | `^4.2.1` (daily 02:00 auto-scrape) |
| `bcryptjs`, `jsonwebtoken` | auth |
| `dotenv` | `^16.6.1` |
| `nodemon` (dev) | `^3.0.1` |
| Python scraper (separate microservice) | FastAPI + Crawl4AI under `backend/scraper/`, uv-managed |

No test runner, no linter, no build step configured (per `package.json` and `CLAUDE.md`).

---

## EXECUTIVE SUMMARY

| Metric | Value |
|---|---:|
| Total Instagram posts in DB (`recentPosts`) | **4,131** |
| Brands with full sample (100 posts) | **40 / 43** PFE-Tunisian (+ 1 Nike legacy + 1 Sephora outlier = 44 total IG analyses) |
| Brands flagged for re-scraping priority | **3** (`nike`, `sephora`, `fstunis`) |
| OK brands (≥100 posts, fresh) | **40 / 43** PFE-Tunisian |
| Average time span covered per brand | **~310 days** (range 53–1,110) |
| Average days-since-newest-post | **~10 days** (range 7–25) |
| Most recent scrape | 2026-04-21 (last week) |
| Oldest data point in DB | 2023-04-07 (kfctunisie) |
| Errors logged on prior runs | **0** |

### Recommendations for the upcoming re-scraping run

1. **Use incremental scraping** — every PFE-Tunisian brand was last scraped 7–8 days ago and has its newest post within 7–25 days. Re-scraping the full 100 posts would mostly re-fetch the same data. Strategy: fetch `resultsLimit: 30` (or similar) and de-dup against existing `postUrl` keys, append only the new ones.

2. **Skip `nike` and `sephora`** — they are not part of the Tunisian PFE dataset. The deactivation script `deactivate-beauty-sephora.js` already exists for Sephora; consider running it (separate task) or hard-excluding via `isActive: false`. The Nike row is from `Nike Test Project` and should be excluded by `projectId` filter.

3. **`fstunis` cannot be improved** — the source profile has only 20 posts. The current 19/20 capture is essentially complete. Don't re-attempt.

4. **Use the existing batch scripts** — they already implement smart-skip (`SKIP_THRESHOLD = 100`). For incremental, **lower the threshold or change the strategy** to "fetch newest-N and merge by `postUrl`". Otherwise, **every PFE-Tunisian brand will be skipped again** (as happened to fashion on 2026-04-21).

5. **Hashtags via `topHashtags` only** — 53% of posts have empty `hashtags[]` arrays at the post level. The aggregate `socialanalyses.topHashtags` (parsed inline from caption text by `_extractHashtags`) is the reliable signal for Step 4 (insights) and Step 5 (campaign generator).

6. **Multilingual captions** confirmed (Arabic + French + English in same caption). Make sure any LLM/RAG step uses a model that handles all three (current `groq-sdk` choice is fine for Llama-class models).

7. **No data corruption** — 0 future-dated posts, 0 NaN dates, 0 scraping errors. The current dataset is clean enough to proceed.

8. **Apify rate-limit** — keep the existing `DELAY_MS = 3000` between brands. The April-2026 wave hit no rate limits.

— End of audit —
