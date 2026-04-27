import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { generateSwot, getSwot } from './api';

export const swotKey = (competitorId: string | undefined) =>
  ['swot', competitorId] as const;

export function useSwot(competitorId: string | undefined) {
  return useQuery({
    queryKey: swotKey(competitorId),
    queryFn: () => getSwot(competitorId!),
    enabled: !!competitorId,
    staleTime: 60_000
  });
}

export function useGenerateSwot(competitorId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => generateSwot(competitorId!),
    onSuccess: (data) => {
      qc.setQueryData(swotKey(competitorId), data);
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: swotKey(competitorId) });
    }
  });
}
