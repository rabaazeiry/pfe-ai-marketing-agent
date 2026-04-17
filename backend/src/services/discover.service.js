// backend/src/services/discover.service.js
// VERSION 13 — Fusion doublons IG+FB par companyName normalisé dans _saveCompetitors

const { chromium }  = require('playwright');
const searchService = require('./search.service');
const { extractCompanyName } = require('../utils/filters.util');
const Competitor    = require('../models/Competitor.model');
const Project       = require('../models/Project.model');

// ─────────────────────────────────────────────────────────────────────────────
// DOMAINES EXCLUS
// ─────────────────────────────────────────────────────────────────────────────
const EXCLUDED_DOMAINS = new Set([
  'booking.com', 'expedia.com', 'hotels.com', 'agoda.com',
  'airbnb.com', 'vrbo.com', 'trivago.com', 'kayak.com', 'kayak.fr',
  'tripadvisor.com', 'tripadvisor.fr', 'tripadvisor.tn',
  'holidaycheck.com', 'lastminute.com', 'opodo.com',
  'zenhotels.com', 'reservations.com', 'hotelscombined.com',
  'ttsbooking.tn', 'tta.tn', 'carthago.com',
  'all.accor.com', 'oktunisia.com', 'theluxuryeditor.com',
  'wego.com', 'tn.wego.com', 'wegoarabia.com',
  'google.com', 'google.tn', 'bing.com', 'duckduckgo.com',
  'tunisiebooking.com', 'tunisiebooking.tn', 'tunisie-reservation.com',
  'yelp.com', 'foursquare.com', 'wanderlog.com', 'petitfute.com',
  'restaurantguru.com', 'bnina.tn',
  'wikipedia.org', 'medium.com', 'blogspot.com', 'wordpress.com',
  'routard.com', 'lonelyplanet.com', 'voyageforum.com',
  'marhba.com', 'tunisie.fr', 'tunisia.com',
  'officetourisme.tn', 'tourisme.gov.tn',
  'influencermarketing.ai', 'slh.com',
  'twitter.com', 'x.com', 'youtube.com', 'pinterest.com',
  'tiktok.com', 'snapchat.com', 'reddit.com', 'linktr.ee',
  'play.google.com', 'apps.apple.com', 'gov.tn', 'gouv.fr',
  'mikadothemes.com', 'themeforest.net',
]);

const FAKE_SOCIAL_PATTERNS = [
  'sharer.php', 'shareArticle', 'share?', 'share/',
  'intent/tweet', 'javascript:', 'mailto:',
  'logout', 'login', 'signup', 'register',
  '/explore', '/tags/', '/accounts/', '/directory',
  '/groups/', '/marketplace', '/events/', '/watch',
  '/pages/category', '/search',
  '/reel/', '/p/', '/popular/', '/hashtag/',
  '/stories/', '/posts/', '/shop_tab/',
  '/videos/', '/photos/',
  '/photo/', 'photo/?fbid', 'group.php', '/reels/',
];

const USER_AGENTS = [
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
  'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
];

const MIN_FOLLOWERS = 3000; // ✅ Relevé à 3000 pour filtrer @movenpick_gammarth (2243)
const MIN_FB_LIKES  = 5000; // ✅ Relevé à 5000 pour garder seulement les pages actives

// ─────────────────────────────────────────────────────────────────────────────
// TABLE DE SYNONYMES — pour la fusion des doublons IG+FB
// Clé = username normalisé (minuscule, sans underscore/tiret)
// Valeur = username IG officiel du compte tunisien
// ─────────────────────────────────────────────────────────────────────────────
const SOCIAL_SYNONYMS = {
  // Four Seasons
  'fstunis'          : 'fstunis',
  'fourseasonstu'    : 'fstunis', // "FourSeasonsTunis" normalisé
  'fourseasonstunis' : 'fstunis',

  // Movenpick Lac Tunis
  'movenpicklactunis': 'movenpicklactunis',
  'movenpickdulacu'  : 'movenpicklactunis', // "Mövenpick du Lac" normalisé

  // Movenpick Gammarth — compte officiel seulement
  'movenpickhotelgammarth'    : 'movenpick_hotel_gammarth',
  'movenpick_hotel_gammarth'  : 'movenpick_hotel_gammarth',
  'movenpickgammarth'         : 'movenpick_hotel_gammarth', // FB username

  // Sheraton
  'sheratontunis'    : 'sheratontunis',

  // El Mouradi Gammarth
  'elmouradigammarth': 'elmouradigammarth',
  'mouradigammarth'  : 'elmouradigammarth', // "MouradiGammarth" FB normalisé

  // The Residence
  'theresidencetunis': 'theresidencetunis',

  // Hasdrubal Hammamet
  'hasdrubalhammamet': 'hasdrubalhammamet',

  // Radisson Blu
  'radissonbluhammamet': 'radissonbluhammamet',
};

