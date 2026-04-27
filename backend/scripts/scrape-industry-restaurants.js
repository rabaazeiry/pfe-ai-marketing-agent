// backend/scripts/scrape-industry-restaurants.js
// Smart batch: scrapes the 8 restaurant brands, auto-skips any brand that
// already has ≥ SKIP_THRESHOLD posts in MongoDB. Re-runnable + resumable.
//
// Usage:
//   node scripts/scrape-industry-restaurants.js

require('dotenv').config();
const fs       = require('fs');
const path     = require('path');
const mongoose = require('mongoose');

const connectDB      = require('../src/config/database');
require('../src/models');
const User           = require('../src/models/User.model');
const Project        = require('../src/models/Project.model');
const Competitor     = require('../src/models/Competitor.model');
const SocialAnalysis = require('../src/models/SocialAnalysis.model');
const apifyService   = require('../src/services/apify.service');

// ═══════════════════════════════════════════════════════════
// CONFIG
// ═══════════════════════════════════════════════════════════
const INDUSTRY        = 'restaurants';
const PROJECT_NAME    = 'PFE Analysis - Restaurants';
const TEST_EMAIL      = 'test-nike@example.com';
const POSTS_PER_BRAND = 100;
const DELAY_MS        = 3000;
const SKIP_THRESHOLD  = 100;
const COST_PER_BRAND  = 0.10; // rough Apify credits estimate ($/brand scraped)
const RESULTS_FILE    = path.resolve(__dirname, '..', 'restaurants-batch-results.json');

const BRANDS = [
  // ═══ FINE DINING & LOCAL STARS (4) — sorted by followers ═══
  'the716lac2',          // 72K, 658 posts ⭐ 3 stars
  'legolfe.restaurant',  // 69K, 174 posts 🏆 N°1 50 Best
  'elfirma.tunis',       // 51K, 217 posts
  'baguettebaguette',    // 48K, 1902 posts
  // ═══ INTERNATIONAL CHAINS + LOCAL (4) — sorted by followers ═══
  'kfctunisie',          // 45K, 488 posts 🇺🇸 KFC
  'vie.tunis',           // 28K, 123 posts
  'papajohnstn',         // 22K, 1291 posts 🇺🇸 Papa John's
  'la_salle_a_manger',   // 20K, 1506 posts
];

const sleep = (ms) => new Promise(r => setTimeout(r, ms));

function fmtDuration(ms) {
  const s = Math.round(ms / 1000);
  const m = Math.floor(s / 60);
  return `${m}m ${s - m * 60}s`;
}

