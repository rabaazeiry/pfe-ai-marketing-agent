// backend/scripts/create-projects-batch-1.js
// Upserts the 2 PFE projects (Food + Beauty) under test-nike@example.com.
// Idempotent: safe to run multiple times. Does NOT touch competitors or scraping.
// Usage: node scripts/create-projects-batch-1.js

require('dotenv').config();
const connectDB = require('../src/config/database');
require('../src/models');
const mongoose = require('mongoose');
const User = require('../src/models/User.model');
const Project = require('../src/models/Project.model');

const TEST_EMAIL = 'test-nike@example.com';

const PROJECTS = [
  {
    name          : 'PFE Analysis - Food',
    industry      : 'food',
    marketCategory: 'Food',
    businessIdea  : 'PFE ML dataset - Food industry competitor leaders',
    targetCountry : 'US',
  },
  {
    name          : 'PFE Analysis - Beauty',
    industry      : 'beauty',
    marketCategory: 'Beauty',
    businessIdea  : 'PFE ML dataset - Beauty industry competitor leaders',
    targetCountry : 'US',
  },
];

(async () => {
  try {
    await connectDB();

    const user = await User.findOne({ email: TEST_EMAIL });
    if (!user) {
      console.error(`❌ User not found: ${TEST_EMAIL}`);
      console.error('   Run the test-nike onboarding first, or change TEST_EMAIL.');
      process.exit(1);
    }
    console.log(`👤 User found: ${user.email} (${user._id})\n`);

    const out = {};
    for (const p of PROJECTS) {
      const doc = await Project.findOneAndUpdate(
        { userId: user._id, name: p.name },
        {
          $set: {
            industry      : p.industry,
            marketCategory: p.marketCategory,
            businessIdea  : p.businessIdea,
            targetCountry : p.targetCountry,
            status        : 'active',
          },
          $setOnInsert: {
            userId: user._id,
            name  : p.name,
          },
        },
        { upsert: true, new: true, runValidators: true, setDefaultsOnInsert: true }
      );
      console.log(`✅ ${doc.name}`);
      console.log(`   _id      : ${doc._id}`);
      console.log(`   industry : ${doc.industry}`);
      console.log(`   status   : ${doc.status}\n`);
      out[p.industry] = doc._id.toString();
    }

    console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
    console.log('Project IDs (copy if scrape-batch-1.js needs manual override)');
    console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
    console.log(JSON.stringify(out, null, 2));

    await mongoose.disconnect();
    process.exit(0);
  } catch (err) {
    console.error('❌ FATAL:', err.message);
    console.error(err.stack);
    process.exit(1);
  }
})();
