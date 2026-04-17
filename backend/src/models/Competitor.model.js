// src/models/Competitor.model.js
// VERSION 5 — CORRECTION: Ajout followers et postsCount dans socialMedia

const mongoose = require('mongoose');

const competitorSchema = new mongoose.Schema({

  // ===== RELATION AVEC LE PROJET =====
  projectId: {
    type    : mongoose.Schema.Types.ObjectId,
    ref     : 'Project',
    required: [true, 'Projet requis'],
    index   : true
  },

  // ===== INFORMATIONS DE BASE =====
  companyName: {
    type     : String,
    required : [true, 'Nom de l\'entreprise requis'],
    minlength: [2, 'Minimum 2 caractères'],
    maxlength: [100, 'Maximum 100 caractères'],
    trim     : true
  },

  website: {
    type   : String,
    trim   : true,
    default: ''
  },

  description: {
    type     : String,
    maxlength: [1000, 'Maximum 1000 caractères'],
    trim     : true,
    default  : ''
  },

  logo: {
    url   : { type: String, default: '' },
    source: { type: String, default: '' }
  },

  // ===== CLASSIFICATION SIMPLE : STARTUP / LEADER =====
  classificationMaturity: {
    type   : String,
    enum   : {
      values : ['startup', 'leader'],
      message: '{VALUE} n\'est pas valide — utiliser startup ou leader'
    },
    default: 'startup'
  },

  classification: {
    type   : String,
    default: 'startup'
  },

  classificationScore: {
    type   : Number,
    default: 0,
    min    : 0,
    max    : 100
  },

  classificationJustification: {
    type     : String,
    default  : '',
    maxlength: [500, 'Maximum 500 caractères']
  },

  rank: {
    type   : Number,
    default: 0,
    min    : 0
  },

  isManuallyAdded: {
    type   : Boolean,
    default: false
  },

  foundedYear: {
    type: Number,
    min : [1800, 'Année invalide'],
    max : [new Date().getFullYear(), 'Année future invalide']
  },

  country: {
    type     : String,
    uppercase: true,
    trim     : true,
    validate : {
      validator: function(v) { return !v || /^[A-Z]{2}$/.test(v); },
      message  : 'Code pays invalide (ex: TN, FR, US, UK)'
    }
  },

  // ===== RÉSEAUX SOCIAUX =====
  // ✅ CORRIGÉ - Ajout de followers et postsCount
  socialMedia: {
    instagram: {
      username  : { type: String, trim: true, default: '' },
      url       : { type: String, trim: true, default: '' },
      verified  : { type: Boolean, default: false },
      followers : { type: Number, default: 0, min: 0 },
      postsCount: { type: Number, default: 0, min: 0 }
    },
    facebook: {
      username  : { type: String, trim: true, default: '' },
      url       : { type: String, trim: true, default: '' },
      verified  : { type: Boolean, default: false },
      followers : { type: Number, default: 0, min: 0 },
      postsCount: { type: Number, default: 0, min: 0 }
    },
    linkedin: {
      username  : { type: String, trim: true, default: '' },
      url       : { type: String, trim: true, default: '' },
      verified  : { type: Boolean, default: false },
      followers : { type: Number, default: 0, min: 0 },
      postsCount: { type: Number, default: 0, min: 0 }
    },
    tiktok: {
      username  : { type: String, trim: true, default: '' },
      url       : { type: String, trim: true, default: '' },
      verified  : { type: Boolean, default: false },
      followers : { type: Number, default: 0, min: 0 },
      postsCount: { type: Number, default: 0, min: 0 }
    }
  },

  // ===== ANALYSE SWOT =====
  swotAnalysis: {
    strengths: {
      type    : [String], default: [],
      validate: { validator: arr => arr.length <= 10, message: 'Maximum 10 forces' }
    },
    weaknesses: {
      type    : [String], default: [],
      validate: { validator: arr => arr.length <= 10, message: 'Maximum 10 faiblesses' }
    },
    opportunities: {
      type    : [String], default: [],
      validate: { validator: arr => arr.length <= 10, message: 'Maximum 10 opportunités' }
    },
    threats: {
      type    : [String], default: [],
      validate: { validator: arr => arr.length <= 10, message: 'Maximum 10 menaces' }
    },
    analyzedAt: { type: Date }
  },

  // ===== STATUT DE SCRAPING =====
  scrapingStatus: {
    type   : String,
    enum   : {
      values : ['pending', 'in_progress', 'completed', 'failed'],
      message: '{VALUE} n\'est pas un statut valide'
    },
    default: 'pending'
  },

  lastScrapedAt: { type: Date },
  scrapingError : { type: String, default: '' },

  // ===== MÉTRIQUES GLOBALES =====
  metrics: {
    totalFollowers    : { type: Number, default: 0, min: 0 },
    avgEngagementRate : { type: Number, default: 0, min: 0, max: 100 },
    platformsCount    : { type: Number, default: 0, min: 0, max: 4 },
    overallScore      : { type: Number, default: 0, min: 0, max: 100 }
  },

  // ===== MÉTADONNÉES =====
  discoveredAt: { type: Date, default: Date.now },
  isActive    : { type: Boolean, default: true },
  notes       : { type: String, maxlength: [1000, 'Maximum 1000 caractères'], default: '' }

}, {
  timestamps: true,
  toJSON    : { virtuals: true },
  toObject  : { virtuals: true }
});

