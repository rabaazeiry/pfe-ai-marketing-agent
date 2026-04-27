// backend/src/services/marketResearch.service.js
// Step 2 — Market Summary generation (Ollama + Llama 3.3, no RAG, MongoDB-only)
//
// Inputs de vérité :
//   projects        → _id, industry, country (fallback targetCountry), businessIdea
//   competitors     → _id, companyName, marketPosition, geographicScope,
//                     classification, metrics.totalFollowers, metrics.avgEngagementRate
//   socialanalyses  → competitorId, followers, postsPerWeek, engagementRate,
//                     topHashtags, contentDistribution, bestDays, bestHours
//
// Notes :
//   • `marketPosition` et `geographicScope` existent dans MongoDB via bulkWrite
//     mais ne sont PAS déclarés dans le schéma Mongoose actuel.
//     On lit les concurrents avec `.lean()` pour récupérer les champs bruts.
//   • `leaderCount` / `startupCount`  ← marketPosition
//   • `localCount`  / `internationalCount` ← geographicScope
//     Les deux axes sont indépendants, pas collapsés dans `classification`.

const Competitor     = require('../models/Competitor.model');
const SocialAnalysis = require('../models/SocialAnalysis.model');
const MarketResearch = require('../models/MarketResearch.model');
const Project        = require('../models/Project.model');
const env            = require('../config/env');

const MAX_COMPETITORS_IN_CONTEXT = 10;
const MAX_SOCIALS_PER_COMPETITOR = 3;
const MAX_HASHTAGS               = 10;
const MIN_SUMMARY_CHARS          = 200;

const COUNTRY_NAMES = {
  TN: 'Tunisie', MA: 'Maroc', DZ: 'Algérie', FR: 'France', EG: 'Égypte',
  SN: 'Sénégal', US: 'États-Unis', UK: 'Royaume-Uni', DE: 'Allemagne',
  IT: 'Italie',  ES: 'Espagne',   CA: 'Canada',       AE: 'Émirats Arabes Unis'
};

class MarketResearchService {

  // ═══════════════════════════════════════════════════════════
  // ENTRÉE PUBLIQUE
  // ═══════════════════════════════════════════════════════════

  async generateMarketSummary(projectId) {
    console.log(`\n📊 Market Summary — projet ${projectId}`);

    const project = await Project.findById(projectId);
    if (!project) throw new Error('Projet non trouvé');

    // ✅ lean() : récupère les champs bruts (marketPosition, geographicScope inclus)
    const competitors = await Competitor
      .find({ projectId, isActive: true })
      .sort({ 'metrics.totalFollowers': -1 })
      .limit(MAX_COMPETITORS_IN_CONTEXT)
      .lean();

    if (!competitors.length) {
      const err = new Error('Aucun concurrent actif pour ce projet');
      err.code = 'NO_COMPETITORS';
      throw err;
    }

    const competitorIds = competitors.map(c => c._id);
    const socials = await SocialAnalysis
      .find({ competitorId: { $in: competitorIds }, scrapingStatus: 'completed' })
      .lean();

    const socialsByCompetitor = this._groupBy(socials, s => String(s.competitorId));

    const mr = await MarketResearch.findOrCreate(projectId);
    mr.status = 'in_progress';
    await mr.save();

    try {
      const countryLabel = this._resolveCountryLabel(project);
      const stats        = this._calculateStats(competitors, socials);
      const contentAgg   = this._aggregateContent(socials);
      const context      = this._buildContext(project, countryLabel, competitors, socialsByCompetitor, stats, contentAgg);

      console.log(`   📋 ${competitors.length} concurrents, ${socials.length} analyses sociales`);
      console.log(`   📋 Overview: leader=${stats.leaderCount} startup=${stats.startupCount} local=${stats.localCount} intl=${stats.internationalCount}`);
      console.log(`   🤖 Génération section par section (${env.OLLAMA_MODEL})...`);

      // Architecture : backend = source de vérité (chiffres, noms, classifications).
      // LLM = rédige UNIQUEMENT une interprétation qualitative par section (1-2 phrases,
      // aucun chiffre, aucun nom de marque). Si la réponse LLM échoue la validation,
      // on garde la phrase factuelle déterministe seule — le document reste valide.
      let { summary, llmOk, llmTotal } = await this._buildValidatedSummary(context, competitors);
      console.log(`   📝 Summary assemblé : ${summary.length} chars, ${llmOk}/${llmTotal} interprétations LLM validées`);

      let final = this._validateFinal(summary, context, competitors);
      if (!final.ok) {
        console.warn(`   ⚠️  Validation finale échouée : ${final.reasons.join(' ; ')}`);
        console.warn(`   🛟 Bascule sur le Market Summary 100 % déterministe`);
        summary = this._buildDeterministicSummary(context, competitors);
        final   = this._validateFinal(summary, context, competitors);
        if (!final.ok) {
          throw new Error(`Validation finale impossible même en mode déterministe : ${final.reasons.join(' ; ')}`);
        }
      }

      if (summary.length < MIN_SUMMARY_CHARS) {
        throw new Error(`Market Summary trop court (${summary.length} chars)`);
      }

      await mr.updateMarketSummary(summary, competitors.length);
      await mr.updateMarketOverview(stats);
      mr.classificationSummary = this._buildClassificationSummary(competitors);
      mr.aiModelUsed           = env.OLLAMA_MODEL;
      await mr.markAsCompleted();

      console.log(`   ✅ Market Summary généré (${summary.length} chars)`);
      return mr;

    } catch (error) {
      console.error(`   ❌ Échec Market Summary: ${error.message}`);
      await mr.markAsFailed(error.message);
      throw error;
    }
  }

