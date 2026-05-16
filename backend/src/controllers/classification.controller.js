// backend/src/controllers/classification.controller.js
// VERSION FINALE — lean() + cleaning + debug logs

const Competitor            = require('../models/Competitor.model');
const Project               = require('../models/Project.model');
const classificationService = require('../services/classification.service');
const cleaningService       = require('../services/cleaning.service');
const { classifyCompetitor: classifyWithGemini } = require('../services/classificationGemini.service');

// ═══════════════════════════════════════════════════════════
// CLASSIFIER TOUS LES CONCURRENTS D'UN PROJET
// POST /api/classification/project/:projectId
// ═══════════════════════════════════════════════════════════
exports.classifyAll = async (req, res, next) => {
  try {
    const { projectId } = req.params;

    // ✅ .lean() → plain JS objects → données accessibles par LLM
    const project = await Project.findById(projectId).lean();
    if (!project) {
      return res.status(404).json({
        success: false,
        message: 'Projet non trouvé'
      });
    }

    if (project.userId.toString() !== req.user.id) {
      return res.status(403).json({
        success: false,
        message: 'Accès refusé'
      });
    }

    // ✅ .lean() → description + socialMedia accessibles
    const competitors = await Competitor.find({ projectId }).lean();

    if (competitors.length === 0) {
      return res.status(400).json({
        success: false,
        message: 'Aucun concurrent trouvé. Lancez discover + enrich d\'abord.'
      });
    }

    console.log(`\n🚀 Classification: ${project.name}`);
    console.log(`📋 ${competitors.length} concurrent(s) à classifier`);

    // ✅ Nettoyer données avant classification
    console.log('\n🧹 Nettoyage données...');
    const cleanedCompetitors = cleaningService.cleanCompetitors(competitors);
    cleaningService.generateCleaningReport(competitors, cleanedCompetitors);

    // ✅ Debug : vérifier données après nettoyage
    console.log('\n📋 Données envoyées au LLM :');
    cleanedCompetitors.forEach(c => {
      const socialCount = [
        c.socialMedia?.instagram?.username,
        c.socialMedia?.facebook?.username,
        c.socialMedia?.linkedin?.username,
        c.socialMedia?.tiktok?.username
      ].filter(Boolean).length;

      const foundedYear = c.notes?.includes('Founded:')
        ? c.notes.replace('Founded:', '').trim()
        : c.foundedYear || 'N/A';

      console.log(
        `   → ${c.companyName.padEnd(20)} | ` +
        `desc: ${c.description ? '✅' : '❌'} | ` +
        `social: ${socialCount} | ` +
        `founded: ${foundedYear} | ` +
        `domain: ${c.website?.match(/\.\w+$/)?.[0] || 'N/A'}`
      );
    });

    // ✅ Lancer classification
    const results = await classificationService.classifyAll(
      cleanedCompetitors,
      project
    );

    // ✅ Sauvegarder résultats en MongoDB
    let successCount = 0;
    for (const result of results) {
      await Competitor.findByIdAndUpdate(result.competitorId, {
        classification            : result.classification,
        classificationScore       : result.classificationScore,
        classificationJustification: result.classificationJustification
      });
      successCount++;
    }

    // ✅ Résumé par catégorie
    const summary = {
      leader       : results.filter(r => r.classification === 'leader').length,
      international: results.filter(r => r.classification === 'international').length,
      startup      : results.filter(r => r.classification === 'startup').length,
      local        : results.filter(r => r.classification === 'local').length
    };

    console.log(`\n📊 Résumé classification :`);
    console.log(`   leader        : ${summary.leader}`);
    console.log(`   international : ${summary.international}`);
    console.log(`   startup       : ${summary.startup}`);
    console.log(`   local         : ${summary.local}`);

    res.status(200).json({
      success: true,
      message: `${successCount} concurrent(s) classifié(s)`,
      data   : { summary, results }
    });

  } catch (error) {
    next(error);
  }
};

