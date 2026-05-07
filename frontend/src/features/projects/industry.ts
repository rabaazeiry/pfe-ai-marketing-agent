import type { IndustryKey } from './types';

const SUPPORTED: IndustryKey[] = ['hotels', 'restaurants', 'beauty', 'fashion', 'patisserie'];

/**
 * Map a project's free-form `industry` / `marketCategory` string to one of the
 * 5 RAG industries we have insights for. Returns `null` when no match.
 *
 * Project values seen in the codebase: "Fashion & Retail", "Tourism & Hotels",
 * "Restaurants", "Beauty", "Patisserie", etc.
 */
export function normalizeIndustry(...candidates: Array<string | null | undefined>): IndustryKey | null {
  for (const raw of candidates) {
    if (!raw) continue;
    const s = raw.toLowerCase().trim();

    if (SUPPORTED.includes(s as IndustryKey)) return s as IndustryKey;

    if (s.includes('hotel') || s.includes('tourism') || s.includes('hospitality')) return 'hotels';
    if (s.includes('restaurant') || s.includes('food') || s.includes('catering')) return 'restaurants';
    if (s.includes('beauty') || s.includes('cosmetic') || s.includes('skincare')) return 'beauty';
    if (s.includes('patisserie') || s.includes('pastry') || s.includes('bakery') || s.includes('boulangerie')) return 'patisserie';
    if (s.includes('fashion') || s.includes('retail') || s.includes('apparel') || s.includes('clothing')) return 'fashion';
  }
  return null;
}
