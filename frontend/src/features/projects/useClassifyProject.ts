import { useMutation, useQueryClient } from '@tanstack/react-query';
import { classifyProject } from './detail.api';

export function useClassifyProject(projectId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () => classifyProject(projectId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['project', projectId, 'detail'] });
      queryClient.invalidateQueries({ queryKey: ['project', projectId, 'competitors'] });
    }
  });
}