// ===== INDEX =====
competitorSchema.index({ projectId: 1, classificationMaturity: 1 });
competitorSchema.index({ projectId: 1, companyName: 1 });
competitorSchema.index({ scrapingStatus: 1 });
competitorSchema.index({ createdAt: -1 });

// ===== CHAMPS VIRTUELS =====
competitorSchema.virtual('displayName').get(function() {
  return `${this.companyName} (${this.classificationMaturity})`;
});

competitorSchema.virtual('isLeader').get(function() {
  return this.classificationMaturity === 'leader';
});

competitorSchema.virtual('isStartup').get(function() {
  return this.classificationMaturity === 'startup';
});

competitorSchema.virtual('hasSocialMedia').get(function() {
  return !!(this.socialMedia?.instagram?.url || this.socialMedia?.facebook?.url);
});

competitorSchema.virtual('hasCompleteSwot').get(function() {
  return (
    (this.swotAnalysis?.strengths?.length     || 0) > 0 &&
    (this.swotAnalysis?.weaknesses?.length    || 0) > 0 &&
    (this.swotAnalysis?.opportunities?.length || 0) > 0 &&
    (this.swotAnalysis?.threats?.length       || 0) > 0
  );
});

// ===== MÉTHODES D'INSTANCE =====
competitorSchema.methods.startScraping = function() {
  this.scrapingStatus = 'in_progress';
  this.scrapingError  = '';
  return this.save();
};

competitorSchema.methods.completeScraping = function() {
  this.scrapingStatus = 'completed';
  this.lastScrapedAt  = new Date();
  this.scrapingError  = '';
  return this.save();
};

competitorSchema.methods.failScraping = function(errorMessage) {
  this.scrapingStatus = 'failed';
  this.scrapingError  = errorMessage;
  return this.save();
};

competitorSchema.methods.archive    = function() { this.isActive = false; return this.save(); };
competitorSchema.methods.reactivate = function() { this.isActive = true;  return this.save(); };

competitorSchema.methods.updateSwot = function(swotData) {
  this.swotAnalysis.strengths     = swotData.strengths     || this.swotAnalysis.strengths;
  this.swotAnalysis.weaknesses    = swotData.weaknesses    || this.swotAnalysis.weaknesses;
  this.swotAnalysis.opportunities = swotData.opportunities || this.swotAnalysis.opportunities;
  this.swotAnalysis.threats       = swotData.threats       || this.swotAnalysis.threats;
  this.swotAnalysis.analyzedAt    = new Date();
  return this.save();
};

