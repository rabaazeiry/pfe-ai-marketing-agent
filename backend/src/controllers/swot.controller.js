// backend/src/controllers/swot.controller.js

const mongoose     = require('mongoose');
const Competitor   = require('../models/Competitor.model');
const SwotAnalysis = require('../models/SwotAnalysis.model');
const swotService  = require('../services/swot.service');

// Garantit que l'utilisateur authentifié possède bien le projet du concurrent.
// Retourne le competitor chargé si OK, ou renvoie 403/404 et stoppe.
async function _loadOwnedCompetitor(req, res) {
  const { competitorId } = req.params;
  if (!mongoose.Types.ObjectId.isValid(competitorId)) {
    res.status(400).json({ success: false, message: 'competitorId invalide' });
    return null;
  }
  const competitor = await Competitor.findById(competitorId).populate('projectId', 'userId');
  if (!competitor) {
    res.status(404).json({ success: false, message: 'Concurrent introuvable' });
    return null;
  }
  const ownerId = competitor.projectId && competitor.projectId.userId;
  if (!ownerId || ownerId.toString() !== req.user._id.toString()) {
    res.status(403).json({ success: false, message: 'Accès refusé' });
    return null;
  }
  return competitor;
}

// GET /api/swot/competitor/:competitorId
async function getSwot(req, res, next) {
  try {
    const competitor = await _loadOwnedCompetitor(req, res);
    if (!competitor) return;

    const doc = await SwotAnalysis.findByCompetitor(competitor._id);
    if (!doc) {
      return res.status(404).json({
        success: false,
        message: 'Aucune analyse SWOT pour ce concurrent'
      });
    }
    return res.json({ success: true, data: doc });
  } catch (err) {
    next(err);
  }
}

// POST /api/swot/competitor/:competitorId/generate
async function generateSwot(req, res, next) {
  try {
    const competitor = await _loadOwnedCompetitor(req, res);
    if (!competitor) return;

    const doc = await swotService.generateForCompetitor(competitor._id);
    return res.json({ success: true, data: doc });
  } catch (err) {
    if (err.code === 'COMPETITOR_INACTIVE') {
      return res.status(409).json({ success: false, message: err.message });
    }
    next(err);
  }
}

module.exports = { getSwot, generateSwot };
