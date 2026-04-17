import { useMutation, useQueryClient } from '@tanstack/react-query';
import { scrapeCompetitorV2, type ScrapeV2Result } from './detail.api';

export function useScrapeCompetitor(projectId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (competitorId: string) => scrapeCompetitorV2(competitorId),
    onSuccess: (_data: ScrapeV2Result) => {
      queryClient.invalidateQueries({ queryKey: ['project', projectId, 'competitors'] });
    }
  });
}
