// backend/src/routes/project.routes.js

const express = require('express');
const router  = express.Router();
const {
  createProject,
  getAllProjects,
  getProject,
  updateProject,
  deleteProject,
  updateProgress,
  getProjectInsights,
  suggestProjectName,
} = require('../controllers/project.controller');
const { classifyProjectCompetitors } = require('../controllers/classification.controller');
const { protect } = require('../middlewares/auth.middleware');

router.use(protect);

// Must be BEFORE /:id to avoid "suggest-name" being treated as an id
router.post('/suggest-name', suggestProjectName);

router.route('/')
  .get(getAllProjects)
  .post(createProject);

router.route('/:id')
  .get(getProject)
  .put(updateProject)
  .delete(deleteProject);

router.patch('/:id/progress',   updateProgress);
router.get('/:id/insights',     getProjectInsights);
router.post('/:id/classify',    classifyProjectCompetitors);

module.exports = router;
