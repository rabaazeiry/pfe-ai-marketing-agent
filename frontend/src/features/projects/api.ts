import { api } from '@/lib/api/client';

export type Project = {
  _id: string;
  businessIdea: string;
  name?: string;
  marketCategory?: string;
  industry?: string;
  country?: string;
  targetCountry?: string;
  competitorsCount?: number;
  status?: string;
  pipelineStatus?: string;
  createdAt?: string;
};

export async function listProjects() {
  const { data } = await api.get<{ success: boolean; data: Project[] }>('/projects');
  return data.data ?? [];
}

export async function getProject(id: string) {
  const { data } = await api.get<{ success: boolean; data: Project }>(`/projects/${id}`);
  return data.data;
}

export async function createProject(payload: Partial<Project>) {
  const { data } = await api.post<{ success: boolean; data: Project }>('/projects', payload);
  return data.data;
}

export async function triggerWsDemo(projectId: string, steps = 5) {
  const { data } = await api.post('/ws-demo/emit', { projectId, steps });
  return data;
}
