// backend/scripts/promote-user-to-admin.js
//
// Passe le rôle d'un utilisateur de "user" à "admin". Ne modifie QUE le
// champ `role` du document User ciblé — aucune autre donnée (projets,
// concurrents, scraping, market summary, SWOT) n'est touchée.
//
// Usage :
//   node scripts/promote-user-to-admin.js                        # applique sur admin@pfe.local
//   node scripts/promote-user-to-admin.js --dry-run              # aperçu uniquement
//   node scripts/promote-user-to-admin.js --email foo@bar.com    # cible un autre email
//
// Idempotent : si l'utilisateur est déjà admin, rien n'est écrit.

require('dotenv').config();

const mongoose  = require('mongoose');
const connectDB = require('../src/config/database');
require('../src/models');
const User = require('../src/models/User.model');

const DRY_RUN    = process.argv.includes('--dry-run');
const emailIdx   = process.argv.indexOf('--email');
const EMAIL      = emailIdx !== -1 ? process.argv[emailIdx + 1] : 'admin@pfe.local';
const TARGET_ROLE = 'admin';

function snapshot(u) {
  return {
    _id      : String(u._id),
    email    : u.email,
    firstName: u.firstName,
    lastName : u.lastName,
    role     : u.role,
    isActive : u.isActive,
    updatedAt: u.updatedAt
  };
}

(async () => {
  try {
    await connectDB();

    const user = await User.findOne({ email: EMAIL });
    if (!user) {
      console.error(`❌ Utilisateur introuvable : ${EMAIL}`);
      await mongoose.connection.close();
      process.exit(1);
    }

    console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
    console.log(`🎯 Utilisateur ciblé : ${EMAIL}`);
    console.log(`   mode = ${DRY_RUN ? 'DRY-RUN (aucune écriture)' : 'APPLY'}`);
    console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');

    console.log('\n📄 AVANT :');
    console.log(JSON.stringify(snapshot(user), null, 2));

    if (user.role === TARGET_ROLE) {
      console.log(`\n✅ ${EMAIL} est déjà "${TARGET_ROLE}" — rien à faire.`);
      await mongoose.connection.close();
      process.exit(0);
    }

    console.log(`\n📝 CHANGEMENT : role "${user.role}" → "${TARGET_ROLE}"`);

    if (DRY_RUN) {
      console.log('\n💡 DRY-RUN : aucune modification appliquée.');
      await mongoose.connection.close();
      process.exit(0);
    }

    user.role = TARGET_ROLE;
    await user.save();

    const refreshed = await User.findById(user._id);
    console.log('\n📄 APRÈS :');
    console.log(JSON.stringify(snapshot(refreshed), null, 2));

    console.log('\n🔎 Vérification :');
    console.log(`   email = ${refreshed.email}`);
    console.log(`   role  = ${refreshed.role}`);
    console.log(`\n✅ Promotion appliquée.`);

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
