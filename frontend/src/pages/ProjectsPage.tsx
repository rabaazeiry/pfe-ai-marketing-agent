import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { useNavigate } from '@tanstack/react-router';
import axios from 'axios';
import { FiAlertTriangle, FiChevronRight, FiFolderPlus, FiPlus, FiZap } from 'react-icons/fi';
import { listProjects, triggerWsDemo } from '@/features/projects/api';
import { NewProjectModal } from '@/features/projects/components/NewProjectModal';
import { useCreateProject } from '@/features/projects/useCreateProject';
import {
  formatPipelineLabel,
  pipelineTone,
  projectStatusTone
} from '@/features/projects/statusBadge';
import { useSocket } from '@/hooks/useSocket';
import { WS_EVENTS, type ScrapingProgress } from '@/lib/ws/events';
import { Skeleton } from '@/components/Skeleton';
import { useToast } from '@/components/Toast';

export function ProjectsPage() {
  const { t } = useTranslation();
  const toast = useToast();
  const {
    data: projects,
    isLoading,
    isError,
    refetch,
    isRefetching
  } = useQuery({ queryKey: ['projects'], queryFn: listProjects });
  const navigate = useNavigate();
  const [demoProjectId, setDemoProjectId] = useState<string>('demo');
  const [progress, setProgress] = useState<{ pct: number; message: string } | null>(null);
  const { on } = useSocket(demoProjectId);

  const [isModalOpen, setIsModalOpen] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const createProjectMutation = useCreateProject();

  useEffect(() => {
    const off1 = on(WS_EVENTS.SCRAPING_STARTED, () => setProgress({ pct: 0, message: t('projects.live.starting') }));
    const off2 = on(WS_EVENTS.SCRAPING_PROGRESS, (p: ScrapingProgress) =>
      setProgress({ pct: p.pct, message: p.message ?? p.step })
    );
    const off3 = on(WS_EVENTS.SCRAPING_COMPLETE, () => {
      setProgress({ pct: 100, message: t('projects.live.done') });
      setTimeout(() => setProgress(null), 1500);
    });
    return () => { off1(); off2(); off3(); };
  }, [demoProjectId, on, t]);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">{t('projects.title')}</h1>
          <p className="text-slate-500">{t('projects.subtitle')}</p>
        </div>
        <button
          className="btn-primary"
          onClick={() => {
            setCreateError(null);
            setIsModalOpen(true);
          }}
        >
          <FiPlus /> {t('projects.new')}
        </button>
      </div>

      <div className="card">
        <div className="flex items-center justify-between mb-3">
          <div>
            <h3 className="font-semibold text-slate-900 flex items-center gap-2">
              <FiZap className="text-amber-500" /> {t('projects.live.title')}
            </h3>
            <p className="text-xs text-slate-500">{t('projects.live.subtitle')}</p>
          </div>
          <div className="flex items-center gap-2">
            <input
              className="input max-w-[12rem]"
              value={demoProjectId}
              onChange={(e) => setDemoProjectId(e.target.value)}
              placeholder={t('projects.live.placeholder')}
            />
            <button className="btn-primary" onClick={() => triggerWsDemo(demoProjectId, 6)}>
              {t('projects.live.trigger')}
            </button>
          </div>
        </div>
        {progress ? (
          <div>
            <div className="flex justify-between text-xs text-slate-500 mb-1">
              <span>{progress.message}</span>
              <span>{progress.pct}%</span>
            </div>
            <div className="h-2 bg-slate-100 rounded-full overflow-hidden">
              <div className="h-full bg-brand-600 transition-all duration-300" style={{ width: `${progress.pct}%` }} />
            </div>
          </div>
        ) : (
          <div className="text-xs text-slate-400">{t('projects.live.idle')}</div>
        )}
      </div>

      <div className="card p-0 overflow-hidden">
        {isLoading ? (
          <ProjectsTableSkeleton />
        ) : isError ? (
          <div className="py-14 px-6 flex flex-col items-center text-center gap-3">
            <div className="h-12 w-12 rounded-full bg-red-50 text-red-600 flex items-center justify-center">
              <FiAlertTriangle className="h-6 w-6" />
            </div>
            <div>
              <div className="text-sm font-semibold text-slate-800">{t('projects.errors.loadTitle')}</div>
              <p className="mt-1 text-xs text-slate-500 max-w-sm">{t('projects.errors.loadBody')}</p>
            </div>
            <button
              className="btn-ghost"
              onClick={() => refetch()}
              disabled={isRefetching}
            >
              {isRefetching ? t('common.loading') : t('common.retry')}
            </button>
          </div>
        ) : !projects || projects.length === 0 ? (
          <div className="py-14 px-6 flex flex-col items-center text-center gap-3">
            <div className="h-12 w-12 rounded-full bg-brand-50 text-brand-600 flex items-center justify-center">
              <FiFolderPlus className="h-6 w-6" />
            </div>
            <div>
              <div className="text-sm font-semibold text-slate-800">{t('projects.empty')}</div>
              <p className="mt-1 text-xs text-slate-500 max-w-sm">{t('projects.emptyHint')}</p>
            </div>
            <button
              className="btn-primary mt-1"
              onClick={() => {
                setCreateError(null);
                setIsModalOpen(true);
              }}
            >
              <FiPlus /> {t('projects.new')}
            </button>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs uppercase tracking-wide text-slate-500 bg-slate-50/70 border-b border-slate-100">
                  <th className="py-3 ps-5 pe-3 text-start font-medium">{t('projects.table.idea')}</th>
                  <th className="py-3 px-3 text-start font-medium">{t('projects.table.category')}</th>
                  <th className="py-3 px-3 text-start font-medium">{t('projects.table.status')}</th>
                  <th className="py-3 px-3 text-start font-medium">{t('projects.table.pipeline')}</th>
                  <th className="py-3 pe-5 ps-3 w-10" aria-hidden />
                </tr>
              </thead>
              <tbody>
                {projects.map((p) => {
                  const statusTone = projectStatusTone(p.status);
                  const pipeTone = pipelineTone(p.pipelineStatus);
                  const statusLabel = p.status
                    ? t(`projects.detail.status.${p.status}`, { defaultValue: p.status })
                    : '—';
                  const pipeLabel = formatPipelineLabel(p.pipelineStatus);
                  return (
                    <tr
                      key={p._id}
                      role="button"
                      tabIndex={0}
                      className="group border-b border-slate-100 last:border-0 cursor-pointer transition-colors hover:bg-slate-50/80 focus:bg-slate-50/80 focus:outline-none"
                      onClick={() =>
                        navigate({ to: '/projects/$projectId', params: { projectId: p._id } })
                      }
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.preventDefault();
                          navigate({ to: '/projects/$projectId', params: { projectId: p._id } });
                        }
                      }}
                    >
                      <td className="py-3.5 ps-5 pe-3 font-medium text-slate-800">
                        <span className="line-clamp-2 max-w-xl">{p.businessIdea}</span>
                      </td>
                      <td className="py-3.5 px-3 text-slate-600">{p.marketCategory ?? '—'}</td>
                      <td className="py-3.5 px-3">
                        <span
                          className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ${statusTone.bg} ${statusTone.text} ${statusTone.ring}`}
                        >
                          <span className={`h-1.5 w-1.5 rounded-full ${statusTone.dot}`} />
                          {statusLabel}
                        </span>
                      </td>
                      <td className="py-3.5 px-3">
                        <span
                          className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ${pipeTone.bg} ${pipeTone.text} ${pipeTone.ring}`}
                        >
                          <span className={`h-1.5 w-1.5 rounded-full ${pipeTone.dot}`} />
                          {pipeLabel}
                        </span>
                      </td>
                      <td className="py-3.5 pe-5 ps-3 text-slate-300 group-hover:text-slate-500 transition-colors">
                        <FiChevronRight className="ms-auto" />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <NewProjectModal
        open={isModalOpen}
        isSubmitting={createProjectMutation.isPending}
        errorMessage={createError}
        onClose={() => {
          if (createProjectMutation.isPending) return;
          setIsModalOpen(false);
          setCreateError(null);
        }}
        onSubmit={async (values) => {
          setCreateError(null);
          try {
            const project = await createProjectMutation.mutateAsync(values);
            setIsModalOpen(false);
            toast.success(
              t('projects.create.toasts.successBody', {
                name: project.businessIdea.slice(0, 60)
              }),
              t('projects.create.toasts.successTitle')
            );
          } catch (err) {
            const fallback = t('projects.create.errors.generic');
            const message = axios.isAxiosError(err)
              ? err.response?.data?.message ?? fallback
              : fallback;
            setCreateError(message);
            toast.error(message, t('projects.create.toasts.errorTitle'));
          }
        }}
      />
    </div>
  );
}

function ProjectsTableSkeleton() {
  const rows = 5;
  return (
    <div className="animate-fade-in">
      <div className="flex items-center gap-3 border-b border-slate-100 bg-slate-50/70 py-3 px-5">
        <Skeleton className="h-3 w-32" />
        <Skeleton className="h-3 w-24" />
        <Skeleton className="h-3 w-20" />
        <Skeleton className="h-3 w-28" />
      </div>
      {Array.from({ length: rows }).map((_, i) => (
        <div
          key={i}
          className="grid grid-cols-[1fr_140px_120px_140px_24px] items-center gap-3 border-b border-slate-100 last:border-0 py-4 px-5"
        >
          <Skeleton className="h-3 w-3/4" />
          <Skeleton className="h-3 w-20" />
          <Skeleton className="h-5 w-16 rounded-full" />
          <Skeleton className="h-5 w-24 rounded-full" />
          <Skeleton className="h-3 w-3 rounded-full" />
        </div>
      ))}
    </div>
  );
}
