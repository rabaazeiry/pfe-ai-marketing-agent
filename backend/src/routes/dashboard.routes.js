// backend/src/routes/dashboard.routes.js

const express = require('express');
const router = express.Router();
const { getDashboardStats } = require('../controllers/dashboard.controller');
const { protect } = require('../middlewares/auth.middleware');

router.use(protect);

router.get('/stats', getDashboardStats);

module.exports = router;
