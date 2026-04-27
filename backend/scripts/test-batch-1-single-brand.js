// backend/scripts/test-batch-1-single-brand.js
// End-to-end sanity check before running the full batch-1.
// Scrapes ONE brand (@patisseriemasmoudi by default) with up to 100 posts, upserts Competitor +
// SocialAnalysis, then re-reads from MongoDB and verifies recentPosts.length.
//
// Usage:
//   node scripts/test-batch-1-single-brand.js                         # defaults to @patisseriemasmoudi
//   node scripts/test-batch-1-single-brand.js patisseriemasmoudi      # any of the 42 TN brands
//   node scripts/test-batch-1-single-brand.js kastelo.com.tn 50       # custom post count

require('dotenv').config();
const connectDB = require('../src/config/database');
require('../src/models');
const mongoose = require('mongoose');

const User = require('../src/models/User.model');
const Project = require('../src/models/Project.model');
const Competitor = require('../src/models/Competitor.model');
const SocialAnalysis = require('../src/models/SocialAnalysis.model');
const apifyService = require('../src/services/apify.service');

const TEST_EMAIL = 'test-nike@example.com';
const DEFAULT_USERNAME = 'patisseriemasmoudi';
const DEFAULT_POSTS    = 100;

// ═══════════════════════════════════════════════════════════
// 42 Tunisia brands — username → industry
// ═══════════════════════════════════════════════════════════
const BRAND_TO_INDUSTRY = {
  // ─── PÂTISSERIE (8) → food ───────────────────────────────
  'patisseriemasmoudi'      : 'food',
  'patisserie_h_by_omar'    : 'food',
  'mamie.karima'            : 'food',
  'lamaisongourmandise'     : 'food',
  'maisonturki'             : 'food',
  'patisserierekik'         : 'food',
  'patisserie.sakka'        : 'food',
  'labeylicale'             : 'food',

  // ─── FASHION (8) → fashion ───────────────────────────────
  'zen.tunisie'             : 'fashion',
  'ha.hamadiabid'           : 'fashion',
  'kastelo.com.tn'          : 'fashion',
  'chedly_sisters'          : 'fashion',
  'zara'                    : 'fashion',
  'bershka'                 : 'fashion',
  'mango'                   : 'fashion',
  'pullandbear'             : 'fashion',

  // ─── BEAUTY (8) → beauty ─────────────────────────────────
  'floraison.official'      : 'beauty',
  'my_story_cosmetics'      : 'beauty',
  'lellacosmetics'          : 'beauty',
  'therapybylk'             : 'beauty',
  'yvesrocher_tunisie'      : 'beauty',
  'nuxetunisie'             : 'beauty',
  'freya.tn'                : 'beauty',
  'biodermatunisie'         : 'beauty',

  // ─── HOTELS (10) → hotels ────────────────────────────────
  'movenpick_hotel_gammarth': 'hotels',
  'movenpicklactunis'       : 'hotels',
  'el_mouradi_hotels'       : 'hotels',
  'la_badira'               : 'hotels',
  'theresidencetunis'       : 'hotels',
  'hiltonskanesmonastir'    : 'hotels',
  'radissonblutunis'        : 'hotels',
  'soussepearlmarriott'     : 'hotels',
  'tunismarriott'           : 'hotels',
  'fstunis'                 : 'hotels',

  // ─── RESTAURANTS (8) → restaurants ───────────────────────
  'the716lac2'              : 'restaurants',
  'legolfe.restaurant'      : 'restaurants',
  'elfirma.tunis'           : 'restaurants',
  'baguettebaguette'        : 'restaurants',
  'vie.tunis'               : 'restaurants',
  'la_salle_a_manger'       : 'restaurants',
  'kfctunisie'              : 'restaurants',
  'papajohnstn'             : 'restaurants',
};

const PROJECT_BY_INDUSTRY = {
  food       : 'PFE Analysis - Food',
  beauty     : 'PFE Analysis - Beauty',
  fashion    : 'PFE Analysis - Fashion',
  hotels     : 'PFE Analysis - Hotels',
  restaurants: 'PFE Analysis - Restaurants',
};

// Pretty-print the 42 supported brands, grouped by industry.
function printSupportedBrands() {
  const groups = {};
  for (const [u, ind] of Object.entries(BRAND_TO_INDUSTRY)) {
    (groups[ind] = groups[ind] || []).push(u);
  }
  for (const ind of Object.keys(PROJECT_BY_INDUSTRY)) {
    const list = groups[ind] || [];
    console.error(`   ─── ${ind.toUpperCase()} (${list.length}) ───`);
    list.forEach(u => console.error(`      @${u}`));
  }
}

