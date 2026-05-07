import { useTranslation } from 'react-i18next';
import { FiBookOpen, FiCheckCircle, FiCpu } from 'react-icons/fi';
import { normalizeIndustry } from '../industry';
import { useIndustryInsights } from '../useProjectDetail';
import type { IndustryKey, RagInsightItem, RagQuestionBlock } from '../types';
import { StateView } from './StateView';

type Props = {
  industry?: string | null;
  marketCategory?: string | null;
};

export function InsightsSection({ industry, marketCategory }: Props) {
  const { t } = useTranslation();

  const key: IndustryKey | null = normalizeIndustry(industry, marketCategory);
  const query = useIndustryInsights(key);
  const bundle = query.data;

  return (
    <div className="card">
      <div className="flex items-start justify-between mb-4 gap-4">
        <div>
          <h3 className="font-semibold text-slate-900">{t('projects.detail.insights.title')}</h3>
          <p className="text-xs text-slate-500">{t('projects.detail.insights.subtitle')}</p>
        </div>
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
      ) : !bundle || bundle.questions.length === 0 ? (
        <StateView variant="empty" title={t('projects.detail.insights.empty')} />
      ) : (
        <div className="space-y-6">
          {bundle.questions.map((q, idx) => (
            <QuestionBlock key={q.question_id} block={q} index={idx + 1} total={bundle.questions.length} />
          ))}
        </div>
      )}
    </div>
  );
}

function QuestionBlock({
  block,
  index,
  total
}: {
  block: RagQuestionBlock;
  index: number;
  total: number;
}) {
  const { t } = useTranslation();
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
      <p className="text-xs text-slate-500 mb-3 leading-relaxed">{block.question_text}</p>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {block.insights.map((ins, i) => (
          <InsightCard key={i} insight={ins} />
        ))}
      </div>

      {block.retrieved_docs.length > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-1.5 text-[11px] text-slate-500">
          <FiBookOpen className="h-3 w-3" />
          <span className="font-medium">{t('projects.detail.insights.retrievedDocs')}:</span>
          {block.retrieved_docs.map((d) => (
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

function InsightCard({ insight }: { insight: RagInsightItem }) {
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
