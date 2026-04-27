// backend/src/services/apify.service.js
// Scraping Instagram + Facebook via Apify REST API

const axios = require('axios');

const APIFY_BASE    = 'https://api.apify.com/v2';
const POLL_INTERVAL = 4000;   // 4 secondes entre chaque poll
const MAX_WAIT      = 300000; // 5 minutes max par run

const ACTORS = {
  INSTAGRAM_PROFILE : 'apify/instagram-profile-scraper',
  INSTAGRAM_POST    : 'apify/instagram-post-scraper',
  FACEBOOK_PAGE     : 'apify/facebook-pages-scraper',
};

class ApifyService {

  constructor() {
    this.token = process.env.APIFY_API_KEY;
  }

  // ═══════════════════════════════════════════════════════
  // MÉTHODE PRINCIPALE — scraper un concurrent complet
  // ═══════════════════════════════════════════════════════

  async scrapeCompetitor(competitor) {
    const result = { instagram: null, facebook: null };

    const igUrl = competitor.socialMedia?.instagram?.url;
    const fbUrl = competitor.socialMedia?.facebook?.url;

    console.log(`\n📱 Apify — scraping: ${competitor.companyName}`);

    if (igUrl) {
      try {
        console.log(`   📸 Instagram: ${igUrl}`);
        result.instagram = await this.scrapeInstagram(igUrl);
        console.log(`   ✅ Instagram: ${result.instagram.followers.toLocaleString()} followers`);
      } catch (e) {
        console.warn(`   ⚠️  Instagram échoué: ${e.message}`);
      }
    }

    if (fbUrl) {
      try {
        console.log(`   👤 Facebook: ${fbUrl}`);
        result.facebook = await this.scrapeFacebook(fbUrl);
        console.log(`   ✅ Facebook: ${result.facebook.followers.toLocaleString()} followers`);
      } catch (e) {
        console.warn(`   ⚠️  Facebook échoué: ${e.message}`);
      }
    }

    return result;
  }

  // ═══════════════════════════════════════════════════════
  // INSTAGRAM — profil + posts récents
  // ═══════════════════════════════════════════════════════

  async scrapeInstagram(profileUrl, postsLimit = 100) {
    const username = this._extractUsername(profileUrl);
    if (!username) throw new Error(`Username introuvable depuis: ${profileUrl}`);

    console.log(`[Apify] Hybrid scrape start: ${username} (limit=${postsLimit})`);

    const [profileSettled, postsSettled] = await Promise.allSettled([
      this._runActor(ACTORS.INSTAGRAM_PROFILE, {
        usernames    : [username],
        resultsLimit : 1,
        resultsType  : 'details',
      }),
      this._runActor(ACTORS.INSTAGRAM_POST, {
        username     : [username],
        resultsLimit : postsLimit,
      }),
    ]);

    if (profileSettled.status === 'rejected') {
      console.warn(`[Apify] Profile actor failed: ${profileSettled.reason?.message}`);
    }
    if (postsSettled.status === 'rejected') {
      console.warn(`[Apify] Post actor failed: ${postsSettled.reason?.message}`);
    }

    const profileItems = profileSettled.status === 'fulfilled' ? profileSettled.value : [];
    const postItems    = postsSettled.status   === 'fulfilled' ? postsSettled.value   : [];

    if (profileItems.length === 0 && postItems.length === 0) {
      throw new Error('Aucune donnée Instagram retournée (profil + posts en échec)');
    }

    const profileRaw = profileItems[0] || {};
    const merged = {
      ...profileRaw,
      latestPosts: postItems.length > 0
        ? postItems
        : (profileRaw.latestPosts || profileRaw.posts || []),
    };

    console.log(`[Apify] Hybrid done: profile=${profileItems.length}, posts=${postItems.length}`);
    return this._transformInstagram(merged, profileUrl);
  }

  // ═══════════════════════════════════════════════════════
  // FACEBOOK — page + posts récents
  // ═══════════════════════════════════════════════════════

  async scrapeFacebook(pageUrl) {
    const items = await this._runActor(ACTORS.FACEBOOK_PAGE, {
      startUrls  : [{ url: pageUrl }],
      maxPosts   : 20,
      scrapeAbout: true,
    });

    if (!items || items.length === 0) throw new Error('Aucune donnée Facebook retournée');
    return this._transformFacebook(items[0], pageUrl);
  }

  // ═══════════════════════════════════════════════════════
  // TRANSFORMATION Instagram → format SocialAnalysis
  // ═══════════════════════════════════════════════════════

