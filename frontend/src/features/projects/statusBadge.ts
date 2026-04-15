import type { ProjectStatus } from './types';

export type BadgeTone = {
  dot: string;
  bg: string;
  text: string;
  ring: string;
};

const UNKNOWN_TONE: BadgeTone = {
  dot: 'bg-slate-400',
  bg: 'bg-slate-50',
  text: 'text-slate-600',
  ring: 'ring-slate-200'
};

const PROJECT_STATUS_TONES: Record<ProjectStatus, BadgeTone> = {
  draft: { dot: 'bg-slate-400', bg: 'bg-slate-50', text: 'text-slate-700', ring: 'ring-slate-200' },
  active: { dot: 'bg-emerald-500', bg: 'bg-emerald-50', text: 'text-emerald-700', ring: 'ring-emerald-200' },
  completed: { dot: 'bg-brand-500', bg: 'bg-brand-50', text: 'text-brand-700', ring: 'ring-brand-200' },
  archived: { dot: 'bg-amber-500', bg: 'bg-amber-50', text: 'text-amber-700', ring: 'ring-amber-200' }
};

export function projectStatusTone(status: string | undefined | null): BadgeTone {
  if (!status) return UNKNOWN_TONE;
  return PROJECT_STATUS_TONES[status as ProjectStatus] ?? UNKNOWN_TONE;
}

/**
 * Classifies the backend pipeline status into a coarse visual family.
 * Keeps the raw backend key for the label and only decides the color.
 */
export function pipelineTone(status: string | undefined | null): BadgeTone {
  if (!status || status === 'idle') {
    return { dot: 'bg-slate-300', bg: 'bg-slate-50', text: 'text-slate-500', ring: 'ring-slate-200' };
  }
  const s = String(status);
  if (s.endsWith('_complete') || s === 'completed') {
    return { dot: 'bg-emerald-500', bg: 'bg-emerald-50', text: 'text-emerald-700', ring: 'ring-emerald-200' };
  }
  if (s.endsWith('_failed') || s === 'failed') {
    return { dot: 'bg-red-500', bg: 'bg-red-50', text: 'text-red-700', ring: 'ring-red-200' };
  }
  // anything in progress
  return { dot: 'bg-brand-500 animate-pulse', bg: 'bg-brand-50', text: 'text-brand-700', ring: 'ring-brand-200' };
}

/**
 * Pretty label for a raw `pipelineStatus` string.
 * E.g. "step3_in_progress" → "Step 3 · In progress".
 */
export function formatPipelineLabel(status: string | undefined | null): string {
  if (!status || status === 'idle') return '—';
  return status
    .replace(/^step(\d+)_/, 'Step $1 · ')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}
