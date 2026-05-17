// backend/src/routes/campaign.routes.js

const express = require('express');
const router  = express.Router();
const { getCampaignByIndustry, regenerateCampaign } = require('../controllers/campaign.controller');
const { protect } = require('../middlewares/auth.middleware');

router.use(protect);

router.get('/:industry', getCampaignByIndustry);
router.post('/:industry/regenerate', regenerateCampaign);

module.exports = router;
