// backend/src/routes/index.js

const express = require('express');
const router = express.Router();

const authRoutes           = require('./auth.routes');
const projectRoutes        = require('./project.routes');
const competitorRoutes     = require('./competitor.routes');
const marketResearchRoutes = require('./marketResearch.routes');
const swotRoutes           = require('./swot.routes');
const classificationRoutes = require('./classification.routes');
const scrapingRoutes       = require('./scraping.routes');
const adminRoutes          = require('./admin.routes');
const wsDemoRoutes         = require('./ws-demo.routes');
const webhookRoutes        = require('./webhooks.routes');
const dashboardRoutes      = require('./dashboard.routes');
const analyticsRoutes      = require('./analytics.routes');
const insightsRoutes       = require('./insights.routes');

router.use('/auth',           authRoutes);
router.use('/projects',       projectRoutes);
router.use('/competitors',    competitorRoutes);
router.use('/market-research',marketResearchRoutes);
router.use('/swot',           swotRoutes);
router.use('/classification', classificationRoutes);
router.use('/scraping',       scrapingRoutes);
router.use('/admin',          adminRoutes);
router.use('/ws-demo',        wsDemoRoutes);
router.use('/webhooks',       webhookRoutes);
router.use('/dashboard',      dashboardRoutes);
router.use('/analytics',      analyticsRoutes);
router.use('/insights',       insightsRoutes);

router.get('/health', (req, res) => {
  res.json({
    success: true,
    message: 'API is running',
    timestamp: new Date().toISOString()
  });
});

module.exports = router;