import { api } from '@/lib/api/client';
import type { MarketResearch } from './types';

function isMissing(err: unknown): boolean {
  const status = (err as { response?: { status?: number } })?.response?.status;
  return status === 404;
}

/**
 * GET /market-research/project/:projectId
 * Returns null if no MarketResearch doc exists yet for this project.
 */
export async function getMarketResearch(projectId: string): Promise<MarketResearch | null> {
  try {
    const { data } = await api.get<{ success: boolean; data: MarketResearch }>(
      `/market-research/project/${projectId}`
    );
    return data.data ?? null;
  } catch (err) {
    if (isMissing(err)) return null;
    throw err;
  }
}

/**
 * POST /market-research/project/:projectId/generate
 * Triggers section-by-section generation on the backend (~60-120s on llama3.1).
 */
export async function generateMarketResearch(projectId: string): Promise<MarketResearch> {
  const { data } = await api.post<{ success: boolean; data: MarketResearch }>(
    `/market-research/project/${projectId}/generate`
  );
  return data.data;
}
