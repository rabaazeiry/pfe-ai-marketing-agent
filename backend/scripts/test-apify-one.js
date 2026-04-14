// backend/scripts/test-apify-one.js
// Smoke-test the existing apify.service.js against ONE real competitor.
// Does NOT touch MongoDB — just prints what Apify would return.
// Usage: node scripts/test-apify-one.js <competitorId>

require('dotenv').config();
const connectDB = require('../src/config/database');
require('../src/models');
const mongoose = require('mongoose');
const Competitor = require('../src/models/Competitor.model');
const apifyService = require('../src/services/apify.service');

const competitorId = process.argv[2];
if (!competitorId) {
  console.error('Usage: node scripts/test-apify-one.js <competitorId>');
  process.exit(1);
}

(async () => {
  const t0 = Date.now();
  try {
    if (!process.env.APIFY_API_KEY) {
      console.error('❌ APIFY_API_KEY is missing from .env');
      process.exit(1);
    }
    console.log(`🔑 APIFY_API_KEY present (${process.env.APIFY_API_KEY.length} chars)`);

    await connectDB();

    const c = await Competitor.findById(competitorId).lean();
    if (!c) { console.error('❌ Competitor not found'); process.exit(1); }

    console.log(`\n🎯 Target: ${c.companyName}`);
    console.log(`   IG url: ${c.socialMedia?.instagram?.url || '(none)'}`);
    console.log(`   FB url: ${c.socialMedia?.facebook?.url || '(none)'}`);
    console.log(`\n⏳ Running Apify (can take 30–120s per platform)...\n`);

    const result = await apifyService.scrapeCompetitor(c);

    console.log('\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
    console.log(`APIFY RESULT  (total elapsed: ${((Date.now() - t0) / 1000).toFixed(1)}s)`);
    console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');

    const summarize = (label, r) => {
      console.log(`\n${label}:`);
      if (!r) { console.log('  (null — skipped or failed)'); return; }
      console.log(`  username      : ${r.username}`);
      console.log(`  followers     : ${r.followers}`);
      console.log(`  following     : ${r.following}`);
      console.log(`  totalPosts    : ${r.totalPosts}`);
      console.log(`  avgLikes      : ${r.avgLikes}`);
      console.log(`  avgComments   : ${r.avgComments}`);
      console.log(`  engagementRate: ${r.engagementRate}`);
      console.log(`  topPosts      : ${r.topPosts?.length || 0}`);
      console.log(`  topHashtags   : ${(r.topHashtags || []).slice(0, 5).join(', ')}`);
      console.log(`  isVerified    : ${r.isVerified}`);
    };

    summarize('INSTAGRAM', result.instagram);
    summarize('FACEBOOK',  result.facebook);

    console.log('\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n');

    await mongoose.disconnect();
    process.exit(0);
  } catch (err) {
    console.error('\n❌ FATAL:', err.message);
    if (err.response?.data) console.error('   response:', JSON.stringify(err.response.data).slice(0, 400));
    process.exit(1);
  }
})();
