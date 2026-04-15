import { api } from '@/lib/api/client';
import type {
  CompetitorSummary,
  ProjectDetail,
  ProjectInsights
} from './types';

function isMissingEndpoint(err: unknown): boolean {
  const status = (err as { response?: { status?: number } })?.response?.status;
  return status === 404 || status === 501;
}

export async function getProjectDetail(id: string): Promise<ProjectDetail> {
  const { data } = await api.get<{ success: boolean; data: ProjectDetail }>(`/projects/${id}`);
  return data.data;
}

export async function getProjectCompetitors(projectId: string): Promise<CompetitorSummary[]> {
  const { data } = await api.get<{ success: boolean; data: CompetitorSummary[] }>(
    `/competitors/project/${projectId}`
  );
  return data.data ?? [];
}

/**
 * GET /projects/:id/insights — falls back to a deterministic mock if the backend
 * route is not yet implemented. Marked `isMocked` so the UI can disclose it.
 */
export async function getProjectInsights(projectId: string): Promise<ProjectInsights> {
  try {
    const { data } = await api.get<{ success: boolean; data: ProjectInsights }>(
      `/projects/${projectId}/insights`
    );
    return { ...data.data, isMocked: false };
  } catch (err) {
    if (isMissingEndpoint(err)) return buildMockInsights(projectId);
    throw err;
  }
}

function buildMockInsights(projectId: string): ProjectInsights {
  const seed = hashString(projectId);
  const trendDelta = ((seed % 60) / 10) - 2;
  const direction = trendDelta > 0.2 ? 'up' : trendDelta < -0.2 ? 'down' : 'flat';

  return {
    topOpportunity:
      'Short-form video content is under-served by your top 3 competitors — a weekly Reels cadence could capture attention quickly.',
    topCompetitorSignal:
      'The highest-engagement competitor posts promotional carousels on Tuesdays and Thursdays around 18:00 local time.',
    engagementTrend: {
      label: 'Avg. engagement / post (last 4 weeks)',
      direction,
      delta: Number(trendDelta.toFixed(2))
    },
    recommendedAction:
      'Schedule two Reels per week mirroring the top-performing format, and A/B test a promo carousel on Tuesday evenings.',
    generatedAt: new Date().toISOString(),
    isMocked: true
  };
}

function hashString(value: string): number {
  let hash = 0;
  for (let i = 0; i < value.length; i += 1) {
    hash = (hash * 31 + value.charCodeAt(i)) >>> 0;
  }
  return hash;
}
