// backend/src/controllers/scraping.controller.js

const scrapingService = require('../services/scraping.unified');
const scraperProxy    = require('../services/scraperProxy.service');
const Competitor      = require('../models/Competitor.model');
const SocialAnalysis  = require('../models/SocialAnalysis.model');
const Project         = require('../models/Project.model');

// ═══════════════════════════════════════════════════════════════════════════
// POST /api/scraping/project/:projectId/scrape
// Scrape Instagram ET Facebook
// ═══════════════════════════════════════════════════════════════════════════
exports.scrapeCompetitors = async (req, res) => {
  try {
    const { projectId }    = req.params;
    const { competitorIds } = req.body;

    if (!projectId) {
      return res.status(400).json({ success: false, message: 'projectId requis' });
    }
    if (!competitorIds || !Array.isArray(competitorIds) || competitorIds.length === 0) {
      return res.status(400).json({ success: false, message: 'competitorIds requis (tableau non vide)' });
    }

    const project = await Project.findById(projectId);
    if (!project) {
      return res.status(404).json({ success: false, message: 'Projet non trouvé' });
    }

    await Project.findByIdAndUpdate(projectId, { pipelineStatus: 'step3_scraping' });

    res.status(200).json({
      success: true,
      message: `Scraping lancé pour ${competitorIds.length} concurrent(s)`,
      data: { projectId, competitorIds, status: 'in_progress' }
    });

    scrapingService.scrapeProjectSocialMedia(projectId, competitorIds, ['instagram', 'facebook'])
      .then(results => {
        console.log(`\n✅ Scraping terminé:`);
        console.log(`   Succès : ${results.successCount}/${results.total}`);
        console.log(`   Échecs : ${results.failedCount}/${results.total}`);
      })
      .catch(err => console.error(`\n❌ Erreur scraping: ${err.message}`));

  } catch (error) {
    console.error('scrapeCompetitors error:', error);
    return res.status(500).json({ success: false, message: error.message });
  }
};

// ═══════════════════════════════════════════════════════════════════════════
// POST /api/scraping/project/:projectId/scrape-instagram
// ✅ NOUVEAU - Scrape INSTAGRAM SEULEMENT
// ═══════════════════════════════════════════════════════════════════════════
exports.scrapeInstagramOnly = async (req, res) => {
  try {
    const { projectId }    = req.params;
    const { competitorIds } = req.body;

    if (!projectId) {
      return res.status(400).json({ success: false, message: 'projectId requis' });
    }
    if (!competitorIds || !Array.isArray(competitorIds) || competitorIds.length === 0) {
      return res.status(400).json({ success: false, message: 'competitorIds requis (tableau non vide)' });
    }

    const project = await Project.findById(projectId);
    if (!project) {
      return res.status(404).json({ success: false, message: 'Projet non trouvé' });
    }

    res.status(200).json({
      success: true,
      message: `Scraping Instagram lancé pour ${competitorIds.length} concurrent(s)`,
      data: { projectId, competitorIds, platform: 'instagram', status: 'in_progress' }
    });

    // ✅ INSTAGRAM SEULEMENT
    scrapingService.scrapeProjectSocialMedia(projectId, competitorIds, ['instagram'])
      .then(results => {
        console.log(`\n✅ Scraping Instagram terminé:`);
        console.log(`   Succès : ${results.successCount}/${results.total}`);
        console.log(`   Échecs : ${results.failedCount}/${results.total}`);
      })
      .catch(err => console.error(`\n❌ Erreur scraping Instagram: ${err.message}`));

  } catch (error) {
    console.error('scrapeInstagramOnly error:', error);
    return res.status(500).json({ success: false, message: error.message });
  }
};

