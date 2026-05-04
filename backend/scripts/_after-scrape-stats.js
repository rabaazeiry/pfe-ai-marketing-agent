// One-off: dump per-brand stats to JSON for the audit-after report.
const path = require('path');
require('dotenv').config({ path: path.resolve(__dirname, '..', '.env') });
const fs = require('fs');
const mongoose = require('mongoose');
require('../src/models');
const SocialAnalysis = require('../src/models/SocialAnalysis.model');
const Competitor     = require('../src/models/Competitor.model');
const Project        = require('../src/models/Project.model');
const connectDB      = require('../src/config/database');

(async () => {
  await connectDB();
  const projects = await Project.find({ name: new RegExp('^PFE Analysis -') }).lean();
  const projIds  = projects.map(p => p._id);

  const compMap = {};
  (await Competitor.find({ projectId: { $in: projIds }, isActive: true }).lean())
    .forEach(c => { compMap[String(c._id)] = { name: c.companyName, proj: String(c.projectId) }; });

  const projMap = Object.fromEntries(projects.map(p => [String(p._id), p.name]));

  const analyses = await SocialAnalysis.find({
    projectId: { $in: projIds },
    platform : 'instagram',
  }).select('competitorId followers totalPosts avgLikes avgComments engagementRate performanceScore lastScrapedAt recentPosts.publishedAt scrapingStatus').lean();

  const rows = [];
  for (const a of analyses) {
    const cid = String(a.competitorId);
    const c   = compMap[cid];
    if (!c) continue;
    const dates = (a.recentPosts || []).map(p => p.publishedAt).filter(Boolean).map(d => new Date(d).getTime());
    const min = dates.length ? new Date(Math.min(...dates)) : null;
    const max = dates.length ? new Date(Math.max(...dates)) : null;
    rows.push({
      project    : projMap[c.proj] || '?',
      brand      : c.name,
      posts      : (a.recentPosts || []).length,
      followers  : a.followers || 0,
      avgLikes   : a.avgLikes || 0,
      avgComments: a.avgComments || 0,
      eng        : a.engagementRate || 0,
      perf       : a.performanceScore || 0,
      oldest     : min ? min.toISOString().slice(0,10) : null,
      newest     : max ? max.toISOString().slice(0,10) : null,
      lastScraped: a.lastScrapedAt ? new Date(a.lastScrapedAt).toISOString() : null,
    });
  }
  rows.sort((a, b) => a.project.localeCompare(b.project) || a.brand.localeCompare(b.brand));

  const outPath = path.resolve(__dirname, '..', '..', 'reports', '_after-stats.json');
  fs.writeFileSync(outPath, JSON.stringify(rows, null, 2));
  console.log(`Wrote ${rows.length} rows to ${outPath}`);
  await mongoose.disconnect();
})().catch(e => { console.error(e); process.exit(1); });