(async () => {
  const t0 = Date.now();
  const stats = {
    startedAt: new Date().toISOString(),
    industry : INDUSTRY,
    project  : PROJECT_NAME,
    brands   : BRANDS,
    skipped  : [],
    success  : [],
    partial  : [],
    failed   : [],
  };

  try {
    if (!process.env.APIFY_API_KEY) {
      console.error('❌ APIFY_API_KEY missing from .env');
      process.exit(1);
    }
    console.log(`🔑 APIFY_API_KEY present (${process.env.APIFY_API_KEY.length} chars)`);
    console.log(`🎯 Industry : ${INDUSTRY} (${BRANDS.length} brands)`);
    console.log(`📦 Target   : ${POSTS_PER_BRAND} posts/brand, skip if ≥${SKIP_THRESHOLD} already in DB\n`);

    await connectDB();

    const user = await User.findOne({ email: TEST_EMAIL });
    if (!user) { console.error(`❌ User not found: ${TEST_EMAIL}`); process.exit(1); }

    const project = await Project.findOne({ userId: user._id, name: PROJECT_NAME });
    if (!project) {
      console.error(`❌ Project not found: ${PROJECT_NAME}`);
      console.error('   Run: node scripts/create-projects-all-industries.js first.');
      process.exit(1);
    }
    console.log(`👤 User    : ${user.email}`);
    console.log(`📂 Project : ${project.name} (${project._id})\n`);
    console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');

    for (let i = 0; i < BRANDS.length; i++) {
      const username = BRANDS[i].toLowerCase();
      const position = `[${i + 1}/${BRANDS.length}]`;
      const igUrl    = `https://www.instagram.com/${username}/`;
      const tBrand   = Date.now();
      let didScrape  = false;

      try {
        // 1. SMART SKIP — does this brand already have enough posts?
        const existing = await Competitor.findOne({
          projectId  : project._id,
          companyName: username,
        });

        if (existing) {
          const existingAnalysis = await SocialAnalysis.findOne({
            projectId   : project._id,
            competitorId: existing._id,
            platform    : 'instagram',
          }).select('recentPosts').lean();

          const existingCount = existingAnalysis?.recentPosts?.length || 0;
          if (existingCount >= SKIP_THRESHOLD) {
            console.log(`${position} ⏭️  @${username}: skipped (${existingCount} posts already in DB)`);
            stats.skipped.push({ username, existingCount });
            continue;
          }
        }

        // 2. SCRAPE
        console.log(`${position} ⏳ @${username}: scraping...`);
        didScrape = true;

        const competitor = await Competitor.findOneAndUpdate(
          { projectId: project._id, companyName: username },
          {
            $set: {
              classification        : 'leader',
              classificationMaturity: 'leader',
              'socialMedia.instagram.username': username,
              'socialMedia.instagram.url'     : igUrl,
              isManuallyAdded       : true,
              scrapingStatus        : 'in_progress',
            },
            $setOnInsert: {
              projectId  : project._id,
              companyName: username,
              isActive   : true,
            },
          },
          { upsert: true, new: true, runValidators: true, setDefaultsOnInsert: true }
        );

        const igResult = await apifyService.scrapeInstagram(igUrl, POSTS_PER_BRAND);

        let analysis = await SocialAnalysis.findOne({
          competitorId: competitor._id,
          platform    : 'instagram',
        });
        if (!analysis) {
          analysis = new SocialAnalysis({
            projectId   : project._id,
            competitorId: competitor._id,
            platform    : 'instagram',
            profileUrl  : igResult.profileUrl,
          });
        }
        Object.assign(analysis, {
          projectId   : project._id,
          competitorId: competitor._id,
          platform    : 'instagram',
          profileUrl  : igResult.profileUrl,
          username    : igResult.username,
          isVerified  : igResult.isVerified,
          bio         : (igResult.bio || '').slice(0, 500),
          followers   : igResult.followers,
          following   : igResult.following,
          totalPosts  : igResult.totalPosts,
          postsPerWeek: igResult.postsPerWeek,
          avgLikes    : igResult.avgLikes,
          avgComments : igResult.avgComments,
          avgShares   : igResult.avgShares,
          avgViews    : igResult.avgViews,
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

        competitor.socialMedia.instagram.followers  = igResult.followers;
        competitor.socialMedia.instagram.postsCount = igResult.totalPosts;
        competitor.socialMedia.instagram.verified   = igResult.isVerified;
        competitor.scrapingStatus = 'completed';
        competitor.lastScrapedAt  = new Date();
        competitor.scrapingError  = '';
        await competitor.save();

        const verified   = await SocialAnalysis.findById(analysis._id).select('recentPosts').lean();
        const savedCount = verified?.recentPosts?.length || 0;
        const elapsedSec = Number(((Date.now() - tBrand) / 1000).toFixed(1));

        if (savedCount === 0) {
          throw new Error('0 posts returned from Apify');
        } else if (savedCount >= POSTS_PER_BRAND) {
          console.log(`${position} ✅ @${username}: ${savedCount} posts saved (${elapsedSec}s)`);
          stats.success.push({ username, postsCount: savedCount, elapsedSec });
        } else {
          console.log(`${position} ⚠️  @${username}: ${savedCount}/${POSTS_PER_BRAND} posts saved (${elapsedSec}s, partial)`);
          stats.partial.push({ username, postsCount: savedCount, elapsedSec });
        }
      } catch (err) {
        const elapsedSec = Number(((Date.now() - tBrand) / 1000).toFixed(1));
        console.log(`${position} ❌ @${username}: ${err.message} (${elapsedSec}s)`);
        stats.failed.push({ username, error: err.message, elapsedSec });
      }

      // Rate limit ONLY between scraped brands (no sleep after a skip)
      if (didScrape && i < BRANDS.length - 1) await sleep(DELAY_MS);
    }

    // ═══════════════════════════════════════════════════════════
    // RECAP
    // ═══════════════════════════════════════════════════════════
    const totalMs       = Date.now() - t0;
    const totalNewPosts = stats.success.reduce((s, b) => s + b.postsCount, 0)
                        + stats.partial.reduce((s, b) => s + b.postsCount, 0);
    const scrapedBrands = stats.success.length + stats.partial.length + stats.failed.length;
    const estCost       = (scrapedBrands * COST_PER_BRAND).toFixed(2);

    stats.endedAt       = new Date().toISOString();
    stats.totalMs       = totalMs;
    stats.totalNewPosts = totalNewPosts;
    stats.estCostUSD    = Number(estCost);

    console.log('\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
    console.log('📊 RESTAURANTS BATCH RECAP');
    console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');

    console.log(`⏭️  Skipped (already in DB) : ${stats.skipped.length} brand(s)`);
    stats.skipped.forEach(b => console.log(`     @${b.username}: ${b.existingCount} posts`));

    console.log(`✅ Scraped (${POSTS_PER_BRAND} posts)      : ${stats.success.length} brand(s)`);
    stats.success.forEach(b => console.log(`     @${b.username}: ${b.postsCount} posts (${b.elapsedSec}s)`));

    console.log(`⚠️  Partial (<${POSTS_PER_BRAND} posts)    : ${stats.partial.length} brand(s)`);
    stats.partial.forEach(b => console.log(`     @${b.username}: ${b.postsCount} posts (${b.elapsedSec}s)`));

    console.log(`❌ Failed                   : ${stats.failed.length} brand(s)`);
    stats.failed.forEach(b => console.log(`     @${b.username}: ${b.error}`));

    console.log(`📦 Total NEW posts scraped  : ${totalNewPosts}`);
    console.log(`⏱️  Total time               : ${fmtDuration(totalMs)}`);
    console.log(`💰 Est. cost                : ~$${estCost} (based on ${scrapedBrands} actually scraped)`);
    console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n');

    fs.writeFileSync(RESULTS_FILE, JSON.stringify(stats, null, 2), 'utf8');
    console.log(`💾 Results saved to: ${RESULTS_FILE}\n`);

    await mongoose.disconnect();

    // Exit 0 if at least one brand is OK (success/partial/skipped); exit 2 only if everything failed
    const anyOK = stats.success.length + stats.partial.length + stats.skipped.length > 0;
    process.exit(anyOK ? 0 : 2);
  } catch (err) {
    console.error('\n❌ FATAL:', err.message);
    console.error(err.stack);
    try { await mongoose.disconnect(); } catch (_) {}
    process.exit(1);
  }
})();
