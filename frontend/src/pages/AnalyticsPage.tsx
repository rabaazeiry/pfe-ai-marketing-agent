import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import {
  BarChart, Bar, ResponsiveContainer, XAxis, YAxis, Tooltip,
  CartesianGrid, LineChart, Line, Legend
} from 'recharts';
import { getAnalyticsOverview } from '@/features/analytics/api';
import { listProjects } from '@/features/projects/api';
import { Skeleton } from '@/components/Skeleton';

const COLORS = [
  '#3066f2', '#5a91ff', '#8eb8ff', '#bcd4ff',
  '#1d4fbf', '#f59e0b', '#10b981', '#ef4444'
];

export function AnalyticsPage() {
  const { t } = useTranslation();
  const [selectedProjectId, setSelectedProjectId] = useState<string>('');

  const { data: projects } = useQuery({
    queryKey: ['projects'],
    queryFn: listProjects
  });

  const { data, isLoading, isError } = useQuery({
    queryKey: ['analytics', 'overview', selectedProjectId || 'all'],
    queryFn: () => getAnalyticsOverview(selectedProjectId || undefined)
  });

  const followers = data?.followersByBrand ?? [];

  // Recharts LineChart needs a flat row per X tick: { week, BrandA: 2.5, BrandB: 1.2, ... }
  const { engagementChart, brandKeys } = useMemo(() => {
    const weeks = data?.engagementOverTime ?? [];
    const brandSet = new Set<string>();
    weeks.forEach((w) => w.values.forEach((v) => brandSet.add(v.brand)));
    const keys = Array.from(brandSet);
    const fmtWeek = (w: { week: string; weekStart?: string }) => {
      if (!w.weekStart) return w.week;
      const d = new Date(w.weekStart);
      return Number.isNaN(d.getTime())
        ? w.week
        : `${w.week} · ${d.toLocaleDateString('fr-FR', { day: '2-digit', month: 'short' })}`;
    };
    const chart = weeks.map((w) => {
      // null (NOT 0) for a brand with no post that week → Recharts draws a gap
      const row: Record<string, string | number | null> = { week: fmtWeek(w) };
      for (const k of keys) row[k] = null;
      for (const v of w.values) row[v.brand] = v.engagement;
      return row;
    });
    return { engagementChart: chart, brandKeys: keys };
  }, [data]);

  const projectLabel = (p: { name?: string; industry?: string; marketCategory?: string }) =>
    p.name || p.industry || p.marketCategory || '—';

  // "has data" = at least one real (non-null) point — a genuine 0 still counts as data
  const hasEngagementData = brandKeys.length > 0 && engagementChart.some((row) =>
    brandKeys.some((k) => row[k] !== null && row[k] !== undefined)
  );

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">{t('analytics.title')}</h1>
          <p className="text-slate-500">{t('analytics.subtitle')}</p>
        </div>

        <label className="flex items-center gap-2 text-sm">
          <span className="text-slate-500">{t('dashboard.filter.label')}</span>
          <select
            value={selectedProjectId}
            onChange={(e) => setSelectedProjectId(e.target.value)}
            className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
          >
            <option value="">{t('dashboard.filter.all')}</option>
            {(projects ?? []).map((p) => (
              <option key={p._id} value={p._id}>
                {projectLabel(p)}
              </option>
            ))}
          </select>
        </label>
      </div>

      {isError && (
        <div className="card border border-rose-200 bg-rose-50 text-rose-700 text-sm">
          {t('dashboard.error')}
        </div>
      )}

      <div className="card">
        <h3 className="font-semibold text-slate-900 mb-2">{t('analytics.followers')}</h3>
        <div className="h-72">
          {isLoading ? (
            <Skeleton className="h-full w-full" />
          ) : followers.length === 0 ? (
            <div className="h-full grid place-items-center text-sm text-slate-400">
              {t('dashboard.empty')}
            </div>
          ) : (
            <ResponsiveContainer>
              <BarChart data={followers}>
                <CartesianGrid strokeDasharray="3 3" stroke="#eef2f7" />
                <XAxis dataKey="name" stroke="#94a3b8" fontSize={12} interval={0} angle={-15} textAnchor="end" height={50} />
                <YAxis stroke="#94a3b8" fontSize={12} />
                <Tooltip />
                <Bar dataKey="followers" fill="#3066f2" radius={[6, 6, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      <div className="card">
        <h3 className="font-semibold text-slate-900 mb-2">{t('analytics.engagementRate')}</h3>
        <div className="h-72">
          {isLoading ? (
            <Skeleton className="h-full w-full" />
          ) : !hasEngagementData ? (
            <div className="h-full grid place-items-center text-sm text-slate-400">
              {t('analytics.noData')}
            </div>
          ) : (
            <ResponsiveContainer>
              <LineChart data={engagementChart}>
                <CartesianGrid strokeDasharray="3 3" stroke="#eef2f7" />
                <XAxis dataKey="week" stroke="#94a3b8" fontSize={12} />
                <YAxis stroke="#94a3b8" fontSize={12} />
                <Tooltip />
                <Legend />
                {brandKeys.map((brand, i) => (
                  <Line
                    key={brand}
                    type="monotone"
                    dataKey={brand}
                    stroke={COLORS[i % COLORS.length]}
                    strokeWidth={2}
                    dot={{ r: 3 }}
                    connectNulls={false}
                  />
                ))}
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
        {hasEngagementData && (
          <p className="mt-2 text-xs text-slate-400">{t('analytics.weeksNote')}</p>
        )}
      </div>
    </div>
  );
}
