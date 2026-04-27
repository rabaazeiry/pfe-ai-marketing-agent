// backend/src/models/index.js

const User           = require('./User.model');
const Project        = require('./Project.model');
const Competitor     = require('./Competitor.model');
const SocialAnalysis = require('./SocialAnalysis.model');
const Insight        = require('./Insight.model');
const CampaignPlan   = require('./CampaignPlan.model');
const Report         = require('./Report.model');
const MarketResearch = require('./MarketResearch.model'); // ✅ AJOUTÉ
const SwotAnalysis   = require('./SwotAnalysis.model');

module.exports = {
  User,
  Project,
  Competitor,
  SocialAnalysis,
  Insight,
  CampaignPlan,
  Report,
  MarketResearch, // ✅ AJOUTÉ
  SwotAnalysis
};