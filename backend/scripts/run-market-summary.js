// backend/scripts/run-market-summary.js
//
// Déclenche la génération du Market Summary (Étape 2) pour un projet donné,
// puis relit le document `marketresearches` stocké et affiche :
//   1. Les logs du service (déjà émis via console.log du service lui-même)
//   2. Le contenu Markdown du Market Summary
//   3. Les champs principaux du document MongoDB
//   4. Un contrôle de cohérence des chiffres clés
//
// Usage :
//   node scripts/run-market-summary.js <projectId>
//   node scripts/run-market-summary.js <projectId> --expected 8:3:5:8:0
//     (format : total:leaders:startups:local:international)

require('dotenv').config();

const mongoose  = require('mongoose');
const connectDB = require('../src/config/database');
require('../src/models');
const MarketResearch = require('../src/models/MarketResearch.model');
const Project        = require('../src/models/Project.model');
const service        = require('../src/services/marketResearch.service');

const projectId = process.argv[2];
if (!projectId) {
  console.error('Usage : node scripts/run-market-summary.js <projectId> [--expected total:leaders:startups:local:international]');
  process.exit(1);
}

// Expected counts (optional)
let expected = null;
const expIdx = process.argv.indexOf('--expected');
if (expIdx !== -1 && process.argv[expIdx + 1]) {
  const parts = process.argv[expIdx + 1].split(':').map(n => Number(n));
  if (parts.length === 5 && parts.every(n => Number.isFinite(n))) {
    expected = {
      totalCompetitors  : parts[0],
      leaderCount       : parts[1],
      startupCount      : parts[2],
      localCount        : parts[3],
      internationalCount: parts[4]
    };
  }
}

(async () => {
  try {
    await connectDB();

    const project = await Project.findById(projectId).lean();
    if (!project) {
      console.error(`❌ Projet introuvable : ${projectId}`);
      process.exit(1);
    }

    console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
    console.log('📁 Projet ciblé');
    console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
    console.log(JSON.stringify({
      _id           : String(project._id),
      name          : project.name,
      industry      : project.industry,
      marketCategory: project.marketCategory,
      country       : project.country,
      targetCountry : project.targetCountry
    }, null, 2));

    // ─── 1. Generation (logs émis par le service) ───────────────────────────
    console.log('\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
    console.log('🚀 Génération du Market Summary');
    console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
    const startedAt = Date.now();
    await service.generateMarketSummary(projectId);
    const duration = ((Date.now() - startedAt) / 1000).toFixed(1);
    console.log(`   ⏱️  Durée totale : ${duration}s`);

    // ─── 2. Relecture du document stocké ────────────────────────────────────
    const mr = await MarketResearch.findOne({ projectId }).lean();
    if (!mr) {
      console.error('❌ Document MarketResearch introuvable après génération');
      process.exit(1);
    }

    // ─── 3. Contenu Markdown ────────────────────────────────────────────────
    console.log('\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
    console.log('📝 Market Summary — contenu Markdown');
    console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
    console.log(mr.marketSummary.content || '(vide)');

    // ─── 4. Champs stockés ──────────────────────────────────────────────────
    console.log('\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
    console.log('💾 Document MarketResearch — champs principaux');
    console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
    console.log(JSON.stringify({
      _id                  : String(mr._id),
      projectId            : String(mr.projectId),
      status               : mr.status,
      aiModelUsed          : mr.aiModelUsed,
      generatedAt          : mr.generatedAt,
      marketSummary_chars  : (mr.marketSummary && mr.marketSummary.content) ? mr.marketSummary.content.length : 0,
      marketSummary_meta   : {
        generatedAt        : mr.marketSummary && mr.marketSummary.generatedAt,
        competitorsAnalyzed: mr.marketSummary && mr.marketSummary.competitorsAnalyzed
      },
      marketOverview       : mr.marketOverview,
      classificationSummary: mr.classificationSummary,
      error                : mr.error
    }, null, 2));

    // ─── 5. Contrôle des chiffres attendus ──────────────────────────────────
    if (expected) {
      console.log('\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
      console.log('🔢 Contrôle des chiffres');
      console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
      const o = mr.marketOverview || {};
      const rows = [
        ['totalCompetitors',   expected.totalCompetitors,   o.totalCompetitors],
        ['leaderCount',        expected.leaderCount,        o.leaderCount],
        ['startupCount',       expected.startupCount,       o.startupCount],
        ['localCount',         expected.localCount,         o.localCount],
        ['internationalCount', expected.internationalCount, o.internationalCount]
      ];
      let allOk = true;
      for (const [field, exp, got] of rows) {
        const ok = exp === got;
        if (!ok) allOk = false;
        console.log(`   ${ok ? '✅' : '❌'} ${field.padEnd(20)}  attendu=${exp}  obtenu=${got}`);
      }
      console.log(allOk ? '\n✅ Tous les chiffres correspondent exactement.' : '\n❌ Divergence détectée.');
    }

    await mongoose.connection.close();
    process.exit(0);

  } catch (err) {
    console.error(`❌ Échec : ${err.message}`);
    if (err.stack) console.error(err.stack);
    try { await mongoose.connection.close(); } catch (_) {}
    process.exit(1);
  }
})();
