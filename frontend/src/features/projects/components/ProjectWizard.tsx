import { useCallback, useEffect, useMemo, useState } from 'react';
import clsx from 'clsx';
import { useTranslation } from 'react-i18next';
import { FiArrowLeft, FiArrowRight, FiChevronRight } from 'react-icons/fi';

export type WizardStep = {
  id: string;
  labelKey: string;
  icon: React.ReactNode;
  render: () => React.ReactNode;
};

type Props = {
  steps: WizardStep[];
  /** Used to scope the URL hash + localStorage key per project. */
  storageKey: string;
  defaultStepId?: string;
};

const URL_PARAM = 'tab';

function readInitialStep(steps: WizardStep[], storageKey: string, defaultStepId?: string) {
  if (typeof window === 'undefined') return defaultStepId ?? steps[0]?.id;
  const fromUrl = new URLSearchParams(window.location.search).get(URL_PARAM);
  if (fromUrl && steps.some((s) => s.id === fromUrl)) return fromUrl;
  const fromStorage = window.localStorage.getItem(storageKey);
  if (fromStorage && steps.some((s) => s.id === fromStorage)) return fromStorage;
  return defaultStepId ?? steps[0]?.id;
}

export function ProjectWizard({ steps, storageKey, defaultStepId }: Props) {
  const { t } = useTranslation();
  const [activeId, setActiveId] = useState<string>(() => readInitialStep(steps, storageKey, defaultStepId) ?? '');

  const activeIndex = useMemo(() => Math.max(0, steps.findIndex((s) => s.id === activeId)), [steps, activeId]);
  const activeStep = steps[activeIndex] ?? steps[0];

  const goTo = useCallback(
    (id: string) => {
      if (!steps.some((s) => s.id === id)) return;
      setActiveId(id);
    },
    [steps]
  );

  // Sync URL + localStorage whenever the active step changes.
  useEffect(() => {
    if (!activeStep) return;
    if (typeof window === 'undefined') return;
    const url = new URL(window.location.href);
    if (url.searchParams.get(URL_PARAM) !== activeStep.id) {
      url.searchParams.set(URL_PARAM, activeStep.id);
      window.history.replaceState({}, '', url.toString());
    }
    window.localStorage.setItem(storageKey, activeStep.id);
  }, [activeStep, storageKey]);

  const goNext = () => {
    const next = steps[activeIndex + 1];
    if (next) goTo(next.id);
  };
  const goBack = () => {
    const prev = steps[activeIndex - 1];
    if (prev) goTo(prev.id);
  };

  if (!activeStep) return null;

  const isFirst = activeIndex === 0;
  const isLast = activeIndex === steps.length - 1;

  return (
    <div className="space-y-4">
      <div
        role="tablist"
        aria-label={t('projects.detail.wizard.tablistLabel')}
        className="card !p-2 flex flex-wrap gap-1 overflow-x-auto"
      >
        {steps.map((s, idx) => {
          const isActive = s.id === activeStep.id;
          const isDone = idx < activeIndex;
          return (
            <button
              key={s.id}
              type="button"
              role="tab"
              aria-selected={isActive}
              aria-controls={`wizard-panel-${s.id}`}
              id={`wizard-tab-${s.id}`}
              onClick={() => goTo(s.id)}
              className={clsx(
                'group inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition-colors whitespace-nowrap',
                isActive
                  ? 'bg-brand-50 text-brand-700 ring-1 ring-brand-100'
                  : isDone
                    ? 'text-slate-700 hover:bg-slate-100'
                    : 'text-slate-500 hover:bg-slate-100'
              )}
            >
              <span
                className={clsx(
                  'inline-flex h-6 w-6 items-center justify-center rounded-full text-[11px] font-semibold',
                  isActive
                    ? 'bg-brand-600 text-white'
                    : isDone
                      ? 'bg-emerald-100 text-emerald-700'
                      : 'bg-slate-100 text-slate-500'
                )}
              >
                {idx + 1}
              </span>
              <span className="text-base leading-none">{s.icon}</span>
              <span>{t(s.labelKey)}</span>
            </button>
          );
        })}
      </div>

      <div
        role="tabpanel"
        id={`wizard-panel-${activeStep.id}`}
        aria-labelledby={`wizard-tab-${activeStep.id}`}
        className="space-y-6"
      >
        {activeStep.render()}
      </div>

      <div className="card flex items-center justify-between gap-3">
        <button
          type="button"
          onClick={goBack}
          disabled={isFirst}
          className={clsx(
            'btn-ghost inline-flex items-center gap-2',
            isFirst && 'opacity-40 cursor-not-allowed'
          )}
        >
          <FiArrowLeft />
          <span>{t('projects.detail.wizard.back')}</span>
        </button>

        <div className="text-xs text-slate-500 inline-flex items-center gap-1">
          <span>{t('projects.detail.wizard.stepOf', { current: activeIndex + 1, total: steps.length })}</span>
          <FiChevronRight className="text-slate-300" />
          <span className="font-medium text-slate-700">{t(activeStep.labelKey)}</span>
        </div>

        <button
          type="button"
          onClick={goNext}
          disabled={isLast}
          className={clsx(
            'btn-primary inline-flex items-center gap-2',
            isLast && 'opacity-40 cursor-not-allowed'
          )}
        >
          <span>{t('projects.detail.wizard.next')}</span>
          <FiArrowRight />
        </button>
      </div>
    </div>
  );
}
