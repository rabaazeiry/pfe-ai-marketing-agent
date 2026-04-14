// scraping.facebook.js
// Service de scraping Facebook via Graph API
// Alternative au scraping HTML - Officiel et stable

const axios = require('axios');

// ═══════════════════════════════════════════════════════════════════════════
// CONFIGURATION
// ═══════════════════════════════════════════════════════════════════════════

const FB_APP_ID = process.env.FB_APP_ID || '964089586088146';
const FB_APP_SECRET = process.env.FB_APP_SECRET || 'TON_APP_SECRET';
const FB_ACCESS_TOKEN = `${FB_APP_ID}|${FB_APP_SECRET}`;

const FB_API_VERSION = 'v21.0';
const FB_API_BASE = `https://graph.facebook.com/${FB_API_VERSION}`;

// ═══════════════════════════════════════════════════════════════════════════
// FONCTION PRINCIPALE : Scraper Facebook via Graph API
// ═══════════════════════════════════════════════════════════════════════════

async function scrapeFacebookGraphAPI(competitor) {
  try {
    console.log(`      📱 Facebook Graph API ${competitor.socialMedia.facebook.url}`);
    
    // 1. Extraire le username de l'URL
    const facebookUrl = competitor.socialMedia.facebook.url;
    const username = extractFacebookUsername(facebookUrl);
    
    if (!username) {
      throw new Error('Username Facebook introuvable dans l\'URL');
    }
    
    console.log(`         🔍 Username: ${username}`);
    
    // 2. Récupérer le Page ID
    const pageId = await getPageId(username);
    
    if (!pageId) {
      throw new Error('Page Facebook introuvable');
    }
    
    console.log(`         🆔 Page ID: ${pageId}`);
    
    // 3. Récupérer les données complètes
    const pageData = await getPageData(pageId);
    
    // 4. Formater les données
    const followers = pageData.fan_count || pageData.followers_count || 0;
    const posts = formatPosts(pageData.posts?.data || []);
    
    console.log(`         📊 ${followers.toLocaleString()} followers, ${posts.length} posts`);
    
    return {
      followers,
      bio: pageData.about || '',
      verified: pageData.verification_status === 'blue_verified',
      posts
    };

  } catch (error) {
    console.error(`         ❌ Erreur Graph API: ${error.message}`);
    throw error;
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// FONCTIONS AUXILIAIRES
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Extrait le username depuis une URL Facebook
 */
function extractFacebookUsername(url) {
  try {
    // Exemples d'URLs :
    // https://www.facebook.com/FourSeasonsTunis/
    // https://www.facebook.com/profile.php?id=123456789
    // https://m.facebook.com/movenpicklactunis
    
    const urlObj = new URL(url);
    const pathname = urlObj.pathname;
    
    // Cas 1: /username/
    const match = pathname.match(/\/([^\/]+)\/?$/);
    if (match && match[1] !== 'profile.php') {
      return match[1];
    }
    
    // Cas 2: /profile.php?id=123456789
    if (pathname.includes('profile.php')) {
      const id = urlObj.searchParams.get('id');
      if (id) return id;
    }
    
    return null;
  } catch (error) {
    console.error('Erreur extraction username:', error.message);
    return null;
  }
}

/**
 * Récupère le Page ID depuis le username
 */
async function getPageId(username) {
  try {
    const url = `${FB_API_BASE}/${username}?access_token=${FB_ACCESS_TOKEN}`;
    const response = await axios.get(url, { timeout: 10000 });
    return response.data.id;
  } catch (error) {
    console.error('Erreur récupération Page ID:', error.message);
    return null;
  }
}

/**
 * Récupère les données complètes de la page
 */
async function getPageData(pageId) {
  try {
    const fields = [
      'name',
      'about',
      'fan_count',
      'followers_count',
      'verification_status',
      'posts.limit(25){message,created_time,full_picture,likes.summary(true),comments.summary(true),shares}'
    ].join(',');
    
    const url = `${FB_API_BASE}/${pageId}?fields=${fields}&access_token=${FB_ACCESS_TOKEN}`;
    
    const response = await axios.get(url, { timeout: 30000 });
    return response.data;
    
  } catch (error) {
    console.error('Erreur récupération données page:', error.message);
    
    // Si l'erreur est liée aux permissions "posts", retry sans les posts
    if (error.response?.data?.error?.code === 100 || error.response?.data?.error?.message?.includes('posts')) {
      console.log('         ⚠️ Pas d\'accès aux posts, récupération followers seulement');
      
      const fieldsBasic = 'name,about,fan_count,followers_count,verification_status';
      const urlBasic = `${FB_API_BASE}/${pageId}?fields=${fieldsBasic}&access_token=${FB_ACCESS_TOKEN}`;
      
      const responseBasic = await axios.get(urlBasic, { timeout: 10000 });
      return { ...responseBasic.data, posts: { data: [] } };
    }
    
    throw error;
  }
}

/**
 * Formate les posts au format attendu
 */
function formatPosts(posts) {
  return posts.map((post, index) => ({
    postUrl: `https://www.facebook.com/${post.id}`,
    imageUrl: post.full_picture || '',
    thumbnailUrl: post.full_picture || '',
    videoUrl: '',
    likes: post.likes?.summary?.total_count || 0,
    comments: post.comments?.summary?.total_count || 0,
    shares: post.shares?.count || 0,
    views: 0,
    caption: post.message || '',
    contentType: post.full_picture ? 'photo' : 'text',
    slideCount: 1,
    hashtags: extractHashtags(post.message || ''),
    location: '',
    publishedAt: post.created_time || new Date().toISOString()
  }));
}

/**
 * Extrait les hashtags d'un texte
 */
function extractHashtags(text) {
  const regex = /#(\w+)/g;
  const matches = text.matchAll(regex);
  return Array.from(matches, m => m[1]);
}

// ═══════════════════════════════════════════════════════════════════════════
// EXPORTS
// ═══════════════════════════════════════════════════════════════════════════

module.exports = {
  scrapeFacebookGraphAPI
};