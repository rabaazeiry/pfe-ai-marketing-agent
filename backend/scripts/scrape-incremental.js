// backend/scripts/scrape-incremental.js
// Incremental Instagram re-scraping with smart deduplication.
// Fetches the N newest posts per brand, merges them into recentPosts
// without creating duplicates (matched on postUrl), trims the window
// to RECENT_POSTS_CAP, recomputes aggregates, and respects a hard
// cumulative-cost stop.
//
// Usage:
//   node scripts/scrape-incremental.js --dry-run --brand=patisseriemasmoudi
//   node scripts/scrape-incremental.js --brand=patisseriemasmoudi
//   node scripts/scrape-incremental.js --industry=patisserie
//   node scripts/scrape-incremental.js --industry=all
//   node scripts/scrape-incremental.js --industry=all --limit=30

const path = require('path');
require('dotenv').config({ path: path.resolve(__dirname, '..', '.env') });
const mongoose = require('mongoose');

const connectDB      = require('../src/config/database');
require('../src/models');
const Project        = require('../src/models/Project.model');
const Competitor     = require('../src/models/Competitor.model');
const SocialAnalysis = require('../src/models/SocialAnalysis.model');
const apifyService   = require('../src/services/apify.service');

// ─────── CONFIG ───────
const POSTS_PER_BRAND    = 50;
const RECENT_POSTS_CAP   = 200;
const COST_PER_BRAND     = 0.115;   // ~$4.60 / 40 brands at 50 posts
const COST_HARD_STOP     = 4.80;
const DELAY_MS           = 3000;
const PFE_PROJECT_PREFIX = 'PFE Analysis -';
const EXCLUDED_USERNAMES = new Set(['nike', 'sephora', 'fstunis']);

const INDUSTRY_TO_PROJECT = {
  patisserie : 'PFE Analysis - Patisserie',
  beauty     : 'PFE Analysis - Beauty',
  fashion    : 'PFE Analysis - Fashion',
  hotels     : 'PFE Analysis - Hotels',
  restaurants: 'PFE Analysis - Restaurants',
};

// ─────── CLI ───────
function parseArgs(argv) {
  const out = { dryRun: false, industry: null, brand: null, limit: POSTS_PER_BRAND, skipRecentHours: 0 };
  for (const a of argv.slice(2)) {
    if (a === '--dry-run') out.dryRun = true;
    else if (a.startsWith('--industry=')) out.industry = a.slice('--industry='.length).toLowerCase();
    else if (a.startsWith('--brand='))    out.brand    = a.slice('--brand='.length).toLowerCase();
    else if (a.startsWith('--limit='))    out.limit    = parseInt(a.slice('--limit='.length), 10);
    else if (a.startsWith('--skip-recent-hours=')) out.skipRecentHours = parseFloat(a.slice('--skip-recent-hours='.length));
    else console.warn(`⚠️  Unknown flag: ${a}`);
  }
  if (!out.industry && !out.brand) {
    console.error('❌ Provide at least --brand=<username> or --industry=<key|all>');
    console.error('   Industries:', Object.keys(INDUSTRY_TO_PROJECT).join(', '), '| all');
    process.exit(1);
  }
  if (out.industry && out.industry !== 'all' && !INDUSTRY_TO_PROJECT[out.industry]) {
    console.error(`❌ Unknown industry: ${out.industry}`);
    process.exit(1);
  }
  if (Number.isNaN(out.limit) || out.limit < 1 || out.limit > 200) {
    console.error('❌ Invalid --limit (must be 1..200)');
    process.exit(1);
  }
  return out;
}

const args = parseArgs(process.argv);
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
const fmtCost = (n) => '$' + n.toFixed(3);

// ─────── BRAND SELECTION ───────
async function selectBrands() {
  const projectFilter = { name: new RegExp('^' + PFE_PROJECT_PREFIX) };
  if (args.industry && args.industry !== 'all') {
    projectFilter.name = INDUSTRY_TO_PROJECT[args.industry];
  }

  const projects = await Project.find(projectFilter).lean();
  if (projects.length === 0) return [];
  const projectIdToName = new Map(projects.map(p => [String(p._id), p.name]));

  const compFilter = {
    projectId: { $in: projects.map(p => p._id) },
    isActive : true,
  };
  if (args.brand) compFilter.companyName = args.brand;

  const competitors = await Competitor.find(compFilter).lean();

  let candidates = competitors
    .filter(c => !EXCLUDED_USERNAMES.has((c.companyName || '').toLowerCase()))
    .filter(c => !!(c.socialMedia && c.socialMedia.instagram && c.socialMedia.instagram.url));

  if (args.skipRecentHours > 0 && candidates.length > 0) {
    const cutoff = new Date(Date.now() - args.skipRecentHours * 3600 * 1000);
    const analyses = await SocialAnalysis.find({
      competitorId: { $in: candidates.map(c => c._id) },
      platform    : 'instagram',
    }).select('competitorId lastScrapedAt').lean();
    const lastByComp = new Map(analyses.map(a => [String(a.competitorId), a.lastScrapedAt]));
    const before = candidates.length;
    const skipped = [];
    candidates = candidates.filter(c => {
      const last = lastByComp.get(String(c._id));
      if (last && new Date(last) > cutoff) {
        skipped.push(c.companyName);
        return false;
      }
      return true;
    });
    console.log(`⏭️  Skipped ${before - candidates.length} brand(s) scraped within last ${args.skipRecentHours}h: ${skipped.join(', ') || '(none)'}`);
  }

  return candidates.map(c => ({
    _id        : c._id,
    projectId  : c.projectId,
    projectName: projectIdToName.get(String(c.projectId)) || '?',
    username   : c.companyName,
    igUrl      : c.socialMedia.instagram.url,
  }));
}

