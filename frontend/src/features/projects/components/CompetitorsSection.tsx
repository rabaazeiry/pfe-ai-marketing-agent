import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  FiDownloadCloud,
  FiExternalLink,
  FiFacebook,
  FiInstagram,
  FiLinkedin,
  FiLoader
} from 'react-icons/fi';
import { useToast } from '@/components/Toast';
import type { ScrapeV2Result } from '../detail.api';
import type { CompetitorClassification, CompetitorSummary, ScrapingStatus } from '../types';
import { useScrapeCompetitor } from '../useScrapeCompetitor';
import { StateView } from './StateView';

type BadgeConfig = { label: string; className: string };

const CLASSIFICATION_BADGE: Record<string, BadgeConfig> = {
  local_leader:           { label: 'Leader Local',           className: 'bg-emerald-50 text-emerald-700 ring-emerald-200' },
  local_startup:          { label: 'Startup Local',          className: 'bg-sky-50 text-sky-700 ring-sky-200' },
  international_leader:   { label: 'Leader International',   className: 'bg-violet-50 text-violet-700 ring-violet-200' },
  international_startup:  { label: 'Startup International',  className: 'bg-orange-50 text-orange-700 ring-orange-200' },
  // fallback for old Ollama values
  leader:  { label: 'Leader',  className: 'bg-emerald-50 text-emerald-700 ring-emerald-200' },
  startup: { label: 'Startup', className: 'bg-sky-50 text-sky-700 ring-sky-200' },
};

function ClassificationBadge({ value }: { value: CompetitorClassification }) {
  const cfg = CLASSIFICATION_BADGE[value] ?? { label: value, className: 'bg-slate-100 text-slate-600 ring-slate-200' };
  return (
    <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded ring-1 ${cfg.className}`}>
      {cfg.label}
    </span>
  );
}

type Props = {
  projectId: string;
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

export function CompetitorsSection({ projectId, competitors, isLoading, isError }: Props) {
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
            <CompetitorRow key={c._id} competitor={c} projectId={projectId} />
          ))}
        </ul>
      )}
    </div>
  );
}

function CompetitorRow({ competitor, projectId }: { competitor: CompetitorSummary; projectId: string }) {
  const { t } = useTranslation();
  const toast = useToast();
  const mutation = useScrapeCompetitor(projectId);
  const [result, setResult] = useState<ScrapeV2Result | null>(null);

  const status = (competitor.scrapingStatus ?? 'pending') as ScrapingStatus;
  const tone = SCRAPING_TONES[status];
  const ig = competitor.socialMedia?.instagram?.url;
  const fb = competitor.socialMedia?.facebook?.url;
  const li = competitor.socialMedia?.linkedin?.url;
  const isScraping = mutation.isPending;
  const hasInstagram = !!ig;

  const handleScrape = () => {
    setResult(null);
    mutation.mutate(competitor._id, {
      onSuccess: (data) => {
        setResult(data);
        toast.success(
          t('projects.detail.competitors.scrape.successBody', {
            name: competitor.companyName,
            count: data.postsCount
          })
        );
      },
      onError: (err) => {
        const msg =
          (err as { response?: { data?: { message?: string } } })?.response?.data?.message ??
          t('projects.detail.competitors.scrape.errorBody');
        toast.error(msg, t('projects.detail.competitors.scrape.errorTitle'));
      }
    });
  };

  return (
    <li className="py-3 space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-medium text-slate-800 truncate">{competitor.companyName}</span>
            {competitor.classification ? (
              <ClassificationBadge value={competitor.classification} />
            ) : competitor.classificationMaturity ? (
              <ClassificationBadge value={competitor.classificationMaturity} />
            ) : null}
            {competitor.isActive === false && (
              <span className="text-[10px] uppercase text-slate-500">
                {t('projects.detail.competitors.inactive')}
              </span>
            )}
          </div>
          {competitor.classificationJustification && (
            <p className="text-[11px] text-slate-400 italic mt-0.5 leading-snug line-clamp-2">
              {competitor.classificationJustification}
            </p>
          )}
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

        <div className="flex items-center gap-2">
          {hasInstagram && (
            <button
              type="button"
              className="btn-ghost !py-1 !px-2.5 !text-xs !gap-1.5"
              onClick={handleScrape}
              disabled={isScraping}
            >
              {isScraping ? (
                <FiLoader className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <FiDownloadCloud className="w-3.5 h-3.5" />
              )}
              {isScraping
                ? t('projects.detail.competitors.scrape.loading')
                : t('projects.detail.competitors.scrape.action')}
            </button>
          )}
          <span className={`text-xs px-2 py-1 rounded-full font-medium ${tone}`}>
            {t(`projects.detail.competitors.scraping.${status}`)}
          </span>
        </div>
      </div>

      {result && result.postsCount > 0 && (
        <ScrapeResultCard result={result} />
      )}
    </li>
  );
}

function ScrapeResultCard({ result }: { result: ScrapeV2Result }) {
  const { t } = useTranslation();
  const sa = result.socialAnalysis;
  const sample = sa.samples?.[0];

  return (
    <div className="rounded-lg border border-brand-100 bg-brand-50/40 p-3 text-xs space-y-2 animate-fade-in">
      <div className="flex items-center gap-3 text-slate-700 font-medium">
        <span>{t('projects.detail.competitors.scrape.result')}</span>
        {result.methodUsed && (
          <span className="text-[10px] uppercase tracking-wide text-brand-600 bg-brand-100 px-1.5 py-0.5 rounded">
            {result.methodUsed}
          </span>
        )}
      </div>
      <div className="grid grid-cols-3 gap-3 text-slate-600">
        <div>
          <div className="text-[10px] uppercase tracking-wide text-slate-400">
            {t('projects.detail.competitors.scrape.posts')}
          </div>
          <div className="font-semibold text-slate-800">{sa.postsCount}</div>
        </div>
        <div>
          <div className="text-[10px] uppercase tracking-wide text-slate-400">
            {t('projects.detail.competitors.scrape.likes')}
          </div>
          <div className="font-semibold text-slate-800">{sa.totalLikes}</div>
        </div>
        <div>
          <div className="text-[10px] uppercase tracking-wide text-slate-400">
            {t('projects.detail.competitors.scrape.comments')}
          </div>
          <div className="font-semibold text-slate-800">{sa.totalComments}</div>
        </div>
      </div>
      {sample && (
        <div className="text-slate-600 border-t border-brand-100 pt-2">
          <span className="text-[10px] uppercase tracking-wide text-slate-400 block mb-1">
            {t('projects.detail.competitors.scrape.sample')}
          </span>
          <p className="leading-relaxed line-clamp-2">{sample.text}</p>
        </div>
      )}
    </div>
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
