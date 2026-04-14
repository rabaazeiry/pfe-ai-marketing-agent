// scraping.unified.js
// Orchestrator — dispatches per-competitor scraping via Apify (primary path).
// Apify returns data already shaped for SocialAnalysis; we persist it here so
// the post('save') hook on SocialAnalysis recomputes Competitor.metrics.

const apifyService = require('./apify.service');
const Competitor = require('../models/Competitor.model');
const SocialAnalysis = require('../models/SocialAnalysis.model');

const PLATFORM_URL_FIELD = {
  instagram: 'instagram',
  facebook: 'facebook',
};

async function scrapeProjectSocialMedia(projectId, competitorIds = null, platforms = ['instagram', 'facebook']) {
  try {
    console.log(`\n🚀 Scraping ${platforms.join(' + ')} pour projet ${projectId}...\n`);

    const query = { projectId, isActive: true };
    if (competitorIds && competitorIds.length > 0) {
      query._id = { $in: competitorIds };
    }

    const competitors = await Competitor.find(query);
    console.log(`📊 ${competitors.length} concurrent(s) à scraper\n`);

    const results = [];

    for (let i = 0; i < competitors.length; i++) {
      const competitor = competitors[i];
      console.log(`[${i + 1}/${competitors.length}] 🏨 ${competitor.companyName}`);

      const result = {
        competitorId: competitor._id,
        companyName: competitor.companyName,
        instagram: false,
        facebook: false,
        error: null,
      };
      const errors = [];

      // Mark in_progress up front so a dead process leaves a visible trace
      // instead of looking like nothing ever ran.
      await Competitor.findByIdAndUpdate(competitor._id, {
        scrapingStatus: 'in_progress',
        lastScrapedAt: new Date(),
      });

      try {
        for (const platform of platforms) {
          const field = PLATFORM_URL_FIELD[platform];
          const url = competitor.socialMedia?.[field]?.url;
          if (!url) {
            console.log(`      ⏭️  ${platform} skipped (no url on competitor.socialMedia.${field}.url)`);
            continue;
          }

          console.log(`      ▶️  ${platform}: starting Apify run for ${url}`);
          try {
            const data = platform === 'instagram'
              ? await apifyService.scrapeInstagram(url)
              : await apifyService.scrapeFacebook(url);

            await persistAnalysis(competitor, platform, data);
            result[platform] = true;
            console.log(`      ✅ ${platform} sauvegardé (${data.followers} followers, ${data.topPosts?.length || 0} top posts)`);
          } catch (error) {
            console.error(`      ❌ ${platform} failed: ${error.message}`);
            if (error.stack) console.error(error.stack);
            errors.push(`${platform}: ${error.message}`);
          }
        }
      } finally {
        // ALWAYS write a terminal status, even if the for-loop throws synchronously
        // (doesn't protect against process death — that's what `in_progress` above is for).
        const anySuccess = result.instagram || result.facebook;
        await Competitor.findByIdAndUpdate(competitor._id, {
          scrapingStatus: anySuccess ? 'completed' : 'failed',
          scrapingError: errors.join(' | '),
          lastScrapedAt: new Date(),
        });
      }

      if (errors.length > 0) result.error = errors.join(' | ');
      results.push(result);

      if (i < competitors.length - 1) {
        console.log('   ⏳ Pause 5 secondes...\n');
        await new Promise(resolve => setTimeout(resolve, 5000));
      }
    }

    const successCount = results.filter(r => r.instagram || r.facebook).length;
    const failedCount = results.length - successCount;

    console.log(`\n✅ Scraping terminé:`);
    console.log(`   Succès : ${successCount}/${results.length}`);
    console.log(`   Échecs : ${failedCount}/${results.length}\n`);

    return { success: true, total: results.length, successCount, failedCount, results };
  } catch (error) {
    console.error('❌ Erreur globale scraping:', error);
    throw error;
  }
}

// Upsert a SocialAnalysis doc using .save() so pre/post hooks fire
// (post-save recomputes Competitor.metrics from all completed analyses).
async function persistAnalysis(competitor, platform, data) {
  let doc = await SocialAnalysis.findOne({ competitorId: competitor._id, platform });
  if (!doc) {
    doc = new SocialAnalysis({
      projectId: competitor.projectId,
      competitorId: competitor._id,
      platform,
      profileUrl: data.profileUrl,
    });
  }

  doc.profileUrl = data.profileUrl || doc.profileUrl;
  doc.username = data.username || '';
  doc.isVerified = !!data.isVerified;
  doc.bio = (data.bio || '').slice(0, 500);
  doc.followers = data.followers || 0;
  doc.following = data.following || 0;
  doc.totalPosts = data.totalPosts || 0;
  doc.postsPerWeek = data.postsPerWeek || 0;
  doc.avgLikes = data.avgLikes || 0;
  doc.avgComments = data.avgComments || 0;
  doc.avgShares = data.avgShares || 0;
  doc.avgViews = data.avgViews || 0;
  doc.engagementRate = data.engagementRate || 0;
  doc.topPosts = data.topPosts || [];
  doc.topHashtags = data.topHashtags || [];
  doc.contentDistribution = data.contentDistribution || doc.contentDistribution;
  doc.bestDays = data.bestDays || [];
  doc.bestHours = data.bestHours || [];
  doc.scrapingStatus = 'completed';
  doc.lastScrapedAt = new Date();
  doc.scrapingError = '';
  doc.calculatePerformanceScore();

  await doc.save();

  await Competitor.findByIdAndUpdate(competitor._id, {
    [`socialMedia.${platform}.followers`]: data.followers || 0,
    [`socialMedia.${platform}.postsCount`]: data.totalPosts || 0,
    [`socialMedia.${platform}.verified`]: !!data.isVerified,
  });
}

module.exports = { scrapeProjectSocialMedia };
