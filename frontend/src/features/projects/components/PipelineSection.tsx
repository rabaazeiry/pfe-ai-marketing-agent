import type { ReactElement } from 'react';
import { useTranslation } from 'react-i18next';
import { FiAlertCircle, FiCheckCircle, FiCircle, FiLoader } from 'react-icons/fi';
import type { PipelineStep, PipelineStepState, ProjectDetail } from '../types';
import { derivePipeline } from '../pipeline';

type Props = { project: ProjectDetail };

const ICONS: Record<PipelineStepState, ReactElement> = {
  done: <FiCheckCircle className="w-5 h-5 text-emerald-600" />,
  running: <FiLoader className="w-5 h-5 text-brand-600 animate-spin" />,
  pending: <FiCircle className="w-5 h-5 text-slate-300" />,
  failed: <FiAlertCircle className="w-5 h-5 text-red-600" />
};

const TONES: Record<PipelineStepState, string> = {
  done: 'text-emerald-700',
  running: 'text-brand-700 font-medium',
  pending: 'text-slate-500',
  failed: 'text-red-700 font-medium'
};

export function PipelineSection({ project }: Props) {
  const { t } = useTranslation();
  const steps = derivePipeline(project);
  const pct = Math.max(0, Math.min(100, project.progressPercentage ?? 0));

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="font-semibold text-slate-900">{t('projects.detail.pipeline.title')}</h3>
          <p className="text-xs text-slate-500">{t('projects.detail.pipeline.subtitle')}</p>
        </div>
        <span className="text-xs text-slate-500">{pct}%</span>
      </div>

      <div className="h-2 bg-slate-100 rounded-full overflow-hidden mb-5">
        <div
          className="h-full bg-brand-600 transition-all duration-500"
          style={{ width: `${pct}%` }}
        />
      </div>

      <ol className="space-y-3">
        {steps.map((step) => (
          <PipelineRow key={step.key} step={step} />
        ))}
      </ol>
    </div>
  );
}

function PipelineRow({ step }: { step: PipelineStep }) {
  const { t } = useTranslation();
  return (
    <li className="flex items-center gap-3">
      <span aria-hidden>{ICONS[step.state]}</span>
      <span className={`text-sm ${TONES[step.state]}`}>
        {t(`projects.detail.pipeline.steps.${step.key}`)}
      </span>
      <span className="ms-auto text-xs text-slate-400">
        {t(`projects.detail.pipeline.state.${step.state}`)}
      </span>
    </li>
  );
}
