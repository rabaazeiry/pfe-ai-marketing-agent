// backend/src/services/extraction.service.js
// VERSION 9 — Dynamic industry (multi-sector)

const Groq = require('groq-sdk');

class ExtractionService {

  constructor() {
    this.groq          = new Groq({ apiKey: process.env.GROQ_API_KEY });
    this.primaryModel  = 'llama-3.3-70b-versatile';
    this.fallbackModel = 'llama-3.1-8b-instant';
    this.maxRetries    = 2;
    this.timeoutMs     = 30000;
  }

  async extractProjectInfo(businessIdea, marketCategory, competitorsHint = [], targetCountry = 'Tunisie') {
    let lastError;

    for (let attempt = 1; attempt <= this.maxRetries; attempt++) {
      const model = attempt === 1 ? this.primaryModel : this.fallbackModel;

      try {
        console.log(`🤖 Extraction LLM — tentative ${attempt}/${this.maxRetries} (${model})`);

        const extracted = await this._callGroq(businessIdea, marketCategory, competitorsHint, targetCountry, model);

        // When marketCategory is empty, trust the LLM's detected industry
        extracted.industry        = marketCategory.trim() || extracted.industry || 'General';
        extracted.country         = targetCountry.trim() || 'Tunisie';
        extracted.marketCategory  = marketCategory.trim() || extracted.industry;
        extracted.competitorsHint = competitorsHint;

        // Enrich queries with competitor hints only
        const catForHints = extracted.marketCategory || extracted.industry || '';
        extracted.searchQueries = this._enrichWithHints(extracted.searchQueries, competitorsHint, catForHints);

        this._validate(extracted);

        console.log('✅ Extraction LLM réussie:', extracted.name);
        console.log(`   industry       : ${extracted.industry}`);
        console.log(`   marketCategory : ${extracted.marketCategory}`);
        console.log(`   country        : ${extracted.country}`);
        console.log(`   keywords       : ${extracted.keywords.slice(0, 5).join(', ')}...`);
        console.log(`   → ${extracted.searchQueries.length} queries`);
        return extracted;

      } catch (error) {
        lastError = error;
        console.warn(`⚠️ Tentative ${attempt} échouée (${model}):`, error.message);
        if (error.status === 429) console.log('   → Rate limit, switch fallback...');
      }
    }

    throw new Error(`Extraction échouée après ${this.maxRetries} tentatives: ${lastError.message}`);
  }

  // ═══════════════════════════════════════════════════════
  // ENRICHISSEMENT — hints utilisateur seulement
  // ═══════════════════════════════════════════════════════

  _enrichWithHints(llmQueries, competitorsHint, marketCategory) {
    const hintQueries = competitorsHint.map(name =>
      `${name} ${marketCategory.toLowerCase()} instagram`
    );
    return [...new Set([...llmQueries, ...hintQueries])].slice(0, 20);
  }

  // ═══════════════════════════════════════════════════════
  // APPEL GROQ
  // ═══════════════════════════════════════════════════════

  async _callGroq(businessIdea, marketCategory, competitorsHint, targetCountry, model) {
    const response = await Promise.race([
      this.groq.chat.completions.create({
        model,
        messages: [
          { role: 'system', content: this._buildSystemPrompt(marketCategory, targetCountry) },
          { role: 'user',   content: this._buildUserPrompt(businessIdea, marketCategory, competitorsHint, targetCountry) },
        ],
        response_format: { type: 'json_object' },
        temperature: 0.2,
        max_tokens: 1024,
      }),
      new Promise((_, reject) =>
        setTimeout(() => reject(new Error('Timeout Groq API')), this.timeoutMs)
      ),
    ]);

    return this._parseJSON(response.choices[0].message.content, marketCategory, targetCountry);
  }

  // ═══════════════════════════════════════════════════════
  // SYSTEM PROMPT — générique par industrie
  // ═══════════════════════════════════════════════════════

