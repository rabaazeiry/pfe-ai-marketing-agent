// backend/src/controllers/project.controller.js
// VERSION 5 — Adapté pour Pâtisserie Tunisienne

const Project           = require('../models/Project.model');
const Insight           = require('../models/Insight.model');
const extractionService = require('../services/extraction.service');

exports.createProject = async (req, res, next) => {
  try {
    const { businessIdea, marketCategory, competitorsHint } = req.body;

    // ===== VALIDATION INPUTS =====
    if (!businessIdea || businessIdea.trim().length < 10) {
      return res.status(400).json({
        success: false,
        message: 'Business idea requise (minimum 10 caractères)'
      });
    }

    if (!marketCategory || marketCategory.trim().length < 2) {
      return res.status(400).json({
        success: false,
        message: 'Market category requise (ex: "Pâtisserie artisanale", "Gâteaux tunisiens")'
      });
    }

    const hints = Array.isArray(competitorsHint)
      ? competitorsHint.filter(h => typeof h === 'string' && h.trim().length > 0).slice(0, 5)
      : [];

    // ===== STEP 1 : EXTRACTION LLM =====
    console.log('🤖 Step 1 — Extraction LLM...');
    console.log(`   businessIdea    : ${businessIdea.trim().substring(0, 80)}...`);
    console.log(`   marketCategory  : ${marketCategory.trim()}`);
    console.log(`   competitorsHint : [${hints.join(', ')}]`);

    let extracted;
    let extractionStatus = 'completed';

    try {
      extracted = await extractionService.extractProjectInfo(
        businessIdea.trim(),
        marketCategory.trim(),
        hints
      );
    } catch (llmError) {
      console.warn('⚠️ LLM extraction échouée, utilisation fallback:', llmError.message);
      extractionStatus = 'failed';

      const words = businessIdea
        .toLowerCase()
        .split(/\s+/)
        .filter(w => w.length > 3)
        .slice(0, 4);
      const word0   = words[0] || 'pâtisserie';
      const catWord = marketCategory.toLowerCase().split(/\s+/)[0] || 'patisserie';

      // ✅ Fallback complet pour Pâtisserie Tunisienne
      extracted = {
        name           : `Projet ${marketCategory.trim()}`,
        industry       : 'Food & Pastry',          // ✅ FIX
        country        : 'Tunisie',
        marketCategory : marketCategory.trim(),
        keywords       : [
          'pâtisserie', 'gâteaux', 'baklawa', 'coffret',
          'livraison', 'tunisie', 'حلويات', 'بقلاوة'
        ],
        searchQueries  : [
          `pâtisserie tunisie instagram`,
          `gâteaux tunisiens instagram`,
          `${catWord} tunis site officiel`,
          `${word0} ${catWord} tunisie`,
          `best pastry shop tunis instagram`,
          `pâtisserie tunisie facebook`,
          `masmoudi patisserie tunisie`,
          `mamie karima patisserie tunisie`,
          `maison turki patisserie tunisie`,
          `patisserie aicha tunisie`,
          `sellami patisserie tunisie`,
          `cakery co tunisie`,
          `حلويات تونس انستقرام`,
          `بقلاوة تونس فيسبوك`,
          `حلويات تونسية انستقرام`,
          `baklawa tunisie livraison`,
          `coffret gâteaux tunisie`,
          `pâtisserie tunisienne livraison`,
          `tunisian pastry instagram`,
          `patisserie artisanale tunis`,
        ],
        industryTerms  : ['patisserie', 'gâteaux', 'baklawa', 'حلويات', 'بقلاوة', 'coffret'],
        targetAudience : [
          'Familles tunisiennes',
          'Mariés et fiancés',
          'Professionnels pour cadeaux',
          'Amateurs de pâtisserie orientale',
          'Diaspora tunisienne'
        ],
        languages      : ['fr', 'ar', 'en'],
        competitorsHint: hints,
      };
    }

    // ===== SAUVEGARDE EN MONGODB =====
    const project = await Project.create({
      // Inputs utilisateur
      userId          : req.user.id,
      businessIdea    : businessIdea.trim(),
      marketCategory  : marketCategory.trim(),
      targetCountry   : 'TN',
      competitorsHint : hints,

      // Générés par LLM
      name            : extracted.name,
      industry        : extracted.industry || 'Food & Pastry',   // ✅ FIX
      country         : 'Tunisie',
      keywords        : extracted.keywords,
      searchQueries   : extracted.searchQueries,
      industryTerms   : extracted.industryTerms || [],
      targetAudience  : extracted.targetAudience,
      languages       : extracted.languages,

      // Status
      extractionStatus,
      pipelineStatus  : extractionStatus === 'completed'
                        ? 'step1_complete'
                        : 'step1_extraction',
    });

    console.log(`✅ Projet créé: ${project.name} (${project._id})`);
    console.log(`   industry       : ${project.industry}`);
    console.log(`   marketCategory : ${project.marketCategory}`);
    console.log(`   keywords       : ${project.keywords.join(', ')}`);
    console.log(`   searchQueries  : ${project.searchQueries.length} queries`);
    console.log(`   industryTerms  : ${(project.industryTerms || []).join(', ')}`);
    console.log(`   targetAudience : ${project.targetAudience.join(', ')}`);
    console.log(`   pipelineStatus : ${project.pipelineStatus}`);

    res.status(201).json({
      success: true,
      message: 'Projet créé avec succès — Step 1 terminé',
      data: {
        project,
        extraction: {
          name           : extracted.name,
          industry       : extracted.industry || 'Food & Pastry',  // ✅ FIX
          country        : 'Tunisie',
          marketCategory : marketCategory.trim(),
          keywords       : extracted.keywords,
          searchQueries  : extracted.searchQueries,
          industryTerms  : extracted.industryTerms || [],
          targetAudience : extracted.targetAudience,
          languages      : extracted.languages,
          competitorsHint: hints,
          status         : extractionStatus
        }
      }
    });

  } catch (error) {
    next(error);
  }
};