(async () => {
  const t0 = Date.now();

  const usernameArg = (process.argv[2] || DEFAULT_USERNAME).toLowerCase();
  const postsArg    = parseInt(process.argv[3], 10) || DEFAULT_POSTS;

  const industry = BRAND_TO_INDUSTRY[usernameArg];
  if (!industry) {
    console.error(`❌ Unknown brand "${usernameArg}". Supported brands (42 total):\n`);
    printSupportedBrands();
    process.exit(1);
  }

  // Derive the richer shape the downstream code expects.
  const brand = {
    igUsername : usernameArg,
    igUrl      : `https://www.instagram.com/${usernameArg}/`,
    companyName: usernameArg,
    industry   : industry,
  };

  try {
    if (!process.env.APIFY_API_KEY) {
      console.error('❌ APIFY_API_KEY missing from .env');
      process.exit(1);
    }
    console.log(`🔑 APIFY_API_KEY present (${process.env.APIFY_API_KEY.length} chars)`);
    console.log(`🎯 Target: @${brand.igUsername} (${brand.industry}) — ${postsArg} posts\n`);

    await connectDB();

    const user = await User.findOne({ email: TEST_EMAIL });
    if (!user) { console.error(`❌ User not found: ${TEST_EMAIL}`); process.exit(1); }

    const project = await Project.findOne({ userId: user._id, name: PROJECT_BY_INDUSTRY[brand.industry] });
    if (!project) {
      console.error(`❌ Project not found: ${PROJECT_BY_INDUSTRY[brand.industry]}`);
      console.error('   Run: node scripts/create-projects-all-industries.js first.');
      process.exit(1);
    }
    console.log(`👤 User    : ${user.email}`);
    console.log(`📂 Project : ${project.name} (${project._id})\n`);

    // 1. Upsert Competitor
    const competitor = await Competitor.findOneAndUpdate(
      { projectId: project._id, companyName: brand.companyName },
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
          projectId  : project._id,
          companyName: brand.companyName,
          isActive   : true,
        },
      },
      { upsert: true, new: true, runValidators: true, setDefaultsOnInsert: true }
    );
    console.log(`🏷️  Competitor: ${competitor.companyName} (${competitor._id})`);

    // 2. Call Apify
    console.log(`⏳ Scraping via Apify (this may take 2–5 min for ${postsArg} posts)...\n`);
    const tApify = Date.now();
    const igResult = await apifyService.scrapeInstagram(brand.igUrl, postsArg);
    const apifyElapsed = ((Date.now() - tApify) / 1000).toFixed(1);
    console.log(`\n📥 Apify returned (${apifyElapsed}s):`);
    console.log(`   username       : ${igResult.username}`);
    console.log(`   followers      : ${igResult.followers.toLocaleString()}`);
    console.log(`   totalPosts     : ${igResult.totalPosts.toLocaleString()}`);
    console.log(`   recentPosts    : ${igResult.recentPosts?.length || 0}`);
    console.log(`   engagementRate : ${igResult.engagementRate}%`);
    console.log(`   topHashtags    : ${(igResult.topHashtags || []).slice(0, 5).join(', ')}\n`);

    // 3. Upsert SocialAnalysis via findOne+save (fires pre/post hooks)
    let analysis = await SocialAnalysis.findOne({ competitorId: competitor._id, platform: 'instagram' });
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
    console.log(`💾 SocialAnalysis saved: ${analysis._id}`);

    // 4. Update Competitor snapshot
    competitor.socialMedia.instagram.followers  = igResult.followers;
    competitor.socialMedia.instagram.postsCount = igResult.totalPosts;
    competitor.socialMedia.instagram.verified   = igResult.isVerified;
    competitor.scrapingStatus = 'completed';
    competitor.lastScrapedAt  = new Date();
    competitor.scrapingError  = '';
    await competitor.save();

    // 5. Re-read from MongoDB to verify persistence
    const verified = await SocialAnalysis.findById(analysis._id)
      .select('username followers recentPosts topHashtags')
      .lean();
    const savedCount = verified?.recentPosts?.length || 0;
    const firstPost  = verified?.recentPosts?.[0];
    const lastPost   = verified?.recentPosts?.[verified.recentPosts.length - 1];

    console.log('\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
    console.log('🔍 VERIFICATION (re-read from MongoDB)');
    console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
    console.log(`   username         : ${verified.username}`);
    console.log(`   followers        : ${verified.followers.toLocaleString()}`);
    console.log(`   recentPosts.length : ${savedCount}`);
    console.log(`   topHashtags      : ${(verified.topHashtags || []).slice(0, 5).join(', ')}`);
    if (firstPost) {
      console.log(`\n   📌 First post (most recent):`);
      console.log(`      url     : ${firstPost.postUrl}`);
      console.log(`      type    : ${firstPost.contentType}`);
      console.log(`      likes   : ${firstPost.likes?.toLocaleString?.() ?? firstPost.likes}`);
      console.log(`      comments: ${firstPost.comments?.toLocaleString?.() ?? firstPost.comments}`);
      console.log(`      published: ${firstPost.publishedAt || '(n/a)'}`);
    }
    if (lastPost && savedCount > 1) {
      console.log(`\n   📌 Last post (oldest in window):`);
      console.log(`      url     : ${lastPost.postUrl}`);
      console.log(`      published: ${lastPost.publishedAt || '(n/a)'}`);
    }

    const totalElapsed = ((Date.now() - t0) / 1000).toFixed(1);
    console.log(`\n   ⏱️  Total elapsed: ${totalElapsed}s`);

    console.log('\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
    let exitCode;
    if (savedCount === 0) {
      console.log('❌ FAIL — 0 posts scraped (Apify returned nothing)');
      console.log('   This indicates a real pipeline error.');
      console.log('   Check Apify logs and network connectivity.');
      exitCode = 2;
    } else if (savedCount >= postsArg) {
      console.log(`✅ PASS — ${savedCount}/${postsArg} posts persisted in MongoDB`);
      console.log('   Pipeline is green. Safe to run the full batch.');
      exitCode = 0;
    } else {
      console.log(`⚠️  PARTIAL — ${savedCount}/${postsArg} posts persisted`);
      console.log('   Apify returned fewer than requested (acceptable per our rule).');
      console.log('   This is normal for brands with limited post history.');
      console.log('   Pipeline works; batch can continue with this brand.');
      exitCode = 0;
    }
    console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n');

    await mongoose.disconnect();
    process.exit(exitCode);
  } catch (err) {
    console.error('\n❌ FATAL:', err.message);
    if (err.response?.data) console.error('   response:', JSON.stringify(err.response.data).slice(0, 400));
    console.error(err.stack);
    try { await mongoose.disconnect(); } catch (_) {}
    process.exit(1);
  }
})();
