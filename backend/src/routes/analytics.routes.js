// backend/src/routes/analytics.routes.js

const express = require('express');
const router = express.Router();
const { getAnalyticsOverview } = require('../controllers/analytics.controller');
const { protect } = require('../middlewares/auth.middleware');

router.use(protect);

router.get('/overview', getAnalyticsOverview);

module.exports = router;
