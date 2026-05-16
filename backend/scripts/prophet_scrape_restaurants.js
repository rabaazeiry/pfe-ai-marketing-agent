/**
 * Prophet Instagram Scraper — RESTAURANTS
 * Scrapes posts from 2023-01-01 to today for 8 restaurant brands.
 * Stores in `prophet_posts` collection (same as other industries).
 * Does NOT touch competitorprofiles.
 *
 * Usage:  node backend/scripts/prophet_scrape_restaurants.js
 * Re-run safe: skips brands already in prophet_posts.
 * Pass --force to re-scrape all brands.
 */

require('dotenv').config({ path: require('path').join(__dirname, '../.env') });

const axios    = require('axios');
const mongoose = require('mongoose');
const dns      = require('dns');

// ─── CONFIG ────────────────────────────────────────────────────────────────
const APIFY_TOKEN    = process.env.APIFY_API_KEY;
const MONGODB_URI    = process.env.MONGODB_URI;
const ACTOR_ID       = 'apify~instagram-scraper';
const APIFY_BASE     = 'https://api.apify.com/v2';
const POLL_INTERVAL  = 10_000;
const POLL_TIMEOUT   = 60_000;
const MAX_WAIT       = 35 * 60_000;
const BETWEEN_BRANDS = 15_000;
const FORCE_RESCRAPE = process.argv.includes('--force');

const BRANDS = [
  { username: 'the716lac2',         isLocal: true  },
  { username: 'legolfe.restaurant', isLocal: true  },
  { username: 'elfirma.tunis',      isLocal: true  },
  { username: 'baguettebaguette',   isLocal: true  },
  { username: 'kfctunisie',         isLocal: false },
  { username: 'vie.tunis',          isLocal: true  },
  { username: 'papajohnstn',        isLocal: false },
  { username: 'la_salle_a_manger',  isLocal: true  },
];

const FROM_DATE = '2023-01-01';
const INDUSTRY  = 'restaurants';

// ─── MONGOOSE SCHEMA ───────────────────────────────────────────────────────
const prophetPostSchema = new mongoose.Schema({
  username       : { type: String, required: true, index: true },
  industry       : { type: String },
  isLocal        : { type: Boolean, default: true },
  publishedAt    : { type: Date },
  likes          : { type: Number, default: 0 },
  comments       : { type: Number, default: 0 },
  engagementRate : { type: Number, default: 0 },
  followers      : { type: Number, default: 0 },
  scrapedAt      : { type: Date, default: Date.now },
}, { collection: 'prophet_posts' });

// ─── APIFY HELPERS ─────────────────────────────────────────────────────────

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

async function runActor(input, attempt = 1) {
  try {
    const res = await axios.post(
      `${APIFY_BASE}/acts/${ACTOR_ID}/runs`,
      input,
      {
        params : { token: APIFY_TOKEN },
        headers: { 'Content-Type': 'application/json' },
        timeout: 30_000,
      }
    );
    const runId = res.data?.data?.id;
    if (!runId) throw new Error('No run ID returned by Apify');
    console.log(`     Run started: ${runId}`);
    return runId;
  } catch (err) {
    const status = err.response?.status;
    if ((status === 403 || status === 502) && attempt <= 4) {
      const wait = attempt * 30_000;
      console.warn(`     ${status} on launch (attempt ${attempt}) — waiting ${wait / 1000}s before retry`);
      await sleep(wait);
      return runActor(input, attempt + 1);
    }
    throw err;
  }
}

async function pollRun(runId) {
  const start = Date.now();
  while (Date.now() - start < MAX_WAIT) {
    await sleep(POLL_INTERVAL);
    try {
      const res    = await axios.get(`${APIFY_BASE}/actor-runs/${runId}`, {
        params: { token: APIFY_TOKEN }, timeout: POLL_TIMEOUT,
      });
      const data   = res.data?.data;
      const status = data?.status;
      const usage  = data?.usageTotalUsd;
      const label  = usage != null ? `  ($${usage.toFixed(4)})` : '';
      console.log(`     Status: ${status}${label}`);
      if (['SUCCEEDED', 'FAILED', 'ABORTED', 'TIMED-OUT'].includes(status)) return data;
    } catch (pollErr) {
      console.warn(`     Poll error (will retry): ${pollErr.message}`);
    }
  }
  throw new Error('Apify run timed out after 35 min');
}

