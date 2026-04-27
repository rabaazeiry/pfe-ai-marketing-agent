// backend/src/models/SocialAnalysis.model.js
// VERSION FINALE - Avec slideCount, imageUrl, videoUrl, location, views

const mongoose = require('mongoose');

// ═══════════════════════════════════════════════════════════════════════════
// SOUS-SCHÉMA POST - VERSION AMÉLIORÉE
// ═══════════════════════════════════════════════════════════════════════════

const topPostSchema = new mongoose.Schema({
  
  // URLs
  postUrl: { 
    type: String, 
    required: true, 
    trim: true 
  },
  
  // ✨ NOUVEAU - Médias
  imageUrl: { 
    type: String, 
    default: '',
    trim: true
  },
  
  thumbnailUrl: { 
    type: String, 
    default: '',
    trim: true 
  },
  
  videoUrl: { 
    type: String, 
    default: '',
    trim: true 
  },
  
  // Métriques engagement
  likes: { 
    type: Number, 
    default: 0, 
    min: 0 
  },
  
  comments: { 
    type: Number, 
    default: 0, 
    min: 0 
  },
  
  shares: { 
    type: Number, 
    default: 0, 
    min: 0 
  },
  
  // ✨ NOUVEAU - Vues (optionnel)
  views: { 
    type: Number, 
    default: 0, 
    min: 0 
  },
  
  // Type de contenu
  contentType: {
    type: String,
    enum: {
      values: ['photo', 'video', 'reel', 'carousel', 'story', 'article', 'document'],
      message: '{VALUE} n\'est pas un type de contenu valide'
    },
    default: 'photo'
  },
  
  // ✨ NOUVEAU - Nombre de slides pour carousels
  slideCount: { 
    type: Number, 
    default: 1, 
    min: 1,
    max: 20  // ✅ Instagram permet jusqu'à 20 slides
  },
  
  // Contenu
  caption: { 
    type: String, 
    default: '',
    maxlength: [2200, 'Caption trop long (max 2200 caractères)']
  },
  
  hashtags: { 
    type: [String], 
    default: [],
    validate: {
      validator: function(arr) {
        return arr.length <= 30;
      },
      message: 'Maximum 30 hashtags par post'
    }
  },
  
  // ✨ NOUVEAU - Localisation (optionnel)
  location: { 
    type: String, 
    default: '',
    trim: true,
    maxlength: [200, 'Localisation trop longue']
  },
  
  // Metadata
  publishedAt: { 
    type: Date 
  },
  
  engagementRate: {
    type: Number,
    default: 0,
    min: 0,
    max: 1000
  }

}, { _id: false });

// ═══════════════════════════════════════════════════════════════════════════
// SCHÉMA PRINCIPAL
// ═══════════════════════════════════════════════════════════════════════════

