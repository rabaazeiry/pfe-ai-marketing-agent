import { useTranslation } from 'react-i18next';
import { FiArrowLeft, FiCalendar, FiTag, FiUsers } from 'react-icons/fi';
import { Link } from '@tanstack/react-router';
import type { ProjectDetail, ProjectStatus } from '../types';
import { projectStatusTone } from '../statusBadge';

type Props = { project: ProjectDetail };

export function ProjectHeader({ project }: Props) {
  const { t, i18n } = useTranslation();
  const status = (project.status ?? 'draft') as ProjectStatus;
  const tone = projectStatusTone(status);
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
    <div className="card space-y-4">
      <Link
        to="/projects"
        className="inline-flex items-center gap-1.5 text-xs font-medium text-slate-500 hover:text-slate-800 transition-colors"
      >
        <FiArrowLeft /> {t('projects.detail.backToList')}
      </Link>

      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <h1 className="text-2xl sm:text-[1.625rem] font-semibold text-slate-900 leading-tight">
            {title}
          </h1>
          {project.description ? (
            <p className="text-slate-600 mt-2 max-w-2xl leading-relaxed">{project.description}</p>
          ) : (
            <p className="text-slate-500 mt-2 max-w-2xl leading-relaxed">{project.businessIdea}</p>
          )}
        </div>
        <span
          className={`inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full font-medium ring-1 ${tone.bg} ${tone.text} ${tone.ring}`}
        >
          <span className={`h-1.5 w-1.5 rounded-full ${tone.dot}`} />
          {t(`projects.detail.status.${status}`)}
        </span>
      </div>

      <div className="flex flex-wrap gap-x-5 gap-y-2 text-xs text-slate-500 pt-3 border-t border-slate-100">
        <MetaItem icon={<FiTag />} label={t('projects.detail.category')} value={category} />
        <MetaItem icon={<FiCalendar />} label={t('projects.detail.createdAt')} value={created} />
        {typeof project.competitorsCount === 'number' && (
          <span className="inline-flex items-center gap-1.5">
            <FiUsers className="text-slate-400" />
            <span>{t('projects.detail.competitorsCount', { count: project.competitorsCount })}</span>
          </span>
        )}
      </div>
    </div>
  );
}

function MetaItem({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="text-slate-400">{icon}</span>
      <span>
        {label}: <strong className="text-slate-700 font-medium">{value}</strong>
      </span>
    </span>
  );
}
