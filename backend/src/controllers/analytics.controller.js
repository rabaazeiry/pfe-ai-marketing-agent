// backend/src/controllers/analytics.controller.js
//
// GET /api/analytics/overview[?projectId=...]
// Returns:
//   followersByBrand:  [{ name, followers }]                       — sum of followers across platforms per brand
//   engagementOverTime: [{ week:'W1'.., weekStart:'YYYY-MM-DD', values:[{ brand, engagement|null }] }]
//                                                                  — the (up to) 4 most recent 7-day windows
//                                                                    that actually contain posts, anchored on
//                                                                    the most recent post date (NOT Date.now()),
//                                                                    so the chart stays populated even when
//                                                                    viewed weeks after the last scrape
//                                                                  — engagement = (likes + comments) / brandFollowers, in %
//                                                                  — engagement = null → brand had no post that
//                                                                    week (rendered as a gap, not a flat 0)
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

    const empty = { followersByBrand: [], engagementOverTime: [] };

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

    // ── 2) engagementOverTime: the (up to) 4 most recent 7-day windows that
    //       actually contain posts. The window is anchored on the most recent
    //       post date (data-relative), NOT Date.now(): otherwise a stale scrape
    //       drifts every post out of the window and the chart collapses to 0.

    // Flatten every dated in-scope post: { brand, ts(ms), interactions }
    const posts = [];
    for (const a of analyses) {
      const brand = brandByCompetitorId.get(a.competitorId.toString());
      if (!brand) continue;
      for (const p of (a.recentPosts || [])) {
        if (!p.publishedAt) continue;
        const ts = new Date(p.publishedAt).getTime();
        if (!Number.isFinite(ts)) continue;
        posts.push({ brand, ts, interactions: (p.likes || 0) + (p.comments || 0) });
      }
    }

    let engagementOverTime = [];
    if (posts.length > 0) {
      // Data-relative anchor = most recent post across the whole scope.
      const anchor = posts.reduce((m, p) => (p.ts > m ? p.ts : m), -Infinity);

      // bin 0 = the 7 days ending at the anchor, bin 1 = the prior 7 days, …
      const binOf = (ts) => Math.floor((anchor - ts) / MS_PER_WEEK);

      // Distinct bins that contain ≥1 post, most-recent first → keep up to 4.
      const populated = [...new Set(posts.map(p => binOf(p.ts)))].sort((x, y) => x - y);
      const selectedBins = populated.slice(0, WEEKS);

      // Chronological order: oldest selected bin = W1 … most recent = last week.
      selectedBins.sort((x, y) => y - x);
      const binToWeekIdx = new Map(selectedBins.map((bin, i) => [bin, i]));
      const selectedSet  = new Set(selectedBins);

      // Brands that have at least one post inside the selected window.
      const brandsInWindow = [...new Set(
        posts.filter(p => selectedSet.has(binOf(p.ts))).map(p => p.brand)
      )];

      // Accumulate interactions AND post counts per brand × selected week.
      const acc = new Map(
        brandsInWindow.map(b => [b, selectedBins.map(() => ({ interactions: 0, count: 0 }))])
      );
      for (const p of posts) {
        const wi = binToWeekIdx.get(binOf(p.ts));
        if (wi === undefined) continue;
        const cell = acc.get(p.brand);
        if (!cell) continue;
        cell[wi].interactions += p.interactions;
        cell[wi].count += 1;
      }

      engagementOverTime = selectedBins.map((bin, i) => {
        const weekStartMs = anchor - (bin + 1) * MS_PER_WEEK; // start of that 7-day window
        const values = brandsInWindow.map((brand) => {
          const { interactions, count } = acc.get(brand)[i];
          const followers = followersMap.get(brand) || 0;
          // count 0 → brand had NO post that week → null (gap, not a flat 0).
          // followers ≤ 0 → cannot compute a rate → also null (no data).
          // count > 0 with 0 interactions → real 0.
          const engagement = (count === 0 || followers <= 0)
            ? null
            : Number(((interactions / followers) * 100).toFixed(2));
          return { brand, engagement };
        });
        return {
          week     : `W${i + 1}`,
          weekStart: new Date(weekStartMs).toISOString().slice(0, 10),
          values
        };
      });
    }

    return res.status(200).json({
      success: true,
      data: { followersByBrand, engagementOverTime }
    });
  } catch (err) {
    next(err);
  }
};
