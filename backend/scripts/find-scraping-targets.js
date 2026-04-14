// backend/scripts/find-scraping-targets.js
// One-shot: list competitors with Instagram / Facebook handles, grouped by project.
// Usage: node scripts/find-scraping-targets.js

require('dotenv').config();
const connectDB = require('../src/config/database');
require('../src/models'); // register all schemas
const mongoose = require('mongoose');
const Competitor = require('../src/models/Competitor.model');
const Project = require('../src/models/Project.model');

(async () => {
  try {
    await connectDB();

    const competitors = await Competitor.find({
      isActive: true,
      $or: [
        { 'socialMedia.instagram.username': { $exists: true, $ne: '' } },
        { 'socialMedia.facebook.url': { $exists: true, $ne: '' } }
      ]
    })
      .select('_id companyName projectId socialMedia scrapingStatus lastScrapedAt')
      .lean();

    if (competitors.length === 0) {
      console.log('\n❌ No competitor has Instagram username or Facebook URL set.');
      console.log('   You need to run Step 2 of the pipeline (competitor discovery) first.\n');
      process.exit(0);
    }

    const byProject = new Map();
    for (const c of competitors) {
      const key = String(c.projectId);
      if (!byProject.has(key)) byProject.set(key, []);
      byProject.get(key).push(c);
    }

    const projects = await Project.find({ _id: { $in: [...byProject.keys()] } })
      .select('_id businessIdea pipelineStatus')
      .lean();

    console.log(`\n📊 Found ${competitors.length} scrape-ready competitor(s) across ${byProject.size} project(s):\n`);

    for (const p of projects) {
      const list = byProject.get(String(p._id)) || [];
      console.log(`━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━`);
      console.log(`PROJECT  ${p._id}`);
      console.log(`  idea   : ${p.businessIdea}`);
      console.log(`  status : ${p.pipelineStatus}`);
      console.log(`  competitors:`);
      for (const c of list) {
        const ig = c.socialMedia?.instagram?.username || '—';
        const fb = c.socialMedia?.facebook?.url || '—';
        console.log(`    • ${c._id}  ${c.companyName}`);
        console.log(`         IG: @${ig}`);
        console.log(`         FB: ${fb}`);
        console.log(`         scrapingStatus: ${c.scrapingStatus || 'pending'}  lastScrapedAt: ${c.lastScrapedAt || 'never'}`);
      }
    }
    console.log(`━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n`);
    console.log(`👉 Pick ONE competitor with a real IG username and copy its _id + projectId.\n`);

    await mongoose.disconnect();
    process.exit(0);
  } catch (err) {
    console.error('❌ Error:', err);
    process.exit(1);
  }
})();
