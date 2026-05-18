import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Joyride, STATUS } from 'react-joyride';
import type { EventData, Step } from 'react-joyride';
import { useAuthStore } from '@/stores/auth.store';
import { useOnboardingStore } from '@/stores/onboarding.store';

// Brand palette (tailwind.config.js): brand-600 #1d4ad4, slate-900 #0f172a.
const TOUR_OPTIONS = {
  primaryColor: '#1d4ad4',
  backgroundColor: '#ffffff',
  arrowColor: '#ffffff',
  textColor: '#0f172a',
  overlayColor: 'rgba(15, 23, 42, 0.45)',
  zIndex: 10000,
  showProgress: true,
  skipBeacon: true, // show the tooltip immediately, no pulsing beacon dot
  buttons: ['back', 'primary', 'skip'] as Array<'back' | 'primary' | 'skip'>,
};

const TOUR_STYLES = {
  tooltip: { borderRadius: 12, fontSize: 14 },
  tooltipContainer: { textAlign: 'start' as const },
  buttonPrimary: { borderRadius: 8 },
  buttonBack: { color: '#475569' },
  buttonSkip: { color: '#94a3b8' },
};

// Each step targets a real DOM node via data-tour="...". If the node is not
// mounted (e.g. the project tabs while the user is on the dashboard), the
// step degrades gracefully to a centered, route-independent info card —
// keeping the tour non-intrusive and impossible to break.
type TourDef = { sel: string; textKey: string; forceCenter?: boolean };

const TOUR_DEFS: TourDef[] = [
  { sel: '[data-tour="dashboard"]',     textKey: 'tour.step1' },
  { sel: '[data-tour="nav-projects"]',  textKey: 'tour.step2' },
  { sel: '[data-tour="tab-pipeline"]',  textKey: 'tour.step3' },
  { sel: '[data-tour="tab-insights"]',  textKey: 'tour.step4' },
  { sel: '[data-tour="tab-market"]',    textKey: 'tour.step5' },
  { sel: '[data-tour="tab-campaign"]',  textKey: 'tour.step6' },
  { sel: '[data-tour="dashboard"]',     textKey: 'tour.step7', forceCenter: true },
];

function buildSteps(t: (k: string) => string): Step[] {
  return TOUR_DEFS.map(({ sel, textKey, forceCenter }) => {
    const exists =
      typeof document !== 'undefined' && !!document.querySelector(sel);
    if (forceCenter || !exists) {
      return { target: 'body', placement: 'center', content: t(textKey) };
    }
    return { target: sel, content: t(textKey) };
  });
}

export function GuidedTour() {
  const { t } = useTranslation();
  const user = useAuthStore((s) => s.user);
  const run = useOnboardingStore((s) => s.run);
  const stopTour = useOnboardingStore((s) => s.stopTour);
  const markSeen = useOnboardingStore((s) => s.markSeen);

  const [steps, setSteps] = useState<Step[]>([]);

  // Resolve targets against the live DOM each time the tour starts.
  useEffect(() => {
    if (run) setSteps(buildSteps(t));
  }, [run, t]);

  const handleEvent = (data: EventData) => {
    const status = data.status as string;
    if (status === STATUS.FINISHED || status === STATUS.SKIPPED) {
      stopTour();
      if (user) markSeen(user.id);
    }
  };

  if (!user) return null;

  return (
    <Joyride
      run={run && steps.length > 0}
      steps={steps}
      continuous
      scrollToFirstStep
      onEvent={handleEvent}
      options={TOUR_OPTIONS}
      styles={TOUR_STYLES}
      locale={{
        back: t('tour.controls.back'),
        close: t('tour.controls.close'),
        last: t('tour.controls.last'),
        next: t('tour.controls.next'),
        skip: t('tour.controls.skip'),
        nextWithProgress: t('tour.controls.nextProgress'),
      }}
    />
  );
}
