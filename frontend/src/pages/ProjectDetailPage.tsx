import { useEffect, useMemo } from 'react';
import { useParams } from '@tanstack/react-router';
import { useTranslation } from 'react-i18next';
import { useQueryClient } from '@tanstack/react-query';
import { FiActivity, FiAlertTriangle, FiBarChart2, FiPieChart, FiTrendingUp, FiUsers } from 'react-icons/fi';
import { ProjectHeader } from '@/features/projects/components/ProjectHeader';
import { CompetitorsSection } from '@/features/projects/components/CompetitorsSection';
import { PipelineSection } from '@/features/projects/components/PipelineSection';
import { InsightsSection } from '@/features/projects/components/InsightsSection';
import { ProjectDetailSkeleton } from '@/features/projects/components/ProjectDetailSkeleton';
import { ProjectWizard, type WizardStep } from '@/features/projects/components/ProjectWizard';
import { MarketResearchSection } from '@/features/marketResearch/components/MarketResearchSection';
import { SwotSection } from '@/features/swot/components/SwotSection';
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

  const steps = useMemo<WizardStep[]>(
    () => [
      {
        id: 'pipeline',
        labelKey: 'projects.detail.tabs.pipeline',
        icon: <FiActivity />,
        render: () => project.data ? <PipelineSection project={project.data} /> : null
      },
      {
        id: 'insights',
        labelKey: 'projects.detail.tabs.insights',
        icon: <FiTrendingUp />,
        render: () => (
          <InsightsSection
            insights={insights.data}
            isLoading={insights.isLoading}
            isError={insights.isError}
          />
        )
      },
      {
        id: 'market',
        labelKey: 'projects.detail.tabs.market',
        icon: <FiBarChart2 />,
        render: () => <MarketResearchSection projectId={projectId} />
      },
      {
        id: 'swot',
        labelKey: 'projects.detail.tabs.swot',
        icon: <FiPieChart />,
        render: () => <SwotSection projectId={projectId} />
      },
      {
        id: 'competitors',
        labelKey: 'projects.detail.tabs.competitors',
        icon: <FiUsers />,
        render: () => (
          <CompetitorsSection
            projectId={projectId}
            competitors={competitors.data}
            isLoading={competitors.isLoading}
            isError={competitors.isError}
          />
        )
      }
    ],
    [
      projectId,
      project.data,
      insights.data,
      insights.isLoading,
      insights.isError,
      competitors.data,
      competitors.isLoading,
      competitors.isError
    ]
  );

  if (project.isLoading) {
    return <ProjectDetailSkeleton />;
  }

  if (project.isError || !project.data) {
    return (
      <div className="card">
        <div className="py-12 px-6 flex flex-col items-center text-center gap-3">
          <div className="h-12 w-12 rounded-full bg-red-50 text-red-600 flex items-center justify-center">
            <FiAlertTriangle className="h-6 w-6" />
          </div>
          <div>
            <div className="text-sm font-semibold text-slate-800">{t('projects.detail.errors.title')}</div>
            <p className="mt-1 text-xs text-slate-500 max-w-sm">{t('projects.detail.errors.project')}</p>
          </div>
          <button
            type="button"
            className="btn-ghost"
            onClick={() => project.refetch()}
            disabled={project.isFetching}
          >
            {project.isFetching ? t('common.loading') : t('common.retry')}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-5xl">
      <ProjectHeader project={project.data} />
      <ProjectWizard steps={steps} storageKey={`project:${projectId}:wizardTab`} />
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
