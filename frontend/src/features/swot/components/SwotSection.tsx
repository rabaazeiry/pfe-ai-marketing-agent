import { useEffect, useMemo, useState } from 'react';
import axios from 'axios';
import clsx from 'clsx';
import { useTranslation } from 'react-i18next';
import { FiCpu, FiLoader, FiRefreshCw, FiShield, FiTarget, FiUsers } from 'react-icons/fi';
import { useToast } from '@/components/Toast';
import { StateView } from '@/features/projects/components/StateView';
import { useProjectCompetitors } from '@/features/projects/useProjectDetail';
import type { CompetitorSummary } from '@/features/projects/types';
import { useGenerateSwot, useSwot } from '../useSwot';
import { SwotQuadrantCard } from './SwotQuadrantCard';

type Props = { projectId: string };

export function SwotSection({ projectId }: Props) {
  const { t, i18n } = useTranslation();
  const toast = useToast();

  const competitorsQuery = useProjectCompetitors(projectId);
  const activeCompetitors = useMemo<CompetitorSummary[]>(
    () => (competitorsQuery.data ?? []).filter((c) => c.isActive !== false),
    [competitorsQuery.data]
  );

  const [selectedId, setSelectedId] = useState<string | null>(null);

  // Auto-select the first active competitor once they load.
  useEffect(() => {
    if (selectedId) return;
    if (activeCompetitors.length > 0) {
      setSelectedId(activeCompetitors[0]._id);
    }
  }, [activeCompetitors, selectedId]);

  const swotQuery = useSwot(selectedId ?? undefined);
  const mutation = useGenerateSwot(selectedId ?? undefined);
  const doc = swotQuery.data ?? null;
  const isMutating = mutation.isPending;

  const runGenerate = async () => {
    if (!selectedId) return;
    toast.info(
      t('projects.detail.swot.toasts.generatingBody'),
      t('projects.detail.swot.toasts.generatingTitle')
    );
    try {
      await mutation.mutateAsync();
      toast.success(
        t('projects.detail.swot.toasts.successBody'),
        t('projects.detail.swot.toasts.successTitle')
      );
    } catch (err) {
      const fallback = t('projects.detail.swot.toasts.errorBody');
      const message = axios.isAxiosError(err)
        ? err.response?.data?.message ?? fallback
        : fallback;
      toast.error(message, t('projects.detail.swot.toasts.errorTitle'));
    }
  };

  return (
    <div className="card">
      <div className="flex items-start justify-between gap-4 mb-4">
        <div className="min-w-0">
          <h3 className="font-semibold text-slate-900 flex items-center gap-2">
            <FiShield className="text-indigo-500" />
            {t('projects.detail.swot.title')}
          </h3>
          <p className="text-xs text-slate-500 mt-0.5">
            {t('projects.detail.swot.subtitle')}
          </p>
        </div>
        {doc?.status === 'completed' && (
          <button
            type="button"
            className="btn-ghost shrink-0"
            onClick={runGenerate}
            disabled={isMutating || !selectedId}
            title={t('projects.detail.swot.regenerate')}
          >
            {isMutating ? (
              <>
                <FiLoader className="animate-spin" />
                {t('projects.detail.swot.inProgress')}
              </>
            ) : (
              <>
                <FiRefreshCw />
                {t('projects.detail.swot.regenerate')}
              </>
            )}
          </button>
        )}
      </div>

      {/* Competitor picker */}
      <CompetitorPicker
        competitors={activeCompetitors}
        selectedId={selectedId}
        onSelect={setSelectedId}
        isLoading={competitorsQuery.isLoading}
        isError={competitorsQuery.isError}
      />

      {/* SWOT body */}
      <div className="mt-5">
        {!selectedId ? null : swotQuery.isLoading && !isMutating ? (
          <StateView variant="loading" title={t('common.loading')} />
        ) : swotQuery.isError ? (
          <StateView variant="error" title={t('projects.detail.errors.title')}>
            {t('projects.detail.swot.errors.load')}
          </StateView>
        ) : isMutating || doc?.status === 'in_progress' ? (
          <StateView
            variant="loading"
            title={t('projects.detail.swot.statusTitle.in_progress')}
          >
            {t('projects.detail.swot.statusBody.in_progress')}
          </StateView>
        ) : !doc ? (
          <StateView
            variant="empty"
            title={t('projects.detail.swot.empty')}
            action={
              <button
                type="button"
                className="btn-primary"
                onClick={runGenerate}
                disabled={isMutating || !selectedId}
              >
                <FiTarget />
                {t('projects.detail.swot.generate')}
              </button>
            }
          >
            {t('projects.detail.swot.emptyHint')}
          </StateView>
        ) : doc.status === 'failed' ? (
          <StateView
            variant="error"
            title={t('projects.detail.swot.statusTitle.failed')}
            action={
              <button
                type="button"
                className="btn-primary"
                onClick={runGenerate}
                disabled={isMutating}
              >
                <FiRefreshCw />
                {t('projects.detail.swot.regenerate')}
              </button>
            }
          >
            {doc.error || t('projects.detail.swot.statusBody.failed')}
          </StateView>
        ) : (
          <>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <SwotQuadrantCard quadrant="strengths"     text={doc.swot.strengths}     source={doc.sources?.strengths} />
              <SwotQuadrantCard quadrant="weaknesses"    text={doc.swot.weaknesses}    source={doc.sources?.weaknesses} />
              <SwotQuadrantCard quadrant="opportunities" text={doc.swot.opportunities} source={doc.sources?.opportunities} />
              <SwotQuadrantCard quadrant="threats"       text={doc.swot.threats}       source={doc.sources?.threats} />
            </div>

            <div className="flex flex-wrap items-center gap-3 text-xs text-slate-500 mt-4">
              {doc.aiModelUsed && (
                <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5">
                  <FiCpu className="h-3 w-3" />
                  {doc.aiModelUsed}
                </span>
              )}
              {doc.generatedAt && (
                <span>
                  {t('projects.detail.swot.generatedAt', {
                    date: formatDate(doc.generatedAt, i18n.language)
                  })}
                </span>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function CompetitorPicker({
  competitors,
  selectedId,
  onSelect,
  isLoading,
  isError
}: {
  competitors: CompetitorSummary[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  isLoading: boolean;
  isError: boolean;
}) {
  const { t } = useTranslation();

  if (isLoading) {
    return <div className="text-xs text-slate-500">{t('common.loading')}</div>;
  }
  if (isError) {
    return <div className="text-xs text-red-600">{t('projects.detail.errors.competitors')}</div>;
  }
  if (competitors.length === 0) {
    return (
      <div className="text-xs text-slate-500 flex items-center gap-2">
        <FiUsers className="text-slate-400" />
        {t('projects.detail.swot.picker.noCompetitors')}
      </div>
    );
  }

  return (
    <div>
      <div className="text-xs text-slate-500 mb-2 flex items-center gap-1.5">
        <FiUsers className="text-slate-400" />
        {t('projects.detail.swot.picker.label')}
      </div>
      <div className="flex flex-wrap gap-1.5">
        {competitors.map((c) => {
          const active = selectedId === c._id;
          return (
            <button
              key={c._id}
              type="button"
              onClick={() => onSelect(c._id)}
              className={clsx(
                'inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ring-1 transition-colors',
                active
                  ? 'bg-brand-600 text-white ring-brand-600'
                  : 'bg-white text-slate-700 ring-slate-200 hover:bg-slate-50 hover:text-slate-900'
              )}
              aria-pressed={active}
            >
              {c.companyName}
            </button>
          );
        })}
      </div>
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
