import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { useNavigate } from '@tanstack/react-router';
import { FiPlus, FiZap } from 'react-icons/fi';
import { listProjects, triggerWsDemo } from '@/features/projects/api';
import { useSocket } from '@/hooks/useSocket';
import { WS_EVENTS, type ScrapingProgress } from '@/lib/ws/events';

export function ProjectsPage() {
  const { t } = useTranslation();
  const { data: projects, isLoading } = useQuery({ queryKey: ['projects'], queryFn: listProjects });
  const navigate = useNavigate();
  const [demoProjectId, setDemoProjectId] = useState<string>('demo');
  const [progress, setProgress] = useState<{ pct: number; message: string } | null>(null);
  const { on } = useSocket(demoProjectId);

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
        <button className="btn-primary">
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

      <div className="card overflow-x-auto">
        {isLoading ? (
          <div className="text-sm text-slate-500">{t('common.loading')}</div>
        ) : !projects || projects.length === 0 ? (
          <div className="text-sm text-slate-500">{t('projects.empty')}</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-start text-xs uppercase tracking-wide text-slate-500 border-b">
                <th className="py-2 text-start">{t('projects.table.idea')}</th>
                <th className="text-start">{t('projects.table.category')}</th>
                <th className="text-start">{t('projects.table.status')}</th>
                <th className="text-start">{t('projects.table.pipeline')}</th>
              </tr>
            </thead>
            <tbody>
              {projects.map((p) => (
                <tr
                  key={p._id}
                  className="border-b last:border-0 hover:bg-slate-50 cursor-pointer"
                  onClick={() => navigate({ to: '/projects/$projectId', params: { projectId: p._id } })}
                >
                  <td className="py-3 font-medium text-slate-800">{p.businessIdea}</td>
                  <td className="text-slate-600">{p.marketCategory ?? '—'}</td>
                  <td className="text-slate-600">{p.status ?? '—'}</td>
                  <td className="text-slate-600">{p.pipelineStatus ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
