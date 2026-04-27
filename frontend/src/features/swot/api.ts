import { api } from '@/lib/api/client';
import type { SwotAnalysis } from './types';

function isMissing(err: unknown): boolean {
  const status = (err as { response?: { status?: number } })?.response?.status;
  return status === 404;
}

/** GET /api/swot/competitor/:competitorId — null if never generated. */
export async function getSwot(competitorId: string): Promise<SwotAnalysis | null> {
  try {
    const { data } = await api.get<{ success: boolean; data: SwotAnalysis }>(
      `/swot/competitor/${competitorId}`
    );
    return data.data ?? null;
  } catch (err) {
    if (isMissing(err)) return null;
    throw err;
  }
}

/** POST /api/swot/competitor/:competitorId/generate — blocks ~60-120s. */
export async function generateSwot(competitorId: string): Promise<SwotAnalysis> {
  const { data } = await api.post<{ success: boolean; data: SwotAnalysis }>(
    `/swot/competitor/${competitorId}/generate`
  );
  return data.data;
}
