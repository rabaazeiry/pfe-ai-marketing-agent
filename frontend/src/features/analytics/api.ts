import { api } from '@/lib/api/client';

export type FollowersByBrand = { name: string; followers: number };

export type WeeklyEngagement = {
  week: string;
  weekStart?: string; // 'YYYY-MM-DD' — start of the 7-day window (data-relative anchor)
  values: { brand: string; engagement: number | null }[]; // null = no post that week (gap, not 0)
};

export type AnalyticsOverview = {
  followersByBrand: FollowersByBrand[];
  engagementOverTime: WeeklyEngagement[];
};

export async function getAnalyticsOverview(projectId?: string): Promise<AnalyticsOverview> {
  const { data } = await api.get<{ success: boolean; data: AnalyticsOverview }>(
    '/analytics/overview',
    { params: projectId ? { projectId } : undefined }
  );
  return data.data;
}
