import { useMutation, useQueryClient } from '@tanstack/react-query';
import axios from 'axios';
import { createProject, type Project } from './api';

export type CreateProjectInput = {
  businessIdea: string;
  marketCategory: string;
};

type MockFallbackOptions = {
  onFallback?: (project: Project) => void;
};

function isNetworkOrServerError(err: unknown) {
  if (!axios.isAxiosError(err)) return false;
  if (!err.response) return true;
  return err.response.status >= 500;
}

function buildMockProject(input: CreateProjectInput): Project {
  const now = new Date().toISOString();
  return {
    _id: `mock-${Date.now()}`,
    businessIdea: input.businessIdea,
    marketCategory: input.marketCategory,
    status: 'draft',
    pipelineStatus: 'step1_pending',
    createdAt: now
  };
}

export function useCreateProject(options: MockFallbackOptions = {}) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (input: CreateProjectInput): Promise<Project> => {
      try {
        return await createProject(input);
      } catch (err) {
        if (isNetworkOrServerError(err)) {
          const mock = buildMockProject(input);
          options.onFallback?.(mock);
          return mock;
        }
        throw err;
      }
    },
    onSuccess: (project) => {
      queryClient.setQueryData<Project[]>(['projects'], (prev) => {
        if (!prev) return [project];
        if (prev.some((p) => p._id === project._id)) return prev;
        return [project, ...prev];
      });
      queryClient.invalidateQueries({ queryKey: ['projects'] });
    }
  });
}
