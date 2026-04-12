import { useTranslation } from 'react-i18next';
import { BarChart, Bar, ResponsiveContainer, XAxis, YAxis, Tooltip, CartesianGrid, LineChart, Line, Legend } from 'recharts';

const followers = [
  { brand: 'Brand A', followers: 18200 },
  { brand: 'Brand B', followers: 12400 },
  { brand: 'Brand C', followers: 26800 },
  { brand: 'Brand D', followers: 9100 },
  { brand: 'Brand E', followers: 15300 }
];

const engagementOverTime = [
  { week: 'W1', A: 3.2, B: 2.1, C: 4.8 },
  { week: 'W2', A: 3.5, B: 2.4, C: 4.9 },
  { week: 'W3', A: 4.1, B: 2.9, C: 5.3 },
  { week: 'W4', A: 4.6, B: 3.1, C: 5.0 }
];

export function AnalyticsPage() {
  const { t } = useTranslation();
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">{t('analytics.title')}</h1>
        <p className="text-slate-500">{t('analytics.subtitle')}</p>
      </div>

      <div className="card">
        <h3 className="font-semibold text-slate-900 mb-2">{t('analytics.followers')}</h3>
        <div className="h-72">
          <ResponsiveContainer>
            <BarChart data={followers}>
              <CartesianGrid strokeDasharray="3 3" stroke="#eef2f7" />
              <XAxis dataKey="brand" stroke="#94a3b8" fontSize={12} />
              <YAxis stroke="#94a3b8" fontSize={12} />
              <Tooltip />
              <Bar dataKey="followers" fill="#3066f2" radius={[6, 6, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="card">
        <h3 className="font-semibold text-slate-900 mb-2">{t('analytics.engagementRate')}</h3>
        <div className="h-72">
          <ResponsiveContainer>
            <LineChart data={engagementOverTime}>
              <CartesianGrid strokeDasharray="3 3" stroke="#eef2f7" />
              <XAxis dataKey="week" stroke="#94a3b8" fontSize={12} />
              <YAxis stroke="#94a3b8" fontSize={12} />
              <Tooltip />
              <Legend />
              <Line type="monotone" dataKey="A" stroke="#3066f2" strokeWidth={2} />
              <Line type="monotone" dataKey="B" stroke="#5a91ff" strokeWidth={2} />
              <Line type="monotone" dataKey="C" stroke="#8eb8ff" strokeWidth={2} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
