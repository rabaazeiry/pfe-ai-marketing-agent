import axios from 'axios';
import { useTranslation } from 'react-i18next';
import { FiBarChart2, FiCpu, FiLoader, FiRefreshCw, FiZap } from 'react-icons/fi';
import { useToast } from '@/components/Toast';
import { StateView } from '@/features/projects/components/StateView';
import { useGenerateMarketResearch, useMarketResearch } from '../useMarketResearch';
import { MarketOverviewGrid } from './MarketOverviewGrid';
import { MarketSummaryMarkdown } from './MarketSummaryMarkdown';

type Props = { projectId: string };

export function MarketResearchSection({ projectId }: Props) {
  const { t, i18n } = useTranslation();
  const toast = useToast();
  const query = useMarketResearch(projectId);
  const mutation = useGenerateMarketResearch(projectId);

  const doc = query.data ?? null;
  const isMutating = mutation.isPending;
  const effectiveStatus = isMutating ? 'in_progress' : doc?.status;

  const runGenerate = async () => {
    toast.info(
      t('projects.detail.marketResearch.toasts.generatingBody'),
      t('projects.detail.marketResearch.toasts.generatingTitle')
    );
    try {
      await mutation.mutateAsync();
      toast.success(
        t('projects.detail.marketResearch.toasts.successBody'),
        t('projects.detail.marketResearch.toasts.successTitle')
      );
    } catch (err) {
      const fallback = t('projects.detail.marketResearch.toasts.errorBody');
      const message = axios.isAxiosError(err)
        ? err.response?.data?.message ?? fallback
        : fallback;
      toast.error(message, t('projects.detail.marketResearch.toasts.errorTitle'));
    }
  };

  return (
    <div className="card">
      <div className="flex items-start justify-between gap-4 mb-4">
        <div className="min-w-0">
          <h3 className="font-semibold text-slate-900 flex items-center gap-2">
            <FiBarChart2 className="text-brand-600" />
            {t('projects.detail.marketResearch.title')}
          </h3>
          <p className="text-xs text-slate-500 mt-0.5">
            {t('projects.detail.marketResearch.subtitle')}
          </p>
        </div>
        {doc?.status === 'completed' && (
          <button
            type="button"
            className="btn-ghost shrink-0"
            onClick={runGenerate}
            disabled={isMutating}
            title={t('projects.detail.marketResearch.regenerate')}
          >
            {isMutating ? (
              <>
                <FiLoader className="animate-spin" />
                {t('projects.detail.marketResearch.inProgress')}
              </>
            ) : (
              <>
                <FiRefreshCw />
                {t('projects.detail.marketResearch.regenerate')}
              </>
            )}
          </button>
        )}
      </div>

      {query.isLoading && !isMutating ? (
        <StateView variant="loading" title={t('common.loading')} />
      ) : query.isError ? (
        <StateView variant="error" title={t('projects.detail.errors.title')}>
          {t('projects.detail.marketResearch.errors.load')}
        </StateView>
      ) : isMutating || effectiveStatus === 'in_progress' ? (
        <StateView
          variant="loading"
          title={t('projects.detail.marketResearch.statusTitle.in_progress')}
        >
          {t('projects.detail.marketResearch.statusBody.in_progress')}
        </StateView>
      ) : !doc ? (
        <StateView
          variant="empty"
          title={t('projects.detail.marketResearch.empty')}
          action={
            <button
              type="button"
              className="btn-primary"
              onClick={runGenerate}
              disabled={isMutating}
            >
              <FiZap />
              {t('projects.detail.marketResearch.generate')}
            </button>
          }
        >
          {t('projects.detail.marketResearch.emptyHint')}
        </StateView>
      ) : doc.status === 'failed' ? (
        <StateView
          variant="error"
          title={t('projects.detail.marketResearch.statusTitle.failed')}
          action={
            <button
              type="button"
              className="btn-primary"
              onClick={runGenerate}
              disabled={isMutating}
            >
              <FiRefreshCw />
              {t('projects.detail.marketResearch.regenerate')}
            </button>
          }
        >
          {doc.error || t('projects.detail.marketResearch.statusBody.failed')}
        </StateView>
      ) : (
        <div className="space-y-5">
          <MarketOverviewGrid overview={doc.marketOverview} />

          <div className="rounded-xl border border-slate-100 bg-slate-50/40 p-4">
            <MarketSummaryMarkdown content={doc.marketSummary.content} />
          </div>

          <div className="flex flex-wrap items-center gap-3 text-xs text-slate-500 pt-1">
            {doc.aiModelUsed && (
              <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5">
                <FiCpu className="h-3 w-3" />
                {doc.aiModelUsed}
              </span>
            )}
            {doc.generatedAt && (
              <span>
                {t('projects.detail.marketResearch.generatedAt', {
                  date: formatDate(doc.generatedAt, i18n.language)
                })}
              </span>
            )}
            {typeof doc.marketSummary.competitorsAnalyzed === 'number' && (
              <span>
                {t('projects.detail.marketResearch.competitorsAnalyzed', {
                  count: doc.marketSummary.competitorsAnalyzed
                })}
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function formatDate(iso: string, lang: string): string {
  try {
    return new Intl.DateTimeFormat(lang, {
      dateStyle: 'medium',
      timeStyle: 'short'
    }).format(new Date(iso));
  } catch {
    return iso;
  }
}
