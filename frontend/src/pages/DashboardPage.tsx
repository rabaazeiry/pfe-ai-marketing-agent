import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Link } from '@tanstack/react-router';
import { FiFolder, FiUsers, FiTrendingUp, FiActivity } from 'react-icons/fi';
import {
  BarChart, Bar, ResponsiveContainer, XAxis, YAxis, Tooltip,
  LineChart, Line, PieChart, Pie, Cell, Legend, CartesianGrid
} from 'recharts';
import { useAuthStore } from '@/stores/auth.store';
import { useOnboardingStore } from '@/stores/onboarding.store';
import { formatNumber } from '@/lib/format';
import { Skeleton } from '@/components/Skeleton';
import { getDashboardStats } from '@/features/dashboard/api';
import { listProjects } from '@/features/projects/api';

const COLORS = ['#3066f2', '#5a91ff', '#8eb8ff', '#bcd4ff', '#dde9ff'];

type KpiProps = {
  icon: React.ReactNode;
  label: string;
  value: string;
  to: string;
};

function Kpi({ icon, label, value, to }: KpiProps) {
  return (
    <Link
      to={to}
      className="card flex items-center gap-4 hover:shadow-md hover:border-brand-200 transition cursor-pointer"
    >
      <div className="w-11 h-11 rounded-lg bg-brand-50 text-brand-700 grid place-items-center text-xl">
        {icon}
      </div>
      <div>
        <div className="text-xs text-slate-500">{label}</div>
        <div className="text-2xl font-semibold text-slate-900">{value}</div>
      </div>
    </Link>
  );
}

function KpiSkeleton() {
  return (
    <div className="card flex items-center gap-4">
      <Skeleton className="w-11 h-11 rounded-lg" />
      <div className="space-y-2">
        <Skeleton className="h-3 w-24" />
        <Skeleton className="h-6 w-16" />
      </div>
    </div>
  );
}

function ChartEmpty({ label }: { label: string }) {
  return (
    <div className="h-64 grid place-items-center text-sm text-slate-400">
      {label}
    </div>
  );
}

export function DashboardPage() {
  const { t, i18n } = useTranslation();
  const user = useAuthStore((s) => s.user);
  const lang = i18n.language;

  // First-login guided tour: auto-start once per user, then mark seen so it
  // never nags again (re-runnable from Settings → "Revoir le tour").
  const tourSeenIds = useOnboardingStore((s) => s.seenUserIds);
  const markTourSeen = useOnboardingStore((s) => s.markSeen);
  const startTour = useOnboardingStore((s) => s.startTour);
  useEffect(() => {
    if (user && !tourSeenIds.includes(user.id)) {
      markTourSeen(user.id);
      startTour();
    }
  }, [user, tourSeenIds, markTourSeen, startTour]);

  const [selectedProjectId, setSelectedProjectId] = useState<string>('');

  const { data: projects } = useQuery({
    queryKey: ['projects'],
    queryFn: listProjects
  });

  const { data, isLoading, isError } = useQuery({
    queryKey: ['dashboard', 'stats', selectedProjectId || 'all'],
    queryFn: () => getDashboardStats(selectedProjectId || undefined)
  });

  const projectLabel = (p: { name?: string; industry?: string; marketCategory?: string }) =>
    p.name || p.industry || p.marketCategory || '—';

  const kpis = data?.kpis;
  const engagementByDay = data?.charts.engagementByDay ?? [];
  const contentMix = data?.charts.contentMix ?? [];

  const engagementValue =
    kpis?.avgEngagementRate === null || kpis?.avgEngagementRate === undefined
      ? t('dashboard.noValue')
      : `${formatNumber(kpis.avgEngagementRate, lang)}%`;

  return (
    <div className="space-y-6" data-tour="dashboard">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">
            {t('dashboard.greeting', { name: user?.firstName ?? '' })}
          </h1>
          <p className="text-slate-500">{t('dashboard.subtitle')}</p>
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

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {isLoading ? (
          <>
            <KpiSkeleton /><KpiSkeleton /><KpiSkeleton /><KpiSkeleton />
          </>
        ) : (
          <>
            <Kpi
              icon={<FiFolder />}
              label={t('dashboard.kpi.projects')}
              value={formatNumber(kpis?.projects ?? 0, lang)}
              to="/projects"
            />
            <Kpi
              icon={<FiUsers />}
              label={t('dashboard.kpi.competitors')}
              value={formatNumber(kpis?.competitors ?? 0, lang)}
              to="/projects"
            />
            <Kpi
              icon={<FiActivity />}
              label={t('dashboard.kpi.posts')}
              value={formatNumber(kpis?.postsAnalyzed ?? 0, lang)}
              to="/analytics"
            />
            <Kpi
              icon={<FiTrendingUp />}
              label={t('dashboard.kpi.engagement')}
              value={engagementValue}
              to="/analytics"
            />
          </>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="card lg:col-span-2">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="font-semibold text-slate-900">{t('dashboard.charts.engagement')}</h3>
              <p className="text-xs text-slate-500">{t('dashboard.charts.engagementSubtitle')}</p>
            </div>
          </div>
          <div className="h-64">
            {isLoading ? (
              <Skeleton className="h-full w-full" />
            ) : engagementByDay.length === 0 ? (
              <ChartEmpty label={t('dashboard.empty')} />
            ) : (
              <ResponsiveContainer>
                <LineChart data={engagementByDay}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#eef2f7" />
                  <XAxis dataKey="day" stroke="#94a3b8" fontSize={12} />
                  <YAxis stroke="#94a3b8" fontSize={12} />
                  <Tooltip />
                  <Line type="monotone" dataKey="likes" stroke="#3066f2" strokeWidth={2} dot={{ r: 3 }} />
                </LineChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>

        <div className="card">
          <h3 className="font-semibold text-slate-900">{t('dashboard.charts.mix')}</h3>
          <p className="text-xs text-slate-500 mb-4">{t('dashboard.charts.mixSubtitle')}</p>
          <div className="h-64">
            {isLoading ? (
              <Skeleton className="h-full w-full" />
            ) : contentMix.length === 0 ? (
              <ChartEmpty label={t('dashboard.empty')} />
            ) : (
              <ResponsiveContainer>
                <PieChart>
                  <Pie data={contentMix} dataKey="value" nameKey="name" innerRadius={45} outerRadius={75} paddingAngle={3}>
                    {contentMix.map((_, i) => (
                      <Cell key={i} fill={COLORS[i % COLORS.length]} />
                    ))}
                  </Pie>
                  <Legend />
                </PieChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>
      </div>

      <div className="card">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-semibold text-slate-900">{t('dashboard.charts.posts')}</h3>
        </div>
        <div className="h-64">
          {isLoading ? (
            <Skeleton className="h-full w-full" />
          ) : engagementByDay.length === 0 ? (
            <ChartEmpty label={t('dashboard.empty')} />
          ) : (
            <ResponsiveContainer>
              <BarChart data={engagementByDay}>
                <CartesianGrid strokeDasharray="3 3" stroke="#eef2f7" />
                <XAxis dataKey="day" stroke="#94a3b8" fontSize={12} />
                <YAxis stroke="#94a3b8" fontSize={12} />
                <Tooltip />
                <Bar dataKey="posts" fill="#3066f2" radius={[6, 6, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>
    </div>
  );
}