// ─────────────────────────────────────────────────────────────────────────────
// LISTE DES 15 HÔTELS VÉRIFIÉS — injection MANUELLE uniquement
// ─────────────────────────────────────────────────────────────────────────────
const KNOWN_COMPETITORS_HOTELS = [
  // ── TUNIS / GAMMARTH ──────────────────────────────────────────────────
  {
    companyName: 'Four Seasons Tunis',
    instagram  : 'https://www.instagram.com/fstunis/',
    facebook   : 'https://www.facebook.com/FourSeasonsTunis/',
    website    : 'https://www.fourseasons.com/tunis/',
    maturity   : 'leader',
  },
  {
    companyName: 'The Residence Tunis',
    instagram  : 'https://www.instagram.com/theresidencetunis/',
    facebook   : 'https://www.facebook.com/TheResidenceTunis/',
    website    : 'https://www.cenizaro.com/theresidence/tunis',
    maturity   : 'startup',
  },
  {
    companyName: 'Movenpick Hotel Lac Tunis',
    instagram  : 'https://www.instagram.com/movenpicklactunis/',
    facebook   : 'https://www.facebook.com/movenpicklactunis/',
    website    : 'https://movenpick.accor.com/en/africa/tunisia/tunis/hotel-du-lac-tunis.html',
    maturity   : 'leader',
  },
  {
    companyName: 'Movenpick Hotel Gammarth',
    instagram  : 'https://www.instagram.com/movenpick_hotel_gammarth/',
    facebook   : 'https://www.facebook.com/movenpickgammarth/',
    website    : 'https://movenpick.accor.com/en/africa/tunisia/tunis/hotel-gammarth.html',
    maturity   : 'leader',
  },
  {
    companyName: 'Sheraton Tunis',
    instagram  : 'https://www.instagram.com/sheratontunis/',
    facebook   : 'https://www.facebook.com/sheratontunis/',
    website    : 'https://www.marriott.com/en-us/hotels/tunsi-sheraton-tunis-hotel/overview/',
    maturity   : 'leader',
  },
  {
    companyName: 'El Mouradi Gammarth',
    instagram  : 'https://www.instagram.com/elmouradigammarth/',
    facebook   : 'https://www.facebook.com/MouradiGammarth/',
    website    : 'https://www.elmouradi.com',
    maturity   : 'startup',
  },
  // ── HAMMAMET ──────────────────────────────────────────────────────────
  {
    companyName: 'Hasdrubal Thalassa Hammamet',
    instagram  : '',
    facebook   : 'https://www.facebook.com/hasdrubalhammamet/',
    website    : 'https://hammamet.hasdrubal-thalassa.com/',
    maturity   : 'startup',
  },
  {
    companyName: 'Radisson Blu Hammamet',
    instagram  : 'https://www.instagram.com/radissonbluhammamet/',
    facebook   : 'https://www.facebook.com/RadissonBluHammamet/',
    website    : 'https://www.radissonhotels.com/en-us/hotels/radisson-blu-hammamet',
    maturity   : 'leader',
  },
  {
    companyName: 'Laico Hammamet',
    instagram  : '',
    facebook   : 'https://www.facebook.com/hotellaicohammamet/',
    website    : '',
    maturity   : 'startup',
  },
  // ── SOUSSE ────────────────────────────────────────────────────────────
  {
    companyName: 'Movenpick Resort Sousse',
    instagram  : 'https://www.instagram.com/movenpick_resort_sousse/',
    facebook   : 'https://www.facebook.com/moevenpicksousse/',
    website    : 'https://movenpick.accor.com/en/africa/tunisia/sousse/hotel-sousse.html',
    maturity   : 'leader',
  },
  // ── MONASTIR ──────────────────────────────────────────────────────────
  {
    companyName: 'Hilton Skanes Monastir',
    instagram  : 'https://www.instagram.com/hiltonskanesmonastir/',
    facebook   : 'https://www.facebook.com/hiltonskanesmonastir/',
    website    : 'https://www.hilton.com/en/hotels/monhihi-hilton-skanes-monastir-beach-resort/',
    maturity   : 'leader',
  },
  // ── DJERBA ────────────────────────────────────────────────────────────
  {
    companyName: 'Hasdrubal Prestige Djerba',
    instagram  : 'https://www.instagram.com/hasdrubal_prestige_hotel/',
    facebook   : 'https://www.facebook.com/hasdrubalprestige/',
    website    : 'https://hasdrubalprestige.tn/',
    maturity   : 'startup',
  },
  // ── TOZEUR ────────────────────────────────────────────────────────────
  {
    companyName: 'Anantara Sahara Tozeur',
    instagram  : 'https://www.instagram.com/anantaratozeur/',
    facebook   : 'https://www.facebook.com/anantaratozeur/',
    website    : 'https://www.anantara.com/en/sahara-tozeur',
    maturity   : 'leader',
  },
  // ── CHAÎNES ───────────────────────────────────────────────────────────
  {
    companyName: 'El Mouradi Hotels',
    instagram  : 'https://www.instagram.com/el_mouradi_hotels/',
    facebook   : 'https://www.facebook.com/elmouradihotels/',
    website    : 'https://www.elmouradi.com',
    maturity   : 'leader',
  },
  {
    companyName: 'Iberostar Tunisia',
    instagram  : 'https://www.instagram.com/iberostartunisia/',
    facebook   : 'https://www.facebook.com/iberostartunisia/',
    website    : 'https://www.iberostar.com/en/hotels/tunisie/',
    maturity   : 'leader',
  },
];