competitorSchema.methods.updateClassification = function(data) {
  if (data.maturity) {
    this.classificationMaturity = data.maturity;
    this.classification         = data.maturity;
  }
  this.classificationScore         = data.score         || 0;
  this.classificationJustification = data.justification || '';
  return this.save();
};

competitorSchema.methods.updateLogo = function(logoUrl, source) {
  this.logo.url    = logoUrl || '';
  this.logo.source = source  || '';
  return this.save();
};

// ===== MÉTHODES STATIQUES =====
competitorSchema.statics.findByProject = function(projectId) {
  return this.find({ projectId, isActive: true })
    .sort({ 'metrics.overallScore': -1 });
};

competitorSchema.statics.findLeaders = function(projectId) {
  return this.find({ projectId, classificationMaturity: 'leader', isActive: true })
    .sort({ 'metrics.overallScore': -1 });
};

competitorSchema.statics.findStartups = function(projectId) {
  return this.find({ projectId, classificationMaturity: 'startup', isActive: true })
    .sort({ 'metrics.overallScore': -1 });
};

competitorSchema.statics.countByScrapingStatus = async function(projectId) {
  const competitors = await this.find({ projectId });
  return {
    total      : competitors.length,
    pending    : competitors.filter(c => c.scrapingStatus === 'pending').length,
    in_progress: competitors.filter(c => c.scrapingStatus === 'in_progress').length,
    completed  : competitors.filter(c => c.scrapingStatus === 'completed').length,
    failed     : competitors.filter(c => c.scrapingStatus === 'failed').length
  };
};

competitorSchema.statics.getStatsByClassification = async function(projectId) {
  const competitors = await this.find({ projectId, isActive: true });
  return {
    total   : competitors.length,
    leaders : competitors.filter(c => c.classificationMaturity === 'leader').length,
    startups: competitors.filter(c => c.classificationMaturity === 'startup').length,
  };
};

// ===== HOOKS =====
const VALID_MATURITIES = ['startup', 'leader'];
const MATURITY_MAP = { seed: 'startup', emerging: 'startup', growth: 'startup', mature: 'leader', dominant: 'leader' };

function normalizeMaturity(value) {
  if (VALID_MATURITIES.includes(value)) return value;
  return MATURITY_MAP[value] || 'startup';
}

// pre('validate') runs BEFORE Mongoose enum validation — pre('save') is too late
competitorSchema.pre('validate', function(next) {
  this.classificationMaturity = normalizeMaturity(this.classificationMaturity);
  this.classification = this.classificationMaturity;
  next();
});

// findByIdAndUpdate / updateOne / updateMany bypass pre('save') — normalize here too
function normalizeMaturityInUpdate(next) {
  const update = this.getUpdate();
  if (update?.classificationMaturity) {
    update.classificationMaturity = normalizeMaturity(update.classificationMaturity);
    update.classification = update.classificationMaturity;
  }
  if (update?.$set?.classificationMaturity) {
    update.$set.classificationMaturity = normalizeMaturity(update.$set.classificationMaturity);
    update.$set.classification = update.$set.classificationMaturity;
  }
  next();
}
competitorSchema.pre('findOneAndUpdate', normalizeMaturityInUpdate);
competitorSchema.pre('updateOne', normalizeMaturityInUpdate);
competitorSchema.pre('updateMany', normalizeMaturityInUpdate);

competitorSchema.pre('deleteOne', { document: true, query: false }, async function(next) {
  try {
    const SocialAnalysis = mongoose.models.SocialAnalysis || null;
    if (SocialAnalysis) {
      await SocialAnalysis.deleteMany({ competitorId: this._id });
    }
    next();
  } catch (error) {
    next();
  }
});

module.exports = mongoose.model('Competitor', competitorSchema);