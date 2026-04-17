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
 * GET /projects/:id/insights — returns null when no insights have been
 * generated yet (backend 404), so the UI can show an empty state.
 */
export async function getProjectInsights(projectId: string): Promise<ProjectInsights | null> {
  try {
    const { data } = await api.get<{ success: boolean; data: ProjectInsights }>(
      `/projects/${projectId}/insights`
    );
    return data.data;
  } catch (err) {
    if (isMissingEndpoint(err)) return null;
    throw err;
  }
}

// ─── Sprint 12: scrape a single competitor via Python /v2/scrape ────────────

export type ScrapeV2Result = {
  competitorId: string;
  companyName: string;
  methodUsed: string | null;
  postsCount: number;
  socialAnalysis: {
    competitor: string;
    postsCount: number;
    totalLikes: number;
    totalComments: number;
    languages: string[];
    samples: { url: string; text: string; likes: number; comments: number }[];
  };
  competitorUpdate: Record<string, { posts: number; likes: number; comments: number }>;
};

export async function scrapeCompetitorV2(competitorId: string): Promise<ScrapeV2Result> {
  const { data } = await api.post<{ success: boolean; data: ScrapeV2Result }>(
    `/scraping/competitor/${competitorId}/scrape-v2`
  );
  return data.data;
}
