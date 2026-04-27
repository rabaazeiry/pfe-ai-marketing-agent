// backend/scripts/scrape-batch-1.js
// Batch 1 — scrape 150 most recent Instagram posts for 12 brands (6 Food + 6 Beauty).
// Upserts Competitor (key: projectId + companyName) and SocialAnalysis (key: competitorId + platform).
// Stores ALL fetched posts in SocialAnalysis.recentPosts — no slicing, no truncation.
// Re-runnable without creating duplicates.
// Usage: node scripts/scrape-batch-1.js

require('dotenv').config();
const fs = require('fs');
const path = require('path');
const connectDB = require('../src/config/database');
require('../src/models');
const mongoose = require('mongoose');

const User = require('../src/models/User.model');
const Project = require('../src/models/Project.model');
const Competitor = require('../src/models/Competitor.model');
const SocialAnalysis = require('../src/models/SocialAnalysis.model');
const apifyService = require('../src/services/apify.service');

// ═══════════════════════════════════════════════════════════
// CONFIG
// ═══════════════════════════════════════════════════════════

const TEST_EMAIL      = 'test-nike@example.com';
const POSTS_PER_BRAND = 150;
const MIN_REQUIRED    = 150;   // hard failure if we can't persist at least this many
const WARN_THRESHOLD  = 100;   // warn but don't fail between WARN_THRESHOLD and MIN_REQUIRED
const DELAY_BETWEEN   = 3000;  // 3s between brands
const MAX_RETRIES     = 2;     // 2 retries on Apify failure (3 attempts total)
const RETRY_BACKOFF   = 5000;  // 5s between retries

const BRANDS = [
  // ── FOOD ────────────────────────────────────────────────
  { industry: 'food',   companyName: 'Starbucks',      igUsername: 'starbucks',   igUrl: 'https://www.instagram.com/starbucks/'   },
  { industry: 'food',   companyName: "McDonald's",     igUsername: 'mcdonalds',   igUrl: 'https://www.instagram.com/mcdonalds/'   },
  { industry: 'food',   companyName: 'KFC',            igUsername: 'kfc',         igUrl: 'https://www.instagram.com/kfc/'         },
  { industry: 'food',   companyName: "Domino's Pizza", igUsername: 'dominos',     igUrl: 'https://www.instagram.com/dominos/'     },
  { industry: 'food',   companyName: 'Chipotle',       igUsername: 'chipotle',    igUrl: 'https://www.instagram.com/chipotle/'    },
  { industry: 'food',   companyName: 'Krispy Kreme',   igUsername: 'krispykreme', igUrl: 'https://www.instagram.com/krispykreme/' },
  // ── BEAUTY ──────────────────────────────────────────────
  { industry: 'beauty', companyName: 'Sephora',        igUsername: 'sephora',     igUrl: 'https://www.instagram.com/sephora/'     },
  { industry: 'beauty', companyName: 'Glossier',       igUsername: 'glossier',    igUrl: 'https://www.instagram.com/glossier/'    },
  { industry: 'beauty', companyName: "L'Oréal Paris",  igUsername: 'lorealparis', igUrl: 'https://www.instagram.com/lorealparis/' },
  { industry: 'beauty', companyName: 'Fenty Beauty',   igUsername: 'fentybeauty', igUrl: 'https://www.instagram.com/fentybeauty/' },
  { industry: 'beauty', companyName: 'The Body Shop',  igUsername: 'thebodyshop', igUrl: 'https://www.instagram.com/thebodyshop/' },
  { industry: 'beauty', companyName: 'KIKO Milano',    igUsername: 'kikomilano',  igUrl: 'https://www.instagram.com/kikomilano/'  },
];

const PROJECT_NAME = {
  food  : 'PFE Analysis - Food',
  beauty: 'PFE Analysis - Beauty',
};

const sleep = (ms) => new Promise(r => setTimeout(r, ms));

// ═══════════════════════════════════════════════════════════
// SCRAPE ONE BRAND (with retry)
// ═══════════════════════════════════════════════════════════