const socialAnalysisSchema = new mongoose.Schema({

  // ═══ RELATIONS ═══
  projectId: {
    type: mongoose.Schema.Types.ObjectId,
    ref: 'Project',
    required: [true, 'Projet requis'],
    index: true
  },

  competitorId: {
    type: mongoose.Schema.Types.ObjectId,
    ref: 'Competitor',
    required: [true, 'Concurrent requis'],
    index: true
  },

  // ═══ PLATEFORME ═══
  platform: {
    type: String,
    enum: {
      values: ['instagram', 'linkedin', 'facebook', 'tiktok'],
      message: '{VALUE} n\'est pas une plateforme valide'
    },
    required: [true, 'Plateforme requise']
  },

  profileUrl: { 
    type: String, 
    required: [true, 'URL requise'], 
    trim: true 
  },
  
  username: { 
    type: String, 
    trim: true, 
    default: '' 
  },
  
  isVerified: { 
    type: Boolean, 
    default: false 
  },
  
  bio: { 
    type: String, 
    maxlength: [500, 'Maximum 500 caractères'], 
    default: '' 
  },

  // ═══ MÉTRIQUES PRINCIPALES ═══
  followers: { 
    type: Number, 
    default: 0, 
    min: 0 
  },
  
  following: { 
    type: Number, 
    default: 0, 
    min: 0 
  },
  
  totalPosts: { 
    type: Number, 
    default: 0, 
    min: 0 
  },
  
  postsPerWeek: { 
    type: Number, 
    default: 0, 
    min: 0 
  },

  // ═══ MÉTRIQUES D'ENGAGEMENT ═══
  avgLikes: { 
    type: Number, 
    default: 0, 
    min: 0 
  },
  
  avgComments: { 
    type: Number, 
    default: 0, 
    min: 0 
  },
  
  avgShares: { 
    type: Number, 
    default: 0, 
    min: 0 
  },
  
  avgViews: { 
    type: Number, 
    default: 0, 
    min: 0 
  },
  
  engagementRate: {
    type: Number,
    default: 0,
    min: 0,
    max: 1000
  },

  // ═══ ANALYSE DE CONTENU ═══
  recentPosts: {
    type: [topPostSchema],
    default: []
  },

  topHashtags: {
    type: [String],
    validate: { 
      validator: arr => arr.length <= 30, 
      message: 'Maximum 30 hashtags' 
    },
    default: []
  },

  contentThemes: { 
    type: [String], 
    default: [] 
  },

  contentDistribution: {
    photo: { type: Number, default: 0, min: 0 },
    video: { type: Number, default: 0, min: 0 },
    reel: { type: Number, default: 0, min: 0 },
    carousel: { type: Number, default: 0, min: 0 },
    story: { type: Number, default: 0, min: 0 }
  },

  // ═══ ANALYSE TEMPORELLE ═══
  bestDays: {
    type: [String],
    enum: ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'],
    default: []
  },

  bestHours: {
    type: [Number],
    validate: {
      validator: arr => arr.every(h => h >= 0 && h <= 23),
      message: 'Heures invalides (0-23)'
    },
    default: []
  },

  // ═══ ANALYSE SENTIMENT ═══
  sentiment: {
    positive: {
      type: Number,
      default: 0,
      min: 0,
      max: 100
    },
    negative: {
      type: Number,
      default: 0,
      min: 0,
      max: 100
    },
    neutral: {
      type: Number,
      default: 0,
      min: 0,
      max: 100
    },
    avgScore: {
      type: Number,
      default: 0,
      min: -1,
      max: 1
    },
    modelUsed: {
      type: String,
      default: 'camembert'
    },
    analyzedCommentsCount: {
      type: Number,
      default: 0,
      min: 0
    }
  },

  // ═══ STATUT DU SCRAPING ═══
  scrapingStatus: {
    type: String,
    enum: {
      values: ['pending', 'in_progress', 'completed', 'failed', 'partial'],
      message: '{VALUE} n\'est pas un statut valide'
    },
    default: 'pending'
  },

  lastScrapedAt: { type: Date },
  analysedAt: { type: Date },
  scrapingError: { type: String, default: '' },
  scrapingAttempts: { type: Number, default: 0, min: 0 },

  // ═══ SCORE DE PERFORMANCE ═══
  performanceScore: { 
    type: Number, 
    default: 0, 
    min: 0, 
    max: 100 
  },
  
  rawData: { 
    type: mongoose.Schema.Types.Mixed, 
    default: {} 
  }

}, {
  timestamps: true,
  toJSON: { virtuals: true },
  toObject: { virtuals: true }
});

// ═══════════════════════════════════════════════════════════════════════════
// INDEX
// ═══════════════════════════════════════════════════════════════════════════

socialAnalysisSchema.index({ competitorId: 1, platform: 1 }, { unique: true });
socialAnalysisSchema.index({ projectId: 1, platform: 1 });
socialAnalysisSchema.index({ projectId: 1 });
socialAnalysisSchema.index({ scrapingStatus: 1 });
socialAnalysisSchema.index({ lastScrapedAt: -1 });
socialAnalysisSchema.index({ performanceScore: -1 });

// ═══════════════════════════════════════════════════════════════════════════
// CHAMPS VIRTUELS
// ═══════════════════════════════════════════════════════════════════════════

socialAnalysisSchema.virtual('followerRatio').get(function() {
  if (this.following === 0) return 0;
  return (this.followers / this.following).toFixed(2);
});

socialAnalysisSchema.virtual('avgTotalEngagement').get(function() {
  return this.avgLikes + this.avgComments + this.avgShares;
});

socialAnalysisSchema.virtual('isActive').get(function() {
  if (!this.lastScrapedAt) return false;
  const days = (Date.now() - this.lastScrapedAt) / (1000 * 60 * 60 * 24);
  return days <= 30;
});

socialAnalysisSchema.virtual('displayName').get(function() {
  return `${this.platform} - @${this.username || 'unknown'}`;
});

