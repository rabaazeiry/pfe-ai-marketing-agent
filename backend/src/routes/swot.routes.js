// backend/src/routes/swot.routes.js

const express = require('express');
const router  = express.Router();
const { getSwot, generateSwot } = require('../controllers/swot.controller');
const { protect } = require('../middlewares/auth.middleware');

router.use(protect);

router.get ('/competitor/:competitorId',          getSwot);
router.post('/competitor/:competitorId/generate', generateSwot);

module.exports = router;
