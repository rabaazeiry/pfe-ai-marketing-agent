import { useState } from 'react';
import axios from 'axios';
import { useTranslation } from 'react-i18next';
import {
  FiCalendar,
  FiChevronDown,
  FiChevronUp,
  FiClock,
  FiCpu,
  FiHash,
  FiLoader,
  FiRefreshCw,
  FiTarget,
} from 'react-icons/fi';
import clsx from 'clsx';
import { useToast } from '@/components/Toast';
import { normalizeIndustry } from '../industry';
import { useIndustryCampaign, useRegenerateIndustryCampaign } from '../useProjectDetail';
import type { CampaignPost, CampaignWeek, IndustryKey } from '../types';
import { StateView } from './StateView';

type Props = {
  industry?: string | null;
  marketCategory?: string | null;
};

// Parse a "YYYY-MM-DD" string without UTC shift, then format for the
// active locale. Falls back to the raw string if it isn't a plain date.
function formatDay(iso: string, lang: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!m) return iso;
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  return d.toLocaleDateString(lang, { day: 'numeric', month: 'short', year: 'numeric' });
}

const INTENSITY_BADGE: Record<string, string> = {
  high: 'bg-amber-50 text-amber-700',
  normal: 'bg-brand-50 text-brand-700',
  low: 'bg-slate-100 text-slate-500',
};

const STATUS_FLAG: Record<string, string> = {
  REPAIRED: 'bg-amber-50 text-amber-700',
  FALLBACK: 'bg-slate-100 text-slate-500',
};

export function CampaignSection({ industry, marketCategory }: Props) {
  const { t } = useTranslation();
  const toast = useToast();

  const key: IndustryKey | null = normalizeIndustry(industry, marketCategory);
  const query = useIndustryCampaign(key);
  const mutation = useRegenerateIndustryCampaign(key);
  const bundle = query.data;

  const handleRegenerate = async () => {
    try {
      await mutation.mutateAsync();
      toast.success(
        'Campagne régénérée avec succès !',
        'Régénération terminée'
      );
    } catch (err) {
      const fallback = 'Impossible de lancer la régénération.';
      const message = axios.isAxiosError(err)
        ? err.response?.data?.message ?? fallback
        : fallback;
      toast.error(message, 'Erreur de régénération');
    }
  };

  return (
    <div className="card">
      <div className="flex items-start justify-between mb-4 gap-4">
        <div>
          <h3 className="font-semibold text-slate-900">{t('projects.detail.campaign.title')}</h3>
          <p className="text-xs text-slate-500">{t('projects.detail.campaign.subtitle')}</p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {bundle && (
            <div className="flex flex-col items-end text-[11px] text-slate-500">
              <span className="inline-flex items-center gap-1.5 rounded-full bg-brand-50 text-brand-700 px-2 py-0.5 font-medium">
                <FiCpu className="h-3 w-3" />
                {bundle.model}
              </span>
              <span className="mt-1">
                {t('projects.detail.campaign.industryBadge', { industry: bundle.industry })}
              </span>
            </div>
          )}
          {key && (
            <button
              type="button"
              className="btn-ghost shrink-0"
              onClick={handleRegenerate}
              disabled={mutation.isPending}
              title="Régénérer la campagne via Llama 3.1"
            >
              {mutation.isPending ? (
                <FiLoader className="animate-spin h-4 w-4" />
              ) : (
                <FiRefreshCw className="h-4 w-4" />
              )}
              <span className="ml-1.5">
                {mutation.isPending
                  ? t('projects.detail.campaign.regenerating')
                  : t('projects.detail.campaign.regenerate')}
              </span>
            </button>
          )}
        </div>
      </div>

      {!key ? (
        <StateView variant="empty" title={t('projects.detail.campaign.empty')}>
          {t('projects.detail.campaign.unsupportedIndustry')}
        </StateView>
      ) : query.isLoading ? (
        <StateView variant="loading" title={t('common.loading')} />
      ) : query.isError ? (
        <StateView variant="error" title={t('projects.detail.errors.title')}>
          {t('projects.detail.errors.campaign')}
        </StateView>
      ) : !bundle || (bundle.weeks ?? []).length === 0 ? (
        <StateView variant="empty" title={t('projects.detail.campaign.empty')} />
      ) : (
        <div className="space-y-6">
          <CampaignSummary summary={bundle.campaign_summary} />
          {(bundle.weeks ?? []).map((w) => (
            <WeekCard key={w.week_index} week={w} />
          ))}
        </div>
      )}
    </div>
  );
}

function CampaignSummary({
  summary,
}: {
  summary: {
    title: string;
    objective: string;
    target_audience: string;
    platforms: string[];
  };
}) {
  const { t } = useTranslation();
  return (
    <section className="rounded-xl border border-brand-100 bg-brand-50/40 px-4 py-3">
      <h4 className="text-sm font-semibold text-slate-900 leading-snug">{summary.title}</h4>
      <p className="mt-2 text-xs text-slate-700 leading-relaxed">
        <span className="font-semibold uppercase tracking-wide text-[11px] text-brand-700">
          {t('projects.detail.campaign.objective')}:
        </span>{' '}
        {summary.objective}
      </p>
      <p className="mt-2 text-xs text-slate-700 leading-relaxed">
        <span className="font-semibold uppercase tracking-wide text-[11px] text-brand-700">
          {t('projects.detail.campaign.targetAudience')}:
        </span>{' '}
        {summary.target_audience}
      </p>
      {summary.platforms?.length > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-1.5 text-[11px] text-slate-500">
          <span className="font-semibold uppercase tracking-wide text-brand-700">
            {t('projects.detail.campaign.platforms')}:
          </span>
          {summary.platforms.map((p) => (
            <span
              key={p}
              className="rounded bg-white px-1.5 py-0.5 font-medium text-slate-600 border border-slate-100"
            >
              {p}
            </span>
          ))}
        </div>
      )}
    </section>
  );
}

