// backend/src/models/MarketResearch.model.js
// ✅ Fix maxlength 3000 → 5000

const mongoose = require('mongoose');

const marketResearchSchema = new mongoose.Schema({

  projectId: {
    type    : mongoose.Schema.Types.ObjectId,
    ref     : 'Project',
    required: [true, 'Projet requis'],
    unique  : true,
    index   : true
  },

  marketSummary: {
    content: {
      type     : String,
      default  : '',
      maxlength: [5000, 'Maximum 5000 caractères'], // ✅ Fix 3000 → 5000
      trim     : true
    },
    generatedAt: {
      type: Date
    },
    competitorsAnalyzed: {
      type   : Number,
      default: 0,
      min    : 0
    }
  },

  marketOverview: {
    totalCompetitors: {
      type   : Number,
      default: 0,
      min    : 0
    },
    leaderCount: {
      type   : Number,
      default: 0,
      min    : 0
    },
    startupCount: {
      type   : Number,
      default: 0,
      min    : 0
    },
    localCount: {
      type   : Number,
      default: 0,
      min    : 0
    },
    internationalCount: {
      type   : Number,
      default: 0,
      min    : 0
    },
    dominantPlatform: {
      type   : String,
      enum   : ['instagram', 'facebook', 'linkedin', 'tiktok', ''],
      default: ''
    },
    marketMaturity: {
      type   : String,
      enum   : ['emerging', 'growing', 'mature', 'declining', 'unknown'],
      default: 'unknown'
    }
  },

  classificationSummary: {
    type: [{
      classification: {
        type: String,
        enum: ['startup', 'leader', 'local', 'international']
      },
      count      : { type: Number, default: 0 },
      competitors: [{ type: String }]
    }],
    default: []
  },

  status: {
    type: String,
    enum: {
      values : ['pending', 'in_progress', 'completed', 'failed'],
      message: '{VALUE} n\'est pas un statut valide'
    },
    default: 'pending'
  },

  aiModelUsed: {
    type   : String,
    default: '',
    trim   : true
  },

  generatedAt: {
    type: Date
  },

  error: {
    type   : String,
    default: ''
  }

}, {
  timestamps: true,
  toJSON    : { virtuals: true },
  toObject  : { virtuals: true }
});

marketResearchSchema.index({ projectId: 1 }, { unique: true });
marketResearchSchema.index({ status: 1 });

marketResearchSchema.virtual('isCompleted').get(function() {
  return this.status === 'completed';
});

marketResearchSchema.virtual('hasMarketSummary').get(function() {
  return !!(this.marketSummary && this.marketSummary.content);
});

marketResearchSchema.methods.markAsCompleted = function() {
  this.status      = 'completed';
  this.error       = '';
  this.generatedAt = new Date();
  return this.save();
};

marketResearchSchema.methods.markAsFailed = function(errorMessage) {
  this.status = 'failed';
  this.error  = errorMessage || '';
  return this.save();
};

marketResearchSchema.methods.updateMarketSummary = function(content, competitorsAnalyzed) {
  this.marketSummary.content             = content || '';
  this.marketSummary.generatedAt         = new Date();
  this.marketSummary.competitorsAnalyzed = competitorsAnalyzed || 0;
  return this.save();
};

marketResearchSchema.methods.updateMarketOverview = function(overviewData) {
  this.marketOverview.totalCompetitors   = overviewData.totalCompetitors   || 0;
  this.marketOverview.leaderCount        = overviewData.leaderCount        || 0;
  this.marketOverview.startupCount       = overviewData.startupCount       || 0;
  this.marketOverview.localCount         = overviewData.localCount         || 0;
  this.marketOverview.internationalCount = overviewData.internationalCount || 0;
  this.marketOverview.dominantPlatform   = overviewData.dominantPlatform   || '';
  this.marketOverview.marketMaturity     = overviewData.marketMaturity     || 'unknown';
  return this.save();
};

marketResearchSchema.statics.findByProject = function(projectId) {
  return this.findOne({ projectId });
};

marketResearchSchema.statics.findOrCreate = async function(projectId) {
  let research = await this.findOne({ projectId });
  if (!research) {
    research = await this.create({ projectId });
  }
  return research;
};

module.exports = mongoose.model('MarketResearch', marketResearchSchema);