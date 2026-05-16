// backend/src/services/classificationGemini.service.js
// Classification via Gemini 2.0 Flash (free tier)

const GEMINI_URL = 'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent';

const VALID_CATEGORIES = ['local_leader', 'local_startup', 'international_leader', 'international_startup'];

function buildPrompt(competitor, project) {
  const username =
    competitor.socialMedia?.instagram?.username ||
    competitor.socialMedia?.facebook?.username ||
    competitor.companyName;

  const followers =
    competitor.metrics?.totalFollowers ||
    (competitor.socialMedia?.instagram?.followers || 0) +
    (competitor.socialMedia?.facebook?.followers || 0) +
    (competitor.socialMedia?.linkedin?.followers || 0);

  const engagementRate = competitor.metrics?.avgEngagementRate || 0;

  const bio = (competitor.description || '')
    .replace(/\s+/g, ' ')
    .trim()
    .substring(0, 400);

  const country = competitor.country || project?.targetCountry || 'Unknown';

  const isLocal =
    !bio.toLowerCase().includes('international') &&
    !bio.toLowerCase().includes('worldwide') &&
    !bio.toLowerCase().includes('global') &&
    !bio.toLowerCase().includes('across') &&
    followers < 500_000;

  return `You are a marketing intelligence expert. Classify this competitor for a ${project?.industry || 'business'} project targeting ${project?.targetCountry || 'local'} market.

Competitor:
- Name/Username: ${username}
- Total Followers: ${followers.toLocaleString()}
- Engagement Rate: ${engagementRate}%
- Country: ${country}
- Bio: ${bio || 'No description'}
- Appears local: ${isLocal}

Classification categories:
- "local_leader": Established, dominant brand in their local/national market. Followers typically >10K, well-known locally.
- "local_startup": Small or new local business. Followers typically <10K, recently started or niche.
- "international_leader": Major brand operating in multiple countries. Large following (>100K) or explicitly global/international presence.
- "international_startup": Growing brand expanding across borders but not yet a major player.

Decision rules:
1. Followers >500K → international_leader
2. Mentions "worldwide", "global", "X countries" in bio → international
3. Followers 10K–500K + local market focus → local_leader
4. Followers <10K + local market → local_startup
5. When unsure → local_startup

Respond ONLY with valid JSON, no other text:
{
  "classification": "local_leader" or "local_startup" or "international_leader" or "international_startup",
  "confidence": 0-100,
  "reason": "one sentence"
}`;
}

async function classifyCompetitor(competitor, project) {
  const apiKey = process.env.GEMINI_API_KEY;
  if (!apiKey) throw new Error('GEMINI_API_KEY manquant dans .env');

  const prompt = buildPrompt(competitor, project);

  const response = await fetch(`${GEMINI_URL}?key=${apiKey}`, {
    method : 'POST',
    headers: { 'Content-Type': 'application/json' },
    body   : JSON.stringify({
      contents       : [{ parts: [{ text: prompt }] }],
      generationConfig: { temperature: 0.1, maxOutputTokens: 200 }
    })
  });

  if (!response.ok) {
    const errText = await response.text();
    throw new Error(`Gemini ${response.status}: ${errText.substring(0, 200)}`);
  }

  const data = await response.json();
  const raw  = data.candidates?.[0]?.content?.parts?.[0]?.text || '';

  const jsonMatch = raw.match(/\{[\s\S]*?\}/);
  if (!jsonMatch) throw new Error(`Pas de JSON dans la réponse Gemini: ${raw.substring(0, 100)}`);

  const parsed = JSON.parse(jsonMatch[0]);

  if (!VALID_CATEGORIES.includes(parsed.classification)) {
    throw new Error(`Catégorie invalide: ${parsed.classification}`);
  }

  return {
    classification: parsed.classification,
    confidence    : Math.max(0, Math.min(100, Number(parsed.confidence) || 50)),
    reason        : (parsed.reason || '').substring(0, 490)
  };
}

module.exports = { classifyCompetitor };
