// backend/src/services/swot.service.js
//
// SWOT v2 — data-driven, non-generic, chiffré.
//
// Principes :
//   1. Backend agrège TOUTES les données disponibles :
//        - Competitor (followers, engagement, classification…)
//        - SocialAnalysis (postsPerWeek, contentMix, hashtags…)
//        - MarketResearch (moyennes sectorielles, maturité, plateforme dominante)
//        - Agrégats sectoriels recalculés à la volée si MarketResearch absent.
//   2. Backend construit un objet FACTS détaillé, puis dérive des
//      observations chiffrées (deltas concurrent vs secteur).
//   3. Pour chaque section (S / W / O / T / Recommandations) :
//        a. Prompt strict injectant les chiffres exacts
//        b. Sortie LLM = bullets "- ..." (2 à 4 par section)
//        c. Validator :
//             - taille min/max par bullet
//             - ≥ 1 chiffre cité par bullet
//             - CHAQUE chiffre doit être dans la whitelist extraite des FACTS
//               (normalisation : on compare les suites de chiffres, ignorant
//                ',', '.', '%', ' ') → impossible d'inventer un nombre
//             - mots interdits (imperatifs bannis hors Recommandations)
//        d. Bullets invalides filtrés ; si trop peu → complétion par fallback
//      déterministe tiré directement des FACTS.
//   4. Garanties :
//        - Weaknesses JAMAIS vide (fallback tire des faiblesses réalistes :
//          dépendance plateforme, concentration format, absence internationale).
//        - Chaque bullet cite un chiffre réel (grounding vérifiable).
//        - Backward-compat : `swot.strengths` (string) conservé pour le front
//          existant, mais les données vraies vivent dans `swotBullets.*`.

const Competitor     = require('../models/Competitor.model');
const SocialAnalysis = require('../models/SocialAnalysis.model');
const Project        = require('../models/Project.model');
const MarketResearch = require('../models/MarketResearch.model');
const SwotAnalysis   = require('../models/SwotAnalysis.model');
const env            = require('../config/env');

const SECTIONS = ['strengths', 'weaknesses', 'opportunities', 'threats', 'recommendations'];
const QUADRANTS = ['strengths', 'weaknesses', 'opportunities', 'threats'];

// Mots/formules toujours interdits (self-reference, flou).
const FORBIDDEN_COMMON = /\bswot\b|\bconclusion\b/i;
// Impératifs & verbes prescriptifs — interdits dans S/W/O/T mais AUTORISÉS
// dans "recommendations" (c'est le but d'une reco).
const FORBIDDEN_IMPERATIVE = /(il\s+faut|il\s+convient|devrait|\bdoit\b|suggérons|suggerons|recommand(?:ation|ons|er))/i;

const PLATFORM_LABEL = {
  instagram: 'Instagram',
  facebook : 'Facebook',
  linkedin : 'LinkedIn',
  tiktok   : 'TikTok'
};

// ═══════════════════════════════════════════════════════════
// PROMPT UNIFIÉ — un seul appel LLM, sortie JSON stricte.
// FACTS injectées via le placeholder {{FACTS_JSON}}.
// ═══════════════════════════════════════════════════════════
const FINAL_PROMPT = `You are a senior strategy consultant from a top-tier firm (McKinsey / BCG level), specializing in competitive intelligence, digital performance, and growth strategy for consumer brands.

You operate AUTONOMOUSLY: nobody will edit your output. The SWOT you produce will be sent directly to a CMO. Therefore the output must be expert-level on the first attempt — no manual correction is allowed.

IMPORTANT:
Final output MUST be written in PROFESSIONAL FRENCH.
Return ONLY a valid JSON object — no prose, no markdown, no code fence, no comments.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OBJECTIVE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Produce a CONSULTANT-GRADE SWOT for ONE competitor based ONLY on the structured FACTS below. Every bullet must read like a slide a strategy consultant would put in front of a CMO: factual, comparative, and tied to a concrete business consequence.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CONTEXT (single source of truth — never invent numbers)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

FACTS:
{{FACTS_JSON}}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HARD CONTRACT FOR EVERY BULLET — METRIC → COMPARISON → BUSINESS IMPACT (NON-NEGOTIABLE)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Each bullet MUST contain THREE explicit components, in this order:

  1. METRIC : an EXACT number copied from FACTS (no rounding, no estimation, no invention).
  2. COMPARISON : the corresponding sector benchmark / gap / position from FACTS (sectorAvg…, gap, position "above" / "below" / "equal").
  3. BUSINESS IMPACT : a CONCRETE consequence for the business. Pick AT LEAST ONE from this allowed list and name it explicitly in the bullet:
       • acquisition client (CAC, taux d'acquisition)
       • conversion (de l'audience en interactions ou en clients)
       • visibilité / portée organique
       • qualité d'engagement et interaction d'audience
       • compétitivité (différenciation, pression concurrentielle)
       • potentiel de croissance
       • part de marché / part de voix
       • rétention / fidélisation
       • dépendance / risque algorithmique

A bullet without an EXPLICIT business consequence from the list above is INVALID — rewrite it before emitting.

Words like "good", "strong", "faible", "important", "intéressant", "notable", "significatif" used ALONE — without naming a specific impact from the list — are FORBIDDEN.

Every bullet must answer the test : "So what for the business?". If that answer is not explicit in the sentence, the bullet is invalid.

DESCRIPTIVE BAD vs CONSULTING GOOD :

  BAD  : "Engagement de 0,33% inférieur à la moyenne sectorielle."
  GOOD : "Taux d'engagement de 0,33% inférieur à la moyenne sectorielle de 0,46%, limitant la capacité à convertir l'audience en interactions et réduisant le potentiel d'acquisition client."

  BAD  : "Concurrence forte."
  GOOD : "Présence de 10 leaders actifs dans le secteur, intensifiant la pression sur la différenciation et augmentant le coût d'acquisition client par rapport aux acteurs émergents."

  BAD  : "Reels sous-utilisés."
  GOOD : "Sous-exploitation des reels (30% du mix vs 55% au niveau secteur, écart de −25 points), opportunité de capter de la portée organique sur le format préféré de l'algorithme."

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SWOT LOGIC — STRICT (NEVER VIOLATE)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Strengths      = INTERNAL + POSITIVE  → un avantage compétitif chiffré (métrique > secteur, statut leader, portée internationale, format maîtrisé sans sur-concentration).
Weaknesses     = INTERNAL + NEGATIVE  → un écart de performance chiffré (métrique < secteur, dépendance plateforme, score de diversité bas, sur-concentration d'un format).
Opportunities  = EXTERNAL + EXPLOITABLE GAP → un GAP visible dans FACTS (gap de format négatif, plateforme dominante non couverte, hashtags sectoriels absents, marché en croissance, expansion géographique) AVEC une action stratégique pour l'exploiter.
Threats        = EXTERNAL + MEASURABLE RISK → un risque externe chiffré (nombre de leaders/startups, dépendance algorithmique partagée, maturité de marché, sur-exposition à un format) AVEC l'impact business mesurable.

Use FACTS pre-classifications as ground truth :
  • engagementPosition / postingPosition dictate the quadrant for engagement and cadence.
  • A metric placed against its position is an automatic logical error.
  • The SAME metric NEVER appears in two contradictory quadrants.
  • A Strength is NEVER restated as an Opportunity. A Weakness is NEVER restated as a Threat.

Weaknesses MUST NEVER be empty. If the brand performs well overall, surface at least 2 STRUCTURAL weaknesses (platformDependency, low hashtagDiversityScore, low consistencyScore, single format ≥ 60% of mix, lack of international presence).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ATOMICITY & STYLE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  • ONE primary idea per bullet. Sector benchmark + gap count as supporting context, not as separate ideas.
  • NEVER chain ideas with "et également", "par ailleurs", "de plus", "en outre", "ainsi que".
  • Length: 1 to 2 sentences, 60 to 280 characters.
  • Tone: French of a senior analyst writing for a CMO. Precise, analytical, zero marketing fluff.
  • Forbidden phrases (auto-rejected): "forte présence", "bon engagement", "contenu attractif", "bonne stratégie", "concurrence forte" sans chiffre, "marché mature" sans chiffre.
  • Never name a brand other than the analyzed competitor.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RECOMMENDATIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Each recommendation MUST be directly traceable to a Strength, Weakness, Opportunity, or Threat above.
Pattern : <action verb at infinitive> + <measurable target taken from FACTS> + <expected business outcome>.

Allowed action verbs : Augmenter, Diversifier, Tester, Ouvrir, Capitaliser, Réduire, Renforcer, Réallouer, Industrialiser.

Example :
"Augmenter la cadence de 1,6 à 3,2 publications par semaine pour combler le retard sectoriel et accroître la part de voix sur Instagram."

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
AUTO-VALIDATION (MANDATORY — perform silently before emitting)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

BEFORE producing the final JSON, run this internal checklist on EVERY bullet of EVERY section. Fix any failure by REWRITING the bullet — do NOT emit a bullet that fails any check.

For each bullet :
  ✔ Does it contain at least one EXACT number from FACTS ?              (else → rewrite)
  ✔ Does it contain a COMPARISON to sector / benchmark / gap / position ? (else → rewrite)
  ✔ Does it explicitly name a BUSINESS IMPACT from the allowed list ?    (else → rewrite)
  ✔ Is it placed in the CORRECT quadrant per SWOT logic ?                (else → move it)
  ✔ Is it free of forbidden phrases ("forte présence", "bon engagement", "concurrence forte" sans chiffre, etc.) ? (else → rewrite)
  ✔ Is it 60–280 characters, 1–2 sentences, ONE primary idea ?           (else → split / shorten)
  ✔ Does the SAME metric appear in another quadrant ?                    (else → keep ; if yes → remove the duplicate)

For each section :
  ✔ At least 2 bullets, max 4.
  ✔ "weaknesses" is NEVER empty — if all metrics look favourable, surface ≥ 2 STRUCTURAL weaknesses (platformDependency, low hashtagDiversityScore, low consistencyScore, single format ≥ 60%, no international presence).
  ✔ "recommendations" : every entry traceable to a specific Strength / Weakness / Opportunity / Threat above, and contains an action verb + measurable target + expected business outcome.

If any check fails, REWRITE the offending bullet until it passes. Only then emit the final JSON.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT (STRICT JSON, FRENCH ONLY)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{
  "strengths": [],
  "weaknesses": [],
  "opportunities": [],
  "threats": [],
  "recommendations": []
}

Rules :
  • 2 to 4 bullets per section.
  • Each bullet = 1 to 2 sentences MAX, ≤ 280 characters.
  • The JSON object is the ONLY thing returned. No prose, no markdown, no code fence, no commentary.

Return JSON ONLY in FRENCH.`;

