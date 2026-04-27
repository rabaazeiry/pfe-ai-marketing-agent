// backend/src/models/SwotAnalysis.model.js
//
// Analyse SWOT générée par concurrent (on-demand).
// Pattern analogue à MarketResearch.model.js : chiffres backend, prose LLM,
// validation stricte, source par quadrant pour traçabilité.
//
// Un doc par concurrent (unique index on competitorId). Re-génération =
// overwrite.

const mongoose = require('mongoose');

const SOURCE_TYPES = ['llm', 'fallback', 'mixed'];
const QUADRANT_TEXT_MAX = 2000;

const sourceSchema = new mongoose.Schema({
  type   : { type: String, enum: SOURCE_TYPES, default: 'fallback' },
  reason : { type: String, default: '' }
}, { _id: false });

const swotAnalysisSchema = new mongoose.Schema({
  competitorId: {
    type    : mongoose.Schema.Types.ObjectId,
    ref     : 'Competitor',
    required: true,
    unique  : true,
    index   : true
  },
  projectId: {
    type    : mongoose.Schema.Types.ObjectId,
    ref     : 'Project',
    required: true,
    index   : true
  },
  companyName: { type: String, default: '', trim: true },

  status: {
    type: String,
    enum: ['pending', 'in_progress', 'completed', 'failed'],
    default: 'pending'
  },
  aiModelUsed: { type: String, default: '', trim: true },
  generatedAt: { type: Date },
  error      : { type: String, default: '' },

  // Snapshot des chiffres utilisés — audit : prouve que le LLM n'a pas inventé.
  facts: {
    followers            : { type: Number, default: 0 },
    engagementRate       : { type: Number, default: 0 },
    postsPerWeek         : { type: Number, default: 0 },
    contentMix           : { type: mongoose.Schema.Types.Mixed, default: {} },
    topHashtags          : { type: [String], default: [] },
    platforms            : { type: [String], default: [] },
    classificationMaturity: { type: String, default: '' },
    geographicScope      : { type: String, default: '' },
    industry             : { type: String, default: '' },
    country              : { type: String, default: '' },
    // Benchmarks sectoriels (depuis MarketResearch si dispo)
    sectorAvgEngagement  : { type: Number, default: null },
    sectorAvgPostsPerWeek: { type: Number, default: null },
    sectorLeaderCount    : { type: Number, default: null },
    sectorStartupCount   : { type: Number, default: null },
    sectorDominantPlatform: { type: String, default: '' },
    sectorMaturity       : { type: String, default: '' },
    hasMarketSummary     : { type: Boolean, default: false }
  },

  // Les 4 quadrants — FORME LEGACY (string) pour compat front actuel.
  // Chaîne construite en joignant les bullets par " • ".
  swot: {
    strengths    : { type: String, default: '', maxlength: QUADRANT_TEXT_MAX, trim: true },
    weaknesses   : { type: String, default: '', maxlength: QUADRANT_TEXT_MAX, trim: true },
    opportunities: { type: String, default: '', maxlength: QUADRANT_TEXT_MAX, trim: true },
    threats      : { type: String, default: '', maxlength: QUADRANT_TEXT_MAX, trim: true }
  },

  // Les 4 quadrants — FORME STRUCTURÉE : 2 à 4 bullets étayés par des chiffres.
  // C'est ce que consomme tout futur front amélioré.
  swotBullets: {
    strengths    : { type: [String], default: [] },
    weaknesses   : { type: [String], default: [] },
    opportunities: { type: [String], default: [] },
    threats      : { type: [String], default: [] }
  },

  // Recommandations actionnables issues du SWOT (bonus §6 de l'upgrade).
  recommendations: { type: [String], default: [] },

  // Source par section (llm / fallback / mixed) + raison du rejet si applicable.
  sources: {
    strengths      : { type: sourceSchema, default: () => ({}) },
    weaknesses     : { type: sourceSchema, default: () => ({}) },
    opportunities  : { type: sourceSchema, default: () => ({}) },
    threats        : { type: sourceSchema, default: () => ({}) },
    recommendations: { type: sourceSchema, default: () => ({}) }
  }
}, {
  timestamps: true,
  toJSON    : { virtuals: true },
  toObject  : { virtuals: true }
});

swotAnalysisSchema.index({ projectId: 1 });
swotAnalysisSchema.index({ status: 1 });

swotAnalysisSchema.virtual('isCompleted').get(function() {
  return this.status === 'completed';
});

swotAnalysisSchema.methods.markAsCompleted = function() {
  this.status      = 'completed';
  this.error       = '';
  this.generatedAt = new Date();
  return this.save();
};

swotAnalysisSchema.methods.markAsFailed = function(errorMessage) {
  this.status = 'failed';
  this.error  = errorMessage || '';
  return this.save();
};

swotAnalysisSchema.statics.findByCompetitor = function(competitorId) {
  return this.findOne({ competitorId });
};

swotAnalysisSchema.statics.findOrCreate = async function(competitorId, projectId) {
  let doc = await this.findOne({ competitorId });
  if (!doc) {
    doc = await this.create({ competitorId, projectId });
  }
  return doc;
};

module.exports = mongoose.model('SwotAnalysis', swotAnalysisSchema);
