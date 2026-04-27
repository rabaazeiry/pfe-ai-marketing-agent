// backend/scripts/reassign-dataset-projects.js
//
// Re-assigne les 5 projets du dataset PFE (Patisserie, Fashion, Hotels, Beauty,
// Restaurants) à un utilisateur cible — par défaut admin@pfe.local — pour que
// ce dernier puisse les voir via GET /api/projects (qui filtre par
// `userId = req.user.id`).
//
// Ne supprime AUCUNE donnée. N'écrit rien tant que --apply n'est pas passé.
//
// Backend :
//   - projects.controller.js: find({ userId: req.user.id })
//   - competitors.controller.js: autorise si project.userId === req.user._id
//   - marketResearch.controller.js: pas de filtrage userId (protégé JWT seulement)
//   → reassigner `Project.userId` suffit pour voir la liste, ouvrir le détail,
//     afficher les concurrents et lancer la génération du Market Summary.
//
// Usage :
//   node scripts/reassign-dataset-projects.js                 # dry-run (défaut)
//   node scripts/reassign-dataset-projects.js --apply         # applique
//   node scripts/reassign-dataset-projects.js --email foo@bar # cible un autre user
//
// Idempotent : si un projet appartient déjà à l'utilisateur cible, il est sauté.

require('dotenv').config();

const mongoose  = require('mongoose');
const connectDB = require('../src/config/database');
require('../src/models');
const User    = require('../src/models/User.model');
const Project = require('../src/models/Project.model');

const DATASET_NAMES = [
  'PFE Analysis - Patisserie',
  'PFE Analysis - Fashion',
  'PFE Analysis - Hotels',
  'PFE Analysis - Beauty',
  'PFE Analysis - Restaurants'
];

const APPLY = process.argv.includes('--apply');
const emailIdx = process.argv.indexOf('--email');
const TARGET_EMAIL = emailIdx !== -1 ? process.argv[emailIdx + 1] : 'admin@pfe.local';

(async () => {
  try {
    await connectDB();

    const target = await User.findOne({ email: TARGET_EMAIL });
    if (!target) {
      console.error(`❌ Utilisateur cible introuvable : ${TARGET_EMAIL}`);
      console.error(`   Crée-le ou précise un autre email via --email <addr>`);
      await mongoose.connection.close();
      process.exit(1);
    }

    console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
    console.log(`🎯 Utilisateur cible : ${target.email} (${target._id}) — rôle=${target.role}`);
    console.log(`   mode = ${APPLY ? 'APPLY' : 'DRY-RUN (aucune écriture)'}`);
    console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');

    // Locate the 5 dataset projects
    const projects = await Project.find({ name: { $in: DATASET_NAMES } });

    if (!projects.length) {
      console.error(`❌ Aucun projet du dataset trouvé (cherché : ${DATASET_NAMES.join(', ')})`);
      await mongoose.connection.close();
      process.exit(1);
    }

    // Collect owners for readability
    const ownerIds   = [...new Set(projects.map(p => String(p.userId)))].filter(Boolean);
    const ownerUsers = await User.find({ _id: { $in: ownerIds } }).select('email role').lean();
    const ownerById  = new Map(ownerUsers.map(u => [String(u._id), u]));

    console.log(`\n📄 ${projects.length} projet(s) dataset trouvés :\n`);
    const plan = [];
    for (const p of projects) {
      const currentOwnerId = String(p.userId);
      const currentOwner   = ownerById.get(currentOwnerId);
      const sameUser       = currentOwnerId === String(target._id);
      const ownerLabel     = currentOwner
        ? `${currentOwner.email} (${currentOwnerId})`
        : `<unknown user ${currentOwnerId}>`;
      console.log(`   • ${p.name}`);
      console.log(`       _id       : ${p._id}`);
      console.log(`       owner     : ${ownerLabel}`);
      console.log(`       action    : ${sameUser ? 'skip (déjà assigné)' : `→ ${target.email}`}`);
      if (!sameUser) plan.push(p);
    }

    // Also surface the count of missing dataset projects, if any
    const missing = DATASET_NAMES.filter(n => !projects.find(p => p.name === n));
    if (missing.length) {
      console.log(`\n⚠️  ${missing.length} projet(s) attendus non trouvés :`);
      missing.forEach(n => console.log(`     - ${n}`));
    }

    if (plan.length === 0) {
      console.log(`\n✅ Tous les projets appartiennent déjà à ${target.email}. Rien à faire.`);
      await mongoose.connection.close();
      process.exit(0);
    }

    if (!APPLY) {
      console.log(`\n💡 DRY-RUN : ${plan.length} projet(s) seraient re-assignés à ${target.email}.`);
      console.log(`   Lance avec --apply pour appliquer.`);
      await mongoose.connection.close();
      process.exit(0);
    }

    // Apply reassignment via Mongoose save() so validators + hooks run
    console.log(`\n🔄 Application…`);
    for (const p of plan) {
      p.userId = target._id;
      await p.save();
      console.log(`   ✅ ${p.name} → ${target.email}`);
    }

    // Verify
    const ownedCount = await Project.countDocuments({ userId: target._id });
    console.log('\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
    console.log(`🔢 Projets actuellement possédés par ${target.email} : ${ownedCount}`);
    console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');

    await mongoose.connection.close();
    process.exit(0);

  } catch (err) {
    console.error(`❌ Échec : ${err.message}`);
    if (err.stack) console.error(err.stack);
    try { await mongoose.connection.close(); } catch (_) {}
    process.exit(1);
  }
})();
