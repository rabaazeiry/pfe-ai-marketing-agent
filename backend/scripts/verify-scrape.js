// backend/scripts/verify-scrape.js
// Inspect what the smoke-test scrape actually wrote to MongoDB.
// Usage: node scripts/verify-scrape.js <competitorId>

require('dotenv').config();
const connectDB = require('../src/config/database');
require('../src/models');
const mongoose = require('mongoose');
const Competitor = require('../src/models/Competitor.model');
const SocialAnalysis = require('../src/models/SocialAnalysis.model');

const competitorId = process.argv[2];
if (!competitorId) {
  console.error('Usage: node scripts/verify-scrape.js <competitorId>');
  process.exit(1);
}

(async () => {
  try {
    await connectDB();

    const c = await Competitor.findById(competitorId).lean();
    if (!c) {
      console.log(`❌ Competitor ${competitorId} not found.`);
      process.exit(1);
    }

    console.log('\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
    console.log('COMPETITOR');
    console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
    console.log(`  _id             : ${c._id}`);
    console.log(`  companyName     : ${c.companyName}`);
    console.log(`  scrapingStatus  : ${c.scrapingStatus}`);
    console.log(`  scrapingError   : ${c.scrapingError || '(none)'}`);
    console.log(`  lastScrapedAt   : ${c.lastScrapedAt || '(never)'}`);
    console.log(`  metrics         :`, c.metrics);
    console.log(`  IG              :`, c.socialMedia?.instagram);
    console.log(`  FB              :`, c.socialMedia?.facebook);

    const analyses = await SocialAnalysis.find({ competitorId }).lean();

    console.log('\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
    console.log(`SOCIAL ANALYSES  (${analyses.length} docs)`);
    console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');

    if (analyses.length === 0) {
      console.log('  (no SocialAnalysis documents exist for this competitor)');
    }

    for (const a of analyses) {
      console.log(`\n  ── ${a.platform.toUpperCase()} ──`);
      console.log(`  _id             : ${a._id}`);
      console.log(`  scrapingStatus  : ${a.scrapingStatus}`);
      console.log(`  scrapingError   : ${a.scrapingError || '(none)'}`);
      console.log(`  lastScrapedAt   : ${a.lastScrapedAt || '(never)'}`);
      console.log(`  username        : ${a.username}`);
      console.log(`  profileUrl      : ${a.profileUrl}`);
      console.log(`  followers       : ${a.followers}`);
      console.log(`  following       : ${a.following}`);
      console.log(`  totalPosts      : ${a.totalPosts}`);
      console.log(`  avgLikes        : ${a.avgLikes}`);
      console.log(`  avgComments     : ${a.avgComments}`);
      console.log(`  engagementRate  : ${a.engagementRate}`);
      console.log(`  performanceScore: ${a.performanceScore}`);
      console.log(`  topPosts count  : ${a.topPosts?.length || 0}`);
      console.log(`  topHashtags     : ${(a.topHashtags || []).slice(0, 5).join(', ')}${(a.topHashtags || []).length > 5 ? '...' : ''}`);
    }

    console.log('\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n');

    await mongoose.disconnect();
    process.exit(0);
  } catch (err) {
    console.error('❌ Error:', err);
    process.exit(1);
  }
})();