// ─────── MERGE LOGIC ───────
function mergeRecentPosts(existing, fresh) {
  const seen = new Set();
  const merged = [];
  let added = 0, dupes = 0;

  for (const p of existing) {
    if (p && p.postUrl && !seen.has(p.postUrl)) {
      seen.add(p.postUrl);
      merged.push(p);
    }
  }
  for (const p of fresh) {
    if (!p || !p.postUrl) continue;
    if (seen.has(p.postUrl)) { dupes++; continue; }
    seen.add(p.postUrl);
    merged.push(p);
    added++;
  }

  merged.sort((a, b) => {
    const ta = a.publishedAt ? new Date(a.publishedAt).getTime() : 0;
    const tb = b.publishedAt ? new Date(b.publishedAt).getTime() : 0;
    return tb - ta;
  });

  const trimmed   = merged.slice(0, RECENT_POSTS_CAP);
  const trimCount = Math.max(0, merged.length - trimmed.length);
  return { trimmed, added, dupes, trimCount };
}

function recomputeAggregates(analysis, posts) {
  if (!posts.length) return;
  const sum = (k) => posts.reduce((s, p) => s + (Number(p[k]) || 0), 0);
  const avg = (k) => Math.round(sum(k) / posts.length);
  analysis.avgLikes    = avg('likes');
  analysis.avgComments = avg('comments');
  analysis.avgShares   = avg('shares');
  analysis.avgViews    = avg('views');
  if (analysis.followers > 0) {
    const eng = (analysis.avgLikes + analysis.avgComments + analysis.avgShares) / analysis.followers * 100;
    analysis.engagementRate = parseFloat(eng.toFixed(2));
  }
}

// ─────── PER-BRAND PIPELINE ───────
async function processBrand(brand, idx, total, runStats) {
  const tag = `[${idx + 1}/${total}] @${brand.username}`;
  const t0  = Date.now();

  const existing = await SocialAnalysis.findOne({
    competitorId: brand._id,
    platform    : 'instagram',
  });
  const existingCount = existing && existing.recentPosts ? existing.recentPosts.length : 0;

  if (args.dryRun) {
    console.log(`${tag} (dry-run) project="${brand.projectName}" url=${brand.igUrl} existing=${existingCount} would-fetch=${args.limit}`);
    runStats.previewed.push({
      username: brand.username,
      project : brand.projectName,
      existing: existingCount,
    });
    return;
  }

  if (runStats.cost + COST_PER_BRAND > COST_HARD_STOP) {
    console.log(`${tag} ⛔ cost gate: would exceed ${fmtCost(COST_HARD_STOP)} (current ${fmtCost(runStats.cost)})`);
    runStats.aborted = true;
    return;
  }

  console.log(`${tag} ⏳ scraping ${args.limit} posts (cost so far: ${fmtCost(runStats.cost)})`);

  let igResult;
  try {
    igResult = await apifyService.scrapeInstagram(brand.igUrl, args.limit);
  } catch (err) {
    console.log(`${tag} ❌ Apify failed: ${err.message}`);
    runStats.failed.push({ username: brand.username, error: err.message });
    runStats.cost += COST_PER_BRAND;
    return;
  }
  runStats.cost += COST_PER_BRAND;

  const existingPlain = (existing && existing.recentPosts ? existing.recentPosts : [])
    .map(p => (p && typeof p.toObject === 'function') ? p.toObject() : p);
  const fresh = igResult.recentPosts || [];
  const merge = mergeRecentPosts(existingPlain, fresh);

  let analysis = existing;
  if (!analysis) {
    analysis = new SocialAnalysis({
      projectId   : brand.projectId,
      competitorId: brand._id,
      platform    : 'instagram',
      profileUrl  : igResult.profileUrl || brand.igUrl,
    });
  }

  if (igResult.username     !== undefined) analysis.username     = igResult.username;
  if (igResult.bio          !== undefined) analysis.bio          = (igResult.bio || '').slice(0, 500);
  if (igResult.isVerified   !== undefined) analysis.isVerified   = igResult.isVerified;
  if (igResult.followers    !== undefined) analysis.followers    = igResult.followers;
  if (igResult.following    !== undefined) analysis.following    = igResult.following;
  if (igResult.totalPosts   !== undefined) analysis.totalPosts   = igResult.totalPosts;
  if (igResult.postsPerWeek !== undefined) analysis.postsPerWeek = igResult.postsPerWeek;
  if (igResult.topHashtags) analysis.topHashtags = igResult.topHashtags;

  analysis.recentPosts      = merge.trimmed;
  recomputeAggregates(analysis, merge.trimmed);
  if (typeof analysis.calculatePerformanceScore === 'function') {
    analysis.calculatePerformanceScore();
  }
  analysis.scrapingStatus   = 'completed';
  analysis.lastScrapedAt    = new Date();
  analysis.scrapingError    = '';
  analysis.scrapingAttempts = (analysis.scrapingAttempts || 0) + 1;

  await analysis.save(); // post-save hook recalculates Competitor.metrics

  // Mirror snapshot fields on Competitor.socialMedia.instagram
  const competitor = await Competitor.findById(brand._id);
  if (competitor) {
    if (igResult.followers  !== undefined) competitor.socialMedia.instagram.followers  = igResult.followers;
    if (igResult.totalPosts !== undefined) competitor.socialMedia.instagram.postsCount = igResult.totalPosts;
    if (igResult.isVerified !== undefined) competitor.socialMedia.instagram.verified   = igResult.isVerified;
    competitor.scrapingStatus = 'completed';
    competitor.lastScrapedAt  = new Date();
    competitor.scrapingError  = '';
    await competitor.save();
  }

  const elapsedSec = ((Date.now() - t0) / 1000).toFixed(1);
  console.log(`${tag} ✅ +${merge.added} new, ${merge.dupes} dup, total=${merge.trimmed.length} (trimmed=${merge.trimCount}) in ${elapsedSec}s`);

  runStats.success.push({
    username   : brand.username,
    fetched    : fresh.length,
    added      : merge.added,
    dupes      : merge.dupes,
    trimmed    : merge.trimCount,
    totalAfter : merge.trimmed.length,
    elapsedSec : Number(elapsedSec),
  });
}