async function scrapeBrand(brand, projectId, index, total) {
  const tag = `[${index}/${total}] @${brand.igUsername} (${brand.industry})`;
  const t0 = Date.now();

  // 1. Upsert Competitor
  const competitor = await Competitor.findOneAndUpdate(
    { projectId, companyName: brand.companyName },
    {
      $set: {
        classification        : 'leader',
        classificationMaturity: 'leader',
        'socialMedia.instagram.username': brand.igUsername,
        'socialMedia.instagram.url'     : brand.igUrl,
        isManuallyAdded       : true,
        scrapingStatus        : 'in_progress',
      },
      $setOnInsert: {
        projectId,
        companyName: brand.companyName,
        isActive   : true,
      },
    },
    { upsert: true, new: true, runValidators: true, setDefaultsOnInsert: true }
  );

  // 2. Scrape Instagram with retry loop
  let igResult = null;
  let lastError = null;

  for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
    try {
      igResult = await apifyService.scrapeInstagram(brand.igUrl, POSTS_PER_BRAND);
      break;
    } catch (err) {
      lastError = err;
      if (attempt < MAX_RETRIES) {
        console.log(`   ❌ ${tag}: ${err.message} — retry ${attempt + 1}/${MAX_RETRIES}...`);
        await sleep(RETRY_BACKOFF);
      }
    }
  }

  if (!igResult) {
    competitor.scrapingStatus = 'failed';
    competitor.scrapingError  = lastError?.message || 'Unknown error';
    await competitor.save();
    const elapsed = ((Date.now() - t0) / 1000).toFixed(1);
    console.log(`❌ ${tag}: FAILED after ${MAX_RETRIES + 1} attempts (${elapsed}s)`);
    return { ok: false, brand, error: lastError?.message, elapsedSec: parseFloat(elapsed), postsCount: 0 };
  }

  // 3. Upsert SocialAnalysis — findOne+save so pre/post hooks fire
  //    (post-save syncs Competitor.metrics)
  let analysis = await SocialAnalysis.findOne({ competitorId: competitor._id, platform: 'instagram' });
  if (!analysis) {
    analysis = new SocialAnalysis({
      projectId,
      competitorId: competitor._id,
      platform    : 'instagram',
      profileUrl  : igResult.profileUrl,
    });
  }
  Object.assign(analysis, {
    projectId,
    competitorId       : competitor._id,
    platform           : 'instagram',
    profileUrl         : igResult.profileUrl,
    username           : igResult.username,
    isVerified         : igResult.isVerified,
    bio                : (igResult.bio || '').slice(0, 500),
    followers          : igResult.followers,
    following          : igResult.following,
    totalPosts         : igResult.totalPosts,
    postsPerWeek       : igResult.postsPerWeek,
    avgLikes           : igResult.avgLikes,
    avgComments        : igResult.avgComments,
    avgShares          : igResult.avgShares,
    avgViews           : igResult.avgViews,
    engagementRate     : igResult.engagementRate,
    recentPosts        : igResult.recentPosts || [],
    topHashtags        : igResult.topHashtags,
    contentDistribution: igResult.contentDistribution,
    bestDays           : igResult.bestDays,
    bestHours          : igResult.bestHours,
    scrapingStatus     : 'completed',
    lastScrapedAt      : new Date(),
    scrapingError      : '',
  });
  analysis.scrapingAttempts = (analysis.scrapingAttempts || 0) + 1;
  await analysis.save();

  // 4. Verify persistence — re-read from DB to confirm what's actually stored
  const saved = await SocialAnalysis.findById(analysis._id).select('recentPosts').lean();
  const savedCount = saved?.recentPosts?.length || 0;

  // 5. Update Competitor social snapshot + status
  competitor.socialMedia.instagram.followers  = igResult.followers;
  competitor.socialMedia.instagram.postsCount = igResult.totalPosts;
  competitor.socialMedia.instagram.verified   = igResult.isVerified;
  competitor.scrapingStatus = 'completed';
  competitor.lastScrapedAt  = new Date();
  competitor.scrapingError  = '';
  await competitor.save();

  const elapsed = ((Date.now() - t0) / 1000).toFixed(1);
  console.log(`   ✅ @${brand.igUsername}: ${savedCount} recent posts saved in MongoDB (${igResult.followers.toLocaleString()} followers, ${elapsed}s)`);

  // 6. Hard fail if persisted count is below MIN_REQUIRED
  if (savedCount < MIN_REQUIRED) {
    const err = new Error(`POST_COUNT_INSUFFICIENT: @${brand.igUsername} saved only ${savedCount} posts (< ${MIN_REQUIRED} required). Apify may have returned fewer than requested — investigate before continuing.`);
    err.isPostCountError = true;
    throw err;
  }
  if (savedCount < WARN_THRESHOLD) {
    console.log(`   ⚠️  @${brand.igUsername}: low post count (${savedCount} < ${WARN_THRESHOLD})`);
  }

  return {
    ok            : true,
    brand,
    elapsedSec    : parseFloat(elapsed),
    postsCount    : savedCount,
    followers     : igResult.followers,
    engagementRate: igResult.engagementRate,
    competitorId  : competitor._id.toString(),
    analysisId    : analysis._id.toString(),
  };
}

// ═══════════════════════════════════════════════════════════
// MAIN
// ═══════════════════════════════════════════════════════════

