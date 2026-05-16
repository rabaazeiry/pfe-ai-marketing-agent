// src/models/Project.model.js
// VERSION 4 — Fix industry Fashion & Retail

const mongoose = require('mongoose');

const projectSchema = new mongoose.Schema({

  // ===== RELATION AVEC L'UTILISATEUR =====
  userId: {
    type    : mongoose.Schema.Types.ObjectId,
    ref     : 'User',
    required: [true, 'Utilisateur requis'],
    index   : true
  },

  // ===== ENTRÉES UTILISATEUR =====
  businessIdea: {
    type     : String,
    required : [true, 'Idée business requise'],
    minlength: [10, 'Minimum 10 caractères'],
    maxlength: [1000, 'Maximum 1000 caractères'],
    trim     : true
  },

  marketCategory: {
    type     : String,
    required : [true, 'Catégorie de marché requise'],
    minlength: [2, 'Minimum 2 caractères'],
    maxlength: [200, 'Maximum 200 caractères'],
    trim     : true
  },

  targetCountry: {
    type    : String,
    default : 'TN',
    uppercase: true,
    trim    : true,
    validate: {
      validator: function(v) { return /^[A-Z]{2}$/.test(v); },
      message  : 'Code pays invalide (ex: TN, FR, US, MA)'
    }
  },

  competitorsHint: {
    type   : [String],
    default: [],
    validate: {
      validator: function(v) { return v.length <= 5; },
      message  : 'Maximum 5 concurrents hint'
    }
  },

  // ===== GÉNÉRÉS PAR LLM (Step 1 — Extraction) =====
  name: {
    type   : String,
    trim   : true,
    default: ''
  },

  // ✅ FIX — default changé de 'Food Business' → 'Fashion & Retail'
  industry: {
    type   : String,
    trim   : true,
    default: 'Fashion & Retail'
  },

  country: {
    type   : String,
    trim   : true,
    default: 'Tunisie'
  },

  keywords: {
    type   : [String],
    default: []
  },

  searchQueries: {
    type   : [String],
    default: []
  },

  industryTerms: {
    type   : [String],
    default: []
  },

  targetAudience: {
    type   : [String],
    default: []
  },

  languages: {
    type   : [String],
    default: ['fr', 'ar', 'en']
  },

  extractionStatus: {
    type   : String,
    enum   : ['pending', 'completed', 'failed'],
    default: 'pending'
  },

  pipelineStatus: {
    type: String,
    enum: [
      'idle',
      'step1_extraction',
      'step1_complete',
      'step2_discovery',
      'step2_complete',
      'step3_scraping',
      'step3_complete',
      'step4_insights',
      'step4_complete',
      'step5_campaign',
      'step5_complete',
    ],
    default: 'idle'
  },

  // ===== AUTRES CHAMPS =====
  description       : { type: String, default: '' },
  businessObjectives: { type: String, default: '' },

  status: {
    type   : String,
    enum   : ['draft', 'active', 'completed', 'archived'],
    default: 'draft'
  },

  progressPercentage: { type: Number, default: 0, min: 0, max: 100 },
  competitorsCount  : { type: Number, default: 0, min: 0 },
  lastAnalysisDate  : { type: Date }

}, {
  timestamps: true,
  toJSON    : { virtuals: true },
  toObject  : { virtuals: true }
});

// ===== INDEX =====
projectSchema.index({ userId: 1, status: 1 });
projectSchema.index({ createdAt: -1 });

// ===== VIRTUELS =====
projectSchema.virtual('displayName').get(function() {
  return this.name || 'Projet sans nom';
});

projectSchema.virtual('fullDisplayName').get(function() {
  return `${this.name || 'Projet'} - ${this.marketCategory || this.industry || 'N/A'} (${this.country})`;
});

// ===== MÉTHODES =====
projectSchema.methods.activate  = function() { this.status = 'active';    return this.save(); };
projectSchema.methods.complete   = function() { this.status = 'completed'; return this.save(); };
projectSchema.methods.archive    = function() { this.status = 'archived';  return this.save(); };
projectSchema.methods.incrementCompetitors = function() { this.competitorsCount += 1; return this.save(); };
projectSchema.methods.decrementCompetitors = function() { if (this.competitorsCount > 0) this.competitorsCount -= 1; return this.save(); };
projectSchema.methods.updateProgress = function(p) { this.progressPercentage = Math.min(Math.max(p, 0), 100); return this.save(); };

projectSchema.methods.advancePipeline = function(newStatus) {
  this.pipelineStatus = newStatus;
  const progressMap = {
    'idle': 0, 'step1_extraction': 5, 'step1_complete': 15,
    'step2_discovery': 20, 'step2_complete': 35,
    'step3_scraping': 40, 'step3_complete': 60,
    'step4_insights': 65, 'step4_complete': 80,
    'step5_campaign': 85, 'step5_complete': 100,
  };
  this.progressPercentage = progressMap[newStatus] || this.progressPercentage;
  return this.save();
};

projectSchema.statics.findActiveByUser = function(userId) {
  return this.find({ userId, status: 'active' }).sort({ updatedAt: -1 });
};

projectSchema.statics.countByStatus = async function(userId) {
  const projects = await this.find({ userId });
  return {
    total    : projects.length,
    draft    : projects.filter(p => p.status === 'draft').length,
    active   : projects.filter(p => p.status === 'active').length,
    completed: projects.filter(p => p.status === 'completed').length,
    archived : projects.filter(p => p.status === 'archived').length
  };
};

// ===== HOOKS =====
projectSchema.pre('save', function(next) {
  // Dédupliquer keywords
  if (this.isModified('keywords') && this.keywords.length > 0) {
    this.keywords = [...new Set(
      this.keywords.map(k => k.trim().toLowerCase()).filter(k => k.length > 0)
    )];
  }
  // Dédupliquer industryTerms
  if (this.isModified('industryTerms') && this.industryTerms.length > 0) {
    this.industryTerms = [...new Set(
      this.industryTerms.map(t => t.trim().toLowerCase()).filter(t => t.length > 0)
    )];
  }
  // ✅ FIX — suppression de this.industry = 'Food Business'
  // industry est maintenant géré par extraction.service.js
  if (this.isNew) {
    if (!this.country) this.country = 'Tunisie';
    if (!this.targetCountry) this.targetCountry = 'TN';
  }
  next();
});

projectSchema.pre('deleteOne', { document: true, query: false }, async function(next) {
  try {
    const competitors   = await mongoose.model('Competitor').find({ projectId: this._id });
    const competitorIds = competitors.map(c => c._id);
    if (competitorIds.length > 0) {
      await mongoose.model('SocialAnalysis').deleteMany({ competitorId: { $in: competitorIds } });
    }
    await mongoose.model('Competitor').deleteMany({ projectId: this._id });
    await mongoose.model('Insight').deleteMany({ projectId: this._id });
    await mongoose.model('CampaignPlan').deleteMany({ projectId: this._id });
    await mongoose.model('Report').deleteMany({ projectId: this._id });
    await mongoose.model('MarketResearch').deleteOne({ projectId: this._id });
    next();
  } catch (error) {
    next(error);
  }
});

module.exports = mongoose.model('Project', projectSchema);