async function fetchDataset(datasetId) {
  const res = await axios.get(`${APIFY_BASE}/datasets/${datasetId}/items`, {
    params : { token: APIFY_TOKEN, clean: true, format: 'json', limit: 10_000 },
    timeout: 90_000,
  });
  return Array.isArray(res.data) ? res.data : [];
}

// ─── SCRAPE ONE BRAND ──────────────────────────────────────────────────────

async function scrapeBrand({ username, isLocal }, ProphetPost) {
  console.log(`\n  Scraping @${username} (isLocal: ${isLocal}) ...`);

  if (!FORCE_RESCRAPE) {
    const existing = await ProphetPost.countDocuments({ username });
    if (existing > 0) {
      console.log(`     Already in DB: ${existing} posts — skipping (use --force to re-scrape)`);
      const docs      = await ProphetPost.find({ username }).sort({ publishedAt: 1 }).select('publishedAt followers').lean();
      const oldest    = docs[0]?.publishedAt || null;
      const newest    = docs[docs.length - 1]?.publishedAt || null;
      const followers = docs[docs.length - 1]?.followers || 0;
      return { username, isLocal, posts: existing, oldest, newest, cost: 0, followers, skipped: true };
    }
  }

  const input = {
    directUrls         : [`https://www.instagram.com/${username}/`],
    resultsType        : 'posts',
    resultsLimit       : 1000,
    onlyPostsNewerThan : FROM_DATE,
  };

  let runId;
  try {
    runId = await runActor(input);
  } catch (err) {
    console.error(`     Actor launch failed: ${err.message}`);
    return { username, isLocal, posts: 0, oldest: null, newest: null, cost: 0, error: err.message };
  }

  let run;
  try {
    run = await pollRun(runId);
  } catch (err) {
    console.error(`     Polling failed: ${err.message}`);
    return { username, isLocal, posts: 0, oldest: null, newest: null, cost: 0, error: err.message };
  }

  const cost = run.usageTotalUsd || 0;

  if (run.status !== 'SUCCEEDED') {
    return { username, isLocal, posts: 0, oldest: null, newest: null, cost, error: `Run status: ${run.status}` };
  }

  const items = await fetchDataset(run.defaultDatasetId);
  console.log(`     Raw items from Apify: ${items.length}`);

  if (items.length === 0) {
    return { username, isLocal, posts: 0, oldest: null, newest: null, cost, error: 'No items returned' };
  }

  const followers =
    items[0]?.ownerFollowersCount ||
    items[0]?.followersCount ||
    items[0]?.owner?.followersCount ||
    items[0]?.userFollowersCount ||
    0;

  const fromDate = new Date(FROM_DATE);
  const docs = [];
  for (const item of items) {
    const ts = item.timestamp || item.takenAt || item.date;
    const publishedAt = ts ? new Date(ts) : null;
    if (publishedAt && publishedAt < fromDate) continue;

    const likes    = Math.max(item.likesCount    || item.likes    || 0, 0);
    const comments = Math.max(item.commentsCount || item.comments || 0, 0);
    const er = followers > 0
      ? parseFloat(((likes + comments) / followers * 100).toFixed(4))
      : 0;

    docs.push({
      username,
      industry       : INDUSTRY,
      isLocal,
      publishedAt,
      likes,
      comments,
      engagementRate : er,
      followers,
      scrapedAt      : new Date(),
    });
  }

  if (docs.length === 0) {
    return { username, isLocal, posts: 0, oldest: null, newest: null, cost, followers, error: 'No posts in date range' };
  }

  let inserted = 0;
  try {
    const result = await ProphetPost.insertMany(docs, { ordered: false });
    inserted = result.length;
  } catch (err) {
    inserted = err.result?.nInserted || err.insertedDocs?.length || 0;
    if (inserted === 0 && !err.writeErrors) throw err;
  }

  const dates  = docs.map(d => d.publishedAt).filter(Boolean).sort((a, b) => a - b);
  const oldest = dates[0] || null;
  const newest = dates[dates.length - 1] || null;

  console.log(`     Inserted ${inserted} posts  |  oldest: ${oldest?.toISOString().slice(0,10)}  newest: ${newest?.toISOString().slice(0,10)}`);
  return { username, isLocal, posts: inserted, oldest, newest, cost, followers };
}