// ═══════════════════════════════════════════════════════════════════════════
// POST /api/scraping/project/:projectId/scrape-facebook
// Scrape FACEBOOK SEULEMENT
// ═══════════════════════════════════════════════════════════════════════════
exports.scrapeFacebookOnly = async (req, res) => {
  try {
    const { projectId }    = req.params;
    const { competitorIds } = req.body;

    if (!projectId) {
      return res.status(400).json({ success: false, message: 'projectId requis' });
    }
    if (!competitorIds || !Array.isArray(competitorIds) || competitorIds.length === 0) {
      return res.status(400).json({ success: false, message: 'competitorIds requis (tableau non vide)' });
    }

    const project = await Project.findById(projectId);
    if (!project) {
      return res.status(404).json({ success: false, message: 'Projet non trouvé' });
    }

    res.status(200).json({
      success: true,
      message: `Scraping Facebook lancé pour ${competitorIds.length} concurrent(s)`,
      data: { projectId, competitorIds, platform: 'facebook', status: 'in_progress' }
    });

    scrapingService.scrapeProjectSocialMedia(projectId, competitorIds, ['facebook'])
      .then(results => {
        console.log(`\n✅ Scraping Facebook terminé:`);
        console.log(`   Succès : ${results.successCount}/${results.total}`);
        console.log(`   Échecs : ${results.failedCount}/${results.total}`);
      })
      .catch(err => console.error(`\n❌ Erreur scraping Facebook: ${err.message}`));

  } catch (error) {
    console.error('scrapeFacebookOnly error:', error);
    return res.status(500).json({ success: false, message: error.message });
  }
};

// ═══════════════════════════════════════════════════════════════════════════
// POST /api/scraping/competitor/:competitorId/scrape
// ═══════════════════════════════════════════════════════════════════════════
exports.scrapeOneCompetitor = async (req, res) => {
  try {
    const { competitorId } = req.params;
    const { projectId }    = req.body;

    if (!projectId) {
      return res.status(400).json({ success: false, message: 'projectId requis dans le body' });
    }

    const competitor = await Competitor.findById(competitorId);
    if (!competitor) {
      return res.status(404).json({ success: false, message: 'Concurrent non trouvé' });
    }

    res.status(200).json({
      success: true,
      message: `Scraping lancé pour ${competitor.companyName}`,
      data: { competitorId, companyName: competitor.companyName, status: 'in_progress' }
    });

    scrapingService.scrapeProjectSocialMedia(projectId, [competitorId], ['instagram', 'facebook'])
      .then(result => console.log(`✅ Scraping ${competitor.companyName} terminé:`, result))
      .catch(err  => console.error(`❌ Erreur scraping ${competitor.companyName}:`, err.message));

  } catch (error) {
    console.error('scrapeOneCompetitor error:', error);
    return res.status(500).json({ success: false, message: error.message });
  }
};

// ═══════════════════════════════════════════════════════════════════════════
// GET /api/scraping/project/:projectId/status
// ═══════════════════════════════════════════════════════════════════════════
exports.getScrapingStatus = async (req, res) => {
  try {
    const { projectId } = req.params;

    const competitors = await Competitor.find({ projectId, isActive: true })
      .select('companyName scrapingStatus lastScrapedAt scrapingError metrics socialMedia');

    const statusCount = {
      total      : competitors.length,
      pending    : competitors.filter(c => c.scrapingStatus === 'pending').length,
      in_progress: competitors.filter(c => c.scrapingStatus === 'in_progress').length,
      completed  : competitors.filter(c => c.scrapingStatus === 'completed').length,
      failed     : competitors.filter(c => c.scrapingStatus === 'failed').length,
    };

    const analyses = await SocialAnalysis.find({ projectId })
      .select('competitorId platform scrapingStatus followers engagementRate lastScrapedAt topPosts');

    const competitorsWithAnalysis = competitors.map(c => {
      const igAnalysis = analyses.find(
        a => a.competitorId.toString() === c._id.toString() && a.platform === 'instagram'
      );
      const fbAnalysis = analyses.find(
        a => a.competitorId.toString() === c._id.toString() && a.platform === 'facebook'
      );
      return {
        _id           : c._id,
        companyName   : c.companyName,
        scrapingStatus: c.scrapingStatus,
        lastScrapedAt : c.lastScrapedAt,
        scrapingError : c.scrapingError,
        metrics       : c.metrics,
        instagram     : igAnalysis ? {
          status        : igAnalysis.scrapingStatus,
          followers     : igAnalysis.followers,
          engagementRate: igAnalysis.engagementRate,
          postsScraped  : igAnalysis.topPosts?.length || 0,
          lastScrapedAt : igAnalysis.lastScrapedAt,
        } : null,
        facebook      : fbAnalysis ? {
          status        : fbAnalysis.scrapingStatus,
          followers     : fbAnalysis.followers,
          engagementRate: fbAnalysis.engagementRate,
          postsScraped  : fbAnalysis.topPosts?.length || 0,
          lastScrapedAt : fbAnalysis.lastScrapedAt,
        } : null,
      };
    });

    return res.status(200).json({
      success: true,
      data: { projectId, statusCount, competitors: competitorsWithAnalysis }
    });

  } catch (error) {
    console.error('getScrapingStatus error:', error);
    return res.status(500).json({ success: false, message: error.message });
  }
};

