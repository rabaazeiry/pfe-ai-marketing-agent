import axios from 'axios';
import { useTranslation } from 'react-i18next';
import { FiBookOpen, FiCheckCircle, FiCpu, FiLoader, FiRefreshCw, FiZap } from 'react-icons/fi';
import { useToast } from '@/components/Toast';
import { normalizeIndustry } from '../industry';
import { useIndustryInsights, useRegenerateIndustryInsights } from '../useProjectDetail';
import type { IndustryKey, RagQuestionBlock } from '../types';
import { StateView } from './StateView';

type Props = {
  industry?: string | null;
  marketCategory?: string | null;
};

export function InsightsSection({ industry, marketCategory }: Props) {
  const { t } = useTranslation();
  const toast = useToast();

  const key: IndustryKey | null = normalizeIndustry(industry, marketCategory);
  const query = useIndustryInsights(key);
  const mutation = useRegenerateIndustryInsights(key);
  const bundle = query.data;

  const handleRegenerate = async () => {
    try {
      await mutation.mutateAsync();
      toast.success(
        'Insights régénérés en français avec succès !',
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
          <h3 className="font-semibold text-slate-900">{t('projects.detail.insights.title')}</h3>
          <p className="text-xs text-slate-500">{t('projects.detail.insights.subtitle')}</p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {bundle && (
            <div className="flex flex-col items-end text-[11px] text-slate-500">
              <span className="inline-flex items-center gap-1.5 rounded-full bg-brand-50 text-brand-700 px-2 py-0.5 font-medium">
                <FiCpu className="h-3 w-3" />
                {bundle.model}
              </span>
              <span className="mt-1">
                {t('projects.detail.insights.industryBadge', { industry: bundle.industry })}
              </span>
            </div>
          )}
          {key && (
            <button
              type="button"
              className="btn-ghost shrink-0"
              onClick={handleRegenerate}
              disabled={mutation.isPending}
              title="Régénérer les insights via Llama 3.1"
            >
              {mutation.isPending ? (
                <FiLoader className="animate-spin h-4 w-4" />
              ) : (
                <FiRefreshCw className="h-4 w-4" />
              )}
              <span className="ml-1.5">
                {mutation.isPending ? 'Génération (~2-3 min)…' : 'Régénérer'}
              </span>
            </button>
          )}
        </div>
      </div>

      {!key ? (
        <StateView variant="empty" title={t('projects.detail.insights.empty')}>
          {t('projects.detail.insights.unsupportedIndustry')}
        </StateView>
      ) : query.isLoading ? (
        <StateView variant="loading" title={t('common.loading')} />
      ) : query.isError ? (
        <StateView variant="error" title={t('projects.detail.errors.title')}>
          {t('projects.detail.errors.insights')}
        </StateView>
      ) : !bundle || (bundle.questions ?? []).length === 0 ? (
        <StateView variant="empty" title={t('projects.detail.insights.empty')} />
      ) : (
        <div className="space-y-6">
          {(bundle.questions ?? []).map((q, idx) => (
            <QuestionBlock
              key={q.question_id}
              block={q}
              index={idx + 1}
              total={(bundle.questions ?? []).length}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function QuestionBlock({
  block,
  index,
  total,
}: {
  block: RagQuestionBlock;
  index: number;
  total: number;
}) {
  const { t } = useTranslation();

  // Use the rich structured fields when available, fall back to legacy insights[].
  // Both the V6 RAG envelope and the prose_v1 (Step-4-rework) envelope expose
  // `answer` / `actionable_recommendations`, so the same branch covers both.
  const hasV6 = !!(block.answer || (block.actionable_recommendations?.length));
  const retrievedDocs = block.retrieved_docs ?? [];     // prose_v1 omits this
  const insightsList  = block.insights ?? [];

  return (
    <section>
      <div className="flex items-center gap-2 mb-3">
        <span className="inline-flex items-center justify-center h-6 min-w-6 rounded-full bg-slate-900 text-white text-[11px] font-semibold px-2">
          {index}/{total}
        </span>
        <h4 className="text-sm font-semibold text-slate-900">{block.question_title}</h4>
        {block.status === 'OK' && (
          <FiCheckCircle className="h-3.5 w-3.5 text-emerald-500" aria-hidden />
        )}
      </div>

      {hasV6 ? (
        <V6QuestionContent block={block} />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {insightsList.map((ins, i) => (
            <InsightCard key={i} insight={ins} />
          ))}
        </div>
      )}

      {retrievedDocs.length > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-1.5 text-[11px] text-slate-500">
          <FiBookOpen className="h-3 w-3" />
          <span className="font-medium">{t('projects.detail.insights.retrievedDocs')}:</span>
          {retrievedDocs.map((d) => (
            <span
              key={d}
              className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-slate-600"
            >
              {d}
            </span>
          ))}
        </div>
      )}
    </section>
  );
}

function V6QuestionContent({ block }: { block: RagQuestionBlock }) {
  return (
    <div className="space-y-3">
      {/* Synthesised answer */}
      {block.answer && (
        <p className="text-sm text-slate-700 leading-relaxed bg-slate-50 rounded-lg px-4 py-3 border border-slate-100">
          {block.answer}
        </p>
      )}

      {/* Actionable recommendations */}
      {block.actionable_recommendations && block.actionable_recommendations.length > 0 && (
        <div className="rounded-xl border border-brand-100 bg-brand-50/40 px-4 py-3">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-brand-700 mb-2 flex items-center gap-1.5">
            <FiZap className="h-3 w-3" />
            Recommandations actionnables
          </p>
          <ul className="space-y-2">
            {block.actionable_recommendations.map((rec, i) => (
              <RecommendationItem key={i} index={i + 1} rec={rec} />
            ))}
          </ul>
        </div>
      )}

      {/* Evidence data points */}
      {block.evidence && block.evidence.length > 0 && (
        <div className="rounded-lg border border-slate-100 px-4 py-3">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-500 mb-2">
            Preuves chiffrées
          </p>
          <ul className="space-y-1">
            {block.evidence.map((ev, i) => (
              <li key={i} className="text-[11px] text-slate-600 leading-relaxed font-mono">
                • {typeof ev === 'string' ? ev : (ev as { data_point?: string }).data_point ?? JSON.stringify(ev)}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* ML evidence */}
      {block.ml_evidence && (
        <p className="text-[11px] text-slate-400 italic leading-relaxed">
          <span className="font-semibold not-italic text-slate-500">ML V6 :</span> {block.ml_evidence}
        </p>
      )}
    </div>
  );
}

function RecommendationItem({ index, rec }: { index: number; rec: unknown }) {
  // Recommendations are plain French text from the LLM — display as-is.
  // If somehow an object slips through (old data), stringify it gracefully.
  const text =
    typeof rec === 'string'
      ? rec
      : typeof rec === 'object' && rec !== null
      ? ((rec as { text?: string; recommendation?: string }).text ??
         (rec as { text?: string; recommendation?: string }).recommendation ??
         JSON.stringify(rec))
      : String(rec);

  return (
    <li className="text-xs text-slate-700 leading-relaxed flex gap-2">
      <span className="mt-0.5 inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-brand-600 text-white text-[9px] font-bold">
        {index}
      </span>
      <span className="flex-1">{text}</span>
    </li>
  );
}

function InsightCard({ insight }: { insight: { title: string; content: string; evidence?: string } }) {
  const { t } = useTranslation();
  return (
    <div className="rounded-xl border border-slate-100 bg-white p-4 transition hover:border-slate-200 hover:shadow-soft hover:-translate-y-0.5">
      <h5 className="text-sm font-semibold text-slate-900 leading-snug">{insight.title}</h5>
      <p className="mt-2 text-xs text-slate-700 leading-relaxed">{insight.content}</p>
      {insight.evidence && (
        <p className="mt-3 pt-2 border-t border-slate-100 text-[11px] text-slate-500">
          <span className="font-semibold uppercase tracking-wide">
            {t('projects.detail.insights.evidence')}:
          </span>{' '}
          <span className="font-mono">{insight.evidence}</span>
        </p>
      )}
    </div>
  );
}
