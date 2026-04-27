// scraping.instagram.complete.js
// SCRAPING INSTAGRAM COMPLET - Version finale pour Step 3-5

const axios = require('axios');
const Competitor = require('../models/Competitor.model');
const SocialAnalysis = require('../models/SocialAnalysis.model');

// ═══════════════════════════════════════════════════════════════════════════
// CONFIGURATION
// ═══════════════════════════════════════════════════════════════════════════

const INSTAGRAM_API_URL = 'https://www.instagram.com/api/v1/users/web_profile_info/';
const INSTAGRAM_HEADERS = {
  'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
  'X-IG-App-ID': '936619743392459',
  'Accept': 'application/json',
  'Accept-Language': 'en-US,en;q=0.9',
  'Origin': 'https://www.instagram.com'
};

// ═══════════════════════════════════════════════════════════════════════════
// FONCTION PRINCIPALE : Scraper Instagram complet
// ═══════════════════════════════════════════════════════════════════════════

async function scrapeInstagramComplete(competitor) {
  const username = competitor.socialMedia?.instagram?.username;
  
  if (!username) {
    throw new Error('Username Instagram manquant');
  }
  
  console.log(`\n📸 Scraping Instagram complet: @${username}`);
  
  try {
    // 1. Récupérer les données du profil
    const profileData = await fetchInstagramProfile(username);
    
    // 2. Extraire les posts
    const posts = extractPosts(profileData);
    
    // 3. Calculer les métriques
    const metrics = calculateMetrics(profileData, posts);
    
    // 4. Sauvegarder dans Competitor
    await saveToCompetitor(competitor, profileData, metrics);
    
    // 5. Sauvegarder dans SocialAnalysis
    await saveToSocialAnalysis(competitor, profileData, posts, metrics);
    
    console.log(`   ✅ Scraping complet terminé !`);
    console.log(`   📊 ${metrics.followers.toLocaleString()} followers`);
    console.log(`   📝 ${posts.length} posts analysés`);
    console.log(`   💬 ${metrics.avgLikes.toLocaleString()} likes moy.`);
    console.log(`   💡 ${metrics.engagementRate.toFixed(2)}% engagement`);
    
    return {
      success: true,
      data: { profileData, posts, metrics }
    };
    
  } catch (error) {
    console.error(`   ❌ Erreur: ${error.message}`);
    throw error;
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// RÉCUPÉRATION DES DONNÉES INSTAGRAM
// ═══════════════════════════════════════════════════════════════════════════

async function fetchInstagramProfile(username) {
  const url = `${INSTAGRAM_API_URL}?username=${username}`;
  
  const response = await axios.get(url, {
    headers: {
      ...INSTAGRAM_HEADERS,
      'Referer': `https://www.instagram.com/${username}/`
    },
    timeout: 15000,
    validateStatus: (status) => status === 200
  });
  
  return response.data.data.user;
}

// ═══════════════════════════════════════════════════════════════════════════
// EXTRACTION DES POSTS
// ═══════════════════════════════════════════════════════════════════════════

function extractPosts(userData) {
  const edges = userData.edge_owner_to_timeline_media?.edges || [];
  
  console.log(`   📋 Extraction de ${edges.length} posts...`);
  
  const posts = edges.map(edge => {
    const node = edge.node;
    
    // Extraire le caption et les hashtags
    const captionData = node.edge_media_to_caption?.edges[0]?.node?.text || '';
    const hashtags = extractHashtags(captionData);
    
    // Déterminer le type de contenu
    const contentType = getContentType(node.__typename, node.product_type);
    
    return {
      postUrl: `https://www.instagram.com/p/${node.shortcode}/`,
      imageUrl: node.display_url || '',
      thumbnailUrl: node.thumbnail_src || '',
      videoUrl: node.video_url || '',
      likes: node.edge_liked_by?.count || 0,
      comments: node.edge_media_to_comment?.count || 0,
      shares: 0, // Instagram GraphQL ne donne pas les shares
      views: node.video_view_count || 0,
      contentType: contentType,
      slideCount: node.edge_sidecar_to_children?.edges?.length || 1,
      caption: captionData.substring(0, 2200), // Max 2200 chars
      hashtags: hashtags,
      location: node.location?.name || '',
      publishedAt: new Date(node.taken_at_timestamp * 1000),
      engagementRate: 0 // Sera calculé après
    };
  });
  
  console.log(`   ✅ ${posts.length} posts extraits`);
  
  return posts;
}

// ═══════════════════════════════════════════════════════════════════════════
// UTILITAIRES
// ═══════════════════════════════════════════════════════════════════════════

function extractHashtags(text) {
  const hashtagRegex = /#[\w\u0600-\u06FF]+/g;
  const matches = text.match(hashtagRegex) || [];
  return matches.map(h => h.replace('#', '').toLowerCase()).slice(0, 30);
}

function getContentType(typename, productType) {
  // typename: GraphImage, GraphVideo, GraphSidecar
  // productType: feed, igtv, clips (reels)
  
  if (productType === 'clips') return 'reel';
  if (productType === 'igtv') return 'video';
  
  if (typename === 'GraphSidecar') return 'carousel';
  if (typename === 'GraphVideo') return 'video';
  if (typename === 'GraphImage') return 'photo';
  
  return 'photo';
}

// ═══════════════════════════════════════════════════════════════════════════
// CALCUL DES MÉTRIQUES
// ═══════════════════════════════════════════════════════════════════════════

function calculateMetrics(userData, posts) {
  const followers = userData.edge_followed_by?.count || 0;
  const following = userData.edge_follow?.count || 0;
  const totalPosts = userData.edge_owner_to_timeline_media?.count || 0;
  
  // Calculer moyennes d'engagement
  const totalLikes = posts.reduce((sum, p) => sum + p.likes, 0);
  const totalComments = posts.reduce((sum, p) => sum + p.comments, 0);
  const totalViews = posts.reduce((sum, p) => sum + p.views, 0);
  
  const avgLikes = posts.length > 0 ? Math.round(totalLikes / posts.length) : 0;
  const avgComments = posts.length > 0 ? Math.round(totalComments / posts.length) : 0;
  const avgViews = posts.length > 0 ? Math.round(totalViews / posts.length) : 0;
  
  // Engagement rate
  const avgEngagement = avgLikes + avgComments;
  const engagementRate = followers > 0 
    ? parseFloat(((avgEngagement / followers) * 100).toFixed(2))
    : 0;
  
  // Posts par semaine (basé sur les 12 derniers posts)
  const postsPerWeek = calculatePostsPerWeek(posts);
  
  // Top hashtags
  const topHashtags = getTopHashtags(posts);
  
  // Distribution du contenu
  const contentDistribution = getContentDistribution(posts);
  
  // Meilleurs jours/heures
  const { bestDays, bestHours } = getBestPostingTimes(posts);
  
  return {
    followers,
    following,
    totalPosts,
    avgLikes,
    avgComments,
    avgViews,
    engagementRate,
    postsPerWeek,
    topHashtags,
    contentDistribution,
    bestDays,
    bestHours
  };
}

function calculatePostsPerWeek(posts) {
  if (posts.length === 0) return 0;
  
  const sortedPosts = posts.sort((a, b) => b.publishedAt - a.publishedAt);
  const newestPost = sortedPosts[0].publishedAt;
  const oldestPost = sortedPosts[sortedPosts.length - 1].publishedAt;
  
  const daysDiff = (newestPost - oldestPost) / (1000 * 60 * 60 * 24);
  const weeksDiff = daysDiff / 7;
  
  return weeksDiff > 0 ? parseFloat((posts.length / weeksDiff).toFixed(1)) : 0;
}

function getTopHashtags(posts) {
  const hashtagCount = {};
  
  posts.forEach(post => {
    post.hashtags.forEach(tag => {
      hashtagCount[tag] = (hashtagCount[tag] || 0) + 1;
    });
  });
  
  return Object.entries(hashtagCount)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 20)
    .map(([tag]) => tag);
}

function getContentDistribution(posts) {
  const distribution = {
    photo: 0,
    video: 0,
    reel: 0,
    carousel: 0,
    story: 0
  };
  
  posts.forEach(post => {
    if (distribution.hasOwnProperty(post.contentType)) {
      distribution[post.contentType]++;
    }
  });
  
  return distribution;
}

function getBestPostingTimes(posts) {
  const dayCount = {};
  const hourCount = {};
  
  posts.forEach(post => {
    const date = new Date(post.publishedAt);
    const day = ['sunday', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday'][date.getDay()];
    const hour = date.getHours();
    
    dayCount[day] = (dayCount[day] || 0) + (post.likes + post.comments);
    hourCount[hour] = (hourCount[hour] || 0) + (post.likes + post.comments);
  });
  
  const bestDays = Object.entries(dayCount)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 3)
    .map(([day]) => day);
  
  const bestHours = Object.entries(hourCount)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 3)
    .map(([hour]) => parseInt(hour));
  
  return { bestDays, bestHours };
}