class SwotService {

  // ═══════════════════════════════════════════════════════════
  // ENTRÉE PUBLIQUE
  // ═══════════════════════════════════════════════════════════

  async generateForCompetitor(competitorId) {
    console.log(`\n📊 SWOT v2 — concurrent ${competitorId}`);

    // .lean() : champs hors-schéma (marketPosition, geographicScope persistés
    // via bulkWrite) — même motif que marketResearch.service.js.
    const competitor = await Competitor.findById(competitorId).lean();
    if (!competitor) throw new Error('Concurrent introuvable');
    if (competitor.isActive === false) {
      const err = new Error('Concurrent désactivé');
      err.code = 'COMPETITOR_INACTIVE';
      throw err;
    }

    const project = await Project.findById(competitor.projectId);
    if (!project) throw new Error('Projet introuvable');

    const [socials, marketResearch, sectorBench] = await Promise.all([
      SocialAnalysis.find({ competitorId, scrapingStatus: 'completed' }).lean(),
      MarketResearch.findOne({ projectId: project._id }).lean().catch(() => null),
      this._computeSectorBenchmarks(project._id, competitor._id)
    ]);

    const swotDoc = await SwotAnalysis.findOrCreate(competitor._id, project._id);
    swotDoc.companyName = competitor.companyName;
    swotDoc.status      = 'in_progress';
    await swotDoc.save();

    try {
      const facts       = this._buildFacts(competitor, socials, project, marketResearch, sectorBench);
      const numberSet   = this._buildNumberWhitelist(facts);

      console.log(`   📋 FACTS: followers=${facts.followers} eng=${facts.engagementRate}% vs sector=${facts.sectorAvgEngagement ?? '—'}% ppw=${facts.postsPerWeek} vs ${facts.sectorAvgPostsPerWeek ?? '—'} pos=${facts.classificationMaturity} scope=${facts.geographicScope}`);
      console.log(`   📋 Whitelist: ${numberSet.size} numbers`);
      console.log(`   🤖 Génération SWOT unifiée (prompt pro, JSON strict, ${env.OLLAMA_MODEL})...`);

      // ─── 1 seul appel LLM → JSON strict (toutes sections d'un coup) ───
      const prompt = FINAL_PROMPT.replace('{{FACTS_JSON}}', JSON.stringify(facts, null, 2));

      let llmJson = null;
      let llmError = null;
      try {
        const rawText = await this._callOllama(prompt, { timeoutMs: 120000, maxTokens: 1500, temperature: 0.2 });
        llmJson = this._parseJsonResponse(rawText);
        if (!llmJson) llmError = 'JSON invalide ou introuvable dans la réponse';
      } catch (e) {
        llmError = e.message;
        console.warn(`   ⚠️  Ollama échec (${e.message}) — fallback sur toutes les sections`);
      }

      const bullets = {};
      const sources = {};
      let llmOk = 0;
      const llmTotal = SECTIONS.length;

      for (const section of SECTIONS) {
        const fallback  = this._fallbackBullets(section, facts);
        const raw       = (llmJson && Array.isArray(llmJson[section])) ? llmJson[section] : [];
        const parsed    = raw.filter(b => typeof b === 'string' && b.trim()).map(b => b.trim());

        const validated = [];
        const rejected  = [];
        for (const b of parsed) {
          const v = this._validateBullet(b, numberSet, section);
          if (v.ok) validated.push(b);
          else       rejected.push({ bullet: b.slice(0, 80), reason: v.reason });
        }

        // weaknesses : jamais vide (règle §5) — min 2 partout.
        const minBullets = 2;
        const maxBullets = 4;

        let finalBullets;
        let sourceType  = 'llm';
        let sourceReason = '';

        if (validated.length >= minBullets) {
          finalBullets = validated.slice(0, maxBullets);
        } else if (validated.length > 0) {
          const fillers = fallback.filter(f => !validated.includes(f));
          finalBullets = [...validated, ...fillers].slice(0, maxBullets);
          sourceType   = 'mixed';
          sourceReason = `${validated.length}/${parsed.length} LLM valides, complété par fallback`;
        } else {
          finalBullets = fallback.slice(0, maxBullets);
          sourceType   = 'fallback';
          sourceReason = llmError
            ? `LLM indisponible (${llmError})`
            : (rejected.length ? `LLM rejeté (${rejected[0].reason})` : 'LLM vide');
        }

        bullets[section] = finalBullets;
        sources[section] = { type: sourceType, reason: sourceReason };
        if (sourceType === 'llm') llmOk++;

        console.log(
          `   ${sourceType === 'llm' ? '✅' : sourceType === 'mixed' ? '🔀' : '↩️ '} ${section.padEnd(15)} ` +
          `parsed=${parsed.length} valid=${validated.length} final=${finalBullets.length} (${sourceType}${sourceReason ? `: ${sourceReason}` : ''})`
        );
        for (const r of rejected.slice(0, 2)) {
          console.log(`        • rejet "${r.bullet}…" → ${r.reason}`);
        }
      }

      // ─── Garde-fou cross-section : logique + dédoublonnage ───
      const enforcement = this._enforceCrossSectionLogic(bullets, facts);
      const cleaned     = enforcement.bullets;

      for (const section of SECTIONS) {
        const removed = enforcement.dropped[section];
        if (removed.length) {
          for (const r of removed) {
            console.log(`   🛡️  ${section.padEnd(15)} drop "${r.bullet}…" → ${r.reason}`);
          }
          // Re-remplissage si on tombe sous le minimum
          if (cleaned[section].length < 2) {
            const fb = this._fallbackBullets(section, facts).filter(f => !cleaned[section].includes(f));
            cleaned[section] = [...cleaned[section], ...fb].slice(0, 4);
            if (sources[section].type === 'llm') {
              sources[section].type   = 'mixed';
              sources[section].reason = (sources[section].reason ? sources[section].reason + ' + ' : '') + 'correction logique post-LLM';
            }
            console.log(`   🩹 ${section.padEnd(15)} re-rempli depuis fallback (final=${cleaned[section].length})`);
          }
          bullets[section] = cleaned[section];
        }
      }

      // Persist
      swotDoc.facts          = facts;
      swotDoc.swotBullets    = {
        strengths    : bullets.strengths,
        weaknesses   : bullets.weaknesses,
        opportunities: bullets.opportunities,
        threats      : bullets.threats
      };
      swotDoc.swot = {
        strengths    : bullets.strengths.join(' • '),
        weaknesses   : bullets.weaknesses.join(' • '),
        opportunities: bullets.opportunities.join(' • '),
        threats      : bullets.threats.join(' • ')
      };
      swotDoc.recommendations = bullets.recommendations;
      swotDoc.sources         = sources;
      swotDoc.aiModelUsed     = env.OLLAMA_MODEL;
      await swotDoc.markAsCompleted();

      console.log(`   📝 SWOT assemblé : ${llmOk}/${llmTotal} sections entièrement LLM`);
      console.log(`   ✅ SWOT persisté pour ${competitor.companyName}`);
      return swotDoc;

    } catch (error) {
      console.error(`   ❌ Échec SWOT : ${error.message}`);
      await swotDoc.markAsFailed(error.message);
      throw error;
    }
  }