// ─────────────────────────────────────────────────────────────────────────────
class DiscoverService {

  // ═══════════════════════════════════════════════════════
  // PIPELINE PRINCIPAL
  // ═══════════════════════════════════════════════════════
  async discoverCompetitors(project, options = {}) {
    const { maxResults = 50 } = options;

    try {
      console.log(`\n🚀 Step 2 — Découverte pour: ${project.name}`);

      // 2.0 Nettoyage
      console.log(`\n🧹 ÉTAPE 2.0 — Nettoyage`);
      const cleaned = await this._cleanupFalsePositives(project._id);
      console.log(`   → ${cleaned} supprimé(s)`);

      // 2.1 DuckDuckGo
      const queriesToSearch = project.searchQueries?.length > 0
        ? project.searchQueries : project.keywords;
      console.log(`\n📡 ÉTAPE 2.1 — ${queriesToSearch.length} queries DuckDuckGo`);
      const rawResults = await searchService.search(queriesToSearch, project.targetCountry, 100);
      if (rawResults.length === 0) throw new Error('Aucun résultat trouvé');
      console.log(`📊 ${rawResults.length} résultats bruts`);

      // 2.2 Séparation
      console.log(`\n🔀 ÉTAPE 2.2 — Tri TypeA / TypeB`);
      const { typeA, typeB } = this._separateResults(rawResults);
      console.log(`   TypeA: ${typeA.length} | TypeB: ${typeB.length}`);

      // 2.3 Scraping footers
      console.log(`\n🌐 ÉTAPE 2.3 — Scraping footers`);
      const footerLinks = await this._scrapeFooters(typeB.slice(0, 25));
      console.log(`   ${footerLinks.length} liens sociaux extraits`);

      // 2.4 Combinaison simple (sans fusion — fusion faite dans _saveCompetitors)
      console.log(`\n🔗 ÉTAPE 2.4 — Combinaison`);
      const allCompetitors = this._combineResults(typeA, typeB, footerLinks);
      console.log(`   ${allCompetitors.length} entrées brutes`);

      // 2.5 Filtrage
      console.log(`\n🧹 ÉTAPE 2.5 — Filtrage`);
      const filtered = this._filterByRelevance(allCompetitors);
      console.log(`   ${filtered.length} après filtrage`);

      // 2.6 Sauvegarde avec fusion doublons
      console.log(`\n💾 ÉTAPE 2.6 — Sauvegarde + fusion doublons`);
      const saved = await this._saveCompetitors(filtered.slice(0, maxResults), project._id);
      console.log(`   ✅ ${saved.length} nouveaux sauvegardés`);

      const totalCount = await Competitor.countDocuments({ projectId: project._id });
      await Project.findByIdAndUpdate(project._id, {
        competitorsCount: totalCount,
        pipelineStatus  : 'step2_complete',
      });
      console.log(`   ✅ step2_complete (total: ${totalCount})`);
      console.log(`\n📋 SUITE → POST /api/competitors/project/${project._id}/inject-known`);

      return saved;

    } catch (error) {
      console.error('❌ Erreur:', error.message);
      await Project.findByIdAndUpdate(project._id, { pipelineStatus: 'step2_discovery' }).catch(() => {});
      throw error;
    }
  }

