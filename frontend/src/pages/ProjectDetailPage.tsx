import { useEffect } from 'react';
import { useParams } from '@tanstack/react-router';
import { useTranslation } from 'react-i18next';
import { useQueryClient } from '@tanstack/react-query';
import { ProjectHeader } from '@/features/projects/components/ProjectHeader';
import { CompetitorsSection } from '@/features/projects/components/CompetitorsSection';
import { PipelineSection } from '@/features/projects/components/PipelineSection';
import { InsightsSection } from '@/features/projects/components/InsightsSection';
import { StateView } from '@/features/projects/components/StateView';
import {
  useProjectCompetitors,
  useProjectDetail,
  useProjectInsights
} from '@/features/projects/useProjectDetail';
import { useSocket } from '@/hooks/useSocket';
import { WS_EVENTS } from '@/lib/ws/events';

export function ProjectDetailPage() {
  const { t } = useTranslation();
  const { projectId } = useParams({ strict: false }) as { projectId: string };

  const project = useProjectDetail(projectId);
  const competitors = useProjectCompetitors(projectId);
  const insights = useProjectInsights(projectId);

  useLivePipelineRefresh(projectId);

  if (project.isLoading) {
    return (
      <div className="card">
        <StateView variant="loading" title={t('common.loading')} />
      </div>
    );
  }

  if (project.isError || !project.data) {
    return (
      <div className="card">
        <StateView variant="error" title={t('projects.detail.errors.title')}>
          {t('projects.detail.errors.project')}
        </StateView>
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-5xl">
      <ProjectHeader project={project.data} />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <PipelineSection project={project.data} />
        <InsightsSection
          insights={insights.data}
          isLoading={insights.isLoading}
          isError={insights.isError}
        />
      </div>

      <CompetitorsSection
        competitors={competitors.data}
        isLoading={competitors.isLoading}
        isError={competitors.isError}
      />
    </div>
  );
}

/**
 * Re-fetches the project + competitors whenever a scraping WS event fires so
 * the pipeline/competitor states stay live during a run.
 */
function useLivePipelineRefresh(projectId: string) {
  const queryClient = useQueryClient();
  const { on } = useSocket(projectId);

  useEffect(() => {
    const invalidate = () => {
      queryClient.invalidateQueries({ queryKey: ['project', projectId, 'detail'] });
      queryClient.invalidateQueries({ queryKey: ['project', projectId, 'competitors'] });
    };
    const off1 = on(WS_EVENTS.SCRAPING_PROGRESS, invalidate);
    const off2 = on(WS_EVENTS.SCRAPING_COMPLETE, invalidate);
    const off3 = on(WS_EVENTS.SCRAPING_FAILED, invalidate);
    return () => {
      off1();
      off2();
      off3();
    };
  }, [on, projectId, queryClient]);
}
