// backend/scripts/update-competitor-classification.js
//
// Manually classify the 42 pre-scraped PFE brands.
//
// For each entry:
//   1. Look up `socialanalyses` by username (case-insensitive, lowercased)
//   2. Resolve the competitor's ObjectId
//   3. Queue a `updateOne` that sets:
//        - geographicScope       (new)
//        - marketPosition        (new)
//        - classificationSource  (new, always "manual")
//        - classification        (synced with marketPosition)
//        - classificationMaturity(synced with marketPosition)
//   4. Commit everything via ONE bulkWrite on the raw collection
//      (bypasses Mongoose `strict` mode so the 3 new fields are persisted).
//
// Usage:
//   node scripts/update-competitor-classification.js            # apply
//   node scripts/update-competitor-classification.js --dry-run  # preview only

require('dotenv').config();

const mongoose     = require('mongoose');
const connectDB    = require('../src/config/database');
require('../src/models'); // register every schema (Competitor, SocialAnalysis, ...)
const SocialAnalysis = require('../src/models/SocialAnalysis.model');

// ─── CLI flag ────────────────────────────────────────────────────────────────
const DRY_RUN = process.argv.includes('--dry-run');

// ─── Manual classification dataset (42 brands) ───────────────────────────────
const CLASSIFICATIONS = [
  // Pâtisserie
  { username: 'patisseriemasmoudi',    geographicScope: 'local',         marketPosition: 'leader'  },
  { username: 'patisserie_h_by_omar',  geographicScope: 'local',         marketPosition: 'startup' },
  { username: 'mamie.karima',          geographicScope: 'local',         marketPosition: 'startup' },
  { username: 'lamaisongourmandise',   geographicScope: 'local',         marketPosition: 'startup' },
  { username: 'maisonturki',           geographicScope: 'local',         marketPosition: 'leader'  },
  { username: 'patisserierekik',       geographicScope: 'local',         marketPosition: 'leader'  },
  { username: 'patisserie.sakka',      geographicScope: 'local',         marketPosition: 'startup' },
  { username: 'labeylicale',           geographicScope: 'local',         marketPosition: 'startup' },
  { username: 'floraison.official',    geographicScope: 'local',         marketPosition: 'startup' },

  // Beauty
  { username: 'my_story_cosmetics',    geographicScope: 'local',         marketPosition: 'startup' },
  { username: 'lellacosmetics',        geographicScope: 'local',         marketPosition: 'startup' },
  { username: 'therapybylk',           geographicScope: 'local',         marketPosition: 'startup' },
  { username: 'yvesrocher_tunisie',    geographicScope: 'international', marketPosition: 'leader'  },
  { username: 'nuxetunisie',           geographicScope: 'international', marketPosition: 'leader'  },
  { username: 'freya.tn',              geographicScope: 'local',         marketPosition: 'startup' },
  { username: 'biodermatunisie',       geographicScope: 'international', marketPosition: 'leader'  },

  // Fashion
  { username: 'zara',                  geographicScope: 'international', marketPosition: 'leader'  },
  { username: 'mango',                 geographicScope: 'international', marketPosition: 'leader'  },
  { username: 'bershka',               geographicScope: 'international', marketPosition: 'leader'  },
  { username: 'pullandbear',           geographicScope: 'international', marketPosition: 'leader'  },
  { username: 'ha.hamadiabid',         geographicScope: 'local',         marketPosition: 'leader'  },
  { username: 'zen.tunisie',           geographicScope: 'local',         marketPosition: 'startup' },
  { username: 'kastelo.com.tn',        geographicScope: 'local',         marketPosition: 'startup' },
  { username: 'chedly_sisters',        geographicScope: 'local',         marketPosition: 'startup' },

  // Hotels
  { username: 'fstunis',               geographicScope: 'international', marketPosition: 'leader'  },
  { username: 'soussepearlmarriott',   geographicScope: 'international', marketPosition: 'leader'  },
  { username: 'hiltonskanesmonastir',  geographicScope: 'international', marketPosition: 'leader'  },
  { username: 'radissonblutunis',      geographicScope: 'international', marketPosition: 'leader'  },
  { username: 'tunismarriott',         geographicScope: 'international', marketPosition: 'leader'  },
  { username: 'la_badira',             geographicScope: 'local',         marketPosition: 'leader'  },
  { username: 'movenpick_hotel_gammarth', geographicScope: 'international', marketPosition: 'leader' },
  { username: 'el_mouradi_hotels',     geographicScope: 'local',         marketPosition: 'leader'  },
  { username: 'movenpicklactunis',     geographicScope: 'international', marketPosition: 'leader'  },
  { username: 'theresidencetunis',     geographicScope: 'local',         marketPosition: 'leader'  },

  // Restaurants
  { username: 'the716lac2',            geographicScope: 'local',         marketPosition: 'leader'  },
  { username: 'legolfe.restaurant',    geographicScope: 'local',         marketPosition: 'leader'  },
  { username: 'elfirma.tunis',         geographicScope: 'local',         marketPosition: 'startup' },
  { username: 'baguettebaguette',      geographicScope: 'local',         marketPosition: 'startup' },
  { username: 'kfctunisie',            geographicScope: 'international', marketPosition: 'leader'  },
  { username: 'vie.tunis',             geographicScope: 'local',         marketPosition: 'startup' },
  { username: 'papajohnstn',           geographicScope: 'international', marketPosition: 'leader'  },
  { username: 'la_salle_a_manger',     geographicScope: 'local',         marketPosition: 'startup' },
];