// ─────── MAIN ───────
(async () => {
  const t0 = Date.now();
  const runStats = {
    startedAt: new Date().toISOString(),
    args, cost: 0, aborted: false,
    success: [], failed: [], previewed: [],
  };

  try {
    if (!args.dryRun && !process.env.APIFY_API_KEY) {
      console.error('❌ APIFY_API_KEY missing from .env');
      process.exit(1);
    }

    await connectDB();

    const brands = await selectBrands();
    console.log(`🎯 ${brands.length} eligible brand(s) selected`);
    console.log(`📦 limit=${args.limit} cost-cap=${fmtCost(COST_HARD_STOP)} dry-run=${args.dryRun}\n`);

    if (brands.length === 0) {
      await mongoose.disconnect();
      process.exit(0);
    }

    for (let i = 0; i < brands.length; i++) {
      try {
        await processBrand(brands[i], i, brands.length, runStats);
      } catch (err) {
        console.log(`[${i + 1}/${brands.length}] ❌ unexpected: ${err.message}`);
        runStats.failed.push({ username: brands[i].username, error: err.message });
      }
      if (runStats.aborted) break;
      if (!args.dryRun && i < brands.length - 1) await sleep(DELAY_MS);
    }

    const totalSec = ((Date.now() - t0) / 1000).toFixed(1);
    console.log('\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
    console.log(args.dryRun ? '🔍 DRY-RUN SUMMARY' : '📊 INCREMENTAL SCRAPE SUMMARY');
    console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
    if (args.dryRun) {
      console.log(`Brands previewed: ${runStats.previewed.length}`);
      runStats.previewed.forEach(p =>
        console.log(`  @${p.username} [${p.project}] existing=${p.existing}`));
    } else {
      console.log(`✅ Success: ${runStats.success.length}`);
      runStats.success.forEach(s =>
        console.log(`  @${s.username}: +${s.added} new, ${s.dupes} dup → ${s.totalAfter} total`));
      console.log(`❌ Failed: ${runStats.failed.length}`);
      runStats.failed.forEach(f => console.log(`  @${f.username}: ${f.error}`));
      if (runStats.aborted) console.log('⛔ Aborted by cost gate');
      console.log(`💰 Cumulative cost: ${fmtCost(runStats.cost)} / ${fmtCost(COST_HARD_STOP)}`);
    }
    console.log(`⏱️  Time: ${totalSec}s`);

    await mongoose.disconnect();
    process.exit(0);
  } catch (err) {
    console.error('❌ FATAL:', err.message);
    console.error(err.stack);
    try { await mongoose.disconnect(); } catch (_) {}
    process.exit(1);
  }
})();