// ─── REPORT ────────────────────────────────────────────────────────────────

function prophetFeasibility(result) {
  if (result.error && result.posts === 0) return 'ERROR';
  if (!result.oldest) return 'INSUFFICIENT';
  const oldestYear = new Date(result.oldest).getFullYear();
  if (oldestYear <= 2023) return 'OK';
  if (oldestYear === 2024) return 'LIMITED';
  return 'INSUFFICIENT';
}

function printReport(results) {
  console.log('\n');
  console.log('═'.repeat(72));
  console.log('  PROPHET SCRAPE — RESTAURANTS — FINAL REPORT');
  console.log('═'.repeat(72));

  let totalPosts = 0;
  let totalCost  = 0;

  for (const r of results) {
    const feasibility = prophetFeasibility(r);
    const oldest  = r.oldest ? new Date(r.oldest).toISOString().slice(0, 10) : 'N/A';
    const newest  = r.newest ? new Date(r.newest).toISOString().slice(0, 10) : 'N/A';
    const local   = r.isLocal ? 'local' : 'international';
    const skipped = r.skipped ? '  (already in DB — skipped re-scrape)' : '';
    const err     = r.error   ? `  !! ${r.error}` : '';
    totalPosts += r.posts;
    totalCost  += r.cost;

    console.log(`\n  @${r.username}  [${local}]`);
    console.log(`    Posts scraped : ${r.posts}${skipped}`);
    console.log(`    Date range    : ${oldest}  →  ${newest}`);
    console.log(`    Followers     : ${(r.followers || 0).toLocaleString()}`);
    console.log(`    Cost          : $${r.cost.toFixed(4)}`);
    console.log(`    Prophet       : ${feasibility}${err}`);
  }

  console.log('\n' + '─'.repeat(72));
  console.log(`  Total posts restaurants (this run) : ${totalPosts}`);
  console.log(`  Estimated total cost               : $${totalCost.toFixed(4)}`);
  console.log('═'.repeat(72));
  console.log('\nSTOP — waiting for validation before next industry.\n');
}

// ─── MAIN ──────────────────────────────────────────────────────────────────

async function main() {
  if (!APIFY_TOKEN) throw new Error('APIFY_API_KEY not set in .env');
  if (!MONGODB_URI)  throw new Error('MONGODB_URI not set in .env');

  dns.setServers(['8.8.8.8', '8.8.4.4']);
  console.log('Connecting to MongoDB ...');
  await mongoose.connect(MONGODB_URI);
  console.log('Connected.\n');

  const ProphetPost = mongoose.model('ProphetPost', prophetPostSchema);

  try {
    await ProphetPost.collection.createIndex(
      { username: 1, publishedAt: 1 },
      { unique: true, background: true }
    );
  } catch (_) { /* already exists */ }

  console.log(`Industry : ${INDUSTRY}`);
  console.log(`Brands   : ${BRANDS.length} | From: ${FROM_DATE} | Force: ${FORCE_RESCRAPE}`);
  console.log(`Actor    : ${ACTOR_ID}`);

  const results = [];
  for (let i = 0; i < BRANDS.length; i++) {
    const brand = BRANDS[i];
    const r = await scrapeBrand(brand, ProphetPost);
    results.push(r);

    if (i < BRANDS.length - 1 && !r.skipped) {
      console.log(`     Waiting ${BETWEEN_BRANDS / 1000}s before next brand...`);
      await sleep(BETWEEN_BRANDS);
    }
  }

  printReport(results);
  await mongoose.disconnect();
}

main().catch(err => {
  console.error('\nFATAL:', err.message);
  process.exit(1);
});
