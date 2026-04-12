import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { FiFolder, FiUsers, FiTrendingUp, FiActivity } from 'react-icons/fi';
import { BarChart, Bar, ResponsiveContainer, XAxis, YAxis, Tooltip, LineChart, Line, PieChart, Pie, Cell, Legend, CartesianGrid } from 'recharts';
import { listProjects } from '@/features/projects/api';
import { useAuthStore } from '@/stores/auth.store';
import { formatNumber } from '@/lib/format';

const engagementSeries = [
  { day: 'Mon', posts: 3, likes: 120 },
  { day: 'Tue', posts: 2, likes: 90 },
  { day: 'Wed', posts: 4, likes: 260 },
  { day: 'Thu', posts: 5, likes: 310 },
  { day: 'Fri', posts: 3, likes: 180 },
  { day: 'Sat', posts: 6, likes: 420 },
  { day: 'Sun', posts: 4, likes: 290 }
];

const formatMix = [
  { name: 'Reels', value: 42 },
  { name: 'Carousel', value: 28 },
  { name: 'Static', value: 22 },
  { name: 'Story', value: 8 }
];
const COLORS = ['#3066f2', '#5a91ff', '#8eb8ff', '#bcd4ff'];

function Kpi({ icon, label, value, delta }: { icon: React.ReactNode; label: string; value: string; delta?: string }) {
  return (
    <div className="card flex items-center gap-4">
      <div className="w-11 h-11 rounded-lg bg-brand-50 text-brand-700 grid place-items-center text-xl">{icon}</div>
      <div>
        <div className="text-xs text-slate-500">{label}</div>
        <div className="text-2xl font-semibold text-slate-900">{value}</div>
        {delta && <div className="text-xs text-emerald-600 mt-0.5">{delta}</div>}
      </div>
    </div>
  );
}

export function DashboardPage() {
  const { t, i18n } = useTranslation();
  const user = useAuthStore((s) => s.user);
  const { data: projects } = useQuery({ queryKey: ['projects'], queryFn: listProjects });
  const lang = i18n.language;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">
          {t('dashboard.greeting', { name: user?.firstName ?? '' })}
        </h1>
        <p className="text-slate-500">{t('dashboard.subtitle')}</p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <Kpi icon={<FiFolder />}     label={t('dashboard.kpi.projects')}    value={formatNumber(projects?.length ?? 0, lang)} delta={t('dashboard.kpi.projectsDelta')} />
        <Kpi icon={<FiUsers />}      label={t('dashboard.kpi.competitors')} value={formatNumber(24, lang)}                    delta={t('dashboard.kpi.competitorsDelta')} />
        <Kpi icon={<FiActivity />}   label={t('dashboard.kpi.posts')}       value={formatNumber(1287, lang)}                  delta={t('dashboard.kpi.postsDelta')} />
        <Kpi icon={<FiTrendingUp />} label={t('dashboard.kpi.engagement')}  value={`${formatNumber(4.6, lang)}%`}             delta={t('dashboard.kpi.engagementDelta')} />
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
            <ResponsiveContainer>
              <LineChart data={engagementSeries}>
                <CartesianGrid strokeDasharray="3 3" stroke="#eef2f7" />
                <XAxis dataKey="day" stroke="#94a3b8" fontSize={12} />
                <YAxis stroke="#94a3b8" fontSize={12} />
                <Tooltip />
                <Line type="monotone" dataKey="likes" stroke="#3066f2" strokeWidth={2} dot={{ r: 3 }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="card">
          <h3 className="font-semibold text-slate-900">{t('dashboard.charts.mix')}</h3>
          <p className="text-xs text-slate-500 mb-4">{t('dashboard.charts.mixSubtitle')}</p>
          <div className="h-64">
            <ResponsiveContainer>
              <PieChart>
                <Pie data={formatMix} dataKey="value" nameKey="name" innerRadius={45} outerRadius={75} paddingAngle={3}>
                  {formatMix.map((_, i) => (
                    <Cell key={i} fill={COLORS[i]} />
                  ))}
                </Pie>
                <Legend />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      <div className="card">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-semibold text-slate-900">{t('dashboard.charts.posts')}</h3>
        </div>
        <div className="h-64">
          <ResponsiveContainer>
            <BarChart data={engagementSeries}>
              <CartesianGrid strokeDasharray="3 3" stroke="#eef2f7" />
              <XAxis dataKey="day" stroke="#94a3b8" fontSize={12} />
              <YAxis stroke="#94a3b8" fontSize={12} />
              <Tooltip />
              <Bar dataKey="posts" fill="#3066f2" radius={[6, 6, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