// ─── Helpers ─────────────────────────────────────────────────────────────────
function escapeRegex(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * Resolve a competitorId from a username.
 * Returns { competitorId, duplicateIds } where `duplicateIds` is the list of
 * *distinct* competitorIds found (length > 1 means a conflict).
 */
async function resolveCompetitorId(username) {
  const rx = new RegExp(`^${escapeRegex(username.toLowerCase().trim())}$`, 'i');

  const rows = await SocialAnalysis
    .find({ username: rx, competitorId: { $ne: null } })
    .select('_id username competitorId platform')
    .lean();

  if (rows.length === 0) return { competitorId: null, duplicateIds: [] };

  const distinct = [...new Set(rows.map(r => String(r.competitorId)))];
  return { competitorId: rows[0].competitorId, duplicateIds: distinct };
}

// ─── Main ────────────────────────────────────────────────────────────────────
(async () => {
  const startedAt = Date.now();

  console.log(`\n🚀 update-competitor-classification ${DRY_RUN ? '(DRY-RUN)' : ''}`);
  console.log(`   Entries to process: ${CLASSIFICATIONS.length}\n`);

  await connectDB();

  const summary = {
    total     : CLASSIFICATIONS.length,
    matched   : 0,
    updated   : 0,
    missing   : [],
    duplicates: [],
  };

  const ops = [];

  for (const entry of CLASSIFICATIONS) {
    const { username, geographicScope, marketPosition } = entry;

    try {
      const { competitorId, duplicateIds } = await resolveCompetitorId(username);

      if (!competitorId) {
        summary.missing.push(username);
        console.warn(`⚠️  [MISS]  @${username} — no socialAnalysis with a valid competitorId`);
        continue;
      }

      if (duplicateIds.length > 1) {
        summary.duplicates.push({ username, competitorIds: duplicateIds });
        console.warn(`⚠️  [DUPL]  @${username} → ${duplicateIds.length} distinct competitorIds (keeping ${competitorId})`);
      }

      summary.matched++;

      ops.push({
        updateOne: {
          filter: { _id: competitorId },
          update: {
            $set: {
              geographicScope,
              marketPosition,
              classificationSource  : 'manual',
              classification        : marketPosition,
              classificationMaturity: marketPosition,
              updatedAt             : new Date(),
            },
          },
        },
      });

      console.log(`✔ [OK]    @${username.padEnd(26)} → ${competitorId}  [${geographicScope}/${marketPosition}]`);
    } catch (err) {
      console.error(`❌ [ERR]   @${username} — ${err.message}`);
    }
  }

  // ─── Execute ───────────────────────────────────────────────────────────────
  if (DRY_RUN) {
    console.log(`\n🧪 DRY-RUN — would execute ${ops.length} bulkWrite operation(s). No write performed.`);
  } else if (ops.length > 0) {
    const result = await mongoose.connection.db
      .collection('competitors')
      .bulkWrite(ops, { ordered: false });

    summary.updated     = result.modifiedCount ?? 0;
    summary.matchedInDb = result.matchedCount  ?? 0;

    console.log(`\n💾 bulkWrite → matched=${summary.matchedInDb}  modified=${summary.updated}`);
  } else {
    console.log('\n⏭  Nothing to write (no matched competitors).');
  }

  // ─── Summary ───────────────────────────────────────────────────────────────
  console.log('\n────────────── SUMMARY ──────────────');
  console.log(`Total entries       : ${summary.total}`);
  console.log(`Matched usernames   : ${summary.matched}`);
  console.log(`Documents updated   : ${DRY_RUN ? '(dry-run)' : summary.updated}`);
  console.log(`Missing usernames   : ${summary.missing.length}`);
  if (summary.missing.length) {
    summary.missing.forEach(u => console.log(`   • @${u}`));
  }
  console.log(`Duplicate competitors: ${summary.duplicates.length}`);
  if (summary.duplicates.length) {
    summary.duplicates.forEach(d =>
      console.log(`   • @${d.username} → [${d.competitorIds.join(', ')}]`));
  }
  console.log(`Elapsed             : ${((Date.now() - startedAt) / 1000).toFixed(2)}s`);
  console.log('─────────────────────────────────────\n');

  await mongoose.disconnect();
  process.exit(summary.missing.length > 0 ? 2 : 0);
})().catch(async (err) => {
  console.error('\n❌ FATAL:', err);
  try { await mongoose.disconnect(); } catch { /* ignore */ }
  process.exit(1);
});