  // ═══════════════════════════════════════════════════════
  // INJECTION MANUELLE — après analyse
  // ═══════════════════════════════════════════════════════
  async injectKnownHotels(projectId) {
    console.log(`\n📌 Injection des 15 hôtels vérifiés...`);
    let injected = 0, enriched = 0, skipped = 0;

    for (const comp of KNOWN_COMPETITORS_HOTELS) {
      try {
        const igUsername = this._extractUsernameFromUrl(comp.instagram, 'instagram');
        const fbUsername = this._extractUsernameFromUrl(comp.facebook,  'facebook');

        const orConditions = [];
        if (comp.website) orConditions.push({ website: comp.website });
        if (igUsername)   orConditions.push({ 'socialMedia.instagram.username': igUsername });
        if (fbUsername)   orConditions.push({ 'socialMedia.facebook.username':  fbUsername });
        if (orConditions.length === 0) continue;

        const existing = await Competitor.findOne({ projectId, $or: orConditions });

        if (existing) {
          let updated = false;
          if (!existing.socialMedia.instagram.url && comp.instagram) {
            existing.socialMedia.instagram.url      = comp.instagram;
            existing.socialMedia.instagram.username = igUsername;
            existing.socialMedia.instagram.verified = true;
            updated = true;
          }
          if (!existing.socialMedia.facebook.url && comp.facebook) {
            existing.socialMedia.facebook.url      = comp.facebook;
            existing.socialMedia.facebook.username = fbUsername;
            existing.socialMedia.facebook.verified = true;
            updated = true;
          }
          if (!existing.website && comp.website) { existing.website = comp.website; updated = true; }
          if (existing.classificationMaturity !== 'leader' && comp.maturity === 'leader') {
            existing.classificationMaturity = 'leader';
            existing.classification         = 'leader';
            updated = true;
          }
          if (updated) { await existing.save(); enriched++; console.log(`   🔄 Enrichi (${comp.maturity}): ${comp.companyName}`); }
          else { skipped++; console.log(`   ⏭️  Complet: ${comp.companyName}`); }
          continue;
        }

        await new Competitor({
          projectId,
          companyName            : comp.companyName,
          website                : comp.website || '',
          description            : `Hôtel Tunisie — ${comp.companyName}`,
          classificationMaturity : (comp.maturity === 'leader') ? 'leader' : 'startup',
          classification         : (comp.maturity === 'leader') ? 'leader' : 'startup',
          socialMedia: {
            instagram: { url: comp.instagram || '', username: igUsername, verified: true },
            facebook : { url: comp.facebook  || '', username: fbUsername, verified: true },
            linkedin : { url: '', username: '', verified: false },
            tiktok   : { url: '', username: '', verified: false },
          },
          classificationScore: 0,
          isManuallyAdded    : true,
          discoveredAt       : new Date(),
        }).save();

        injected++;
        console.log(`   ✅ Injecté (${comp.maturity}): ${comp.companyName}`);

      } catch (err) {
        console.warn(`   ⚠️ ${comp.companyName}: ${err.message}`);
      }
    }

    const totalCount = await Competitor.countDocuments({ projectId });
    await Project.findByIdAndUpdate(projectId, { competitorsCount: totalCount });
    console.log(`   → ${injected} injectés | ${enriched} enrichis | ${skipped} complets | total: ${totalCount}`);
    return { injected, enriched, skipped, total: totalCount };
  }

  // ─── 2.2 — Séparer résultats ──────────────────────────────────────────────
  _separateResults(rawResults) {
    const typeA = [];
    const typeB = [];

    for (const result of rawResults) {
      const domain = (result.domain || '').toLowerCase();
      const url    = (result.url    || '').toLowerCase();

      if (this._isExcludedDomain(domain)) continue;

      if (domain.includes('instagram.com')) {
        if (!this._isFakeSocialLink(url) && this._isValidProfileUrl(url, 'instagram')) {
          typeA.push({ ...result, socialType: 'instagram', socialUrl: result.url,
            username: this._extractUsernameFromUrl(result.url, 'instagram') });
        }
        continue;
      }

      if (domain.includes('facebook.com')) {
        if (!this._isFakeSocialLink(url) && this._isValidProfileUrl(url, 'facebook')) {
          typeA.push({ ...result, socialType: 'facebook', socialUrl: result.url,
            username: this._extractUsernameFromUrl(result.url, 'facebook') });
        }
        continue;
      }

      typeB.push(result);
    }

    return { typeA, typeB };
  }