// ===== ROUTES INCHANGÉES =====

exports.getAllProjects = async (req, res, next) => {
  try {
    const projects = await Project.find({ userId: req.user.id }).sort({ updatedAt: -1 });
    res.status(200).json({ success: true, count: projects.length, data: projects });
  } catch (error) { next(error); }
};

exports.getProject = async (req, res, next) => {
  try {
    const project = await Project.findById(req.params.id);
    if (!project) return res.status(404).json({ success: false, message: 'Projet non trouvé' });
    if (project.userId.toString() !== req.user.id) return res.status(403).json({ success: false, message: 'Accès refusé' });
    res.status(200).json({ success: true, data: project });
  } catch (error) { next(error); }
};

exports.updateProject = async (req, res, next) => {
  try {
    let project = await Project.findById(req.params.id);
    if (!project) return res.status(404).json({ success: false, message: 'Projet non trouvé' });
    if (project.userId.toString() !== req.user.id) return res.status(403).json({ success: false, message: 'Accès refusé' });

    const allowedFields = [
      'name', 'businessIdea', 'marketCategory', 'businessObjectives',
      'description', 'status', 'progressPercentage'
    ];
    const updateData = {};
    allowedFields.forEach(field => {
      if (req.body[field] !== undefined) updateData[field] = req.body[field];
    });

    project = await Project.findByIdAndUpdate(
      req.params.id,
      updateData,
      { new: true, runValidators: true }
    );
    res.status(200).json({ success: true, message: 'Projet mis à jour', data: project });
  } catch (error) { next(error); }
};

exports.deleteProject = async (req, res, next) => {
  try {
    const project = await Project.findById(req.params.id);
    if (!project) return res.status(404).json({ success: false, message: 'Projet non trouvé' });
    if (project.userId.toString() !== req.user.id) return res.status(403).json({ success: false, message: 'Accès refusé' });
    await project.deleteOne();
    res.status(200).json({ success: true, message: 'Projet supprimé avec succès' });
  } catch (error) { next(error); }
};

exports.updateProgress = async (req, res, next) => {
  try {
    const { percentage } = req.body;
    if (percentage === undefined || percentage < 0 || percentage > 100) {
      return res.status(400).json({ success: false, message: 'Pourcentage invalide (0-100)' });
    }
    const project = await Project.findById(req.params.id);
    if (!project) return res.status(404).json({ success: false, message: 'Projet non trouvé' });
    if (project.userId.toString() !== req.user.id) return res.status(403).json({ success: false, message: 'Accès refusé' });
    await project.updateProgress(percentage);
    res.status(200).json({
      success: true,
      message: 'Progression mise à jour',
      data: { progressPercentage: project.progressPercentage }
    });
  } catch (error) { next(error); }
};

// ═══════════════════════════════════════════════════════════════════════════
// GET /api/projects/:id/insights
// ═══════════════════════════════════════════════════════════════════════════
exports.getProjectInsights = async (req, res, next) => {
  try {
    const project = await Project.findById(req.params.id);
    if (!project) return res.status(404).json({ success: false, message: 'Projet non trouvé' });
    if (project.userId.toString() !== req.user.id) return res.status(403).json({ success: false, message: 'Accès refusé' });

    const insight = await Insight.findOne({ projectId: req.params.id });
    if (!insight) {
      return res.status(404).json({ success: false, message: 'Aucun insight généré pour ce projet' });
    }
    res.status(200).json({ success: true, data: insight });
  } catch (error) { next(error); }
};