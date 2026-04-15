import { useTranslation } from 'react-i18next';
import {
  FiArrowDownRight,
  FiArrowUpRight,
  FiMinus,
  FiStar,
  FiTarget,
  FiTrendingUp,
  FiZap
} from 'react-icons/fi';
import type { ProjectInsights } from '../types';
import { StateView } from './StateView';

type Props = {
  insights: ProjectInsights | undefined;
  isLoading: boolean;
  isError: boolean;
};

export function InsightsSection({ insights, isLoading, isError }: Props) {
  const { t } = useTranslation();

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="font-semibold text-slate-900">{t('projects.detail.insights.title')}</h3>
          <p className="text-xs text-slate-500">{t('projects.detail.insights.subtitle')}</p>
        </div>
        {insights?.isMocked && (
          <span className="text-[10px] uppercase tracking-wide bg-amber-50 text-amber-700 px-2 py-0.5 rounded-full">
            {t('projects.detail.insights.previewBadge')}
          </span>
        )}
      </div>

      {isLoading ? (
        <StateView variant="loading" title={t('common.loading')} />
      ) : isError ? (
        <StateView variant="error" title={t('projects.detail.errors.title')}>
          {t('projects.detail.errors.insights')}
        </StateView>
      ) : !insights ? (
        <StateView variant="empty" title={t('projects.detail.insights.empty')} />
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <InsightCard
            icon={<FiStar className="text-amber-500" />}
            label={t('projects.detail.insights.topOpportunity')}
            body={insights.topOpportunity}
          />
          <InsightCard
            icon={<FiTarget className="text-brand-600" />}
            label={t('projects.detail.insights.topCompetitorSignal')}
            body={insights.topCompetitorSignal}
          />
          <TrendCard insights={insights} />
          <InsightCard
            icon={<FiZap className="text-emerald-600" />}
            label={t('projects.detail.insights.recommendedAction')}
            body={insights.recommendedAction}
          />
        </div>
      )}
    </div>
  );
}

function InsightCard({
  icon,
  label,
  body
}: {
  icon: React.ReactNode;
  label: string;
  body: string;
}) {
  return (
    <div className="rounded-xl border border-slate-100 p-4">
      <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-slate-500">
        <span className="text-base">{icon}</span>
        {label}
      </div>
      <p className="mt-2 text-sm text-slate-700 leading-relaxed">{body}</p>
    </div>
  );
}

function TrendCard({ insights }: { insights: ProjectInsights }) {
  const { t } = useTranslation();
  const { direction, delta, label } = insights.engagementTrend;
  const Icon = direction === 'up' ? FiArrowUpRight : direction === 'down' ? FiArrowDownRight : FiMinus;
  const tone =
    direction === 'up'
      ? 'text-emerald-600'
      : direction === 'down'
        ? 'text-red-600'
        : 'text-slate-500';
  const sign = delta > 0 ? '+' : '';

  return (
    <div className="rounded-xl border border-slate-100 p-4">
      <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-slate-500">
        <FiTrendingUp className="text-brand-600" />
        {t('projects.detail.insights.engagementTrend')}
      </div>
      <div className="mt-2 flex items-baseline gap-2">
        <span className={`text-2xl font-semibold ${tone}`}>
          {sign}
          {delta}
          <small className="text-sm ms-1">pts</small>
        </span>
        <Icon className={`${tone} w-5 h-5`} />
      </div>
      <p className="text-xs text-slate-500 mt-1">{label}</p>
    </div>
  );
}