  _isValidProfileUrl(url, platform) {
    try {
      const parsed   = new URL(url);
      const segments = parsed.pathname.split('/').filter(s => s.length > 0);

      if (platform === 'instagram') {
        if (segments.length !== 1) return false;
        return /^[A-Za-z0-9_.]{1,30}$/.test(segments[0]);
      }

      if (platform === 'facebook') {
        if (segments[0] === 'people')                            return false;
        if (segments.length === 1 && /^\d+$/.test(segments[0])) return false;
        if (parsed.pathname.includes('profile.php'))             return false;
        if (parsed.pathname.includes('photo'))                   return false;
        if (parsed.pathname.includes('group'))                   return false;
        if (parsed.search.includes('fbid'))                      return false;
        if (parsed.pathname.includes('reels'))                   return false;
        return true;
      }

      return true;
    } catch { return false; }
  }

  // ─── 2.3 — Scraping footers ───────────────────────────────────────────────
  async _scrapeFooters(websites) {
    const footerLinks = [];
    const browser = await chromium.launch({
      headless: true,
      args    : ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
    });
    const context = await browser.newContext({ userAgent: USER_AGENTS[0], locale: 'fr-FR', viewport: { width: 1920, height: 1080 } });

    try {
      for (const site of websites) {
        try {
          console.log(`   🌐 ${site.domain}`);
          const links = await this._extractSocialFromPage(context, site.url);
          if (links.instagram || links.facebook) {
            footerLinks.push({ website: site.url, domain: site.domain, title: site.title, snippet: site.snippet, instagram: links.instagram, facebook: links.facebook });
            console.log(`      ✅ IG:${links.instagram ? '✓' : '✗'} FB:${links.facebook ? '✓' : '✗'}`);
          } else {
            console.log(`      ⚠️  Aucun lien`);
          }
          await this._sleep(1500);
        } catch (err) { console.warn(`      ❌ ${err.message}`); }
      }
    } finally { await browser.close(); }

    return footerLinks;
  }

