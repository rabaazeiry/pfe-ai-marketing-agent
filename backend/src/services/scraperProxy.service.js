/**
 * Thin proxy to the Python scraper microservice's /v2/scrape endpoint.
 * Keeps the controller free of HTTP-client logic and centralises the
 * SCRAPER_URL base so it's easy to swap later.
 */

const axios = require('axios');
const { SCRAPER_URL } = require('../config/env');

const BASE = SCRAPER_URL || 'http://localhost:8000';

/**
 * Call the Python orchestrator for a single competitor + platform.
 *
 * @param {{ projectId: string, competitorId: string, platform: string, target: string }} opts
 * @returns {Promise<{ method_used: string|null, posts_count: number, social_analysis: object, competitor_update: object }>}
 */
exports.scrapeV2 = async ({ projectId, competitorId, platform, target }) => {
  const { data } = await axios.post(`${BASE}/v2/scrape`, {
    project_id: projectId,
    competitor_id: competitorId,
    platform,
    target
  }, { timeout: 30_000 });
  return data;
};
