import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  getInsightsByIndustry,
  getProjectCompetitors,
  getProjectDetail,
  getProjectInsights,
  regenerateIndustryInsights,
} from './detail.api';
import type { IndustryKey } from './types';

export function useProjectDetail(projectId: string | undefined) {
  return useQuery({
    queryKey: ['project', projectId, 'detail'],
    queryFn: () => getProjectDetail(projectId!),
    enabled: !!projectId
  });
}

export function useProjectCompetitors(projectId: string | undefined) {
  return useQuery({
    queryKey: ['project', projectId, 'competitors'],
    queryFn: () => getProjectCompetitors(projectId!),
    enabled: !!projectId
  });
}

export function useProjectInsights(projectId: string | undefined) {
  return useQuery({
    queryKey: ['project', projectId, 'insights'],
    queryFn: () => getProjectInsights(projectId!),
    enabled: !!projectId,
    staleTime: 60_000
  });
}

export function useIndustryInsights(industry: IndustryKey | null) {
  return useQuery({
    queryKey: ['insights', 'industry', industry],
    queryFn: () => getInsightsByIndustry(industry!),
    enabled: !!industry,
    staleTime: 5 * 60_000
  });
}

export function useRegenerateIndustryInsights(industry: IndustryKey | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => regenerateIndustryInsights(industry!),
    onSuccess: (bundle) => {
      // Script ran synchronously — seed the cache immediately with fresh data
      queryClient.setQueryData(['insights', 'industry', industry], bundle);
    },
  });
}
