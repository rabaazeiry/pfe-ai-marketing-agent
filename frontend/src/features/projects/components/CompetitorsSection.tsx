import { useTranslation } from 'react-i18next';
import { FiExternalLink, FiFacebook, FiInstagram, FiLinkedin } from 'react-icons/fi';
import type { CompetitorSummary, ScrapingStatus } from '../types';
import { StateView } from './StateView';

type Props = {
  competitors: CompetitorSummary[] | undefined;
  isLoading: boolean;
  isError: boolean;
};

const SCRAPING_TONES: Record<ScrapingStatus, string> = {
  pending: 'bg-slate-100 text-slate-600',
  in_progress: 'bg-amber-50 text-amber-700',
  completed: 'bg-emerald-50 text-emerald-700',
  failed: 'bg-red-50 text-red-700'
};

export function CompetitorsSection({ competitors, isLoading, isError }: Props) {
  const { t } = useTranslation();

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-3">
        <div>
          <h3 className="font-semibold text-slate-900">{t('projects.detail.competitors.title')}</h3>
          <p className="text-xs text-slate-500">{t('projects.detail.competitors.subtitle')}</p>
        </div>
        {competitors && competitors.length > 0 && (
          <span className="text-xs text-slate-500">
            {t('projects.detail.competitors.total', { count: competitors.length })}
          </span>
        )}
      </div>

      {isLoading ? (
        <StateView variant="loading" title={t('common.loading')} />
      ) : isError ? (
        <StateView variant="error" title={t('projects.detail.errors.title')}>
          {t('projects.detail.errors.competitors')}
        </StateView>
      ) : !competitors || competitors.length === 0 ? (
        <StateView variant="empty" title={t('projects.detail.competitors.empty')}>
          {t('projects.detail.competitors.emptyHint')}
        </StateView>
      ) : (
        <ul className="divide-y divide-slate-100">
          {competitors.map((c) => (
            <CompetitorRow key={c._id} competitor={c} />
          ))}
        </ul>
      )}
    </div>
  );
}

function CompetitorRow({ competitor }: { competitor: CompetitorSummary }) {
  const { t } = useTranslation();
  const status = (competitor.scrapingStatus ?? 'pending') as ScrapingStatus;
  const tone = SCRAPING_TONES[status];
  const ig = competitor.socialMedia?.instagram?.url;
  const fb = competitor.socialMedia?.facebook?.url;
  const li = competitor.socialMedia?.linkedin?.url;

  return (
    <li className="py-3 flex flex-wrap items-center justify-between gap-3">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="font-medium text-slate-800 truncate">{competitor.companyName}</span>
          {competitor.classificationMaturity && (
            <span className="text-[10px] uppercase tracking-wide text-slate-500 bg-slate-100 px-1.5 py-0.5 rounded">
              {competitor.classificationMaturity}
            </span>
          )}
          {competitor.isActive === false && (
            <span className="text-[10px] uppercase text-slate-500">{t('projects.detail.competitors.inactive')}</span>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-3 mt-1 text-xs text-slate-500">
          {competitor.website ? (
            <a
              href={competitor.website}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 hover:text-brand-700"
            >
              {cleanUrl(competitor.website)} <FiExternalLink />
            </a>
          ) : (
            <span>—</span>
          )}
          {ig && <SocialIcon href={ig} icon={<FiInstagram />} label="Instagram" />}
          {fb && <SocialIcon href={fb} icon={<FiFacebook />} label="Facebook" />}
          {li && <SocialIcon href={li} icon={<FiLinkedin />} label="LinkedIn" />}
        </div>
      </div>
      <span className={`text-xs px-2 py-1 rounded-full font-medium ${tone}`}>
        {t(`projects.detail.competitors.scraping.${status}`)}
      </span>
    </li>
  );
}

function SocialIcon({ href, icon, label }: { href: string; icon: React.ReactNode; label: string }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      aria-label={label}
      className="hover:text-brand-700"
    >
      {icon}
    </a>
  );
}

function cleanUrl(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}