  // ═══════════════════════════════════════════════════════════
  // BENCHMARKS SECTORIELS (sans MarketResearch persistant)
  // ═══════════════════════════════════════════════════════════

  async _computeSectorBenchmarks(projectId, excludeCompetitorId) {
    const competitors = await Competitor
      .find({ projectId, isActive: true })
      .select('_id metrics classificationMaturity')
      .lean();
    const ids = competitors.map(c => c._id);

    const socials = await SocialAnalysis
      .find({ competitorId: { $in: ids }, scrapingStatus: 'completed' })
      .lean();

    let engSum = 0, engN = 0;
    let ppwSum = 0, ppwN = 0;
    const mixAgg = { photo: 0, video: 0, reel: 0, carousel: 0, story: 0 };
    const hashtagCount = new Map();

    for (const s of socials) {
      if (Number.isFinite(s.engagementRate) && s.engagementRate > 0) {
        engSum += s.engagementRate; engN++;
      }
      if (Number.isFinite(s.postsPerWeek) && s.postsPerWeek > 0) {
        ppwSum += s.postsPerWeek; ppwN++;
      }
      if (s.contentDistribution) {
        for (const k of Object.keys(mixAgg)) {
          mixAgg[k] += Number(s.contentDistribution[k] || 0);
        }
      }
      for (const raw of (s.topHashtags || [])) {
        if (typeof raw !== 'string') continue;
        const tag = raw.replace(/^#/, '').trim().toLowerCase();
        if (tag.length < 3 || tag.length > 30) continue;
        if (!/^[A-Za-z0-9_À-ſ]+$/.test(tag)) continue;
        hashtagCount.set(tag, (hashtagCount.get(tag) || 0) + 1);
      }
    }

    const totalFormats = Object.values(mixAgg).reduce((a, b) => a + b, 0);
    const sectorContentMix = totalFormats > 0
      ? Object.fromEntries(
          Object.entries(mixAgg)
            .filter(([, v]) => v > 0)
            .map(([k, v]) => [k, Math.round((v / totalFormats) * 100)])
        )
      : {};

    const topSectorHashtags = [...hashtagCount.entries()]
      .sort((a, b) => b[1] - a[1])
      .slice(0, 6)
      .map(([t]) => t);

    return {
      avgEngagement   : engN ? Number((engSum / engN).toFixed(3)) : null,
      avgPostsPerWeek : ppwN ? Number((ppwSum / ppwN).toFixed(2)) : null,
      contentMix      : sectorContentMix,
      topHashtags     : topSectorHashtags,
      competitorsCount: competitors.length,
      excluded        : excludeCompetitorId ? String(excludeCompetitorId) : null
    };
  }

  // ═══════════════════════════════════════════════════════════
  // FACTS — source de vérité unique pour le reste du flow
  // ═══════════════════════════════════════════════════════════

  _buildFacts(competitor, socials, project, marketResearch, sectorBench) {
    // ─── Competitor metrics ─────────────────────────────────
    const followers = (competitor.metrics && competitor.metrics.totalFollowers)
      || socials.reduce((sum, s) => sum + (s.followers || 0), 0)
      || 0;

    const engArr = socials.map(s => s.engagementRate).filter(v => Number.isFinite(v) && v > 0);
    const engMean = engArr.length ? engArr.reduce((a, b) => a + b, 0) / engArr.length : 0;
    const engagementRate = (competitor.metrics && competitor.metrics.avgEngagementRate)
      || Number(engMean.toFixed(3))
      || 0;

    const ppwArr = socials.map(s => s.postsPerWeek).filter(v => Number.isFinite(v) && v > 0);
    const postsPerWeek = ppwArr.length
      ? Number((ppwArr.reduce((a, b) => a + b, 0) / ppwArr.length).toFixed(2))
      : 0;

    // ─── Content mix ────────────────────────────────────────
    const mixAgg = { photo: 0, video: 0, reel: 0, carousel: 0, story: 0 };
    for (const s of socials) {
      if (s.contentDistribution) {
        for (const k of Object.keys(mixAgg)) mixAgg[k] += Number(s.contentDistribution[k] || 0);
      }
    }
    const totalFormats = Object.values(mixAgg).reduce((a, b) => a + b, 0);
    const contentMix = totalFormats > 0
      ? Object.fromEntries(
          Object.entries(mixAgg)
            .filter(([, v]) => v > 0)
            .map(([k, v]) => [k, Math.round((v / totalFormats) * 100)])
        )
      : {};
    const topFormatEntry = Object.entries(contentMix).sort((a, b) => b[1] - a[1])[0];
    const topFormat = topFormatEntry ? { name: topFormatEntry[0], pct: topFormatEntry[1] } : null;

    // ─── Hashtags ───────────────────────────────────────────
    const tagCount = new Map();
    for (const s of socials) {
      for (const raw of (s.topHashtags || [])) {
        if (typeof raw !== 'string') continue;
        const tag = raw.replace(/^#/, '').trim().toLowerCase();
        if (tag.length < 3 || tag.length > 30) continue;
        if (!/^[A-Za-z0-9_À-ſ]+$/.test(tag)) continue;
        tagCount.set(tag, (tagCount.get(tag) || 0) + 1);
      }
    }
    const topHashtags = [...tagCount.entries()]
      .sort((a, b) => b[1] - a[1])
      .slice(0, 6)
      .map(([tag]) => tag);

    const platforms = [...new Set(socials.map(s => s.platform).filter(Boolean))];

    // ─── Position & portée ──────────────────────────────────
    const classificationMaturity = this._resolvePosition(competitor);
    const geographicScope        = this._resolveScope(competitor);

    // ─── Benchmarks sectoriels ──────────────────────────────
    const hasMR = !!(marketResearch && marketResearch.status === 'completed');
    const mo    = hasMR ? (marketResearch.marketOverview || {}) : {};

    const sectorAvgEngagement   = sectorBench.avgEngagement   ?? null;
    const sectorAvgPostsPerWeek = sectorBench.avgPostsPerWeek ?? null;
    const sectorContentMix      = sectorBench.contentMix      || {};
    const sectorTopHashtags     = sectorBench.topHashtags     || [];
    const sectorDominantPlatform = (hasMR && mo.dominantPlatform) || '';
    const sectorMaturity         = (hasMR && mo.marketMaturity) || '';

    // ─── Deltas concurrent vs secteur ───────────────────────
    const engagementDelta = (sectorAvgEngagement != null && engagementRate > 0)
      ? Number((engagementRate - sectorAvgEngagement).toFixed(3))
      : null;
    const postsDelta = (sectorAvgPostsPerWeek != null && postsPerWeek > 0)
      ? Number((postsPerWeek - sectorAvgPostsPerWeek).toFixed(2))
      : null;

    // ═══════════════════════════════════════════════════════════
    // SIGNAUX DÉRIVÉS — comparaisons interprétables (B → G).
    // Le LLM s'en sert directement : pas de calcul à refaire de
    // son côté → moins d'inventions, plus de précision.
    // ═══════════════════════════════════════════════════════════

    // B. Position relative au marché (above / below / equal / unknown)
    const _position = (delta, eps) => {
      if (delta == null) return 'unknown';
      if (Math.abs(delta) < eps) return 'equal';
      return delta > 0 ? 'above' : 'below';
    };
    const engagementPosition = _position(engagementDelta, 0.01); // point d'écart d'engagement
    const postingPosition    = _position(postsDelta,      0.10); // 0.1 post/sem

    // C. Écarts par format (concurrent − secteur), en points de %
    const _mixGap = (key) => {
      const a = Number(contentMix[key] || 0);
      const b = Number((sectorContentMix && sectorContentMix[key]) || 0);
      if (a === 0 && b === 0) return null;
      return a - b;
    };
    const reelGap     = _mixGap('reel');
    const carouselGap = _mixGap('carousel');
    const photoGap    = _mixGap('photo');

    const dominantContentType = topFormat ? topFormat.name : null;
    const usedFormats         = Object.entries(contentMix).filter(([, v]) => v > 0);
    const underusedEntry      = usedFormats.length > 1
      ? [...usedFormats].sort((a, b) => a[1] - b[1])[0]
      : null;
    const underusedContentType = underusedEntry ? underusedEntry[0] : null;

    // D. Activité & consistance
    let activityLevel = 'unknown';
    if (postsPerWeek > 0) {
      if      (postsPerWeek >= 5) activityLevel = 'high';
      else if (postsPerWeek >= 2) activityLevel = 'medium';
      else                        activityLevel = 'low';
    }
    // Score 0–100 : 5 posts/semaine = 100 (cible "haute").
    const consistencyScore = postsPerWeek > 0
      ? Math.min(100, Math.round((postsPerWeek / 5) * 100))
      : 0;

    // E. Compétitivité du marché (proxy simple : densité concurrentielle)
    let competitivenessLevel = 'unknown';
    const compCount = sectorBench.competitorsCount || 0;
    if (compCount > 0) {
      if      (compCount >= 8) competitivenessLevel = 'high';
      else if (compCount >= 4) competitivenessLevel = 'medium';
      else                     competitivenessLevel = 'low';
    }

    // F. Dépendance plateforme (mono-canal = vrai)
    const platformDependency = platforms.length <= 1;

    // G. Score de diversité hashtags 0–100 (saturation à 10 hashtags uniques)
    const hashtagDiversityScore = Math.min(100, Math.round((topHashtags.length / 10) * 100));

    return {
      // ─── Identité ─────────────────────────────────────────
      industry: project.industry || '',
      country : project.country  || '',

      // ─── A. PERFORMANCE METRICS ──────────────────────────
      followers,
      engagementRate,
      postsPerWeek,

      // ─── B. MARKET COMPARISON ────────────────────────────
      sectorAvgEngagement,
      sectorAvgPostsPerWeek,
      sectorAvgPosts        : sectorAvgPostsPerWeek, // alias contractuel
      engagementGap         : engagementDelta,
      postingGap            : postsDelta,
      engagementPosition,
      postingPosition,

      // ─── C. CONTENT STRATEGY ANALYSIS ────────────────────
      contentMix,
      sectorContentMix,
      reelGap,
      carouselGap,
      photoGap,
      dominantContentType,
      underusedContentType,
      topFormat, // rétro-compat fallback

      // ─── D. ACTIVITY & CONSISTENCY ───────────────────────
      activityLevel,
      consistencyScore,

      // ─── E. MARKET POSITIONING ───────────────────────────
      classification        : geographicScope,        // local | international | unknown
      geographicScope,                                // rétro-compat fallback
      marketPosition        : classificationMaturity, // leader | startup | unknown
      classificationMaturity,                         // rétro-compat fallback
      competitivenessLevel,

      // ─── F. PLATFORM & DEPENDENCY ────────────────────────
      platforms,
      dominantPlatform      : sectorDominantPlatform || null,
      sectorDominantPlatform,                         // rétro-compat fallback
      platformDependency,

      // ─── G. HASHTAG / CONTENT SIGNALS ────────────────────
      topHashtags,
      sectorTopHashtags,
      hashtagDiversityScore,

      // ─── Structure secteur (rétro-compat fallback) ───────
      sectorMaturity,
      sectorLeaderCount       : hasMR ? (mo.leaderCount        ?? null) : null,
      sectorStartupCount      : hasMR ? (mo.startupCount       ?? null) : null,
      sectorLocalCount        : hasMR ? (mo.localCount         ?? null) : null,
      sectorInternationalCount: hasMR ? (mo.internationalCount ?? null) : null,
      sectorCompetitorsCount  : sectorBench.competitorsCount || null,
      hasMarketSummary        : hasMR,

      // ─── Deltas bruts (rétro-compat fallback) ────────────
      engagementDelta,
      postsDelta
    };
  }

  _resolvePosition(c) {
    if (c.marketPosition === 'leader' || c.marketPosition === 'startup') return c.marketPosition;
    if (c.classificationMaturity === 'leader' || c.classificationMaturity === 'startup') return c.classificationMaturity;
    return 'unknown';
  }

  _resolveScope(c) {
    if (c.geographicScope === 'local' || c.geographicScope === 'international') return c.geographicScope;
    if (c.classification === 'local' || c.classification === 'international') return c.classification;
    return 'unknown';
  }

  // ═══════════════════════════════════════════════════════════
  // FORMAT HELPERS
  // ═══════════════════════════════════════════════════════════

  _fmtInt(n) {
    if (n == null || !Number.isFinite(Number(n))) return '—';
    return new Intl.NumberFormat('fr-FR').format(Number(n)).replace(/ /g, ' ');
  }
  _fmtPct(n, decimals = 2) {
    if (n == null || !Number.isFinite(Number(n))) return '—';
    return `${Number(n).toFixed(decimals).replace('.', ',')}%`;
  }
  _fmtNum(n, decimals = 1) {
    if (n == null || !Number.isFinite(Number(n))) return '—';
    return Number(n).toFixed(decimals).replace('.', ',').replace(/,0$/, '');
  }
  _fmtDelta(n, decimals = 2) {
    if (n == null || !Number.isFinite(Number(n))) return '—';
    const sign = n >= 0 ? '+' : '−';
    return `${sign}${Math.abs(n).toFixed(decimals).replace('.', ',')}`;
  }
  _platLabel(p) { return PLATFORM_LABEL[p] || p || ''; }

  // ═══════════════════════════════════════════════════════════
  // NUMBER WHITELIST — normalisation : on compare les suites
  // de chiffres en ignorant ponctuation/espaces/%/units.
  // "146 846" ≡ "146846"  ;  "0,30" ≡ "030"  ;  "30%" ≡ "30"
  // ═══════════════════════════════════════════════════════════

  _normNum(raw) {
    if (raw == null) return null;
    const digits = String(raw).replace(/[^\d]/g, '');
    return digits || null;
  }

  _buildNumberWhitelist(f) {
    const set = new Set();
    const add = (v) => {
      const n = this._normNum(v);
      if (n) set.add(n);
    };

    // Concurrent
    add(f.followers);
    add(Math.round(Number(f.engagementRate)));
    add(Number(f.engagementRate).toFixed(2));       // "0.30"
    add(Number(f.engagementRate).toFixed(3));
    add(Math.round(Number(f.engagementRate) * 100));
    add(Math.round(Number(f.postsPerWeek)));
    add(Number(f.postsPerWeek).toFixed(1));          // "1.6"
    add(Number(f.postsPerWeek).toFixed(2));

    for (const pct of Object.values(f.contentMix || {})) add(pct);
    for (const pct of Object.values(f.sectorContentMix || {})) add(pct);

    // Secteur
    add(f.sectorAvgEngagement);
    if (f.sectorAvgEngagement != null) {
      add(Number(f.sectorAvgEngagement).toFixed(2));
      add(Number(f.sectorAvgEngagement).toFixed(3));
      add(Math.round(Number(f.sectorAvgEngagement) * 100));
    }
    add(f.sectorAvgPostsPerWeek);
    if (f.sectorAvgPostsPerWeek != null) {
      add(Number(f.sectorAvgPostsPerWeek).toFixed(1));
      add(Number(f.sectorAvgPostsPerWeek).toFixed(2));
      add(Math.round(Number(f.sectorAvgPostsPerWeek)));
    }
    add(f.sectorLeaderCount);
    add(f.sectorStartupCount);
    add(f.sectorLocalCount);
    add(f.sectorInternationalCount);
    add(f.sectorCompetitorsCount);

    // Deltas
    if (f.engagementDelta != null) {
      add(Number(Math.abs(f.engagementDelta)).toFixed(2));
      add(Number(Math.abs(f.engagementDelta)).toFixed(3));
      add(Math.round(Math.abs(f.engagementDelta) * 100));
    }
    if (f.postsDelta != null) {
      add(Number(Math.abs(f.postsDelta)).toFixed(1));
      add(Number(Math.abs(f.postsDelta)).toFixed(2));
      add(Math.round(Math.abs(f.postsDelta)));
    }

    // ─── Signaux dérivés (gaps de format, scores 0–100) ───
    const addAbsAndRaw = (v) => {
      if (v == null || !Number.isFinite(Number(v))) return;
      add(Math.abs(v));
      add(v);
    };
    addAbsAndRaw(f.reelGap);
    addAbsAndRaw(f.carouselGap);
    addAbsAndRaw(f.photoGap);
    add(f.consistencyScore);
    add(f.hashtagDiversityScore);

    // Petits entiers fréquents (0, 1, 2) utiles en comparatif "1 seule plateforme"
    [0, 1, 2].forEach(n => set.add(String(n)));

    return set;
  }

  _extractNumbers(text) {
    const matches = text.match(/\d[\d\s,. ]*\d|\d/g) || [];
    return matches.map(m => m.replace(/[^\d]/g, '')).filter(Boolean);
  }

  // ═══════════════════════════════════════════════════════════
  // PARSING + VALIDATION PAR BULLET
  // ═══════════════════════════════════════════════════════════

  // Extraction tolérante : le LLM peut encadrer le JSON de texte
  // parasite ou d'un code fence ```json. On isole le premier bloc { ... }
  // équilibré et on tente JSON.parse.
  _parseJsonResponse(text) {
    if (!text) return null;
    let raw = String(text).trim();
    const fence = raw.match(/```(?:json)?\s*([\s\S]*?)```/i);
    if (fence) raw = fence[1].trim();

    const start = raw.indexOf('{');
    if (start === -1) return null;
    let depth = 0;
    let end = -1;
    for (let i = start; i < raw.length; i++) {
      const ch = raw[i];
      if (ch === '{') depth++;
      else if (ch === '}') { depth--; if (depth === 0) { end = i; break; } }
    }
    if (end === -1) return null;

    try {
      const obj = JSON.parse(raw.slice(start, end + 1));
      return (obj && typeof obj === 'object') ? obj : null;
    } catch (_) {
      return null;
    }
  }

  _parseBullets(text) {
    if (!text) return [];
    const lines = text.split(/\r?\n/).map(l => l.trim());
    const bullets = [];
    for (const l of lines) {
      const m = l.match(/^[-*•·]\s+(.+)$/);
      if (m) bullets.push(m[1].trim());
    }
    // Fallback : si le LLM n'a pas utilisé de puces, essayer split par numérotation "1."
    if (bullets.length === 0) {
      for (const l of lines) {
        const m = l.match(/^\d+\.\s+(.+)$/);
        if (m) bullets.push(m[1].trim());
      }
    }
    return bullets;
  }

  // ═══════════════════════════════════════════════════════════
  // CROSS-SECTION ENFORCEMENT
  // Garde-fou logique appliqué APRÈS la validation par bullet :
  //   - dédoublonne entre quadrants (même phrase ailleurs)
  //   - drop bullets qui contredisent les positions pré-calculées
  //     (ex : engagement vanté en strengths alors que
  //     engagementPosition === 'below')
  //   - drop bullets multi-idées (≥ 3 numéros distincts)
  // Le caller (generateForCompetitor) re-remplit avec le fallback
  // déterministe si une section tombe sous le minimum.
  // ═══════════════════════════════════════════════════════════

  _isEngagementBullet(b) {
    return /\bengag/i.test(b);
  }
  _isPostingBullet(b) {
    return /(post(?:s|ing|er)?|publication|cadence|fréquen|publier)/i.test(b);
  }
  _bulletKey(b) {
    return String(b).toLowerCase().replace(/[\s.,;:!?'"()«»–—-]+/g, ' ').trim().slice(0, 80);
  }

  _enforceCrossSectionLogic(bullets, facts) {
    const out = {
      strengths     : [...(bullets.strengths      || [])],
      weaknesses    : [...(bullets.weaknesses     || [])],
      opportunities : [...(bullets.opportunities  || [])],
      threats       : [...(bullets.threats        || [])],
      recommendations: [...(bullets.recommendations || [])]
    };
    const dropped = { strengths: [], weaknesses: [], opportunities: [], threats: [], recommendations: [] };

    // ─── 1) Dédoublonnage cross-section (clé normalisée) ───
    for (let i = 0; i < SECTIONS.length; i++) {
      const a = SECTIONS[i];
      const seen = new Set(out[a].map(b => this._bulletKey(b)));
      for (let j = i + 1; j < SECTIONS.length; j++) {
        const b = SECTIONS[j];
        out[b] = out[b].filter(x => {
          const k = this._bulletKey(x);
          if (seen.has(k)) { dropped[b].push({ bullet: x.slice(0, 80), reason: `doublon de ${a}` }); return false; }
          return true;
        });
      }
    }

    // ─── 2) Logique d'engagement ───
    if (facts.engagementPosition === 'below') {
      out.strengths = out.strengths.filter(b => {
        if (this._isEngagementBullet(b)) {
          dropped.strengths.push({ bullet: b.slice(0, 80), reason: 'engagement < secteur ne peut pas être une force' });
          return false;
        }
        return true;
      });
    } else if (facts.engagementPosition === 'above') {
      out.weaknesses = out.weaknesses.filter(b => {
        if (this._isEngagementBullet(b)) {
          dropped.weaknesses.push({ bullet: b.slice(0, 80), reason: 'engagement > secteur ne peut pas être une faiblesse' });
          return false;
        }
        return true;
      });
    }

    // ─── 3) Logique de cadence de publication ───
    if (facts.postingPosition === 'below') {
      out.strengths = out.strengths.filter(b => {
        if (this._isPostingBullet(b)) {
          dropped.strengths.push({ bullet: b.slice(0, 80), reason: 'cadence < secteur ne peut pas être une force' });
          return false;
        }
        return true;
      });
    } else if (facts.postingPosition === 'above') {
      out.weaknesses = out.weaknesses.filter(b => {
        if (this._isPostingBullet(b)) {
          dropped.weaknesses.push({ bullet: b.slice(0, 80), reason: 'cadence > secteur ne peut pas être une faiblesse' });
          return false;
        }
        return true;
      });
    }

    // ─── 4) Atomicité : ≥ 3 numéros distincts = bullet multi-idées ───
    for (const section of SECTIONS) {
      out[section] = out[section].filter(b => {
        const distinct = new Set(this._extractNumbers(b));
        if (distinct.size > 3) {
          dropped[section].push({ bullet: b.slice(0, 80), reason: `multi-idées (${distinct.size} chiffres distincts)` });
          return false;
        }
        return true;
      });
    }

    return { bullets: out, dropped };
  }

  _validateBullet(bullet, numberSet, section) {
    if (!bullet) return { ok: false, reason: 'vide' };
    const t = bullet.trim().replace(/\s+/g, ' ');
    if (t.length < 25)  return { ok: false, reason: `trop court (${t.length})` };
    if (t.length > 300) return { ok: false, reason: `trop long (${t.length})` };
    if (/\*\*|##/.test(t))          return { ok: false, reason: 'markdown' };
    if (FORBIDDEN_COMMON.test(t))   return { ok: false, reason: 'mot interdit (common)' };
    if (section !== 'recommendations' && FORBIDDEN_IMPERATIVE.test(t)) {
      return { ok: false, reason: 'impératif interdit hors recommandations' };
    }

    // Chaque bullet DOIT citer au moins un chiffre…
    const nums = this._extractNumbers(t);
    if (nums.length === 0) return { ok: false, reason: 'aucun chiffre cité' };

    // …ET chaque chiffre DOIT être dans la whitelist des FACTS.
    for (const n of nums) {
      if (!numberSet.has(n)) return { ok: false, reason: `nombre inventé "${n}"` };
    }

    return { ok: true };
  }

  // ═══════════════════════════════════════════════════════════
  // FALLBACK DÉTERMINISTE PAR SECTION
  // Chaque bullet construit depuis les FACTS → chiffres corrects par
  // construction → passe la validation par conception.
  // ═══════════════════════════════════════════════════════════

  _fallbackBullets(section, f) {
    if (section === 'strengths')      return this._fbStrengths(f);
    if (section === 'weaknesses')     return this._fbWeaknesses(f);
    if (section === 'opportunities')  return this._fbOpportunities(f);
    if (section === 'threats')        return this._fbThreats(f);
    if (section === 'recommendations')return this._fbRecommendations(f);
    return [];
  }

  _fbStrengths(f) {
    const out = [];
    const plat = f.platforms.map(p => this._platLabel(p)).join(' + ') || 'les réseaux sociaux';

    if (f.followers > 0) {
      out.push(`Audience digitale de ${this._fmtInt(f.followers)} abonnés sur ${plat}.`);
    }
    if (f.engagementRate > 0 && f.sectorAvgEngagement != null && f.engagementDelta != null && f.engagementDelta > 0) {
      out.push(`Engagement de ${this._fmtPct(f.engagementRate)} supérieur à la moyenne sectorielle (${this._fmtPct(f.sectorAvgEngagement)}), écart de ${this._fmtDelta(f.engagementDelta)} point.`);
    } else if (f.engagementRate > 0) {
      out.push(`Engagement moyen observé de ${this._fmtPct(f.engagementRate)} sur le périmètre analysé.`);
    }
    if (f.classificationMaturity === 'leader') {
      out.push(`Positionnement de leader reconnu parmi les ${this._fmtInt(f.sectorLeaderCount ?? 0)} leaders identifiés du secteur.`);
    }
    if (f.topFormat) {
      out.push(`Format ${f.topFormat.name} mobilisé à ${this._fmtInt(f.topFormat.pct)}% du mix de contenu publié.`);
    }
    if (f.geographicScope === 'international') {
      out.push(`Présence établie à l'international, parmi les ${this._fmtInt(f.sectorInternationalCount ?? 0)} acteurs internationaux du secteur.`);
    }
    return out.slice(0, 4);
  }

  _fbWeaknesses(f) {
    const out = [];

    if (f.engagementRate > 0 && f.sectorAvgEngagement != null && f.engagementDelta != null && f.engagementDelta < 0) {
      out.push(`Engagement de ${this._fmtPct(f.engagementRate)} en deçà de la moyenne sectorielle (${this._fmtPct(f.sectorAvgEngagement)}), écart de ${this._fmtDelta(f.engagementDelta)} point.`);
    }
    if (f.postsPerWeek > 0 && f.sectorAvgPostsPerWeek != null && f.postsDelta != null && f.postsDelta < 0) {
      out.push(`Fréquence de publication de ${this._fmtNum(f.postsPerWeek)} post par semaine, en retrait de ${this._fmtDelta(f.postsDelta, 1)} vs la moyenne du secteur (${this._fmtNum(f.sectorAvgPostsPerWeek)}).`);
    }
    if (f.topFormat && f.topFormat.pct >= 60) {
      out.push(`Concentration forte du mix de contenu sur le format ${f.topFormat.name} (${this._fmtInt(f.topFormat.pct)}%), peu de diversification.`);
    }
    if (f.platforms.length <= 1) {
      const p = f.platforms[0] ? this._platLabel(f.platforms[0]) : 'une seule plateforme';
      out.push(`Dépendance à 1 seule plateforme (${p}), exposition élevée aux changements d'algorithme.`);
    }
    if (f.geographicScope === 'local' && f.sectorInternationalCount != null && f.sectorInternationalCount >= 1) {
      out.push(`Couverture exclusivement locale alors que ${this._fmtInt(f.sectorInternationalCount)} acteur(s) international(aux) sont présents dans le secteur.`);
    }
    if (f.topHashtags.length <= 2) {
      out.push(`Empreinte thématique restreinte : ${this._fmtInt(f.topHashtags.length)} hashtags dominants seulement, vs ${this._fmtInt(f.sectorTopHashtags.length || 0)} récurrents au niveau du secteur.`);
    }
    if (f.followers > 0 && f.engagementRate > 0 && f.engagementRate < 0.2) {
      out.push(`Engagement absolu de ${this._fmtPct(f.engagementRate)} faible rapporté à ${this._fmtInt(f.followers)} abonnés, suggérant une audience peu interactive.`);
    }

    // Garantie §5 : JAMAIS vide.
    if (out.length < 2) {
      out.push(`Taux d'engagement moyen de ${this._fmtPct(f.engagementRate)} — marge d'amélioration sur la qualité d'interaction.`);
      out.push(`Dépendance à 1 seule plateforme principale (${this._platLabel(f.platforms[0] || 'instagram')}) parmi les canaux sociaux.`);
    }
    return out.slice(0, 4);
  }

  _fbOpportunities(f) {
    const out = [];
    if (f.sectorMaturity === 'growing' || f.sectorMaturity === 'emerging') {
      out.push(`Secteur en ${f.sectorMaturity === 'growing' ? 'croissance' : 'émergence'}, avec ${this._fmtInt(f.sectorCompetitorsCount || 0)} concurrents actifs et un espace pour renforcer la part de voix.`);
    }
    if (f.sectorDominantPlatform && !f.platforms.includes(f.sectorDominantPlatform)) {
      out.push(`Présence à ouvrir sur ${this._platLabel(f.sectorDominantPlatform)}, plateforme dominante du secteur actuellement non couverte.`);
    }
    if (f.topFormat && f.sectorContentMix && f.sectorContentMix[f.topFormat.name]) {
      const sectorPct = f.sectorContentMix[f.topFormat.name];
      if (f.topFormat.pct < sectorPct) {
        out.push(`Format ${f.topFormat.name} exploité à ${this._fmtInt(f.topFormat.pct)}% vs ${this._fmtInt(sectorPct)}% au niveau sectoriel — marge d'intensification.`);
      }
    }
    // Format sectoriel dominant non exploité
    const sectorTopFormatEntry = Object.entries(f.sectorContentMix || {}).sort((a, b) => b[1] - a[1])[0];
    if (sectorTopFormatEntry) {
      const [name, pct] = sectorTopFormatEntry;
      const selfPct = f.contentMix[name] || 0;
      if (selfPct < pct - 10) {
        out.push(`Format ${name} dominant dans le secteur (${this._fmtInt(pct)}%) mais sous-exploité par la marque (${this._fmtInt(selfPct)}%).`);
      }
    }
    if (f.geographicScope === 'local' && f.sectorInternationalCount === 0) {
      out.push(`Opportunité d'expansion : ${this._fmtInt(f.sectorInternationalCount ?? 0)} acteur international recensé dans le secteur, fenêtre d'ouverture disponible.`);
    }
    if (f.sectorTopHashtags.length > f.topHashtags.length) {
      out.push(`${this._fmtInt(f.sectorTopHashtags.length)} hashtags récurrents au niveau secteur, vs ${this._fmtInt(f.topHashtags.length)} repérés sur la marque — gisement éditorial à explorer.`);
    }
    if (out.length < 2) {
      out.push(`Activité sectorielle à ${this._fmtNum(f.sectorAvgPostsPerWeek || 0)} posts/semaine en moyenne — fenêtre pour densifier la présence éditoriale.`);
    }
    return out.slice(0, 4);
  }

  _fbThreats(f) {
    const out = [];
    if (f.sectorLeaderCount != null && f.sectorLeaderCount >= 3) {
      out.push(`Concurrence établie forte : ${this._fmtInt(f.sectorLeaderCount)} leaders présents dans le secteur.`);
    }
    if (f.sectorStartupCount != null && f.sectorStartupCount >= 3) {
      out.push(`Montée en puissance rapide : ${this._fmtInt(f.sectorStartupCount)} startups actives sur le secteur.`);
    }
    if (f.sectorDominantPlatform && f.platforms.includes(f.sectorDominantPlatform)) {
      out.push(`Dépendance à ${this._platLabel(f.sectorDominantPlatform)} partagée par l'ensemble du secteur, sensibilité aux évolutions d'algorithme.`);
    }
    if (f.sectorMaturity === 'mature' || f.sectorMaturity === 'declining') {
      out.push(`Secteur à maturité ${f.sectorMaturity === 'declining' ? 'en déclin' : 'élevée'} parmi ${this._fmtInt(f.sectorCompetitorsCount || 0)} acteurs, acquisition de nouveaux clients plus coûteuse.`);
    }
    if (f.topFormat && f.topFormat.pct >= 70) {
      out.push(`Sur-exposition au format ${f.topFormat.name} (${this._fmtInt(f.topFormat.pct)}% du mix), vulnérable à une chute de reach sur ce format.`);
    }
    if (out.length < 2) {
      out.push(`Concentration de l'activité sur 1 plateforme principale — risque en cas d'évolution d'algorithme.`);
      out.push(`Cadence sectorielle à ${this._fmtNum(f.sectorAvgPostsPerWeek || 0)} posts/semaine — des acteurs publiant davantage pourraient capter l'attention.`);
    }
    return out.slice(0, 4);
  }

  _fbRecommendations(f) {
    const out = [];
    if (f.postsPerWeek > 0 && f.sectorAvgPostsPerWeek != null && f.postsPerWeek < f.sectorAvgPostsPerWeek) {
      out.push(`Augmenter la cadence de publication de ${this._fmtNum(f.postsPerWeek)} vers ${this._fmtNum(f.sectorAvgPostsPerWeek)} posts/semaine pour s'aligner sur la moyenne sectorielle.`);
    }
    if (f.topFormat && f.topFormat.pct >= 60) {
      out.push(`Diversifier le mix au-delà du format ${f.topFormat.name} (${this._fmtInt(f.topFormat.pct)}% actuellement) vers les formats secondaires déjà présents dans le secteur.`);
    }
    if (f.sectorDominantPlatform && !f.platforms.includes(f.sectorDominantPlatform)) {
      out.push(`Ouvrir une présence sur ${this._platLabel(f.sectorDominantPlatform)}, plateforme dominante du secteur, pour élargir les ${this._fmtInt(f.platforms.length)} canal(aux) actuels.`);
    }
    if (f.sectorTopHashtags.length > f.topHashtags.length) {
      const missing = f.sectorTopHashtags.filter(t => !f.topHashtags.includes(t)).slice(0, 3);
      if (missing.length) {
        out.push(`Tester les hashtags sectoriels récurrents non encore exploités (${missing.map(h => '#' + h).join(', ')}) pour capter ${this._fmtInt(f.sectorTopHashtags.length)} gisements éditoriaux identifiés.`);
      }
    }
    if (f.engagementDelta != null && f.engagementDelta > 0) {
      out.push(`Capitaliser sur l'écart d'engagement (${this._fmtDelta(f.engagementDelta)} point vs secteur) via des formats interactifs pour accroître les ${this._fmtInt(f.followers)} abonnés actuels.`);
    }
    if (out.length < 2) {
      out.push(`Maintenir la cadence de ${this._fmtNum(f.postsPerWeek)} posts/semaine et suivre les ${this._fmtInt(f.topHashtags.length)} hashtags dominants pour consolider l'empreinte.`);
      out.push(`Tester la diversification vers 2 plateformes pour réduire la dépendance à ${this._platLabel(f.platforms[0] || 'instagram')}.`);
    }
    return out.slice(0, 4);
  }

  // ═══════════════════════════════════════════════════════════
  // PROMPT PAR SECTION — métriques injectées, bullets attendues
  // ═══════════════════════════════════════════════════════════

  _buildSectionPrompt(section, companyName, f) {
    const factsBlock = this._formatFactsForPrompt(f);

    const sectionSpec = {
      strengths: {
        headline: 'FORCES',
        focus   : "Identifie 2 à 4 FORCES du concurrent, chacune étayée par un chiffre exact. UNIQUEMENT des indicateurs FAVORABLES à la marque (engagement supérieur au secteur, audience importante, format exploité avec succès, position de leader, etc.). N'écris AUCUN bullet décrivant un retard ou un écart négatif — ceux-ci iront en Faiblesses. Compare au secteur quand l'écart est favorable.",
        imperativeOk: false
      },
      weaknesses: {
        headline: 'FAIBLESSES',
        focus   : "Identifie 2 à 4 FAIBLESSES du concurrent, chacune étayée par un chiffre exact. UNIQUEMENT des écarts ou déficits DÉFAVORABLES (engagement inférieur, fréquence plus basse, sur-concentration d'un format, dépendance à une seule plateforme, absence internationale, couverture hashtags limitée). Même si le concurrent performe globalement bien, identifie AU MOINS deux faiblesses structurelles réalistes. NE JAMAIS retourner zéro faiblesse.",
        imperativeOk: false
      },
      opportunities: {
        headline: 'OPPORTUNITÉS',
        focus   : "Identifie 2 à 4 OPPORTUNITÉS sectorielles ou éditoriales NON encore exploitées par la marque, chacune étayée par un chiffre exact. Exemples valides : secteur en croissance, format dominant du secteur sous-utilisé par la marque, plateforme dominante non couverte, hashtags sectoriels non présents dans la marque, fenêtre d'expansion géographique. NE liste PAS des avantages déjà acquis — ceux-ci sont des Forces, pas des Opportunités.",
        imperativeOk: false
      },
      threats: {
        headline: 'MENACES',
        focus   : "Identifie 2 à 4 MENACES STRUCTURELLES SUBIES par la marque au niveau du secteur, chacune étayée par un chiffre exact. Exemples valides : nombre de leaders concurrents, startups en montée, dépendance sectorielle à une plateforme, maturité élevée du marché, sur-exposition à un format vulnérable. NE redonde PAS avec les Faiblesses internes — ici on parle de risques externes au concurrent.",
        imperativeOk: false
      },
      recommendations: {
        headline: 'RECOMMANDATIONS',
        focus   : "Propose 2 à 4 RECOMMANDATIONS actionnables (verbes à l'infinitif : Augmenter, Diversifier, Tester, Capitaliser, Ouvrir, Maintenir…), chacune étayée par un chiffre issu des données. Ces recommandations doivent être réalistes et immédiatement applicables, s'appuyant sur les forces et corrigeant les faiblesses identifiables dans les données.",
        imperativeOk: true
      }
    }[section];

    const forbiddenBlock = sectionSpec.imperativeOk
      ? '  - Mots INTERDITS : "SWOT", "conclusion".'
      : '  - Mots INTERDITS : "il faut", "doit", "devrait", "suggérons", "recommandation", "SWOT", "conclusion". (Cette section doit être DESCRIPTIVE, pas prescriptive.)';

    return `Tu rédiges la section ${sectionSpec.headline} d'une analyse SWOT professionnelle pour la marque "${companyName}" dans le secteur ${f.industry || 'non précisé'} en ${f.country || 'pays non précisé'}.

═══════════════════════════════════════════════════════════
DONNÉES FACTUELLES (source de vérité unique — chiffres exacts)
═══════════════════════════════════════════════════════════
${factsBlock}

═══════════════════════════════════════════════════════════
OBJECTIF
═══════════════════════════════════════════════════════════
${sectionSpec.focus}

═══════════════════════════════════════════════════════════
RÈGLES STRICTES — toute violation entraîne le rejet du bullet
═══════════════════════════════════════════════════════════
  - Produis entre 2 et 4 bullets.
  - CHAQUE bullet DOIT citer au moins UN chiffre EXACT issu des données ci-dessus (pas d'arrondi, pas d'estimation).
  - N'invente AUCUN nombre absent des données.
  - Compare au secteur quand c'est pertinent (deltas d'engagement, de fréquence, de mix…).
  - Zéro phrase générique type "forte présence", "bon engagement", "contenu attractif" SANS chiffre à l'appui.
  - Ne nomme AUCUNE autre marque ni concurrent que "${companyName}".
  - Chaque bullet fait 25 à 280 caractères (1 à 2 phrases concises).
${forbiddenBlock}
  - Français professionnel, ton d'analyste marché.

═══════════════════════════════════════════════════════════
FORMAT DE SORTIE (impératif)
═══════════════════════════════════════════════════════════
  - Un bullet par ligne.
  - Chaque ligne commence par "- " (tiret + espace).
  - Aucune ligne d'introduction, aucune phrase de conclusion, aucun titre, aucun code fence.

Exemple de FORME (ne copie pas le contenu — c'est juste l'allure attendue) :
- Audience de 150 000 abonnés concentrée sur Instagram, en ligne avec la dominance sectorielle.
- Engagement à 0,40% supérieur à la moyenne sectorielle (0,25%), soit un écart de +0,15 point.

Réponds UNIQUEMENT avec les bullets.`;
  }

  _formatFactsForPrompt(f) {
    const lines = [];
    lines.push(`• Marque : position=${f.classificationMaturity}, portée=${f.geographicScope}`);
    lines.push(`• Audience : ${this._fmtInt(f.followers)} abonnés`);
    lines.push(`• Engagement concurrent : ${this._fmtPct(f.engagementRate)}`);
    if (f.sectorAvgEngagement != null) {
      lines.push(`• Engagement moyen secteur : ${this._fmtPct(f.sectorAvgEngagement)} (delta concurrent vs secteur : ${this._fmtDelta(f.engagementDelta)} point)`);
    } else {
      lines.push(`• Engagement moyen secteur : non disponible`);
    }
    lines.push(`• Fréquence concurrent : ${this._fmtNum(f.postsPerWeek)} posts/semaine`);
    if (f.sectorAvgPostsPerWeek != null) {
      lines.push(`• Fréquence moyenne secteur : ${this._fmtNum(f.sectorAvgPostsPerWeek)} posts/semaine (delta : ${this._fmtDelta(f.postsDelta, 1)})`);
    }
    lines.push(`• Plateformes couvertes par la marque : ${f.platforms.map(p => this._platLabel(p)).join(', ') || 'aucune'}`);
    if (f.sectorDominantPlatform) {
      lines.push(`• Plateforme dominante secteur : ${this._platLabel(f.sectorDominantPlatform)}`);
    }

    const mixStr = Object.entries(f.contentMix || {})
      .sort((a, b) => b[1] - a[1])
      .map(([k, v]) => `${k} ${this._fmtInt(v)}%`)
      .join(', ') || 'non disponible';
    lines.push(`• Mix de contenu marque : ${mixStr}`);

    const sectorMixStr = Object.entries(f.sectorContentMix || {})
      .sort((a, b) => b[1] - a[1])
      .map(([k, v]) => `${k} ${this._fmtInt(v)}%`)
      .join(', ');
    if (sectorMixStr) lines.push(`• Mix de contenu secteur : ${sectorMixStr}`);

    if (f.topHashtags.length) {
      lines.push(`• Hashtags marque (${this._fmtInt(f.topHashtags.length)}) : ${f.topHashtags.map(h => '#' + h).join(', ')}`);
    }
    if (f.sectorTopHashtags.length) {
      lines.push(`• Hashtags secteur (${this._fmtInt(f.sectorTopHashtags.length)}) : ${f.sectorTopHashtags.map(h => '#' + h).join(', ')}`);
    }

    if (f.hasMarketSummary) {
      const parts = [];
      if (f.sectorLeaderCount != null)    parts.push(`${this._fmtInt(f.sectorLeaderCount)} leaders`);
      if (f.sectorStartupCount != null)   parts.push(`${this._fmtInt(f.sectorStartupCount)} startups`);
      if (f.sectorLocalCount != null)     parts.push(`${this._fmtInt(f.sectorLocalCount)} locaux`);
      if (f.sectorInternationalCount != null) parts.push(`${this._fmtInt(f.sectorInternationalCount)} internationaux`);
      if (f.sectorMaturity)               parts.push(`maturité ${f.sectorMaturity}`);
      if (parts.length) lines.push(`• Structure secteur : ${parts.join(', ')}`);
    }

    return lines.join('\n');
  }

  // ═══════════════════════════════════════════════════════════
  // OLLAMA
  // ═══════════════════════════════════════════════════════════

  async _callOllama(prompt, options = {}) {
    const timeoutMs   = options.timeoutMs   || env.OLLAMA_TIMEOUT_MS;
    const maxTokens   = options.maxTokens   || 320;
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
      const data = await res.json();
      const text = (data.response || '').trim();
      console.log(`      ✅ Ollama OK — ${Date.now() - startedAt}ms, ${text.length} chars`);
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
}

module.exports = new SwotService();