(async () => {
  const t0 = Date.now();
  const results = { startedAt: new Date().toISOString(), brands: [] };
  let stoppedEarly = false;

  try {
    if (!process.env.APIFY_API_KEY) {
      console.error('❌ APIFY_API_KEY missing from .env');
      process.exit(1);
    }
    console.log(`🔑 APIFY_API_KEY present (${process.env.APIFY_API_KEY.length} chars)\n`);

    await connectDB();

    const user = await User.findOne({ email: TEST_EMAIL });
    if (!user) { console.error(`❌ User not found: ${TEST_EMAIL}`); process.exit(1); }

    // Resolve project IDs by name
    const projectIds = {};
    for (const industry of Object.keys(PROJECT_NAME)) {
      const p = await Project.findOne({ userId: user._id, name: PROJECT_NAME[industry] });
      if (!p) {
        console.error(`❌ Project not found: ${PROJECT_NAME[industry]}`);
        console.error('   Run: node scripts/create-projects-batch-1.js first.');
        process.exit(1);
      }
      projectIds[industry] = p._id;
    }
    console.log(`📂 Food project   : ${projectIds.food}`);
    console.log(`📂 Beauty project : ${projectIds.beauty}\n`);

    const foodCount   = BRANDS.filter(b => b.industry === 'food').length;
    const beautyCount = BRANDS.filter(b => b.industry === 'beauty').length;
    console.log(`🚀 BATCH 1 - Starting ${BRANDS.length} brands (${foodCount} Food + ${beautyCount} Beauty)`);
    console.log(`   Posts per brand : ${POSTS_PER_BRAND}`);
    console.log(`   Min required    : ${MIN_REQUIRED} (hard fail below this)`);
    console.log(`   Delay between   : ${DELAY_BETWEEN}ms`);
    console.log(`   Retries on fail : ${MAX_RETRIES}\n`);

    // Sequential execution (Apify rate limits; also keeps logs readable)
    for (let i = 0; i < BRANDS.length; i++) {
      const brand = BRANDS[i];
      const projectId = projectIds[brand.industry];
      console.log(`⏳ [${i + 1}/${BRANDS.length}] @${brand.igUsername} (${brand.industry})...`);
      try {
        const r = await scrapeBrand(brand, projectId, i + 1, BRANDS.length);
        results.brands.push(r);
      } catch (err) {
        if (err.isPostCountError) {
          console.error(`\n🛑 STOPPING BATCH: ${err.message}`);
          results.brands.push({ ok: false, brand, error: err.message, elapsedSec: 0, postsCount: 0 });
          stoppedEarly = true;
          break;
        }
        console.log(`❌ @${brand.igUsername}: unexpected error — ${err.message}`);
        results.brands.push({ ok: false, brand, error: err.message, elapsedSec: 0, postsCount: 0 });
      }
      if (i < BRANDS.length - 1) await sleep(DELAY_BETWEEN);
    }

    // ─── SUMMARY ─────────────────────────────────────────────
    const totalElapsed = (Date.now() - t0) / 1000;
    const ok   = results.brands.filter(b => b.ok);
    const fail = results.brands.filter(b => !b.ok);
    const totalPostsPersisted = ok.reduce((s, b) => s + (b.postsCount || 0), 0);
    const estimatedCost = (ok.length * 0.05).toFixed(2);

    results.finishedAt        = new Date().toISOString();
    results.totalSec          = parseFloat(totalElapsed.toFixed(1));
    results.successCount      = ok.length;
    results.failureCount      = fail.length;
    results.totalPostsPersisted = totalPostsPersisted;
    results.stoppedEarly      = stoppedEarly;

    console.log('\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
    console.log('📊 BATCH 1 RECAP');
    console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
    console.log(`   ✅ Success       : ${ok.length}/${BRANDS.length} brands`);
    console.log(`   ❌ Failed        : ${fail.length}/${BRANDS.length} brands`);
    console.log(`   📦 Total posts persisted : ${totalPostsPersisted}`);
    console.log(`   ⏱️  Total time    : ${(totalElapsed / 60).toFixed(1)} min`);
    console.log(`   💰 Est. cost     : ~$${estimatedCost}`);
    if (stoppedEarly) {
      console.log(`   🛑 Stopped early : yes (insufficient post count)`);
    }

    if (fail.length > 0) {
      console.log('\n   Failed brands:');
      fail.forEach(f => console.log(`     - @${f.brand.igUsername}: ${f.error}`));
    }

    const reportPath = path.join(__dirname, '..', 'batch-1-results.json');
    fs.writeFileSync(reportPath, JSON.stringify(results, null, 2));
    console.log(`\n   📂 Report: ${reportPath}\n`);

    await mongoose.disconnect();
    process.exit(fail.length === 0 ? 0 : 2);
  } catch (err) {
    console.error('\n❌ FATAL:', err.message);
    console.error(err.stack);
    try {
      results.fatalError = err.message;
      results.finishedAt = new Date().toISOString();
      fs.writeFileSync(path.join(__dirname, '..', 'batch-1-results.json'), JSON.stringify(results, null, 2));
    } catch (_) {}
    try { await mongoose.disconnect(); } catch (_) {}
    process.exit(1);
  }
})();