  // ─── Alias rétro-compatible pour le controller existant ───
  async generateMarketResearch(projectId) {
    return this.generateMarketSummary(projectId);
  }

  // ═══════════════════════════════════════════════════════════
  // AGRÉGATION
  // ═══════════════════════════════════════════════════════════

  _resolveCountryLabel(project) {
    if (project.country && project.country.trim()) return project.country.trim();
    const iso = (project.targetCountry || '').toUpperCase();
    return COUNTRY_NAMES[iso] || iso || 'Non précisé';
  }

  // Rend une formulation française naturelle du secteur, ex.:
  //   "Patisserie"        → "secteur de la pâtisserie"
  //   "Hotels"            → "secteur hôtelier"
  //   "Fashion & Retail"  → "secteur de la mode et du retail"
  _renderIndustryLabel(industry) {
    if (!industry) return 'secteur non précisé';
    const key = industry
      .toLowerCase()
      .normalize('NFD').replace(/[̀-ͯ]/g, '')
      .trim();

    const map = [
      [/patisser/,            'secteur de la pâtisserie'],
      [/boulanger/,           'secteur de la boulangerie'],
      [/hotel|hospitality/,   'secteur hôtelier'],
      [/restaur/,             'secteur de la restauration'],
      [/beaut|cosmet/,        'secteur de la beauté et des cosmétiques'],
      [/fashion|mode|retail/, 'secteur de la mode et du retail'],
      [/sant|health|pharma/,  'secteur de la santé'],
      [/tech|software|saas/,  'secteur technologique'],
      [/educ|formation/,      'secteur de l\'éducation'],
      [/immobil|real estate/, 'secteur immobilier'],
      [/tour|travel/,         'secteur du tourisme'],
      [/aliment|food/,        'secteur de l\'alimentation']
    ];
    for (const [re, label] of map) if (re.test(key)) return label;
    return `secteur « ${industry.trim()} »`;
  }