function WeekCard({ week }: { week: CampaignWeek }) {
  const { t, i18n } = useTranslation();
  const intensityClass = INTENSITY_BADGE[week.intensity] ?? 'bg-slate-100 text-slate-500';

  return (
    <section className="rounded-xl border border-slate-100 bg-white">
      <div className="flex flex-wrap items-center gap-2 px-4 py-3 border-b border-slate-100">
        <span className="inline-flex items-center justify-center h-6 min-w-6 rounded-full bg-slate-900 text-white text-[11px] font-semibold px-2">
          {t('projects.detail.campaign.weekLabel', { index: week.week_index })}
        </span>
        <span className="inline-flex items-center gap-1.5 text-sm font-semibold text-slate-900">
          <FiCalendar className="h-3.5 w-3.5 text-slate-400" aria-hidden />
          {formatDay(week.week_start, i18n.language)}
        </span>
        <span
          className={clsx(
            'inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium capitalize',
            intensityClass
          )}
        >
          {t(`projects.detail.campaign.intensity.${week.intensity}`, {
            defaultValue: week.intensity,
          })}
        </span>
        <span className="text-[11px] text-slate-500">
          {t('projects.detail.campaign.predictedEngagement')}:{' '}
          <span className="font-mono text-slate-600">
            {week.predicted_engagement.toFixed(3)}
          </span>
        </span>
        <span className="ml-auto text-[11px] text-slate-500">
          {t('projects.detail.campaign.postsCount', { count: week.posts_recommended })}
        </span>
      </div>

      <div className="divide-y divide-slate-100">
        {(week.posts ?? []).map((p) => (
          <PostRow key={p.post_index} post={p} />
        ))}
      </div>
    </section>
  );
}

function PostRow({ post }: { post: CampaignPost }) {
  const { t, i18n } = useTranslation();
  const [open, setOpen] = useState(false);
  const statusClass = STATUS_FLAG[post.status];

  return (
    <div className="px-4 py-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-xs">
        <span className="font-semibold text-slate-900">
          {formatDay(post.date, i18n.language)}
        </span>
        <span className="text-slate-500 capitalize">{post.day_of_week}</span>
        <span className="inline-flex items-center gap-1 text-slate-500">
          <FiClock className="h-3 w-3" aria-hidden />
          {post.best_time}
        </span>
        <span className="rounded bg-slate-100 px-1.5 py-0.5 font-medium text-slate-600 capitalize">
          {post.format}
        </span>
        <span className="text-slate-700">{post.theme}</span>
        {statusClass && (
          <span
            className={clsx(
              'inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] font-medium',
              statusClass
            )}
            title={t('projects.detail.campaign.statusHint')}
          >
            {post.status}
          </span>
        )}
        <button
          type="button"
          className="ml-auto inline-flex items-center gap-1 text-[11px] font-medium text-brand-700 hover:text-brand-800"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
        >
          {open
            ? t('projects.detail.campaign.hideDetails')
            : t('projects.detail.campaign.showDetails')}
          {open ? <FiChevronUp className="h-3 w-3" /> : <FiChevronDown className="h-3 w-3" />}
        </button>
      </div>

      {post.hashtags?.length > 0 && (
        <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[11px] text-slate-500">
          <FiHash className="h-3 w-3" aria-hidden />
          {post.hashtags.map((h) => (
            <span
              key={h}
              className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-slate-600"
            >
              {h}
            </span>
          ))}
        </div>
      )}

      {open && (
        <div className="mt-3 space-y-2 rounded-lg border border-slate-100 bg-slate-50 px-4 py-3">
          <DetailField label={t('projects.detail.campaign.caption')} value={post.caption} />
          <DetailField label={t('projects.detail.campaign.hook')} value={post.hook} />
          <DetailField label={t('projects.detail.campaign.adAngle')} value={post.ad_angle} />
          <DetailField
            label={t('projects.detail.campaign.productionGuide')}
            value={post.production_guide}
          />
          <DetailField
            label={t('projects.detail.campaign.visualRecommendation')}
            value={post.visual_recommendation}
          />
        </div>
      )}
    </div>
  );
}

function DetailField({ label, value }: { label: string; value: string }) {
  if (!value) return null;
  return (
    <p className="text-xs text-slate-700 leading-relaxed">
      <span className="font-semibold uppercase tracking-wide text-[11px] text-slate-500 flex items-center gap-1.5">
        <FiTarget className="h-3 w-3" aria-hidden />
        {label}
      </span>
      <span className="mt-0.5 block">{value}</span>
    </p>
  );
}
