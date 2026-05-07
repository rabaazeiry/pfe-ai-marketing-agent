import { useQuery } from '@tanstack/react-query';
import {
  getInsightsByIndustry,
  getProjectCompetitors,
  getProjectDetail,
  getProjectInsights
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
