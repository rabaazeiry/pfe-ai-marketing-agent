/**
 * Prophet — Fix Engagement Rate
 * For each username in prophet_posts, looks up followers in competitorprofiles,
 * then updates all prophet_posts documents with correct followers + engagementRate.
 *
 * Usage: node backend/scripts/prophet_fix_engagement.js
 */

require('dotenv').config({ path: require('path').join(__dirname, '../.env') });

const mongoose = require('mongoose');
const dns      = require('dns');

async function main() {
  if (!process.env.MONGODB_URI) throw new Error('MONGODB_URI not set in .env');

  dns.setServers(['8.8.8.8', '8.8.4.4']);
  console.log('Connecting to MongoDB ...');
  await mongoose.connect(process.env.MONGODB_URI);
  console.log('Connected.\n');

  const db           = mongoose.connection.db;
  const prophetCol   = db.collection('prophet_posts');
  const socialCol    = db.collection('socialanalyses');  // source of truth for followers

  // ── 1. Get distinct usernames from prophet_posts ──────────────────────────
  const usernames = await prophetCol.distinct('username');
  console.log(`Distinct usernames in prophet_posts : ${usernames.length}`);

  // ── 2. Look up followers in socialanalyses (instagram platform only) ──────
  const followersMap = {};  // username → followers count
  const notFound     = [];

  for (const username of usernames) {
    const profile = await socialCol.findOne(
      { username, platform: 'instagram' },
      { projection: { followers: 1 } }
    );

    const followers = profile?.followers || 0;

    if (!profile || followers === 0) {
      notFound.push(username);
    }

    followersMap[username] = followers;
    console.log(`  @${username.padEnd(35)} → followers: ${followers.toLocaleString()}${!profile ? '  (NOT FOUND in socialanalyses)' : ''}`);
  }

  // ── 3. Update prophet_posts in bulk per username ──────────────────────────
  console.log('\nUpdating prophet_posts ...\n');

  let totalUpdated = 0;

  for (const username of usernames) {
    const followers = followersMap[username] || 0;

    if (followers === 0) {
      // Still update followers field to 0 and set engagementRate = 0
      const res = await prophetCol.updateMany(
        { username },
        [
          {
            $set: {
              followers      : 0,
              engagementRate : 0,
            },
          },
        ]
      );
      totalUpdated += res.modifiedCount;
      continue;
    }

    // Use aggregation pipeline update to compute engagementRate per document
    const res = await prophetCol.updateMany(
      { username },
      [
        {
          $set: {
            followers,
            engagementRate: {
              $round: [
                {
                  $multiply: [
                    { $divide: [{ $add: ['$likes', '$comments'] }, followers] },
                    100,
                  ],
                },
                4,
              ],
            },
          },
        },
      ]
    );
    totalUpdated += res.modifiedCount;
    console.log(`  @${username.padEnd(35)} updated ${res.modifiedCount} docs  (followers: ${followers.toLocaleString()})`);
  }

  // ── 4. Sample 5 updated documents ────────────────────────────────────────
  console.log('\n' + '─'.repeat(72));
  console.log('SAMPLE — 5 documents (one per industry):');
  console.log('─'.repeat(72));

  const industries = ['patisserie', 'fashion', 'beauty', 'hotels', 'restaurants'];
  for (const industry of industries) {
    const doc = await prophetCol.findOne(
      { industry, followers: { $gt: 0 } },
      { projection: { username: 1, industry: 1, likes: 1, comments: 1, followers: 1, engagementRate: 1, publishedAt: 1 } }
    );
    if (doc) {
      console.log(`\n  [${industry}] @${doc.username}`);
      console.log(`    publishedAt    : ${doc.publishedAt?.toISOString().slice(0,10)}`);
      console.log(`    likes          : ${doc.likes}`);
      console.log(`    comments       : ${doc.comments}`);
      console.log(`    followers      : ${doc.followers.toLocaleString()}`);
      console.log(`    engagementRate : ${doc.engagementRate}%`);
    } else {
      console.log(`\n  [${industry}] — no document with followers > 0`);
    }
  }

  // ── 5. Summary ────────────────────────────────────────────────────────────
  console.log('\n' + '═'.repeat(72));
  console.log('  ENGAGEMENT FIX — SUMMARY');
  console.log('═'.repeat(72));
  console.log(`  Total documents updated          : ${totalUpdated.toLocaleString()}`);
  console.log(`  Usernames with followers data    : ${usernames.length - notFound.length}`);
  console.log(`  Usernames NOT in socialanalyses (engagementRate = 0)  :`);
  if (notFound.length === 0) {
    console.log('    — none, all brands found —');
  } else {
    notFound.forEach(u => console.log(`    • ${u}`));
  }
  console.log('═'.repeat(72));
  console.log('\nSTOP — waiting for validation.\n');

  await mongoose.disconnect();
}

main().catch(err => {
  console.error('\nFATAL:', err.message);
  process.exit(1);
});
