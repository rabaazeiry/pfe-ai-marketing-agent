// backend/scripts/deactivate-beauty-sephora.js
//
// Désactive le concurrent "Sephora" du projet Beauty (test historique,
// ne fait pas partie du dataset Beauty Tunisie) SANS suppression définitive.
//
// Actions :
//   1. Trouve le concurrent Sephora dans le projet Beauty (match insensible
//      à la casse sur companyName).
//   2. Competitor : isActive = false, notes += marqueur d'exclusion.
//   3. SocialAnalysis liées : isActive = false via updateMany sur la
//      collection brute (le champ n'existe pas dans le schéma Mongoose ;
//      la virtuelle est dérivée de lastScrapedAt). Pattern déjà employé
//      par update-competitor-classification.js pour des champs hors-schéma.
//   4. Vérification : compte les concurrents encore actifs du projet et
//      liste leurs noms.
//
// Usage :
//   node scripts/deactivate-beauty-sephora.js              # applique
//   node scripts/deactivate-beauty-sephora.js --dry-run    # aperçu uniquement
//
// Idempotent.

require('dotenv').config();

const mongoose  = require('mongoose');
const connectDB = require('../src/config/database');
require('../src/models');
const Project        = require('../src/models/Project.model');
const Competitor     = require('../src/models/Competitor.model');
const SocialAnalysis = require('../src/models/SocialAnalysis.model');

const PROJECT_ID = '69e54de3c8a0e851a8b19de0';
const BRAND_RE   = /sephora/i;
const NOTE_TAG   = 'Test scraping initial - excluded from Beauty Tunisia dataset';
const DRY_RUN    = process.argv.includes('--dry-run');

(async () => {
  try {
    await connectDB();

    const project = await Project.findById(PROJECT_ID);
    if (!project) {
      console.error(`❌ Projet introuvable : ${PROJECT_ID}`);
      process.exit(1);
    }

    console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
    console.log(`🎯 Projet : ${project.name} (${PROJECT_ID})`);
    console.log(`   mode = ${DRY_RUN ? 'DRY-RUN (aucune écriture)' : 'APPLY'}`);
    console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');

    // 1. Locate Sephora
    const candidates = await Competitor.find({
      projectId  : PROJECT_ID,
      companyName: { $regex: BRAND_RE }
    });

    if (candidates.length === 0) {
      console.error(`❌ Aucun concurrent "Sephora" trouvé dans ce projet.`);
      await mongoose.connection.close();
      process.exit(1);
    }
    if (candidates.length > 1) {
      console.warn(`⚠️  ${candidates.length} concurrents correspondent à /sephora/i :`);
      candidates.forEach(c => console.warn(`   - ${c._id}  "${c.companyName}"  isActive=${c.isActive}`));
      console.warn(`   → désactivation appliquée sur TOUS.`);
    }

    // 2. Apply competitor update
    let competitorsTouched = 0;
    const touchedIds = [];
    for (const c of candidates) {
      const before = { isActive: c.isActive, notes: c.notes };
      const alreadyInactive = c.isActive === false;
      const alreadyTagged   = typeof c.notes === 'string' && c.notes.includes(NOTE_TAG);

      if (alreadyInactive && alreadyTagged) {
        console.log(`\n✅ ${c.companyName} (${c._id}) déjà désactivé + tagué — aucune modification.`);
        continue;
      }

      console.log(`\n📝 ${c.companyName} (${c._id})`);
      console.log(`   AVANT : isActive=${before.isActive}, notes=${JSON.stringify(before.notes)}`);

      const newNotes = alreadyTagged
        ? c.notes
        : (c.notes && c.notes.trim() ? `${c.notes.trim()}\n${NOTE_TAG}` : NOTE_TAG);

      if (!DRY_RUN) {
        c.isActive = false;
        c.notes    = newNotes;
        await c.save();
        competitorsTouched++;
      }

      console.log(`   APRÈS : isActive=false, notes=${JSON.stringify(newNotes)}`);
      touchedIds.push(c._id);
    }

    // 3. Deactivate related SocialAnalysis (via raw collection, schema-agnostic)
    const socialsBefore = await SocialAnalysis.find({ competitorId: { $in: touchedIds.length ? touchedIds : candidates.map(c => c._id) } }).lean();
    console.log(`\n📡 ${socialsBefore.length} document(s) SocialAnalysis liés à Sephora.`);
    if (socialsBefore.length) {
      for (const s of socialsBefore) {
        console.log(`   - ${s._id}  platform=${s.platform}  username=${s.username || '—'}  isActive(brut)=${s.isActive ?? '—'}`);
      }
    }

    if (!DRY_RUN && socialsBefore.length) {
      const res = await mongoose.connection.db.collection('socialanalyses').updateMany(
        { competitorId: { $in: socialsBefore.map(s => s._id.constructor === mongoose.Types.ObjectId ? s.competitorId : new mongoose.Types.ObjectId(s.competitorId)) } },
        { $set: { isActive: false, deactivatedAt: new Date(), deactivationReason: NOTE_TAG } }
      );
      console.log(`   🔕 updateMany matched=${res.matchedCount} modified=${res.modifiedCount}`);
    }

    // 4. Verify
    const activeCount = await Competitor.countDocuments({ projectId: PROJECT_ID, isActive: true });
    const activeList  = await Competitor.find({ projectId: PROJECT_ID, isActive: true })
      .sort({ 'metrics.totalFollowers': -1 })
      .select('companyName metrics.totalFollowers')
      .lean();

    console.log('\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
    console.log(`🔢 Concurrents actifs restants : ${activeCount}`);
    console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
    activeList.forEach((c, i) => {
      const fol = c.metrics && c.metrics.totalFollowers ? c.metrics.totalFollowers : '—';
      console.log(`   ${String(i + 1).padStart(2, ' ')}. ${c.companyName}  (followers=${fol})`);
    });

    if (DRY_RUN) console.log('\n💡 DRY-RUN : aucune modification appliquée.');
    else        console.log(`\n✅ Terminé — ${competitorsTouched} concurrent(s) désactivé(s).`);

    await mongoose.connection.close();
    process.exit(0);

  } catch (err) {
    console.error(`❌ Échec : ${err.message}`);
    if (err.stack) console.error(err.stack);
    try { await mongoose.connection.close(); } catch (_) {}
    process.exit(1);
  }
})();
