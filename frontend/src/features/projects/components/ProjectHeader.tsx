import { useTranslation } from 'react-i18next';
import { FiArrowLeft, FiCalendar, FiTag } from 'react-icons/fi';
import { Link } from '@tanstack/react-router';
import type { ProjectDetail, ProjectStatus } from '../types';

type Props = { project: ProjectDetail };

const STATUS_TONES: Record<ProjectStatus, string> = {
  draft: 'bg-slate-100 text-slate-700',
  active: 'bg-emerald-50 text-emerald-700',
  completed: 'bg-brand-50 text-brand-700',
  archived: 'bg-amber-50 text-amber-700'
};

export function ProjectHeader({ project }: Props) {
  const { t, i18n } = useTranslation();
  const status = (project.status ?? 'draft') as ProjectStatus;
  const created = project.createdAt
    ? new Date(project.createdAt).toLocaleDateString(i18n.language, {
        year: 'numeric',
        month: 'short',
        day: 'numeric'
      })
    : '—';
  const category = project.marketCategory ?? project.industry ?? '—';
  const title = project.name?.trim() || project.businessIdea;

  return (
    <div className="card space-y-3">
      <Link
        to="/projects"
        className="inline-flex items-center gap-1 text-xs text-slate-500 hover:text-slate-800"
      >
        <FiArrowLeft /> {t('projects.detail.backToList')}
      </Link>

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold text-slate-900 truncate">{title}</h1>
          {project.description ? (
            <p className="text-slate-600 mt-1 max-w-2xl">{project.description}</p>
          ) : (
            <p className="text-slate-500 mt-1 max-w-2xl">{project.businessIdea}</p>
          )}
        </div>
        <span className={`text-xs px-2 py-1 rounded-full font-medium ${STATUS_TONES[status]}`}>
          {t(`projects.detail.status.${status}`)}
        </span>
      </div>

      <div className="flex flex-wrap gap-4 text-xs text-slate-500 pt-2 border-t border-slate-100">
        <span className="inline-flex items-center gap-1">
          <FiTag /> {t('projects.detail.category')}: <strong className="text-slate-700">{category}</strong>
        </span>
        <span className="inline-flex items-center gap-1">
          <FiCalendar /> {t('projects.detail.createdAt')}: <strong className="text-slate-700">{created}</strong>
        </span>
        {typeof project.competitorsCount === 'number' && (
          <span className="inline-flex items-center gap-1">
            {t('projects.detail.competitorsCount', { count: project.competitorsCount })}
          </span>
        )}
      </div>
    </div>
  );
}
