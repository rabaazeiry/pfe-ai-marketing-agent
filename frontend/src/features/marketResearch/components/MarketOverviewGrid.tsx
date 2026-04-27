import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import {
  FiAward,
  FiGlobe,
  FiLayers,
  FiMapPin,
  FiRadio,
  FiTrendingUp,
  FiUsers,
  FiZap
} from 'react-icons/fi';
import type { DominantPlatform, MarketOverview } from '../types';

type Props = { overview: MarketOverview };

const PLATFORM_LABEL: Record<DominantPlatform, string> = {
  instagram: 'Instagram',
  facebook: 'Facebook',
  linkedin: 'LinkedIn',
  tiktok: 'TikTok',
  '': '—'
};

export function MarketOverviewGrid({ overview }: Props) {
  const { t } = useTranslation();

  const maturityLabel = t(
    `projects.detail.marketResearch.maturity.${overview.marketMaturity}`,
    { defaultValue: overview.marketMaturity }
  ) as string;
  const platformLabel = PLATFORM_LABEL[overview.dominantPlatform] ?? '—';

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
      <OverviewCell
        icon={<FiUsers />}
        tone="bg-brand-50 text-brand-600"
        label={t('projects.detail.marketResearch.overview.totalCompetitors')}
        value={overview.totalCompetitors}
      />
      <OverviewCell
        icon={<FiAward />}
        tone="bg-amber-50 text-amber-600"
        label={t('projects.detail.marketResearch.overview.leaderCount')}
        value={overview.leaderCount}
      />
      <OverviewCell
        icon={<FiZap />}
        tone="bg-emerald-50 text-emerald-600"
        label={t('projects.detail.marketResearch.overview.startupCount')}
        value={overview.startupCount}
      />
      <OverviewCell
        icon={<FiMapPin />}
        tone="bg-slate-100 text-slate-600"
        label={t('projects.detail.marketResearch.overview.localCount')}
        value={overview.localCount}
      />
      <OverviewCell
        icon={<FiGlobe />}
        tone="bg-indigo-50 text-indigo-600"
        label={t('projects.detail.marketResearch.overview.internationalCount')}
        value={overview.internationalCount}
      />
      <OverviewCell
        icon={<FiRadio />}
        tone="bg-rose-50 text-rose-600"
        label={t('projects.detail.marketResearch.overview.dominantPlatform')}
        value={platformLabel}
      />
      <OverviewCell
        icon={<FiTrendingUp />}
        tone="bg-sky-50 text-sky-600"
        label={t('projects.detail.marketResearch.overview.marketMaturity')}
        value={maturityLabel}
      />
      <OverviewCell
        icon={<FiLayers />}
        tone="bg-violet-50 text-violet-600"
        label={t('projects.detail.marketResearch.overview.coverage')}
        value={formatCoverage(overview)}
      />
    </div>
  );
}

function OverviewCell({
  icon,
  tone,
  label,
  value
}: {
  icon: ReactNode;
  tone: string;
  label: string;
  value: ReactNode;
}) {
  return (
    <div className="rounded-xl border border-slate-100 bg-white p-3 flex items-center gap-3">
      <span className={`inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${tone}`}>
        {icon}
      </span>
      <div className="min-w-0">
        <div className="text-[11px] uppercase tracking-wide text-slate-500 truncate">{label}</div>
        <div className="text-sm font-semibold text-slate-900 truncate">{value}</div>
      </div>
    </div>
  );
}

function formatCoverage(o: MarketOverview): string {
  return `${o.localCount} / ${o.internationalCount}`;
}
