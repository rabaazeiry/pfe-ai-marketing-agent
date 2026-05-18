import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from '@tanstack/react-router';
import { useQuery } from '@tanstack/react-query';
import { Joyride, EVENTS, STATUS } from 'react-joyride';
import type { Controls, EventData, Step } from 'react-joyride';
import { useAuthStore } from '@/stores/auth.store';
import { useOnboardingStore } from '@/stores/onboarding.store';
import { listProjects } from '@/features/projects/api';

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

// Generous ceilings: the project-detail route does a network fetch (project +
// competitors) and only renders the wizard tablist once that resolves, so the
// `before` hook may legitimately wait a few seconds. These must exceed the
// internal wait below or Joyride would abort the hook prematurely.
const ELEMENT_WAIT_MS = 10_000;
const BEFORE_TIMEOUT_MS = 12_000;

// Poll the live DOM until the target exists (route changed → component mounted →
// element painted). Resolves as soon as it appears, or after `timeout` so the
// tour can never hang; a still-missing target is handled by the
// error:target_not_found safety net in onEvent.
function waitForElement(selector: string, timeout = ELEMENT_WAIT_MS): Promise<void> {
  return new Promise((resolve) => {
    if (typeof document === 'undefined') return resolve();
    if (document.querySelector(selector)) return resolve();
    const started = Date.now();
    const id = window.setInterval(() => {
      if (document.querySelector(selector) || Date.now() - started >= timeout) {
        window.clearInterval(id);
        resolve();
      }
    }, 50);
  });
}

type NavFn = ReturnType<typeof useNavigate>;

// Where each step lives. `path` = a static route; `tab` = the first project's
// detail page with a given wizard tab; `center` = no route, centered card
// (graceful fallback when the user has no projects yet — unchanged behavior).
type Place =
  | { kind: 'path'; to: '/' | '/projects' }
  | { kind: 'tab'; tab: string }
  | { kind: 'center' };

type TourDef = { sel: string; textKey: string; place: Place; forceCenter?: boolean };

const TOUR_DEFS: TourDef[] = [
  { sel: '[data-tour="dashboard"]',    textKey: 'tour.step1', place: { kind: 'path', to: '/' } },
  { sel: '[data-tour="nav-projects"]', textKey: 'tour.step2', place: { kind: 'path', to: '/projects' } },
  { sel: '[data-tour="tab-pipeline"]', textKey: 'tour.step3', place: { kind: 'tab', tab: 'pipeline' } },
  { sel: '[data-tour="tab-insights"]', textKey: 'tour.step4', place: { kind: 'tab', tab: 'insights' } },
  { sel: '[data-tour="tab-market"]',   textKey: 'tour.step5', place: { kind: 'tab', tab: 'market' } },
  { sel: '[data-tour="tab-campaign"]', textKey: 'tour.step6', place: { kind: 'tab', tab: 'campaign' } },
  { sel: '[data-tour="dashboard"]',    textKey: 'tour.step7', place: { kind: 'path', to: '/' }, forceCenter: true },
];

/**
 * Build the steps. Each step carries a `before` hook (react-joyride v3 API)
 * that performs the route change *and waits for the target DOM node to mount*
 * before resolving — Joyride only paints the tooltip once the promise settles,
 * so it can never anchor to a missing element.
 *
 * We drive navigation from `before` rather than the fire-and-forget `onEvent`
 * callback on purpose: `onEvent` cannot delay the tooltip, so navigating there
 * would race the route mount and point the tooltip at empty space.
 *
 * When the user has no project, the tab steps degrade to centered, route-less
 * info cards (no navigation) — exactly the previous graceful fallback.
 */
function buildSteps(
  t: (k: string) => string,
  navigate: NavFn,
  firstProjectId: string | undefined
): Step[] {
  return TOUR_DEFS.map(({ sel, textKey, place, forceCenter }) => {
    const content = t(textKey);

    // Tab steps with no project → keep the legacy centered fallback verbatim.
    const isTab = place.kind === 'tab';
    const degraded = isTab && !firstProjectId;

    if (forceCenter || degraded) {
      const before = async () => {
        if (place.kind === 'path') {
          try { await navigate({ to: place.to }); } catch { /* tour is non-blocking */ }
        }
        // degraded tab steps: no navigation (legacy behavior)
      };
      return {
        target: 'body',
        placement: 'center',
        content,
        before,
        beforeTimeout: BEFORE_TIMEOUT_MS,
      } as Step;
    }

    const before = async () => {
      try {
        if (place.kind === 'path') {
          await navigate({ to: place.to });
        } else if (place.kind === 'tab' && firstProjectId) {
          await navigate({
            to: '/projects/$projectId',
            params: { projectId: firstProjectId },
          });
        }
      } catch {
        /* navigation cancelled/redirected — fall through, the wait + safety
           net below still keep the tour from anchoring to nothing */
      }

      await waitForElement(sel);

      // ProjectWizard only reads the active tab from the URL on mount, so for
      // steps 4-6 (already on the detail page) changing the route won't switch
      // panels. Click the tab button — it's always rendered in the tablist —
      // so the highlighted tab and the panel behind it stay in sync.
      if (place.kind === 'tab') {
        (document.querySelector(sel) as HTMLElement | null)?.click();
      }
    };

    return {
      target: sel,
      content,
      before,
      beforeTimeout: BEFORE_TIMEOUT_MS,
      targetWaitTimeout: 2_000,
    } as Step;
  });
}

export function GuidedTour() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.user);
  const run = useOnboardingStore((s) => s.run);
  const stopTour = useOnboardingStore((s) => s.stopTour);
  const markSeen = useOnboardingStore((s) => s.markSeen);

  // Shares the dashboard's ['projects'] cache; only fetched while the tour
  // runs so it adds zero overhead on normal navigation.
  const projectsQuery = useQuery({
    queryKey: ['projects'],
    queryFn: listProjects,
    enabled: run,
  });
  const firstProjectId = projectsQuery.data?.[0]?._id;

  const [steps, setSteps] = useState<Step[]>([]);

  // Resolve steps once the tour starts AND the projects query has settled
  // (data, empty, or error) so step 3-6 know whether to navigate into a
  // project or fall back to a centered card. Reset on stop so a later replay
  // re-resolves against a possibly-changed project list.
  useEffect(() => {
    if (!run) {
      setSteps([]);
      return;
    }
    if (projectsQuery.isLoading) return;
    setSteps(buildSteps(t, navigate, firstProjectId));
  }, [run, t, navigate, firstProjectId, projectsQuery.isLoading]);

  const handleEvent = (data: EventData, controls: Controls) => {
    const status = data.status as string;
    if (status === STATUS.FINISHED || status === STATUS.SKIPPED) {
      stopTour();
      if (user) markSeen(user.id);
      return;
    }
    // Safety net: if a target still cannot be found after navigating + waiting
    // (e.g. the project-detail API is down), end the tour gracefully rather
    // than show a tooltip pointing at nothing.
    if (data.type === EVENTS.TARGET_NOT_FOUND) {
      controls.skip();
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