// Autres fonctions...
exports.getScrapingResults = async (req, res) => {
  try {
    const { projectId } = req.params;
    const analyses = await SocialAnalysis.find({ projectId, scrapingStatus: 'completed' })
      .populate('competitorId', 'companyName classificationMaturity socialMedia website')
      .sort({ createdAt: -1 });
    return res.status(200).json({ success: true, count: analyses.length, data: analyses || [] });
  } catch (error) {
    return res.status(500).json({ success: false, message: error.message });
  }
};

exports.resetScraping = async (req, res) => {
  try {
    const { projectId } = req.params;
    await SocialAnalysis.deleteMany({ projectId });
    await Competitor.updateMany({ projectId }, {
      scrapingStatus: 'pending', lastScrapedAt: null, scrapingError: '',
      metrics: { totalFollowers: 0, avgEngagementRate: 0, platformsCount: 0, overallScore: 0 }
    });
    await Project.findByIdAndUpdate(projectId, { pipelineStatus: 'step2_complete' });
    return res.status(200).json({ success: true, message: 'Scraping réinitialisé' });
  } catch (error) {
    return res.status(500).json({ success: false, message: error.message });
  }
};

exports.resetFacebook = async (req, res) => {
  try {
    const { projectId } = req.params;
    const deleted = await SocialAnalysis.deleteMany({ projectId, platform: 'facebook' });
    return res.status(200).json({
      success: true,
      message: `Facebook reset — ${deleted.deletedCount} analyses supprimées`,
      data: { deletedCount: deleted.deletedCount }
    });
  } catch (error) {
    return res.status(500).json({ success: false, message: error.message });
  }
};

// ═══════════════════════════════════════════════════════════════════════════
// POST /api/scraping/competitor/:competitorId/scrape-v2
// Sprint 12 — Calls the Python /v2/scrape orchestrator (sync response)
// ═══════════════════════════════════════════════════════════════════════════
exports.scrapeCompetitorV2 = async (req, res) => {
  // TEMPORARILY DISABLED — Instagram blocks unauthenticated HTTP requests
  // (redirects to /accounts/login/). The Python HTTP method always returns 0 posts.
  // Re-enable once authenticated scraping or a working alternative is implemented.
  return res.status(503).json({
    success: false,
    message: 'Scraping Instagram HTTP temporairement désactivé (Instagram bloque les requêtes sans login)'
  });

  /*
  --- original logic (kept for re-activation) ---
  try {
    const { competitorId } = req.params;

    const competitor = await Competitor.findById(competitorId);
    if (!competitor) {
      return res.status(404).json({ success: false, message: 'Concurrent non trouvé' });
    }

    const igUrl = competitor.socialMedia?.instagram?.url;
    if (!igUrl) {
      return res.status(400).json({
        success: false,
        message: 'Ce concurrent n\'a pas de profil Instagram configuré'
      });
    }

    competitor.scrapingStatus = 'in_progress';
    await competitor.save();

    const result = await scraperProxy.scrapeV2({
      projectId: competitor.projectId.toString(),
      competitorId: competitor._id.toString(),
      platform: 'instagram',
      target: igUrl
    });

    competitor.scrapingStatus = result.posts_count > 0 ? 'completed' : 'pending';
    competitor.lastScrapedAt = new Date();
    await competitor.save();

    return res.status(200).json({
      success: true,
      message: `Scraping terminé pour ${competitor.companyName}`,
      data: {
        competitorId: competitor._id,
        companyName: competitor.companyName,
        methodUsed: result.method_used,
        postsCount: result.posts_count,
        socialAnalysis: result.social_analysis,
        competitorUpdate: result.competitor_update
      }
    });
  } catch (error) {
    console.error('scrapeCompetitorV2 error:', error.message);
    try {
      await Competitor.findByIdAndUpdate(req.params.competitorId, { scrapingStatus: 'failed' });
    } catch {}

    const status = error.response?.status === 502 ? 502 : 500;
    const message = error.code === 'ECONNREFUSED'
      ? 'Python scraper service is not running (ECONNREFUSED)'
      : error.message;
    return res.status(status).json({ success: false, message });
  }
  --- end of original logic ---
  */
};