  async _extractSocialFromPage(context, url) {
    const page = await context.newPage();
    try {
      await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 15000 });
      await page.waitForTimeout(2000);
      return await page.evaluate(() => {
        const links = Array.from(document.querySelectorAll('a[href]')).map(a => a.href).filter(h => h?.startsWith('http'));
        let instagram = '', facebook = '';
        for (const link of links) {
          const l = link.toLowerCase();
          if (!instagram && l.includes('instagram.com/') && !l.includes('/p/') && !l.includes('/reel/') && !l.includes('/explore') && !l.includes('/tags/') && !l.includes('/accounts/') && !l.includes('/popular/') && !l.includes('/stories/') && !l.includes('sharer') && !l.includes('share') && !l.includes('login')) instagram = link;
          if (!facebook  && l.includes('facebook.com/')  && !l.includes('sharer') && !l.includes('share') && !l.includes('login') && !l.includes('signup') && !l.includes('/groups/') && !l.includes('/events/') && !l.includes('/watch') && !l.includes('/people/') && !l.includes('/posts/') && !l.includes('/photos/') && !l.includes('/photo/') && !l.includes('fbid') && !l.includes('/videos/') && !l.includes('/shop_tab/') && !l.includes('/reels/') && !l.includes('group.php') && !l.includes('profile.php')) facebook = link;
        }
        return { instagram, facebook };
      });
    } catch { return { instagram: '', facebook: '' }; }
    finally { await page.close(); }
  }

  // ─── 2.4 — Combinaison simple (pas de fusion ici) ─────────────────────────
  _combineResults(typeA, typeB, footerLinks) {
    const results = [];

    // TypeA : chaque lien social = 1 entrée
    for (const item of typeA) {
      results.push({
        companyName: this._extractCompanyNameFromSocial(item),
        website    : '',
        description: item.snippet || '',
        instagram  : item.socialType === 'instagram' ? item.socialUrl : '',
        facebook   : item.socialType === 'facebook'  ? item.socialUrl : '',
        igUsername : item.socialType === 'instagram' ? item.username : '',
        fbUsername : item.socialType === 'facebook'  ? item.username : '',
        source     : 'typeA',
      });
    }

    // Footer links
    for (const item of footerLinks) {
      results.push({
        companyName: extractCompanyName(item.title, item.domain),
        website    : item.website,
        description: item.snippet || '',
        instagram  : item.instagram || '',
        facebook   : item.facebook  || '',
        igUsername : this._extractUsernameFromUrl(item.instagram, 'instagram'),
        fbUsername : this._extractUsernameFromUrl(item.facebook,  'facebook'),
        source     : 'typeB',
      });
    }

    return results;
  }

  // ─── 2.5 — Filtrage qualité ───────────────────────────────────────────────
  _filterByRelevance(competitors) {
    return competitors.filter(comp => {

      const hasIG = !!(comp.instagram);
      const hasFB = !!(comp.facebook);
      if (!hasIG && !hasFB) { console.log(`   🚫 Rejeté (pas de social): ${comp.companyName}`); return false; }

      if (comp.website) {
        try {
          const domain = new URL(comp.website).hostname.replace('www.', '').toLowerCase();
          if (this._isExcludedDomain(domain)) { console.log(`   🚫 Rejeté (domaine exclu): ${comp.companyName}`); return false; }
        } catch {}
        const urlLower = comp.website.toLowerCase();
        if (['/blog/', '/article/', '/news/', '/top-', '/best-', '/guide-', '/forum/', '/tag/'].some(p => urlLower.includes(p))) {
          console.log(`   🚫 Rejeté (URL blog): ${comp.companyName}`); return false;
        }
      }

      // Rejeter comptes globaux (pas locaux Tunisie)
      const suspiciousIG = ['wegoarabia', 'bookingcom', 'tripadvisor', 'movenpickhotels'];
      if (comp.igUsername && suspiciousIG.some(s => comp.igUsername.toLowerCase().includes(s))) {
        console.log(`   🚫 Rejeté (compte global @${comp.igUsername}): ${comp.companyName}`); return false;
      }

      if (comp.description) {
        const desc      = comp.description;
        const descLower = desc.toLowerCase();

        // Followers IG < MIN
        const followersMatch = desc.match(/([\d,]+[KkMm]?)\s*Followers/i);
        if (followersMatch && comp.instagram) {
          const followers = this._parseCount(followersMatch[1]);
          if (followers < MIN_FOLLOWERS) {
            console.log(`   🚫 Rejeté (${followers} followers < ${MIN_FOLLOWERS}): ${comp.companyName}`); return false;
          }
        }

        // Likes FB < MIN (si FB only)
        if (comp.facebook && !comp.instagram) {
          const fbLikesMatch = desc.match(/([\d,]+)\s*likes/i);
          if (fbLikesMatch) {
            const likes = parseInt(fbLikesMatch[1].replace(/,/g, ''));
            if (likes < MIN_FB_LIKES) {
              console.log(`   🚫 Rejeté (${likes} FB likes < ${MIN_FB_LIKES}): ${comp.companyName}`); return false;
            }
          }
        }

        // 0 posts
        const postsMatch = desc.match(/,\s*(\d+)\s*Posts/i);
        if (postsMatch && parseInt(postsMatch[1]) === 0) {
          console.log(`   🚫 Rejeté (0 posts): ${comp.companyName}`); return false;
        }

        // Spam following
        const followMatch = desc.match(/([\d,]+)\s*Followers,\s*([\d,]+)\s*Following/i);
        if (followMatch) {
          const followers = parseInt(followMatch[1].replace(/,/g, ''));
          const following = parseInt(followMatch[2].replace(/,/g, ''));
          if (following > followers * 3 && followers < 5000) {
            console.log(`   🚫 Rejeté (spam following): ${comp.companyName}`); return false;
          }
        }

        // Agrégateurs
        if (['comparez les prix', 'best hotel deals', 'compare prices', 'book hotels', 'احجز'].some(p => descLower.includes(p))) {
          console.log(`   🚫 Rejeté (agrégateur): ${comp.companyName}`); return false;
        }

        // Agences
        if (['agence de voyage', 'tour operator', 'voyages organisés'].some(p => descLower.includes(p)) && !descLower.includes('chambre') && !descLower.includes('hôtel ')) {
          console.log(`   🚫 Rejeté (agence): ${comp.companyName}`); return false;
        }

        // Maisons d'hôtes
        const nameAndDesc = `${comp.companyName} ${descLower}`;
        if (['maison d\'hôte', 'maison hote', 'gîte', 'riad', 'chambre d\'hôte', 'homestay'].some(p => nameAndDesc.toLowerCase().includes(p))) {
          console.log(`   🚫 Rejeté (maison d'hôtes): ${comp.companyName}`); return false;
        }

        // Doit être un hôtel
        const HOTEL_INDICATORS = ['hotel', 'hôtel', 'resort', 'palace', 'spa', 'thalasso', 'hilton', 'marriott', 'movenpick', 'sheraton', 'radisson', 'iberostar', 'hasdrubal', 'anantara', 'four seasons', 'el mouradi', 'chambre', 'suite', 'piscine', 'فندق', 'منتجع'];
        if (!HOTEL_INDICATORS.some(p => nameAndDesc.toLowerCase().includes(p))) {
          console.log(`   🚫 Rejeté (pas un hôtel): ${comp.companyName}`); return false;
        }
      }

      return true;
    });
  }

  // ─── 2.6 — Sauvegarde avec FUSION DOUBLONS IG+FB ─────────────────────────
  async _saveCompetitors(competitors, projectId) {
    const saved = [];

    for (const comp of competitors) {
      try {
        const igUsername = comp.igUsername || this._extractUsernameFromUrl(comp.instagram, 'instagram');
        const fbUsername = comp.fbUsername || this._extractUsernameFromUrl(comp.facebook,  'facebook');

        // ✅ Résoudre le canonical IG via SOCIAL_SYNONYMS
        const igCanonical = igUsername ? (SOCIAL_SYNONYMS[igUsername.toLowerCase()] || igUsername) : '';
        const fbCanonical = fbUsername ? (SOCIAL_SYNONYMS[fbUsername.toLowerCase()] || '') : '';

        // ✅ Construire les conditions de recherche incluant les synonymes
        const orConditions = [];
        if (igCanonical) orConditions.push({ 'socialMedia.instagram.username': igCanonical });
        if (igUsername && igUsername !== igCanonical) orConditions.push({ 'socialMedia.instagram.username': igUsername });
        if (fbCanonical) orConditions.push({ 'socialMedia.instagram.username': fbCanonical });
        if (fbUsername)  orConditions.push({ 'socialMedia.facebook.username':  fbUsername  });
        if (comp.website) orConditions.push({ website: comp.website });
        if (orConditions.length === 0) orConditions.push({ companyName: comp.companyName });

        const existing = await Competitor.findOne({ projectId, $or: orConditions });

        if (existing) {
          // Enrichir si des champs manquent
          let updated = false;
          if (!existing.socialMedia.instagram.url && comp.instagram) {
            existing.socialMedia.instagram.url      = comp.instagram;
            existing.socialMedia.instagram.username = igCanonical || igUsername;
            updated = true;
          }
          if (!existing.socialMedia.facebook.url && comp.facebook) {
            existing.socialMedia.facebook.url      = comp.facebook;
            existing.socialMedia.facebook.username = fbUsername;
            updated = true;
          }
          if (!existing.website && comp.website) { existing.website = comp.website; updated = true; }
          if (updated) { await existing.save(); console.log(`   🔄 Fusionné/enrichi: ${existing.companyName}`); }
          else console.log(`   ⏭️  Existe: ${comp.companyName}`);
          continue;
        }

        // Créer nouveau concurrent
        const competitor = new Competitor({
          projectId,
          companyName            : comp.companyName || 'Inconnu',
          website                : comp.website || '',
          description            : (comp.description || '').substring(0, 900),
          classificationMaturity : 'startup',
          classification         : 'startup',
          socialMedia: {
            instagram: { url: comp.instagram || '', username: igCanonical || igUsername, verified: false },
            facebook : { url: comp.facebook  || '', username: fbUsername,                verified: false },
            linkedin : { url: '', username: '', verified: false },
            tiktok   : { url: '', username: '', verified: false },
          },
          classificationScore: 0,
          isManuallyAdded    : false,
          discoveredAt       : new Date(),
        });

        await competitor.save();
        saved.push(competitor);

        console.log(`   ✅ ${comp.companyName} (IG:${comp.instagram ? '✓' : '✗'} FB:${comp.facebook ? '✓' : '✗'})`);

      } catch (err) { console.error(`   ❌ ${comp.companyName}: ${err.message}`); }
    }

    return saved;
  }

  // ─── Cleanup ──────────────────────────────────────────────────────────────
  async _cleanupFalsePositives(projectId) {
    const competitors = await Competitor.find({ projectId, isManuallyAdded: false });
    let removed = 0;

    for (const comp of competitors) {
      let shouldRemove = false, reason = '';

      if (comp.website) {
        try {
          const domain = new URL(comp.website).hostname.replace('www.', '').toLowerCase();
          if (this._isExcludedDomain(domain)) { shouldRemove = true; reason = `domaine exclu`; }
        } catch {}
      }

      if (!shouldRemove && comp.socialMedia?.instagram?.username) {
        const suspicious = ['wegoarabia', 'bookingcom', 'tripadvisor', 'movenpickhotels'];
        if (suspicious.some(s => comp.socialMedia.instagram.username.toLowerCase().includes(s))) {
          shouldRemove = true; reason = `username agrégateur/global`;
        }
      }

      // Nettoyer URLs FB invalides
      if (!shouldRemove && comp.socialMedia?.facebook?.url) {
        const fbUrl = comp.socialMedia.facebook.url.toLowerCase();
        if (['photo/?fbid', '/photo/', 'group.php', '/reels/'].some(p => fbUrl.includes(p))) {
          if (comp.socialMedia.instagram.url) {
            comp.socialMedia.facebook.url = '';
            comp.socialMedia.facebook.username = '';
            await comp.save();
            console.log(`   🧹 FB nettoyé: ${comp.companyName}`);
          } else {
            shouldRemove = true; reason = `URL FB invalide`;
          }
        }
      }

      // Rejeter @movenpick_gammarth (compte non officiel)
      if (!shouldRemove && comp.socialMedia?.instagram?.username === 'movenpick_gammarth') {
        shouldRemove = true; reason = `compte non officiel @movenpick_gammarth`;
      }

      if (shouldRemove) {
        await Competitor.deleteOne({ _id: comp._id });
        removed++;
        console.log(`   🗑️  Supprimé (${reason}): ${comp.companyName}`);
      }
    }

    return removed;
  }

  async cleanupFalsePositives(projectId) { return this._cleanupFalsePositives(projectId); }

  // ─── Helpers ──────────────────────────────────────────────────────────────
  _isExcludedDomain(domain) {
    const lower = domain.toLowerCase();
    for (const ex of EXCLUDED_DOMAINS) { if (lower === ex || lower.endsWith('.' + ex)) return true; }
    return false;
  }

  _isFakeSocialLink(url) { return FAKE_SOCIAL_PATTERNS.some(p => url.toLowerCase().includes(p)); }

  _extractUsernameFromUrl(url, platform) {
    if (!url) return '';
    try {
      const parsed  = new URL(url);
      const ignored = ['company', 'in', 'pub', 'pages', 'groups', 'channel', 'user', 'home', 'about', 'posts', 'search', 'hashtag', 'explore', 'profile.php', 'p', 'reel', 'reels', 'stories', 'people', 'popular', 'photos', 'videos', 'shop_tab', 'photo'];
      const segments = parsed.pathname.split('/').filter(s => s.length > 1);
      const username = segments.find(s => !ignored.includes(s.toLowerCase()) && !/^\d+$/.test(s)) || '';
      return username.replace(/^@/, '');
    } catch { return ''; }
  }

  _extractCompanyNameFromSocial(item) {
    const title = item.title || '';
    const m1 = title.match(/^(.+?)\s*\(/);
    if (m1) return m1[1].trim();
    const m2 = title.match(/^(.+?)\s*[-|–]/);
    if (m2) return m2[1].trim();
    if (item.username) return item.username.replace(/[._-]/g, ' ').split(' ').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
    return title.split(' ').slice(0, 3).join(' ') || 'Inconnu';
  }

  _parseCount(str) {
    if (!str) return 0;
    const clean = str.replace(/,/g, '').trim();
    if (/[Mm]$/.test(clean)) return Math.round(parseFloat(clean) * 1_000_000);
    if (/[Kk]$/.test(clean)) return Math.round(parseFloat(clean) * 1_000);
    return parseInt(clean) || 0;
  }

  _sleep(ms) { return new Promise(r => setTimeout(r, ms)); }
}

module.exports = new DiscoverService();