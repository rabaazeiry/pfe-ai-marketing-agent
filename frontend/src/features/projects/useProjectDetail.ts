import { useQuery } from '@tanstack/react-query';
import {
  getProjectCompetitors,
  getProjectDetail,
  getProjectInsights
} from './detail.api';

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
