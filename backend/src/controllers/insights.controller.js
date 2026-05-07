// backend/src/controllers/insights.controller.js
//
// Sert les insights RAG générés par ml-service (Step 4e).
// Source : ml-service/data/step4/insights/insights_<industry>.json

const fs   = require('fs/promises');
const path = require('path');

const INSIGHTS_DIR = path.resolve(
  __dirname, '..', '..', '..', 'ml-service', 'data', 'step4', 'insights'
);

const VALID_INDUSTRIES = ['hotels', 'restaurants', 'beauty', 'fashion', 'patisserie'];

// GET /api/insights/:industry
exports.getInsightsByIndustry = async (req, res, next) => {
  try {
    const industry = String(req.params.industry || '').toLowerCase().trim();

    if (!VALID_INDUSTRIES.includes(industry)) {
      return res.status(400).json({
        success: false,
        message: `Industrie invalide. Valeurs autorisées : ${VALID_INDUSTRIES.join(', ')}`
      });
    }

    const file = path.join(INSIGHTS_DIR, `insights_${industry}.json`);

    let raw;
    try {
      raw = await fs.readFile(file, 'utf-8');
    } catch (err) {
      if (err.code === 'ENOENT') {
        return res.status(404).json({
          success: false,
          message: `Aucun fichier d'insights pour l'industrie "${industry}"`
        });
      }
      throw err;
    }

    const data = JSON.parse(raw);
    return res.status(200).json({ success: true, data });
  } catch (err) {
    next(err);
  }
};