  _transformInstagram(raw, profileUrl) {
    const posts = raw.latestPosts || raw.posts || [];

    const avgLikes    = this._avg(posts.map(p => Math.max(p.likesCount    || p.likes    || 0, 0)));
    const avgComments = this._avg(posts.map(p => Math.max(p.commentsCount || p.comments || 0, 0)));
    const followers   = raw.followersCount || raw.followers || 0;

    const engagementRate = followers > 0
      ? parseFloat(((avgLikes + avgComments) / followers * 100).toFixed(2))
      : 0;

    // Keep ALL posts (no slice, no sort-by-likes). Apify returns them most-recent-first,
    // which matches the `recentPosts` semantic. We preserve that order.
    const recentPosts = posts.map(p => ({
      postUrl        : p.url || (p.shortCode ? `https://www.instagram.com/p/${p.shortCode}/` : ''),
      imageUrl       : p.displayUrl || p.imageUrl || '',
      thumbnailUrl   : p.thumbnailUrl || '',
      videoUrl       : p.videoUrl || '',
      likes          : Math.max(p.likesCount    || p.likes    || 0, 0),
      comments       : Math.max(p.commentsCount || p.comments || 0, 0),
      shares         : 0,
      views          : Math.max(p.videoViewCount || p.videoPlayCount || 0, 0),
      contentType    : this._igContentType(p.type || p.productType || ''),
      slideCount     : Array.isArray(p.childPosts) ? Math.min(Math.max(p.childPosts.length, 1), 20) : 1,
      caption        : (p.caption || '').substring(0, 2200),
      hashtags       : this._extractHashtags(p.caption || ''),
      location       : (p.locationName || '').substring(0, 200),
      publishedAt    : p.timestamp ? new Date(p.timestamp) : null,
      engagementRate : followers > 0
        ? parseFloat(((Math.max(p.likesCount || 0, 0) + Math.max(p.commentsCount || 0, 0)) / followers * 100).toFixed(2))
        : 0,
    }));

    const allCaptions = posts.map(p => p.caption || '').join(' ');

    return {
      platform           : 'instagram',
      profileUrl,
      username           : raw.username || '',
      bio                : raw.biography || raw.bio || '',
      isVerified         : raw.verified  || raw.isVerified || false,
      followers,
      following          : raw.followingCount || raw.following || 0,
      totalPosts         : raw.postsCount || raw.mediaCount || posts.length,
      postsPerWeek       : this._postsPerWeek(posts.map(p => p.timestamp).filter(Boolean)),
      avgLikes,
      avgComments,
      avgShares          : 0,
      avgViews           : this._avg(posts.map(p => Math.max(p.videoViewCount || p.videoPlayCount || 0, 0))),
      engagementRate,
      recentPosts,
      topHashtags        : this._topHashtags(allCaptions),
      contentDistribution: this._contentDistribution(posts.map(p => p.type || p.productType || 'Image')),
      ...this._bestTimes(posts.map(p => p.timestamp).filter(Boolean)),
    };
  }

  // ═══════════════════════════════════════════════════════
  // TRANSFORMATION Facebook → format SocialAnalysis
  // ═══════════════════════════════════════════════════════

  _transformFacebook(raw, pageUrl) {
    const posts = raw.posts || [];

    const avgLikes    = this._avg(posts.map(p => p.likes    || p.likesCount    || 0));
    const avgComments = this._avg(posts.map(p => p.comments || p.commentsCount || 0));
    const avgShares   = this._avg(posts.map(p => p.shares   || p.sharesCount   || 0));
    const followers   = raw.followers || raw.likes || raw.fanCount || 0;

    const engagementRate = followers > 0
      ? parseFloat(((avgLikes + avgComments + avgShares) / followers * 100).toFixed(2))
      : 0;

    const recentPosts = posts.map(p => ({
      postUrl        : p.url || p.postUrl || '',
      likes          : p.likes    || p.likesCount    || 0,
      comments       : p.comments || p.commentsCount || 0,
      shares         : p.shares   || p.sharesCount   || 0,
      contentType    : p.video ? 'video' : 'photo',
      caption        : (p.text || p.message || '').substring(0, 2200),
      hashtags       : this._extractHashtags(p.text || p.message || ''),
      publishedAt    : p.time ? new Date(p.time) : null,
      engagementRate : followers > 0
        ? parseFloat((((p.likes || 0) + (p.comments || 0) + (p.shares || 0)) / followers * 100).toFixed(2))
        : 0,
    }));

    const allTexts = posts.map(p => p.text || p.message || '').join(' ');

    return {
      platform           : 'facebook',
      profileUrl         : pageUrl,
      username           : raw.username || raw.pageUrl?.split('/').filter(Boolean).pop() || '',
      bio                : raw.about || raw.description || '',
      isVerified         : raw.isVerified || raw.verified || false,
      followers,
      following          : 0,
      totalPosts         : posts.length,
      postsPerWeek       : this._postsPerWeek(posts.map(p => p.time).filter(Boolean)),
      avgLikes,
      avgComments,
      avgShares,
      avgViews           : 0,
      engagementRate,
      recentPosts,
      topHashtags        : this._topHashtags(allTexts),
      contentDistribution: { photo: 0, video: 0, reel: 0, carousel: 0, story: 0 },
      reviewsCount       : raw.reviews || raw.reviewsCount || 0,
      rating             : raw.rating  || 0,
      ...this._bestTimes(posts.map(p => p.time).filter(Boolean)),
    };
  }

