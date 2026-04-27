// backend/src/controllers/dashboard.controller.js
//
// GET /api/dashboard/stats[?projectId=...]
// Aggregates KPIs and chart series for the authenticated user's dashboard.
// Without projectId  → global view across all projects owned by the user.
// With projectId     → scoped to that single project (ownership enforced).
// Pulls from: Project, Competitor, SocialAnalysis (no scraping/SWOT side effects).

const mongoose       = require('mongoose');
const Project        = require('../models/Project.model');
const Competitor     = require('../models/Competitor.model');
const SocialAnalysis = require('../models/SocialAnalysis.model');

// Display order Mon..Sun, mapped from JS Date#getDay() (0 = Sun)
const WEEKDAY_KEYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const DISPLAY_ORDER = [1, 2, 3, 4, 5, 6, 0];

exports.getDashboardStats = async (req, res, next) => {
  try {
    const userId = req.user._id;
    const { projectId } = req.query;

    let projectIds;
    let projectCount;

    if (projectId) {
      // ── Scoped view: validate + ownership check ──
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
      // When filtered, KPI "projects" reflects the scope (1 selected project)
      projectCount = 1;
    } else {
      // ── Global view: all projects owned by the user ──
      const projects = await Project.find({ userId }).select('_id').lean();
      projectIds = projects.map(p => p._id);
      projectCount = projects.length;
    }

    if (projectIds.length === 0) {
      return res.status(200).json({
        success: true,
        data: {
          kpis: {
            projects: 0,
            competitors: 0,
            postsAnalyzed: 0,
            avgEngagementRate: null
          },
          charts: {
            engagementByDay: [],
            contentMix: []
          }
        }
      });
    }

    // 2) Competitors linked to those projects (active only — matches list views)
    const competitorCount = await Competitor.countDocuments({
      projectId: { $in: projectIds },
      isActive : true
    });

    // 3) Social analyses for those projects
    const analyses = await SocialAnalysis
      .find({ projectId: { $in: projectIds } })
      .select('engagementRate recentPosts contentDistribution')
      .lean();

    // KPI — posts analyzed: sum of actually-scraped recentPosts arrays
    // (totalPosts on the analysis is the platform's lifetime count, not what we analyzed)
    const postsAnalyzed = analyses.reduce(
      (s, a) => s + (Array.isArray(a.recentPosts) ? a.recentPosts.length : 0),
      0
    );

    // KPI — average engagement rate across analyses that actually have a value
    const rated = analyses.filter(
      a => typeof a.engagementRate === 'number' && a.engagementRate > 0
    );
    const avgEngagementRate = rated.length === 0
      ? null
      : Number((rated.reduce((s, a) => s + a.engagementRate, 0) / rated.length).toFixed(2));

    // CHART — engagement / posts by weekday, aggregated from recentPosts.publishedAt
    const buckets = WEEKDAY_KEYS.map(day => ({ day, likes: 0, posts: 0 }));
    for (const a of analyses) {
      for (const p of (a.recentPosts || [])) {
        if (!p.publishedAt) continue;
        const idx = new Date(p.publishedAt).getDay();
        if (idx < 0 || idx > 6) continue;
        buckets[idx].likes += p.likes || 0;
        buckets[idx].posts += 1;
      }
    }
    const engagementByDay = DISPLAY_ORDER.map(i => buckets[i]);
    const hasDayData = engagementByDay.some(d => d.posts > 0);

    // CHART — content mix from contentDistribution; fall back to recentPosts.contentType
    // when contentDistribution wasn't populated by the scraper
    const mixTotals = { photo: 0, video: 0, reel: 0, carousel: 0, story: 0 };
    for (const a of analyses) {
      const dist = a.contentDistribution || {};
      mixTotals.photo    += dist.photo    || 0;
      mixTotals.video    += dist.video    || 0;
      mixTotals.reel     += dist.reel     || 0;
      mixTotals.carousel += dist.carousel || 0;
      mixTotals.story    += dist.story    || 0;
    }
    let contentMix = Object.entries(mixTotals)
      .filter(([, v]) => v > 0)
      .map(([name, value]) => ({ name, value }));

    if (contentMix.length === 0) {
      const fromRecent = {};
      for (const a of analyses) {
        for (const p of (a.recentPosts || [])) {
          const t = p.contentType || 'photo';
          fromRecent[t] = (fromRecent[t] || 0) + 1;
        }
      }
      contentMix = Object.entries(fromRecent).map(([name, value]) => ({ name, value }));
    }

    return res.status(200).json({
      success: true,
      data: {
        kpis: {
          projects         : projectCount,
          competitors      : competitorCount,
          postsAnalyzed,
          avgEngagementRate
        },
        charts: {
          engagementByDay: hasDayData ? engagementByDay : [],
          contentMix
        }
      }
    });
  } catch (err) {
    next(err);
  }
};