// ═══════════════════════════════════════════════════════════════════════════
// SAUVEGARDE DANS COMPETITOR
// ═══════════════════════════════════════════════════════════════════════════

async function saveToCompetitor(competitor, userData, metrics) {
  await Competitor.findByIdAndUpdate(competitor._id, {
    'socialMedia.instagram.followers': metrics.followers,
    'socialMedia.instagram.postsCount': metrics.totalPosts,
    'socialMedia.instagram.verified': userData.is_verified || false,
    lastScrapedAt: new Date(),
    scrapingStatus: 'completed'
  });
  
  console.log(`   💾 Données sauvegardées dans Competitor`);
}

// ═══════════════════════════════════════════════════════════════════════════
// SAUVEGARDE DANS SOCIALANALYSIS
// ═══════════════════════════════════════════════════════════════════════════

async function saveToSocialAnalysis(competitor, userData, posts, metrics) {
  const analysisData = {
    projectId: competitor.projectId,
    competitorId: competitor._id,
    platform: 'instagram',
    profileUrl: `https://www.instagram.com/${userData.username}/`,
    username: userData.username,
    isVerified: userData.is_verified || false,
    bio: userData.biography || '',
    
    // Métriques principales
    followers: metrics.followers,
    following: metrics.following,
    totalPosts: metrics.totalPosts,
    postsPerWeek: metrics.postsPerWeek,
    
    // Engagement
    avgLikes: metrics.avgLikes,
    avgComments: metrics.avgComments,
    avgViews: metrics.avgViews,
    engagementRate: metrics.engagementRate,
    
    // Posts (all, ordered most-recent-first)
    recentPosts: posts,
    
    // Hashtags
    topHashtags: metrics.topHashtags,
    
    // Distribution contenu
    contentDistribution: metrics.contentDistribution,
    
    // Meilleurs moments
    bestDays: metrics.bestDays,
    bestHours: metrics.bestHours,
    
    // Statut
    scrapingStatus: 'completed',
    lastScrapedAt: new Date(),
    analysedAt: new Date()
  };
  
  // Upsert (create or update)
  await SocialAnalysis.findOneAndUpdate(
    { competitorId: competitor._id, platform: 'instagram' },
    analysisData,
    { upsert: true, new: true }
  );
  
  console.log(`   💾 Analyse complète sauvegardée dans SocialAnalysis`);
}

// ═══════════════════════════════════════════════════════════════════════════
// EXPORTS
// ═══════════════════════════════════════════════════════════════════════════

module.exports = {
  scrapeInstagramComplete
};