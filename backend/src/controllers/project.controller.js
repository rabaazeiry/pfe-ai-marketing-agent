// backend/src/controllers/project.controller.js

const Project           = require('../models/Project.model');
const Insight           = require('../models/Insight.model');
const extractionService = require('../services/extraction.service');

// ─── Converts user-typed country name to ISO 2-letter code for the DB field ──
function mapToCountryCode(name) {
  const n = (name || '').toLowerCase().trim();
  if (n.includes('tunisi') || n === 'tn')                       return 'TN';
  if (n.includes('franc')  || n === 'fr')                       return 'FR';
  if (n.includes('maroc')  || n.includes('morocco') || n==='ma')return 'MA';
  if (n.includes('algeri') || n === 'dz')                       return 'DZ';
  if (n.includes('sénégal')|| n.includes('senegal') || n==='sn')return 'SN';
  if (n.includes('belgiq') || n === 'be')                       return 'BE';
  if (n.includes('espagne')|| n.includes('spain')   || n==='es')return 'ES';
  if (n.includes('italie') || n.includes('italy')   || n==='it')return 'IT';
  if (n.includes('canada') || n === 'ca')                       return 'CA';
  return 'TN';
}

// ═══════════════════════════════════════════════════════════════════════════
// POST /api/projects/suggest-name
// Returns a Groq-generated project name without saving anything.
// ═══════════════════════════════════════════════════════════════════════════
exports.suggestProjectName = async (req, res, next) => {
  try {
    const { businessIdea, marketCategory, targetCountry = 'Tunisie' } = req.body;

    if (!businessIdea || businessIdea.trim().length < 10) {
      return res.status(400).json({ success: false, message: 'Business idea requise (minimum 10 caractères)' });
    }

    // marketCategory is optional here — when empty, the LLM will auto-detect the industry
    let name, keywords, industry;

    try {
      const extracted = await extractionService.extractProjectInfo(
        businessIdea.trim(),
        (marketCategory || '').trim(),
        [],
        (targetCountry || 'Tunisie').trim()
      );
      name     = extracted.name;
      keywords = extracted.keywords;
      industry = extracted.industry;
    } catch (llmError) {
      console.warn('⚠️ suggest-name LLM échoué, fallback:', llmError.message);
      name     = `Projet ${marketCategory.trim()}`;
      keywords = [];
      industry = marketCategory.trim();
    }

    res.status(200).json({
      success: true,
      data: { name, keywords, industry, targetCountry: (targetCountry || 'Tunisie').trim() }
    });

  } catch (error) {
    next(error);
  }
};

// ═══════════════════════════════════════════════════════════════════════════
// POST /api/projects
// ═══════════════════════════════════════════════════════════════════════════
exports.createProject = async (req, res, next) => {
  try {
    const {
      businessIdea,
      marketCategory,
      targetCountry  = 'Tunisie',
      name           : userProvidedName,
      competitorsHint,
    } = req.body;

    // ===== VALIDATION =====
    if (!businessIdea || businessIdea.trim().length < 10) {
      return res.status(400).json({
        success: false,
        message: 'Business idea requise (minimum 10 caractères)'
      });
    }

    if (!marketCategory || marketCategory.trim().length < 2) {
      return res.status(400).json({
        success: false,
        message: 'Industrie requise (ex: "Fashion", "Hotels", "Patisserie")'
      });
    }

    const country = (targetCountry || 'Tunisie').trim();
    const hints   = Array.isArray(competitorsHint)
      ? competitorsHint.filter(h => typeof h === 'string' && h.trim().length > 0).slice(0, 5)
      : [];

    // ===== STEP 1 : EXTRACTION LLM =====
    console.log('🤖 Step 1 — Extraction LLM...');
    console.log(`   businessIdea    : ${businessIdea.trim().substring(0, 80)}`);
    console.log(`   marketCategory  : ${marketCategory.trim()}`);
    console.log(`   targetCountry   : ${country}`);
    console.log(`   competitorsHint : [${hints.join(', ')}]`);

    let extracted;
    let extractionStatus = 'completed';

    try {
      extracted = await extractionService.extractProjectInfo(
        businessIdea.trim(),
        marketCategory.trim(),
        hints,
        country
      );
    } catch (llmError) {
      console.warn('⚠️ LLM extraction échouée, fallback générique:', llmError.message);
      extractionStatus = 'failed';

      const words = businessIdea
        .toLowerCase()
        .split(/\s+/)
        .filter(w => w.length > 3)
        .slice(0, 4);
      const cat = marketCategory.toLowerCase();

      extracted = {
        name           : `Projet ${marketCategory.trim()}`,
        industry       : marketCategory.trim(),
        country,
        marketCategory : marketCategory.trim(),
        keywords       : [cat, ...words].slice(0, 6),
        searchQueries  : [
          `${cat} instagram`,
          `${cat} facebook`,
          `${cat} ${country.toLowerCase()} instagram`,
          `${cat} ${country.toLowerCase()} facebook`,
          `meilleur ${cat} instagram`,
          `top ${cat} ${country.toLowerCase()}`,
        ],
        industryTerms  : words.slice(0, 4),
        targetAudience : ['Clients locaux', 'Professionnels', 'Particuliers'],
        languages      : ['fr', 'ar', 'en'],
        competitorsHint: hints,
      };
    }

    // If the user edited the suggested name in the form, honour it
    if (userProvidedName && userProvidedName.trim().length >= 2) {
      extracted.name = userProvidedName.trim();
    }

    // ===== SAUVEGARDE =====
    const project = await Project.create({
      userId          : req.user.id,
      businessIdea    : businessIdea.trim(),
      marketCategory  : marketCategory.trim(),
      targetCountry   : mapToCountryCode(country),
      country,
      competitorsHint : hints,

      name            : extracted.name,
      industry        : extracted.industry,
      keywords        : extracted.keywords,
      searchQueries   : extracted.searchQueries,
      industryTerms   : extracted.industryTerms || [],
      targetAudience  : extracted.targetAudience,
      languages       : extracted.languages,

      extractionStatus,
      pipelineStatus  : extractionStatus === 'completed'
                        ? 'step1_complete'
                        : 'step1_extraction',
    });

    console.log(`✅ Projet créé: ${project.name} (${project._id})`);
    console.log(`   industry       : ${project.industry}`);
    console.log(`   country        : ${project.country}`);
    console.log(`   keywords       : ${project.keywords.join(', ')}`);
    console.log(`   searchQueries  : ${project.searchQueries.length} queries`);
    console.log(`   pipelineStatus : ${project.pipelineStatus}`);

    res.status(201).json({
      success: true,
      message: 'Projet créé avec succès — Step 1 terminé',
      data: {
        project,
        extraction: {
          name           : extracted.name,
          industry       : extracted.industry,
          country,
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

// ===== CRUD INCHANGÉ =====

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

    project = await Project.findByIdAndUpdate(req.params.id, updateData, { new: true, runValidators: true });
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