  _buildSystemPrompt(marketCategory, targetCountry) {
    const autoDetect = !marketCategory || !marketCategory.trim();
    const industryLine = autoDetect
      ? `INDUSTRIE : Détecte-la toi-même depuis la description du projet et indique-la dans le champ "industry" du JSON.`
      : `INDUSTRIE CIBLE : ${marketCategory}`;

    return `Tu es un expert en marketing digital et en analyse de marché au ${targetCountry}.

OBJECTIF : Analyser un projet business et générer des données structurées pour identifier des concurrents sur Instagram et Facebook.

${industryLine}
PAYS CIBLE : ${targetCountry}

RÈGLES JSON STRICTES :
- projectName : nom court et percutant pour le projet (2-5 mots)
- industry : ${autoDetect ? 'nomme l\'industrie détectée (ex: "Fashion", "Restauration", "Beauté")' : `recopie exactement "${marketCategory}"`}
- keywords : 8-12 mots-clés pertinents pour ce secteur. Courts, sans stopwords, sans noms propres.
- searchQueries : 8-12 requêtes pour trouver des pages/comptes concurrents. Format : "nom_concurrent industrie instagram" ou "nom_concurrent ${targetCountry.toLowerCase()} facebook". Utilise des vrais noms d'entreprises.
- industryTerms : 5-8 mots qu'on trouve dans les URLs ou noms de comptes sociaux du secteur
- targetAudience : 3-5 segments de clients cibles réalistes
- languages : langues utilisées dans ce marché (tableau JSON, ex: ["fr", "ar", "en"])

INTERDIT ABSOLUMENT :
❌ Agrégateurs, répertoires, plateformes de réservation (booking, tripadvisor, yelp...)
❌ Réseaux sociaux génériques (facebook.com, instagram.com) comme searchQuery
❌ Inventer des noms de concurrents fictifs

Réponds UNIQUEMENT en JSON valide, sans texte avant ou après.`;
  }

  // ═══════════════════════════════════════════════════════
  // USER PROMPT — paramétrique
  // ═══════════════════════════════════════════════════════

  _buildUserPrompt(businessIdea, marketCategory, competitorsHint, targetCountry) {
    const autoDetect = !marketCategory || !marketCategory.trim();
    let prompt = `Projet à analyser :

Business Idea : ${businessIdea}
Industrie     : ${autoDetect ? '[détecter depuis la description]' : marketCategory}
Pays cible    : ${targetCountry}`;

    if (competitorsHint.length > 0) {
      prompt += `\nConcurrents connus : ${competitorsHint.join(', ')}
→ Intègre absolument ces noms dans les searchQueries`;
    }

    prompt += `

Génère le JSON suivant (adapté au secteur ${marketCategory} au ${targetCountry}) :
{
  "projectName": "Nom du Projet ${marketCategory}",
  "industry": "${marketCategory}",
  "keywords": ["mot1", "mot2", "mot3", "mot4", "mot5"],
  "searchQueries": [
    "concurrent1 ${marketCategory.toLowerCase()} instagram",
    "concurrent2 ${targetCountry.toLowerCase()} facebook",
    "meilleur ${marketCategory.toLowerCase()} ${targetCountry.toLowerCase()} instagram"
  ],
  "industryTerms": ["terme1", "terme2", "terme3"],
  "targetAudience": ["Segment 1", "Segment 2", "Segment 3"],
  "languages": ["fr", "ar", "en"]
}

Retourne UNIQUEMENT le JSON valide.`;

    return prompt;
  }

  // ═══════════════════════════════════════════════════════
  // PARSE + VALIDATE
  // ═══════════════════════════════════════════════════════

  _parseJSON(content, marketCategory, targetCountry) {
    try {
      const jsonMatch = content.match(/\{[\s\S]*\}/);
      const parsed = JSON.parse(jsonMatch ? jsonMatch[0] : content);
      return {
        name           : (parsed.projectName || parsed.name || '').trim(),
        // When marketCategory is empty, use what the LLM detected
        industry       : marketCategory.trim() || parsed.industry || 'General',
        country        : targetCountry  || 'Tunisie',
        marketCategory : marketCategory.trim() || parsed.industry || '',
        keywords       : (parsed.keywords || []).map(k => k.trim().toLowerCase()).filter(k => k.length > 1),
        searchQueries  : parsed.searchQueries || [],
        industryTerms  : (parsed.industryTerms || []).map(t => t.trim().toLowerCase()).filter(t => t.length > 1),
        targetAudience : parsed.targetAudience || [],
        languages      : parsed.languages || ['fr', 'ar', 'en'],
        competitorsHint: [],
      };
    } catch (error) {
      throw new Error(`Parse JSON échoué: ${error.message}`);
    }
  }

  _validate(data) {
    const errors = [];
    if (!data.name || data.name.length < 2)                                    errors.push('name manquant');
    if (!Array.isArray(data.keywords)      || data.keywords.length < 4)        errors.push('keywords insuffisants');
    if (!Array.isArray(data.searchQueries) || data.searchQueries.length < 4)   errors.push('searchQueries insuffisants');
    if (!Array.isArray(data.targetAudience)|| data.targetAudience.length < 1)  errors.push('targetAudience manquant');
    if (!Array.isArray(data.languages)     || data.languages.length < 1)       errors.push('languages manquant');
    if (errors.length > 0) throw new Error(`Validation échouée: ${errors.join(', ')}`);
  }
}

module.exports = new ExtractionService();
