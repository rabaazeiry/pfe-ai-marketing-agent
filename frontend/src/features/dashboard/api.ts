import { api } from '@/lib/api/client';

export type DashboardKpis = {
  projects: number;
  competitors: number;
  postsAnalyzed: number;
  /** null when no analysis has produced an engagement rate yet */
  avgEngagementRate: number | null;
};

export type EngagementByDayPoint = {
  day: string;
  likes: number;
  posts: number;
};

export type ContentMixSlice = {
  name: string;
  value: number;
};

export type DashboardStats = {
  kpis: DashboardKpis;
  charts: {
    engagementByDay: EngagementByDayPoint[];
    contentMix: ContentMixSlice[];
  };
};

export async function getDashboardStats(projectId?: string): Promise<DashboardStats> {
  const { data } = await api.get<{ success: boolean; data: DashboardStats }>(
    '/dashboard/stats',
    { params: projectId ? { projectId } : undefined }
  );
  return data.data;
}