socialAnalysisSchema.virtual('dominantSentiment').get(function() {
  const { positive, negative, neutral } = this.sentiment;
  if (positive >= negative && positive >= neutral) return 'positive';
  if (negative >= positive && negative >= neutral) return 'negative';
  return 'neutral';
});

// ═══════════════════════════════════════════════════════════════════════════
// MÉTHODES D'INSTANCE
// ═══════════════════════════════════════════════════════════════════════════

socialAnalysisSchema.methods.calculateEngagementRate = function() {
  if (this.followers === 0) { 
    this.engagementRate = 0; 
    return 0; 
  }
  const total = this.avgLikes + this.avgComments + this.avgShares;
  this.engagementRate = parseFloat(((total / this.followers) * 100).toFixed(2));
  return this.engagementRate;
};

socialAnalysisSchema.methods.calculatePerformanceScore = function() {
  let score = 0;
  
  // Score followers
  if (this.followers >= 100000) score += 30;
  else if (this.followers >= 50000) score += 25;
  else if (this.followers >= 10000) score += 20;
  else if (this.followers >= 5000) score += 15;
  else if (this.followers >= 1000) score += 10;
  else score += 5;

  // Score engagement
  if (this.engagementRate >= 10) score += 40;
  else if (this.engagementRate >= 5) score += 30;
  else if (this.engagementRate >= 3) score += 20;
  else if (this.engagementRate >= 1) score += 10;
  else score += 5;

  // Score fréquence
  if (this.postsPerWeek >= 7) score += 20;
  else if (this.postsPerWeek >= 5) score += 15;
  else if (this.postsPerWeek >= 3) score += 10;
  else if (this.postsPerWeek >= 1) score += 5;

  // Bonus vérifié
  if (this.isVerified) score += 10;
  
  this.performanceScore = Math.min(score, 100);
  return this.performanceScore;
};

socialAnalysisSchema.methods.startScraping = function() {
  this.scrapingStatus = 'in_progress';
  this.scrapingAttempts += 1;
  this.scrapingError = '';
  return this.save();
};

socialAnalysisSchema.methods.completeScraping = function(data = {}) {
  this.scrapingStatus = 'completed';
  this.lastScrapedAt = new Date();
  this.analysedAt = new Date();
  this.scrapingError = '';
  
  if (data.followers) this.followers = data.followers;
  if (data.following) this.following = data.following;
  if (data.totalPosts) this.totalPosts = data.totalPosts;
  if (data.postsPerWeek) this.postsPerWeek = data.postsPerWeek;
  if (data.avgLikes) this.avgLikes = data.avgLikes;
  if (data.avgComments) this.avgComments = data.avgComments;
  
  this.calculateEngagementRate();
  this.calculatePerformanceScore();
  return this.save();
};

socialAnalysisSchema.methods.failScraping = function(errorMessage) {
  this.scrapingStatus = 'failed';
  this.scrapingError = errorMessage;
  return this.save();
};

socialAnalysisSchema.methods.updateSentiment = function(sentimentData) {
  this.sentiment.positive = sentimentData.positive || 0;
  this.sentiment.negative = sentimentData.negative || 0;
  this.sentiment.neutral = sentimentData.neutral || 0;
  this.sentiment.avgScore = sentimentData.avgScore || 0;
  this.sentiment.modelUsed = sentimentData.modelUsed || 'camembert';
  this.sentiment.analyzedCommentsCount = sentimentData.analyzedCommentsCount || 0;
  return this.save();
};

// ═══════════════════════════════════════════════════════════════════════════
// MÉTHODES STATIQUES
// ═══════════════════════════════════════════════════════════════════════════

socialAnalysisSchema.statics.findByCompetitorAndPlatform = function(competitorId, platform) {
  return this.findOne({ competitorId, platform });
};

socialAnalysisSchema.statics.findByCompetitor = function(competitorId) {
  return this.find({ competitorId }).sort({ performanceScore: -1 });
};

socialAnalysisSchema.statics.findByProject = function(projectId) {
  return this.find({ projectId })
    .populate('competitorId', 'companyName classification')
    .sort({ performanceScore: -1 });
};

socialAnalysisSchema.statics.getStatsByPlatform = async function(competitorId) {
  const analyses = await this.find({ competitorId });
  const stats = {};
  analyses.forEach(a => {
    stats[a.platform] = {
      followers: a.followers,
      engagementRate: a.engagementRate,
      performanceScore: a.performanceScore,
      lastScraped: a.lastScrapedAt,
      sentiment: a.sentiment
    };
  });
  return stats;
};