  // Rejette les hashtags manifestement faibles / malformés.
  _isValidHashtag(h) {
    if (typeof h !== 'string') return false;
    const tag = h.replace(/^#/, '').trim();
    if (tag.length < 3 || tag.length > 30)                  return false;
    if (!/[A-Za-zÀ-ÿ]/.test(tag))                           return false; // au moins une lettre
    if (!/^[A-Za-z0-9_À-ſ]+$/.test(tag))          return false; // caractères propres
    if (/^(ha+|lo+l|xd+|test+)$/i.test(tag))                return false;
    return true;
  }

  // Agrégation industry-level : compte la fréquence réelle sur TOUTES les analyses
  // sociales pour éviter que le LLM cherry-pick une valeur aberrante d'un seul compte.
  _aggregateContent(socials) {
    const dayCount  = new Map();
    const hourCount = new Map();
    const tagCount  = new Map();
    const formats   = { photo: 0, video: 0, reel: 0, carousel: 0, story: 0 };

    let postsPerWeekSum = 0, postsPerWeekN = 0;
    let engRateSum      = 0, engRateN      = 0;

    for (const s of socials) {
      for (const d of (s.bestDays || []))  dayCount.set(d,  (dayCount.get(d)  || 0) + 1);
      for (const h of (s.bestHours || [])) hourCount.set(h, (hourCount.get(h) || 0) + 1);
      for (const raw of (s.topHashtags || [])) {
        if (!this._isValidHashtag(raw)) continue;
        const tag = raw.replace(/^#/, '').trim().toLowerCase();
        tagCount.set(tag, (tagCount.get(tag) || 0) + 1);
      }
      if (s.contentDistribution) {
        for (const k of Object.keys(formats)) {
          formats[k] += Number(s.contentDistribution[k] || 0);
        }
      }
      if (s.postsPerWeek)   { postsPerWeekSum += s.postsPerWeek;   postsPerWeekN++; }
      if (s.engagementRate) { engRateSum      += s.engagementRate; engRateN++;      }
    }

    const topN = (map, n) => [...map.entries()]
      .sort((a, b) => b[1] - a[1])
      .slice(0, n)
      .map(([value, count]) => ({ value, count }));

    const topBestDays  = topN(dayCount,  3);
    const topBestHours = topN(hourCount, 3);
    const topHashtags  = topN(tagCount, 10);

    const totalFormats = Object.values(formats).reduce((a, b) => a + b, 0);
    const contentMix = totalFormats > 0
      ? Object.fromEntries(
          Object.entries(formats)
            .filter(([, v]) => v > 0)
            .map(([k, v]) => [k, Math.round((v / totalFormats) * 100)])
        )
      : {};

    const avgPostsPerWeek   = postsPerWeekN ? Number((postsPerWeekSum / postsPerWeekN).toFixed(2)) : 0;
    const avgEngagementRate = engRateN      ? Number((engRateSum      / engRateN).toFixed(2))      : 0;

    return { topBestDays, topBestHours, topHashtags, contentMix, avgPostsPerWeek, avgEngagementRate };
  }

  _resolvePosition(c) {
    if (c.marketPosition === 'leader' || c.marketPosition === 'startup') {
      return c.marketPosition;
    }
    if (c.classificationMaturity === 'leader' || c.classificationMaturity === 'startup') {
      return c.classificationMaturity;
    }
    return 'unknown';
  }

  _resolveScope(c) {
    if (c.geographicScope === 'local' || c.geographicScope === 'international') {
      return c.geographicScope;
    }
    if (c.classification === 'local' || c.classification === 'international') {
      return c.classification;
    }
    return 'unknown';
  }

  _calculateStats(competitors, socials) {
    let leaderCount = 0, startupCount = 0, localCount = 0, internationalCount = 0;

    for (const c of competitors) {
      const pos   = this._resolvePosition(c);
      const scope = this._resolveScope(c);
      if (pos   === 'leader')        leaderCount++;
      if (pos   === 'startup')       startupCount++;
      if (scope === 'local')         localCount++;
      if (scope === 'international') internationalCount++;
    }

    // Plateforme dominante : celle qui compte le plus d'analyses sociales actives
    const platformCounts = { instagram: 0, facebook: 0, linkedin: 0, tiktok: 0 };
    for (const s of socials) {
      if (platformCounts[s.platform] !== undefined) platformCounts[s.platform]++;
    }
    const dominantPlatform = Object.entries(platformCounts)
      .sort((a, b) => b[1] - a[1])[0][1] > 0
        ? Object.entries(platformCounts).sort((a, b) => b[1] - a[1])[0][0]
        : '';

    // Maturité marché (heuristique simple)
    let marketMaturity = 'unknown';
    if (internationalCount >= 2)  marketMaturity = 'mature';
    else if (leaderCount    >= 2) marketMaturity = 'growing';
    else if (startupCount   >= 2) marketMaturity = 'emerging';

    return {
      totalCompetitors: competitors.length,
      leaderCount, startupCount, localCount, internationalCount,
      dominantPlatform, marketMaturity
    };
  }

  _buildClassificationSummary(competitors) {
    // Info secondaire : on expose les 4 axes (leader/startup + local/international)
    // comme buckets simples, utile pour l'UI mais pas source de vérité.
    const buckets = [
      { classification: 'leader',        filter: c => this._resolvePosition(c) === 'leader' },
      { classification: 'startup',       filter: c => this._resolvePosition(c) === 'startup' },
      { classification: 'local',         filter: c => this._resolveScope(c)    === 'local' },
      { classification: 'international', filter: c => this._resolveScope(c)    === 'international' }
    ];
    return buckets
      .map(b => {
        const list = competitors.filter(b.filter);
        return {
          classification: b.classification,
          count         : list.length,
          competitors   : list.map(c => c.companyName)
        };
      })
      .filter(b => b.count > 0);
  }

  // ═══════════════════════════════════════════════════════════
  // CONTEXTE JSON ENVOYÉ AU LLM
  // ═══════════════════════════════════════════════════════════

  _buildContext(project, countryLabel, competitors, socialsByCompetitor, stats, contentAgg) {
    const businessIdea   = (project.businessIdea || '').trim().substring(0, 300);
    const industryRaw    = project.industry || 'Non précisé';
    const industryLabel  = this._renderIndustryLabel(industryRaw);

    const competitorsPayload = competitors.map(c => {
      const competitorSocials = (socialsByCompetitor.get(String(c._id)) || [])
        .sort((a, b) => (b.followers || 0) - (a.followers || 0))
        .slice(0, MAX_SOCIALS_PER_COMPETITOR)
        .map(s => this._socialPayload(s));

      const entry = {
        id            : String(c._id),
        name          : c.companyName,
        marketPosition: this._resolvePosition(c),
        geographicScope: this._resolveScope(c)
      };
      if (c.country)                           entry.country          = c.country;
      if (c.classification)                    entry.classification   = c.classification;
      if (c.metrics && (c.metrics.totalFollowers || c.metrics.avgEngagementRate)) {
        entry.metrics = {};
        if (c.metrics.totalFollowers)    entry.metrics.totalFollowers    = c.metrics.totalFollowers;
        if (c.metrics.avgEngagementRate) entry.metrics.avgEngagementRate = c.metrics.avgEngagementRate;
      }
      if (competitorSocials.length) entry.social = competitorSocials;
      return entry;
    });

    const context = {
      project: {
        projectId    : String(project._id),
        industry     : industryRaw,
        industryLabel,
        country      : countryLabel
      },
      marketStats: {
        totalCompetitors  : stats.totalCompetitors,
        leaderCount       : stats.leaderCount,
        startupCount      : stats.startupCount,
        localCount        : stats.localCount,
        internationalCount: stats.internationalCount,
        dominantPlatform  : stats.dominantPlatform,
        marketMaturity    : stats.marketMaturity,
        avgPostsPerWeek   : contentAgg.avgPostsPerWeek,
        avgEngagementRate : contentAgg.avgEngagementRate,
        topBestDays       : contentAgg.topBestDays,   // [{value,count}] industry-wide
        topBestHours      : contentAgg.topBestHours,  // [{value,count}] industry-wide
        topHashtags       : contentAgg.topHashtags,   // [{value,count}] industry-wide, filtrés
        contentMix        : contentAgg.contentMix     // { photo:%, video:%, reel:%, ... }
      },
      competitors: competitorsPayload
    };

    if (businessIdea) context.project.businessIdea = businessIdea;
    return context;
  }

  _socialPayload(s) {
    const out = { platform: s.platform };
    if (s.followers)      out.followers      = s.followers;
    if (s.postsPerWeek)   out.postsPerWeek   = s.postsPerWeek;
    if (s.engagementRate) out.engagementRate = s.engagementRate;

    // Hashtags filtrés pour retirer typos / tags malformés
    if (Array.isArray(s.topHashtags) && s.topHashtags.length) {
      const clean = s.topHashtags
        .filter(h => this._isValidHashtag(h))
        .slice(0, MAX_HASHTAGS);
      if (clean.length) out.topHashtags = clean;
    }
    if (s.contentDistribution) {
      const cd = s.contentDistribution;
      const nonZero = Object.fromEntries(
        Object.entries(cd).filter(([, v]) => v && v > 0)
      );
      if (Object.keys(nonZero).length) out.contentDistribution = nonZero;
    }
    // ⚠️ bestDays / bestHours NE sont PAS exposés par concurrent : ils seraient
    // cherry-pickés. On ne donne que l'agrégat industry-level dans marketStats.
    return out;
  }

  // ═══════════════════════════════════════════════════════════
  // ARCHITECTURE SECTION-PAR-SECTION
  // Backend calcule tous les chiffres et rédige la phrase factuelle
  // de chaque section. Le LLM ajoute UNIQUEMENT 1-2 phrases
  // d'interprétation qualitative (aucun chiffre, aucun nom).
  // Section 2 (Acteurs clés) est 100 % déterministe.
  // ═══════════════════════════════════════════════════════════

  // Titres EXACTS — assemblés par le backend, le LLM ne les produit jamais.
  _sectionTitles() {
    return [
      "## 1. Vue d'ensemble du marché",
      "## 2. Acteurs clés",
      "## 3. Présence digitale",
      "## 4. Observations principales",
      "## 5. Synthèse"
    ];
  }

  _forbiddenRegex() {
    // Unifié pour l'interprétation LLM ET la validation finale du doc.
    return /(swot|campagne|calendrier\s+(?:éditorial|editorial)|plan\s+de\s+contenu|stratégie|strategie|\bhook\b|\bcaption\b|recommand(?:ation|ons|er|ations)|conclusion)/i;
  }

  _platformLabel(p) {
    return { instagram: 'Instagram', facebook: 'Facebook', linkedin: 'LinkedIn', tiktok: 'TikTok' }[p] || '';
  }

  _maturitySentence(m) {
    return {
      emerging : "Le marché apparaît à un stade émergent.",
      growing  : "Le marché apparaît en croissance.",
      mature   : "Le marché apparaît mature.",
      declining: "Le marché apparaît en déclin."
    }[m] || "La maturité du marché n'est pas clairement établie dans les données.";
  }

  _dayFr(d) {
    const map = { monday: 'lundi', tuesday: 'mardi', wednesday: 'mercredi', thursday: 'jeudi', friday: 'vendredi', saturday: 'samedi', sunday: 'dimanche' };
    if (!d) return '';
    const key = String(d).trim().toLowerCase();
    return map[key] || key;
  }

  _fmtInt(n) {
    if (n == null || !Number.isFinite(Number(n))) return '—';
    return new Intl.NumberFormat('fr-FR').format(Number(n)).replace(/ /g, ' ');
  }

  _fmtNum(n, decimals = 1) {
    if (n == null || !Number.isFinite(Number(n))) return '—';
    return Number(n).toFixed(decimals).replace('.', ',').replace(/,0$/, '');
  }

  _fmtPct(n, decimals = 2) {
    if (n == null || !Number.isFinite(Number(n))) return '—';
    return `${Number(n).toFixed(decimals).replace('.', ',')} %`;
  }

  _plural(n, singular, plural) {
    return Number(n) >= 2 ? plural : singular;
  }

  // ─── Phrases factuelles par section (source de vérité backend) ───────────

  _anchorSection1(context) {
    const s   = context.marketStats;
    const lbl = context.project.industryLabel;
    const cty = context.project.country;
    return (
      `Le ${lbl} en ${cty} compte ${s.totalCompetitors} ${this._plural(s.totalCompetitors, 'concurrent identifié', 'concurrents identifiés')} : ` +
      `${s.leaderCount} ${this._plural(s.leaderCount, 'leader', 'leaders')} et ${s.startupCount} ${this._plural(s.startupCount, 'startup', 'startups')}, ` +
      `dont ${s.localCount} ${this._plural(s.localCount, 'acteur local', 'acteurs locaux')} et ` +
      `${s.internationalCount} ${this._plural(s.internationalCount, 'acteur international', 'acteurs internationaux')}. ` +
      this._maturitySentence(s.marketMaturity)
    );
  }

  _anchorSection3(context) {
    const s        = context.marketStats;
    const platform = this._platformLabel(s.dominantPlatform);
    const platSent = platform
      ? `La plateforme dominante du secteur est ${platform}.`
      : `Aucune plateforme dominante ne se dégage des données.`;

    const freqSent = (s.avgPostsPerWeek && Number(s.avgPostsPerWeek) > 0)
      ? `Les acteurs publient en moyenne ${this._fmtNum(s.avgPostsPerWeek, 1)} ${this._plural(s.avgPostsPerWeek, 'post', 'posts')} par semaine`
      : `La fréquence moyenne de publication n'est pas disponible dans les données`;

    const engSent = (s.avgEngagementRate && Number(s.avgEngagementRate) > 0)
      ? `, avec un engagement moyen de ${this._fmtPct(s.avgEngagementRate, 2)}.`
      : `, et le taux d'engagement moyen n'est pas disponible.`;

    const days  = (s.topBestDays  || []).slice(0, 3).map(d => this._dayFr(d.value)).join(', ');
    const hours = (s.topBestHours || []).slice(0, 3).map(h => `${h.value}h`).join(', ');
    const winSent = (days || hours)
      ? ` Les jours de publication les plus fréquents sont ${days || 'non significatifs'} ; les créneaux horaires majoritaires se situent autour de ${hours || 'non significatives'}.`
      : ` Les fenêtres de publication dominantes ne sont pas significatives dans les données.`;

    return `${platSent} ${freqSent}${engSent}${winSent}`;
  }

  _anchorSection4(context) {
    const s        = context.marketStats;
    const mixArr   = Object.entries(s.contentMix || {}).sort((a, b) => b[1] - a[1]);
    const mixStr   = mixArr.length ? mixArr.map(([k, v]) => `${k} ${v} %`).join(', ') : 'répartition des formats non disponible';
    const hashArr  = (s.topHashtags || []).slice(0, 6).map(h => `#${h.value}`);
    const hashStr  = hashArr.length ? hashArr.join(', ') : 'aucun hashtag dominant identifié';
    return `La répartition des formats publiés dans le secteur est la suivante : ${mixStr}. Les hashtags récurrents observés incluent ${hashStr}.`;
  }

  _anchorSection5(context) {
    const s = context.marketStats;
    let balance;
    if (s.leaderCount > s.startupCount) {
      balance = `une prédominance des leaders (${s.leaderCount}) sur les startups (${s.startupCount})`;
    } else if (s.startupCount > s.leaderCount) {
      balance = `une prédominance des startups (${s.startupCount}) sur les leaders (${s.leaderCount})`;
    } else {
      balance = `un équilibre entre leaders (${s.leaderCount}) et startups (${s.startupCount})`;
    }
    let geo;
    if (s.internationalCount === 0 && s.localCount > 0) {
      geo = `Aucun acteur international n'a été identifié ; la couverture est exclusivement locale (${s.localCount}).`;
    } else if (s.localCount === 0 && s.internationalCount > 0) {
      geo = `Aucun acteur local n'a été identifié ; la couverture est exclusivement internationale (${s.internationalCount}).`;
    } else {
      geo = `La couverture se partage entre ${s.localCount} ${this._plural(s.localCount, 'acteur local', 'acteurs locaux')} et ${s.internationalCount} ${this._plural(s.internationalCount, 'acteur international', 'acteurs internationaux')}.`;
    }
    return `Le secteur présente ${balance}. ${geo}`;
  }

  // ─── Section 2 — 100 % déterministe, jamais touchée par le LLM ───────────

  _buildSection2(competitors) {
    const leaders  = competitors.filter(c => this._resolvePosition(c) === 'leader');
    const startups = competitors.filter(c => this._resolvePosition(c) === 'startup');
    const others   = competitors.filter(c => {
      const p = this._resolvePosition(c);
      return p !== 'leader' && p !== 'startup';
    });

    const fmtLine = (c) => {
      const scope = this._resolveScope(c);
      const scopeLbl = scope === 'local' ? 'local'
                      : scope === 'international' ? 'international'
                      : 'portée non précisée';
      const followers = (c.metrics && c.metrics.totalFollowers)
        ? `${this._fmtInt(c.metrics.totalFollowers)} ${this._plural(c.metrics.totalFollowers, 'abonné', 'abonnés')}`
        : 'abonnés non disponibles';
      const eng = (c.metrics && c.metrics.avgEngagementRate)
        ? `engagement moyen ${this._fmtPct(c.metrics.avgEngagementRate, 2)}`
        : 'engagement non disponible';
      return `- ${c.companyName} — ${scopeLbl}, ${followers}, ${eng}`;
    };

    const lines = [];
    lines.push(`**Leaders (${leaders.length})**`);
    if (leaders.length) {
      for (const c of leaders) lines.push(fmtLine(c));
    } else {
      lines.push('- (aucun leader identifié)');
    }
    lines.push('');
    lines.push(`**Startups (${startups.length})**`);
    if (startups.length) {
      for (const c of startups) lines.push(fmtLine(c));
    } else {
      lines.push('- (aucune startup identifiée)');
    }
    if (others.length) {
      lines.push('');
      lines.push(`**Position non classée (${others.length})**`);
      for (const c of others) lines.push(fmtLine(c));
    }
    return lines.join('\n');
  }

  // ─── Prompt court d'interprétation (LLM, 1-2 phrases qualitatives) ───────

  _buildInterpPrompt(sectionKey, anchor) {
    const focus = {
      section1: "ce que cette structure traduit sur la concentration, la diversité et l'ouverture du marché",
      section3: "ce que ces usages révèlent des habitudes éditoriales du secteur sur les réseaux sociaux",
      section4: "ce que cette répartition de formats et ces hashtags évoquent en termes de thématiques dominantes",
      section5: "ce que cette configuration signale sur la structure concurrentielle du secteur"
    }[sectionKey];

    return `Tu rédiges UNE interprétation qualitative courte qui suivra la phrase factuelle ci-dessous dans une étude de marché.

Phrase factuelle (déjà rédigée par le backend, ne la réécris pas) :
« ${anchor} »

Objectif : en 1 à 2 phrases, commente ${focus}.

RÈGLES STRICTES — toute violation entraîne le rejet de ta réponse :
- 1 à 2 phrases, 25 à 60 mots au total.
- PAS de titre, PAS de "##", PAS de "**", PAS de liste à puces, PAS de guillemets.
- PAS de chiffres, PAS de pourcentages (ils sont déjà dans la phrase factuelle).
- PAS de nom de concurrent, PAS de marque.
- PAS de recommandation, PAS de conseil, PAS de prescription, PAS d'impératif.
- Mots INTERDITS : "stratégie", "campagne", "plan de contenu", "calendrier éditorial", "hook", "caption", "SWOT", "recommandation", "conclusion".
- Français neutre, descriptif, registre professionnel.

Réponds UNIQUEMENT avec le paragraphe d'interprétation. Aucune introduction, aucune formule de politesse, aucun préambule.`;
  }

  _validateInterp(text) {
    if (!text) return { ok: false, reason: 'vide' };
    const t = text.trim();
    if (t.length < 40)  return { ok: false, reason: `trop court (${t.length})` };
    if (t.length > 500) return { ok: false, reason: `trop long (${t.length})` };
    if (/^##|\n##|\*\*/.test(t))        return { ok: false, reason: 'contient du markdown' };
    if (/^\s*[-*•]\s/m.test(t))          return { ok: false, reason: 'contient une liste' };
    if (/\d/.test(t))                    return { ok: false, reason: 'contient un chiffre' };
    if (this._forbiddenRegex().test(t))  return { ok: false, reason: 'contient un mot interdit' };
    return { ok: true, reason: '' };
  }

  // ─── Orchestration : 5 sections, une par une ─────────────────────────────

  async _buildValidatedSummary(context, competitors) {
    const titles = this._sectionTitles();

    const anchors = {
      section1: this._anchorSection1(context),
      section3: this._anchorSection3(context),
      section4: this._anchorSection4(context),
      section5: this._anchorSection5(context)
    };

    const interpKeys = ['section1', 'section3', 'section4', 'section5'];
    const interps    = {};
    let llmOk = 0;
    const llmTotal = interpKeys.length;

    for (const key of interpKeys) {
      const prompt = this._buildInterpPrompt(key, anchors[key]);
      let text = '';
      try {
        text = await this._callOllama(prompt, { timeoutMs: 90000, maxTokens: 180, temperature: 0.2 });
      } catch (e) {
        console.warn(`   ⚠️  ${key} : LLM échec (${e.message}) — fallback anchor only`);
      }
      const v = this._validateInterp(text);
      if (v.ok) {
        interps[key] = text.trim();
        llmOk++;
        console.log(`   ✅ ${key} : interprétation LLM validée (${text.trim().length} chars)`);
      } else {
        interps[key] = '';
        console.log(`   ↩️  ${key} : interprétation rejetée (${v.reason}) — anchor seul`);
      }
    }

    const body2 = this._buildSection2(competitors);

    const join = (anchor, interp) => interp ? `${anchor} ${interp}` : anchor;

    const summary = [
      titles[0], '',
      join(anchors.section1, interps.section1), '',
      titles[1], '',
      body2, '',
      titles[2], '',
      join(anchors.section3, interps.section3), '',
      titles[3], '',
      join(anchors.section4, interps.section4), '',
      titles[4], '',
      join(anchors.section5, interps.section5)
    ].join('\n').trim();

    return { summary, llmOk, llmTotal };
  }

  // ─── Fallback 100 % déterministe (aucun appel LLM) ───────────────────────

  _buildDeterministicSummary(context, competitors) {
    const titles = this._sectionTitles();
    return [
      titles[0], '',
      this._anchorSection1(context), '',
      titles[1], '',
      this._buildSection2(competitors), '',
      titles[2], '',
      this._anchorSection3(context), '',
      titles[3], '',
      this._anchorSection4(context), '',
      titles[4], '',
      this._anchorSection5(context)
    ].join('\n').trim();
  }

  // ─── Validation finale du document assemblé ──────────────────────────────

  _validateFinal(summary, context, competitors) {
    const reasons = [];
    const titles  = this._sectionTitles();

    // 1. 5 titres EXACTS, dans l'ordre, aucun autre header ##.
    const headerLines = summary.split('\n').filter(l => /^##\s/.test(l.trim()));
    if (headerLines.length !== 5) {
      reasons.push(`${headerLines.length} titres ## trouvés (attendu : 5)`);
    } else {
      for (let i = 0; i < 5; i++) {
        if (headerLines[i].trim() !== titles[i]) {
          reasons.push(`titre ${i + 1} = "${headerLines[i].trim()}" ≠ "${titles[i]}"`);
        }
      }
    }

    // 2. Aucun mot interdit dans l'ensemble du document.
    if (this._forbiddenRegex().test(summary)) {
      reasons.push('mot interdit détecté dans le document');
    }

    // 3. Tous les concurrents présents (section 2 déterministe garantit cela,
    //    validation défensive au cas où la section 2 aurait été corrompue).
    for (const c of competitors) {
      if (!summary.includes(c.companyName)) {
        reasons.push(`concurrent absent du document : ${c.companyName}`);
      }
    }

    // 4. Chiffres clés du backend présents quelque part dans le doc.
    const s = context.marketStats;
    const mustNumbers = [
      ['totalCompetitors',   s.totalCompetitors],
      ['leaderCount',        s.leaderCount],
      ['startupCount',       s.startupCount],
      ['localCount',         s.localCount],
      ['internationalCount', s.internationalCount]
    ];
    for (const [label, n] of mustNumbers) {
      if (!new RegExp(`\\b${n}\\b`).test(summary)) {
        reasons.push(`chiffre ${label}=${n} absent du document`);
      }
    }

    return { ok: reasons.length === 0, reasons };
  }

  // ═══════════════════════════════════════════════════════════
  // OLLAMA
  // ═══════════════════════════════════════════════════════════

  async _callOllama(prompt, options = {}) {
    const timeoutMs   = options.timeoutMs   || env.OLLAMA_TIMEOUT_MS;
    const maxTokens   = options.maxTokens   || 1500;
    const temperature = options.temperature != null ? options.temperature : 0.2;

    const controller = new AbortController();
    const timeout    = setTimeout(() => controller.abort(), timeoutMs);

    const startedAt  = Date.now();
    const promptSize = Buffer.byteLength(prompt, 'utf8');
    console.log(`      🤖 Ollama → ${env.OLLAMA_URL} (model=${env.OLLAMA_MODEL} bytes=${promptSize} timeout=${timeoutMs}ms tokens=${maxTokens})`);

    try {
      const res = await fetch(env.OLLAMA_URL, {
        method : 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal : controller.signal,
        body   : JSON.stringify({
          model  : env.OLLAMA_MODEL,
          prompt,
          stream : false,
          options: { temperature, num_predict: maxTokens }
        })
      });

      if (!res.ok) {
        const body = await res.text().catch(() => '');
        throw new Error(`Ollama HTTP ${res.status}: ${body.slice(0, 200)}`);
      }

      const data     = await res.json();
      const text     = (data.response || '').trim();
      const duration = Date.now() - startedAt;
      console.log(`      ✅ Ollama OK — ${duration}ms, ${text.length} chars`);
      return text;

    } catch (err) {
      const duration = Date.now() - startedAt;
      if (err.name === 'AbortError') {
        console.error(`      ⏱️  Ollama timeout après ${duration}ms (limite=${timeoutMs}ms)`);
        throw new Error(`Ollama timeout après ${timeoutMs}ms`);
      }
      console.error(`      ❌ Ollama erreur après ${duration}ms: ${err.message}`);
      throw err;
    } finally {
      clearTimeout(timeout);
    }
  }

  // ═══════════════════════════════════════════════════════════
  // UTILS
  // ═══════════════════════════════════════════════════════════

  _groupBy(arr, keyFn) {
    const map = new Map();
    for (const item of arr) {
      const k = keyFn(item);
      if (!map.has(k)) map.set(k, []);
      map.get(k).push(item);
    }
    return map;
  }
}

module.exports = new MarketResearchService();
