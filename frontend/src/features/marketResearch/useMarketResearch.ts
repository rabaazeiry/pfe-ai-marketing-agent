import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { generateMarketResearch, getMarketResearch } from './api';

export const marketResearchKey = (projectId: string | undefined) =>
  ['market-research', projectId] as const;

export function useMarketResearch(projectId: string | undefined) {
  return useQuery({
    queryKey: marketResearchKey(projectId),
    queryFn: () => getMarketResearch(projectId!),
    enabled: !!projectId,
    staleTime: 60_000
  });
}

export function useGenerateMarketResearch(projectId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => generateMarketResearch(projectId!),
    onSuccess: (data) => {
      qc.setQueryData(marketResearchKey(projectId), data);
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: marketResearchKey(projectId) });
    }
  });
}