socialAnalysisSchema.statics.getProjectStats = async function(projectId) {
  const analyses = await this.find({ projectId, scrapingStatus: 'completed' });
  
  if (analyses.length === 0) {
    return { 
      totalAnalyses: 0, 
      totalFollowers: 0, 
      avgEngagementRate: 0, 
      platforms: {} 
    };
  }
  
  const totalFollowers = analyses.reduce((sum, a) => sum + a.followers, 0);
  const avgEngagement = analyses.reduce((sum, a) => sum + a.engagementRate, 0) / analyses.length;
  
  const platforms = {};
  analyses.forEach(a => {
    if (!platforms[a.platform]) {
      platforms[a.platform] = { count: 0, totalFollowers: 0 };
    }
    platforms[a.platform].count++;
    platforms[a.platform].totalFollowers += a.followers;
  });
  
  return { 
    totalAnalyses: analyses.length, 
    totalFollowers, 
    avgEngagementRate: avgEngagement.toFixed(2), 
    platforms 
  };
};

socialAnalysisSchema.statics.findNeedingRescraping = function(days = 7) {
  const cutoff = new Date();
  cutoff.setDate(cutoff.getDate() - days);
  
  return this.find({
    $or: [
      { scrapingStatus: 'failed' },
      { scrapingStatus: 'pending' },
      { lastScrapedAt: { $lt: cutoff } }
    ]
  });
};

socialAnalysisSchema.statics.countByStatus = async function(competitorId) {
  const analyses = await this.find({ competitorId });
  
  return {
    total: analyses.length,
    pending: analyses.filter(a => a.scrapingStatus === 'pending').length,
    in_progress: analyses.filter(a => a.scrapingStatus === 'in_progress').length,
    completed: analyses.filter(a => a.scrapingStatus === 'completed').length,
    failed: analyses.filter(a => a.scrapingStatus === 'failed').length,
    partial: analyses.filter(a => a.scrapingStatus === 'partial').length
  };
};

// ═══════════════════════════════════════════════════════════════════════════
// HOOKS (MIDDLEWARE MONGOOSE)
// ═══════════════════════════════════════════════════════════════════════════

socialAnalysisSchema.pre('save', function(next) {
  // Synchroniser analysedAt avec lastScrapedAt
  if (this.isModified('lastScrapedAt')) {
    this.analysedAt = this.lastScrapedAt;
  }
  
  // Normaliser username
  if (this.isModified('username') && this.username) {
    this.username = this.username.replace('@', '').trim().toLowerCase();
  }
  
  // Nettoyer hashtags
  if (this.isModified('topHashtags')) {
    this.topHashtags = [...new Set(
      this.topHashtags
        .map(h => h.replace('#', '').trim().toLowerCase())
        .filter(h => h.length > 0)
    )];
  }
  
  // Normaliser profileUrl
  if (this.isModified('profileUrl') && this.profileUrl) {
    if (!this.profileUrl.startsWith('http')) {
      this.profileUrl = 'https://' + this.profileUrl;
    }
  }
  
  // recentPosts: pas de tri — on préserve l'ordre chronologique d'Apify (most recent first)

  next();
});

socialAnalysisSchema.post('save', async function(doc) {
  try {
    const Competitor = mongoose.model('Competitor');
    const competitor = await Competitor.findById(doc.competitorId);
    
    if (competitor) {
      const analyses = await mongoose.model('SocialAnalysis').find({
        competitorId: doc.competitorId,
        scrapingStatus: 'completed'
      });
      
      const totalFollowers = analyses.reduce((sum, a) => sum + a.followers, 0);
      const avgEngagement = analyses.length > 0
        ? analyses.reduce((sum, a) => sum + a.engagementRate, 0) / analyses.length 
        : 0;
      
      competitor.metrics = {
        totalFollowers,
        avgEngagementRate: parseFloat(avgEngagement.toFixed(2)),
        platformsCount: analyses.length,
        overallScore: parseInt(
          (analyses.length > 0
            ? analyses.reduce((sum, a) => sum + a.performanceScore, 0) / analyses.length 
            : 0
          ).toFixed(0)
        )
      };
      
      await competitor.save();
    }
  } catch (error) {
    console.error('Erreur mise à jour métriques:', error);
  }
});

// ═══════════════════════════════════════════════════════════════════════════
// EXPORT
// ═══════════════════════════════════════════════════════════════════════════

module.exports = mongoose.model('SocialAnalysis', socialAnalysisSchema);