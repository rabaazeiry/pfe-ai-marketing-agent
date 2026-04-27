// backend/scripts/create-projects-all-industries.js
// Upserts the 3 remaining PFE projects (Fashion + Hotels + Restaurants) under
// test-nike@example.com. Food and Beauty are verified but NOT modified.
// Idempotent: safe to run multiple times. Does NOT touch competitors or scraping.
// Usage: node scripts/create-projects-all-industries.js

require('dotenv').config();
const connectDB = require('../src/config/database');
require('../src/models');
const mongoose = require('mongoose');
const User = require('../src/models/User.model');
const Project = require('../src/models/Project.model');

const TEST_EMAIL = 'test-nike@example.com';

// Projects to upsert (new ones only — Food + Beauty are left untouched).
const NEW_PROJECTS = [
  {
    name          : 'PFE Analysis - Fashion',
    industry      : 'fashion',
    marketCategory: 'Fashion',
    businessIdea  : 'PFE ML dataset - Fashion industry competitors',
    country       : 'Tunisie',
    targetCountry : 'TN',
  },
  {
    name          : 'PFE Analysis - Hotels',
    industry      : 'hotels',
    marketCategory: 'Hospitality',
    businessIdea  : 'PFE ML dataset - Hotels industry competitors',
    country       : 'Tunisie',
    targetCountry : 'TN',
  },
  {
    name          : 'PFE Analysis - Restaurants',
    industry      : 'restaurants',
    marketCategory: 'Restaurants',
    businessIdea  : 'PFE ML dataset - Restaurants industry competitors',
    country       : 'Tunisie',
    targetCountry : 'TN',
  },
];

// Projects that must already exist — verified but untouched.
const EXISTING_PROJECT_NAMES = [
  'PFE Analysis - Food',
  'PFE Analysis - Beauty',
];

(async () => {
  try {
    await connectDB();

    const user = await User.findOne({ email: TEST_EMAIL });
    if (!user) {
      console.error(`❌ User not found: ${TEST_EMAIL}`);
      process.exit(1);
    }
    console.log(`👤 User found: ${user.email} (${user._id})\n`);

    // 1. Verify existing Food + Beauty (read-only, no writes)
    console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
    console.log('🔒 EXISTING projects (unchanged)');
    console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
    const existing = [];
    for (const name of EXISTING_PROJECT_NAMES) {
      const p = await Project.findOne({ userId: user._id, name });
      if (p) {
        console.log(`✅ ${p.name}`);
        console.log(`   _id      : ${p._id}`);
        console.log(`   industry : ${p.industry}`);
        console.log(`   status   : ${p.status}\n`);
        existing.push(p);
      } else {
        console.log(`⚠️  ${name} — not found (expected, but missing)\n`);
      }
    }

    // 2. Upsert the 3 new projects (idempotent)
    console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
    console.log('✨ NEW projects (upsert)');
    console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
    const created = {};
    for (const p of NEW_PROJECTS) {
      const doc = await Project.findOneAndUpdate(
        { userId: user._id, name: p.name },
        {
          $set: {
            industry      : p.industry,
            marketCategory: p.marketCategory,
            businessIdea  : p.businessIdea,
            country       : p.country,
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
      created[p.industry] = doc._id.toString();
    }

    // 3. Final summary
    const total = await Project.countDocuments({ userId: user._id });
    console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
    console.log('📊 SUMMARY');
    console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
    console.log(`   Existing (unchanged) : ${existing.map(p => p.name.replace('PFE Analysis - ', '')).join(', ') || '(none)'}`);
    console.log(`   New project IDs      :`);
    console.log(JSON.stringify(created, null, 2));
    console.log(`   Total projects for ${TEST_EMAIL}: ${total}`);

    await mongoose.disconnect();
    process.exit(0);
  } catch (err) {
    console.error('❌ FATAL:', err.message);
    console.error(err.stack);
    try { await mongoose.disconnect(); } catch (_) {}
    process.exit(1);
  }
})();