// ═══════════════════════════════════════════════════════════
// CLASSIFIER UN SEUL CONCURRENT
// POST /api/classification/competitor/:competitorId
// ═══════════════════════════════════════════════════════════
exports.classifyOne = async (req, res, next) => {
  try {
    const { competitorId } = req.params;

    // ✅ .lean() ici aussi
    const competitor = await Competitor.findById(competitorId).lean();
    if (!competitor) {
      return res.status(404).json({
        success: false,
        message: 'Concurrent non trouvé'
      });
    }

    const project = await Project.findById(competitor.projectId).lean();
    if (!project) {
      return res.status(404).json({
        success: false,
        message: 'Projet non trouvé'
      });
    }

    if (project.userId.toString() !== req.user.id) {
      return res.status(403).json({
        success: false,
        message: 'Accès refusé'
      });
    }

    // Nettoyer avant classification
    const cleaned = cleaningService.cleanCompetitor(competitor);

    const result = await classificationService.classifyCompetitor(
      cleaned,
      project
    );

    await Competitor.findByIdAndUpdate(competitorId, {
      classification            : result.classification,
      classificationScore       : result.classificationScore,
      classificationJustification: result.classificationJustification
    });

    res.status(200).json({
      success: true,
      message: 'Concurrent classifié avec succès',
      data   : {
        companyName               : competitor.companyName,
        classification            : result.classification,
        classificationScore       : result.classificationScore,
        classificationJustification: result.classificationJustification
      }
    });

  } catch (error) {
    next(error);
  }
};

// ═══════════════════════════════════════════════════════════
// CLASSIFIER TOUS LES CONCURRENTS VIA GEMINI (pipeline step 3)
// POST /api/projects/:id/classify
// ═══════════════════════════════════════════════════════════
exports.classifyProjectCompetitors = async (req, res, next) => {
  try {
    const { id: projectId } = req.params;

    const project = await Project.findById(projectId);
    if (!project) {
      return res.status(404).json({ success: false, message: 'Projet non trouvé' });
    }
    if (project.userId.toString() !== req.user.id) {
      return res.status(403).json({ success: false, message: 'Accès refusé' });
    }

    const competitors = await Competitor.find({ projectId, isActive: true }).lean();
    if (competitors.length === 0) {
      return res.status(400).json({
        success: false,
        message: 'Aucun concurrent trouvé — lancez la découverte en premier.'
      });
    }

    console.log(`\n🤖 Classification Gemini: ${project.name} — ${competitors.length} concurrent(s)`);

    const results = [];
    for (const competitor of competitors) {
      try {
        const gemini = await classifyWithGemini(competitor, project);

        // map combined classification to maturity (startup | leader)
        const maturity = gemini.classification.includes('leader') ? 'leader' : 'startup';

        // Use collection.updateOne to bypass the normalizeMaturityInUpdate hook
        // so the detailed classification ('local_leader', etc.) is preserved as-is
        await Competitor.collection.updateOne(
          { _id: competitor._id },
          { $set: {
            classification            : gemini.classification,
            classificationMaturity    : maturity,
            classificationScore       : gemini.confidence,
            classificationJustification: gemini.reason
          }}
        );

        results.push({
          competitorId  : competitor._id,
          companyName   : competitor.companyName,
          classification: gemini.classification,
          confidence    : gemini.confidence,
          reason        : gemini.reason
        });

        console.log(`   ✅ ${competitor.companyName} → ${gemini.classification} (${gemini.confidence}%)`);
      } catch (err) {
        console.error(`   ❌ ${competitor.companyName}: ${err.message}`);
        results.push({
          competitorId: competitor._id,
          companyName : competitor.companyName,
          error       : err.message
        });
      }

      // small delay to respect Gemini free-tier rate limits
      await new Promise(r => setTimeout(r, 300));
    }

    // Advance pipeline to step3_complete (classification done, 60%)
    await project.advancePipeline('step3_complete');

    const classified = results.filter(r => !r.error).length;
    console.log(`\n✅ Classification terminée: ${classified}/${competitors.length}`);

    return res.status(200).json({
      success   : true,
      classified,
      total     : competitors.length,
      results
    });

  } catch (error) {
    next(error);
  }
};