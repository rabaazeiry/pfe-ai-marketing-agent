import type { ReactElement } from 'react';
import { useTranslation } from 'react-i18next';
import { FiAlertCircle, FiCheck, FiLoader } from 'react-icons/fi';
import type { PipelineStep, PipelineStepState, ProjectDetail } from '../types';
import { derivePipeline, PIPELINE_STEP_ORDER } from '../pipeline';

type Props = { project: ProjectDetail };

type StepVisuals = {
  marker: ReactElement;
  markerBg: string;
  markerRing: string;
  label: string;
  pill: string;
  connector: string;
};

const VISUALS: Record<PipelineStepState, Omit<StepVisuals, 'marker'> & { marker: ReactElement | null }> = {
  done: {
    marker: <FiCheck className="w-4 h-4" />,
    markerBg: 'bg-emerald-500 text-white',
    markerRing: 'ring-emerald-100',
    label: 'text-slate-800 font-medium',
    pill: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
    connector: 'bg-emerald-400'
  },
  running: {
    marker: <FiLoader className="w-4 h-4 animate-spin" />,
    markerBg: 'bg-brand-600 text-white',
    markerRing: 'ring-brand-100',
    label: 'text-slate-900 font-semibold',
    pill: 'bg-brand-50 text-brand-700 ring-brand-200',
    connector: 'bg-slate-200'
  },
  pending: {
    marker: null,
    markerBg: 'bg-white text-slate-400 border border-slate-200',
    markerRing: 'ring-transparent',
    label: 'text-slate-500',
    pill: 'bg-slate-50 text-slate-500 ring-slate-200',
    connector: 'bg-slate-200'
  },
  failed: {
    marker: <FiAlertCircle className="w-4 h-4" />,
    markerBg: 'bg-red-500 text-white',
    markerRing: 'ring-red-100',
    label: 'text-red-700 font-medium',
    pill: 'bg-red-50 text-red-700 ring-red-200',
    connector: 'bg-red-300'
  }
};

export function PipelineSection({ project }: Props) {
  const { t } = useTranslation();
  const steps = derivePipeline(project);
  const pct = Math.max(0, Math.min(100, project.progressPercentage ?? 0));

  return (
    <div className="card">
      <div className="flex items-start justify-between mb-4">
        <div>
          <h3 className="font-semibold text-slate-900">{t('projects.detail.pipeline.title')}</h3>
          <p className="text-xs text-slate-500">{t('projects.detail.pipeline.subtitle')}</p>
        </div>
        <div className="text-right">
          <div className="text-lg font-semibold text-slate-900 leading-none">{pct}%</div>
          <div className="text-[10px] uppercase tracking-wide text-slate-400 mt-1">
            {t('projects.detail.pipeline.progress')}
          </div>
        </div>
      </div>

      <div className="h-2 bg-slate-100 rounded-full overflow-hidden mb-5">
        <div
          className="h-full bg-gradient-to-r from-brand-500 to-brand-600 transition-all duration-500"
          style={{ width: `${pct}%` }}
        />
      </div>

      <ol className="space-y-0">
        {steps.map((step, idx) => (
          <PipelineRow
            key={step.key}
            step={step}
            index={idx}
            isLast={idx === PIPELINE_STEP_ORDER.length - 1}
          />
        ))}
      </ol>
    </div>
  );
}

function PipelineRow({
  step,
  index,
  isLast
}: {
  step: PipelineStep;
  index: number;
  isLast: boolean;
}) {
  const { t } = useTranslation();
  const v = VISUALS[step.state];

  return (
    <li className="relative flex items-start gap-3">
      <div className="flex flex-col items-center">
        <span
          className={`relative z-10 inline-flex h-7 w-7 items-center justify-center rounded-full text-xs font-semibold ring-4 ${v.markerBg} ${v.markerRing}`}
          aria-hidden
        >
          {v.marker ?? index + 1}
        </span>
        {!isLast && <span className={`w-0.5 grow min-h-[22px] ${v.connector}`} />}
      </div>

      <div className={`flex flex-1 items-center justify-between gap-3 ${isLast ? 'pb-0' : 'pb-4'} pt-0.5`}>
        <span className={`text-sm ${v.label}`}>
          {t(`projects.detail.pipeline.steps.${step.key}`)}
        </span>
        <span
          className={`text-[11px] px-2 py-0.5 rounded-full ring-1 font-medium ${v.pill}`}
        >
          {t(`projects.detail.pipeline.state.${step.state}`)}
        </span>
      </div>
    </li>
  );
}
