// backend/src/controllers/analytics.controller.js
//
// GET /api/analytics/overview[?projectId=...]
// Returns:
//   followersByBrand:  [{ name, followers }]                       — sum of followers across platforms per brand
//   engagementOverTime: [{ week: 'W1'..'W4', values: [{ brand, engagement }] }]
//                                                                  — last 4 rolling weeks
//                                                                  — engagement = (likes + comments) / brandFollowers, in %
//
// Without projectId  → all projects owned by the user
// With projectId     → that single project (ownership enforced)
// Reads from: Project, Competitor, SocialAnalysis (no scraping/SWOT side effects).

const mongoose       = require('mongoose');
const Project        = require('../models/Project.model');
const Competitor     = require('../models/Competitor.model');
const SocialAnalysis = require('../models/SocialAnalysis.model');

const WEEKS = 4;
const MS_PER_WEEK = 7 * 24 * 60 * 60 * 1000;

exports.getAnalyticsOverview = async (req, res, next) => {
  try {
    const userId = req.user._id;
    const { projectId } = req.query;

    // ── Resolve project scope ──
    let projectIds;
    if (projectId) {
      if (!mongoose.Types.ObjectId.isValid(projectId)) {
        return res.status(400).json({ success: false, message: 'projectId invalide' });
      }
      const project = await Project.findById(projectId).select('userId').lean();
      if (!project) {
        return res.status(404).json({ success: false, message: 'Projet non trouvé' });
      }
      if (project.userId.toString() !== userId.toString()) {
        return res.status(403).json({ success: false, message: 'Accès refusé' });
      }
      projectIds = [project._id];
    } else {
      const projects = await Project.find({ userId }).select('_id').lean();
      projectIds = projects.map(p => p._id);
    }

    const empty = { followersByBrand: [], engagementOverTime: emptyWeeks() };

    if (projectIds.length === 0) {
      return res.status(200).json({ success: true, data: empty });
    }

    // ── Competitors in scope (active only) ──
    const competitors = await Competitor
      .find({ projectId: { $in: projectIds }, isActive: true })
      .select('_id companyName')
      .lean();

    if (competitors.length === 0) {
      return res.status(200).json({ success: true, data: empty });
    }

    const competitorIds = competitors.map(c => c._id);
    const brandByCompetitorId = new Map(
      competitors.map(c => [c._id.toString(), c.companyName])
    );

    // ── Social analyses for those competitors ──
    const analyses = await SocialAnalysis
      .find({ competitorId: { $in: competitorIds } })
      .select('competitorId followers recentPosts')
      .lean();

    // ── 1) followersByBrand: sum followers across platforms per brand ──
    const followersMap = new Map(); // brand -> total followers
    for (const a of analyses) {
      const brand = brandByCompetitorId.get(a.competitorId.toString());
      if (!brand) continue;
      followersMap.set(brand, (followersMap.get(brand) || 0) + (a.followers || 0));
    }

    const followersByBrand = Array.from(followersMap.entries())
      .filter(([, followers]) => followers > 0)
      .map(([name, followers]) => ({ name, followers }))
      .sort((a, b) => b.followers - a.followers);

    // ── 2) engagementOverTime: bucket recentPosts into the last 4 weeks ──
    // W1 = oldest (3 weeks ago), W4 = current week
    const now = Date.now();

    // brand -> [interactions per week index 0..3]
    const interactionsByBrandWeek = new Map();
    function getBucket(brand) {
      let arr = interactionsByBrandWeek.get(brand);
      if (!arr) {
        arr = new Array(WEEKS).fill(0);
        interactionsByBrandWeek.set(brand, arr);
      }
      return arr;
    }

    for (const a of analyses) {
      const brand = brandByCompetitorId.get(a.competitorId.toString());
      if (!brand) continue;
      const bucket = getBucket(brand);
      for (const p of (a.recentPosts || [])) {
        if (!p.publishedAt) continue;
        const ageMs = now - new Date(p.publishedAt).getTime();
        if (ageMs < 0 || ageMs >= WEEKS * MS_PER_WEEK) continue;
        const weekIdx = WEEKS - 1 - Math.floor(ageMs / MS_PER_WEEK); // 0 = W1 (oldest), 3 = W4
        bucket[weekIdx] += (p.likes || 0) + (p.comments || 0);
      }
    }

    // Build the per-week structure. Engagement = interactions / brandFollowers, expressed as %
    const engagementOverTime = emptyWeeks();
    for (const [brand, weekInteractions] of interactionsByBrandWeek.entries()) {
      const followers = followersMap.get(brand) || 0;
      for (let i = 0; i < WEEKS; i++) {
        const interactions = weekInteractions[i];
        const engagement = followers > 0
          ? Number(((interactions / followers) * 100).toFixed(2))
          : 0;
        engagementOverTime[i].values.push({ brand, engagement });
      }
    }

    return res.status(200).json({
      success: true,
      data: { followersByBrand, engagementOverTime }
    });
  } catch (err) {
    next(err);
  }
};

function emptyWeeks() {
  return Array.from({ length: WEEKS }, (_, i) => ({
    week  : `W${i + 1}`,
    values: []
  }));
}
