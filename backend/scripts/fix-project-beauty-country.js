// backend/scripts/fix-project-beauty-country.js
//
// Corrige UNIQUEMENT le champ targetCountry du projet Beauty
// (passe de "US" à "TN"). Tous les autres champs restent intacts.
//
// Usage :
//   node scripts/fix-project-beauty-country.js              # applique
//   node scripts/fix-project-beauty-country.js --dry-run    # aperçu uniquement
//
// Idempotent : si targetCountry est déjà "TN", rien n'est écrit.

require('dotenv').config();

const mongoose  = require('mongoose');
const connectDB = require('../src/config/database');
require('../src/models');
const Project = require('../src/models/Project.model');

const PROJECT_ID     = '69e54de3c8a0e851a8b19de0';
const NEW_VALUE      = 'TN';
const DRY_RUN        = process.argv.includes('--dry-run');

function snapshot(p) {
  return {
    _id           : String(p._id),
    name          : p.name,
    industry      : p.industry,
    marketCategory: p.marketCategory,
    country       : p.country,
    targetCountry : p.targetCountry,
    pipelineStatus: p.pipelineStatus,
    status        : p.status,
    updatedAt     : p.updatedAt
  };
}

(async () => {
  try {
    await connectDB();

    const project = await Project.findById(PROJECT_ID);
    if (!project) {
      console.error(`❌ Projet introuvable : ${PROJECT_ID}`);
      process.exit(1);
    }

    console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
    console.log(`🔍 Projet ciblé : ${PROJECT_ID}`);
    console.log(`   mode = ${DRY_RUN ? 'DRY-RUN (aucune écriture)' : 'APPLY'}`);
    console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');

    console.log('\n📄 AVANT :');
    console.log(JSON.stringify(snapshot(project), null, 2));

    if (project.targetCountry === NEW_VALUE) {
      console.log(`\n✅ targetCountry est déjà "${NEW_VALUE}" — rien à faire.`);
      await mongoose.connection.close();
      process.exit(0);
    }

    console.log(`\n📝 CHANGEMENT : targetCountry "${project.targetCountry}" → "${NEW_VALUE}"`);

    if (DRY_RUN) {
      console.log('\n💡 DRY-RUN : aucune modification appliquée.');
      await mongoose.connection.close();
      process.exit(0);
    }

    project.targetCountry = NEW_VALUE;
    await project.save();

    const refreshed = await Project.findById(PROJECT_ID);
    console.log('\n📄 APRÈS :');
    console.log(JSON.stringify(snapshot(refreshed), null, 2));
    console.log('\n✅ Projet mis à jour.');

    await mongoose.connection.close();
    process.exit(0);

  } catch (err) {
    console.error(`❌ Échec : ${err.message}`);
    if (err.errors) {
      for (const [field, e] of Object.entries(err.errors)) {
        console.error(`   • ${field}: ${e.message}`);
      }
    }
    try { await mongoose.connection.close(); } catch (_) {}
    process.exit(1);
  }
})();
