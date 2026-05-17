import { api } from '@/lib/api/client';
import type {
  CampaignBundle,
  CompetitorSummary,
  IndustryInsightsBundle,
  IndustryKey,
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

/**
 * GET /insights/:industry — returns the RAG-generated insights bundle
 * (5 questions x 5 insights) for one of the supported industries.
 * Returns null on 404 so the UI can show an empty state.
 */
export async function getInsightsByIndustry(
  industry: IndustryKey
): Promise<IndustryInsightsBundle | null> {
  try {
    const { data } = await api.get<{ success: boolean; data: IndustryInsightsBundle }>(
      `/insights/${industry}`
    );
    return data.data;
  } catch (err) {
    if (isMissingEndpoint(err)) return null;
    throw err;
  }
}

/**
 * POST /insights/:industry/regenerate — runs the Python script synchronously
 * (~2-3 min) and returns the freshly generated insights bundle.
 */
export async function regenerateIndustryInsights(
  industry: IndustryKey
): Promise<IndustryInsightsBundle> {
  const { data } = await api.post<{ success: boolean; data: IndustryInsightsBundle }>(
    `/insights/${industry}/regenerate`,
    null,
    { timeout: 10 * 60 * 1000 } // 10 min — script takes ~2-3 min
  );
  return data.data;
}

/**
 * GET /campaign/:industry — returns the Step 5 campaign bundle
 * (4-week Prophet-anchored calendar) for one of the supported industries.
 * Returns null on 404/501 so the UI can show an empty state.
 */
export async function getCampaignByIndustry(
  industry: IndustryKey
): Promise<CampaignBundle | null> {
  try {
    const { data } = await api.get<{ success: boolean; data: CampaignBundle }>(
      `/campaign/${industry}`
    );
    return data.data;
  } catch (err) {
    if (isMissingEndpoint(err)) return null;
    throw err;
  }
}

/**
 * POST /campaign/:industry/regenerate — runs the Python campaign generator
 * synchronously (~15 min) and returns the freshly generated campaign bundle.
 */
export async function regenerateCampaign(
  industry: IndustryKey
): Promise<CampaignBundle> {
  const { data } = await api.post<{ success: boolean; data: CampaignBundle }>(
    `/campaign/${industry}/regenerate`,
    null,
    { timeout: 10 * 60 * 1000 } // 10 min — same as insights regenerate
  );
  return data.data;
}

// ─── Classification Gemini — pipeline step 3 ─────────────────────────────────

export type ClassifyResult = {
  competitorId: string;
  companyName: string;
  classification?: string;
  confidence?: number;
  reason?: string;
  error?: string;
};

export async function classifyProject(projectId: string): Promise<{
  classified: number;
  total: number;
  results: ClassifyResult[];
}> {
  const { data } = await api.post<{
    success: boolean;
    classified: number;
    total: number;
    results: ClassifyResult[];
  }>(`/projects/${projectId}/classify`);
  return { classified: data.classified, total: data.total, results: data.results };
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
