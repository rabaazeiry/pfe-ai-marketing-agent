// backend/scripts/run-swot-one.js
//
// Smoke-test : génère une SWOT pour UN seul concurrent (par défaut le leader
// du projet Patisserie) et affiche le document stocké.
//
// Usage :
//   node scripts/run-swot-one.js                          # patisseriemasmoudi
//   node scripts/run-swot-one.js --competitor <_id>
//   node scripts/run-swot-one.js --name patisseriemasmoudi

require('dotenv').config();

const mongoose  = require('mongoose');
const connectDB = require('../src/config/database');
require('../src/models');
const Competitor   = require('../src/models/Competitor.model');
const SwotAnalysis = require('../src/models/SwotAnalysis.model');
const swotService  = require('../src/services/swot.service');

const idIdx   = process.argv.indexOf('--competitor');
const nameIdx = process.argv.indexOf('--name');
const TARGET_ID   = idIdx   !== -1 ? process.argv[idIdx   + 1] : null;
const TARGET_NAME = nameIdx !== -1 ? process.argv[nameIdx + 1] : 'patisseriemasmoudi';

(async () => {
  try {
    await connectDB();

    let competitor;
    if (TARGET_ID) {
      competitor = await Competitor.findById(TARGET_ID);
    } else {
      competitor = await Competitor.findOne({ companyName: TARGET_NAME });
    }
    if (!competitor) {
      console.error(`❌ Concurrent introuvable (id=${TARGET_ID}, name=${TARGET_NAME})`);
      process.exit(1);
    }

    console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
    console.log(`🎯 Concurrent : ${competitor.companyName}  (${competitor._id})`);
    console.log(`   projectId : ${competitor.projectId}`);
    console.log(`   isActive  : ${competitor.isActive}`);
    console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');

    const startedAt = Date.now();
    await swotService.generateForCompetitor(competitor._id);
    const duration = ((Date.now() - startedAt) / 1000).toFixed(1);
    console.log(`   ⏱️  Durée totale : ${duration}s`);

    const doc = await SwotAnalysis.findByCompetitor(competitor._id).lean();

    console.log('\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
    console.log('📝 SWOT — bullets structurés');
    console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
    const quadLabels = {
      strengths    : '🟢 Forces',
      weaknesses   : '🔴 Faiblesses',
      opportunities: '🔵 Opportunités',
      threats      : '🟠 Menaces'
    };
    const b = doc.swotBullets || {};
    for (const q of ['strengths', 'weaknesses', 'opportunities', 'threats']) {
      console.log(`\n${quadLabels[q]} (${(b[q] || []).length})`);
      for (const bullet of (b[q] || [])) {
        console.log(`  • ${bullet}`);
      }
    }

    console.log('\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
    console.log('🎯 Recommandations actionnables');
    console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
    for (const bullet of (doc.recommendations || [])) {
      console.log(`  • ${bullet}`);
    }

    console.log('\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
    console.log('📡 Sources par section');
    console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
    for (const s of ['strengths', 'weaknesses', 'opportunities', 'threats', 'recommendations']) {
      const src = doc.sources[s] || {};
      console.log(`   ${s.padEnd(16, ' ')} → ${src.type || '—'}${src.reason ? `  (${src.reason})` : ''}`);
    }

    console.log('\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
    console.log('💾 Facts');
    console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
    console.log(JSON.stringify(doc.facts, null, 2));

    console.log('\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
    console.log('🗄️  Document SwotAnalysis (méta)');
    console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
    console.log(JSON.stringify({
      _id: String(doc._id),
      competitorId: String(doc.competitorId),
      projectId: String(doc.projectId),
      companyName: doc.companyName,
      status: doc.status,
      aiModelUsed: doc.aiModelUsed,
      generatedAt: doc.generatedAt,
      error: doc.error
    }, null, 2));

    await mongoose.connection.close();
    process.exit(0);

  } catch (err) {
    console.error(`❌ Échec : ${err.message}`);
    if (err.stack) console.error(err.stack);
    try { await mongoose.connection.close(); } catch (_) {}
    process.exit(1);
  }
})();
