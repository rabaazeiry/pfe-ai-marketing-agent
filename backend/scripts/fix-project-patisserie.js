// backend/scripts/fix-project-patisserie.js
//
// Corrige les incohérences du projet PFE identifié comme "Food" alors que
// les concurrents réellement rattachés appartiennent au secteur "patisserie".
//
// Mise à jour appliquée :
//   industry       : "food"              → "patisserie"
//   marketCategory : "Food"              → "Patisserie"
//   name           : "PFE Analysis - Food" → "PFE Analysis - Patisserie"
//   country        : "Tunisie" (inchangé, forcé)
//   targetCountry  : "US"                → "TN"
//
// Usage :
//   node scripts/fix-project-patisserie.js              # applique
//   node scripts/fix-project-patisserie.js --dry-run    # aperçu uniquement
//   node scripts/fix-project-patisserie.js --id <_id>   # cible un projet précis
//
// Idempotent : si le projet est déjà à jour, rien n'est écrit.

require('dotenv').config();

const mongoose  = require('mongoose');
const connectDB = require('../src/config/database');
require('../src/models'); // enregistre tous les schémas
const Project = require('../src/models/Project.model');

const DRY_RUN = process.argv.includes('--dry-run');
const idFlagIdx = process.argv.indexOf('--id');
const TARGET_ID = idFlagIdx !== -1 ? process.argv[idFlagIdx + 1] : null;

const SOURCE_NAME = 'PFE Analysis - Food';

const UPDATES = {
  industry      : 'patisserie',
  marketCategory: 'Patisserie',
  name          : 'PFE Analysis - Patisserie',
  country       : 'Tunisie',
  targetCountry : 'TN'
};

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

    const query = TARGET_ID
      ? { _id: new mongoose.Types.ObjectId(TARGET_ID) }
      : { name: SOURCE_NAME };

    console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
    console.log(`🔍 Recherche du projet : ${JSON.stringify(query)}`);
    console.log(`   mode = ${DRY_RUN ? 'DRY-RUN (aucune écriture)' : 'APPLY'}`);
    console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');

    const candidates = await Project.find(query);
    if (!candidates.length) {
      console.error(`❌ Aucun projet trouvé pour ${JSON.stringify(query)}`);
      process.exit(1);
    }
    if (candidates.length > 1) {
      console.error(`❌ ${candidates.length} projets correspondent — précise avec --id <_id> :`);
      candidates.forEach(p => console.error(`   - ${p._id}  name="${p.name}"  industry="${p.industry}"`));
      process.exit(1);
    }

    const project = candidates[0];
    console.log('\n📄 AVANT :');
    console.log(JSON.stringify(snapshot(project), null, 2));

    // Détecter ce qui changera réellement
    const diff = {};
    for (const [k, v] of Object.entries(UPDATES)) {
      if (project[k] !== v) diff[k] = { from: project[k], to: v };
    }

    if (Object.keys(diff).length === 0) {
      console.log('\n✅ Projet déjà conforme — rien à faire.');
      await mongoose.connection.close();
      process.exit(0);
    }

    console.log('\n📝 CHANGEMENTS :');
    console.log(JSON.stringify(diff, null, 2));

    if (DRY_RUN) {
      console.log('\n💡 DRY-RUN : aucune modification appliquée.');
      await mongoose.connection.close();
      process.exit(0);
    }

    // Application via Mongoose (.save() → validateurs + timestamps)
    for (const [k, v] of Object.entries(UPDATES)) project[k] = v;
    await project.save();

    const refreshed = await Project.findById(project._id);
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