  // ═══════════════════════════════════════════════════════
  // APIFY REST API — lancer + attendre + récupérer
  // ═══════════════════════════════════════════════════════

  async _runActor(actorId, input) {
    const runRes = await axios.post(
      `${APIFY_BASE}/acts/${encodeURIComponent(actorId)}/runs`,
      input,
      {
        params : { token: this.token },
        headers: { 'Content-Type': 'application/json' },
        timeout: 30000,
      }
    );

    const runId = runRes.data?.data?.id;
    if (!runId) throw new Error('Run ID non retourné par Apify');
    console.log(`   🔄 Run démarré: ${runId}`);

    const run = await this._pollRun(runId);
    if (run.status !== 'SUCCEEDED') throw new Error(`Run Apify échoué: ${run.status}`);

    return await this._getDataset(run.defaultDatasetId);
  }

  async _pollRun(runId) {
    const start = Date.now();
    while (Date.now() - start < MAX_WAIT) {
      await this._sleep(POLL_INTERVAL);
      const res    = await axios.get(`${APIFY_BASE}/actor-runs/${runId}`, {
        params: { token: this.token }, timeout: 10000,
      });
      const status = res.data?.data?.status;
      console.log(`   ⏳ Status: ${status}`);
      if (['SUCCEEDED', 'FAILED', 'ABORTED', 'TIMED-OUT'].includes(status)) return res.data.data;
    }
    throw new Error('Timeout Apify — run trop long (>3min)');
  }

  async _getDataset(datasetId) {
    const res = await axios.get(`${APIFY_BASE}/datasets/${datasetId}/items`, {
      params: { token: this.token, clean: true, format: 'json' }, timeout: 30000,
    });
    return res.data || [];
  }

  // ═══════════════════════════════════════════════════════
  // UTILITAIRES
  // ═══════════════════════════════════════════════════════

  _extractUsername(url) {
    try {
      const segments = new URL(url).pathname.split('/').filter(s => s.length > 0);
      return segments[0] || '';
    } catch { return ''; }
  }

  _igContentType(type) {
    const t = (type || '').toLowerCase();
    if (t.includes('video') || t.includes('reel')) return 'reel';
    if (t.includes('sidecar') || t.includes('carousel')) return 'carousel';
    return 'photo';
  }

  _extractHashtags(text) {
    if (!text) return [];
    const matches = text.match(/#[\w\u0600-\u06FF]+/g) || [];
    return [...new Set(matches.map(h => h.replace('#', '').toLowerCase()))].slice(0, 10);
  }

  _topHashtags(allText) {
    const tags = this._extractHashtags(allText);
    const freq = {};
    tags.forEach(t => { freq[t] = (freq[t] || 0) + 1; });
    return Object.entries(freq)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 15)
      .map(([tag]) => tag);
  }

  _contentDistribution(types) {
    const dist = { photo: 0, video: 0, reel: 0, carousel: 0, story: 0 };
    types.forEach(t => {
      const mapped = this._igContentType(t);
      if (dist[mapped] !== undefined) dist[mapped]++;
    });
    return dist;
  }

  _bestTimes(timestamps) {
    if (!timestamps.length) return { bestDays: [], bestHours: [] };
    const DAY_NAMES = ['sunday','monday','tuesday','wednesday','thursday','friday','saturday'];
    const dayCount  = new Array(7).fill(0);
    const hourCount = new Array(24).fill(0);
    timestamps.forEach(ts => {
      const d = new Date(ts);
      if (!isNaN(d)) { dayCount[d.getDay()]++; hourCount[d.getHours()]++; }
    });
    const bestDays  = dayCount.map((c,i) => [i,c]).sort((a,b) => b[1]-a[1]).slice(0,3).map(([i]) => DAY_NAMES[i]);
    const bestHours = hourCount.map((c,i) => [i,c]).sort((a,b) => b[1]-a[1]).slice(0,3).map(([i]) => i);
    return { bestDays, bestHours };
  }

  _postsPerWeek(timestamps) {
    if (timestamps.length < 2) return 0;
    const dates  = timestamps.map(ts => new Date(ts)).filter(d => !isNaN(d)).sort((a,b) => a-b);
    const weeks  = (dates[dates.length-1] - dates[0]) / (1000*60*60*24*7);
    if (weeks < 0.5) return dates.length;
    return parseFloat((dates.length / weeks).toFixed(1));
  }

  _avg(arr) {
    if (!arr.length) return 0;
    return Math.round(arr.reduce((s,v) => s+v, 0) / arr.length);
  }

  _sleep(ms) { return new Promise(r => setTimeout(r, ms)); }
}

module.exports = new ApifyService();
