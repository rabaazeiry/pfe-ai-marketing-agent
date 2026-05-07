// backend/src/routes/insights.routes.js

const express = require('express');
const router  = express.Router();
const { getInsightsByIndustry } = require('../controllers/insights.controller');
const { protect } = require('../middlewares/auth.middleware');

router.use(protect);

router.get('/:industry', getInsightsByIndustry);

module.exports = router;
